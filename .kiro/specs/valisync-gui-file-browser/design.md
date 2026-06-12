# Design Document: valisync-gui-file-browser

## Architecture

This specification adheres to the existing MVVM pattern. The primary architectural shift involves splitting the responsibilities of the old `ChannelBrowserVM` into two distinct ViewModels, reflecting the master-detail UI.

### Component Interaction

```mermaid
graph TD
    subgraph View (PySide6)
        MainWindow[MainWindow]
        FB_View[FileBrowserView]
        CB_View[ChannelBrowserView]
        
        MainWindow --> FB_View
        MainWindow --> CB_View
    end
    subgraph ViewModel
        AppVM[AppViewModel<br>state: active_file_key]
        FB_VM[FileBrowserVM]
        CB_VM[ChannelBrowserVM]
        
        FB_View -. selection changed .-> FB_VM
        FB_VM -. calls .-> AppVM::set_active_file
        AppVM -. notifies .-> CB_VM
        CB_VM -. notifies .-> CB_View
    end
    subgraph Model
        Session[Session]
    end

    AppVM --> Session
    FB_VM --> Session
    CB_VM --> Session
```

## ViewModels

### AppViewModel (Modification)
- **State Added**: Needs a new state variable to track the currently active (selected) file. E.g., `self._active_file_key: str | None = None`.
- **Method Added**: `set_active_file(key: str | None)`. This method updates the state and calls `self._notify("active_file")`.

### FileBrowserVM (New)
- **Role**: Provides the list of loaded file keys/paths to the View.
- **State**: A flat list of loaded files (can derive this from `Session.list_loaded()` or `AppViewModel`).
- **Actions**: Handles selection changes from the View, calling `AppViewModel.set_active_file(...)`.
- **Observation**: Subscribes to `AppViewModel` for `"loaded"` events to refresh its list.

### ChannelBrowserVM (Refactor)
- **Role**: Provides the flat list of signals for the currently active file.
- **State Modification**: Removes the hierarchical tree logic. The internal representation should become a flat list of signal metadata objects.
- **Observation**: Subscribes to `AppViewModel` for `"active_file"` events. When notified, it queries the `Session` for the signals of `AppViewModel.active_file_key` and notifies the View.

## Views and Adapters

### FileBrowserView (New)
- **Implementation**: A simple `QListView` or `QTreeView` (used as a flat list).
- **Model**: Needs a new adapter in `qt_signal_models.py` (e.g., `FileStringListModel` inheriting from `QStringListModel` or `QAbstractListModel`) to bridge `FileBrowserVM` and Qt.

### ChannelBrowserView (Refactor)
- **Implementation**: Retain `QTreeView` but configure it to look like a flat table (e.g., `setRootIsDecorated(False)`).
- **Adapter Refactor**: The adapter (`SignalTreeModel`) in `qt_signal_models.py` must be completely rewritten. It will no longer manage hierarchical `TreeItem`s. Instead, it will be a simple tabular model (e.g., `SignalListModel` inheriting from `QAbstractTableModel`) serving 2 columns: Name and Unit.

## MainWindow

- Instantiates `FileBrowserVM` and `FileBrowserView`.
- Wraps `FileBrowserView` in a `QDockWidget` (`file_dock`).
- Arranges docks using `splitDockWidget` or by placing `file_dock` first and `channel_dock` immediately below it in the `RightDockWidgetArea`.
- Adds `file_dock` to the "View" menu toggles.
