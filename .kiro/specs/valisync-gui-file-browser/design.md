# Design Document: valisync-gui-file-browser

## Overview

The `valisync-gui-file-browser` extension refactors the primary navigation UI of ValiSync. By separating file management (Master) from channel exploration (Detail), we reduce cognitive load and improve performance when hundreds of signals are spread across multiple loaded files.

The design follows the strict MVVM architecture established in the MVP.

## Architecture

### Component Interaction

The `AppViewModel` serves as the source of truth for the application state, including the `active_file_key`. The `FileBrowserVM` writes to this state, and the `ChannelBrowserVM` reacts to it.

```mermaid
graph TD
    subgraph View (PySide6)
        MainWindow[MainWindow]
        FB_View[FileBrowserView]
        CB_View[ChannelBrowserView]
        
        MainWindow --> FB_View
        MainWindow --> CB_View
    end
    subgraph VM (Pure Python)
        AppVM[AppViewModel]
        FB_VM[FileBrowserVM]
        CB_VM[ChannelBrowserVM]
        
        FB_View -. change selection .-> FB_VM
        FB_VM -. set_active_file(key) .-> AppVM
        AppVM -. notify('active_file') .-> CB_VM
        CB_VM -. notify('signals') .-> CB_View
    end
    subgraph Model
        Session[Session]
    end

    AppVM --> Session
    FB_VM --> Session
    CB_VM --> Session
```

## ViewModels

### AppViewModel (Modified)

**State:**
- `active_file_key: str | None`: The absolute path (key) of the currently selected file.
- `loaded_files: list[str]`: List of keys for all loaded signal groups.

**Actions:**
- `set_active_file(key: str | None) -> None`: Updates the state and calls `self._notify("active_file")`.

### FileBrowserVM (New)

**Role:** Manages the list of files available for selection.

**State:**
- `files: list[str]`: The list of filenames (basename) derived from `AppViewModel.loaded_files`.

**Actions:**
- `select_file(index: int) -> None`: Translates the list index to a file key and calls `AppViewModel.set_active_file(key)`.

**Observation:**
- Subscribes to `AppViewModel` for `"loaded"` and `"unloaded"` events to refresh the file list.

### ChannelBrowserVM (Refactored)

**Role:** Provides a flat list of signals for the currently active file.

**State:**
- `signals: list[SignalItem]`: Flat list of signal objects containing `name`, `unit`, and `signal_key`.
- `filter_text: str`: Used for incremental search.

**Observation:**
- Subscribes to `AppViewModel` for `"active_file"` changes.
- When notified, it fetches the `SignalGroup` for the `active_file_key` from the `Session`, flattens its signals into `SignalItem` objects, and notifies the View.
- **Unit extraction**: `unit = signal.metadata.get("unit", "")`.

## Views and Adapters

### FileBrowserView (New)

- **UI**: A `QDockWidget` containing a `QListView`.
- **Adapter**: `FileListModel` (inherits `QAbstractListModel`).
  - Implements `data()` to return filenames.
  - Connects to `FileBrowserVM` notifications to trigger `layoutChanged`.

### ChannelBrowserView (Refactored)

- **UI**: A `QDockWidget` containing a `QTreeView`.
- **Configuration**:
  - `setRootIsDecorated(False)`: Disables the tree expansion icons.
  - `setItemsExpandable(False)`: Forces a flat appearance.
- **Adapter**: `SignalTableModel` (refactored from `SignalTreeModel`).
  - Inherits `QAbstractTableModel`.
  - **Columns (2)**: 0 = "Name", 1 = "Unit".
  - Connects to `ChannelBrowserVM` notifications to refresh data.

## MainWindow Integration

**Layout Wiring:**
```python
# Initial setup in MainWindow.__init__
self.addDockWidget(Qt.RightDockWidgetArea, self.file_browser_dock)
self.addDockWidget(Qt.RightDockWidgetArea, self.channel_browser_dock)
# Stack them vertically
self.splitDockWidget(self.file_browser_dock, self.channel_browser_dock, Qt.Vertical)
```

## Testing Strategy

1.  **VM Unit Tests**:
    - Verify `AppViewModel.set_active_file` notifies observers.
    - Verify `ChannelBrowserVM` updates its list correctly when `active_file_key` changes.
2.  **Adapter Tests**:
    - Verify `SignalTableModel` correctly maps `signal.metadata["unit"]` to column 1.
3.  **Integration Tests**:
    - Use `QtBot` to select an item in `FileBrowserView` and assert that `ChannelBrowserView` displays the expected signals.
