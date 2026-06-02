"""ChannelBrowserVM — hierarchical signal browser, pure Python (no Qt imports).

Presents Session signals grouped by source key > signal name.  Supports
incremental substring filtering, selection state, and per-signal visibility
toggling.  All state changes broadcast a short change tag via _notify so that
Qt (or test code) can react without polling.

The key separator ``"::"`` is treated as a documented contract: a group key
contains no ``"::"`` and the namespaced signal name is ``"<key>::<origname>"``.
We deliberately do NOT import the KEY_SEPARATOR constant from core internals to
keep this ViewModel free of core package coupling beyond Session and models.
"""

from __future__ import annotations

from typing import Any

from valisync.core.session import Session
from valisync.gui.viewmodels.observable import Observable

_SEP = "::"


class ChannelBrowserVM(Observable):
    """ViewModel for the channel-browser panel.

    Parameters
    ----------
    session:
        The application Session to read signals from.
    """

    def __init__(self, session: Session) -> None:
        super().__init__()
        self._session = session
        self._filter_text: str = ""
        self._selection: list[str] = []
        # visibility defaults to True; only keys explicitly toggled-off are stored.
        self._hidden: set[str] = set()

    # ─── Core query ──────────────────────────────────────────────────────────

    def tree(self) -> list[dict[str, Any]]:
        """Return the filtered hierarchical signal tree.

        Structure::

            [
              {
                "key": str,           # group key, e.g. "csv_1"
                "signals": [
                  {
                    "name": str,        # namespaced, e.g. "csv_1::speed"
                    "display_name": str,# original, e.g. "speed"
                    "dtype": str,       # numpy dtype string
                    "count": int,       # number of samples
                    "time_range": tuple[float, float] | None,
                    "visible": bool,
                  },
                  ...
                ]
              },
              ...
            ]

        Groups whose signals are all filtered out are omitted from the result.
        """
        filter_lower = self._filter_text.lower()
        groups: dict[str, list[dict[str, Any]]] = {}

        for sig in self._session.signals():
            parts = sig.name.split(_SEP, 1)
            if len(parts) == 2:
                key, orig_name = parts
            else:
                # Defensive: a name without the "::" namespace separator cannot
                # arise today (SignalGroupManager namespaces every signal) but a
                # future Derived signal might — group it under its full name
                # rather than crash the whole browser.
                key = orig_name = sig.name

            if filter_lower and filter_lower not in orig_name.lower():
                continue

            n = len(sig.timestamps)
            if n > 0:
                time_range: tuple[float, float] | None = (
                    float(sig.timestamps[0]),
                    float(sig.timestamps[-1]),
                )
            else:
                time_range = None

            leaf: dict[str, Any] = {
                "name": sig.name,
                "display_name": orig_name,
                "dtype": str(sig.values.dtype),
                "count": n,
                "time_range": time_range,
                "visible": sig.name not in self._hidden,
            }

            groups.setdefault(key, []).append(leaf)

        return [{"key": k, "signals": v} for k, v in groups.items()]

    # ─── Refresh ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-read signals from the Session and notify subscribers."""
        self._notify("tree")

    # ─── Filter ──────────────────────────────────────────────────────────────

    def set_filter(self, text: str) -> None:
        """Set the incremental substring filter and notify subscribers.

        An empty string clears the filter (all signals visible).
        Matching is case-insensitive and applied to the original signal name
        (the portion after the ``"::"`` separator).
        """
        self._filter_text = text
        self._notify("filter")

    # ─── Selection ───────────────────────────────────────────────────────────

    def set_selection(self, signal_keys: list[str]) -> None:
        """Replace the current selection with *signal_keys* (namespaced names)."""
        self._selection = list(signal_keys)

    def selected(self) -> list[str]:
        """Return the current selection as a list of namespaced signal names."""
        return list(self._selection)

    # ─── Visibility ──────────────────────────────────────────────────────────

    def toggle_visibility(self, signal_key: str) -> None:
        """Flip the visibility of *signal_key*.

        Signals are visible by default; the first toggle hides them.
        """
        if signal_key in self._hidden:
            self._hidden.discard(signal_key)
        else:
            self._hidden.add(signal_key)

    def is_visible(self, signal_key: str) -> bool:
        """Return True if *signal_key* is currently visible (default: True)."""
        return signal_key not in self._hidden

    def visible_signal_keys(self) -> list[str]:
        """Return the namespaced names of all currently-visible loaded signals."""
        return [
            sig.name for sig in self._session.signals() if sig.name not in self._hidden
        ]

    # ─── Introspection ───────────────────────────────────────────────────────

    def inspect(self) -> dict[str, Any]:
        """Return a structured snapshot of ViewModel state.

        Suitable for headless test assertions and AI-agent introspection.
        """
        tree = self.tree()
        tree_summary = [
            {"key": g["key"], "signal_count": len(g["signals"])} for g in tree
        ]
        return {
            "filter_text": self._filter_text,
            "selection": list(self._selection),
            "visibility_map": {
                sig.name: sig.name not in self._hidden
                for sig in self._session.signals()
            },
            "tree_summary": tree_summary,
        }
