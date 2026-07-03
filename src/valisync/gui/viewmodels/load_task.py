"""LoadTask — async-style load ViewModel with injectable execution (Task 4.1).

Pure Python, no PySide6/Qt imports.  Threading is explicitly out of scope;
the caller passes a zero-argument callable (e.g. ``lambda: session.load(...)``),
which is invoked synchronously inside ``run``.  The real worker-thread
integration in a later task can wrap ``run`` in a QRunnable without changing
this module.

State machine:
    idle → loading → done       (on success)
    idle → loading → error      (on exception)
    idle → loading → cancelled  (user-initiated abort — not an error; reached
                                  from both the failed path (LoadCancelled
                                  raised before completion) and the finished
                                  path (a worker that completes too late,
                                  after cancel_active() — the "手遅れ完走" case)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from valisync.gui.viewmodels.observable import Observable


class LoadTask(Observable):
    """Observable model for a single file-load operation.

    Attributes
    ----------
    state:
        One of ``"idle"``, ``"loading"``, ``"done"``, ``"error"``, ``"cancelled"``.
    result_key:
        The string key returned by the load callable on success; ``None``
        otherwise.
    error_message:
        The stringified exception message on failure; ``None`` otherwise.
    """

    def __init__(self) -> None:
        super().__init__()
        self.state: str = "idle"
        self.result_key: str | None = None
        self.error_message: str | None = None

    def begin(self) -> None:
        """Enter the loading state and notify (call on the GUI thread)."""
        self.state = "loading"
        self._notify("loading")

    def succeed(self, key: str) -> None:
        """Record the result key, enter the done state, and notify."""
        self.result_key = key
        self.state = "done"
        self._notify("done")

    def fail(self, message: str) -> None:
        """Record the error message, enter the error state, and notify."""
        self.error_message = message
        self.state = "error"
        self._notify("error")

    def cancel(self) -> None:
        """Enter the cancelled state and notify (user-initiated, not an error)."""
        self.state = "cancelled"
        self._notify("cancelled")

    def run(self, load_callable: Callable[[], str]) -> None:
        """Execute *load_callable* synchronously, driving state transitions.

        Transitions:
          1. ``begin()`` → "loading".
          2. Invoke ``load_callable()``.
          3a. On success: ``succeed(key)`` → "done".
          3b. On any exception: ``fail(message)`` → "error" (not re-raised).

        The threaded path (``workers.LoadController``) drives the same
        begin/succeed/fail transitions from queued signals instead.
        """
        self.begin()
        try:
            self.succeed(load_callable())
        except Exception as exc:
            self.fail(str(exc))

    def inspect(self) -> dict[str, Any]:
        """Return a structured snapshot of the task state.

        Suitable for headless test assertions and AI-agent introspection.
        """
        return {
            "state": self.state,
            "result_key": self.result_key,
            "error_message": self.error_message,
        }
