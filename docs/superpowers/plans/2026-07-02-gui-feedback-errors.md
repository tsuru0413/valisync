# gui-feedback-errors 第1弾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ファイルロードのエラーと成功時診断を、専用 Diagnostics ドック＋ハードエラーのモーダル＋ステータスバーで可視化し、サイレント失敗を解消する（FB-01/02/03/06）。

**Architecture:** 案A（厳密）— `Session.load` の戻り値を `str` から `LoadOutcome(key, diagnostics)` に変更し、`LoadError` に `diagnostics` を追加。診断を運ぶ正準経路を Loader→Session→Worker→新 `DiagnosticsViewModel`→新 `DiagnosticsView`（QDockWidget）に一本化。ハードエラーは加えて `QMessageBox.critical`。

**Tech Stack:** Python 3.12/3.13・PySide6・pytest/pytest-qt・ruff・mypy。MVVM（Session が唯一のゲートウェイ、ViewModel は Qt-free）。

## Status / Resume（2026-07-02）

**全タスク完了。** Task 1-6 すべて実装・review・merge 前ゲート充足済み。

- **Task 1: 完了** — commit `21e92f4`（`Session.load` → `LoadOutcome`、`LoadError.diagnostics`、呼び出し移行）。
- **Task 2: 完了** — commit `5cb8565`（`LoadWorker`/`LoadController` が `LoadOutcome`/例外を運ぶ。順序注意ブロック〔下記〕で前倒しした main_window の `_load_file`/`_on_loaded` 変更を含む）。
- **Task 3: 完了** — commit `8da9a8c`（`DiagnosticsViewModel`）。
- **Task 4: 完了** — commit `667ced2` + `f7a66ea`（`DiagnosticsView` QDockWidget、review fix round で destroyed→unsubscribe 追加）。
- **Task 5: 完了** — commit `f413c9f` + `25e9001`（MainWindow 配線。review fix round でプランスニペットの `_on_diagnostic_activated` の key 照合バグを spec §4.4 準拠の source_name/group_signals 解決に修正）。
- **Task 6: 完了** — commit `0e112aa`（`/gui-test-plan` 分析＋Layer B 3件＋realgui 2件。分析ブロックは `.superpowers/sdd/task-6-analysis.md`）。realgui ①ゲート: scoped 2/2 pass、headless full 651 passed/0 errors。

進捗 ledger は `.superpowers/sdd/progress.md`（最終 whole-branch レビューの follow-up 一覧を含む）。

> **⚠️ Task 2 の順序注意（Task 1 の暫定移行に起因・必読）** — **Task 2 で消化済み**（下記は履歴として保持）。
> `tests/gui/test_integration.py:65 test_file_drop_loads_and_refreshes_tree` は `main_window._load_file` → LoadController/worker → `_finish`/`_on_loaded` を実際に叩く。Task 1 は全 suite green のため、暫定的に `main_window._load_file` の lambda を `lambda: session.load(target, None).key`（**str 返し**）に変更している。
> Task 2 で `LoadWorker.finished` を `Signal(object)`・`LoadController._finish` を `outcome.key`/`on_success(outcome)` に変えると、この暫定 str と衝突して当該テストが赤になる（worker が str を emit → `_finish` が `str.key` で AttributeError）。
> **対処**: Task 2 では併せて `main_window._load_file` を `lambda: session.load(target, None)`（**LoadOutcome 返し**）に戻し、`_on_loaded(self, outcome: LoadOutcome)` として最小限 `self.app_vm.register_loaded(outcome.key)` にする（＝Task 5 の `_load_file`/`_on_loaded` シグネチャ変更の中核を Task 2 に前倒し）。Task 5 は outcome 型になった `_on_loaded` の上に診断追記／ステータスバー／アクティブ化／ドックを積む（Task 5 Step 3 のコードはこの前提で読む）。

## Global Constraints

- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- ViewModel は Qt import 禁止（純 Python）。core アクセスは `Session` 経由のみ。
- コメントは WHY を書く。自明なコードに説明を付けない。
- GUI テストは `docs/gui-testing-layers.md` に従う（Layer A/B 必須・CI、Layer C はローカル `--realgui`）。入力経路の受け入れ要件設計は `/gui-test-plan`、merge 前は `/gui-verify`。
- QDockWidget/QToolBar には `setObjectName` を付与（saveState/restoreState のため。memory: dock 復元）。
- worktree では作業前に `uv sync --extra dev`（親の旧コードへのフォールバック防止）。
- 各タスク末尾で `uv run pytest` 全緑を確認してからコミット。

---

## File Structure

**Core（Task 1）**
- Modify `src/valisync/core/session.py` — `LoadOutcome` 追加、`Session.load` の戻り値変更、`load_many` の `succeeded` 型変更、`LoadError.diagnostics` 追加。
- Modify `src/valisync/gui/viewmodels/app_viewmodel.py:148` — `request_load` が `.key` を使う。
- Migrate（戻り値を使う直接 `session.load` 呼び出し）: `tests/test_session.py`・`tests/gui/test_graph_area_cursor.py`・`test_graph_panel_view.py`・`test_graph_panel_vm.py`・`test_integration.py`・`test_load_task.py`・`test_lod_benchmark.py`。

**Worker（Task 2）**
- Modify `src/valisync/gui/workers/load_worker.py` — signals を `object` 化、`LoadOutcome`/例外を運ぶ。
- Modify `tests/gui/test_load_worker.py` — 新シグネチャに追従。

**新 ViewModel（Task 3）**
- Create `src/valisync/gui/viewmodels/diagnostics_vm.py` — `DiagnosticEntry` + `DiagnosticsViewModel`。
- Create `tests/gui/test_diagnostics_vm.py`。

**新 View（Task 4）**
- Create `src/valisync/gui/views/diagnostics_view.py` — `DiagnosticsView(QDockWidget)`。
- Create `tests/gui/test_diagnostics_view.py`。

**MainWindow 配線（Task 5）**
- Modify `src/valisync/gui/views/main_window.py` — dock + statusBar + `_on_loaded(outcome)` + `_on_load_error(path, err)` + アクティブファイル設定 + View メニュートグル。
- Modify `tests/gui/test_main_window.py` — 配線テスト（monkeypatch QMessageBox、FB-03）。

---

## Task 1: Core — `LoadOutcome` と診断の正準化（案A）

**Files:**
- Modify: `src/valisync/core/session.py`
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py:126-150`
- Test: `tests/test_session.py`（拡張＋移行）

**Interfaces:**
- Produces: `LoadOutcome(key: str, diagnostics: tuple[Diagnostic, ...])`（frozen）。`Session.load(path, format_def=None) -> LoadOutcome`。`Session.load_many(...) -> LoadManyResult`（`succeeded: tuple[LoadOutcome, ...]`）。`LoadError(file_path, messages, diagnostics=())` に `diagnostics` 属性。

- [x] **Step 1: Write the failing test（成功時に診断を返す・LoadError が診断を持つ）**

`tests/test_session.py` に追加:

```python
from valisync.core.models.load_result import Diagnostic
from valisync.core.session import LoadError, LoadOutcome


def test_load_returns_outcome_with_key_and_diagnostics(tmp_path):
    csv = _write_csv(tmp_path)  # 既存ヘルパ（本ファイルの CSV 生成）
    session = Session()
    outcome = session.load(csv, format_def=_FMT)
    assert isinstance(outcome, LoadOutcome)
    assert outcome.key == "csv_1"
    assert isinstance(outcome.diagnostics, tuple)


def test_load_error_carries_diagnostics(tmp_path):
    session = Session()
    bad = tmp_path / "nope.mf4"          # 存在しない → mdf4 ローダーが失敗
    bad.write_bytes(b"not an mdf")
    try:
        session.load(bad, None)
    except LoadError as exc:
        assert isinstance(exc.diagnostics, tuple)
    else:
        raise AssertionError("expected LoadError")
```

> `_write_csv`/`_FMT` は `tests/test_session.py` 既存の生成ヘルパを使う（無ければ既存テスト冒頭のパターンで作る）。

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session.py::test_load_returns_outcome_with_key_and_diagnostics -v`
Expected: FAIL（`LoadOutcome` 未定義 / `load` が str を返す）。

- [x] **Step 3: Implement — `session.py` を変更**

`src/valisync/core/session.py` の import に追加:

```python
from valisync.core.models.load_result import Diagnostic
```

`LoadError` を差し替え:

```python
class LoadError(Exception):
    """Raised when a single-file load fails; carries the loader diagnostics."""

    def __init__(
        self,
        file_path: Path,
        messages: list[str],
        diagnostics: tuple[Diagnostic, ...] = (),
    ) -> None:
        self.file_path = file_path
        self.messages = messages
        self.diagnostics = tuple(diagnostics)
        super().__init__(f"failed to load {file_path}: {'; '.join(messages)}")
```

`LoadManyResult` の直前に追加:

```python
@dataclass(frozen=True)
class LoadOutcome:
    """Result of a successful single-file load: group key + loader diagnostics.

    ``diagnostics`` surfaces non-fatal issues (skipped channels, dropped enum
    labels, 0-channel files) that the GUI shows in the Diagnostics dock (FB-02).
    """

    key: str
    diagnostics: tuple[Diagnostic, ...] = ()
```

`LoadManyResult.succeeded` の型を変更:

```python
@dataclass(frozen=True)
class LoadManyResult:
    succeeded: tuple[LoadOutcome, ...] = ()
    failed: tuple[tuple[Path, tuple[str, ...]], ...] = ()
```

`Session.load` を変更（末尾のみ）:

```python
    def load(
        self, file_path: Path, format_def: FormatDefinition | None = None
    ) -> LoadOutcome:
        file_path = Path(file_path)
        if self._csv_loader.supports(file_path):
            if format_def is None:
                raise ValueError("CSV files require a FormatDefinition")
            result = self._csv_loader.load(file_path, format_def)
        elif self._mdf4_loader.supports(file_path):
            result = self._mdf4_loader.load(file_path)
        else:
            raise ValueError(f"no loader supports file: {file_path}")

        if result.signal_group is None:
            messages = [d.message for d in result.diagnostics]
            raise LoadError(file_path, messages, diagnostics=result.diagnostics)
        key = self._groups.add(result.signal_group)
        return LoadOutcome(key=key, diagnostics=result.diagnostics)
```

`Session.load_many` の `succeeded` 追加は `self.load(...)`（LoadOutcome）をそのまま append するだけなので本体変更不要（`succeeded.append(self.load(file_path, format_def))` が LoadOutcome を積む）。型注釈 `succeeded: list[LoadOutcome]` に更新。

- [x] **Step 4: Migrate `request_load`（production）**

`src/valisync/gui/viewmodels/app_viewmodel.py:148` を変更:

```python
        outcome = self._session.load(Path(path), format_def)
        self.register_loaded(outcome.key)
        return outcome.key
```

（`request_load` の戻り値は `str` のまま＝request_load 呼び出し側は無改修。）

- [x] **Step 5: Migrate 直接 `session.load` の戻り値使用箇所（テスト）**

変換ルール: `key = session.load(...)` → `key = session.load(...).key`。`ka = session.load(a, ...)` 等も同様。`load_many` は `result.succeeded[0]` → `result.succeeded[0].key`。`task.run(lambda: session.load(...))` は `lambda: session.load(...).key`。**戻り値を使わない `session.load(...)`（`_panel_factory.py` や多くの realgui）は無改修**。

対象（行は目安・着手時に再確認）:
- `tests/test_session.py`:47, 68, 82, 83, 114, 127 → `.key`。:99-102 の `result.succeeded[0] == "csv_1"` → `result.succeeded[0].key == "csv_1"`。
- `tests/gui/test_graph_area_cursor.py`:31 → `.key`
- `tests/gui/test_graph_panel_view.py`:59 → `.key`
- `tests/gui/test_graph_panel_vm.py`:73 → `.key`
- `tests/gui/test_integration.py`:92, 115 → `.key`
- `tests/gui/test_load_task.py`:164, 179, 189 → lambda を `session.load(...).key` に
- `tests/gui/test_lod_benchmark.py`:43 → `.key`

（`tests/gui/test_load_worker.py` の 2 箇所は Task 2 で扱う。）

- [x] **Step 6: Run full suite green**

Run: `uv run pytest -q`
Expected: PASS（新テスト2件含め全緑）。1件でも赤なら移行漏れ → 赤テストの `session.load(...)` に `.key` を補う。

- [x] **Step 7: 型・lint**

Run: `uv run mypy src/ && uv run ruff check && uv run ruff format --check`
Expected: いずれもエラー無し。

- [x] **Step 8: Commit**

```bash
git add src/valisync/core/session.py src/valisync/gui/viewmodels/app_viewmodel.py tests/
git commit -m "feat(core): Session.load が LoadOutcome(key, diagnostics) を返す（案A・FB-02 土台）"
```

---

## Task 2: Worker — `LoadOutcome`/例外を運ぶ

**Files:**
- Modify: `src/valisync/gui/workers/load_worker.py`
- Test: `tests/gui/test_load_worker.py`

**Interfaces:**
- Consumes: `LoadOutcome`（Task 1）。
- Produces: `LoadWorkerSignals.finished = Signal(object)`（`LoadOutcome`）/ `failed = Signal(object)`（例外 `Exception`、多くは `LoadError`）。`LoadController.submit(..., on_success: Callable[[LoadOutcome], None], on_error: Callable[[Exception], None])`。

- [x] **Step 1: Write the failing test（finished が LoadOutcome、failed が例外を運ぶ）**

`tests/gui/test_load_worker.py` の `TestLoadWorker` を差し替え:

```python
    def test_emits_finished_with_outcome(self, qtbot, tmp_path):
        from valisync.core.session import LoadOutcome
        from valisync.gui.workers.load_worker import LoadWorker

        path, fmt = _csv(tmp_path)
        session = Session()
        worker = LoadWorker(lambda: session.load(path, fmt))
        with qtbot.waitSignal(worker.signals.finished, timeout=3000) as blocker:
            QThreadPool.globalInstance().start(worker)
        assert isinstance(blocker.args[0], LoadOutcome)
        assert blocker.args[0].key
        assert len(session.signals()) == 1

    def test_emits_failed_with_exception(self, qtbot):
        from valisync.gui.workers.load_worker import LoadWorker

        def boom():
            raise ValueError("nope")

        worker = LoadWorker(boom)
        with qtbot.waitSignal(worker.signals.failed, timeout=3000) as blocker:
            QThreadPool.globalInstance().start(worker)
        assert isinstance(blocker.args[0], Exception)
        assert "nope" in str(blocker.args[0])
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_load_worker.py::TestLoadWorker -v`
Expected: FAIL（finished/failed が str のまま）。

- [x] **Step 3: Implement — `load_worker.py` を変更**

`LoadWorkerSignals` を変更:

```python
class LoadWorkerSignals(QObject):
    """Signal carrier for :class:`LoadWorker` (QRunnable cannot emit signals)."""

    finished = Signal(object)  # LoadOutcome on success
    failed = Signal(object)  # the raised Exception (usually LoadError) on failure
```

`LoadWorker.run` / 型を変更:

```python
    def __init__(self, load_callable: Callable[[], object]) -> None:
        super().__init__()
        self._load_callable = load_callable
        self.signals = LoadWorkerSignals()

    def run(self) -> None:
        try:
            outcome = self._load_callable()  # LoadOutcome
        except Exception as exc:  # report, never crash the pool thread
            self.signals.failed.emit(exc)
        else:
            self.signals.finished.emit(outcome)
```

`LoadController._finish` の `task.succeed`/`on_success` を LoadOutcome 対応に:

```python
    def _finish(self, worker, outcome, task, busy, on_success):
        self._active.discard(worker)
        if busy is not None:
            busy.hide()
        if task is not None:
            task.succeed(outcome.key)
        if on_success is not None:
            on_success(outcome)
```

`LoadController._fail` の引数名を `exc` にし、`task.fail(str(exc))` / `on_error(exc)`:

```python
    def _fail(self, worker, exc, task, busy, on_error):
        self._active.discard(worker)
        if busy is not None:
            busy.hide()
        if task is not None:
            task.fail(str(exc))
        if on_error is not None:
            on_error(exc)
```

`submit` 内の connect ラムダの引数名を合わせる（`lambda outcome: self._finish(...)` / `lambda exc: self._fail(...)`）。`on_success`/`on_error` の型注釈を更新:

```python
        on_success: Callable[[object], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
```

- [x] **Step 4: 既存 LoadController テストを追従**

`tests/gui/test_load_worker.py::TestLoadController::test_success_updates_tree_task_and_hides_busy` の `on_success` を outcome 受けに:

```python
            on_success=lambda outcome: (
                app_vm.register_loaded(outcome.key),
                keys.append(outcome.key),
            ),
```

`test_failure_sets_task_error` は `on_error=errors.append`（例外オブジェクトを受ける）→ `assert errors and "bad file" in str(errors[0])` に更新。`task.error_message` は `str(exc)` なので `"bad file" in (task.error_message or "")` はそのまま緑。

- [x] **Step 5: Run tests**

Run: `uv run pytest tests/gui/test_load_worker.py -v`
Expected: PASS。

- [x] **Step 6: Commit**

```bash
git add src/valisync/gui/workers/load_worker.py tests/gui/test_load_worker.py
git commit -m "feat(gui): LoadWorker/Controller が LoadOutcome/例外を運ぶ（診断伝播）"
```

---

## Task 3: `DiagnosticsViewModel`（Qt-free）

**Files:**
- Create: `src/valisync/gui/viewmodels/diagnostics_vm.py`
- Test: `tests/gui/test_diagnostics_vm.py`

**Interfaces:**
- Consumes: `Diagnostic`（`valisync.core.models.load_result`）。
- Produces: `DiagnosticEntry(level, message, source, signal_name, seq)`。`DiagnosticsViewModel(Observable)`: `add(source: str, diagnostics: Iterable[Diagnostic]) -> None`、`clear() -> None`、`entries(level: str | None = None) -> list[DiagnosticEntry]`、`counts() -> tuple[int, int]`（errors, warnings）。通知タグ `"diagnostics"`。

- [x] **Step 1: Write the failing test**

`tests/gui/test_diagnostics_vm.py`:

```python
from valisync.core.models.load_result import Diagnostic
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel


def _diag(level, msg, signal=None):
    return Diagnostic(level=level, message=msg, signal_name=signal)


def test_add_appends_and_notifies():
    vm = DiagnosticsViewModel()
    seen = []
    vm.subscribe(seen.append)
    vm.add("a.mf4", [_diag("warning", "skip", "gps")])
    assert "diagnostics" in seen
    e = vm.entries()
    assert len(e) == 1
    assert e[0].source == "a.mf4"
    assert e[0].level == "warning"
    assert e[0].signal_name == "gps"


def test_counts_errors_and_warnings():
    vm = DiagnosticsViewModel()
    vm.add("a", [_diag("error", "boom"), _diag("warning", "w1"), _diag("warning", "w2")])
    assert vm.counts() == (1, 2)


def test_entries_filter_by_level():
    vm = DiagnosticsViewModel()
    vm.add("a", [_diag("error", "e"), _diag("warning", "w")])
    assert len(vm.entries("error")) == 1
    assert vm.entries("error")[0].message == "e"


def test_clear_empties_and_notifies():
    vm = DiagnosticsViewModel()
    vm.add("a", [_diag("warning", "w")])
    seen = []
    vm.subscribe(seen.append)
    vm.clear()
    assert vm.entries() == []
    assert "diagnostics" in seen


def test_seq_is_monotonic_across_adds():
    vm = DiagnosticsViewModel()
    vm.add("a", [_diag("warning", "w1")])
    vm.add("b", [_diag("warning", "w2")])
    seqs = [e.seq for e in vm.entries()]
    assert seqs == sorted(seqs) and len(set(seqs)) == 2
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_diagnostics_vm.py -v`
Expected: FAIL（モジュール未作成）。

- [x] **Step 3: Implement**

`src/valisync/gui/viewmodels/diagnostics_vm.py`:

```python
"""DiagnosticsViewModel — Qt-free accumulator of load diagnostics (FB-02).

Collects Diagnostic records emitted by loads (success-time warnings and
hard-error messages) so the Diagnostics dock can display a session history.
Pure Python; the View subscribes for the "diagnostics" change tag.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from valisync.core.models.load_result import Diagnostic
from valisync.gui.viewmodels.observable import Observable


@dataclass(frozen=True)
class DiagnosticEntry:
    """A single diagnostic with its source file and receipt order (seq)."""

    level: str  # "error" | "warning"
    message: str
    source: str  # file basename
    signal_name: str | None
    seq: int  # monotonic receipt order (stable display order)


class DiagnosticsViewModel(Observable):
    """Accumulates DiagnosticEntry records; notifies "diagnostics" on change."""

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[DiagnosticEntry] = []
        self._seq: int = 0

    def add(self, source: str, diagnostics: Iterable[Diagnostic]) -> None:
        """Append each Diagnostic under *source*; notify once if any were added."""
        added = False
        for d in diagnostics:
            self._entries.append(
                DiagnosticEntry(
                    level=d.level,
                    message=d.message,
                    source=source,
                    signal_name=d.signal_name,
                    seq=self._seq,
                )
            )
            self._seq += 1
            added = True
        if added:
            self._notify("diagnostics")

    def clear(self) -> None:
        """Drop all entries and notify."""
        self._entries.clear()
        self._notify("diagnostics")

    def entries(self, level: str | None = None) -> list[DiagnosticEntry]:
        """Return entries, optionally filtered by level ("error"/"warning")."""
        if level is None:
            return list(self._entries)
        return [e for e in self._entries if e.level == level]

    def counts(self) -> tuple[int, int]:
        """Return (error_count, warning_count)."""
        errors = sum(1 for e in self._entries if e.level == "error")
        warnings = sum(1 for e in self._entries if e.level == "warning")
        return errors, warnings
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/gui/test_diagnostics_vm.py -v`
Expected: PASS（5件）。

- [x] **Step 5: Commit**

```bash
git add src/valisync/gui/viewmodels/diagnostics_vm.py tests/gui/test_diagnostics_vm.py
git commit -m "feat(gui): DiagnosticsViewModel（診断の蓄積・フィルタ・件数）"
```

---

## Task 4: `DiagnosticsView`（QDockWidget）

**Files:**
- Create: `src/valisync/gui/views/diagnostics_view.py`
- Test: `tests/gui/test_diagnostics_view.py`

**Interfaces:**
- Consumes: `DiagnosticsViewModel`（Task 3）。
- Produces: `DiagnosticsView(QDockWidget)`; `objectName == "diagnostics_dock"`; テーブルは VM の `entries(current_filter)` を表示; `set_filter(level | None)`; ダブルクリックで `entry_activated = Signal(str)`（signal_name または source）を emit。VM の "diagnostics" 購読で自動再描画。

- [x] **Step 1: Write the failing test（Layer B: 描画・フィルタ・Clear）**

`tests/gui/test_diagnostics_view.py`:

```python
from valisync.core.models.load_result import Diagnostic
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel
from valisync.gui.views.diagnostics_view import DiagnosticsView


def _mk(qtbot):
    vm = DiagnosticsViewModel()
    view = DiagnosticsView(vm)
    qtbot.addWidget(view)
    return vm, view


def test_object_name_for_state_persistence(qtbot):
    _, view = _mk(qtbot)
    assert view.objectName() == "diagnostics_dock"


def test_rows_reflect_vm_entries(qtbot):
    vm, view = _mk(qtbot)
    vm.add("a.mf4", [Diagnostic(level="error", message="boom")])
    vm.add("b.mf4", [Diagnostic(level="warning", message="skip", signal_name="gps")])
    assert view.row_count() == 2


def test_filter_warnings_only(qtbot):
    vm, view = _mk(qtbot)
    vm.add("a", [Diagnostic(level="error", message="e"),
                 Diagnostic(level="warning", message="w")])
    view.set_filter("warning")
    assert view.row_count() == 1


def test_clear_empties_view(qtbot):
    vm, view = _mk(qtbot)
    vm.add("a", [Diagnostic(level="warning", message="w")])
    view.clear_diagnostics()
    assert view.row_count() == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_diagnostics_view.py -v`
Expected: FAIL（モジュール未作成）。

- [x] **Step 3: Implement**

`src/valisync/gui/views/diagnostics_view.py`:

```python
"""DiagnosticsView — dockable list of load diagnostics (FB-02 surface).

A QDockWidget with a table (level / source / message / signal) plus a filter
(All/Errors/Warnings) and Clear. Subscribes to DiagnosticsViewModel and rebuilds
its rows on the "diagnostics" change tag. Double-clicking a row emits
``entry_activated`` with the signal name (or source) so MainWindow can jump to it.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel

_LEVEL_ICON = {"error": "⛔", "warning": "⚠"}
_HEADERS = ("Lv", "ソース", "メッセージ", "対象")


class DiagnosticsView(QDockWidget):
    """Dockable diagnostics list bound to a DiagnosticsViewModel."""

    entry_activated = Signal(str)

    def __init__(self, vm: DiagnosticsViewModel) -> None:
        super().__init__("Diagnostics")
        self.setObjectName("diagnostics_dock")  # required for saveState/restoreState
        self._vm = vm
        self._filter: str | None = None

        container = QWidget(self)
        outer = QVBoxLayout(container)

        bar = QHBoxLayout()
        self._btn_all = QPushButton("All")
        self._btn_err = QPushButton("Errors")
        self._btn_warn = QPushButton("Warnings")
        self._btn_clear = QPushButton("Clear")
        self._btn_all.clicked.connect(lambda: self.set_filter(None))
        self._btn_err.clicked.connect(lambda: self.set_filter("error"))
        self._btn_warn.clicked.connect(lambda: self.set_filter("warning"))
        self._btn_clear.clicked.connect(self.clear_diagnostics)
        for b in (self._btn_all, self._btn_err, self._btn_warn, self._btn_clear):
            bar.addWidget(b)
        bar.addStretch(1)
        outer.addLayout(bar)

        self._table = QTableWidget(0, len(_HEADERS), container)
        self._table.setHorizontalHeaderLabels(list(_HEADERS))
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        outer.addWidget(self._table)

        self.setWidget(container)
        self._unsubscribe = self._vm.subscribe(self._on_vm_change)
        self._rebuild()

    def set_filter(self, level: str | None) -> None:
        self._filter = level
        self._rebuild()

    def clear_diagnostics(self) -> None:
        self._vm.clear()  # triggers "diagnostics" → _rebuild

    def row_count(self) -> int:
        """Number of rows currently displayed (test-facing)."""
        return self._table.rowCount()

    def _on_vm_change(self, change: str) -> None:
        if change == "diagnostics":
            self._rebuild()

    def _rebuild(self) -> None:
        entries = self._vm.entries(self._filter)
        self._table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            cells = (
                _LEVEL_ICON.get(e.level, "?"),
                e.source,
                e.message,
                e.signal_name or "—",
            )
            for c, text in enumerate(cells):
                self._table.setItem(r, c, QTableWidgetItem(text))

    def _on_double_click(self, row: int, _col: int) -> None:
        entries = self._vm.entries(self._filter)
        if 0 <= row < len(entries):
            e = entries[row]
            self.entry_activated.emit(e.signal_name or e.source)
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/gui/test_diagnostics_view.py -v`
Expected: PASS（4件）。

- [x] **Step 5: 型・lint**

Run: `uv run mypy src/ && uv run ruff check`
Expected: エラー無し。

- [x] **Step 6: Commit**

```bash
git add src/valisync/gui/views/diagnostics_view.py tests/gui/test_diagnostics_view.py
git commit -m "feat(gui): DiagnosticsView（QDockWidget・フィルタ/Clear/ダブルクリック）"
```

---

## Task 5: MainWindow 配線（FB-01/02/03/06）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_main_window.py`

**Interfaces:**
- Consumes: `LoadOutcome`（T1）、`DiagnosticsViewModel`/`DiagnosticsView`（T3/T4）、`app_vm.set_active_file`（既存）。
- Produces: `MainWindow.diagnostics_vm` / `MainWindow.diagnostics_dock`。`_on_loaded(outcome: LoadOutcome)` / `_on_load_error(path: Path, err: Exception)`。ステータスバー更新。

- [x] **Step 1: Write the failing tests（Layer A 配線）**

`tests/gui/test_main_window.py` に追加（`_make_window` は既存ヘルパ）:

```python
from pathlib import Path

from valisync.core.models.load_result import Diagnostic
from valisync.core.session import LoadError, LoadOutcome


def test_load_error_shows_dialog_and_records(qtbot, monkeypatch):
    window = _make_window(qtbot)
    calls = {}
    import valisync.gui.views.main_window as mw

    monkeypatch.setattr(
        mw.QMessageBox, "critical",
        lambda *a, **k: calls.setdefault("shown", a),
    )
    err = LoadError(Path("bad.mdf"), ["no loader supports file"])
    window._on_load_error(Path("bad.mdf"), err)
    assert "shown" in calls  # FB-01: modal shown
    assert window.diagnostics_vm.counts()[0] == 1  # 1 error recorded


def test_on_loaded_records_warnings_and_activates(qtbot, tmp_path):
    window = _make_window(qtbot)
    # Load a real CSV via the app_vm so a group exists, then simulate the callback.
    # (QSettings isolation is applied automatically by the autouse fixture in
    #  tests/gui/conftest.py — no import needed.)
    key = window.app_vm.request_load(_write_csv(tmp_path), _csv_format())
    outcome = LoadOutcome(
        key=key, diagnostics=(Diagnostic(level="warning", message="skip", signal_name="x"),)
    )
    window._on_loaded(outcome)
    assert window.app_vm.active_file_key == key      # FB-03
    assert window.diagnostics_vm.counts()[1] >= 1    # FB-02 warning recorded


def test_diagnostics_dock_exists_with_object_name(qtbot):
    window = _make_window(qtbot)
    assert window.diagnostics_dock.objectName() == "diagnostics_dock"
```

> `_write_csv`/`_csv_format` は本テストに無ければ `tests/gui/test_app_viewmodel.py` のヘルパを複製（同ディレクトリの既存パターン）。

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gui/test_main_window.py -k "load_error or on_loaded or diagnostics_dock" -v`
Expected: FAIL（属性/挙動未実装）。

- [x] **Step 3: Implement — `main_window.py`**

import 追加:

```python
from pathlib import Path

from PySide6.QtWidgets import QDockWidget, QMainWindow, QMessageBox, QToolBar

from valisync.core.session import LoadError, LoadOutcome
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel
from valisync.gui.views.diagnostics_view import DiagnosticsView
```

`__init__` の ViewModels 群に追加:

```python
        self.diagnostics_vm = DiagnosticsViewModel()
```

Channel dock 構築後（`splitDockWidget` の後あたり）に Diagnostics ドックを追加:

```python
        # ── Diagnostics dock (bottom, FB-02/FB-06 surface) ───────────────────
        self.diagnostics_dock = DiagnosticsView(self.diagnostics_vm)
        self.diagnostics_dock.entry_activated.connect(self._on_diagnostic_activated)
        self.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.diagnostics_dock
        )
```

View メニューにトグル追加（既存 `view_menu` に）:

```python
        view_menu.addAction(self.diagnostics_dock.toggleViewAction())
```

ステータスバーを初期化（toolbar 構築後あたり）:

```python
        self.statusBar().showMessage("準備完了")
```

`_load_file` の `on_error` を path 付きに:

```python
    def _load_file(self, path: str | Path) -> None:
        session = self.app_vm.session
        target = Path(path)
        self._load_controller.submit(
            lambda: session.load(target, None),
            busy=self.busy_overlay,
            on_success=self._on_loaded,
            on_error=lambda err: self._on_load_error(target, err),
        )
```

`_on_loaded` / `_on_load_error` を差し替え、ヘルパ追加:

```python
    def _on_loaded(self, outcome: LoadOutcome) -> None:
        # GUI thread; register, surface diagnostics, activate, update status.
        self.app_vm.register_loaded(outcome.key)
        source = self.app_vm.session.source_name(outcome.key)
        self.diagnostics_vm.add(source, outcome.diagnostics)
        self.app_vm.set_active_file(outcome.key)  # FB-03: fill Channel Browser
        msg = f"{source} を読み込みました"
        if outcome.diagnostics:
            msg += f" ・ ⚠ {len(outcome.diagnostics)} 件の診断（Diagnostics を参照）"
        self.statusBar().showMessage(msg)

    def _on_load_error(self, path: Path, err: Exception) -> None:
        # FB-01: never silent — record + modal + status.
        source = path.name
        diags = getattr(err, "diagnostics", ())
        messages = getattr(err, "messages", [str(err)])
        if diags:
            self.diagnostics_vm.add(source, diags)
        else:
            from valisync.core.models.load_result import Diagnostic

            self.diagnostics_vm.add(
                source, [Diagnostic(level="error", message="; ".join(messages))]
            )
        self.statusBar().showMessage(f"⛔ 読み込み失敗: {source}")
        self.diagnostics_dock.show()
        self.diagnostics_dock.raise_()
        QMessageBox.critical(
            self,
            "読み込みエラー",
            f"{source} を読み込めませんでした。\n\n" + "; ".join(messages),
        )

    def _on_diagnostic_activated(self, target: str) -> None:
        # Best-effort jump: select the signal's file in the channel browser.
        # (Detailed signal-row selection is a later task; activating the file is
        # enough to surface the context.)
        for key in self.app_vm.loaded_file_keys:
            if target.startswith(key) or key in target:
                self.app_vm.set_active_file(key)
                return
```

`_on_load_error` は `LoadError` 以外（`ValueError` 等）も `err` として受けるため `getattr` で防御。

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/gui/test_main_window.py -v`
Expected: PASS（既存＋新規）。

- [x] **Step 5: 全緑・型・lint**

Run: `uv run pytest -q && uv run mypy src/ && uv run ruff check && uv run ruff format --check`
Expected: 全て緑/エラー無し。

- [x] **Step 6: Commit**

```bash
git add src/valisync/gui/views/main_window.py tests/gui/test_main_window.py
git commit -m "feat(gui): MainWindow に Diagnostics ドック＋モーダル＋ステータスバー配線（FB-01/02/03/06）"
```

---

## Task 6: 入力経路の受け入れ要件（`/gui-test-plan`）＋実機検証（`/gui-verify`）

**目的:** ダブルクリック→ジャンプ・フィルタボタンの入力経路が headless で false-green にならないことを保証（catalog の realgui 教訓）。

- [x] **Step 1:** `/gui-test-plan` を実行し、`DiagnosticsView` の入力経路（フィルタボタン clicked、行ダブルクリック→`entry_activated`→アクティブファイル切替）について②実質的な受け入れ要件（Layer 判定・realgui 要否）を設計する。ダブルクリック→ジャンプは Layer C 候補。
- [x] **Step 2:** 設計に従い Layer B（合成 double-click → signal emit）を `tests/gui/test_diagnostics_view.py` に追加。必要なら Layer C（`tests/realgui/`）を追加。
- [x] **Step 3:** merge 前に `/gui-verify` を実行し、①realgui 証拠ゲートを満たす（realgui が skipped=検証済みと誤認されない）。
- [x] **Step 4: Commit**（テスト追加分）。

---

## Self-Review

**1. Spec coverage（spec §6 の FB 対応表）**
- FB-01 → Task 5 `_on_load_error`（modal + 記録 + status + dock raise）✓
- FB-02 → Task 1（LoadOutcome/LoadError.diagnostics）+ Task 2（worker 伝播）+ Task 3/4（VM/View）+ Task 5（`_on_loaded` で add）✓
- FB-03 → Task 5 `_on_loaded` の `set_active_file` ✓
- FB-06 → Task 5 `statusBar()` ✓
- spec §8 テスト戦略 → Core 単体（T1）/Layer A（T2,T5）/Layer B（T4）/入力経路（T6）✓

**2. Placeholder scan:** Step のコードはすべて実体。TBD/TODO/「適切に」等の曖昧語なし。（初稿にあった不完全 import 断片 `from tests.gui.conftest import` は本 self-review で除去済み。）

**3. Type consistency:** `LoadOutcome.key: str` / `diagnostics: tuple[Diagnostic,...]`、`DiagnosticsViewModel.add(source, diagnostics)`、`entries(level)`、`counts()->(int,int)`、`DiagnosticsView.row_count()`/`set_filter`/`clear_diagnostics`/`entry_activated: Signal(str)` は全タスクで一貫。`_on_loaded(outcome)` / `_on_load_error(path, err)` は Task 2 の `on_success(LoadOutcome)`/`on_error(Exception)` と整合。
