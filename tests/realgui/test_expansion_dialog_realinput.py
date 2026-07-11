"""Layer C: FU-01 — 多数チャンネルの ExpansionDialog が画面内に収まり、
実マウスホイールで最下段チェックボックスへ到達して操作できる (到達性 E2E)。

`--realgui` opt-in・実ディスプレイ+Windows 必須。offscreen には実 WM 配置が
無いため「ダイアログが画面外へ伸び OK/Cancel に届かない」現象の反証は実機
でしか成立しない。スクロールは実 OS ホイール (`_realgui_input.wheel`・repo 初出)
で駆動する — `verticalScrollBar().setValue()` や合成 QWheelEvent は Layer B
であり到達性の証明にならない。

isVisible() は画面外でも True を返すため「画面内」の証拠には使わない
(visibleRegion + グローバル矩形 in screen — FU-04 と同じ判定)。

honest-RED: チェック列を QScrollArea から外し直接レイアウトへ戻す (pre-FU-01
相当) sabotage で本テストが実際に FAIL する (ダイアログ高 3020px > 画面 864px)
ことを実証済み (Task 2 Step 5)。クランプ分岐のみの無効化では RED にならない —
Qt 6.11 は QScrollArea.sizeHint を ~36x24 文字高に制限するため、スクロール化
そのものが通常画面ではダイアログ高を抑える (クランプは小型画面向けの保険)。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    at,
    skip_unless_real_display,
    wheel,
)

pytestmark = pytest.mark.realgui


def _many(n: int):  # type: ignore[no-untyped-def]
    from valisync.core.loaders.mdf_loader import ExpansionRequest, OversizedChannel

    return ExpansionRequest(
        channels=tuple(
            OversizedChannel(name=f"Ch{i:03d}", column_count=2000) for i in range(n)
        )
    )


def _onscreen(w) -> bool:  # type: ignore[no-untyped-def]
    """visibleRegion 非空 + グローバル矩形が画面内 (isVisible は不使用)。"""
    from PySide6.QtWidgets import QApplication

    scr = QApplication.primaryScreen().geometry()
    tl = w.mapToGlobal(w.rect().topLeft())
    br = w.mapToGlobal(w.rect().bottomRight())
    return (
        scr.contains(tl)
        and scr.contains(br)
        and not w.visibleRegion().isEmpty()
        and w.width() > 5
    )


def _phys(widget) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """widget 中心の物理ピクセル (DPR スケール) を呼び出し時点で算出。"""
    c = widget.rect().center()
    g = widget.mapToGlobal(c)
    dpr = widget.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _real_click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    at(x, y, LUP)


def test_bottom_checkbox_reachable_by_real_wheel_then_ok(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-01 受け入れ: 画面高を超える本数でもダイアログは画面内に収まり、
    実ホイール→最下段チェック実クリック→OK 実クリックが通る。"""
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from valisync.gui.views.expansion_dialog import ExpansionDialog

    screen = QApplication.primaryScreen().geometry()
    # どの画面高でも「スクロールしないと最下段に届かない」本数を画面から導出
    # (1 行 ~18px の保守見積で画面高の ~2 倍)。
    n = max(60, (screen.height() * 2) // 18)
    dlg = ExpansionDialog(_many(n))
    qtbot.addWidget(dlg)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dlg.show()  # exec() はモーダルループでテストをブロックするため show()
    dlg.raise_()
    dlg.activateWindow()
    qtbot.waitExposed(dlg)
    QApplication.processEvents()

    # 修正の核: ダイアログ高が画面内 (sabotage 時はここで FAIL = honest-RED)。
    assert dlg.height() <= screen.height(), (
        f"FU-01 再発: ダイアログ高 {dlg.height()}px > 画面 {screen.height()}px"
    )
    box = dlg.findChild(QDialogButtonBox)
    assert box is not None
    ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_btn is not None
    assert _onscreen(ok_btn), "OK ボタンが画面外 (FU-01 再発)"
    assert _onscreen(dlg._checks[0]), "先頭チェックボックスが画面外"
    assert dlg._checks[-1].visibleRegion().isEmpty(), (
        "前提不成立: 最下段が最初から可視 = チャンネル数が画面に対して少なすぎる"
    )

    # 実ホイールで最下段が可視になるまで下スクロール (カーソルは viewport 上)。
    vp_x, vp_y = _phys(dlg._scroll.viewport())
    last_cb = dlg._checks[-1]
    deadline = time.monotonic() + 10.0
    while last_cb.visibleRegion().isEmpty() and time.monotonic() < deadline:
        wheel(vp_x, vp_y, -120 * 5)
        for _ in range(4):
            QApplication.processEvents()
            time.sleep(0.02)
    shot_scrolled = tmp_path / "fu01_scrolled_bottom.png"
    QApplication.primaryScreen().grabWindow(0).save(str(shot_scrolled))
    assert not last_cb.visibleRegion().isEmpty(), (
        f"実ホイールで最下段へ到達できない。screenshot: {shot_scrolled}"
    )

    # 最下段を実クリック → チェックが入る (「アクセス不能」の直接反証)。
    _real_click(*_phys(last_cb))
    qtbot.waitUntil(last_cb.isChecked, timeout=3000)

    # OK を実クリック → accept され最下段インデックスが結果に含まれる。
    with qtbot.waitSignal(dlg.accepted, timeout=3000):
        _real_click(*_phys(ok_btn))

    print(f"[FU-01] n={n} result_indices contains last: {n - 1 in dlg.result_indices}")
    print(f"[FU-01] screenshot: {shot_scrolled}")
    assert n - 1 in dlg.result_indices, (
        f"OK 実クリック後の result_indices に最下段 {n - 1} が無い: "
        f"{sorted(dlg.result_indices)}。screenshot: {shot_scrolled}"
    )
