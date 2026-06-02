"""Graph_Panel view — pyqtgraph waveform projection of GraphPanelVM (Task 8.2).

A thin ``pyqtgraph.PlotWidget`` wrapper.  It owns no plot state: every render
projects ``vm.render_data()`` (already LOD-reduced by the VM via
``Session.downsample``) onto one ``PlotDataItem`` per curve, coloured as the VM
assigned, with a legend entry.  Empty curves still appear in the legend
(R8.5).  Signal drops (``SIGNAL_KEYS_MIME``) add to the VM, and resize reports
the new pixel width so the VM can re-pick the LOD target.

Zoom/pan (Task 8.3) and X-axis sync (Task 8.4) build on this view later.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QResizeEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from valisync.gui.adapters.qt_signal_models import (
    SIGNAL_KEYS_MIME,
    decode_signal_keys,
)
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


class GraphPanelView(QWidget):
    """PyQtGraph waveform view bound to a :class:`GraphPanelVM`."""

    def __init__(self, vm: GraphPanelVM, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.vm = vm
        self._items: dict[str, pg.PlotDataItem] = {}

        self.plot_widget = pg.PlotWidget()
        self._plot_item = self.plot_widget.getPlotItem()
        self._plot_item.setLabel("bottom", "Time", units="s")
        self._legend = self._plot_item.addLegend()
        # Let drops bubble to this container rather than being eaten by the
        # GraphicsView; the container owns the drag-and-drop contract.
        self.plot_widget.setAcceptDrops(False)
        self.setAcceptDrops(True)

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
        """Re-project vm.render_data() onto the plot, reconciling curve items."""
        curves = self.vm.render_data()
        desired = {c.name: c for c in curves}

        # Drop curves no longer present (removed or toggled invisible).
        for key in list(self._items):
            if key not in desired:
                item = self._items.pop(key)
                self._plot_item.removeItem(item)
                self._legend.removeItem(item)

        # Add or update the remaining curves.
        for curve in curves:
            pen = pg.mkPen(curve.color)
            item = self._items.get(curve.name)
            if item is None:
                item = self._plot_item.plot(name=curve.name)
                self._items[curve.name] = item
            item.setData(curve.timestamps, curve.values)
            item.setPen(pen)

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

    def legend_labels(self) -> list[str]:
        """Return the signal names currently shown in the legend."""
        return [label.text for _sample, label in self._legend.items]

    # ─── Drag-and-drop sink (R12.4) ────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(SIGNAL_KEYS_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(SIGNAL_KEYS_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        keys = decode_signal_keys(event.mimeData())
        if not keys:
            event.ignore()
            return
        for key in keys:
            self.vm.add_signal(key)  # notifies → refresh()
        event.acceptProposedAction()

    # ─── Resize → LOD pixel budget ──────────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.vm.set_panel_width(max(1, event.size().width()))  # notifies → refresh()
