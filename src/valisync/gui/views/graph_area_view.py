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

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFocusEvent,
    QKeyEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLineEdit,
    QSplitter,
    QStyle,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView

PanelFactory = Callable[[GraphPanelVM], QWidget]


def _default_panel_factory(panel_vm: GraphPanelVM) -> QWidget:
    return GraphPanelView(panel_vm)


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
    ) -> None:
        super().__init__(parent)
        self.vm = vm
        self._panel_factory: PanelFactory = panel_factory or _default_panel_factory
        # Guards against re-entrancy when we programmatically set the current
        # tab during a rebuild (which would otherwise echo back into the VM).
        self._syncing = False
        self._drop_active = False
        self.setAcceptDrops(True)
        # PC-07: (tab_index, panel_index, widget) の現行 GraphPanelView 一覧。
        # "active_panel" の軽量経路が rebuild なしで枠を再適用するために使う。
        self._panel_views: list[tuple[int, int, GraphPanelView]] = []

        # X-sync toggle for the active tab (R7.3).
        self.sync_checkbox = QCheckBox("Sync X")
        self.sync_checkbox.toggled.connect(self._on_sync_toggled)

        self.tabs = QTabWidget(self)
        self.tabs.currentChanged.connect(self._on_current_changed)

        # SH-02: 新規タブのアフォーダンス (コーナー "+" と Ctrl+T)。
        new_tab_btn = QToolButton(self.tabs)
        new_tab_btn.setObjectName("new_tab_button")
        new_tab_btn.setText("+")
        new_tab_btn.setToolTip("新規タブ (Ctrl+T)")
        new_tab_btn.clicked.connect(lambda: self.add_tab())
        self.tabs.setCornerWidget(new_tab_btn, Qt.Corner.TopRightCorner)

        self._new_tab_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        self._new_tab_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._new_tab_shortcut.activated.connect(lambda: self.add_tab())

        # SH-04: タブを閉じる。最後の1枚の抑制は _rebuild で per-tab に行う。
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.remove_tab)

        # SH-13: ダブルクリックでタブ改名。
        self._rename_editor: _TabRenameEditor | None = None
        self.tabs.tabBarDoubleClicked.connect(self._begin_rename)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.sync_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.tabs)

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
            self._update_sync_checkbox()
        elif change == "active_panel":
            self._sync_active_frames()  # 軽量: rebuild しない (クリック中の破棄禁止)
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
        self._update_sync_checkbox()
        self._sync_active_frames()

    def _sync_active_frames(self) -> None:
        """Re-apply the active-panel frame from VM state (rebuild 後と "active_panel")。"""
        for tab_index, panel_index, widget in self._panel_views:
            widget.set_panel_active(
                panel_index == self.vm.active_panel_index(tab_index)
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
            self._rename_editor.setStyleSheet("border: 1px solid #c0392b;")
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
