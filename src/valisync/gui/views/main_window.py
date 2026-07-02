"""MainWindow — top-level application shell and integration hub (Tasks 6.1 / 10).

Builds the shared ViewModels off the AppViewModel's Session, mounts the real
Channel_Browser and Graph_Area views in dockable panels, and wires the
cross-view workflow:

- a load (file drop, Data Explorer) runs off-thread via LoadController with a
  BusyOverlay, then refreshes the channel tree and re-renders the panels;
- "add to active panel" from the channel browser plots on the active panel;
- the toolbar opens the Data Explorer window.

It stays thin: all state lives in the ViewModels; this class only constructs
collaborators and connects their signals.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QDockWidget, QMainWindow, QToolBar

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.views.busy_overlay import BusyOverlay
from valisync.gui.views.channel_browser_view import ChannelBrowserView
from valisync.gui.views.data_explorer_view import DataExplorerView
from valisync.gui.views.file_browser_view import FileBrowserView
from valisync.gui.views.graph_area_view import GraphAreaView
from valisync.gui.workers.load_worker import LoadController

_ORG = "ValiSync"
_APP = "ValiSync"


class MainWindow(QMainWindow):
    """Application shell: dockable Channel_Browser + Graph_Area, wired together.

    Parameters
    ----------
    app_vm:
        The application-level ViewModel.  Its ``session`` is shared with the
        Channel_Browser and Graph_Area ViewModels so loaded data is visible
        everywhere.
    """

    def __init__(self, app_vm: AppViewModel) -> None:
        super().__init__()
        self.app_vm = app_vm
        self.setWindowTitle("ValiSync")

        # ── Shared ViewModels (one Session) ──────────────────────────────────
        self.file_browser_vm = FileBrowserVM(app_vm)
        self.channel_browser_vm = ChannelBrowserVM(app_vm)
        self.graph_area_vm = GraphAreaVM(app_vm)

        # ── Views ────────────────────────────────────────────────────────────
        self.file_browser_view = FileBrowserView(self.file_browser_vm)
        self.channel_browser_view = ChannelBrowserView(self.channel_browser_vm)
        self.graph_area_view = GraphAreaView(self.graph_area_vm)
        self.busy_overlay = BusyOverlay(self)
        self._load_controller = LoadController(parent=self)
        self.data_explorer: DataExplorerView | None = None

        # ── File Browser dock (right top) ────────────────────────────────────
        self.file_dock = QDockWidget("File Browser", self)
        self.file_dock.setObjectName("file_dock")  # required for saveState/restoreState
        self.file_dock.setWidget(self.file_browser_view)
        self.file_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.file_dock)

        # ── Channel Browser dock (right bottom) ──────────────────────────────
        self.channel_dock = QDockWidget("Channel Browser", self)
        self.channel_dock.setObjectName("channel_dock")
        self.channel_dock.setWidget(self.channel_browser_view)
        self.channel_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.channel_dock)

        # Stack them vertically
        self.splitDockWidget(self.file_dock, self.channel_dock, Qt.Orientation.Vertical)

        # ── Graph Area (Central Widget) ──────────────────────────────────────
        self.setCentralWidget(self.graph_area_view)

        # ── View menu (dock toggles, R1.4) ───────────────────────────────────
        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.file_dock.toggleViewAction())
        view_menu.addAction(self.channel_dock.toggleViewAction())

        # ── Toolbar (R1.5) ───────────────────────────────────────────────────
        toolbar: QToolBar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")  # required for saveState/restoreState
        self.action_data_explorer: QAction = QAction("Data Explorer", self)
        self.action_data_explorer.triggered.connect(self.open_data_explorer)
        toolbar.addAction(self.action_data_explorer)

        # ── Cross-view wiring ────────────────────────────────────────────────
        self.channel_browser_view.add_to_panel_requested.connect(
            self._add_to_active_panel
        )
        self.graph_area_view.file_dropped.connect(self._load_file)
        self._app_unsubscribe = self.app_vm.subscribe(self._on_app_change)

        self._restore_state()

    # ─── Load pipeline ─────────────────────────────────────────────────────────

    def _load_file(self, path: str | Path) -> None:
        """Load *path* off-thread (MDF4; CSV needs a format picker, deferred)."""
        session = self.app_vm.session
        target = Path(path)
        self._load_controller.submit(
            lambda: session.load(target, None).key,
            busy=self.busy_overlay,
            on_success=self._on_loaded,
            on_error=self._on_load_error,
        )

    def _on_loaded(self, key: str) -> None:
        # Runs on the GUI thread; register_loaded notifies "loaded".
        self.app_vm.register_loaded(key)

    def _on_load_error(self, _message: str) -> None:
        # MVP: keep running; a status surface for errors is a later refinement.
        pass

    def _on_app_change(self, change: str) -> None:
        if change == "loaded":
            self.channel_browser_vm.refresh()
            # Panels are reconciled by GraphAreaVM, which subscribes to app_vm.

    def _add_to_active_panel(self, keys: list[str]) -> None:
        """Plot *keys* on the first panel of the active tab (the 'active' panel)."""
        panels = self.graph_area_vm.panels(self.graph_area_vm.active_tab_index)
        if not panels:
            return
        for key in keys:
            panels[0].add_signal(key)

    # ─── Actions ────────────────────────────────────────────────────────────────

    def open_data_explorer(self, *_: object) -> None:
        """Open (or re-show) the standalone Data Explorer window (R1.5)."""
        if self.data_explorer is None:
            self.data_explorer = DataExplorerView(
                self.app_vm, load_handler=self._load_file
            )
        self.data_explorer.show()
        self.data_explorer.raise_()

    # ─── State persistence ────────────────────────────────────────────────────

    def save_state(self) -> None:
        """Persist window geometry and dock arrangement to QSettings."""
        settings = QSettings(_ORG, _APP)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Persist window state on close so it can be restored next launch (R2.3)."""
        self.save_state()
        super().closeEvent(event)

    def _restore_state(self) -> None:
        """Restore geometry/dock state saved by a previous session.

        Guarded against missing/corrupt values: absent keys return None and
        both restoreGeometry/restoreState silently ignore falsy byte-arrays.
        """
        settings = QSettings(_ORG, _APP)
        geometry = settings.value("geometry")
        state = settings.value("windowState")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
