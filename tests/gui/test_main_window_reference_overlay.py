"""Layer B: MainWindow integration for the E-2b same-name overlay handler.

Drives the ACTUAL wiring (FileBrowserView.overlay_reference_requested ->
MainWindow._overlay_reference_signals) end to end: the pure-logic partition of
skip categories is already covered exhaustively at Layer A
(tests/gui/test_reference_overlay.py) — this file only proves the handler
resolves the right panel/reference/session and renders the status message.
"""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _mf4_with_speed(path: Path, unit: str = "km/h") -> Path:
    return write_mdf4(
        path,
        [
            {
                "name": "speed",
                "timestamps": [0.0, 1.0, 2.0],
                "values": [1.0, 2.0, 3.0],
                "bus_type": CAN,
                "unit": unit,
            }
        ],
    )


def _speed_key(mw: MainWindow, group_key: str) -> str:
    return next(
        s.name
        for s in mw.app_vm.session.group_signals(group_key)
        if s.name.endswith("::speed")
    )


def test_overlay_request_adds_matching_signal_to_active_panel(
    qtbot: QtBot, tmp_path: Path
) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)

    key1 = mw.app_vm.request_load(_mf4_with_speed(tmp_path / "a.mf4"))
    key2 = mw.app_vm.request_load(_mf4_with_speed(tmp_path / "b.mf4"))
    assert mw.app_vm.reference_file_key == key1

    ref_speed = _speed_key(mw, key1)
    tgt_speed = _speed_key(mw, key2)

    vm = mw.graph_area_vm
    panel = vm.panels(vm.active_tab_index)[vm.active_panel_index()]
    panel.add_signal(ref_speed)

    # Drive the real signal wiring (not the handler method directly).
    mw.file_browser_view.overlay_reference_requested.emit(key2)

    entries = {(sk, ax) for _eid, sk, ax in panel.plotted_entries()}
    assert entries == {(ref_speed, 0), (tgt_speed, 0)}
    assert "b.mf4" in mw.status_message()
    assert "1 件重ねました" in mw.status_message()


def test_overlay_request_with_no_reference_entries_shows_dedicated_message(
    qtbot: QtBot, tmp_path: Path
) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)

    mw.app_vm.request_load(_mf4_with_speed(tmp_path / "a.mf4"))
    key2 = mw.app_vm.request_load(_mf4_with_speed(tmp_path / "b.mf4"))
    # Nothing plotted on the active panel at all.

    mw.file_browser_view.overlay_reference_requested.emit(key2)

    assert mw.status_message() == "基準の信号がプロットされていません"


def test_overlay_request_unit_mismatch_is_reported_in_summary(
    qtbot: QtBot, tmp_path: Path
) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)

    key1 = mw.app_vm.request_load(_mf4_with_speed(tmp_path / "a.mf4", unit="km/h"))
    key2 = mw.app_vm.request_load(_mf4_with_speed(tmp_path / "b.mf4", unit="mph"))

    vm = mw.graph_area_vm
    panel = vm.panels(vm.active_tab_index)[vm.active_panel_index()]
    panel.add_signal(_speed_key(mw, key1))

    mw.file_browser_view.overlay_reference_requested.emit(key2)

    assert mw.status_message() == "b.mf4 の同名信号を 0 件重ねました（単位不一致 1）"
