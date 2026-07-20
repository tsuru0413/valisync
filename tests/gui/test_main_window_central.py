from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _mw(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    mw = MainWindow(AppViewModel())
    # Recent/永続化をテスト分離
    mw.recent_files = mw.recent_files.__class__(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(mw)
    return mw


def _csv_format() -> FormatDefinition:
    return FormatDefinition(
        name="test_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )


def _write_csv(dir_path: Path) -> Path:
    csv_file = dir_path / "data.csv"
    csv_file.write_text("t,speed\n0.0,10.0\n1.0,20.0\n2.0,30.0\n")
    return csv_file


def test_starts_on_welcome(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert mw.showing_welcome() is True
    # central_stack は CentralWithRails (辺レール枠) に包まれ中央に据わる
    # (edge-aware-dock-collapse Task 1)。旧「centralWidget() is central_stack」を
    # 「stack が central widget の子」へ更新。
    assert mw.central_stack.parentWidget() is mw.centralWidget()


def test_first_load_swaps_to_graph_and_unload_keeps_it(
    qtbot: QtBot, tmp_path: Path
) -> None:
    mw = _mw(qtbot, tmp_path)
    # 初回ロードを模擬 (app_vm の loaded 通知が届くと workbench へスワップ)。
    # unload_file は Session.remove_group を経由するため、register_loaded だけの
    # 偽キーでは KeyError になる — 実際に (軽量) ロードして本物のグループを作る。
    key = mw.app_vm.request_load(_write_csv(tmp_path), _csv_format())
    assert mw.showing_welcome() is False
    # 最後の1件アンロードでも Welcome へ戻さない
    mw.app_vm.unload_file(key)
    assert mw.showing_welcome() is False
