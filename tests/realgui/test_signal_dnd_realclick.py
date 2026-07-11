"""Layer C: real-OS-input tests for signal drag-and-drop from ChannelBrowser to GraphPanel.

Opt-in — run with ``--realgui`` on Windows + a real display. Drives a genuine
QDrag from a ChannelBrowser tree row (Qt's built-in startDrag) and drops it on a
GraphPanel zone, exercising the OS → QDrag.exec → dropEvent child→parent bubbling
that a synthesized event cannot reproduce (memory gui_drag_drop_not_sendevent_reproducible).
The QDrag is driven from a background OS thread with a watchdog (drive_qdrag) so
the OLE modal loop cannot hang the machine. See .claude/skills/gui-verify/ (Layer C).
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    VK_CONTROL,
    drive_qdrag,
    skip_unless_real_display,
)

pytestmark = pytest.mark.realgui


def _fmt():
    from valisync.core.models import Delimiter, FormatDefinition

    return FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )


def _make_browser_and_panel(qtbot: QtBot, tmp_path: Path):
    """Build a ChannelBrowser (drag source) + GraphPanel (drop target) sharing one
    session, shown side by side. Returns (browser, panel, keys) where keys are the
    browser's signal keys in row order (also valid in the panel's VM because both
    widgets share the same Session via app_vm.session)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.channel_browser_view import ChannelBrowserView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    # _CapturingPanel is defined here to defer the GraphPanelView import
    # (all realgui helpers keep heavy imports inside functions so collection
    # under offscreen never touches real-display-dependent code paths).
    class _CapturingPanel(GraphPanelView):
        drop_seen: bool = False

        def dropEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dropEvent(ev)  # type: ignore[arg-type]
            self.drop_seen = True

    csv = tmp_path / "d.csv"
    csv.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    file_key = app_vm.request_load(csv, _fmt())
    app_vm.set_active_file(file_key)

    browser = ChannelBrowserView(ChannelBrowserVM(app_vm))
    # Share the SAME session so the browser's namespaced keys (e.g. "csv_1::a")
    # resolve in the panel's VM: GraphPanelVM._signal_map() looks up by sig.name
    # from the session, and ChannelBrowserVM uses the same session via app_vm.
    panel = _CapturingPanel(GraphPanelVM(app_vm.session))
    qtbot.addWidget(browser)
    qtbot.addWidget(panel)
    for w, x in ((browser, 200), (panel, 640)):
        w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        w.setGeometry(x, 250, 400, 360)
        w.show()
        qtbot.waitExposed(w)
    qtbot.waitUntil(
        lambda: browser.tree.visualRect(browser.proxy.index(0, 0)).height() > 0,
        timeout=3000,
    )
    QApplication.processEvents()
    QApplication.processEvents()
    # browser.model is SignalTableModel; signal_key_at returns the namespaced key
    # (e.g. "csv_1::a") for a given QModelIndex — confirmed in qt_signal_models.py.
    keys = [browser.model.signal_key_at(browser.model.index(r, 0)) for r in range(2)]
    return browser, panel, keys


def _row_phys(browser, row: int) -> tuple[int, int]:
    """Physical-pixel center of a ChannelBrowser tree row."""
    idx = browser.proxy.index(row, 0)
    dpr = browser.devicePixelRatioF()
    center = browser.tree.visualRect(idx).center()
    gp = browser.tree.viewport().mapToGlobal(center)
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _panel_point_phys(panel, lx: int, ly: int) -> tuple[int, int]:
    """Physical-pixel of a logical (lx, ly) point in the panel's widget space."""
    from PySide6.QtCore import QPoint

    dpr = panel.devicePixelRatioF()
    gp = panel.mapToGlobal(QPoint(lx, ly))
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _select_rows(browser, rows: list[int]) -> None:
    from PySide6.QtCore import QItemSelectionModel

    sm = browser.tree.selectionModel()
    sm.clearSelection()
    flag = (
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows
    )
    for r in rows:
        sm.select(browser.model.index(r, 0), flag)


def test_drop_on_plot_creates_new_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """H1: drag signal row → drop on plot centre (ZONE_PLOT) → a new axis appears."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)
    assert keys[0], "browser produced no signal key for row 0"
    n_before = len(panel.vm.axes)

    _select_rows(browser, [0])
    QApplication.processEvents()

    press = _row_phys(browser, 0)
    target = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "h1.png"))

    assert panel.drop_seen, (
        f"no dropEvent on the panel — real QDrag never completed. screenshot: {tmp_path / 'h1.png'}"
    )
    # panel.signal_keys_drawn() (GraphPanelView method) returns the signal_keys of
    # PlotDataItems currently drawn — confirmed in graph_panel_view.py. curve_keys()
    # now returns entry_ids (PC-01), so signal_key membership goes through this
    # instead. Note: no equivalent exists on GraphPanelVM; the VM uses _plotted
    # internally.
    qtbot.waitUntil(lambda: keys[0] in panel.signal_keys_drawn(), timeout=2000)
    assert len(panel.vm.axes) >= max(1, n_before), "no axis holds the dropped signal"


# ---------------------------------------------------------------------------
# H2 / H3 helpers
# ---------------------------------------------------------------------------


def _prepare_one_axis(panel, keys: list[str], qtbot: QtBot) -> None:
    """Plot keys[0] onto a fresh axis so a Y-band overwrite/join target exists."""
    from PySide6.QtWidgets import QApplication

    panel.vm.create_new_axis(keys[0])
    for _ in range(3):
        QApplication.processEvents()
    # signal_keys_drawn() is a GraphPanelView method — confirmed in graph_panel_view.py.
    qtbot.waitUntil(lambda: keys[0] in panel.signal_keys_drawn(), timeout=2000)


def _y_band_phys(panel, axis_index: int) -> tuple[int, int]:
    """Physical pixel inside the Y gutter band of axis_index (a Y zone —
    ZONE_Y_INNER or ZONE_Y_OUTER; dropEvent routes BOTH identically to the
    overwrite/join branch, so either is correct for H2/H3).

    The point sits inside the per-column gutter (x < plot_rect.left()); the exact
    inner/outer split (classify_zone, graph_panel_view.py:143-147) does not change
    the routing, and _axis_index_at recovers the column via the same //72 math.

    YAxisVM attrs confirmed (y_axis_vm.py): top_ratio, height_ratio, column.
    _Y_AXIS_FIXED_WIDTH=72 confirmed (graph_panel_view.py:89).
    """
    from valisync.gui.views.graph_panel_view import _Y_AXIS_FIXED_WIDTH

    ax = panel.vm.axes[axis_index]
    # Inside the column's gutter (closer to the plot half) → a Y zone.
    lx = int(_Y_AXIS_FIXED_WIDTH * (ax.column + 0.75))
    ly = int((ax.top_ratio + ax.height_ratio / 2) * panel.height())
    return _panel_point_phys(panel, lx, ly)


# ---------------------------------------------------------------------------
# H2: Y-band drop → overwrite
# ---------------------------------------------------------------------------


def test_drop_on_y_band_overwrites_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """H2: drop a 2nd signal on an existing axis's Y band (no Ctrl) → overwrite."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)
    _prepare_one_axis(panel, keys, qtbot)  # keys[0] on axis 0

    _select_rows(browser, [1])
    QApplication.processEvents()
    press = _row_phys(browser, 1)
    target = _y_band_phys(panel, 0)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "h2.png"))

    assert panel.drop_seen, f"no dropEvent. screenshot: {tmp_path / 'h2.png'}"
    # Overwrite: axis 0 now holds keys[1] and NOT keys[0].
    qtbot.waitUntil(lambda: keys[1] in panel.signal_keys_drawn(), timeout=2000)
    assert keys[0] not in panel.signal_keys_drawn(), (
        f"overwrite did not replace the original signal. screenshot: {tmp_path / 'h2.png'}"
    )


# ---------------------------------------------------------------------------
# H3: Y-band Ctrl drop → join
# ---------------------------------------------------------------------------


def test_ctrl_drop_on_y_band_joins_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """H3: Ctrl-held drop on an existing axis's Y band → join (both signals kept)."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)
    _prepare_one_axis(panel, keys, qtbot)  # keys[0] on axis 0

    _select_rows(browser, [1])
    QApplication.processEvents()
    press = _row_phys(browser, 1)
    target = _y_band_phys(panel, 0)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(
        press, [mid, target], done=lambda: panel.drop_seen, modifier_vk=VK_CONTROL
    )

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "h3.png"))

    assert panel.drop_seen, f"no dropEvent. screenshot: {tmp_path / 'h3.png'}"
    # Join: BOTH signals present on the axis.
    qtbot.waitUntil(
        lambda: (
            keys[0] in panel.signal_keys_drawn()
            and keys[1] in panel.signal_keys_drawn()
        ),
        timeout=2000,
    )


# ---------------------------------------------------------------------------
# H4: multi-select → bulk add
# ---------------------------------------------------------------------------


def test_multiselect_drop_on_plot_adds_all(qtbot: QtBot, tmp_path: Path) -> None:
    """H4: Ctrl/Shift multi-select two rows → one drag → both signals added.

    _select_rows sets QItemSelectionModel selection for both rows before the drag.
    Qt's built-in QAbstractItemView.startDrag() builds the mimeData from
    selectedIndexes(), so both keys are encoded in the mime payload and a single
    QDrag carries them both to the dropEvent.
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)

    _select_rows(browser, [0, 1])  # both rows selected → mime carries both keys
    QApplication.processEvents()
    press = _row_phys(browser, 0)  # press on a selected row
    target = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "h4.png"))

    assert panel.drop_seen, f"no dropEvent. screenshot: {tmp_path / 'h4.png'}"
    # Both keys must appear because the mime payload carried both selected rows.
    qtbot.waitUntil(
        lambda: (
            keys[0] in panel.signal_keys_drawn()
            and keys[1] in panel.signal_keys_drawn()
        ),
        timeout=2000,
    )


# ---------------------------------------------------------------------------
# C2 guard: drop → immediate plain gesture (re-entrancy / stale scene)
# ---------------------------------------------------------------------------


def test_drop_then_immediate_gesture_does_not_hang(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """C2 guard: a signal drop immediately followed by another gesture must not hang.

    A synchronous dropEvent rebuild (graph_panel_view.py:1686-1701) destroys and
    recreates scene items inside the QDrag.exec OLE modal loop.  The next gesture
    can be mis-routed to the destroyed scene item and either hang or recurse into
    another QDrag (memory gui_realgui_qdrag_rebuild_stale_scene).  This test
    exercises that re-entrancy path on real win32 — if it hangs the controller
    applies a QTimer.singleShot(0, ...) deferral to the rebuild (same pattern as
    the axis-move at line 1672).  Reaching the end assertion is the pass criterion.
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    from tests.realgui._realgui_input import LDOWN, LUP, MOVE, at

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)

    _select_rows(browser, [0])
    QApplication.processEvents()
    press = _row_phys(browser, 0)
    target = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)
    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)
    for _ in range(3):
        QApplication.processEvents()
    assert panel.drop_seen, f"no dropEvent. screenshot: {tmp_path / 'c2.png'}"

    # Wait for the drop to fully materialise before exercising the gesture.
    qtbot.waitUntil(lambda: keys[0] in panel.signal_keys_drawn(), timeout=2000)

    # Immediately drive a plain left-drag inside the plot (pan/zoom zone — not a
    # QDrag).  Manual at() loop (NOT drive_qdrag) because this is an ordinary
    # mouse gesture, not a DnD gesture.  Keep total move small and bounded.
    cx, cy = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    at(cx, cy, LDOWN)
    for dx in (8, 16, 24, 32):
        at(cx + dx, cy, MOVE)
        QApplication.processEvents()
    at(cx + 32, cy, LUP)
    QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "c2.png"))
    # Reaching here without a hang is the primary assertion.
    assert panel.vm.axes, "panel lost its axes after drop+gesture"


def test_drop_highlight_visible_mid_drag(qtbot: QtBot, tmp_path: Path) -> None:
    """Low: the blue drop-highlight border is shown mid-drag and cleared after drop.

    GraphPanelView.dragEnterEvent sets _set_drop_highlight(True) for signal mime
    (graph_panel_view.py:1656-1660); dropEvent clears it. Existing D&D realgui only
    asserts drop_seen — this asserts the honest visual state: is_drop_highlighted()
    is True while the drag hovers, and False after the drop.

    Honest RED: make GraphPanelView._set_drop_highlight (graph_panel_view.py:1650)
    a no-op (``self._drop_active = active`` → ``pass``) — the highlight never turns
    on, mid_highlighted stays False, and the assertion fails.
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.channel_browser_view import ChannelBrowserView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    class _HighlightCapturingPanel(GraphPanelView):
        mid_highlighted: bool = False
        mid_border: bool = False
        drop_seen: bool = False

        def dragMoveEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dragMoveEvent(ev)  # type: ignore[arg-type]
            # Capture the drop-highlight state WHILE the drag hovers the panel.
            if self.is_drop_highlighted():
                self.mid_highlighted = True
                if "border" in self.styleSheet():
                    self.mid_border = True

        def dropEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dropEvent(ev)  # type: ignore[arg-type]
            self.drop_seen = True

    from PySide6.QtCore import Qt

    csv = tmp_path / "d.csv"
    csv.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    file_key = app_vm.request_load(csv, _fmt())
    app_vm.set_active_file(file_key)

    browser = ChannelBrowserView(ChannelBrowserVM(app_vm))
    panel = _HighlightCapturingPanel(GraphPanelVM(app_vm.session))
    qtbot.addWidget(browser)
    qtbot.addWidget(panel)
    for w, x in ((browser, 200), (panel, 640)):
        w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        w.setGeometry(x, 250, 400, 360)
        w.show()
        qtbot.waitExposed(w)
    qtbot.waitUntil(
        lambda: browser.tree.visualRect(browser.proxy.index(0, 0)).height() > 0,
        timeout=3000,
    )
    QApplication.processEvents()

    _select_rows(browser, [0])
    QApplication.processEvents()

    press = _row_phys(browser, 0)
    target = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "drop_highlight.png")
        )

    assert panel.drop_seen, (
        f"no dropEvent — QDrag never completed. screenshot: {tmp_path / 'drop_highlight.png'}"
    )
    assert panel.mid_highlighted, (
        "drop-highlight (is_drop_highlighted) was never True mid-drag — the blue "
        f"border feedback is broken. screenshot: {tmp_path / 'drop_highlight.png'}"
    )
    assert panel.mid_border, "styleSheet had no border while highlighted mid-drag"
    # Cleared after drop.
    assert not panel.is_drop_highlighted(), (
        "drop-highlight not cleared after drop — _set_drop_highlight(False) not reached"
    )
