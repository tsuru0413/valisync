"""GraphAreaVM — tabbed container ViewModel (Task 3.2).

Pure Python, no PySide6/Qt imports.  Access to core only via Session.

Model: a tabbed container where each tab holds one or more GraphPanelVM
instances and an x-axis-sync flag.  Mutations notify subscribers with a
descriptive change tag so the Qt layer can decide what to refresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from valisync.core.session import Session
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

    def __init__(self, session: Session) -> None:
        super().__init__()
        self._session = session
        # Start with one tab containing one empty GraphPanelVM.
        self._tabs: list[_Tab] = [_Tab(name="Tab 1", panels=[GraphPanelVM(session)])]
        self.active_tab_index: int = 0

    # ─── Tab management ───────────────────────────────────────────────────────

    def add_tab(self, name: str | None = None) -> int:
        """Create a new tab, make it active, and return its index.

        Auto-generates "Tab N" when *name* is None.
        """
        if name is None:
            name = f"Tab {len(self._tabs) + 1}"
        self._tabs.append(_Tab(name=name, panels=[GraphPanelVM(self._session)]))
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
        self._tabs.pop(index)
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

    def add_panel(self, tab_index: int) -> int:
        """Append a new GraphPanelVM to the tab at *tab_index*.

        Raises ValueError when the tab already has 8 panels (R6.5).
        Returns the index of the new panel.
        """
        tab = self._tabs[tab_index]
        if len(tab.panels) >= 8:
            raise ValueError("Tab already has 8 panels — the maximum allowed (R6.5)")
        tab.panels.append(GraphPanelVM(self._session))
        self._notify("panels")
        return len(tab.panels) - 1

    def remove_panel(self, tab_index: int, panel_index: int) -> None:
        """Remove the panel at *panel_index* from the tab at *tab_index*.

        Raises ValueError when only one panel remains in the tab (R6.6).
        """
        tab = self._tabs[tab_index]
        if len(tab.panels) == 1:
            raise ValueError("Cannot remove the last remaining panel from a tab")
        tab.panels.pop(panel_index)
        self._notify("panels")

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
        for panel in tab.panels:
            panel.set_x_range(lo, hi)

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
