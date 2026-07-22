"""Layer C: 読み値ペインの縦スクロール (B6/UXG-17) を実 OS 入力/実表示で検証する。

readout-pane B6 は CursorReadout を QScrollArea 化し、行数がウィンドウの最小高さを
押し上げないよう minimumSizeHint を有界化した (spec §2.6)。この効果 —
ウィンドウを縦縮小しても診断ドックが圧潰されない・読み値側に縦スクロールバーが
出る・スクロール後も正しい行を実クリックできる — は実 QMainWindow のドック
レイアウト計算/実ペイントを経ないと確証できない
(memory gui_dock_toggle_width_change_needs_real_display_and_layout と同型の懸念:
dock まわりの高さ配分は offscreen では確認できずレイアウト依存)。

--realgui opt-in・実ディスプレイ+Windows 必須。

再利用: tests/realgui/test_collapsible_docks_realclick.py の `_shown_mw` 作法
(MainWindow を実ジオメトリで表示)・test_readout_pane_realclick.py の
`_widget_center_phys` 作法 (module-local 忠実コピー — cross-test-module import を
避ける確立済みの流儀)。
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui

_N_SIGNALS = 22  # 3行有界化の閾値 (3) を大きく超え、縦オーバーフローを確実に誘発する


def _session_with_n_signals(tmp_path: Path, n: int):  # type: ignore[no-untyped-def]
    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session

    csv_path = tmp_path / "wide.csv"
    header = "t," + ",".join(f"sig{i:02d}" for i in range(n))
    lines = [header]
    for i in range(30):
        row = [f"{i * 0.1:.3f}"] + [str(float((i + j) % 10)) for j in range(n)]
        lines.append(",".join(row))
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    session = Session()
    session.load(
        csv_path,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=n,
            has_header=True,
        ),
    )
    return session


def _shown_mw_with_signals(qtbot: QtBot, tmp_path: Path, n: int = _N_SIGNALS):  # type: ignore[no-untyped-def]
    """MainWindow を実ジオメトリで表示し、1パネル1軸に n 信号+A カーソルを設置する
    (readout が global モードで n 行になる)。戻り値は (mw, panel_view)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    session = _session_with_n_signals(tmp_path, n)
    app_vm = AppViewModel(session)
    mw = MainWindow(app_vm)
    qtbot.addWidget(mw)
    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    mw.showNormal()
    ag = QApplication.primaryScreen().availableGeometry()
    mw.setGeometry(
        ag.x() + 40,
        ag.y() + 40,
        min(1100, ag.width() - 80),
        min(800, ag.height() - 80),
    )
    mw.raise_()
    mw.activateWindow()
    qtbot.waitExposed(mw)
    qtbot.waitUntil(lambda: not mw.isMaximized() and mw.width() > 800, timeout=3000)
    QApplication.processEvents()

    # Welcome -> GraphArea 切替 (production は open_file 経路で立てるフラグを
    # 直接立てる — このテストは open_file の CSV ダイアログ経路を通らない)。
    mw._workbench_started = True
    mw._update_central()

    panel_vm = mw.graph_area_vm.panels(0)[0]
    keys = sorted(s.name for s in session.signals())
    for k in keys[:n]:
        panel_vm.add_signal(k)
    panel_vm.x_range = panel_vm.x_range or (0.0, 1.0)
    panel_vm.toggle_main_cursor(True)
    for _ in range(5):
        QApplication.processEvents()

    panel_view = mw.graph_area_view.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    return mw, panel_view


def _real_click(x: int, y: int) -> None:
    from PySide6.QtWidgets import QApplication

    at(x, y, LDOWN)
    QApplication.processEvents()
    at(x, y, LUP)
    for _ in range(6):
        QApplication.processEvents()


def _widget_center_phys(view, w) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """物理スクリーン中心座標(w は view と同じトップレベルウィンドウ内の子ウィジェット)。"""
    from PySide6.QtCore import QPoint

    dpr = view.devicePixelRatioF()
    gp = w.mapToGlobal(QPoint(w.width() // 2, w.height() // 2))
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_shrink_window_keeps_diagnostics_dock_and_readout_scrolls(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """22行シード → ウィンドウを縦縮小 → (a) 診断ドックが圧潰されない
    (b) 読み値に縦スクロールバーが出る (c) スクロール後の可視行を実クリック
    → 正しい曲線がハイライトされる (spec §4 Layer C・UXG-17 の受け入れ本体)。

    honest RED gate: minimumSizeHint override を削って旧 (行数比例) の高さへ
    戻すと、ウィンドウが target_h まで縮まなくなるか、縮んだ場合は診断ドックが
    圧潰される (readout の巨大な最小高さが QMainWindow のドックレイアウトへ
    伝播するため — memory gui_dock_toggle_width_change_needs_real_display_and_layout
    と同型)。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    mw, panel_view = _shown_mw_with_signals(qtbot, tmp_path)
    readout = mw.graph_area_view.readout_pane
    qtbot.waitUntil(lambda: len(readout.row_texts()) == _N_SIGNALS, timeout=3000)

    diag_h_before = mw.diagnostics_dock.height()
    assert diag_h_before > 0, "setup: diagnostics_dock が既に高さ0"

    # --- ウィンドウを縦縮小 (readout が行数分の高さを要求していれば診断ドックが
    # 圧潰されるはずの操作) ---
    ag = QApplication.primaryScreen().availableGeometry()
    target_h = min(560, ag.height() - 80)
    mw.resize(mw.width(), target_h)
    for _ in range(10):
        QApplication.processEvents()
    qtbot.wait(80)
    for _ in range(5):
        QApplication.processEvents()

    diag_h_after = mw.diagnostics_dock.height()
    sb = readout._scroll.verticalScrollBar()
    shot_shrunk = tmp_path / "readout_scroll_shrunk.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_shrunk))

    print(
        f"[readout-scroll] target_h={target_h} actual_h={mw.height()} "
        f"diag_before={diag_h_before} diag_after={diag_h_after} "
        f"scroll_visible={sb.isVisible()} scroll_max={sb.maximum()}"
    )

    assert mw.height() <= target_h + 40, (
        f"ウィンドウが要求どおり縮小できていない (height={mw.height()}, "
        f"target={target_h}) — readout の行数分の高さがウィンドウ最小高を"
        f"押し上げている可能性 (UXG-17 未解消)。screenshot: {shot_shrunk}"
    )
    assert diag_h_after > diag_h_before * 0.5, (
        f"縮小で診断ドックが圧潰された (before={diag_h_before}, "
        f"after={diag_h_after})。screenshot: {shot_shrunk}"
    )
    assert sb.isVisible(), (
        f"読み値ペインに縦スクロールバーが出ていない。screenshot: {shot_shrunk}"
    )

    # --- スクロール後、可視行 (最終行) を実クリック → 正しい曲線がハイライトされる ---
    target_entry_id = panel_view.curve_keys()[-1]
    sb.setValue(sb.maximum())
    for _ in range(5):
        QApplication.processEvents()

    last_label = readout._value_labels[-1][0]
    phys = _widget_center_phys(mw, last_label)
    _real_click(*phys)

    shot_clicked = tmp_path / "readout_scroll_clicked.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_clicked))

    assert panel_view.active_curve_id() == target_entry_id, (
        "スクロール後の可視行(最終行)実クリックが誤った曲線をハイライトした "
        f"(expected entry_id={target_entry_id!r}, "
        f"got {panel_view.active_curve_id()!r}). screenshot: {shot_clicked}"
    )
