"""Graph_Panel view — pyqtgraph waveform projection of GraphPanelVM.

Task 8.2: project ``vm.render_data()`` (LOD-reduced by the VM) onto one
``PlotDataItem`` per curve, with colours and a legend; accept signal drops;
report pixel width on resize.

Interaction model: the time (X) axis has always-on widget-level zoom/pan via
inner/outer zones; each Y axis owns its resize/zoom/pan/move on its
``_AlignedAxisItem``, accepted only while that axis is active.  The logic is
split into pure, headless-testable pieces (zone classification, range math) and
thin Qt event handlers.  The VM is the single source of truth for the visible
range; gestures update it and the resulting notify re-projects the plot.
pyqtgraph's own mouse handling is disabled so this model fully owns interaction.

Zoom/pan are applied once per gesture (range-select / pan on release), so the
16 ms budget is met by the VM's render cache + bounded point count.  Live
drag-preview with a debounce timer is a noted refinement (R9.5).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsWidget,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.adapters.qt_signal_models import (
    AXIS_INDEX_MIME,
    SIGNAL_KEYS_MIME,
    decode_axis_move,
    decode_signal_keys,
    encode_axis_move,
)
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.cursor_shapes import CursorKind, cursor

# ─── Axis interaction zones (R9.1 / R10.1) ────────────────────────────────────

ZONE_PLOT = "plot"
ZONE_X_INNER = "x_inner"
ZONE_X_OUTER = "x_outer"
ZONE_Y_INNER = "y_inner"
ZONE_Y_OUTER = "y_outer"
ZONE_NONE = "none"

# R14 time-offset gesture tolerances (scene pixels). Cursor-line proximity is
# wider than the curve tolerance so the cursor line wins on overlap (§4).
CURVE_HIT_TOL_PX = 8.0
CURSOR_LINE_HIT_PX = 10.0

# Active Y-axis grip/frame/interior zones for resize gestures (Task 3).
AXZONE_GRIP_TOP = "ax_grip_top"
AXZONE_GRIP_BOTTOM = "ax_grip_bottom"
AXZONE_FRAME = "ax_frame"
AXZONE_ZOOM = "ax_zoom"
AXZONE_PAN = "ax_pan"

# Fixed pixel width shared by every stacked Y-axis so their tick spines (and
# right-aligned tick numbers) line up into one vertical edge. Sized for ~6-digit
# / scientific labels (e.g. "-1.2e+06" ≈ 48px) plus tick marks and the unit
# label. Fixed — not data-dependent — so the layout never shifts when the
# displayed signals change. Larger magnitudes stay within it via pyqtgraph's
# automatic SI-prefix / scientific tick formatting.
_Y_AXIS_FIXED_WIDTH = 72

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

    NOTE: ZONE_Y_INNER / ZONE_Y_OUTER are still returned unchanged even though
    widget-level Y zoom/pan was removed (Task 8).  These zones continue to serve
    as drop-target geometry in dropEvent (R5 overwrite / Ctrl-join routing).
    _AlignedAxisItem now owns all Y zoom/pan interaction.
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


def classify_axis_zone(
    lx: float,
    ly: float,
    w: float,
    h: float,
    *,
    grip_w: float,
    grip_h: float,
    frame: float,
    tol: float,
) -> str:
    """Classify an item-local point on an active axis spine into a gesture zone.

    Priority: grip (resize) > frame border (move) > interior (inner=zoom / outer=pan).
    Inner = right (plot-side); outer = left (window-edge side). The grip hit-area is
    the centred grip rect expanded by *tol* for grabbability (NOT a full-width band).

    The move-frame border is *frame* px on the left/right (the natural grab edge,
    where width is fixed and ample). The top/bottom band is capped at h/4 so a short
    (resized-down) axis always keeps a zoom/pan interior in its middle half instead
    of collapsing entirely into the move-frame.
    """
    half = grip_w / 2.0
    in_grip_x = abs(lx - w / 2.0) <= half + tol
    if in_grip_x and ly <= grip_h + tol:
        return AXZONE_GRIP_TOP
    if in_grip_x and ly >= h - grip_h - tol:
        return AXZONE_GRIP_BOTTOM
    v_frame = min(frame, h / 4.0)
    on_border = lx <= frame or lx >= w - frame or ly <= v_frame or ly >= h - v_frame
    if on_border:
        return AXZONE_FRAME
    return AXZONE_ZOOM if lx >= w / 2.0 else AXZONE_PAN


def grip_resize_delta(
    cursor_scene_y: float,
    panel_top: float,
    panel_height: float,
    grip_offset: float,
    current_edge_ratio: float,
) -> float:
    """How far (in panel-height ratio) a grabbed axis edge must move to track the cursor.

    The cursor's scene-Y is mapped to a fraction of the FULL panel height — the same
    0..1 space as ``top_ratio``/``height_ratio`` — then the grab offset captured at
    drag start is re-added and the current edge ratio subtracted. Absolute (not a
    pixel delta) so it is immune to (a) the axis geometry shifting mid-drag, which a
    top-edge resize causes, and (b) the per-axis-height scaling error of dividing a
    pixel delta by the spine height (the cause of the cursor/edge mismatch and the
    runaway-to-minimum).
    """
    if panel_height <= 0:
        return 0.0
    cursor_ratio = (cursor_scene_y - panel_top) / panel_height
    return (cursor_ratio + grip_offset) - current_edge_ratio


def reset_scene_drag_state(scene: Any) -> None:
    """Clear a pyqtgraph GraphicsScene's press/drag bookkeeping after a modal QDrag.

    ``QDrag.exec`` (launched from ``mouseDragEvent`` to move an axis) runs Windows'
    OLE modal loop, which swallows the mouse-release — so ``GraphicsScene.
    mouseReleaseEvent`` never runs its own reset and leaves ``dragButtons`` /
    ``dragItem`` / ``clickEvents`` / ``lastDrag`` pointing at the source item, which
    the axis-move rebuild has since deleted. The NEXT press is then delivered to
    that stale ``dragItem`` with ``isStart=False``, so the first grip-resize (or
    re-grab to move) after a move silently does nothing. This replicates
    pyqtgraph's release-time reset so the next gesture starts clean. No-op if the
    scene is missing or lacks the attributes (defensive across pyqtgraph versions).
    """
    if scene is None:
        return
    scene.dragButtons = []
    scene.dragItem = None
    scene.clickEvents = []
    scene.lastDrag = None
    # Also forget the last hover: pyqtgraph picks a *new* drag's target from
    # lastHoverEvent.dragItems() (GraphicsScene.sendDragEvent), and after the move
    # rebuild that still points at the destroyed source item. Clearing it forces
    # re-discovery of the live item under the cursor via itemsNearEvent — otherwise
    # the next drag is delivered to the stale item in its old coordinate frame
    # (cursor maps outside it → mis-classified as a frame-move → another QDrag → hang).
    scene.lastHoverEvent = None


def cursor_for_zone(zone: str) -> CursorKind:
    """Map a zone to the hover cursor kind that hints its gesture (PC-14).

    X inner = range-select zoom (custom horizontal zoom bracket), X outer = pan
    (SizeHor). Y zones fall through to ARROW: _AlignedAxisItem owns the Y hover
    cursor, so the widget must not impose a competing cursor there.
    """
    if zone == ZONE_X_INNER:
        return CursorKind.ZOOM_H
    if zone == ZONE_X_OUTER:
        return CursorKind.PAN_H
    return CursorKind.ARROW


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

    # Grip/frame/interior zone constants (Task 5 — matched by cursor_for_local).
    GRIP_W: float = 40.0  # centred grip rect width (pixels)
    GRIP_H: float = 8.0  # grip rect height (pixels)
    # Move-frame border thickness. Wide enough to grab reliably and to keep the
    # SizeAll move-cursor from flickering in a hairline band; the top/bottom band is
    # capped at h/4 in classify_axis_zone so a short axis keeps a zoom/pan interior.
    FRAME: float = 8.0
    TOL: float = 4.0  # grip hit-area expansion for grabbability (pixels)

    # Set per-build by the view (_reconcile_axes); None => not draggable/activatable.
    _vm_axis_index: int | None = None
    # Back-reference to the parent GraphPanelView set by _reconcile_axes; None on
    # bare instances (e.g. unit-tested in isolation) so click/hover events are no-ops.
    _panel_view: GraphPanelView | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Required so Qt delivers hoverMoveEvent / hoverLeaveEvent to this item.
        self.setAcceptHoverEvents(True)
        # Drag state (Task 6): reset on each drag start via _begin_axis_drag.
        # _zone is the AXZONE_* constant set during isStart; the subsequent
        # update/finish helpers read it to route to the correct VM method.
        self._zone: str = AXZONE_FRAME  # placeholder; overwritten by _begin_axis_drag
        self._drag_start_data: float = 0.0  # data-coordinate at drag-start cursor pos
        self._drag_h: float = 0.0  # bounding-rect height captured at drag start
        # (edge ratio - cursor ratio) captured when a grip is grabbed; re-added each
        # update so the edge tracks the cursor without snapping to it on first move.
        self._grip_offset: float = 0.0

    def set_vm_axis_index(self, index: int) -> None:
        """Tell this axis which VM axis index a drag from it should carry."""
        self._vm_axis_index = index

    def set_panel_view(self, panel: GraphPanelView) -> None:
        """Wire this axis back to the containing GraphPanelView for click activation."""
        self._panel_view = panel

    def _emit_panel_activation(self) -> None:
        """Emit panel activation for a click that landed on this axis.

        This is the *sole* activation path for axis clicks, not a backup: a
        click on this AxisItem is accepted (consumed) by the scene item for Y
        zoom/pan/resize, so it never propagates up to
        GraphPanelView.mousePressEvent. Only plot-area presses reach that
        widget-level handler; axis presses must emit activation from here.
        Both paths can fire for a single physical click (a plot-area press,
        never an axis press), and that duplicate is safe — see the
        activate_requested declaration below for why.
        """
        if self._panel_view is not None:
            self._panel_view.activate_requested.emit()

    # ── Task 5: cursor mapping + active/hover frame ────────────────────────────

    def cursor_for_local(self, lx: float, ly: float, h: float) -> CursorKind:
        """Return the hover cursor kind for item-local point (lx, ly) on a spine of height h.

        Pure (h is passed explicitly, not read from geometry) so it is headless-
        testable without a scene.  Delegates zone classification to the module-
        level ``classify_axis_zone``; zoom/pan use the unified custom vertical
        bracket / SizeVer to match the X axis scheme (PC-13).
        """
        z = classify_axis_zone(
            lx,
            ly,
            self.width(),
            h,
            grip_w=self.GRIP_W,
            grip_h=self.GRIP_H,
            frame=self.FRAME,
            tol=self.TOL,
        )
        return {
            AXZONE_GRIP_TOP: CursorKind.RESIZE_V,
            AXZONE_GRIP_BOTTOM: CursorKind.RESIZE_V,
            AXZONE_FRAME: CursorKind.MOVE,
            AXZONE_ZOOM: CursorKind.ZOOM_V,
            AXZONE_PAN: CursorKind.PAN_V,
        }[z]

    def _is_active_or_hover(self) -> bool:
        """Return True if this axis is currently the active or hovered axis.

        Reads transient UI state from ``_panel_view``; always False on bare
        instances (``_panel_view`` is None) so painting stays a no-op there.
        """
        view = self._panel_view
        if view is None or self._vm_axis_index is None:
            return False
        return self._vm_axis_index in (view._active_axis_index, view._hover_axis_index)

    def hoverMoveEvent(self, ev: Any) -> None:
        """Update hover state and cursor on mouse-over.

        Called by Qt when the cursor enters or moves within this item's
        bounding rect (requires ``setAcceptHoverEvents(True)`` in __init__).
        Delegates state bookkeeping to ``GraphPanelView.set_hover_axis`` and
        applies a zone-sensitive cursor only when this axis is also active.
        """
        view = self._panel_view
        if view is None or self._vm_axis_index is None:
            return
        view.set_hover_axis(self._vm_axis_index)
        if self._vm_axis_index == view._active_axis_index:
            p = ev.pos()
            self.setCursor(
                cursor(
                    self.cursor_for_local(p.x(), p.y(), self.boundingRect().height())
                )
            )
        else:
            # 非アクティブ軸: 「クリックで活性化」を示す(操作は活性化必須・PC-13)。
            self.setCursor(cursor(CursorKind.ACTIVATE))

    def hoverLeaveEvent(self, ev: Any) -> None:
        """Clear hover state and reset cursor when the mouse leaves the spine."""
        view = self._panel_view
        if view is not None:
            view.set_hover_axis(None)
        self.unsetCursor()

    def paint(self, p: Any, *args: Any) -> None:
        """Paint the spine, then overlay an active/hover frame and grip handles.

        The overlay is Case C (spine outline only): an amber border when
        hovered, plus two centred rounded grip rects when the axis is also
        active (task 5).  Non-active/non-hover → base paint only, no cost.
        """
        super().paint(p, *args)
        if not self._is_active_or_hover():
            return
        r = self.boundingRect()
        p.save()
        # Amber frame border — always shown while active OR hovered.
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#f59e0b"), 2))
        p.drawRect(r.adjusted(1, 1, -1, -1))
        # Grip handles — only shown when this axis is the ACTIVE axis.
        if (
            self._panel_view is not None
            and self._vm_axis_index == self._panel_view._active_axis_index
        ):
            p.setBrush(QColor("#ffffff"))
            p.setPen(QPen(QColor("#b45309"), 1))
            cx = r.center().x()
            for cy in (r.top() + 1.0, r.bottom() - 1.0):
                p.drawRoundedRect(
                    QRectF(
                        cx - self.GRIP_W / 2,
                        cy - self.GRIP_H / 2,
                        self.GRIP_W,
                        self.GRIP_H,
                    ),
                    3,
                    3,
                )
        p.restore()

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

    def mouseClickEvent(self, ev: Any) -> None:
        """Activate this axis on a left click (pyqtgraph scene event, not Qt press).

        pyqtgraph's GraphicsScene fires ``mouseClickEvent`` after a press+release
        without a drag gesture — the same routing path that delivers
        ``mouseDragEvent``.  The parent AxisItem.mouseClickEvent merely forwards
        to the linked ViewBox; since these axes are *unlinked*, the parent is a
        no-op and our override is the sole handler.  The click sets the panel's
        active axis so Task 6's gesture dispatcher can route subsequent events to
        the correct Y-axis.
        """
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        if self._panel_view is not None and self._vm_axis_index is not None:
            self._panel_view.set_active_axis(self._vm_axis_index)
            self._panel_view._deactivate_curve()  # axis click is a different target
        self._emit_panel_activation()
        ev.accept()

    # ── Task 6: zone-routed drag helpers ──────────────────────────────────────

    def _panel_region(self) -> QRectF:
        """Full panel plot rect (scene coords) — the pixel extent of the 0..1
        height-ratio space. Unit rect on bare/unlaid-out instances."""
        view = self._panel_view
        if view is None or not view._view_boxes:
            return QRectF(0.0, 0.0, 1.0, 1.0)
        return view._view_boxes[0].sceneBoundingRect()

    def _local_y_to_data(self, ly: float, h: float) -> float:
        """Convert item-local y pixel to data-coordinate using the current y_range.

        The spine maps linearly: top (ly=0) → y_hi, bottom (ly=h) → y_lo.
        ``h`` is passed explicitly so callers can use the height captured at
        drag-start even when the geometry changes mid-drag.
        """
        view = self._panel_view
        if view is None or self._vm_axis_index is None:
            return 0.0
        rng = view.vm.axes[self._vm_axis_index].y_range or (0.0, 1.0)
        lo, hi = rng
        frac = min(max(ly / max(h, 1.0), 0.0), 1.0)  # 0=top → 1=bottom
        return hi - frac * (hi - lo)  # top=hi, bottom=lo

    def _begin_axis_drag(self, lx: float, ly: float) -> bool:
        """Classify the drag start zone; return True if this axis should handle it.

        Only the active axis accepts drag gestures. Stores ``_zone``,
        ``_drag_start_data``, and ``_drag_h`` for use by the update/finish
        helpers called during the same drag sequence.

        Layer B direct-call surface: callers pass item-local (lx, ly) and
        inspect _zone / VM side-effects; no real pyqtgraph event needed.
        """
        view = self._panel_view
        if view is None or self._vm_axis_index != view._active_axis_index:
            return False
        h = self.boundingRect().height()
        self._zone = classify_axis_zone(
            lx,
            ly,
            self.width(),
            h,
            grip_w=self.GRIP_W,
            grip_h=self.GRIP_H,
            frame=self.FRAME,
            tol=self.TOL,
        )
        self._drag_start_data = self._local_y_to_data(ly, h)
        self._drag_h = h
        return True

    def _grip_grab_offset(self, cursor_scene_y: float) -> float:
        """Offset (edge ratio - cursor ratio) at grab time, so the edge tracks the
        cursor without snapping to it on the first move. 0 if state is unavailable."""
        view = self._panel_view
        if view is None or self._vm_axis_index is None:
            return 0.0
        region = self._panel_region()
        if region.height() <= 0:
            return 0.0
        cursor_ratio = (cursor_scene_y - region.y()) / region.height()
        axis = view.vm.axes[self._vm_axis_index]
        edge_ratio = (
            axis.top_ratio
            if self._zone == AXZONE_GRIP_TOP
            else axis.top_ratio + axis.height_ratio
        )
        return edge_ratio - cursor_ratio

    def _update_axis_drag(self, cursor_scene_y: float) -> None:
        """Track the grabbed grip edge to the cursor (absolute, panel-proportional).

        Called on each intermediate drag event for AXZONE_GRIP_TOP/BOTTOM only.
        ``cursor_scene_y`` is the cursor's scene Y; it maps to a panel-height ratio
        and the dragged edge follows it via ``resize_axis_edge`` (model-B clamps
        still apply). ZOOM/PAN commit at finish, not incrementally.
        """
        view = self._panel_view
        if view is None or self._vm_axis_index is None:
            return
        if self._zone not in (AXZONE_GRIP_TOP, AXZONE_GRIP_BOTTOM):
            return
        region = self._panel_region()
        axis = view.vm.axes[self._vm_axis_index]
        if self._zone == AXZONE_GRIP_TOP:
            edge, current = "top", axis.top_ratio
        else:
            edge, current = "bottom", axis.top_ratio + axis.height_ratio
        delta = grip_resize_delta(
            cursor_scene_y, region.y(), region.height(), self._grip_offset, current
        )
        view.vm.resize_axis_edge(self._vm_axis_index, edge, delta)

    def _finish_axis_drag(self, lx: float, ly: float) -> None:
        """Commit a zoom or pan on drag finish.

        ZOOM: range-select — the two endpoints become the new y_range (VM
        normalises lo/hi order). PAN: the data value that was at the cursor's
        start position is shifted to the end position.
        """
        view = self._panel_view
        if view is None or self._vm_axis_index is None:
            return
        end = self._local_y_to_data(ly, self._drag_h)
        if self._zone == AXZONE_ZOOM:
            view.vm.set_axis_range(self._vm_axis_index, self._drag_start_data, end)
        elif self._zone == AXZONE_PAN:
            rng = view.vm.axes[self._vm_axis_index].y_range or (0.0, 1.0)
            lo, hi = rng
            shift = self._drag_start_data - end
            view.vm.set_axis_range(self._vm_axis_index, lo + shift, hi + shift)

    def mouseDragEvent(self, ev: Any) -> None:
        """Route left-drag by zone: grips → resize, frame → move QDrag,
        inner → zoom, outer → pan.  Only the active axis accepts drag events.

        The base AxisItem.mouseDragEvent only pans a *linked* ViewBox; these
        axes are unlinked so the parent is a safe no-op. Real drag delivery
        (OS → pyqtgraph scene → here) is Layer C; the helper logic (_begin /
        _update / _finish) is verified by the Layer B tests directly.
        """
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        if ev.isStart():
            p = ev.pos()
            if not self._begin_axis_drag(p.x(), p.y()):
                ev.ignore()
                return
            if self._zone == AXZONE_FRAME:
                # Axis-move: launch a QDrag carrying the VM index so the panel's
                # drop sink can relocate the axis. The relayout is applied on the
                # NEXT event-loop turn (GraphPanelView.dropEvent defers it) so the
                # rebuild does not destroy this item while pyqtgraph's scene still
                # holds drag references to it. Verified Layer C only (the blocking
                # drag.exec loop cannot run under the offscreen platform).
                if self._vm_axis_index is not None:
                    view = self._panel_view
                    if view is not None:
                        drag = QDrag(view)
                        drag.setMimeData(
                            encode_axis_move(view._panel_index, self._vm_axis_index)
                        )
                        drag.exec(Qt.DropAction.MoveAction)
                ev.accept()
                return
            if self._zone in (AXZONE_GRIP_TOP, AXZONE_GRIP_BOTTOM):
                # Capture the grab offset so the edge tracks the cursor 1:1 from here.
                self._grip_offset = self._grip_grab_offset(ev.scenePos().y())
        # Grips track the cursor absolutely (scene coords) so the edge follows it 1:1
        # and the axis geometry shifting mid-drag cannot feed back into the delta.
        if self._zone in (AXZONE_GRIP_TOP, AXZONE_GRIP_BOTTOM) and not ev.isStart():
            self._update_axis_drag(ev.scenePos().y())
        # Zoom / pan commit on release (range-select model, not live-preview).
        if ev.isFinish() and self._zone in (AXZONE_ZOOM, AXZONE_PAN):
            p = ev.pos()
            self._finish_axis_drag(p.x(), p.y())
        ev.accept()


class GraphPanelView(QWidget):
    """PyQtGraph waveform view bound to a :class:`GraphPanelVM`."""

    # Panel add/remove are area-level operations; the GraphAreaView wires these
    # to GraphAreaVM (R14.3).
    add_panel_requested = Signal()
    remove_panel_requested = Signal()
    # Emitted on offset-drag release when the user confirms a scope in the apply
    # dialog. The GraphAreaView wires this to GraphAreaVM.apply_offset (R14).
    offset_apply_requested = Signal(str, float, str)
    # Emitted when an axis-move drop targets a different panel (Task 3).
    # Args: source_panel_index, axis_index, col, position (int | None).
    # Uses object so None ("append at end") survives the signal boundary.
    cross_panel_axis_move_requested = Signal(int, int, int, object)
    # PC-07: 左クリックでこのパネルをアクティブに (GraphAreaView が VM へ配線)。
    # 2つの emit 元は排他的なクリック対象をカバーする: プロット領域の press は
    # mousePressEvent に届いて emit し、軸クリックは scene アイテムに accept され
    # 親へ伝播しないので _AlignedAxisItem._emit_panel_activation が emit する。
    # 通常は1回の物理クリックにつき1回だけ発火するが、配送が万一重なっても
    # 購読側 (GraphAreaVM.set_active_panel) が同じ index への再設定を no-op に
    # しており冪等なので安全。
    activate_requested = Signal()

    def __init__(
        self,
        vm: GraphPanelVM,
        parent: QWidget | None = None,
        apply_dialog_fn: Callable[[str, float], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.vm = vm
        self._apply_dialog_fn = apply_dialog_fn
        # Curve items keyed by VM entry_id (a stable per-entry ID), NOT signal_key,
        # so the same signal on two axes draws as two independent items.
        self._items: dict[int, pg.PlotDataItem] = {}
        # Which ViewBox each entry's curve lives in (kept in sync by refresh).
        # Used by the R14 curve hit-test to map candidate data points to scene px.
        self._item_vb: dict[int, pg.ViewBox] = {}
        # entry_id -> signal_key, for legacy signal_key-addressed accessors and for
        # resolving the offset-apply target (offsets apply per signal, not per entry).
        self._item_signal_key: dict[int, str] = {}
        self._y_axes: list[pg.AxisItem] = []
        self._view_boxes: list[pg.ViewBox] = []
        # One empty width-reserving container per occupied column (root col = the
        # column index); it pins the fixed gutter width and supplies that column's
        # X band. AxisItems are scene items positioned over it by
        # _sync_overlay_geometry (no grid row-stretch — that would normalise away
        # blank gaps). Empty until the first _reconcile_axes build.
        self._column_containers: dict[int, QGraphicsWidget] = {}
        # Snapshot of the last-built grid structure (column_count + per-axis
        # column/row placement); lets _reconcile_axes take a fast path that only
        # retunes row stretch + labels when nothing structural changed.
        self._build_signature: tuple[object, ...] = ()
        self._drag_zone: str | None = None
        self._drag_start: QPointF | None = None
        self._drop_active = False
        self._removable = True
        # Global cursor state (R15/R16)
        self._suppress_cursor_signal = False
        # R14 offset-drag transient state (None when no drag is active).
        self._offset_drag_key: int | None = None  # entry_id of the dragged curve
        self._offset_drag_start_x: float | None = None
        self._offset_orig_xy: tuple[Any, Any] | None = None
        self._offset_orig_pen: Any = None
        self._offset_last_delta: float = 0.0
        # Active/hover axis — transient UI state, not persisted to the VM.
        # _active_axis_index: the axis the user last clicked (None = none selected).
        # _hover_axis_index: the axis under the cursor (None = none hovered).
        # Both drive frame/grip repaint in Task 5+; declared here so Task 4 can test
        # them and later tasks wire visuals without touching __init__.
        self._active_axis_index: int | None = None
        self._hover_axis_index: int | None = None
        # Active curve (entry_id) — transient View state, drives thick-pen feedback.
        self._active_curve_id: int | None = None
        # DP16: candidate captured on a curve press until the drag threshold is
        # crossed (entry_id, press position).  None when no candidate is pending.
        self._curve_press_candidate: tuple[int, QPointF] | None = None
        # Panel index within the GraphAreaView (set by _wire_panel via set_panel_index).
        self._panel_index: int = 0
        # Axis-move drag feedback: lazily created, reused per drag, nulled on rebuild.
        self._axis_move_line: QGraphicsLineItem | None = None
        self._axis_move_highlight: QGraphicsRectItem | None = None
        self._axis_move_dimmed_index: int | None = None

        self.plot_widget = pg.GraphicsLayoutWidget()
        # The central layout reserves a fixed-width gutter container in columns
        # 0..N-1 and the plot area in column N (= vm.column_count); the stacked
        # Y-axis spines are scene items drawn over the gutters at absolute strips.
        # _reconcile_axes owns it.
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
        # Forward viewport hover moves to this widget so mouseMoveEvent is reached
        # for zone-cursor updates.  QGraphicsView (plot_widget) fills the panel and
        # its viewport consumes OS mouse-move events; without this filter,
        # GraphPanelView.mouseMoveEvent is never called on no-button moves.
        self.plot_widget.viewport().installEventFilter(self)

        # SH-06: パネル追加/削除の可視アフォーダンス (右クリックメニューと併存)。
        # plot_widget を panel 原点(0,0)に保つため、レイアウト行を確保せず右上に
        # 浮かせる。chrome を上に積むと plot がシフトし、event.position()(パネル空間)
        # と _plot_rect_in_widget/mapToScene(plot_widget 空間)の hit-test が乖離する。
        self._panel_chrome = QWidget(self)
        chrome_layout = QHBoxLayout(self._panel_chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(1)
        add_panel_btn = QToolButton(self._panel_chrome)
        add_panel_btn.setObjectName("add_panel_button")
        add_panel_btn.setText("+")
        add_panel_btn.setToolTip("パネルを追加")
        add_panel_btn.clicked.connect(lambda: self.add_panel_requested.emit())
        chrome_layout.addWidget(add_panel_btn)
        self._remove_panel_button = QToolButton(self._panel_chrome)
        self._remove_panel_button.setObjectName("remove_panel_button")
        self._remove_panel_button.setText("×")  # noqa: RUF001
        self._remove_panel_button.setToolTip("パネルを削除")
        self._remove_panel_button.setEnabled(self._removable)
        self._remove_panel_button.clicked.connect(
            lambda: self.remove_panel_requested.emit()
        )
        chrome_layout.addWidget(self._remove_panel_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot_widget)
        # chrome は plot_widget の上に浮かせる (レイアウト非参加で plot を原点に保つ)。
        self._panel_chrome.raise_()
        self._position_panel_chrome()

        # PC-07: アクティブパネル枠。chrome と同じく overlay (レイアウト非参加) で
        # plot_widget を原点 (0,0) に保つ。WA_TransparentForMouseEvents で
        # ゾーン hit-test に一切干渉しない。色はアクティブ軸 amber (#f59e0b) と同系。
        self._active_frame = QFrame(self)
        self._active_frame.setObjectName("active_panel_frame")
        self._active_frame.setStyleSheet(
            "#active_panel_frame {"
            " border: 1px solid #f59e0b; border-radius: 2px; background: transparent; }"
        )
        self._active_frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._active_frame.setGeometry(self.rect())
        self._active_frame.setVisible(False)

        unsubscribe = self.vm.subscribe(self._on_vm_change)
        self._unsubscribe = unsubscribe
        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        self.destroyed.connect(lambda *_: unsubscribe())

        self.refresh()

        # ── Global cursor (R15) ──────────────────────────────────────────────
        from valisync.gui.views.cursor_readout import CursorReadout

        # A (global) amber solid + B (delta) blue dashed.  Both are created,
        # z-ordered, attached and drag-wired identically (only pen + handler
        # differ) via _make_cursor_line, and re-attached together on every axis
        # rebuild via _cursor_lines.
        self._cursor_line = self._make_cursor_line(
            pg.mkPen("#f9e2af", width=2), self._on_cursor_line_dragged
        )
        self._cursor_line_b = self._make_cursor_line(
            pg.mkPen("#89b4fa", width=2, style=Qt.PenStyle.DashLine),
            self._on_cursor_line_b_dragged,
        )
        self._readout = CursorReadout(self)
        self._readout.setVisible(False)
        # Wire stat-column toggle to VM so VM is the source of truth (spec §7).
        # The lambda captures vm_ref to avoid a strong __self__ cycle through self.
        vm_ref = self.vm

        def _on_stat_toggled(col: str, on: bool) -> None:
            cols = set(vm_ref.visible_stat_cols)
            if on:
                cols.add(col)
            else:
                cols.discard(col)
            vm_ref.set_visible_stats(cols)

        self._readout._on_stat_toggled = _on_stat_toggled
        # Track whether the readout has been placed at (8,8) for the current cursor
        # session, so subsequent syncs don't snap a user-dragged readout back to
        # the corner.  Reset to False whenever the readout is hidden (cursor cleared).
        self._readout_placed: bool = False
        # ClickFocus so keyPressEvent (Escape during offset drag) reaches us; the
        # offset drag always begins with a click, so focus is guaranteed then.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # ─── Rendering ─────────────────────────────────────────────────────────────

    def _on_vm_change(self, change: str) -> None:
        if change in ("cursor", "delta"):
            self._sync_cursor_from_vm()
            return
        self.refresh()

    def refresh(self) -> None:
        """Re-project vm.render_data() onto the plot, reconciling multiple axes."""
        # 1. Reconcile Y-axes and ViewBoxes
        self._reconcile_axes()

        # 2. Get render curves from VM
        curves = self.vm.render_data()
        desired = {c.entry_id: c for c in curves}

        # 3. Drop curves no longer present
        for eid in list(self._items):
            if eid not in desired:
                item = self._items.pop(eid)
                self._item_vb.pop(eid, None)
                self._item_signal_key.pop(eid, None)
                # Find which ViewBox it was in and remove it
                for vb in self._view_boxes:
                    if item in vb.addedItems:
                        vb.removeItem(item)
                        break

        # 4. Add or update remaining curves
        for curve in curves:
            item = self._items.get(curve.entry_id)
            if item is None:
                item = pg.PlotDataItem(name=curve.name)
                self._items[curve.entry_id] = item

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
            self._item_vb[curve.entry_id] = target_vb
            self._item_signal_key[curve.entry_id] = curve.name

            item.setData(curve.timestamps, curve.values)
            width = 2.5 if curve.entry_id == self._active_curve_id else 1.0
            item.setPen(pg.mkPen(curve.color, width=width))

        # R14: if a curve was rebuilt mid-offset-drag, keep the preview consistent.
        if self._offset_drag_key is not None:
            if self._offset_drag_key not in self._items:
                self._cancel_offset_drag()  # active waveform removed (§9)
            elif self._offset_orig_xy is not None:
                orig_xs, orig_ys = self._offset_orig_xy
                self._items[self._offset_drag_key].setData(
                    orig_xs + self._offset_last_delta, orig_ys
                )

        # 5. Update geometry and ranges
        # The overlaid secondary ViewBoxes must track the master's plot rect on
        # every render (the layout reflows the master after axis changes).
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

        # Re-attach BOTH cursor lines to the (possibly rebuilt) master ViewBox
        # BEFORE syncing, so _sync_cursor_from_vm() (which sets A/B value+visibility)
        # runs against attached lines — A and B symmetric.  Guard against a deleted
        # C++ object (can happen if _reconcile_axes failed to detach a line before
        # ci.clear() destroyed its parent ViewBox).
        if self._view_boxes:
            for line in self._cursor_lines():
                with contextlib.suppress(RuntimeError):
                    # Defensive: scene() raises on an already-dead C++ line; skip it
                    # (lines are normally kept alive by the scene-detach above).
                    if line.scene() is None:
                        self._view_boxes[0].addItem(line, ignoreBounds=True)
            if hasattr(self, "_cursor_line"):
                with contextlib.suppress(RuntimeError):
                    # Defensive: skip sync if a cursor line's C++ object is dead.
                    self._sync_cursor_from_vm()

    def _sync_overlay_geometry(self) -> None:
        """Align secondary ViewBoxes AND axis spines to absolute region strips.

        Region i (column c, top t, height h) occupies the strip
        [R.y()+t*R.height(), h*R.height()] of the master plot rect R (so a region
        sum < 1.0 leaves a genuine blank band — no normalization). X comes from the
        column container so spines sit in their gutter. Called on refresh and on the
        master's sigResized, so geometry follows window resizes.
        """
        if not self._view_boxes:
            return
        R = self._view_boxes[0].sceneBoundingRect()
        for vb in self._view_boxes[1:]:
            vb.setGeometry(R)
        for i, axis_vm in enumerate(self.vm.axes):
            container = self._column_containers.get(axis_vm.column)
            if container is None:
                continue
            band = container.sceneBoundingRect()
            strip = QRectF(
                band.x(),
                R.y() + axis_vm.top_ratio * R.height(),
                band.width(),
                axis_vm.height_ratio * R.height(),
            )
            self._y_axes[i].setGeometry(strip)

        # 幾何変化(軸/カラム追加・リサイズ)後も readout をプロット矩形へ追従させる。
        # _reposition_readout 内で was_user_moved を尊重。init 中の最初の refresh は
        # _readout 未生成なので getattr ガードで skip する。
        if getattr(self, "_readout_placed", False) and not self._readout.isHidden():
            self._reposition_readout()

    def _axis_placement(self) -> list[tuple[int, int, int]]:
        """Map each VM axis to ``(vm_index, column, rank*2)``.

        Within a column, axes are ranked top→bottom by ``top_ratio`` (mirroring
        the VM's ``_col`` helper). The third element encodes the vertical rank
        (``rank * 2``, kept for signature stability); it feeds the rebuild
        signature and the occupied-column set — axes are no longer placed into
        grid rows, but positioned at absolute strips by ``_sync_overlay_geometry``.
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
        """Reconcile AxisItems and ViewBoxes with the VM's axes/columns.

        Each occupied column reserves a fixed-width container (root col = the
        axis's column); the plot ViewBox container occupies root col =
        ``column_count`` and every lower column reserves fixed Y-axis width, so
        empty columns stay as drop-target gutters. AxisItems are scene items
        (not grid-managed) positioned at absolute region strips by
        ``_sync_overlay_geometry`` — this is what lets a region sum < 1.0 render a
        genuine blank band instead of being normalised to fill the column.

        The ViewBox overlay model is unchanged: ``_view_boxes[0]`` is the
        layout-managed master and the rest are scene items kept aligned to it by
        ``_sync_overlay_geometry``; ``_view_boxes[i]``/``_y_axes[i]`` stay paired
        with ``vm.axes[i]`` so ``refresh()``'s index mapping still holds.
        """
        placement = self._axis_placement()
        signature = (self.vm.column_count, tuple(sorted(placement)))

        # Fast path: column grouping and vertical order are identical, so only
        # height_ratio/labels could have changed (e.g. a resize gesture). Retune
        # labels in place instead of rebuilding. The new height_ratio/top_ratio are
        # applied by _sync_overlay_geometry(), which refresh() calls right after
        # this returns: it repositions every spine and ViewBox to the live absolute
        # strips (no grid row-stretch).
        if self._column_containers and signature == self._build_signature:
            for i, _col, _row in placement:
                axis_vm = self.vm.axes[i]
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

        # Secondary ViewBoxes and AxisItems live straight in the scene (so
        # waveforms draw unclipped and spines sit at absolute strips), so
        # ci.clear() — which only drops layout-managed items — leaves them behind
        # as orphans that keep drawing stale curves/ticks. Remove them explicitly
        # first. (The master ViewBox, column containers, and X-axis are
        # layout-managed, so ci.clear() drops those.)
        for vb in self._view_boxes[1:]:
            scene = vb.scene()
            if scene is not None:
                scene.removeItem(vb)
        for axis in self._y_axes:
            axis_scene = axis.scene()
            if axis_scene is not None:
                axis_scene.removeItem(axis)
        # The cursor line is added to the master ViewBox (layout-managed); removing
        # it from the ViewBox before ci.clear() prevents the C++ object from being
        # destroyed by the layout teardown. The line is re-attached to the new
        # master ViewBox at the end of refresh().
        if self._view_boxes:
            for line in self._cursor_lines():
                with contextlib.suppress(RuntimeError):
                    # Detach the line from the dying ViewBox/scene BEFORE ci.clear()
                    # destroys it; otherwise the line is a child of the destroyed
                    # ViewBox and its C++ object dies with it (cursor vanishes on an
                    # axis-structure rebuild).  These lines are added with
                    # ignoreBounds and are not reliably tracked in addedItems, so
                    # fall back to scene-level removal — refresh() re-attaches them.
                    if line in self._view_boxes[0].addedItems:
                        self._view_boxes[0].removeItem(line)
                    else:
                        scene = line.scene()
                        if scene is not None:
                            scene.removeItem(line)
        self.plot_widget.ci.clear()
        self._y_axes.clear()
        self._view_boxes.clear()
        self._items.clear()  # Clear items to force re-adding to new ViewBoxes
        self._item_vb.clear()  # No stale ViewBox refs after rebuild (spec §R14)
        self._item_signal_key.clear()
        self._column_containers = {}

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

        # One empty width-reserving container per occupied column, in its matching
        # root column. It pins the fixed gutter width (so removing the axes from
        # the grid doesn't collapse the column and let the plot slide left) and
        # supplies that column's X band for _sync_overlay_geometry.
        for col in sorted({c for _, c, _ in placement}):
            container = QGraphicsWidget()
            container.setMaximumWidth(_Y_AXIS_FIXED_WIDTH)
            self.plot_widget.addItem(container, row=0, col=col)
            self._column_containers[col] = container

        # Create ViewBoxes + AxisItems in VM order so _view_boxes[i]/_y_axes[i]
        # stay paired with vm.axes[i]; AxisItems are scene items positioned at
        # absolute strips by _sync_overlay_geometry (NOT grid-managed).
        master_vb: pg.ViewBox | None = None
        for i, axis_vm in enumerate(self.vm.axes):
            vb = pg.ViewBox()
            vb.setMouseEnabled(x=False, y=False)
            vb.disableAutoRange()
            # Suppress pyqtgraph's default right-click "Plot Options" menu so the
            # panel's own contextMenuEvent wins on a real OS right-click. Applied
            # to every ViewBox (master + secondary overlays) so a right-click on
            # any axis region raises the panel menu, not pyqtgraph's.
            vb.setMenuEnabled(False)
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
            # Tighten the bounding rect to the spine strip: by default pyqtgraph
            # pads it 15px above/below to reserve room for labels that overflow the
            # ends, which would make a region's painted rect overlap its neighbour
            # (and the blank gap). With absolute strips we want the spine to occupy
            # exactly its region, and overlapping tick labels in short regions are
            # better hidden than allowed to bleed across the gap.
            axis.setStyle(hideOverlappingLabels=True)
            # Tag the axis with its VM index so a drag from it carries that index,
            # and wire the panel view reference so click events reach set_active_axis.
            axis.set_vm_axis_index(i)
            axis.set_panel_view(self)
            if axis_vm.name or axis_vm.unit:
                axis.setLabel(text=axis_vm.name or None, units=axis_vm.unit or None)
            self._y_axes.append(axis)

            # Add the axis straight to the scene (like the secondary ViewBoxes);
            # _sync_overlay_geometry sets its absolute strip geometry. Adding it to
            # a grid sub-layout would normalise the column and erase blank gaps.
            self.plot_widget.scene().addItem(axis)

        # The VM always holds at least one axis, so the master ViewBox is set.
        assert master_vb is not None
        # Add X-axis at the bottom of the plot column (Row 1).
        self.plot_widget.addItem(self._x_axis, row=1, col=column_count)
        self._x_axis.linkToView(master_vb)
        # Keep overlays aligned when the window (and thus the master) resizes
        # without a VM change, since refresh() is not called in that case.
        master_vb.sigResized.connect(self._sync_overlay_geometry)
        self._build_signature = signature

    # ─── Active-axis state (Task 4) ────────────────────────────────────────────

    def set_active_axis(self, index: int | None) -> None:
        """Set/clear the active axis (transient UI state) and repaint frames.

        Transient: this state is never propagated to the VM.  It drives the
        active-frame highlight (Task 5) and the gesture dispatcher's axis
        selection (Task 6).  Calling with the already-active index is a no-op
        so callers need not guard against repeated events.
        """
        if index == self._active_axis_index:
            return
        self._active_axis_index = index
        for ax in self._y_axes:
            ax.update()  # repaint frame/grips for each axis spine

    def active_curve_id(self) -> int | None:
        """Return the currently active curve's entry_id (None if none)."""
        return self._active_curve_id

    def _activate_curve(self, entry_id: int) -> None:
        """Make *entry_id* the active curve: thick pen + activate its axis too.

        Per spec §2 the curve's axis is activated alongside so the amber frame
        and the thick curve always point at the same axis.  refresh() is the
        authoritative re-pen (applies width 2.5 to the active entry).
        """
        self._active_curve_id = entry_id
        axis = self.vm.axis_of_entry(entry_id)
        if axis is not None:
            self.set_active_axis(axis)
        self.refresh()

    def _deactivate_curve(self) -> None:
        """Clear the active curve (another target was clicked) and un-thicken it."""
        if self._active_curve_id is None:
            return
        self._active_curve_id = None
        self.refresh()

    def set_hover_axis(self, index: int | None) -> None:
        """Set/clear the hovered axis (transient UI state) and repaint frames.

        Mirrors ``set_active_axis``: transient, never propagated to the VM.
        Called by ``_AlignedAxisItem.hoverMoveEvent``/``hoverLeaveEvent`` when
        the cursor enters or leaves a spine.  No-op if already at the same index.
        """
        if index == self._hover_axis_index:
            return
        self._hover_axis_index = index
        for ax in self._y_axes:
            ax.update()  # repaint hover frame for each axis spine

    # ─── Test/introspection surface ────────────────────────────────────────────

    def axis_columns(self) -> list[int]:
        """Return the sorted root grid columns that are currently occupied.

        Same public semantics as before (occupied gutter columns); the backing
        store is now the per-column width-reserving containers.
        """
        return sorted(self._column_containers)

    def plot_grid_column(self) -> int:
        """Return the root grid column reserved for the plot ViewBox container."""
        return self.vm.column_count

    def curve_keys(self) -> list[int]:
        """Return the entry_ids of the curves currently drawn, in draw order."""
        return list(self._items)

    def curve_xy(self, entry_id: int) -> tuple[object, object]:
        """Return the (x, y) arrays currently set on *entry_id*'s curve."""
        return self._items[entry_id].getData()

    def pen_color(self, entry_id: int) -> str:
        """Return the hex colour of *entry_id*'s curve pen (e.g. ``#1f77b4``)."""
        return pg.mkPen(self._items[entry_id].opts["pen"]).color().name()

    def pen_width(self, entry_id: int) -> float:
        """Return the pen width of *entry_id*'s curve (active curve = 2.5)."""
        return float(pg.mkPen(self._items[entry_id].opts["pen"]).widthF())

    def is_clipped(self, entry_id: int) -> bool:
        """Return whether *entry_id*'s curve is clipped to its ViewBox."""
        return bool(self._items[entry_id].opts.get("clipToView", False))

    # ── signal_key resolution helpers (drawn curves are entry_id-addressed) ──
    def entry_id_for(self, signal_key: str) -> int:
        """Resolve the first drawn entry_id with *signal_key* (raises KeyError if none).

        Curves are addressed by entry_id; callers that only know a signal_key
        (tests, signal-level membership) resolve through here.  First-match is
        exact when a signal_key is drawn once, which is the common case.
        """
        for eid, sk in self._item_signal_key.items():
            if sk == signal_key:
                return eid
        raise KeyError(signal_key)

    def signal_keys_drawn(self) -> list[str]:
        """Return the signal_keys of the drawn curves, in draw order (may repeat)."""
        return [self._item_signal_key[eid] for eid in self._items]

    # ─── Global cursor (R15) + Delta cursor (R16) ────────────────────────────────

    def _make_cursor_line(self, pen: Any, on_dragged: Any) -> Any:
        """Create a hidden, draggable vertical cursor line on the master ViewBox.

        Shared by the A (global) and B (delta) lines so their creation, z-order,
        attach and drag-wiring stay identical — only pen and handler differ.
        """
        line = pg.InfiniteLine(angle=90, movable=True, pen=pen)
        line.setVisible(False)
        line.setZValue(10)
        # PC-22: 水平ドラッグ可のアフォーダンス(色ハイライトに加えポインタ形状も変える)。
        line.setCursor(cursor(CursorKind.DRAG_H))
        if self._view_boxes:
            self._view_boxes[0].addItem(line, ignoreBounds=True)
        line.sigPositionChanged.connect(on_dragged)
        return line

    def _cursor_lines(self) -> list[Any]:
        """Existing A/B cursor InfiniteLines, in creation order (attach/detach)."""
        return [
            getattr(self, name)
            for name in ("_cursor_line", "_cursor_line_b")
            if hasattr(self, name)
        ]

    def _plot_area_top_left(self) -> QPoint | None:
        """プロット描画領域(master ViewBox)の左上を GraphPanelView 座標で返す。

        レイアウト未確定(ViewBox 無し)や破棄済み C++ オブジェクトなら None。
        """
        if not self._view_boxes:
            return None
        try:
            scene_tl = self._view_boxes[0].sceneBoundingRect().topLeft()
            view_pt = self.plot_widget.mapFromScene(scene_tl)
            global_pt = self.plot_widget.viewport().mapToGlobal(view_pt)
            return self.mapFromGlobal(global_pt)
        except RuntimeError:
            return None

    def _reposition_readout(self) -> None:
        """readout をプロット矩形左上+マージンへ移動(ユーザードラッグ位置は尊重・PC-21)。"""
        if self._readout.was_user_moved():
            return
        tl = self._plot_area_top_left()
        if tl is None:
            return
        self._readout.move(tl.x() + 8, tl.y() + 8)

    def _sync_cursor_from_vm(self) -> None:
        """Reflect A/B cursor + readout from full VM state."""
        t = self.vm.cursor_t
        if t is None:
            self._cursor_line.setVisible(False)
            self._cursor_line_b.setVisible(False)
            self._readout.setVisible(False)
            self._readout_placed = False
            self._readout.reset_user_moved()
            return
        self._suppress_cursor_signal = True
        try:
            self._cursor_line.setValue(t)
            if self.vm.cursor_t_b is not None:
                self._cursor_line_b.setValue(self.vm.cursor_t_b)
        finally:
            # Always clear the echo-guard, even if setValue raises on a deleted
            # C++ object during a rebuild, so it can never stick True.
            self._suppress_cursor_signal = False
        self._cursor_line.setVisible(True)
        if self.vm.delta_enabled and self.vm.cursor_t_b is not None:
            self._cursor_line_b.setVisible(True)
            # Push VM's visible_stat_cols into the readout before rendering so
            # the VM is the single source of truth (spec §7).
            self._readout.sync_visible_stats(self.vm.visible_stat_cols)
            self._readout.set_delta(t, self.vm.cursor_t_b, self.vm.delta_readings())
        else:
            self._cursor_line_b.setVisible(False)
            self._readout.set_global(t, self.vm.cursor_readings())
        if not self._readout_placed:
            # 初回表示時にプロット矩形左上へ配置(以降のカーソル同期では
            # ユーザーがドラッグ移動した位置を乱さない)。
            self._reposition_readout()
            self._readout_placed = True
        self._readout.setVisible(True)
        self._readout.raise_()

    def _on_cursor_line_dragged(self) -> None:
        if self._suppress_cursor_signal:
            return
        self.vm.set_cursor(float(self._cursor_line.value()))

    def _on_cursor_line_b_dragged(self) -> None:
        if self._suppress_cursor_signal:
            return
        self.vm.set_cursor_b(float(self._cursor_line_b.value()))

    # Test introspection
    def cursor_line_visible(self) -> bool:
        return bool(self._cursor_line.isVisible())

    def cursor_line_value(self) -> float:
        return float(self._cursor_line.value())

    def delta_line_visible(self) -> bool:
        return bool(self._cursor_line_b.isVisible())

    def delta_line_value(self) -> float:
        return float(self._cursor_line_b.value())

    def readout_visible(self) -> bool:
        # isVisible() depends on ancestors being shown; isHidden() checks only
        # this widget's own flag, so the test can work without show().
        return not self._readout.isHidden()

    # ─── Gesture application (data-coordinate; the zoom/pan contract) ───────────

    def apply_zone_drag(self, zone: str, start_value: float, end_value: float) -> None:
        """Apply a drag in *zone*: inner = range-select zoom, outer = pan.

        Only X zones are handled here; Y zoom/pan is owned by _AlignedAxisItem (Task 8).
        """
        if zone == ZONE_X_INNER:
            self.vm.set_x_range(*ordered_pair(start_value, end_value))
        elif zone == ZONE_X_OUTER and self.vm.x_range is not None:
            lo, hi = self.vm.x_range
            self.vm.set_x_range(*pan_range(lo, hi, start_value - end_value))

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
        """Identify which Y-axis is at *pos*.

        The cursor's COLUMN is resolved first (same band math as
        ``_axis_drop_target``); only axes in that column are then matched on the
        vertical band. Without the column filter an outer-column axis that spans
        the full height (band ``[0, 1]``) would match every ``y_rel`` and steal
        drops/zoom gestures aimed at the inner column.
        """
        if not self._y_axes:
            return 0

        col = max(0, min(int(pos.x() // _Y_AXIS_FIXED_WIDTH), self.vm.column_count - 1))
        plot_rect = self._plot_rect_in_widget()
        y_rel = (pos.y() - plot_rect.top()) / plot_rect.height()

        for i, axis_vm in enumerate(self.vm.axes):
            if axis_vm.column == col and (
                axis_vm.top_ratio <= y_rel <= axis_vm.top_ratio + axis_vm.height_ratio
            ):
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

    def _curve_at(self, pos: QPointF) -> int | None:
        """Return the entry_id of the nearest curve within CURVE_HIT_TOL_PX of *pos*.

        Returns None when *pos* is within CURSOR_LINE_HIT_PX of a visible cursor
        line (priority: cursor line > curve, §4) or when no curve is close enough.
        Distance is measured in scene pixels via each item's own ViewBox, so the
        check is correct under multi-axis layouts and any LOD level. entry_id (not
        signal_key) so duplicate signals on different axes are distinguishable.
        """
        if not self._view_boxes or not self._items:
            return None
        try:
            scene_pos = self.plot_widget.mapToScene(pos.toPoint())
        except Exception:
            return None

        # Cursor-line guard: yield to a nearby visible cursor line.
        vb0 = self._view_boxes[0]
        for line in self._cursor_lines():
            try:
                if not line.isVisible():
                    continue
                line_scene_x = vb0.mapViewToScene(QPointF(float(line.value()), 0.0)).x()
            except Exception:
                continue
            if abs(scene_pos.x() - line_scene_x) <= CURSOR_LINE_HIT_PX:
                return None

        best_key: int | None = None
        best_dist = CURVE_HIT_TOL_PX
        for eid, item in self._items.items():
            vb = self._item_vb.get(eid)
            if vb is None:
                continue
            xs, ys = item.getData()
            if xs is None or len(xs) == 0:
                continue
            data_x = vb.mapSceneToView(scene_pos).x()
            idx = int(np.searchsorted(xs, data_x))
            for cand in (idx - 1, idx):
                if cand < 0 or cand >= len(xs):
                    continue
                cand_scene = vb.mapViewToScene(
                    QPointF(float(xs[cand]), float(ys[cand]))
                )
                dx = scene_pos.x() - cand_scene.x()
                dy = scene_pos.y() - cand_scene.y()
                dist = (dx * dx + dy * dy) ** 0.5
                if dist <= best_dist:
                    best_dist = dist
                    best_key = eid
        return best_key

    # ─── R14 offset drag ────────────────────────────────────────────────────────

    def _begin_offset_drag(self, entry_id: int, pos: QPointF) -> None:
        """Activate offset drag on *entry_id*: capture origin, highlight, set cursor."""
        start_x = self._data_value(pos, "x")
        if start_x is None:
            return
        item = self._items[entry_id]
        xs, ys = item.getData()
        self._offset_drag_key = entry_id
        self._offset_drag_start_x = start_x
        self._offset_orig_xy = (np.asarray(xs).copy(), np.asarray(ys).copy())
        self._offset_orig_pen = item.opts.get("pen")
        self._offset_last_delta = 0.0
        # Highlight the active waveform (wider pen, same colour) per §12.
        cur_color = pg.mkPen(item.opts["pen"]).color().name()
        item.setPen(pg.mkPen(cur_color, width=3))
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        # A real OS drag delivers MOVE events to the child GraphicsLayoutWidget
        # (a QGraphicsView), not to this parent QWidget — only the press/release
        # propagate up.  Without an explicit grab the move-driven preview never
        # runs and the gesture commits Δt=0.  Grab so move/release route here;
        # _end_offset_drag / _reset_offset_state release it on every exit.
        self.grabMouse()

    def _update_offset_preview(self, pos: QPointF, global_pos: QPointF) -> None:
        """Shift the active curve by Δt = current_x - start_x and show the tooltip."""
        key = self._offset_drag_key
        if key is None or key not in self._items or self._offset_orig_xy is None:
            self._cancel_offset_drag()
            return
        cur_x = self._data_value(pos, "x")
        if cur_x is None or self._offset_drag_start_x is None:
            return
        delta_t = cur_x - self._offset_drag_start_x
        self._offset_last_delta = delta_t
        orig_xs, orig_ys = self._offset_orig_xy
        self._items[key].setData(orig_xs + delta_t, orig_ys)
        QToolTip.showText(global_pos.toPoint(), f"Δt = {delta_t:+.3g} s")

    def _end_offset_drag(self) -> None:
        """On release: stop tracking and defer the apply dialog (avoid exec in handler)."""
        key = self._offset_drag_key
        delta_t = self._offset_last_delta
        if key is None:
            return
        # Release the grab before the (deferred) modal so the dialog can take mouse
        # input; the drag itself is over.  _reset_offset_state also releases for the
        # Escape / curve-removed paths that never reach here.
        self.releaseMouse()
        # Defer so QDialog.exec() does not run inside the mouse-event handler
        # (mirrors the axis-move deferred-drop pattern; avoids stale-scene hangs).
        QTimer.singleShot(0, lambda: self._finish_offset(key, delta_t))

    def _finish_offset(self, entry_id: int, delta_t: float) -> None:
        """Show the apply dialog and emit / cancel based on the chosen scope."""
        if entry_id not in self._items:
            self._reset_offset_state()
            return
        signal_key = self._item_signal_key.get(entry_id)
        if signal_key is None:
            self._reset_offset_state()
            return
        fn = self._apply_dialog_fn or self._default_apply_dialog
        scope = fn(signal_key, delta_t)
        if scope in ("signal", "group"):
            # Clear the drag state BEFORE emitting.  The emit synchronously drives
            # the offsets broadcast → this panel's refresh(); if _offset_drag_key
            # were still set, the mid-drag guard there would re-apply the full
            # (unclipped) preview data over the VM's authoritative clipped render,
            # desyncing the dragged panel from broadcast-only panels.  restore_data
            # is False: the broadcast refresh repaints from the committed offset.
            self._reset_offset_state(restore_data=False)
            self.offset_apply_requested.emit(signal_key, delta_t, scope)
        else:
            self._cancel_offset_drag()

    def _cancel_offset_drag(self) -> None:
        """Discard the preview, restore original data + pen, clear state (R14.7/8)."""
        self._reset_offset_state(restore_data=True)

    def _reset_offset_state(self, restore_data: bool = True) -> None:
        key = self._offset_drag_key
        if key is not None and key in self._items:
            if restore_data and self._offset_orig_xy is not None:
                self._items[key].setData(*self._offset_orig_xy)
            if self._offset_orig_pen is not None:
                self._items[key].setPen(self._offset_orig_pen)
        QToolTip.hideText()
        self._offset_drag_key = None
        self._offset_drag_start_x = None
        self._offset_orig_xy = None
        self._offset_orig_pen = None
        self._offset_last_delta = 0.0
        # Restore the default cursor so the SizeHorCursor set by _begin_offset_drag
        # does not linger through the apply dialog or into the next mouse move.
        self.unsetCursor()
        # Release the mouse grab taken in _begin_offset_drag.  Safe to call when not
        # holding it (Qt no-ops); covers the Escape / curve-removed cancel paths
        # that bypass _end_offset_drag.
        self.releaseMouse()

    def _default_apply_dialog(self, signal_key: str, delta_t: float) -> str | None:
        """Modal apply dialog: 'signal' / 'group' / None (cancel). Enter → signal."""
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QRadioButton,
            QVBoxLayout,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("時間オフセットの適用")
        lay = QVBoxLayout(dlg)
        lay.addWidget(
            QLabel(f"Δt = {delta_t:+.3g} s を適用します。対象を選択してください。")
        )
        sig_radio = QRadioButton("この信号のみ")
        grp_radio = QRadioButton("同じファイルグループ全体")
        sig_radio.setChecked(True)  # default → Enter applies signal scope
        lay.addWidget(sig_radio)
        lay.addWidget(grp_radio)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setDefault(True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return "signal" if sig_radio.isChecked() else "group"

    # ─── Mouse handlers — X zoom/pan + R14 offset drag ──────────────────────────

    def _hover_cursor(self, pos: QPointF) -> CursorKind:
        """Hover cursor kind for a panel-local point.

        Plot area over an offset-draggable curve -> DRAG_H (SizeHor) so the
        offset gesture is discoverable and not a surprise; otherwise the X-zone
        cursor. Y zones are owned by _AlignedAxisItem (ARROW here).
        """
        zone = self._zone_at(pos)
        if zone == ZONE_PLOT and self._curve_at(pos) is not None:
            return CursorKind.DRAG_H
        return cursor_for_zone(zone)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Only the left button drives X zoom/pan; right-click opens the context
        # menu and must not start a drag gesture.  Y zoom/pan is owned by
        # _AlignedAxisItem (Task 8) so only X zones start a widget-level drag.
        if event.button() == Qt.MouseButton.LeftButton:
            self.activate_requested.emit()  # PC-07: どのゾーンでも押下=活性化
            zone = self._zone_at(event.position())
            if zone in (ZONE_X_INNER, ZONE_X_OUTER):
                self._deactivate_curve()  # X zone is a different target -> deactivate
                self._drag_zone = zone
                self._drag_start = event.position()
            elif zone == ZONE_PLOT:
                eid = self._curve_at(event.position())
                if eid is not None:
                    # DP16: a press does not begin the drag immediately -- it is held
                    # as a candidate until a move exceeds startDragDistance (promote
                    # to offset drag) or release arrives within the threshold
                    # (activate).  The child QGraphicsView consumes moves while the
                    # mouse is down, so the parent needs an explicit grab here to
                    # observe them at all (released on activation/escape/drag end).
                    self._curve_press_candidate = (eid, event.position())
                    self.grabMouse()
                else:
                    self._deactivate_curve()  # empty-plot click -> deactivate
            else:
                self._deactivate_curve()
        super().mousePressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Forward no-button viewport moves to this widget's zone-cursor logic.

        plot_widget (QGraphicsView) fills the entire panel; its viewport receives
        OS hover moves and does NOT propagate them to GraphPanelView.mouseMoveEvent.
        This filter intercepts those moves and updates the panel cursor so the
        SizeHorCursor appears when the user hovers the X-axis strip.

        Only the no-button hover path is handled here; press/drag events continue
        to reach mousePressEvent / mouseReleaseEvent normally (Qt delivers press
        and release to the parent when no grabMouse is active).
        """
        if (
            watched is self.plot_widget.viewport()
            and isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseMove
            and event.buttons() == Qt.MouseButton.NoButton
            and self._drag_zone is None
        ):
            pos_in_panel = self.plot_widget.viewport().mapTo(
                self, event.position().toPoint()
            )
            self.setCursor(cursor(self._hover_cursor(QPointF(pos_in_panel))))
        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._curve_press_candidate is not None:
            eid, start = self._curve_press_candidate
            moved = (event.position() - start).manhattanLength()
            if moved >= QApplication.startDragDistance():
                self._curve_press_candidate = None  # promoted -> candidate discarded
                self._begin_offset_drag(eid, start)
                self._update_offset_preview(event.position(), event.globalPosition())
            super().mouseMoveEvent(event)
            return
        if self._offset_drag_key is not None:
            self._update_offset_preview(event.position(), event.globalPosition())
            super().mouseMoveEvent(event)
            return
        if self._drag_zone is None:
            self.setCursor(cursor(self._hover_cursor(event.position())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._curve_press_candidate is not None:
            eid, _ = self._curve_press_candidate
            self._curve_press_candidate = None
            self.releaseMouse()  # release the grab taken on press
            self._activate_curve(eid)  # within threshold -> activate
            super().mouseReleaseEvent(event)
            return
        if self._offset_drag_key is not None:
            self._end_offset_drag()
            super().mouseReleaseEvent(event)
            return
        if self._drag_zone is not None and self._drag_start is not None:
            # _drag_zone can only be an X zone (Y zoom/pan moved to _AlignedAxisItem).
            axis = "x"
            start = self._data_value(self._drag_start, axis)
            end = self._data_value(event.position(), axis)
            if start is not None and end is not None:
                self.apply_zone_drag(self._drag_zone, start, end)
        self._drag_zone = None
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._curve_press_candidate is not None:
                self._curve_press_candidate = None
                self.releaseMouse()
                event.accept()
                return
            if self._offset_drag_key is not None:
                self._cancel_offset_drag()
                event.accept()
                return
        if event.key() == Qt.Key.Key_H:
            aid = self._active_curve_id
            # active curve が非表示中でも entry として存在すれば再表示できる
            # (非表示曲線はクリック不可のため H の対象として維持する・spec §10)。
            if aid is not None and self.vm.signal_key_for_entry(aid) is not None:
                self.vm.toggle_entry_visibility(aid)
            elif self._active_axis_index is not None:
                self.vm.toggle_axis_visibility(self._active_axis_index)
            event.accept()
            return
        super().keyPressEvent(event)

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
            decoded_move = decode_axis_move(md)
            if decoded_move is not None:
                _, axis_index = decoded_move
                self._update_axis_move_feedback(axis_index, event.position())
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_highlight(False)
        self._clear_axis_move_feedback()
        super().dragLeaveEvent(event)

    def _apply_deferred_axis_move(
        self, axis_index: int, col: int, position: int | None
    ) -> None:
        """Apply a deferred axis-move and clear pyqtgraph's stale scene state.

        Runs one event-loop turn after the drop (see ``dropEvent``), so the QDrag
        and its queued mouse events have fully unwound before the rebuild destroys
        the old axis items.  The rebuild then replaces every axis item, so we drop
        the scene's press/drag/hover bookkeeping (which still points at the old,
        now-deleted items) — otherwise the next gesture is misrouted to a dead item.
        """
        self.vm.move_axis_to_column(axis_index, col, position)
        reset_scene_drag_state(self.plot_widget.scene())

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_highlight(False)

        # Axis-move drop: relocate an existing axis to the target column/position.
        # Checked BEFORE signal-key handling so the two gestures never overlap;
        # only fires when the drag actually carried an axis index.
        decoded = decode_axis_move(event.mimeData())
        if decoded is not None:
            source_panel_index, axis_index = decoded
            col, position = self._axis_drop_target(event.position())
            self._clear_axis_move_feedback()
            event.acceptProposedAction()
            # Defer the relayout off the QDrag's modal call stack. Applying it here
            # (inside drag.exec) rebuilds the axis items while pyqtgraph's scene
            # still holds press/drag/hover references to the drag's source item, so
            # the next gesture is delivered to that destroyed item — the first
            # resize/move after a move broke (no-op, or a re-entrant QDrag hang).
            # Running it on the next event-loop turn lets the drag fully unwind.
            if source_panel_index == self._panel_index:
                # Same panel → existing within-panel reorder (unchanged).
                QTimer.singleShot(
                    0, lambda: self._apply_deferred_axis_move(axis_index, col, position)
                )
            else:
                # Cross-panel → ask GraphArea to relocate (deferred off the QDrag
                # modal stack, same C2 reason as the within-panel path).
                QTimer.singleShot(
                    0,
                    lambda: self.cross_panel_axis_move_requested.emit(
                        source_panel_index, axis_index, col, position
                    ),
                )
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
        self._position_panel_chrome()
        self._active_frame.setGeometry(self.rect())

    def _position_panel_chrome(self) -> None:
        """Keep the +/x overlay pinned to the top-right corner, above the plot."""
        self._panel_chrome.adjustSize()
        x = self.width() - self._panel_chrome.width() - 2
        self._panel_chrome.move(max(0, x), 2)
        self._panel_chrome.raise_()

    # ─── Context menu (R14.3) ───────────────────────────────────────────────────

    def set_removable(self, removable: bool) -> None:
        """Set whether Remove Panel is available (R6.6) — menu action and visible button."""
        self._removable = removable
        self._remove_panel_button.setEnabled(removable)

    def set_panel_active(self, active: bool) -> None:
        """Show/hide the active-panel frame (PC-07). Repaint-only — no relayout."""
        self._active_frame.setVisible(active)
        if active:
            self._active_frame.raise_()
            self._panel_chrome.raise_()  # chrome は枠より上 (+/x ボタンを隠さない)

    def set_panel_index(self, panel_index: int) -> None:
        """Record this panel's index within the GraphAreaView (called by _wire_panel)."""
        self._panel_index = panel_index

    def _reset_all_axes(self) -> None:
        self.vm.reset_x()
        self.vm.reset_y()

    def build_context_menu(self) -> QMenu:
        """Build the blank-area panel menu (add/remove panel, reset axes, interp)."""
        from valisync.core.interpolation import InterpolationMethod

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
        menu.addSeparator()
        main_act = menu.addAction("メインカーソル")
        main_act.setCheckable(True)
        main_act.setChecked(self.vm.cursor_t is not None)
        # setChecked BEFORE toggled.connect so the initial state-set does not fire the handler
        main_act.toggled.connect(lambda checked: self.vm.toggle_main_cursor(checked))
        sub_act = menu.addAction("サブカーソル（Δ）")  # noqa: RUF001
        sub_act.setCheckable(True)
        sub_act.setChecked(self.vm.delta_enabled)
        sub_act.setEnabled(self.vm.cursor_t is not None)  # greyed out until main ON
        # setChecked BEFORE toggled.connect so the initial state-set does not fire the handler
        sub_act.toggled.connect(lambda checked: self.vm.toggle_delta(checked))
        interp = menu.addMenu("補間方式")
        for label, method in (
            ("線形", InterpolationMethod.LINEAR),
            ("前値保持", InterpolationMethod.ZERO_ORDER_HOLD),
            ("最近傍", InterpolationMethod.NEAREST),
        ):
            interp.addAction(label).triggered.connect(
                lambda *_, m=method: self.vm.set_interp_method(m)
            )
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.build_context_menu().exec(event.globalPos())
