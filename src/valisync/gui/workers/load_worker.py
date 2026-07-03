"""Off-thread file loading (Task 9.1).

``LoadWorker`` runs an injected load callable on a ``QThreadPool`` thread and
reports the outcome via queued signals.  Only the thread-safe heavy work
(``Session.load``, which returns a ``LoadOutcome`` — group key plus loader
diagnostics) runs off-thread; all state changes and notifications happen back
on the GUI thread, so ViewModels stay Qt-free and are never mutated from a
worker thread.

``LoadController`` orchestrates loads: it flips a ``LoadTask`` to loading,
shows a ``BusyOverlay``, submits the worker, and on the queued completion
drives the task to done/error/cancelled, updates the overlay, and invokes a
caller-supplied success/error callback.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from valisync.core.session import LoadCancelled, LoadOutcome

if TYPE_CHECKING:
    from valisync.gui.viewmodels.load_task import LoadTask
    from valisync.gui.views.busy_overlay import BusyOverlay


class LoadWorkerSignals(QObject):
    """Signal carrier for :class:`LoadWorker` (QRunnable cannot emit signals)."""

    finished = Signal(object)  # LoadOutcome on success
    failed = Signal(object)  # the raised Exception (usually LoadError) on failure


class LoadWorker(QRunnable):
    """Run *load_callable* off-thread and emit finished/failed.

    Parameters
    ----------
    load_callable:
        A zero-argument callable returning the loaded :class:`LoadOutcome` —
        typically ``lambda: session.load(path, format_def)``.  Injecting it
        keeps the worker decoupled from Session and trivially testable.
    """

    def __init__(self, load_callable: Callable[[], LoadOutcome]) -> None:
        super().__init__()
        self._load_callable = load_callable
        self.signals = LoadWorkerSignals()

    def run(self) -> None:
        try:
            outcome = self._load_callable()  # LoadOutcome
        except Exception as exc:  # report, never crash the pool thread
            self.signals.failed.emit(exc)
        else:
            self.signals.finished.emit(outcome)


class LoadController(QObject):
    """Drive off-thread loads and update GUI state on completion.

    Busy visibility is count-based: the overlay stays up until every active
    load finishes (multiple drops share one overlay). ``cancel_active`` sets
    each load's cancel_event (cooperative hard-cancel) and releases the UI
    immediately (soft-cancel); late results from already-cancelled workers
    are routed to ``on_discard`` so the caller can roll back registration.
    """

    def __init__(
        self,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pool = thread_pool or QThreadPool.globalInstance()
        # worker → (cancel_event, label, busy, on_discard)
        self._active: dict[
            LoadWorker,
            tuple[
                threading.Event | None,
                str | None,
                BusyOverlay | None,
                Callable[[LoadOutcome], None] | None,
            ],
        ] = {}
        self._cancelled: set[LoadWorker] = set()

    def submit(
        self,
        load_callable: Callable[[], LoadOutcome],
        *,
        task: LoadTask | None = None,
        busy: BusyOverlay | None = None,
        on_success: Callable[[LoadOutcome], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        cancel_event: threading.Event | None = None,
        label: str | None = None,
        on_cancelled: Callable[[], None] | None = None,
        on_discard: Callable[[LoadOutcome], None] | None = None,
    ) -> None:
        """Begin loading: flag task, then run *load_callable* off-thread."""
        if task is not None:
            task.begin()

        worker = LoadWorker(load_callable)
        self._active[worker] = (cancel_event, label, busy, on_discard)
        worker.signals.finished.connect(
            lambda outcome: self._finish(worker, outcome, task, on_success)
        )
        worker.signals.failed.connect(
            lambda exc: self._fail(worker, exc, task, on_error, on_cancelled)
        )
        self._refresh_busy(busy)
        self._pool.start(worker)

    def cancel_active(self) -> None:
        """Cancel every active load: hard (events) + soft (immediate UI release)."""
        busies = set()
        for worker, (event, _label, busy, _discard) in self._active.items():
            if event is not None:
                event.set()
            self._cancelled.add(worker)
            if busy is not None:
                busies.add(busy)
        for busy in busies:
            busy.hide()

    def _pop(
        self, worker: LoadWorker
    ) -> tuple[
        threading.Event | None,
        str | None,
        BusyOverlay | None,
        Callable[[LoadOutcome], None] | None,
    ]:
        info = self._active.pop(worker)
        was_cancelled = worker in self._cancelled
        self._cancelled.discard(worker)
        if not was_cancelled:
            self._refresh_busy(info[2])
        return info if not was_cancelled else (info[0], info[1], None, info[3])

    def _refresh_busy(self, busy: BusyOverlay | None) -> None:
        """Count-based visibility: label for 1, count for N, hide at 0."""
        if busy is None:
            return
        labels = [
            label
            for w, (_e, label, b, _d) in self._active.items()
            if b is busy and w not in self._cancelled
        ]
        if not labels:
            busy.hide()
            return
        if len(labels) == 1:
            busy.set_message(f"読み込み中: {labels[0] or 'ファイル'}")
        else:
            busy.set_message(f"{len(labels)} ファイルを読み込み中")
        busy.show()

    def _finish(
        self,
        worker: LoadWorker,
        outcome: LoadOutcome,
        task: LoadTask | None,
        on_success: Callable[[LoadOutcome], None] | None,
    ) -> None:
        was_cancelled = worker in self._cancelled
        _event, _label, _busy, on_discard = self._pop(worker)
        if was_cancelled:
            # 手遅れ完走: task はまだ "loading" のまま(failed 経路の LoadCancelled
            # と違い、この経路は例外を投げないので task.cancel() を明示しないと
            # 固着する)。登録の巻き戻しは呼び出し側に委ねる(spec §5)。
            if task is not None:
                task.cancel()
            if on_discard is not None:
                on_discard(outcome)
            return
        if task is not None:
            task.succeed(outcome.key)
        if on_success is not None:
            on_success(outcome)

    def _fail(
        self,
        worker: LoadWorker,
        exc: Exception,
        task: LoadTask | None,
        on_error: Callable[[Exception], None] | None,
        on_cancelled: Callable[[], None] | None,
    ) -> None:
        was_cancelled = worker in self._cancelled
        self._pop(worker)
        if isinstance(exc, LoadCancelled) or was_cancelled:
            # ユーザー起点の正常系 — エラー面へ流さない(spec §4.1/§6)
            if task is not None:
                task.cancel()
            if on_cancelled is not None:
                on_cancelled()
            return
        if task is not None:
            task.fail(str(exc))
        if on_error is not None:
            on_error(exc)
