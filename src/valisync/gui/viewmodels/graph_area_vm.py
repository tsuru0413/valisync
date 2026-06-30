"""GraphAreaVM — tabbed container ViewModel (Task 3.2).

Pure Python, no PySide6/Qt imports.  Access to core only via Session.

Model: a tabbed container where each tab holds one or more GraphPanelVM
instances and an x-axis-sync flag.  Mutations notify subscribers with a
descriptive change tag so the Qt layer can decide what to refresh.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.viewmodels.observable import Observable


@dataclass
class _Tab:
    """Internal representation of one tab."""

    name: str
    panels: list[GraphPanelVM] = field(default_factory=list)
    x_sync_enabled: bool = True


class GraphAreaVM(Observable):
    """ViewModel for the tabbed graph area.

    Invariants maintained at all times:
    - At least one tab exists (R5.6).
    - Each tab has at least one panel and at most eight panels (R6.5, R6.6).
    - active_tab_index is always a valid index into _tabs.
    """

    def __init__(self, app_vm: AppViewModel) -> None:
        super().__init__()
        self._app_vm = app_vm
        self._session = app_vm.session
        # Guards re-entrancy while pushing a synced range to sibling panels.
        self._propagating = False
        self._panel_unsubs: dict[int, Callable[[], None]] = {}
        # Start with one tab containing one empty GraphPanelVM.
        first_panel = GraphPanelVM(self._session)
        self._tabs: list[_Tab] = [_Tab(name="Tab 1", panels=[first_panel])]
        self.active_tab_index: int = 0
        self._subscribe_panel(first_panel)
        # Own panel reconciliation for app-level data events (load/unload).
        self._app_unsub = app_vm.subscribe(self._on_app_change)

    # ─── App-level reconciliation ─────────────────────────────────────────────

    def _on_app_change(self, change: str) -> None:
        """Reconcile every panel against the Session on app-level data events.

        On ``"loaded"`` a signal added before its data existed must re-render;
        on ``"unloaded"`` panels drop signals whose group is gone (R7.4). This is
        the panel coordination previously done by ``MainWindow``.
        """
        if change == "loaded":
            self._for_each_panel(lambda p: p.refresh())
        elif change == "unloaded":
            self._for_each_panel(lambda p: p.prune_missing_signals())
        elif change == "offsets":
            # R14.5: push the latest offsets to EVERY panel (all tabs) and
            # re-render. _for_each_panel spans all tabs (propagate_cursor is
            # tab-local and must NOT be reused here).
            sig_off = self._app_vm.signal_offsets
            file_off = self._app_vm.file_offsets

            def _apply(p: GraphPanelVM) -> None:
                p.set_offsets(sig_off, file_off)
                p.refresh()

            self._for_each_panel(_apply)

    def _for_each_panel(self, fn: Callable[[GraphPanelVM], None]) -> None:
        """Apply *fn* to every panel across all tabs."""
        for tab in self._tabs:
            for panel in tab.panels:
                fn(panel)

    # ─── X-sync wiring ────────────────────────────────────────────────────────

    def _subscribe_panel(self, panel: GraphPanelVM) -> None:
        """Watch *panel* so its X-range changes can drive synced siblings."""

        def on_change(change: str) -> None:
            self._on_panel_change(panel, change)

        self._panel_unsubs[id(panel)] = panel.subscribe(on_change)

    def _unsubscribe_panel(self, panel: GraphPanelVM) -> None:
        unsub = self._panel_unsubs.pop(id(panel), None)
        if unsub is not None:
            unsub()

    def _on_panel_change(self, panel: GraphPanelVM, change: str) -> None:
        """Propagate a panel's X-range (when synced) or cursor (always) to siblings."""
        if self._propagating:
            return
        for tab_index, tab in enumerate(self._tabs):
            if panel not in tab.panels:
                continue
            if change == "range" and tab.x_sync_enabled and panel.x_range is not None:
                lo, hi = panel.x_range
                self.propagate_x_range(tab_index, lo, hi)
            elif change == "cursor":
                # Cursor is a time value broadcast to all sibling panels regardless
                # of the X-sync toggle; each panel renders it within its own range.
                self.propagate_cursor(tab_index, panel.cursor_t)
            return

    # ─── Tab management ───────────────────────────────────────────────────────

    def add_tab(self, name: str | None = None) -> int:
        """Create a new tab, make it active, and return its index.

        Auto-generates "Tab N" when *name* is None.
        """
        if name is None:
            name = f"Tab {len(self._tabs) + 1}"
        panel = GraphPanelVM(self._session)
        self._tabs.append(_Tab(name=name, panels=[panel]))
        self._subscribe_panel(panel)
        self.active_tab_index = len(self._tabs) - 1
        self._notify("tabs")
        return self.active_tab_index

    def remove_tab(self, index: int) -> None:
        """Remove the tab at *index*.

        Raises ValueError when only one tab remains (R5.6).
        Adjusts active_tab_index so it stays valid after removal.
        """
        if len(self._tabs) == 1:
            raise ValueError("Cannot remove the last remaining tab")
        removed = self._tabs.pop(index)
        for panel in removed.panels:
            self._unsubscribe_panel(panel)
        # Keep active index valid: if we removed the active tab or a tab
        # before it, clamp to the new length.
        if self.active_tab_index >= len(self._tabs):
            self.active_tab_index = len(self._tabs) - 1
        elif index < self.active_tab_index:
            self.active_tab_index -= 1
        self._notify("tabs")

    def rename_tab(self, index: int, name: str) -> None:
        """Rename the tab at *index*.

        Raises ValueError when len(name) is not in [1, 32] (R5.4).
        """
        if not (1 <= len(name) <= 32):
            raise ValueError(
                f"Tab name must be between 1 and 32 characters, got {len(name)}"
            )
        self._tabs[index].name = name
        self._notify("tabs")

    def set_active_tab(self, index: int) -> None:
        """Make the tab at *index* the active tab."""
        self.active_tab_index = index
        self._notify("active")

    # ─── Panel management ────────────────────────────────────────────────────

    def add_panel(self, tab_index: int | None = None) -> int:
        """Append a new GraphPanelVM to the tab at *tab_index*.

        Defaults to the active tab if *tab_index* is None.
        Raises ValueError when the tab already has 8 panels (R6.5).
        Returns the index of the new panel.
        """
        if tab_index is None:
            tab_index = self.active_tab_index
        tab = self._tabs[tab_index]
        if len(tab.panels) >= 8:
            raise ValueError("Tab already has 8 panels — the maximum allowed (R6.5)")
        panel = GraphPanelVM(self._session)
        tab.panels.append(panel)
        self._subscribe_panel(panel)
        self._notify("panels")
        return len(tab.panels) - 1

    def remove_panel(self, tab_index: int, panel_index: int) -> None:
        """Remove the panel at *panel_index* from the tab at *tab_index*.

        Raises ValueError when only one panel remains in the tab (R6.6).
        """
        tab = self._tabs[tab_index]
        if len(tab.panels) == 1:
            raise ValueError("Cannot remove the last remaining panel from a tab")
        panel = tab.panels.pop(panel_index)
        self._unsubscribe_panel(panel)
        self._notify("panels")

    def move_axis_across_panels(
        self,
        tab_index: int,
        src_panel_index: int,
        axis_index: int,
        dst_panel_index: int,
        column: int,
        position: int | None = None,
    ) -> None:
        """Move an axis (with its signals + settings) from one panel to another in
        the same tab. Same-panel (src==dst) is a no-op (the View routes same-panel
        drags to the panel's own move_axis_to_column). Stale indices are no-ops.
        """
        panels = self.panels(tab_index)
        if not (
            0 <= src_panel_index < len(panels) and 0 <= dst_panel_index < len(panels)
        ):
            return
        if src_panel_index == dst_panel_index:
            return
        src, dst = panels[src_panel_index], panels[dst_panel_index]
        moved = src.extract_axis(axis_index)
        if moved is None:
            return
        axis, entries = moved
        dst.insert_axis(axis, entries, column, position)

    # ─── X-axis sync ─────────────────────────────────────────────────────────

    def set_x_sync(self, tab_index: int, enabled: bool) -> None:
        """Enable or disable x-axis synchronisation for the tab (R7.3)."""
        self._tabs[tab_index].x_sync_enabled = enabled
        self._notify("sync")

    def propagate_x_range(self, tab_index: int, lo: float, hi: float) -> None:
        """If sync is enabled, push (lo, hi) to every panel in the tab (R7.1/R7.2).

        When sync is disabled nothing happens — panels stay independent (R7.4).
        """
        tab = self._tabs[tab_index]
        if not tab.x_sync_enabled:
            return
        # Guard so each sibling's resulting "range" notify doesn't re-trigger
        # _on_panel_change and recurse.
        self._propagating = True
        try:
            for panel in tab.panels:
                panel.set_x_range(lo, hi)
        finally:
            self._propagating = False

    def propagate_cursor(self, tab_index: int, t: float | None) -> None:
        """Push cursor time *t* to every panel in the tab (R15.1), guarded against re-entry."""
        self._propagating = True
        try:
            for panel in self._tabs[tab_index].panels:
                panel.set_cursor(t)
        finally:
            self._propagating = False

    def apply_offset(self, signal_key: str, delta_t: float, scope: str) -> None:
        """Forward an offset request to the AppViewModel (View-layer wiring target).

        The resulting 'offsets' notification is handled by _on_app_change, which
        broadcasts to all panels. Keeps GraphPanelView decoupled from AppViewModel.
        """
        self._app_vm.apply_offset(signal_key, delta_t, scope)

    # ─── Accessors ───────────────────────────────────────────────────────────

    def tabs(self) -> list[_Tab]:
        """Return a read-only view of the tab list."""
        return list(self._tabs)

    def active_tab(self) -> _Tab:
        """Return the currently active tab."""
        return self._tabs[self.active_tab_index]

    def panels(self, tab_index: int) -> list[GraphPanelVM]:
        """Return the panels list for the tab at *tab_index*."""
        return list(self._tabs[tab_index].panels)

    # ─── Introspection ───────────────────────────────────────────────────────

    def inspect(self) -> dict[str, Any]:
        """Return a structured snapshot of the ViewModel state.

        Suitable for headless test assertions and AI-agent introspection.
        """
        return {
            "active_tab_index": self.active_tab_index,
            "tabs": [
                {
                    "name": tab.name,
                    "panel_count": len(tab.panels),
                    "x_sync_enabled": tab.x_sync_enabled,
                }
                for tab in self._tabs
            ],
        }
