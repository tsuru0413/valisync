"""BusyOverlay — indeterminate busy indicator shown during loads (Task 9.1).

A message label, a centred indeterminate QProgressBar, and a cancel button
(``cancel_requested`` is emitted on click; wiring the click to an actual
cancellation is the caller's job — see ``LoadController.cancel_active``).
Starts hidden. ``LoadController`` drives visibility on a count basis: shown
while at least one load is active (label text reflects 1-vs-N loads), hidden
once the active count reaches zero. When given a parent, ``cover()`` resizes
it to fill the parent so it reads as an overlay.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
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

        # FU-02: 表示中に親が resize されると cover() が stale になり、透過
        # overlay のラベル/キャンセルが旧矩形の中心へズレて届きにくくなる。
        # 親の Resize を購読して追従する (親側の変更なしで自己完結)。
        if parent is not None:
            parent.installEventFilter(self)

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
        """Show the overlay, covering the parent and raising it above siblings."""
        self.cover()
        super().show()
        # FU-19: central_stack/ドックは overlay より後に生成され Qt 兄弟 z-order で
        # 上に積まれる。表示のたび最前面へ持ち上げないと不透明なプロット背景に隠れる。
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # 親の resize へ追従 (可視時のみ — 非表示時は show() が cover する)。
        # False を返しイベントは消費しない (親の通常の resize 処理を妨げない)。
        # filter は親にのみ install しているため watched は常に親。
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self.cover()
        return False
