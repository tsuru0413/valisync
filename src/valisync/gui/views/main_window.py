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
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QToolBar,
)

from valisync.core.loaders.csv_format_detector import CsvFormatDetector
from valisync.core.models.format_def import FormatDefinition
from valisync.core.session import LoadOutcome
from valisync.gui.theme import apply as theme_apply
from valisync.gui.theme import icons
from valisync.gui.theme.tokens import ThemeMode
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM
from valisync.gui.views.analysis_actions import (
    build_analysis_actions,
    sync_analysis_actions,
)
from valisync.gui.views.busy_overlay import BusyOverlay
from valisync.gui.views.central_with_rails import CentralWithRails
from valisync.gui.views.channel_browser_view import ChannelBrowserView
from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar
from valisync.gui.views.csv_format_dialog import CsvFormatDialog
from valisync.gui.views.data_explorer_view import DataExplorerView
from valisync.gui.views.diagnostics_view import DiagnosticsView
from valisync.gui.views.export_csv_dialog import ExportCsvDialog
from valisync.gui.views.file_browser_view import FileBrowserView
from valisync.gui.views.graph_area_view import GraphAreaView
from valisync.gui.views.recent_files import RecentFiles
from valisync.gui.views.shell_actions import ShellActions
from valisync.gui.views.signal_preview_window import SignalPreviewWindow
from valisync.gui.views.welcome_view import WelcomeView
from valisync.gui.workers.expansion_confirmer import ExpansionConfirmer
from valisync.gui.workers.export_worker import ExportController
from valisync.gui.workers.load_worker import LoadController
from valisync.gui.workers.teardown_service import TeardownService

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
        # FU-16: hand a closed file's ~10 GB group to a GUI-thread byte-budget
        # background drain so close returns at once; on_finished (mark_released)
        # clears the File Browser's releasing (spinner) row once a file's data
        # is fully freed.
        self.teardown_service = TeardownService(
            on_finished=self.app_vm.mark_released, parent=self
        )
        self.app_vm.set_teardown(self.teardown_service)
        self._update_window_title()

        # ── Shared ViewModels (one Session) ──────────────────────────────────
        self.file_browser_vm = FileBrowserVM(app_vm)
        self.channel_browser_vm = ChannelBrowserVM(app_vm)
        self.graph_area_vm = GraphAreaVM(app_vm)
        self.diagnostics_vm = DiagnosticsViewModel()

        # spec §2.2: Analyze メニューと各パネルの空白右クリックメニューが共有する
        # 解析系 QAction 群。trigger 時の配送先は固定 dispatch ではなく、メニューを
        # 開く直前に sync_analysis_actions が再ターゲットする書き換え可能な内部状態
        # (analysis_actions.py 参照) -- ここでは QWidget を close over しないので
        # 参照循環にはならない。
        self._analysis_actions = build_analysis_actions(self)

        # ── Views ────────────────────────────────────────────────────────────
        self.file_browser_view = FileBrowserView(self.file_browser_vm)
        self.channel_browser_view = ChannelBrowserView(self.channel_browser_vm)
        self.graph_area_view = GraphAreaView(
            self.graph_area_vm, analysis_actions=self._analysis_actions
        )
        self.busy_overlay = BusyOverlay(self)
        self._load_controller = LoadController(parent=self)
        self._export_controller = ExportController(parent=self)
        # GUI スレッド所属 — ワーカーからの展開確認をモーダルへ marshal (LD-14)。
        self._expansion_confirmer = ExpansionConfirmer(self)
        # LD-01: CSV フォーマット解決 (検出して確認ダイアログ)。テストで差し替え可能。
        self._csv_format_resolver: Callable[[Path], FormatDefinition | None] = (
            self._default_csv_format_resolver
        )
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
        # 辺対応の折りたたみは左/右/下のみ対応 (edge-aware-dock-collapse) — 上は禁止。
        self.file_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
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
        # 辺対応の折りたたみは左/右/下のみ対応 (edge-aware-dock-collapse) — 上は禁止。
        self.channel_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.channel_dock)

        # Stack them vertically
        self.splitDockWidget(self.file_dock, self.channel_dock, Qt.Orientation.Vertical)

        # ── Diagnostics dock (bottom, FB-02/FB-06 surface) ───────────────────
        self.diagnostics_dock = DiagnosticsView(self.diagnostics_vm)
        self.diagnostics_dock.entry_activated.connect(self._on_diagnostic_activated)
        # 辺対応の折りたたみは左/右/下のみ対応 (edge-aware-dock-collapse) — 上は禁止。
        self.diagnostics_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.diagnostics_dock
        )

        # ── Central: Welcome / Graph Area を QStackedWidget で切替 ──────────────
        self.recent_files = RecentFiles()
        self._workbench_started = False
        self.welcome_view = WelcomeView(self.recent_files)
        self.welcome_view.open_requested.connect(self._on_open_requested)
        self.central_stack = QStackedWidget(self)
        self.central_stack.addWidget(self.welcome_view)  # index 0
        self.central_stack.addWidget(self.graph_area_view)  # index 1
        # 畳んだドックの辺レールを中央の縁に置く枠で包む (edge-aware-collapse)。
        self._central_with_rails = CentralWithRails(self.central_stack)
        self.setCentralWidget(self._central_with_rails)

        # ── 辺対応の折りたたみ (edge-aware-dock-collapse) ────────────────────
        from valisync.gui.views.dock_collapse_rail import DockCollapseRail

        self._collapse_rails: dict[Qt.DockWidgetArea, DockCollapseRail] = {}
        for edge in (
            Qt.DockWidgetArea.LeftDockWidgetArea,
            Qt.DockWidgetArea.RightDockWidgetArea,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        ):
            rail = DockCollapseRail(edge)
            rail.expand_requested.connect(self._expand_dock)
            self._central_with_rails.set_rail(edge, rail)
            self._collapse_rails[edge] = rail

        self._collapsible_bars: dict[str, CollapsibleDockTitleBar] = {}
        self._collapsed_docks: set[str] = set()
        self._expanded_extent: dict[str, int] = {}
        # _collapse_dock/_expand_dock 自身の hide()/show() が visibilityChanged
        # を再発火させる (無限再入防止・レビュー Important 1)。
        self._suppress_dock_reconcile = False
        self._dock_rail_order = {  # 辺上の位置順 (File 上/Channel 下)
            "file_dock": 0,
            "channel_dock": 1,
            "diagnostics_dock": 0,
        }
        for dock, title in (
            (self.file_dock, "File Browser"),
            (self.channel_dock, "Channel Browser"),
            (self.diagnostics_dock, "Diagnostics"),
        ):
            bar = CollapsibleDockTitleBar(dock, self, title)
            dock.setTitleBarWidget(bar)
            bar.collapse_requested.connect(lambda d=dock: self._collapse_dock(d))
            self._collapsible_bars[dock.objectName()] = bar
            # 集約状態機械 (_expand_dock) を経由しない外部 show() (View メニュー/
            # ツールバーの toggleViewAction・_on_load_error の直接 show() 等) が
            # 畳み状態を孤立させないよう、可視化を単一箇所で自己修復する
            # (レビュー Important 1)。_restore_state() より前に接続すること —
            # このループ時点では _collapsed_docks は空なので起動時の
            # restoreState 由来の可視化変化は no-op。
            dock.visibilityChanged.connect(
                lambda visible, d=dock: self._on_dock_visibility_changed(d, visible)
            )

        self._update_central()

        # ── 領域境界フレーム (region-frames spec §7) — 対象はシェルが選ぶ ──────
        theme_apply.frame_region(self.file_browser_view, "region_file_browser")
        theme_apply.frame_region(self.channel_browser_view, "region_channel_browser")
        theme_apply.frame_region(self.diagnostics_dock.widget(), "region_diagnostics")
        theme_apply.frame_region(self.central_stack, "region_central")

        # ── ShellActions (QAction レジストリ) ────────────────────────────────
        self.shell_actions = ShellActions(self)
        self.shell_actions.action("open").triggered.connect(self.open_file)
        self.shell_actions.action("open_folder").triggered.connect(
            self.open_data_explorer
        )
        self.shell_actions.action("export").triggered.connect(self.export_csv)

        # ── メニューバー ─────────────────────────────────────────────────────
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.shell_actions.action("open"))
        file_menu.addAction(self.shell_actions.action("open_folder"))
        self.recent_menu = file_menu.addMenu("Recent Files")
        file_menu.addAction(self.shell_actions.action("export"))
        file_menu.addSeparator()
        self.action_exit = file_menu.addAction("E&xit")
        # StandardKey.Quit は Windows で Key_Exit(押せないメディアキー)に解決する
        # ため、明示 Ctrl+Q を使う(主対象 OS は Windows)。
        self.action_exit.setShortcut(QKeySequence("Ctrl+Q"))
        self.action_exit.triggered.connect(self.close)

        # ── View menu (dock toggles, R1.4) ───────────────────────────────────
        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.file_dock.toggleViewAction())
        view_menu.addAction(self.channel_dock.toggleViewAction())
        view_menu.addAction(self.diagnostics_dock.toggleViewAction())
        view_menu.addSeparator()

        # 増分4: テーマ三態 (再起動反映 — 選択は QSettings 保存のみ・spec §11)。
        theme_menu = view_menu.addMenu("テーマ")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        current_mode = theme_apply.load_theme_mode()
        for label, mode in (
            ("ライト", ThemeMode.LIGHT),
            ("ダーク", ThemeMode.DARK),
            ("オート (OS に合わせる)", ThemeMode.AUTO),
        ):
            act = theme_menu.addAction(label)
            act.setCheckable(True)
            self._theme_group.addAction(act)
            # setChecked は triggered 配線の前 (排他カスケード誤発火の構造回避 —
            # gui_qactiongroup_exclusive_radio_menu の既存規約)
            act.setChecked(mode is current_mode)
            act.triggered.connect(lambda _=False, m=mode: self._on_theme_selected(m))

        view_menu.addSeparator()
        self.action_reset_layout = view_menu.addAction("Reset Layout")
        self.action_reset_layout.triggered.connect(self._reset_layout)

        # Analyze メニュー (spec §2.2): 各パネルの空白右クリックメニューと同一の
        # AnalysisActions インスタンスを掲載する (checked/文言の乖離を構造防止)。
        analyze_menu = self.menuBar().addMenu("&Analyze")
        analyze_menu.addAction(self._analysis_actions.cursor_a)
        analyze_menu.addAction(self._analysis_actions.cursor_b)
        analyze_menu.addSeparator()
        analyze_menu.addAction(self._analysis_actions.clear_cursors)
        interp_menu = analyze_menu.addMenu("補間方式")
        for act in self._analysis_actions.interp_actions.values():
            interp_menu.addAction(act)
        analyze_menu.addSeparator()
        analyze_menu.addAction(self._analysis_actions.step_hint)
        analyze_menu.setToolTipsVisible(True)
        # aboutToShow の setChecked 同期は toggled は発火させても triggered は発火
        # させない (Qt 仕様) ため、ここで無条件に同期してもハンドラは起動しない。
        analyze_menu.aboutToShow.connect(self._sync_analysis_actions)

        help_menu = self.menuBar().addMenu("&Help")
        about = help_menu.addAction("&About ValiSync")
        about.triggered.connect(self._show_about)

        # ── Toolbar (R1.5) ───────────────────────────────────────────────────
        toolbar: QToolBar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")  # required for saveState/restoreState
        toolbar.addAction(self.shell_actions.action("open"))
        toolbar.addAction(self.shell_actions.action("export"))
        toolbar.addSeparator()
        self.action_data_explorer = QAction(
            icons.icon("data_explorer"),
            "Data Explorer",
            self,
        )
        self.action_data_explorer.setToolTip("データエクスプローラを開く")
        self.action_data_explorer.setStatusTip("データエクスプローラを開く")
        self.action_data_explorer.triggered.connect(self.open_data_explorer)
        toolbar.addAction(self.action_data_explorer)
        toolbar.addSeparator()
        toolbar.addAction(self.file_dock.toggleViewAction())
        toolbar.addAction(self.channel_dock.toggleViewAction())
        toolbar.addAction(self.diagnostics_dock.toggleViewAction())

        # Status bar surfaces load outcomes (FB-06); shown even before any load.
        self.statusBar().showMessage("準備完了")

        # ── Cross-view wiring ────────────────────────────────────────────────
        self.channel_browser_view.add_to_panel_requested.connect(
            self._add_to_active_panel
        )
        # FU-13: single-instance, non-modal preview window opened by double-click.
        self.signal_preview_window = SignalPreviewWindow(
            SignalPreviewVM(self.app_vm), parent=self
        )
        self.channel_browser_view.preview_requested.connect(
            self.signal_preview_window.show_signal
        )
        self.graph_area_view.file_dropped.connect(self._load_file)
        self._app_unsubscribe = self.app_vm.subscribe(self._on_app_change)

        self._rebuild_recent_menu()
        # SH-11: 永続状態で上書きされる前の既定配置を捕捉 (Reset Layout 用)。
        self._default_state = self.saveState()
        self._state_restored = self._restore_state()
        # restoreState resets dock corner config to Qt defaults, so re-apply FU-10
        # after the startup restore (and after Reset Layout -- see _reset_layout).
        self._apply_dock_corners()
        # UX-21 応急: 初期ドック比率 File:Channel≈1:4 (spec §1.5-12)。ここではまだ
        # 未表示 (pre-show) — dock extent が未確定で resizeDocks が no-op になる
        # 罠を踏むため、実際の適用は showEvent 後まで遅延する。
        self._default_dock_ratio_applied = False

    # ─── Load pipeline ─────────────────────────────────────────────────────────

    def _load_file(self, path: str | Path) -> None:
        """Load *path* off-thread. CSV は事前にフォーマットを解決する (LD-01)。"""
        session = self.app_vm.session
        target = Path(path)
        if session.is_csv(target):
            fmt = self._csv_format_resolver(target)
            if fmt is None:
                self._on_load_cancelled(target)  # ダイアログキャンセル=中止(エラー無し)
                return
        else:
            fmt = None  # MDF は従来どおりフォーマット不要
        cancel_event = threading.Event()  # 所有=ここ・セット権=controller(spec §4.1)

        def _discard(outcome: LoadOutcome) -> None:
            # 手遅れ完走のロールバック; remove_group の戻り値は on_discard の
            # Callable[[LoadOutcome], None] 契約に不要なので握りつぶす。
            session.remove_group(outcome.key, force=True)

        self._load_controller.submit(
            lambda: session.load(
                target,
                fmt,
                cancel=cancel_event.is_set,
                confirm_expansion=self._expansion_confirmer.confirm,
            ),
            busy=self.busy_overlay,
            cancel_event=cancel_event,
            label=target.name,
            on_success=lambda outcome: self._on_loaded(outcome, target),
            on_error=lambda err: self._on_load_error(target, err),
            on_cancelled=lambda: self._on_load_cancelled(target),
            on_discard=_discard,
        )

    def _default_csv_format_resolver(self, path: Path) -> FormatDefinition | None:
        """既定の CSV フォーマット解決: 自動検出 → 確認ダイアログ (LD-01)。"""
        detected = CsvFormatDetector().detect(path)
        return CsvFormatDialog.ask(detected, parent=self)

    def _on_loaded(self, outcome: LoadOutcome, source_path: Path | None = None) -> None:
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
        # SH-01: Recent には再開可能な絶対パスを保存する。表示用の source は
        # basename(source_name) だが、それを保存すると Path.exists() の剪定で
        # 消えるため、実際に開いたパス(source_path)を使う。
        if source_path is not None:
            self.recent_files.add(str(source_path))
            self._rebuild_recent_menu()
            self.welcome_view.refresh()

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
            self._workbench_started = True
            self._update_central()
        if change in ("active_file", "loaded", "unloaded"):
            self._update_window_title()
        if change in ("loaded", "unloaded"):
            # SH-03: データがあるときだけ Export を許可 (spec §6.4)
            self.shell_actions.action("export").setEnabled(
                bool(self.app_vm.loaded_file_keys)
            )

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

    def _update_central(self) -> None:
        """Welcome か GraphArea を表示。初回ロードで GraphArea へ永続スワップ。

        _workbench_started が True になったら、最後の1件をアンロードしても
        Welcome へは戻さない (workbench を奪わない・spec §4.2)。
        """
        widget = self.graph_area_view if self._workbench_started else self.welcome_view
        self.central_stack.setCurrentWidget(widget)

    def showing_welcome(self) -> bool:
        return self.central_stack.currentWidget() is self.welcome_view

    def _on_open_requested(self, path: object) -> None:
        """WelcomeView からの Open 要求。None=ダイアログ / str=そのパスを直接ロード。"""
        if path is None:
            self.open_file()
        else:
            self._load_file(str(path))

    def _add_to_active_panel(self, keys: list[str]) -> None:
        """Plot *keys* on the ACTIVE panel of the active tab (PC-07)."""
        vm = self.graph_area_vm
        panels = vm.panels(vm.active_tab_index)
        if not panels:
            return  # 防御的 no-op (VM 不変条件により通常到達不能)
        target = panels[vm.active_panel_index()]
        for key in keys:
            target.add_signal(key)

    def _active_panel_vm(self) -> GraphPanelVM | None:
        """Analyze メニューの AnalysisActions dispatch (spec §2.2: メニューバー経由
        は常にアクティブパネルへ配送)。GraphAreaView 側の解決を素通しする。"""
        return self.graph_area_view.active_panel_vm()

    def _sync_analysis_actions(self) -> None:
        """Analyze メニュー表示直前に checked/enabled をアクティブパネルへ同期する。

        setChecked は toggled は発火させても triggered は発火させないため (Qt の
        仕様)、ここで無条件に呼んでも共有 QAction の VM 変異ハンドラ (triggered
        配線) は起動しない — 「メニューを開いただけでカーソルが動く」事故の構造的
        防止 (spec §2.2 blocker)。
        """
        sync_analysis_actions(self._analysis_actions, self._active_panel_vm())

    # ─── Actions ────────────────────────────────────────────────────────────────

    _OPEN_FILTER = "計測ファイル (*.mf4 *.mdf *.dat *.csv);;すべてのファイル (*)"

    def open_file(self, *_: object) -> None:
        """File>Open / Ctrl+O / Welcome CTA / toolbar の集約先。

        v1 は単一ファイル。選択されたら既存 _load_file (オフスレッド・CSV
        フォーマット解決・診断) へ委譲する。
        """
        path, _sel = QFileDialog.getOpenFileName(
            self, "計測ファイルを開く", "", self._OPEN_FILTER
        )
        if path:
            self._load_file(path)

    def export_csv(self, *_: object) -> None:
        """File>Export / Ctrl+E / ツールバーの集約先 (SH-03)。

        アクティブパネルのプロット中信号を初期選択に ExportCsvDialog を開き、
        確定したら既存の BusyOverlay パターンでオフスレッド書き出しする。
        """
        panels = self.graph_area_vm.panels(self.graph_area_vm.active_tab_index)
        initial = (
            set(panels[self.graph_area_vm.active_panel_index()].plotted_signal_keys())
            if panels
            else set()
        )
        req = ExportCsvDialog.ask(self.app_vm, initial, self)
        if req is None:
            return
        session = self.app_vm.session
        self._export_controller.submit(
            lambda: session.export_csv(
                req.signals, req.output_path, req.use_unified_timeline, req.options
            ),
            busy=self.busy_overlay,
            label=req.output_path.name,
            on_success=lambda: self.statusBar().showMessage(
                f"エクスポートしました: {req.output_path.name}"
            ),
            on_error=self._on_export_error,
        )

    def _on_export_error(self, err: Exception) -> None:
        # FB-01 同様: 失敗を握りつぶさない (ステータス+モーダル)。
        self.statusBar().showMessage(f"⛔ エクスポート失敗: {err}")
        QMessageBox.critical(
            self, "エクスポートエラー", f"CSV を書き出せませんでした。\n\n{err}"
        )

    def open_data_explorer(self, *_: object) -> None:
        """Open (or re-show) the standalone Data Explorer window (R1.5)."""
        if self.data_explorer is None:
            self.data_explorer = DataExplorerView(
                self.app_vm, load_handler=self._load_file
            )
        self.data_explorer.show()
        self.data_explorer.raise_()

    def _rebuild_recent_menu(self) -> None:
        """File>Recent Files を現在の MRU (存在するもの) で作り直す。"""
        self.recent_menu.clear()
        paths = self.recent_files.existing()
        if not paths:
            empty = self.recent_menu.addAction("（履歴なし）")  # noqa: RUF001
            empty.setEnabled(False)
            return
        for p in paths:
            act = self.recent_menu.addAction(p)
            act.triggered.connect(lambda _=False, path=p: self._load_file(path))

    def _about_text(self) -> str:
        try:
            from importlib.metadata import version

            ver = version("valisync")
        except Exception:  # PackageNotFoundError 等
            ver = "unknown"
        return f"ValiSync v{ver} — ADAS 信号解析デスクトップ"

    def _show_about(self) -> None:
        QMessageBox.about(self, "About ValiSync", self._about_text())

    # ─── State persistence ────────────────────────────────────────────────────

    def save_state(self) -> None:
        """Persist window geometry and dock arrangement to QSettings."""
        settings = QSettings(_ORG, _APP)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        settings.setValue("dockCollapsed", self._dock_collapsed_map())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Persist window state on close so it can be restored next launch (R2.3)."""
        self.save_state()
        super().closeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        """UX-21 応急: 初回 show 後に既定ドック比率を一度だけ適用する (spec §1.5-12b)。

        pre-show (__init__ 時点) は dock extent が未確定で resizeDocks が no-op
        になる (_collapse_dock の Important 2 コメントと同型の罠) ため、
        singleShot(0) で「show イベント自体の処理が終わった後」まで遅延する。
        """
        super().showEvent(event)
        if not self._default_dock_ratio_applied:
            self._default_dock_ratio_applied = True
            if not self._state_restored:
                QTimer.singleShot(0, self._apply_default_dock_ratio)

    def _apply_default_dock_ratio(self) -> None:
        """初期ドック比率 File:Channel≈1:4 (UX-21 応急・spec §1.5-12)。

        pre-show は dock extent 未確定で no-op になるため初回 show 後に呼ぶ
        (_apply_saved_collapse が hide 主体の別手法で回避しているのと同じ
        pre-show 罠 — こちらは resizeDocks が extent を要するため遅延で回避)。
        """
        self.resizeDocks(
            [self.file_dock, self.channel_dock], [1, 4], Qt.Orientation.Vertical
        )

    def _restore_state(self) -> bool:
        """Restore geometry/dock state saved by a previous session.

        Guarded against missing/corrupt values: absent keys return None and
        both restoreGeometry/restoreState silently ignore falsy byte-arrays.

        Returns whether ``restoreState()`` actually applied a saved
        ``windowState`` (its own bool, propagated — spec §1.5-12a). Absent a
        saved state this is False, which is what gates the UX-21 default dock
        ratio: a user's own saved layout must not be clobbered.
        """
        settings = QSettings(_ORG, _APP)
        geometry = settings.value("geometry")
        state = settings.value("windowState")
        if geometry:
            self.restoreGeometry(geometry)
        restored = False
        if state:
            restored = self.restoreState(state)
        self._apply_saved_collapse()
        return restored

    def _dock_collapsed_map(self) -> dict[str, bool]:
        return {
            name: (name in self._collapsed_docks) for name in self._collapsible_bars
        }

    def _save_dock_collapsed(self, *_: object) -> None:
        settings = QSettings(_ORG, _APP)
        settings.setValue("dockCollapsed", self._dock_collapsed_map())

    def _apply_saved_collapse(self) -> None:
        """QSettings の collapse 状態を新機構 (hide+レール) で再適用。

        restoreState はドックの配置/サイズを戻すが「畳み=hide+レールタブ」は
        runtime 状態で乗らないため、_restore_state/_reset_layout の後に再適用する
        (corner 再適用と同型)。
        """
        settings = QSettings(_ORG, _APP)
        saved = settings.value("dockCollapsed") or {}
        if not isinstance(saved, dict):
            return
        docks = {d.objectName(): d for d in self._collapsible_bars_docks()}
        for name, dock in docks.items():
            if bool(saved.get(name, False)):
                self._collapse_dock(dock)

    def _collapsible_bars_docks(self) -> list[QDockWidget]:
        return [self.file_dock, self.channel_dock, self.diagnostics_dock]

    def _dock_extent(self, dock: QDockWidget) -> int:
        area = self.dockWidgetArea(dock)
        from valisync.gui.views.dock_collapse_rail import RailKind, rail_kind_for_area

        kind = rail_kind_for_area(area)
        return dock.width() if kind is RailKind.VERTICAL else dock.height()

    def _collapse_dock(self, dock: QDockWidget) -> None:
        if dock.isFloating():
            return  # フロート中は畳まない (chevron も無効)
        area = self.dockWidgetArea(dock)
        rail = self._collapse_rails.get(area)
        if rail is None:
            return  # 対応外の辺 (通常起きない — 上は禁止済み)
        name = dock.objectName()
        # 起動時の _apply_saved_collapse は window.show() より前 (未表示・未
        # レイアウト) に走るため、そこで extent を捕捉すると未確定の既定値を
        # 記録してしまう (レビュー Important 2)。既に隠れている (=このドック
        # のレイアウトはまだ確定していない) ドックからは捕捉しない — 展開時は
        # resizeDocks をスキップし、Qt 自身の restoreState 復元に委ねる。
        if not dock.isHidden():
            self._expanded_extent[name] = self._dock_extent(dock)
        try:
            self._suppress_dock_reconcile = True
            dock.hide()
        finally:
            self._suppress_dock_reconcile = False
        title = {
            "file_dock": "File Browser",
            "channel_dock": "Channel Browser",
            "diagnostics_dock": "Diagnostics",
        }[name]
        rail.add_tab(dock, title, self._dock_rail_order.get(name, 0))
        self._collapsed_docks.add(name)
        self._save_dock_collapsed()

    def _expand_dock(self, dock: QDockWidget) -> None:
        from valisync.gui.views.dock_collapse_rail import RailKind, rail_kind_for_area

        name = dock.objectName()
        for rail in self._collapse_rails.values():
            rail.remove_tab(dock)
        try:
            self._suppress_dock_reconcile = True
            dock.show()
        finally:
            self._suppress_dock_reconcile = False
        area = self.dockWidgetArea(dock)
        extent = self._expanded_extent.get(name)
        kind = rail_kind_for_area(area)
        if extent is not None and kind is not None:
            orient = (
                Qt.Orientation.Horizontal
                if kind is RailKind.VERTICAL
                else Qt.Orientation.Vertical
            )
            self.resizeDocks([dock], [extent], orient)
        self._collapsed_docks.discard(name)
        self._save_dock_collapsed()

    def _on_dock_visibility_changed(self, dock: QDockWidget, visible: bool) -> None:
        """畳み状態機械を経由しない外部 show() を自己修復する (レビュー Important 1)。

        View メニュー/ツールバーの toggleViewAction、_on_load_error の
        diagnostics_dock.show() など、_expand_dock を呼ばない経路で畳み済み
        ドックが可視化された場合、レールタブ除去・_collapsed_docks 除籍・
        永続化を _expand_dock に委譲して行う。hide 方向 (visible=False) は
        素通り — 畳み対象でないドックを閉じる操作は通常の hide のままでよく、
        ここで「畳む」処理はしない (collapse は chevron からのみ)。
        """
        if self._suppress_dock_reconcile:
            return  # _collapse_dock/_expand_dock 自身の hide()/show() 由来 (再入防止)
        if visible and dock.objectName() in self._collapsed_docks:
            self._expand_dock(dock)

    def _apply_dock_corners(self) -> None:
        """FU-10: give the bottom-right corner to the Right area so the File/Channel
        Browser docks span the right column full-height (Qt's default assigns it to
        the Bottom area, letting Diagnostics extend under and shorten them). Called
        AFTER every restoreState -- restoreState resets corner config to defaults."""
        self.setCorner(
            Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea
        )

    def _reset_layout(self) -> None:
        """Restore the default dock/toolbar arrangement captured at startup (SH-11)."""
        for dock in list(self._collapsible_bars_docks()):
            if dock.objectName() in self._collapsed_docks:
                self._expand_dock(dock)
        self.restoreState(self._default_state)
        self._apply_dock_corners()  # restoreState reset the FU-10 corner; re-apply
        # spec §1.5-12c: _default_state was captured before the 1:4 ratio is ever
        # applied (it's saved at the top of __init__), so without this the
        # startup ratio and Reset Layout would silently diverge.
        self._apply_default_dock_ratio()

    def _on_theme_selected(self, mode: ThemeMode) -> None:
        """テーマ radio 選択 — 保存のみ。set_active/apply_theme は呼ばない (再起動反映)。"""
        theme_apply.save_theme_mode(mode)
        labels = {
            ThemeMode.LIGHT: "ライト",
            ThemeMode.DARK: "ダーク",
            ThemeMode.AUTO: "オート",
        }
        self.statusBar().showMessage(
            f"テーマを「{labels[mode]}」に変更しました。再起動で反映されます", 8000
        )
