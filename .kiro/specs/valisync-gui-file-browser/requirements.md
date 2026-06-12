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
2. WHEN the Active File changes, the ChannelBrowser SHALL update its content within 100ms.
3. WHEN no file is selected (e.g., initial state or all files unloaded), the ChannelBrowser SHALL be empty.
4. WHEN multiple files are selected (if supported in future), the selection behavior SHALL prioritize the first selected item as the Active File.

### Requirement 6: Column Specifications (R6)
**User Story:** As a user, I need to see the signal name and its physical unit.
1. THE ChannelBrowser SHALL display exactly two columns: **Name** and **Unit**.
2. THE "Unit" SHALL be extracted from the signal's metadata (if available).
3. THE previously supported columns "Type", "Samples", and "Time Range" SHALL be removed to minimize horizontal clutter.
