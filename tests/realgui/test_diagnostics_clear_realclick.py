"""Layer C: real OS click on diagnostics Clear -> real confirm dialog -> real
click "クリア" -> diagnostics emptied (B5/UXG-27).

Layer A (tests/gui/test_diagnostics_view.py) covers the 3 branches
(confirm/cancel/zero-skip) via ``_confirm_fn`` stub injection, avoiding the
real ``QMessageBox.exec()`` modal loop. This file is the one place that
exercises the *real* dialog end to end: a genuine OS click on the Clear
button opens ``clear_diagnostics()``'s ``QMessageBox`` (a nested, synchronous
Qt event loop — same shape as ``contextMenuEvent``'s ``menu.exec()`` in
test_readout_realclick.py), and a second genuine OS click on the dialog's
relabelled "クリア" button dismisses it with ``Yes``.

Reuses the established modal pattern from test_readout_realclick.py's
``_open_menu_click_item``/``_menu_hang_watchdog`` (module-local copy per that
file's own precedent: kept per-file to avoid cross-test-module imports). If
the real click misses the dialog's button, nothing closes the popup and the
nested ``exec()`` blocks forever; the watchdog thread sends a real Escape
after a deadline so the test fails on a clean assertion instead of hanging.
"""

from __future__ import annotations

import contextlib
import threading
import time

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
)
from tests.realgui._realgui_input import key as key_input

pytestmark = pytest.mark.realgui


def _dialog_hang_watchdog(stop: threading.Event) -> None:
    """Force-close a stuck ``QMessageBox.exec()`` modal loop with a real Escape.

    ``clear_diagnostics()`` calls ``box.exec()`` synchronously — a *nested* Qt
    event loop, just like ``contextMenuEvent``'s ``menu.exec()``. If the real
    click on the dialog's button misses its target, nothing closes the popup
    and the nested ``exec()`` blocks forever; the caller's outer
    ``QTimer.singleShot(5000, loop.quit)`` safety net only reaches the OUTER
    loop and cannot unwind the nested exec(). ``QMessageBox``'s default
    button is No, and Escape triggers the dialog's reject path, so this
    daemon thread sends ``VK_ESCAPE`` after a deadline and the test then
    fails on a clean assertion instead of hanging. The caller sets ``stop``
    immediately after its ``loop.exec()`` returns, so in the happy path this
    thread sees ``stop`` well before its deadline and never fires.
    (module-local copy of the helper established in
    test_axis_menu_offset.py / test_readout_realclick.py.)
    """
    deadline = time.time() + 4.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.1)
    if not stop.is_set():
        key_input(VK_ESCAPE)


def _click_clear_then_confirm(view, phys, shot_dialog):  # type: ignore[no-untyped-def]
    """Real left-click at *phys* (the Clear button), screenshot the resulting
    modal dialog, then real-click its relabelled "クリア" (Yes) button.

    Mirrors test_readout_realclick.py's ``_open_menu_click_item``: the
    ``QMessageBox`` opens inside ``clear_diagnostics``'s synchronous
    ``exec()``, and the capture ``singleShot`` fires *inside* that nested
    modal loop. A dialog-hang watchdog guards against the click missing its
    target.
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from valisync.gui import strings as S

    px, py = phys
    captured: dict[str, object] = {}
    loop = QEventLoop()

    def _do_click_clear() -> None:
        at(px, py, LDOWN)
        at(px, py, LUP)
        # clear_diagnostics()'s QMessageBox.exec() opens here synchronously
        # (real modal loop) — _capture_and_click_yes (a later singleShot)
        # runs inside it.

    def _capture_and_click_yes() -> None:
        box = QApplication.activeModalWidget()
        captured["type"] = type(box).__name__ if box is not None else None
        with contextlib.suppress(Exception):
            QApplication.primaryScreen().grabWindow(0).save(str(shot_dialog))
        if isinstance(box, QMessageBox):
            yes_button = box.button(QMessageBox.StandardButton.Yes)
            captured["yes_text"] = yes_button.text() if yes_button is not None else None
            if yes_button is not None:
                dpr = box.devicePixelRatioF()
                gp = yes_button.mapToGlobal(yes_button.rect().center())
                hx, hy = round(gp.x() * dpr), round(gp.y() * dpr)
                at(hx, hy, LDOWN)
                at(hx, hy, LUP)
                # Firing at the rect is NOT proof it landed/dismissed the
                # dialog (exec() may still be blocked; see
                # _dialog_hang_watchdog). The real evidence is the per-test
                # effect assertion.
                captured["clicked"] = True
        loop.quit()

    stop = threading.Event()
    watchdog = threading.Thread(target=_dialog_hang_watchdog, args=(stop,), daemon=True)
    watchdog.start()

    QTimer.singleShot(300, _do_click_clear)
    QTimer.singleShot(900, _capture_and_click_yes)
    QTimer.singleShot(5000, loop.quit)  # outer safety net
    loop.exec()

    # loop.exec() returned -> any nested QMessageBox.exec() already unwound;
    # stop the watchdog before it can fire a stray Escape at a later test.
    stop.set()
    watchdog.join(timeout=2.0)
    captured["confirm_title"] = S.DIAG_CLEAR_CONFIRM_TITLE  # sanity anchor
    return captured


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
    # DiagnosticsView alone (not the full MainWindow) — same precedent as
    # test_diagnostics_dock_realinput.py.
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 80, screen.y() + 80, 520, 300)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    return vm, view


def test_real_click_clear_opens_dialog_and_confirm_empties(
    qtbot: QtBot, tmp_path
) -> None:
    """Real click on Clear -> real confirm dialog -> real click "クリア" ->
    table empty + placeholder + counts 0/0/0."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    from valisync.gui import strings as S

    vm, view = _show_view(qtbot)
    assert view.row_count() == 2

    center = view._btn_clear.rect().center()
    gp = view._btn_clear.mapToGlobal(center)
    dpr = view.devicePixelRatioF()
    phys = (round(gp.x() * dpr), round(gp.y() * dpr))

    shot_dialog = tmp_path / "diag_clear_confirm_dialog.png"
    captured = _click_clear_then_confirm(view, phys, shot_dialog)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "diag_clear_after.png")
        )

    assert captured.get("type") == "QMessageBox", (
        "real click on Clear did not raise the confirm dialog "
        f"(got {captured.get('type')!r}). screenshot: {shot_dialog}"
    )
    assert captured.get("yes_text") == S.DIAG_CLEAR_CONFIRM_YES, (
        f"confirm dialog's Yes button was not relabelled: {captured.get('yes_text')!r}"
    )
    assert captured.get("clicked"), (
        "real click on the confirm dialog's 'クリア' button failed to fire"
    )
    assert view.row_count() == 0
    assert vm.entries() == []
    assert view._stack.currentWidget() is view._placeholder
    # D-3: counts are now an icon+number HBox per level (view._count_value_labels),
    # not a single emoji-glyph label.
    assert {lvl: lbl.text() for lvl, lbl in view._count_value_labels.items()} == {
        "error": "0",
        "warning": "0",
        "info": "0",
    }
