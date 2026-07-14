"""Tests for FileListModel adapter.

Tests verify:
- rowCount matches FileBrowserVM.files count
- data() returns filenames from VM
- model refreshes when VM notifies 'files'
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from valisync.core.models import SignalGroup
from valisync.gui.adapters.qt_signal_models import FileListModel
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM


def test_row_count_matches_vm(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/a.mf4").absolute(), "MDF4", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/b.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]

    vm = FileBrowserVM(app_vm)
    model = FileListModel(vm)

    assert model.rowCount(QModelIndex()) == 2


def test_data_returns_filenames(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    k = app_vm.session._groups.add(
        SignalGroup((), Path("/path/a.mf4").absolute(), "MDF4", datetime.now())
    )
    app_vm._loaded_keys = [k]

    vm = FileBrowserVM(app_vm)
    model = FileListModel(vm)

    index = model.index(0, 0, QModelIndex())
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "a.mf4"


def test_refreshes_on_vm_notification(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    model = FileListModel(vm)

    assert model.rowCount(QModelIndex()) == 0

    # Simulate load
    k = app_vm.session._groups.add(
        SignalGroup((), Path("/new.mf4").absolute(), "MDF4", datetime.now())
    )
    app_vm._loaded_keys = [k]
    app_vm._notify("loaded")

    assert model.rowCount(QModelIndex()) == 1
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "new.mf4"


def test_releasing_row_foreground_uses_token(qtbot: QtBot, monkeypatch) -> None:
    """配線検証: 解放中行の ForegroundRole が text_releasing トークンを返す。"""
    from PySide6.QtGui import QColor

    from valisync.gui.theme.tokens import active

    app_vm = AppViewModel()
    k = app_vm.session._groups.add(
        SignalGroup((), Path("/a.mf4").absolute(), "MDF4", datetime.now())
    )
    app_vm._loaded_keys = [k]
    vm = FileBrowserVM(app_vm)
    model = FileListModel(vm)
    monkeypatch.setattr(vm, "is_releasing", lambda row: True)

    index = model.index(0, 0, QModelIndex())
    expected = QColor(*active().colors.text_releasing.rgba)
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) == expected
