from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _mw(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    mw = MainWindow(AppViewModel())
    mw.recent_files = mw.recent_files.__class__(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(mw)
    return mw


def test_open_file_dialog_cancel_does_not_load(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    mw = _mw(qtbot, tmp_path)
    called: list[str] = []
    monkeypatch.setattr(mw, "_load_file", lambda p: called.append(str(p)))
    # ダイアログがキャンセル (空文字) を返す
    monkeypatch.setattr(
        "valisync.gui.views.main_window.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
    mw.open_file()
    assert called == []


def test_open_file_dialog_selection_loads(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    mw = _mw(qtbot, tmp_path)
    called: list[str] = []
    monkeypatch.setattr(mw, "_load_file", lambda p: called.append(str(p)))
    monkeypatch.setattr(
        "valisync.gui.views.main_window.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "run.mf4"), "")),
    )
    mw.open_file()
    assert called == [str(tmp_path / "run.mf4")]


def test_loaded_records_full_resolvable_path_in_recent(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    mw = _mw(qtbot, tmp_path)
    full = tmp_path / "sub" / "run.mf4"  # has a directory component
    # display message uses source_name (basename); Recent must use the full path
    monkeypatch.setattr(mw.app_vm.session, "source_name", lambda k: full.name)

    class _Outcome:
        key = "mf4_1"
        diagnostics = ()

    mw._on_loaded(_Outcome(), source_path=full)  # type: ignore[arg-type]
    items = mw.recent_files.items()
    assert str(full) in items  # full resolvable path stored
    assert full.name not in items  # NOT the bare basename (guards SH-01 regression)
