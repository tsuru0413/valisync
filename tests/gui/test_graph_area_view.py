"""Tests for GraphAreaView — Task 8.1.

The Graph_Area view is a QTabWidget whose pages are vertical QSplitters
holding one widget per GraphPanelVM.  Tab/panel operations and the
"reject the last one" rules are delegated to GraphAreaVM; the widget tree
is a projection of the VM.  Real panel widgets arrive in Task 8.2 via an
injected ``panel_factory``; here a placeholder factory is used.

TDD: written before the view exists; all must FAIL first.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QSplitter, QTabWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

# ─── Helpers ────────────────────────────────────────────────────────────────


def _make_area(qtbot: QtBot, **kwargs: object) -> object:
    from valisync.gui.views.graph_area_view import GraphAreaView

    vm = GraphAreaVM(AppViewModel(Session()))
    view = GraphAreaView(vm, **kwargs)  # type: ignore[arg-type]
    qtbot.addWidget(view)
    return view


def _page_splitter(view: object, tab_index: int) -> QSplitter:
    page = view.tabs.widget(tab_index)  # type: ignore[attr-defined]
    assert isinstance(page, QSplitter)
    return page


# ─── Initial projection ───────────────────────────────────────────────────────


class TestInitial:
    def test_starts_with_one_tab(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        assert view.tabs.count() == 1  # type: ignore[attr-defined]

    def test_tab_widget_is_qtabwidget(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        assert isinstance(view.tabs, QTabWidget)  # type: ignore[attr-defined]

    def test_each_page_is_a_splitter(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        assert isinstance(_page_splitter(view, 0), QSplitter)

    def test_one_panel_widget_initially(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        assert _page_splitter(view, 0).count() == 1


# ─── Tab operations ─────────────────────────────────────────────────────────--


class TestTabs:
    def test_add_tab_adds_page(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        view.add_tab()  # type: ignore[attr-defined]
        assert view.tabs.count() == 2  # type: ignore[attr-defined]
        assert view.vm.inspect()["active_tab_index"] == 1  # type: ignore[attr-defined]

    def test_add_tab_makes_it_current(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        view.add_tab()  # type: ignore[attr-defined]
        assert view.tabs.currentIndex() == 1  # type: ignore[attr-defined]

    def test_remove_tab_removes_page(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        view.add_tab()  # type: ignore[attr-defined]
        view.remove_tab(1)  # type: ignore[attr-defined]
        assert view.tabs.count() == 1  # type: ignore[attr-defined]

    def test_remove_last_tab_is_rejected(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        view.remove_tab(0)  # type: ignore[attr-defined]
        # The single remaining tab must survive (R5.6).
        assert view.tabs.count() == 1  # type: ignore[attr-defined]

    def test_rename_tab_updates_label(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        view.rename_tab(0, "Speeds")  # type: ignore[attr-defined]
        assert view.tabs.tabText(0) == "Speeds"  # type: ignore[attr-defined]

    def test_rename_tab_rejects_too_long(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        original = view.tabs.tabText(0)  # type: ignore[attr-defined]
        view.rename_tab(0, "x" * 33)  # type: ignore[attr-defined]
        # Invalid name rejected by the VM; the label is unchanged.
        assert view.tabs.tabText(0) == original  # type: ignore[attr-defined]

    def test_current_changed_updates_vm_active(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        view.add_tab()  # type: ignore[attr-defined]
        view.tabs.setCurrentIndex(0)  # type: ignore[attr-defined]
        assert view.vm.inspect()["active_tab_index"] == 0  # type: ignore[attr-defined]


# ─── Panel operations ─────────────────────────────────────────────────────────


class TestPanels:
    def test_add_panel_adds_widget(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        view.add_panel()  # type: ignore[attr-defined]
        assert _page_splitter(view, 0).count() == 2

    def test_remove_panel_removes_widget(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        view.add_panel()  # type: ignore[attr-defined]
        view.remove_panel(1)  # type: ignore[attr-defined]
        assert _page_splitter(view, 0).count() == 1

    def test_remove_last_panel_is_rejected(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        view.remove_panel(0)  # type: ignore[attr-defined]
        # The single remaining panel must survive (R6.6).
        assert _page_splitter(view, 0).count() == 1

    def test_add_panel_beyond_max_is_rejected(self, qtbot: QtBot) -> None:
        view = _make_area(qtbot)
        for _ in range(20):
            view.add_panel()  # type: ignore[attr-defined]
        # Capped at eight panels per tab (R6.5).
        assert _page_splitter(view, 0).count() == 8


# ─── Panel factory injection (seam for Task 8.2) ───────────────────────────────


class TestPanelFactory:
    def test_custom_factory_builds_panel_widgets(self, qtbot: QtBot) -> None:
        built: list[GraphPanelVM] = []

        def factory(panel_vm: GraphPanelVM) -> QLabel:
            built.append(panel_vm)
            label = QLabel("panel")
            label.setProperty("is_custom_panel", True)
            return label

        view = _make_area(qtbot, panel_factory=factory)

        widget = _page_splitter(view, 0).widget(0)
        assert widget.property("is_custom_panel") is True
        assert len(built) == 1


# ─── Lifecycle: no leaks, clean unsubscribe ────────────────────────────────────


class TestSyncCheckboxHitArea:
    def test_sync_checkbox_not_stretched_to_full_width(self, qtbot: QtBot) -> None:
        """FU-17: Sync X チェックボックスは内容幅に固定され、右余白が
        クリック判定に含まれない (全幅ストレッチしない)."""
        from PySide6.QtWidgets import QCheckBox

        view = _make_area(qtbot)
        view.resize(900, 600)  # type: ignore[attr-defined]
        view.show()  # type: ignore[attr-defined]
        qtbot.waitExposed(view)  # type: ignore[arg-type]

        cb = view.sync_checkbox  # type: ignore[attr-defined]
        # 内容幅 (sizeHint) 近傍に固定 = 全幅 900 まで伸びない。
        assert cb.width() <= cb.sizeHint().width() + 8, (
            f"checkbox stretched to {cb.width()} (sizeHint {cb.sizeHint().width()})"
        )
        # content 端よりはるか右の余白は checkbox 本体を返さない (dead margin 消失)。
        far_right = view.width() - 20  # type: ignore[attr-defined]
        hit = view.childAt(far_right, cb.y() + cb.height() // 2)  # type: ignore[attr-defined]
        assert not isinstance(hit, QCheckBox), "right margin still hits the checkbox"


class TestLifecycle:
    def test_rebuild_does_not_leak_pages(self, qtbot: QtBot) -> None:
        """Each _rebuild must dispose old pages; QTabWidget.clear() alone leaks
        a QSplitter per rebuild (it detaches pages without deleting them)."""
        view = _make_area(qtbot)
        for _ in range(5):
            view.add_panel()  # type: ignore[attr-defined]
        for _ in range(3):
            view.add_tab()  # type: ignore[attr-defined]
        qtbot.wait(50)  # let queued deleteLater run

        splitters = view.tabs.findChildren(QSplitter)  # type: ignore[attr-defined]
        assert len(splitters) == view.tabs.count()  # type: ignore[attr-defined]

    def test_unsubscribes_when_destroyed(self, qtbot: QtBot) -> None:
        """A destroyed view must not leave a live VM callback into a dead widget."""
        from valisync.core.session import Session

        vm = GraphAreaVM(AppViewModel(Session()))
        from valisync.gui.views.graph_area_view import GraphAreaView

        view = GraphAreaView(vm)
        # 破棄時 unsubscribe の検証で view を意図的に deleteLater する。qtbot.addWidget で
        # 管理下に置くと teardown が破棄済みオブジェクトを二重削除して RuntimeError になり、
        # その teardown 破綻が次テストの isolation を壊す連鎖エラーを生む。だから登録しない。
        # 姉妹 test_graph_panel_view も同方針。memory: gui_qtbot_addwidget_vs_manual_delete_cascade。
        assert len(vm._callbacks) == 1

        view.deleteLater()
        qtbot.wait(50)  # let the C++ object be destroyed (fires destroyed())

        assert len(vm._callbacks) == 0
        vm.add_tab()  # a notify after destruction must not raise


# ─── FU-15: centralized click-away deselect ───────────────────────────────────


class TestClickAwayDeselect:
    def _panels(self, view: object) -> list:
        return [w for _t, _p, w in view._panel_views]  # type: ignore[attr-defined]

    def test_press_outside_plot_subtree_clears_active_axis(self, qtbot: QtBot) -> None:
        """FU-15: プロット subtree 外のウィジェットへの MouseButtonPress で全パネルの
        アクティブ軸が解除される(clear_active_axis 経由)。"""
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication, QWidget

        view = _make_area(qtbot)
        panels = self._panels(view)
        assert panels, "no panel views"
        for p in panels:
            p.set_active_axis(0)
        assert any(p._active_axis_index == 0 for p in panels)

        # プロット subtree 外の兄弟ウィジェットへ press を配送。
        outsider = QWidget()
        qtbot.addWidget(outsider)
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPoint(1, 1).toPointF()
            if hasattr(QPoint(1, 1), "toPointF")
            else QPoint(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # app フィルタ経路を駆動(GraphAreaView.eventFilter(outsider, ev))。
        QApplication.instance().notify(outsider, ev)

        assert all(p._active_axis_index is None for p in panels), (
            "プロット外クリックで軸が解除されていない"
        )

    def test_press_inside_plot_subtree_does_not_clear(self, qtbot: QtBot) -> None:
        """誤解除ガード: subtree 内(パネル自身/子)への press では解除しない
        (パネル/軸/曲線の既存ハンドラがローカル処理する)。"""
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        view = _make_area(qtbot)
        panels = self._panels(view)
        panels[0].set_active_axis(0)

        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPoint(1, 1).toPointF()
            if hasattr(QPoint(1, 1), "toPointF")
            else QPoint(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # subtree 内オブジェクト(パネル widget)への press。
        QApplication.instance().notify(panels[0], ev)

        assert panels[0]._active_axis_index == 0, "subtree 内 press で誤って解除された"

    def test_press_on_ancestor_bubble_does_not_clear(self, qtbot: QtBot) -> None:
        """FU-23: 実クリックは未 accept 時に GraphAreaView の祖先へバブルする。
        その祖先配送を click-away と誤認して解除してはならない(軸ジェスチャ全滅の真因)。
        """
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

        view = _make_area(qtbot)
        panels = self._panels(view)
        panels[0].set_active_axis(0)

        # GraphAreaView を container の子にして祖先関係を作る。
        container = QWidget()
        qtbot.addWidget(container)
        layout = QVBoxLayout(container)
        layout.addWidget(view)  # type: ignore[arg-type]
        assert container.isAncestorOf(view)  # type: ignore[arg-type]

        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPoint(1, 1).toPointF()
            if hasattr(QPoint(1, 1), "toPointF")
            else QPoint(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # 祖先(container)への配送 = バブル痕跡。解除してはならない。
        QApplication.instance().notify(container, ev)

        assert panels[0]._active_axis_index == 0, (
            "祖先へのバブル配送で誤って軸が解除された(FU-23 退行)"
        )

    def test_event_filter_is_observation_only(self, qtbot: QtBot) -> None:
        """フィルタはイベントを消費しない(常に False を返す)。"""
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QWidget

        view = _make_area(qtbot)
        outsider = QWidget()
        qtbot.addWidget(outsider)
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPoint(1, 1).toPointF()
            if hasattr(QPoint(1, 1), "toPointF")
            else QPoint(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        assert view.eventFilter(outsider, ev) is False  # type: ignore[attr-defined]


def test_file_drop_highlight_border_paints_as_child(qtbot: QtBot) -> None:
    """OS ファイルドラッグの 2px 破線枠が子ウィジェットとして実描画される。

    素の QWidget サブクラスは WA_StyledBackground なしだと子として QSS
    border を描かない (増分1 デバッグテーマ検証で発覚した実バグ)。破線の
    ギャップを避けるため左端列を走査して枠色ピクセルの存在を assert する。
    """
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from valisync.core.session import Session
    from valisync.gui.theme.tokens import active
    from valisync.gui.views.graph_area_view import GraphAreaView

    vm = GraphAreaVM(AppViewModel(Session()))
    view = GraphAreaView(vm)
    parent = QWidget()
    qtbot.addWidget(parent)  # view は parent 所有 — 二重管理を避ける
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(view)
    parent.resize(400, 300)
    parent.show()
    view._set_drop_highlight(True)
    parent.repaint()
    img = parent.grab().toImage()
    expected = active().colors.drop_highlight
    hit = any(
        abs((p := img.pixelColor(1, y)).red() - expected.r) < 12
        and abs(p.green() - expected.g) < 12
        and abs(p.blue() - expected.b) < 12
        for y in range(4, img.height() - 4)
    )
    assert hit, f"左端列に枠色 {expected.hex} のピクセルが1つも無い (不描画)"
