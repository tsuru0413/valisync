"""LoadTask — async-style load ViewModel with injectable execution (Task 4.1).

Pure Python, no PySide6/Qt imports.  Threading is explicitly out of scope;
the caller passes a zero-argument callable (e.g. ``lambda: session.load(...)``),
which is invoked synchronously inside ``run``.  The real worker-thread
integration in a later task can wrap ``run`` in a QRunnable without changing
this module.

State machine:
    idle → loading → done   (on success)
    idle → loading → error  (on exception)
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
        One of ``"idle"``, ``"loading"``, ``"done"``, ``"error"``.
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

    def run(self, load_callable: Callable[[], str]) -> None:
        """Execute *load_callable* synchronously, driving state transitions.

        Transitions:
          1. Set state → "loading", notify.
          2. Invoke ``load_callable()``.
          3a. On success: store result_key, state → "done", notify.
          3b. On any exception: store error_message, state → "error", notify.
             The exception is *not* re-raised; the caller continues normally.
        """
        self.state = "loading"
        self._notify("loading")
        try:
            key = load_callable()
            self.result_key = key
            self.state = "done"
            self._notify("done")
        except Exception as exc:
            self.error_message = str(exc)
            self.state = "error"
            self._notify("error")

    def inspect(self) -> dict[str, Any]:
        """Return a structured snapshot of the task state.

        Suitable for headless test assertions and AI-agent introspection.
        """
        return {
            "state": self.state,
            "result_key": self.result_key,
            "error_message": self.error_message,
        }
