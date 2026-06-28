"""Layer C: real-OS-input E2E for Y-axis height preservation on file unload.

Opt-in — run with ``--realgui`` on Windows + a real display::

    uv run pytest --realgui tests/realgui/test_remove_file_preserves_proportions.py -q

It (1) real-drags a region divider on a GraphPanelView to make the regions
non-equal, then (2) issues a genuine right-click on a FileBrowserView row and
triggers "Remove File", and asserts the surviving graph regions keep their
relative heights. The divider drag is a plain pyqtgraph mouse drag (no QDrag/OLE
modal loop), so it is driven inline with processEvents — no background thread is
needed. Excluded from CI — see docs/gui-testing-layers.md (Layer C).

Note: hijacks the mouse cursor for ~2 s. Coordinates/timing are environment
sensitive; on a miss inspect the screenshots saved under tmp_path.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.realgui

_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010


def test_remove_file_preserves_graph_panel_proportions(
    qtbot: QtBot, tmp_path: Path
) -> None:
    if sys.platform != "win32":
        pytest.skip("real OS input uses Win32 mouse_event (Windows-only)")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMenu

    if QGuiApplication.platformName() == "offscreen":
        pytest.skip(
            "requires a real display — run: uv run pytest --realgui tests/realgui/"
        )

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.file_browser_view import FileBrowserView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    user32 = ctypes.windll.user32

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

    # ─── App + 3 single-signal files (3 regions; middle file gets removed) ─────
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

    # ─── GraphPanelView (for the real divider drag) ───────────────────────────
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
            bool(gpv._dividers)  # type: ignore[attr-defined]
            and gpv._dividers[0].sceneBoundingRect().width() > 0
        ),  # type: ignore[attr-defined]
        timeout=3000,
    )

    dpr = gpv.devicePixelRatioF()

    def _phys(global_pt: object) -> tuple[int, int]:
        return round(global_pt.x() * dpr), round(global_pt.y() * dpr)  # type: ignore[attr-defined]

    # Divider 0 sits between region 0 and region 1. Drag it UP to shrink region 0,
    # producing non-equal heights we can later check survive the file removal.
    div = gpv._dividers[0]  # type: ignore[attr-defined]
    scene_c = div.sceneBoundingRect().center()
    vp = gpv.plot_widget.mapFromScene(scene_c)  # type: ignore[attr-defined]
    start_global = gpv.plot_widget.viewport().mapToGlobal(vp)  # type: ignore[attr-defined]
    sx, sy = _phys(start_global)
    drag_px = round(gpv.height() * 0.18 * dpr)  # move up ~18% of the panel height

    def _at(x: int, y: int, flag: int) -> None:
        user32.SetCursorPos(int(x), int(y))
        user32.mouse_event(flag, 0, 0, 0, 0)

    _at(sx, sy, _MOUSEEVENTF_LEFTDOWN)
    QApplication.processEvents()
    for step in range(1, 6):  # incremental moves so pyqtgraph emits drag deltas
        _at(sx, sy - round(drag_px * step / 5), _MOUSEEVENTF_MOVE)
        QApplication.processEvents()
        time.sleep(0.03)
    _at(sx, sy - drag_px, _MOUSEEVENTF_LEFTUP)
    for _ in range(3):
        QApplication.processEvents()

    # Region 0 must now differ from region 1 (the drag actually moved heights).
    heights_before = [
        a.height_ratio for a in sorted(panel.axes, key=lambda a: a.top_ratio)
    ]
    assert abs(heights_before[0] - heights_before[1]) > 0.02, (
        "real divider drag did not change region heights; "
        f"got {heights_before}. Tune coords/timing — see tmp_path screenshots."
    )

    # ─── FileBrowserView (for the real Remove File right-click) ───────────────
    fbv = FileBrowserView(FileBrowserVM(app))
    qtbot.addWidget(fbv)
    fbv.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    fbv.setGeometry(840, 120, 360, 240)
    fbv.show()
    qtbot.waitExposed(fbv)
    # file_b is the 2nd loaded → row index 1 in loaded_file_keys order.
    row = app.loaded_file_keys.index(file_b)
    qtbot.waitUntil(
        lambda: fbv.list_view.visualRect(fbv.model.index(row, 0)).height() > 0,
        timeout=3000,
    )

    lv = fbv.list_view
    center = lv.visualRect(fbv.model.index(row, 0)).center()
    rx, ry = _phys(lv.viewport().mapToGlobal(center))

    # Real right-click opens the context menu; then trigger "Remove File".
    _at(rx, ry, _MOUSEEVENTF_RIGHTDOWN)
    user32.mouse_event(_MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    qtbot.waitUntil(
        lambda: isinstance(QApplication.activePopupWidget(), QMenu), timeout=3000
    )
    menu = QApplication.activePopupWidget()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "menu.png"))
    remove_action = next(a for a in menu.actions() if a.text() == "Remove File")
    remove_action.trigger()
    menu.close()
    for _ in range(3):
        QApplication.processEvents()

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "after.png"))

    # ─── Assert: middle region pruned, survivors keep their relative heights ──
    assert len(panel.axes) == 2, (
        f"expected 2 regions after Remove File, got {len(panel.axes)}. "
        f"Screenshots: {tmp_path}"
    )
    cols = sorted(panel.axes, key=lambda a: a.top_ratio)
    ratio_before = heights_before[0] / heights_before[2]
    ratio_after = cols[0].height_ratio / cols[1].height_ratio
    assert ratio_after == pytest.approx(ratio_before, rel=0.05), (
        "surviving regions did not keep their relative heights after removal; "
        f"before={heights_before}, after={[c.height_ratio for c in cols]}. "
        f"Screenshots: {tmp_path}"
    )
    assert len(gpv._view_boxes) == 2  # type: ignore[attr-defined]
