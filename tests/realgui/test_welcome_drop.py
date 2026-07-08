"""Layer C: real-OS-input test for file (URL-mime) drop onto WelcomeView.

Merge-blocker regression (spec 4.2) — the Welcome screen advertises drag-and-drop
("mf4 / mdf / dat / csv をドラッグ&ドロップ") but, before this fix, never called
``setAcceptDrops(True)`` and had no ``dropEvent`` at all. ``GraphAreaView`` already
had a proven ``file_dropped`` drop path, but ``MainWindow`` shows ``WelcomeView``
as the front page of a ``QStackedWidget`` at launch, so that path was inert: a
real OS drop landed on a widget that silently ignores all drags.

A real Windows Explorer drag is NOT automatable (cross-process OLE DoDragDrop);
an in-app QDrag carrying a QUrl mime goes through the identical Qt IDropTarget
path and is the correct, honest substitute (same rationale as
test_file_drop_realclick.py / M5 and test_data_explorer_file_drop.py).

Structural risk under test
--------------------------
``WelcomeView.__init__`` (welcome_view.py) now calls ``self.setAcceptDrops(True)``
and defines ``dragEnterEvent`` / ``dragMoveEvent`` / ``dropEvent``; ``dropEvent``
emits ``open_requested`` (str) for each dropped local-file URL — the same signal
the CTA button and recent-file rows use, which ``MainWindow`` wires to
``_load_file``. This test drives a real OS drag onto a shown ``WelcomeView`` and
asserts the signal fires with the dropped path, proving the real IDropTarget
delivery chain reaches the new handler (not just the handler's internal logic,
which tests/gui/test_welcome_view.py already covers by direct dropEvent() call).

Honest RED
----------
Comment out ``self.setAcceptDrops(True)`` in ``WelcomeView.__init__``
(welcome_view.py): Qt then never delivers drag/drop events to the widget at all
(no dragEnterEvent, no dropEvent), ``open_requested`` is never emitted for the
drop, and ``len(open_requested_spy) == 1`` fails (RED).
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import drive_qdrag, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _make_source_and_welcome(qtbot: QtBot, local_file: Path, tmp_path: Path):
    """Build a URL-drag source widget + WelcomeView shown side by side.

    Returns (source, view, open_requested_spy). ``open_requested_spy``
    accumulates every value ``view.open_requested`` emits (None for the CTA /
    str for a recent row or a drop). Qt/valisync imports are kept inside the
    function so offscreen collection never triggers display-dependent imports
    (same pattern as test_data_explorer_file_drop.py's helper).
    """
    from PySide6.QtCore import QMimeData, QSettings, Qt, QUrl
    from PySide6.QtGui import QDrag
    from PySide6.QtWidgets import QApplication, QWidget

    from valisync.gui.views.recent_files import RecentFiles
    from valisync.gui.views.welcome_view import WelcomeView

    class _UrlSource(QWidget):
        """Press -> move -> QDrag with QUrl mime -> enter OLE modal loop."""

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
                drag.exec(Qt.DropAction.CopyAction)
                self._press_pos = None
                self._dragging = False
            super().mouseMoveEvent(event)

    url = QUrl.fromLocalFile(str(local_file))
    source = _UrlSource(url)
    qtbot.addWidget(source)
    source.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    source.setGeometry(60, 320, 80, 60)
    source.show()
    qtbot.waitExposed(source)

    # Isolated QSettings (ini file under tmp_path) — an unset settings arg
    # would fall back to the real registry-backed ValiSync/ValiSync store,
    # which must never be touched from a test (same isolation as
    # tests/gui/test_welcome_view.py's _recent() helper).
    recent = RecentFiles(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    view = WelcomeView(recent)
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(220, 160, 700, 500)
    view.show()
    qtbot.waitExposed(view)

    for _ in range(3):
        QApplication.processEvents()

    open_requested_spy: list[object] = []
    view.open_requested.connect(open_requested_spy.append)

    return source, view, open_requested_spy


def _widget_phys(w, lx: int, ly: int) -> tuple[int, int]:
    from PySide6.QtCore import QPoint

    dpr = w.devicePixelRatioF()
    gp = w.mapToGlobal(QPoint(lx, ly))
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_welcome_drop_emits_open_requested(qtbot: QtBot, tmp_path: Path) -> None:
    """M-welcome: in-app QDrag with QUrl mime dropped on WelcomeView -> open_requested.

    Exercises the real Qt OLE IDropTarget chain: QDrag.exec() in source -> OS
    IDropTarget on the WelcomeView window -> WelcomeView.dragEnterEvent accepts
    URL mime -> dropEvent -> open_requested.emit(local) per URL. The drop point
    (lower stretch region, below the CTA button and the empty recent-files box)
    lands directly on WelcomeView itself, not on a child button.
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    local_file = tmp_path / "welcome_drop.csv"
    local_file.write_text("t,v\n0.0,1.0\n", encoding="utf-8")

    source, view, open_requested_spy = _make_source_and_welcome(
        qtbot, local_file, tmp_path
    )

    press = _widget_phys(source, source.width() // 2, source.height() // 2)
    # Drop target: lower third of WelcomeView (layout.addStretch(2) region) —
    # empty space below the CTA button, clear of any child widget.
    tgt_lx = view.width() // 2
    tgt_ly = int(view.height() * 0.85)
    target = _widget_phys(view, tgt_lx, tgt_ly)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: len(open_requested_spy) > 0)

    for _ in range(4):
        QApplication.processEvents()

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "welcome_drop.png")
        )

    assert len(open_requested_spy) == 1, (
        "open_requested not emitted — URL mime drag did not reach "
        f"WelcomeView.dropEvent. screenshot: {tmp_path / 'welcome_drop.png'}"
    )
    assert Path(str(open_requested_spy[0])).resolve() == local_file.resolve(), (
        f"open_requested emitted wrong path: "
        f"{open_requested_spy[0]!r} != {str(local_file)!r}"
    )
