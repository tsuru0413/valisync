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
        self._active_file_key: str | None = None

    @property
    def session(self) -> Session:
        """The shared Session (so sibling ViewModels read the same data)."""
        return self._session

    @property
    def active_file_key(self) -> str | None:
        """The absolute path/key of the currently selected file."""
        return self._active_file_key

    @property
    def loaded_file_keys(self) -> list[str]:
        """List of keys (paths) for all currently loaded files."""
        return list(self._loaded_keys)

    def set_active_file(self, key: str | None) -> None:
        """Set the active file and notify subscribers ('active_file')."""
        self._active_file_key = key
        self._notify("active_file")

    # ─── Load ────────────────────────────────────────────────────────────────

    def request_load(
        self,
        path: Path | str,
        format_def: FormatDefinition | None = None,
    ) -> str:
        """Load *path* synchronously via the Session and record the group key.

        The threaded path runs ``session.load`` off-thread and calls
        :meth:`register_loaded` on the GUI thread instead.

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
        self.register_loaded(key)
        return key

    def register_loaded(self, key: str) -> None:
        """Record an already-loaded group key and notify (GUI-thread side)."""
        self._loaded_keys.append(key)
        self._notify("loaded")

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
            "active_file": self._active_file_key,
        }
