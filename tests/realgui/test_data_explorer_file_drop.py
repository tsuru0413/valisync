"""Layer C: real-OS-input test for OS file (URL-mime) drop onto DataExplorerView.

Low-cluster item — DataExplorer OS file-manager drop (R12.1). A real Windows
Explorer drag is not automatable (cross-process OLE DoDragDrop); an in-app QDrag
carrying a QUrl mime goes through the identical Qt IDropTarget path and is the
correct substitute (same rationale as test_file_drop_realclick.py / M5).

DataExplorerView is a QMainWindow with setAcceptDrops(True) (data_explorer_view.py:80).
Its dragEnterEvent (line 154) accepts hasUrls(); dropEvent (line 166) converts each
url.toLocalFile() and calls self._load_handler(local) (line 174). A load_handler is
injected at construction (data_explorer_view.py:56) so the drop is observable without
touching the real loader.

Honest RED: change DataExplorerView.dragEnterEvent (data_explorer_view.py:155-156)
from ``event.acceptProposedAction()`` to ``event.ignore()`` — the drop is refused,
dropEvent never runs, _load_handler is never called, and the assertion below fails.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import drive_qdrag, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _make_source_and_explorer(qtbot: QtBot, local_file: Path):
    """Build a URL-drag source widget + DataExplorerView shown side by side.

    Returns (source, explorer, load_spy). ``load_spy`` accumulates each path the
    injected load_handler receives. Qt/valisync imports are kept inside the
    function so offscreen collection never triggers display-dependent imports.
    """
    from PySide6.QtCore import QMimeData, Qt, QUrl
    from PySide6.QtGui import QDrag
    from PySide6.QtWidgets import QApplication, QWidget

    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.data_explorer_view import DataExplorerView

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

    load_spy: list[str] = []
    explorer = DataExplorerView(
        AppViewModel(Session()),
        load_handler=lambda p: load_spy.append(str(p)),
    )
    qtbot.addWidget(explorer)
    explorer.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    explorer.setGeometry(220, 160, 700, 500)
    explorer.show()
    qtbot.waitExposed(explorer)

    for _ in range(3):
        QApplication.processEvents()

    return source, explorer, load_spy


def _widget_phys(w, lx: int, ly: int) -> tuple[int, int]:
    from PySide6.QtCore import QPoint

    dpr = w.devicePixelRatioF()
    gp = w.mapToGlobal(QPoint(lx, ly))
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_data_explorer_file_drop_calls_load_handler(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Low: in-app QDrag with QUrl mime dropped on DataExplorer → _load_handler(path).

    Exercises the real Qt OLE IDropTarget chain: QDrag.exec() in source →
    DataExplorerView.dragEnterEvent accepts URL mime → dropEvent →
    _load_handler(local) per URL. The QTreeView child does not accept drops, so
    the drag reaches the QMainWindow drop handler (structural point under test).
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    local_file = tmp_path / "explorer_drop.csv"
    local_file.write_text("t,v\n0.0,1.0\n", encoding="utf-8")

    source, explorer, load_spy = _make_source_and_explorer(qtbot, local_file)

    press = _widget_phys(source, source.width() // 2, source.height() // 2)
    # Drop onto the centre of the explorer window (tree area). The QMainWindow
    # owns setAcceptDrops; the tree child does not accept drops, so the drag
    # bubbles to DataExplorerView.dropEvent.
    target = _widget_phys(explorer, explorer.width() // 2, explorer.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: len(load_spy) > 0)

    for _ in range(4):
        QApplication.processEvents()

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "explorer_drop.png")
        )

    assert len(load_spy) == 1, (
        "load_handler not called — URL mime drop did not reach "
        f"DataExplorerView.dropEvent. screenshot: {tmp_path / 'explorer_drop.png'}"
    )
    assert Path(load_spy[0]).resolve() == Path(str(local_file)).resolve(), (
        f"load_handler got wrong path: {load_spy[0]!r} != {str(local_file)!r}"
    )
