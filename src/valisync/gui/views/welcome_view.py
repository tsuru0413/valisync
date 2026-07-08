"""WelcomeView — central empty-state onboarding (SH-01).

The single highest-leverage fix for "a first-time engineer can't find how to
open data": the blank central area becomes an Open call-to-action plus a
Recent Files list. Emits open_requested(None) for the CTA and
open_requested(path) for a recent entry; MainWindow performs the actual load.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.views.recent_files import RecentFiles


class WelcomeView(QWidget):
    open_requested = Signal(object)  # None=CTA / str=recent path

    def __init__(self, recent: RecentFiles, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._recent = recent

        title = QLabel("計測ファイルを開く")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("mf4 / mdf / dat / csv をドラッグ&ドロップ、または下のボタンから")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)

        self.cta = QPushButton("計測ファイルを開く  (Ctrl+O)")
        self.cta.setObjectName("welcome_open_cta")
        self.cta.clicked.connect(lambda: self.open_requested.emit(None))

        self._recent_box = QVBoxLayout()

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.cta, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(self._recent_box)
        layout.addStretch(2)

        self.refresh()

    def _emit_recent(self, path: str) -> None:
        self.open_requested.emit(path)

    def refresh(self) -> None:
        # Recent 行を作り直す (存在するもののみ)
        while self._recent_box.count():
            item = self._recent_box.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        for path in self._recent.existing():
            btn = QPushButton(path)
            btn.setFlat(True)
            btn.clicked.connect(lambda _=False, p=path: self._emit_recent(p))
            self._recent_box.addWidget(btn)

    # ─── OS file drop → open pipeline (spec 4.2) ───────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        # spec 4.2: Welcome 上のドロップも open_requested に集約する
        # (起動時は GraphAreaView が隠れており、その drop 経路は届かないため)
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        for url in mime.urls():
            local = url.toLocalFile()
            if local:
                self.open_requested.emit(local)
        event.acceptProposedAction()
