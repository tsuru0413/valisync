"""Layer C: real-OS-input test for the DiagnosticsView row double-click jump.

Opt-in — run with ``--realgui`` on a real display + Windows. The row
double-click path (``QTableWidget`` viewport hit-test → ``cellDoubleClicked``
→ ``entry_activated``) is a new dock-internal input route (Task 4/5); Layer A/B
already cover the handler and the *synthetic* dblclick event routing
(``tests/gui/test_diagnostics_view.py``), but only a genuine OS double-click
exercises the OS → Qt ``WM_LBUTTONDBLCLK`` translation and the real item-view
hit-test — neither is re-checkable from Layer A/B (see
``docs/gui-testing-layers.md``, Layer C).

Doubled-click formation is a repo-first technique for realgui: two press+release
pairs at the *same* point (no MOVE, extending the pure-click precedent in
``tests/realgui/test_click_activate_axis.py``) spaced inside the OS
``GetDoubleClickTime()`` window.

The VM's ``Diagnostic`` entries here carry no ``signal_name`` (the current
loaders never set it — see ``diagnostics_view.py``'s ``_on_double_click``), so
``entry_activated`` always emits the source basename fallback; the signal-name
branch is latent and intentionally not asserted here (per the analysis block).

Honest RED (see ``tests/gui/test_diagnostics_view.py`` /
``tests/gui/test_main_window.py`` for the sabotage-RED evidence on the
underlying ``cellDoubleClicked``/``entry_activated`` connects — this Layer C
file adds OS-translation coverage on top of that, not a duplicate RED).
"""

from __future__ import annotations

import contextlib
import ctypes
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui

_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None


def _double_click_interval_s() -> float:
    """Half the OS double-click window (ms), capped so the test stays snappy."""
    ms = _user32.GetDoubleClickTime() if _user32 is not None else 500
    return min(ms / 2, 150) / 1000


def _double_click(x: int, y: int) -> None:
    """Issue a genuine OS double-click at physical (x, y): two press/release
    pairs at the same point, no MOVE between them, spaced inside
    ``GetDoubleClickTime()`` — the OS then coalesces the second press into
    ``WM_LBUTTONDBLCLK`` (Qt: ``QEvent.MouseButtonDblClick``)."""
    from PySide6.QtWidgets import QApplication

    interval_s = _double_click_interval_s()
    at(x, y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(x, y, LUP)
    QApplication.processEvents()
    time.sleep(interval_s)
    at(x, y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(x, y, LUP)
    for _ in range(4):
        QApplication.processEvents()
        time.sleep(0.02)


def _show_view(qtbot: QtBot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models.load_result import Diagnostic
    from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel
    from valisync.gui.views.diagnostics_view import DiagnosticsView

    vm = DiagnosticsViewModel()
    vm.add("a.mf4", [Diagnostic(level="error", message="boom")])
    vm.add("b.mf4", [Diagnostic(level="warning", message="skip")])
    view = DiagnosticsView(vm)
    qtbot.addWidget(view)
    # DiagnosticsView alone (not the full MainWindow — no realgui precedent
    # assembles MainWindow, since tests/gui/conftest's QSettings isolation is
    # scoped to tests/gui/ and would not apply here).
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 80, screen.y() + 80, 520, 300)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    table = view._table
    qtbot.waitUntil(
        lambda: table.visualItemRect(table.item(0, 0)).height() > 0, timeout=3000
    )
    return vm, view


def test_real_os_dblclick_on_row_emits_entry_activated(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """A real OS double-click on row 0's cell fires ``entry_activated`` with
    row 0's source (``a.mf4`` — no signal_name is set, so the fallback is the
    source basename)."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    _vm, view = _show_view(qtbot)
    table = view._table

    center = table.visualItemRect(table.item(0, 0)).center()
    gp = table.viewport().mapToGlobal(center)
    dpr = view.devicePixelRatioF()
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    shot_path = tmp_path / "diagnostics_dblclick.png"
    with qtbot.waitSignal(view.entry_activated, timeout=3000) as blocker:
        _double_click(phys_x, phys_y)
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_path))

    assert blocker.args == ["a.mf4"], (
        "expected entry_activated('a.mf4') from a real OS double-click on row 0 "
        f"— got {blocker.args!r}. screenshot: {shot_path}"
    )


def test_real_click_on_warnings_button_filters_rows(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Real OS left-click on the Warnings button filters the table to 1 row —
    cheap same-file physical-click entry point for Path 1's filter bar."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    _, view = _show_view(qtbot)

    center = view._btn_warn.rect().center()
    gp = view._btn_warn.mapToGlobal(center)
    dpr = view.devicePixelRatioF()
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    shot_path = tmp_path / "diagnostics_filter_click.png"
    at(phys_x, phys_y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(phys_x, phys_y, LUP)
    for _ in range(6):
        QApplication.processEvents()
        time.sleep(0.02)
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_path))

    assert view.row_count() == 1, (
        f"expected 1 row after a real OS click on Warnings, got {view.row_count()}. "
        f"screenshot: {shot_path}"
    )
