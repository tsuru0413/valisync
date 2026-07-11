"""BusyOverlay の Layer A/B: 親 resize 追従 (FU-02) と表示契約。

resize は `parent.resize()` で駆動する (実 QResizeEvent が配送され eventFilter
の実経路を通る)。`overlay.eventFilter(...)` の直接呼び出しはハンドラ直叩き=
実経路の迂回になるため使わない。
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.busy_overlay import BusyOverlay


def _shown_parent(qtbot: QtBot, w: int = 400, h: int = 300) -> QWidget:
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(w, h)
    parent.show()
    qtbot.waitExposed(parent)
    return parent


def test_visible_overlay_tracks_parent_resize(qtbot: QtBot) -> None:
    """FU-02: 表示中の親 resize (拡大/縮小の両方向) に overlay が追従する。

    修正前は show() 時の cover() だけで resize 後も旧ジオメトリのまま RED
    (実測: window を 1400x844 から 1024x650 にしても overlay は 1400x844)。
    """
    parent = _shown_parent(qtbot)
    overlay = BusyOverlay(parent)
    overlay.show()
    assert overlay.geometry() == parent.rect()

    parent.resize(640, 480)  # 拡大
    QApplication.processEvents()
    assert parent.size() == QSize(640, 480)  # イベント非消費 (親の resize は成立)
    assert overlay.geometry() == parent.rect()  # 追従 (修正前はここで RED)

    parent.resize(320, 240)  # 縮小 (実機で観測された方向)
    QApplication.processEvents()
    assert overlay.geometry() == parent.rect()


def test_hidden_overlay_covers_on_next_show_after_resize(qtbot: QtBot) -> None:
    """非表示中の resize は無害 — 次回 show() の cover() で正す (既存挙動の回帰ガード)。"""
    parent = _shown_parent(qtbot)
    overlay = BusyOverlay(parent)
    parent.resize(640, 480)
    QApplication.processEvents()
    overlay.show()
    assert overlay.geometry() == parent.rect()


def test_parentless_overlay_show_does_not_crash(qtbot: QtBot) -> None:
    """parent なし構築でも show()/cover() は no-op で成立する (既存契約)。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    overlay.show()
    assert overlay.isVisible()
