# 増分B（決定的なハンドル解放＋teardown ペーシング）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 開いた mf4 のロックを unload で**決定的に**解放し、遅延ロード後の teardown が UI を固めないようにする。

**Architecture:** `MdfHandle.close()` を `Session.remove_group` から呼ぶ（core が handle 寿命を持ち、unload と `_discard` の両方を構造的にカバー）。teardown のバイト会計を正直化すると未展開グループが 1 ティックで解放され **実測 649ms のフリーズ**になるため、**バイト予算と信号数上限（8,000/tick）の二軸**にする。エクスポート実行中の unload は明示ガードで拒否する（現状は `BusyOverlay` の偶然に依存）。

**Tech Stack:** Python 3.13 / PySide6 / asammdf 8.8.22 / pytest。

**設計 spec:** [2026-07-24-lazy-load-signal-samples-design.md](../specs/2026-07-24-lazy-load-signal-samples-design.md) の「増分B」節（2026-07-29 再定義版）が一次情報源。

## Global Constraints

- 品質ゲート全通過: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- **ユーザー決定（変更不可）**:
  1. close は **`Session.remove_group`** に置く（`AppViewModel.unload_file` ではない）。
  2. エクスポート中の unload は**許容するが、明示ガードで到達不能を確実にする**（`BusyOverlay` の偶然に依存しない）。
  3. ドレインの 1 ティック上限は **8,000 信号**（実測 1.97µs/信号 ⇒ ≈16ms＝60fps の 1 フレーム）。バイト予算 64 MiB との**二軸**で、先に達した方で中断。
  4. **MDF3 が開けない defect は本増分に含めない**（follow-up 起票）。
- **`MdfHandle._closed` のフラグは lock の外で立てる設計を維持する**（lock 内に移すと、待機中の reader が `is_closed` を False と読んで閉じる直前の handle に select を投げるため厳密に悪化する）。アトミック化はするが、位置は変えない。WHY をコメントに残す。
- `RemovalResult.removed_columns` の配線は**本増分ではない**（`_mint_column` が `None` を返す限り常に `()`＝end-to-end 検証不能・E-3 の完了定義）。
- GUI 変更は Layer A/B（CI）必須・Layer C（`--realgui`）で ①gate。
- コメントは WHY を書く。DRY / YAGNI / TDD。
- 実装はブランチ `feature/lazy-load-samples` 上。main 直接編集禁止。

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `src/valisync/core/session.py` | `remove_group` で handle close・`load` の登録失敗で close | 変更 |
| `src/valisync/core/loaders/mdf_handle.py` | `_closed` の check-and-set をアトミック化（位置は維持） | 変更 |
| `src/valisync/core/models/sample_source.py` | double-checked read・`array_if_materialized`（会計の id-dedup 用） | 変更 |
| `src/valisync/gui/workers/teardown_service.py` | 二軸ペーシング（バイト＋信号数）・master の identity dedup | 変更 |
| `src/valisync/gui/workers/export_worker.py` | 実行中判定の公開（`is_busy`） | 変更 |
| `src/valisync/gui/views/main_window.py` | `_discard` を teardown 経路へ・excepthook 診断の dedup とラベル | 変更 |

---

## Task 1: `Session.remove_group` で handle を閉じる

**Files:**
- Modify: `src/valisync/core/session.py`（`remove_group`・~291）
- Test: `tests/core/test_handle_release.py`（新規）

**Interfaces:**
- Produces: `remove_group` が成功時に `SignalGroup.handle`（あれば）を close する。CSV グループは `handle is None` なので no-op。

- [ ] **Step 1: 失敗テストを書く**

`tests/core/test_handle_release.py`:

```python
"""unload でファイルロックが決定的に解放されることを固定する (増分B)。

今日でも最終的には解放されるが、それは asammdf の MDF.__del__ 経由で
「そのグループの最後の Signal 参照が死んだ時」= TeardownService のドレイン後
であり非決定的。明示 close で決定化する。
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.session import Session


def _load_one(tmp_path: Path) -> tuple[Session, str, Path]:
    path = tmp_path / "lock.mf4"
    write_mdf4(path, [("Spd", CAN, np.arange(8, dtype=np.float64))])
    session = Session()
    outcome = session.load(path, confirm_expansion=None)
    return session, outcome.key, path


def test_file_is_locked_while_loaded(tmp_path: Path) -> None:
    session, _key, path = _load_one(tmp_path)
    victim = tmp_path / "moved.mf4"
    with pytest.raises(OSError):
        os.replace(path, victim)  # 開いている間は移動できない


def test_remove_group_releases_the_lock_without_gc(tmp_path: Path) -> None:
    # gc.collect() を呼ばずに解放されることが「決定的」の意味
    session, key, path = _load_one(tmp_path)
    session.remove_group(key)
    victim = tmp_path / "moved.mf4"
    os.replace(path, victim)  # 例外が出なければ成功
    assert victim.exists()


def test_handle_is_closed_after_remove(tmp_path: Path) -> None:
    session, key, _path = _load_one(tmp_path)
    group = session._groups.group(key)  # remove 前に掴んでおく
    handle = group.handle
    assert handle is not None and handle.is_closed is False
    session.remove_group(key)
    assert handle.is_closed is True


def test_remove_group_is_idempotent_for_csv_groups(tmp_path: Path) -> None:
    # CSV は handle=None。close 経路が None で落ちないこと
    from valisync.core.models import Delimiter, FormatDefinition

    csv = tmp_path / "d.csv"
    csv.write_text("t,v\n0,1\n1,2\n", encoding="utf-8")
    session = Session()
    fmt = FormatDefinition(
        time_column=0, delimiter=Delimiter.COMMA, header_rows=1, unit_row=None
    )
    key = session.load(csv, fmt).key
    result = session.remove_group(key)
    assert result.removed is True
```

> 実装者へ: `write_mdf4` / `FormatDefinition` の実シグネチャを `tests/mdf4_helpers.py` と
> `src/valisync/core/models/format_def.py` で確認し、実物に合わせること。CSV の
> fixture は既存テストに同型のものがあるはずなのでそれを流用してよい。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/test_handle_release.py -q`
Expected: `test_remove_group_releases_the_lock_without_gc` と
`test_handle_is_closed_after_remove` が FAIL（close されないため）

- [ ] **Step 3: `remove_group` で close する**

`session.py` の `remove_group` の成功経路（グループを pop した後・`RemovalResult` を返す前）に:

```python
        # 増分B: handle 寿命は core が持つ。ここで閉じることで unload と
        # MainWindow._discard (キャンセル完走のロールバック) の両方が構造的に
        # カバーされる — GUI 側 (unload_file) に置くと _discard が漏れる。
        # CSV/Derived グループは handle=None なので no-op。
        handle = getattr(group, "handle", None)
        if handle is not None:
            handle.close()
```

（`group` は既に pop 済みのローカル変数名に合わせること。`SignalGroupManager.remove` は
`(group, columns)` を返す実装になっているので、その戻り値から取る。）

- [ ] **Step 4: 通ることを確認 + 既存テスト全通過**

Run: `uv run pytest tests/core/ tests/test_session.py tests/gui/ -q`
Expected: PASS。close 後に遅延読みしようとするテストがあれば、それは
**`SampleReadError` になるのが正しい**（増分A で実装済み）。落ちたら中身を確認する。

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/core/session.py tests/core/test_handle_release.py
git commit -m "feat(core): remove_group で MDF ハンドルを閉じる (ファイルロックの決定的解放)"
```

---

## Task 2: `Session.load` の登録失敗で handle を閉じる

**Files:**
- Modify: `src/valisync/core/session.py`（`load` の `add()` 周辺・~166）
- Test: `tests/core/test_handle_release.py`

**Interfaces:**
- Consumes: Task 1 の close 規約

- [ ] **Step 1: 失敗テストを書く**

`tests/core/test_handle_release.py` に追記:

```python
def test_registration_failure_does_not_leak_the_handle(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """add() が raise してもファイルはロックされたままにならない。

    GUI では _on_load_error がモーダルを出す間トレースバックが handle を pin する
    ため、閉じないとダイアログ表示中ずっとロックが残る。
    """
    path = tmp_path / "reg_fail.mf4"
    write_mdf4(path, [("Spd", CAN, np.arange(8, dtype=np.float64))])
    session = Session()

    def _boom(_group):  # type: ignore[no-untyped-def]
        raise ValueError("unsupported file_format: 'MDF3'")

    monkeypatch.setattr(session._groups, "add", _boom)
    with pytest.raises(ValueError):
        session.load(path, confirm_expansion=None)

    victim = tmp_path / "moved2.mf4"
    os.replace(path, victim)  # 例外が出なければリークしていない
    assert victim.exists()
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/test_handle_release.py::test_registration_failure_does_not_leak_the_handle -q`
Expected: FAIL（`os.replace` が `OSError`）

- [ ] **Step 3: `load` の登録を try/except で囲む**

`session.py` の `load` で `self._groups.add(result.signal_group)` している箇所を:

```python
        try:
            key = self._groups.add(result.signal_group)
        except Exception:
            # 登録に失敗したグループは誰も所有しない。handle を閉じないと
            # トレースバックが生かし続け、GUI のエラーダイアログ表示中ずっと
            # ファイルがロックされる。
            handle = getattr(result.signal_group, "handle", None)
            if handle is not None:
                handle.close()
            raise
```

（実際の変数名・戻り値の扱いは現行コードに合わせること。）

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/ tests/test_session.py -q`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/core/session.py tests/core/test_handle_release.py
git commit -m "fix(core): 登録失敗時に MDF ハンドルを閉じる (エラーダイアログ中のロック残留を解消)"
```

---

## Task 3: teardown の二軸ペーシング（バイト＋信号数）

**Files:**
- Modify: `src/valisync/gui/workers/teardown_service.py`
- Test: `tests/gui/test_teardown_pacing.py`（新規）

**Interfaces:**
- Produces: `TeardownService(..., byte_budget=..., signal_budget=8000)`。`_drain` は
  **バイト予算と信号数予算のどちらかに達したら中断**する。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_teardown_pacing.py`:

```python
"""ドレインは 1 ティックで 8,000 信号を超えない (増分B・FU-16 の再来防止)。

バイト会計を正直にすると未展開の遅延グループは実質 0 バイトになり、330,004
シェルが 1 ティックで解放されて実測 649ms のフリーズになる。信号数の上限は
オプションではなく必須。時間ではなく **信号数** で assert する (マシン依存回避)。
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from valisync.core.models import Signal, SignalGroup
from valisync.gui.workers.teardown_service import TeardownService


class _ZeroByteSource:
    """未展開の遅延ソース相当: 会計上 0 バイト."""

    is_materialized = False
    nbytes_if_materialized = 0

    def __init__(self, n: int) -> None:
        self.length = n

    def array(self) -> np.ndarray:  # pragma: no cover - 呼ばれてはいけない
        raise AssertionError("teardown must not materialize")


def _lazy_group(n_signals: int) -> SignalGroup:
    ts = np.arange(4, dtype=np.float64)
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,  # master は identity 共有 (会計で dedup されるべき)
            values_source=_ZeroByteSource(4),  # type: ignore[arg-type]
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i in range(n_signals)
    )
    return SignalGroup(
        signals=sigs,
        source_path=Path("/x.mf4").resolve(),
        file_format="MDF4",
        loaded_at=datetime.datetime.now(),
    )


def test_one_tick_never_frees_more_than_the_signal_budget(qtbot) -> None:  # type: ignore[no-untyped-def]
    svc = TeardownService(signal_budget=100)
    svc.enqueue("k", _lazy_group(1000))
    before = svc.pending_signals()
    svc._drain()  # 1 ティックぶんだけ回す
    freed = before - svc.pending_signals()
    assert freed == 100, f"1 ティックで {freed} 信号を解放した (上限 100)"


def test_drain_completes_across_ticks(qtbot) -> None:  # type: ignore[no-untyped-def]
    finished: list[str] = []
    svc = TeardownService(on_finished=finished.append, signal_budget=100)
    svc.enqueue("k", _lazy_group(1000))
    qtbot.waitUntil(lambda: finished == ["k"], timeout=5000)
    assert svc.pending_signals() == 0


def test_default_signal_budget_is_8000(qtbot) -> None:  # type: ignore[no-untyped-def]
    # 実測 1.97us/信号 => 約 16ms = 60fps の 1 フレーム
    svc = TeardownService()
    svc.enqueue("k", _lazy_group(20000))
    before = svc.pending_signals()
    svc._drain()
    assert before - svc.pending_signals() == 8000
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_teardown_pacing.py -q`
Expected: FAIL（`signal_budget` 引数が無い／1 ティックで全部解放される）

- [ ] **Step 3: 二軸ペーシングを実装**

`teardown_service.py`:

```python
_BYTE_BUDGET = 64 * 1024 * 1024  # 64 MiB per tick
# 未展開の遅延シェルはバイト会計上ほぼ 0 なので、バイト予算だけでは 330k シェルが
# 1 ティックで解放され実測 649ms 固まる (FU-16 の再来)。解放コストは個数にも比例
# する (実測 1.97us/信号) ため、信号数の上限を第 2 の軸として持つ。
# 8,000 signals ≈ 16ms = 60fps の 1 フレーム。
_SIGNAL_BUDGET = 8_000
```

`__init__` に `signal_budget: int = _SIGNAL_BUDGET` を足し `self._signal_budget` に保持。
`_drain` のループ条件を**両方**見る形へ:

```python
    def _drain(self) -> None:
        freed_bytes = 0
        freed_signals = 0
        while self._groups and freed_bytes < self._budget and freed_signals < self._signal_budget:
            key, sigs = self._groups[0]
            while (
                sigs
                and freed_bytes < self._budget
                and freed_signals < self._signal_budget
            ):
                sig = sigs.pop()
                freed_bytes += _retained_bytes(sig)
                freed_signals += 1
                self._pending_signals -= 1
                del sig
            if not sigs:
                self._groups.popleft()
                if self._on_finished is not None:
                    self._on_finished(key)
        if not self._groups:
            self._timer.stop()
```

- [ ] **Step 4: 通ることを確認 + 既存 teardown テスト全通過**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

`signal_budget` の条件を `_drain` から一時的に外し、
`test_one_tick_never_frees_more_than_the_signal_budget` が **FAIL** する
（1 ティックで 1000 信号すべて解放される）ことを確認してから戻す。**結果を報告に記す。**

- [ ] **Step 6: ゲート＋コミット**

```bash
git add src/valisync/gui/workers/teardown_service.py tests/gui/test_teardown_pacing.py
git commit -m "fix(gui): teardown を二軸ペーシング化 (8,000 信号/tick で 649ms フリーズを防ぐ)"
```

---

## Task 4: 会計の identity dedup（master の 5 万倍過大計上を是正）

**Files:**
- Modify: `src/valisync/core/models/sample_source.py`（`array_if_materialized` 追加）
- Modify: `src/valisync/gui/workers/teardown_service.py`（`_retained_bytes`）
- Test: `tests/gui/test_teardown_pacing.py`

**Interfaces:**
- Produces: `SampleSource.array_if_materialized() -> np.ndarray | None`（**展開を誘発しない**・
  未展開なら `None`）。会計はこれで id-dedup する。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_teardown_pacing.py` に追記:

```python
def test_shared_master_is_counted_once_per_group(qtbot) -> None:  # type: ignore[no-untyped-def]
    """master はグループ内で identity 共有。信号ごとに数えると 5 万倍過大になる。"""
    svc = TeardownService()
    group = _lazy_group(100)  # 全 Signal が同一の timestamps オブジェクトを共有
    master_nbytes = group.signals[0].timestamps.nbytes
    svc.enqueue("k", group)
    total = svc.pending_bytes()
    # 100 信号ぶん (100 * master) ではなく master 1 本ぶんに近いこと
    assert total < master_nbytes * 5, f"{total} bytes — master を信号ごとに計上している"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_teardown_pacing.py::test_shared_master_is_counted_once_per_group -q`
Expected: FAIL（100 倍計上されている）

- [ ] **Step 3: `array_if_materialized` を足して会計を dedup 化**

`sample_source.py` の `SampleSource` プロトコルと両実装に:

```python
    def array_if_materialized(self) -> np.ndarray | None:
        """展開済みなら値配列、未展開なら None (**展開は誘発しない**).

        nbytes_if_materialized は数値しか返さないので id-dedup ができない。
        teardown 会計が共有配列を二重計上しないために同一性が要る。
        """
```

`EagerValues` は常に `self._array`、`LazyMdfValues` は `self._cache`（未展開なら `None`）。

`teardown_service.py` の会計を、**グループ単位で id を跨いで dedup** する形へ:

```python
def _retained_bytes(sig: Signal, seen: set[int]) -> int:
    """この Signal が保持しているバイト数 (既に数えた配列は id で除外).

    master はグループ内で identity 共有されるので、信号ごとに数えると prod_demo で
    実体 0.2 MiB に対し 10,316 MiB (約 5 万倍) を計上してしまう。
    """
```

`_drain`/`pending_bytes` は `seen: set[int]` を持ち回す（`pending_bytes` は呼び出しごとに
新しい `seen` を作る）。**未展開信号の `sig.values` は絶対に読まない**（増分A の契約）。

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS（既存の teardown テストも含む）

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/core/models/sample_source.py src/valisync/gui/workers/teardown_service.py tests/gui/test_teardown_pacing.py
git commit -m "fix(gui): teardown 会計を identity dedup 化 (共有 master の 5 万倍過大計上を是正)"
```

---

## Task 5: `_discard` を teardown 経路へ・エクスポート中の unload を明示ガード

**Files:**
- Modify: `src/valisync/gui/workers/export_worker.py`（`is_busy`）
- Modify: `src/valisync/gui/views/main_window.py`（`_discard`・unload ガード）
- Test: `tests/gui/test_discard_and_export_guard.py`（新規）

**Interfaces:**
- Produces: `ExportController.is_busy() -> bool`（`self._active` が空でないか）

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_discard_and_export_guard.py`:

```python
"""_discard の同期解放と、エクスポート中 unload の明示ガード (増分B)。"""

from __future__ import annotations


def test_export_controller_reports_busy_while_a_worker_is_active(qtbot) -> None:  # type: ignore[no-untyped-def]
    from valisync.gui.workers.export_worker import ExportController

    ctrl = ExportController()
    assert ctrl.is_busy() is False
    # 実行中ワーカーを 1 つ登録した状態を作る (実 submit は I/O を伴うため
    # 内部集合を使う — 実装に合わせて調整すること)
    ...
```

> 実装者へ: `ExportController` の実 API（`submit` のシグネチャ・`_active` の中身）を読み、
> **実際に submit して busy になることを確認する形**にできるならそちらを優先すること
> （内部集合を直接いじるテストは最後の手段）。`is_busy` が「実行中に True」を返すことと、
> 完了後に False へ戻ることの両方を assert する。
>
> unload ガードのテストは、`MainWindow` を組み立ててエクスポート中に unload を試み、
> **拒否されて（ステータス/ダイアログで通知され）グループが残る**ことを assert する。
> 実 API 名は現行コードに合わせる。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_discard_and_export_guard.py -q`
Expected: FAIL（`is_busy` 未定義）

- [ ] **Step 3: `is_busy` と unload ガードを実装**

`export_worker.py`:

```python
    def is_busy(self) -> bool:
        """エクスポートが実行中か (増分B: unload ガードの判定に使う)."""
        return bool(self._active)
```

`main_window.py` の unload 入口に:

```python
        # 増分B: エクスポート中の unload はハンドルを閉じ、実行中の select を
        # SampleReadError で殺す。今日は BusyOverlay が偶然クリックを遮っている
        # だけなので、明示的に拒否して「偶然」への依存をやめる。
        if self._export_controller.is_busy():
            self.set_status_message(S.UNLOAD_BLOCKED_BY_EXPORT)
            return
```

`strings.py` に `UNLOAD_BLOCKED_BY_EXPORT`（例:「エクスポート中はファイルを閉じられません」）を追加。

- [ ] **Step 4: `_discard` を teardown 経路へ**

`main_window.py:609-612` の `_discard` は `remove_group` の戻り値を捨てている。
Task 1 で close は自動的に効くようになるが、**遅延解放が無いままだと 330k シェルを
GUI スレッドで同期解放（実測 649ms）**する。`TeardownService` へ渡す形にする。
`_discard` はファイルを register していないので、`'releasing'` スピナーを出さない
経路が要る（`enqueue` に `announce: bool = True` を足すか、`AppViewModel` を経由しない
直接 enqueue にする — **どちらでもよいが、FileBrowser に幽霊行が出ないこと**を
テストで確認すること）。

- [ ] **Step 5: 通ることを確認**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS

- [ ] **Step 6: ゲート＋コミット**

```bash
git add src/valisync/gui/workers/export_worker.py src/valisync/gui/views/main_window.py src/valisync/gui/strings.py tests/gui/test_discard_and_export_guard.py
git commit -m "fix(gui): _discard を teardown 経路へ・エクスポート中の unload を明示ガード"
```

---

## Task 6: 繰越 Minor 3 件（excepthook dedup・`_closed` アトミック化・double-checked read）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（excepthook）
- Modify: `src/valisync/core/loaders/mdf_handle.py`（`_closed`）
- Modify: `src/valisync/core/models/sample_source.py`（`array()`）
- Test: 既存の該当テストへ追記

- [ ] **Step 1: 失敗テストを書く**

3 件それぞれに:
1. **excepthook dedup**: 同じ `signal_key` で `SampleReadError` を 2 回起こしても診断は 1 件。
   ラベルが固定文字列でなく**実ファイル basename** になる（render 境界＝
   `graph_panel_vm.py:1656-1684` と同じ規約）。
2. **`_closed` アトミック化**: 2 スレッドから同時に `close()` しても `mdf.close()` は 1 回だけ
   （スパイで回数を数える）。
3. **double-checked read**: キャッシュ済みの `array()` が `handle.lock` を取らない
   （lock を取得済みの別スレッドがいてもブロックしない／lock 取得をスパイして 0 回）。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/ tests/core/ -q`（新規 3 件が FAIL）

- [ ] **Step 3: 実装**

1. excepthook は `GraphPanelVM._read_error_reported` と同型の dedup セット＋
   `Path(source_file).name` をラベルに。
2. `MdfHandle` の `_closed` を `threading.Lock` 下の check-and-set にする**が、
   フラグを立てる位置は lock の外のまま**（Global Constraints の理由）。
   ※ ここで使うのは close 専用の小さい lock で、読み直列化用の `handle.lock` とは別物。
   同じ lock を使うと in-flight read を待って GUI が固まる。
3. `LazyMdfValues.array()` の先頭で lock を取る前にキャッシュを見る:

```python
        cached = self._cache
        if cached is not None:
            return cached  # double-checked: ヒットは lock 不要 (代入は 1 回だけ・GIL 下で atomic)
        with self._handle.lock:
            ...
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/ tests/gui/ -q`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/gui/views/main_window.py src/valisync/core/loaders/mdf_handle.py src/valisync/core/models/sample_source.py tests/
git commit -m "fix: 繰越 Minor 3 件 (excepthook dedup・_closed アトミック化・キャッシュヒットの lock 回避)"
```

---

## Task 7: ①gate realgui ＋ 実測（受け入れ）

**Files:**
- Create: `tests/realgui/test_unload_releases_file_realclick.py`

- [ ] **Step 1: realgui テストを書く**

実ディスプレイで実 mf4 をロード → **実クリックで unload** → **その場でファイルを削除できる**
（実 OS の `os.remove`）ことを assert。さらにエクスポート中は unload が**拒否される**ことも
実操作で確認する。共有 `tests/realgui/_realgui_input` を使い、**実マウスドラッグは使わない**。

- [ ] **Step 2: 実行して実機 pass を確認**

Run: `uv run pytest --realgui tests/realgui/test_unload_releases_file_realclick.py -q`
Expected: PASS

- [ ] **Step 3: ドレインのフリーズを実測**

`scripts/measure_lazy_footprint.py` に「prod_demo をロード → unload → ドレイン完了までの
**最大ティック時間**」を出す段を足し、実行する。**最大ティックが ~16ms 前後**に収まることを
確認する（8,000 信号/tick の設計値）。数値を報告と PR 本文に記録。

- [ ] **Step 4: フルゲート＋コミット**

Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/`

```bash
git add tests/realgui/test_unload_releases_file_realclick.py scripts/measure_lazy_footprint.py
git commit -m "test(gui): 増分B の ①gate realgui ＋ドレインのティック時間実測"
```

---

## Self-Review（プラン著者チェック）

- **Spec coverage（増分B）**: close の `remove_group` 配置＝Task 1／登録失敗のリーク＝Task 2／
  二軸ペーシング＝Task 3／会計の identity dedup＝Task 4／`_discard` と export ガード＝Task 5／
  繰越 Minor 3 件＝Task 6／①gate と実測＝Task 7。
- **意図的にプラン外**: `RemovalResult.removed_columns` の配線（E-3 の完了定義）・
  `MainWindow.closeEvent` での一括 close（Session 列挙 API が要る・YAGNI）・
  MDF3 が開けない defect（ユーザー決定 4 で follow-up）。
- **型整合**: `MdfHandle.close()/is_closed`・`SampleSource.array_if_materialized()`・
  `TeardownService(signal_budget=)`・`ExportController.is_busy()` は全 Task で一貫。
- **Placeholder**: Task 5 Step 1 のテストは実 API を読んでから書くよう明示指示している
  （`ExportController` の submit シグネチャに依存するため）。それ以外は具体コードつき。

> **実装上の注意**: Task 3 Step 5 の sabotage（信号数上限を外すと 1 ティックで全部解放される
> ことの実証）は**必須ステップ**。この増分の存在理由そのものなので、証明できないなら
> 実装が効いていない。
