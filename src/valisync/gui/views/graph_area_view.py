"""Graph_Area view — tabbed, splittable panel container (Tasks 8.1 / 8.4).

A QTabWidget whose pages are vertical QSplitters, one child widget per
GraphPanelVM.  Tab/panel structure mirrors GraphAreaVM; all mutation rules
("reject the last tab/panel", "max 8 panels") and X-axis sync live in the VM,
so this widget just delegates and re-projects on notify.

Panel widgets are built by ``panel_factory`` (default: a real GraphPanelView,
sharing the injected ``analysis_actions`` — spec §2.2 — with every panel and the
Analyze menu). Injecting the factory keeps the container decoupled and testable.

X-axis sync (Task 8.4; right-click-only since 計測 IA 刷新 spec §2.3 / v3 決定4):
each panel's blank-area context menu carries a "X軸同期(タブ内全パネル)" toggle
(ASCII-safe parens here — the real menu label uses full-width parens, see
``build_context_menu``) that drives ``GraphAreaVM.set_x_sync`` through an
injected getter/setter pair (ownership of the flag stays here, in the area, so
GraphPanelView stays area-independent). The propagation itself is in the VM
(a panel's X-range change drives its siblings), so zooming one GraphPanelView
updates the others through the VM layer.
"""

from __future__ import annotations

import contextlib
import weakref
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFocusEvent,
    QKeyEvent,
    QKeySequence,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QSplitter,
    QStyle,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.theme import qss
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.analysis_actions import _INTERP_LABELS, AnalysisActions
from valisync.gui.views.cursor_readout import CursorReadout
from valisync.gui.views.graph_panel_view import GraphPanelView

PanelFactory = Callable[[GraphPanelVM], QWidget]


class _TabRenameEditor(QLineEdit):
    """タブバー上のインライン改名エディタ (SH-13)。

    Enter/フォーカス喪失で committed、Escape で cancelled を出す。位置決めと
    ライフサイクルは GraphAreaView が握る。
    """

    committed = Signal(str)
    cancelled = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.committed.emit(self.text())
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.committed.emit(self.text())


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
        analysis_actions: AnalysisActions | None = None,
    ) -> None:
        super().__init__(parent)
        self.vm = vm
        # spec §2.2: MainWindow が生成した解析系 QAction の共有セット (Analyze メニ
        # ューと同一インスタンス)。既定パネルファクトリへ注入する — panel_factory を
        # 明示注入するテスト/代替経路 (フェイクビュー等) はこの注入をバイパスする。
        self._analysis_actions = analysis_actions
        if panel_factory is None:
            # self._build_default_panel の束縛メソッドをそのまま self の属性に
            # 保持すると self -> 属性 -> 束縛メソッド -> self という参照循環になり、
            # readout_pane 配線 (下の _readout_clear 等) と同型の GC 順序問題を招く
            # (再現: tests/gui/test_graph_area_view.py::TestClickAwayDeselect の
            # reparent teardown で "already deleted")。weakref で断ち切る。
            self_ref = weakref.ref(self)

            # spec §2.3: X 軸同期の所有は area 側のまま — パネルには getter/setter
            # ペアだけを注入する (GraphPanelView の area 非依存を維持)。self を直接
            # close over すると、これらの closure は生成される GraphPanelView (self
            # の Qt 子孫) の属性としてぶら下がるため、panel_factory と同じ参照循環
            # 事故 (weakref コメント参照) を再現する — weakref 経由に統一する。
            def _get_x_sync() -> bool:
                view = self_ref()
                if view is None:
                    return False
                tabs = view.vm.tabs()
                if not tabs:
                    return False
                return tabs[view.vm.active_tab_index].x_sync_enabled

            def _set_x_sync(enabled: bool) -> None:
                view = self_ref()
                if view is not None:
                    view.vm.set_x_sync(view.vm.active_tab_index, enabled)

            def panel_factory(panel_vm: GraphPanelVM) -> QWidget:
                view = self_ref()
                aa = view._analysis_actions if view is not None else None
                return GraphPanelView(
                    panel_vm,
                    analysis_actions=aa,
                    x_sync_getter=_get_x_sync,
                    x_sync_setter=_set_x_sync,
                )

        self._panel_factory: PanelFactory = panel_factory
        # Guards against re-entrancy when we programmatically set the current
        # tab during a rebuild (which would otherwise echo back into the VM).
        self._syncing = False
        self._drop_active = False
        self.setAcceptDrops(True)
        # R12.5: OS ファイルドロップの破線枠 overlay。素の QWidget への QSS
        # border は子に覆われ構造的に見えないため、GraphPanelView の
        # _active_frame/_drop_frame と同型の QFrame overlay で最前面に描く。
        self._drop_frame = QFrame(self)
        self._drop_frame.setObjectName("area_drop_highlight_frame")
        self._drop_frame.setStyleSheet(qss.area_drop_highlight())
        self._drop_frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._drop_frame.setGeometry(self.rect())
        self._drop_frame.setVisible(False)
        # PC-07: (tab_index, panel_index, widget) の現行 GraphPanelView 一覧。
        # "active_panel" の軽量経路が rebuild なしで枠を再適用するために使う。
        self._panel_views: list[tuple[int, int, GraphPanelView]] = []

        self.tabs = QTabWidget(self)
        self.tabs.currentChanged.connect(self._on_current_changed)

        # SH-02: 新規タブのアフォーダンス ("+"・後段で読み値トグルと横並びの corner
        # コンテナへ入れる — spec §2.3。Ctrl+T は独立。
        new_tab_btn = QToolButton(self.tabs)
        new_tab_btn.setObjectName("new_tab_button")
        new_tab_btn.setText("+")
        new_tab_btn.setToolTip("新規タブ (Ctrl+T)")
        new_tab_btn.clicked.connect(lambda: self.add_tab())

        self._new_tab_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        self._new_tab_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._new_tab_shortcut.activated.connect(lambda: self.add_tab())

        # SH-04: タブを閉じる。最後の1枚の抑制は _rebuild で per-tab に行う。
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.remove_tab)

        # SH-13: ダブルクリックでタブ改名。
        self._rename_editor: _TabRenameEditor | None = None
        self.tabs.tabBarDoubleClicked.connect(self._begin_rename)

        # readout-pane Task 4: 読み値は GraphPanelView 個別ではなく、この単一ペイン
        # (QSplitter の右側) がアクティブパネルの状態を pull する (_sync_readout)。
        self.readout_pane = CursorReadout()
        self._readout_visible = True
        # 信号ゼロ時の自動収納 (spec §2.6) — トグル状態 (_readout_visible) とは
        # 独立した第3状態。実際の可視性は両者の AND (_apply_readout_visibility)。
        self._readout_stowed = False
        self.readout_pane.row_activated.connect(self._on_readout_row_activated)
        # weakref 経由で配線: readout_pane は self の Qt 子で、そこへ self の
        # bound method を平の属性として直接ぶら下げると Python レベルの参照サイクル
        # (readout_pane -> bound method -> self) ができ、self の Python wrapper が
        # 単純な参照カウントでは解放されず循環 GC 待ちになる。無関係な兄弟オブジェクト
        # (Qt 親を持たない一時 QWidget) が先に参照カウントで即時破棄され、その Qt 子
        # 破棄カスケードで self の C++ 側だけ先に死んで Python wrapper が生き残ると、
        # 後段の close() が "already deleted" で落ちる — tests/gui/test_graph_area_view.py
        # ::TestClickAwayDeselect::test_press_on_ancestor_bubble_does_not_clear で実証済みの
        # 実回帰 (Task 4 で追加した配線が原因)。weakref で参照サイクルを断つ。
        self_ref = weakref.ref(self)

        def _readout_clear() -> None:
            view = self_ref()
            if view is not None:
                view._on_readout_clear()

        def _readout_precision(p: int) -> None:
            view = self_ref()
            if view is not None:
                view._on_readout_precision(p)

        def _readout_stat_toggled(col: str, on: bool) -> None:
            view = self_ref()
            if view is not None:
                view._on_readout_stat_toggled(col, on)

        self.readout_pane._on_clear = _readout_clear
        self.readout_pane._on_precision = _readout_precision
        self.readout_pane._on_stat_toggled = _readout_stat_toggled

        self._readout_split = QSplitter(Qt.Orientation.Horizontal, self)
        self._readout_split.addWidget(self.tabs)
        self._readout_split.addWidget(self.readout_pane)
        self._readout_split.setStretchFactor(0, 1)  # プロット側が伸びる
        self._readout_split.setStretchFactor(1, 0)

        self.readout_toggle_button = QToolButton()
        self.readout_toggle_button.setObjectName("readout_toggle_button")
        self.readout_toggle_button.setCheckable(True)
        self.readout_toggle_button.setChecked(True)
        self.readout_toggle_button.setText("読み値")
        self.readout_toggle_button.setToolTip("読み値ペインの表示切替")
        self.readout_toggle_button.toggled.connect(self.set_readout_visible)

        # spec §2.3: corner コンテナ化。専用のタブ行 (旧 top_row) は撤去し、"+" と
        # 読み値トグルをタブバー右肩の corner widget に横並びで収める
        # (test-lock 追随: cornerWidget().objectName() 単一ボタン assert は
        # findChild(QToolButton, "new_tab_button") へ — 個々のボタンの objectName
        # は変えない)。
        corner = QWidget(self.tabs)
        corner.setObjectName("tab_corner_container")
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(4)
        corner_layout.addWidget(new_tab_btn)
        corner_layout.addWidget(self.readout_toggle_button)
        self.tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._readout_split)

        unsubscribe = self.vm.subscribe(self._on_vm_change)
        self._unsubscribe = unsubscribe
        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        self.destroyed.connect(lambda *_: unsubscribe())

        # FU-15: centralized click-away — プロット subtree 外の押下でアクティブ Y 軸を
        # 解除する。単一介入点なので新ドック/エリアはゼロ配線で対応。app にフィルタを
        # 設置する。明示 removeEventFilter は不要かつ有害: Qt はフィルタ登録先(app)より
        # フィルタ自身(self)が先に破棄された場合、self の destroyed 時点で自動的に
        # フィルタ登録を解除する(実測で確認済み — 破棄後は app 経由のイベントが
        # 二度と self.eventFilter に届かない)。逆に self を自身の destroyed スロットで
        # 使うと shiboken が signal 発火と同時に self のラッパーを無効化済みのため
        # RuntimeError("already deleted") になる。
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._rebuild()

    # ─── VM reactions ──────────────────────────────────────────────────────────

    def _on_vm_change(self, change: str) -> None:
        if change == "active":
            self._sync_current()
        elif change == "active_panel":
            self._sync_active_frames()  # 軽量: rebuild しない (クリック中の破棄禁止)
            self._sync_readout()
        elif change == "sync":
            # spec §2.3: sync 状態を映す常設ウィジェットはもう無い (右クリック時に
            # getter で都度読む) — 反映不要。ここで _rebuild() へ落とすと sync
            # トグルのたびタブ全体を無駄に再構築してしまうため、明示的な no-op。
            pass
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
            self._panel_views.clear()
            for tab_index, tab in enumerate(self.vm.tabs()):
                splitter = QSplitter(Qt.Orientation.Vertical)
                panel_vms = self.vm.panels(tab_index)
                for panel_index, panel_vm in enumerate(panel_vms):
                    widget = self._panel_factory(panel_vm)
                    self._wire_panel(
                        widget, tab_index, panel_index, removable=len(panel_vms) > 1
                    )
                    if isinstance(widget, GraphPanelView):
                        self._panel_views.append((tab_index, panel_index, widget))
                    splitter.addWidget(widget)
                self.tabs.addTab(splitter, tab.name)
            # SH-04: 最後の1枚は閉じさせない (remove_tab も ValueError を握るが、
            # ボタン自体を消して操作不能を明示)。close ボタン位置はスタイル依存。
            if self.tabs.count() == 1:
                bar = self.tabs.tabBar()
                pos = QTabBar.ButtonPosition(
                    bar.style().styleHint(
                        QStyle.StyleHint.SH_TabBar_CloseButtonPosition, None, bar
                    )
                )
                bar.setTabButton(0, pos, None)
            self.tabs.setCurrentIndex(self.vm.active_tab_index)
        finally:
            self._syncing = False
        self._sync_active_frames()
        self._sync_readout()

    def _sync_active_frames(self) -> None:
        """Re-apply the active-panel frame from VM state (rebuild 後と "active_panel")。

        枠はタブ内にパネルが2枚以上あるときのみ描く — 1枚ならアクティブは自明で
        枠は情報を運ばない (増分A・DP15「1枚でも枠」を意図的に supersede)。
        追跡/配送 (active_panel_index) は不変。
        """
        for tab_index, panel_index, widget in self._panel_views:
            widget.set_panel_active(
                panel_index == self.vm.active_panel_index(tab_index)
                and len(self.vm.panels(tab_index)) >= 2
            )

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
        widget.offset_reset_requested.connect(lambda k, sc: self.vm.reset_offset(k, sc))
        widget.activate_requested.connect(
            lambda *_: self.vm.set_active_panel(tab_index, panel_index)
        )
        widget.cross_panel_axis_move_requested.connect(
            lambda src, ax, col, pos: self.vm.move_axis_across_panels(
                tab_index, src, ax, panel_index, col, pos
            )
        )
        # readout-pane Task 4: every panel's cursor/delta/stat/precision change
        # pulls a re-sync of the single readout pane; _sync_readout() only ever
        # reads the currently active tab/panel, so wiring every panel is safe.
        widget.readout_changed.connect(lambda *_: self._sync_readout())

    def clear_active_axis(self) -> None:
        """全パネルのアクティブ Y 軸(view-transient)を解除する。FU-15 の単一解除点。"""
        for _tab, _panel, widget in self._panel_views:
            if isinstance(widget, GraphPanelView):
                widget.set_active_axis(None)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """FU-15: プロット subtree 外の左押下でアクティブ軸を解除する(観測のみ)。

        MouseButtonPress 以外は即スルー。押下対象ウィジェットを解決し、self
        (GraphAreaView)自身またはその子孫でなければ subtree 外とみなし
        clear_active_axis()。押下対象が非 QWidget/解決不能なら誤解除を避けて何もしない。
        常に False を返しイベントを消費しない。

        注: QMenu popup は別トップレベルウィンドウなので、コンテキストメニュー項目の
        クリックも subtree 外=解除トリガになる(意図的・spec 想定内で無害)。無害なのは
        メニューアクションが対象軸を build 時に束縛する(例 build_axis_menu(_axis_index_at(pos))
        は具体 index を capture)ためで、実行時に _active_axis_index を読むメニューハンドラを
        将来足すと、項目クリックで解除された後の None を読んで壊れる — その場合はこの
        解除を該当メニュー中は抑制するか、ハンドラを build 時束縛にすること。
        """
        if event.type() == QEvent.Type.MouseButtonPress:
            # obj = イベント配送先。実クリックでは押下対象ウィジェット(その viewport)で
            # あり、合成テストでも notify(target, ev) の target になるため主経路に使う。
            # widgetAt は obj が非 QWidget のときの fallback(globalPos はここでのみ触る)。
            target = obj if isinstance(obj, QWidget) else None
            if target is None:
                target = QApplication.widgetAt(
                    event.globalPosition().toPoint()  # type: ignore[attr-defined]
                )
            if isinstance(target, QWidget) and not (
                target is self
                or self.isAncestorOf(target)
                # FU-23: 未 accept の press は同一物理イベントが GraphAreaView の
                # 祖先(central stack/MainWindow)へバブルする。その祖先配送は
                # subtree 外でなく内側扱い — click-away と誤認すると軸レーンの
                # 押下が自らアクティブ軸を解除しジェスチャが全滅する(真因)。
                or target.isAncestorOf(self)
            ):
                self.clear_active_axis()
        return False

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
        self._sync_readout()

    # ─── Readout pane (readout-pane Task 4 -> 計測 IA Task 8) ──────────────────

    def _sync_readout(self) -> None:
        """アクティブタブのアクティブパネル VM を単一ペインへ反映する。

        3方向に分岐する (spec §2.6): 信号ゼロ (アクティブパネル不在/信号なし) は
        ペインを自動収納 (readout_stowed)。カーソル未設置+信号ありは凡例モード
        (set_legend)。カーソル設置は計測モード (set_global/set_delta・既存)。
        spec-B 案b の「プロットをクリックしてカーソルを設置」プレースホルダは
        凡例モードへ supersede 済み — このメソッドはもう呼ばない。
        """
        tab = self.tabs.currentIndex()
        if tab < 0:
            self._stow_readout()
            return
        panels = self.vm.panels(tab)
        active = self.vm.active_panel_index(tab)
        if not panels or active < 0 or active >= len(panels):
            self._stow_readout()
            return
        pvm = panels[active]
        if pvm.cursor_t is None:
            legend = pvm.legend_readings()
            if not legend:
                self._stow_readout()
                return
            self._unstow_readout()
            self.readout_pane.set_legend(legend)
            return
        readings = pvm.cursor_readings()
        if not readings:
            self._stow_readout()
            return
        self._unstow_readout()
        if pvm.delta_enabled and pvm.cursor_t_b is not None:
            self.readout_pane.sync_visible_stats(pvm.visible_stat_cols)
            self.readout_pane.set_delta(
                pvm.cursor_t,
                pvm.cursor_t_b,
                pvm.delta_readings(),
                interp_label=_INTERP_LABELS.get(pvm.interp_method, ""),
                precision=pvm.value_precision,
            )
        else:
            self.readout_pane.set_global(
                pvm.cursor_t,
                readings,
                interp_label=_INTERP_LABELS.get(pvm.interp_method, ""),
                precision=pvm.value_precision,
            )

    def _stow_readout(self) -> None:
        """信号ゼロ — ペインを自動収納する (トグルの ON/OFF 状態は変更しない)。

        ユーザーの表示意思 (_readout_visible) を保持したまま画面から消し、
        信号が現れれば _sync_readout が自動的に元へ戻す (spec §2.6)。
        """
        self._readout_stowed = True
        self._apply_readout_visibility()

    def _unstow_readout(self) -> None:
        self._readout_stowed = False
        self._apply_readout_visibility()

    def _apply_readout_visibility(self) -> None:
        """実際の可視性 = トグル ON かつ収納中でない (両者の AND・spec §2.6)。"""
        self.readout_pane.setVisible(self._readout_visible and not self._readout_stowed)

    def _on_readout_row_activated(self, entry_id: int) -> None:
        """Pane row click -> highlight that entry_id's curve on the active panel."""
        tab = self.tabs.currentIndex()
        active = self.vm.active_panel_index(tab)
        for t, p, widget in self._panel_views:
            if t == tab and p == active:
                widget.activate_curve_by_id(entry_id)
                break

    def active_panel_vm(self) -> GraphPanelVM | None:
        """Resolve the active tab's active panel VM, or None if unavailable.

        Shared dispatch target for the Analyze menu's AnalysisActions (spec
        §2.2): the menu bar always targets "whatever panel is active right
        now", unlike a blank panel menu which targets itself.
        """
        tab = self.tabs.currentIndex()
        if tab < 0:
            return None
        panels = self.vm.panels(tab)
        active = self.vm.active_panel_index(tab)
        if not panels or active < 0 or active >= len(panels):
            return None
        return panels[active]

    def _active_pvm_call(self, fn: Callable[[GraphPanelVM], None]) -> None:
        """Look up the active tab/panel's VM and apply *fn* (no-op if absent)."""
        pvm = self.active_panel_vm()
        if pvm is not None:
            fn(pvm)

    def _on_readout_clear(self) -> None:
        self._active_pvm_call(lambda pvm: pvm.toggle_main_cursor(False))

    def _on_readout_precision(self, p: int) -> None:
        self._active_pvm_call(lambda pvm: pvm.set_value_precision(p))

    def _on_readout_stat_toggled(self, col: str, on: bool) -> None:
        def _apply(pvm: GraphPanelVM) -> None:
            cols = set(pvm.visible_stat_cols)
            if on:
                cols.add(col)
            else:
                cols.discard(col)
            pvm.set_visible_stats(cols)

        self._active_pvm_call(_apply)

    def set_readout_visible(self, visible: bool) -> None:
        self._readout_visible = visible
        self._apply_readout_visibility()

    def readout_visible(self) -> bool:
        """トグルの ON/OFF 状態 (収納中かどうかは含まない — readout_stowed 参照)。"""
        return self._readout_visible

    def readout_stowed(self) -> bool:
        """信号ゼロによる自動収納中かどうか (spec §2.6)。"""
        return self._readout_stowed

    # ─── Commands (delegate to VM; rejections are swallowed as UI no-ops) ───────

    def add_tab(self, name: str | None = None) -> None:
        self.vm.add_tab(name)

    def remove_tab(self, index: int) -> None:
        with contextlib.suppress(ValueError):  # last tab — keep it (R5.6)
            self.vm.remove_tab(index)

    def rename_tab(self, index: int, name: str) -> None:
        with contextlib.suppress(ValueError):  # invalid length — leave label (R5.4)
            self.vm.rename_tab(index, name)

    def _begin_rename(self, index: int) -> None:
        if index < 0:
            return
        self._discard_rename_editor()  # 進行中があれば畳む
        bar = self.tabs.tabBar()
        editor = _TabRenameEditor(bar)
        editor.setText(self.tabs.tabText(index))
        editor.selectAll()
        editor.setGeometry(bar.tabRect(index))
        editor.committed.connect(lambda text: self._finish_rename(index, text))
        editor.cancelled.connect(self._discard_rename_editor)
        editor.show()
        editor.setFocus()
        self._rename_editor = editor

    def _finish_rename(self, index: int, text: str) -> None:
        # Focus loss re-entrancy で二重呼出しされるため、editor 破棄済みなら単発化。
        if self._rename_editor is None:
            return
        # 範囲外は editor を残して修正させる (赤枠でフィードバック)。
        if not (1 <= len(text) <= 32):
            self._rename_editor.setStyleSheet(qss.rename_error_border())
            return
        self._discard_rename_editor()  # 先に _rename_editor=None にする
        self.rename_tab(index, text)  # VM 反映 -> _rebuild

    def _discard_rename_editor(self) -> None:
        editor = self._rename_editor
        self._rename_editor = None
        if editor is not None:
            editor.hide()
            editor.deleteLater()

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
        self._drop_frame.setVisible(active)
        if active:
            self._drop_frame.raise_()  # overlay は後生成の兄弟に沈む — 表示時に前面化

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._drop_frame.setGeometry(self.rect())

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
