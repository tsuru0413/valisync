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


def test_list_uses_custom_context_menu_policy(qtbot: QtBot) -> None:
    """The list MUST use CustomContextMenu so Qt emits customContextMenuRequested
    on a real right-click.

    The previous contextMenuEvent-override-on-the-container approach relied on the
    right-click propagating up from the child QListView, which does not fire — so
    the menu never appeared in the real GUI. This asserts the policy that makes the
    real-right-click signal fire.
    """
    from PySide6.QtCore import Qt

    app_vm = AppViewModel()
    app_vm._loaded_keys = ["a.mf4"]
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)

    assert view.list_view.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_right_click_on_row_opens_remove_menu_and_unloads(
    qtbot: QtBot, monkeypatch
) -> None:
    """User-operation-equivalent: emit customContextMenuRequested — the signal Qt
    fires on a real right-click on the list — at a row's position, and assert the
    'Remove File' menu is built for that row, the row is selected, and triggering
    the action unloads the file.

    This drives the SAME entry point a real right-click uses (the signal), so it
    catches missing/incorrect wiring that a direct contextMenuEvent call cannot.
    The modal .exec() is absorbed by spying build_context_menu (no headless block).
    """
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import Mock

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

    captured: dict = {}
    real_build = view.build_context_menu

    def spy_build(row: int) -> object:
        captured["row"] = row
        captured["menu"] = real_build(row)
        return Mock()  # the slot calls .exec() on this -> no-op

    monkeypatch.setattr(view, "build_context_menu", spy_build)

    # The signal carries a viewport-relative position; fire it over row 1 (b.csv).
    pos = view.list_view.visualRect(view.model.index(1, 0)).center()
    view.list_view.customContextMenuRequested.emit(pos)

    assert captured["row"] == 1
    assert view.list_view.currentIndex().row() == 1
    assert [a.text() for a in captured["menu"].actions()] == ["Remove File"]

    captured["menu"].actions()[0].trigger()
    assert vm.files == ["a.csv"]


def test_right_click_on_empty_area_shows_no_menu(qtbot: QtBot, monkeypatch) -> None:
    """A right-click below the items (empty area) builds no menu."""
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import Mock

    from PySide6.QtCore import QPoint

    from valisync.core.models import SignalGroup

    app_vm = AppViewModel()
    k = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/a.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k]
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)
    view.resize(200, 200)
    view.show()
    qtbot.waitExposed(view)

    built: list[int] = []
    monkeypatch.setattr(
        view, "build_context_menu", lambda row: built.append(row) or Mock()
    )

    view.list_view.customContextMenuRequested.emit(QPoint(5, 10_000))

    assert built == []  # no menu for empty space
