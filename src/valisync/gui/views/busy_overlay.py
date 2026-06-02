"""BusyOverlay — indeterminate busy indicator shown during loads (Task 9.1).

A thin widget with a centred indeterminate QProgressBar.  Starts hidden; the
load controller shows it while a worker runs and hides it on completion.  When
given a parent, ``cover()`` resizes it to fill the parent so it reads as an
overlay.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProgressBar, QVBoxLayout, QWidget


class BusyOverlay(QWidget):
    """Indeterminate busy overlay, hidden until explicitly shown."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.progress_bar = QProgressBar(self)
        # range (0, 0) makes the bar indeterminate (no percentage).
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        self.hide()

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
