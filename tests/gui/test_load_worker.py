"""Tests for off-thread loading: BusyOverlay, LoadWorker, LoadController — Task 9.1.

The worker runs the (thread-safe) Session.load off the GUI thread and reports
completion via queued signals; the controller drives a LoadTask + BusyOverlay
and a caller-supplied success/error callback on the main thread.

TDD: written before the implementation; all must FAIL first.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThreadPool
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
from valisync.gui.viewmodels.load_task import LoadTask

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv(tmp_path: Path) -> tuple[Path, FormatDefinition]:
    fmt = FormatDefinition(
        name="fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    path = tmp_path / "d.csv"
    path.write_text("t,v\n0.0,1.0\n1.0,2.0\n", encoding="utf-8")
    return path, fmt


# ─── LoadTask state methods (drive the threaded path on the main thread) ───────


class TestLoadTaskStates:
    def test_begin_sets_loading_and_notifies(self) -> None:
        task = LoadTask()
        seen: list[str] = []
        task.subscribe(seen.append)
        task.begin()
        assert task.state == "loading"
        assert "loading" in seen

    def test_succeed_sets_done_with_key(self) -> None:
        task = LoadTask()
        seen: list[str] = []
        task.subscribe(seen.append)
        task.succeed("csv_1")
        assert task.state == "done"
        assert task.result_key == "csv_1"
        assert "done" in seen

    def test_fail_sets_error_with_message(self) -> None:
        task = LoadTask()
        seen: list[str] = []
        task.subscribe(seen.append)
        task.fail("boom")
        assert task.state == "error"
        assert task.error_message == "boom"
        assert "error" in seen


# ─── BusyOverlay ──────────────────────────────────────────────────────────────


class TestBusyOverlay:
    def test_starts_hidden(self, qtbot: QtBot) -> None:
        from valisync.gui.views.busy_overlay import BusyOverlay

        overlay = BusyOverlay()
        qtbot.addWidget(overlay)
        assert overlay.isHidden()

    def test_progress_bar_is_indeterminate(self, qtbot: QtBot) -> None:
        from valisync.gui.views.busy_overlay import BusyOverlay

        overlay = BusyOverlay()
        qtbot.addWidget(overlay)
        assert overlay.is_indeterminate()

    def test_show_then_hide(self, qtbot: QtBot) -> None:
        from valisync.gui.views.busy_overlay import BusyOverlay

        overlay = BusyOverlay()
        qtbot.addWidget(overlay)
        overlay.show()
        assert not overlay.isHidden()
        overlay.hide()
        assert overlay.isHidden()


# ─── LoadWorker ───────────────────────────────────────────────────────────────


class TestLoadWorker:
    def test_emits_finished_with_key(self, qtbot: QtBot, tmp_path: Path) -> None:
        from valisync.gui.workers.load_worker import LoadWorker

        path, fmt = _csv(tmp_path)
        session = Session()
        worker = LoadWorker(lambda: session.load(path, fmt))

        with qtbot.waitSignal(worker.signals.finished, timeout=3000) as blocker:
            QThreadPool.globalInstance().start(worker)

        assert isinstance(blocker.args[0], str) and blocker.args[0]
        assert len(session.signals()) == 1

    def test_emits_failed_on_exception(self, qtbot: QtBot) -> None:
        from valisync.gui.workers.load_worker import LoadWorker

        def boom() -> str:
            raise ValueError("nope")

        worker = LoadWorker(boom)
        with qtbot.waitSignal(worker.signals.failed, timeout=3000) as blocker:
            QThreadPool.globalInstance().start(worker)

        assert "nope" in blocker.args[0]


# ─── LoadController ───────────────────────────────────────────────────────────


class TestLoadController:
    def test_success_updates_tree_task_and_hides_busy(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        from valisync.gui.views.busy_overlay import BusyOverlay
        from valisync.gui.workers.load_worker import LoadController

        path, fmt = _csv(tmp_path)
        session = Session()
        cb_vm = ChannelBrowserVM(session)
        task = LoadTask()
        busy = BusyOverlay()
        qtbot.addWidget(busy)
        keys: list[str] = []

        controller = LoadController()
        controller.submit(
            lambda: session.load(path, fmt),
            task=task,
            busy=busy,
            on_success=lambda key: (cb_vm.refresh(), keys.append(key)),
        )

        qtbot.waitUntil(lambda: task.state == "done", timeout=3000)
        assert len(keys) == 1
        assert len(cb_vm.tree()) == 1  # tree now reflects the loaded file
        assert busy.isHidden()

    def test_busy_shown_during_load(self, qtbot: QtBot) -> None:
        from valisync.gui.views.busy_overlay import BusyOverlay
        from valisync.gui.workers.load_worker import LoadController

        release = threading.Event()

        def slow() -> str:
            release.wait(timeout=3.0)
            return "csv_1"

        busy = BusyOverlay()
        qtbot.addWidget(busy)
        controller = LoadController()
        controller.submit(slow, busy=busy)

        # Busy is shown synchronously on submit, before the worker finishes.
        assert not busy.isHidden()
        release.set()
        qtbot.waitUntil(lambda: busy.isHidden(), timeout=3000)

    def test_failure_sets_task_error(self, qtbot: QtBot) -> None:
        from valisync.gui.workers.load_worker import LoadController

        def boom() -> str:
            raise ValueError("bad file")

        task = LoadTask()
        errors: list[str] = []
        controller = LoadController()
        controller.submit(boom, task=task, on_error=errors.append)

        qtbot.waitUntil(lambda: task.state == "error", timeout=3000)
        assert "bad file" in (task.error_message or "")
        assert errors and "bad file" in errors[0]
