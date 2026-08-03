"""Off-thread CSV export (SH-03 / E-4b).

ExportWorker runs an injected zero-arg export callable on a QThreadPool thread
and reports completion via queued signals. ExportController shows a BusyOverlay
while the export runs and drives success/error/cancel callbacks back on the GUI
thread, so the View stays responsive during large writes.

E-4b: 進捗 (ブロック単位) と協調キャンセルを運ぶ ``ExportRun`` を追加した。
``prepare()`` が **submit の前に** ハンドルを返すのは、export callable を組むのは
呼び出し側で、submit の後ではワーカーが走り出してから進捗を差し込む窓が無いから。
callable の引数を controller が規定しない形にしてあるので、**ゼロ引数 submit の
既存契約** (tests/gui/test_export_worker_compat.py) はそのまま生きる。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from valisync.core.export.csv_exporter import ExportCancelled
from valisync.gui import strings as S
from valisync.gui.views.busy_overlay import (
    acquire_busy,
    release_busy,
    set_busy_cancel_enabled,
    set_busy_progress,
)

if TYPE_CHECKING:
    from valisync.gui.views.busy_overlay import BusyOverlay


class ExportWorkerSignals(QObject):
    finished = Signal()
    failed = Signal(object)  # the raised Exception


class ExportRunSignals(QObject):
    progress = Signal(int, int)  # (done_units, total_units)


class ExportRun:
    """1 回のエクスポートに紐づく進捗シンクと協調キャンセル Event。

    ``ExportController.prepare()`` が **GUI スレッドで** 作る — QObject の affinity が
    GUI スレッドになり、ワーカースレッドからの emit が自動的に queued 配送になる
    (ワーカースレッドから直接 UI を触ると Qt が落ちる)。呼び出し側はこれを export
    callable へ close over して ``CsvExporter.export(progress=, cancel=)`` へ渡す。
    """

    __slots__ = ("cancel", "signals")

    def __init__(self) -> None:
        self.signals = ExportRunSignals()
        self.cancel = threading.Event()

    def progress(self, done: int, total: int) -> None:
        """ワーカースレッドから呼ぶ (queued で GUI スレッドへ運ばれる)。"""
        self.signals.progress.emit(int(done), int(total))


class ExportWorker(QRunnable):
    def __init__(
        self,
        export_callable: Callable[[], None],
        *,
        run: ExportRun,
        busy: BusyOverlay | None = None,
    ) -> None:
        super().__init__()
        self._export_callable = export_callable
        self.signals = ExportWorkerSignals()
        # run/busy は worker に持たせる (controller 側に第 2 の dict を作らない)。
        # `_active` を dict 化すると tests/gui/test_export_worker_compat.py の
        # 「`_active == set()` で保持解除を観測する」pin が壊れる — あの pin は
        # まさに Task 8/9 が壊しやすい不変条件として置かれたもの。
        # 名前が `export_run` なのは、`run` だと QRunnable.run() を **インスタンス
        # 属性で覆って** しまい pool が「呼べないもの」を呼ぶため。
        self.export_run = run
        self.busy = busy

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
        # so the callback (and the busy release) silently never fires.
        # E-4b: worker が run/busy も抱えるので、cancel_active が Event へ届く
        # 経路もこの集合が唯一の入口になった。
        self._active: set[ExportWorker] = set()

    def is_busy(self) -> bool:
        """エクスポートが実行中か (増分B: unload 拒否ガードの判定に使う)。

        submit で _active に入り _finish/_fail (GUI スレッドの queued スロット) で
        抜けるので、pool でワーカーが走り始める前から True になる — ガードとしては
        それが正しい (submit 直後の unload も拒否したい)。
        """
        return bool(self._active)

    def prepare(self) -> ExportRun:
        """submit の **前** に進捗/キャンセルのハンドルを渡す。

        export callable を組むのは呼び出し側なので、submit の後では間に合わない
        (ワーカーが走り出してから progress を差し込む窓は無い)。
        """
        return ExportRun()

    def submit(
        self,
        export_callable: Callable[[], None],
        *,
        run: ExportRun | None = None,
        busy: BusyOverlay | None = None,
        on_success: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_cancelled: Callable[[Exception], None] | None = None,
        label: str | None = None,
    ) -> None:
        run = run if run is not None else ExportRun()
        worker = ExportWorker(export_callable, run=run, busy=busy)
        self._active.add(worker)
        if busy is not None:
            acquire_busy(busy, self, S.BUSY_EXPORTING_TMPL.format(label=label or "CSV"))
            run.signals.progress.connect(
                lambda done, total: set_busy_progress(busy, self, done, total)
            )
        worker.signals.finished.connect(lambda: self._finish(worker, on_success))
        worker.signals.failed.connect(
            lambda exc: self._fail(worker, exc, on_error, on_cancelled)
        )
        self._pool.start(worker)

    def cancel_active(self) -> None:
        """実行中のエクスポートへ協調キャンセルを要求する。

        load 側 (soft-cancel = 即 UI 解放) と **意図的に非対称**: overlay は
        ExportCancelled が戻るまで下ろさない。temp を消し切る前に「中止した」と
        見せると、ユーザーは残骸が消える前に次のエクスポートを始められ、
        「失敗ならファイルが存在しない」(spec §10) の観測窓が壊れる。

        アイドルなら no-op — MainWindow のルータが全 controller へ無条件に配れる
        のはこの性質による (ルータに「今どれが動いているか」を持たせない)。
        """
        for worker in self._active:
            worker.export_run.cancel.set()
            if worker.busy is not None:
                # set_message でなく acquire (= 同一 owner の文言更新) を使うのは、
                # 所有者の記録側も書き換えるため。set_message だけだと、同時に走る
                # ロードが完了したときに release が **中止前の文言** を復元する。
                acquire_busy(worker.busy, self, S.BUSY_EXPORT_CANCELLING)
                set_busy_cancel_enabled(
                    worker.busy, False, owner=self
                )  # 二重押しを止める

    def _release(self, worker: ExportWorker) -> None:
        """*worker* の名義を返す (同じ overlay を掴む別 export が残っていれば保留)。"""
        busy = worker.busy
        if busy is None:
            return
        if any(other.busy is busy for other in self._active):
            return
        release_busy(busy, self)

    def _finish(
        self,
        worker: ExportWorker,
        on_success: Callable[[], None] | None,
    ) -> None:
        # Discard first: the signal has already been delivered by this point
        # (we're running inside its queued-connection slot), so releasing our
        # reference here cannot race the delivery it guards.
        self._active.discard(worker)
        self._release(worker)
        if on_success is not None:
            on_success()

    def _fail(
        self,
        worker: ExportWorker,
        exc: Exception,
        on_error: Callable[[Exception], None] | None,
        on_cancelled: Callable[[Exception], None] | None,
    ) -> None:
        self._active.discard(worker)
        self._release(worker)
        if isinstance(exc, ExportCancelled):
            # ユーザー起点 (と decay) の正常系 — エラー面へ流さない
            # (LoadCancelled が on_cancelled へ回るのと同型)。
            if on_cancelled is not None:
                on_cancelled(exc)
            return
        if on_error is not None:
            on_error(exc)
