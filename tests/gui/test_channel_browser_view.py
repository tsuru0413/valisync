"""Tests for ChannelBrowserView refactored for master-detail (Task 2.3).

The view is a QWidget containing a search box and a hierarchical QTreeView
(FU-22 B: array bases collapse under a parent node; scalars stay top-level
leaves). It binds to SignalTreeModel and ChannelBrowserVM.
"""

from __future__ import annotations

from pathlib import Path

import pytest
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


def _loaded_vm(tmp_path: Path) -> tuple[AppViewModel, ChannelBrowserVM, str]:
    """Same fixture data as test_channel_browser_vm.py's helper of the same name."""
    path = tmp_path / "d.csv"
    path.write_text("t,speed,brake\n0.0,1.0,0.0\n1.0,2.0,1.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, _csv_format())
    return app_vm, ChannelBrowserVM(app_vm), key


def _csv_format_n(n_signals: int) -> FormatDefinition:
    """Like _csv_format() but for an arbitrary signal-column count (PC-20)."""
    return FormatDefinition(
        name="test",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=n_signals,
        has_header=True,
    )


def _cb_view_with_signals(
    qtbot: QtBot, tmp_path: Path, names: list[str]
) -> ChannelBrowserView:
    """Build a ChannelBrowserView with *names* registered, in that column
    (== registration) order, as the active file's signals.

    Used by the PC-20 sort tests, which need a deliberately non-alphabetical
    initial order to distinguish "source order" from "sorted order".
    """
    path = tmp_path / "sort.csv"
    header = "t," + ",".join(names)
    row0 = "0.0," + ",".join("1.0" for _ in names)
    row1 = "1.0," + ",".join("2.0" for _ in names)
    path.write_text(f"{header}\n{row0}\n{row1}\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, _csv_format_n(len(names)))
    app_vm.set_active_file(key)
    vm = ChannelBrowserVM(app_vm)
    view = ChannelBrowserView(vm)
    qtbot.addWidget(view)
    return view


def _select(view: ChannelBrowserView, row: int) -> None:
    index = view.model.index(row, 0)
    view.tree.selectionModel().select(
        index,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )


def _make_view_with_arrays(
    qtbot: QtBot, tmp_path: Path
) -> tuple[AppViewModel, ChannelBrowserView, str]:
    """Build a ChannelBrowserView whose active file has one array base
    (Arr[0]/Arr[1] -> collapsible parent) plus one scalar (top-level leaf).

    group_signals is monkeypatched directly so no real load is needed; the
    active file key just has to be set before ChannelBrowserVM/View exist
    since SignalTreeModel reads tree_groups() in its own __init__.
    """
    import numpy as np

    from valisync.core.models import Signal

    app_vm = AppViewModel()

    def _sig(name: str) -> Signal:
        return Signal(
            name=name,
            timestamps=np.array([0.0]),
            values=np.array([1.0]),
            file_format="MDF4",
            bus_type="",
            source_file="",
            metadata={"unit": "V"},
        )

    app_vm.session.group_signals = lambda k: [  # type: ignore[method-assign]
        _sig("g::Arr[0]"),
        _sig("g::Arr[1]"),
        _sig("g::Scalar"),
    ]
    app_vm.set_active_file("g")
    vm = ChannelBrowserVM(app_vm)
    view = ChannelBrowserView(vm)
    qtbot.addWidget(view)
    return app_vm, view, "g"


# ─── Tests ──────────────────────────────────────────────────────────────────


# ─── Hierarchy parity (FU-22 B increment 1) ──────────────────────────────────


def test_view_uses_signal_tree_model(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-22 B: ChannelBrowserView は SignalTreeModel(階層)を表示する。"""
    from valisync.gui.adapters.signal_tree_model import SignalTreeModel

    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    assert isinstance(view.model, SignalTreeModel)
    assert not hasattr(view, "proxy")  # proxy 撤去(FU-22 B: 遅延保持)
    assert view.tree.model() is view.model  # model 直結
    top0 = view.model.index(0, 0, QModelIndex())
    assert view.model.rowCount(top0) >= 1  # array 親に子


def test_selected_leaf_resolves_source_key(qtbot: QtBot, tmp_path: Path) -> None:
    """親を展開しリーフを選択すると selected_signal_keys が源 key を返す(親スレッド grab)。"""
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    model = view.model
    parent = model.index(0, 0, QModelIndex())  # array parent
    child = model.index(0, 0, parent)  # first leaf child (no proxy threading)
    view.tree.selectionModel().select(
        child,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    keys = view.selected_signal_keys()
    assert len(keys) == 1 and keys[0].endswith("[0]")


def test_selecting_parent_yields_no_leaf_keys_in_incr1(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """増分①: 親選択は源 key を持たない(親追加は増分④)。"""
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    parent = view.model.index(0, 0, QModelIndex())
    view.tree.selectionModel().select(
        parent,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    assert view.selected_signal_keys() == []


class TestSearchFilter:
    def test_search_box_filters_list(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, key = _setup_app(tmp_path)  # sig_a, sig_b (scalars)
        app_vm.set_active_file(key)
        vm = ChannelBrowserVM(app_vm)
        view = _make_view(qtbot, vm)

        assert view.model.rowCount() == 2  # both scalars = top-level leaves
        view.search_box.setText("sig_a")
        # Debounced: filter applies after the timer fires in the event loop.
        qtbot.waitUntil(lambda: view.model.rowCount() == 1, timeout=1000)

    def test_search_box_debounces_filter(self, qtbot: QtBot, tmp_path: Path) -> None:
        """FU-22 B increment 2: keystrokes do not call set_filter synchronously;
        the debounce timer applies it once after typing pauses."""
        app_vm, key = _setup_app(tmp_path)
        app_vm.set_active_file(key)
        vm = ChannelBrowserVM(app_vm)
        view = _make_view(qtbot, vm)

        view.search_box.setText("sig_a")
        assert vm._filter_text == ""  # NOT applied synchronously (debounced)
        qtbot.waitUntil(
            lambda: vm._filter_text == "sig_a", timeout=1000
        )  # applied after debounce


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
    def test_hierarchical_appearance(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, _ = _setup_app(tmp_path)
        vm = ChannelBrowserVM(app_vm)
        view = _make_view(qtbot, vm)

        # FU-22 B: array bases are collapsible -> expand/collapse decoration on
        assert view.tree.rootIsDecorated()


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
    view.search_box.setText("xyz123")  # debounced textChanged -> set_filter
    qtbot.waitUntil(lambda: view.is_showing_placeholder(), timeout=1000)
    assert "xyz123" in view.placeholder_label.text()
    view.search_box.setText("")
    qtbot.waitUntil(lambda: not view.is_showing_placeholder(), timeout=1000)


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


# ─── Double-click / Enter (PC-04) ────────────────────────────────────────────
# 二重発火ガード: Windows では QAbstractItemView.activated が Enter でも発火
# するため、tree.activated (dblclick 用) と eventFilter (Return/Enter 用) を
# 両方配線すると 1 打鍵で 2 回 emit しうる。eventFilter が消費して防ぐ (spec §6)。


def test_enter_emits_add_exactly_once(qtbot: QtBot, tmp_path: Path) -> None:
    """二重発火ガード: Windows では activated も Enter で発火する ── 1 回だけ emit。"""
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)
    emitted: list[list[str]] = []
    view.add_to_panel_requested.connect(emitted.append)
    _select(view, 0)

    view.tree.setFocus()
    qtbot.keyClick(view.tree, Qt.Key.Key_Return)

    assert len(emitted) == 1


def test_enter_without_selection_does_not_emit(qtbot: QtBot, tmp_path: Path) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)
    emitted: list[list[str]] = []
    view.add_to_panel_requested.connect(emitted.append)

    view.tree.setFocus()
    qtbot.keyClick(view.tree, Qt.Key.Key_Return)

    assert emitted == []


def test_double_click_emits_add(qtbot: QtBot, tmp_path: Path) -> None:
    """Layer B dblclick: fresh itemview は warm-up click 前置が必須 (memory)。"""
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = _make_view(qtbot, vm)
    emitted: list[list[str]] = []
    view.add_to_panel_requested.connect(emitted.append)

    # view.tree is bound directly to view.model (no proxy, FU-22 B).
    index = view.model.index(0, 0)
    qtbot.waitUntil(lambda: view.tree.visualRect(index).height() > 0)
    rect_center = view.tree.visualRect(index).center()

    # warm-up (sabotage 検証: warm-up 単独では emit されないことを確認してから dblclick)
    qtbot.mouseClick(view.tree.viewport(), Qt.MouseButton.LeftButton, pos=rect_center)
    assert emitted == []  # warm-up が自力発火しない証明 (false-green 防止)

    qtbot.mouseDClick(view.tree.viewport(), Qt.MouseButton.LeftButton, pos=rect_center)

    assert len(emitted) == 1
    assert emitted[0] == view.selected_signal_keys()


# ─── Header-click Column Sort (PC-20/DP2) ────────────────────────────────────
# FU-22 B increment 1 dropped the QSortFilterProxyModel that used to sit
# between SignalTreeModel (source) and the tree -- it forced eager
# materialization of all array children on every reset (~456ms at prod scale),
# defeating the lazy tree built in Tasks 1-4. Sort moves VM-side in increment
# 3 (proxy dropped); the tests below are skipped until then.


@pytest.mark.skip(reason="FU-22 B: sort moves VM-side in increment 3 (proxy dropped)")
def test_default_order_is_source_order(qtbot: QtBot, tmp_path: Path) -> None:
    # ソート未クリックの既定は源順(登録順)を保つ(sortByColumn(-1) パススルー)。
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    names = [view.proxy.index(r, 0).data() for r in range(view.proxy.rowCount())]
    assert names == ["zed", "alpha", "mid"]  # 名前昇順に勝手に並び替えない


@pytest.mark.skip(reason="FU-22 B: sort moves VM-side in increment 3 (proxy dropped)")
def test_header_click_sorts_by_name(qtbot: QtBot, tmp_path: Path) -> None:
    # 登録順 "zed","alpha","mid" → 名前昇順ソートで alpha,mid,zed
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    view.proxy.sort(0, Qt.SortOrder.AscendingOrder)  # Name 列 昇順
    names = [view.proxy.index(r, 0).data() for r in range(view.proxy.rowCount())]
    assert names == ["alpha", "mid", "zed"]


@pytest.mark.skip(reason="FU-22 B: sort moves VM-side in increment 3 (proxy dropped)")
def test_selected_keys_correct_after_sort(qtbot: QtBot, tmp_path: Path) -> None:
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    view.proxy.sort(0, Qt.SortOrder.AscendingOrder)
    # ソート後の視覚的先頭行(=alpha)を選択 → mapToSource で alpha の key が返る
    top = view.proxy.index(0, 0)
    view.tree.selectionModel().select(
        top,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    keys = view.selected_signal_keys()
    assert len(keys) == 1
    assert keys[0].endswith(
        "::alpha"
    )  # 見た目どおり alpha(源 index ずれで zed にならない)


@pytest.mark.skip(reason="FU-22 B: sort moves VM-side in increment 3 (proxy dropped)")
def test_dnd_mime_keys_correct_after_sort(qtbot: QtBot, tmp_path: Path) -> None:
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    view.proxy.sort(0, Qt.SortOrder.AscendingOrder)
    top = view.proxy.index(0, 0)
    view.tree.selectionModel().select(
        top,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    md = view.mime_data_for_selection()
    from valisync.gui.adapters.qt_signal_models import decode_signal_keys

    keys = decode_signal_keys(md)
    assert keys and keys[0].endswith("::alpha")


@pytest.mark.skip(reason="FU-22 B: sort moves VM-side in increment 3 (proxy dropped)")
def test_sort_is_case_insensitive(qtbot: QtBot, tmp_path: Path) -> None:
    # 実 ADAS 信号名は大小混在 (EngineSpeed/vehSpd) -- QSortFilterProxyModel の
    # 既定 CaseSensitive のままだと大文字始まりが全て小文字始まりより前に来て
    # A-Z 走査が2ブロックに分断される (レビュー指摘の Minor follow-up)。
    view = _cb_view_with_signals(qtbot, tmp_path, ["Beta", "alpha", "Gamma"])
    view.proxy.sort(0, Qt.SortOrder.AscendingOrder)
    names = [view.proxy.index(r, 0).data() for r in range(view.proxy.rowCount())]
    assert names == ["alpha", "Beta", "Gamma"]
