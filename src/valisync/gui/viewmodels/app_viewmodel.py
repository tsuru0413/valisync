"""AppViewModel — application-level state, pure Python (no Qt imports).

The single ViewModel that the main window binds to.  All core access goes
through ``valisync.core.session.Session``; this module must never import
other core internals directly.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from valisync.core.models import FormatDefinition, Signal
from valisync.core.session import Session
from valisync.gui.viewmodels.observable import Observable


class AppViewModel(Observable):
    """Application-level ViewModel holding session state.

    Parameters
    ----------
    session:
        An existing ``Session`` to use.  When *None* a fresh ``Session()``
        is constructed.  Passing a custom session is useful for integration
        tests that need to pre-load data.
    """

    def __init__(self, session: Session | None = None) -> None:
        super().__init__()
        self._session: Session = session if session is not None else Session()
        self._loaded_keys: list[str] = []
        self._active_tab: int = 0
        self._data_sources: list[str] = []

    # ─── Load ────────────────────────────────────────────────────────────────

    def request_load(
        self,
        path: Path | str,
        format_def: FormatDefinition | None = None,
    ) -> str:
        """Load *path* via the Session and record the returned group key.

        NOTE: async worker-thread loading is out of scope for this task;
        loading is synchronous here and a later task will introduce threading.

        Parameters
        ----------
        path:
            File path to load.
        format_def:
            Required for CSV files; ignored for MDF4.

        Returns
        -------
        str
            The group key assigned by the Session (e.g. ``"csv_1"``).
        """
        key = self._session.load(Path(path), format_def)
        self._loaded_keys.append(key)
        self._notify("loaded")
        return key

    # ─── Signals proxy ───────────────────────────────────────────────────────

    def signals(self) -> list[Signal]:
        """Return the full namespaced signal list from the underlying Session."""
        return self._session.signals()

    # ─── Data sources ────────────────────────────────────────────────────────

    def add_data_source(self, path: Path | str) -> None:
        """Register a data-source folder path and notify subscribers."""
        self._data_sources.append(str(path))
        self._notify("data_sources")

    def remove_data_source(self, path: Path | str) -> None:
        """Remove a data-source folder path (no-op if absent) and notify."""
        key = str(path)
        with contextlib.suppress(ValueError):
            self._data_sources.remove(key)
        self._notify("data_sources")

    # ─── Inspection ──────────────────────────────────────────────────────────

    def inspect(self) -> dict[str, object]:
        """Return a structured snapshot of application state.

        Suitable for headless test assertions and AI-agent introspection.
        """
        return {
            "loaded_keys": list(self._loaded_keys),
            "active_tab": self._active_tab,
            "data_sources": list(self._data_sources),
        }
