"""MainWindow — top-level application shell (Task 6.1).

This is a THIN Qt adapter: no business logic lives here.  All state is owned
by AppViewModel; MainWindow only wires Qt signals/slots and dock layout.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QToolBar,
    QWidget,
)

from valisync.gui.viewmodels.app_viewmodel import AppViewModel

_ORG = "ValiSync"
_APP = "ValiSync"


class MainWindow(QMainWindow):
    """Application shell: two dockable panels + toolbar + settings persistence.

    Parameters
    ----------
    app_vm:
        The application-level ViewModel this window observes.
    channel_browser_widget:
        Widget to embed inside the Channel Browser dock.  A placeholder
        ``QLabel`` is used when *None* (later waves inject the real view).
    graph_area_widget:
        Widget to embed inside the Graph Area dock.  Same placeholder rule.
    """

    def __init__(
        self,
        app_vm: AppViewModel,
        channel_browser_widget: QWidget | None = None,
        graph_area_widget: QWidget | None = None,
    ) -> None:
        super().__init__()
        self._app_vm = app_vm
        self.setWindowTitle("ValiSync")

        # ── Dock contents ────────────────────────────────────────────────────
        cb_widget = channel_browser_widget or QLabel("Channel Browser")
        ga_widget = graph_area_widget or QLabel("Graph Area")

        # ── Channel Browser dock (left area by default) ──────────────────────
        self.channel_dock = QDockWidget("Channel Browser", self)
        self.channel_dock.setWidget(cb_widget)
        # Floatable + Closable + Movable (default Qt flags, kept explicit)
        self.channel_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.channel_dock)

        # ── Graph Area dock (right area by default) ──────────────────────────
        self.graph_dock = QDockWidget("Graph Area", self)
        self.graph_dock.setWidget(ga_widget)
        self.graph_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.graph_dock)

        # ── View menu (dock toggle actions, R1.4) ────────────────────────────
        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.channel_dock.toggleViewAction())
        view_menu.addAction(self.graph_dock.toggleViewAction())

        # ── Toolbar (R1.5) ───────────────────────────────────────────────────
        toolbar: QToolBar = self.addToolBar("Main")
        self.action_data_explorer: QAction = QAction("Data Explorer", self)
        self.action_data_explorer.triggered.connect(self.open_data_explorer)
        toolbar.addAction(self.action_data_explorer)

        # ── Restore geometry / dock state from previous session (R2.3) ───────
        self._restore_state()

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

    # ─── Actions ──────────────────────────────────────────────────────────────

    def open_data_explorer(self) -> None:
        """Placeholder: open the Data Explorer panel.

        Later waves will implement the real Data Explorer view and override
        this method (or connect the action differently).
        """
