"""Graph_Area view — tabbed, splittable panel container (Tasks 8.1 / 8.4).

A QTabWidget whose pages are vertical QSplitters, one child widget per
GraphPanelVM.  Tab/panel structure mirrors GraphAreaVM; all mutation rules
("reject the last tab/panel", "max 8 panels") and X-axis sync live in the VM,
so this widget just delegates and re-projects on notify.

Panel widgets are built by ``panel_factory`` (default: a real GraphPanelView).
Injecting the factory keeps the container decoupled and testable.

X-axis sync (Task 8.4): a sync toggle drives ``GraphAreaVM.set_x_sync``; the
propagation itself is in the VM (a panel's X-range change drives its siblings),
so zooming one GraphPanelView updates the others through the VM layer.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView

PanelFactory = Callable[[GraphPanelVM], QWidget]


def _default_panel_factory(panel_vm: GraphPanelVM) -> QWidget:
    return GraphPanelView(panel_vm)


class GraphAreaView(QWidget):
    """Tabbed container projecting :class:`GraphAreaVM`."""

    # Emitted when OS files are dropped onto the area; the integration layer
    # connects this to the load pipeline (R12.1).
    file_dropped = Signal(str)

    def __init__(
        self,
        vm: GraphAreaVM,
        panel_factory: PanelFactory | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.vm = vm
        self._panel_factory: PanelFactory = panel_factory or _default_panel_factory
        # Guards against re-entrancy when we programmatically set the current
        # tab during a rebuild (which would otherwise echo back into the VM).
        self._syncing = False
        self._drop_active = False
        self.setAcceptDrops(True)

        # X-sync toggle for the active tab (R7.3).
        self.sync_checkbox = QCheckBox("Sync X")
        self.sync_checkbox.toggled.connect(self._on_sync_toggled)

        self.tabs = QTabWidget(self)
        self.tabs.currentChanged.connect(self._on_current_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.sync_checkbox)
        layout.addWidget(self.tabs)

        unsubscribe = self.vm.subscribe(self._on_vm_change)
        self._unsubscribe = unsubscribe
        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        self.destroyed.connect(lambda *_: unsubscribe())
        self._rebuild()

    # ─── VM reactions ──────────────────────────────────────────────────────────

    def _on_vm_change(self, change: str) -> None:
        if change == "active":
            self._sync_current()
            self._update_sync_checkbox()
        elif change == "sync":
            self._update_sync_checkbox()
        else:  # "tabs" | "panels"
            self._rebuild()

    def _rebuild(self) -> None:
        """Re-project the whole VM tab/panel tree onto the QTabWidget."""
        self._syncing = True
        try:
            # QTabWidget.clear() detaches pages without destroying them, leaking
            # a QSplitter (and its panel widgets) on every rebuild.  Dispose the
            # old pages explicitly.
            old_pages = [self.tabs.widget(i) for i in range(self.tabs.count())]
            self.tabs.clear()
            for page in old_pages:
                if page is not None:
                    page.setParent(None)
                    page.deleteLater()
            for tab_index, tab in enumerate(self.vm.tabs()):
                splitter = QSplitter(Qt.Orientation.Vertical)
                panel_vms = self.vm.panels(tab_index)
                for panel_index, panel_vm in enumerate(panel_vms):
                    widget = self._panel_factory(panel_vm)
                    self._wire_panel(
                        widget, tab_index, panel_index, removable=len(panel_vms) > 1
                    )
                    splitter.addWidget(widget)
                self.tabs.addTab(splitter, tab.name)
            self.tabs.setCurrentIndex(self.vm.active_tab_index)
        finally:
            self._syncing = False
        self._update_sync_checkbox()

    def _wire_panel(
        self, widget: QWidget, tab_index: int, panel_index: int, removable: bool
    ) -> None:
        """Connect a GraphPanelView's add/remove requests to area operations.

        Bound to this call's *tab_index*/*panel_index* (not loop vars), so the
        connected lambdas capture the correct position.
        """
        if not isinstance(widget, GraphPanelView):
            return
        widget.set_removable(removable)
        widget.set_panel_index(panel_index)
        widget.add_panel_requested.connect(lambda *_: self.add_panel(tab_index))
        widget.remove_panel_requested.connect(
            lambda *_: self.remove_panel(panel_index, tab_index)
        )
        widget.offset_apply_requested.connect(
            lambda k, dt, sc: self.vm.apply_offset(k, dt, sc)
        )
        widget.cross_panel_axis_move_requested.connect(
            lambda src, ax, col, pos: self.vm.move_axis_across_panels(
                tab_index, src, ax, panel_index, col, pos
            )
        )

    def _sync_current(self) -> None:
        self._syncing = True
        try:
            self.tabs.setCurrentIndex(self.vm.active_tab_index)
        finally:
            self._syncing = False

    def _on_current_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self.vm.set_active_tab(index)

    # ─── X-sync toggle ─────────────────────────────────────────────────────────

    def _on_sync_toggled(self, checked: bool) -> None:
        self.vm.set_x_sync(self.vm.active_tab_index, checked)

    def _update_sync_checkbox(self) -> None:
        """Reflect the active tab's sync flag without echoing back to the VM."""
        tabs = self.vm.tabs()
        if not tabs:
            return
        enabled = tabs[self.vm.active_tab_index].x_sync_enabled
        self.sync_checkbox.blockSignals(True)
        self.sync_checkbox.setChecked(enabled)
        self.sync_checkbox.blockSignals(False)

    # ─── Commands (delegate to VM; rejections are swallowed as UI no-ops) ───────

    def add_tab(self, name: str | None = None) -> None:
        self.vm.add_tab(name)

    def remove_tab(self, index: int) -> None:
        with contextlib.suppress(ValueError):  # last tab — keep it (R5.6)
            self.vm.remove_tab(index)

    def rename_tab(self, index: int, name: str) -> None:
        with contextlib.suppress(ValueError):  # invalid length — leave label (R5.4)
            self.vm.rename_tab(index, name)

    def add_panel(self, tab_index: int | None = None) -> None:
        with contextlib.suppress(ValueError):  # at the 8-panel cap (R6.5)
            self.vm.add_panel(self._target_tab(tab_index))

    def remove_panel(self, panel_index: int, tab_index: int | None = None) -> None:
        with contextlib.suppress(ValueError):  # last panel — keep it (R6.6)
            self.vm.remove_panel(self._target_tab(tab_index), panel_index)

    def _target_tab(self, tab_index: int | None) -> int:
        return self.vm.active_tab_index if tab_index is None else tab_index

    # ─── OS file drop → load pipeline (R12.1) ──────────────────────────────────

    def is_drop_highlighted(self) -> bool:
        """Return True while a droppable file drag is hovering (R12.5)."""
        return self._drop_active

    def _set_drop_highlight(self, active: bool) -> None:
        self._drop_active = active
        self.setStyleSheet(
            "GraphAreaView { border: 2px dashed #1f77b4; }" if active else ""
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_drop_highlight(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_highlight(False)
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        for url in mime.urls():
            local = url.toLocalFile()
            if local:
                self.file_dropped.emit(local)
        event.acceptProposedAction()
