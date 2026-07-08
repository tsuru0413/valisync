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
