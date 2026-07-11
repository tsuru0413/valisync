"""Layer C: real-OS-input test for BusyOverlay's cancel button (FB-04).

Opt-in — run with ``--realgui`` on a real display + Windows. BusyOverlay's
cancel_button sits under a semi-transparent overlay that covers the whole
parent (``cover()``); hit-testing it goes through the real OS -> Qt hit-test
chain that a synthesized click cannot exercise (see .claude/skills/gui-verify/,
Layer C). This is the sole new input route in this batch — spec §7 marks it
Layer C required.

Wires cancel_requested -> LoadController.cancel_active exactly as MainWindow
does (main_window.py:71), so a real click both fires the signal AND (via that
wiring) hides the overlay immediately — the ②実質性 bar from the task brief.

Follows the pure-click precedent in test_click_activate_axis.py (press+release
at the same point, no MOVE) and the window-placement recipe in
test_axis_hover_frame.py (StaysOnTop, availableGeometry-clamped, waitExposed).
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_real_click_on_cancel_button_fires_signal_and_hides_overlay(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Real OS click on cancel_button -> cancel_requested fires AND (via the
    MainWindow-style wiring to LoadController.cancel_active) the overlay hides
    immediately and the load's hard-cancel event is set."""
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget

    from valisync.gui.views.busy_overlay import BusyOverlay
    from valisync.gui.workers.load_worker import LoadController

    release = threading.Event()
    cancel_event = threading.Event()
    discards: list[object] = []

    def slow_load() -> str:
        release.wait(timeout=5.0)  # keeps the load "active" until after the click
        return "late_result"

    parent = QWidget()
    qtbot.addWidget(parent)
    overlay = BusyOverlay(parent)
    controller = LoadController()
    overlay.cancel_requested.connect(controller.cancel_active)  # main_window.py:71

    parent.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    parent.setGeometry(screen.x() + 80, screen.y() + 80, 400, 300)
    parent.show()
    qtbot.waitExposed(parent)
    for _ in range(3):
        QApplication.processEvents()

    controller.submit(
        slow_load,
        busy=overlay,
        cancel_event=cancel_event,
        label="a.mf4",
        on_discard=discards.append,
    )
    qtbot.waitUntil(lambda: not overlay.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: overlay.cancel_button.rect().height() > 0, timeout=3000)

    center = overlay.cancel_button.rect().center()
    gp = overlay.cancel_button.mapToGlobal(center)
    dpr = overlay.devicePixelRatioF()
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    shot_path = tmp_path / "busy_cancel_realclick.png"
    with qtbot.waitSignal(overlay.cancel_requested, timeout=3000):
        at(phys_x, phys_y, LDOWN)
        QApplication.processEvents()
        time.sleep(0.05)
        at(phys_x, phys_y, LUP)  # same point, no MOVE -> pure click
        for _ in range(4):
            QApplication.processEvents()
            time.sleep(0.02)
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_path))

    assert overlay.isHidden(), (
        "cancel_requested fired but the overlay did not hide via the "
        f"LoadController.cancel_active wiring. screenshot: {shot_path}"
    )
    assert cancel_event.is_set(), (
        f"hard-cancel event was not set by the real click. screenshot: {shot_path}"
    )

    release.set()  # let the now-cancelled worker drain so no thread lingers
    qtbot.waitUntil(lambda: discards == ["late_result"], timeout=3000)
