"""Tests for FileBrowserVM.

Tests verify:
- files property returns filenames (basenames) of loaded files
- select_file(index) updates AppViewModel.active_file_key
- VM refreshes its list when AppViewModel notifies 'loaded'
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from valisync.core.models import SignalGroup
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM


def test_initial_files_list_is_empty() -> None:
    app_vm = AppViewModel()
    fb_vm = FileBrowserVM(app_vm)
    assert fb_vm.files == []


def test_files_list_contains_basenames() -> None:
    app_vm = AppViewModel()
    # Simulate real group keys and SignalGroup objects in session
    # Based on core logic, first MDF4 is mf4_1, first CSV is csv_1
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data1.mf4").absolute(), "MDF4", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data2.csv").absolute(), "CSV", datetime.now())
    )

    app_vm._loaded_keys = [k1, k2]

    fb_vm = FileBrowserVM(app_vm)

    # Actual source filenames should be extracted
    assert fb_vm.files == ["data1.mf4", "data2.csv"]


def test_select_file_updates_app_vm() -> None:
    app_vm = AppViewModel()
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data1.mf4").absolute(), "MDF4", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data2.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    fb_vm = FileBrowserVM(app_vm)

    fb_vm.select_file(1)
    assert app_vm.active_file_key == k2


def test_refreshes_on_loaded_notification() -> None:
    app_vm = AppViewModel()
    fb_vm = FileBrowserVM(app_vm)
    notifications: list[str] = []
    fb_vm.subscribe(notifications.append)

    # Simulate load with real key and group
    k = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data1.mf4").absolute(), "MDF4", datetime.now())
    )
    app_vm._loaded_keys = [k]
    app_vm._notify("loaded")

    assert fb_vm.files == ["data1.mf4"]
    assert "files" in notifications
