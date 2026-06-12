# Requirements Document: valisync-gui-file-browser

## Introduction

This specification defines the extraction of the `FileBrowser` from the existing `ChannelBrowser` to implement a master-detail pattern. This improves usability and overview when handling multiple loaded data files.

## Glossary
- **FileBrowser**: A new UI component listing all currently loaded files.
- **ChannelBrowser**: The existing component, which will be refactored to display a flat list of signals belonging to the currently selected file in the FileBrowser.
- **Master-Detail**: An architectural pattern where selecting an item in a master list (FileBrowser) updates the details shown in a secondary view (ChannelBrowser).

## Requirements

### Requirement 1: Independent Dock Widgets (R1)
**User Story:** As a user, I want to manage the file list and signal list independently so I can arrange my workspace freely.
1. THE GUI_Application SHALL implement `FileBrowser` and `ChannelBrowser` as two distinct and independent `QDockWidget` instances.
2. BOTH Dock_Widgets SHALL support standard dock features (movable, floatable, closable, tabbed).

### Requirement 2: Initial Layout (R2)
**User Story:** As a user, I want a logical default layout when the application starts.
1. THE GUI_Application SHALL position the `FileBrowser` dock in the `RightDockWidgetArea` upon initialization.
2. THE GUI_Application SHALL position the `ChannelBrowser` dock immediately below the `FileBrowser` in the `RightDockWidgetArea` by default.

### Requirement 3: FileBrowser Responsibilities (R3)
**User Story:** As a user, I want to clearly see which files are loaded.
1. THE FileBrowser SHALL display a flat list of all loaded files.
2. THE FileBrowser SHALL allow the user to select exactly one file at a time (single selection mode).

### Requirement 4: ChannelBrowser Presentation (R4)
**User Story:** As a user, I want a compact and clean list of signals without unnecessary hierarchical depth.
1. THE ChannelBrowser SHALL display signals in a flat list (or table), completely replacing the previous tree hierarchy.

### Requirement 5: Master-Detail Synchronization (R5)
**User Story:** As a user, I want the signal list to automatically update based on the file I select.
1. WHEN the user selects a file in the FileBrowser, THE ChannelBrowser SHALL immediately update to display only the signals contained within that selected file.
2. WHEN the user selects multiple files or no files in the FileBrowser, THE ChannelBrowser SHALL display an empty list (multi-file signal merging is deferred to future extensions).

### Requirement 6: ChannelBrowser Column Adjustments (R6)
**User Story:** As a user, I only need to see the signal name and its physical unit to make plotting decisions.
1. THE ChannelBrowser SHALL remove the "Type", "Samples", and "Time Range" columns.
2. THE ChannelBrowser SHALL display exactly two columns: "Name" and "Unit".
