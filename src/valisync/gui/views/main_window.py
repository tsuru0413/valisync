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

import threading
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QDockWidget, QMainWindow, QMessageBox, QToolBar

from valisync.core.session import LoadOutcome
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.views.busy_overlay import BusyOverlay
from valisync.gui.views.channel_browser_view import ChannelBrowserView
from valisync.gui.views.data_explorer_view import DataExplorerView
from valisync.gui.views.diagnostics_view import DiagnosticsView
from valisync.gui.views.file_browser_view import FileBrowserView
from valisync.gui.views.graph_area_view import GraphAreaView
from valisync.gui.workers.expansion_confirmer import ExpansionConfirmer
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
        self._update_window_title()

        # ── Shared ViewModels (one Session) ──────────────────────────────────
        self.file_browser_vm = FileBrowserVM(app_vm)
        self.channel_browser_vm = ChannelBrowserVM(app_vm)
        self.graph_area_vm = GraphAreaVM(app_vm)
        self.diagnostics_vm = DiagnosticsViewModel()

        # ── Views ────────────────────────────────────────────────────────────
        self.file_browser_view = FileBrowserView(self.file_browser_vm)
        self.channel_browser_view = ChannelBrowserView(self.channel_browser_vm)
        self.graph_area_view = GraphAreaView(self.graph_area_vm)
        self.busy_overlay = BusyOverlay(self)
        self._load_controller = LoadController(parent=self)
        # GUI スレッド所属 — ワーカーからの展開確認をモーダルへ marshal (LD-14)。
        self._expansion_confirmer = ExpansionConfirmer(self)
        self.busy_overlay.cancel_requested.connect(self._load_controller.cancel_active)
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

        # ── Diagnostics dock (bottom, FB-02/FB-06 surface) ───────────────────
        self.diagnostics_dock = DiagnosticsView(self.diagnostics_vm)
        self.diagnostics_dock.entry_activated.connect(self._on_diagnostic_activated)
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.diagnostics_dock
        )

        # ── Graph Area (Central Widget) ──────────────────────────────────────
        self.setCentralWidget(self.graph_area_view)

        # ── View menu (dock toggles, R1.4) ───────────────────────────────────
        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.file_dock.toggleViewAction())
        view_menu.addAction(self.channel_dock.toggleViewAction())
        view_menu.addAction(self.diagnostics_dock.toggleViewAction())

        # ── Toolbar (R1.5) ───────────────────────────────────────────────────
        toolbar: QToolBar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")  # required for saveState/restoreState
        self.action_data_explorer: QAction = QAction("Data Explorer", self)
        self.action_data_explorer.triggered.connect(self.open_data_explorer)
        toolbar.addAction(self.action_data_explorer)

        # Status bar surfaces load outcomes (FB-06); shown even before any load.
        self.statusBar().showMessage("準備完了")

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
        cancel_event = threading.Event()  # 所有=ここ・セット権=controller(spec §4.1)

        def _discard(outcome: LoadOutcome) -> None:
            # 手遅れ完走のロールバック; remove_group の戻り値は on_discard の
            # Callable[[LoadOutcome], None] 契約に不要なので握りつぶす。
            session.remove_group(outcome.key, force=True)

        self._load_controller.submit(
            lambda: session.load(
                target,
                None,
                cancel=cancel_event.is_set,
                confirm_expansion=self._expansion_confirmer.confirm,
            ),
            busy=self.busy_overlay,
            cancel_event=cancel_event,
            label=target.name,
            on_success=self._on_loaded,
            on_error=lambda err: self._on_load_error(target, err),
            on_cancelled=lambda: self._on_load_cancelled(target),
            on_discard=_discard,
        )

    def _on_loaded(self, outcome: LoadOutcome) -> None:
        # GUI thread; register, surface diagnostics, activate, update status.
        self.app_vm.register_loaded(outcome.key)
        source = self.app_vm.session.source_name(outcome.key)
        self.diagnostics_vm.add(source, outcome.diagnostics)
        self.app_vm.set_active_file(outcome.key)  # FB-03: fill Channel Browser
        msg = f"{source} を読み込みました"
        # LD-12: info は非アラーム(透明化) - error/warning のみ "⚠" で数える。
        n_alert = sum(1 for d in outcome.diagnostics if d.level in ("error", "warning"))
        n_info = len(outcome.diagnostics) - n_alert
        if n_alert:
            msg += f" ・ ⚠ {n_alert} 件の診断（Diagnostics を参照）"  # noqa: RUF001
        elif n_info:
            msg += f" ・ ℹ {n_info} 件の情報（Diagnostics を参照）"  # noqa: RUF001
        self.statusBar().showMessage(msg)

    def _on_load_error(self, path: Path, err: Exception) -> None:
        # FB-01: never silent — record + modal + status.
        source = path.name
        diags = getattr(err, "diagnostics", ())
        messages = getattr(err, "messages", [str(err)])
        if diags:
            self.diagnostics_vm.add(source, diags)
        else:
            from valisync.core.models.load_result import Diagnostic

            self.diagnostics_vm.add(
                source, [Diagnostic(level="error", message="; ".join(messages))]
            )
        self.statusBar().showMessage(f"⛔ 読み込み失敗: {source}")
        self.diagnostics_dock.show()
        self.diagnostics_dock.raise_()
        QMessageBox.critical(
            self,
            "読み込みエラー",
            f"{source} を読み込めませんでした。\n\n" + "; ".join(messages),
        )

    def _on_load_cancelled(self, path: Path) -> None:
        # ユーザー起点の正常系: status のみ(モーダル/診断は出さない・spec §6)
        self.statusBar().showMessage(f"キャンセルしました: {path.name}")

    def _on_diagnostic_activated(self, target: str) -> None:
        # Best-effort jump: select the signal's file in the channel browser.
        # (Detailed signal-row selection is a later task; activating the file is
        # enough to surface the context.)
        #
        # `target` is always `e.source` (a file basename) — DiagnosticsView
        # unified diagnostic-jump to source only (signal_name is display-only,
        # see diagnostics_view.py). Group keys ("csv_1", "mf4_2") share no
        # textual relationship with the basename, so we resolve via Session's
        # public recovery points instead of string matching against the key.
        for key in self.app_vm.loaded_file_keys:
            if self.app_vm.session.source_name(key) == target:
                self.app_vm.set_active_file(key)
                return
        # Defensive: no current emitter sends a signal name here, but this
        # fallback stays ready for a future signal-name emit / signal-row
        # selection without another _on_diagnostic_activated rewrite.
        for key in self.app_vm.loaded_file_keys:
            try:
                group_sigs = self.app_vm.session.group_signals(key)
            except KeyError:
                continue
            if any(sig.name == target for sig in group_sigs):
                self.app_vm.set_active_file(key)
                return

    def _on_app_change(self, change: str) -> None:
        if change == "loaded":
            self.channel_browser_vm.refresh()
            # Panels are reconciled by GraphAreaVM, which subscribes to app_vm.
        if change in ("active_file", "loaded", "unloaded"):
            self._update_window_title()

    def _update_window_title(self) -> None:
        """FB-07: show the active file so the title answers 'what am I looking at'."""
        key = self.app_vm.active_file_key
        if key is None:
            self.setWindowTitle("ValiSync")
            return
        try:
            name = self.app_vm.session.source_name(key)
        except KeyError:
            self.setWindowTitle("ValiSync")
            return
        self.setWindowTitle(f"{name} — ValiSync")

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
