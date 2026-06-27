# File Unload (valisync-gui-file-browser R7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user remove (unload) a loaded file from the FileBrowser, removing its Signal_Group from the Session and reconciling the file list, active file, and graph panels (curves + axes).

**Architecture:** The `Session` is the single source of truth. `AppViewModel.unload_file(key)` removes the group and notifies; every component reconciles against the Session (FileBrowserVM rebuilds its list, ChannelBrowserVM empties if the active file was cleared, graph panels prune signals no longer in the Session and re-normalize their axes). `GraphAreaVM` subscribes to `AppViewModel` and owns panel reconciliation for both load and unload — removing that coordination from `MainWindow`, so load and unload are handled the same way by the VM that owns the panels. Removal is made symmetric with addition by reconciling axes via the existing `_normalize_axes()`.

**Tech Stack:** Python, PySide6, pytest / pytest-qt. Pure-Python ViewModels (no Qt). Run tests with `uv run python -m pytest`.

---

## File Structure

- Modify `src/valisync/gui/viewmodels/graph_panel_vm.py` — add `prune_missing_signals()`; make `remove_signal()` reconcile axes.
- Modify `src/valisync/gui/viewmodels/app_viewmodel.py` — add `unload_file(key)`.
- Modify `src/valisync/gui/viewmodels/graph_area_vm.py` — take `app_vm`, subscribe to it, and reconcile panels on `"loaded"` (refresh) / `"unloaded"` (prune). Moves `_refresh_panels` ownership here. Migrate ~50 `GraphAreaVM(session)` test constructions to `GraphAreaVM(AppViewModel(session))`.
- Modify `src/valisync/gui/viewmodels/file_browser_vm.py` — add `unload(index)`.
- Modify `src/valisync/gui/views/file_browser_view.py` — add context menu ("Remove File").
- Modify `src/valisync/gui/views/main_window.py` — construct `GraphAreaVM(app_vm)`; drop the `_refresh_panels` call/method from `_on_app_change` (GraphAreaVM owns it now). Also repoint the one `_refresh_panels` caller in `tests/gui/test_integration.py`.
- Tests in the matching `tests/...` files + one integration test.

> Note: `_normalize_axes()` (added for the first-D&D fix) already prunes empty axes and re-splits survivors equally; reusing it on the removal path is what makes removal symmetric with `create_new_axis`.

---

### Task 1: GraphPanelVM — reconcile axes on removal + prune_missing_signals

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- Test: `tests/gui/test_graph_panel_multi_axis.py`

- [ ] **Step 1: Write failing tests** (append to `class TestMultiAxisLayout`)

```python
    def test_remove_signal_prunes_now_empty_axis(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Removing the only signal on an axis drops that axis (no empty region)."""
        session, _ = _loaded_session(tmp_path, n_signals=2)
        keys = _keys(session)
        vm = GraphPanelVM(session)
        vm.create_new_axis(keys[0])
        vm.create_new_axis(keys[1])
        assert len(vm.axes) == 2

        vm.remove_signal(keys[0])

        assert len(vm.axes) == 1  # empty axis pruned
        assert vm.axes[0].height_ratio == 1.0
        plotted = [p["signal_key"] for p in vm.inspect()["plotted_signals"]]
        assert plotted == [keys[1]]

    def test_prune_missing_signals_drops_signals_absent_from_session(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """prune_missing_signals removes plotted entries no longer in the Session."""
        session, _ = _loaded_session(tmp_path, n_signals=2)
        keys = _keys(session)
        vm = GraphPanelVM(session)
        vm.create_new_axis(keys[0])
        vm.create_new_axis(keys[1])

        # Simulate keys[0] no longer existing in the Session.
        remaining = [s for s in session.signals() if s.name != keys[0]]
        session.signals = lambda: remaining  # type: ignore[method-assign]
        vm.prune_missing_signals()

        plotted = [p["signal_key"] for p in vm.inspect()["plotted_signals"]]
        assert plotted == [keys[1]]
        assert len(vm.axes) == 1  # axes reconciled
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run python -m pytest "tests/gui/test_graph_panel_multi_axis.py::TestMultiAxisLayout::test_remove_signal_prunes_now_empty_axis" "tests/gui/test_graph_panel_multi_axis.py::TestMultiAxisLayout::test_prune_missing_signals_drops_signals_absent_from_session" -p no:cacheprovider`
Expected: FAIL (`test_remove_signal_...` asserts `1 == 2`; `prune_missing_signals` does not exist → AttributeError).

- [ ] **Step 3: Implement** (in `graph_panel_vm.py`)

Make `remove_signal` reconcile axes (add the `_normalize_axes()` call):

```python
    def remove_signal(self, signal_key: str) -> None:
        """Remove *signal_key* from the plot and reconcile axes."""
        self._plotted = [e for e in self._plotted if e.signal_key != signal_key]
        self._normalize_axes()
        self._invalidate_cache()
        self._notify("signals")
```

Add `prune_missing_signals` (place it right after `remove_signal`):

```python
    def prune_missing_signals(self) -> None:
        """Drop plotted signals no longer present in the Session, reconcile axes.

        Keyed on the Session (not on any specific unloaded key), so it is correct
        regardless of why a signal disappeared.
        """
        present = {s.name for s in self._session.signals()}
        kept = [e for e in self._plotted if e.signal_key in present]
        if len(kept) == len(self._plotted):
            return
        self._plotted = kept
        self._normalize_axes()
        self._invalidate_cache()
        self._notify("signals")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run python -m pytest tests/gui/test_graph_panel_multi_axis.py -p no:cacheprovider`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_multi_axis.py
git commit -m "feat(gui): reconcile axes on signal removal + add prune_missing_signals"
```

---

### Task 2: AppViewModel.unload_file

**Files:**
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py`
- Test: `tests/gui/test_app_viewmodel.py`

- [ ] **Step 1: Write failing test** (append to `tests/gui/test_app_viewmodel.py`; reuse that file's CSV helpers — check the top of the file for the existing `_csv_format`/load helper and mirror it)

```python
def test_unload_file_removes_group_clears_active_and_notifies(tmp_path) -> None:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

    app_vm = AppViewModel()
    csv = tmp_path / "a.csv"
    csv.write_text("t,speed\n0.0,1.0\n", encoding="utf-8")
    key = app_vm.request_load(csv, _csv_format())  # _csv_format(): existing helper
    app_vm.set_active_file(key)

    events: list[str] = []
    app_vm.subscribe(events.append)

    app_vm.unload_file(key)

    assert key not in app_vm.loaded_file_keys
    assert app_vm.active_file_key is None
    assert app_vm.session.signals() == []
    assert "unloaded" in events and "active_file" in events
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/gui/test_app_viewmodel.py::test_unload_file_removes_group_clears_active_and_notifies -p no:cacheprovider`
Expected: FAIL with AttributeError (`unload_file` not defined).

- [ ] **Step 3: Implement** (add after `set_active_file` in `app_viewmodel.py`)

```python
    def unload_file(self, key: str) -> None:
        """Unload a loaded file: remove its group from the Session and reconcile.

        Refused without side effects when a Derived_Signal depends on the group
        (``Session.remove_group`` returns ``removed=False``). Currently
        unreachable — Derived_Signals are out of scope until valisync-gui-derived.
        """
        result = self._session.remove_group(key)
        if not result.removed:
            return
        if key in self._loaded_keys:
            self._loaded_keys.remove(key)
        if self._active_file_key == key:
            self._active_file_key = None
            self._notify("active_file")
        self._notify("unloaded")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run python -m pytest tests/gui/test_app_viewmodel.py -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/valisync/gui/viewmodels/app_viewmodel.py tests/gui/test_app_viewmodel.py
git commit -m "feat(gui): AppViewModel.unload_file removes group + reconciles state"
```

---

### Task 3: GraphAreaVM owns panel reconciliation (subscribes to AppViewModel)

GraphAreaVM takes `app_vm`, derives `session` from it, and reconciles its panels on
app-level data events itself: `"loaded"` → refresh every panel; `"unloaded"` →
prune every panel. This relocates the panel coordination that lived in
`MainWindow._on_app_change/_refresh_panels` (Task 6 removes it there).

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py`
- Test: `tests/gui/test_graph_area_vm.py` (+ migrate ~50 constructions across
  `test_graph_area_vm.py`, `test_graph_area_view.py`, `test_context_menus.py`,
  `test_dnd_workflow.py`, `test_x_sync.py`)

- [ ] **Step 1: Write failing behavior test** (append to `tests/gui/test_graph_area_vm.py`)

```python
def test_graph_area_prunes_panels_when_file_unloaded(tmp_path) -> None:
    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

    fmt = FormatDefinition(
        name="f", delimiter=Delimiter.COMMA, timestamp_column=0,
        timestamp_unit="sec", signal_start_column=1, signal_end_column=1,
        has_header=True,
    )
    csv = tmp_path / "a.csv"
    csv.write_text("t,speed\n0.0,1.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(csv, fmt)
    vm = GraphAreaVM(app_vm)
    panel = vm.panels(0)[0]
    panel.add_signal(f"{key}::speed")
    assert [p["signal_key"] for p in panel.inspect()["plotted_signals"]] == [
        f"{key}::speed"
    ]

    app_vm.unload_file(key)  # AppViewModel notifies "unloaded"; GraphAreaVM reacts

    assert [p["signal_key"] for p in panel.inspect()["plotted_signals"]] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/gui/test_graph_area_vm.py::test_graph_area_prunes_panels_when_file_unloaded -p no:cacheprovider`
Expected: FAIL — `GraphAreaVM(app_vm)` passes an `AppViewModel` where a `Session` is
expected (AttributeError when the constructor calls `session.signals()` etc.).

- [ ] **Step 3: Implement** the new constructor + subscription (in `graph_area_vm.py`)

Add the import at the top:

```python
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
```

Change `__init__` to take `app_vm` and subscribe:

```python
    def __init__(self, app_vm: AppViewModel) -> None:
        super().__init__()
        self._app_vm = app_vm
        self._session = app_vm.session
        self._propagating = False
        self._panel_unsubs: dict[int, Callable[[], None]] = {}
        first_panel = GraphPanelVM(self._session)
        self._tabs: list[_Tab] = [_Tab(name="Tab 1", panels=[first_panel])]
        self.active_tab_index: int = 0
        self._subscribe_panel(first_panel)
        # Own panel reconciliation for app-level data events.
        self._app_unsub = app_vm.subscribe(self._on_app_change)
```

Add the handler + reconcilers:

```python
    def _on_app_change(self, change: str) -> None:
        if change == "loaded":
            self._for_each_panel(lambda p: p.refresh())
        elif change == "unloaded":
            self._for_each_panel(lambda p: p.prune_missing_signals())

    def _for_each_panel(self, fn: Callable[[GraphPanelVM], None]) -> None:
        for tab in self._tabs:
            for panel in tab.panels:
                fn(panel)
```

> Every other use of `session` inside this class stays the same — it now reads
> `self._session` (assigned from `app_vm.session`), so no further changes are
> needed in `add_tab`, `add_panel`, etc.

- [ ] **Step 4: Migrate existing constructions**

In each of `tests/gui/test_graph_area_vm.py`, `test_graph_area_view.py`,
`test_context_menus.py`, `test_dnd_workflow.py`, `test_x_sync.py`:
add `from valisync.gui.viewmodels.app_viewmodel import AppViewModel` and replace
every `GraphAreaVM(session)` → `GraphAreaVM(AppViewModel(session))` and every
`GraphAreaVM(Session())` → `GraphAreaVM(AppViewModel(Session()))`.

Run (per file): `uv run python -m pytest tests/gui/test_graph_area_vm.py -p no:cacheprovider`

- [ ] **Step 5: Run all affected tests**

Run: `uv run python -m pytest tests/gui/test_graph_area_vm.py tests/gui/test_graph_area_view.py tests/gui/test_context_menus.py tests/gui/test_dnd_workflow.py tests/gui/test_x_sync.py -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/valisync/gui/viewmodels/graph_area_vm.py tests/gui/
git commit -m "refactor(gui): GraphAreaVM owns panel reconciliation on load/unload"
```

---

### Task 4: FileBrowserVM.unload

**Files:**
- Modify: `src/valisync/gui/viewmodels/file_browser_vm.py`
- Test: `tests/gui/test_file_browser_vm.py`

- [ ] **Step 1: Write failing test** (append to `tests/gui/test_file_browser_vm.py`)

This module builds loaded state by injecting real `SignalGroup`s into the Session
(see its existing `test_files_list_contains_basenames`) — *not* via `request_load`.
Mirror that so `remove_group` has a real group to remove. `datetime`, `Path`, and
`SignalGroup` are already imported at the top of the file.

```python
def test_unload_removes_file_from_list() -> None:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM

    app_vm = AppViewModel()
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/b.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    vm = FileBrowserVM(app_vm)
    assert vm.files == ["a.csv", "b.csv"]

    vm.unload(0)

    assert vm.files == ["b.csv"]
    assert vm.unload(5) is None  # out of range is a safe no-op
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/gui/test_file_browser_vm.py::test_unload_removes_file_from_list -p no:cacheprovider`
Expected: FAIL with AttributeError (`unload` not defined).

- [ ] **Step 3: Implement** (add after `select_file` in `file_browser_vm.py`)

```python
    def unload(self, index: int) -> None:
        """Unload the file at list *index* (no-op when out of range)."""
        keys = self._app_vm.loaded_file_keys
        if 0 <= index < len(keys):
            self._app_vm.unload_file(keys[index])
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run python -m pytest tests/gui/test_file_browser_vm.py -p no:cacheprovider`
Expected: PASS (`unload` removes the file; the existing `"unloaded"` listener refreshes the list).

- [ ] **Step 5: Commit**

```bash
git add src/valisync/gui/viewmodels/file_browser_vm.py tests/gui/test_file_browser_vm.py
git commit -m "feat(gui): FileBrowserVM.unload(index) unloads via AppViewModel"
```

---

### Task 5: FileBrowserView — "Remove File" context menu

**Files:**
- Modify: `src/valisync/gui/views/file_browser_view.py`
- Test: `tests/gui/test_file_browser_view.py`

- [ ] **Step 1: Write failing test** (append to `tests/gui/test_file_browser_view.py`)

Inject real `SignalGroup`s (same pattern as Task 4) so the unload actually removes a
group. `AppViewModel`, `FileBrowserVM`, `FileBrowserView`, and `QtBot` are already
imported at the top of this file; add `datetime`, `Path`, and `SignalGroup` locally.

```python
def test_context_menu_remove_unloads_file(qtbot: QtBot) -> None:
    from datetime import datetime
    from pathlib import Path

    from valisync.core.models import SignalGroup

    app_vm = AppViewModel()
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/b.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    assert vm.files == ["a.csv", "b.csv"]

    menu = view.build_context_menu(0)
    actions = menu.actions()
    assert [act.text() for act in actions] == ["Remove File"]
    actions[0].trigger()

    assert vm.files == ["b.csv"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest tests/gui/test_file_browser_view.py::test_context_menu_remove_unloads_file -p no:cacheprovider`
Expected: FAIL with AttributeError (`build_context_menu` not defined).

- [ ] **Step 3: Implement** (in `file_browser_view.py`)

Add imports near the top:

```python
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QListView, QMenu, QVBoxLayout, QWidget
```

Add these methods to `FileBrowserView`:

```python
    def build_context_menu(self, row: int) -> QMenu:
        """Single-action menu ('Remove File') wired to unload row *row*."""
        menu = QMenu(self)
        menu.addAction("Remove File").triggered.connect(
            lambda *_: self._vm.unload(row)
        )
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        pos = self.list_view.viewport().mapFromGlobal(event.globalPos())
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return
        self.list_view.setCurrentIndex(index)  # right-click selects the row
        self.build_context_menu(index.row()).exec(event.globalPos())
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run python -m pytest tests/gui/test_file_browser_view.py -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/valisync/gui/views/file_browser_view.py tests/gui/test_file_browser_view.py
git commit -m "feat(gui): FileBrowserView Remove File context menu"
```

---

### Task 6: MainWindow — hand panel reconciliation to GraphAreaVM

MainWindow no longer coordinates panels on data events; GraphAreaVM (Task 3) owns
that. MainWindow only constructs `GraphAreaVM(app_vm)` and keeps the ChannelBrowser
refresh.

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Modify: `tests/gui/test_integration.py` (the one call site of `_refresh_panels`)
- Test: covered by `tests/gui/test_app.py` / `test_integration.py` (Task 7).

- [ ] **Step 1: Construct GraphAreaVM with app_vm**

Change line 59 from `self.graph_area_vm = GraphAreaVM(session)` to:

```python
        self.graph_area_vm = GraphAreaVM(app_vm)
```

After this change the `session = app_vm.session` local (line 53) is unused in
`__init__` — the load path (`_load_file`) builds its own `self.app_vm.session` local.
**Delete line 53**; `ruff check` flags it as F841 otherwise.

- [ ] **Step 2: Drop panel coordination from `_on_app_change`**

Replace the method with:

```python
    def _on_app_change(self, change: str) -> None:
        if change == "loaded":
            self.channel_browser_vm.refresh()
```

- [ ] **Step 3: Repoint the one test that calls `_refresh_panels`**

`tests/gui/test_integration.py::TestLoadRefresh::test_load_refreshes_panel_with_preadded_signal`
calls `window._refresh_panels()` (currently line 98) to clear the stale empty cache.
That MainWindow method is going away — refresh the panel directly instead (the `panel`
local is already in scope on the line above). Replace that line with:

```python
        panel.refresh()
```

- [ ] **Step 4: Delete the now-unused `_refresh_panels` method**

Remove `MainWindow._refresh_panels` (GraphAreaVM owns panel reconciliation now). Verify
no caller remains *anywhere*: `git grep -n "_refresh_panels"` (whole repo, not just
`src/`) returns nothing.

- [ ] **Step 5: Run the GUI suite to verify nothing broke**

Run: `uv run python -m pytest tests/gui/test_app.py tests/gui/test_integration.py -p no:cacheprovider`
Expected: PASS (load still refreshes panels — now via GraphAreaVM; the pre-added-signal
test refreshes its panel directly).

- [ ] **Step 6: Commit**

```bash
git add src/valisync/gui/views/main_window.py tests/gui/test_integration.py
git commit -m "refactor(gui): MainWindow delegates panel reconciliation to GraphAreaVM"
```

---

### Task 7: Integration test — end-to-end unload

**Files:**
- Test: `tests/gui/test_integration.py`

- [ ] **Step 1: Write the integration test** (append to `tests/gui/test_integration.py`)

`build_main_window` (imported from `valisync.gui.app` at the top of this file) and the
`_mf4` MDF4 helper (also at the top) are already available — reuse them, don't add a CSV
helper. `build_main_window()` creates its own `AppViewModel`; load through
`window.app_vm.request_load` so `"loaded"` fires and the panels wire up.

```python
def test_unload_removes_file_signals_and_curves(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """E2E: unloading a plotted file removes its curves, empties the active
    ChannelBrowser, and drops it from the FileBrowser."""
    window = build_main_window()
    qtbot.addWidget(window)
    key = window.app_vm.request_load(_mf4(tmp_path), None)
    sig_name = f"{key}::speed"

    # Make it active and plot its signal on the active panel.
    window.app_vm.set_active_file(key)
    panel = window.graph_area_vm.panels(0)[0]
    panel.add_signal(sig_name)
    assert [p["signal_key"] for p in panel.inspect()["plotted_signals"]] == [sig_name]

    # Unload via the FileBrowser VM (same path the context menu drives).
    window.file_browser_vm.unload(0)

    assert window.app_vm.loaded_file_keys == []
    assert window.app_vm.active_file_key is None
    assert window.channel_browser_vm.signals == []
    assert [p["signal_key"] for p in panel.inspect()["plotted_signals"]] == []
```

> `build_main_window()` returns a typed `MainWindow`, so `window.app_vm` /
> `window.graph_area_vm` / `window.file_browser_vm` / `window.channel_browser_vm` need
> no `# type: ignore` (unlike the `_window()` helper, which returns `object`).

- [ ] **Step 2: Run to verify it passes**

Run: `uv run python -m pytest tests/gui/test_integration.py::test_unload_removes_file_signals_and_curves -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 3: Full gate + commit**

```bash
uv run python -m pytest -p no:cacheprovider
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/gui/test_integration.py
git commit -m "test(gui): end-to-end file unload integration test"
```

Expected: all tests pass; ruff (check + format) and mypy clean.

---

## Self-Review

**Spec coverage (R7):**
- R7.1 (context-menu Remove File on selected) → Task 5.
- R7.2 (remove group, no confirmation) → Task 2 (`remove_group`, no dialog).
- R7.3 (active file → None) → Task 2.
- R7.4 (remove curves + reconcile axes) → Task 1 (`prune_missing_signals` + `_normalize_axes`), Task 3, Task 6.
- R7.5 (FileBrowser list updates) → Task 4 (existing `"unloaded"` listener).
- R7.6 (refuse on Derived dependency, no side effects) → Task 2 (`if not result.removed: return`).

**Notes for the implementer — setup differs per test module; match each file, don't invent:**
- `tests/gui/test_app_viewmodel.py` has a no-arg `_csv_format()` helper + `request_load` (Task 2).
- `tests/gui/test_graph_panel_multi_axis.py` imports `_loaded_session`/`_keys` from
  `tests/gui/test_graph_panel_view.py` (already at its top) (Task 1).
- `tests/gui/test_file_browser_vm.py` and `test_file_browser_view.py` inject real
  `SignalGroup`s via `app_vm.session._groups.add(...)` and set `app_vm._loaded_keys`
  (no CSV, no `request_load`) (Tasks 4, 5). `remove_group` then has a real group to remove.
- `tests/gui/test_integration.py` uses the `_mf4` MDF4 helper + `build_main_window`
  (imported from `valisync.gui.app`, *not* `views.main_window`) (Tasks 6, 7).
- Accessor `inspect()["plotted_signals"][i]["signal_key"]` is confirmed against
  `graph_panel_vm.py` — don't invent alternative accessor names.
- After unload removes all signals from a panel, `_normalize_axes()` keeps one empty
  placeholder axis (full height) — the intended "panel back to empty" state.
