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
        qtbot.addWidget(view)
        assert len(vm._callbacks) == 1

        view.deleteLater()
        qtbot.wait(50)  # let the C++ object be destroyed (fires destroyed())

        assert len(vm._callbacks) == 0
        vm.add_tab()  # a notify after destruction must not raise
