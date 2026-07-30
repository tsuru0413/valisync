from __future__ import annotations

import datetime
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from asammdf import MDF

from valisync.core.loaders.column_names import (
    ColumnRecord,
    ColumnSpec,
    leaf_count,
    spec_from_probe,
)
from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.models import Diagnostic, LoadResult, Signal, SignalGroup
from valisync.core.models.load_result import LoadCancelled
from valisync.core.models.sample_source import LazyMdfValues

# Maps asammdf BusType int values to Signal.bus_type strings.
# asammdf v4_constants.BusType: CAN=2, ETHERNET=7.
_BUS_TYPE_MAP: dict[int, str] = {
    2: "CAN",
    7: "Ethernet",
}


def _detect_bus_type(source: Any) -> str:
    if source is None:
        return ""
    # XCP runs over various buses; detect by source name heuristic
    if "xcp" in (getattr(source, "name", "") or "").lower():
        return "XCP"
    return _BUS_TYPE_MAP.get(getattr(source, "bus_type", 0), "")


def _flatten(name: str, arr: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """samples (axis 0 = サンプル) を 1D 列へ再帰フラット展開する (LD-14).

    構造化 dtype はフィールドごとに ``Name.field`` へ、多次元配列は先頭の
    非サンプル軸を ``Name[i]`` で 1 段ずつ剥がして 1D になるまで再帰する。
    リーフでのみ連続化し中間スライスのコピーを避ける。
    """
    if arr.dtype.names:  # 構造化: フィールドごとに再帰
        out: list[tuple[str, np.ndarray]] = []
        for field in arr.dtype.names:
            out.extend(_flatten(f"{name}.{field}", arr[field]))
        return out
    if arr.ndim <= 1:  # リーフ
        return [(name, np.ascontiguousarray(arr))]
    return [
        pair
        for i in range(arr.shape[1])
        for pair in _flatten(f"{name}[{i}]", arr[:, i])
    ]


def _all_leaf_count(spec: ColumnSpec) -> int:
    """展開後の全リーフ列数 — **dtype 非依存に数える** (LD-14 の列名文法).

    「N 本に展開」info 診断の母数 (spec S2)。数値リーフだけを数える
    column_names.leaf_count とは意図的に別物である。
    """
    if spec.kind == "struct":
        return sum(_all_leaf_count(sub) for _n, sub in spec.fields)
    if spec.kind == "array":
        assert spec.child is not None
        return spec.axis_len * _all_leaf_count(spec.child)
    return 1


def _expansion_diagnostic(
    display_name: str,
    samples: np.ndarray,
    leaf_total: int,
    numeric_total: int,
    diagnostics: list[Diagnostic],
) -> None:
    """「N 本に展開」info を物理チャンネル 1 件だけ emit する (E-3 反転).

    列を実際に作らなくなったので、件数は **dtype 非依存の全リーフ数**
    (_all_leaf_count) を渡す — 数値リーフだけを数える column_names.leaf_count に
    替えると混在構造 (Q.x + Q.tag) の表示が「2 本」->「1 本」に変わり、列展開
    時代の文言と非互換になる。文言と signal_name は旧 _explode_samples と同一。

    **D1 (T7 決定)**: その dtype 非依存の N は、混在構造ではユーザーが到達できる
    列数と食い違う (Q は「2 本」だがブラウザ/エクスポートに出るのは Q.x の 1 本)。
    反転前はその差を per-column の「非数値型のためスキップ」warning が説明していたが、
    集約 (意図的 supersede) で消えた。N そのものは S2 の mandate ゆえ据え置き、
    **食い違うときだけ**到達可能な本数を併記して説明を復活させる。数値==全数の
    通常ケース (prod_demo は全件そう: info 320 / warning 0) では文言完全不変。
    """
    if samples.dtype.names:
        shape_desc = "構造化チャンネル"
    else:
        shape_desc = "x".join(str(d) for d in samples.shape[1:]) + " 配列"
    message = f"信号 '{display_name}': {shape_desc}を {leaf_total} 本に展開"
    if numeric_total != leaf_total:
        message += f"（うち数値列 {numeric_total} 本）"  # noqa: RUF001
    diagnostics.append(
        Diagnostic(
            level="info",
            message=message,
            signal_name=display_name,
        )
    )


def _extract_value_labels(conversion: Any) -> dict[float, str] | None:
    """value2text (TABX) の値→ラベル表を抽出。取れなければ None (生値で続行).

    ``select()`` の戻り Signal は conversion が常に None (ignore_value2text の
    真偽に依らず・Task 2 で実測確認) — 呼び出し元は select を経ない生チャンネル
    (``mdf.groups[gi].channels[ci].conversion``) を渡す。

    ChannelConversion の val_N/text_N は動的属性 (asammdf 内部表現・ソース
    確認: .venv/Lib/site-packages/asammdf/blocks/v4_blocks.py の TABX 読込/
    構築コード) — val_i は ``conversion.val_i`` (float)、対応テキストは
    ``conversion.referenced_blocks["text_i"]`` (ファイル読込時は
    decode=False で bytes、from_dict 経由の in-memory 構築時も utf-8
    encode 済み bytes)。RTABX (範囲変換) は val_i を持たず lower_i/upper_i を
    使うため、この走査は自然に対象外になる (値ラベルは離散値の概念であり
    範囲には適用しない)。
    """
    if conversion is None:
        return None
    referenced_blocks = getattr(conversion, "referenced_blocks", None)
    if not referenced_blocks:
        return None
    try:
        labels: dict[float, str] = {}
        i = 0
        while hasattr(conversion, f"val_{i}") and f"text_{i}" in referenced_blocks:
            val = getattr(conversion, f"val_{i}")
            text = referenced_blocks[f"text_{i}"]
            if isinstance(text, bytes):
                try:
                    text = text.decode("utf-8")
                except UnicodeDecodeError:
                    text = text.decode("latin-1")
            if not isinstance(text, str):
                break  # ネストした ChannelConversion 等 (default 系) は対象外
            labels[float(val)] = text
            i += 1
        return labels or None
    except Exception:
        return None  # 抽出失敗はチャンネル生存を妨げない (spec §3.3)


def _extract_metadata(asammdf_sig: Any, raw_conversion: Any = None) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if asammdf_sig.unit:
        meta["unit"] = asammdf_sig.unit
    if asammdf_sig.comment:
        meta["comment"] = asammdf_sig.comment
    display_name = getattr(asammdf_sig, "display_name", None)
    if display_name:
        meta["display_name"] = display_name
    source = getattr(asammdf_sig, "source", None)
    if source is not None:
        meta["channel_group_name"] = getattr(source, "path", "") or ""
        meta["source_bus_type"] = getattr(source, "bus_type", 0)
        meta["source_name"] = getattr(source, "name", "") or ""
    # conversion_info は spec §3.3 の互換キー。呼び出し元の形状プローブは非 raw で
    # 引くため asammdf_sig.conversion は常に None (実測) — 実体は raw_conversion
    # (生チャンネルの ChannelConversion) から来る。asammdf_sig 側の取得は raw な
    # Signal を渡す呼び出し用に残す (この経路では実質フォールバックのみが効く)。
    # 帰結: 展開リーフは raw_conversion を None にして継承を止めているので
    # conversion_info も載らない = 「配列成分は value_labels も conversion_info も
    # 持たない」(LD-07) の設計どおり。
    conversion = getattr(asammdf_sig, "conversion", None) or raw_conversion
    if conversion is not None:
        meta["conversion_info"] = str(conversion)
    labels = _extract_value_labels(raw_conversion)
    if labels:
        meta["value_labels"] = labels
    return meta


class MdfLoader:
    """MDF (3.x / 4.x) file loader using asammdf. Reads all channel groups in one pass."""

    _READ_OPTIONS: ClassVar[dict[str, Any]] = {
        "time_from_zero": False,
    }
    # 唯一のプローブ: 1 レコードだけ **遅延読みと同じ非 raw の正準オプション**
    # (raw=False / ignore_value2text_conversions=True (LD-13) / copy_master=False
    # (LD-10) — LazyMdfValues.array() と同一セット) で読む。値の全読みは遅延。
    #
    # 非 raw 1 本で全用途 (形状・ColumnSpec・selector・metadata・展開列数・数値性
    # ゲート) を賄える根拠:
    #   - 形状 / _flatten のリーフ名 / metadata (unit・comment・display_name・
    #     source) は変換非依存。prod_demo.mf4 の全 4,324 チャンネルで raw と非 raw の
    #     shape・リーフ名・dtype.kind・上記 metadata が完全一致し、select コストも
    #     同等 (raw 0.75s / 非 raw 0.74s) と実測。
    #   - 数値性 (dtype.kind) のゲートだけは **非 raw 側でなければ誤る**。asammdf は
    #     ignore_value2text_conversions で TABX/RTABX/TRANS/BITFIELD を短絡するが
    #     CONVERSION_TYPE_TTAB (text→value) には同ガードが無く (v4_blocks.py:4337)、
    #     raw=テキスト / 物理値=数値になる。本読みは非 raw で行われるので raw の
    #     dtype でゲートすると「数値なのに非数値としてスキップ」する (回帰テスト:
    #     test_ttab_channel_survives_with_physical_numeric_values)。
    # 以前は raw プローブと非 raw の dtype プローブを 2 本 select していたが、上記の
    # とおり非 raw 1 本に統合できる (2 本目は prod 実測で load wall +1.35s の純粋な
    # 重複読み — 12.11s → 13.46s)。
    _PROBE_OPTIONS: ClassVar[dict[str, Any]] = {
        "record_count": 1,
        "raw": False,
        "ignore_value2text_conversions": True,
        "copy_master": False,
    }
    # master 読み専用 (_load_group): 遅延読みと同じ正準オプションで 1 チャンネル
    # だけ select し timestamps を取る。get_master(gi) と違い開いたハンドルに
    # 生レコードブロックを残さない (詳細は _load_group のコメント)。
    _MASTER_OPTIONS: ClassVar[dict[str, Any]] = {
        "raw": False,
        "ignore_value2text_conversions": True,
        "copy_master": False,
    }
    # LD-02: MDF 3.x/4.x を版横断で受理。版判定は asammdf の内容自動判別に委任。
    # 非MDF/破損 (誤ラベルの .dat 等) は load() の try/except で error 診断化する。
    _SUPPORTED_SUFFIXES: ClassVar[frozenset[str]] = frozenset({".mf4", ".mdf", ".dat"})

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self._SUPPORTED_SUFFIXES

    @staticmethod
    def _format_label(mdf: Any) -> str:
        """MDF の版から file_format ラベルを決める (v4→MDF4 / それ以外→MDF3・LD-02)。"""
        version = str(getattr(mdf, "version", "4"))
        return "MDF4" if version.startswith("4") else "MDF3"

    def load(
        self,
        file_path: Path,
        cancel: Callable[[], bool] | None = None,
    ) -> LoadResult:
        if not file_path.exists() or not file_path.is_file():
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error",
                        message=f"ファイルが見つからないか、アクセスできません: {file_path}",
                    ),
                ),
            )

        try:
            mdf = MDF(str(file_path), **self._READ_OPTIONS)
        except Exception as exc:
            # ハンドル未生成のためリークなし (close 不要)。
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error",
                        message=f"MDF '{file_path.name}' の解析に失敗しました: {exc}",
                    ),
                ),
            )

        # 遅延読みのため MDF を開いたまま MdfHandle で保持する。成功経路では
        # SignalGroup がハンドルを所有し unload まで close しない。エラー/キャンセル
        # 経路でのみ明示的に close して決定的にハンドル/ロックを解放する (M3)。
        resolved_path = file_path.resolve()
        # source_path は Signal.source_file と同一の文字列にする — 遅延読みが失敗
        # したとき、診断ラベルが render 境界 (Signal 経由) と食い違わないため。
        handle = MdfHandle(mdf, str(resolved_path))
        signals: list[Signal] = []
        diagnostics: list[Diagnostic] = []
        # 物理チャンネル 1 本につき 1 レコード (列数ではない) — prod 4,324 件。
        column_records: dict[str, ColumnRecord] = {}
        # mdf.close() 後は版が読めない恐れがあるため、ここで確定させる (LD-02)。
        format_label = self._format_label(mdf)
        try:
            name_total = self._count_names(mdf)
            name_seen: dict[str, int] = {}
            # mdf.virtual_groups (物理グループ数ではない) を走査 — v4.20+ の
            # remote-master/column-storage ファイルでは follower 物理グループの
            # gi が virtual_groups のキーに乗らない (マスタ側 gi に統合される)。
            # 物理グループ数で回すと follower gi で included_channels() が
            # KeyError → 外側の broad except に飲まれファイル全体が全滅する
            # (Task 2 レビュー critical)。asammdf 公式パターン (iter_channels
            # 等) と同じ規則。
            for gi in mdf.virtual_groups:
                self._load_group(
                    mdf,
                    gi,
                    resolved_path,
                    name_total,
                    name_seen,
                    signals,
                    diagnostics,
                    cancel,
                    handle,
                    column_records,
                )
        except LoadCancelled:
            # Must not be swallowed by the broad except below (LoadCancelled is
            # an Exception too) — propagate so the caller sees a cancel, not a
            # generic "failed to read channels" diagnostic. キャンセルでも
            # ハンドルはリークさせない (成功経路のみ close を省く)。
            handle.close()
            raise
        except Exception as exc:
            handle.close()
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error",
                        message=f"'{file_path.name}' のチャンネル読み取りに失敗しました: {exc}",
                    ),
                ),
            )

        if not signals:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    message="チャンネルが 0 本です（全チャンネルが読み取り不能）",  # noqa: RUF001
                )
            )

        signal_group = SignalGroup(
            signals=tuple(signals),
            source_path=resolved_path,
            file_format=format_label,
            loaded_at=datetime.datetime.now(),
            handle=handle,
        )
        return LoadResult(
            signal_group=signal_group,
            diagnostics=tuple(diagnostics),
            column_records=column_records,
        )

    @staticmethod
    def _group_entries(mdf: Any, gi: int) -> list[tuple[str, int, int]]:
        """(name, group_index, channel_index) for gi's leaf channels.

        ``mdf.included_channels(gi)`` は同グループのマスタと、構造化チャンネルの
        成分 (channel_dependencies で辿れる子, 例: x/y) を除外済み — 素朴に
        ``group.channels`` を列挙すると親+成分の重複取得になる (Task 1 レビュー
        で確認, LD-13 一次情報)。戻り値は ``{gi: {phys_gi: [ch_index, ...]}}``。
        """
        included = mdf.included_channels(gi)[gi]
        return [
            (mdf.groups[phys_gi].channels[ci].name, phys_gi, ci)
            for phys_gi, channel_indexes in included.items()
            for ci in channel_indexes
        ]

    def _count_names(self, mdf: Any) -> dict[str, int]:
        """重複名 [idx] 曖昧化のための事前カウント (メタデータ走査のみ).

        ``load()`` と同じ理由 (virtual_groups が follower 物理グループを
        キーに含まないケースがある, Task 2 レビュー critical) で
        ``mdf.virtual_groups`` を走査する。
        """
        totals: dict[str, int] = {}
        for gi in mdf.virtual_groups:
            for name, _gi, _ci in self._group_entries(mdf, gi):
                totals[name] = totals.get(name, 0) + 1
        return totals

    def _load_group(
        self,
        mdf: Any,
        gi: int,
        resolved_path: Path,
        name_total: dict[str, int],
        name_seen: dict[str, int],
        signals: list[Signal],
        diagnostics: list[Diagnostic],
        cancel: Callable[[], bool] | None,
        handle: MdfHandle,
        column_records: dict[str, ColumnRecord],
    ) -> None:
        entries = self._group_entries(mdf, gi)
        if not entries:
            return
        if cancel is not None and cancel():
            raise LoadCancelled(f"load cancelled: {resolved_path.name}")

        # master を仮想グループ単位で単体読みする (値は読まない)。診断・同一性・
        # 長さの土台。
        #
        # get_master(gi) は使えない: 遅延読みのためハンドルを開いたままにする本
        # ローダーでは、get_master がグループの生レコードブロック全体を開いた
        # ハンドル上にキャッシュし、ハンドルが生きている限り解放されない
        # (prod_demo.mf4 1.36GB で +1,296MB 保持・master 実体は全グループ計
        # 0.20MB)。select はフラグメントをストリームし何も保持しない
        # (同条件で +197MB) — 得られる master 列は get_master と完全一致する
        # (実測・tests/core/loaders/test_mdf_loader_lazy.py で固定)。
        #
        # entries[0] はこのグループの実チャンネル (マスタは included_channels が
        # 除外済み)。オプションは LazyMdfValues.array() と同じ正準セット。
        # timestamps は copy_master=False で asammdf 内部を指しうるため、
        # 参照を残さないよう必ずコピーしてから凍結する。
        asig = mdf.select([entries[0]], **self._MASTER_OPTIONS)[0]
        master = np.array(asig.timestamps, dtype=np.float64, copy=True)
        del asig  # 値サンプルを即時に解放 (master だけを持ち越す)
        if len(master) > 0 and not np.all(np.isfinite(master)):
            # 文言は現行と同一 (チャンネルごとに emit — 既存テスト互換)。
            for base_name, _g, _c in entries:
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message=(
                            f"信号 '{base_name}': 非有限タイムスタンプを含むため"
                            "スキップ（時刻軸が破損）"  # noqa: RUF001
                        ),
                        signal_name=base_name,
                    )
                )
            return
        master.flags.writeable = False
        diffs = np.diff(master)
        # (非単調, 重複) を1回だけ計算 — グループ内の全列で共有する。
        n_backward, n_dup = int(np.sum(diffs < 0)), int(np.sum(diffs == 0))

        # 形状のみ 1 レコードプローブで取る (値の全読みは遅延)。列名 (=selector)・
        # dtype・source は 1 レコードから確定する (shape[1:]/dtype/metadata は
        # record_count に依存しない)。プローブは非 raw = 本読み
        # (LazyMdfValues.array()) と同じ側なので、その dtype がそのまま数値性
        # ゲートの根拠になる (_PROBE_OPTIONS のコメント参照)。
        probes = mdf.select(entries, **self._PROBE_OPTIONS)
        for (base_name, _g, _c), probe in zip(entries, probes, strict=True):
            if cancel is not None and cancel():
                raise LoadCancelled(f"load cancelled: {resolved_path.name}")
            idx = name_seen.get(base_name, 0)
            name_seen[base_name] = idx + 1
            deduplicated = name_total[base_name] > 1
            signal_name = f"{base_name}[{idx}]" if deduplicated else base_name
            if signal_name in column_records:
                # 1:1 不変条件 (表のキー集合 == 発行された Signal 名) の loud-fail。
                # LD-08 の [i] 曖昧化は **生チャンネル名としても合法な形** なので、
                # 別の物理チャンネルの名前と字面で衝突しうる (同名 'A' 2 本 ->
                # A[0]/A[1] と、文字どおり 'A[0]' という第 3 のチャンネルが同居)。
                # 表への代入は last-wins・signals への append は上書きしないため、
                # 黙って通すと表と Signal が 1:1 でなくなり、いずれも**例外を出さずに**
                # 壊れる: (a) 列数の母数が 1 チャンネル分丸ごと過少になる
                # (b) ブラウザが 2 本を 1 行へ畳み、物理チャンネルが木/フィルタ/
                # D&D/プレビュー/エクスポートから同時に消える (c) 生き残った表の
                # 側が配列なら _mint_column が表示名の最長一致で **別チャンネルの
                # 列** を鋳造し、値は一方から・timestamps/unit/bus_type/source_file は
                # もう一方から来る (長さが偶然一致すると sample_source の長さ検証も
                # 通るので、時間軸だけ別チャンネルの「普通に見える曲線」になる)。
                # 誤データより見える拒否を選ぶ。
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message=(
                            f"信号 '{signal_name}': 同名の別チャンネルが既にあるため"
                            "スキップ（列名が一意になりません）"  # noqa: RUF001
                        ),
                        signal_name=signal_name,
                    )
                )
                continue

            samples = probe.samples
            spec = spec_from_probe(samples)
            exploded = samples.ndim != 1 or bool(samples.dtype.names)
            # E-3 反転: 展開列は Signal にしない。作るのは **物理チャンネル 1 本に
            # つき Signal 1 個** で、列は SignalGroupManager が ColumnRecord から
            # 要求時に鋳造する (264,004 -> 4,324)。
            all_leaves = _all_leaf_count(spec)
            numeric_leaves = leaf_count(spec)
            if exploded and all_leaves:
                _expansion_diagnostic(
                    signal_name, samples, all_leaves, numeric_leaves, diagnostics
                )
            if all_leaves == 0:
                # 0 幅軸の展開不能列。列展開時代も pairs が空でループが 1 度も回らず
                # Signal も診断も出なかった — その沈黙をそのまま保つ。
                continue

            # 数値性は **リーフ単位** で判定する (spec S2)。構造化チャンネルの親
            # probe は dtype.kind == 'V' なので、親の dtype をゲートに使うと全ての
            # 構造化チャンネルが「非数値型のためスキップ」で消滅する。probe は非 raw
            # (= 本読みと同じ側) なので、その dtype がそのままゲートの根拠になる
            # (raw 側で判定すると TTAB が消える・_PROBE_OPTIONS のコメント参照)。
            if numeric_leaves == 0:
                # signal_name を Diagnostic に載せないのは列展開時代と同一
                # (1-D 非数値の診断を byte-identical に保つ)。
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"信号 '{signal_name}': 非数値型のためスキップ"
                            f"（dtype {samples.dtype}）"  # noqa: RUF001
                        ),
                    )
                )
                continue

            # 非単調/重複はグループ master の性質なので **物理チャンネル 1 件**。
            # 列ごとの emit は prod で 1 グループ最大 96,000 件の水増しだった
            # (配列/構造化チャンネルの列単位 warning 集約は意図的 supersede・
            # 1-D チャンネルの文言/件数/signal_name は不変)。
            if n_backward or n_dup:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"信号 '{signal_name}': 非単調 {n_backward} 箇所・"
                            f"重複タイムスタンプ {n_dup} 点"
                            "（表示/演算は整列ビューで補正）"  # noqa: RUF001
                        ),
                        signal_name=signal_name,
                    )
                )

            # value_labels (value2text) は 1D 通常チャンネルのみ継承する —
            # value2text はスカラー enum の概念で、展開対象チャンネル (2D/構造化)
            # には意味を持たない (LD-07)。取得元を生チャンネルにしているのは、
            # 展開時に None を渡して継承を止められる唯一の口だから (probe は非 raw
            # なので conversion が常に None)。
            raw_conversion = (
                None if exploded else mdf.groups[_g].channels[_c].conversion
            )
            metadata = _extract_metadata(probe, raw_conversion)
            # ブラウザの「1 行=1 物理チャンネル」グループ化キー。生 base_name では
            # なく signal_name を使う: LD-08 で name_total>1 のとき base_name は別の
            # 物理チャンネル (別 gi/ci・別 shape/unit) と共有され同一性を失う。
            metadata["physical_channel"] = signal_name
            if deduplicated:
                # E-2b: LD-08 の [idx] 曖昧化を経た名前だけに立てる旗 (cross-file の
                # 同名重ねから除外する唯一の根拠)。展開名 "Mat[0]" は文字列として
                # 同じ形でも立てない — 判定は name_total[base_name] だから。
                metadata["name_deduplicated"] = True
            # E-3: 鋳造 (要求時の列生成) の材料はここでしか確定できない。表示名からは
            # 生名も (gi, ci) も復元できず、後から引き直すとファイル全体の再走査に
            # なる。spec は既に読んだ 1 レコードプローブ由来で値を持たない。
            # **Signal を作る分岐の内側** に置くこと — skip したチャンネルを表に
            # 残すと「行はあるが Signal が無い」死にキーが復活する。
            column_records[signal_name] = ColumnRecord(
                raw_base_name=base_name,
                group_index=_g,
                channel_index=_c,
                spec=spec,
            )
            signals.append(
                Signal(
                    name=signal_name,
                    timestamps=master,
                    # selector=None: 物理チャンネル全体を読む器。列は鋳造側が
                    # ColumnRecord から selector 付き LazyMdfValues で作る (LD-14)。
                    values_source=LazyMdfValues(
                        handle, base_name, _g, _c, length=len(master)
                    ),
                    file_format=self._format_label(mdf),  # LD-02: MDF3/MDF4
                    bus_type=_detect_bus_type(getattr(probe, "source", None)),
                    source_file=str(resolved_path),
                    metadata=metadata,
                )
            )
