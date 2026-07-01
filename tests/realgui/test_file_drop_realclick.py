"""Layer C: real-OS-input test for file (URL-mime) drop onto GraphAreaView.

M5 — shell file drop (in-app QDrag URL-mime substitute).

A real Windows Explorer drag is NOT automatable: Explorer uses a cross-process
OLE DoDragDrop call that no Win32 ``mouse_event`` / ``SendInput`` hook can
drive from the same process.  An in-app QDrag carrying a ``QUrl`` mime goes
through the *identical* Qt IDropTarget / QWin32DragManager path and is the
correct, honest substitute.  The child-ignore / parent-accept propagation chain
is identical to the Explorer case; only the OLE drag *initiator* differs
(same-process helper widget vs. Explorer.exe).

Structural risk under test
--------------------------
``GraphPanelView`` has ``setAcceptDrops(True)`` (graph_panel_view.py:685) and
is a child of ``GraphAreaView``.  ``GraphPanelView.dragEnterEvent`` (line 1656)
checks for ``SIGNAL_KEYS_MIME`` / ``AXIS_INDEX_MIME`` only; the else-branch at
line 1662 calls ``event.ignore()`` for any other mime type (including URL mime).
Qt then propagates the drag to the parent ``GraphAreaView``, which has
``setAcceptDrops(True)`` (graph_area_view.py:62) and accepts URL mime in its
``dragEnterEvent`` (line 210), ultimately calling ``dropEvent`` (line 227) which
emits ``file_dropped`` (line 236) for each local-file URL.

Honest RED
----------
Change the else-branch of ``GraphPanelView.dragEnterEvent`` (line 1662 in
graph_panel_view.py) from ``event.ignore()`` to ``event.acceptProposedAction()``:
the child panel accepts the URL drag, so the parent ``GraphAreaView.dropEvent``
is never reached, ``file_dropped`` is never emitted, and the assertion
``len(file_dropped_spy) == 1`` fails (RED).
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import drive_qdrag, skip_unless_real_display

pytestmark = pytest.mark.realgui


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source_and_area(qtbot: QtBot, local_file: Path):
    """Build a URL-drag source widget + GraphAreaView shown side by side.

    Returns (source, area, file_dropped_spy).  ``file_dropped_spy`` is a list
    that accumulates each path string emitted by ``area.file_dropped``.

    All Qt class definitions are kept *inside* this function so that collection
    under the offscreen platform never triggers real-display-dependent imports
    (same pattern as test_signal_dnd_realclick._make_browser_and_panel).
    """
    from PySide6.QtCore import QMimeData, Qt, QUrl
    from PySide6.QtGui import QDrag
    from PySide6.QtWidgets import QApplication, QWidget

    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.graph_area_view import GraphAreaView

    # --- URL-mime drag source ---
    # A plain QWidget whose mouseMoveEvent (after a real LDOWN) triggers a
    # QDrag.exec() carrying a QUrl mime.  drive_qdrag drives the real OS
    # mouse events from a background thread so the OLE modal loop is not blocked
    # on the GUI thread (memory: gui_realgui_drag_qtimer_hang).

    class _UrlSource(QWidget):
        """Press → move → QDrag with QUrl mime → enter OLE modal loop."""

        def __init__(self, url: QUrl) -> None:
            super().__init__()
            self._url = url
            self._press_pos = None
            self._dragging = False
            self.setFixedSize(80, 60)

        def mousePressEvent(self, event) -> None:  # type: ignore[override]
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_pos = event.pos()
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
            # Guard against re-entrancy; only start the drag once per press.
            if (
                self._press_pos is not None
                and not self._dragging
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                self._dragging = True
                mime = QMimeData()
                mime.setUrls([self._url])
                drag = QDrag(self)
                drag.setMimeData(mime)
                # exec() blocks this GUI-thread call on the OLE modal loop.
                # The background thread in drive_qdrag continues sending real
                # OS mouse events to steer the drag to the target widget and
                # release it.  The watchdog ESC+LUP unblocks exec() if needed.
                drag.exec(Qt.DropAction.CopyAction)
                self._press_pos = None
                self._dragging = False
            super().mouseMoveEvent(event)

    url = QUrl.fromLocalFile(str(local_file))
    source = _UrlSource(url)
    qtbot.addWidget(source)
    source.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # Position source to the left of the GraphAreaView with no overlap.
    source.setGeometry(60, 320, 80, 60)
    source.show()
    qtbot.waitExposed(source)

    # --- GraphAreaView (drop target) ---
    # An empty area with a single panel is sufficient — the test verifies the
    # URL-mime propagation chain (child ignore → parent accept → file_dropped),
    # not data loading.
    area_vm = GraphAreaVM(AppViewModel(Session()))
    area = GraphAreaView(area_vm)
    qtbot.addWidget(area)
    area.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    area.setGeometry(220, 160, 700, 500)
    area.show()
    qtbot.waitExposed(area)

    for _ in range(3):
        QApplication.processEvents()

    file_dropped_spy: list[str] = []
    area.file_dropped.connect(file_dropped_spy.append)

    return source, area, file_dropped_spy


def _widget_phys(w, lx: int, ly: int) -> tuple[int, int]:
    """Physical-pixel screen coordinate of widget-local (lx, ly).

    Follows the same dpr-scaling pattern as _panel_point_phys in
    test_signal_dnd_realclick.py.
    """
    from PySide6.QtCore import QPoint

    dpr = w.devicePixelRatioF()
    gp = w.mapToGlobal(QPoint(lx, ly))
    return round(gp.x() * dpr), round(gp.y() * dpr)


# ---------------------------------------------------------------------------
# M5: URL-mime file drop → file_dropped signal
# ---------------------------------------------------------------------------


def test_file_drop_emits_file_dropped(qtbot: QtBot, tmp_path: Path) -> None:
    """M5: in-app QDrag with QUrl mime dropped on GraphAreaView → file_dropped.

    Exercises the full real Qt OLE IDropTarget chain:
      QDrag.exec() in source → OS IDropTarget on target window
      → GraphPanelView.dragEnterEvent ignores URL mime (event.ignore() line 1662)
      → Qt propagates drag to parent GraphAreaView.dragEnterEvent (accepts)
      → GraphAreaView.dropEvent → file_dropped.emit(path)

    In-app QDrag with QUrl mime is the correct substitute for a Windows Explorer
    drag; see module docstring for the rationale.
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    local_file = tmp_path / "drop_target.csv"
    local_file.write_text("t,v\n0.0,1.0\n", encoding="utf-8")

    source, area, file_dropped_spy = _make_source_and_area(qtbot, local_file)

    # Press at the center of the source widget.
    press = _widget_phys(source, source.width() // 2, source.height() // 2)

    # Drop target: center of the GraphAreaView's panel region.  Offset +80 px
    # from the widget's vertical center to land well inside the GraphPanelView
    # (past the sync-checkbox header ~20 px and tab-bar ~25 px).
    tgt_lx = area.width() // 2
    tgt_ly = area.height() // 2 + 80
    target = _widget_phys(area, tgt_lx, tgt_ly)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    # drive_qdrag presses on the source in a background OS thread, moves to the
    # threshold (triggering _UrlSource.mouseMoveEvent → QDrag.exec()), then
    # steers the drag to 'target' and releases.  The GUI thread pumps events
    # until file_dropped_spy is populated or the deadline expires.
    drive_qdrag(press, [mid, target], done=lambda: len(file_dropped_spy) > 0)

    for _ in range(4):
        QApplication.processEvents()

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "m5.png"))

    assert len(file_dropped_spy) == 1, (
        "file_dropped not emitted — URL mime drag did not reach "
        f"GraphAreaView.dropEvent.  screenshot: {tmp_path / 'm5.png'}"
    )
    # Normalize to Path for platform-independent slash comparison (QUrl
    # round-trips correctly on Windows; Path.resolve() handles any divergence).
    assert Path(file_dropped_spy[0]).resolve() == Path(str(local_file)).resolve(), (
        f"file_dropped emitted wrong path: "
        f"{file_dropped_spy[0]!r} != {str(local_file)!r}"
    )
