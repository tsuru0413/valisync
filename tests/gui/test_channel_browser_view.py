"""Tests for ChannelBrowserView refactored for master-detail (Task 2.3).

The view is a QWidget containing a search box and a flat QTreeView.
It binds to SignalTableModel and ChannelBrowserVM.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt
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


def _loaded_vm(tmp_path: Path) -> tuple[AppViewModel, ChannelBrowserVM, str]:
    """Same fixture data as test_channel_browser_vm.py's helper of the same name."""
    path = tmp_path / "d.csv"
    path.write_text("t,speed,brake\n0.0,1.0,0.0\n1.0,2.0,1.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, _csv_format())
    return app_vm, ChannelBrowserVM(app_vm), key


def _select(view: ChannelBrowserView, row: int) -> None:
    index = view.model.index(row, 0)
    view.tree.selectionModel().select(
        index,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
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
    def test_refreshes_on_active_file_change(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        app_vm, key = _setup_app(tmp_path)
        vm = ChannelBrowserVM(app_vm)
        view = _make_view(qtbot, vm)

        assert view.model.rowCount() == 0
        app_vm.set_active_file(key)
        assert view.model.rowCount() == 2


# ─── Header / Empty-State Tests (FB-05/08/09) ────────────────────────────────


def test_header_label_shows_active_file_and_counts(
    qtbot: QtBot, tmp_path: Path
) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)
    assert "d.csv" in view.header_label.text()
    assert "2 ch 中 2 件表示" in view.header_label.text()


def test_placeholder_when_none_selected(qtbot: QtBot, tmp_path: Path) -> None:
    app_vm, vm, _key = _loaded_vm(tmp_path)
    app_vm.set_active_file(None)
    view = _make_view(qtbot, vm)
    assert view.is_showing_placeholder()
    assert "ファイルを選択" in view.placeholder_label.text()


def test_placeholder_no_match_includes_query_and_recovers(
    qtbot: QtBot, tmp_path: Path
) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)
    view.search_box.setText("xyz123")  # 実経路: textChanged → set_filter
    assert view.is_showing_placeholder()
    assert "xyz123" in view.placeholder_label.text()
    view.search_box.setText("")
    assert not view.is_showing_placeholder()


def test_no_channels_placeholder_shown_after_refresh(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    # mdf_loader は全チャンネル skip 時に 0ch グループを登録し得る
    # (production 到達可能・catalog LD-05) — この経路が View まで通しで
    # プレースホルダに落ちることを確認する(VM 単体では View の
    # QStackedWidget 切替配線までは検証できない)。
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)

    monkeypatch.setattr(app_vm.session, "group_signals", lambda _k: [])
    vm.refresh()  # "signals" notify で View を再描画させる

    assert view.is_showing_placeholder()
    assert "このファイルに信号がありません" in view.placeholder_label.text()


# ─── Add Button (PC-02) ──────────────────────────────────────────────────────
# view/選択の構築式は本ファイル既存の _loaded_vm/_make_view/_select に倣う
# (このファイルに view fixture・_select_first_row ヘルパは存在しないため)。


def test_add_button_disabled_without_selection(qtbot: QtBot, tmp_path: Path) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)
    assert not view.add_button.isEnabled()


def test_add_button_enabled_with_selection(qtbot: QtBot, tmp_path: Path) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)
    _select(view, 0)
    assert view.add_button.isEnabled()


def test_add_button_disabled_after_clear(qtbot: QtBot, tmp_path: Path) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)
    _select(view, 0)
    view.tree.selectionModel().clearSelection()
    assert not view.add_button.isEnabled()


def test_add_button_click_emits_selected_keys(qtbot: QtBot, tmp_path: Path) -> None:
    """Layer B: 実クリック(合成) -> clicked -> emit の実経路。emit 直叩き禁止。"""
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)
    emitted: list[list[str]] = []
    view.add_to_panel_requested.connect(emitted.append)
    _select(view, 0)

    qtbot.mouseClick(view.add_button, Qt.MouseButton.LeftButton)

    assert emitted == [view.selected_signal_keys()]
    assert emitted[0]  # 空 emit でない
