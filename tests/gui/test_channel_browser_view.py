"""Tests for ChannelBrowserView — Task 7.2.

The view is a thin QWidget: a search box over a QTreeView bound to
ChannelTreeModel.  It forwards user gestures to ChannelBrowserVM (filter,
selection, visibility) and builds a drag MimeData payload of selected
signal keys.  All assertions go through the VM's observable state or the
adapter, never pixels.

TDD: written before the view exists; all must FAIL first.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QModelIndex
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv_format_2cols() -> FormatDefinition:
    return FormatDefinition(
        name="t2",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )


def _write_2col_csv(path: Path) -> Path:
    path.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n2.0,3.0,6.0\n", encoding="utf-8")
    return path


def _loaded_session(tmp_path: Path, name: str = "data.csv") -> tuple[Session, str]:
    csv_file = _write_2col_csv(tmp_path / name)
    session = Session()
    key = session.load(csv_file, _csv_format_2cols())
    return session, key


def _make_view(qtbot: QtBot, vm: ChannelBrowserVM) -> object:
    from valisync.gui.views.channel_browser_view import ChannelBrowserView

    view = ChannelBrowserView(vm)
    qtbot.addWidget(view)
    return view


def _leaf_index(view: object, group_row: int, leaf_row: int) -> QModelIndex:
    model = view.tree_model  # type: ignore[attr-defined]
    group = model.index(group_row, 0, QModelIndex())
    return model.index(leaf_row, 0, group)


def _select(view: object, index: QModelIndex, clear: bool = True) -> None:
    flags = (
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows
    )
    if clear:
        flags |= QItemSelectionModel.SelectionFlag.Clear
    view.tree.selectionModel().select(index, flags)  # type: ignore[attr-defined]


# ─── Search box → filter ───────────────────────────────────────────────────


class TestSearchFilter:
    def test_search_box_narrows_tree(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        view.search_box.setText("a")  # type: ignore[attr-defined]

        group_index = view.tree_model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        # Only signal 'a' matches the substring filter.
        assert view.tree_model.rowCount(group_index) == 1  # type: ignore[attr-defined]

    def test_search_box_updates_vm_filter(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        view.search_box.setText("xyz")  # type: ignore[attr-defined]

        assert vm.inspect()["filter_text"] == "xyz"

    def test_clearing_search_restores_full_tree(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path)
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        view.search_box.setText("a")  # type: ignore[attr-defined]
        view.search_box.setText("")  # type: ignore[attr-defined]

        group_index = view.tree_model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        assert view.tree_model.rowCount(group_index) == 2  # type: ignore[attr-defined]


# ─── Selection → VM ────────────────────────────────────────────────────────


class TestSelection:
    def test_selecting_leaf_updates_vm_selection(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, key = _loaded_session(tmp_path)
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        _select(view, _leaf_index(view, 0, 0))

        assert len(vm.selected()) == 1
        assert vm.selected()[0].startswith(f"{key}::")

    def test_multi_selection_collects_all_keys(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, key = _loaded_session(tmp_path)
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        _select(view, _leaf_index(view, 0, 0), clear=True)
        _select(view, _leaf_index(view, 0, 1), clear=False)

        assert set(vm.selected()) == {f"{key}::a", f"{key}::b"}

    def test_group_selection_yields_no_signal_keys(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path)
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        group_index = view.tree_model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        _select(view, group_index)

        # Selecting a group header contributes no signal keys.
        assert vm.selected() == []


# ─── Drag MimeData ──────────────────────────────────────────────────────────


class TestDragMime:
    def test_mime_data_carries_selected_keys(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        from valisync.gui.adapters.qt_signal_models import (
            SIGNAL_KEYS_MIME,
            decode_signal_keys,
        )

        session, key = _loaded_session(tmp_path)
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        _select(view, _leaf_index(view, 0, 0), clear=True)
        _select(view, _leaf_index(view, 0, 1), clear=False)
        mime = view.mime_data_for_selection()  # type: ignore[attr-defined]

        assert mime.hasFormat(SIGNAL_KEYS_MIME)
        assert set(decode_signal_keys(mime)) == {f"{key}::a", f"{key}::b"}

    def test_mime_data_empty_when_nothing_selected(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        from valisync.gui.adapters.qt_signal_models import decode_signal_keys

        session, _ = _loaded_session(tmp_path)
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        mime = view.mime_data_for_selection()  # type: ignore[attr-defined]

        assert decode_signal_keys(mime) == []


# ─── Visibility toggle ────────────────────────────────────────────────────────


class TestVisibilityToggle:
    def test_toggle_selected_hides_signal(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        _select(view, _leaf_index(view, 0, 0))
        view.toggle_visibility_for_selection()  # type: ignore[attr-defined]

        sel = vm.selected()[0]
        assert vm.is_visible(sel) is False


# ─── External refresh ─────────────────────────────────────────────────────────


class TestExternalRefresh:
    def test_loading_new_signals_updates_tree_on_vm_refresh(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        csv1 = _write_2col_csv(tmp_path / "d1.csv")
        csv2 = _write_2col_csv(tmp_path / "d2.csv")
        session = Session()
        session.load(csv1, _csv_format_2cols())
        vm = ChannelBrowserVM(session)
        view = _make_view(qtbot, vm)

        before = view.tree_model.rowCount(QModelIndex())  # type: ignore[attr-defined]
        session.load(csv2, _csv_format_2cols())
        vm.refresh()
        after = view.tree_model.rowCount(QModelIndex())  # type: ignore[attr-defined]

        assert after == before + 1


# ─── Mime encode/decode round-trip (adapter helpers) ───────────────────────────


class TestMimeHelpers:
    def test_encode_decode_round_trip(self, qtbot: QtBot) -> None:
        from valisync.gui.adapters.qt_signal_models import (
            decode_signal_keys,
            encode_signal_keys,
        )

        keys = ["csv_1::a", "csv_1::b", "mf4_2::speed"]
        assert decode_signal_keys(encode_signal_keys(keys)) == keys

    def test_decode_unrelated_mime_is_empty(self, qtbot: QtBot) -> None:
        from PySide6.QtCore import QMimeData

        from valisync.gui.adapters.qt_signal_models import decode_signal_keys

        md = QMimeData()
        md.setText("not signal keys")
        assert decode_signal_keys(md) == []
