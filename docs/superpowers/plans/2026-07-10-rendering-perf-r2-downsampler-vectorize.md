# rendering-correctness-perf 増分2: ダウンサンプラのベクトル化 ＋ X-sync 冗長ガード Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RN-04（X 同期の全パネル扇状展開フリーズ）を、その内側で回るダウンサンプラの min-max 選択を**ベクトル化**して解消し、加えて `set_x_range` の同値再セットを no-op 化して冗長 render を除去する。

**Architecture:** 2つの独立修正。(1) `Downsampler.downsample` のバケット毎 Python ループ（`np.nanargmin`/`nanargmax` を ~1600 回）を、セグメント単位の min/max とその first-hit インデックスを求める **NumPy ベクトル演算**へ置換する。選択ロジックは同一ファイル内の純関数 `_minmax_indices` へ抽出して単体テスト可能にする（出力インデックスは現行と完全一致＝挙動保存）。(2) `GraphPanelVM.set_x_range` 先頭にレンジ不変 early-return を追加（増分1 RN-03 の `set_panel_width` ガードと同型）。

**Tech Stack:** Python 3.13 / NumPy / PySide6（Qt6・本増分は View 非変更）/ pyqtgraph / MVVM。テストは pytest ＋ hypothesis（PBT）。

## Global Constraints

- **挙動保存（ピクセル不変）**: ベクトル化後の `downsample` は現行と**同一のサンプル集合**を選ぶ。既存の `tests/test_downsampler.py`（Req 14.2/14.3/14.4/14.6/14.7）と `tests/test_pbt_downsampler.py`（property-based）が**全 PASS** であることが一次ゲート。
- **threading なし**: オフスレッド並列は本増分の非目標（YAGNI）。UI スレッド据え置き。
- **MVVM 非変更**: View（`graph_panel_view.py`）は無変更。修正は core（`downsampler.py`）と VM（`graph_panel_vm.py`）に閉じる。
- **realgui 不要**: 両修正とも Layer A / core ユニットで実質を尽くせる（GUI 入力経路の変更なし）。realgui テストの新規追加・変更なし。
- **perf は CI アサートにしない**: 速度はマシン依存でフレークするため PR/spec に測定値を記録するに留める（既存 `test_downsample_large_signal_is_fast` の `elapsed < 1.0` は据え置き＝退化検知の緩いガードとして残す）。
- **品質ゲート**: コミット前に `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` を通す。
- **コミット trailer（本ブランチ規約・必須）**: 各コミットメッセージ末尾に以下2行を付す。
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4
  ```

---

## File Structure

- **`src/valisync/core/downsampler/downsampler.py`**（Modify）: バケット毎ループ（現行 L67-76）を撤去し、新設のモジュールレベル純関数 `_minmax_indices(vs, seg_starts, seg_ends)` の呼び出しへ置換。バリデーション（L29-32）・pass-through（L36-50）・バケット割当とセグメント境界算出（L52-65）・末尾の `Signal(...)` 構築（L77-85）は不変。
- **`tests/test_downsampler.py`**（Modify）: 新規に `_minmax_indices` の弁別的単体テスト（hand-computed）＋独立参照ループとのパリティテストを追記。既存テストは不変（挙動保存の一次ゲート）。
- **`src/valisync/gui/viewmodels/graph_panel_vm.py`**（Modify）: `set_x_range`（現行 L599-604）先頭にレンジ不変ガードを追加。
- **`tests/gui/test_graph_panel_vm.py`**（Modify）: `set_x_range` ガードの弁別テストを追記（RN-03 の `test_set_panel_width_unchanged_is_noop` と同型）。

---

## Task 1: ダウンサンプラのベクトル化（`_minmax_indices` 抽出）

**Files:**
- Modify: `src/valisync/core/downsampler/downsampler.py`（新設 `_minmax_indices`・`downsample` L67-76 を置換）
- Test: `tests/test_downsampler.py`（弁別的単体テスト＋パリティテストを追記）

**Interfaces:**
- Consumes: `Signal.sorted_view()`（既存）・`downsample` 内で算出済みの `vs`（np.ndarray, float64）・`seg_starts`（np.intp, 狭義増加なバケット境界）・`seg_ends`（np.intp, `seg_ends[i] == seg_starts[i+1]`・最後は `len(vs)`）。
- Produces: `_minmax_indices(vs: np.ndarray, seg_starts: np.ndarray, seg_ends: np.ndarray) -> np.ndarray` — 昇順ソート済みの選択インデックス（各セグメントの min を最初に達成するインデックスと max を最初に達成するインデックス。全 NaN セグメントはその先頭インデックス）。返り値は `np.unique` 済みなので昇順・重複なし。

### 背景（実装者向け・必読）

現行 `downsample` は各バケット（セグメント）ごとに Python ループで `np.nanargmin`/`np.nanargmax` を呼ぶ。これがバケット数ぶんの固定オーバーヘッド（内部で NaN 置換コピー＋全走査）を生み、狭窓ズームインでも重い（cProfile で特定・本番想定で 8 パネル同期時 ~1 秒フリーズ）。同じ出力を **NumPy の `reduceat` ベース**で一括計算すると、狭窓で ~53×・全範囲で ~1.6× 高速になる（プロトタイプで出力インデックス完全一致を実証済み）。

**契約（現行ループと厳密一致させる不変条件）:**
- 各セグメントで min を達成する**最初の**インデックスと max を達成する**最初の**インデックスの2点を選ぶ（`np.nanargmin`/`nanargmax` は先頭優先なので一致させる）。
- 混在 NaN セグメント: NaN は min/max の勝者にしない（有限値のみで min/max）。
- 全 NaN セグメント: そのセグメントの先頭インデックス1点のみを残す（現行 `else: result.add(lo)`）。
- 返り値は入力インデックスの部分集合・昇順・重複なし。

### 実装（ベクトル化アルゴリズム）

```python
def _minmax_indices(
    vs: np.ndarray, seg_starts: np.ndarray, seg_ends: np.ndarray
) -> np.ndarray:
    """Per-segment min-max sample selection, vectorized (NaN-aware).

    For each contiguous segment [seg_starts[i], seg_ends[i]) return the FIRST
    index attaining that segment's min and the FIRST attaining its max — matching
    np.nanargmin/np.nanargmax's leading-tie preference. A segment whose values are
    all NaN keeps its first index (seg start). Result is sorted, de-duplicated
    input indices.

    seg_starts must be strictly increasing (distinct bucket boundaries) so
    reduceat treats each as its own segment. seg_ends[i] == seg_starts[i+1].
    """
    n_seg = len(seg_starts)
    m = len(vs)

    # NaN を極値へ退避: min には +inf、max には -inf を割り当て決して勝たせない。
    finite = np.isfinite(vs)
    v_min = np.where(finite, vs, np.inf)
    v_max = np.where(finite, vs, -np.inf)

    # 各要素 -> 所属セグメント id（セグメント長で arange を反復）。
    seg_id = np.repeat(np.arange(n_seg), seg_ends - seg_starts)
    idx = np.arange(m)

    # セグメントごとの min/max 値（reduceat で一括縮約）。
    seg_min = np.minimum.reduceat(v_min, seg_starts)
    seg_max = np.maximum.reduceat(v_max, seg_starts)

    # 各セグメントで min/max を達成する「最初の」インデックス（非達成は番兵 m）。
    # 全 NaN セグメントは seg_min=+inf に全要素が一致 -> 先頭 index を選ぶ。
    min_hit = np.where(v_min == seg_min[seg_id], idx, m)
    max_hit = np.where(v_max == seg_max[seg_id], idx, m)
    argmin_seg = np.minimum.reduceat(min_hit, seg_starts)
    argmax_seg = np.minimum.reduceat(max_hit, seg_starts)

    return np.unique(np.concatenate([argmin_seg, argmax_seg]))
```

（`downsample` 内の呼び出し置換は Step 6 に示す。）

---

- [ ] **Step 1: `_minmax_indices` の弁別的単体テストを書く（失敗する）**

`tests/test_downsampler.py` 末尾に追記する。先頭の import に `_minmax_indices` を加える（現状 `from valisync.core.downsampler import Downsampler` だが、`_minmax_indices` は `downsampler.py` モジュール内にあるため `from valisync.core.downsampler.downsampler import _minmax_indices` で取り込む）。

```python
def _segs(starts: list[int], m: int) -> tuple[np.ndarray, np.ndarray]:
    """Build (seg_starts, seg_ends) for contiguous segments over m elements."""
    seg_starts = np.array(starts, dtype=np.intp)
    seg_ends = np.concatenate((seg_starts[1:], [m])).astype(np.intp)
    return seg_starts, seg_ends


def test_minmax_indices_single_segment_global_min_max() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([5.0, 6.0, 7.0, -3.0, 4.0, 2.0, 1.0, 9.0, 8.0, 0.0])
    seg_starts, seg_ends = _segs([0], len(vs))  # one bucket
    # global min -3 @ idx3, global max 9 @ idx7
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [3, 7]


def test_minmax_indices_two_segments() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([5.0, 6.0, 7.0, -3.0, 4.0, 2.0, 1.0, 9.0, 8.0, 0.0])
    seg_starts, seg_ends = _segs([0, 5], len(vs))
    # seg0 [idx0..4]: min -3@3, max 7@2 ; seg1 [idx5..9]: min 0@9, max 9@7
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [2, 3, 7, 9]


def test_minmax_indices_first_occurrence_tie_break() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([3.0, 1.0, 3.0, 1.0])  # max 3 first@0, min 1 first@1
    seg_starts, seg_ends = _segs([0], len(vs))
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [0, 1]


def test_minmax_indices_mixed_nan_segment() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([np.nan, 5.0, np.nan, 2.0, np.nan])  # min 2@3, max 5@1
    seg_starts, seg_ends = _segs([0], len(vs))
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [1, 3]


def test_minmax_indices_all_nan_segment_keeps_first() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([np.nan, np.nan, np.nan])
    seg_starts, seg_ends = _segs([0], len(vs))
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [0]
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_downsampler.py -k minmax_indices -v`
Expected: FAIL — `ImportError: cannot import name '_minmax_indices'`（関数未定義）。

- [ ] **Step 3: `_minmax_indices` を実装**

`src/valisync/core/downsampler/downsampler.py` に、モジュールレベル関数として（`import numpy as np` の下・`class Downsampler` の**前**に）上記「実装（ベクトル化アルゴリズム）」の `_minmax_indices` を追加する。

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/test_downsampler.py -k minmax_indices -v`
Expected: PASS（5件）。

- [ ] **Step 5: 独立参照ループとのパリティテストを書いて実行**

`tests/test_downsampler.py` 末尾に追記。現行アルゴリズムを模した**独立参照**（`np.nanargmin`/`nanargmax` ループ）とベクトル化版が、finite / 一部 NaN / 全 NaN バケットで同一インデックスを返すことを固定シードで assert する。

```python
def _reference_indices(
    vs: np.ndarray, seg_starts: np.ndarray, seg_ends: np.ndarray
) -> np.ndarray:
    """Independent reference: the pre-vectorization per-bucket loop."""
    result: set[int] = set()
    for lo, hi in zip(seg_starts.tolist(), seg_ends.tolist(), strict=True):
        seg = vs[lo:hi]
        if np.any(np.isfinite(seg)):
            result.add(lo + int(np.nanargmin(seg)))
            result.add(lo + int(np.nanargmax(seg)))
        else:
            result.add(lo)
    return np.array(sorted(result))


@pytest.mark.parametrize("nan_frac", [0.0, 0.05, 0.5, 1.0])
def test_minmax_indices_matches_reference_loop(nan_frac: float) -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    rng = np.random.default_rng(0)
    m = 5000
    vs = rng.standard_normal(m)
    if nan_frac > 0:
        vs[rng.random(m) < nan_frac] = np.nan
    # 40 contiguous segments of ~equal length (strictly-increasing starts).
    seg_starts = np.unique(np.linspace(0, m, 41, endpoint=True).astype(np.intp)[:-1])
    seg_ends = np.concatenate((seg_starts[1:], [m])).astype(np.intp)

    got = _minmax_indices(vs, seg_starts, seg_ends)
    ref = _reference_indices(vs, seg_starts, seg_ends)
    assert got.tolist() == ref.tolist()
```

Run: `uv run pytest tests/test_downsampler.py -k "minmax_indices or matches_reference" -v`
Expected: PASS（9件）。

- [ ] **Step 6: `downsample` をベクトル化版へ配線（ループ撤去）**

`src/valisync/core/downsampler/downsampler.py` の現行 L67-76 の Python ループ:

```python
        result: set[int] = set()
        for lo, hi in zip(seg_starts.tolist(), seg_ends.tolist(), strict=True):
            seg = vs[lo:hi]
            if np.any(np.isfinite(seg)):
                result.add(lo + int(np.nanargmin(seg)))
                result.add(lo + int(np.nanargmax(seg)))
            else:
                result.add(lo)  # all-NaN bucket: keep one sample

        sorted_idx = np.array(sorted(result))
```

を、次の1行へ置換する（`return Signal(... timestamps=ts[sorted_idx] ...)` はそのまま）:

```python
        sorted_idx = _minmax_indices(vs, seg_starts, seg_ends)
```

- [ ] **Step 7: ダウンサンプラの全テスト＋PBT を実行（挙動保存ゲート）**

Run: `uv run pytest tests/test_downsampler.py tests/test_pbt_downsampler.py -v`
Expected: PASS（既存の Req 14.2/14.3/14.4/14.6/14.7・pass-through・all-NaN・非単調・large-fast＋新規 9 件＋PBT すべて）。既存テストが1件でも赤なら**挙動が変わっている**＝ベクトル化のバグ。falls back せず原因修正。

- [ ] **Step 8: LOD 描画回帰テストを実行**

Run: `uv run pytest tests/gui/test_lod_render.py tests/gui/test_lod_benchmark.py -v`
Expected: PASS（ダウンサンプラは出力不変なので render 結果も不変）。※ファイルが存在しない場合は `uv run pytest -k lod -v` で LOD 関連を実行。

- [ ] **Step 9: 品質ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/downsampler/ tests/test_downsampler.py
uv run ruff format --check src/valisync/core/downsampler/ tests/test_downsampler.py
uv run mypy src/valisync/core/downsampler/
git add src/valisync/core/downsampler/downsampler.py tests/test_downsampler.py
git commit -m "perf(core): ダウンサンプラの min-max 選択をベクトル化（RN-04・出力不変）

バケット毎 Python ループ（nanargmin/nanargmax ~1600回）を reduceat ベースの
_minmax_indices へ抽出・置換。狭窓 ~53x/全範囲 ~1.6x（プロトタイプで出力
インデックス完全一致）。既存 test_downsampler/PBT 全 PASS が挙動保存の証明。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4"
```

---

## Task 2: `set_x_range` レンジ不変ガード（RN-04 冗長 render 除去）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`set_x_range` 先頭にガード・現行 L599-604）
- Test: `tests/gui/test_graph_panel_vm.py`（弁別ガードテストを追記）

**Interfaces:**
- Consumes: `GraphPanelVM.x_range: tuple[float, float] | None`（既存）・`_invalidate_cache()`・`_notify("range")`・`subscribe(cb)`（cb は変更文字列を1引数で受ける）。
- Produces: 変更なし（`set_x_range` のシグネチャ不変）。

### 背景（実装者向け・必読）

X 同期 ON で連続ズーム/パンすると、`GraphAreaVM.propagate_x_range` が全パネルへ `set_x_range` を同期ループ配送する。このとき (a) source パネル自身が既に持つレンジで再セットされ**二重描画**し、(b) 既に同じレンジへ同期済みの兄弟パネルも冗長に再描画する。現行 `set_x_range` はレンジが変わらなくても無条件で `_invalidate_cache`＋`_notify("range")` するため、この冗長分がすべて render を起こす。増分1 RN-03 の `set_panel_width` ガードと同型の「同値なら early-return」で除去する。

現行（`src/valisync/gui/viewmodels/graph_panel_vm.py` L599-604）:

```python
    def set_x_range(self, lo: float, hi: float) -> None:
        """Set the horizontal view range and invalidate the render cache."""
        self.x_range = (lo, hi)
        self._x_range_is_auto = False  # RN-02: 手動ズーム/パン/同期由来は auto を外す
        self._invalidate_cache()
        self._notify("range")
```

- [ ] **Step 1: 弁別ガードテストを書く（失敗する）**

`tests/gui/test_graph_panel_vm.py` の RN-03 ガードテスト（`test_set_panel_width_unchanged_is_noop`, 現行 L1716 付近）の直後に追記する。`_loaded_vm` は同ファイル既存のヘルパ。

```python
def test_set_x_range_unchanged_is_noop(tmp_path: Path) -> None:
    """X-sync fan-out re-sets the SOURCE panel to its current range and pushes an
    already-synced range to siblings. Re-applying the same (lo, hi) must be a no-op:
    no cache invalidation, no 'range' notify (RN-04). A different range still
    invalidates and notifies as before."""
    vm = _loaded_vm(tmp_path)
    vm.set_x_range(0.0, 10.0)  # known starting range

    calls: list[int] = []
    original = vm._invalidate_cache

    def spy() -> None:
        calls.append(1)
        original()

    vm._invalidate_cache = spy  # type: ignore[method-assign]

    notes: list[str] = []
    vm.subscribe(notes.append)

    vm.set_x_range(0.0, 10.0)  # same range -> no work
    assert calls == []
    assert "range" not in notes

    vm.set_x_range(0.0, 20.0)  # different range -> invalidates + notifies as before
    assert calls == [1]
    assert "range" in notes
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py::test_set_x_range_unchanged_is_noop -v`
Expected: FAIL — 同値再セットで現行は invalidate するため `assert calls == []` が `calls == [1]` で落ちる。

- [ ] **Step 3: レンジ不変ガードを追加**

`set_x_range` を次へ置換する（先頭に early-return を追加）:

```python
    def set_x_range(self, lo: float, hi: float) -> None:
        """Set the horizontal view range and invalidate the render cache."""
        # X-sync fan-out re-applies the current range to the source panel and pushes
        # already-synced ranges to siblings. Skip the redundant re-render when the
        # range is unchanged (RN-04); a real change proceeds as before.
        if self.x_range == (lo, hi):
            return
        self.x_range = (lo, hi)
        self._x_range_is_auto = False  # RN-02: 手動ズーム/パン/同期由来は auto を外す
        self._invalidate_cache()
        self._notify("range")
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py::test_set_x_range_unchanged_is_noop -v`
Expected: PASS。

- [ ] **Step 5: VM ＋ X-sync 回帰テストを実行**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py tests/gui/test_graph_area_vm.py tests/gui/test_graph_panel_zoom.py -v`
Expected: PASS（既存の set_x_range / ズーム / X 同期テストがガードで壊れない＝異なるレンジは従来どおり処理される）。1件でも赤なら、同値再セットに依存していた既存テストを洗い出して原因を判断（黙って skip しない）。

- [ ] **Step 6: 品質ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
uv run ruff format --check src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
uv run mypy src/valisync/gui/viewmodels/graph_panel_vm.py
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "perf(gui): set_x_range に不変ガード（RN-04 の X-sync 冗長 render 除去）

X 同期の扇状展開で source の二重描画・同期済み兄弟への冗長配送を no-op 化。
増分1 RN-03 の set_panel_width ガードと同型。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4"
```

---

## 完了時の全体ゲート（両タスク後）

- [ ] `uv run pytest`（**0 errors** ＝ headless 全体・テスト間汚染なし）
- [ ] `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`
- [ ] realgui: **対象外**（GUI 入力経路の変更なし・両修正は Layer A/core で実質充足）。`/gui-verify` は「realgui カバレッジ対象の変更なし」で終了する想定。

## Self-Review（プラン作成者チェック済み）

- **Spec coverage**: 修正1（ベクトル化）→ Task 1。修正2（`set_x_range` ガード）→ Task 2。テスト戦略（既存契約テスト＋PBT ゲート・新規パリティ・ガードスパイ）→ Task 1 Step 5/7・Task 2 Step 1。非目標（オフスレッド/アルゴリズム意味変更なし）→ Global Constraints で明記。全 spec 要素にタスク対応あり・ギャップなし。
- **Placeholder scan**: TBD/TODO なし。全コードステップに実コードあり。
- **Type consistency**: `_minmax_indices(vs, seg_starts, seg_ends) -> np.ndarray` を Task 1 で定義し同名で `downsample` から呼ぶ。`set_x_range(self, lo, hi) -> None` はシグネチャ不変。テストヘルパ `_segs`/`_reference_indices`/`_loaded_vm` の名前・引数一貫。
