# FU-16 remove_group 遅延分割解放 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** prod（330k ch・~10 GB）のクローズで UI が ~6 秒フリーズする真因＝`Session.remove_group` の同期 refcount dealloc を、GUI スレッドの byte-budget 分割解放（graveyard＋`QTimer(0)`）へ逃がし、対象ファイル行にスピナーを出して背景解放を可視化する。

**Architecture:** core は「削除グループを捨てず `RemovalResult.removed_group` で手渡す」だけ（Qt 非依存）。GUI 層の `TeardownService`（`QObject`）が graveyard に保持し、tick あたりバイト予算まで参照を落として分割解放する。`AppViewModel.unload_file` は即 return（論理クローズは同期）、解放完了で File Browser の releasing 行を消す。

**Tech Stack:** Python 3 / PySide6 / pyqtgraph / numpy / pytest / uv。

## Global Constraints

- **core（`session.py` / `AppViewModel`）は Qt を import しない**。`TeardownService`（Qt）は duck-typed に注入（`enqueue(key, group)` を持つオブジェクト）。未注入時は `removed_group` がスコープ終了で**即時同期解放**＝現行挙動を保存（ヘッドレス/テスト互換）。
- **byte-budget 既定 = 64 MiB**（`sig.timestamps.nbytes + sig.values.nbytes` を積算・超過で次 tick）。1 tick は「予算＋最大1配列」を超えない（巨大配列 1 本は単独 tick）。
- **perf E2E は prod スケール必須＋実ロード経路**: 実 `MainWindow._load_file`（オフスレッド）＋`ExpansionConfirmer` 全展開 → **`len(session.signals()) == 330_004` を検証**してから計測（内部 `request_load`・小データ・confirmer 未 patch は無効＝[[gui_perf_e2e_repro_must_drive_real_load_path]]）。合格閾値: **同期 close < 200 ms／drain 中 heartbeat 最大 gap < 150 ms**。honest-RED=現行同期 remove_group ~7 s 単発 gap。
- **スコープ**: close 経路のみ。FU-03／FU-18／`gc.freeze()`／worker thread は不採用。
- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- prod デモデータ: `uv run python scripts/generate_demo_mf4.py --profile prod`（≈1.36 GB・`demo_data/prod_demo.mf4`・gitignore）。perf は `VALISYNC_PROD_MF4` env で場所指定・CI 除外。

---

### Task 1: `RemovalResult.removed_group`（core：グループ手渡し）

**Files:**
- Modify: `src/valisync/core/session.py`（`RemovalResult`＝`:75-84`・`remove_group`＝`:260-276`）
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `SignalGroupManager.remove(key) -> SignalGroup`（既存・pop したグループを返す）
- Produces: `RemovalResult(removed, dependent_signals, removed_group)` — `removed_group` は removed=True 時に pop グループ、依存拒否時 None。Task 4 が `result.removed_group` を消費。

- [ ] **Step 1: Write the failing test**

`tests/test_session.py` に追加（既存の `_write_min_csv`/`_csv_format`/`Session.load` ヘルパを流用。無ければ近接テストの最小 CSV/format 生成を流用）:

```python
import weakref


def test_remove_group_hands_off_group_and_defers_dealloc(tmp_path: Path) -> None:
    """remove_group returns the popped SignalGroup so the caller can defer its
    (potentially huge) dealloc off the calling thread. While the caller holds
    the returned group, core does NOT free it (FU-16)."""
    session = Session()
    key = session.load(_write_min_csv(tmp_path / "a.csv"), _csv_format()).key
    result = session.remove_group(key)
    assert result.removed is True
    assert result.removed_group is not None
    ref = weakref.ref(result.removed_group)
    # Caller holds it -> alive (core did not synchronously dealloc it).
    assert ref() is not None
    # Dropping the only strong ref frees it (proves it was the caller's to free).
    del result
    import gc

    gc.collect()
    assert ref() is None


def test_remove_group_refused_has_no_removed_group() -> None:
    """When removal is refused (dependent Derived_Signal, not forced),
    removed_group is None."""
    # 既存の依存拒否テストがあれば同じ setup を流用。無ければ _DerivedRecord を
    # 仕込んだ session で remove_group(force=False) を呼び removed=False を作る。
    ...  # 既存の "remove refused" テスト setup を再利用して removed_group is None を追加 assert
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session.py::test_remove_group_hands_off_group_and_defers_dealloc -v`
Expected: FAIL — `AttributeError: 'RemovalResult' object has no attribute 'removed_group'`

- [ ] **Step 3: Write minimal implementation**

`RemovalResult` にフィールド追加（`:75-84`）:

```python
@dataclass(frozen=True)
class RemovalResult:
    """Outcome of a remove_group request (Req 4.5).

    ``removed`` is False when dependent Derived_Signals exist and removal was not
    forced; ``dependent_signals`` then names the blocking Derived_Signals.
    ``removed_group`` carries the popped Signal_Group on success so the GUI can
    defer its dealloc off the UI thread (FU-16); None when removal was refused.
    """

    removed: bool
    dependent_signals: tuple[str, ...] = ()
    removed_group: SignalGroup | None = None
```

`remove_group`（`:260-276`）で捕捉して載せる:

```python
        group = self._groups.remove(key)   # capture instead of discarding
        return RemovalResult(
            removed=True, dependent_signals=dependents, removed_group=group
        )
```

`SignalGroup` の import が無ければ session.py 先頭の core.models import に追加。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_session.py -k "remove_group" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/valisync/core/session.py tests/test_session.py
git commit -m "feat(fu16): RemovalResult.removed_group — 削除グループを手渡し（遅延解放の土台）"
```

---

### Task 2: perf E2E ハーネス＋honest-RED ベースライン（prod・実ロード経路）

**Files:**
- Create: `scripts/fu16_teardown_bench.py`
- （前提）`demo_data/prod_demo.mf4` 生成済み（`VALISYNC_PROD_MF4` で場所指定可）

**Interfaces:**
- Consumes: `MainWindow`（実 `_load_file`）・`ExpansionConfirmer`（全展開 patch）・`file_browser_view._confirm_and_unload` または `app_vm.unload_file`・`QTimer` heartbeat
- Produces: 標準出力に `reached_channels`／`sync_close_ms`／`drain_max_gap_ms`／`drain_total_ms`。honest-RED（現行同期 remove_group）で `sync_close_ms ≈ 7000`・`drain_*` は 0（同期のため drain 無し）。

このタスクは perf E2E の honest-RED。**現行コード（同期 remove_group・TeardownService 未配線）で prod 実測**し、~7 s の単発フリーズを確定する。scratchpad の再現ハーネス（`fu16_repro.py`／`fu16_poc.py`）の実ロード経路を製品スクリプト化する。CI 除外（重い・ローカル実測）。

- [ ] **Step 1: prod デモデータを用意**

Run: `uv run python scripts/generate_demo_mf4.py --profile prod`（既存なら skip）
Expected: `demo_data/prod_demo.mf4`（≈1.36 GB・展開後 330,004 ch）

- [ ] **Step 2: ハーネスを書く**

`scripts/fu16_teardown_bench.py`（`QT_QPA_PLATFORM=windows` 推奨・実ロード経路必須）:

```python
"""FU-16 teardown perf bench: prod スケールで close の同期時間＋drain 中の UI 応答を実測.

実アプリ経路（MainWindow._load_file オフスレッド＋ExpansionConfirmer 全展開 → 330,004ch）
で実 close を回し、(1) 同期 close 時間 (2) drain 中 heartbeat 最大 gap を測る。
内部 API・小データ・confirmer 未 patch は 6 秒を隠すため厳禁（len(signals) を検証）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

PROD = Path(os.environ.get("VALISYNC_PROD_MF4", "demo_data/prod_demo.mf4"))


def _patch_expand_all() -> None:
    """ExpansionConfirmer.confirm を全 index 展開に差し替え（330k 到達に必須）。"""
    from valisync.gui.workers import expansion_confirmer as ec

    def _all(self, request):  # noqa: ANN001
        return set(range(len(request.oversized)))  # 実 request の全 oversized を展開

    ec.ExpansionConfirmer.confirm = _all  # type: ignore[method-assign]


def main() -> None:
    app = QApplication([])
    _patch_expand_all()
    from valisync.gui.views.main_window import MainWindow

    win = MainWindow()
    win.show()

    # 実ロード経路（オフスレッド）でロード完了まで event loop を回す。
    win._load_file(PROD)  # 実アプリの開く経路（LoadController 経由）
    deadline = time.perf_counter() + 120
    while win.app_vm.session is None or len(win.app_vm.session.signals()) == 0:
        app.processEvents()
        if time.perf_counter() > deadline:
            raise TimeoutError("load did not complete")
        time.sleep(0.02)

    reached = len(win.app_vm.session.signals())
    assert reached == 330_004, f"reached {reached} ch (expected 330004 — expand-all 未達)"

    # heartbeat: 20ms ごとに now を記録し、tick 間 gap の最大を測る。
    gaps: list[float] = []
    last = [time.perf_counter()]
    hb = QTimer()
    hb.setInterval(20)

    def _beat() -> None:
        now = time.perf_counter()
        gaps.append((now - last[0]) * 1000)
        last[0] = now

    hb.timeout.connect(_beat)
    hb.start()

    # 実 close（確認ダイアログはスキップ＝直接 unload_file で close 経路を駆動）。
    key = win.app_vm.loaded_file_keys[0]
    last[0] = time.perf_counter()
    t0 = time.perf_counter()
    win.app_vm.unload_file(key)      # 同期部分（fix 前は ~7s ここでブロック）
    sync_close_ms = (time.perf_counter() - t0) * 1000

    # drain 完了まで event loop を回す（fix 後は背景 drain。fix 前は既に空）。
    drain_start = time.perf_counter()
    while getattr(win, "teardown_service", None) is not None and (
        win.teardown_service.pending_bytes() > 0
    ):
        app.processEvents()
        if time.perf_counter() - drain_start > 60:
            break
    drain_total_ms = (time.perf_counter() - drain_start) * 1000

    # 同期 close 中の gap も含めるため、close 前後の gaps を対象にする。
    drain_max_gap_ms = max(gaps) if gaps else 0.0
    print(f"reached_channels={reached}")
    print(f"sync_close_ms={sync_close_ms:.1f}")
    print(f"drain_max_gap_ms={drain_max_gap_ms:.1f}")
    print(f"drain_total_ms={drain_total_ms:.1f}")


if __name__ == "__main__":
    main()
```

`MainWindow._load_file` / `app_vm` / `loaded_file_keys` / `ExpansionRequest.oversized` の正確な名前は実装時に `src/valisync/gui/views/main_window.py`・`gui/workers/expansion_confirmer.py` で確認して合わせる（scratchpad の `fu16_repro.py` に動作実績あり）。`teardown_service`/`pending_bytes()` は Task 3/6 で導入する（honest-RED 時は未存在なので `getattr(...) is not None` ガードで drain ループを 0 回に）。

- [ ] **Step 3: honest-RED を実測（現行の同期 remove_group で）**

Run: `VALISYNC_PROD_MF4=demo_data/prod_demo.mf4 QT_QPA_PLATFORM=windows uv run python scripts/fu16_teardown_bench.py`
Expected（現行）: `reached_channels=330004`・`sync_close_ms ≈ 7000`（同期フリーズ）・`drain_* ≈ 0`。**この before 値を PR に転記**。

- [ ] **Step 4: Commit**

```bash
git add scripts/fu16_teardown_bench.py
git commit -m "test(fu16): teardown perf ハーネス＋honest-RED（prod 実ロード経路・同期 close ~7s を記録）"
```

---

### Task 3: `TeardownService`（graveyard＋byte-budget QTimer drain）

**Files:**
- Create: `src/valisync/gui/workers/teardown_service.py`
- Test: `tests/gui/test_teardown_service.py`

**Interfaces:**
- Consumes: `SignalGroup`（`.signals` ＝ `tuple[Signal, ...]`・各 `Signal.timestamps/.values` は numpy）
- Produces: `TeardownService(on_finished: Callable[[str], None] | None = None, byte_budget: int = _BYTE_BUDGET, parent=None)`／`enqueue(key: str, group: SignalGroup) -> None`／`pending_bytes() -> int`（テスト・bench 用）。Task 4 が `enqueue` を、Task 6 が `on_finished` を配線。

> 設計 spec §4.3 を実装で微細化: 「解放開始」は `unload_file` が enqueue 時に同期でマークする（Task 4）ため、Service のコールバックは **`on_finished` のみ**。

- [ ] **Step 1: Write the failing tests（Layer A）**

`tests/gui/test_teardown_service.py`:

```python
from __future__ import annotations

import gc
import weakref

import numpy as np
import pytest

from valisync.core.models import Signal, SignalGroup
from valisync.gui.workers.teardown_service import TeardownService


def _sig(name: str, n: int) -> Signal:
    return Signal(
        name=name,
        timestamps=np.zeros(n, dtype=np.float64),
        values=np.zeros(n, dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def _group(sigs: tuple[Signal, ...]) -> SignalGroup:
    from datetime import datetime
    from pathlib import Path

    return SignalGroup(
        signals=sigs, source_path=Path("x.csv"), file_format="CSV", loaded_at=datetime(2026, 1, 1)
    )


def _drain_all(svc: TeardownService, qtbot) -> None:
    qtbot.waitUntil(lambda: svc.pending_bytes() == 0, timeout=5000)


def test_drains_in_byte_budget_slices(qtbot) -> None:
    """1 tick は byte 予算＋最大1配列を超えない（巨大配列 1 本は単独 tick）。"""
    # 各 Signal ~8 MB (1e6 f64 ×2). budget 16MB -> tick あたり ~2-3 signal.
    sigs = tuple(_sig(f"s{i}", 1_000_000) for i in range(10))
    svc = TeardownService(byte_budget=16 * 1024 * 1024)
    slice_bytes: list[int] = []
    orig = svc._drain

    def _spy() -> None:
        before = svc.pending_bytes()
        orig()
        slice_bytes.append(before - svc.pending_bytes())

    svc._drain = _spy  # type: ignore[method-assign]
    svc.enqueue("g", _group(sigs))
    _drain_all(svc, qtbot)
    max_signal_bytes = 1_000_000 * 8 * 2
    for b in slice_bytes:
        assert b <= 16 * 1024 * 1024 + max_signal_bytes  # 予算＋最大1配列


def test_huge_array_gets_its_own_tick(qtbot) -> None:
    """予算より大きい 1 配列でも単独 tick で解放できる（件数分割の 576ms スパイク回避）。"""
    big = _sig("big", 5_000_000)  # ~80 MB
    svc = TeardownService(byte_budget=16 * 1024 * 1024)
    svc.enqueue("g", _group((big,)))
    _drain_all(svc, qtbot)
    assert svc.pending_bytes() == 0


def test_on_finished_fires_per_key_and_actually_frees(qtbot) -> None:
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=1 * 1024 * 1024)
    s = _sig("s", 1_000_000)
    ref = weakref.ref(s.values)
    grp = _group((s,))
    del s
    svc.enqueue("g", grp)
    del grp
    _drain_all(svc, qtbot)
    gc.collect()
    assert done == ["g"]
    assert ref() is None  # 配列が実際に解放された


def test_multiple_keys_fifo_each_finishes(qtbot) -> None:
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=4 * 1024 * 1024)
    svc.enqueue("a", _group((_sig("a1", 500_000), _sig("a2", 500_000))))
    svc.enqueue("b", _group((_sig("b1", 500_000),)))
    _drain_all(svc, qtbot)
    assert sorted(done) == ["a", "b"]


def test_empty_group_finishes_immediately(qtbot) -> None:
    done: list[str] = []
    svc = TeardownService(on_finished=done.append)
    svc.enqueue("g", _group(()))
    assert done == ["g"]
    assert svc.pending_bytes() == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/gui/test_teardown_service.py -v`
Expected: FAIL — `ModuleNotFoundError: ...teardown_service`

- [ ] **Step 3: Implement**

`src/valisync/gui/workers/teardown_service.py`:

```python
"""Off-UI-thread graveyard for freeing a closed file's ~10 GB in byte-budget
slices (FU-16). A closed file's Signal_Group is stashed here and drained a
budget's worth of bytes per zero-interval QTimer tick, so the event loop keeps
running between ticks and the UI stays responsive during the ~seconds of frees.

Runs entirely on the GUI thread (no worker thread): the freeze is per-tick byte
volume, not GIL contention (PoC verified) — naive offthread is a GIL trap.
Slicing by BYTES (not signal count) bounds a single huge array to one tick.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from valisync.core.models import Signal, SignalGroup

_BYTE_BUDGET = 64 * 1024 * 1024  # 64 MiB per tick


class TeardownService(QObject):
    def __init__(
        self,
        on_finished: Callable[[str], None] | None = None,
        *,
        byte_budget: int = _BYTE_BUDGET,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_finished = on_finished
        self._budget = byte_budget
        self._graveyard: list[tuple[str, Signal]] = []
        self._pending_count: dict[str, int] = {}
        self._pending_bytes = 0
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._drain)

    def pending_bytes(self) -> int:
        return self._pending_bytes

    def enqueue(self, key: str, group: SignalGroup) -> None:
        sigs = list(group.signals)
        if not sigs:
            if self._on_finished is not None:
                self._on_finished(key)
            return
        self._pending_count[key] = self._pending_count.get(key, 0) + len(sigs)
        for s in sigs:
            self._graveyard.append((key, s))
            self._pending_bytes += s.timestamps.nbytes + s.values.nbytes
        # NOTE: caller must not keep a ref to `group` after this (it does not).
        if not self._timer.isActive():
            self._timer.start()

    def _drain(self) -> None:
        freed = 0
        while self._graveyard:
            key, sig = self._graveyard.pop()
            freed += sig.timestamps.nbytes + sig.values.nbytes
            self._pending_bytes -= sig.timestamps.nbytes + sig.values.nbytes
            self._pending_count[key] -= 1
            if self._pending_count[key] == 0:
                del self._pending_count[key]
                if self._on_finished is not None:
                    self._on_finished(key)
            del sig  # drop the last strong ref -> the arrays free here
            if freed >= self._budget:
                break
        if not self._graveyard:
            self._timer.stop()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/gui/test_teardown_service.py -v`
Expected: PASS（全 5 テスト）

- [ ] **Step 5: サボタージュ検証**

一時的に `_drain` の `if freed >= self._budget: break` を削除（＝全部を 1 tick で解放）し、`test_drains_in_byte_budget_slices` が「1 slice に全 bytes」で FAIL することを確認 → 戻す（コミットしない）。

- [ ] **Step 6: 品質ゲート＋Commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_teardown_service.py -q
git add src/valisync/gui/workers/teardown_service.py tests/gui/test_teardown_service.py
git commit -m "feat(fu16): TeardownService — graveyard＋byte-budget QTimer 分割解放（Layer A・サボタージュRED済）"
```

---

### Task 4: `AppViewModel` 配線（teardown 注入＋releasing 状態＋unload 遅延）

**Files:**
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py`（`__init__`＝`:29-41`・`unload_file`＝`:123-141`）
- Test: `tests/gui/test_app_viewmodel.py`

**Interfaces:**
- Consumes: `RemovalResult.removed_group`（Task 1）・duck-typed teardown（`enqueue(key, group)`・Task 3 の `TeardownService`）
- Produces: `set_teardown(service)`／`releasing_files -> list[tuple[str, str]]`（(key, name) 挿入順）／`mark_released(key)`。`unload_file` は `removed_group` を service へ渡し releasing にマーク・即 return。

- [ ] **Step 1: Write the failing tests（Layer A）**

`tests/gui/test_app_viewmodel.py` に追加（既存 `_write_csv`/`_csv_format` 流用）:

```python
class _FakeTeardown:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def enqueue(self, key, group) -> None:  # noqa: ANN001
        self.calls.append((key, group))


def test_unload_defers_removed_group_to_teardown_and_marks_releasing(tmp_path) -> None:
    app_vm = AppViewModel()
    fake = _FakeTeardown()
    app_vm.set_teardown(fake)
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    name = app_vm.session.source_name(key)

    app_vm.unload_file(key)

    # remove_group の削除グループが service へ渡る（core は同期解放しない）。
    assert len(fake.calls) == 1 and fake.calls[0][0] == key
    assert fake.calls[0][1] is not None
    # releasing にマーク（名前は unload 時にキャプチャ＝session から消えても表示可）。
    assert app_vm.releasing_files == [(key, name)]
    # 論理クローズは同期で完了（loaded から消える）。
    assert key not in app_vm.loaded_file_keys


def test_mark_released_removes_from_releasing(tmp_path) -> None:
    app_vm = AppViewModel()
    fake = _FakeTeardown()
    app_vm.set_teardown(fake)
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    app_vm.unload_file(key)
    seen: list[str] = []
    app_vm.subscribe(lambda tag: seen.append(tag) if tag == "releasing" else None)

    app_vm.mark_released(key)

    assert app_vm.releasing_files == []
    assert "releasing" in seen


def test_unload_without_teardown_frees_immediately_no_releasing(tmp_path) -> None:
    """teardown 未注入（ヘッドレス既定）では releasing にせず即時解放（現行挙動保存）。"""
    app_vm = AppViewModel()
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    app_vm.unload_file(key)
    assert app_vm.releasing_files == []
    assert key not in app_vm.loaded_file_keys
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/gui/test_app_viewmodel.py -k "releasing or teardown" -v`
Expected: FAIL — `AttributeError: 'AppViewModel' object has no attribute 'set_teardown'`

- [ ] **Step 3: Implement**

`__init__`（`:32` 付近）に状態追加:

```python
        self._teardown: object | None = None          # duck-typed: enqueue(key, group)
        self._releasing: dict[str, str] = {}           # key -> display name (capture at unload)
```

メソッド追加（`unload_file` 付近）:

```python
    def set_teardown(self, service: object) -> None:
        """Inject the GUI-thread teardown service (duck-typed ``enqueue(key, group)``)."""
        self._teardown = service

    @property
    def releasing_files(self) -> list[tuple[str, str]]:
        """(key, display name) of files whose data is still draining, in order."""
        return list(self._releasing.items())

    def mark_released(self, key: str) -> None:
        """Called by the teardown service when *key*'s data is fully freed."""
        if self._releasing.pop(key, None) is not None:
            self._notify("releasing")
```

`unload_file`（`:123-141`）を差し替え:

```python
    def unload_file(self, key: str) -> None:
        """Unload a loaded file: remove its group and defer the ~10 GB dealloc.

        The heavy dealloc of the removed group is handed to the injected teardown
        service (byte-budget background drain) so the UI thread returns at once
        (FU-16). Logical close (loaded list / active file / offsets / prune) stays
        synchronous. Refused without side effects when a Derived_Signal depends on
        the group.
        """
        name = self._safe_source_name(key)
        result = self._session.remove_group(key)
        if not result.removed:
            return
        if key in self._loaded_keys:
            self._loaded_keys.remove(key)
        if self._active_file_key == key:
            self._active_file_key = None
            self._notify("active_file")
        self._file_offsets.pop(key, None)
        self._purge_signal_offsets_under(key)
        self._notify("unloaded")
        if result.removed_group is not None and self._teardown is not None:
            self._releasing[key] = name
            self._teardown.enqueue(key, result.removed_group)   # background drain
            self._notify("releasing")
        # else: removed_group falls out of scope here -> immediate sync free.

    def _safe_source_name(self, key: str) -> str:
        try:
            return self._session.source_name(key)
        except KeyError:
            return key
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/gui/test_app_viewmodel.py -v`
Expected: PASS（新規＋既存無回帰）

- [ ] **Step 5: Commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_app_viewmodel.py -q
git add src/valisync/gui/viewmodels/app_viewmodel.py tests/gui/test_app_viewmodel.py
git commit -m "feat(fu16): AppViewModel が removed_group を TeardownService へ遅延・releasing 状態を保持"
```

---

### Task 5: `FileBrowserVM` — `loaded ∪ releasing` 合成

**Files:**
- Modify: `src/valisync/gui/viewmodels/file_browser_vm.py`（`_refresh`＝`:104-119`・`_on_app_change`＝`:99-102`）
- Test: `tests/gui/test_file_browser_vm.py`

**Interfaces:**
- Consumes: `AppViewModel.loaded_file_keys`・`releasing_files`・`source_name`
- Produces: `files -> list[str]`（loaded 名 ＋ releasing 名）／`is_releasing(row) -> bool`。releasing 行は loaded 行の**後ろ**に並ぶ（`select_file`/`unload` の `index < len(loaded_keys)` ガードで自動的に no-op）。

- [ ] **Step 1: Write the failing tests（Layer A）**

`tests/gui/test_file_browser_vm.py`（無ければ新規・既存 FB テストの setup を流用）:

```python
def test_releasing_file_stays_after_loaded_rows_until_released(tmp_path) -> None:
    app_vm = AppViewModel()

    class _Fake:
        def enqueue(self, key, group):  # noqa: ANN001
            pass

    app_vm.set_teardown(_Fake())
    k1 = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    k2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _csv_format())
    vm = FileBrowserVM(app_vm)
    n1, n2 = app_vm.session.source_name(k1), app_vm.session.source_name(k2)

    app_vm.unload_file(k1)  # k1 -> releasing（loaded から消え、末尾に releasing 行）

    assert vm.files == [n2, n1]          # loaded(n2) の後ろに releasing(n1)
    assert vm.is_releasing(0) is False   # loaded 行
    assert vm.is_releasing(1) is True    # releasing 行

    app_vm.mark_released(k1)
    assert vm.files == [n2]
    assert vm.is_releasing(0) is False
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/gui/test_file_browser_vm.py -k releasing -v`
Expected: FAIL（releasing 行が出ない／`is_releasing` 未定義）

- [ ] **Step 3: Implement**

`_on_app_change`（`:99-102`）に "releasing" を追加:

```python
    def _on_app_change(self, change: str) -> None:
        if change in ("loaded", "unloaded", "releasing"):
            self._refresh()
```

`_refresh`（`:104-119`）を loaded ∪ releasing 合成に:

```python
    def _refresh(self) -> None:
        """Rebuild the row list: loaded files first, then still-releasing files.

        Releasing rows sit AFTER loaded rows so the existing index guards in
        select_file/unload (index < len(loaded_file_keys)) make them no-op —
        i.e. non-interactive by construction (FU-16).
        """
        loaded: list[str] = []
        for key in self._app_vm.loaded_file_keys:
            try:
                loaded.append(self._app_vm.session.source_name(key))
            except KeyError:
                loaded.append(key)
        releasing = [name for _key, name in self._app_vm.releasing_files]
        self._loaded_count = len(loaded)
        self._files = loaded + releasing
        self._notify("files")

    def is_releasing(self, row: int) -> bool:
        """True when the row at *row* is a still-releasing (spinner) placeholder."""
        return row >= getattr(self, "_loaded_count", len(self._files))
```

`__init__` に `self._loaded_count = 0` を追加（`self._files: list[str] = []` の直後）。

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/gui/test_file_browser_vm.py -v`
Expected: PASS（新規＋既存無回帰＝loaded のみ時 `is_releasing` 全 False）

- [ ] **Step 5: Commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_file_browser_vm.py -q
git add src/valisync/gui/viewmodels/file_browser_vm.py tests/gui/test_file_browser_vm.py
git commit -m "feat(fu16): FileBrowserVM が loaded∪releasing を合成（releasing 行は末尾＝非操作）"
```

---

### Task 6: File Browser view — スピナー描画（アニメ・淡色・非操作）

**Files:**
- Modify: `src/valisync/gui/adapters/qt_signal_models.py`（`FileListModel`）
- Create: `src/valisync/gui/views/file_row_spinner.py`（`ReleasingSpinnerDelegate`）
- Modify: `src/valisync/gui/views/file_browser_view.py`（delegate 装着＋回転タイマー）
- Test: `tests/gui/test_file_browser_view.py`

**Interfaces:**
- Consumes: `FileBrowserVM.is_releasing(row)`
- Produces: releasing 行が非選択・非有効（`flags`）＋スピナー（delegate 描画）＋淡色。実 Qt クリックで no-op。

- [ ] **Step 1: Write the failing tests（Layer A/B）**

`tests/gui/test_file_browser_view.py` に追加:

```python
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QMouseEvent


def test_releasing_row_is_non_interactive(qtbot, tmp_path) -> None:
    """releasing 行は選択不可・有効フラグ無し（クリックしても選択/close されない）。"""
    app_vm, k1, k2 = _two_file_app_vm_with_fake_teardown(tmp_path)  # ヘルパ（下記）
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    app_vm.unload_file(k1)  # k1 -> releasing（末尾行）

    releasing_row = 1
    idx = view.model.index(releasing_row, 0)
    flags = view.model.flags(idx)
    assert not (flags & Qt.ItemFlag.ItemIsSelectable)
    assert not (flags & Qt.ItemFlag.ItemIsEnabled)

    # 実 Qt クリック（Layer B）: releasing 行を押しても選択されない。
    rect = view.list_view.visualRect(idx)
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress, rect.center(), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.list_view.viewport(), ev)
    assert not view.list_view.selectionModel().isSelected(idx)


def test_releasing_row_exposes_spinner_state(qtbot, tmp_path) -> None:
    """delegate が読む custom role が releasing 行で True・loaded 行で False。"""
    app_vm, k1, k2 = _two_file_app_vm_with_fake_teardown(tmp_path)
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    app_vm.unload_file(k1)
    assert view.model.data(view.model.index(1, 0), FileListModel.ReleasingRole) is True
    assert view.model.data(view.model.index(0, 0), FileListModel.ReleasingRole) is False
```

`_two_file_app_vm_with_fake_teardown` ヘルパは Task 5 のテストと同型（fake teardown 注入＋2 ファイル load）。テストモジュール内に定義する。

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/gui/test_file_browser_view.py -k releasing -v`
Expected: FAIL（`ReleasingRole` 未定義／releasing 行が selectable）

- [ ] **Step 3: `FileListModel` に releasing role/flags を実装**

`FileListModel`（`qt_signal_models.py`）に追加:

```python
    ReleasingRole = Qt.ItemDataRole.UserRole + 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._vm.files)):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._vm.files[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._vm.tooltip_text(index.row())
        if role == FileListModel.ReleasingRole:
            return self._vm.is_releasing(index.row())
        if role == Qt.ItemDataRole.ForegroundRole and self._vm.is_releasing(index.row()):
            from PySide6.QtGui import QColor
            return QColor(128, 128, 128)  # 淡色
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.isValid() and self._vm.is_releasing(index.row()):
            # 解放中の行は選択も操作も不可（スピナーのプレースホルダ）。
            return base & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled
        return base
```

（`_on_vm_change` の `beginResetModel/endResetModel` は "files" 通知で既に走るので releasing の増減も反映される。）

- [ ] **Step 4: スピナー delegate＋回転タイマー**

`src/valisync/gui/views/file_row_spinner.py`:

```python
"""ReleasingSpinnerDelegate — paints a rotating arc on File Browser rows whose
data is still draining (FU-16). No text ("解放中" は出さない): the spinner alone
signals release-in-progress; the row is dimmed and non-interactive."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate

from valisync.gui.adapters.qt_signal_models import FileListModel


class ReleasingSpinnerDelegate(QStyledItemDelegate):
    """Draws the default item, then a spinner arc for releasing rows at *angle*."""

    def __init__(self, angle_provider, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._angle = angle_provider  # callable -> int degrees

    def paint(self, painter, option, index) -> None:  # noqa: ANN001
        super().paint(painter, option, index)
        if not index.data(FileListModel.ReleasingRole):
            return
        d = min(option.rect.height() - 8, 16)
        x = option.rect.left() + 6
        y = option.rect.center().y() - d / 2
        rect = QRectF(x, y, d, d)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(120, 160, 255), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        start = int(self._angle()) * 16          # Qt angles are in 1/16 deg
        painter.drawArc(rect, -start, 300 * 16)  # 300° arc = spinner gap
        painter.restore()
```

`file_browser_view.py` に装着（`__init__` の list_view 生成後）:

```python
        # Spinner animation: advance an angle and repaint releasing rows only.
        from PySide6.QtCore import QTimer
        from valisync.gui.views.file_row_spinner import ReleasingSpinnerDelegate

        self._spin_angle = 0
        self.list_view.setItemDelegate(ReleasingSpinnerDelegate(lambda: self._spin_angle, self))
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(80)
        self._spin_timer.timeout.connect(self._advance_spinner)
        self._spin_timer.start()
```

```python
    def _advance_spinner(self) -> None:
        self._spin_angle = (self._spin_angle + 30) % 360
        # releasing 行がある時だけ再描画（無ければ無駄描画しない）。
        if any(self._vm.is_releasing(r) for r in range(len(self._vm.files))):
            self.list_view.viewport().update()
```

- [ ] **Step 5: Run to verify pass（Layer A/B）**

Run: `uv run pytest tests/gui/test_file_browser_view.py -v`
Expected: PASS

- [ ] **Step 6: 品質ゲート＋Commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_file_browser_view.py tests/gui/test_file_browser_vm.py -q
git add src/valisync/gui/adapters/qt_signal_models.py src/valisync/gui/views/file_row_spinner.py src/valisync/gui/views/file_browser_view.py tests/gui/test_file_browser_view.py
git commit -m "feat(fu16): File Browser の releasing 行にスピナー（淡色・非操作・アニメ）"
```

---

### Task 7: MainWindow 配線＋after 実測（byte-budget チューニング）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（`AppViewModel`/`FileBrowserVM` 構築箇所）
- （計測のみ・`scripts/fu16_teardown_bench.py` 再実行）

**Interfaces:**
- Consumes: `TeardownService`（Task 3）・`AppViewModel.set_teardown`/`mark_released`（Task 4）
- Produces: 実アプリで close→背景 drain→スピナー→行削除が動く。`MainWindow.teardown_service` を公開（bench の drain ループ用）。

- [ ] **Step 1: TeardownService を生成・注入・配線**

`main_window.py` の `AppViewModel` 構築直後（実装時に該当行を確認）:

```python
        from valisync.gui.workers.teardown_service import TeardownService

        self.teardown_service = TeardownService(on_finished=self.app_vm.mark_released, parent=self)
        self.app_vm.set_teardown(self.teardown_service)
```

（`self.app_vm` の正確な属性名は `main_window.py` で確認して合わせる。`on_finished=self.app_vm.mark_released` が GUI スレッドで releasing 行を消す。）

- [ ] **Step 2: 起動して手動スモーク（実 GUI・small データで可）**

Run: `uv run valisync`（小さな mf4/csv を開いて close）
Expected: close が即完了・行が一瞬スピナー→消える（small データは一瞬なので確認は Step 4 の prod 実測が本番）。クラッシュ無し。

- [ ] **Step 3: after 実測（同ハーネス・prod）**

Run: `VALISYNC_PROD_MF4=demo_data/prod_demo.mf4 QT_QPA_PLATFORM=windows uv run python scripts/fu16_teardown_bench.py`
Expected（修正後）: `sync_close_ms < 200`・`drain_max_gap_ms < 150`・`drain_total_ms` 数秒。**before(~7000/0) と after を並記して PR に転記**。閾値未達（max_gap ≥ 150）なら Task 3 の `_BYTE_BUDGET` を縮小（32 MiB 等）して再測。

- [ ] **Step 4: 既存無回帰＋Commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest -q
git add src/valisync/gui/views/main_window.py
git commit -m "feat(fu16): MainWindow が TeardownService を配線・prod after 実測（同期<200ms・drain max-gap<150ms）"
```

---

### Task 8: realgui（①証拠ゲート）— スピナー可視・UI 応答・完了で消滅

**Files:**
- Create: `tests/realgui/test_close_release_spinner.py`

**Interfaces:**
- Consumes: `tests/realgui/` の共有ヘルパ（`_realgui_input`・`ExpansionConfirmer` 全展開 patch・`tests/realgui/conftest.py` の QSettings 隔離）

`/gui-verify` reference/realgui-recipe に従い、実 prod close の Layer C（実 OS 入力＋実ディスプレイ＋スクショ AI 判定）を書く。合成 `qtbot`/`sendEvent` は Layer B 偽装なので不可（`tests/gui/test_realgui_layer_c_contract.py` が落とす）。

- [ ] **Step 1: realgui テストを書く**

`tests/realgui/test_close_release_spinner.py`（`@pytest.mark.realgui`・`QT_QPA_PLATFORM=windows`）:
- prod（`VALISYNC_PROD_MF4`）を実 `_load_file`＋ExpansionConfirmer 全展開でロード（`len(session.signals())==330004` を assert）。
- File Browser の対象行を**実 OS 右クリック**（`_realgui_input.at()`）→「Remove File」→ 確認 Yes を**実クリック**。
- close 直後: 対象行に**スピナーが可視**（スクショ AI 判定＝クルクル・淡色・テキスト無し）＋**UI が固まらない**（drain 中に別操作＝別ウィンドウ前面化やカーソル移動が効く／heartbeat）。
- drain 完了後: **対象行が消えている**（スクショ）。
- honest-RED: fix 前（同期 remove_group）は close 中に UI が ~7 s フリーズしスピナーも出ない（sabotage 実証）。

- [ ] **Step 2: 実機実行＋証拠**

Run: `uv run pytest --realgui tests/realgui/test_close_release_spinner.py -v`
Expected: PASS＋スクショ（スピナー可視／完了で消滅）。

- [ ] **Step 3: Commit**

```bash
git add tests/realgui/test_close_release_spinner.py
git commit -m "test(fu16): realgui — 実 prod close でスピナー可視・UI 応答・完了で消滅（①証拠ゲート）"
```

---

### Task 9: catalog 更新（FU-16 ✅解消）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（FU-16 行・SS-FOLLOWUP 見出し）

- [ ] **Step 1: FU-16 行を ✅解消へ**

FU-16 行の重要度を `✅` にし、根治（remove_group の byte-budget 遅延分割解放＋File Browser スピナー）・**prod before/after（同期 ~7000ms→<200ms・drain 中 heartbeat 最大 gap<150ms）**・realgui 証拠を追記。

- [ ] **Step 2: SS-FOLLOWUP 見出しの進捗を更新**（`:157`）: 「FU-16 ✅解消（PR #XX・prod 実測 ~7s→数十ms・スピナー UX）」。

- [ ] **Step 3: Commit**

```bash
git add docs/audit-findings-catalog.md
git commit -m "docs(fu16): FU-16 ✅解消を catalog 反映（prod 実測 ~7s→<200ms・スピナー UX・realgui）"
```

---

## Self-Review

**1. Spec coverage:**
- core removed_group 手渡し → Task 1 ✅
- TeardownService（graveyard＋byte-budget QTimer drain＋on_finished）→ Task 3 ✅
- unload_file 遅延＋releasing 状態（AppViewModel 所有）→ Task 4 ✅
- File Browser loaded∪releasing → Task 5 ✅／スピナー描画（淡色・非操作・アニメ・テキスト無し）→ Task 6 ✅
- MainWindow 配線 → Task 7 ✅
- perf E2E（prod 実ロード経路・330k 検証・同期<200ms/drain max-gap<150ms・honest-RED）→ Task 2（before）・Task 7（after）✅
- realgui（①証拠ゲート・スピナー可視/応答/消滅）→ Task 8 ✅
- エッジ（アプリ終了=drain 放棄で OS 回収／同一再オープン=別キー独立／複数同時=FIFO・per-key on_finished）→ Task 3/4 のテストで担保 ✅
- catalog → Task 9 ✅

**2. Placeholder scan:** 実装/テストコードは具体。`<before>/<after>` は実測後に埋める実値プレースホルダ（意図的）。ハーネスの API 名（`_load_file`/`app_vm`/`ExpansionRequest.oversized`）は「実装時に該当ファイルで確認」と具体化（scratchpad `fu16_repro.py` に実績）。

**3. Type consistency:** `RemovalResult.removed_group: SignalGroup | None`（Task 1）→ Task 4 が `result.removed_group` 消費・一致。`TeardownService.enqueue(key: str, group: SignalGroup)`（Task 3）→ Task 4 の duck-typed 注入・Task 6 は `is_releasing(row: int) -> bool`（Task 5）を model/delegate が消費・一致。`FileListModel.ReleasingRole`（Task 6）を delegate が読む・一致。`mark_released(key)`（Task 4）を Task 7 が `on_finished` に配線・一致。
