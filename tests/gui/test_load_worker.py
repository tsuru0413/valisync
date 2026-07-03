"""Tests for off-thread loading: BusyOverlay, LoadWorker, LoadController — Task 9.1 (Refactored).

The worker runs the (thread-safe) Session.load off the GUI thread and reports
completion via queued signals; the controller drives a LoadTask + BusyOverlay
and a caller-supplied success/error callback on the main thread.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThreadPool
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
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

    def test_set_message_reflected_in_label(self, qtbot: QtBot) -> None:
        from valisync.gui.views.busy_overlay import BusyOverlay

        overlay = BusyOverlay()
        qtbot.addWidget(overlay)
        overlay.set_message("読み込み中: a.mf4")
        assert overlay.message() == "読み込み中: a.mf4"

    def test_cancel_button_click_emits_cancel_requested(self, qtbot: QtBot) -> None:
        from PySide6.QtCore import Qt

        from valisync.gui.views.busy_overlay import BusyOverlay

        overlay = BusyOverlay()
        qtbot.addWidget(overlay)
        overlay.show()
        with qtbot.waitSignal(overlay.cancel_requested, timeout=2000):
            qtbot.mouseClick(overlay.cancel_button, Qt.MouseButton.LeftButton)


# ─── LoadWorker ───────────────────────────────────────────────────────────────


class TestLoadWorker:
    def test_emits_finished_with_outcome(self, qtbot: QtBot, tmp_path: Path) -> None:
        from valisync.core.session import LoadOutcome
        from valisync.gui.workers.load_worker import LoadWorker

        path, fmt = _csv(tmp_path)
        session = Session()
        worker = LoadWorker(lambda: session.load(path, fmt))
        with qtbot.waitSignal(worker.signals.finished, timeout=3000) as blocker:
            QThreadPool.globalInstance().start(worker)
        assert isinstance(blocker.args[0], LoadOutcome)
        assert blocker.args[0].key
        assert len(session.signals()) == 1

    def test_emits_failed_with_exception(self, qtbot: QtBot) -> None:
        from valisync.gui.workers.load_worker import LoadWorker

        def boom():
            raise ValueError("nope")

        worker = LoadWorker(boom)
        with qtbot.waitSignal(worker.signals.failed, timeout=3000) as blocker:
            QThreadPool.globalInstance().start(worker)
        assert isinstance(blocker.args[0], Exception)
        assert "nope" in str(blocker.args[0])


# ─── LoadController ───────────────────────────────────────────────────────────


class TestLoadController:
    def test_success_updates_tree_task_and_hides_busy(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        from valisync.gui.views.busy_overlay import BusyOverlay
        from valisync.gui.workers.load_worker import LoadController

        path, fmt = _csv(tmp_path)
        app_vm = AppViewModel()
        cb_vm = ChannelBrowserVM(app_vm)
        task = LoadTask()
        busy = BusyOverlay()
        qtbot.addWidget(busy)
        keys: list[str] = []

        controller = LoadController()
        controller.submit(
            lambda: app_vm.session.load(path, fmt),
            task=task,
            busy=busy,
            on_success=lambda outcome: (
                app_vm.register_loaded(outcome.key),
                keys.append(outcome.key),
            ),
        )

        qtbot.waitUntil(lambda: task.state == "done", timeout=3000)
        assert len(keys) == 1

        # Select the active file to see signals
        app_vm.set_active_file(keys[0])
        assert len(cb_vm.signals) == 1
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

        def boom():
            raise ValueError("bad file")

        task = LoadTask()
        errors: list[Exception] = []
        controller = LoadController()
        controller.submit(boom, task=task, on_error=errors.append)

        qtbot.waitUntil(lambda: task.state == "error", timeout=3000)
        assert "bad file" in (task.error_message or "")
        assert errors and "bad file" in str(errors[0])

    def test_cancel_active_hides_busy_immediately_and_discards_result(
        self, qtbot: QtBot
    ) -> None:
        import threading

        from valisync.gui.views.busy_overlay import BusyOverlay
        from valisync.gui.workers.load_worker import LoadController

        release = threading.Event()
        cancel_event = threading.Event()
        results: list[object] = []
        discards: list[object] = []

        def slow_ok() -> str:
            release.wait(timeout=3.0)  # cancel 後に「手遅れ完走」する
            return "late_result"

        busy = BusyOverlay()
        qtbot.addWidget(busy)
        controller = LoadController()
        controller.submit(
            slow_ok,
            busy=busy,
            cancel_event=cancel_event,
            label="a.mf4",
            on_success=results.append,
            on_discard=discards.append,
        )
        assert not busy.isHidden()

        controller.cancel_active()
        assert cancel_event.is_set()  # ハード側へ中断要求
        assert busy.isHidden()  # ソフト側は即時解放

        release.set()  # worker は完走するが…
        qtbot.waitUntil(lambda: len(discards) == 1, timeout=3000)
        assert results == []  # on_success は呼ばれない
        assert discards == ["late_result"]

    def test_load_cancelled_routes_to_on_cancelled_not_on_error(
        self, qtbot: QtBot
    ) -> None:
        from valisync.core.session import LoadCancelled
        from valisync.gui.viewmodels.load_task import LoadTask
        from valisync.gui.workers.load_worker import LoadController

        def boom() -> str:
            raise LoadCancelled("cancelled")

        task = LoadTask()
        errors: list[object] = []
        cancelled: list[bool] = []
        controller = LoadController()
        controller.submit(
            boom,
            task=task,
            on_error=errors.append,
            on_cancelled=lambda: cancelled.append(True),
        )
        qtbot.waitUntil(lambda: task.state == "cancelled", timeout=3000)
        assert cancelled == [True]
        assert errors == []  # エラー扱いしない(spec §4.1)

    def test_busy_stays_visible_until_all_loads_finish(self, qtbot: QtBot) -> None:
        import threading

        from valisync.gui.views.busy_overlay import BusyOverlay
        from valisync.gui.workers.load_worker import LoadController

        rel1, rel2 = threading.Event(), threading.Event()
        busy = BusyOverlay()
        qtbot.addWidget(busy)
        controller = LoadController()
        controller.submit(lambda: rel1.wait(3.0) or "k1", busy=busy, label="a.mf4")
        controller.submit(lambda: rel2.wait(3.0) or "k2", busy=busy, label="b.mf4")
        assert "2 ファイル" in busy.message()  # 複数ロード表示

        rel1.set()
        qtbot.waitUntil(lambda: "b.mf4" in busy.message(), timeout=3000)
        assert not busy.isHidden()  # 片方完了ではまだ隠さない

        rel2.set()
        qtbot.waitUntil(lambda: busy.isHidden(), timeout=3000)

    def test_cancel_active_late_finish_sets_task_cancelled(self, qtbot: QtBot) -> None:
        """A task submitted with `task=` must not stick at "loading" forever.

        The failed-path late result (LoadCancelled) already flips the task to
        "cancelled"; the finished-path late completion ("手遅れ完走") must do
        the same, otherwise the task is stuck "loading" even though
        on_discard already rolled back Session registration.
        """
        from valisync.gui.views.busy_overlay import BusyOverlay
        from valisync.gui.workers.load_worker import LoadController

        release = threading.Event()
        cancel_event = threading.Event()
        discards: list[object] = []

        def slow_ok() -> str:
            release.wait(timeout=3.0)  # cancel 後に完走する(手遅れ完走)
            return "late_result"

        busy = BusyOverlay()
        qtbot.addWidget(busy)
        task = LoadTask()
        controller = LoadController()
        controller.submit(
            slow_ok,
            task=task,
            busy=busy,
            cancel_event=cancel_event,
            on_discard=discards.append,
        )

        controller.cancel_active()
        release.set()

        qtbot.waitUntil(lambda: task.state == "cancelled", timeout=3000)
        assert discards == ["late_result"]
