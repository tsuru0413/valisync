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

import itertools
import threading
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, cast

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QFont,
    QKeySequence,
    QShowEvent,
    QStatusTipEvent,
)
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from valisync.core.loaders.csv_format_detector import CsvFormatDetector
from valisync.core.models.format_def import FormatDefinition
from valisync.core.session import LoadOutcome
from valisync.gui import reference_overlay
from valisync.gui import strings as S
from valisync.gui.strings import mn
from valisync.gui.theme import apply as theme_apply
from valisync.gui.theme import icons, tokens
from valisync.gui.theme import qss as theme_qss
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

# QMainWindow の saveState/restoreState 用スキーマバージョン。ドック構造を非互換に
# 変えたら bump する。旧版で保存された windowState blob を新コードが restoreState で
# 適用すると、食い違うドック配置が show() 描画時にネイティブクラッシュ (0xC0000005)
# する実機退行を防ぐ (candidate A のレールドック導入で顕在化)。restoreState(state,
# version) は version 不一致で False を返し適用しない。合わせて _restore_state 側で
# stateVersion キーを突合し、不一致なら永続状態を破棄して既定レイアウトで起動する。
# v2: 空レールドックを QDockAreaLayout の常在メンバにしない非互換変更 (レールを
# member→非member 化)。v1 の member 入り blob を restore すると show() 前の緩和経路
# (normalize の removeDockWidget) に載るが、非再現の native crash は決定的排除が正解
# ゆえ bump して v1 blob を discard する (代償=直近 dev レイアウトの一度きりリセット)。
_STATE_VERSION = 2

# spec §2.3: 辺 (Qt.DockWidgetArea) → dock_panel_* アイコン意味名の接尾辞。
# 上/なしは対象外 (allowedAreas で禁止済み)。フォールバック "left" は理論上の
# 防御 — dockWidgetArea() はフロート中/非表示中も実領域を返し NoDockWidgetArea
# を返さないことをレビューで実測済みのため、通常到達しない。
_DOCK_EDGE_SUFFIX: dict[Qt.DockWidgetArea, str] = {
    Qt.DockWidgetArea.LeftDockWidgetArea: "left",
    Qt.DockWidgetArea.RightDockWidgetArea: "right",
    Qt.DockWidgetArea.BottomDockWidgetArea: "bottom",
}


def _dock_toggle_state(
    is_hidden: bool, collapsed: bool, edge: Qt.DockWidgetArea
) -> tuple[bool, str]:
    """(可視/畳み/辺) → (checked, icon 意味名) の全域写像 (spec §2.3 の状態表)。

    Qt ウィジェットに触れない純ロジック — `_sync_dock_action` から呼ばれる。
    畳み (collapsed) は is_hidden の値に関係なく最優先 (レールタブが可視の
    代理表現) で checked=True・partial アイコン。畳みでなく可視 (not
    is_hidden) なら checked=True・通常アイコン。どちらでもなければ非表示
    (checked=False・アイコンは通常形のまま — unchecked の見た目で非表示を
    表現する)。並行状態を作らない設計 (spec §2.3) の直接反映として、この
    3 分岐が唯一の真実。
    """
    base = f"dock_panel_{_DOCK_EDGE_SUFFIX.get(edge, 'left')}"
    if collapsed:
        return True, f"{base}_partial"
    if not is_hidden:
        return True, base
    return False, base


class MainWindow(QMainWindow):
    """Application shell: dockable Channel_Browser + Graph_Area, wired together.

    Parameters
    ----------
    app_vm:
        The application-level ViewModel.  Its ``session`` is shared with the
        Channel_Browser and Graph_Area ViewModels so loaded data is visible
        everywhere.
    """

    # spec §2.3: View メニュー/ツールバー 2 面が共有するカスタム QAction の文言
    # (非ニーモニクス — G-46 決定どおり dock トグルは付与対象外)。
    _DOCK_TITLES: ClassVar[dict[str, str]] = {
        "file_dock": S.DOCK_FILE_BROWSER,
        "channel_dock": S.DOCK_CHANNEL_BROWSER,
        "diagnostics_dock": S.DOCK_DIAGNOSTICS,
    }

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
        self.file_dock = QDockWidget(S.DOCK_FILE_BROWSER, self)
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
        self.channel_dock = QDockWidget(S.DOCK_CHANNEL_BROWSER, self)
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
        # candidate A (#17): central_stack を直接中央に据える。折りたたみレールは
        # 中央の縁ではなく「各辺の最外ドック」に据える (下で構築)。
        self.setCentralWidget(self.central_stack)

        # ── 辺対応の折りたたみ — レール最外ドック化 (candidate A・#17) ─────────
        # 旧: レール widget を中央 (CentralWithRails) の縁に置いていたため、片方の
        # ドックが開いていると QMainWindow のドック領域 (中央の外側) に残る開ドックと
        # プロットの間にレールが挟まった。candidate A ではレールを各辺の最外側の
        # QDockWidget に据え、順序を「プロット / 開ドック / レール(画面端)」にする。
        from valisync.gui.views.dock_collapse_rail import DockCollapseRail

        # レール最外化の再入 (_place_rail_outermost が real dock を動かすと
        # dockLocationChanged が再発火する) を防ぐガード。
        self._suppress_rail_reassert = False
        self._collapse_rails: dict[Qt.DockWidgetArea, DockCollapseRail] = {}
        self._rail_docks: dict[Qt.DockWidgetArea, QDockWidget] = {}
        for edge in (
            Qt.DockWidgetArea.LeftDockWidgetArea,
            Qt.DockWidgetArea.RightDockWidgetArea,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        ):
            rail = DockCollapseRail(edge)
            rail.expand_requested.connect(self._expand_dock)
            rail_dock = QDockWidget("", self)
            # objectName は saveState/restoreState 互換のため安定 (guardrail 2)。
            rail_dock.setObjectName(f"collapse_rail_{_DOCK_EDGE_SUFFIX[edge]}")
            rail_dock.setWidget(rail)
            # 非移動/非クローズ/非フロート + タイトルバー無し = 薄いレール見た目
            # (guardrail 1)。allowedAreas も自辺へ固定して迷子移動を防ぐ。
            rail_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
            rail_dock.setTitleBarWidget(QWidget(rail_dock))
            rail_dock.setAllowedAreas(edge)
            self._collapse_rails[edge] = rail
            self._rail_docks[edge] = rail_dock
        # #17 (native crash 根治): レールドックは生成のみで「レイアウト非メンバ」
        # として開始する。空のレールを QDockAreaLayout の常在メンバに残すと、
        # setCorner との不整合な dock-area ツリーを作り window.show() の初回同期
        # relayout (Qt6Widgets) が 0xC0000005 で落ちる実機クラッシュの真因になる。
        # 折りたたんだ時だけ _place_rail_outermost で追加し、空になったら
        # removeDockWidget で完全除去する (_collapse_dock/_expand_dock)。
        # 実ドックの移動 (D&D/restoreState) でレールの最外順序が崩れたら能動是正する
        # (guardrail 3)。レールドック自身は接続しない (自分の再配置で再入しないため)。
        for _real_dock in self._collapsible_bars_docks():
            _real_dock.dockLocationChanged.connect(
                lambda _area, d=_real_dock: self._reassert_rails_after_move(d)
            )

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
            (self.file_dock, S.DOCK_FILE_BROWSER),
            (self.channel_dock, S.DOCK_CHANNEL_BROWSER),
            (self.diagnostics_dock, S.DOCK_DIAGNOSTICS),
        ):
            bar = CollapsibleDockTitleBar(dock, self, title)
            dock.setTitleBarWidget(bar)
            bar.collapse_requested.connect(lambda d=dock: self._collapse_dock(d))
            self._collapsible_bars[dock.objectName()] = bar
            # 集約状態機械 (_expand_dock) を経由しない外部 show() (D-3 の三態
            # カスタム QAction は collapsed 分岐で自ら _expand_dock を呼ぶため
            # 対象外だが、_on_load_error の直接 show() や QDockWidget 組込み
            # toggleViewAction() 等、経由しない経路は依然存在する) が畳み状態を
            # 孤立させないよう、可視化を単一箇所で自己修復する (レビュー
            # Important 1)。_restore_state() より前に接続すること — このループ
            # 時点では _collapsed_docks は空なので起動時の restoreState 由来の
            # 可視化変化は no-op。
            dock.visibilityChanged.connect(
                lambda visible, d=dock: self._on_dock_visibility_changed(d, visible)
            )

        # D-3/UX-45: ドックごとに 1 個のカスタム checkable QAction (三態トグル)
        # を View メニュー/ツールバー 2 面共有で構築する。_restore_state() より
        # 前に呼ぶこと (直上の visibilityChanged 接続と同じ制約 — restoreState は
        # visibilityChanged をフラッピング発火し最終状態で収束させる必要がある)。
        self._build_dock_actions()

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
        # E-3: Welcome CTA は ShellActions より先に構築されるため後注入
        # (ラベル部固定・ショートカット部のみ action.changed で追随)。
        self.welcome_view.set_open_action(self.shell_actions.action("open"))

        # ── メニューバー ─────────────────────────────────────────────────────
        file_menu = self.menuBar().addMenu(S.MENU_FILE)
        file_menu.addAction(self.shell_actions.action("open"))
        file_menu.addAction(self.shell_actions.action("open_folder"))
        self.recent_menu = file_menu.addMenu(S.MENU_RECENT)
        file_menu.addAction(self.shell_actions.action("export"))
        file_menu.addSeparator()
        self.action_exit = file_menu.addAction(S.ACTION_EXIT)
        # StandardKey.Quit は Windows で Key_Exit(押せないメディアキー)に解決する
        # ため、明示 Ctrl+Q を使う(主対象 OS は Windows)。
        self.action_exit.setShortcut(QKeySequence("Ctrl+Q"))
        self.action_exit.triggered.connect(self.close)

        # ── View menu (dock toggles, R1.4) ───────────────────────────────────
        # D-3/UX-45: toggleViewAction ではなく _build_dock_actions が構築した
        # 三態カスタム QAction を掲載する (ツールバーと共有 — 2 面参照一致)。
        view_menu = self.menuBar().addMenu(S.MENU_VIEW)
        view_menu.addAction(self._dock_actions["file_dock"])
        view_menu.addAction(self._dock_actions["channel_dock"])
        view_menu.addAction(self._dock_actions["diagnostics_dock"])
        view_menu.addSeparator()

        # 増分4: テーマ三態 (再起動反映 — 選択は QSettings 保存のみ・spec §11)。
        theme_menu = view_menu.addMenu(S.MENU_THEME)
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        current_mode = theme_apply.load_theme_mode()
        for label, mode in (
            (S.THEME_LIGHT, ThemeMode.LIGHT),
            (S.THEME_DARK, ThemeMode.DARK),
            (S.THEME_AUTO_MENU_LABEL, ThemeMode.AUTO),
        ):
            act = theme_menu.addAction(label)
            act.setCheckable(True)
            self._theme_group.addAction(act)
            # setChecked は triggered 配線の前 (排他カスケード誤発火の構造回避 —
            # gui_qactiongroup_exclusive_radio_menu の既存規約)
            act.setChecked(mode is current_mode)
            act.triggered.connect(lambda _=False, m=mode: self._on_theme_selected(m))

        view_menu.addSeparator()
        self.action_reset_layout = view_menu.addAction(S.ACTION_RESET_LAYOUT)
        self.action_reset_layout.triggered.connect(self._reset_layout)

        # Analyze メニュー (spec §2.2): 各パネルの空白右クリックメニューと同一の
        # AnalysisActions インスタンスを掲載する (checked/文言の乖離を構造防止)。
        analyze_menu = self.menuBar().addMenu(S.MENU_ANALYZE)
        analyze_menu.addAction(self._analysis_actions.cursor_a)
        analyze_menu.addAction(self._analysis_actions.cursor_b)
        analyze_menu.addSeparator()
        analyze_menu.addAction(self._analysis_actions.clear_cursors)
        interp_menu = analyze_menu.addMenu(mn(S.INTERP_METHOD, "I"))
        for act in self._analysis_actions.interp_actions.values():
            interp_menu.addAction(act)
        analyze_menu.addSeparator()
        analyze_menu.addAction(self._analysis_actions.step_hint)
        # 比較モードトグル (comparison-mode-toggle spec §2 M4): AnalysisActions
        # (panel-scoped) には載せない — app_vm 由来の状態を同期できないため、
        # MainWindow 所有の独立 QAction とし checked/enabled は
        # _sync_analysis_actions 内で app_vm を直読して同期する。
        analyze_menu.addSeparator()
        self._comparison_mode_action = QAction(S.ACTION_COMPARISON_MODE, self)
        self._comparison_mode_action.setCheckable(True)
        self._comparison_mode_action.triggered.connect(self._on_toggle_comparison_mode)
        analyze_menu.addAction(self._comparison_mode_action)
        analyze_menu.setToolTipsVisible(True)
        # aboutToShow の setChecked 同期は toggled は発火させても triggered は発火
        # させない (Qt 仕様) ため、ここで無条件に同期してもハンドラは起動しない。
        analyze_menu.aboutToShow.connect(self._sync_analysis_actions)

        help_menu = self.menuBar().addMenu(S.MENU_HELP)
        about = help_menu.addAction(mn(S.ABOUT_TITLE, "A"))
        about.triggered.connect(self._show_about)

        # ── Toolbar (R1.5) ───────────────────────────────────────────────────
        toolbar: QToolBar = self.addToolBar(S.TOOLBAR_MAIN)
        toolbar.setObjectName("main_toolbar")  # required for saveState/restoreState
        toolbar.addAction(self.shell_actions.action("open"))
        toolbar.addAction(self.shell_actions.action("export"))
        toolbar.addSeparator()
        self.action_data_explorer = QAction(
            icons.icon("data_explorer"),
            S.ACTION_DATA_EXPLORER,
            self,
        )
        self.action_data_explorer.setToolTip(S.STATUS_OPEN_DATA_EXPLORER)
        self.action_data_explorer.setStatusTip(S.STATUS_OPEN_DATA_EXPLORER)
        self.action_data_explorer.triggered.connect(self.open_data_explorer)
        toolbar.addAction(self.action_data_explorer)
        toolbar.addSeparator()
        # D-3/UX-45: 三態カスタム QAction (View メニューと共有・同一 QAction
        # インスタンス)。File/Channel は同一辺 (右) で三態アイコンが同一になり
        # テキスト無しでは区別できない (実測済みの退行) ため、この 3 ボタンだけ
        # ToolButtonTextBesideIcon にする (他のツールバーボタンは既定の icon-only
        # のまま — spec §2.3)。
        for dock_name in ("file_dock", "channel_dock", "diagnostics_dock"):
            dock_action = self._dock_actions[dock_name]
            toolbar.addAction(dock_action)
            dock_button = toolbar.widgetForAction(dock_action)
            assert isinstance(dock_button, QToolButton)
            dock_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # ── Status bar: 左=計測即値 (A/B/Δt) / 右=メッセージ (spec §2.4・v3 決定2) ─
        self._build_status_bar()
        # FB-06: shown even before any load.
        self.set_status_message("準備完了")

        # ── Cross-view wiring ────────────────────────────────────────────────
        self.channel_browser_view.add_to_panel_requested.connect(
            self._add_to_active_panel
        )
        self.file_browser_view.overlay_reference_requested.connect(
            self._overlay_reference_signals
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
        # spec §2.4: area レベル _notify("cursor") (Task 2 発火源) と タブ/パネル/
        # アクティブ変更を 1 本で購読し、左即値をアクティブタブの CursorState へ
        # 追随させる (パネル個別購読の張り替えを避ける pull 型)。
        self._graph_area_unsubscribe = self.graph_area_vm.subscribe(
            self._on_graph_area_change
        )
        self._update_immediate_values()  # 初期表示 (未設置=空文字)

        self._rebuild_recent_menu()
        # SH-11: 永続状態で上書きされる前の既定配置を捕捉 (Reset Layout 用)。
        self._default_state = self.saveState(_STATE_VERSION)
        self._state_restored = self._restore_state()
        # restoreState resets dock corner config to Qt defaults, so re-apply FU-10
        # after the startup restore (and after Reset Layout -- see _reset_layout).
        self._apply_dock_corners()
        # D-3/UX-45: restoreState はフラッピング (一時的な visibilityChanged の
        # 連打) を経て最終状態に収束するため、visibilityChanged 経由の sync だけ
        # に頼らず、構築完了時点で全ドックへ無条件に再同期する (spec §2.3)。
        for _dock in self._collapsible_bars_docks():
            self._sync_dock_action(_dock)
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
            msg += S.STATUS_DIAG_ALERT_TMPL.format(n=n_alert)
        elif n_info:
            msg += S.STATUS_DIAG_INFO_TMPL.format(n=n_info)
        self.set_status_message(msg)
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
        self.set_status_message(f"⛔ 読み込み失敗: {source}")
        self.diagnostics_dock.show()
        self.diagnostics_dock.raise_()
        QMessageBox.critical(
            self,
            "読み込みエラー",
            f"{source} を読み込めませんでした。\n\n" + "; ".join(messages),
        )

    def _on_load_cancelled(self, path: Path) -> None:
        # ユーザー起点の正常系: status のみ(モーダル/診断は出さない・spec §6)
        self.set_status_message(f"キャンセルしました: {path.name}")

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

    def _overlay_reference_signals(self, target_key: str) -> None:
        """基準ファイルの同名信号をアクティブパネルの同軸へ重ねる (E-2b)。

        Thin dispatcher (spec §3's "重ねハンドラ"): resolve the active panel /
        reference key here (Qt-owned state), delegate the actual matching
        algorithm to the pure ``reference_overlay`` module, then render the
        result as a status message.
        """
        reference_key = self.app_vm.reference_file_key
        if reference_key is None:
            return  # 防御的 no-op (メニューはロード済みファイルがある時のみ出る)
        panels = self.graph_area_vm.panels(self.graph_area_vm.active_tab_index)
        if not panels:
            return  # 防御的 no-op (VM 不変条件により通常到達不能)
        panel = panels[self.graph_area_vm.active_panel_index()]
        result = reference_overlay.overlay_reference_signals(
            panel, self.app_vm.session, reference_key, target_key
        )
        target_name = reference_overlay.file_display_name(
            self.app_vm.session, self.app_vm.loaded_file_keys, target_key
        )
        self.set_status_message(
            reference_overlay.format_overlay_summary(result, target_name),
            timeout_ms=8000,
        )

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

        比較モード項目 (comparison-mode-toggle spec §2 M4) は panel VM でなく
        app_vm を直読する — checked は生フラグ `comparison_enabled`
        (`is_comparison_mode()` の AND ≥2 述語ではない・取り違えは「1 ファイル+ON」で
        checked が誤って False になる退行)。
        """
        sync_analysis_actions(self._analysis_actions, self._active_panel_vm())
        self._comparison_mode_action.setChecked(self.app_vm.comparison_enabled)
        enabled = len(self.app_vm.loaded_file_keys) >= 2
        self._comparison_mode_action.setEnabled(enabled)
        if not enabled:
            self._comparison_mode_action.setToolTip(S.TOOLTIP_COMPARISON_NEEDS_TWO)

    def _on_toggle_comparison_mode(self, checked: bool) -> None:
        """比較モードトグルのハンドラ。ON 時は基準ファイルを開示する (spec §3 M8) —
        `register_loaded` が無条件に最初のロードを基準へ設定済みだが単一モードでは
        不可視のため、「いつの間にか基準が決まっている」唐突さを避ける。"""
        self.app_vm.set_comparison_mode(checked)
        if checked and self.app_vm.reference_file_key is not None:
            name = self.app_vm.session.source_name(self.app_vm.reference_file_key)
            self.set_status_message(
                S.STATUS_COMPARISON_REFERENCE_TMPL.format(name=name)
            )

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
        出力範囲 (F-0/UX-28) の x_range・カーソル A/B はここでアクティブタブから
        一度だけスナップショットして DI 注入する — ダイアログは GraphAreaVM を
        直接握らない (View 分離・spec §2.3)。表示中に選択が変わっても x_range/
        カーソルは反映されない (意図的なスナップショット)。オフセット有無は対照的
        にリアクティブでなければならない (I2 fix・task-3-review.md #1・spec §2.1):
        ダイアログのツリーは全ファイル全信号を列挙するため、`initial` だけを見た
        bool を1回渡すと、開いた後に別ファイルのオフセット信号をチェックしても
        ガードが働かない穴になる。値でなく `panel.offset_for`
        (Callable[[str], float] — app-global な signal/file offset dict を
        任意の namespaced key に対し解決できる) をそのまま渡し、ダイアログ側で
        checked 集合に対しその場で再評価させる。
        """
        panels = self.graph_area_vm.panels(self.graph_area_vm.active_tab_index)
        initial = (
            set(panels[self.graph_area_vm.active_panel_index()].plotted_signal_keys())
            if panels
            else set()
        )
        panel = self.graph_area_vm.active_panel()
        cursor_state = self.graph_area_vm.active_tab().cursor_state
        req = ExportCsvDialog.ask(
            self.app_vm,
            initial,
            self,
            x_range=panel.x_range,
            cursor_a=cursor_state.cursor_t,
            cursor_b=cursor_state.cursor_t_b,
            offset_for=panel.offset_for,
        )
        if req is None:
            return
        session = self.app_vm.session
        self._export_controller.submit(
            lambda: session.export_csv(
                req.signals, req.output_path, req.use_unified_timeline, req.options
            ),
            busy=self.busy_overlay,
            label=req.output_path.name,
            on_success=lambda: self.set_status_message(
                f"エクスポートしました: {req.output_path.name}"
            ),
            on_error=self._on_export_error,
        )

    def _on_export_error(self, err: Exception) -> None:
        # FB-01 同様: 失敗を握りつぶさない (ステータス+モーダル)。
        self.set_status_message(f"⛔ エクスポート失敗: {err}")
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

            ver_part = f"v{version('valisync')}"
        except Exception:  # PackageNotFoundError 等
            # G-37: "v{ver}" の合成をやめ、不明時は表示分岐で文字列全体を差し替える
            # (旧 "v不明" のような合成事故を構造的に回避)。
            ver_part = S.ABOUT_VERSION_UNKNOWN
        return f"ValiSync {ver_part} — ADAS 信号解析デスクトップ"

    def _show_about(self) -> None:
        QMessageBox.about(self, S.ABOUT_TITLE, self._about_text())

    # ─── Status bar (spec §2.4) ─────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        """左=計測即値 (A/B/Δt mono) / 右=メッセージ の 2 領域を構成する。

        左は addWidget (通常領域)・右は addPermanentWidget (常設領域) — Qt 内部の
        showMessage は使わない (それは常設含む左右を一時的に覆い隠すため・§2.4)。
        """
        bar = self.statusBar()
        # mono フォントは QFont で設定 (font-family QSS は等幅へ解決しないことがある)。
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("monospace")
        c = tokens.active().colors
        self._status_cursor_a = QLabel("")
        self._status_cursor_b = QLabel("")
        self._status_cursor_delta = QLabel("")
        for label, color in (
            (self._status_cursor_a, c.chrome_cursor_a),
            (self._status_cursor_b, c.chrome_cursor_b),
            (self._status_cursor_delta, c.chrome_text),
        ):
            label.setFont(mono)
            label.setStyleSheet(theme_qss.status_immediate_label(color))
            bar.addWidget(label)
        # 右: メッセージラベル (showMessage の置換先)。
        self._status_message_label = QLabel("")
        bar.addPermanentWidget(self._status_message_label)
        # 単発自動クリア用タイマー (再呼び出しで破棄・set_status_message で使う)。
        self._status_timer: QTimer | None = None

    def set_status_message(self, text: str, timeout_ms: int = 0) -> None:
        """右ラベルへメッセージを表示する (showMessage の置換・spec §2.4)。

        timeout_ms > 0 で単発 QTimer 自動クリア。再呼び出しは前タイマーを破棄する
        ので、連続表示で古いクリアが新メッセージを消す事故を防ぐ。
        """
        self._status_message_label.setText(text)
        if self._status_timer is not None:
            self._status_timer.stop()
            self._status_timer = None
        if timeout_ms > 0:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._status_message_label.setText(""))
            timer.start(timeout_ms)
            self._status_timer = timer

    def status_message(self) -> str:
        """右メッセージラベルの現在テキスト (set_status_message と対称・テスト用)。"""
        return self._status_message_label.text()

    def event(self, event: QEvent) -> bool:
        """QStatusTipEvent を横取りして右ラベルへ流す (spec §2.4 blocker)。

        Qt はメニュー/ツールバー hover のたび QStatusTipEvent を既定処理で内部
        showMessage へ流し、左の計測即値領域を覆い隠す。ここで消費し (既定処理へ
        通さず True を返す) set_status_message へルーティングすることで左即値を
        守る。空 tip は hover 解除時に Qt が送るので、そのままクリア動作となる。
        """
        if event.type() == QEvent.Type.StatusTip:
            self.set_status_message(cast(QStatusTipEvent, event).tip())
            return True
        return super().event(event)

    def _on_graph_area_change(self, change: str) -> None:
        """アクティブタブの CursorState 変化・切替で左即値を更新する (spec §2.4)。"""
        if change in ("cursor", "active", "tabs", "panels"):
            self._update_immediate_values()

    def _update_immediate_values(self) -> None:
        """アクティブタブのアクティブパネル VM から A/B/Δt を pull して setText。

        未設置のフィールドは空文字。Δt は A・B の双方が設置済みのときのみ表示する。
        """
        panel = self.graph_area_vm.active_panel()  # VM 不変条件により常に有効
        a = panel.cursor_t
        b = panel.cursor_t_b
        self._status_cursor_a.setText(f"A {a:.3f} s" if a is not None else "")
        self._status_cursor_b.setText(f"B {b:.3f} s" if b is not None else "")
        self._status_cursor_delta.setText(
            f"Δt {b - a:.3f} s" if a is not None and b is not None else ""
        )

    # ─── State persistence ────────────────────────────────────────────────────

    def save_state(self) -> None:
        """Persist window geometry and dock arrangement to QSettings."""
        settings = QSettings(_ORG, _APP)
        settings.setValue("stateVersion", _STATE_VERSION)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState(_STATE_VERSION))
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
        # candidate A: pre-show の _apply_saved_collapse (起動時 restore の畳み再適用)
        # で立てたレールドックの可視/最外は window show で飛ぶ (pre-show の dock
        # setVisible は show で上書きされる — extent と同型の pre-show 罠)。show 後に
        # レールの可視/位置を rail の中身と突き合わせて据え直す。
        QTimer.singleShot(0, self._reconcile_rails_after_show)

    def _reconcile_rails_after_show(self) -> None:
        """レールドックの配置/可視を rail の中身 (タブ有無) と一致させる (show 後)。

        #17: 判定はメンバか (dockWidgetArea != NoDockWidgetArea) と rail の空判定で
        行う。非空レールが未配置 or 不可視なら最外へ追加して表示、空レールが配置済み
        ならレイアウトから除去する。整合済みは触らないので通常 show (un-minimize 等)
        は no-op で余計な再配置フリッカを起こさない。
        """
        for edge, rail in self._collapse_rails.items():
            rail_dock = self._rail_docks[edge]
            is_member = (
                self.dockWidgetArea(rail_dock) != Qt.DockWidgetArea.NoDockWidgetArea
            )
            if not rail.is_empty():
                if not is_member or rail_dock.isHidden():
                    self._place_rail_outermost(edge)
                    rail_dock.setVisible(True)
                    self._pin_rail_thin(edge)
            elif is_member:
                self.removeDockWidget(rail_dock)

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
        # スキーマバージョン突合: 旧版で保存された互換性のないレイアウト状態を新コードが
        # 適用すると show() 描画でネイティブクラッシュする実機退行を防ぐ。不一致 (旧キー
        # 欠落=0 含む) なら永続レイアウトを破棄して既定で起動する (geometry/windowState/
        # dockCollapsed をまとめて除去。次回 close 時に現行版で保存し直される)。
        saved_version = settings.value("stateVersion", 0, type=int)
        if saved_version != _STATE_VERSION:
            settings.remove("geometry")
            settings.remove("windowState")
            settings.remove("dockCollapsed")
            self._normalize_rail_placement()
            return False
        geometry = settings.value("geometry")
        state = settings.value("windowState")
        if geometry:
            self.restoreGeometry(geometry)
        restored = False
        if state:
            restored = self.restoreState(state, _STATE_VERSION)
        # candidate A: restoreState 後にレール順序/可視を正規化してから畳みを再適用
        # (旧 blob はレールドックを含まず最外順序が保証されない・guardrail 4)。
        self._normalize_rail_placement()
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
        rail_dock = self._rail_docks.get(area)
        if rail is None or rail_dock is None:
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
            "file_dock": S.DOCK_FILE_BROWSER,
            "channel_dock": S.DOCK_CHANNEL_BROWSER,
            "diagnostics_dock": S.DOCK_DIAGNOSTICS,
        }[name]
        # #17: 空→非空の最初のタブでのみレールドックをレイアウトへ追加する (空の
        # 間は非メンバ)。was_empty は add_tab より前に捕捉する。既に非空
        # (2つ目以降) なら配置済みなので追加せず表示 + pin のみ。
        was_empty = rail.is_empty()
        rail.add_tab(dock, title, self._dock_rail_order.get(name, 0))
        if was_empty:
            self._place_rail_outermost(area)  # 最外へ追加 (可視は下で明示)
        rail_dock.setVisible(True)
        self._pin_rail_thin(area)
        self._collapsed_docks.add(name)
        self._save_dock_collapsed()
        # D-3/UX-45: _collapsed_docks 変異後 (関数末尾) に呼ぶ — 変異前だと三態
        # トグル QAction が stale な (畳み前の) 状態を読んでしまう (spec §2.3)。
        self._sync_dock_action(dock)

    def _expand_dock(self, dock: QDockWidget) -> None:
        from valisync.gui.views.dock_collapse_rail import RailKind, rail_kind_for_area

        name = dock.objectName()
        for edge, rail in self._collapse_rails.items():
            rail.remove_tab(dock)
            # #17: 空になったレールはレイアウトから完全除去する (メンバに残さない)。
            # removeDockWidget はドックを hide もするためゼロ幅回収と非可視化を兼ねる。
            if rail.is_empty():
                self.removeDockWidget(self._rail_docks[edge])
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
        # D-3/UX-45: _collapsed_docks 変異後 (関数末尾) に呼ぶ — 理由は
        # _collapse_dock 末尾と同型 (spec §2.3)。
        self._sync_dock_action(dock)

    # ─── レール最外ドックの配置/維持 (candidate A・#17) ─────────────────────────

    def _place_rail_outermost(self, edge: Qt.DockWidgetArea) -> None:
        """1 辺のレールドックを最外側 (画面端側) へ配置する。

        Right/Bottom は ``addDockWidget(area, rail, orientation)`` の append が
        「最外の新カラム/新バンド」を作る (スパイクで実機実証: 既存の File/Channel
        カラムがあっても append 先は最外)。Left は append が「内側 (右)」に着地
        するため rail-first の rebuild で最外化する。``removeDockWidget`` を先に
        呼び冪等化する (再アサート時に現位置から一旦外す)。

        ``removeDockWidget`` はレールドックを隠すため、呼び出し前の可視状態を復元
        して「最外へ据え直しても見えたまま」を保つ (可視の非空レールを再アサート
        しても消えない — 呼び出し側は可視を別途操作する必要がない)。
        """
        rail_dock = self._rail_docks[edge]
        was_visible = not rail_dock.isHidden()
        self._suppress_rail_reassert = True
        try:
            if edge == Qt.DockWidgetArea.RightDockWidgetArea:
                self.removeDockWidget(rail_dock)
                self.addDockWidget(edge, rail_dock, Qt.Orientation.Horizontal)
            elif edge == Qt.DockWidgetArea.BottomDockWidgetArea:
                self.removeDockWidget(rail_dock)
                self.addDockWidget(edge, rail_dock, Qt.Orientation.Vertical)
            else:  # LeftDockWidgetArea
                self._rebuild_left_edge_outermost()
        finally:
            self._suppress_rail_reassert = False
        rail_dock.setVisible(was_visible)

    def _rebuild_left_edge_outermost(self) -> None:
        """左辺を「レール(最外/左端) / 開ドック列」へ組み直す。

        ``addDockWidget(Left, rail, H)`` は最内 (右) に着地するため使えない。
        レールを単独で全域に据えてから ``splitDockWidget(rail, dock0, H)`` で開ドックを
        右へ割り、残りを縦積みで戻す (スパイクで 1..N ドックを実機実証)。左辺は
        既定レイアウトに無い希少経路 (ユーザーが左へ D&D したときのみ)。
        """
        left = Qt.DockWidgetArea.LeftDockWidgetArea
        rail_dock = self._rail_docks[left]
        # 左辺の可視な非レールドックを現在の縦位置順で集める。
        col = [
            d
            for d in self._collapsible_bars_docks()
            if not d.isHidden()
            and not d.isFloating()
            and self.dockWidgetArea(d) == left
        ]
        col.sort(key=lambda d: d.mapToGlobal(d.rect().topLeft()).y())
        self.removeDockWidget(rail_dock)
        for d in col:
            self.removeDockWidget(d)
        self.addDockWidget(left, rail_dock)  # レール単独 (全域)
        if col:
            self.splitDockWidget(rail_dock, col[0], Qt.Orientation.Horizontal)
            for prev, cur in itertools.pairwise(col):
                self.splitDockWidget(prev, cur, Qt.Orientation.Vertical)
        for d in col:
            d.setVisible(True)

    def _pin_rail_thin(self, edge: Qt.DockWidgetArea) -> None:
        """レールドックを内容ぶんの薄さ (sizeHint) へ詰める。

        QMainWindow のドックはカラム幅を等分しがちなので、可視化直後に
        ``resizeDocks`` で最小幅/高さへ寄せて「薄いレール」を保つ。
        """
        from valisync.gui.views.dock_collapse_rail import RailKind, rail_kind_for_area

        rail = self._collapse_rails[edge]
        rail_dock = self._rail_docks[edge]
        kind = rail_kind_for_area(edge)
        hint = rail.sizeHint()
        if kind is RailKind.VERTICAL:
            self.resizeDocks(
                [rail_dock], [max(hint.width(), 1)], Qt.Orientation.Horizontal
            )
        elif kind is RailKind.HORIZONTAL:
            self.resizeDocks(
                [rail_dock], [max(hint.height(), 1)], Qt.Orientation.Vertical
            )

    def _reassert_rails_after_move(self, dock: QDockWidget) -> None:
        """実ドックの移動後、その移動先の辺のレールを最外へ戻す (guardrail 3)。

        ``dockLocationChanged`` はドラッグ中に何度も発火し、Qt のレイアウト処理の
        再入と衝突しうるため、次のイベントループへ遅延して安全に据え直す。
        自分の ``_place_rail_outermost`` 由来の移動は ``_suppress_rail_reassert``
        で無視する (無限ループ防止)。
        """
        if self._suppress_rail_reassert:
            return
        area = self.dockWidgetArea(dock)
        if area not in self._rail_docks:
            return
        QTimer.singleShot(0, lambda a=area: self._reassert_rail_now(a))

    def _reassert_rail_now(self, edge: Qt.DockWidgetArea) -> None:
        """遅延実行される最外再アサート本体 (レール非空時のみ薄く詰め直す)。

        ``_place_rail_outermost`` は可視状態を保つため、可視の非空レールは最外へ
        戻っても見えたまま。空レールは元々隠れているので触らない。
        """
        if self._suppress_rail_reassert:
            return
        # #17: 空レールは配置しない (メンバに残さない)。移動で最外を保つのは非空時のみ。
        if self._collapse_rails[edge].is_empty():
            return
        self._place_rail_outermost(edge)
        self._pin_rail_thin(edge)

    def _normalize_rail_placement(self) -> None:
        """restoreState/_reset_layout 後にレール順序・可視性を正規化する (guardrail 4)。

        #17: 非空レールのみ最外へ据え直して表示し、空レールはレイアウトから除去する
        (空ドックをメンバに残さない)。畳み済み分は続く _apply_saved_collapse が
        _collapse_dock 経由で再追加する。両呼び出し元は事前に展開/リセットするため
        通常このメソッド時点で全レールは空 (非空分岐は保険)。
        """
        self._suppress_rail_reassert = True
        try:
            for edge, rail in self._collapse_rails.items():
                rail_dock = self._rail_docks[edge]
                if rail.is_empty():
                    self.removeDockWidget(rail_dock)
                else:
                    self._place_rail_outermost(edge)
                    rail_dock.setVisible(True)
                    self._pin_rail_thin(edge)
        finally:
            self._suppress_rail_reassert = False

    def _on_dock_visibility_changed(self, dock: QDockWidget, visible: bool) -> None:
        """畳み状態機械を経由しない外部 show() を自己修復する (レビュー Important 1)。

        _on_load_error の diagnostics_dock.show() や QDockWidget 組込みの
        toggleViewAction() など、_expand_dock を呼ばない経路で畳み済みドックが
        可視化された場合、レールタブ除去・_collapsed_docks 除籍・永続化を
        _expand_dock に委譲して行う。hide 方向 (visible=False) は素通り —
        畳み対象でないドックを閉じる操作は通常の hide のままでよく、ここで
        「畳む」処理はしない (collapse は chevron からのみ)。
        """
        if self._suppress_dock_reconcile:
            return  # _collapse_dock/_expand_dock 自身の hide()/show() 由来 (再入防止)
        if visible and dock.objectName() in self._collapsed_docks:
            self._expand_dock(dock)

    # ─── ドックトグルの三態化 (D-3 Task2/UX-45) ─────────────────────────────────

    def _build_dock_actions(self) -> None:
        """View メニュー/ツールバー 2 面が共有するカスタム checkable QAction を
        ドックごとに 1 個構築する (toggleViewAction の置換・spec §2.3)。

        呼び出し側 (`__init__`) は `_restore_state()` より前に呼ぶこと —
        restoreState は visibilityChanged をフラッピング発火し最終状態で収束
        させる必要があるため (このメソッド内の visibilityChanged 接続と同じ
        制約)。handler は **triggered のみ**へ接続する (toggled 禁止 —
        toggled はプログラム的 setChecked (`_sync_dock_action`) でも発火し、
        handler とのあいだで無限振動する)。
        """
        self._dock_actions: dict[str, QAction] = {}
        self._dock_action_icon_names: dict[str, str] = {}
        for dock in self._collapsible_bars_docks():
            name = dock.objectName()
            action = QAction(self._DOCK_TITLES[name], self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, d=dock: self._on_dock_action_triggered(d)
            )
            self._dock_actions[name] = action
            # トリガ: visibilityChanged/dockLocationChanged はいずれも引数を無視し
            # 「再プローブの合図」としてのみ使う (spec §2.3) — シグナル引数
            # (visible/area) は判定に使わない (tabify 背面/フロートで嘘値になる)。
            dock.visibilityChanged.connect(
                lambda _visible, d=dock: self._sync_dock_action(d)
            )
            dock.dockLocationChanged.connect(
                lambda _area, d=dock: self._sync_dock_action(d)
            )
            self._sync_dock_action(dock)

    def _sync_dock_action(self, dock: QDockWidget) -> None:
        """可視/畳み/辺を再プローブし、対応 QAction の checked/icon を導出更新する
        (spec §2.3)。並行状態を作らない — 呼ぶたびに Qt から実状態を読み直す
        (`isHidden()` ポーリング・`dockWidgetArea()` 再プローブ)。handler は
        triggered 接続のみ (toggled 禁止) なので、ここでの setChecked は
        プログラム的変更として静かに反映され、handler との無限振動を起こさない。
        """
        name = dock.objectName()
        action = self._dock_actions[name]
        edge = self.dockWidgetArea(dock)
        checked, icon_name = _dock_toggle_state(
            dock.isHidden(), name in self._collapsed_docks, edge
        )
        action.setChecked(checked)
        action.setIcon(icons.icon(icon_name))
        self._dock_action_icon_names[name] = icon_name

    def _on_dock_action_triggered(self, dock: QDockWidget) -> None:
        """三態トグル QAction のクリック挙動 (spec §2.3)。

        checkable QAction はクリックで checked が Qt により自動反転済みだが、
        ここではその値を信用せず、クリック前の実状態 (再プローブ) から遷移を
        決める: 非表示 → `show()` + `raise_()` (plain show() は tabify 背面を
        前面化しない — 実測。既存 `_on_load_error` と同型)、展開 → `hide()`、
        レール → `_expand_dock()`。最後に `_sync_dock_action` で確定状態へ
        上書きする。
        """
        name = dock.objectName()
        if name in self._collapsed_docks:
            self._expand_dock(dock)  # 末尾で _sync_dock_action 済み
        elif dock.isHidden():
            dock.show()
            dock.raise_()
        else:
            dock.hide()
        self._sync_dock_action(dock)

    def dock_action_icon_name(self, name: str) -> str:
        """objectName から現在のドックトグル QAction に設定済みのアイコン意味名を
        返す (introspection — QIcon はキャッシュキー恒等比較が信頼できないため
        保持名で検証する。CollapsibleDockTitleBar.chevron_icon_name と同型の
        B4 パターン・テスト用)。
        """
        return self._dock_action_icon_names[name]

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
        self.restoreState(self._default_state, _STATE_VERSION)
        self._apply_dock_corners()  # restoreState reset the FU-10 corner; re-apply
        # #17: 冒頭で全展開したのでこの時点でレールは全空。_default_state は
        # レールドック非メンバ時に採取済み (レールを含まない) ため restoreState では
        # レールは入らない。空レールをレイアウトから除去して正規化する (guardrail 4)。
        self._normalize_rail_placement()
        # spec §1.5-12c: _default_state was captured before the 1:4 ratio is ever
        # applied (it's saved at the top of __init__), so without this the
        # startup ratio and Reset Layout would silently diverge.
        self._apply_default_dock_ratio()
        # D-3/UX-45: restoreState 由来のフラッピングだけに頼らず、構築完了時と
        # 同様に無条件で再同期する (spec §2.3 — Reset Layout 後は 3 action とも
        # 展開/checked へ復帰することが受け入れ基準)。
        for dock in self._collapsible_bars_docks():
            self._sync_dock_action(dock)

    def _on_theme_selected(self, mode: ThemeMode) -> None:
        """テーマ radio 選択 — 保存のみ。set_active/apply_theme は呼ばない (再起動反映)。"""
        theme_apply.save_theme_mode(mode)
        labels = {
            ThemeMode.LIGHT: "ライト",
            ThemeMode.DARK: "ダーク",
            ThemeMode.AUTO: "オート",
        }
        self.set_status_message(
            f"テーマを「{labels[mode]}」に変更しました。再起動で反映されます",
            timeout_ms=8000,
        )
