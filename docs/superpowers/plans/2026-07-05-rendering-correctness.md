# rendering-correctness（RN-01/RN-02）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 波形描画のビューポート処理が疎信号のズーム時消失（RN-01）と別時間域の追加信号の無表示無告知（RN-02）で黙ってデータを見えなくする2件を解消する。

**Architecture:** `graph_panel_vm.py` の X 窓スライスを窓外の隣接サンプル1点ずつまで拡張（RN-01）、`_x_range_is_auto` フラグで「自動フィット中は追加時に和集合へ拡張・手動ズーム後は尊重」を実現（RN-02）。View 層・他 VM は不変更。

**Tech Stack:** Python 3.12/3.13・numpy・PySide6（VM は Qt-free ロジック）・pytest / pytest-qt。

## Global Constraints

- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- コメントは WHY を書く。全角括弧・記号は docstring/コメントで RUF001/002/003 に触れるため半角化するか `# noqa: RUF00x`。
- 変更は `src/valisync/gui/viewmodels/graph_panel_vm.py` のみ。
- レンダテストは GUI レンダ経由の false-green（memory `gui_offset_render_test_xrange_pitfall`）を避け、x_range を明示固定し RenderCurve の timestamps を直接検証。
- テストヘルパは既存の `_register_signal(session, sig, tmp_path)`・`GraphPanelVM(session)`・`vm.add_signal(key)` を流用。

---

### Task 1: RN-01 — X 窓スライスに境界サンプルを取り込む

窓内厳密スライスを窓外の隣接サンプル1点ずつまで拡張し、窓を横切る線分が描かれるようにする。

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`render_data` の窓スライス）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Consumes: 既存 `render_data()`・`set_x_range()`・`_register_signal`（テスト）
- Produces: 窓スライスの拡張（外部シグネチャ不変）

- [ ] **Step 1: 疎信号のズーム消失テストを書く**

`tests/gui/test_graph_panel_vm.py` の末尾に追加:

```python
def _sparse_sig(name: str = "sparse") -> Signal:
    """t=0,100,200 の疎信号 (値も 0,100,200)."""
    return Signal(
        name=name,
        timestamps=np.array([0.0, 100.0, 200.0], dtype=np.float64),
        values=np.array([0.0, 100.0, 200.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def test_rn01_sparse_signal_visible_when_zoomed_between_samples(
    tmp_path: Path,
) -> None:
    """窓内にサンプルが無くても窓を横切る線分の端点が含まれる (RN-01)."""
    session = Session()
    key = _register_signal(session, _sparse_sig(), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.set_x_range(40.0, 60.0)  # サンプルの無い窓へズーム
    curves = vm.render_data()
    ts = curves[0].timestamps
    # 境界2点 (t=0 と t=100) が含まれ、線分 0->100 が [40,60] を横切って描ける
    assert 0.0 in ts.tolist() and 100.0 in ts.tolist()


def test_rn01_window_after_signal_end_no_fabricated_line(tmp_path: Path) -> None:
    """信号終端より後の窓は境界1点のみ (可視域外・外挿の捏造なし) (RN-01)."""
    session = Session()
    key = _register_signal(session, _sparse_sig(), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.set_x_range(300.0, 400.0)  # 信号は t<=200
    ts = vm.render_data()[0].timestamps
    assert ts.tolist() == [200.0]  # 終端の1点のみ (可視域外でクリップ)


def test_rn01_full_view_unchanged(tmp_path: Path) -> None:
    """全体表示 (x_range=None 相当) では全サンプルが出る (回帰) (RN-01)."""
    session = Session()
    key = _register_signal(session, _sparse_sig(), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(key)  # auto-fit で [0,200]
    ts = vm.render_data()[0].timestamps
    assert ts.tolist() == [0.0, 100.0, 200.0]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k rn01 -v`
Expected: FAIL（`test_rn01_sparse_signal_visible...` は現行スライスで空 → `curves[0].timestamps` が空でアサート失敗）

- [ ] **Step 3: 窓スライスを拡張**

`src/valisync/gui/viewmodels/graph_panel_vm.py` の `render_data` 内の窓スライスを変更:

```python
            # Slice to visible window using searchsorted on monotonic timestamps.
            # RN-01: 窓外の隣接サンプルを左右1点ずつ含め、窓内にサンプルが無くても
            # 窓を横切る線分が描けるようにする (疎信号のズーム消失を防ぐ)。
            lo_idx = int(np.searchsorted(ts, x_lo, side="left"))
            hi_idx = int(np.searchsorted(ts, x_hi, side="right"))
            lo_ext = max(0, lo_idx - 1)
            hi_ext = min(len(ts), hi_idx + 1)
            ts_slice = ts[lo_ext:hi_ext]
            vs_slice = vs[lo_ext:hi_ext]
```

（元の `lo_idx`/`hi_idx` スライス2行を上記へ置換。以降の空スライス分岐・ダウンサンプリングは不変。）

- [ ] **Step 4: 通過＋既存無回帰を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -v`
Expected: PASS（RN-01 新3テスト＋既存の render/slice テストが全て緑）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
uv run ruff format src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
uv run mypy src/
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "fix(gui): X 窓スライスに境界サンプルを取り込む (RN-01) — 疎信号のズーム消失を解消"
```

---

### Task 2: RN-02 — 自動フィット状態を追跡し和集合へ拡張

`_x_range_is_auto` フラグを導入し、自動フィット中は追加時に全信号の時間和集合へ拡張、手動ズーム後は尊重する。

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`__init__`・`set_x_range`・`reset_x`・`_auto_fit_ranges`）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Consumes: 既存 `add_signal`（→`_auto_fit_ranges`）・`set_x_range`・`reset_x`
- Produces: `self._x_range_is_auto: bool`（内部状態）／`_auto_fit_ranges` の条件を auto フラグ基準へ

- [ ] **Step 1: auto フィット/和集合拡張のテストを書く**

`tests/gui/test_graph_panel_vm.py` の末尾に追加:

```python
def _ranged_sig(name: str, t0: float, t1: float) -> Signal:
    """[t0, t1] の 2 点信号 (別時間域の比較用)."""
    return Signal(
        name=name,
        timestamps=np.array([t0, t1], dtype=np.float64),
        values=np.array([1.0, 2.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def test_rn02_second_signal_expands_range_in_auto_mode(tmp_path: Path) -> None:
    """自動フィット中は別時間域の2本目追加で x_range が和集合へ拡張 (RN-02)."""
    session = Session()
    a = _register_signal(session, _ranged_sig("A", 0.0, 100.0), tmp_path)
    b = _register_signal(session, _ranged_sig("B", 500.0, 600.0), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(a)
    assert vm.x_range == (0.0, 100.0) and vm._x_range_is_auto is True
    vm.add_signal(b)
    assert vm.x_range == (0.0, 600.0)  # 和集合 — B が窓外に消えない


def test_rn02_manual_zoom_is_respected(tmp_path: Path) -> None:
    """手動ズーム後は追加で範囲を触らない (RN-02・ユーザー決定=何もしない)."""
    session = Session()
    a = _register_signal(session, _ranged_sig("A", 0.0, 100.0), tmp_path)
    c = _register_signal(session, _ranged_sig("C", 500.0, 600.0), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(a)
    vm.set_x_range(40.0, 60.0)  # 手動ズーム
    assert vm._x_range_is_auto is False
    vm.add_signal(c)
    assert vm.x_range == (40.0, 60.0)  # ズーム尊重・拡張しない


def test_rn02_reset_x_returns_to_auto(tmp_path: Path) -> None:
    """reset_x は union フィット＋auto へ復帰 (RN-02)."""
    session = Session()
    a = _register_signal(session, _ranged_sig("A", 0.0, 100.0), tmp_path)
    b = _register_signal(session, _ranged_sig("B", 500.0, 600.0), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(a)
    vm.set_x_range(40.0, 60.0)  # manual
    vm.add_signal(b)  # manual なので拡張しない
    vm.reset_x()
    assert vm.x_range == (0.0, 600.0) and vm._x_range_is_auto is True
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k rn02 -v`
Expected: FAIL（`_x_range_is_auto` 属性なし／2本目で拡張されない）

- [ ] **Step 3: auto フラグを実装**

`__init__` の `self.x_range` 定義（`self.x_range: tuple[float, float] | None = None`）の直後に追加:

```python
        # RN-02: x_range が「自動フィット由来」か「手動ズーム由来」かを区別する。
        # None チェックだけだと初回オートフィット後の非 None を手動と誤認し、
        # 別時間域の2本目信号が窓外で無表示になる。
        self._x_range_is_auto: bool = True
```

`set_x_range` に手動マークを追加:

```python
    def set_x_range(self, lo: float, hi: float) -> None:
        """Set the horizontal view range and invalidate the render cache."""
        self.x_range = (lo, hi)
        self._x_range_is_auto = False  # RN-02: 手動ズーム/パン/同期由来は auto を外す
        self._invalidate_cache()
        self._notify("range")
```

`reset_x` の末尾（`self.x_range = ...` の直後）に auto 復帰を追加:

```python
        self.x_range = (lo, hi) if lo is not None and hi is not None else None
        self._x_range_is_auto = True  # RN-02: 明示リセットで自動フィットへ復帰
        self._invalidate_cache()
        self._notify("range")
```

`_auto_fit_ranges` の条件を auto フラグ基準へ変更:

```python
        if self._x_range_is_auto:  # RN-02: None のときだけでなく auto のとき常に
            x_lo: float | None = None
            x_hi: float | None = None
            for entry in self._plotted:
                sig = sig_map.get(entry.signal_key)
                if sig is None or len(sig.timestamps) == 0:
                    continue
                s_ts = sig.sorted_view()[0]
                ts0 = float(s_ts[0])
                tsN = float(s_ts[-1])
                x_lo = ts0 if x_lo is None else min(x_lo, ts0)
                x_hi = tsN if x_hi is None else max(x_hi, tsN)
            if x_lo is not None and x_hi is not None:
                self.x_range = (x_lo, x_hi)
```

（`if self.x_range is None:` を `if self._x_range_is_auto:` に置換。union 計算本体は不変。x_range のキャッシュキーが変わるので拡張後は自然に再レンダされる。）

- [ ] **Step 4: 通過＋既存無回帰を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py tests/gui/test_graph_area_vm.py -v`
Expected: PASS（RN-02 新3テスト＋既存の add_signal/auto-fit/X 同期テストが全て緑）

- [ ] **Step 5: X 同期の無回帰を確認**

Run: `uv run pytest tests/gui -k "sync or graph_area or graph_panel" -q`
Expected: PASS（X 同期は `set_x_range` 経由で手動マークされドライバに追従＝設計どおり・回帰なし）

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
uv run ruff format src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
uv run mypy src/
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "fix(gui): 自動フィット中は追加信号で x_range を和集合へ拡張 (RN-02)"
```

---

### Task 3: ドキュメント更新（catalog・roadmap）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（RN-01/RN-02 を ✅解消に）
- Modify: `docs/roadmap.md`（SS-RENDER の RN-01/02 完了）

- [ ] **Step 1: catalog の RN-01/02 行を解消済みへ更新**

`docs/audit-findings-catalog.md` の SS-RENDER セクションを更新:

- RN-01: 「✅**解消** X 窓スライスを窓外の隣接サンプル1点ずつまで拡張し、窓を横切る線分の端点を保持。疎信号のズーム時消失を解消」
- RN-02: 「✅**解消** `_x_range_is_auto` フラグを導入し、自動フィット中は追加信号で x_range を全信号の時間和集合へ拡張（手動ズーム後は尊重・Reset X が受け皿）。別時間域の2本目信号が窓外で無表示になる問題を解消」

- [ ] **Step 2: roadmap の SS-RENDER を更新**

`docs/roadmap.md` の②表 `rendering-correctness-perf` 行に RN-01/02（描画の正しさ）完了を反映し、残りは RN-03/04/05（性能・Y 軸退化）である旨を記述。プロース注記に spec/plan ポインタを追加。

- [ ] **Step 3: 最終ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add docs/
git commit -m "docs: rendering-correctness (RN-01/RN-02) を catalog/roadmap へ反映"
```

---

## Self-Review

- **Spec coverage**: §3.1 RN-01 → Task 1／§3.2 RN-02 → Task 2／§7 docs → Task 3。全カバー。
- **型整合**: `_x_range_is_auto: bool` を Task 2 で `__init__`/`set_x_range`/`reset_x`/`_auto_fit_ranges` に一貫適用。`render_data` のスライス変更（Task 1）は外部シグネチャ不変。
- **プレースホルダ**: なし（各ステップに実コード）。
- **既存挙動の変更明示**: Task 1 は空スライス→境界2点で疎信号が見えるように（全体表示は回帰なし）。Task 2 は「None のときだけフィット」→「auto のとき常に union フィット」。X 同期は `set_x_range` 経由で手動マークされ設計どおり追従（Task 2 Step 5 で無回帰確認）。
- **false-green 回避**: レンダテストは x_range を明示固定し RenderCurve の timestamps を直接検証（memory `gui_offset_render_test_xrange_pitfall`）。
