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

from dataclasses import dataclass
from typing import Any

import numpy as np

from valisync.core.models import Signal
from valisync.core.session import Session
from valisync.gui.viewmodels.observable import Observable
from valisync.gui.viewmodels.y_axis_vm import YAxisVM

# Matplotlib tab10 palette — 10 visually distinct colours.
_PALETTE: tuple[str, ...] = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)

# Number of decimal places used when building the cache key from x-range floats.
# 9 decimal places = ~1 ns precision on seconds timestamps, more than sufficient.
_CACHE_KEY_DECIMALS: int = 9

# Minimum height ratio for a single axis (5%)
MIN_H: float = 0.05


@dataclass
class RenderCurve:
    """Immutable rendering payload for one signal curve.

    Passed directly to the Qt layer for painting — no Session or Signal objects
    cross this boundary, which keeps the View layer thin.
    """

    name: str  # namespaced signal key, e.g. "csv_1::speed"
    color: str  # hex colour, e.g. "#1f77b4"
    timestamps: np.ndarray  # float64, already LOD-reduced if applicable
    values: np.ndarray  # float64, same length as timestamps
    axis_index: int = 0  # Added for multi-axis support


@dataclass
class _PlottedEntry:
    """Internal record for one plotted signal."""

    signal_key: str
    color: str
    visible: bool = True
    axis_index: int = 0


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
        self.x_range: tuple[float, float] | None = None
        self._column_count: int = 2
        self._axes: list[YAxisVM] = [YAxisVM(column=self._column_count - 1)]
        self.panel_width_px: int = 800
        self.lod_active: bool = False
        self.last_rendered_points: int = 0
        # Cache: maps cache-key → list[RenderCurve]
        self._cache: dict[tuple[Any, ...], list[RenderCurve]] = {}

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
        color = _PALETTE[len(self._plotted) % len(_PALETTE)]
        self._plotted.append(
            _PlottedEntry(signal_key=signal_key, color=color, axis_index=axis_index)
        )

        # Propagate unit + representative name from signal to axis.
        sig = self._signal_map().get(signal_key)
        if sig and 0 <= axis_index < len(self._axes):
            axis = self._axes[axis_index]
            unit = sig.metadata.get("unit", "")
            if unit:
                axis.unit = unit
            # The first signal added to an axis is its representative label;
            # later joined signals do not replace it (first-wins).
            if not axis.name:
                axis.name = signal_key.split("::")[-1]

        self._auto_fit_ranges()
        self._invalidate_cache()
        self._notify("signals")

    def overwrite_axis(self, signal_key: str, axis_index: int) -> None:
        """Replace all signals on *axis_index* with *signal_key*.

        Existing plotted entries on that axis are dropped, the axis label/unit
        are cleared so the new signal becomes the representative, then
        ``add_signal_to_axis`` re-adds the signal, auto-fits, and notifies.
        ``add_signal_to_axis`` (the Ctrl-add path) is left completely unchanged.
        """
        self._plotted = [e for e in self._plotted if e.axis_index != axis_index]
        if 0 <= axis_index < len(self._axes):
            self._axes[axis_index].name = ""
            self._axes[axis_index].unit = ""
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
        self._invalidate_cache()
        self._notify("signals")

    def prune_missing_signals(self) -> None:
        """Drop plotted signals no longer present in the Session, reconcile axes.

        Keyed on the Session (not on any specific unloaded key), so it is correct
        regardless of why a signal disappeared.  ``render_data`` already skips
        absent signals; this clears the lingering bookkeeping and prunes empty
        axes. Survivors keep their heights/positions; removed bands stay blank.
        """
        present = {s.name for s in self._session.signals()}
        kept = [e for e in self._plotted if e.signal_key in present]
        if len(kept) == len(self._plotted):
            return
        self._plotted = kept
        self._compact_axes()
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

    def toggle_visibility(self, signal_key: str) -> None:
        """Flip the visibility of *signal_key*."""
        for entry in self._plotted:
            if entry.signal_key == signal_key:
                entry.visible = not entry.visible
                break
        self._invalidate_cache()
        self._notify("signals")

    # ─── Range management ────────────────────────────────────────────────────

    def set_x_range(self, lo: float, hi: float) -> None:
        """Set the horizontal view range and invalidate the render cache."""
        self.x_range = (lo, hi)
        self._invalidate_cache()
        self._notify("range")

    def set_y_range(self, lo: float, hi: float) -> None:
        """Set the vertical view range and invalidate the render cache."""
        self.y_range = (lo, hi)
        self._invalidate_cache()
        self._notify("range")

    def reset_x(self) -> None:
        """Fit x_range to the union of all plotted signals' time extents."""
        lo: float | None = None
        hi: float | None = None
        sig_map = self._signal_map()
        for entry in self._plotted:
            sig = sig_map.get(entry.signal_key)
            if sig is None or len(sig.timestamps) == 0:
                continue
            ts0 = float(sig.timestamps[0])
            tsN = float(sig.timestamps[-1])
            lo = ts0 if lo is None else min(lo, ts0)
            hi = tsN if hi is None else max(hi, tsN)
        # Clear to None when nothing is fittable so a later add_signal can
        # auto-fit instead of being clipped to a stale window.
        self.x_range = (lo, hi) if lo is not None and hi is not None else None
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
                finite_vals = sig.values[np.isfinite(sig.values)]
                if len(finite_vals) == 0:
                    continue
                v_lo = float(finite_vals.min())
                v_hi = float(finite_vals.max())
                lo = v_lo if lo is None else min(lo, v_lo)
                hi = v_hi if hi is None else max(hi, v_hi)

            # Clear to None when nothing is fittable so a later add_signal can
            # auto-fit instead of being clipped to a stale window.
            axis.set_range(lo, hi)

        self._invalidate_cache()
        self._notify("range")

    def set_panel_width(self, px: int) -> None:
        """Update the panel pixel width; invalidates the render cache."""
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
                    )
                )
                continue

            ts = sig.timestamps
            vs = sig.values

            # Determine visible x-window
            if self.x_range is not None:
                x_lo, x_hi = self.x_range
            else:
                if len(ts) == 0:
                    x_lo, x_hi = 0.0, 0.0
                else:
                    x_lo = float(ts[0])
                    x_hi = float(ts[-1])

            # Slice to visible window using searchsorted on monotonic timestamps
            lo_idx = int(np.searchsorted(ts, x_lo, side="left"))
            hi_idx = int(np.searchsorted(ts, x_hi, side="right"))
            ts_slice = ts[lo_idx:hi_idx]
            vs_slice = vs[lo_idx:hi_idx]

            if len(ts_slice) == 0:
                # Empty slice — legend entry still included
                curves.append(
                    RenderCurve(
                        name=entry.signal_key,
                        color=entry.color,
                        timestamps=np.empty(0, dtype=np.float64),
                        values=np.empty(0, dtype=np.float64),
                        axis_index=entry.axis_index,
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
                )
            )

        # Update aggregate state
        self.last_rendered_points = total_points
        self.lod_active = any_downsampled

        self._cache[cache_key] = curves
        return curves

    def resize_axis(
        self, divider_index: int, delta_ratio: float, column: int | None = None
    ) -> None:
        """Resize two vertically-adjacent axes by moving the divider between them.

        delta_ratio is positive for moving the divider down.

        When *column* is given, the divider is scoped to that column and the two
        affected axes are the vertically-adjacent pair (ordered by ``top_ratio``)
        at ranks ``divider_index`` / ``divider_index + 1`` — correct even when
        VM-index order diverges from vertical order (after ``move_axis_to_column``).
        When *column* is None (legacy callers), ``divider_index`` indexes the
        VM-index-adjacent pair instead.
        """
        if column is None:
            # Legacy: VM-index-adjacent pair (kept for existing callers/tests).
            if divider_index < 0 or divider_index >= len(self._axes) - 1:
                return
            above = self._axes[divider_index]
            below = self._axes[divider_index + 1]
        else:
            col_axes = sorted(
                [a for a in self._axes if a.column == column],
                key=lambda a: a.top_ratio,
            )
            if divider_index < 0 or divider_index >= len(col_axes) - 1:
                return
            above = col_axes[divider_index]
            below = col_axes[divider_index + 1]

        # Ensure minimum height (e.g., 5%)
        min_h = 0.05
        if above.height_ratio + delta_ratio < min_h:
            delta_ratio = min_h - above.height_ratio
        if below.height_ratio - delta_ratio < min_h:
            delta_ratio = below.height_ratio - min_h

        above.height_ratio += delta_ratio
        below.top_ratio += delta_ratio
        below.height_ratio -= delta_ratio

        self._notify("axes")

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
        rank = col_axes.index(axis)

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

    def _signal_map(self) -> dict[str, Signal]:
        """Return {signal.name: signal} for every signal in the Session."""
        return {s.name: s for s in self._session.signals()}

    def _auto_fit_ranges(self) -> None:
        """Fit x_range and y_range to all plotted signals if not yet set.

        Called after add_signal; only updates ranges that are still None to
        preserve any manually-set range.
        """
        sig_map = self._signal_map()

        if self.x_range is None:
            x_lo: float | None = None
            x_hi: float | None = None
            for entry in self._plotted:
                sig = sig_map.get(entry.signal_key)
                if sig is None or len(sig.timestamps) == 0:
                    continue
                ts0 = float(sig.timestamps[0])
                tsN = float(sig.timestamps[-1])
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
                    finite_vals = sig.values[np.isfinite(sig.values)]
                    if len(finite_vals) == 0:
                        continue
                    v_lo = float(finite_vals.min())
                    v_hi = float(finite_vals.max())
                    lo = v_lo if lo is None else min(lo, v_lo)
                    hi = v_hi if hi is None else max(hi, v_hi)

                if lo is not None and hi is not None:
                    axis.set_range(lo, hi)

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
