"""Tests for FileBrowserView.

Tests verify:
- contains a QListView
- selection in QListView calls select_file on VM
- model is correctly set
"""

from __future__ import annotations

from PySide6.QtWidgets import QListView
from pytestqt.qtbot import QtBot

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.views.file_browser_view import FileBrowserView


def test_view_contains_list_view(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    assert isinstance(view.list_view, QListView)


def test_selection_triggers_vm_select(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    app_vm._loaded_keys = ["a.mf4", "b.csv"]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    # Select the second item (index 1)
    index = view.model.index(1, 0)
    view.list_view.selectionModel().select(
        index, view.list_view.selectionModel().SelectionFlag.Select
    )

    # VM should be updated
    assert app_vm.active_file_key == "b.csv"


def test_empty_selection_clears_vm(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    app_vm._loaded_keys = ["a.mf4"]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    # Select first
    index = view.model.index(0, 0)
    view.list_view.selectionModel().select(
        index, view.list_view.selectionModel().SelectionFlag.Select
    )
    assert app_vm.active_file_key == "a.mf4"

    # Clear selection
    view.list_view.selectionModel().clearSelection()

    assert app_vm.active_file_key is None


def test_context_menu_remove_unloads_file(qtbot: QtBot) -> None:
    from datetime import datetime
    from pathlib import Path

    from valisync.core.models import SignalGroup

    app_vm = AppViewModel()
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/b.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    assert vm.files == ["a.csv", "b.csv"]

    menu = view.build_context_menu(0)
    actions = menu.actions()
    assert [act.text() for act in actions] == ["Remove File"]
    actions[0].trigger()

    assert vm.files == ["b.csv"]


def test_context_menu_event_resolves_and_selects_row(qtbot: QtBot) -> None:
    """Right-click row resolution: a position over a file row resolves+selects
    it; a position over empty space resolves to None (no menu).

    Guards the contextMenuEvent path that build_context_menu alone cannot cover —
    its modal .exec() keeps the real event handler out of the menu test, so the
    row-resolution logic is extracted into _select_row_at and tested here.
    """
    from datetime import datetime
    from pathlib import Path

    from PySide6.QtCore import QPoint

    from valisync.core.models import SignalGroup

    app_vm = AppViewModel()
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/b.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    view.resize(200, 200)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(
        lambda: view.list_view.visualRect(view.model.index(0, 0)).height() > 0,
        timeout=2000,
    )

    # A point over row 1 resolves to row 1 and selects it.
    rect1 = view.list_view.visualRect(view.model.index(1, 0))
    over_row1 = view.list_view.viewport().mapToGlobal(rect1.center())
    assert view._select_row_at(over_row1) == 1
    assert view.list_view.currentIndex().row() == 1

    # A point far past the last item is empty space -> None (no menu shown).
    far_below = view.list_view.viewport().mapToGlobal(QPoint(5, 10_000))
    assert view._select_row_at(far_below) is None
