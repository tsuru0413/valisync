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
