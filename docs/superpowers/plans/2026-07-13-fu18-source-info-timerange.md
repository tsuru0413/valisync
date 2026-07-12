# FU-18 source_info time-range Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Session.source_info` の t_min/t_max 算出を全信号 `sorted_view()` から生 timestamps min/max ＋ master id() dedup に置換し、ソース情報 hover のフリーズ（prod 264k で 7689ms/+4.69GB）を 0ms/0GB にする。

**Architecture:** `Signal` に「sorted_view を誘発せず生 timestamps の (min,max) を返す」ガードレール `time_range()` を新設。`source_info` は channel-group 内で共有される master timestamps を `id()` で dedup し、unique master ごとに1回だけ `time_range()` を呼ぶ。sorted_view の argsort・float64 upcast・per-Signal キャッシュ汚染を全撤去（FU-20 の native dtype メモリ勝ちを守る）。

**Tech Stack:** Python 3.12/3.13・numpy・pytest。core は Qt 非依存。

## Global Constraints

（spec `docs/superpowers/specs/2026-07-13-fu18-source-info-timerange-design.md` から）

- **core は Qt 非依存を維持**（`signal.py`・`session.py` に Qt import を入れない）。
- **engine.py は変更しない** — `_compute_result_timestamps` は `:328-329` で refs の sorted_view を union グリッド構築に本当に使うため、範囲取得を time_range() に置換しても blowup を回避できない（スコープクリープ）。
- **`SourceInfo` 型・フィールド・戻り値契約は不変**（`full_path`/`size_bytes`/`t_min`/`t_max`/`n_channels`/`file_format`）。
- **`sorted_view()`/`finite_view()`/FU-20 の native dtype 保持は不変**（本 PR で触れない）。
- **VM・GUI・hover 配線は不変**（`file_browser_vm`/`qt_signal_models` を変更しない）。
- **`size_bytes` は毎回 `source_path.stat().st_size`**（揮発値・キャッシュしない）。
- **空信号ガード維持**（`len(s.timestamps)` 0 の信号は範囲に寄与しない・channel 数には数える）。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過をコミット前に。

---

### Task 1: `Signal.time_range()` ガードレールヘルパ

**Files:**
- Modify: `src/valisync/core/models/signal.py`（`Signal` にメソッド追加・`is_monotonic` プロパティの前後どちらでも可）
- Test: `tests/test_signal_sorted_view.py`（既存 `_sig` helper を再利用）

**Interfaces:**
- Consumes: 既存 `_sig(ts, vs)` helper（`tests/test_signal_sorted_view.py:15`）。
- Produces: `Signal.time_range(self) -> tuple[float, float] | None` — 空なら None・それ以外は `(float(timestamps.min()), float(timestamps.max()))`。**sorted_view() を呼ばない**（`_sorted_view_cache` を populate しない）。Task 2 が使う。

- [ ] **Step 1: Write the failing tests**

`tests/test_signal_sorted_view.py` の末尾に追記:

```python
def test_time_range_returns_raw_min_max():
    sig = _sig([0.0, 1.0, 2.0], [10.0, 20.0, 30.0])
    assert sig.time_range() == (0.0, 2.0)


def test_time_range_non_monotonic_uses_raw_extremes():
    # 非単調でも生 min/max（ソート不要）
    sig = _sig([5.0, 1.0, 3.0], [1.0, 2.0, 3.0])
    assert sig.time_range() == (1.0, 5.0)


def test_time_range_empty_is_none():
    sig = _sig([], [])
    assert sig.time_range() is None


def test_time_range_does_not_trigger_sorted_view():
    # ガードレールの核: 範囲取得が float64 値キャッシュを materialize しない
    sig = _sig([5.0, 1.0, 3.0], [1.0, 2.0, 3.0])
    sig.time_range()
    assert getattr(sig, "_sorted_view_cache", None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_signal_sorted_view.py -k time_range -v`
Expected: FAIL（`AttributeError: 'Signal' object has no attribute 'time_range'`）

- [ ] **Step 3: Implement `time_range()`**

`src/valisync/core/models/signal.py` の `Signal` クラス内（`is_monotonic` プロパティの直前）に追加:

```python
    def time_range(self) -> tuple[float, float] | None:
        """Raw ``(min, max)`` timestamp without materialising ``sorted_view()``.

        Cheap time-range accessor for metadata surfaces (e.g. ``source_info``).
        Reads the raw timestamps deliberately — NOT ``sorted_view()[0][0]/[-1]``
        — so it never upcasts values to float64 or populates the per-Signal
        cache. That matters at prod scale: ``source_info`` walks every signal
        (264k), and routing that through ``sorted_view`` would re-inflate the
        native dtype 8x and undo FU-20 (FU-18). Timestamps are finite by
        construction (``__post_init__`` guard), so min/max are finite. Returns
        None for an empty signal.
        """
        ts = self.timestamps
        if len(ts) == 0:
            return None
        return (float(ts.min()), float(ts.max()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_signal_sorted_view.py -k time_range -v`
Expected: PASS（4 件）

- [ ] **Step 5: Run gate + commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/core/models/signal.py tests/test_signal_sorted_view.py
git commit -m "feat(core): Signal.time_range() 生 min/max ガードレール(sorted_view 非誘発)"
```

---

### Task 2: `source_info` を master id() dedup ＋ time_range() へ置換

**Files:**
- Modify: `src/valisync/core/session.py:235-241`（`source_info` の t_min/t_max 算出）
- Test: `tests/test_session.py`（既存 `_derived`/`_group_of` helper を再利用）

**Interfaces:**
- Consumes: `Signal.time_range()`（Task 1）・`_derived(name, ts, vs)`（`tests/test_session.py:24`）・`_group_of(signals, source_path)`（`:36`）・`session._groups.add(group) -> key`。
- Produces: 挙動不変の `source_info`（同じ `SourceInfo`）だが内部は sorted_view を呼ばない。後続タスクなし（Task 3 は実測のみ）。

- [ ] **Step 1: Write the failing tests**

`tests/test_session.py` の SourceInfo テスト群（`test_source_info_time_range_non_monotonic` の後、`test_namespaced_wrappers_share_sorted_view_cache` の前あたり）に追記:

```python
def test_source_info_does_not_pollute_sorted_view_cache(tmp_path):
    # source_info は範囲のみ必要 — sorted_view() を呼ぶと全信号の値を float64 へ
    # upcast＋キャッシュし prod で +GB 膨張(FU-18)。sabotage(sorted_view()[0][0]
    # へ復帰)でこの assert が RED になる honest observable。
    master = np.arange(5.0, dtype=np.float64)
    master.flags.writeable = False  # __post_init__ は read-only 配列を共有保持
    sigs = [
        Signal(
            name=f"s{i}",
            timestamps=master,
            values=(np.arange(5, dtype=np.uint8) + i),
            file_format="Derived",
            bus_type="",
            source_file="",
            metadata={},
        )
        for i in range(4)
    ]
    session = Session()
    key = session._groups.add(_group_of(sigs, tmp_path / "shared.csv"))
    session.source_info(key)
    grp = session._groups.group(key)
    assert all(getattr(s, "_sorted_view_cache", None) is None for s in grp.signals)


def test_source_info_time_range_spans_multiple_masters(tmp_path):
    # 独立 master 2本 + 片方は非単調 → 全体の min/max を跨いで集計
    session = Session()
    a = _derived("a", [2.0, 5.0], [1.0, 2.0])
    b = _derived("b", [0.0, 3.0, 1.0], [3.0, 4.0, 5.0])
    key = session._groups.add(_group_of([a, b], tmp_path / "multi.csv"))
    info = session.source_info(key)
    assert info.t_min == 0.0 and info.t_max == 5.0


def test_source_info_ignores_empty_signals_but_counts_them(tmp_path):
    session = Session()
    empty = _derived("e", [], [])
    real = _derived("r", [1.0, 4.0], [10.0, 20.0])
    key = session._groups.add(_group_of([empty, real], tmp_path / "mix.csv"))
    info = session.source_info(key)
    assert info.t_min == 1.0 and info.t_max == 4.0
    assert info.n_channels == 2  # 空信号も channel 数には数える


def test_source_info_time_range_none_when_all_empty(tmp_path):
    session = Session()
    key = session._groups.add(_group_of([_derived("e", [], [])], tmp_path / "e.csv"))
    info = session.source_info(key)
    assert info.t_min is None and info.t_max is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session.py -k "source_info" -v`
Expected: `test_source_info_does_not_pollute_sorted_view_cache` が FAIL（現行 `sorted_view()[0][0]` が `_sorted_view_cache` を populate するため `all(... is None)` が False）。他の3件は現行実装でも PASS しうる（挙動不変を lock するため RED 必須ではない）。

- [ ] **Step 3: Rewrite source_info の t_min/t_max 算出**

`src/valisync/core/session.py:235-236` の2行を削除し、下記へ置換（`return SourceInfo(...)` の直前）:

```python
        # t_min/t_max は範囲のみ必要 — sorted_view() を呼ぶと FU-20 の native
        # dtype 値を全信号ぶん float64 へ upcast＋キャッシュし prod(264k)で +数GB
        # 膨張する(FU-18)。channel-group 内は master timestamps を共有するので
        # id() で dedup し、unique master ごとに1回だけ生 min/max を取る。
        reps = {id(s.timestamps): s for s in group.signals if len(s.timestamps)}
        ranges = [r for s in reps.values() if (r := s.time_range()) is not None]
        t_min = min(r[0] for r in ranges) if ranges else None
        t_max = max(r[1] for r in ranges) if ranges else None
```

そして `SourceInfo(...)` の `t_min=`/`t_max=` を新しいローカル変数へ:

```python
        return SourceInfo(
            full_path=group.source_path,
            size_bytes=size,
            t_min=t_min,
            t_max=t_max,
            n_channels=len(group.signals),
            file_format=group.file_format,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_session.py -k "source_info" -v`
Expected: PASS（新規4件 ＋ 既存 `test_source_info_fields`/`_size_none_when_file_gone`/`_unknown_key_raises`/`_time_range_non_monotonic` 全て）

- [ ] **Step 5: Full suite + gate + commit**

```bash
uv run pytest -q
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/core/session.py tests/test_session.py
git commit -m "perf(fu18): source_info を master id dedup＋time_range 化(sorted_view 撤去で hover blowup 解消)"
```

---

### Task 3: ローカル prod_demo で hover 実測（非コミット・E2E ゲート）

**Files:**
- 参照: `<scratchpad>/repro_fu18.py`（既存・修正前に 7689ms/+4.69GB を実測済み）
- **src/ 変更なし**（測定のみ・commit 不要）

**Interfaces:**
- Consumes: Task 2 完了後の `source_info`・実 `demo_data/prod_demo.mf4`（生成物・非コミット）。
- Produces: 修正後の初回 `source_info` 時間 ~0ms・RSS 非増加の実測証拠（SDD report / ledger に記録）。

- [ ] **Step 1: prod_demo.mf4 の存在確認（無ければ生成）**

Run: `ls demo_data/prod_demo.mf4 2>/dev/null || uv run python scripts/generate_demo_mf4.py --profile quick`
Expected: `demo_data/prod_demo.mf4` が存在（quick ≈170MB でも 264k 展開でスケール検証に十分。既に hils/quick 生成済みならそれを使う）

- [ ] **Step 2: 修正後の hover を実測**

Run: `uv run python "<scratchpad>/repro_fu18.py"`
（`<scratchpad>` は `C:/Users/trtrm/AppData/Local/Temp/claude/D--Programming-projects-valisync/f2bee1e9-232f-420e-b6ef-f2a0dceaef1b/scratchpad`）
Expected: `[hover #1] source_info: ~0 ms  RSS ... (+0.00 GB)`（修正前 7689ms/+4.69GB からの改善）。`t_min=0.0 t_max≈119.99` が修正前と一致（値不変）。

- [ ] **Step 3: 証拠を記録**

SDD report / progress ledger に「修正前 7689ms/+4.69GB → 修正後 ~0ms/+0.00GB・t_min/t_max 不変」を数値で記録。src/ diff は空（測定タスク）。commit なし。

---

## Self-Review

**1. Spec coverage:**
- A（生 min/max 置換）→ Task 2 Step 3。✅
- B（master id() dedup）→ Task 2 Step 3 `reps` ＋ `test_source_info_does_not_pollute_sorted_view_cache`（共有 master）。✅
- ガードレール `Signal.time_range()` → Task 1。✅
- engine.py 非変更 → Global Constraints に明記・どのタスクも触れない。✅
- C（メモ化）棄却 → 実装しない（プランに登場しない）。✅
- テスト: `_sorted_view_cache is None` sabotage-RED → Task 2 Step 1/2。値正しさ非単調 → 既存 `_time_range_non_monotonic` ＋ 新 `_spans_multiple_masters`。空ガード → `_ignores_empty_signals_but_counts_them`＋`_none_when_all_empty`。time_range 単体 → Task 1。ローカル prod 実測 → Task 3。✅
- 負の契約（SourceInfo 型・sorted_view/FU-20・VM/GUI 配線・size_bytes 毎回 stat 不変）→ Global Constraints。✅

**2. Placeholder scan:** TBD/TODO/"handle edge cases" 等なし。全ステップに実コード・実コマンド・期待出力あり。✅

**3. Type consistency:** `time_range() -> tuple[float, float] | None` を Task 1 で定義し Task 2 で `(r := s.time_range()) is not None` として消費（型整合）。`reps: dict[int, Signal]`・`ranges: list[tuple[float, float]]`・`t_min/t_max: float | None`。mypy クリーン想定（walrus で None 除外後 `r` は `tuple[float,float]`）。✅
