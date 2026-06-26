# Implementation Tasks: valisync-gui-file-browser

These tasks define the implementation sequence for extracting the FileBrowser and refactoring the ChannelBrowser into a master-detail structure.

## Wave 0: AppViewModel Foundation
Establish the cross-component communication channel.

- [x] Task 0.1: Add `active_file_key` state and `set_active_file` method to `AppViewModel`.
  - [x] **Red**: Add test in `tests/gui/test_app_viewmodel.py` verifying `set_active_file` notifies observers with the correct tag.
  - [x] **Green**: Implement property and setter in `AppViewModel`.
- [x] Task 0.2: Ensure `AppViewModel.loaded_files` (or similar) is correctly populated from the Session.
  - [x] **Verify**: Run `pytest tests/gui/test_app_viewmodel.py`.

## Wave 1: FileBrowser Component
Create the "Master" component for file selection.

- [x] Task 1.1: Implement `FileBrowserVM`.
  - [x] **Red**: Add `tests/gui/test_file_browser_vm.py` verifying file list generation (basenames) and `select_file` interaction with `AppViewModel`.
  - [x] **Green**: Implement `FileBrowserVM` with `AppViewModel` subscription.
- [x] Task 1.2: Implement `FileListModel` adapter.
  - [x] **Red**: Add test in `tests/gui/test_qt_signal_models.py` verifying row count and `data()` output for a list of file keys.
  - [x] **Green**: Implement `FileListModel` in `src/valisync/gui/adapters/qt_signal_models.py`.
- [x] Task 1.3: Implement `FileBrowserView`.
  - [x] **Red**: Add `tests/gui/test_file_browser_view.py` verifying `QListView` integration and selection signal emission to VM.
  - [x] **Green**: Implement `FileBrowserView` class using `QListView`.

## Wave 2: ChannelBrowser Transformation
Refactor the "Detail" component into a flat tabular view.

- [x] Task 2.1: Refactor `ChannelBrowserVM`.
  - [x] **Red**: Update `tests/gui/test_channel_browser_vm.py` to assert a flat list of `SignalItem` objects instead of a tree. Verify it reacts to `active_file_key` changes.
  - [x] **Green**: Strip tree logic from `ChannelBrowserVM` and implement `active_file` observation. Extract `unit` metadata.
- [x] Task 2.2: Refactor `SignalTreeModel` to `SignalTableModel`.
  - [x] **Red**: Update `tests/gui/test_qt_signal_models.py` to verify `SignalTableModel` provides 2 columns (Name, Unit).
  - [x] **Green**: Rewrite the adapter in `src/valisync/gui/adapters/qt_signal_models.py`. Delete `TreeItem` classes if no longer used.
- [x] Task 2.3: Refactor `ChannelBrowserView`.
  - [x] **Red**: Update `tests/gui/test_channel_browser_view.py`. Assert tree decoration is disabled and context menu logic still maps to correct signal keys.
  - [x] **Green**: Configure `QTreeView` for flat display. Update search/filter logic.

## Wave 3: Integration and Layout
Finalize the new layout in the main window.

- [x] Task 3.1: Mount `FileBrowser` in `MainWindow`.
  - [x] **Act**: Modify `MainWindow.__init__` to instantiate FB components. Add `file_dock` to the right area.
- [x] Task 3.2: Configure vertical stack layout.
  - [x] **Act**: Use `splitDockWidget` in `MainWindow` to place `file_dock` above `channel_dock`.
- [x] Task 3.3: Verify End-to-End Workflow.
  - [x] **Verify**: Run `uv run valisync`, load two files, verify selecting one updates the signal list of the other. Verify drag-to-plot still works.

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


---

## Revision S1 (再レビュー反映)

別エージェント作成の可能性を踏まえた spec/実装の再レビューにより、design が実在しない
Session API を前提としていた点を修正:

- `Session.source_name(key)` / `Session.group_signals(key)` を**公開API化**（`SignalGroupManager` にも追加）。
- `FileBrowserVM` の `session._groups`(private) 直接アクセスを除去、`ChannelBrowserVM` /
  `SignalTableModel` の全信号走査を per-file 取得＋スナップショットキャッシュに修正。
- design.md を実 API に合わせて訂正。

残課題 S2–S5（性能要件の検証、unload 要否、親 spec トレース、wave 再構成）は
[docs/file-browser-spec-revision-followup.md](../../../docs/file-browser-spec-revision-followup.md) に記録。
