"""Layer C (realgui): FU-15 — 実 ChannelBrowser クリックでプロットのアクティブ Y 軸が
解除される(クロスウィジェット実配送)。

GraphAreaView.eventFilter は QApplication にインストールされ、押下対象がプロット
subtree 外なら全パネルの set_active_axis(None) を呼ぶ(graph_area_view.py の
"centralized click-away" — Task 3)。headless では兄弟 QWidget への合成 press
(``QApplication.instance().notify(outsider, ev)``)でしか触れないこの経路を、
実 OS クリック(ChannelBrowser の実座標)で裏取りする — MainWindow を実ディスプレイに
mount し、ChannelBrowser の実座標を win32 マウスイベントで叩く。

合成入力の偽装をしない(memory gui_realgui_synthetic_click_mislabeled_layer_c):
qtbot.mouseClick/trigger は使わず、tests/realgui/_realgui_input.at() の win32
mouse_event で実クリックする。証拠は QScreen.grabWindow によるスクリーンショット。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

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


def _make_window_with_active_axes(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    """MainWindow(ChannelBrowser + GraphArea) を構築し、2 パネルへ信号を1本ずつ
    プロットして両パネルの軸0をアクティブ化する。

    軸のアクティブ化は panel.set_active_axis(0) の直接呼び出しで確立する(brief
    が明示的に許容する経路 — set_active_axis 自体は各 _y_axes[i].update() を
    内部で呼ぶので追加の refresh は不要)。このテストの実 OS 入力は後続の
    ChannelBrowser クリック(解除経路)に集中させる。

    QSettings 隔離は tests/realgui/conftest.py の autouse が効く。信号ロードは
    off-thread の LoadController を経由せず session.load→_on_loaded を直接呼んで
    同期化する(test_active_panel_flow.py と同じパターン)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    csv = tmp_path / "sig.csv"
    rows = ["t,speed"]
    for i in range(24):
        rows.append(f"{i * 0.1:.3f},{10.0 + i * 0.8:.4f}")
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
    window.graph_area_vm.add_panel(0)  # 2 パネル化

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

    # 両パネルへ同じ信号をプロットし、それぞれの軸0をアクティブ化する。
    panel_widgets = [w for _t, _p, w in window.graph_area_view._panel_views]
    assert len(panel_widgets) == 2, "2 パネル構成になっていない"
    for panel_vm in window.graph_area_vm.panels(0):
        panel_vm.add_signal(signal_key)
    for _ in range(3):
        QApplication.processEvents()
    for widget in panel_widgets:
        widget.set_active_axis(0)
    assert all(w._active_axis_index == 0 for w in panel_widgets), (
        "前提の確立に失敗: 両パネルの軸0がアクティブになっていない"
    )
    return window, panel_widgets


def test_channelbrowser_click_deselects_active_axis(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-15 クロスウィジェット実配送: ChannelBrowser の実クリックで全パネルの
    アクティブ Y 軸が解除される。

    Honest RED: GraphAreaView.__init__ の ``app.installEventFilter(self)``
    (graph_area_view.py) を一時的にスキップすると、このテストは
    ChannelBrowser を実クリックしても _active_axis_index が 0 のまま残り、
    最終 assert で落ちる(2026-07-12 手動確認・実装には戻していない)。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    window, panel_widgets = _make_window_with_active_axes(qtbot, tmp_path)
    _shot(tmp_path, "01_axes_active_before_click")

    # 実 OS クリックで ChannelBrowser の可視アイテム(row0)を左クリックする。
    # obj = 配送先(tree.viewport()) は GraphAreaView の subtree 外 — クロス
    # ウィジェット実配送(合成 notify ではなく実 OS ヒットテスト経由)。
    tree = window.channel_browser_view.tree
    model = (
        window.channel_browser_view.model
    )  # FU-22 B: proxy dropped, tree is model-direct
    qtbot.waitUntil(
        lambda: tree.visualRect(model.index(0, 0)).height() > 0, timeout=3000
    )
    rect = tree.visualRect(model.index(0, 0))
    vp = tree.viewport()
    from PySide6.QtCore import QPoint

    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    _real_click(*_phys_center(vp, local))

    qtbot.waitUntil(
        lambda: all(w._active_axis_index is None for w in panel_widgets),
        timeout=2000,
    )
    shot = _shot(tmp_path, "02_axes_deselected_after_channelbrowser_click")
    QApplication.processEvents()

    assert all(w._active_axis_index is None for w in panel_widgets), (
        "実 ChannelBrowser クリックで全パネルのアクティブ軸が解除されない "
        f"(クロスウィジェット click-away フィルタが実 OS 経路で通っていない)。"
        f" screenshot: {shot}"
    )
