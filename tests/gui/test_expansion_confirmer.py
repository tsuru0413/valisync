from __future__ import annotations

import threading

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.loaders.mdf_loader import ExpansionRequest, OversizedChannel
from valisync.gui.views.expansion_dialog import ExpansionDialog
from valisync.gui.workers.expansion_confirmer import ExpansionConfirmer


def _req() -> ExpansionRequest:
    return ExpansionRequest(
        channels=(OversizedChannel(name="Wide", column_count=1025),)
    )


def test_confirm_marshals_to_gui_thread(qtbot: QtBot, monkeypatch) -> None:
    """別スレッドからの confirm が GUI スレッドの ask を呼び結果を返す (LD-14)."""
    seen_thread: list[int] = []

    def fake_ask(request, parent=None):  # GUI スレッドで呼ばれるはず
        seen_thread.append(threading.get_ident())
        return {0}

    monkeypatch.setattr(ExpansionDialog, "ask", staticmethod(fake_ask))

    confirmer = ExpansionConfirmer()

    result: dict[str, set[int]] = {}
    worker_thread_id: list[int] = []

    def worker() -> None:
        worker_thread_id.append(threading.get_ident())
        result["value"] = confirmer.confirm(_req())

    t = threading.Thread(target=worker)
    t.start()
    # GUI スレッドはイベントを回して queued スロットを処理する
    qtbot.waitUntil(lambda: "value" in result, timeout=3000)
    t.join(timeout=3000)

    assert result["value"] == {0}
    # ask は GUI (メイン) スレッドで実行され、worker スレッドとは別 ident
    assert seen_thread and seen_thread[0] != worker_thread_id[0]
