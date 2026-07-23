"""Layer C: real-OS-input GUI test for the FileBrowser "Remove File" menu.

Opt-in — run with ``--realgui``. Requires a real display + Windows: it moves the
physical cursor and issues a genuine right-click via Win32 ``SendInput``/
``mouse_event``, then asserts the context menu actually popped up. This is the
only tier that exercises the OS → Qt event translation (WM_CONTEXTMENU →
QContextMenuEvent) that a synthesized event cannot. Excluded from the default run
and from CI — see ``.claude/skills/gui-verify/`` (Layer C).

Run deliberately (e.g. before release, or after touching context-menu / event
routing) on a Windows machine with a real display::

    uv run pytest --realgui tests/realgui/

Note: this hijacks the mouse cursor for ~1s while it runs.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import RDOWN, RUP, at, skip_unless_real_display
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui


def test_remove_file_menu_appears_on_real_os_right_click(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()

    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    from valisync.core.models import SignalGroup
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
    from valisync.gui.views.file_browser_view import FileBrowserView

    # Two loaded files so the FileBrowser list has rows to right-click.
    app_vm = AppViewModel()
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("b.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    # This test's E-2a/b assertions (below) exercise the comparison-mode
    # affordances ("基準に設定"/"基準の同名信号を重ねる"), which the
    # comparison-mode-toggle spec (2026-07-23 §3 M7) now gates on an explicit
    # user opt-in rather than "2+ files loaded" alone — enable it here so the
    # menu-content assertion continues to test what it always intended to
    # (M13 site-by-site follow-up; this site's intent is comparison behavior,
    # not single-mode behavior).
    app_vm.set_comparison_mode(True)

    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 360, 240)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(
        lambda: view.list_view.visualRect(view.model.index(0, 0)).height() > 0,
        timeout=3000,
    )

    lv = view.list_view
    dpr = view.devicePixelRatioF()
    center = lv.visualRect(view.model.index(0, 0)).center()
    gp = lv.viewport().mapToGlobal(center)
    # Qt reports logical global coords; SetCursorPos wants physical pixels.
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    captured: dict[str, object] = {}

    def do_real_right_click() -> None:
        at(phys_x, phys_y, RDOWN)
        at(phys_x, phys_y, RUP)
        # A real menu opens modally here; capture() fires inside that loop.

    loop = QEventLoop()

    def capture() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "realclick.png"))
        if isinstance(popup, QMenu):
            captured["actions"] = [a.text() for a in popup.actions()]
            popup.close()
        loop.quit()

    QTimer.singleShot(300, do_real_right_click)
    QTimer.singleShot(900, capture)
    QTimer.singleShot(4000, loop.quit)  # safety net
    loop.exec()

    assert captured.get("type") == "QMenu", (
        "no context menu appeared on a real OS right-click; "
        f"got {captured.get('type')!r}. screenshot: {tmp_path / 'realclick.png'}"
    )
    # E-2a/b: reference_file_key is None here (app_vm._loaded_keys was set
    # directly, bypassing register_loaded's auto-reference), so neither loaded
    # row is "the reference" — both new items appear alongside Remove File.
    assert captured.get("actions") == [
        S.ACTION_REMOVE_FILE,
        S.ACTION_SET_REFERENCE,
        S.ACTION_OVERLAY_REFERENCE,
    ]
