# FU-08 信号マップ・キャッシュ化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `SignalGroupManager` に namespaced 信号マップをキャッシュし、大容量ファイルで信号1本プロット時の ~8秒フリーズ（`_signal_map` の264k全走査）を ~数十ms に解消する。

**Architecture:** `SignalGroupManager` が namespaced 信号の list（重複保持）と `{name: Signal}` map（dedupe）を遅延構築・キャッシュし、`add()`/`remove()` でのみ無効化する。`Session.signal_map()` が委譲を公開し、`GraphPanelVM._signal_map()` は常態（オフセット無し）でキャッシュを読取専用ゼロコピー返し、稀なオフセット時のみ該当信号を `apply_offset` で上書きする。

**Tech Stack:** Python 3.13、PySide6（Qt6）、numpy、pytest。コアは純ロジック、VM は MVVM の ViewModel（Qt ウィジェット非依存）。

## Global Constraints

- **不変性厳守**: `Signal` は frozen（`timestamps`/`values` は `writeable=False`）。namespaced ラッパーもキャッシュ後は不変扱い。
- **`_sorted_view_delegate` 禁則**: `apply_offset` が返す別配列 Signal には `_sorted_view_delegate` を**付けない**（`signal_group_manager.py:83-88` の不変条件）。既存 `_namespaced` のみが delegate を設定する。
- **キャッシュ無効化点は `add()`/`remove()` のみ**（`_groups` の唯一の変異点）。
- **`signals()` の現行セマンティクス厳守**: list を返し重複名を保持（dedupe しない）。`signal_map()` は dict で last-wins dedupe（既存 `_signal_map` と同一）。
- **GUI 入力経路の変更なし = Layer A（ヘッドレス単体）のみ**。realgui 不要（`docs/gui-testing-layers.md`）。
- **品質ゲート**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` を全通過。
- 既存挙動（オートフィットのレンジ結果）は不変。

---

### Task 1: SignalGroupManager に namespaced list/map キャッシュ＋`signal_map()`＋無効化

**Files:**
- Modify: `src/valisync/core/loaders/signal_group_manager.py`
- Test: `tests/test_signal_group_manager_cache.py`（新規）

**Interfaces:**
- Consumes: 既存 `SignalGroupManager.add(group) -> str`、`remove(key) -> SignalGroup`、`_namespaced(key, group) -> list[Signal]`、`_groups: dict[str, SignalGroup]`。
- Produces:
  - `SignalGroupManager.signals() -> list[Signal]`（キャッシュ由来・重複保持・毎回新規リスト）
  - `SignalGroupManager.signal_map() -> Mapping[str, Signal]`（`MappingProxyType`・dedupe・読取専用）
  - 内部: `self._namespaced_list: list[Signal] | None`、`self._namespaced_map: dict[str, Signal] | None`、`self._ensure_namespaced() -> None`

- [ ] **Step 1: Write the failing tests**

`tests/test_signal_group_manager_cache.py` を新規作成:

```python
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup


def _sig(name: str, vs: list[float]) -> Signal:
    n = len(vs)
    return Signal(
        name=name,
        timestamps=np.arange(n, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={},
    )


def _group(signals: list[Signal]) -> SignalGroup:
    return SignalGroup(
        signals=tuple(signals),
        source_path=Path("f.mf4"),
        file_format="MDF4",
        loaded_at=datetime.now(),
    )


def test_signal_map_content_and_namespacing() -> None:
    m = SignalGroupManager()
    key = m.add(_group([_sig("a", [1.0]), _sig("b", [2.0])]))
    sm = m.signal_map()
    assert set(sm.keys()) == {f"{key}::a", f"{key}::b"}
    assert [s.name for s in m.signals()] == [f"{key}::a", f"{key}::b"]


def test_signals_reflects_add_and_remove() -> None:
    m = SignalGroupManager()
    k1 = m.add(_group([_sig("a", [1.0])]))
    assert {s.name for s in m.signals()} == {f"{k1}::a"}
    k2 = m.add(_group([_sig("c", [3.0])]))
    assert {s.name for s in m.signals()} == {f"{k1}::a", f"{k2}::c"}
    m.remove(k1)
    assert {s.name for s in m.signals()} == {f"{k2}::c"}


def test_repeated_calls_reuse_same_wrapper() -> None:
    m = SignalGroupManager()
    key = m.add(_group([_sig("a", [1.0])]))
    assert m.signal_map()[f"{key}::a"] is m.signal_map()[f"{key}::a"]
    assert m.signals()[0] is m.signals()[0]


def test_signal_map_is_read_only() -> None:
    m = SignalGroupManager()
    key = m.add(_group([_sig("a", [1.0])]))
    sm = m.signal_map()
    assert isinstance(sm, MappingProxyType)
    with pytest.raises(TypeError):
        sm[f"{key}::a"] = _sig("x", [0.0])  # type: ignore[index]


def test_build_runs_once_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    m = SignalGroupManager()
    m.add(_group([_sig("a", [1.0]), _sig("b", [2.0])]))
    m.signals()  # ウォーム: 初回アクセスで構築を済ませる
    calls: list[str] = []
    orig = SignalGroupManager._namespaced

    def spy(key: str, group: SignalGroup) -> list[Signal]:
        calls.append(key)
        return orig(key, group)

    monkeypatch.setattr(SignalGroupManager, "_namespaced", staticmethod(spy))
    for _ in range(5):
        m.signals()
        m.signal_map()
    assert calls == []  # ウォーム済みキャッシュ→反復呼出で再構築ゼロ


def test_build_runs_once_at_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    # 大 group でも構築は1回のみ（O(N) 再構築の回帰を決定的に検出）
    m = SignalGroupManager()
    calls: list[str] = []
    orig = SignalGroupManager._namespaced

    def spy(key: str, group: SignalGroup) -> list[Signal]:
        calls.append(key)
        return orig(key, group)

    monkeypatch.setattr(SignalGroupManager, "_namespaced", staticmethod(spy))
    m.add(_group([_sig(f"s{i}", [float(i)]) for i in range(5000)]))
    for _ in range(10):
        m.signals()
        m.signal_map()
    assert len(calls) == 1  # 5000信号でも _namespaced 呼出は group あたり1回きり
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_signal_group_manager_cache.py -v`
Expected: FAIL（`signal_map` 属性なし／`test_build_runs_once_*` は現行の毎回再構築で calls が増える）

- [ ] **Step 3: Implement the cache**

`src/valisync/core/loaders/signal_group_manager.py` を編集。ファイル冒頭の import に追加:

```python
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from valisync.core.models import Signal, SignalGroup
```

`__init__` にキャッシュ用フィールドを追加:

```python
    def __init__(self) -> None:
        self._groups: dict[str, SignalGroup] = {}
        self._counters: dict[str, int] = {}
        self._namespaced_list: list[Signal] | None = None
        self._namespaced_map: dict[str, Signal] | None = None
```

`add()` の末尾（`return key` の直前）と `remove()` の `pop` 成功後にキャッシュ無効化を挿入。`add()`:

```python
        self._groups[key] = group
        self._invalidate_namespaced()
        return key
```

`remove()`:

```python
        try:
            group = self._groups.pop(key)
        except KeyError:
            raise KeyError(f"no Signal_Group registered under key: {key!r}") from None
        self._invalidate_namespaced()
        return group
```

無効化ヘルパと遅延構築を追加（`_namespaced` の直後あたり）:

```python
    def _invalidate_namespaced(self) -> None:
        """Drop the namespaced caches; rebuilt lazily on next access."""
        self._namespaced_list = None
        self._namespaced_map = None

    def _ensure_namespaced(self) -> None:
        """Build and cache the namespaced signal list/map once (idempotent).

        The expensive work — creating one namespaced Signal wrapper per signal
        across all groups — happens here a single time per load/unload, not on
        every ``signals()``/``signal_map()`` call (FU-08). The list preserves
        every signal (duplicate namespaced names included); the map is keyed by
        name with last-wins dedupe, matching the historical ``signals()``-to-dict
        behaviour its callers relied on.
        """
        if self._namespaced_list is not None:
            return
        result: list[Signal] = []
        for key, group in self._groups.items():
            result.extend(self._namespaced(key, group))
        self._namespaced_list = result
        self._namespaced_map = {sig.name: sig for sig in result}
```

`signals()` をキャッシュ由来に置換し、`signal_map()` を新設:

```python
    def signals(self) -> list[Signal]:
        """Return every signal across all groups, name-spaced by its group key."""
        self._ensure_namespaced()
        assert self._namespaced_list is not None
        return list(self._namespaced_list)

    def signal_map(self) -> Mapping[str, Signal]:
        """Read-only ``{namespaced_name: Signal}`` view, cached (FU-08).

        Last-wins on duplicate namespaced names (same as building a dict from
        ``signals()``). Returned as a ``MappingProxyType`` so callers cannot
        mutate — and corrupt — the shared cache.
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        return MappingProxyType(self._namespaced_map)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_signal_group_manager_cache.py -v`
Expected: PASS（6件）

- [ ] **Step 5: Run the broader core suite + gates**

Run: `uv run pytest tests/test_session.py tests/test_pbt_sync.py -q && uv run ruff check src/valisync/core/loaders/signal_group_manager.py && uv run mypy src/valisync/core/loaders/signal_group_manager.py`
Expected: PASS / no errors（既存の `signals()` 利用が壊れていない）

- [ ] **Step 6: Commit**

```bash
git add src/valisync/core/loaders/signal_group_manager.py tests/test_signal_group_manager_cache.py
git commit -m "perf(core): SignalGroupManager に namespaced list/map をキャッシュ（FU-08 Task1）"
```

---

### Task 2: `Session.signal_map()` 委譲を追加

**Files:**
- Modify: `src/valisync/core/session.py`
- Test: `tests/test_session_signal_map.py`（新規）

**Interfaces:**
- Consumes: Task 1 の `SignalGroupManager.signal_map() -> Mapping[str, Signal]`、既存 `Session._groups`、`Session.signals()`、`Session.load()`。
- Produces: `Session.signal_map() -> Mapping[str, Signal]`

- [ ] **Step 1: Write the failing test**

`tests/test_session_signal_map.py` を新規作成:

```python
from pathlib import Path
from types import MappingProxyType

import pytest

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session

_FMT = FormatDefinition(
    name="fmt",
    delimiter=Delimiter.COMMA,
    timestamp_column=0,
    timestamp_unit="sec",
    signal_start_column=1,
    signal_end_column=2,
    has_header=True,
)


def _load_two(tmp_path: Path) -> Session:
    csv = tmp_path / "d.csv"
    rows = ["t,s1,s2"] + [f"{i * 0.1:.1f},{i}.0,{i * 2}.0" for i in range(5)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    session = Session()
    session.load(csv, _FMT)
    return session


def test_signal_map_matches_signals(tmp_path: Path) -> None:
    session = _load_two(tmp_path)
    sm = session.signal_map()
    assert set(sm.keys()) == {s.name for s in session.signals()}


def test_signal_map_is_read_only(tmp_path: Path) -> None:
    session = _load_two(tmp_path)
    sm = session.signal_map()
    assert isinstance(sm, MappingProxyType)
    with pytest.raises(TypeError):
        sm["x"] = None  # type: ignore[index]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session_signal_map.py -v`
Expected: FAIL（`Session` に `signal_map` 属性なし）

- [ ] **Step 3: Implement the delegation**

`src/valisync/core/session.py` の import に `Mapping` を追加（既存 import 群へ）:

```python
from collections.abc import Mapping
```

`signals()`（L188 付近）の直後に追加:

```python
    def signal_map(self) -> Mapping[str, Signal]:
        """Read-only ``{namespaced_name: Signal}`` view over all loaded signals.

        Cached at the SignalGroupManager level and rebuilt only on load/unload
        (FU-08) — callers on the autofit hot path avoid re-walking every signal.
        """
        return self._groups.signal_map()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_session_signal_map.py -v`
Expected: PASS（2件）

- [ ] **Step 5: Gates**

Run: `uv run ruff check src/valisync/core/session.py && uv run mypy src/valisync/core/session.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/valisync/core/session.py tests/test_session_signal_map.py
git commit -m "perf(core): Session.signal_map() 委譲を追加（FU-08 Task2）"
```

---

### Task 3: `GraphPanelVM._signal_map()` をキャッシュ利用へ＋オフセット上書き

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`_signal_map` = L1220 付近）
- Test: `tests/gui/test_graph_panel_signal_map_cache.py`（新規）

**Interfaces:**
- Consumes: Task 2 の `Session.signal_map() -> Mapping[str, Signal]`、既存 `Session.apply_offset(signal, file_offset=0.0, signal_offset=0.0) -> Signal`、`GraphPanelVM(session)`、`GraphPanelVM.set_offsets(signal_offsets, file_offsets)`、`add_signal_to_axis(key, axis)`、`reset_y()`、`reset_axis_y(i)`。
- Produces: `GraphPanelVM._signal_map(self) -> Mapping[str, Signal]`（返り値は読取専用マッピング）

- [ ] **Step 1: Write the failing tests**

`tests/gui/test_graph_panel_signal_map_cache.py` を新規作成:

```python
from pathlib import Path

import numpy as np
import pytest

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

_FMT = FormatDefinition(
    name="fmt",
    delimiter=Delimiter.COMMA,
    timestamp_column=0,
    timestamp_unit="sec",
    signal_start_column=1,
    signal_end_column=2,
    has_header=True,
)


def _vm_two(tmp_path: Path) -> tuple[GraphPanelVM, list[str], Session]:
    csv = tmp_path / "d.csv"
    rows = ["t,s1,s2"] + [f"{i * 0.1:.1f},{i}.0,{(i + 10)}.0" for i in range(5)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    session = Session()
    session.load(csv, _FMT)
    keys = sorted(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(keys[0], 0)
    vm.add_signal_to_axis(keys[1], 0)
    return vm, keys, session


def test_no_offset_returns_base_wrappers(tmp_path: Path) -> None:
    vm, keys, session = _vm_two(tmp_path)
    sm = vm._signal_map()
    assert sm[keys[0]] is session.signal_map()[keys[0]]  # ゼロコピー（同一ラッパー）


def test_signal_offset_applies_to_target_only(tmp_path: Path) -> None:
    vm, keys, session = _vm_two(tmp_path)
    base0 = session.signal_map()[keys[0]]
    vm.set_offsets({keys[0]: 0.5}, {})
    sm = vm._signal_map()
    np.testing.assert_allclose(sm[keys[0]].timestamps, base0.timestamps + 0.5)
    assert sm[keys[1]] is session.signal_map()[keys[1]]  # 非対象は base のまま


def test_file_offset_applies_group_wide(tmp_path: Path) -> None:
    vm, keys, session = _vm_two(tmp_path)
    group_key = keys[0].split("::", 1)[0]
    base0 = session.signal_map()[keys[0]]
    base1 = session.signal_map()[keys[1]]
    vm.set_offsets({}, {group_key: 0.3})
    sm = vm._signal_map()
    np.testing.assert_allclose(sm[keys[0]].timestamps, base0.timestamps + 0.3)
    np.testing.assert_allclose(sm[keys[1]].timestamps, base1.timestamps + 0.3)


def test_reset_y_covers_signal_range(tmp_path: Path) -> None:
    vm, keys, _ = _vm_two(tmp_path)
    vm.reset_y()
    lo, hi = vm._axes[0].y_range
    assert lo is not None and hi is not None
    # 2信号 s1(0..4) と s2(10..14) の和集合を内包
    assert lo <= 0.0 and hi >= 14.0


def test_map_built_once_across_add_and_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from valisync.core.loaders.signal_group_manager import SignalGroupManager

    vm, keys, _ = _vm_two(tmp_path)
    calls: list[str] = []
    orig = SignalGroupManager._namespaced

    def spy(key: str, group: object) -> list:  # type: ignore[type-arg]
        calls.append(key)
        return orig(key, group)  # type: ignore[arg-type]

    monkeypatch.setattr(SignalGroupManager, "_namespaced", staticmethod(spy))
    for _ in range(5):
        vm.reset_y()
        vm.reset_axis_y(0)
    assert calls == []  # add_signal 時点で構築済み→autofit 群では再構築ゼロ
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gui/test_graph_panel_signal_map_cache.py -v`
Expected: FAIL（`test_no_offset_returns_base_wrappers` は現行が新規 dict を作るため同一性不成立／`test_map_built_once...` は毎回 `session.signals()`→`_namespaced` 再走査で calls が増える）

- [ ] **Step 3: Rewrite `_signal_map()` to use the cache**

`src/valisync/gui/viewmodels/graph_panel_vm.py` の import に `Mapping` を追加（既存 typing/collections import 群へ。未あれば）:

```python
from collections.abc import Mapping
```

`_signal_map()`（L1220 付近）本体を置換:

```python
    def _signal_map(self) -> Mapping[str, Signal]:
        """Return {signal.name: signal} with stored time offsets applied (R14).

        Fast path (no offsets, the norm): return the Session's cached read-only
        map unchanged — no per-call rebuild of the 264k-entry map (FU-08). Only
        when an offset is set do we shallow-overlay the affected signals via the
        pure Session.apply_offset; a zero total leaves the base wrapper in place.
        Group key is the prefix before '::' (same convention as Session).
        """
        base = self._session.signal_map()
        if not self._file_offsets and not self._signal_offsets:
            return base
        result: dict[str, Signal] = {}
        for name, sig in base.items():
            group_key = name.split("::", 1)[0]
            file_off = self._file_offsets.get(group_key, 0.0)
            sig_off = self._signal_offsets.get(name, 0.0)
            if file_off or sig_off:
                result[name] = self._session.apply_offset(
                    sig, file_offset=file_off, signal_offset=sig_off
                )
            else:
                result[name] = sig
        return result
```

- [ ] **Step 4: Verify all 9 call sites tolerate a read-only Mapping**

`_signal_map()` の返り値が読取専用（`MappingProxyType`）になり得るため、破壊的操作していないか確認。

Run: `grep -n "_signal_map()" src/valisync/gui/viewmodels/graph_panel_vm.py`
各呼び出し元（L249/643/706/725/787/960/1038/1113/1246 付近）が `.get(...)` / 反復のみで、`sig_map[...] = ...`・`.pop`・`.update` 等の破壊的操作をしていないことを目視確認。破壊的に使う箇所があれば、その箇所でのみ `dict(self._signal_map())` に変換する（キャッシュは汚さない）。確認結果を報告に記載。

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/gui/test_graph_panel_signal_map_cache.py -v`
Expected: PASS（5件）

- [ ] **Step 6: Run GUI VM regression suites + gates**

Run: `uv run pytest tests/gui/test_graph_panel_offset_drag.py tests/gui/test_graph_panel_multi_axis.py tests/gui/test_graph_area_vm_offsets.py tests/gui/test_graph_panel_plotted_keys.py -q && uv run ruff check src/valisync/gui/viewmodels/graph_panel_vm.py && uv run mypy src/valisync/gui/viewmodels/graph_panel_vm.py`
Expected: PASS / no errors（オフセット・オートフィット・マルチ軸の既存挙動が不変）

- [ ] **Step 7: Commit**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_signal_map_cache.py
git commit -m "perf(gui): _signal_map をキャッシュ利用へ・オフセットは該当のみ上書き（FU-08 Task3）"
```

---

### Task 4: 全体ゲート＋prod 実機再計測（成功基準の検証）

**Files:**
- Test: 既存スイート全体（変更なし）
- 参照: `docs/audit-findings-catalog.md`（FU-08 行）

**Interfaces:**
- Consumes: Task 1–3 の実装。

- [ ] **Step 1: 全品質ゲート**

Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / no errors（0 failures・0 errors）

- [ ] **Step 2: prod 実機再計測（手動・成功基準）**

`demo_data/prod_demo.mf4` が存在する環境で、信号追加と `reset_y` が **~数十ms** に改善したことを確認（現行 8000ms/5400ms からの2桁改善）。計測ハーネス例（`add_signal` の per-add 時間・`reset_y()` 中央値を出力）を一時スクリプトで実行し、結果を報告に記載。prod 非在の環境では「合成5000信号の Task1/Task3 build-once テストで代替済み」と明記（`~数十ms` 目標はマシン依存のため CI 化しない）。

- [ ] **Step 3: カタログ更新（FU-08 を解消済みへ）**

`docs/audit-findings-catalog.md` の FU-08 行の重要度を `✅完了` に変更し、末尾に「PR #XX で解消（SignalGroupManager キャッシュ化・prod 実測 ~数十ms）」を追記。SS-FOLLOWUP イントロの FU-08 記述も完了へ更新。

- [ ] **Step 4: Commit**

```bash
git add docs/audit-findings-catalog.md
git commit -m "docs(catalog): FU-08 を解消済みへ更新（SignalGroupManager キャッシュ化）"
```

---

## Self-Review

**1. Spec coverage:**
- コアキャッシュ（① SignalGroupManager）→ Task 1。`signal_map()` を `MappingProxyType` 読取専用・`add`/`remove` 無効化・順序保存・重複保持（list）／dedupe（map）→ Task 1 で網羅。
- ② Session.signal_map() 委譲 → Task 2。
- ③ GraphPanelVM._signal_map() ゼロコピー常態＋オフセット上書き・delegate 禁則 → Task 3（`apply_offset` は別配列 Signal を返し delegate を付けないため不変条件遵守）。
- テスト（内容/順序・invalidation・同一ラッパー・MappingProxy 読取専用・オフセット適用・レンジ不変・build-once スパイ）→ Task 1/2/3 に配置。全9呼び出し元の読取専用確認 → Task 3 Step 4。
- perf 回帰ガード → **決定的な build-once スパイ（Task1 scale 5000＋Task3 add/reset）で実現**（flaky な wall-clock 閾値テストは CI 不採用）。成功基準 `~数十ms` は Task 4 の prod 手動計測で検証。**（spec の「合成5万で <100ms」を、決定的で非フレークな build-once 検証＋手動 prod 計測に置換。同一の回帰＝O(N) 再構築の復活を確実に捕捉する上位互換。）**

**2. Placeholder scan:** TBD/TODO/「適切に処理」等なし。全テスト・実装コードは実体を記載。PR 番号のみ Task 4 Step 3 で後埋め（マージ時に確定＝正当）。

**3. Type consistency:** `signal_map() -> Mapping[str, Signal]`（SignalGroupManager / Session / GraphPanelVM で一貫）。`_ensure_namespaced()`・`_invalidate_namespaced()`・`_namespaced_list`/`_namespaced_map` は Task 1 内で一貫。`set_offsets(signal_offsets, file_offsets)`・`apply_offset(signal, file_offset=, signal_offset=)` は実シグネチャに一致。
