"""BusyOverlay — indeterminate busy indicator shown during loads (Task 9.1).

A thin widget with a centred indeterminate QProgressBar.  Starts hidden; the
load controller shows it while a worker runs and hides it on completion.  When
given a parent, ``cover()`` resizes it to fill the parent so it reads as an
overlay.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget


class BusyOverlay(QWidget):
    """Indeterminate busy overlay, hidden until explicitly shown."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel("読み込み中…", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QProgressBar(self)
        # range (0, 0) makes the bar indeterminate (no percentage).
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)

        self.cancel_button = QPushButton("キャンセル", self)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self.hide()

    def set_message(self, text: str) -> None:
        """Show *text* as the load description (FB-04 label)."""
        self._label.setText(text)

    def message(self) -> str:
        """Current label text (test-facing)."""
        return self._label.text()

    def is_indeterminate(self) -> bool:
        """Return True when the progress bar shows an indeterminate animation."""
        return self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0

    def cover(self) -> None:
        """Resize to fill the parent (so it overlays the busy area)."""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    def show(self) -> None:
        """Show the overlay, first sizing it to cover the parent if any."""
        self.cover()
        super().show()
