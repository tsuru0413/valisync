"""Shell chrome tests — shortcuts and menu mnemonics (SH-05)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence
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


def test_open_folder_has_shortcut(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert mw.shell_actions.action("open_folder").shortcut() == QKeySequence(
        "Ctrl+Shift+O"
    )


def test_exit_has_ctrl_q_shortcut(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    # StandardKey.Quit は Windows で押せない Key_Exit(メディアキー)に解決するため
    # 明示 Ctrl+Q を検証。toString で「実効ショートカットが押下可能な組合せ」を確認
    # する(Key_Exit なら "Ctrl+Q" を含まず落ちる honest なアサート)。
    assert "Ctrl+Q" in mw.action_exit.shortcut().toString()


def test_menu_titles_have_mnemonics(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    titles = [a.text() for a in mw.menuBar().actions()]
    assert "ファイル(&F)" in titles
    assert "表示(&V)" in titles
    assert "ヘルプ(&H)" in titles


def test_toolbar_has_dock_toggles(qtbot: QtBot, tmp_path: Path) -> None:
    """D-3/UX-45: toggleViewAction ではなく三態カスタム QAction (_dock_actions)
    がツールバーに掲載される (docs/superpowers/specs/2026-07-22-d3-tristate-
    icons-design.md §2.3 — toggleViewAction はどの面にも掲載しない)。"""
    from PySide6.QtWidgets import QToolBar

    mw = _mw(qtbot, tmp_path)
    toolbar = mw.findChild(QToolBar, "main_toolbar")
    assert toolbar is not None
    toolbar_actions = toolbar.actions()
    assert mw._dock_actions["file_dock"] in toolbar_actions
    assert mw._dock_actions["channel_dock"] in toolbar_actions
    assert mw._dock_actions["diagnostics_dock"] in toolbar_actions


def test_toolbar_toggle_hides_dock(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    mw.show()
    qtbot.waitExposed(mw)
    toggle = mw._dock_actions["file_dock"]  # ツールバーボタンと同一 action
    assert mw.file_dock.isVisible()
    toggle.trigger()
    assert not mw.file_dock.isVisible()


def test_reset_layout_restores_default_dock_area(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtCore import Qt

    mw = _mw(qtbot, tmp_path)
    # 構築直後の area は _restore_state(実レジストリ)依存なのでアサートしない。
    mw.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, mw.file_dock)
    assert mw.dockWidgetArea(mw.file_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    mw._reset_layout()
    assert mw.dockWidgetArea(mw.file_dock) == Qt.DockWidgetArea.RightDockWidgetArea


def test_reset_layout_action_in_view_menu(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert mw.action_reset_layout.text() == "レイアウトをリセット(&R)"


def test_data_explorer_action_has_icon_and_tooltip(
    qtbot: QtBot, tmp_path: Path
) -> None:
    mw = _mw(qtbot, tmp_path)
    assert not mw.action_data_explorer.icon().isNull()
    assert mw.action_data_explorer.toolTip() != ""


def test_about_text_includes_version(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    text = mw._about_text()
    assert text.startswith("ValiSync v")
    assert "—" in text  # "ValiSync v{ver} — ..."


def test_about_text_shows_version_unknown_when_lookup_fails(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-37: v{ver} の合成事故 ("v不明" 等) を分岐で回避する。"""
    import importlib.metadata

    def _raise(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _raise)  # type: ignore[attr-defined]
    mw = _mw(qtbot, tmp_path)
    text = mw._about_text()
    assert "バージョン不明" in text
    assert "v不明" not in text
    assert not text.startswith("ValiSync v")
