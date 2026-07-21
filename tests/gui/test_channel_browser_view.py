"""Tests for ChannelBrowserView refactored for master-detail (Task 2.3).

The view is a QWidget containing a search box and a hierarchical QTreeView
(FU-22 B: array bases collapse under a parent node; scalars stay top-level
leaves). It binds to SignalTreeModel and ChannelBrowserVM.
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


def _cb_view_with_units(
    qtbot: QtBot, names_and_units: list[tuple[str, str]]
) -> ChannelBrowserView:
    """Build a ChannelBrowserView whose active file's signals carry the given
    (name, unit) pairs, in that order (registration == tree order, since the
    default sort is passthrough). Used by the UX-29 Unit-column-width tests,
    which need explicit control over per-signal units."""
    import numpy as np

    from valisync.core.models import Signal

    app_vm = AppViewModel()

    def _sig(name: str, unit: str) -> Signal:
        return Signal(
            name=name,
            timestamps=np.array([0.0]),
            values=np.array([1.0]),
            file_format="MDF4",
            bus_type="",
            source_file="",
            metadata={"unit": unit},
        )

    app_vm.session.group_signals = lambda k: [  # type: ignore[method-assign]
        _sig(name, unit) for name, unit in names_and_units
    ]
    app_vm.set_active_file("g")
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


# ─── Double-click / Enter (FU-06/FU-13) ──────────────────────────────────────
# PC-02 の add_button と Enter-add の eventFilter は撤去(Task 3)。追加は
# 右クリックメニュー(_emit_add_selected)と D&D のみに一本化。ダブルクリックは
# preview_requested を emit する(add ではない)。


def test_double_click_emits_preview_not_add(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-13: double-click emits preview_requested with the leaf key, NOT add."""
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    parent = view.model.index(0, 0, QModelIndex())  # array parent
    child = view.model.index(0, 0, parent)  # a leaf
    view.tree.selectionModel().select(
        child,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    with qtbot.waitSignal(view.preview_requested, timeout=1000) as prev:
        view.tree.doubleClicked.emit(child)
    assert prev.args[0].endswith("[0]")


def test_no_add_button(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-06: the 'add to active panel' button is removed."""
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    assert not hasattr(view, "add_button")


def test_enter_does_not_emit_add(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-06/Enter removal: pressing Enter on the tree emits neither add nor preview."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    parent = view.model.index(0, 0, QModelIndex())
    child = view.model.index(0, 0, parent)
    view.tree.selectionModel().select(
        child,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    fired: list[str] = []
    view.add_to_panel_requested.connect(lambda _k: fired.append("add"))
    view.preview_requested.connect(lambda _k: fired.append("preview"))
    ev = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
    )
    view.tree.keyPressEvent(ev)
    assert fired == []  # Enter does nothing


def test_context_menu_add_still_emits(qtbot: QtBot, tmp_path: Path) -> None:
    """Regression: right-click 'Add to Active Panel' still emits add_to_panel_requested."""
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    parent = view.model.index(0, 0, QModelIndex())
    child = view.model.index(0, 0, parent)
    view.tree.selectionModel().select(
        child,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    menu = view.build_context_menu()
    add_action = next(a for a in menu.actions() if a.text() == "Add to Active Panel")
    with qtbot.waitSignal(view.add_to_panel_requested, timeout=1000):
        add_action.trigger()


# ─── Header-click Column Sort (PC-20/DP2) ────────────────────────────────────
# FU-22 B increment 1 dropped the QSortFilterProxyModel that used to sit
# between SignalTreeModel (source) and the tree -- it forced eager
# materialization of all array children on every reset (~456ms at prod scale),
# defeating the lazy tree built in Tasks 1-4. Sort is now implemented VM-side
# on SignalTreeModel itself (increment 3: SignalTreeModel.sort() + the view's
# setSortingEnabled/sortByColumn(-1) wiring) -- these tests exercise the model
# directly with no proxy indirection.


def test_default_order_is_source_order(qtbot: QtBot, tmp_path: Path) -> None:
    # ソート未クリックの既定は源順(登録順)を保つ(sortByColumn(-1) パススルー)。
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    names = [
        view.model.index(r, 0, QModelIndex()).data()
        for r in range(view.model.rowCount(QModelIndex()))
    ]
    assert names == ["zed", "alpha", "mid"]  # 名前昇順に勝手に並び替えない


def test_header_click_sorts_by_name(qtbot: QtBot, tmp_path: Path) -> None:
    # 登録順 "zed","alpha","mid" → 名前昇順ソートで alpha,mid,zed
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    view.model.sort(0, Qt.SortOrder.AscendingOrder)  # Name 列 昇順
    names = [
        view.model.index(r, 0, QModelIndex()).data()
        for r in range(view.model.rowCount(QModelIndex()))
    ]
    assert names == ["alpha", "mid", "zed"]


def test_selected_keys_correct_after_sort(qtbot: QtBot, tmp_path: Path) -> None:
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    view.model.sort(0, Qt.SortOrder.AscendingOrder)
    # ソート後の視覚的先頭行(=alpha)を選択 → model 直結で alpha の key が返る
    top = view.model.index(0, 0, QModelIndex())
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


def test_dnd_mime_keys_correct_after_sort(qtbot: QtBot, tmp_path: Path) -> None:
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    view.model.sort(0, Qt.SortOrder.AscendingOrder)
    top = view.model.index(0, 0, QModelIndex())
    view.tree.selectionModel().select(
        top,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    md = view.mime_data_for_selection()
    from valisync.gui.adapters.qt_signal_models import decode_signal_keys

    keys = decode_signal_keys(md)
    assert keys and keys[0].endswith("::alpha")


def test_sort_is_case_insensitive(qtbot: QtBot, tmp_path: Path) -> None:
    # 実 ADAS 信号名は大小混在 (EngineSpeed/vehSpd) -- 単純な CaseSensitive
    # ソートだと大文字始まりが全て小文字始まりより前に来て A-Z 走査が2ブロック
    # に分断される (レビュー指摘の Minor follow-up)。SignalTreeModel._sort_key
    # は .lower() で正規化するので混在しても連続する。
    view = _cb_view_with_signals(qtbot, tmp_path, ["Beta", "alpha", "Gamma"])
    view.model.sort(0, Qt.SortOrder.AscendingOrder)
    names = [
        view.model.index(r, 0, QModelIndex()).data()
        for r in range(view.model.rowCount(QModelIndex()))
    ]
    assert names == ["alpha", "Beta", "Gamma"]


def test_sorting_enabled_does_not_materialize_children(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-22 B: setSortingEnabled(True) の tree でも array 子は展開まで materialize
    されない(QSortFilterProxyModel がこれを破壊していた教訓の直接検証)。"""
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    view.model.sort(0, Qt.SortOrder.AscendingOrder)
    qtbot.wait(10)  # let the tree react to the sort
    parents = [n for n in view.model._top if n.key is None]
    assert parents and all(n.children is None for n in parents)


# ─── Column width defaults (UX-29) ────────────────────────────────────────────
# spec §1.5-13: Name stretches to fill remaining space; Unit is Interactive
# and sized from a bounded content sample -- ResizeToContents must never be
# used on Unit (prod 264k-330k rows would re-walk sizeHintForColumn on every
# reset, an FU-22-class freeze).


def test_name_column_stretches_unit_column_is_interactive(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QHeaderView

    app_vm, key = _setup_app(tmp_path)
    app_vm.set_active_file(key)
    vm = ChannelBrowserVM(app_vm)
    view = _make_view(qtbot, vm)

    header = view.tree.header()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.Interactive
    # QTreeView defaults stretchLastSection to True, which would silently
    # force-stretch Unit (the last column) regardless of the Interactive mode
    # set on it above -- must be disabled for Interactive to actually stick.
    assert not header.stretchLastSection()


def test_unit_column_width_truncates_sample_at_50_rows(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """A Unit string beyond the first 50 rows must not influence the sampled
    column width -- proves the sample is bounded (never a full O(rows) scan,
    the ResizeToContents hazard this design deliberately avoids)."""
    names_and_units = [(f"sig{i}", "V") for i in range(50)] + [
        ("sig_overflow", "X" * 200)
    ]
    view = _cb_view_with_units(qtbot, names_and_units)

    samples = view._sample_unit_values(50)
    assert len(samples) == 50
    assert all(s == "V" for s in samples)  # the 200-char overflow never sampled

    # If the 200-char overflow unit had been sampled, the width would be
    # clamped to the 120px cap; confirm it stayed near the short "V" samples.
    assert view.tree.columnWidth(1) < 100


def test_unit_column_width_falls_back_to_min_when_model_empty(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """No active file -> no rows to sample; must not crash and must fall back
    to exactly _UNIT_COLUMN_MIN_WIDTH (not 0px, which would hide the column)."""
    from valisync.gui.views.channel_browser_view import _UNIT_COLUMN_MIN_WIDTH

    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    view = _make_view(qtbot, vm)
    assert view.tree.columnWidth(1) == _UNIT_COLUMN_MIN_WIDTH


def test_unit_column_width_clamps_to_max_when_sample_has_long_unit(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Positive control for the 120px cap (companion to the truncation test
    above, which keeps its long string OUTSIDE the 50-row window): a long
    Unit string INSIDE the window must actually drive the width to exactly
    _UNIT_COLUMN_MAX_WIDTH, proving the clamp branch engages rather than
    merely never overflowing by coincidence."""
    from valisync.gui.views.channel_browser_view import _UNIT_COLUMN_MAX_WIDTH

    names_and_units = [(f"sig{i}", "V") for i in range(49)] + [("sig_long", "X" * 200)]
    view = _cb_view_with_units(qtbot, names_and_units)
    assert view.tree.columnWidth(1) == _UNIT_COLUMN_MAX_WIDTH


def test_sampling_reflects_real_leaf_units_once_group_materialized(
    qtbot: QtBot,
) -> None:
    """has_materialized_children() positive branch: once a group's children
    are already materialized (e.g. by a prior user expansion), the bounded
    Unit-column sample descends into it and picks up the REAL leaf unit
    strings, not just the group's own blank Unit cell. Distinguished from the
    not-yet-materialized case by an actual width increase (a relative
    comparison, not a hardcoded pixel value, to stay robust to font-metric
    differences across environments) -- the negative branch (never forcing
    materialization) is already covered by
    test_sorting_enabled_does_not_materialize_children in the sort section
    above."""
    import numpy as np

    from valisync.core.models import Signal

    long_unit = "kilometers_per_hour_precise"
    app_vm = AppViewModel()

    def _sig(name: str, unit: str) -> Signal:
        return Signal(
            name=name,
            timestamps=np.array([0.0]),
            values=np.array([1.0]),
            file_format="MDF4",
            bus_type="",
            source_file="",
            metadata={"unit": unit},
        )

    app_vm.session.group_signals = lambda k: [  # type: ignore[method-assign]
        _sig("g::Arr[0]", long_unit),
        _sig("g::Arr[1]", long_unit),
        _sig("g::Scalar", "V"),
    ]
    app_vm.set_active_file("g")
    vm = ChannelBrowserVM(app_vm)
    view = ChannelBrowserView(vm)
    qtbot.addWidget(view)

    group_index = view.model.index(0, 0, QModelIndex())

    # Not yet materialized: sampling must not force it (FU-22 B) -- the group
    # contributes only its own blank Unit cell, so the sample never sees the
    # long leaf unit and width tracks "V" alone.
    before_samples = view._sample_unit_values(50)
    assert long_unit not in before_samples
    width_before = view.tree.columnWidth(1)

    # Simulate a real user expansion: Qt's item view reaches a group's
    # children via index()/rowCount(), exactly like SignalTreeModel.index()
    # does when the tree actually expands that node.
    view.model.index(0, 0, group_index)
    assert view.model.has_materialized_children(group_index)

    # sort() reorders _top/_Node.children IN PLACE (unlike a signals/filter
    # reset, which calls _rebuild() and would construct fresh _Node objects,
    # re-losing the materialized state) -- it is the reset vehicle that
    # matches "the user re-sorts after already expanding a node".
    view.model.sort(0, Qt.SortOrder.AscendingOrder)

    after_samples = view._sample_unit_values(50)
    assert long_unit in after_samples
    assert view.tree.columnWidth(1) > width_before
