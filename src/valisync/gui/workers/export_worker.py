"""Off-thread CSV export (SH-03).

ExportWorker runs an injected zero-arg export callable on a QThreadPool thread
and reports completion via queued signals. ExportController shows a BusyOverlay
while the export runs and drives success/error callbacks back on the GUI thread,
so the View stays responsive during large writes (the exporter builds all rows
in memory then does one atomic write - the direct reason off-thread is needed).

Simpler than LoadController: export returns None and has no cancel/discard/task.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

if TYPE_CHECKING:
    from valisync.gui.views.busy_overlay import BusyOverlay


class ExportWorkerSignals(QObject):
    finished = Signal()
    failed = Signal(object)  # the raised Exception


class ExportWorker(QRunnable):
    def __init__(self, export_callable: Callable[[], None]) -> None:
        super().__init__()
        self._export_callable = export_callable
        self.signals = ExportWorkerSignals()

    def run(self) -> None:
        try:
            self._export_callable()
        except Exception as exc:  # report, never crash the pool thread
            self.signals.failed.emit(exc)
        else:
            self.signals.finished.emit()


class ExportController(QObject):
    def __init__(
        self,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pool = thread_pool or QThreadPool.globalInstance()
        # QThreadPool's autoDelete frees the QRunnable (and its `signals`
        # QObject) right after run() returns. Without a Python reference kept
        # here until the callback fires, GC can collect worker+signals before
        # the GUI thread's event loop delivers the queued finished/failed
        # signal - Qt purges undelivered posted events for destroyed QObjects,
        # so the callback (and busy.hide()) silently never fires. Not used for
        # cancel/discard/task tracking (export has none) - purely signal
        # delivery lifetime safety, same rationale as LoadController._active.
        self._active: set[ExportWorker] = set()

    def submit(
        self,
        export_callable: Callable[[], None],
        *,
        busy: BusyOverlay | None = None,
        on_success: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        label: str | None = None,
    ) -> None:
        if busy is not None:
            busy.set_message(f"エクスポート中: {label or 'CSV'}")
            busy.show()
        worker = ExportWorker(export_callable)
        self._active.add(worker)
        worker.signals.finished.connect(lambda: self._finish(worker, busy, on_success))
        worker.signals.failed.connect(
            lambda exc: self._fail(worker, busy, exc, on_error)
        )
        self._pool.start(worker)

    def _finish(
        self,
        worker: ExportWorker,
        busy: BusyOverlay | None,
        on_success: Callable[[], None] | None,
    ) -> None:
        # Discard first: the signal has already been delivered by this point
        # (we're running inside its queued-connection slot), so releasing our
        # reference here cannot race the delivery it guards.
        self._active.discard(worker)
        if busy is not None:
            busy.hide()
        if on_success is not None:
            on_success()

    def _fail(
        self,
        worker: ExportWorker,
        busy: BusyOverlay | None,
        exc: Exception,
        on_error: Callable[[Exception], None] | None,
    ) -> None:
        self._active.discard(worker)
        if busy is not None:
            busy.hide()
        if on_error is not None:
            on_error(exc)
