"""WelcomeView — central empty-state onboarding (SH-01).

The single highest-leverage fix for "a first-time engineer can't find how to
open data": the blank central area becomes an Open call-to-action plus a
Recent Files list. Emits open_requested(None) for the CTA and
open_requested(path) for a recent entry; MainWindow performs the actual load.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from valisync.gui import strings as S
from valisync.gui.views.recent_files import RecentFiles

# FU-04: Recent ボタンのラベル省略予算 (px)。フルパスをそのままラベルにすると
# minimumSizeHint がパス長に比例し、中央 QStackedWidget (全ページ最大) 経由で
# ウィンドウ最小幅が画面幅を超え、再レイアウト時に右側ドックが画面外へ
# 押し出される。ラベル側の有界化が根本解決 (spec 2026-07-11-fu04 参照)。
_RECENT_LABEL_MAX_W = 360


class WelcomeView(QWidget):
    open_requested = Signal(object)  # None=CTA / str=recent path

    def __init__(self, recent: RecentFiles, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._recent = recent

        title = QLabel(S.WELCOME_OPEN_LABEL)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("mf4 / mdf / dat / csv をドラッグ&ドロップ、または下のボタンから")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)

        # E-3: ショートカット表記部は set_open_action() の後注入まで未確定
        # (ShellActions は WelcomeView より後に構築される)。
        self.cta = QPushButton(S.WELCOME_OPEN_LABEL)
        self.cta.setObjectName("welcome_open_cta")
        self.cta.clicked.connect(lambda: self.open_requested.emit(None))
        self._open_action: QAction | None = None

        self._recent_box = QVBoxLayout()

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.cta, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(self._recent_box)
        layout.addStretch(2)

        self.refresh()

    def set_open_action(self, action: QAction) -> None:
        """CTA のショートカット表記部を実 QAction から動的合成する (E-3)。

        WelcomeView は ShellActions より先に構築されるため後注入。ラベル部は
        strings 定数 (WELCOME_OPEN_LABEL) 固定・ショートカット部のみ
        ``action.shortcut()`` から合成し、``action.changed`` で追随する。
        ``action.text()`` は使わない — ニーモニクス付与後は「開く(&O)…」になり
        ラベルと食い違うため (R-04)。
        """
        self._open_action = action
        action.changed.connect(self._sync_open_cta_text)
        self._sync_open_cta_text()

    def _sync_open_cta_text(self) -> None:
        assert self._open_action is not None
        shortcut = self._open_action.shortcut().toString()
        text = S.WELCOME_OPEN_LABEL
        if shortcut:
            text = f"{text} ({shortcut})"
        self.cta.setText(text)

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
            btn = QPushButton()
            btn.setFlat(True)
            # ラベルだけ中央省略で有界化 (FU-04)。ElideMiddle はドライブ名と
            # 末尾ファイル名を残す。フルパスは tooltip とクリック emit に保持。
            fm = btn.fontMetrics()
            btn.setText(
                fm.elidedText(path, Qt.TextElideMode.ElideMiddle, _RECENT_LABEL_MAX_W)
            )
            btn.setToolTip(path)
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
