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

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QContextMenuEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from valisync.gui.adapters.qt_signal_models import (
    SIGNAL_KEYS_MIME,
    decode_signal_keys,
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
        # Assigned later in _reconcile_axes; declared here (no runtime binding,
        # so the hasattr(_axis_layout) guard still holds) to let mypy resolve
        # their type at the use sites in refresh().
        self._legend: pg.LegendItem
        self._axis_layout: pg.GraphicsLayout
        self._drag_zone: str | None = None
        self._drag_start: QPointF | None = None
        self._drop_active = False
        self._removable = True

        self.plot_widget = pg.GraphicsLayoutWidget()
        # The central layout manages axes in col 0 and the plot area in col 1.
        self._layout = self.plot_widget.ci.layout
        self._layout.setColumnFixedWidth(0, _Y_AXIS_FIXED_WIDTH)  # Width for Y-axes

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

    def _reconcile_axes(self) -> None:
        """Ensure the number of AxisItems, ViewBoxes, and Dividers matches the VM."""
        n_axes = len(self.vm.axes)

        # If count matches, just update stretch factors and labels in the sub-layout
        if hasattr(self, "_axis_layout") and len(self._y_axes) == n_axes:
            for i, axis_vm in enumerate(self.vm.axes):
                self._axis_layout.layout.setRowStretchFactor(
                    i * 2, int(axis_vm.height_ratio * 1000)
                )
                if axis_vm.unit:
                    self._y_axes[i].setLabel(units=axis_vm.unit)
            return

        # Count mismatch: rebuild layout
        # (Slightly heavy but robust for now)
        # Secondary ViewBoxes were added straight to the scene, so ci.clear()
        # (which only drops layout-managed items) leaves them behind as orphans
        # that keep drawing their stale curve. Remove them explicitly first.
        for vb in self._view_boxes[1:]:
            scene = vb.scene()
            if scene is not None:
                scene.removeItem(vb)
        self.plot_widget.ci.clear()
        self._y_axes.clear()
        self._view_boxes.clear()
        self._dividers.clear()
        self._items.clear()  # Clear items to force re-adding to new ViewBoxes

        # We'll use a single legend for the whole panel
        self._legend = pg.LegendItem()

        # Root layout configuration (2x2)
        # Row 0: Axes (Col 0), ViewBoxes (Col 1)
        # Row 1: empty (Col 0), X-axis (Col 1)
        root = self.plot_widget.ci.layout
        root.setColumnFixedWidth(0, _Y_AXIS_FIXED_WIDTH)
        root.setColumnStretchFactor(1, 1)  # Ensure plot area takes remaining width
        root.setRowStretchFactor(0, 1)
        root.setRowStretchFactor(1, 0)  # Fixed height for X-axis

        # Add Axis Sub-Layout
        self._axis_layout = self.plot_widget.addLayout(row=0, col=0)

        # Primary ViewBox (the one at the bottom usually has the X-axis)
        master_vb = None

        for i in range(n_axes):
            axis_vm = self.vm.axes[i]

            # Create ViewBox
            vb = pg.ViewBox()
            vb.setMouseEnabled(x=False, y=False)
            vb.disableAutoRange()
            self._view_boxes.append(vb)

            if master_vb is None:
                master_vb = vb
            else:
                vb.setXLink(master_vb)

            # Create AxisItem. It is NOT linked to the ViewBox: the ViewBox uses
            # an expanded virtual range, so the axis range is driven directly
            # (refresh -> setRange) with the real data range instead.
            axis = pg.AxisItem(orientation="left")
            # Fixed width shared by all stacked axes so their spines/tick numbers
            # align; overrides pyqtgraph's per-axis auto-width (which is ragged).
            axis.setWidth(_Y_AXIS_FIXED_WIDTH)
            if axis_vm.unit:
                axis.setLabel(units=axis_vm.unit)
            self._y_axes.append(axis)

            # Add to Axis Sub-Layout
            row = i * 2
            self._axis_layout.addItem(axis, row=row, col=0)
            self._axis_layout.layout.setRowStretchFactor(
                row, int(axis_vm.height_ratio * 1000)
            )

            # Add ViewBox to the root layout (Col 1)
            if i == 0:
                # Primary ViewBox is managed by the layout in Col 1, Row 0
                self.plot_widget.addItem(vb, row=0, col=1)
                master_vb = vb
            else:
                # Secondary ViewBoxes are added to the scene and overlay the
                # master's plot rect (kept in sync by _sync_overlay_geometry).
                vb.setXLink(master_vb)
                self.plot_widget.scene().addItem(vb)

            # Add Divider if not the last axis
            if i < n_axes - 1:
                divider = RegionDividerItem(self.vm, i)
                self._dividers.append(divider)
                # Dividers are in between axis rows in the sub-layout
                self._axis_layout.addItem(divider, row=row + 1, col=0)
                self._axis_layout.layout.setRowFixedHeight(row + 1, 1)

        # The VM always holds at least one axis, so the master ViewBox is set.
        assert master_vb is not None
        # Add X-axis at the bottom (Row 1, Col 1)
        self.plot_widget.addItem(self._x_axis, row=1, col=1)
        self._x_axis.linkToView(master_vb)
        # Keep overlays aligned when the window (and thus the master) resizes
        # without a VM change, since refresh() is not called in that case.
        master_vb.sigResized.connect(self._sync_overlay_geometry)
        # Add legend to the master ViewBox
        self._legend.setParentItem(master_vb)

    # ─── Test/introspection surface ────────────────────────────────────────────

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
        if event.mimeData().hasFormat(SIGNAL_KEYS_MIME):
            self._set_drop_highlight(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(SIGNAL_KEYS_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_highlight(False)
        keys = decode_signal_keys(event.mimeData())
        if not keys:
            event.ignore()
            return

        pos = event.position()
        zone = self._zone_at(pos)

        for key in keys:
            if zone in (ZONE_Y_INNER, ZONE_Y_OUTER):
                axis_idx = self._axis_index_at(pos)
                self.vm.add_signal_to_axis(key, axis_idx)
            else:
                # Dropped on plot area (ZONE_PLOT) or elsewhere: create new axis
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
