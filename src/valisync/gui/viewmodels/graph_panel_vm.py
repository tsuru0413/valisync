"""GraphPanelVM — pure-Python ViewModel for the graph panel with dynamic LOD.

No PySide6/Qt/pyqtgraph imports.  Downsampling is always delegated to
``Session.downsample`` — never reimplemented here.

LOD pipeline (render_data):
  1. Slice the visible x-window via np.searchsorted on monotonic timestamps.
  2. If the slice exceeds 2*panel_width_px points, downsample via Session.
  3. Cache the result keyed by (rounded x_lo, rounded x_hi, panel_width_px,
     sorted tuple of visible signal keys) — unchanged inputs return the same
     list without recomputation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from valisync.core.interpolation import InterpolationMethod
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.core.models import Signal
from valisync.core.session import Session
from valisync.core.statistics.range_stats import StatisticsResult
from valisync.gui.theme import tokens
from valisync.gui.viewmodels.observable import Observable
from valisync.gui.viewmodels.y_axis_vm import YAxisVM

# Number of decimal places used when building the cache key from x-range floats.
# 9 decimal places = ~1 ns precision on seconds timestamps, more than sufficient.
_CACHE_KEY_DECIMALS: int = 9


def _padded_range(lo: float, hi: float) -> tuple[float, float]:
    """Expand a degenerate (~zero-width) auto-fit range around its centre.

    A constant signal fits to (v, v); mapped verbatim that yields a 1e-9-wide,
    degenerate Y axis (RN-05). Widen it to a readable window centred on v:
    +/-50% of |v|, or [-1, 1] when v == 0. Non-degenerate ranges pass through
    unchanged. Auto-fit callers only -- manual set_y_range keeps exact values.
    """
    if hi - lo > max(abs(hi), abs(lo), 1.0) * 1e-9:
        return (lo, hi)
    v = (lo + hi) / 2.0
    pad = abs(v) * 0.5 if v != 0.0 else 1.0
    return (v - pad, v + pad)


def _scaled_range(lo: float, hi: float, factor: float) -> tuple[float, float] | None:
    """Scale a range around its center by *factor* (FU-09 center-based zoom).

    factor < 1 shrinks (zoom in), > 1 expands (zoom out). Returns None for a
    degenerate (zero-width) span or any non-finite input/result, so callers
    treat it as a no-op rather than producing an unusable range.
    """
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return None
    center = (lo + hi) / 2.0
    half = (hi - lo) / 2.0 * factor
    if half == 0.0:
        return None
    new_lo, new_hi = center - half, center + half
    if not (math.isfinite(new_lo) and math.isfinite(new_hi)):
        return None
    return (new_lo, new_hi)


MIN_H: float = 0.05


@dataclass
class RenderCurve:
    """Immutable rendering payload for one signal curve.

    Passed directly to the Qt layer for painting — no Session or Signal objects
    cross this boundary, which keeps the View layer thin.
    """

    name: str  # namespaced signal key, e.g. "csv_1::speed"
    color: str  # hex colour (theme.tokens.signal_palette 由来 or ユーザー指定)
    timestamps: np.ndarray  # float64, already LOD-reduced if applicable
    values: np.ndarray  # float64, same length as timestamps
    axis_index: int = 0  # Added for multi-axis support
    entry_id: int = 0  # stable curve id (View internal key, per-entry op targeting)


@dataclass
class CursorReading:
    """1 信号のカーソル位置読み取り(Global_Cursor 用)。value=None は範囲外。"""

    name: str
    color: str
    value: float | None
    in_range: bool
    label: str | None = None  # value_labels 命中時のみ (LD-07)
    unit: str = ""  # metadata['unit'] (PC-11)
    entry_id: int = 0  # 逆引き用 (行クリック→曲線ハイライト)。既定0は非プロット文脈
    range_lo: float | None = None  # 信号の finite 最小 (min-max 列)。None=値域不明
    range_hi: float | None = None  # 信号の finite 最大


@dataclass
class DeltaReading:
    """1 信号の Delta 読み取り(R16/R17)。value_a=None は A 範囲外、dy=None は A/B どちらか範囲外。"""

    name: str
    color: str
    value_a: float | None
    dy: float | None
    stats: StatisticsResult  # count==0 はデータなし
    in_range: bool
    label: str | None = None  # value_a の value_labels 命中時のみ (LD-07)
    unit: str = ""  # metadata['unit'] (PC-11)
    entry_id: int = 0  # 逆引き用 (行クリック→曲線ハイライト)。既定0は非プロット文脈


def _resolve_value_label(sig: Signal | None, value: float | None) -> str | None:
    """整数に厳密一致し value_labels に載る値のみラベル化 (補間途中に嘘を付けない)。

    NaN/Inf は round() が ValueError/OverflowError を送出する (NaN 隣接補間は
    正規の動作で NaN を返す) ため、有限性を先に確認する。
    """
    if value is None or sig is None or not sig.metadata or not math.isfinite(value):
        return None
    labels = sig.metadata.get("value_labels")
    if not labels:
        return None
    r = round(value)
    if abs(value - r) < 1e-9:
        return labels.get(float(r))
    return None


@dataclass
class _PlottedEntry:
    """Internal record for one plotted signal."""

    signal_key: str
    color: str
    visible: bool = True
    axis_index: int = 0
    # monotonic stable id, distinguishes entries sharing a signal_key
    entry_id: int = 0


class GraphPanelVM(Observable):
    """ViewModel for the main graph panel with dynamic Level-of-Detail.

    Parameters
    ----------
    session:
        The application Session — the *only* gateway to core modules.
    """

    def __init__(self, session: Session) -> None:
        super().__init__()
        self._session = session
        self._plotted: list[_PlottedEntry] = []
        self._next_entry_id: int = 0  # monotonic id issued on each add
        self.x_range: tuple[float, float] | None = None
        # RN-02: x_range が「自動フィット由来」か「手動ズーム由来」かを区別する。
        # None チェックだけだと初回オートフィット後の非 None を手動と誤認し、
        # 別時間域の2本目信号が窓外で無表示になる。
        self._x_range_is_auto: bool = True
        self._column_count: int = 2
        self._axes: list[YAxisVM] = [YAxisVM(column=self._column_count - 1)]
        self.panel_width_px: int = 800
        self.lod_active: bool = False
        self.last_rendered_points: int = 0
        # Cache: maps cache-key → list[RenderCurve]
        self._cache: dict[tuple[Any, ...], list[RenderCurve]] = {}

        # Global cursor (R15) — transient, never persisted.
        self.cursor_t: float | None = None
        self.interp_method: InterpolationMethod = InterpolationMethod.LINEAR

        # Delta cursor + range stats (R16/R17) — transient, never persisted.
        self.cursor_t_b: float | None = None
        self.delta_enabled: bool = False
        # Stat column visibility (spec §7) — which of the 5 stat columns to show
        # in Delta readout. GraphPanelView syncs this into CursorReadout on each
        # render so the VM is the single source of truth.
        self.visible_stat_cols: set[str] = {"mean", "max", "min", "std", "count"}

        # 値・統計列の表示桁数(source of truth は VM。4/6/8 切替・既定 6・DP9)。
        # 時刻ヘッダと count には適用しない(spec 増分3 readout 刷新)。
        self.value_precision: int = 6

        # X 方向グリッド線の表示 (パネルごと transient・PC-15/DP13)。
        self.grid_enabled: bool = False

        # Time offsets (R14) — applied at render time to the ORIGINAL session
        # signal. signal_offsets keyed by namespaced name, file_offsets by group
        # key. Pushed in by GraphAreaVM on 'offsets' events; the authoritative
        # source is AppViewModel.
        self._signal_offsets: dict[str, float] = {}
        self._file_offsets: dict[str, float] = {}

    @property
    def y_range(self) -> tuple[float, float] | None:
        """Primary Y-axis range (for backward compatibility)."""
        if not self._axes:
            return None
        return self._axes[0].y_range

    @y_range.setter
    def y_range(self, val: tuple[float, float] | None) -> None:
        if self._axes and val is not None:
            self._axes[0].set_range(val[0], val[1])

    @property
    def axes(self) -> list[YAxisVM]:
        """Return the list of Y-axes."""
        return self._axes

    @property
    def column_count(self) -> int:
        """Number of vertical columns for Y-axis layout (default 2)."""
        return self._column_count

    def set_column_count(self, n: int) -> None:
        """Set the column count, clamped to >= 1, then reconcile axes and notify."""
        self._column_count = max(1, n)
        # Clamp any axis stranded in a now-out-of-range column; otherwise
        # _reconcile_axes would place it in the plot's own root grid cell
        # (column == column_count) and overlap the layout.
        for a in self._axes:
            a.column = min(a.column, self._column_count - 1)
        self._compact_axes()
        self._relayout_columns()
        self._notify("axes")

    # ─── Signal list management ──────────────────────────────────────────────

    def add_signal(self, signal_key: str) -> None:
        """Append *signal_key* to the plot with the next palette colour.

        Auto-fits x_range and y_range to the union of all plotted signals when
        those ranges have not been set manually.
        """
        self.add_signal_to_axis(signal_key, 0)

    def add_signal_to_axis(self, signal_key: str, axis_index: int) -> None:
        """Add *signal_key* to a specific axis."""
        palette = tokens.active().colors.signal_palette
        color = palette[len(self._plotted) % len(palette)].hex
        entry_id = self._next_entry_id
        self._next_entry_id += 1
        self._plotted.append(
            _PlottedEntry(
                signal_key=signal_key,
                color=color,
                axis_index=axis_index,
                entry_id=entry_id,
            )
        )

        self._recalc_axis_labels()
        self._auto_fit_ranges()
        self._invalidate_cache()
        self._notify("signals")

    def plotted_signal_keys(self) -> list[str]:
        """Return plotted signal keys in add order, without duplicates.

        Deduplicates using dict.fromkeys to preserve insertion order while
        removing duplicates. Used by the Export dialog for initial selection.
        """
        return list(dict.fromkeys(e.signal_key for e in self._plotted))

    def overwrite_axis(self, signal_key: str, axis_index: int) -> None:
        """Replace all signals on *axis_index* with *signal_key*.

        Existing plotted entries on that axis are dropped, then
        ``add_signal_to_axis`` re-adds the signal, auto-fits, and notifies.
        The axis label/unit need no explicit clear here: add_signal_to_axis's
        ``_recalc_axis_labels`` re-derives them from whatever entry is now
        the axis's oldest, so the new signal becomes the representative as a
        side effect (y_range reset is Task 4).
        ``add_signal_to_axis`` (the Ctrl-add path) is left completely unchanged.
        """
        self._plotted = [e for e in self._plotted if e.axis_index != axis_index]
        self.add_signal_to_axis(signal_key, axis_index)

    def create_new_axis(self, signal_key: str) -> None:
        """Add *signal_key* as a new vertical region.

        A fresh axis is appended for the signal, then :meth:`_compact_axes`
        prunes any empty axis (e.g. the initial placeholder) so the first signal
        fills the whole panel and subsequent signals split it into equal regions.
        """
        new_col = self._column_count - 1
        same_col = [a.top_ratio for a in self._axes if a.column == new_col]
        new_axis = YAxisVM(column=new_col)
        # Give the new axis a transient top_ratio that sorts it after all
        # existing axes in the same column so _relayout_columns places it at the
        # bottom (rule A: new axis appends below existing ones).
        new_axis.top_ratio = (max(same_col) + 1.0) if same_col else 0.0
        self._axes.append(new_axis)
        self.add_signal_to_axis(signal_key, len(self._axes) - 1)
        self._compact_axes()
        self._relayout_columns()
        self._notify("axes")

    def move_axis_to_column(
        self, axis_index: int, column: int, position: int | None = None
    ) -> None:
        """Move an axis to *column*, inserting at vertical *position* (0=top, None=bottom).

        Heights are **preserved, not equal-split**.  The destination column is
        re-stacked keeping each axis's height (scaled down only if the column
        would overflow — see :meth:`_layout_column_preserving`); the source
        column is left untouched, so the vacated band stays blank (mirroring
        removal).  A same-column move is therefore a pure reorder.  A stale drag
        index (e.g. axes changed mid-drag) is a no-op, not an ``IndexError``.
        """
        if not (0 <= axis_index < len(self._axes)):
            return
        column = max(0, min(column, self._column_count - 1))
        moved = self._axes[axis_index]
        moved.column = column
        others = sorted(
            [a for a in self._axes if a.column == column and a is not moved],
            key=lambda a: a.top_ratio,
        )
        if position is None or position >= len(others):
            insert_at = len(others)
        else:
            insert_at = max(0, position)
        ordered = [*others[:insert_at], moved, *others[insert_at:]]
        self._layout_column_preserving(ordered)
        self._notify("axes")

    def extract_axis(
        self, axis_index: int
    ) -> tuple[YAxisVM, list[_PlottedEntry]] | None:
        """Remove the axis at *axis_index* and its plotted signals from this panel.

        Returns the YAxisVM (carrying unit/name/y_range/height_ratio) and its
        _PlottedEntry list (signal_key/color/visible) so a sibling panel can
        re-create the axis verbatim. The vacated band stays blank (_compact_axes,
        mirroring removal). Stale index → None (no-op).
        """
        if not (0 <= axis_index < len(self._axes)):
            return None
        axis = self._axes[axis_index]
        entries = [e for e in self._plotted if e.axis_index == axis_index]
        self._plotted = [e for e in self._plotted if e.axis_index != axis_index]
        self._compact_axes()  # prune the now-signal-less moved axis, remap survivors
        # Break the alias: if _compact_axes kept the extracted axis as the empty-
        # panel placeholder, swap it for a fresh one so source and target own
        # distinct YAxisVM objects (else the target's relayout mutates the source
        # placeholder, and a later remove_signal on the empty source corrupts the
        # moved axis in the target).
        if self._axes and self._axes[0] is axis:
            placeholder = YAxisVM()
            placeholder.top_ratio, placeholder.height_ratio = 0.0, 1.0
            placeholder.column = self._column_count - 1
            self._axes = [placeholder]
        self._invalidate_cache()
        self._notify("axes")
        return axis, entries

    def insert_axis(
        self,
        axis: YAxisVM,
        entries: list[_PlottedEntry],
        column: int,
        position: int | None,
    ) -> None:
        """Insert a previously-extracted *axis* (with its *entries*) at *column*/*position*.

        The axis keeps its carried settings; signals keep their colors. The target
        column is re-stacked preserving heights (move_axis_to_column), so the moved
        axis lands at the requested vertical position.
        """
        new_index = len(self._axes)
        axis.column = max(0, min(column, self._column_count - 1))
        self._axes.append(axis)
        for e in entries:
            e.axis_index = new_index
            # Cross-panel move: entry_id is unique only within a VM, so the
            # source VM's id can collide with an existing id in this (dest) VM.
            # Renumber into this VM's id-space; color/axis settings are kept.
            e.entry_id = self._next_entry_id
            self._next_entry_id += 1
            self._plotted.append(e)
        # Drop the target's initial empty placeholder (mirrors create_new_axis), so
        # dropping onto a blank panel does not leave a phantom empty axis band.
        # _compact_axes is an identity remap when the target already has
        # signal-bearing axes, so this is safe for the non-empty-target case too.
        self._compact_axes()
        new_index = self._axes.index(axis)
        self.move_axis_to_column(
            new_index, axis.column, position
        )  # re-stack + notify "axes"
        self._invalidate_cache()
        self._notify("signals")

    def _compact_axes(self) -> None:
        """Prune signal-less axes and remap plotted entries to compacted indices.

        Survivors keep their existing top_ratio/height_ratio, so a removed axis
        leaves a blank band with no reflow — this *is* the layout behavior for
        removal. The add / column-count paths follow this with
        :meth:`_relayout_columns` to re-split equally; the move path instead
        uses :meth:`_layout_column_preserving`. When no signals remain,
        collapse to a single full-height placeholder in the inner (last) column.
        """
        used = sorted({e.axis_index for e in self._plotted})
        if not used:
            keep = self._axes[0] if self._axes else YAxisVM()
            keep.top_ratio, keep.height_ratio = 0.0, 1.0
            keep.column = self._column_count - 1
            self._axes = [keep]
            return
        remap = {old: new for new, old in enumerate(used)}
        self._axes = [self._axes[old] for old in used]
        for entry in self._plotted:
            entry.axis_index = remap[entry.axis_index]

    def _recalc_axis_labels(self) -> None:
        """全軸の name/unit を現存エントリから再導出する (Stage A 契約 §2.1-2).

        代表 = 軸上の最古 (追加順) エントリ。name/unit は常に代表信号の対 —
        増分更新 (name first-wins / unit last-wins) は別信号の捏造ペア (UX-01) を
        生むため全廃した。ラベルはオフセット非依存なので base の signal_map を
        使う (オフセット適用中の全チャンネル overlay 再構築を踏まない・spec §3.3)。
        O(axes x plotted) — プロット済みエントリ有界で無視できる。
        """
        sig_map = self._session.signal_map()
        for i, axis in enumerate(self._axes):
            rep = next((e for e in self._plotted if e.axis_index == i), None)
            if rep is None:
                axis.name = ""
                axis.unit = ""
                continue
            axis.name = rep.signal_key.split(KEY_SEPARATOR, 1)[-1]
            sig = sig_map.get(rep.signal_key)
            axis.unit = str(sig.metadata.get("unit", "")) if sig else ""

    def _relayout_columns(self) -> None:
        """Assign top_ratio/height_ratio per column, splitting height equally.

        Used by the add / column-count paths, where a fresh equal split is
        the intended layout. Removal does NOT call this — survivors keep their
        existing ratios and the removed band stays blank (see
        :meth:`remove_signal`).

        Axes are grouped by column; within each column the vertical order is taken
        from the pre-existing top_ratio, then each column's axes split the full
        column height equally.
        """
        col_groups: dict[int, list[YAxisVM]] = {}
        for axis in self._axes:
            col_groups.setdefault(axis.column, []).append(axis)
        for axes_in_col in col_groups.values():
            ordered = sorted(axes_in_col, key=lambda a: a.top_ratio)
            h = 1.0 / len(ordered)
            cursor = 0.0
            for axis in ordered:
                axis.top_ratio = cursor
                axis.height_ratio = h
                cursor += h

    def _layout_column_preserving(self, axes_in_order: list[YAxisVM]) -> None:
        """Lay out one column's axes top-to-bottom, preserving their heights.

        Stacks ``axes_in_order`` from the top using each axis's current
        ``height_ratio``.  Only when the heights sum to more than 1.0 (an axis
        was added to an already-full column) are they scaled down uniformly to
        fit — relative proportions are kept.  When they sum to less than 1.0 the
        remainder stays a blank band at the bottom.  Used by
        :meth:`move_axis_to_column`; the add / column-count paths use
        :meth:`_relayout_columns` (equal split).
        """
        total = sum(a.height_ratio for a in axes_in_order)
        if total > 1.0 + 1e-9:
            scale = 1.0 / total
            for axis in axes_in_order:
                axis.height_ratio *= scale
        cursor = 0.0
        for axis in axes_in_order:
            axis.top_ratio = cursor
            cursor += axis.height_ratio

    def remove_signal(self, signal_key: str) -> None:
        """Remove *signal_key* from the plot and reconcile axes.

        Survivors keep their absolute heights and positions: the removed axis is
        pruned from the layout and its band is left blank (no reflow). Only when
        the last signal is removed does the panel collapse to a full-height
        placeholder (handled by :meth:`_compact_axes`).
        """
        self._plotted = [e for e in self._plotted if e.signal_key != signal_key]
        self._compact_axes()
        self._recalc_axis_labels()
        self._invalidate_cache()
        self._notify("signals")

    def prune_missing_signals(self) -> None:
        """Drop plotted signals whose source group is no longer loaded.

        Filters by *group key* membership (O(#files)) instead of walking every
        Session signal — the latter forced a namespaced rebuild of all
        remaining signals on the first call after unload and re-scanned O(n)
        per panel, freezing the app on close at prod scale (FU-16). A
        signal_key ``{group_key}::{name}`` survives iff its group_key is still
        loaded; whole groups load/unload together so per-signal matching is
        unnecessary. Survivors keep heights/positions; removed bands stay blank.
        """
        live = set(self._session.group_keys())
        kept = [
            e for e in self._plotted if e.signal_key.split(KEY_SEPARATOR, 1)[0] in live
        ]
        if len(kept) == len(self._plotted):
            return
        self._plotted = kept
        self._compact_axes()
        self._recalc_axis_labels()
        self._invalidate_cache()
        self._notify("signals")

    def refresh(self) -> None:
        """Drop the render cache and re-emit so the view re-reads Session data.

        Called after a load completes: a signal added before its data existed
        cached an empty curve under an unchanged key; invalidating lets the now
        present data render (review finding ⑥).
        """
        self._invalidate_cache()
        self._notify("signals")

    def set_offsets(
        self, signal_offsets: dict[str, float], file_offsets: dict[str, float]
    ) -> None:
        """Store the current time offsets and invalidate the render cache (R14.5).

        Called by GraphAreaVM on every 'offsets' broadcast. The next render_data()
        applies them via Session.apply_offset. Cache invalidation (not a cache-key
        change) is what makes a new offset bust the stale curve — render_data's key
        intentionally omits offsets because they only change through this method.

        x_range is intentionally NOT touched: this method is broadcast to every
        panel on every apply (R14.5), so resetting the viewport here would discard
        each panel's zoom/pan state. The wiring layer (Task 3/GraphAreaVM) is
        responsible for any viewport adjustment after applying offsets.
        """
        self._signal_offsets = dict(signal_offsets)
        self._file_offsets = dict(file_offsets)
        self._invalidate_cache()

    def offset_for(self, signal_key: str) -> float:
        """Return the combined (signal + file) time offset applied to *signal_key*.

        Public getter over the private offset dicts set_offsets stores. Drives the
        curve menu's "オフセットをリセット…" enabled state and the "オフセット: +Xs"
        info row. Group key is the prefix before '::' (same convention as _signal_map).
        """
        group_key = signal_key.split("::", 1)[0]
        return self._file_offsets.get(group_key, 0.0) + self._signal_offsets.get(
            signal_key, 0.0
        )

    def toggle_visibility(self, signal_key: str) -> None:
        """Flip the visibility of *signal_key*."""
        for entry in self._plotted:
            if entry.signal_key == signal_key:
                entry.visible = not entry.visible
                break
        self._invalidate_cache()
        self._notify("signals")

    def toggle_entry_visibility(self, entry_id: int) -> None:
        """Flip the visibility of the entry with *entry_id* (entry-addressed)."""
        for e in self._plotted:
            if e.entry_id == entry_id:
                e.visible = not e.visible
                break
        self._invalidate_cache()
        self._notify("signals")

    def set_color(self, entry_id: int, color: str) -> None:
        """Set the colour of the entry with *entry_id* and bust the render cache.

        Colour is intentionally NOT part of _make_cache_key, so the cache must be
        invalidated here or render_data would return the stale-coloured curve.
        """
        for e in self._plotted:
            if e.entry_id == entry_id:
                e.color = color
                break
        self._invalidate_cache()
        self._notify("signals")

    def remove_entry(self, entry_id: int) -> None:
        """Remove the entry with *entry_id* and reconcile axes (entry-addressed).

        Mirrors remove_signal but targets one entry: survivors keep their
        heights, the vacated axis band stays blank, and the panel collapses to a
        placeholder only when the last entry is removed (via _compact_axes).
        """
        self._plotted = [e for e in self._plotted if e.entry_id != entry_id]
        self._compact_axes()
        self._recalc_axis_labels()
        self._invalidate_cache()
        self._notify("signals")

    def toggle_axis_visibility(self, axis_index: int) -> None:
        """Flip visibility of all entries on *axis_index* (H fallback, DP5).

        If any entry on the axis is visible, hide them all; otherwise show them
        all. No-op when the axis has no entries.
        """
        on_axis = [e for e in self._plotted if e.axis_index == axis_index]
        if not on_axis:
            return
        any_visible = any(e.visible for e in on_axis)
        for e in on_axis:
            e.visible = not any_visible
        self._invalidate_cache()
        self._notify("signals")

    # ─── Range management ────────────────────────────────────────────────────

    def set_x_range(self, lo: float, hi: float) -> None:
        """Set the horizontal view range and invalidate the render cache."""
        # X-sync fan-out re-applies the current range to the source panel and pushes
        # already-synced ranges to siblings. Skip the redundant re-render when the
        # range is unchanged (RN-04); a real change proceeds as before.
        if self.x_range == (lo, hi):
            return
        self.x_range = (lo, hi)
        self._x_range_is_auto = False  # RN-02: 手動ズーム/パン/同期由来は auto を外す
        self._invalidate_cache()
        self._notify("range")

    def set_y_range(self, lo: float, hi: float) -> None:
        """Set the vertical view range and invalidate the render cache."""
        self.y_range = (lo, hi)
        self._invalidate_cache()
        self._notify("range")

    def set_axis_range(self, axis_index: int, lo: float, hi: float) -> None:
        """Set the Y data range of one axis (active-axis zoom/pan target)."""
        if not (0 <= axis_index < len(self._axes)):
            return
        self._axes[axis_index].set_range(min(lo, hi), max(lo, hi))
        self._notify("axes")

    def zoom_axis(self, axis_index: int, factor: float) -> None:
        """Zoom one Y-axis around its center by *factor* (FU-09). No-op when the
        axis has no concrete range or the span is degenerate/non-finite."""
        if not (0 <= axis_index < len(self._axes)):
            return
        rng = self._axes[axis_index].y_range
        if rng is None:
            return
        scaled = _scaled_range(rng[0], rng[1], factor)
        if scaled is not None:
            self.set_axis_range(axis_index, scaled[0], scaled[1])

    def zoom_x(self, factor: float) -> None:
        """Zoom the X range around its center by *factor* (FU-09), via set_x_range
        so the existing X-sync fan-out applies. No-op when x_range is unset or the
        span is degenerate/non-finite."""
        if self.x_range is None:
            return
        scaled = _scaled_range(self.x_range[0], self.x_range[1], factor)
        if scaled is not None:
            self.set_x_range(scaled[0], scaled[1])

    def _fit_axis(self, axis: YAxisVM, lo: float | None, hi: float | None) -> None:
        """Store an auto-fit result on *axis*, widening a degenerate constant-signal
        span so its Y axis stays readable (RN-05). None lo/hi clears the range
        (nothing fittable), matching the prior set_range(None, None) behaviour.
        """
        if lo is not None and hi is not None:
            lo, hi = _padded_range(lo, hi)
        axis.set_range(lo, hi)

    def reset_axis_y(self, axis_index: int) -> None:
        """Fit one Y-axis to the visible values of the signals assigned to it.

        Single-axis version of reset_y (the axis-menu "この軸をオートフィット").
        Invisible entries are excluded and the fit uses the aligned (sorted,
        keep-last) view — the same window that is actually drawn. Clears to None
        when nothing is fittable so a later add_signal can auto-fit.
        """
        if not (0 <= axis_index < len(self._axes)):
            return
        sig_map = self._signal_map()
        lo: float | None = None
        hi: float | None = None
        for entry in self._plotted:
            if entry.axis_index != axis_index or not entry.visible:
                continue
            sig = sig_map.get(entry.signal_key)
            if sig is None or len(sig.values) == 0:
                continue
            vs = sig.sorted_view()[1]
            finite_vals = vs[np.isfinite(vs)]
            if len(finite_vals) == 0:
                continue
            v_lo = float(finite_vals.min())
            v_hi = float(finite_vals.max())
            lo = v_lo if lo is None else min(lo, v_lo)
            hi = v_hi if hi is None else max(hi, v_hi)
        self._fit_axis(self._axes[axis_index], lo, hi)
        self._invalidate_cache()
        self._notify("range")

    def remove_axis(self, axis_index: int) -> None:
        """Remove every entry on *axis_index* and reconcile axes (axis-menu 削除).

        Mirrors remove_entry but targets a whole axis: survivors keep their
        heights, the vacated band stays blank, and the panel collapses to a
        placeholder only when the last entry is removed (via _compact_axes).
        """
        if not (0 <= axis_index < len(self._axes)):
            return
        self._plotted = [e for e in self._plotted if e.axis_index != axis_index]
        self._compact_axes()
        self._recalc_axis_labels()
        self._invalidate_cache()
        self._notify("signals")

    def move_entry_to_new_axis(self, entry_id: int) -> None:
        """Re-assign the entry with *entry_id* to a fresh Y-axis (曲線「新しい軸へ移動」).

        Mirrors create_new_axis's layout bookkeeping but moves an existing entry
        instead of adding a signal: a new axis is appended in the inner column,
        the entry is re-pointed to it, then _compact_axes prunes the now-empty
        source axis (no empty axes are left behind) and _relayout_columns re-splits
        equally. _invalidate_cache is explicit here because the render cache-key
        omits axis_index (a stale-cache curve would keep drawing on the old axis).
        """
        entry = next((e for e in self._plotted if e.entry_id == entry_id), None)
        if entry is None:
            return
        new_col = self._column_count - 1
        same_col = [a.top_ratio for a in self._axes if a.column == new_col]
        new_axis = YAxisVM(column=new_col)
        new_axis.top_ratio = (max(same_col) + 1.0) if same_col else 0.0
        self._axes.append(new_axis)
        entry.axis_index = len(self._axes) - 1
        self._compact_axes()
        self._relayout_columns()
        self._invalidate_cache()
        self._notify("axes")

    def reset_x(self) -> None:
        """Fit x_range to the union of all plotted signals' time extents."""
        lo: float | None = None
        hi: float | None = None
        sig_map = self._signal_map()
        for entry in self._plotted:
            sig = sig_map.get(entry.signal_key)
            if sig is None or len(sig.timestamps) == 0:
                continue
            s_ts = sig.sorted_view()[0]
            ts0 = float(s_ts[0])
            tsN = float(s_ts[-1])
            lo = ts0 if lo is None else min(lo, ts0)
            hi = tsN if hi is None else max(hi, tsN)
        # Clear to None when nothing is fittable so a later add_signal can
        # auto-fit instead of being clipped to a stale window.
        self.x_range = (lo, hi) if lo is not None and hi is not None else None
        self._x_range_is_auto = True  # RN-02: 明示リセットで自動フィットへ復帰
        self._invalidate_cache()
        self._notify("range")

    def reset_y(self) -> None:
        """Fit all Y-axes to visible values of signals assigned to them."""
        sig_map = self._signal_map()

        # Build list of signals per axis
        axis_to_sigs: dict[int, list[str]] = {}
        for entry in self._plotted:
            if not entry.visible:
                continue
            axis_to_sigs.setdefault(entry.axis_index, []).append(entry.signal_key)

        for i, axis in enumerate(self._axes):
            lo: float | None = None
            hi: float | None = None
            for sig_key in axis_to_sigs.get(i, []):
                sig = sig_map.get(sig_key)
                if sig is None or len(sig.values) == 0:
                    continue
                # Fit on the aligned (sorted, keep-last) view — this is what
                # actually gets drawn. Raw sig.values still holds duplicate-ts
                # samples that keep-last discards; letting those leak in would
                # stretch y_range past what's ever visible on screen.
                vs = sig.sorted_view()[1]
                finite_vals = vs[np.isfinite(vs)]
                if len(finite_vals) == 0:
                    continue
                v_lo = float(finite_vals.min())
                v_hi = float(finite_vals.max())
                lo = v_lo if lo is None else min(lo, v_lo)
                hi = v_hi if hi is None else max(hi, v_hi)

            # Clear to None when nothing is fittable so a later add_signal can
            # auto-fit instead of being clipped to a stale window.
            self._fit_axis(axis, lo, hi)

        self._invalidate_cache()
        self._notify("range")

    def set_panel_width(self, px: int) -> None:
        """Update the panel pixel width; invalidates the render cache.

        Height-only resizes re-call this with an unchanged width. LOD depends on
        panel_width_px (part of the render cache key), never on height, so
        re-fitting then is pure waste -- bail out unless the pixel budget
        actually changed (RN-03).
        """
        if px == self.panel_width_px:
            return
        self.panel_width_px = px
        self._invalidate_cache()
        self._notify("range")

    # ─── LOD render pipeline ──────────────────────────────────────────────────

    def render_data(self) -> list[RenderCurve]:
        """Return one RenderCurve per VISIBLE plotted signal, LOD-reduced.

        The result is cached by (x_lo, x_hi, panel_width_px, visible_keys).
        Repeated calls with unchanged state return the cached list instantly.
        """
        cache_key = self._make_cache_key()
        if cache_key in self._cache:
            return self._cache[cache_key]

        sig_map = self._signal_map()
        n_target = max(2, 2 * self.panel_width_px)

        curves: list[RenderCurve] = []
        total_points = 0
        any_downsampled = False

        for entry in self._plotted:
            if not entry.visible:
                continue

            sig = sig_map.get(entry.signal_key)
            if sig is None:
                # Signal not found in session: yield empty legend entry
                curves.append(
                    RenderCurve(
                        name=entry.signal_key,
                        color=entry.color,
                        timestamps=np.empty(0, dtype=np.float64),
                        values=np.empty(0, dtype=np.float64),
                        axis_index=entry.axis_index,
                        entry_id=entry.entry_id,
                    )
                )
                continue

            ts, vs = sig.sorted_view()

            # Determine visible x-window
            if self.x_range is not None:
                x_lo, x_hi = self.x_range
            else:
                if len(ts) == 0:
                    x_lo, x_hi = 0.0, 0.0
                else:
                    x_lo = float(ts[0])
                    x_hi = float(ts[-1])

            # Slice to visible window using searchsorted on monotonic timestamps.
            # RN-01: 窓外の隣接サンプルを左右1点ずつ含め、窓内にサンプルが無くても
            # 窓を横切る線分が描けるようにする (疎信号のズーム消失を防ぐ)。
            lo_idx = int(np.searchsorted(ts, x_lo, side="left"))
            hi_idx = int(np.searchsorted(ts, x_hi, side="right"))
            lo_ext = max(0, lo_idx - 1)
            hi_ext = min(len(ts), hi_idx + 1)
            ts_slice = ts[lo_ext:hi_ext]
            vs_slice = vs[lo_ext:hi_ext]

            if len(ts_slice) == 0:
                # Empty slice — legend entry still included
                curves.append(
                    RenderCurve(
                        name=entry.signal_key,
                        color=entry.color,
                        timestamps=np.empty(0, dtype=np.float64),
                        values=np.empty(0, dtype=np.float64),
                        axis_index=entry.axis_index,
                        entry_id=entry.entry_id,
                    )
                )
                continue

            if len(ts_slice) <= n_target:
                # No downsampling needed
                out_ts = ts_slice
                out_vs = vs_slice
            else:
                # Build a sliced Signal and delegate to Session.downsample.
                # Signal.__post_init__ copies non-writeable arrays automatically,
                # so passing read-only views from the parent is safe.
                sliced_sig = Signal(
                    name=sig.name,
                    timestamps=ts_slice,
                    values=vs_slice,
                    file_format=sig.file_format,
                    bus_type=sig.bus_type,
                    source_file=sig.source_file,
                    metadata=sig.metadata,
                )
                reduced = self._session.downsample(sliced_sig, n_target)
                out_ts = reduced.timestamps
                out_vs = reduced.values
                any_downsampled = True

            total_points += len(out_ts)
            curves.append(
                RenderCurve(
                    name=entry.signal_key,
                    color=entry.color,
                    timestamps=out_ts,
                    values=out_vs,
                    axis_index=entry.axis_index,
                    entry_id=entry.entry_id,
                )
            )

        # Update aggregate state
        self.last_rendered_points = total_points
        self.lod_active = any_downsampled

        self._cache[cache_key] = curves
        return curves

    def resize_axis_edge(self, axis_index: int, edge: str, delta_ratio: float) -> None:
        """Resize a single axis by dragging one edge (model B).

        Only the dragged edge moves: the axis's opposite edge is anchored and the
        neighbour is never pushed. Other axes are untouched; the adjacent gap on the
        dragged side absorbs the change. ``delta_ratio`` is positive downward.
        Constraints: min height 5%, don't pass the neighbour, don't move the opposite edge.
        """
        if not (0 <= axis_index < len(self._axes)):
            return
        axis = self._axes[axis_index]
        col_axes = sorted(
            (a for a in self._axes if a.column == axis.column),
            key=lambda a: a.top_ratio,
        )
        rank = next(i for i, a in enumerate(col_axes) if a is axis)

        if edge == "bottom":
            # bottom = top + height moves; top fixed. New bottom limited by next.top or 1.0.
            lower_bound = (
                col_axes[rank + 1].top_ratio if rank + 1 < len(col_axes) else 1.0
            )
            new_bottom = axis.top_ratio + axis.height_ratio + delta_ratio
            new_bottom = min(new_bottom, lower_bound)  # don't push neighbour
            new_bottom = max(
                new_bottom, axis.top_ratio + MIN_H
            )  # min height (top fixed)
            axis.height_ratio = new_bottom - axis.top_ratio
        elif edge == "top":
            # top moves; bottom = top + height fixed. New top limited by prev.bottom or 0.0.
            upper = col_axes[rank - 1] if rank - 1 >= 0 else None
            upper_bound = (upper.top_ratio + upper.height_ratio) if upper else 0.0
            bottom = axis.top_ratio + axis.height_ratio
            new_top = axis.top_ratio + delta_ratio
            new_top = max(new_top, upper_bound)  # don't push neighbour
            new_top = min(new_top, bottom - MIN_H)  # min height (bottom fixed)
            axis.top_ratio = new_top
            axis.height_ratio = bottom - new_top
        else:
            return

        self._notify("axes")

    # ─── Global cursor (R15) ─────────────────────────────────────────────────

    def set_cursor(self, t: float | None) -> None:
        """Set the global (A) cursor time and notify.

        Clearing A (t=None) also clears the Delta cursor: B is meaningless
        without A (the invariant also fires when a sibling broadcast clears A).
        """
        self.cursor_t = t
        if t is None:
            self.delta_enabled = False
            self.cursor_t_b = None
        self._notify("cursor")

    def set_interp_method(self, method: InterpolationMethod) -> None:
        """Set the interpolation method used for cursor readings and notify."""
        self.interp_method = method
        self._notify("cursor")

    def cursor_readings(self) -> list[CursorReading]:
        """Interpolated value of each visible signal at cursor_t (Session-delegated).

        Returns [] when no cursor is set.  value=None / in_range=False when the
        cursor falls outside a signal's timestamp range (R15.5).
        """
        if self.cursor_t is None:
            return []
        sig_map = self._signal_map()
        out: list[CursorReading] = []
        for entry in self._plotted:
            if not entry.visible:
                continue
            sig = sig_map.get(entry.signal_key)
            if sig is None:
                out.append(
                    CursorReading(
                        entry.signal_key,
                        entry.color,
                        None,
                        False,
                        entry_id=entry.entry_id,
                    )
                )
                continue
            unit = sig.metadata.get("unit", "") if sig.metadata else ""
            val = self._session.interpolate(sig, self.cursor_t, self.interp_method)
            _fts, _fvals = sig.finite_view()
            r_lo = float(_fvals.min()) if _fvals.size else None
            r_hi = float(_fvals.max()) if _fvals.size else None
            out.append(
                CursorReading(
                    entry.signal_key,
                    entry.color,
                    val,
                    val is not None,
                    label=_resolve_value_label(sig, val),
                    unit=unit,
                    entry_id=entry.entry_id,
                    range_lo=r_lo,
                    range_hi=r_hi,
                )
            )
        return out

    # ─── Delta cursor + range stats (R16/R17) ────────────────────────────────

    def _default_cursor_x(self, frac: float) -> float:
        """Data-x at *frac* of the visible x-range (0.5=centre, 0.75=right-ish)."""
        if self.x_range is None:
            return 0.0
        lo, hi = self.x_range
        return lo + frac * (hi - lo)

    def toggle_main_cursor(self, on: bool) -> None:
        """Show A at the visible-width 50% (on) or clear A and Delta (off)."""
        self.set_cursor(self._default_cursor_x(0.5) if on else None)

    def toggle_delta(self, on: bool) -> None:
        """Show B at 75% (on) or remove it (off).  No-op when A is not set."""
        if on:
            if self.cursor_t is None:
                return  # B requires A (View greys this out; VM guards too)
            self.delta_enabled = True
            self.cursor_t_b = self._default_cursor_x(0.75)
        else:
            self.delta_enabled = False
            self.cursor_t_b = None
        self._notify("delta")

    def set_cursor_b(self, t: float) -> None:
        """Move the Delta (B) cursor and notify (local — not broadcast)."""
        self.cursor_t_b = t
        self._notify("delta")

    def _reference_timestamps(
        self, reference_entry_id: int | None
    ) -> np.ndarray | None:
        """Displayed (offset-applied), sorted timestamps of the reference signal.

        Resolves *reference_entry_id* to its signal_key, honouring it only when
        that entry is currently visible; otherwise (None / absent / hidden) falls
        back to the first visible entry. Returns None when no visible signal is
        available. Uses sorted_view (all recorded samples, offset applied) so the
        snap targets exactly what is drawn.
        """
        key: str | None = None
        if reference_entry_id is not None:
            visible = any(
                e.entry_id == reference_entry_id and e.visible for e in self._plotted
            )
            if visible:
                key = self.signal_key_for_entry(reference_entry_id)
        if key is None:
            for e in self._plotted:
                if e.visible:
                    key = e.signal_key
                    break
        if key is None:
            return None
        sig = self._signal_map().get(key)
        if sig is None or len(sig.timestamps) == 0:
            return None
        return sig.sorted_view()[0]

    def step_cursor(
        self, which: str, direction: int, reference_entry_id: int | None = None
    ) -> None:
        """Move the A or B cursor to the reference signal's adjacent sample time.

        *which* is "A" or "B"; *direction* is +1 (right) or -1 (left). The cursor
        snaps to the neighbouring recorded timestamp of the reference signal on
        the DISPLAYED time axis (offsets applied), so arrow-key stepping lands
        exactly on samples. Clamps at the first/last sample. No-op when the
        relevant cursor is unset or no visible reference signal exists.
        """
        if which == "A":
            current = self.cursor_t
        elif which == "B":
            current = self.cursor_t_b if self.delta_enabled else None
        else:
            return
        if current is None:
            return
        ts = self._reference_timestamps(reference_entry_id)
        if ts is None or len(ts) == 0:
            return
        if direction > 0:
            idx = int(np.searchsorted(ts, current, side="right"))
            target = ts[idx] if idx < len(ts) else ts[-1]
        else:
            idx = int(np.searchsorted(ts, current, side="left")) - 1
            target = ts[idx] if idx >= 0 else ts[0]
        target_f = float(target)
        if which == "A":
            self.set_cursor(target_f)
        else:
            self.set_cursor_b(target_f)

    def set_visible_stats(self, cols: set[str]) -> None:
        """Update visible stat columns and notify 'delta' so the view re-renders.

        Implements the spec §7 requirement: stat column selection is VM state,
        not view state — CursorReadout reads this via GraphPanelView on each sync.
        """
        self.visible_stat_cols = set(cols)
        self._notify("delta")

    def set_value_precision(self, p: int) -> None:
        """Set the displayed value/stat precision and notify so the readout re-renders."""
        self.value_precision = p
        self._notify("cursor")

    def toggle_grid(self, on: bool) -> None:
        """Toggle the per-panel X-direction grid and notify the view to re-apply."""
        self.grid_enabled = on
        self._notify("grid")

    @property
    def delta_t(self) -> float | None:
        """Signed Δt = tB - tA (None unless both cursors are set)."""
        if self.cursor_t is None or self.cursor_t_b is None:
            return None
        return self.cursor_t_b - self.cursor_t

    def delta_readings(self) -> list[DeltaReading]:
        """Per-signal A値・Δy・range stats over [A,B] (Session-delegated).

        Returns [] unless Delta is enabled.  Stats use min/max(A,B) so a B<A
        drag never raises (compute_statistics rejects t_start>t_end).
        """
        if not self.delta_enabled or self.cursor_t is None or self.cursor_t_b is None:
            return []
        a, b = self.cursor_t, self.cursor_t_b
        lo, hi = (a, b) if a <= b else (b, a)
        sig_map = self._signal_map()
        out: list[DeltaReading] = []
        for entry in self._plotted:
            if not entry.visible:
                continue
            sig = sig_map.get(entry.signal_key)
            if sig is None:
                out.append(
                    DeltaReading(
                        entry.signal_key,
                        entry.color,
                        None,
                        None,
                        StatisticsResult(
                            mean=float("nan"),
                            max=float("nan"),
                            min=float("nan"),
                            std=float("nan"),
                            count=0,
                        ),
                        False,
                        entry_id=entry.entry_id,
                    )
                )
                continue
            unit = sig.metadata.get("unit", "") if sig.metadata else ""
            va = self._session.interpolate(sig, a, self.interp_method)
            vb = self._session.interpolate(sig, b, self.interp_method)
            dy = (vb - va) if (va is not None and vb is not None) else None
            stats = self._session.compute_statistics(sig, lo, hi)
            out.append(
                DeltaReading(
                    entry.signal_key,
                    entry.color,
                    va,
                    dy,
                    stats,
                    va is not None,
                    label=_resolve_value_label(sig, va),
                    unit=unit,
                    entry_id=entry.entry_id,
                )
            )
        return out

    def signal_key_for_entry(self, entry_id: int) -> str | None:
        """Return the signal_key of the entry with *entry_id* (None if absent)."""
        for e in self._plotted:
            if e.entry_id == entry_id:
                return e.signal_key
        return None

    def axis_of_entry(self, entry_id: int) -> int | None:
        """Return the axis_index of the entry with *entry_id* (None if absent)."""
        for e in self._plotted:
            if e.entry_id == entry_id:
                return e.axis_index
        return None

    def entries_on_axis(self, axis_index: int) -> list[tuple[int, str, str, bool]]:
        """Return (entry_id, signal_key, color, visible) for every entry on *axis_index*.

        Drives the axis-menu curve list (checkable, includes hidden entries).
        signal_key doubles as the display label. Pure read — no notify.
        """
        return [
            (e.entry_id, e.signal_key, e.color, e.visible)
            for e in self._plotted
            if e.axis_index == axis_index
        ]

    # ─── Introspection ────────────────────────────────────────────────────────

    def inspect(self) -> dict[str, Any]:
        """Return a structured snapshot of ViewModel state.

        Suitable for headless test assertions and AI-agent introspection.
        """
        return {
            "plotted_signals": [
                {
                    "signal_key": e.signal_key,
                    "color": e.color,
                    "visible": e.visible,
                    "axis_index": e.axis_index,
                    "entry_id": e.entry_id,
                }
                for e in self._plotted
            ],
            "x_range": self.x_range,
            "y_range": self.y_range,
            "axes": [
                {
                    "range": ax.y_range,
                    "top_ratio": ax.top_ratio,
                    "height_ratio": ax.height_ratio,
                    "column": ax.column,
                    "unit": ax.unit,
                }
                for ax in self._axes
            ],
            "column_count": self._column_count,
            "panel_width_px": self.panel_width_px,
            "lod_active": self.lod_active,
            "last_rendered_points": self.last_rendered_points,
        }

    # ─── Private helpers ──────────────────────────────────────────────────────

    def _signal_map(self) -> Mapping[str, Signal]:
        """Return {signal.name: signal} with stored time offsets applied (R14).

        Fast path (no offsets, the norm): return the Session's cached read-only
        map unchanged — no per-call rebuild of the 264k-entry map (FU-08). Only
        when an offset is set do we shallow-overlay the affected signals via the
        pure Session.apply_offset; a zero total leaves the base wrapper in place.
        Group key is the prefix before '::' (same convention as Session).
        """
        base = self._session.signal_map()
        if not self._file_offsets and not self._signal_offsets:
            return base
        result: dict[str, Signal] = {}
        for name, sig in base.items():
            group_key = name.split("::", 1)[0]
            file_off = self._file_offsets.get(group_key, 0.0)
            sig_off = self._signal_offsets.get(name, 0.0)
            if file_off or sig_off:
                result[name] = self._session.apply_offset(
                    sig, file_offset=file_off, signal_offset=sig_off
                )
            else:
                result[name] = sig
        return result

    def _auto_fit_ranges(self) -> None:
        """Fit x_range and y_range to all plotted signals if not yet set.

        Called after add_signal; only updates ranges that are still None to
        preserve any manually-set range.
        """
        sig_map = self._signal_map()

        # RN-02: None のときだけでなく auto のとき常に全信号の和集合へフィット。
        # 初回オートフィット後も auto のままなら、別時間域の追加信号で範囲が広がり
        # 窓外の無表示を防ぐ。手動ズーム後 (auto=False) は尊重して触らない。
        if self._x_range_is_auto:
            x_lo: float | None = None
            x_hi: float | None = None
            for entry in self._plotted:
                sig = sig_map.get(entry.signal_key)
                if sig is None or len(sig.timestamps) == 0:
                    continue
                s_ts = sig.sorted_view()[0]
                ts0 = float(s_ts[0])
                tsN = float(s_ts[-1])
                x_lo = ts0 if x_lo is None else min(x_lo, ts0)
                x_hi = tsN if x_hi is None else max(x_hi, tsN)
            if x_lo is not None and x_hi is not None:
                self.x_range = (x_lo, x_hi)

        # Build list of signals per axis
        axis_to_sigs: dict[int, list[str]] = {}
        for entry in self._plotted:
            axis_to_sigs.setdefault(entry.axis_index, []).append(entry.signal_key)

        for i, axis in enumerate(self._axes):
            if axis.y_range is None:
                lo: float | None = None
                hi: float | None = None
                for sig_key in axis_to_sigs.get(i, []):
                    sig = sig_map.get(sig_key)
                    if sig is None or len(sig.values) == 0:
                        continue
                    # See reset_y: fit on the aligned view, not raw duplicate-ts
                    # values that keep-last discards before rendering.
                    vs = sig.sorted_view()[1]
                    finite_vals = vs[np.isfinite(vs)]
                    if len(finite_vals) == 0:
                        continue
                    v_lo = float(finite_vals.min())
                    v_hi = float(finite_vals.max())
                    lo = v_lo if lo is None else min(lo, v_lo)
                    hi = v_hi if hi is None else max(hi, v_hi)

                self._fit_axis(axis, lo, hi)

    def _make_cache_key(self) -> tuple[Any, ...]:
        """Build a hashable cache key capturing all inputs that affect the render."""
        visible_keys = tuple(e.signal_key for e in self._plotted if e.visible)
        if self.x_range is not None:
            x_lo_r = round(self.x_range[0], _CACHE_KEY_DECIMALS)
            x_hi_r = round(self.x_range[1], _CACHE_KEY_DECIMALS)
        else:
            x_lo_r = None
            x_hi_r = None
        return (x_lo_r, x_hi_r, self.panel_width_px, visible_keys)

    def _invalidate_cache(self) -> None:
        """Clear the render cache so the next render_data call recomputes."""
        self._cache.clear()
