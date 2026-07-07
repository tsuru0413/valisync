from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
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


def test_recent_row_emits_its_path(qtbot: QtBot, tmp_path: Path) -> None:
    real = tmp_path / "run.mf4"
    real.write_bytes(b"x")
    rf = _recent(tmp_path)
    rf.add(str(real))
    view = WelcomeView(rf)
    qtbot.addWidget(view)
    view.refresh()
    got: list[object] = []
    view.open_requested.connect(got.append)
    view._emit_recent(str(real))  # 行クリックの内部ハンドラを直叩き (Layer A)
    assert got == [str(real)]
