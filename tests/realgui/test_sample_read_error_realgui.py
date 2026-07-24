"""Layer C: 遅延サンプル読み取り失敗でアプリが落ちないことを実 OS 入力で実証 (Task 7)。

honest layering (spec §Task 7): PySide6 は Qt スロット/仮想メソッド内の未処理
Python 例外を実イベントループでのみ ``sys.excepthook`` へルーティングする。headless
の直叩き/qtbot は例外をテストへ伝播させるだけで「実行時にプロセスが生存するか」を
再現しない (false-green) ため、app レベルフックの生存はここ (実 MainWindow + 実右
クリックメニュー) でしか証明できない。

シナリオ (両方向):
- 非発火側: 健全な信号を実右クリックメニューで別パネルへ追加 → 正常プロット
  (フックが正常フローを飲まない)。
- 発火側: 遅延読みが失敗する信号を実右クリックメニューでもう一方のパネルへ追加 →
  auto-fit が SampleReadError を投げ、app レベルフックが握って診断+ステータスに
  落とす。プロセスは生存し、健全パネルの曲線は描かれたまま。

実マウスドラッグは使わない (共有マシンでハング・memory gui_realgui_drag_qtimer_hang)。
追加は実クリック選択→実右クリックメニュー、である。
"""

from __future__ import annotations

import contextlib
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
)
from tests.realgui._realgui_input import key as key_input
from valisync.core.models import Signal, SignalGroup
from valisync.core.models.sample_source import SampleReadError
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui


class _FailingSource:
    """A SampleSource whose lazy value read always fails (network-drive drop等)."""

    is_materialized = False
    length = 3
    nbytes_if_materialized = 0

    def array(self) -> np.ndarray:
        raise SampleReadError(
            "信号「z_bad」のサンプル読み取りに失敗しました: I/O error"
        )


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int) -> None:
    for _ in range(n):
        _pump(0.02)


def _real_click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    _pump_n(4)


def _phys_center(w, local) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    gp = w.mapToGlobal(local)
    dpr = w.devicePixelRatioF()
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _shot(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    p = tmp_path / f"{name}.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(p))
    return p


def _panel_widget(window, tab: int, panel: int):  # type: ignore[no-untyped-def]
    return window.graph_area_view.tabs.widget(tab).widget(panel)


def _make_window_with_bad_and_healthy(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Build a real MainWindow whose active file has TWO scalar signals — one
    healthy (eager) and one whose lazy read fails — plus a 2nd panel.

    Both are scalar bases, so the channel-tree shows two top-level leaves. The
    file is registered directly (register_loaded + set_active_file) — the same
    GUI-thread registration/activation the load callback performs — bypassing
    the loader so a lazy-FAILING Signal (which no loader produces) is reachable.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    session = window.app_vm.session

    ts = np.linspace(0.0, 1.0, 20, dtype=np.float64)
    healthy = Signal(
        name="a_good",
        timestamps=ts,
        values=np.linspace(10.0, 30.0, 20).astype(np.float64),
        file_format="MDF4",
        bus_type="",
        source_file=str(tmp_path / "mix.mf4"),
    )
    bad = Signal(
        name="z_bad",
        timestamps=np.array([0.0, 0.5, 1.0], dtype=np.float64),
        values_source=_FailingSource(),  # type: ignore[arg-type]
        file_format="MDF4",
        bus_type="",
        source_file=str(tmp_path / "mix.mf4"),
    )
    key = session._groups.add(
        SignalGroup(
            signals=(healthy, bad),
            source_path=tmp_path / "mix.mf4",
            file_format="MDF4",
            loaded_at=datetime.now(),
        )
    )
    window.app_vm.register_loaded(key)
    window.app_vm.set_active_file(key)
    window.graph_area_vm.add_panel(0)  # 2 panels (new one auto-active)

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    w = min(1120, screen.width() - 120)
    h = min(760, screen.height() - 120)
    window.setGeometry(screen.x() + 60, screen.y() + 60, w, h)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    _pump_n(3)

    model = window.channel_browser_view.model
    qtbot.waitUntil(lambda: model.rowCount() >= 2, timeout=3000)
    # Map signal-name suffix → row-0 leaf key (both are top-level scalar leaves).
    keys_by_row: dict[int, str] = {}
    for row in range(model.rowCount()):
        k = model.signal_key_at(model.index(row, 0))
        if k is not None:
            keys_by_row[row] = k
    good_row = next(r for r, k in keys_by_row.items() if k.endswith("a_good"))
    bad_row = next(r for r, k in keys_by_row.items() if k.endswith("z_bad"))
    return window, good_row, bad_row, keys_by_row[good_row], keys_by_row[bad_row]


def _real_select_and_menu_add(window, row: int) -> None:  # type: ignore[no-untyped-def]
    """Real-click the tree row to select it, then real right-click and real-click
    the "Add to Active Panel" menu row (nested QMenu.exec — driven by singleShots).

    An ESC watchdog closes a stuck popup so a missed click fails on an assertion
    rather than hanging the shared machine.
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    tree = window.channel_browser_view.tree
    model = window.channel_browser_view.model
    idx = model.index(row, 0)
    rect = tree.visualRect(idx)
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    px, py = _phys_center(vp, local)
    _real_click(px, py)  # select the row → "Add to Active Panel" enabled

    loop = QEventLoop()

    def right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def click_item() -> None:
        menu = QApplication.activePopupWidget()
        if isinstance(menu, QMenu):
            act = next(
                (a for a in menu.actions() if a.text() == S.ACTION_ADD_TO_ACTIVE_PANEL),
                None,
            )
            if act is not None:
                gc = menu.mapToGlobal(menu.actionGeometry(act).center())
                dpr = menu.devicePixelRatioF()
                mx, my = round(gc.x() * dpr), round(gc.y() * dpr)
                at(mx, my, LDOWN)
                at(mx, my, LUP)
        loop.quit()

    def watchdog() -> None:
        if isinstance(QApplication.activePopupWidget(), QMenu):
            key_input(VK_ESCAPE)
        loop.quit()

    QTimer.singleShot(300, right_click)
    QTimer.singleShot(1000, click_item)
    QTimer.singleShot(1600, watchdog)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()


def test_sample_read_error_degrades_without_crash(qtbot: QtBot, tmp_path: Path) -> None:
    """健全信号は正常プロット・失敗信号は app フックで握って生存 (両方向・実 OS 入力)。"""
    skip_unless_real_display()

    window, good_row, bad_row, good_key, _bad_key = _make_window_with_bad_and_healthy(
        qtbot, tmp_path
    )
    vm = window.graph_area_vm

    # ── 非発火側: 健全信号をパネル2 (index 1) へ実追加 → 正常プロット ──
    vm.set_active_panel(0, 1)
    _pump_n(2)
    _real_select_and_menu_add(window, good_row)
    panel2 = _panel_widget(window, 0, 1)
    qtbot.waitUntil(
        lambda: good_key in vm.panels(0)[1].plotted_signal_keys(), timeout=3000
    )
    shot_ok = _shot(tmp_path, "01_healthy_plotted")
    assert good_key in panel2.signal_keys_drawn(), (
        f"健全信号がパネル2に実描画されない (フックが正常フローを飲んだ疑い)。{shot_ok}"
    )
    # 健全追加では診断は出ない (フックは SampleReadError 以外を握らない)。
    assert window.diagnostics_vm.counts()[0] == 0, (
        "健全信号の追加で error 診断が出てはならない"
    )

    # ── 発火側: 失敗信号をパネル1 (index 0) へ実追加 → auto-fit が投げ→フックが握る ──
    vm.set_active_panel(0, 0)
    _pump_n(2)
    errors_before = window.diagnostics_vm.counts()[0]
    _real_select_and_menu_add(window, bad_row)
    _pump_n(6)
    shot_bad = _shot(tmp_path, "02_bad_added_survives")

    # (1) プロセス生存: ウィンドウはまだ可視で応答する
    assert window.isVisible(), (
        f"失敗信号の追加後ウィンドウが消えた (プロセスが落ちた疑い)。{shot_bad}"
    )
    # (2) 診断が出た (app フックが握って落とした)
    qtbot.waitUntil(
        lambda: window.diagnostics_vm.counts()[0] > errors_before, timeout=3000
    )
    assert window.diagnostics_vm.counts()[0] > errors_before, (
        f"失敗信号の追加で診断が出ない (app フックが握っていない)。{shot_bad}"
    )
    entry = window.diagnostics_vm.entries("error")[-1]
    assert "サンプル読み取り" in entry.message, (
        f"診断メッセージが遅延読み失敗を示さない: {entry.message!r}"
    )
    # (3) 健全パネルの曲線は依然描かれている (失敗が全体を巻き添えにしない)
    assert good_key in panel2.signal_keys_drawn(), (
        f"失敗信号の追加後に健全曲線まで消えた。{shot_bad}"
    )

    # (4) 応答性: 追加後も実クリックが届き、状態が**変わる**
    #     現在アクティブなのはパネル1 (index 0)。同じパネルを押しても
    #     set_active_panel は no-op で assert が押下前から真になる (恒真) ため、
    #     必ず**別**のパネル (index 1) を押して index の遷移を観測する。
    before = vm.active_panel_index(0)
    assert before == 0, "前提: 失敗信号を追加したパネル1がアクティブのはず"
    px, py = _phys_center(panel2, QPoint(panel2.width() // 2, 16))
    _real_click(px, py)
    qtbot.waitUntil(lambda: vm.active_panel_index(0) == 1, timeout=2000)
    assert vm.active_panel_index(0) == 1, (
        f"失敗信号の追加後にパネル実クリックが効かない (イベントループ停止の疑い)。"
        f"クリック前 {before} → 現在 {vm.active_panel_index(0)}。{shot_bad}"
    )
