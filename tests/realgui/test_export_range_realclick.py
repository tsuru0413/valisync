# ruff: noqa: RUF002, RUF003
"""Layer C (realgui, T-C2) — 範囲付きエクスポートの実ジャーニー (F-0/UX-28・design spec §2)。

実 MainWindow に実信号をプロットし、2 カーソル (A=2.0s / B=6.0s) を設置したうえで、
実 ExportCsvDialog の [カーソル A–B] ラジオを実 OS クリックで選択 -> 実 OK クリックで
確定 -> 実ファイルへ書き出し -> 書き出したファイルを実際に読み直して行の時間範囲が
A–B の閉区間に収まることを検証する。[全期間] との行数差も確認する。

あわせて I2 (オフセット座標系ガード) の実挙動を1点実証する: 選択信号に非ゼロオフセット
を与えると [現在の表示範囲]/[カーソル A–B] ラジオが実際に disabled 表示になる。

headless (Layer A: test_csv_exporter.py の time_start/time_end・Layer B:
test_export_csv_dialog.py のラジオ/ガード配線) は境界値・型・シグナル配線を直接検証
済み。本テストは「実ラジオクリック -> 実 OK クリック -> 実ディスクファイル」という
実経路全体が一貫していることの証明であり、ロジック単体の再検証ではない。

エビデンス: design_export/evidence_f0/ へ保存。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui

_EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "design_export" / "evidence_f0"

_N = 40
_DT = 0.25  # power-of-two step -> exact binary float, no rounding at boundaries
_CURSOR_A = 2.0
_CURSOR_B = 6.0


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int, dt: float = 0.02) -> None:
    for _ in range(n):
        _pump(dt)


def _write_csv(path: Path) -> None:
    lines = ["t,VehSpd,EngineSpeed"]
    for i in range(_N):
        t = i * _DT
        lines.append(f"{t:.3f},{10.0 + i:.2f},{800.0 + i:.2f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _phys_center(widget, local_center):  # type: ignore[no-untyped-def]
    gp = widget.mapToGlobal(local_center)
    dpr = widget.devicePixelRatioF()
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _real_click_widget(widget) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QPoint

    x, y = _phys_center(widget, QPoint(widget.width() // 2, widget.height() // 2))
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    _pump_n(4)


def _read_timestamps(path: Path) -> list[float]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].startswith("timestamp,"), f"想定外のヘッダ: {lines[:1]}"
    return [float(line.split(",", 1)[0]) for line in lines[1:] if line]


def test_export_cursor_range_realclick_writes_bounded_file(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.export_csv_dialog import ExportCsvDialog
    from valisync.gui.views.main_window import MainWindow

    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    csv = tmp_path / "range.csv"
    _write_csv(csv)
    fmt = FormatDefinition(
        name="range_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    session = window.app_vm.session
    outcome = session.load(csv, fmt)
    window._on_loaded(outcome)

    vehspd = next(
        s.name for s in session.group_signals(outcome.key) if s.name.endswith("VehSpd")
    )
    engspeed = next(
        s.name
        for s in session.group_signals(outcome.key)
        if s.name.endswith("EngineSpeed")
    )

    vm = window.graph_area_vm
    panel_vm = vm.panels(vm.active_tab_index)[vm.active_panel_index()]
    panel_vm.add_signal(vehspd)
    panel_vm.add_signal(engspeed)
    panel_vm.set_cursor(_CURSOR_A)
    panel_vm.set_cursor_b(_CURSOR_B)

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(
        screen.x() + 60,
        screen.y() + 60,
        min(1120, screen.width() - 120),
        min(760, screen.height() - 120),
    )
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    _pump_n(4)

    panel = window.graph_area_vm.active_panel()
    cursor_state = window.graph_area_vm.active_tab().cursor_state
    assert cursor_state.cursor_t == _CURSOR_A
    assert cursor_state.cursor_t_b == _CURSOR_B

    def _open_dialog(initial: set[str]):  # type: ignore[no-untyped-def]
        dlg = ExportCsvDialog(
            window.app_vm,
            initial,
            window,
            x_range=panel.x_range,
            cursor_a=cursor_state.cursor_t,
            cursor_b=cursor_state.cursor_t_b,
            offset_for=panel.offset_for,
        )
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dlg.move(screen.x() + 80, screen.y() + 80)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        qtbot.waitExposed(dlg)
        _pump_n(3)
        return dlg

    initial = {vehspd, engspeed}

    # ── (1) [全期間] (既定) を実 OK クリックで確定 ─────────────────────────
    dlg_all = _open_dialog(initial)
    out_all = tmp_path / "export_all.csv"
    dlg_all._save_path_provider = lambda: str(out_all)  # モーダル QFileDialog 回避
    ok_all = dlg_all._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_all.isEnabled()
    _real_click_widget(ok_all)
    qtbot.waitUntil(lambda: dlg_all._result is not None, timeout=2000)
    req_all = dlg_all._result
    assert req_all is not None
    assert req_all.options.time_start is None and req_all.options.time_end is None
    session.export_csv(
        req_all.signals,
        req_all.output_path,
        req_all.use_unified_timeline,
        req_all.options,
    )
    ts_all = _read_timestamps(out_all)
    assert len(ts_all) == _N, f"全期間エクスポートの行数が想定外: {len(ts_all)}"

    # ── (2) [カーソル A–B] を実クリックで選択 -> 実 OK クリックで確定 ──────
    dlg_cur = _open_dialog(initial)
    assert dlg_cur._range_cursor.isEnabled(), "A/B 両設置済みなのに disabled"
    _real_click_widget(dlg_cur._range_cursor)
    qtbot.waitUntil(lambda: dlg_cur._range_cursor.isChecked(), timeout=2000)
    assert dlg_cur._range_cursor.isChecked(), (
        "実クリックでカーソル A-B ラジオが選択されない"
    )
    assert not dlg_cur._range_all.isChecked(), (
        "排他が効いておらず [全期間] が残っている"
    )

    shot_dialog = _EVIDENCE_DIR / "03_export_dialog_cursor_range.png"
    dlg_cur.grab().save(str(shot_dialog))

    out_cursor = tmp_path / "export_cursor.csv"
    dlg_cur._save_path_provider = lambda: str(out_cursor)
    ok_cur = dlg_cur._buttons.button(QDialogButtonBox.StandardButton.Ok)
    _real_click_widget(ok_cur)
    qtbot.waitUntil(lambda: dlg_cur._result is not None, timeout=2000)
    req_cur = dlg_cur._result
    assert req_cur is not None
    assert req_cur.options.time_start == _CURSOR_A
    assert req_cur.options.time_end == _CURSOR_B
    session.export_csv(
        req_cur.signals,
        req_cur.output_path,
        req_cur.use_unified_timeline,
        req_cur.options,
    )

    # ── 実出力ファイルの実読み直し: 行の時間範囲が A-B 閉区間に収まる ─────
    ts_cursor = _read_timestamps(out_cursor)
    assert ts_cursor, "カーソル範囲エクスポートが空 (書き出しが機能していない)"
    assert all(_CURSOR_A <= t <= _CURSOR_B for t in ts_cursor), (
        f"出力行の時間範囲が A-B 閉区間をはみ出す: min={min(ts_cursor)} "
        f"max={max(ts_cursor)} (expected [{_CURSOR_A}, {_CURSOR_B}])"
    )
    expected_n = round((_CURSOR_B - _CURSOR_A) / _DT) + 1
    assert len(ts_cursor) == expected_n, (
        f"カーソル範囲エクスポートの行数が想定外: got={len(ts_cursor)} "
        f"expected={expected_n}. 全期間との差={len(ts_all) - len(ts_cursor)}"
    )
    assert len(ts_cursor) < len(ts_all), "範囲指定が全期間より行数を削減していない"

    # ── (3) I2: 選択信号に非ゼロオフセットがあると表示由来2ラジオが実際に disabled ──
    window.app_vm.apply_offset(engspeed, 1.0, "signal")
    assert panel.offset_for(engspeed) == 1.0, "オフセット適用がパネルへ伝播していない"

    dlg_offset = _open_dialog(initial)  # engspeed が checked 集合に含まれる
    shot_offset = _EVIDENCE_DIR / "04_export_dialog_offset_guard.png"
    dlg_offset.grab().save(str(shot_offset))
    assert not dlg_offset._range_visible.isEnabled(), (
        f"オフセット選択時に [現在の表示範囲] が disabled になっていない。"
        f" screenshot: {shot_offset}"
    )
    assert not dlg_offset._range_cursor.isEnabled(), (
        f"オフセット選択時に [カーソル A-B] が disabled になっていない。"
        f" screenshot: {shot_offset}"
    )
    assert dlg_offset._range_visible.toolTip() == S.EXPORT_RANGE_OFFSET_TOOLTIP
    assert dlg_offset._range_cursor.toolTip() == S.EXPORT_RANGE_OFFSET_TOOLTIP
    dlg_offset.close()

    window.app_vm.reset_offset(engspeed, "signal")
    window.close()
