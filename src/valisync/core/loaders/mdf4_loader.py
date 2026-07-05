from __future__ import annotations

import datetime
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from asammdf import MDF

from valisync.core.models import Diagnostic, LoadResult, Signal, SignalGroup
from valisync.core.models.load_result import LoadCancelled

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

    ``_flatten`` と同じ規則: 構造化はフィールド再帰合算、多次元は非サンプル軸
    (shape[1:]) の積。プローブ (record_count=1) と本読みで shape[1:] は一致する
    ため 1 レコードから正確な展開列数が得られる。
    """
    if arr.dtype.names:
        return sum(_leaf_column_count(arr[f]) for f in arr.dtype.names)
    if arr.ndim <= 1:
        return 1
    return int(np.prod(arr.shape[1:]))


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
                message=f"Signal '{base_name}': {shape_desc}を {len(pairs)} 本に展開",
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
    # select() の戻り Signal は conversion が常に None のため、互換キー
    # conversion_info も生チャンネル側 (raw_conversion) から生成する (spec §3.3)
    conversion = getattr(asammdf_sig, "conversion", None) or raw_conversion
    if conversion is not None:
        meta["conversion_info"] = str(conversion)
    labels = _extract_value_labels(raw_conversion)
    if labels:
        meta["value_labels"] = labels
    return meta


class Mdf4Loader:
    """MDF4 file loader using asammdf. Reads all channel groups in one pass."""

    _READ_OPTIONS: ClassVar[dict[str, Any]] = {
        "time_from_zero": False,
    }
    # ignore_value2text_conversions は MDF() には無効な dead オプションだった
    # (LD-13)。select() では有効 — enum は生値で届き、変換表は conversion に残る。
    _SELECT_OPTIONS: ClassVar[dict[str, Any]] = {
        "ignore_value2text_conversions": True,
        "copy_master": False,  # マスタ複製の排除 (LD-10)
    }

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".mf4"

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
                        message=f"File not found or not accessible: {file_path}",
                    ),
                ),
            )

        try:
            mdf = MDF(str(file_path), **self._READ_OPTIONS)
        except Exception as exc:
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error",
                        message=f"Failed to parse MDF4 '{file_path.name}': {exc}",
                    ),
                ),
            )

        signals: list[Signal] = []
        diagnostics: list[Diagnostic] = []
        resolved_path = file_path.resolve()
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
                )
        except LoadCancelled:
            # Must not be swallowed by the broad except below (LoadCancelled is
            # an Exception too) — propagate so the caller sees a cancel, not a
            # generic "failed to read channels" diagnostic.
            raise
        except Exception as exc:
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error",
                        message=f"Failed to read channels from '{file_path.name}': {exc}",
                    ),
                ),
            )
        finally:
            mdf.close()

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
            file_format="MDF4",
            loaded_at=datetime.datetime.now(),
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
    ) -> None:
        entries = self._group_entries(mdf, gi)
        if not entries:
            return
        if cancel is not None and cancel():
            raise LoadCancelled(f"load cancelled: {resolved_path.name}")
        asigs = mdf.select(entries, **self._SELECT_OPTIONS)

        master: np.ndarray | None = None
        master_bad = False
        master_diffs_warn: tuple[int, int] | None = None  # (非単調, 重複) を1回だけ計算
        for (base_name, _g, _c), asig in zip(entries, asigs, strict=True):
            if cancel is not None and cancel():
                raise LoadCancelled(f"load cancelled: {resolved_path.name}")
            idx = name_seen.get(base_name, 0)
            name_seen[base_name] = idx + 1
            signal_name = (
                f"{base_name}[{idx}]" if name_total[base_name] > 1 else base_name
            )

            if master is None and not master_bad:
                ts64 = asig.timestamps.astype(np.float64, copy=False)
                if len(ts64) > 0 and not np.all(np.isfinite(ts64)):
                    master_bad = True
                else:
                    ts64.flags.writeable = False
                    master = ts64
                    diffs = np.diff(master)
                    master_diffs_warn = (
                        int(np.sum(diffs < 0)),
                        int(np.sum(diffs == 0)),
                    )
            if master_bad:
                # 文言は現行と同一 (チャンネルごとに emit — 既存テスト互換)
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message=(
                            f"Signal '{base_name}': 非有限タイムスタンプを含むため"
                            " skip（時刻軸が破損）"  # noqa: RUF001
                        ),
                        signal_name=base_name,
                    )
                )
                continue

            samples = asig.samples
            exploded = samples.ndim != 1 or bool(samples.dtype.names)
            # 多次元/構造化は展開して複数列に、通常 1D は単一要素のペアに正規化
            # してから同じ astype/警告/Signal 構築ループへ流す (LD-12)。展開後
            # の各列名は "曖昧化済みベース名から派生" (spec §3.2 — 例 M[0][i]):
            # signal_name (name[idx] 済み) を _explode_samples の base に渡す。
            if exploded:
                pairs = _explode_samples(signal_name, samples, diagnostics)
            else:
                pairs = [(signal_name, samples)]

            # value_labels (value2text) は 1D 通常チャンネルのみ継承する —
            # value2text はスカラー enum の概念で、展開後の列 (2D/構造化の
            # 各成分) には意味を持たない (LD-07 spec 注記)。select() の戻り
            # asig.conversion は常に None (Task 2 実測) なので生チャンネル
            # (mdf.groups[gi].channels[ci]) から取得する。
            raw_conversion = (
                None if exploded else mdf.groups[_g].channels[_c].conversion
            )

            for out_name, col in pairs:
                try:
                    values = col.astype(np.float64, copy=False)
                except (ValueError, TypeError) as exc:
                    diagnostics.append(
                        Diagnostic(
                            level="warning",
                            message=(
                                f"Signal '{out_name}' has non-numeric values,"
                                f" skipped: {exc}"
                            ),
                        )
                    )
                    continue
                values.flags.writeable = False

                n_backward, n_dup = master_diffs_warn or (0, 0)
                if n_backward or n_dup:
                    diagnostics.append(
                        Diagnostic(
                            level="warning",
                            message=(
                                f"Signal '{out_name}': 非単調 {n_backward} 箇所・"
                                f"重複タイムスタンプ {n_dup} 点"
                                "（表示/演算は整列ビューで補正）"  # noqa: RUF001
                            ),
                            signal_name=out_name,
                        )
                    )

                assert (
                    master is not None
                )  # unreachable: master_bad already continue'd above
                signals.append(
                    Signal(
                        name=out_name,
                        timestamps=master,
                        values=values,
                        file_format="MDF4",
                        bus_type=_detect_bus_type(getattr(asig, "source", None)),
                        source_file=str(resolved_path),
                        metadata=_extract_metadata(asig, raw_conversion),
                    )
                )
