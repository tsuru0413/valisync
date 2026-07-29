from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from asammdf import MDF

from valisync.core.loaders.column_names import ColumnSpec, spec_from_probe
from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.models import Diagnostic, LoadResult, Signal, SignalGroup
from valisync.core.models.load_result import LoadCancelled
from valisync.core.models.sample_source import LazyMdfValues

EXPANSION_COLUMN_LIMIT = 1024  # per-channel の展開後リーフ列数の上限 (LD-14)


@dataclass(frozen=True)
class OversizedChannel:
    """展開列数が上限を超えるチャンネル (確認ダイアログ提示用)."""

    name: str
    column_count: int


@dataclass(frozen=True)
class ExpansionRequest:
    """上限超チャンネルの集約 — confirm_expansion コールバックへ渡す."""

    channels: tuple[OversizedChannel, ...]


# confirm_expansion(request) -> 展開する channels のインデックス集合。
# 返らなかったインデックスはスキップ。空集合は全スキップ。
ConfirmExpansion = Callable[[ExpansionRequest], set[int]]

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


def _leaf_column_count(arr: np.ndarray) -> int:
    """arr を _flatten したときのリーフ列数 (1 レコードの samples でも可・LD-14).

    1024 ガードの母数なので **dtype 非依存に全リーフを数える** (数値のみを数える
    column_names.leaf_count とは意図的に別物)。構造は column_names の ColumnSpec に
    委譲し、規則の二重実装を避ける。
    """
    return _all_leaf_count(spec_from_probe(arr))


def _all_leaf_count(spec: ColumnSpec) -> int:
    if spec.kind == "struct":
        return sum(_all_leaf_count(sub) for _n, sub in spec.fields)
    if spec.kind == "array":
        assert spec.child is not None
        return spec.axis_len * _all_leaf_count(spec.child)
    return 1


def _explode_samples(
    base_name: str,
    samples: np.ndarray,
    diagnostics: list[Diagnostic],
) -> list[tuple[str, np.ndarray]]:
    """多次元/構造化 samples を 1D 列へ多段展開 (LD-14).

    ``_flatten`` に一本化。展開できたら透明化のため info 診断を 1 件 emit する。
    展開不能な列 (0 幅など) は自然に空リストになる。
    """
    pairs = _flatten(base_name, samples)
    if pairs:
        if samples.dtype.names:
            shape_desc = "構造化チャンネル"
        else:
            shape_desc = "x".join(str(d) for d in samples.shape[1:]) + " 配列"
        diagnostics.append(
            Diagnostic(
                level="info",
                message=f"信号 '{base_name}': {shape_desc}を {len(pairs)} 本に展開",
                signal_name=base_name,
            )
        )
    return pairs


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
    # conversion_info は spec §3.3 の互換キー。呼び出し元の形状プローブは
    # raw=True で引くため asammdf_sig.conversion には**そのチャンネルの
    # ChannelConversion** が入る (raw=False の戻りは None — 実測)。raw_conversion
    # フォールバックは非 raw 経路/生チャンネル渡しのために残す (消すと
    # conversion_info が欠ける)。
    # 既知の副作用 (増分B で是正予定): 展開リーフでは raw_conversion を意図的に
    # None にして継承を止めているが、raw=True プローブ側が非 None のため
    # conversion_info だけはリーフにも載る。現状 src 内に読み手はゼロ。
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
    # 形状スキャン専用: 1 レコードだけ raw で読む (変換不要・形状は変換非依存)。
    # 値の本読みは遅延 — LazyMdfValues.array() が非 raw の正準オプション
    # raw=False / ignore_value2text_conversions=True (LD-13) / copy_master=False
    # (LD-10) で単一チャンネル select する。
    _PROBE_OPTIONS: ClassVar[dict[str, Any]] = {
        "record_count": 1,
        "raw": True,
        "ignore_value2text_conversions": True,
        "copy_master": False,
    }
    # 数値性 (dtype.kind) 判定専用: 1 レコードを **遅延読みと同じ非 raw の正準
    # オプション** で読む。raw プローブの dtype では判定できない — 変換次第で
    # raw と物理値の dtype.kind が食い違う (下の _load_group のゲート参照)。
    _DTYPE_PROBE_OPTIONS: ClassVar[dict[str, Any]] = {
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

    def _scan_oversized(
        self,
        mdf: Any,
        cancel: Callable[[], bool] | None,
    ) -> tuple[list[OversizedChannel], list[tuple[int, int]]]:
        """本読み前に各チャンネルの展開列数を 1 レコードプローブで算出する (LD-14).

        1024 超のチャンネルを集約して返す。呼び出しはグループ単位 (仮想グループ数
        ぶん) の極小読みで済む。戻り値は表示用 OversizedChannel 列と、対応する
        (物理gi, ci) キー列 (本読みでの除外照合用) の並列リスト。
        """
        oversized: list[OversizedChannel] = []
        keys: list[tuple[int, int]] = []
        for gi in mdf.virtual_groups:
            if cancel is not None and cancel():
                raise LoadCancelled("load cancelled during expansion scan")
            entries = self._group_entries(mdf, gi)
            if not entries:
                continue
            probes = mdf.select(entries, **self._PROBE_OPTIONS)
            for (name, phys_gi, ci), probe in zip(entries, probes, strict=True):
                cols = _leaf_column_count(probe.samples)
                if cols > EXPANSION_COLUMN_LIMIT:
                    oversized.append(OversizedChannel(name=name, column_count=cols))
                    keys.append((phys_gi, ci))
        return oversized, keys

    def load(
        self,
        file_path: Path,
        cancel: Callable[[], bool] | None = None,
        confirm_expansion: ConfirmExpansion | None = None,
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
        handle = MdfHandle(mdf)
        signals: list[Signal] = []
        diagnostics: list[Diagnostic] = []
        resolved_path = file_path.resolve()
        # mdf.close() 後は版が読めない恐れがあるため、ここで確定させる (LD-02)。
        format_label = self._format_label(mdf)
        try:
            # 本読み前に展開列数をスキャンし、1024 超は確認 (無ければ全スキップ)。
            # 承認されなかった超過チャンネルは skip_keys で本読み entries からも
            # 除外する (本読みすらしない = メモリ/時間も節約・LD-14)。
            oversized, over_keys = self._scan_oversized(mdf, cancel)
            skip_keys: set[tuple[int, int]] = set()
            if oversized:
                if confirm_expansion is not None:
                    chosen = confirm_expansion(
                        ExpansionRequest(channels=tuple(oversized))
                    )
                else:
                    chosen = set()  # ヘッドレス: 確認できないので全スキップ (安全側)
                skip_keys = {key for i, key in enumerate(over_keys) if i not in chosen}
                for i, key in enumerate(over_keys):
                    if key in skip_keys:
                        diagnostics.append(
                            Diagnostic(
                                level="warning",
                                message=(
                                    f"信号 '{oversized[i].name}': 展開列数 "
                                    f"{oversized[i].column_count} が上限 "
                                    f"{EXPANSION_COLUMN_LIMIT} を超えるためスキップ"
                                ),
                                signal_name=oversized[i].name,
                            )
                        )

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
                    skip_keys,
                    handle,
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
        return LoadResult(signal_group=signal_group, diagnostics=tuple(diagnostics))

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
        skip_keys: set[tuple[int, int]],
        handle: MdfHandle,
    ) -> None:
        # skip_keys の (gi, ci) は上限超で展開しないと決まったチャンネル — 本読み
        # entries から外し select にも渡さない (LD-14)。
        entries = [
            e for e in self._group_entries(mdf, gi) if (e[1], e[2]) not in skip_keys
        ]
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
        # record_count に依存しない)。
        probes = mdf.select(entries, **self._PROBE_OPTIONS)
        # 数値性ゲートだけは物理値 (非 raw) 側の dtype で判定する — raw と物理値で
        # dtype.kind が食い違う変換が実在するため。asammdf は
        # ignore_value2text_conversions で TABX/RTABX/TRANS/BITFIELD を短絡するが
        # CONVERSION_TYPE_TTAB (text→value) には同ガードが無く
        # (v4_blocks.py:4337)、raw=テキスト / 物理値=数値になる。値の本読みは
        # LazyMdfValues.array() が非 raw で行うので、ゲートも同じ側で見ないと
        # 「数値なのに非数値としてスキップ」する (形状/ColumnSpec/metadata は
        # 変換非依存なので raw プローブのまま)。
        dtype_probes = mdf.select(entries, **self._DTYPE_PROBE_OPTIONS)
        for (base_name, _g, _c), probe, dtype_probe in zip(
            entries, probes, dtype_probes, strict=True
        ):
            if cancel is not None and cancel():
                raise LoadCancelled(f"load cancelled: {resolved_path.name}")
            idx = name_seen.get(base_name, 0)
            name_seen[base_name] = idx + 1
            deduplicated = name_total[base_name] > 1
            signal_name = f"{base_name}[{idx}]" if deduplicated else base_name

            samples = probe.samples
            exploded = samples.ndim != 1 or bool(samples.dtype.names)
            # 多次元/構造化は展開して複数列に、通常 1D は単一要素のペアに正規化
            # してから同じ dtype 検査/警告/Signal 構築ループへ流す (LD-12)。
            #   out_name: 曖昧化済み signal_name 由来 (spec §3.2 — 例 M[0][i])。
            #   selector: LazyMdfValues は base_name で _flatten してリーフを引く
            #     ため base_name 由来のリーフキーにする。out_leaves と sel_leaves
            #     は同一構造の走査で順序一致し prefix のみ相違する (signal_name が
            #     曖昧化された場合でも遅延読みが正しいリーフを抽出できる)。
            #   col_probe: 1 レコードの該当リーフ (dtype 検査用)。
            if exploded:
                out_leaves = _explode_samples(signal_name, samples, diagnostics)
                sel_leaves = _flatten(base_name, samples)
                pairs: list[tuple[str, tuple[str, ...] | None, np.ndarray]] = [
                    (out_name, (sel_name,), col)
                    for (out_name, _o), (sel_name, col) in zip(
                        out_leaves, sel_leaves, strict=True
                    )
                ]
                # リーフ単位のゲート用に物理値側も同じ規則で 1 度だけ展開する
                # (ペアごとに _flatten を呼ぶと O(リーフ数^2) になる)。
                phys_leaf_dtypes = {
                    sel_name: col.dtype
                    for sel_name, col in _flatten(base_name, dtype_probe.samples)
                }
            else:
                pairs = [(signal_name, None, samples)]
                phys_leaf_dtypes = {}

            # value_labels (value2text) は 1D 通常チャンネルのみ継承する —
            # value2text はスカラー enum の概念で、展開後の列 (2D/構造化の
            # 各成分) には意味を持たない (LD-07 spec 注記)。取得元を生チャンネル
            # (mdf.groups[gi].channels[ci]) にしているのは、展開時に None を
            # 渡して継承を止められる唯一の口だから — probe は raw=True なので
            # probe.conversion にも同じ ChannelConversion が入っており
            # (raw=False なら None・実測)、そちらではリーフ単位に殺せない。
            raw_conversion = (
                None if exploded else mdf.groups[_g].channels[_c].conversion
            )

            for out_name, selector, col_probe in pairs:
                # FU-20: native dtype を保持し float64 膨張 (wide uint8 の 8x) を避ける。
                # 数値 (int/uint/float/bool) 以外は Signal が扱えないため従来どおり skip。
                # 判定は **物理値プローブ (非 raw = 本読みと同じ側) の該当リーフ**
                # で行う (値の全読みは不要)。リーフが物理値側で引けない場合のみ
                # raw リーフへフォールバックする (変換で形が変わる想定は無いが、
                # 引けないことを理由にチャンネルを落とさない)。float64 化は計算境界
                # Signal.sorted_view() で行う。
                gate_dtype = (
                    dtype_probe.samples.dtype
                    if selector is None
                    else phys_leaf_dtypes.get(selector[-1], col_probe.dtype)
                )
                if gate_dtype.kind not in "iufb":
                    diagnostics.append(
                        Diagnostic(
                            level="warning",
                            message=(
                                f"信号 '{out_name}': 非数値型のためスキップ"
                                f"（dtype {gate_dtype}）"  # noqa: RUF001
                            ),
                        )
                    )
                    continue

                if n_backward or n_dup:
                    diagnostics.append(
                        Diagnostic(
                            level="warning",
                            message=(
                                f"信号 '{out_name}': 非単調 {n_backward} 箇所・"
                                f"重複タイムスタンプ {n_dup} 点"
                                "（表示/演算は整列ビューで補正）"  # noqa: RUF001
                            ),
                            signal_name=out_name,
                        )
                    )

                out_metadata = _extract_metadata(probe, raw_conversion)
                # ブラウザの「1 行=1 物理チャンネル」グループ化キー。文字列解析では
                # ACC.Speed (チャンネル名) と P.x (構造化フィールド) を区別できない。
                # 生 base_name ではなく signal_name を使う: LD-08 で name_total>1 のとき
                # base_name は別の物理チャンネル (別 gi/ci・別 shape/unit) と共有され
                # 同一性を失う。selector 側の生名は LazyMdfValues が別に保持している。
                out_metadata["physical_channel"] = signal_name
                if deduplicated:
                    # E-2b: this name involved a LD-08 [idx] disambiguation —
                    # the ONLY basis cross-file same-name matching uses to
                    # exclude a signal from automatic overlay (spec §3 step 5).
                    # Array-expansion names (LD-14, e.g. "Mat[0]") look the
                    # same textually but are NOT flagged: deduplicated is keyed
                    # off name_total[base_name] (occurrences of the ORIGINAL
                    # channel name), not the "[i]" suffix pattern itself.
                    out_metadata["name_deduplicated"] = True
                signals.append(
                    Signal(
                        name=out_name,
                        timestamps=master,
                        values_source=LazyMdfValues(
                            handle,
                            base_name,
                            _g,
                            _c,
                            length=len(master),
                            selector=selector,
                        ),
                        file_format=self._format_label(
                            mdf
                        ),  # LD-02: 版に応じ MDF3/MDF4
                        bus_type=_detect_bus_type(getattr(probe, "source", None)),
                        source_file=str(resolved_path),
                        metadata=out_metadata,
                    )
                )
