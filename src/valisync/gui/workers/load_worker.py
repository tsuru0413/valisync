"""Off-thread file loading (Task 9.1).

``LoadWorker`` runs an injected load callable on a ``QThreadPool`` thread and
reports the outcome via queued signals.  Only the thread-safe heavy work
(``Session.load``, which returns immutable Signals) runs off-thread; all state
changes and notifications happen back on the GUI thread, so ViewModels stay
Qt-free and are never mutated from a worker thread.

``LoadController`` orchestrates one load: it flips a ``LoadTask`` to loading,
shows a ``BusyOverlay``, submits the worker, and on the queued completion
drives the task to done/error, hides the overlay, and invokes a caller-supplied
success/error callback.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

if TYPE_CHECKING:
    from valisync.gui.viewmodels.load_task import LoadTask
    from valisync.gui.views.busy_overlay import BusyOverlay


class LoadWorkerSignals(QObject):
    """Signal carrier for :class:`LoadWorker` (QRunnable cannot emit signals)."""

    finished = Signal(str)  # the group key on success
    failed = Signal(str)  # the error message on failure


class LoadWorker(QRunnable):
    """Run *load_callable* off-thread and emit finished/failed.

    Parameters
    ----------
    load_callable:
        A zero-argument callable returning the loaded group key — typically
        ``lambda: session.load(path, format_def)``.  Injecting it keeps the
        worker decoupled from Session and trivially testable.
    """

    def __init__(self, load_callable: Callable[[], str]) -> None:
        super().__init__()
        self._load_callable = load_callable
        self.signals = LoadWorkerSignals()

    def run(self) -> None:
        try:
            key = self._load_callable()
        except Exception as exc:  # report, never crash the pool thread
            self.signals.failed.emit(str(exc))
        else:
            self.signals.finished.emit(key)


class LoadController(QObject):
    """Drive a single off-thread load and update GUI state on completion.

    Lives on the GUI thread; the worker's queued signals are delivered here so
    every state change runs on the GUI thread.
    """

    def __init__(
        self,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pool = thread_pool or QThreadPool.globalInstance()
        # Keep workers referenced until they finish; QThreadPool.start does not
        # hold a Python reference, so a GC'd worker would drop its signals.
        self._active: set[LoadWorker] = set()

    def submit(
        self,
        load_callable: Callable[[], str],
        *,
        task: LoadTask | None = None,
        busy: BusyOverlay | None = None,
        on_success: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Begin loading: flag task/busy, then run *load_callable* off-thread."""
        if task is not None:
            task.begin()
        if busy is not None:
            busy.show()

        worker = LoadWorker(load_callable)
        self._active.add(worker)
        worker.signals.finished.connect(
            lambda key: self._finish(worker, key, task, busy, on_success)
        )
        worker.signals.failed.connect(
            lambda msg: self._fail(worker, msg, task, busy, on_error)
        )
        self._pool.start(worker)

    def _finish(
        self,
        worker: LoadWorker,
        key: str,
        task: LoadTask | None,
        busy: BusyOverlay | None,
        on_success: Callable[[str], None] | None,
    ) -> None:
        self._active.discard(worker)
        if busy is not None:
            busy.hide()
        if task is not None:
            task.succeed(key)
        if on_success is not None:
            on_success(key)

    def _fail(
        self,
        worker: LoadWorker,
        message: str,
        task: LoadTask | None,
        busy: BusyOverlay | None,
        on_error: Callable[[str], None] | None,
    ) -> None:
        self._active.discard(worker)
        if busy is not None:
            busy.hide()
        if task is not None:
            task.fail(message)
        if on_error is not None:
            on_error(message)
