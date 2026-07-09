"""ChannelBrowserVM — flat signal browser for the active file.

Presents a flat list of signals for the currently selected file in AppViewModel.
Supports incremental substring filtering and selection state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from valisync.gui.viewmodels.observable import Observable

if TYPE_CHECKING:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

_SEP = "::"


@dataclass(frozen=True)
class SignalItem:
    """Represents a single signal entry in the browser list."""

    name: str  # Original name, e.g. "speed"
    unit: str  # Physical unit, e.g. "km/h"
    key: str  # Full namespaced key, e.g. "csv_1::speed"
    tooltip: str = ""  # value_labels のラベル行 (LD-07・空=ツールチップなし)


def _labels_tooltip(metadata: dict[str, Any] | None) -> str:
    """Render enum value_labels as a tooltip line, e.g. '0=OFF, 1=LEFT, 2=RIGHT'.

    Sorted by value ascending; truncated to the first 8 entries with a
    '… (全 n 件)' suffix beyond that (spec §3.3, LD-07).
    """
    labels = (metadata or {}).get("value_labels")
    if not labels:
        return ""
    items = sorted(labels.items())
    head = ", ".join(f"{v:g}={t}" for v, t in items[:8])
    if len(items) > 8:
        return f"ラベル: {head}, … (全 {len(items)} 件)"
    return f"ラベル: {head}"


class ChannelBrowserVM(Observable):
    """ViewModel for the channel-browser panel.

    Parameters
    ----------
    app_vm:
        The parent application ViewModel providing the active file context.
    """

    def __init__(self, app_vm: AppViewModel) -> None:
        super().__init__()
        self._app_vm = app_vm
        self._filter_text: str = ""
        self._selection: list[str] = []

        # Subscribe to AppViewModel events to react to file selection changes
        self._unsubscribe = self._app_vm.subscribe(self._on_app_change)

    @property
    def signals(self) -> list[SignalItem]:
        """Return the flat list of signals for the active file, filtered."""
        active_key = self._app_vm.active_file_key
        if not active_key:
            return []

        # Fetch only the active file's signals (no full-session scan).
        try:
            group_sigs = self._app_vm.session.group_signals(active_key)
        except KeyError:
            return []

        filter_lower = self._filter_text.lower()
        results: list[SignalItem] = []

        for sig in group_sigs:
            # sig.name is "{active_key}::{orig}"; strip the known prefix.
            orig_name = sig.name.split(_SEP, 1)[1] if _SEP in sig.name else sig.name

            if filter_lower and filter_lower not in orig_name.lower():
                continue

            unit = sig.metadata.get("unit", "") if sig.metadata else ""

            results.append(
                SignalItem(
                    name=orig_name,
                    unit=str(unit),
                    key=sig.name,
                    tooltip=_labels_tooltip(sig.metadata),
                )
            )

        return results

    # ─── Header / empty-state (FB-05/09) ────────────────────────────────────

    def _group_total(self) -> tuple[str, int] | None:
        """Return (basename, total channel count) for the active file, or None."""
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        try:
            total = len(self._app_vm.session.group_signals(active_key))
            name = self._app_vm.session.source_name(active_key)
        except KeyError:
            return None
        return name, total

    def header_text(self) -> str:
        """One-line context header: which file, how many shown of how many."""
        info = self._group_total()
        if info is None:
            return "ファイル未選択"
        name, total = info
        if total == 0:
            return f"{name} — 0 ch"
        return f"{name} — {total} ch 中 {len(self.signals)} 件表示"

    def empty_state(self) -> str:
        """Why the list is empty: none_selected / no_channels / no_match / has_rows."""
        info = self._group_total()
        if info is None:
            return "none_selected"
        if info[1] == 0:
            return "no_channels"
        if not self.signals:
            return "no_match"
        return "has_rows"

    def filter_query(self) -> str:
        """Current filter text (for the no_match placeholder message)."""
        return self._filter_text

    # ─── Refresh ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Manually trigger a refresh notification."""
        self._notify("signals")

    # ─── Filter ──────────────────────────────────────────────────────────────

    def set_filter(self, text: str) -> None:
        """Set the incremental substring filter and notify subscribers."""
        self._filter_text = text
        self._notify("filter")

    # ─── Selection ───────────────────────────────────────────────────────────

    def set_selection(self, signal_keys: list[str]) -> None:
        """Replace the current selection with *signal_keys* (namespaced names)."""
        self._selection = list(signal_keys)

    def selected(self) -> list[str]:
        """Return the current selection as a list of namespaced signal names."""
        return list(self._selection)

    # ─── Event Handling ──────────────────────────────────────────────────────

    def _on_app_change(self, change: str) -> None:
        """Handle notifications from AppViewModel."""
        if change == "active_file":
            self._notify("signals")

    # ─── Introspection ───────────────────────────────────────────────────────

    def inspect(self) -> dict[str, Any]:
        """Return a structured snapshot of ViewModel state."""
        return {
            "active_file": self._app_vm.active_file_key,
            "filter_text": self._filter_text,
            "selection": list(self._selection),
            "signal_count": len(self.signals),
        }
