"""Layer C 常設ジャーニースモーク (gui-verify ゲート (e))。

実 MainWindow + 実 OS 入力で基本ジャーニーを一気通貫し、グローバル介入
(app click-away フィルタ)下でも「軸クリック活性化に続くジェスチャが
ユーザー可視の効果を生む」ことを検証する。FU-23: 祖先バブル誤発火で
軸ジェスチャが無効化される退行を捕まえる honest-RED。相互作用バグは
diff スコープ選定が構造的に取りこぼすため、機構盲目の無条件チェックで受ける。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    MOVE,
    at,
    skip_unless_real_display,
    to_phys,
)

pytestmark = pytest.mark.realgui


def test_axis_activate_then_zoom_takes_effect(qtbot: QtBot, tmp_path: Path) -> None:
    """実クリックで軸を活性化 -> 続く実内側ドラッグで Y レンジが実際にズームする。

    ズームは ACTIVE 軸でのみ受理される。現 HEAD (祖先バブル誤発火) では RED:
    内側ドラッグの press 直後に clear_active_axis が誤発火して _active_axis_index=None
    に落ち、ジェスチャが拒否 -> Y レンジ不変。FU-23 修正で GREEN。単一軸で成立し、
    RED はバグ由来のみに帰属する (grip リサイズは 2 軸必須で単一軸だと縮む余地が
    無く RED が交絡するため不採用)。
    """
    skip_unless_real_display()
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
        name="smoke_fmt",
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
    for _ in range(3):
        QApplication.processEvents()

    # 信号を最初のパネルへプロット (軸0/ズーム対象)。
    model = window.channel_browser_view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=3000)
    signal_key = model.signal_key_at(model.index(0, 0))
    assert signal_key is not None
    for panel_vm in window.graph_area_vm.panels(0):
        panel_vm.add_signal(signal_key)
    for _ in range(3):
        QApplication.processEvents()

    panel = next(w for _t, _p, w in window.graph_area_view._panel_views)
    qtbot.waitUntil(
        lambda: panel._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )

    # --- 実クリックで軸0を活性化 (純クリック: 同一点 press->release, 移動なし)。
    spine0 = panel._y_axes[0].sceneBoundingRect()
    cx, cy = to_phys(panel, spine0.center().x(), spine0.center().y())
    at(cx, cy, LDOWN)
    time.sleep(0.05)
    at(cx, cy, LUP)
    for _ in range(4):
        QApplication.processEvents()
    assert panel._active_axis_index == 0, "実クリックで軸0が活性化しない"

    lo0, hi0 = panel._y_axes[0].range
    span_before = hi0 - lo0

    # --- 活性化に続く実内側ドラッグ (軸0スパイン右側=プロット側=ズームゾーン)。
    inner_x = spine0.x() + spine0.width() * 0.78
    x0, ya = to_phys(panel, inner_x, spine0.y() + spine0.height() * 0.30)
    _, yb = to_phys(panel, inner_x, spine0.y() + spine0.height() * 0.70)
    at(x0, ya, LDOWN)
    time.sleep(0.05)
    for yy in (ya + (yb - ya) // 3, ya + 2 * (yb - ya) // 3, yb):
        at(x0, yy, MOVE)
        QApplication.processEvents()
        time.sleep(0.04)
    at(x0, yb, LUP)
    for _ in range(4):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "smoke_zoom.png")
        )

    lo1, hi1 = panel._y_axes[0].range
    span_after = hi1 - lo1
    assert span_after < span_before * 0.9, (
        "活性化に続く内側ドラッグが Y レンジを変えない = ジェスチャ未完遂 "
        f"(span {span_before:.3f} -> {span_after:.3f}, app フィルタ誤発火の疑い)。"
        f" screenshot: {tmp_path / 'smoke_zoom.png'}"
    )
