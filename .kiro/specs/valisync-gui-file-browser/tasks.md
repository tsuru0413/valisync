# Implementation Tasks: valisync-gui-file-browser

These tasks define the implementation sequence for extracting the FileBrowser and refactoring the ChannelBrowser into a master-detail structure.

## Wave 0: AppViewModel Foundation
Establish the cross-component communication channel.

- [ ] Task 0.1: Add `active_file_key` state and `set_active_file` method to `AppViewModel`.
  - [ ] **Red**: Add test in `tests/gui/test_app_viewmodel.py` verifying `set_active_file` notifies observers with the correct tag.
  - [ ] **Green**: Implement property and setter in `AppViewModel`.
- [ ] Task 0.2: Ensure `AppViewModel.loaded_files` (or similar) is correctly populated from the Session.
  - [ ] **Verify**: Run `pytest tests/gui/test_app_viewmodel.py`.

## Wave 1: FileBrowser Component
Create the "Master" component for file selection.

- [ ] Task 1.1: Implement `FileBrowserVM`.
  - [ ] **Red**: Add `tests/gui/test_file_browser_vm.py` verifying file list generation (basenames) and `select_file` interaction with `AppViewModel`.
  - [ ] **Green**: Implement `FileBrowserVM` with `AppViewModel` subscription.
- [ ] Task 1.2: Implement `FileListModel` adapter.
  - [ ] **Red**: Add test in `tests/gui/test_qt_signal_models.py` verifying row count and `data()` output for a list of file keys.
  - [ ] **Green**: Implement `FileListModel` in `src/valisync/gui/adapters/qt_signal_models.py`.
- [ ] Task 1.3: Implement `FileBrowserView`.
  - [ ] **Red**: Add `tests/gui/test_file_browser_view.py` verifying `QListView` integration and selection signal emission to VM.
  - [ ] **Green**: Implement `FileBrowserView` class using `QListView`.

## Wave 2: ChannelBrowser Transformation
Refactor the "Detail" component into a flat tabular view.

- [ ] Task 2.1: Refactor `ChannelBrowserVM`.
  - [ ] **Red**: Update `tests/gui/test_channel_browser_vm.py` to assert a flat list of `SignalItem` objects instead of a tree. Verify it reacts to `active_file_key` changes.
  - [ ] **Green**: Strip tree logic from `ChannelBrowserVM` and implement `active_file` observation. Extract `unit` metadata.
- [ ] Task 2.2: Refactor `SignalTreeModel` to `SignalTableModel`.
  - [ ] **Red**: Update `tests/gui/test_qt_signal_models.py` to verify `SignalTableModel` provides 2 columns (Name, Unit).
  - [ ] **Green**: Rewrite the adapter in `src/valisync/gui/adapters/qt_signal_models.py`. Delete `TreeItem` classes if no longer used.
- [ ] Task 2.3: Refactor `ChannelBrowserView`.
  - [ ] **Red**: Update `tests/gui/test_channel_browser_view.py`. Assert tree decoration is disabled and context menu logic still maps to correct signal keys.
  - [ ] **Green**: Configure `QTreeView` for flat display. Update search/filter logic.

## Wave 3: Integration and Layout
Finalize the new layout in the main window.

- [ ] Task 3.1: Mount `FileBrowser` in `MainWindow`.
  - [ ] **Act**: Modify `MainWindow.__init__` to instantiate FB components. Add `file_dock` to the right area.
- [ ] Task 3.2: Configure vertical stack layout.
  - [ ] **Act**: Use `splitDockWidget` in `MainWindow` to place `file_dock` above `channel_dock`.
- [ ] Task 3.3: Verify End-to-End Workflow.
  - [ ] **Verify**: Run `uv run valisync`, load two files, verify selecting one updates the signal list of the other. Verify drag-to-plot still works.

---

### Task Dependency Graph
```json
{
  "tasks": [
    { "id": "0.1", "desc": "AppViewModel active_file state", "deps": [] },
    { "id": "1.1", "desc": "FileBrowserVM", "deps": ["0.1"] },
    { "id": "1.2", "desc": "FileListModel adapter", "deps": ["1.1"] },
    { "id": "1.3", "desc": "FileBrowserView", "deps": ["1.2"] },
    { "id": "2.1", "desc": "Refactor ChannelBrowserVM", "deps": ["0.1"] },
    { "id": "2.2", "desc": "Refactor SignalTableModel", "deps": ["2.1"] },
    { "id": "2.3", "desc": "Refactor ChannelBrowserView", "deps": ["2.2"] },
    { "id": "3.1", "desc": "MainWindow Integration", "deps": ["1.3", "2.3"] },
    { "id": "3.2", "desc": "Dock Layout Positioning", "deps": ["3.1"] },
    { "id": "3.3", "desc": "Final Verification", "deps": ["3.2"] }
  ]
}
```
