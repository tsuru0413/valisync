"""Layer C: a real OS pure-click on a non-active axis spine activates that axis.

Opt-in — run with ``--realgui`` on Windows + a real display. The whole active-axis
gesture model has one entry point — clicking an axis spine to activate it — that the
existing realgui suite bypasses by calling view.set_active_axis(0) directly. This test
drives a genuine left press+release (no movement → below pyqtgraph's drag threshold →
mouseClickEvent, not mouseDragEvent) on a non-active spine and asserts it activates
(via _AlignedAxisItem.mouseClickEvent → set_active_axis) and that a subsequent real
grip drag then acts on the now-active axis. See docs/gui-testing-layers.md (Layer C).
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


def _show_two_axis_panel(qtbot: QtBot):
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    from PySide6.QtCore import Qt

    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 800, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return view


def _spine_center_phys(view, axis_index: int) -> tuple[int, int]:
    spine = view._y_axes[axis_index].sceneBoundingRect()
    return to_phys(view, spine.center().x(), spine.center().y())


def test_real_click_activates_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """Pure click on axis 1's spine switches the active axis 0 → 1."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _show_two_axis_panel(qtbot)
    view.set_active_axis(0)  # start with axis 0 active so the click must SWITCH to 1
    QApplication.processEvents()
    assert view._active_axis_index == 0

    cx, cy = _spine_center_phys(view, 1)
    at(cx, cy, LDOWN)
    time.sleep(0.05)
    at(cx, cy, LUP)  # same point, no MOVE → pure click → mouseClickEvent
    for _ in range(4):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "activate.png"))

    assert view._active_axis_index == 1, (
        "real click on axis 1 spine did not activate it "
        f"(got {view._active_axis_index}). screenshot: {tmp_path / 'activate.png'}"
    )


def test_click_activation_enables_grip_resize(qtbot: QtBot, tmp_path: Path) -> None:
    """After a real click activates axis 1, a real grip drag resizes axis 1 —
    impossible unless the click activated it (_begin_axis_drag rejects non-active)."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _show_two_axis_panel(qtbot)
    view.set_active_axis(0)  # axis 1 is NOT active
    QApplication.processEvents()

    R = view._view_boxes[0].sceneBoundingRect()

    def strip_h(i: int) -> float:
        return view._y_axes[i].sceneBoundingRect().height() / R.height()

    h1_before = strip_h(1)

    # Pure click on axis 1 spine → activate it.
    cx, cy = _spine_center_phys(view, 1)
    at(cx, cy, LDOWN)
    time.sleep(0.05)
    at(cx, cy, LUP)
    for _ in range(4):
        QApplication.processEvents()
    assert view._active_axis_index == 1, "click did not activate axis 1"

    # Subsequent real grip drag: axis 1's TOP grip dragged DOWN shrinks axis 1
    # (model B: neighbour untouched, gap absorbs). Small uniform steps keep the
    # first threshold crossing inside the grip band (see test_active_axis_resize).
    spine1 = view._y_axes[1].sceneBoundingRect()
    gx, gy = to_phys(view, spine1.center().x(), spine1.top() + 2)
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    for k in range(1, 6):  # drag DOWN ~60px
        at(gx, gy + k * 12, MOVE)
        QApplication.processEvents()
        time.sleep(0.03)
    at(gx, gy + 60, LUP)
    for _ in range(4):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "resize.png"))

    h1_after = strip_h(1)
    assert h1_after < h1_before - 0.03, (
        "axis 1 did not shrink — click-activation did not enable the grip gesture "
        f"(before={h1_before:.3f} after={h1_after:.3f}). screenshot: {tmp_path / 'resize.png'}"
    )
