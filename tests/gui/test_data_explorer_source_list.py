from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QListWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel


def _make_explorer(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    from valisync.gui.views.data_explorer_view import DataExplorerView

    view = DataExplorerView(AppViewModel(), sources_file=None)
    qtbot.addWidget(view)
    return view


def test_source_list_exists(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    assert isinstance(view.source_list, QListWidget)
    assert view.source_list.objectName() == "data_source_list"


def test_add_source_appears_in_list(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    d = tmp_path / "src_a"
    d.mkdir()
    view.add_source(d)
    labels = [view.source_list.item(i).text() for i in range(view.source_list.count())]
    assert str(d) in labels


def test_selecting_source_roots_tree(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    d = tmp_path / "src_b"
    d.mkdir()
    view.add_source(d)
    row = next(
        i
        for i in range(view.source_list.count())
        if view.source_list.item(i).text() == str(d)
    )
    view.source_list.setCurrentRow(row)
    rooted = Path(view.fs_model.filePath(view.tree.rootIndex()))
    assert rooted == d


def test_remove_acts_on_selected_source(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    d = tmp_path / "src_c"
    d.mkdir()
    view.add_source(d)
    view.source_list.setCurrentRow(0)
    view._on_remove_source_clicked()
    assert str(d) not in view.sources()


def test_remove_without_selection_gives_feedback(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    view.source_list.setCurrentRow(-1)  # no selection
    view._on_remove_source_clicked()  # must not raise; shows a status message
    assert view.statusBar().currentMessage() != ""
