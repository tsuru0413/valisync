"""ワーカースレッド→GUI スレッドの展開確認モーダル委譲 (LD-14).

ロードはワーカースレッドで走るが、確認モーダルは GUI スレッドで出す必要がある。
confirm() をワーカースレッドから呼ぶと、Signal (QueuedConnection) で GUI スレッド
のスロットへ marshal し、threading.Event でモーダルの回答までワーカーをブロックする。
ロード中の GUI スレッドはブロックされていない (オフスレッドロード) ため、queued
スロットが処理でき入れ子イベントループが回る = デッドロックしない。
"""

from __future__ import annotations

import threading
from typing import cast

from PySide6.QtCore import QObject, Qt, Signal, Slot

from valisync.core.loaders.mdf4_loader import ExpansionRequest
from valisync.gui.views.expansion_dialog import ExpansionDialog

_Payload = tuple[ExpansionRequest, dict[str, set[int]], threading.Event]


class ExpansionConfirmer(QObject):
    _requested = Signal(object)  # (request, holder: dict, event) を GUI スレッドへ

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # confirmer は GUI スレッド所属。worker からの emit は自動で QueuedConnection。
        self._requested.connect(self._on_requested, Qt.ConnectionType.QueuedConnection)

    def confirm(self, request: ExpansionRequest) -> set[int]:
        """ワーカースレッドから呼ぶ。GUI モーダルの回答までブロックし結果を返す."""
        holder: dict[str, set[int]] = {}
        event = threading.Event()
        self._requested.emit((request, holder, event))
        event.wait()
        return holder.get("result", set())

    @Slot(object)
    def _on_requested(self, payload: object) -> None:
        request, holder, event = cast("_Payload", payload)
        try:
            holder["result"] = ExpansionDialog.ask(request)
        finally:
            event.set()
