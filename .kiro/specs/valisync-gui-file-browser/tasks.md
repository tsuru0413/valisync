# Implementation Tasks: valisync-gui-file-browser

These tasks define the implementation sequence for extracting the FileBrowser and refactoring the ChannelBrowser into a master-detail structure.

## Wave 0: Core VM Adjustments
Add the necessary cross-component state to the AppViewModel before building the specific components.

- [ ] Task 0.1: Add `active_file_key` state and `set_active_file` method to `AppViewModel`. (Emits `"active_file"` change event).

## Wave 1: FileBrowser Implementation
Build the new FileBrowser layer.

- [ ] Task 1.1: Create `FileBrowserVM` that subscribes to `AppViewModel` `"loaded"` events and manages a list of loaded files.
- [ ] Task 1.2: Create a Qt item model adapter (e.g., `FileListModel`) in `adapters/qt_signal_models.py` for the FileBrowser.
- [ ] Task 1.3: Create `FileBrowserView` containing a `QListView` (or `QTreeView`), using the adapter, and connecting its selection signal to the VM.

## Wave 2: ChannelBrowser Refactoring
Rewrite the ChannelBrowser to consume a single active file and display a flat table (Name, Unit).

- [ ] Task 2.1: Refactor `ChannelBrowserVM`. Remove hierarchical tree logic. Make it observe `"active_file"` on `AppViewModel` and maintain a flat list of `(name, unit)` tuples.
- [ ] Task 2.2: Refactor `SignalTreeModel` in `adapters/qt_signal_models.py` into a flat `SignalTableModel` supporting only 2 columns (Name, Unit). Remove `TreeItem` utility classes if unused.
- [ ] Task 2.3: Refactor `ChannelBrowserView`. Remove hierarchy expansion logic, configure it as a flat table view (`setRootIsDecorated(False)`). Update context menu logic to match the new flat data structure.

## Wave 3: MainWindow Integration
Wire everything together in the shell.

- [ ] Task 3.1: Modify `MainWindow` to instantiate `FileBrowserVM` and `FileBrowserView`.
- [ ] Task 3.2: Create `file_dock` in `MainWindow`, add it to the `RightDockWidgetArea`, and place `channel_dock` below it.
- [ ] Task 3.3: Add `file_dock` to the "View" toggle menu in `MainWindow` and verify application starts and functions correctly.

---

### Task Dependency Graph
```json
{
  "tasks": [
    { "id": "0.1", "desc": "AppViewModel active_file state", "deps": [] },
    { "id": "1.1", "desc": "FileBrowserVM", "deps": ["0.1"] },
    { "id": "1.2", "desc": "Qt adapter for FileBrowser", "deps": ["1.1"] },
    { "id": "1.3", "desc": "FileBrowserView", "deps": ["1.2"] },
    { "id": "2.1", "desc": "Refactor ChannelBrowserVM", "deps": ["0.1"] },
    { "id": "2.2", "desc": "Refactor SignalTreeModel to SignalTableModel", "deps": ["2.1"] },
    { "id": "2.3", "desc": "Refactor ChannelBrowserView", "deps": ["2.2"] },
    { "id": "3.1", "desc": "Instantiate FileBrowser in MainWindow", "deps": ["1.3", "2.3"] },
    { "id": "3.2", "desc": "Layout Docks in MainWindow", "deps": ["3.1"] },
    { "id": "3.3", "desc": "Wire menus and finalize", "deps": ["3.2"] }
  ]
}
```
