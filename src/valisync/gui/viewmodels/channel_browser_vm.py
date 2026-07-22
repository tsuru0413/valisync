"""ChannelBrowserVM — flat signal browser for the active file.

Presents a flat list of signals for the currently selected file in AppViewModel.
Supports incremental substring filtering and selection state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from valisync.gui import strings as S
from valisync.gui.viewmodels.observable import Observable

if TYPE_CHECKING:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

_SEP = "::"
_BASE_RE = re.compile(r"[\[.]")


def _base_of(orig: str) -> str:
    """Base channel name = orig up to the first LD-14 suffix marker ('[' or '.')."""
    m = _BASE_RE.search(orig)
    return orig[: m.start()] if m else orig


@dataclass(frozen=True)
class SignalItem:
    """Represents a single signal entry in the browser list."""

    name: str  # Original name, e.g. "speed"
    unit: str  # Physical unit, e.g. "km/h"
    key: str  # Full namespaced key, e.g. "csv_1::speed"


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

        # FU-11: active_key ごと 1 度だけ作る (orig, lower, unit, key) タプル列と、
        # (active_key, filter) でメモした結果。生存キーは counter 非減で不変信号集合に
        # 対応するため stale 化しない。無効化は _on_app_change("active_file") で行う。
        self._prep_key: str | None = None
        self._prep: list[tuple[str, str, str, str]] = []
        self._memo_key: tuple[str, str] | None = None
        self._memo_result: list[SignalItem] = []

    @property
    def signals(self) -> list[SignalItem]:
        """Return the flat list of signals for the active file, filtered.

        Memoised by (active_key, filter) so the three per-keystroke consumers
        (model reset + header_text + empty_state) share a single filter pass.
        """
        active_key = self._app_vm.active_file_key
        if not active_key:
            return []
        sig_key = (active_key, self._filter_text)
        if self._memo_key != sig_key:
            try:
                self._memo_result = self._filtered()
            except KeyError:
                self._memo_result = []
            self._memo_key = sig_key
        return self._memo_result

    def _ensure_prep(self) -> None:
        """Build the filter-independent (orig, lower, unit, key) tuples once per
        active file (FU-11). Reads session.group_signals dynamically so a
        monkeypatched session (tests) is honoured on the first lazy access."""
        active_key = self._app_vm.active_file_key
        if self._prep_key == active_key:
            return
        if not active_key:
            self._prep = []
            self._prep_key = active_key
            return
        group_sigs = self._app_vm.session.group_signals(active_key)  # Part A: cached
        prep: list[tuple[str, str, str, str]] = []
        for sig in group_sigs:
            orig = sig.name.split(_SEP, 1)[1] if _SEP in sig.name else sig.name
            unit = str(sig.metadata.get("unit", "")) if sig.metadata else ""
            prep.append((orig, orig.lower(), unit, sig.name))
        self._prep = prep
        self._prep_key = active_key

    def _filtered(self) -> list[SignalItem]:
        """Apply the current substring filter over the precomputed tuples,
        building a SignalItem only for matches (FU-11)."""
        self._ensure_prep()
        fl = self._filter_text.lower()
        if not fl:
            return [SignalItem(name=n, unit=u, key=k) for n, _lo, u, k in self._prep]
        return [
            SignalItem(name=n, unit=u, key=k) for n, lo, u, k in self._prep if fl in lo
        ]

    def shown_count(self) -> int:
        """Number of signals shown after the current filter, WITHOUT building
        SignalItems. header_text/empty_state need only the count; materializing
        264k SignalItems here was the residual ~263ms of the FU-22 B freeze."""
        self._ensure_prep()
        fl = self._filter_text.lower()
        if not fl:
            return len(self._prep)
        return sum(1 for _n, lo, _u, _k in self._prep if fl in lo)

    def tree_groups(self) -> list[tuple[str, list[tuple[str, str, str]]]]:
        """Group the active file's signals by base channel for the tree browser.

        Returns [(base, [(orig, unit, key), ...]), ...] in base first-seen order.
        Filtered by the current substring filter (fl in leaf name); a base appears
        only if at least one of its leaves matches. Empty filter -> all signals."""
        try:
            self._ensure_prep()
        except KeyError:
            # set_active_file() does not validate the key exists (FU-22 A), so a
            # notify can still be in flight for a key the session already
            # dropped. Same guard as signals/_group_total (FU-22 B: this became
            # production-reachable once ChannelBrowserView switched to
            # SignalTreeModel, whose _on_vm_change calls tree_groups() directly).
            return []
        fl = self._filter_text.lower()
        groups: dict[str, list[tuple[str, str, str]]] = {}
        order: list[str] = []
        for orig, lower, unit, key in self._prep:
            if fl and fl not in lower:
                continue
            base = _base_of(orig)
            bucket = groups.get(base)
            if bucket is None:
                bucket = groups[base] = []
                order.append(base)
            bucket.append((orig, unit, key))
        return [(b, groups[b]) for b in order]

    # ─── Header / empty-state (FB-05/09) ────────────────────────────────────

    def _group_total(self) -> tuple[str, int] | None:
        """Return (basename, total channel count) for the active file, or None."""
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        try:
            self._ensure_prep()  # prep hit なら追加 fetch なし
            name = self._app_vm.session.source_name(active_key)
        except KeyError:
            return None
        return name, len(self._prep)

    def header_text(self) -> str:
        """One-line context header: which file, how many shown of how many."""
        info = self._group_total()
        if info is None:
            return "ファイル未選択"
        name, total = info
        if total == 0:
            return S.CHANNEL_HEADER_EMPTY_TMPL.format(name=name)
        return S.CHANNEL_HEADER_COUNT_TMPL.format(
            name=name, total=total, shown=self.shown_count()
        )

    def empty_state(self) -> str:
        """Why the list is empty: none_selected / no_channels / no_match / has_rows."""
        info = self._group_total()
        if info is None:
            return "none_selected"
        if info[1] == 0:
            return "no_channels"
        if self.shown_count() == 0:
            return "no_match"
        return "has_rows"

    def filter_query(self) -> str:
        """Current filter text (for the no_match placeholder message)."""
        return self._filter_text

    # ─── Refresh ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Manually trigger a refresh notification."""
        self._prep_key = None  # FU-11: manually clear cache on explicit refresh
        self._memo_key = None
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

    # ─── Tooltip (PC-19/DP14) ────────────────────────────────────────────────

    def _signal_by_key(self, key: str) -> Any | None:
        """Look up the active file's Signal whose namespaced name == key."""
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        try:
            for sig in self._app_vm.session.group_signals(active_key):
                if sig.name == key:
                    return sig
        except KeyError:
            return None
        return None

    def tooltip_for(self, key: str) -> str:
        """Lazily assemble a multi-line tooltip for *key* (PC-19).

        Sections (absent lines omitted for CSV/Derived): unit / sample count
        (raw recorded len) / origin (bus_type, channel_group_name, source_name) /
        comment / value_labels. Time range is intentionally excluded.
        """
        sig = self._signal_by_key(key)
        if sig is None:
            return ""
        md = sig.metadata or {}
        lines: list[str] = []
        unit = md.get("unit", "")
        if unit:
            lines.append(f"単位: {unit}")
        lines.append(f"サンプル数: {len(sig.timestamps)}")
        origin = " / ".join(
            b
            for b in (
                sig.bus_type,
                md.get("channel_group_name", ""),
                md.get("source_name", ""),
            )
            if b
        )
        if origin:
            lines.append(f"由来: {origin}")
        comment = md.get("comment", "")
        if comment:
            lines.append(f"コメント: {comment}")
        labels = _labels_tooltip(md)  # "ラベル: ..." or ""
        if labels:
            lines.append(labels)
        return "\n".join(lines)

    # ─── Event Handling ──────────────────────────────────────────────────────

    def _on_app_change(self, change: str) -> None:
        """Handle notifications from AppViewModel."""
        if change == "active_file":
            self._prep_key = None  # FU-11: 別ファイルの prep/memo を捨てる
            self._memo_key = None
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
