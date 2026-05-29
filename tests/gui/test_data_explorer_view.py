"""Tests for DataExplorerView — Task 7.3.

The Data_Explorer is a standalone QMainWindow with a filesystem tree.  It
registers data-source folders (persisted as JSON), and activating a file
forwards it to AppViewModel.request_load.  Assertions go through the
AppViewModel's observable state and the persistence round-trip, never pixels.

MDF4 is used for the load path because it needs no FormatDefinition (CSV
would require a format picker, which is out of MVP scope here).

TDD: written before the view exists; all must FAIL first.
"""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.gui.persistence import data_sources
from valisync.gui.viewmodels.app_viewmodel import AppViewModel

# ─── Helpers ────────────────────────────────────────────────────────────────


def _make_explorer(
    qtbot: QtBot, app_vm: AppViewModel, sources_file: Path | None = None
) -> object:
    from valisync.gui.views.data_explorer_view import DataExplorerView

    view = DataExplorerView(app_vm, sources_file=sources_file)
    qtbot.addWidget(view)
    return view


def _make_mf4(tmp_path: Path, name: str = "log.mf4") -> Path:
    return write_mdf4(
        tmp_path / name,
        [
            {
                "name": "speed",
                "timestamps": [0.0, 0.1, 0.2],
                "values": [1.0, 2.0, 3.0],
                "bus_type": CAN,
            }
        ],
    )


# ─── Source registration ──────────────────────────────────────────────────────


class TestSourceRegistration:
    def test_add_source_registers_in_app_vm(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm)

        view.add_source(tmp_path)  # type: ignore[attr-defined]

        assert str(tmp_path) in view.sources()  # type: ignore[attr-defined]
        assert str(tmp_path) in app_vm.inspect()["data_sources"]

    def test_add_source_sets_tree_root(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm)

        view.add_source(tmp_path)  # type: ignore[attr-defined]

        root_index = view.tree.rootIndex()  # type: ignore[attr-defined]
        root_path = view.fs_model.filePath(root_index)  # type: ignore[attr-defined]
        assert Path(root_path) == tmp_path

    def test_remove_source_unregisters(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm)

        view.add_source(tmp_path)  # type: ignore[attr-defined]
        view.remove_source(tmp_path)  # type: ignore[attr-defined]

        assert str(tmp_path) not in view.sources()  # type: ignore[attr-defined]


# ─── Persistence round-trip ────────────────────────────────────────────────────


class TestPersistence:
    def test_add_source_persists_to_file(self, qtbot: QtBot, tmp_path: Path) -> None:
        sources_file = tmp_path / "sources.json"
        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm, sources_file=sources_file)
        folder = tmp_path / "logs"
        folder.mkdir()

        view.add_source(folder)  # type: ignore[attr-defined]

        assert str(folder) in data_sources.load(sources_file)

    def test_sources_restored_from_file_on_init(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        sources_file = tmp_path / "sources.json"
        folder = tmp_path / "logs"
        folder.mkdir()
        data_sources.save([folder], sources_file)

        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm, sources_file=sources_file)

        assert str(folder) in view.sources()  # type: ignore[attr-defined]
        assert str(folder) in app_vm.inspect()["data_sources"]

    def test_remove_source_persists(self, qtbot: QtBot, tmp_path: Path) -> None:
        sources_file = tmp_path / "sources.json"
        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm, sources_file=sources_file)
        folder = tmp_path / "logs"
        folder.mkdir()

        view.add_source(folder)  # type: ignore[attr-defined]
        view.remove_source(folder)  # type: ignore[attr-defined]

        assert str(folder) not in data_sources.load(sources_file)


# ─── File activation → request_load ─────────────────────────────────────────--


class TestActivation:
    def test_load_path_invokes_request_load(self, qtbot: QtBot, tmp_path: Path) -> None:
        mf4 = _make_mf4(tmp_path)
        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm)

        view.load_path(mf4)  # type: ignore[attr-defined]

        assert len(app_vm.inspect()["loaded_keys"]) == 1
        assert any(s.name.endswith("::speed") for s in app_vm.signals())

    def test_double_click_handler_loads_file(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        mf4 = _make_mf4(tmp_path)
        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm)

        # QFileSystemModel.index(path) resolves an existing path synchronously.
        index = view.fs_model.index(str(mf4))  # type: ignore[attr-defined]
        view._on_activated(index)  # type: ignore[attr-defined]

        assert len(app_vm.inspect()["loaded_keys"]) == 1

    def test_activating_directory_does_not_load(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        subdir = tmp_path / "sub"
        subdir.mkdir()
        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm)

        index = view.fs_model.index(str(subdir))  # type: ignore[attr-defined]
        view._on_activated(index)  # type: ignore[attr-defined]

        # Directories are navigated, not loaded.
        assert app_vm.inspect()["loaded_keys"] == []


# ─── Window identity ──────────────────────────────────────────────────────────


class TestWindow:
    def test_is_standalone_window(self, qtbot: QtBot) -> None:
        from PySide6.QtWidgets import QMainWindow

        app_vm = AppViewModel()
        view = _make_explorer(qtbot, app_vm)
        assert isinstance(view, QMainWindow)
