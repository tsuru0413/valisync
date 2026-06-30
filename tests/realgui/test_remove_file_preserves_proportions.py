"""Layer C: real-OS-input E2E for Y-axis height preservation on file unload.

Opt-in — run with ``--realgui`` on Windows + a real display::

    uv run pytest --realgui tests/realgui/test_remove_file_preserves_proportions.py -q

It (1) makes the three regions non-equal via ``resize_axis_edge`` (the coupled
region divider was removed with the active-axis model; the height setup is just
scaffolding — the load-bearing Layer C subject is the file removal), then (2)
issues a genuine right-click on a FileBrowserView row and triggers "Remove File",
and asserts rendered geometry (strip fractions + blank-band absence), not VM
height_ratio: survivors keep their absolute RENDERED strips and the removed middle
band is genuinely blank in the scene.

Robustness for unattended runs: each window is forced to the foreground before
real input is sent (so clicks land on the intended widget, not whatever is under
the cursor), and a background watchdog thread blasts ESC + button-release after a
deadline so a stray real click that opens an OS-native modal can never hang the
run — it fails cleanly instead. faulthandler dumps every thread's stack if the
test exceeds its budget, to pinpoint a block.

Excluded from CI — see docs/gui-testing-layers.md (Layer C). Hijacks the mouse
cursor for ~2 s. Coordinates/timing are environment sensitive; on a miss inspect
the screenshots saved under tmp_path.
"""

from __future__ import annotations

import contextlib
import ctypes
import faulthandler
import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    KEYUP,
    LUP,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
)

pytestmark = pytest.mark.realgui

# Right-click constants not in shared helper
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_ASFW_ANY = -1


def test_remove_file_preserves_graph_panel_proportions(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()

    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.file_browser_view import FileBrowserView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    user32 = ctypes.windll.user32

    # Background safety net: if the main thread blocks (e.g. a stray real click
    # opened an OS-native modal that processEvents cannot exit), this releases
    # ESC + all mouse buttons so the block returns and the test fails cleanly
    # instead of hanging the machine.
    abort = threading.Event()

    def _watchdog() -> None:
        if not abort.wait(timeout=30.0):
            user32.keybd_event(VK_ESCAPE, 0, 0, 0)
            user32.keybd_event(VK_ESCAPE, 0, KEYUP, 0)
            user32.mouse_event(LUP, 0, 0, 0, 0)
            user32.mouse_event(_MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

    wd = threading.Thread(target=_watchdog, daemon=True)
    wd.start()
    # Dump all thread stacks if we blow the budget, so any block is diagnosable
    # in the test log (fires before the watchdog so the stack is still blocked).
    faulthandler.dump_traceback_later(25, exit=False)

    def _foreground(widget: object) -> None:
        """Bring *widget* to the foreground so real clicks land on it."""
        widget.activateWindow()  # type: ignore[attr-defined]
        widget.raise_()  # type: ignore[attr-defined]
        QApplication.processEvents()
        with contextlib.suppress(Exception):
            user32.AllowSetForegroundWindow(_ASFW_ANY)
            user32.SetForegroundWindow(int(widget.winId()))  # type: ignore[attr-defined]
        QApplication.processEvents()
        time.sleep(0.15)

    try:

        def _fmt() -> FormatDefinition:
            return FormatDefinition(
                name="fmt",
                delimiter=Delimiter.COMMA,
                timestamp_column=0,
                timestamp_unit="sec",
                signal_start_column=1,
                signal_end_column=1,
                has_header=True,
            )

        def _write_csv(path: Path) -> Path:
            lines = ["t,s1"]
            for i in range(50):
                lines.append(f"{i * 0.01:.3f},{float(i % 50):.1f}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path

        # ─── App + 3 single-signal files (3 regions; middle file removed) ──────
        app = AppViewModel()
        seen: set[str] = set()

        def _load(name: str) -> tuple[str, str]:
            key = app.request_load(_write_csv(tmp_path / name), _fmt())
            sig = (set(s.name for s in app.signals()) - seen).pop()
            seen.add(sig)
            return key, sig

        _, sig_a = _load("a.csv")
        file_b, sig_b = _load("b.csv")
        _, sig_c = _load("c.csv")

        area = GraphAreaVM(app)
        panel = area.panels(0)[0]
        panel.create_new_axis(sig_a)  # axis 0 (top)
        panel.create_new_axis(sig_b)  # axis 1 (middle, file_b)
        panel.create_new_axis(sig_c)  # axis 2 (bottom)

        # ─── GraphPanelView (for the real divider drag) ───────────────────────
        gpv = GraphPanelView(panel)
        qtbot.addWidget(gpv)
        gpv.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        gpv.setGeometry(120, 120, 700, 600)
        gpv.show()
        qtbot.waitExposed(gpv)
        QApplication.processEvents()
        QApplication.processEvents()
        qtbot.waitUntil(
            lambda: (
                len(gpv._y_axes) == 3  # type: ignore[attr-defined]
                and gpv._view_boxes[0].sceneBoundingRect().height() > 100  # type: ignore[attr-defined]
            ),
            timeout=3000,
        )
        _foreground(gpv)

        dpr = gpv.devicePixelRatioF()

        def _phys(global_pt: object) -> tuple[int, int]:
            return round(global_pt.x() * dpr), round(global_pt.y() * dpr)  # type: ignore[attr-defined]

        # Make the regions non-equal: shrink the top region via per-axis resize
        # (model B) so its bottom edge moves up, opening a gap below it. The coupled
        # divider this test used to drag was removed with the active-axis model; the
        # height setup is scaffolding — the load-bearing real-input step is the
        # right-click "Remove File" further down.
        panel.resize_axis_edge(0, "bottom", -0.13)
        for _ in range(3):
            QApplication.processEvents()

        # Region 0 must now differ from region 1 (the resize actually applied).
        heights_before = [
            a.height_ratio for a in sorted(panel.axes, key=lambda a: a.top_ratio)
        ]
        with contextlib.suppress(Exception):
            QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "setup.png"))
        assert abs(heights_before[0] - heights_before[1]) > 0.02, (
            "resize_axis_edge did not change region heights; "
            f"got {heights_before}. See {tmp_path / 'setup.png'}."
        )

        # ─── FileBrowserView (for the real Remove File right-click) ───────────
        fbv = FileBrowserView(FileBrowserVM(app))
        qtbot.addWidget(fbv)
        fbv.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        fbv.setGeometry(840, 120, 360, 240)
        fbv.show()
        qtbot.waitExposed(fbv)
        # file_b is the 2nd loaded → its row in loaded_file_keys order.
        row = app.loaded_file_keys.index(file_b)
        qtbot.waitUntil(
            lambda: fbv.list_view.visualRect(fbv.model.index(row, 0)).height() > 0,
            timeout=3000,
        )
        _foreground(fbv)

        lv = fbv.list_view
        center = lv.visualRect(fbv.model.index(row, 0)).center()
        rx, ry = _phys(lv.viewport().mapToGlobal(center))

        # The FileBrowser context menu opens via a modal ``QMenu.exec`` (its own
        # nested event loop), so it cannot be observed from an outer
        # ``waitUntil`` — the menu must be captured by a QTimer that fires INSIDE
        # the modal loop. This mirrors tests/realgui/test_file_browser_realclick.py.
        captured: dict[str, object] = {}
        loop = QEventLoop()

        def _do_right_click() -> None:
            at(rx, ry, _MOUSEEVENTF_RIGHTDOWN)
            user32.mouse_event(_MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            # The modal menu opens here; _capture() (a later singleShot) runs
            # inside that loop.

        def _capture() -> None:
            popup = QApplication.activePopupWidget()
            with contextlib.suppress(Exception):
                QApplication.primaryScreen().grabWindow(0).save(
                    str(tmp_path / "menu.png")
                )
            if isinstance(popup, QMenu):
                captured["actions"] = [a.text() for a in popup.actions()]
                for a in popup.actions():
                    if a.text() == "Remove File":
                        a.trigger()
                        captured["triggered"] = True
                        break
                popup.close()
            loop.quit()

        QTimer.singleShot(200, _do_right_click)
        QTimer.singleShot(800, _capture)
        QTimer.singleShot(5000, loop.quit)  # safety net
        loop.exec()

        assert captured.get("triggered"), (
            "real right-click did not open a 'Remove File' menu; "
            f"popup actions={captured.get('actions')}. Screenshots: {tmp_path}"
        )
        for _ in range(3):
            QApplication.processEvents()

        with contextlib.suppress(Exception):
            QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "after.png"))

        # ─── Assert: middle region pruned; blank gap rendered in scene ─────────
        assert len(panel.axes) == 2, (
            f"expected 2 regions after Remove File, got {len(panel.axes)}. "
            f"Screenshots: {tmp_path}"
        )
        # RENDERED geometry (NOT VM height_ratio): survivors keep their absolute
        # strips and the removed middle band is genuinely blank. The prior
        # height_ratio/sum asserts were the false-green — the VM computed the gap
        # but the View never painted it.
        for _ in range(3):
            QApplication.processEvents()
        qtbot.waitUntil(
            lambda: (
                len(gpv._y_axes) == 2  # type: ignore[attr-defined]
                and gpv._view_boxes[0].sceneBoundingRect().height() > 100
            ),  # type: ignore[attr-defined]
            timeout=3000,
        )
        R = gpv._view_boxes[0].sceneBoundingRect()  # type: ignore[attr-defined]

        def _strip(i: int) -> tuple[float, float]:
            r = gpv._y_axes[i].sceneBoundingRect()  # type: ignore[attr-defined]
            return ((r.y() - R.y()) / R.height(), r.height() / R.height())

        rendered = sorted(_strip(i) for i in range(len(gpv._y_axes)))  # type: ignore[attr-defined]
        (top_top, top_h), (bot_top, bot_h) = rendered
        # Survivors keep their absolute heights as RENDERED strip fractions
        # (top == heights_before[0]; bottom == heights_before[2]).
        assert top_h == pytest.approx(heights_before[0], abs=0.04), (
            f"top survivor not rendered at its absolute height: {top_h} != "
            f"{heights_before[0]}. Screenshots: {tmp_path}"
        )
        assert bot_h == pytest.approx(heights_before[2], abs=0.04), (
            f"bottom survivor not rendered at its absolute height: {bot_h} != "
            f"{heights_before[2]}. Screenshots: {tmp_path}"
        )
        # Removed middle band is blank: a real gap is rendered between survivors
        # and no spine paints inside it.
        gap_lo = R.y() + (top_top + top_h) * R.height()
        gap_hi = R.y() + bot_top * R.height()
        assert gap_hi - gap_lo > 0.05 * R.height(), (
            f"no blank band rendered between survivors (gap collapsed). "
            f"Screenshots: {tmp_path}"
        )
        mid = gap_lo + 0.5 * (gap_hi - gap_lo)
        for i in range(len(gpv._y_axes)):  # type: ignore[attr-defined]
            r = gpv._y_axes[i].sceneBoundingRect()  # type: ignore[attr-defined]
            assert not (r.y() < mid < r.y() + r.height()), (
                f"a spine paints inside the blank band. Screenshots: {tmp_path}"
            )
        assert len(gpv._view_boxes) == 2  # type: ignore[attr-defined]
    finally:
        faulthandler.cancel_dump_traceback_later()
        abort.set()
        wd.join(timeout=2.0)
