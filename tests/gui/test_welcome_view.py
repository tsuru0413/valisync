from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.recent_files import RecentFiles
from valisync.gui.views.welcome_view import WelcomeView


def _recent(tmp_path: Path) -> RecentFiles:
    return RecentFiles(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )


def test_cta_emits_open_requested_none(qtbot: QtBot, tmp_path: Path) -> None:
    view = WelcomeView(_recent(tmp_path))
    qtbot.addWidget(view)
    got: list[object] = []
    view.open_requested.connect(got.append)
    view.findChild(type(view.cta), "welcome_open_cta").click()
    assert got == [None]


def test_recent_row_click_emits_its_path(qtbot: QtBot, tmp_path: Path) -> None:
    # Seed 2 rows so a late-binding closure bug (every row emits the last path)
    # is caught: existing() is newest-first, so row 0 must emit the NEWEST path,
    # not the final loop value.
    a = tmp_path / "a.mf4"
    a.write_bytes(b"x")
    b = tmp_path / "b.mf4"
    b.write_bytes(b"x")
    rf = _recent(tmp_path)
    rf.add(str(a))
    rf.add(str(b))  # newest -> row 0
    view = WelcomeView(rf)
    qtbot.addWidget(view)
    view.refresh()
    assert view._recent_box.count() == 2  # rebuild produced both rows
    got: list[object] = []
    view.open_requested.connect(got.append)
    row0 = view._recent_box.itemAt(0).widget()
    assert isinstance(row0, QPushButton)
    row0.click()  # real button click -> per-row lambda -> _emit_recent
    assert got == [str(b)]  # row 0 = newest = b; late-binding bug would emit a


def test_refresh_with_no_recent_files_shows_no_rows(
    qtbot: QtBot, tmp_path: Path
) -> None:
    view = WelcomeView(_recent(tmp_path))  # empty MRU
    qtbot.addWidget(view)
    view.refresh()
    assert view._recent_box.count() == 0
