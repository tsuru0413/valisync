"""Graph_Panel view — pyqtgraph waveform projection of GraphPanelVM.

Task 8.2: project ``vm.render_data()`` (LOD-reduced by the VM) onto one
``PlotDataItem`` per curve, with colours and a legend; accept signal drops;
report pixel width on resize.

Task 8.3: custom X/Y zoom/pan built on inner/outer axis zones.  The interaction
logic is split into pure, headless-testable pieces (zone classification, range
math) and thin Qt event handlers.  The VM is the single source of truth for the
visible range; every gesture calls ``set_x_range``/``set_y_range``/``reset_*``
and the resulting notify re-projects the plot.  pyqtgraph's own mouse handling
is disabled so the zone model fully owns interaction.

Zoom/pan are applied once per gesture (range-select/pan on release, wheel per
notch), so the 16 ms budget is met by the VM's render cache + bounded point
count.  Live drag-preview with a debounce timer is a noted refinement (R9.5).
"""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsRectItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.adapters.qt_signal_models import (
    AXIS_INDEX_MIME,
    SIGNAL_KEYS_MIME,
    decode_axis_index,
    decode_signal_keys,
    encode_axis_index,
)
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.region_divider_item import RegionDividerItem

# ─── Axis interaction zones (R9.1 / R10.1) ────────────────────────────────────

ZONE_PLOT = "plot"
ZONE_X_INNER = "x_inner"
ZONE_X_OUTER = "x_outer"
ZONE_Y_INNER = "y_inner"
ZONE_Y_OUTER = "y_outer"
ZONE_NONE = "none"

# Fixed pixel width shared by every stacked Y-axis so their tick spines (and
# right-aligned tick numbers) line up into one vertical edge. Sized for ~6-digit
# / scientific labels (e.g. "-1.2e+06" ≈ 48px) plus tick marks and the unit
# label. Fixed — not data-dependent — so the layout never shifts when the
# displayed signals change. Larger magnitudes stay within it via pyqtgraph's
# automatic SI-prefix / scientific tick formatting.
_Y_AXIS_FIXED_WIDTH = 72

# Wheel zoom factors (factor < 1 zooms in, keeping the cursor fixed).
_WHEEL_IN = 0.8
_WHEEL_OUT = 1.25


# ─── Pure interaction helpers (headless-testable) ─────────────────────────────


def ordered_pair(a: float, b: float) -> tuple[float, float]:
    """Return (a, b) sorted ascending — a range from two drag endpoints."""
    return (a, b) if a <= b else (b, a)


def zoom_range(
    lo: float, hi: float, center: float, factor: float
) -> tuple[float, float]:
    """Scale [lo, hi] about *center* by *factor* (factor < 1 zooms in)."""
    return (center + (lo - center) * factor, center + (hi - center) * factor)


def pan_range(lo: float, hi: float, delta: float) -> tuple[float, float]:
    """Shift [lo, hi] by *delta*."""
    return (lo + delta, hi + delta)


def classify_zone(
    px: float,
    py: float,
    plot_rect: QRectF,
    width: float,
    height: float,
    inner_frac: float = 0.5,
) -> str:
    """Classify a widget-space point into a plot/axis zone.

    The X-axis strip below the plot and the Y-axis strip left of it are each
    split into an *inner* half (closer to the plot) and an *outer* half (closer
    to the window edge).  Inner = range-select zoom; outer = pan.
    """
    left, right = plot_rect.left(), plot_rect.right()
    top, bottom = plot_rect.top(), plot_rect.bottom()

    if left <= px <= right and top <= py <= bottom:
        return ZONE_PLOT

    # X-axis strip (below the plot): inner is the top half (next to the plot).
    if py > bottom and left <= px <= right:
        strip = height - bottom
        if strip <= 0:
            return ZONE_X_OUTER
        return ZONE_X_INNER if py <= bottom + inner_frac * strip else ZONE_X_OUTER

    # Y-axis strip (left of the plot): inner is the right half (next to the plot).
    if px < left and top <= py <= bottom:
        if left <= 0:
            return ZONE_Y_OUTER
        return ZONE_Y_INNER if px >= left - inner_frac * left else ZONE_Y_OUTER

    return ZONE_NONE


def cursor_for_zone(zone: str) -> Qt.CursorShape:
    """Map a zone to the hover cursor that hints its gesture (R9.7 / R10.7)."""
    if zone in (ZONE_X_INNER, ZONE_X_OUTER):
        return Qt.CursorShape.SizeHorCursor
    if zone in (ZONE_Y_INNER, ZONE_Y_OUTER):
        return Qt.CursorShape.SizeVerCursor
    return Qt.CursorShape.ArrowCursor


class _AlignedAxisItem(pg.AxisItem):
    """Left axis whose tick labels use one consistent notation.

    pyqtgraph formats each tick independently, so a single axis can mix plain
    ("500000") and scientific ("1e+06") labels. When any tick falls back to
    scientific notation, render every non-zero tick in scientific (keeping
    pyqtgraph's significant-figure precision; "0" stays "0") so the column reads
    uniformly.

    The axis also acts as a drag SOURCE for the axis-move gesture: a left-drag
    starts a ``QDrag`` carrying this axis's VM index (set by the view), which the
    panel's drop sink decodes to relocate the axis. The VM index is ``None`` on a
    bare instance (e.g. unit-tested in isolation), making the drag a no-op there.
    """

    # Set per-build by the view (_reconcile_axes); None => not draggable.
    _vm_axis_index: int | None = None

    def set_vm_axis_index(self, index: int) -> None:
        """Tell this axis which VM axis index a drag from it should carry."""
        self._vm_axis_index = index

    def tickStrings(
        self, values: list[float], scale: float, spacing: float
    ) -> list[str]:
        strings = super().tickStrings(values, scale, spacing)
        if self.logMode or not any("e" in s for s in strings):
            return strings
        out: list[str] = []
        for v in values:
            vs = v * scale
            if vs == 0:
                out.append("0")
                continue
            # 6 significant figures like pyqtgraph's "%g", forced to exponential
            # with trailing zeros trimmed: 5e5 -> "5e+05", 1.5e6 -> "1.5e+06".
            mantissa, exp = (f"{vs:.5e}").split("e")
            mantissa = mantissa.rstrip("0").rstrip(".")
            out.append(f"{mantissa}e{exp}")
        return out

    def mouseDragEvent(self, ev: Any) -> None:
        """Start an axis-move QDrag on left-drag (real delivery is Layer-C/manual).

        The base ``AxisItem.mouseDragEvent`` only pans a *linked* ViewBox; these
        axes are unlinked, so it no-ops and is safe to override. Offscreen Qt
        cannot run the blocking drag loop, so this path is verified by Layer C /
        manual, not the headless Layer B suite.
        """
        if self._vm_axis_index is None or ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        if ev.isStart():
            view = self.getViewWidget()
            if view is not None:
                drag = QDrag(view)
                drag.setMimeData(encode_axis_index(self._vm_axis_index))
                drag.exec(Qt.DropAction.MoveAction)
        ev.accept()


class GraphPanelView(QWidget):
    """PyQtGraph waveform view bound to a :class:`GraphPanelVM`."""

    # Panel add/remove are area-level operations; the GraphAreaView wires these
    # to GraphAreaVM (R14.3).
    add_panel_requested = Signal()
    remove_panel_requested = Signal()

    def __init__(self, vm: GraphPanelVM, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.vm = vm
        self._items: dict[str, pg.PlotDataItem] = {}
        self._y_axes: list[pg.AxisItem] = []
        self._view_boxes: list[pg.ViewBox] = []
        self._dividers: list[RegionDividerItem] = []
        # One axis sub-layout per occupied column (root col = the column index).
        # Empty until the first _reconcile_axes build.
        self._axis_layouts: dict[int, pg.GraphicsLayout] = {}
        # Snapshot of the last-built grid structure (column_count + per-axis
        # column/row placement); lets _reconcile_axes take a fast path that only
        # retunes row stretch + labels when nothing structural changed.
        self._build_signature: tuple[object, ...] = ()
        # Assigned in _reconcile_axes' rebuild path; declared here (no runtime
        # binding) so mypy resolves its type at the use sites in refresh().
        self._legend: pg.LegendItem
        self._drag_zone: str | None = None
        self._drag_start: QPointF | None = None
        self._drop_active = False
        self._removable = True
        # Axis-move drag feedback: lazily created, reused per drag, nulled on rebuild.
        self._axis_move_line: QGraphicsLineItem | None = None
        self._axis_move_highlight: QGraphicsRectItem | None = None
        self._axis_move_dimmed_index: int | None = None

        self.plot_widget = pg.GraphicsLayoutWidget()
        # The central layout stacks Y-axis sub-layouts in columns 0..N-1 and the
        # plot area in column N (= vm.column_count); _reconcile_axes owns it.
        self._layout = self.plot_widget.ci.layout

        # Shared X-axis at the bottom (linked to the first ViewBox).
        self._x_axis = pg.AxisItem(orientation="bottom")
        self._x_axis.setLabel("Time", units="s")

        # Own all interaction via the zone model: disable pyqtgraph's built-in
        # mouse pan/zoom and auto-range; the VM drives the visible range.

        # Let drops bubble to this container rather than being eaten by the
        # GraphicsView; the container owns the drag-and-drop contract.
        self.plot_widget.setAcceptDrops(False)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot_widget)

        unsubscribe = self.vm.subscribe(self._on_vm_change)
        self._unsubscribe = unsubscribe
        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        self.destroyed.connect(lambda *_: unsubscribe())

        self.refresh()

    # ─── Rendering ─────────────────────────────────────────────────────────────

    def _on_vm_change(self, _change: str) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Re-project vm.render_data() onto the plot, reconciling multiple axes."""
        # 1. Reconcile Y-axes, ViewBoxes, and Dividers
        self._reconcile_axes()

        # 2. Get render curves from VM
        curves = self.vm.render_data()
        desired = {c.name: c for c in curves}

        # 3. Drop curves no longer present
        for key in list(self._items):
            if key not in desired:
                item = self._items.pop(key)
                # Find which ViewBox it was in and remove it
                for vb in self._view_boxes:
                    if item in vb.addedItems:
                        vb.removeItem(item)
                        break
                if self._legend:
                    self._legend.removeItem(item)

        # 4. Add or update remaining curves
        for curve in curves:
            item = self._items.get(curve.name)
            if item is None:
                item = pg.PlotDataItem(name=curve.name)
                self._items[curve.name] = item
                if self._legend:
                    self._legend.addItem(item, curve.name)

            item.setClipToView(False)
            # Add to correct ViewBox based on axis_index
            target_vb = self._view_boxes[
                min(curve.axis_index, len(self._view_boxes) - 1)
            ]
            if item not in target_vb.addedItems:
                # Remove from previous ViewBox if any
                for vb in self._view_boxes:
                    if vb != target_vb and item in vb.addedItems:
                        vb.removeItem(item)
                target_vb.addItem(item)

            item.setData(curve.timestamps, curve.values)
            item.setPen(pg.mkPen(curve.color))

        # 5. Update geometry and ranges
        # The overlaid secondary ViewBoxes must track the master's plot rect on
        # every render (the layout reflows the master after axis/divider changes).
        self._sync_overlay_geometry()

        # Shared X-range
        if self.vm.x_range is not None:
            for vb in self._view_boxes:
                vb.setXRange(*self.vm.x_range, padding=0)

        # Per-axis Y mapping: the ViewBox gets the expanded *virtual* range so its
        # data lands in its home region, while the AxisItem shows the real data
        # range so its tick labels stay correct.
        for i, axis_vm in enumerate(self.vm.axes):
            if axis_vm.y_range is not None:
                y_lo, y_hi = axis_vm.y_range
                full_lo, full_hi = axis_vm.calculate_virtual_range()
                self._view_boxes[i].setYRange(full_lo, full_hi, padding=0)
                self._y_axes[i].setRange(y_lo, y_hi)

    def _sync_overlay_geometry(self) -> None:
        """Align every overlaid ViewBox to the master's plot rect.

        Secondary ViewBoxes live directly in the scene (so waveforms draw
        unclipped across the whole panel); their geometry must follow the
        master's, otherwise they keep a stale rect and render their waveforms
        outside their home region.
        """
        if not self._view_boxes:
            return
        rect = self._view_boxes[0].sceneBoundingRect()
        for vb in self._view_boxes[1:]:
            vb.setGeometry(rect)

    def _axis_placement(self) -> list[tuple[int, int, int]]:
        """Map each VM axis to its grid slot as ``(vm_index, column, row)``.

        Within a column, axes stack top→bottom by ``top_ratio`` (mirroring the
        VM's ``_col`` helper); ``row = rank * 2`` so the odd rows in between stay
        free for the dividers that separate consecutive axes.
        """
        by_col: dict[int, list[tuple[float, int]]] = {}
        for i, ax in enumerate(self.vm.axes):
            by_col.setdefault(ax.column, []).append((ax.top_ratio, i))
        placement: list[tuple[int, int, int]] = []
        for col in sorted(by_col):
            for rank, (_top, i) in enumerate(sorted(by_col[col])):
                placement.append((i, col, rank * 2))
        return placement

    def _reconcile_axes(self) -> None:
        """Reconcile AxisItems, ViewBoxes, and Dividers with the VM's axes/columns.

        AxisItems are grouped into one sub-layout per occupied column (root
        col = the axis's column); the plot ViewBox container occupies root
        col = ``column_count`` and every lower column reserves fixed Y-axis
        width, so empty columns stay as drop-target gutters for a later task.

        The ViewBox overlay model is unchanged: ``_view_boxes[0]`` is the
        layout-managed master and the rest are scene items kept aligned to it by
        ``_sync_overlay_geometry``; ``_view_boxes[i]``/``_y_axes[i]`` stay paired
        with ``vm.axes[i]`` so ``refresh()``'s index mapping still holds.
        """
        placement = self._axis_placement()
        signature = (self.vm.column_count, tuple(sorted(placement)))

        # Fast path: column grouping and vertical order are identical, so only
        # height_ratio/labels could have changed (e.g. a divider drag). Retune
        # row stretch + labels in place instead of rebuilding — this keeps the
        # dragged divider object alive rather than recreating it under the cursor.
        if self._axis_layouts and signature == self._build_signature:
            for i, col, row in placement:
                axis_vm = self.vm.axes[i]
                self._axis_layouts[col].layout.setRowStretchFactor(
                    row, int(axis_vm.height_ratio * 1000)
                )
                if axis_vm.name or axis_vm.unit:
                    self._y_axes[i].setLabel(
                        text=axis_vm.name or None, units=axis_vm.unit or None
                    )
            return

        # Structure changed: rebuild.
        # Clear and explicitly remove axis-move feedback items before ci.clear();
        # they live directly in the scene (not the layout), so ci.clear() would
        # leave them as stale orphans — mirrors the secondary-ViewBox discipline.
        self._clear_axis_move_feedback()
        for _fb_item in (self._axis_move_line, self._axis_move_highlight):
            if _fb_item is not None:
                _fb_scene = _fb_item.scene()
                if _fb_scene is not None:
                    _fb_scene.removeItem(_fb_item)
        self._axis_move_line = None
        self._axis_move_highlight = None

        # Secondary ViewBoxes live straight in the scene (so waveforms draw
        # unclipped), so ci.clear() — which only drops layout-managed items —
        # leaves them behind as orphans that keep drawing their stale curve.
        # Remove them explicitly first.
        for vb in self._view_boxes[1:]:
            scene = vb.scene()
            if scene is not None:
                scene.removeItem(vb)
        self.plot_widget.ci.clear()
        self._y_axes.clear()
        self._view_boxes.clear()
        self._dividers.clear()
        self._items.clear()  # Clear items to force re-adding to new ViewBoxes
        self._axis_layouts = {}

        # We'll use a single legend for the whole panel
        self._legend = pg.LegendItem()

        # Root layout: columns 0..N-1 each reserve fixed Y-axis width (so empty
        # columns stay as fixed-width drop-target gutters); the plot column N
        # takes the remaining width. Row 0 = axes/plot, row 1 = fixed X-axis.
        column_count = self.vm.column_count
        root = self.plot_widget.ci.layout
        for c in range(column_count):
            root.setColumnFixedWidth(c, _Y_AXIS_FIXED_WIDTH)
        root.setColumnStretchFactor(column_count, 1)
        root.setRowStretchFactor(0, 1)
        root.setRowStretchFactor(1, 0)  # Fixed height for X-axis

        # One axis sub-layout per occupied column, in its matching root column.
        for col in sorted({c for _, c, _ in placement}):
            self._axis_layouts[col] = self.plot_widget.addLayout(row=0, col=col)

        row_of = {i: row for i, _c, row in placement}
        col_of = {i: c for i, c, _row in placement}

        # Create ViewBoxes + AxisItems in VM order so _view_boxes[i]/_y_axes[i]
        # stay paired with vm.axes[i]; AxisItems are PLACED by column/row.
        master_vb: pg.ViewBox | None = None
        for i, axis_vm in enumerate(self.vm.axes):
            vb = pg.ViewBox()
            vb.setMouseEnabled(x=False, y=False)
            vb.disableAutoRange()
            self._view_boxes.append(vb)

            if master_vb is None:
                # Master ViewBox is layout-managed in the plot column.
                master_vb = vb
                self.plot_widget.addItem(vb, row=0, col=column_count)
            else:
                # Secondary ViewBoxes overlay the master's plot rect (kept in
                # sync by _sync_overlay_geometry) and share its X range.
                vb.setXLink(master_vb)
                self.plot_widget.scene().addItem(vb)

            # Create AxisItem. It is NOT linked to the ViewBox: the ViewBox uses
            # an expanded virtual range, so the axis range is driven directly
            # (refresh -> setRange) with the real data range instead.
            axis = _AlignedAxisItem(orientation="left")
            # Fixed width shared by all stacked axes so their spines/tick numbers
            # align; overrides pyqtgraph's per-axis auto-width (which is ragged).
            axis.setWidth(_Y_AXIS_FIXED_WIDTH)
            # Tag the axis with its VM index so a drag from it carries that index.
            axis.set_vm_axis_index(i)
            if axis_vm.name or axis_vm.unit:
                axis.setLabel(text=axis_vm.name or None, units=axis_vm.unit or None)
            self._y_axes.append(axis)

            sub = self._axis_layouts[col_of[i]]
            sub.addItem(axis, row=row_of[i], col=0)
            sub.layout.setRowStretchFactor(row_of[i], int(axis_vm.height_ratio * 1000))

        # Dividers sit between vertically-consecutive axes WITHIN a column, just
        # below the upper axis. The divider's axis_index is the upper axis's
        # vertical RANK in its column (not a VM index) and it carries that
        # column, so resize_axis stays column-scoped and follows vertical
        # (top_ratio) order — correct even when VM-index order diverges from
        # vertical order after a move_axis_to_column. ``placement`` is grouped by
        # column then ranked top→bottom, so counting per column gives each
        # column's vertical axis count; a divider at vertical rank k sits at
        # sub-layout row ``k*2 + 1`` (between axis rows ``k*2`` and ``(k+1)*2``).
        axes_per_col: dict[int, int] = {}
        for _vm_index, col, _row in placement:
            axes_per_col[col] = axes_per_col.get(col, 0) + 1
        for col, n_axes in axes_per_col.items():
            sub = self._axis_layouts[col]
            for rank in range(n_axes - 1):
                divider = RegionDividerItem(self.vm, rank, column=col)
                self._dividers.append(divider)
                drow = rank * 2 + 1
                sub.addItem(divider, row=drow, col=0)
                sub.layout.setRowFixedHeight(drow, 1)

        # The VM always holds at least one axis, so the master ViewBox is set.
        assert master_vb is not None
        # Add X-axis at the bottom of the plot column (Row 1).
        self.plot_widget.addItem(self._x_axis, row=1, col=column_count)
        self._x_axis.linkToView(master_vb)
        # Keep overlays aligned when the window (and thus the master) resizes
        # without a VM change, since refresh() is not called in that case.
        master_vb.sigResized.connect(self._sync_overlay_geometry)
        # Add legend to the master ViewBox
        self._legend.setParentItem(master_vb)
        self._build_signature = signature

    # ─── Test/introspection surface ────────────────────────────────────────────

    def axis_columns(self) -> list[int]:
        """Return the sorted root grid columns that currently hold an AxisItem."""
        return sorted(self._axis_layouts)

    def plot_grid_column(self) -> int:
        """Return the root grid column reserved for the plot ViewBox container."""
        return self.vm.column_count

    def curve_keys(self) -> list[str]:
        """Return the signal keys currently drawn (one PlotDataItem each)."""
        return list(self._items)

    def curve_xy(self, key: str) -> tuple[object, object]:
        """Return the (x, y) arrays currently set on *key*'s curve."""
        return self._items[key].getData()

    def pen_color(self, key: str) -> str:
        """Return the hex colour of *key*'s curve pen (e.g. ``#1f77b4``)."""
        return pg.mkPen(self._items[key].opts["pen"]).color().name()

    def is_clipped(self, key: str) -> bool:
        """Return whether *key*'s curve is clipped to its ViewBox."""
        return bool(self._items[key].opts.get("clipToView", False))

    def legend_labels(self) -> list[str]:
        """Return the signal names currently shown in the legend."""
        return [label.text for _sample, label in self._legend.items]

    # ─── Gesture application (data-coordinate; the zoom/pan contract) ───────────

    def apply_zone_drag(self, zone: str, start_value: float, end_value: float) -> None:
        """Apply a drag in *zone*: inner = range-select zoom, outer = pan."""
        if zone == ZONE_X_INNER:
            self.vm.set_x_range(*ordered_pair(start_value, end_value))
        elif zone == ZONE_X_OUTER and self.vm.x_range is not None:
            lo, hi = self.vm.x_range
            self.vm.set_x_range(*pan_range(lo, hi, start_value - end_value))
        elif zone == ZONE_Y_INNER:
            self.vm.set_y_range(*ordered_pair(start_value, end_value))
        elif zone == ZONE_Y_OUTER and self.vm.y_range is not None:
            lo, hi = self.vm.y_range
            self.vm.set_y_range(*pan_range(lo, hi, start_value - end_value))

    def apply_zone_wheel(self, zone: str, center_value: float, factor: float) -> None:
        """Zoom the zone's axis about *center_value* by *factor*."""
        if zone in (ZONE_X_INNER, ZONE_X_OUTER) and self.vm.x_range is not None:
            lo, hi = self.vm.x_range
            self.vm.set_x_range(*zoom_range(lo, hi, center_value, factor))
        elif zone in (ZONE_Y_INNER, ZONE_Y_OUTER) and self.vm.y_range is not None:
            lo, hi = self.vm.y_range
            self.vm.set_y_range(*zoom_range(lo, hi, center_value, factor))

    def reset_zone(self, zone: str) -> None:
        """Reset the zone's axis to the full data extent (double-click, R9.6)."""
        if zone in (ZONE_X_INNER, ZONE_X_OUTER):
            self.vm.reset_x()
        elif zone in (ZONE_Y_INNER, ZONE_Y_OUTER):
            self.vm.reset_y()

    # ─── Pixel ↔ zone/data glue (best-effort; smoke-tested) ─────────────────────

    def _plot_rect_in_widget(self) -> QRectF:
        """Return the plot (viewbox) rect in this widget's coordinate space."""
        try:
            # All ViewBoxes share the same space in col 1
            vb = self._view_boxes[0] if self._view_boxes else None
            if vb is None:
                return QRectF(0.0, 0.0, float(self.width()), float(self.height()))

            scene_rect = vb.sceneBoundingRect()
            # GraphicsLayoutWidget.mapFromScene maps from scene to widget coordinates
            top_left = self.plot_widget.mapFromScene(scene_rect.topLeft())
            bottom_right = self.plot_widget.mapFromScene(scene_rect.bottomRight())
            return QRectF(QPointF(top_left), QPointF(bottom_right))
        except Exception:
            return QRectF(0.0, 0.0, float(self.width()), float(self.height()))

    def _zone_at(self, pos: QPointF) -> str:
        return classify_zone(
            pos.x(), pos.y(), self._plot_rect_in_widget(), self.width(), self.height()
        )

    def _axis_index_at(self, pos: QPointF) -> int:
        """Identify which Y-axis is at *pos*."""
        # Simple vertical split for now based on relative height
        if not self._y_axes:
            return 0

        plot_rect = self._plot_rect_in_widget()
        y_rel = (pos.y() - plot_rect.top()) / plot_rect.height()

        for i, axis_vm in enumerate(self.vm.axes):
            if axis_vm.top_ratio <= y_rel <= axis_vm.top_ratio + axis_vm.height_ratio:
                return i
        return 0

    def _axis_drop_target(self, pos: QPointF) -> tuple[int, int]:
        """Map a widget-space *pos* to an axis-move target ``(column, position)``.

        The column is the fixed-width Y-axis band ``pos.x()`` falls in (clamped to
        ``0..column_count-1``). The vertical *position* is the insertion index
        among that column's axes: with N axes there are N+1 boundaries (each
        axis's top edge plus the column bottom), and the nearest boundary to
        ``pos.y()`` wins. An empty/lone column inserts at position 0.
        """
        col = max(0, min(int(pos.x() // _Y_AXIS_FIXED_WIDTH), self.vm.column_count - 1))
        rect = self._plot_rect_in_widget()
        col_axes = sorted(
            (a for a in self.vm.axes if a.column == col), key=lambda a: a.top_ratio
        )
        if not col_axes:
            return (col, 0)
        top, h = rect.top(), rect.height()
        boundaries = [top + a.top_ratio * h for a in col_axes] + [top + h]
        position = min(
            range(len(boundaries)), key=lambda k: abs(boundaries[k] - pos.y())
        )
        return (col, position)

    # ─── Axis-move drag feedback ───────────────────────────────────────────────

    def _ensure_feedback_items(self) -> None:
        """Lazily create and register the axis-move feedback items in the scene.

        Items are created once and reused for every drag-move notification;
        show/hide toggles replace recreate-per-event to avoid scene churn.
        """
        scene = self.plot_widget.scene()
        if self._axis_move_line is None:
            line = QGraphicsLineItem()
            pen = QPen(QColor(255, 165, 0))  # orange
            pen.setWidth(3)
            line.setPen(pen)
            line.setZValue(100)
            line.setVisible(False)
            scene.addItem(line)
            self._axis_move_line = line
        if self._axis_move_highlight is None:
            rect_item = QGraphicsRectItem()
            rect_item.setBrush(QBrush(QColor(255, 165, 0, 60)))  # translucent orange
            rect_item.setPen(QPen(Qt.PenStyle.NoPen))
            rect_item.setZValue(100)
            rect_item.setVisible(False)
            scene.addItem(rect_item)
            self._axis_move_highlight = rect_item

    def _update_axis_move_feedback(self, source_index: int, pos: QPointF) -> None:
        """Update insertion-line / column-highlight while an axis-move drag is active.

        Called from ``dragMoveEvent`` on every cursor move.  For a non-empty
        target column an orange line snaps to the nearest of the N+1 axis
        boundaries; for an empty column the whole band is highlighted instead.
        The source axis is dimmed to signal it is being relocated.
        """
        self._ensure_feedback_items()
        col, position = self._axis_drop_target(pos)
        rect = self._plot_rect_in_widget()
        W = _Y_AXIS_FIXED_WIDTH
        x_start = float(col * W)
        x_end = float((col + 1) * W)
        col_axes = sorted(
            (a for a in self.vm.axes if a.column == col), key=lambda a: a.top_ratio
        )

        # Dim the source axis (idempotent on repeated calls for the same source).
        if 0 <= source_index < len(self._y_axes):
            self._y_axes[source_index].setOpacity(0.35)
            self._axis_move_dimmed_index = source_index

        if not col_axes:
            # Empty column: highlight the full column band instead of a line.
            assert self._axis_move_highlight is not None
            assert self._axis_move_line is not None
            self._axis_move_highlight.setRect(
                QRectF(x_start, rect.top(), float(W), rect.height())
            )
            self._axis_move_highlight.setVisible(True)
            self._axis_move_line.setVisible(False)
        else:
            # Non-empty column: show insertion line at the nearest boundary.
            boundaries = [
                rect.top() + a.top_ratio * rect.height() for a in col_axes
            ] + [rect.top() + rect.height()]
            boundary_y = boundaries[position]
            assert self._axis_move_line is not None
            assert self._axis_move_highlight is not None
            self._axis_move_line.setLine(x_start, boundary_y, x_end, boundary_y)
            self._axis_move_line.setVisible(True)
            self._axis_move_highlight.setVisible(False)

    def _axis_move_line_y(self) -> float:
        """Return the scene-y of the current insertion line (test introspection)."""
        if self._axis_move_line is None:
            return 0.0
        return self._axis_move_line.line().y1()

    def _clear_axis_move_feedback(self) -> None:
        """Hide feedback items and restore any dimmed axis's opacity.

        Called on drag-leave, drop completion, and at the start of every
        structural rebuild so no stale visual state leaks across rebuilds.
        """
        if self._axis_move_line is not None:
            self._axis_move_line.setVisible(False)
        if self._axis_move_highlight is not None:
            self._axis_move_highlight.setVisible(False)
        if self._axis_move_dimmed_index is not None:
            if 0 <= self._axis_move_dimmed_index < len(self._y_axes):
                self._y_axes[self._axis_move_dimmed_index].setOpacity(1.0)
            self._axis_move_dimmed_index = None

    def _data_value(self, pos: QPointF, axis: str) -> float | None:
        try:
            axis_idx = self._axis_index_at(pos)
            vb = self._view_boxes[axis_idx] if axis == "y" else self._view_boxes[0]

            scene_pos = self.plot_widget.mapToScene(pos.toPoint())
            point = vb.mapSceneToView(scene_pos)
            return float(point.x() if axis == "x" else point.y())
        except Exception:
            return None

    # ─── Mouse / wheel handlers (thin glue over the gesture methods) ────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Only the left button drives zoom/pan; right-click opens the context
        # menu and must not start a drag gesture.
        if event.button() == Qt.MouseButton.LeftButton:
            zone = self._zone_at(event.position())
            if zone in (ZONE_X_INNER, ZONE_X_OUTER, ZONE_Y_INNER, ZONE_Y_OUTER):
                self._drag_zone = zone
                self._drag_start = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_zone is None:
            self.setCursor(cursor_for_zone(self._zone_at(event.position())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_zone is not None and self._drag_start is not None:
            axis = "x" if self._drag_zone in (ZONE_X_INNER, ZONE_X_OUTER) else "y"
            start = self._data_value(self._drag_start, axis)
            end = self._data_value(event.position(), axis)
            if start is not None and end is not None:
                self.apply_zone_drag(self._drag_zone, start, end)
        self._drag_zone = None
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.reset_zone(self._zone_at(event.position()))
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        zone = self._zone_at(event.position())
        axis = (
            "x"
            if zone in (ZONE_X_INNER, ZONE_X_OUTER)
            else "y"
            if zone in (ZONE_Y_INNER, ZONE_Y_OUTER)
            else None
        )
        if axis is not None:
            center = self._data_value(event.position(), axis)
            if center is not None:
                factor = _WHEEL_IN if event.angleDelta().y() > 0 else _WHEEL_OUT
                self.apply_zone_wheel(zone, center, factor)
        event.accept()

    # ─── Drag-and-drop sink (R12.4) ────────────────────────────────────────────

    def is_drop_highlighted(self) -> bool:
        """Return True while a droppable drag is hovering (R12.5)."""
        return self._drop_active

    def _set_drop_highlight(self, active: bool) -> None:
        self._drop_active = active
        self.setStyleSheet(
            "GraphPanelView { border: 2px solid #1f77b4; }" if active else ""
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        md = event.mimeData()
        if md.hasFormat(SIGNAL_KEYS_MIME) or md.hasFormat(AXIS_INDEX_MIME):
            self._set_drop_highlight(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        md = event.mimeData()
        if md.hasFormat(SIGNAL_KEYS_MIME) or md.hasFormat(AXIS_INDEX_MIME):
            event.acceptProposedAction()
            axis_index = decode_axis_index(md)
            if axis_index is not None:
                self._update_axis_move_feedback(axis_index, event.position())
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_highlight(False)
        self._clear_axis_move_feedback()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_highlight(False)

        # Axis-move drop: relocate an existing axis to the target column/position.
        # Checked BEFORE signal-key handling so the two gestures never overlap;
        # only fires when the drag actually carried an axis index.
        axis_index = decode_axis_index(event.mimeData())
        if axis_index is not None:
            col, position = self._axis_drop_target(event.position())
            self.vm.move_axis_to_column(axis_index, col, position)
            self._clear_axis_move_feedback()
            event.acceptProposedAction()
            return

        keys = decode_signal_keys(event.mimeData())
        if not keys:
            event.ignore()
            return

        pos = event.position()
        zone = self._zone_at(pos)
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

        if zone in (ZONE_Y_INNER, ZONE_Y_OUTER):
            axis_idx = self._axis_index_at(pos)
            if ctrl:
                # Ctrl = join: add each dropped signal alongside existing ones.
                for key in keys:
                    self.vm.add_signal_to_axis(key, axis_idx)
            else:
                # Plain drop = overwrite (R5): replace axis contents with ALL
                # dropped signals — first via overwrite, rest via add.
                self.vm.overwrite_axis(keys[0], axis_idx)
                for key in keys[1:]:
                    self.vm.add_signal_to_axis(key, axis_idx)
        else:
            # Dropped on plot area (ZONE_PLOT) or elsewhere: create new axis.
            for key in keys:
                self.vm.create_new_axis(key)

        event.acceptProposedAction()

    # ─── Resize → LOD pixel budget ──────────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.vm.set_panel_width(max(1, event.size().width()))  # notifies → refresh()

    # ─── Context menu (R14.3) ───────────────────────────────────────────────────

    def set_removable(self, removable: bool) -> None:
        """Set whether the 'Remove Panel' action is enabled (R6.6 grey-out)."""
        self._removable = removable

    def _reset_all_axes(self) -> None:
        self.vm.reset_x()
        self.vm.reset_y()

    def build_context_menu(self) -> QMenu:
        """Build the blank-area panel menu (add/remove panel, reset axes)."""
        menu = QMenu(self)
        menu.addAction("Add Panel").triggered.connect(
            lambda *_: self.add_panel_requested.emit()
        )
        remove = menu.addAction("Remove Panel")
        remove.setEnabled(self._removable)
        remove.triggered.connect(lambda *_: self.remove_panel_requested.emit())
        menu.addAction("Reset All Axes").triggered.connect(
            lambda *_: self._reset_all_axes()
        )
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.build_context_menu().exec(event.globalPos())
