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
        # Reference file (E-2a) — defaults to the first loaded file, migrates to
        # the surviving load-order head on unload. Transient (never persisted,
        # same as the offsets below — F-1 handles .vsession).
        self._reference_file_key: str | None = None
        # Time-offset state (R14) — transient, never persisted (Phase 3).
        # signal_offsets: keyed by namespaced signal name (e.g. "csv_1::speed").
        # file_offsets: keyed by group key (e.g. "csv_1"). Both are additive
        # deltas applied to the ORIGINAL session signal at render time.
        self._signal_offsets: dict[str, float] = {}
        self._file_offsets: dict[str, float] = {}
        self._teardown: object | None = None  # duck-typed: enqueue(key, group)
        self._releasing: dict[str, str] = {}  # key -> display name (capture at unload)

    @property
    def session(self) -> Session:
        """The shared Session (so sibling ViewModels read the same data)."""
        return self._session

    @property
    def signal_offsets(self) -> dict[str, float]:
        """Per-signal time offsets (copy), keyed by namespaced signal name."""
        return dict(self._signal_offsets)

    @property
    def file_offsets(self) -> dict[str, float]:
        """Per-group time offsets (copy), keyed by group key."""
        return dict(self._file_offsets)

    def apply_offset(self, signal_key: str, delta_t: float, scope: str) -> None:
        """Accumulate a time offset for *signal_key* and notify ('offsets').

        ``scope="signal"`` adds ``delta_t`` to the per-signal offset; ``scope="group"``
        adds it to the per-group (file) offset keyed by the group prefix. Offsets are
        additive on the original session signal (R14.3); the render path applies them
        via Session.apply_offset (a pure function).
        """
        if scope == "signal":
            self._signal_offsets[signal_key] = (
                self._signal_offsets.get(signal_key, 0.0) + delta_t
            )
        elif scope == "group":
            group_key = signal_key.split("::", 1)[0]
            self._file_offsets[group_key] = (
                self._file_offsets.get(group_key, 0.0) + delta_t
            )
            # Group apply discards sibling per-signal adjustments so the whole
            # group lands on one uniform offset (user decision): drop every
            # signal_offset under this group's "<group>::" prefix.
            self._purge_signal_offsets_under(group_key)
        else:
            raise ValueError(f"scope must be 'signal' or 'group', got {scope!r}")
        self._notify("offsets")

    def reset_offset(self, signal_key: str, scope: str) -> None:
        """Zero the time offset for *signal_key* and notify ('offsets').

        Symmetric to apply_offset: ``scope="signal"`` drops the per-signal offset;
        ``scope="group"`` drops the per-group (file) offset AND every sibling
        per-signal offset under the group prefix (whole group back to zero). Emits
        the same 'offsets' notification, so the existing GraphAreaVM broadcast
        re-renders every panel.
        """
        if scope == "signal":
            self._signal_offsets.pop(signal_key, None)
        elif scope == "group":
            group_key = signal_key.split("::", 1)[0]
            self._file_offsets.pop(group_key, None)
            self._purge_signal_offsets_under(group_key)
        else:
            raise ValueError(f"scope must be 'signal' or 'group', got {scope!r}")
        self._notify("offsets")

    def _purge_signal_offsets_under(self, group_key: str) -> None:
        """Drop every per-signal offset whose key is under *group_key* (``"<group>::"`` prefix)."""
        prefix = f"{group_key}::"
        for sk in [k for k in self._signal_offsets if k.startswith(prefix)]:
            del self._signal_offsets[sk]

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
        if key == self._active_file_key:
            # FU-22: 同一キー再選択は state 不変。無条件 notify は ChannelBrowser の
            # 264k 行モデルを重複リビルドする (prod 実測 ~5s)。同一キーは no-op で根絶。
            return
        self._active_file_key = key
        self._notify("active_file")

    @property
    def reference_file_key(self) -> str | None:
        """The group key of the comparison "reference" file (E-2a), or None."""
        return self._reference_file_key

    def set_reference_file(self, key: str | None) -> None:
        """Set the reference file and notify subscribers ('reference').

        No-op (no notify) when *key* is already the current reference —
        mirrors :meth:`set_active_file`'s same-key guard.
        """
        if key == self._reference_file_key:
            return
        self._reference_file_key = key
        self._notify("reference")

    def set_teardown(self, service: object) -> None:
        """Inject the GUI-thread teardown service (duck-typed ``enqueue(key, group)``)."""
        self._teardown = service

    @property
    def releasing_files(self) -> list[tuple[str, str]]:
        """(key, display name) of files whose data is still draining, in order."""
        return list(self._releasing.items())

    def mark_released(self, key: str) -> None:
        """Called by the teardown service when *key*'s data is fully freed."""
        if self._releasing.pop(key, None) is not None:
            self._notify("releasing")

    def unload_file(self, key: str) -> None:
        """Unload a loaded file: remove its group and defer the ~10 GB dealloc.

        The heavy dealloc of the removed group is handed to the injected teardown
        service (byte-budget background drain) so the UI thread returns at once
        (FU-16). Logical close (loaded list / active file / offsets / prune) stays
        synchronous. Refused without side effects when a Derived_Signal depends on
        the group.
        """
        name = self._safe_source_name(key)
        result = self._session.remove_group(key)
        if not result.removed:
            return
        if key in self._loaded_keys:
            self._loaded_keys.remove(key)
        if self._reference_file_key == key:
            # Migrate to the surviving load-order head (spec §2) — completed
            # (and notified) before "unloaded" so FileBrowserVM's badge refresh
            # sees the new reference regardless of which tag it reacts to.
            self._reference_file_key = (
                self._loaded_keys[0] if self._loaded_keys else None
            )
            self._notify("reference")
        if self._active_file_key == key:
            self._active_file_key = None
            self._notify("active_file")
        self._file_offsets.pop(key, None)
        self._purge_signal_offsets_under(key)
        self._notify("unloaded")
        if result.removed_group is not None and self._teardown is not None:
            self._releasing[key] = name
            self._teardown.enqueue(key, result.removed_group)  # type: ignore[attr-defined]
            self._notify("releasing")
        # else: removed_group falls out of scope here -> immediate sync free.

    def _safe_source_name(self, key: str) -> str:
        try:
            return self._session.source_name(key)
        except KeyError:
            return key

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
        outcome = self._session.load(Path(path), format_def)
        self.register_loaded(outcome.key)
        return outcome.key

    def register_loaded(self, key: str) -> None:
        """Record an already-loaded group key and notify (GUI-thread side).

        The first ever load becomes the reference (E-2a, spec §2) — folded
        into the same "loaded" notify since FileBrowserVM refreshes on it.
        """
        if self._reference_file_key is None:
            self._reference_file_key = key
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
            "reference_file": self._reference_file_key,
            "signal_offsets": dict(self._signal_offsets),
            "file_offsets": dict(self._file_offsets),
        }
