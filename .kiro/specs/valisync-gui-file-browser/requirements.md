# Requirements Document: valisync-gui-file-browser

## Introduction

This sub-spec defines the extraction of the `FileBrowser` from the existing `ChannelBrowser` to implement a **Master-Detail** pattern (Phase 2 extension). The primary objective is to separate file management from signal exploration, improving usability when handling multiple large datasets.

Success criteria: "User loads multiple files via DataExplorer -> FileBrowser lists filenames -> Selecting a file in FileBrowser immediately populates ChannelBrowser with a flat list of signals (Name and Unit) for that file only -> Dragging signals to graphs functions as before."

## Glossary
- **FileBrowser**: A new UI component listing all currently loaded files in the Session.
- **ChannelBrowser**: The existing component, refactored to display a flat tabular list of signals for the active file.
- **Active File**: The single file currently selected in the FileBrowser, determining the content of the ChannelBrowser.

## Requirements

### Requirement 1: Independent Dock Widgets (R1)
**User Story:** As a user, I want to manage the file list and signal list independently to optimize screen real estate.
1. THE GUI_Application SHALL implement `FileBrowser` and `ChannelBrowser` as two distinct and independent `QDockWidget` instances.
2. BOTH Dock_Widgets SHALL support standard dock features (movable, floatable, closable, tabbed).

### Requirement 2: Initial Layout and Grouping (R2)
**User Story:** As a user, I want a logical vertical stack for file and channel navigation by default.
1. THE GUI_Application SHALL position the `FileBrowser` dock in the `RightDockWidgetArea` upon initialization.
2. THE GUI_Application SHALL position the `ChannelBrowser` dock immediately below the `FileBrowser` in the same area.
3. THE GUI_Application SHALL group these docks such that they are stacked vertically by default but can be rearranged by the user.

### Requirement 3: FileBrowser Presentation (R3)
**User Story:** As a user, I want a flat, readable list of my loaded files.
1. THE FileBrowser SHALL display a flat list of all loaded files in the Session.
2. THE FileBrowser SHALL display only the **filename** (e.g., `data.mf4`), not the full absolute path, to conserve space.
3. THE FileBrowser SHALL support **single selection** only.
4. WHEN a file is selected, it becomes the **Active File**.

### Requirement 4: ChannelBrowser Presentation (R4)
**User Story:** As a user, I want a fast, searchable table of signals for the selected file.
1. THE ChannelBrowser SHALL display signals in a flat tabular view, removing all hierarchical tree structures.
2. THE ChannelBrowser SHALL provide an incremental search (real-time filtering) as defined in the original MVP (R4.3).

### Requirement 5: Master-Detail Synchronization (R5)
**User Story:** As a user, I expect the signal list to be perfectly synced with my file selection.
1. THE ChannelBrowser SHALL display only the signals contained within the **Active File**.
2. WHEN the Active File changes, THE ChannelBrowser SHALL refresh by fetching **only that file's signals** (via `Session.group_signals(active_key)`) and SHALL NOT scan the full Session, so the update cost scales with the active file's signal count, not the total number of loaded signals. *(Revised in S2: the original "within 100ms" was an unverifiable wall-clock target with no enforcing mechanism. This states the per-file mechanism that delivers responsiveness and is guarded by a structural test asserting no full-session scan — see `tests/gui/test_channel_browser_vm.py`.)*
3. WHEN no file is selected (e.g., initial state or all files unloaded), the ChannelBrowser SHALL be empty.
4. WHEN multiple files are selected (if supported in future), the selection behavior SHALL prioritize the first selected item as the Active File.

### Requirement 6: Column Specifications (R6)
**User Story:** As a user, I need to see the signal name and its physical unit.
1. THE ChannelBrowser SHALL display exactly two columns: **Name** and **Unit**.
2. THE "Unit" SHALL be extracted from the signal's metadata (if available).
3. THE previously supported columns "Type", "Samples", and "Time Range" SHALL be removed to minimize horizontal clutter.

### Requirement 7: File Unload (R7)
**User Story:** As a user handling multiple datasets, I want to remove (unload) a loaded file I no longer need, so the file list and graphs stay uncluttered. *(Added in revision S3; this is the requirement that makes R5.3's "all files unloaded" reachable.)*
1. THE FileBrowser SHALL provide a context-menu action ("Remove File") to unload the **selected** file (right-clicking a row selects it first).
2. WHEN a file is unloaded, THE GUI_Application SHALL remove its Signal_Group from the Session. No confirmation dialog is shown (files can be re-loaded via the DataExplorer).
3. WHEN the unloaded file is the Active File, THE Active File SHALL become `None` (the ChannelBrowser empties per R5.3).
4. WHEN signals from the unloaded file are plotted in any Graph_Panel, THOSE curves SHALL be removed and the panel's axes reconciled so no empty region is left occupying space (removal is symmetric with signal addition).
5. THE FileBrowser list SHALL update to no longer list the unloaded file.
6. WHEN a Derived_Signal depends on the unloaded file (future capability; `Session.remove_group` refuses without `force`), THE unload SHALL be refused without side effects. *(Currently unreachable — Derived_Signals are out of scope until `valisync-gui-derived`.)*

### Requirement 8: Drag-and-Drop Preservation (R8)
**User Story:** As a user, I want the existing drag-to-plot workflow to keep working after the master-detail split, so my muscle memory is preserved. *(Added in revision S4 — this behavior was previously only stated in the Introduction's success-criteria prose ("Dragging signals to graphs functions as before"), never as a checkable requirement.)*
1. THE ChannelBrowser SHALL allow dragging a signal — or a Ctrl/Shift multi-selection of signals — from the flat list onto a Graph_Panel to add its waveform, as in the MVP.
2. THE drag payload SHALL carry the **namespaced** signal keys so the drop target resolves them via the Session.

### Requirement 9: Signal Context Menu Preservation (R9)
**User Story:** As a user, I want the per-signal right-click action to remain available in the flat ChannelBrowser. *(Added in revision S4 — same gap as R8: implemented in the MVP but never re-stated as a requirement here.)*
1. WHEN a signal row is right-clicked, THE ChannelBrowser SHALL offer the MVP context-menu action **"Add to Active Panel"**, which emits the selected signal's namespaced key(s) to plot on the active Graph_Panel.

> **Verification of R8/R9**: both behaviors are already covered by existing tests — `tests/gui/test_dnd_workflow.py` (drag-to-plot, including multi-select) and `tests/gui/test_context_menus.py` ("Add to Active Panel"). R8/R9 formalize the requirement so the coverage is traceable, not new behavior.

## Traceability to parent `valisync-gui`

The MVP sub-specs (e.g. `valisync-gui-axes`) extract their requirements from the parent `valisync-gui` (29 requirements). This sub-spec's independent R1–R9 are mapped back here (gap closed in revision S4).

| file-browser | parent `valisync-gui` | note |
|---|---|---|
| R1 (independent docks) | R1 (docking system) | adds FileBrowser as a new Dock_Widget |
| R2 (layout / grouping) | R1, R2 (layout save/restore) | |
| R3 (FileBrowser presentation) | R3 (DataExplorer→browser), R4 | extracts the "master" (MVP had only Channel_Browser) |
| R4 (flat ChannelBrowser table) | R4.1 (tree→flat, refined), R4.4 (incremental search) | |
| R5 (master-detail sync) | R4 (refinement) | |
| R6 (Name/Unit columns) | R4.2 (metadata reduced to Name/Unit) | |
| R7 (File Unload) | — (no parent equivalent) | new in this sub-spec (revision S3) |
| R8 (D&D preservation) | R4.5/R4.6, R22.2/R22.3 | |
| R9 (signal context menu) | R29.4 | only "Add to Active Panel" implemented in MVP; parent also envisions new-Y-axis / preview / properties (future) |
