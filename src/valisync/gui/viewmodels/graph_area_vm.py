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

from valisync.gui import strings as S
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_panel_vm import CursorState, GraphPanelVM
from valisync.gui.viewmodels.observable import Observable


@dataclass
class _Tab:
    """Internal representation of one tab."""

    name: str
    panels: list[GraphPanelVM] = field(default_factory=list)
    x_sync_enabled: bool = True
    active_panel_index: int = 0
    # タブ内全パネルが共有する計測カーソル状態 (spec §2.1)。default_factory は
    # 単体構築時の保険 — 実運用の生成点 (__init__/add_tab/add_panel) は常に
    # 同一オブジェクトをパネルとタブの双方へ明示注入する。
    cursor_state: CursorState = field(default_factory=CursorState)


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
        # Start with one tab containing one empty GraphPanelVM, sharing a single
        # CursorState with its tab from the outset (spec §2.1).
        first_cursor_state = CursorState()
        first_panel = self._make_panel(first_cursor_state)
        self._tabs: list[_Tab] = [
            _Tab(
                name=S.TAB_DEFAULT_TMPL.format(n=1),
                panels=[first_panel],
                cursor_state=first_cursor_state,
            )
        ]
        self.active_tab_index: int = 0
        self._subscribe_panel(first_panel)
        # Own panel reconciliation for app-level data events (load/unload).
        self._app_unsub = app_vm.subscribe(self._on_app_change)

    # ─── Panel factory ─────────────────────────────────────────────────────────

    def _make_panel(self, cursor_state: CursorState) -> GraphPanelVM:
        """Single construction point for every GraphPanelVM (spec §4.1).

        All 3 sites that create a panel (this __init__, add_tab, add_panel)
        route through here so the AppViewModel's hue resolver reaches every
        panel structurally — a per-call-site injection would silently regress
        the moment a 4th construction site is added (reviewer-flagged risk).
        """
        return GraphPanelVM(
            self._session,
            cursor_state=cursor_state,
            hue_resolver=self._app_vm.file_hue_resolver(),
        )

    # ─── App-level reconciliation ─────────────────────────────────────────────

    def _on_app_change(self, change: str) -> None:
        """Reconcile every panel against the Session on app-level data events.

        On ``"loaded"`` a signal added before its data existed must re-render,
        and every not-manually-pinned entry is recolored into its file's hue
        family (E-2c, spec §4.2 — reapply_auto_colors is a no-op when
        is_comparison_mode() is false, so a 1st load costs nothing extra
        here); on ``"unloaded"`` panels drop signals whose group is gone
        (R7.4) and are NOT recolored (spec §4.2's intentional non-symmetry —
        existing colors stay put). On ``"comparison_mode"`` (the user
        toggling comparison mode on/off, comparison-mode-toggle spec §4)
        every panel reapplies auto colors the same way — ON recolors into
        hue families, OFF is a no-op that freezes existing colors. This is
        the panel coordination previously done by ``MainWindow``.
        """
        if change == "loaded":

            def _reconcile(p: GraphPanelVM) -> None:
                p.refresh()
                p.reapply_auto_colors()

            self._for_each_panel(_reconcile)
        elif change == "unloaded":
            self._for_each_panel(lambda p: p.prune_missing_signals())
        elif change == "comparison_mode":
            # ON: recolor autos into hue families. OFF: reapply is a
            # structural no-op (resolver returns None for every group ->
            # reapply_auto_colors' `continue` on `hue is None` leaves
            # existing colors untouched), so the SAME call gives
            # freeze-on-OFF for free (spec §4, user decision 3). No ON/OFF
            # branching needed.
            self._for_each_panel(lambda p: p.reapply_auto_colors())
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
        """Propagate a panel's X-range (when synced) or cursor/delta (always) to siblings."""
        if self._propagating:
            return
        for tab_index, tab in enumerate(self._tabs):
            if panel not in tab.panels:
                continue
            if change == "range" and tab.x_sync_enabled and panel.x_range is not None:
                lo, hi = panel.x_range
                self.propagate_x_range(tab_index, lo, hi)
            elif change in ("cursor", "delta"):
                # CursorState is a SHARED object per tab (spec §2.1): every
                # sibling panel already reads the post-change value the instant
                # it's written, so there is nothing to push. Distribution is a
                # bare re-emit of the SAME tag so each sibling's own View
                # (subscribed only to its own panel VM) refreshes via the
                # lightweight cursor-line path instead of falling back to a
                # full refresh() (any OTHER tag would). NEVER call
                # _invalidate_cache here — cursor is not part of the render
                # cache key, so invalidating on every cursor move would nuke
                # the tab's whole LOD cache for nothing (perf regression).
                self._broadcast_tag(tab_index, change)
                self._notify("cursor")  # area-level: statusbar/readout pull (§2.4)
            return

    def _broadcast_tag(self, tab_index: int, tag: str) -> None:
        """Re-emit *tag* on every panel of the tab at *tab_index*.

        Loops over ALL panels in the tab, including the one that originated
        the change — same shape as the pre-sharing propagate_cursor/
        propagate_x_range — and relies on _propagating to short-circuit the
        resulting re-entrant _on_panel_change calls rather than special-
        casing the source panel out of the loop.
        """
        self._propagating = True
        try:
            for sibling in self._tabs[tab_index].panels:
                sibling._notify(tag)
        finally:
            self._propagating = False

    # ─── Tab management ───────────────────────────────────────────────────────

    def add_tab(self, name: str | None = None) -> int:
        """Create a new tab, make it active, and return its index.

        Auto-generates "Tab N" when *name* is None.
        """
        if name is None:
            name = S.TAB_DEFAULT_TMPL.format(n=len(self._tabs) + 1)
        # New tab gets its OWN fresh CursorState (spec §2.1) — tabs are
        # independent measurement contexts, never sharing across tabs.
        cursor_state = CursorState()
        panel = self._make_panel(cursor_state)
        self._tabs.append(_Tab(name=name, panels=[panel], cursor_state=cursor_state))
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
        # Share the tab's existing CursorState (spec §2.1 blocker): a new panel
        # must see whatever A/B/Δ is already live in the tab, not roll it back.
        panel = self._make_panel(tab.cursor_state)
        tab.panels.append(panel)
        self._subscribe_panel(panel)
        # PC-07: 作った=使う。新規パネルを自動アクティブ化("panels" の rebuild が
        # 枠を再適用するので "active_panel" は重ねて出さない)。
        tab.active_panel_index = len(tab.panels) - 1
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
        if tab.active_panel_index >= len(tab.panels):
            tab.active_panel_index = len(tab.panels) - 1
        elif panel_index < tab.active_panel_index:
            tab.active_panel_index -= 1
        self._notify("panels")

    def set_active_panel(self, tab_index: int, panel_index: int) -> None:
        """Make the panel at *panel_index* the active panel of tab *tab_index*.

        Out-of-range indices are ignored (clicks race panel removal). Notifies
        "active_panel" only on change — the View treats it as a repaint-only
        path (never a rebuild).
        """
        tab = self._tabs[tab_index]
        if not (0 <= panel_index < len(tab.panels)):
            return
        if tab.active_panel_index == panel_index:
            return
        tab.active_panel_index = panel_index
        self._notify("active_panel")

    def active_panel_index(self, tab_index: int | None = None) -> int:
        """Return the active panel index of *tab_index* (default: active tab)."""
        if tab_index is None:
            tab_index = self.active_tab_index
        return self._tabs[tab_index].active_panel_index

    def active_panel(self) -> GraphPanelVM:
        """Return the active panel VM of the active tab (Add/Export の配送先)."""
        tab = self.active_tab()
        return tab.panels[tab.active_panel_index]

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
        """Broadcast a "cursor" notify to every panel in the tab (R15.1).

        *t* is accepted but unused: CursorState is now a single object shared
        by every panel in the tab (spec §2.1), so the moment one panel's
        setter writes cursor_t, every sibling already reads the same value —
        there is nothing left to push. Kept only for call-signature
        compatibility with the pre-sharing version (and any external caller).
        """
        del t
        self._broadcast_tag(tab_index, "cursor")

    def apply_offset(self, signal_key: str, delta_t: float, scope: str) -> None:
        """Forward an offset request to the AppViewModel (View-layer wiring target).

        The resulting 'offsets' notification is handled by _on_app_change, which
        broadcasts to all panels. Keeps GraphPanelView decoupled from AppViewModel.
        """
        self._app_vm.apply_offset(signal_key, delta_t, scope)

    def reset_offset(self, signal_key: str, scope: str) -> None:
        """Forward an offset-reset request to the AppViewModel (View-layer wiring target).

        Symmetric to apply_offset; the resulting 'offsets' notification is handled
        by _on_app_change, which re-broadcasts the reduced offsets to every panel.
        """
        self._app_vm.reset_offset(signal_key, scope)

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
                    "active_panel_index": tab.active_panel_index,
                }
                for tab in self._tabs
            ],
        }
