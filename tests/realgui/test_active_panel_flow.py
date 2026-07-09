# ruff: noqa: RUF003
"""Layer C: アクティブパネル閉ループの実 OS 入力実証 (PC-07 / PC-02 / PC-04)。

合成 qtbot ではなく実クリック / 実ダブルクリック / 実 Enter で MainWindow を駆動し、
OS→Qt ヒットテスト/配送で以下の閉ループが成立することを検証する (Layer B との違い):

- パネル 2 の実クリック → パネル 2 が活性化し amber 枠が描画される (スクショ)
- 別ウィジェット (ChannelBrowser) の行を実クリック選択 → Add ボタンを実クリック →
  信号がアクティブパネル (パネル 2) に着地し曲線が実描画される (スクショ)
- パネル 1 の Y 軸ストリップを実クリック → 軸クリック経路でパネル 1 に活性化が戻る
- 実ダブルクリックで 1 回だけ追加・実 Enter で 1 回だけ追加 (二重発火なしの実証明)

自動 assert (VM 状態・_active_frame.isVisible()・raw エントリ数) は backstop、
スクショが判定の本体。plotted_signal_keys() は dedup を返すため、二重発火の観測は
inspect()["plotted_signals"] の raw エントリ数で数える (dedup では 1 vs 2 を区別不能)。
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
    VK_RETURN,
    at,
    double_click,
    skip_unless_real_display,
    to_phys,
)
from tests.realgui._realgui_input import key as key_input

pytestmark = pytest.mark.realgui


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int) -> None:
    for _ in range(n):
        _pump(0.02)


def _real_click(x: int, y: int) -> None:
    """純クリック: 同一点で press→release (MOVE なし)。"""
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    _pump_n(4)


def _phys_center(w, local_center) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    gp = w.mapToGlobal(local_center)
    dpr = w.devicePixelRatioF()
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _shot(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    p = tmp_path / f"{name}.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(p))
    return p


def _panel_widget(window, tab_index: int, panel_index: int):  # type: ignore[no-untyped-def]
    """GraphAreaView の QSplitter ページから panel_index 番目の GraphPanelView を返す。"""
    page = window.graph_area_view.tabs.widget(tab_index)  # QSplitter
    return page.widget(panel_index)


def _entry_count(panel_vm, key: str) -> int:  # type: ignore[no-untyped-def]
    """key の raw プロットエントリ数 (dedup しない — 二重発火検出用)。"""
    return sum(
        1 for e in panel_vm.inspect()["plotted_signals"] if e["signal_key"] == key
    )


def _make_window_with_two_panels_and_signal(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    """MainWindow を構築し、CSV 1 信号を同期ロード・2 パネル化して表示する。

    QSettings 隔離は tests/realgui/conftest.py の autouse が効く。信号ロードは
    off-thread の LoadController を経由せず session.load→_on_loaded を直接呼んで
    同期化する (production の完走コールバックと同じ登録/活性化経路)。返り値の
    signal_key は ChannelBrowser の row0 に出る namespaced キー。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    csv = tmp_path / "sig.csv"
    rows = ["t,speed"]
    for i in range(24):
        rows.append(f"{i * 0.1:.3f},{10.0 + i * 0.8:.4f}")  # 明瞭な右肩上がりの直線
    csv.write_text("\n".join(rows) + "\n")
    fmt = FormatDefinition(
        name="rt_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    outcome = window.app_vm.session.load(csv, fmt)
    window._on_loaded(outcome)  # 登録+活性化+ChannelBrowser 反映+workbench 表示
    window.graph_area_vm.add_panel(0)  # 2 パネル化 (新パネルが自動アクティブ)

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    w = min(1120, screen.width() - 120)
    h = min(760, screen.height() - 120)
    window.setGeometry(screen.x() + 60, screen.y() + 60, w, h)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(3):
        QApplication.processEvents()

    model = window.channel_browser_view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=3000)
    signal_key = model.signal_key_at(model.index(0, 0))
    assert signal_key is not None, "ChannelBrowser に信号行が出ていない"
    return window, signal_key


@pytest.mark.realgui
def test_click_activates_panel_and_add_routes_there(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """PC-07/PC-02 閉ループ: 実クリックで活性化 → 別ウィジェットの Add がアクティブパネルへ着地。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    window, key = _make_window_with_two_panels_and_signal(qtbot, tmp_path)
    vm = window.graph_area_vm
    vm.set_active_panel(0, 0)  # 前提固定: パネル 1 (index 0) を active に
    QApplication.processEvents()

    panel0 = _panel_widget(window, 0, 0)
    panel1 = _panel_widget(window, 0, 1)
    qtbot.waitUntil(
        lambda: (
            bool(panel1._view_boxes)
            and panel1._view_boxes[0].sceneBoundingRect().height() > 40
        ),
        timeout=3000,
    )

    # 1) パネル 2 (index 1) の空白部を実クリック → 活性化＋枠
    px, py = _phys_center(panel1, QPoint(panel1.width() // 2, 16))
    _real_click(px, py)
    shot1 = _shot(tmp_path, "01_panel2_active_frame")
    qtbot.waitUntil(lambda: vm.active_panel_index(0) == 1, timeout=2000)
    assert vm.active_panel_index(0) == 1, (
        f"パネル 2 の実クリックで active_panel が 1 にならない。screenshot: {shot1}"
    )
    assert panel1._active_frame.isVisible(), (
        f"パネル 2 に amber 枠が出ない。screenshot: {shot1}"
    )
    assert not panel0._active_frame.isVisible(), (
        f"パネル 1 の枠が残っている。screenshot: {shot1}"
    )

    # 2) [レビュー追加] パネル 1 (index 0) の Y 軸ストリップを実クリック → active==0 に戻る
    #    (軸クリック経路 _AlignedAxisItem.mouseClickEvent → set_active_axis/activate の実証)
    spine = panel0._y_axes[0].sceneBoundingRect()
    ax_x, ax_y = to_phys(panel0, spine.center().x(), spine.center().y())
    at(ax_x, ax_y, LDOWN)
    time.sleep(0.05)
    at(ax_x, ax_y, LUP)  # 同一点・MOVE なし → 純クリック → mouseClickEvent
    _pump_n(4)
    qtbot.waitUntil(lambda: vm.active_panel_index(0) == 0, timeout=2000)
    assert vm.active_panel_index(0) == 0, (
        "パネル 1 の Y 軸ストリップの実クリックで active_panel が 0 に戻らない "
        "(軸クリック活性化経路が実 OS で通らない)。"
    )
    assert panel0._active_frame.isVisible()

    # 3) Add 閉ループを brief どおりパネル 2 へ着地させるため、パネル 2 を再活性化
    _real_click(px, py)
    qtbot.waitUntil(lambda: vm.active_panel_index(0) == 1, timeout=2000)

    # 4) ChannelBrowser の row0 を実クリックで選択 → Add ボタンを実クリック
    tree = window.channel_browser_view.tree
    proxy = window.channel_browser_view.proxy
    qtbot.waitUntil(
        lambda: tree.visualRect(proxy.index(0, 0)).height() > 0, timeout=3000
    )
    rect = tree.visualRect(proxy.index(0, 0))
    vp = tree.viewport()
    # visualRect 幅は viewport 幅を超えうる (center.x が右隣ペインに着弾)。x をクランプ。
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    _real_click(*_phys_center(vp, local))
    add_btn = window.channel_browser_view.add_button
    qtbot.waitUntil(lambda: add_btn.isEnabled(), timeout=2000)
    _real_click(*_phys_center(add_btn, add_btn.rect().center()))

    # 5) パネル 2 に着地 (パネル 1 は空のまま)＋曲線が実描画
    panel1_vm = vm.panels(0)[1]
    panel0_vm = vm.panels(0)[0]
    qtbot.waitUntil(lambda: key in panel1_vm.plotted_signal_keys(), timeout=2000)
    shot2 = _shot(tmp_path, "02_curve_on_panel2")
    assert key in panel1_vm.plotted_signal_keys(), (
        f"Add がアクティブパネル 2 に着地しない。screenshot: {shot2}"
    )
    assert key not in panel0_vm.plotted_signal_keys(), (
        f"信号が非アクティブなパネル 1 に誤着地した。screenshot: {shot2}"
    )
    assert key in panel1.signal_keys_drawn(), (
        f"パネル 2 に曲線が実描画されていない。screenshot: {shot2}"
    )


@pytest.mark.realgui
def test_dblclick_and_enter_add_once_each(qtbot: QtBot, tmp_path: Path) -> None:
    """PC-04: 実ダブルクリックで 1 回追加・実 Enter で 1 回追加 (二重発火なしの実証明)。"""
    skip_unless_real_display()

    window, key = _make_window_with_two_panels_and_signal(qtbot, tmp_path)
    vm = window.graph_area_vm
    target = vm.active_panel()  # add_panel で index 1 が active

    tree = window.channel_browser_view.tree
    proxy = window.channel_browser_view.proxy
    qtbot.waitUntil(
        lambda: tree.visualRect(proxy.index(0, 0)).height() > 0, timeout=3000
    )
    rect = tree.visualRect(proxy.index(0, 0))
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    rx, ry = _phys_center(vp, local)

    # 実ダブルクリック → activated 経路で 1 回だけ追加
    double_click(rx, ry)
    _pump_n(4)
    qtbot.waitUntil(lambda: _entry_count(target, key) >= 1, timeout=2000)
    assert _entry_count(target, key) == 1, (
        f"実ダブルクリックで {_entry_count(target, key)} 回追加された (期待 1・二重発火)。"
    )

    # 実 Enter → eventFilter 経路でもう 1 回だけ追加 (activated も発火するなら +2)。
    # 実キーは前面ウィンドウのフォーカス widget へ届く — 直前の実ダブルクリックで
    # tree がフォーカス済み。
    key_input(VK_RETURN)
    _pump_n(4)
    qtbot.waitUntil(lambda: _entry_count(target, key) >= 2, timeout=2000)
    shot3 = _shot(tmp_path, "03_dblclick_enter_add")
    assert _entry_count(target, key) == 2, (
        f"実 Enter 後の追加数が {_entry_count(target, key)} (期待 2・二重発火なら 4)。"
        f"screenshot: {shot3}"
    )
