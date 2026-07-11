"""Layer C: real-OS-input GUI test for cross-panel axis drag (panel0 -> panel1).

Opt-in -- run with ``--realgui``. Requires a real display + Windows: it presses
the physical left mouse button over the frame zone of panel0's axis-0 spine and
drags to panel1's plot centre via Win32 ``mouse_event``, then asserts that the
axis (and its signal) moved to panel1 and left panel0.

This is the only tier that exercises the full OS -> pyqtgraph -> QDrag ->
cross-widget dropEvent -> GraphAreaView wiring chain that synthetic events cannot:

  1. Real WM_LBUTTONDOWN on the FRAME band of panel0's AxisItem.
  2. WM_MOUSEMOVE events cross pyqtgraph's 4-px threshold ->
     ``_AlignedAxisItem.mouseDragEvent`` fires with ``isStart()==True``.
  3. Zone = AXZONE_FRAME -> ``QDrag.exec`` starts and blocks the GUI thread
     inside Windows' OLE ``DoDragDrop`` modal loop.
  4. More WM_MOUSEMOVE events drive the cursor across the QSplitter boundary
     to panel1's widget; panel1's ``dragEnterEvent`` accepts AXIS_INDEX_MIME.
  5. WM_LBUTTONUP -> panel1's ``dropEvent`` -> ``cross_panel_axis_move_requested``
     (deferred via QTimer.singleShot(0)) -> GraphAreaView._wire_panel -> VM.
  6. VM removes the axis from panel0 and inserts it into panel1; both panel
     views refresh() their _items -> panel1.signal_keys_drawn() gains k0.

A watchdog (ESC + LEFTUP after 3 s) guarantees the drag never hangs the machine
even if the synthetic drop fails to complete.

Excluded from the default run and CI -- see ``.claude/skills/gui-verify/`` (Layer C).

Run deliberately (e.g. before release, or after touching axis-move / drag routing)
on a Windows machine with a real display::

    uv run pytest --realgui tests/realgui/

Note: this hijacks the mouse cursor for ~3 s while it runs.  Real-drag behaviour
is unverified in headless / offscreen mode; confirm with the above command on a
real Windows display.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import drive_qdrag, skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_axis_drag_cross_panel(qtbot: QtBot, tmp_path: Path) -> None:
    """Drag panel0's axis-0 (frame zone) across the QSplitter boundary to panel1.

    Verifies the full cross-panel axis-move chain end-to-end:
      * real left-press on the FRAME band of panel0's _y_axes[0] spine
      * WM_MOUSEMOVE crosses pyqtgraph's 4-px drag threshold ->
        _AlignedAxisItem.mouseDragEvent starts QDrag.exec
      * cursor moves cross the QSplitter boundary to panel1's widget area
      * panel1.dragEnterEvent accepts AXIS_INDEX_MIME; dragMoveEvent accepts
      * WM_LBUTTONUP -> panel1.dropEvent decodes source_panel=0 != self._panel_index=1
        -> QTimer.singleShot(0) emits cross_panel_axis_move_requested(0, 0, col, pos)
      * GraphAreaView._wire_panel lambda -> GraphAreaVM.move_axis_across_panels
      * VM: src.extract_axis(0) + dst.insert_axis(...) -> both panel VMs notify
      * panel0.refresh() removes k0 from _items; panel1.refresh() adds k0 to _items
      * Assertions: k0 in panel1.signal_keys_drawn() AND k0 not in panel0.signal_keys_drawn()
    """
    skip_unless_real_display()

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.graph_area_view import GraphAreaView

    # ─── Session with two signals ──────────────────────────────────────────────
    def _write_tiny_csv(path: Path) -> Path:
        lines = ["t,s1,s2"]
        for i in range(50):
            t = i * 0.01
            lines.append(f"{t:.3f},{float(i % 50):.1f},{float((i * 2) % 50):.1f}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    csv = _write_tiny_csv(tmp_path / "data.csv")
    session = Session()
    session.load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=2,
            has_header=True,
        ),
    )
    signal_keys = sorted(s.name for s in session.signals())
    k0, k1 = signal_keys[0], signal_keys[1]

    # ─── ViewModel: one tab, two panels; panel0 has 2 axes ────────────────────
    area_vm = GraphAreaVM(AppViewModel(session))
    area_vm.add_panel(0)  # tab 0 now has 2 panels (panel0 default + panel1 empty)
    p0_vm, p1_vm = area_vm.panels(0)[0], area_vm.panels(0)[1]
    p0_vm.add_signal_to_axis(k0, 0)  # fills placeholder -> axis 0 = k0
    p0_vm.create_new_axis(k1)  # axis 1 = k1

    assert len(p0_vm.axes) == 2
    assert len(p1_vm.axes) == 1  # placeholder only
    assert k0 in [e.signal_key for e in p0_vm._plotted]

    # ─── View: GraphAreaView with 2-panel splitter ────────────────────────────
    # GraphAreaView._rebuild() populates tabs.widget(0) as a QSplitter with
    # two GraphPanelView children: splitter.widget(0) = panel0, .widget(1) = panel1.
    view = GraphAreaView(area_vm)
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # Wide + tall geometry so both panels are visible in the vertical splitter.
    view.setGeometry(100, 100, 1200, 700)
    view.show()
    qtbot.waitExposed(view)
    # Two processEvents passes let pyqtgraph compute initial item geometry.
    QApplication.processEvents()
    QApplication.processEvents()

    # Reach panel widgets via the QSplitter (confirmed: view.tabs.widget(0) is the
    # QSplitter; .widget(0) and .widget(1) are GraphPanelView instances).
    splitter = view.tabs.widget(0)
    panel0 = splitter.widget(0)
    panel1 = splitter.widget(1)

    # Wait for panel0's first axis spine to have a non-zero scene bounding rect
    # (confirms the pyqtgraph layout has settled before we query coordinates).
    qtbot.waitUntil(
        lambda: panel0._y_axes[0].sceneBoundingRect().width() > 0,  # type: ignore[attr-defined]
        timeout=3000,
    )

    # Activate panel0's axis 0 -- the frame QDrag only launches from an active axis
    # (_begin_axis_drag rejects non-active). Mirror test_multi_column_axis.py.
    panel0.set_active_axis(0)  # type: ignore[attr-defined]
    QApplication.processEvents()

    # ─── DPI conversion factor (logical -> physical pixels) ───────────────────
    dpr = view.devicePixelRatioF()

    # ─── Source: FRAME zone of panel0._y_axes[0] (spine left edge, vertical centre)
    # _AlignedAxisItem.FRAME = 8 px; pressing at x=spine.x()+2 reliably lands in
    # the frame band (lx=2 < FRAME=8) regardless of spine width.
    src_item = panel0._y_axes[0]  # type: ignore[attr-defined]
    _src_rect = src_item.sceneBoundingRect()
    scene_src = QPoint(int(_src_rect.x() + 2), int(_src_rect.center().y()))
    src_vp = panel0.plot_widget.mapFromScene(scene_src)  # type: ignore[attr-defined]
    src_global = panel0.plot_widget.viewport().mapToGlobal(src_vp)  # type: ignore[attr-defined]
    src_phys_x = round(src_global.x() * dpr)
    src_phys_y = round(src_global.y() * dpr)

    # ─── Target: centre of panel1's widget ────────────────────────────────────
    # panel1 is a GraphPanelView below panel0 in the vertical QSplitter.
    # Dropping at panel1.width()//2, panel1.height()//2 lands in its plot area;
    # panel1.dragEnterEvent accepts AXIS_INDEX_MIME and panel1.dropEvent fires.
    panel1_center_logi = panel1.mapToGlobal(
        QPoint(panel1.width() // 2, panel1.height() // 2)
    )
    tgt_phys_x = round(panel1_center_logi.x() * dpr)
    tgt_phys_y = round(panel1_center_logi.y() * dpr)

    # Intermediate waypoint: halfway between source and target for a smooth path.
    mid_phys_x = (src_phys_x + tgt_phys_x) // 2
    mid_phys_y = (src_phys_y + tgt_phys_y) // 2

    # ─── Real-OS QDrag driven by shared helper ────────────────────────────────
    # done() waits until the QTimer.singleShot(0) fires inside the pump loop,
    # which lets the VM and panel1 view refresh before done() returns True.
    drive_qdrag(
        (src_phys_x, src_phys_y),
        [(mid_phys_x, mid_phys_y), (tgt_phys_x, tgt_phys_y)],
        done=lambda: k0 in panel1.signal_keys_drawn(),  # type: ignore[attr-defined]
    )

    # Settle the event loop: the QTimer.singleShot(0) in dropEvent may need one
    # more processEvents to fire cross_panel_axis_move_requested and propagate
    # the VM -> view notify -> refresh() -> _items update.
    for _ in range(5):
        QApplication.processEvents()

    # Screenshot (best-effort; saved for debugging if the assertion fails).
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "after_cross_panel_drag.png")
        )

    # ─── Assertions ───────────────────────────────────────────────────────────
    # k0 must have moved INTO panel1 and be GONE from panel0.
    assert k0 in panel1.signal_keys_drawn(), (  # type: ignore[attr-defined]
        f"k0 ({k0!r}) did not appear in panel1 after cross-panel drag -- "
        f"the real-OS QDrag may not have reached panel1.dropEvent. "
        f"Screenshots saved to {tmp_path}"
    )
    assert k0 not in panel0.signal_keys_drawn(), (  # type: ignore[attr-defined]
        f"k0 ({k0!r}) is still in panel0 after cross-panel drag -- "
        f"VM.move_axis_across_panels may not have removed it from the source. "
        f"Screenshots saved to {tmp_path}"
    )
