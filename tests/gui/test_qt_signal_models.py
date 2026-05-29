"""Tests for ChannelTreeModel — Task 7.1.

The adapter bridges ChannelBrowserVM.tree() to a QAbstractItemModel so a
QTreeView can render the signal hierarchy.  These tests assert that the
model's rows/columns/data mirror the VM tree exactly, and that refresh()
re-syncs after the underlying Session changes.

TDD: written before the adapter exists; all must FAIL first.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
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


def _loaded_vm(tmp_path: Path, name: str = "data.csv") -> tuple[ChannelBrowserVM, str]:
    csv_file = _write_2col_csv(tmp_path / name)
    session = Session()
    key = session.load(csv_file, _csv_format_2cols())
    return ChannelBrowserVM(session), key


def _make_model(qtbot: QtBot, vm: ChannelBrowserVM) -> object:
    """Construct a ChannelTreeModel bound to *vm*.  qtbot ensures a QApplication."""
    from valisync.gui.adapters.qt_signal_models import ChannelTreeModel

    return ChannelTreeModel(vm)


def _disp(model: object, index: QModelIndex) -> object:
    return model.data(index, Qt.ItemDataRole.DisplayRole)  # type: ignore[attr-defined]


# ─── Shape: rows / columns ────────────────────────────────────────────────────


class TestShape:
    def test_root_row_count_equals_group_count(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        vm, _ = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        assert model.rowCount(QModelIndex()) == len(vm.tree())  # type: ignore[attr-defined]

    def test_group_row_count_equals_signal_count(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        vm, key = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        group_index = model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        group = next(g for g in vm.tree() if g["key"] == key)
        assert model.rowCount(group_index) == len(group["signals"])  # type: ignore[attr-defined]

    def test_column_count_is_four(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, _ = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        assert model.columnCount(QModelIndex()) == 4  # type: ignore[attr-defined]

    def test_leaf_has_no_children(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, _ = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        group_index = model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        leaf_index = model.index(0, 0, group_index)  # type: ignore[attr-defined]
        assert model.rowCount(leaf_index) == 0  # type: ignore[attr-defined]

    def test_empty_session_has_no_rows(self, qtbot: QtBot) -> None:
        vm = ChannelBrowserVM(Session())
        model = _make_model(qtbot, vm)
        assert model.rowCount(QModelIndex()) == 0  # type: ignore[attr-defined]


# ─── Data: group + leaf cells ──────────────────────────────────────────────────


class TestData:
    def test_group_row_displays_key(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, key = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        group_index = model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        assert _disp(model, group_index) == key

    def test_leaf_columns_match_vm_leaf(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, key = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        group_index = model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        group = next(g for g in vm.tree() if g["key"] == key)
        leaf = group["signals"][0]

        name_cell = _disp(model, model.index(0, 0, group_index))  # type: ignore[attr-defined]
        dtype_cell = _disp(model, model.index(0, 1, group_index))  # type: ignore[attr-defined]
        count_cell = _disp(model, model.index(0, 2, group_index))  # type: ignore[attr-defined]

        assert name_cell == leaf["display_name"]
        assert dtype_cell == leaf["dtype"]
        assert str(leaf["count"]) in str(count_cell)

    def test_group_meta_columns_blank(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, _ = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        # Columns 1..3 on a group row carry no metadata.
        group_dtype = model.data(  # type: ignore[attr-defined]
            model.index(0, 1, QModelIndex()),  # type: ignore[attr-defined]
            Qt.ItemDataRole.DisplayRole,
        )
        assert group_dtype in ("", None)

    def test_header_data_titles(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, _ = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        titles = [
            model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)  # type: ignore[attr-defined]
            for c in range(4)
        ]
        # First column is the name/tree column; the rest expose signal metadata.
        assert titles[0]
        assert len(titles) == 4
        assert all(t for t in titles)


# ─── index / parent round-trip ─────────────────────────────────────────────────


class TestNavigation:
    def test_parent_of_leaf_is_group(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, _ = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        group_index = model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        leaf_index = model.index(0, 0, group_index)  # type: ignore[attr-defined]
        parent = model.parent(leaf_index)  # type: ignore[attr-defined]
        assert parent.row() == group_index.row()
        assert parent.internalId() == group_index.internalId()

    def test_parent_of_group_is_invalid(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, _ = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        group_index = model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        assert not model.parent(group_index).isValid()  # type: ignore[attr-defined]

    def test_signal_key_at_leaf_is_namespaced_name(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        vm, key = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        group_index = model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        leaf_index = model.index(0, 0, group_index)  # type: ignore[attr-defined]
        sig_key = model.signal_key_at(leaf_index)  # type: ignore[attr-defined]
        assert sig_key in (f"{key}::a", f"{key}::b")

    def test_signal_key_at_group_is_none(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, _ = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        group_index = model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        assert model.signal_key_at(group_index) is None  # type: ignore[attr-defined]


# ─── refresh() re-syncs with the VM/Session ────────────────────────────────────


class TestRefresh:
    def test_refresh_picks_up_new_group(self, qtbot: QtBot, tmp_path: Path) -> None:
        csv1 = _write_2col_csv(tmp_path / "d1.csv")
        csv2 = _write_2col_csv(tmp_path / "d2.csv")
        session = Session()
        session.load(csv1, _csv_format_2cols())
        vm = ChannelBrowserVM(session)
        model = _make_model(qtbot, vm)

        before = model.rowCount(QModelIndex())  # type: ignore[attr-defined]
        session.load(csv2, _csv_format_2cols())
        model.refresh()  # type: ignore[attr-defined]
        after = model.rowCount(QModelIndex())  # type: ignore[attr-defined]

        assert after == before + 1

    def test_refresh_reflects_filter(self, qtbot: QtBot, tmp_path: Path) -> None:
        vm, _ = _loaded_vm(tmp_path)
        model = _make_model(qtbot, vm)
        vm.set_filter("a")
        model.refresh()  # type: ignore[attr-defined]
        group_index = model.index(0, 0, QModelIndex())  # type: ignore[attr-defined]
        # Only signal 'a' survives the filter.
        assert model.rowCount(group_index) == 1  # type: ignore[attr-defined]
