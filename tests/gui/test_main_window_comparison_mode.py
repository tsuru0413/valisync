"""Layer B: Analyze メニュー「比較モード」トグルの MainWindow 同期 (Task 3).

比較モード切替 spec (docs/superpowers/specs/2026-07-23-comparison-mode-toggle-design.md)
§7 T-B1/T-B2。checkstate は生フラグ (`app_vm.comparison_enabled`) を掴み点とし、
`is_comparison_mode()` (フラグ AND ≥2 ファイル述語) との取り違えを sabotage で
固定する意図を持つ。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _mf4_with_speed(path: Path) -> Path:
    return write_mdf4(
        path,
        [
            {
                "name": "speed",
                "timestamps": [0.0, 1.0, 2.0],
                "values": [1.0, 2.0, 3.0],
                "bus_type": CAN,
                "unit": "km/h",
            }
        ],
    )


@pytest.fixture
def main_window_two_files(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.app_vm.request_load(_mf4_with_speed(tmp_path / "a.mf4"))
    mw.app_vm.request_load(_mf4_with_speed(tmp_path / "b.mf4"))
    return mw


@pytest.fixture
def main_window_one_file(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.app_vm.request_load(_mf4_with_speed(tmp_path / "a.mf4"))
    return mw


# ─── T-B1: メニュー同期 + 生フラグ厳守 ──────────────────────────────────────


def test_comparison_action_reflects_raw_flag_and_enabled_on_count(
    main_window_two_files: MainWindow,
) -> None:
    mw = main_window_two_files
    mw._sync_analysis_actions()
    act = mw._comparison_mode_action
    assert act.isEnabled() is True  # 2 files
    assert act.isChecked() is False  # default OFF
    act.trigger()
    assert mw.app_vm.comparison_enabled is True
    assert act.isChecked() is True


def test_comparison_action_checkstate_uses_raw_flag_not_predicate(
    main_window_one_file: MainWindow,
) -> None:
    """sabotage 対象: checkstate に is_comparison_mode() (AND ≥2 述語) を使うと
    1 ファイル + フラグ ON でも checked=False になり本テストが RED 化する。"""
    mw = main_window_one_file
    mw.app_vm.set_comparison_mode(True)  # raw flag True, but 1 file
    mw._sync_analysis_actions()
    assert mw._comparison_mode_action.isChecked() is True
    assert mw._comparison_mode_action.isEnabled() is False


# ─── T-B2: <2 ファイル無効 + checked 保持 (spec §2 M6 の意図的到達状態) ──────


def test_comparison_action_disabled_and_checked_after_unload_below_two(
    main_window_one_file: MainWindow,
) -> None:
    mw = main_window_one_file
    mw._sync_analysis_actions()
    assert mw._comparison_mode_action.isEnabled() is False


def test_comparison_action_stays_checked_but_disabled_after_unload_to_one(
    main_window_two_files: MainWindow,
) -> None:
    """2 ファイル・ON → 1 ファイルへ unload → disabled かつ checked=保持
    (「✓グレーアウト」— 設定は保持・2 つ以上で再適用の意図的決定・spec §2 M6)。"""
    mw = main_window_two_files
    mw._sync_analysis_actions()
    mw._comparison_mode_action.trigger()
    assert mw.app_vm.comparison_enabled is True

    key = mw.app_vm.loaded_file_keys[0]
    mw.app_vm.unload_file(key)
    mw._sync_analysis_actions()

    assert mw._comparison_mode_action.isEnabled() is False
    assert mw._comparison_mode_action.isChecked() is True


# ─── M8: 基準ファイルのステータス開示 ────────────────────────────────────────


def test_toggle_on_shows_reference_file_status(
    main_window_two_files: MainWindow,
) -> None:
    mw = main_window_two_files
    mw._sync_analysis_actions()
    mw._comparison_mode_action.trigger()
    assert "a.mf4" in mw.status_message()
