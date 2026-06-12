"""Tests for ChannelBrowserView refactored for master-detail (Task 2.3).

The view is a QWidget containing a search box and a flat QTreeView.
It binds to SignalTableModel and ChannelBrowserVM.
"""

from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt
from pytestqt.qtbot import QtBot

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
from valisync.gui.views.channel_browser_view import ChannelBrowserView

# ─── Helpers ────────────────────────────────────────────────────────────────

def _csv_format() -> FormatDefinition:
    return FormatDefinition(
        name="test",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )

def _write_csv(path: Path) -> Path:
    path.write_text("t,sig_a,sig_b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    return path

def _setup_app(tmp_path: Path) -> tuple[AppViewModel, str]:
    app_vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")
    key = app_vm.request_load(csv_file, _csv_format())
    return app_vm, key

def _make_view(qtbot: QtBot, vm: ChannelBrowserVM) -> ChannelBrowserView:
    view = ChannelBrowserView(vm)
    qtbot.addWidget(view)
    return view

def _select(view: ChannelBrowserView, row: int) -> None:
    index = view.model.index(row, 0)
    view.tree.selectionModel().select(
        index,
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    )

# ─── Tests ──────────────────────────────────────────────────────────────────

class TestSearchFilter:
    def test_search_box_filters_list(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, key = _setup_app(tmp_path)
        app_vm.set_active_file(key)
        vm = ChannelBrowserVM(app_vm)
        view = _make_view(qtbot, vm)
        
        assert view.model.rowCount() == 2
        view.search_box.setText("sig_a")
        assert view.model.rowCount() == 1

class TestSelection:
    def test_selection_updates_vm(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, key = _setup_app(tmp_path)
        app_vm.set_active_file(key)
        vm = ChannelBrowserVM(app_vm)
        view = _make_view(qtbot, vm)
        
        _select(view, 0)
        assert len(vm.selected()) == 1
        assert vm.selected()[0] == f"{key}::sig_a"

class TestLayout:
    def test_flat_appearance(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, _ = _setup_app(tmp_path)
        vm = ChannelBrowserVM(app_vm)
        view = _make_view(qtbot, vm)
        
        # Decoration (expand/collapse icons) should be disabled for a flat list
        assert not view.tree.rootIsDecorated()

class TestActiveFileSync:
    def test_refreshes_on_active_file_change(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, key = _setup_app(tmp_path)
        vm = ChannelBrowserVM(app_vm)
        view = _make_view(qtbot, vm)
        
        assert view.model.rowCount() == 0
        app_vm.set_active_file(key)
        assert view.model.rowCount() == 2
