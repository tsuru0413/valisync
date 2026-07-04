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


def _extract_metadata(asammdf_sig: Any) -> dict[str, Any]:
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
    conversion = getattr(asammdf_sig, "conversion", None)
    if conversion is not None:
        meta["conversion_info"] = str(conversion)
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
        try:
            name_total = self._count_names(mdf)
            name_seen: dict[str, int] = {}
            for gi in range(len(mdf.groups)):
                self._load_group(
                    mdf,
                    gi,
                    file_path,
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
            source_path=file_path.resolve(),
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
        """重複名 [idx] 曖昧化のための事前カウント (メタデータ走査のみ)."""
        totals: dict[str, int] = {}
        for gi in range(len(mdf.groups)):
            for name, _gi, _ci in self._group_entries(mdf, gi):
                totals[name] = totals.get(name, 0) + 1
        return totals

    def _load_group(
        self,
        mdf: Any,
        gi: int,
        file_path: Path,
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
            raise LoadCancelled(f"load cancelled: {file_path.name}")
        asigs = mdf.select(entries, **self._SELECT_OPTIONS)

        master: np.ndarray | None = None
        master_bad = False
        master_diffs_warn: tuple[int, int] | None = None  # (非単調, 重複) を1回だけ計算
        for (base_name, _g, _c), asig in zip(entries, asigs, strict=True):
            if cancel is not None and cancel():
                raise LoadCancelled(f"load cancelled: {file_path.name}")
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
            if samples.ndim != 1 or samples.dtype.names:
                # Task 3 で展開に置換 — 本タスクでは現行どおり skip
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"Signal '{base_name}' has {samples.ndim}D samples"
                            " (expected 1D), skipped"
                        ),
                    )
                )
                continue

            try:
                values = samples.astype(np.float64, copy=False)
            except (ValueError, TypeError) as exc:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=f"Signal '{base_name}' has non-numeric values, skipped: {exc}",
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
                            f"Signal '{base_name}': 非単調 {n_backward} 箇所・"
                            f"重複タイムスタンプ {n_dup} 点"
                            "（表示/演算は整列ビューで補正）"  # noqa: RUF001
                        ),
                        signal_name=base_name,
                    )
                )

            assert (
                master is not None
            )  # unreachable: master_bad already continue'd above
            signals.append(
                Signal(
                    name=signal_name,
                    timestamps=master,
                    values=values,
                    file_format="MDF4",
                    bus_type=_detect_bus_type(getattr(asig, "source", None)),
                    source_file=str(file_path.resolve()),
                    metadata=_extract_metadata(asig),
                )
            )
