from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.workers.export_worker import ExportController


def test_success_invokes_on_success(qtbot: QtBot) -> None:
    ctl = ExportController()
    done: list[int] = []
    ran: list[int] = []
    ctl.submit(lambda: ran.append(1), on_success=lambda: done.append(1))
    qtbot.waitUntil(lambda: done == [1], timeout=3000)
    assert ran == [1]


def test_failure_invokes_on_error(qtbot: QtBot) -> None:
    ctl = ExportController()
    errs: list[Exception] = []

    def _boom() -> None:
        raise OSError("disk full")

    ctl.submit(_boom, on_error=errs.append)
    qtbot.waitUntil(lambda: len(errs) == 1, timeout=3000)
    assert isinstance(errs[0], OSError)


def test_busy_shown_then_hidden(qtbot: QtBot) -> None:
    class _Busy:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def set_message(self, m: str) -> None:
            self.calls.append("msg")

        def show(self) -> None:
            self.calls.append("show")

        def hide(self) -> None:
            self.calls.append("hide")

    ctl = ExportController()
    busy = _Busy()
    done: list[int] = []
    ctl.submit(lambda: None, busy=busy, on_success=lambda: done.append(1))
    qtbot.waitUntil(lambda: done == [1], timeout=3000)
    assert "show" in busy.calls and busy.calls[-1] == "hide"


def test_failure_busy_shown_then_hidden(qtbot: QtBot) -> None:
    # Symmetry with test_busy_shown_then_hidden: the failed() path must also
    # hide the overlay (both _finish and _fail call busy.hide()).
    class _Busy:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def set_message(self, m: str) -> None:
            self.calls.append("msg")

        def show(self) -> None:
            self.calls.append("show")

        def hide(self) -> None:
            self.calls.append("hide")

    def _boom() -> None:
        raise OSError("disk full")

    ctl = ExportController()
    busy = _Busy()
    errs: list[Exception] = []
    ctl.submit(_boom, busy=busy, on_error=errs.append)
    qtbot.waitUntil(lambda: len(errs) == 1, timeout=3000)
    assert "show" in busy.calls and busy.calls[-1] == "hide"


def test_callback_survives_gc_pressure(qtbot: QtBot) -> None:
    # worker を保持しないと、submit() 後の GC で queued signal が消え callback が不達になる。
    import gc
    import time

    ctl = ExportController()
    done: list[int] = []
    ctl.submit(lambda: time.sleep(0.1), on_success=lambda: done.append(1))
    gc.collect()  # 保持が無いと worker+signals をここで回収し callback を失う
    # GUI スレッドを能動的にブロックし、queued finished イベントを一切ポンプさせない。
    # ワーカースレッド側の run() 完了 -> QThreadPool autoDelete -> signals 破棄 ->
    # 未配送 posted event の purge を GUI スレッドの介入なしに完走させることで、
    # 「GUI スレッドがイベントループで先に拾ってしまい偶然グリーンになる」レースを
    # 排除し、参照未保持バグを決定的に再現する。
    time.sleep(0.3)
    qtbot.waitUntil(lambda: done == [1], timeout=3000)
    assert done == [1]
