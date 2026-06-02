"""Graph_Area view — tabbed, splittable panel container (Task 8.1).

A QTabWidget whose pages are vertical QSplitters, one child widget per
GraphPanelVM.  Tab/panel structure mirrors GraphAreaVM; all mutation rules
("reject the last tab/panel", "max 8 panels") live in the VM, so this widget
just delegates and re-projects on notify.

The real per-panel widget (PyQtGraph plot) arrives in Task 8.2; until then a
caller-supplied ``panel_factory`` builds the panel widgets, defaulting to a
labelled placeholder.  Injecting the factory keeps this view decoupled from
GraphPanelView and gives 8.2 a clean seam.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSplitter, QTabWidget, QVBoxLayout, QWidget

from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

PanelFactory = Callable[[GraphPanelVM], QWidget]


def _default_panel_factory(_panel_vm: GraphPanelVM) -> QWidget:
    return QLabel("Graph Panel")


class GraphAreaView(QWidget):
    """Tabbed container projecting :class:`GraphAreaVM`."""

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

        self.tabs = QTabWidget(self)
        self.tabs.currentChanged.connect(self._on_current_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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
        else:  # "tabs" | "panels" | "sync"
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
                for panel_vm in self.vm.panels(tab_index):
                    splitter.addWidget(self._panel_factory(panel_vm))
                self.tabs.addTab(splitter, tab.name)
            self.tabs.setCurrentIndex(self.vm.active_tab_index)
        finally:
            self._syncing = False

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
