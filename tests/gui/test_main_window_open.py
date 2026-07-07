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


def test_loaded_updates_recent(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    p = tmp_path / "run.mf4"
    p.write_bytes(b"x")

    # _on_loaded は LoadOutcome を受ける。source_name をスタブし、Recent 追加のみ検証。
    class _Outcome:
        key = "mf4_1"
        diagnostics = ()

    mw.app_vm.session.source_name = lambda k: str(p)  # type: ignore[assignment]
    mw._on_loaded(_Outcome())  # type: ignore[arg-type]
    assert str(p) in mw.recent_files.items()
