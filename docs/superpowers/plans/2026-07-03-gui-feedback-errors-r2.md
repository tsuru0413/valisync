# gui-feedback-errors 第2弾 Implementation Plan

## Status（2026-07-03）

Task 1-11 完了。commits: Task1 `db126f5`・T2 `809bd85`・T3 `6b16e60`・T4
`e33419b`・T5 `e778669`+`60ad885`・T6 `bb71ae0`・T7 `41e03a8`・T8 `4d5a9fd`・T9
`6dc60da`・T10 `8ab5baa`+`43cf3b5`・T11 `a18a75d`。realgui ①ゲート scoped
10/10・headless 684 passed/0 errors。

承認済み逸脱4件:
- CSV チェックポイントの data_start 相対位置化（プラン原文はヘッダ有りで
  不発のバグ — `raw_idx % 1000` はヘッダ/単位行分だけオフセットしてズレる
  ため、データ行の相対位置 `(raw_idx - data_start) % 1000` に修正）
- mdf4 の `except LoadCancelled: raise` 追加（広い `except Exception` に
  LoadCancelled が飲まれて一般エラー診断に化けるのを防止）
- Task 7 の textChanged 直結削除（`set_filter` が同期的に "filter" を notify
  するため、追加の直結があると1キーストロークで二重に `_refresh_state` が
  走る — VM 通知一本化）
- Task 5 の on_discard nested function 化（mypy: ラムダに閉じ込めると
  `Callable[[LoadOutcome], None]` の型解決が通らないため）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ロード中の可視化と中断（ハイブリッドキャンセル）＋「いま何を見ているか」の常設表示（ヘッダ/タイトル/プレースホルダ/ツールチップ）で FB-04/05/07/08/09/10 を解消する。

**Architecture:** 第1弾の器（`LoadOutcome` 伝播・ステータスバー・QStackedWidget プレースホルダパターン）の上に積む。core 変更は2点のみ — `Session.load` への `cancel` 協調的中断（`LoadCancelled`）と読み取り専用 `Session.source_info`。GUI は BusyOverlay/LoadController の世代管理＋各 View のヘッダ/プレースホルダ/ToolTipRole。

**Tech Stack:** Python 3.12/3.13・PySide6・pytest/pytest-qt・ruff・mypy。MVVM（Session が唯一のゲートウェイ、ViewModel は Qt-free）。

**Spec:** [docs/superpowers/specs/2026-07-03-gui-feedback-errors-r2-design.md](../specs/2026-07-03-gui-feedback-errors-r2-design.md)

## Global Constraints

- 品質ゲート（コミット前に全通過・プロジェクト全体スコープ）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- ViewModel は Qt import 禁止（純 Python）。core アクセスは `Session` 経由のみ。
- コメントは WHY を書く。自明なコードに説明を付けない。
- GUI テストは `docs/gui-testing-layers.md` に従う（Layer A/B 必須・CI、Layer C はローカル `--realgui`）。既実装コードへのテスト追加は sabotage-RED（対象配線を一時的に外して落ちることを確認→復元）。
- **既存の入力経路（検索・信号 D&D・右クリック・ファイルドロップ）は無変更**（realgui 実証済み経路を壊さない）。
- worktree では作業前に `uv sync --extra dev`。
- キャンセルは**ユーザー起点の正常系**: モーダル無し・Diagnostics 追記無し・ステータスバーのみ（spec §4.1/§6）。
- 実行形態: 実装は直列 SDD。**タスクレビュー/最終レビューは Workflow 多レンズ並列**（spec §7・コントローラ向け指示）。

---

## File Structure

**core（Task 1-2）**
- Modify `src/valisync/core/session.py` — `LoadCancelled`・`Session.load(..., cancel)`・`SourceInfo`/`source_info`。
- Modify `src/valisync/core/loaders/mdf4_loader.py` — `load(..., cancel)`＋チャンネル境界チェック。
- Modify `src/valisync/core/loaders/csv_loader.py` — `load(..., cancel)`＋1000行ごとチェック。

**FB-04 gui（Task 3-5）**
- Modify `src/valisync/gui/views/busy_overlay.py` — ラベル・キャンセルボタン・`cancel_requested`・`set_message`。
- Modify `src/valisync/gui/viewmodels/load_task.py` — `cancelled` 状態。
- Modify `src/valisync/gui/workers/load_worker.py` — `cancel_event`/世代管理/カウント表示/cancelled 経路/`on_discard`。
- Modify `src/valisync/gui/views/main_window.py` — Event 生成・cancel 配線・status。

**表示系（Task 6-10）**
- Modify `src/valisync/gui/viewmodels/channel_browser_vm.py` — `header_text`/`empty_state`/`filter_query`。
- Modify `src/valisync/gui/views/channel_browser_view.py` — ヘッダ QLabel＋QStackedWidget。
- Modify `src/valisync/gui/views/file_browser_view.py` — プレースホルダ。
- Modify `src/valisync/gui/viewmodels/file_browser_vm.py` — `file_info`/`tooltip_text`。
- Modify `src/valisync/gui/adapters/qt_signal_models.py` — `FileListModel` に `ToolTipRole`。
- Modify `src/valisync/gui/views/main_window.py` — タイトル（Task 10）。

**Layer C（Task 11）**
- Create `tests/realgui/test_busy_cancel_realclick.py`。

---

## Task 1: core — `LoadCancelled` と `cancel` パラメータ（FB-04 ハード側）

**Files:**
- Modify: `src/valisync/core/session.py`
- Modify: `src/valisync/core/loaders/mdf4_loader.py`
- Modify: `src/valisync/core/loaders/csv_loader.py`
- Test: `tests/test_session.py`（追加）・`tests/test_loaders.py`（追加）

**Interfaces:**
- Produces: `LoadCancelled(Exception)`（`valisync.core.session`）。`Session.load(path, format_def=None, cancel: Callable[[], bool] | None = None) -> LoadOutcome`。`CsvLoader.load(path, format_def, cancel=None)` / `Mdf4Loader.load(path, cancel=None)` — `cancel()` が True になった次のチェックポイントで `LoadCancelled` を raise（グループ未登録・LoadResult を返さない）。

- [x] **Step 1: Write the failing tests**

`tests/test_session.py` に追加（`_write_csv`/`_FMT` は本ファイル既存ヘルパ）:

```python
from valisync.core.session import LoadCancelled


def test_load_cancel_raises_and_registers_nothing(tmp_path):
    csv = _write_csv(tmp_path)
    session = Session()
    with pytest.raises(LoadCancelled):
        session.load(csv, format_def=_FMT, cancel=lambda: True)
    assert session.signals() == []


def test_load_without_cancel_is_unchanged(tmp_path):
    csv = _write_csv(tmp_path)
    session = Session()
    outcome = session.load(csv, format_def=_FMT)
    assert outcome.key == "csv_1"
```

`tests/test_loaders.py` に追加（CSV はチェック粒度も検証。ヘルパ/FormatDefinition は本ファイル既存のパターンを再利用）:

```python
from valisync.core.session import LoadCancelled


def test_csv_loader_cancel_checked_per_1000_rows(tmp_path):
    # 2500 データ行 → チェックは概ね 1000 行ごと＋ループ外周辺のみ
    fmt = FormatDefinition(
        name="fmt", delimiter=Delimiter.COMMA, timestamp_column=0,
        timestamp_unit="sec", signal_start_column=1, signal_end_column=1,
        has_header=True,
    )
    path = tmp_path / "big.csv"
    rows = "\n".join(f"{i * 0.001},{i}" for i in range(2500))
    path.write_text("t,v\n" + rows + "\n", encoding="utf-8")

    calls = []

    def cancel() -> bool:
        calls.append(1)
        return len(calls) >= 2  # 2回目のチェックで中断

    with pytest.raises(LoadCancelled):
        CsvLoader().load(path, fmt, cancel=cancel)
    assert 2 <= len(calls) <= 5  # 行数比例で毎行呼ばれていないこと


def test_mdf4_loader_cancel_raises(tmp_path):
    path = _write_mdf4(tmp_path)  # tests/mdf4_helpers.py の既存生成ヘルパを使う
    with pytest.raises(LoadCancelled):
        Mdf4Loader().load(path, cancel=lambda: True)
```

> `_write_mdf4` 相当のヘルパ名は `tests/mdf4_helpers.py`・既存の mdf4 テストの使用箇所を確認して合わせる（着手時に実名を確認）。

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session.py -k cancel -v && uv run pytest tests/test_loaders.py -k cancel -v`
Expected: FAIL（`LoadCancelled` 未定義 / `cancel` 引数なしで TypeError）。

- [x] **Step 3: Implement — session.py**

`LoadError` の直後に追加:

```python
class LoadCancelled(Exception):
    """Raised when a load is cancelled via the cooperative ``cancel`` callback.

    User-initiated: callers must NOT surface this as an error (no modal, no
    diagnostics entry) — see spec §4.1/§6.
    """
```

`Session.load` を変更（`cancel` を透過するだけ）:

```python
    def load(
        self,
        file_path: Path,
        format_def: FormatDefinition | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> LoadOutcome:
        file_path = Path(file_path)
        if self._csv_loader.supports(file_path):
            if format_def is None:
                raise ValueError("CSV files require a FormatDefinition")
            result = self._csv_loader.load(file_path, format_def, cancel=cancel)
        elif self._mdf4_loader.supports(file_path):
            result = self._mdf4_loader.load(file_path, cancel=cancel)
        else:
            raise ValueError(f"no loader supports file: {file_path}")
        ...  # 以降（signal_group None → LoadError / add → LoadOutcome）は不変
```

`from collections.abc import Callable` を import に追加（未 import の場合）。

- [x] **Step 4: Implement — mdf4_loader.py**

シグネチャ変更＋`list(...)` の逐次化（mdf4_loader.py:60/88 付近）:

```python
    def load(
        self,
        file_path: Path,
        cancel: Callable[[], bool] | None = None,
    ) -> LoadResult:
```

```python
        # 旧: raw = list(mdf.iter_channels(skip_master=True, copy_master=True))
        # チャンネルデータ読みが支配的コストなので、1 チャンネルごとに
        # 協調的キャンセルを確認できるよう逐次で貯める（spec §4.1）。
        raw = []
        for ch in mdf.iter_channels(skip_master=True, copy_master=True):
            if cancel is not None and cancel():
                raise LoadCancelled(f"load cancelled: {file_path.name}")
            raw.append(ch)
```

変換ループ（同 :112 `for asammdf_sig in raw:`）の先頭にも同じ2行を追加。import: `from valisync.core.session import LoadCancelled` は**循環**になるため、`LoadCancelled` は `valisync.core.models.load_result` に定義し `session.py` から re-export する形にする:

- `src/valisync/core/models/load_result.py` に `class LoadCancelled(Exception)` を定義（docstring は Step 3 のもの）。
- `session.py` は `from valisync.core.models.load_result import Diagnostic, LoadCancelled` として re-export（`__all__` 相当の公開面は session 経由 — テストは `from valisync.core.session import LoadCancelled` を使う）。
- loaders は `from valisync.core.models.load_result import LoadCancelled` を import。

- [x] **Step 5: Implement — csv_loader.py**

シグネチャ: `def load(self, file_path: Path, format_def: FormatDefinition, cancel: Callable[[], bool] | None = None) -> LoadResult:`

データ行ループ（csv_loader.py:107 `for raw_idx, row in enumerate(rows[row_idx:], start=row_idx):`）の先頭に:

> **実装差分（承認済み逸脱）**: プラン原文の `raw_idx % 1000 == 0` はヘッダ/
> 単位行がある CSV では `data_start`（最初のデータ行の index）だけ
> `raw_idx` がオフセットしてズレ、チェックポイントが 1000 行境界からずれる
> だけでなく `has_header=True` の典型ケースで不発になり得るバグだった。
> 実装は **データ行の相対位置**（`data_start` 起点）で判定する。

```python
            # 1000 データ行ごとの協調的キャンセル確認(毎行だとオーバーヘッド・spec
            # §4.1)。ヘッダー/単位行の有無で raw_idx のオフセットが変わるため、
            # 判定はデータ行の相対位置(先頭データ行を含む)で行う。
            if cancel is not None and (raw_idx - data_start) % 1000 == 0 and cancel():
                raise LoadCancelled(f"load cancelled: {file_path.name}")
```

（`data_start = row_idx` はヘッダ/単位行を消費した後、最初のデータ行の
index。csv_loader.py:114 で定義済み。）

- [x] **Step 6: Run tests / full suite / gates**

Run: `uv run pytest tests/test_session.py tests/test_loaders.py -v` → PASS。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 7: Commit**

```bash
git add src/valisync/core/ tests/test_session.py tests/test_loaders.py
git commit -m "feat(core): Session.load に協調的キャンセル（LoadCancelled・チャンネル/1000行境界チェック）"
```

---

## Task 2: core — `SourceInfo` / `Session.source_info`（FB-10 データ源）

**Files:**
- Modify: `src/valisync/core/session.py`
- Test: `tests/test_session.py`（追加）

**Interfaces:**
- Consumes: `SignalGroupManager.group(key) -> SignalGroup`（既存公開・signal_group_manager.py:53）。
- Produces: `SourceInfo(full_path: Path, size_bytes: int | None, t_min: float | None, t_max: float | None, n_channels: int, file_format: str)`（frozen dataclass）。`Session.source_info(key) -> SourceInfo`（KeyError if unknown）。

- [x] **Step 1: Write the failing tests**

`tests/test_session.py` に追加:

```python
from valisync.core.session import SourceInfo


def test_source_info_fields(tmp_path):
    csv = _write_csv(tmp_path)
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    info = session.source_info(key)
    assert isinstance(info, SourceInfo)
    assert info.full_path == csv.resolve()
    assert info.size_bytes == csv.stat().st_size
    assert info.n_channels >= 1
    assert info.file_format == "CSV"
    assert info.t_min is not None and info.t_max is not None
    assert info.t_min <= info.t_max


def test_source_info_size_none_when_file_gone(tmp_path):
    csv = _write_csv(tmp_path)
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    csv.unlink()
    info = session.source_info(key)
    assert info.size_bytes is None          # graceful degradation（spec §6）
    assert info.n_channels >= 1             # メモリ上の情報は生きている


def test_source_info_unknown_key_raises():
    with pytest.raises(KeyError):
        Session().source_info("nope_1")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session.py -k source_info -v`
Expected: FAIL（`SourceInfo` 未定義）。

- [x] **Step 3: Implement — session.py**

`LoadOutcome` の近くに追加:

```python
@dataclass(frozen=True)
class SourceInfo:
    """Read-only metadata of a loaded file for GUI surfaces (FB-10 tooltip).

    ``size_bytes`` is None when the file no longer exists on disk;
    ``t_min``/``t_max`` are None for 0-channel groups.
    """

    full_path: Path
    size_bytes: int | None
    t_min: float | None
    t_max: float | None
    n_channels: int
    file_format: str
```

`Session` にメソッド追加:

```python
    def source_info(self, key: str) -> SourceInfo:
        """Return read-only metadata for the group under *key* (KeyError if unknown)."""
        group = self._groups.group(key)
        try:
            size: int | None = group.source_path.stat().st_size
        except OSError:
            size = None  # moved/deleted after load — show what we still know
        t_mins = [s.timestamps[0] for s in group.signals if len(s.timestamps)]
        t_maxs = [s.timestamps[-1] for s in group.signals if len(s.timestamps)]
        return SourceInfo(
            full_path=group.source_path,
            size_bytes=size,
            t_min=min(t_mins) if t_mins else None,
            t_max=max(t_maxs) if t_maxs else None,
            n_channels=len(group.signals),
            file_format=group.file_format,
        )
```

- [x] **Step 4: Run tests / gates**

Run: `uv run pytest tests/test_session.py -k source_info -v` → PASS。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 5: Commit**

```bash
git add src/valisync/core/session.py tests/test_session.py
git commit -m "feat(core): Session.source_info（FB-10 ツールチップ用の読み取り専用メタデータ）"
```

---

## Task 3: `BusyOverlay` — ラベル・キャンセルボタン・`cancel_requested`

**Files:**
- Modify: `src/valisync/gui/views/busy_overlay.py`
- Test: `tests/gui/test_load_worker.py`（`TestBusyOverlay` に追加）

**Interfaces:**
- Produces: `BusyOverlay.cancel_requested = Signal()`（キャンセルボタン clicked で emit）。`BusyOverlay.set_message(text: str) -> None` / `BusyOverlay.message() -> str`（テスト向け）。既存 `show()`/`hide()`/`cover()`/`is_indeterminate()` は不変。

- [x] **Step 1: Write the failing tests**

`tests/gui/test_load_worker.py` の `TestBusyOverlay` に追加:

```python
    def test_set_message_reflected_in_label(self, qtbot: QtBot) -> None:
        from valisync.gui.views.busy_overlay import BusyOverlay

        overlay = BusyOverlay()
        qtbot.addWidget(overlay)
        overlay.set_message("読み込み中: a.mf4")
        assert overlay.message() == "読み込み中: a.mf4"

    def test_cancel_button_click_emits_cancel_requested(self, qtbot: QtBot) -> None:
        from PySide6.QtCore import Qt
        from valisync.gui.views.busy_overlay import BusyOverlay

        overlay = BusyOverlay()
        qtbot.addWidget(overlay)
        overlay.show()
        with qtbot.waitSignal(overlay.cancel_requested, timeout=2000):
            qtbot.mouseClick(overlay.cancel_button, Qt.MouseButton.LeftButton)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gui/test_load_worker.py::TestBusyOverlay -v`
Expected: FAIL（`set_message`/`cancel_requested` 未定義）。

- [x] **Step 3: Implement — busy_overlay.py**

```python
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget


class BusyOverlay(QWidget):
    """Indeterminate busy overlay with a message label and a cancel button."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel("読み込み中…", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QProgressBar(self)
        # range (0, 0) makes the bar indeterminate (no percentage).
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)

        self.cancel_button = QPushButton("キャンセル", self)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self.hide()

    def set_message(self, text: str) -> None:
        """Show *text* as the load description (FB-04 label)."""
        self._label.setText(text)

    def message(self) -> str:
        """Current label text (test-facing)."""
        return self._label.text()
```

`is_indeterminate()`/`cover()`/`show()` は既存のまま残す。

- [x] **Step 4: Run tests / gates**

Run: `uv run pytest tests/gui/test_load_worker.py -v` → PASS（既存含む）。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 5: Commit**

```bash
git add src/valisync/gui/views/busy_overlay.py tests/gui/test_load_worker.py
git commit -m "feat(gui): BusyOverlay にラベルとキャンセルボタン（FB-04 表面）"
```

---

## Task 4: `LoadController` — 世代管理・カウント表示・cancelled 経路（＋`LoadTask.cancel`）

**Files:**
- Modify: `src/valisync/gui/workers/load_worker.py`
- Modify: `src/valisync/gui/viewmodels/load_task.py`
- Test: `tests/gui/test_load_worker.py`（`TestLoadController` に追加）

**Interfaces:**
- Consumes: `LoadCancelled`（Task 1）・`BusyOverlay.set_message`（Task 3）。
- Produces:
  - `LoadTask.cancel() -> None`（state を `"cancelled"` にし `"cancelled"` を notify）。
  - `LoadController.submit(load_callable, *, task=None, busy=None, on_success=None, on_error=None, cancel_event: threading.Event | None = None, label: str | None = None, on_cancelled: Callable[[], None] | None = None, on_discard: Callable[[LoadOutcome], None] | None = None)`。
  - `LoadController.cancel_active() -> None` — 全アクティブの `cancel_event` をセットし、即時に busy を隠し、以降の finished/failed を破棄（遅延 finished は `on_discard(outcome)` で巻き戻しに回す）。
  - busy はアクティブ数カウントで管理: 1件なら `label`、複数なら「N ファイルを読み込み中」、0 で hide。

- [x] **Step 1: Write the failing tests**

`tests/gui/test_load_worker.py` の `TestLoadController` に追加（`_csv` は既存ヘルパ）:

```python
    def test_cancel_active_hides_busy_immediately_and_discards_result(
        self, qtbot: QtBot
    ) -> None:
        import threading
        from valisync.gui.views.busy_overlay import BusyOverlay
        from valisync.gui.workers.load_worker import LoadController

        release = threading.Event()
        cancel_event = threading.Event()
        results: list[object] = []
        discards: list[object] = []

        def slow_ok() -> str:
            release.wait(timeout=3.0)  # cancel 後に「手遅れ完走」する
            return "late_result"

        busy = BusyOverlay()
        qtbot.addWidget(busy)
        controller = LoadController()
        controller.submit(
            slow_ok, busy=busy, cancel_event=cancel_event, label="a.mf4",
            on_success=results.append, on_discard=discards.append,
        )
        assert not busy.isHidden()

        controller.cancel_active()
        assert cancel_event.is_set()      # ハード側へ中断要求
        assert busy.isHidden()            # ソフト側は即時解放

        release.set()                     # worker は完走するが…
        qtbot.waitUntil(lambda: len(discards) == 1, timeout=3000)
        assert results == []              # on_success は呼ばれない
        assert discards == ["late_result"]

    def test_load_cancelled_routes_to_on_cancelled_not_on_error(
        self, qtbot: QtBot
    ) -> None:
        from valisync.core.session import LoadCancelled
        from valisync.gui.viewmodels.load_task import LoadTask
        from valisync.gui.workers.load_worker import LoadController

        def boom() -> str:
            raise LoadCancelled("cancelled")

        task = LoadTask()
        errors: list[object] = []
        cancelled: list[bool] = []
        controller = LoadController()
        controller.submit(
            boom, task=task,
            on_error=errors.append, on_cancelled=lambda: cancelled.append(True),
        )
        qtbot.waitUntil(lambda: task.state == "cancelled", timeout=3000)
        assert cancelled == [True]
        assert errors == []               # エラー扱いしない（spec §4.1）

    def test_busy_stays_visible_until_all_loads_finish(self, qtbot: QtBot) -> None:
        import threading
        from valisync.gui.views.busy_overlay import BusyOverlay
        from valisync.gui.workers.load_worker import LoadController

        rel1, rel2 = threading.Event(), threading.Event()
        busy = BusyOverlay()
        qtbot.addWidget(busy)
        controller = LoadController()
        controller.submit(lambda: rel1.wait(3.0) or "k1", busy=busy, label="a.mf4")
        controller.submit(lambda: rel2.wait(3.0) or "k2", busy=busy, label="b.mf4")
        assert "2 ファイル" in busy.message()   # 複数ロード表示

        rel1.set()
        qtbot.waitUntil(lambda: "b.mf4" in busy.message(), timeout=3000)
        assert not busy.isHidden()              # 片方完了ではまだ隠さない

        rel2.set()
        qtbot.waitUntil(lambda: busy.isHidden(), timeout=3000)
```

> 既存 `test_busy_shown_during_load` はカウント方式でもそのまま緑（1件表示→完了で hide）。

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gui/test_load_worker.py::TestLoadController -v`
Expected: FAIL（`cancel_event`/`label`/`on_cancelled`/`on_discard` 未対応・`LoadTask.cancel` 未定義）。

- [x] **Step 3: Implement — load_task.py**

docstring の State machine を更新し、メソッド追加:

```python
    def cancel(self) -> None:
        """Enter the cancelled state and notify (user-initiated, not an error)."""
        self.state = "cancelled"
        self._notify("cancelled")
```

- [x] **Step 4: Implement — load_worker.py**

`import threading` を追加。`LoadController` を差し替え:

```python
class LoadController(QObject):
    """Drive off-thread loads and update GUI state on completion.

    Busy visibility is count-based: the overlay stays up until every active
    load finishes (multiple drops share one overlay). ``cancel_active`` sets
    each load's cancel_event (cooperative hard-cancel) and releases the UI
    immediately (soft-cancel); late results from already-cancelled workers
    are routed to ``on_discard`` so the caller can roll back registration.
    """

    def __init__(
        self,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pool = thread_pool or QThreadPool.globalInstance()
        # worker → (cancel_event, label, busy, on_discard)
        self._active: dict[LoadWorker, tuple[
            threading.Event | None, str | None,
            BusyOverlay | None, Callable[[LoadOutcome], None] | None,
        ]] = {}
        self._cancelled: set[LoadWorker] = set()

    def submit(
        self,
        load_callable: Callable[[], LoadOutcome],
        *,
        task: LoadTask | None = None,
        busy: BusyOverlay | None = None,
        on_success: Callable[[LoadOutcome], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        cancel_event: threading.Event | None = None,
        label: str | None = None,
        on_cancelled: Callable[[], None] | None = None,
        on_discard: Callable[[LoadOutcome], None] | None = None,
    ) -> None:
        """Begin loading: flag task, then run *load_callable* off-thread."""
        if task is not None:
            task.begin()

        worker = LoadWorker(load_callable)
        self._active[worker] = (cancel_event, label, busy, on_discard)
        worker.signals.finished.connect(
            lambda outcome: self._finish(worker, outcome, task, on_success)
        )
        worker.signals.failed.connect(
            lambda exc: self._fail(worker, exc, task, on_error, on_cancelled)
        )
        self._refresh_busy(busy)
        self._pool.start(worker)

    def cancel_active(self) -> None:
        """Cancel every active load: hard (events) + soft (immediate UI release)."""
        busies = set()
        for worker, (event, _label, busy, _discard) in self._active.items():
            if event is not None:
                event.set()
            self._cancelled.add(worker)
            if busy is not None:
                busies.add(busy)
        for busy in busies:
            busy.hide()

    def _pop(self, worker: LoadWorker) -> tuple[
        threading.Event | None, str | None,
        BusyOverlay | None, Callable[[LoadOutcome], None] | None,
    ]:
        info = self._active.pop(worker)
        was_cancelled = worker in self._cancelled
        self._cancelled.discard(worker)
        if not was_cancelled:
            self._refresh_busy(info[2])
        return info if not was_cancelled else (info[0], info[1], None, info[3])

    def _refresh_busy(self, busy: BusyOverlay | None) -> None:
        """Count-based visibility: label for 1, count for N, hide at 0."""
        if busy is None:
            return
        labels = [
            label for w, (_e, label, b, _d) in self._active.items()
            if b is busy and w not in self._cancelled
        ]
        if not labels:
            busy.hide()
            return
        if len(labels) == 1:
            busy.set_message(f"読み込み中: {labels[0] or 'ファイル'}")
        else:
            busy.set_message(f"{len(labels)} ファイルを読み込み中")
        busy.show()

    def _finish(
        self,
        worker: LoadWorker,
        outcome: LoadOutcome,
        task: LoadTask | None,
        on_success: Callable[[LoadOutcome], None] | None,
    ) -> None:
        was_cancelled = worker in self._cancelled
        _event, _label, _busy, on_discard = self._pop(worker)
        if was_cancelled:
            # 手遅れ完走: 呼び出し側に登録の巻き戻しを委ねる（spec §5）
            if on_discard is not None:
                on_discard(outcome)
            return
        if task is not None:
            task.succeed(outcome.key)
        if on_success is not None:
            on_success(outcome)

    def _fail(
        self,
        worker: LoadWorker,
        exc: Exception,
        task: LoadTask | None,
        on_error: Callable[[Exception], None] | None,
        on_cancelled: Callable[[], None] | None,
    ) -> None:
        was_cancelled = worker in self._cancelled
        self._pop(worker)
        if isinstance(exc, LoadCancelled) or was_cancelled:
            # ユーザー起点の正常系 — エラー面へ流さない（spec §4.1/§6）
            if task is not None:
                task.cancel()
            if on_cancelled is not None:
                on_cancelled()
            return
        if task is not None:
            task.fail(str(exc))
        if on_error is not None:
            on_error(exc)
```

import 追加: `from valisync.core.session import LoadCancelled, LoadOutcome`（`LoadOutcome` は TYPE_CHECKING に既在なら実 import へ昇格）。`submit` の busy 前 show（旧 `busy.show()`）は `_refresh_busy` に置換されるため削除。

- [x] **Step 5: Run tests / gates**

Run: `uv run pytest tests/gui/test_load_worker.py -v` → PASS（既存＋新規）。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 6: Commit**

```bash
git add src/valisync/gui/workers/load_worker.py src/valisync/gui/viewmodels/load_task.py tests/gui/test_load_worker.py
git commit -m "feat(gui): LoadController に世代管理・カウント表示・cancelled 経路（FB-04）"
```

---

## Task 5: MainWindow — FB-04 配線（Event 生成・キャンセル・status）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_main_window.py`（追加）

**Interfaces:**
- Consumes: Task 3/4 の `cancel_requested`/`submit(..., cancel_event, label, on_cancelled, on_discard)`・`Session.remove_group(key, force=True)`（既存）。
- Produces: `MainWindow._on_load_cancelled(path: Path)`（status 更新）。`busy_overlay.cancel_requested → _load_controller.cancel_active()` 配線。

- [x] **Step 1: Write the failing tests**

`tests/gui/test_main_window.py` に追加:

```python
def test_cancel_requested_wired_to_controller(qtbot, monkeypatch):
    window = _make_window(qtbot)
    calls = []
    monkeypatch.setattr(
        window._load_controller, "cancel_active", lambda: calls.append(True)
    )
    window.busy_overlay.cancel_requested.emit()
    assert calls == [True]


def test_on_load_cancelled_updates_status_without_dialog(qtbot, monkeypatch):
    import valisync.gui.views.main_window as mw

    window = _make_window(qtbot)
    dialogs = []
    monkeypatch.setattr(
        mw.QMessageBox, "critical", lambda *a, **k: dialogs.append(a)
    )
    window._on_load_cancelled(Path("big.mf4"))
    assert "キャンセル" in window.statusBar().currentMessage()
    assert "big.mf4" in window.statusBar().currentMessage()
    assert dialogs == []                     # モーダル無し（spec §6）
    assert window.diagnostics_vm.counts() == (0, 0)  # 診断追記無し
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gui/test_main_window.py -k "cancel" -v`
Expected: FAIL（配線/メソッド未実装）。

- [x] **Step 3: Implement — main_window.py**

`import threading` を追加。`__init__` の busy_overlay 構築後に配線:

```python
        self.busy_overlay.cancel_requested.connect(self._load_controller.cancel_active)
```

`_load_file` を差し替え:

```python
    def _load_file(self, path: str | Path) -> None:
        """Load *path* off-thread (MDF4; CSV needs a format picker, deferred)."""
        session = self.app_vm.session
        target = Path(path)
        cancel_event = threading.Event()  # 所有=ここ・セット権=controller（spec §4.1）
        self._load_controller.submit(
            lambda: session.load(target, None, cancel=cancel_event.is_set),
            busy=self.busy_overlay,
            cancel_event=cancel_event,
            label=target.name,
            on_success=self._on_loaded,
            on_error=lambda err: self._on_load_error(target, err),
            on_cancelled=lambda: self._on_load_cancelled(target),
            on_discard=lambda outcome: session.remove_group(outcome.key, force=True),
        )
```

ヘルパ追加:

```python
    def _on_load_cancelled(self, path: Path) -> None:
        # ユーザー起点の正常系: status のみ（モーダル/診断は出さない・spec §6）
        self.statusBar().showMessage(f"キャンセルしました: {path.name}")
```

- [x] **Step 4: Run tests / gates**

Run: `uv run pytest tests/gui/test_main_window.py -v` → PASS。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 5: Commit**

```bash
git add src/valisync/gui/views/main_window.py tests/gui/test_main_window.py
git commit -m "feat(gui): MainWindow にキャンセル配線＋cancelled ステータス（FB-04 完結）"
```

---

## Task 6: `ChannelBrowserVM` — `header_text` / `empty_state` / `filter_query`

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`
- Test: `tests/gui/test_channel_browser_vm.py`（無ければ新規作成・既存なら追加）

**Interfaces:**
- Produces: `header_text() -> str`（「<basename> — 全 M ch 中 N 件表示」／0ch は「<basename> — 0 ch」／未選択は「ファイル未選択」）。`empty_state() -> str`（`"none_selected" | "no_channels" | "no_match" | "has_rows"`）。`filter_query() -> str`。いずれも純 Python・既存の `"signals"`/`"filter"` 通知で View が再取得する（新規通知タグなし）。

- [x] **Step 1: Write the failing tests**

`tests/gui/test_channel_browser_vm.py`（新規の場合は次の内容で作成。`AppViewModel`/CSV ヘルパは `tests/gui/test_load_worker.py` の `_csv` パターンを再利用）:

```python
from __future__ import annotations

from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM


def _loaded_vm(tmp_path: Path) -> tuple[AppViewModel, ChannelBrowserVM, str]:
    fmt = FormatDefinition(
        name="fmt", delimiter=Delimiter.COMMA, timestamp_column=0,
        timestamp_unit="sec", signal_start_column=1, signal_end_column=2,
        has_header=True,
    )
    path = tmp_path / "d.csv"
    path.write_text("t,speed,brake\n0.0,1.0,0.0\n1.0,2.0,1.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, fmt)
    return app_vm, ChannelBrowserVM(app_vm), key


def test_header_none_selected(tmp_path):
    app_vm, vm, _key = _loaded_vm(tmp_path)
    app_vm.set_active_file(None)
    assert vm.header_text() == "ファイル未選択"
    assert vm.empty_state() == "none_selected"


def test_header_counts_and_has_rows(tmp_path):
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    assert vm.header_text() == "d.csv — 2 ch 中 2 件表示"
    assert vm.empty_state() == "has_rows"


def test_no_match_state_and_query(tmp_path):
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    vm.set_filter("xyz123")
    assert vm.empty_state() == "no_match"
    assert vm.filter_query() == "xyz123"
    assert vm.header_text() == "d.csv — 2 ch 中 0 件表示"


def test_no_channels_state(tmp_path, monkeypatch):
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    # 0ch グループは現行ローダーでは作れないため session 面で再現（spec §4.2）
    monkeypatch.setattr(app_vm.session, "group_signals", lambda _key: [])
    assert vm.empty_state() == "no_channels"
    assert vm.header_text() == "d.csv — 0 ch"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py -v`
Expected: FAIL（メソッド未定義）。

- [x] **Step 3: Implement — channel_browser_vm.py**

`signals` プロパティの後に追加:

```python
    # ─── Header / empty-state (FB-05/09) ────────────────────────────────────

    def _group_total(self) -> tuple[str, int] | None:
        """Return (basename, total channel count) for the active file, or None."""
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        try:
            total = len(self._app_vm.session.group_signals(active_key))
            name = self._app_vm.session.source_name(active_key)
        except KeyError:
            return None
        return name, total

    def header_text(self) -> str:
        """One-line context header: which file, how many shown of how many."""
        info = self._group_total()
        if info is None:
            return "ファイル未選択"
        name, total = info
        if total == 0:
            return f"{name} — 0 ch"
        return f"{name} — {total} ch 中 {len(self.signals)} 件表示"

    def empty_state(self) -> str:
        """Why the list is empty: none_selected / no_channels / no_match / has_rows."""
        info = self._group_total()
        if info is None:
            return "none_selected"
        if info[1] == 0:
            return "no_channels"
        if not self.signals:
            return "no_match"
        return "has_rows"

    def filter_query(self) -> str:
        """Current filter text (for the no_match placeholder message)."""
        return self._filter_text
```

- [x] **Step 4: Run tests / gates**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py -v` → PASS。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 5: Commit**

```bash
git add src/valisync/gui/viewmodels/channel_browser_vm.py tests/gui/test_channel_browser_vm.py
git commit -m "feat(gui): ChannelBrowserVM に header_text/empty_state/filter_query（FB-05/09）"
```

---

## Task 7: `ChannelBrowserView` — ヘッダ QLabel＋QStackedWidget プレースホルダ

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`
- Test: `tests/gui/test_channel_browser_view.py`（追加）

**Interfaces:**
- Consumes: Task 6 の `header_text`/`empty_state`/`filter_query`。
- Produces: `view.header_label: QLabel`・`view.placeholder_label: QLabel`・`view.is_showing_placeholder() -> bool`（テスト向け）。既存 `search_box`/`tree`/D&D/メニュー経路は不変。

- [x] **Step 1: Write the failing tests**

`tests/gui/test_channel_browser_view.py` に追加（`_make_view` 相当の既存 fixture/ヘルパがあれば再利用・無ければ Task 6 の `_loaded_vm` パターンで組む）:

```python
def test_header_label_shows_active_file_and_counts(qtbot, tmp_path):
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = ChannelBrowserView(vm)
    qtbot.addWidget(view)
    assert "d.csv" in view.header_label.text()
    assert "2 ch 中 2 件表示" in view.header_label.text()


def test_placeholder_when_none_selected(qtbot, tmp_path):
    app_vm, vm, _key = _loaded_vm(tmp_path)
    app_vm.set_active_file(None)
    view = ChannelBrowserView(vm)
    qtbot.addWidget(view)
    assert view.is_showing_placeholder()
    assert "ファイルを選択" in view.placeholder_label.text()


def test_placeholder_no_match_includes_query_and_recovers(qtbot, tmp_path):
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    view = ChannelBrowserView(vm)
    qtbot.addWidget(view)
    view.search_box.setText("xyz123")          # 実経路: textChanged → set_filter
    assert view.is_showing_placeholder()
    assert "xyz123" in view.placeholder_label.text()
    view.search_box.setText("")
    assert not view.is_showing_placeholder()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -k "header or placeholder" -v`
Expected: FAIL（属性未定義）。

- [x] **Step 3: Implement — channel_browser_view.py**

モジュールレベルにメッセージ表を定義（no_match は format 引数）:

```python
_EMPTY_MESSAGES = {
    "none_selected": "File Browser でファイルを選択すると\n信号一覧を表示します",
    "no_match": "「{query}」に一致する信号はありません",
    "no_channels": "このファイルに信号がありません\n（Diagnostics に詳細）",
}
```

`__init__` を変更 — 検索ボックスの上にヘッダ、ツリーを QStackedWidget に格納:

```python
        self.header_label = QLabel(self)
        self.placeholder_label = QLabel(self)
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setWordWrap(True)
        # QLabel は既定で plain text — クエリ文字列を HTML 解釈させない（spec §6）
        self.placeholder_label.setTextFormat(Qt.TextFormat.PlainText)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.tree)              # index 0
        self._stack.addWidget(self.placeholder_label)  # index 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header_label)
        layout.addWidget(self.search_box)
        layout.addWidget(self._stack)
```

（既存の `layout.addWidget(self.tree)` は削除。import に `QLabel, QStackedWidget` を追加。）

`_on_vm_change` と textChanged の後段で状態反映（既存 wiring はそのまま・追加のみ）:

```python
        self.search_box.textChanged.connect(lambda _t: self._refresh_state())
```

```python
    def is_showing_placeholder(self) -> bool:
        """True when the placeholder (not the tree) is visible (test-facing)."""
        return self._stack.currentWidget() is self.placeholder_label

    def _refresh_state(self) -> None:
        """Sync header + tree/placeholder switch with the VM (FB-05/08/09)."""
        self.header_label.setText(self._vm.header_text())
        state = self._vm.empty_state()
        if state == "has_rows":
            self._stack.setCurrentWidget(self.tree)
            return
        message = _EMPTY_MESSAGES[state]
        if state == "no_match":
            message = message.format(query=self._vm.filter_query())
        self.placeholder_label.setText(message)
        self._stack.setCurrentWidget(self.placeholder_label)

    def _on_vm_change(self, change: str) -> None:
        """Handle notifications from ChannelBrowserVM."""
        if change in ("signals", "filter"):
            self._refresh_state()
```

`__init__` 末尾（購読設定後）に初期状態反映 `self._refresh_state()` を追加。

- [x] **Step 4: Run tests / 全 suite / gates**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -v` → PASS（既存の検索/D&D/メニューテスト含め無回帰）。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 5: Commit**

```bash
git add src/valisync/gui/views/channel_browser_view.py tests/gui/test_channel_browser_view.py
git commit -m "feat(gui): ChannelBrowser にヘッダ行＋空状態3分類プレースホルダ（FB-05/08/09）"
```

---

## Task 8: `FileBrowserView` — 空プレースホルダ（FB-08）

**Files:**
- Modify: `src/valisync/gui/views/file_browser_view.py`
- Test: `tests/gui/test_file_browser_view.py`（追加）

**Interfaces:**
- Consumes: `FileBrowserVM.files`・`"files"` 通知。
- Produces: `view.placeholder_label: QLabel`・`view.is_showing_placeholder() -> bool`。既存 `list_view`/右クリック経路は不変。

- [x] **Step 1: Write the failing tests**

`tests/gui/test_file_browser_view.py` に追加（既存の view 生成ヘルパを再利用）:

```python
def test_placeholder_shown_when_no_files(qtbot):
    app_vm = AppViewModel()
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)
    assert view.is_showing_placeholder()
    assert "読み込まれていません" in view.placeholder_label.text()


def test_placeholder_hidden_after_load(qtbot, tmp_path):
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    _load_csv(app_vm, tmp_path)   # 既存ヘルパ（無ければ request_load ベースで作る）
    assert not view.is_showing_placeholder()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gui/test_file_browser_view.py -k placeholder -v`
Expected: FAIL。

- [x] **Step 3: Implement — file_browser_view.py**

```python
        self.placeholder_label = QLabel(
            "ファイルが読み込まれていません\n\nウィンドウへファイルをドロップして追加", self
        )
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setWordWrap(True)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.list_view)          # index 0
        self._stack.addWidget(self.placeholder_label)  # index 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        unsubscribe = self._vm.subscribe(self._on_vm_change)
        self.destroyed.connect(lambda *_: unsubscribe())
        self._refresh_state()
```

```python
    def is_showing_placeholder(self) -> bool:
        """True when the placeholder (not the list) is visible (test-facing)."""
        return self._stack.currentWidget() is self.placeholder_label

    def _on_vm_change(self, change: str) -> None:
        if change == "files":
            self._refresh_state()

    def _refresh_state(self) -> None:
        if self._vm.files:
            self._stack.setCurrentWidget(self.list_view)
        else:
            self._stack.setCurrentWidget(self.placeholder_label)
```

import に `QLabel, QStackedWidget` を追加。既存の `layout.addWidget(self.list_view)` は `_stack` 経由に置換。

- [x] **Step 4: Run tests / gates**

Run: `uv run pytest tests/gui/test_file_browser_view.py -v` → PASS（既存の右クリック Layer B 含め無回帰）。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 5: Commit**

```bash
git add src/valisync/gui/views/file_browser_view.py tests/gui/test_file_browser_view.py
git commit -m "feat(gui): FileBrowser に空プレースホルダ（FB-08）"
```

---

## Task 9: FB-10 — `file_info`/`tooltip_text`＋`FileListModel` ToolTipRole

**Files:**
- Modify: `src/valisync/gui/viewmodels/file_browser_vm.py`
- Modify: `src/valisync/gui/adapters/qt_signal_models.py`
- Test: `tests/gui/test_file_browser_vm.py`（無ければ新規）・`tests/gui/test_file_browser_view.py`（model 経由の ToolTipRole）

**Interfaces:**
- Consumes: `Session.source_info(key) -> SourceInfo`（Task 2）。
- Produces: `FileBrowserVM.file_info(index) -> SourceInfo | None`・`FileBrowserVM.tooltip_text(index) -> str | None`。`FileListModel.data(index, Qt.ItemDataRole.ToolTipRole)` が `tooltip_text` を返す。

- [x] **Step 1: Write the failing tests**

`tests/gui/test_file_browser_vm.py`:

```python
def test_tooltip_text_four_lines(tmp_path):
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    path = _write_csv(tmp_path)              # 既存 CSV ヘルパパターン
    app_vm.request_load(path, _fmt())
    text = vm.tooltip_text(0)
    lines = text.splitlines()
    assert lines[0] == str(path.resolve())
    assert lines[1].startswith("サイズ: ")
    assert lines[2].startswith("時間範囲: ")
    assert "（" in lines[2] and lines[2].endswith("s）")
    assert lines[3].startswith("チャンネル: ") and "形式: CSV" in lines[3]


def test_tooltip_omits_size_when_file_gone(tmp_path):
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    path = _write_csv(tmp_path)
    app_vm.request_load(path, _fmt())
    path.unlink()
    text = vm.tooltip_text(0)
    assert "サイズ:" not in text              # graceful degradation（spec §6）
    assert "時間範囲:" in text


def test_tooltip_none_for_out_of_range():
    assert FileBrowserVM(AppViewModel()).tooltip_text(0) is None
```

`tests/gui/test_file_browser_view.py` に追加:

```python
def test_model_provides_tooltip_role(qtbot, tmp_path):
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    _load_csv(app_vm, tmp_path)
    index = view.model.index(0, 0)
    tip = view.model.data(index, Qt.ItemDataRole.ToolTipRole)
    assert tip and "チャンネル:" in tip
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gui/test_file_browser_vm.py tests/gui/test_file_browser_view.py -k tooltip -v`
Expected: FAIL。

- [x] **Step 3: Implement — file_browser_vm.py**

```python
    # ─── FB-10 tooltip ───────────────────────────────────────────────────────

    def file_info(self, index: int) -> SourceInfo | None:
        """SourceInfo for the file at *index*, or None when out of range/unknown."""
        keys = self._app_vm.loaded_file_keys
        if not (0 <= index < len(keys)):
            return None
        try:
            return self._app_vm.session.source_info(keys[index])
        except KeyError:
            return None

    def tooltip_text(self, index: int) -> str | None:
        """Multi-line hover text: path / size / time range / channels+format."""
        info = self.file_info(index)
        if info is None:
            return None
        lines = [str(info.full_path)]
        if info.size_bytes is not None:
            lines.append(f"サイズ: {_fmt_size(info.size_bytes)}")
        if info.t_min is not None and info.t_max is not None:
            duration = info.t_max - info.t_min
            lines.append(
                f"時間範囲: {info.t_min:.3f} – {info.t_max:.3f} s（{duration:.1f} s）"
            )
        else:
            lines.append("時間範囲: —")
        lines.append(f"チャンネル: {info.n_channels} ch ・ 形式: {info.file_format}")
        return "\n".join(lines)
```

モジュールレベルにヘルパ（純 Python）:

```python
def _fmt_size(size_bytes: int) -> str:
    """Human-readable size, one decimal (B/KB/MB/GB)."""
    value = float(size_bytes)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"
```

import: `from valisync.core.session import SourceInfo`（TYPE_CHECKING で可）。

- [x] **Step 4: Implement — qt_signal_models.py（FileListModel.data）**

```python
    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._vm.files)):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._vm.files[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._vm.tooltip_text(index.row())
        return None
```

- [x] **Step 5: Run tests / gates**

Run: `uv run pytest tests/gui/test_file_browser_vm.py tests/gui/test_file_browser_view.py -v` → PASS。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 6: Commit**

```bash
git add src/valisync/gui/viewmodels/file_browser_vm.py src/valisync/gui/adapters/qt_signal_models.py tests/gui/
git commit -m "feat(gui): File Browser ホバーツールチップ（FB-10・source_info 表示）"
```

---

## Task 10: FB-07 — ウィンドウタイトル

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_main_window.py`（追加）

**Interfaces:**
- Consumes: `app_vm.active_file_key`・`session.source_name`・`"active_file"`/`"loaded"`/`"unloaded"` 通知（既存 `_on_app_change` 購読）。
- Produces: タイトル「<basename> — ValiSync」（アクティブ無しは「ValiSync」）。

- [x] **Step 1: Write the failing tests**

`tests/gui/test_main_window.py` に追加:

```python
def test_window_title_tracks_active_file(qtbot, tmp_path):
    window = _make_window(qtbot)
    assert window.windowTitle() == "ValiSync"
    key = window.app_vm.request_load(_write_csv(tmp_path), _csv_format())
    window.app_vm.set_active_file(key)
    assert window.windowTitle().endswith(" — ValiSync")
    assert window.windowTitle().startswith("d.csv")   # _write_csv の basename
    window.app_vm.set_active_file(None)
    assert window.windowTitle() == "ValiSync"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_main_window.py -k window_title -v`
Expected: FAIL（タイトル固定のまま）。

- [x] **Step 3: Implement — main_window.py**

既存の `self.setWindowTitle("ValiSync")` を `self._update_window_title()` に置換し、ヘルパと購読分岐を追加:

```python
    def _update_window_title(self) -> None:
        """FB-07: show the active file so the title answers 'what am I looking at'."""
        key = self.app_vm.active_file_key
        if key is None:
            self.setWindowTitle("ValiSync")
            return
        try:
            name = self.app_vm.session.source_name(key)
        except KeyError:
            self.setWindowTitle("ValiSync")
            return
        self.setWindowTitle(f"{name} — ValiSync")
```

`_on_app_change` に分岐を追加:

```python
    def _on_app_change(self, change: str) -> None:
        if change == "loaded":
            self.channel_browser_vm.refresh()
        if change in ("active_file", "loaded", "unloaded"):
            self._update_window_title()
```

- [x] **Step 4: Run tests / gates**

Run: `uv run pytest tests/gui/test_main_window.py -v` → PASS。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [x] **Step 5: Commit**

```bash
git add src/valisync/gui/views/main_window.py tests/gui/test_main_window.py
git commit -m "feat(gui): ウィンドウタイトルにアクティブファイル名（FB-07）"
```

---

## Task 11: 入力経路ゲート — realgui キャンセルボタン＋`/gui-verify`

**目的:** 本弾唯一の新規入力経路（オーバーレイ上のキャンセルボタン）を実 OS 入力で検証し、①証拠ゲートを満たす。

**gui-test-plan 分析（プラン時実施済み・spec §7）:**
- 変更種別: 入力イベント→ハンドラ。Layer A/B は Task 3-5 で充足。
- Layer C 要: 半透明オーバーレイ上のボタンという新規ヒットテスト経路（D&D/move 特例には非該当だが新規経路の推奨レベル＋FB-04 はユーザー体験の要）。
- ②実質性: 実 OS クリック → `cancel_requested` 発火（`waitSignal`）＋オーバーレイ hidden ＝自動アサート可。スクショ保存＋assert メッセージにパス埋め込み。
- 掴み点監査: ゾーン幾何変更なし → 不要。

**Files:**
- Create: `tests/realgui/test_busy_cancel_realclick.py`

- [x] **Step 1: realgui テストを作成**

構成は `tests/realgui/test_click_activate_axis.py` の純クリック前例＋`test_axis_hover_frame.py` のウィンドウ配置作法（StaysOnTop・availableGeometry 内・`waitExposed`）に従う。`_realgui_input.at`/`skip_unless_real_display` を使用:

- 親 QWidget（400×300）上に `BusyOverlay` を構築し `set_message("読み込み中: a.mf4")`＋`show()`（`cover()` で親全面）。
- `cancel_button` の中心を `mapToGlobal * devicePixelRatioF()` で物理座標化（`test_file_browser_realclick.py:66-70` の作法）。
- 実 OS クリック（LDOWN/LUP・同一点・MOVE 無し）→ `qtbot.waitSignal(overlay.cancel_requested, timeout=3000)` で発火を assert。
- `grabWindow(0)` スクショを保存し assert メッセージにパスを埋め込む。

- [x] **Step 2: scoped 実行で動作確認（マウス数秒占有）**

Run: `uv run pytest --realgui tests/realgui/test_busy_cancel_realclick.py -v`
Expected: PASS（フレークする場合は processEvents 回数・待機を調整）。

- [x] **Step 3: `/gui-verify` で①証拠ゲート**

- [x] `uv run pytest --realgui tests/realgui/test_busy_cancel_realclick.py`（該当のみ scoped）pass ログ＋スクショ証拠を添付
- [x] headless full `uv run pytest` が 0 errors
- [x] 既存 realgui の回帰: 本弾は既存入力経路無変更だが、`channel_browser_view.py` を触るため `uv run pytest --realgui tests/realgui/test_channel_browser_realclick.py` と信号 D&D `test_signal_dnd_realclick.py` を回帰実行
- [ ] CI 緑（push 後確認）— 未 push のため未確認

- [x] **Step 4: Commit**

```bash
git add tests/realgui/test_busy_cancel_realclick.py
git commit -m "test(realgui): キャンセルボタンの実 OS クリック検証（FB-04 ①ゲート）"
```

---

## Self-Review

**1. Spec coverage（spec §8 の対応表）**
- FB-04 → Task 1（core cancel）＋Task 3（overlay）＋Task 4（controller）＋Task 5（配線）＋Task 11（realgui）✓
- FB-05 → Task 6（VM 件数/状態）＋Task 7（View ヘッダ/プレースホルダ）✓
- FB-07 → Task 10 ✓
- FB-08 → Task 7（none_selected）＋Task 8（FileBrowser）✓
- FB-09 → Task 6/7 のヘッダ（ファイル名）✓
- FB-10 → Task 2（source_info）＋Task 9（tooltip）✓
- spec §6 エッジケース → 遅延シグナル破棄/巻き戻し（T4）・cancelled 非エラー（T4/T5）・stat 失敗（T2/T9）・0ch（T6）・クエリ PlainText（T7）✓

**2. Placeholder scan:** 全 Step 実コード。「着手時に実名を確認」は Task 1 の mdf4 ヘルパ名（tests/mdf4_helpers.py 実在・名前のみ要確認）と Task 8 の `_load_csv`（無ければ request_load ベースで作ると明記）の2点で、いずれも解決手順を併記済み。

**3. Type consistency:** `LoadCancelled` は load_result.py 定義・session.py re-export（loaders の循環回避）で全タスク一貫。`submit(..., cancel_event, label, on_cancelled, on_discard)` は T4 定義＝T5 使用が一致。`SourceInfo` フィールドは T2 定義＝T9 使用が一致。`header_text`/`empty_state`/`filter_query` は T6 定義＝T7 使用が一致。`is_showing_placeholder`/`placeholder_label` は T7/T8 で同名（意図的な対称）。
