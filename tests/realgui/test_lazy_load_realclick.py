"""Layer C: 遅延ロードの勝利を実 GUI で end-to-end 実証 (Task 8・①ゲート)。

honest layering (gui-e2e-acceptance §Task 8): ``_values_source.is_materialized``
は「lazy か eager か」の *メカニズム* 証明 — RSS の代理ではない。ここでは実
ディスプレイの本物の MainWindow で実 mf4 (prod_demo.mf4・1.36GB・264k 信号) を
実ロード経路でロードし、実 OS 入力で 1 本だけプロットして、

  (a) プロットした信号は実際に描画される (RenderCurve が非空)、
  (b) *開いた直後* は全信号が未展開 (is_materialized == False) = open はメタ+master のみ、
  (c) 1 本プロット後も *未プロット* 信号は全数未展開のまま、

を assert する。headless の直叩きは namespaced ラッパー/オフセット/描画の実経路を
迂回しうるため、遅延がユーザーの実操作を貫通することはここでしか証明できない
(RSS の実測は scripts/measure_lazy_footprint.py が担う — 両方必要)。

実マウスドラッグは使わない (共有マシンでハング・memory gui_realgui_drag_qtimer_hang)。
プロットは実クリックで行を選択 → 実右クリックメニュー「アクティブパネルに追加」を
実クリック、である (double-click は FU-13 でプレビューに変更・Enter 追加は無いため、
右クリックメニューが唯一の実プロット経路)。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from pytestqt.qtbot import QtBot

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
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui

_PROD_MF4 = Path("D:/Programming/projects/valisync/demo_data/prod_demo.mf4")
_LOAD_TIMEOUT_MS = 180_000  # prod_demo は 1.36GB — 遅延ロードでも数秒〜十数秒


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


def _first_scalar_leaf_row(model) -> int:  # type: ignore[no-untyped-def]
    """First top-level row that is a scalar leaf (signal_key_at not None).

    Array bases (LD-14) collapse under parent rows whose ``signal_key_at`` is
    None; scalars stay top-level leaves. Scanning only top-level indexes is
    lazy-safe — it never materializes a group's children (FU-22 B).
    """
    for row in range(model.rowCount()):
        if model.signal_key_at(model.index(row, 0)) is not None:
            return row
    raise AssertionError("チャンネルツリーにスカラー葉が無い")


def _count_materialized(group_sigs) -> list[str]:  # type: ignore[no-untyped-def]
    """Namespaced names of signals whose value source is materialized."""
    return [s.name for s in group_sigs if s._values_source.is_materialized]


def _real_select_and_menu_add(window, row: int) -> None:  # type: ignore[no-untyped-def]
    """Scroll row into view, real-click to select, then real right-click and
    real-click the "アクティブパネルに追加" menu item (nested QMenu.exec).

    An ESC watchdog closes a stuck popup so a missed click fails on an
    assertion rather than hanging the shared machine.
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    tree = window.channel_browser_view.tree
    model = window.channel_browser_view.model
    idx = model.index(row, 0)
    tree.scrollTo(idx)
    _pump_n(3)
    rect = tree.visualRect(idx)
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    px, py = _phys_center(vp, local)
    _real_click(px, py)  # select the row → "アクティブパネルに追加" enabled

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


def test_lazy_load_keeps_unplotted_unmaterialized(qtbot: QtBot, tmp_path: Path) -> None:
    """実 mf4 ロード → 1 本実プロット → 未プロットは全数未展開 (実 OS 入力・prod スケール)。"""
    skip_unless_real_display()
    if not _PROD_MF4.exists():
        pytest.skip(f"prod スケール mf4 が無い: {_PROD_MF4}")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    # 配列展開は全スキップ (空集合) — 実ロード経路 (off-thread) から呼ばれるが
    # override は set() を返す純関数でスレッド安全・ダイアログ非ブロック。
    window._expansion_confirmer.confirm = lambda request: set()  # type: ignore[assignment]

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    w = min(1200, screen.width() - 120)
    h = min(800, screen.height() - 120)
    window.setGeometry(screen.x() + 60, screen.y() + 60, w, h)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    _pump_n(3)

    # ── 実ロード経路 (LoadController off-thread + busy overlay) を駆動 ──
    window._load_file(_PROD_MF4)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )
    loaded_key = window.app_vm.loaded_file_keys[0]
    session = window.app_vm.session
    group_sigs = session.group_signals(loaded_key)
    assert len(group_sigs) > 1000, (
        f"prod スケールで無い (信号数 {len(group_sigs):,}) — 規模実証にならない"
    )
    _shot(tmp_path, "01_loaded")

    # (b) open = メタ+master のみ: プロット前は全信号が未展開。
    materialized_before = _count_materialized(group_sigs)
    assert materialized_before == [], (
        f"開いた直後に値が展開されている (open が eager の疑い): "
        f"{materialized_before[:5]} ... 計 {len(materialized_before)}"
    )

    # ── チャンネルツリーが 264k 行の reset を終えるのを待つ ──
    model = window.channel_browser_view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=_LOAD_TIMEOUT_MS)
    _pump_n(6)
    leaf_row = _first_scalar_leaf_row(model)
    plotted_key = model.signal_key_at(model.index(leaf_row, 0))
    assert plotted_key is not None

    # ── 実クリックで行選択 → 実右クリックメニュー「追加」を実クリック ──
    vm = window.graph_area_vm
    _real_select_and_menu_add(window, leaf_row)

    panel = _panel_widget(window, 0, 0)  # 既定 1 パネル (active) へ着地
    panel_vm = vm.panels(0)[0]
    qtbot.waitUntil(lambda: plotted_key in panel_vm.plotted_signal_keys(), timeout=5000)
    _pump_n(4)
    shot = _shot(tmp_path, "02_one_plotted")

    # (a) プロットした信号が実際に描画される (RenderCurve が非空)。
    assert plotted_key in panel.signal_keys_drawn(), (
        f"プロットした信号がパネルに実描画されない: {plotted_key!r}。{shot}"
    )
    entry_id = panel.entry_id_for(plotted_key)
    xs, _ys = panel.curve_xy(entry_id)
    assert xs is not None and len(xs) > 0, (
        f"描画カーブが空 (値が読まれていない疑い): {plotted_key!r}。{shot}"
    )

    # (c) プロット後も未プロットは全数未展開 — 展開されたのはプロットした 1 本のみ。
    materialized_after = _count_materialized(group_sigs)
    leaked = [name for name in materialized_after if name != plotted_key]
    assert leaked == [], (
        f"未プロット信号が展開された (遅延が実 GUI を貫通していない): "
        f"{leaked[:5]} ... 計 {len(leaked)} 展開 (plotted={plotted_key!r})。{shot}"
    )
    # プロットした信号は展開済み = レンダが実際に値を読んだ (no-op pass を排除)。
    assert plotted_key in materialized_after, (
        f"プロットした信号が展開されていない (レンダが値を読んでいない疑い): "
        f"{plotted_key!r}。{shot}"
    )
