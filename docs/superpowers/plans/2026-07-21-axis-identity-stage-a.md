# 軸アイデンティティ契約 Stage A（UX-01/02/03 根治）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 軸ラベル・Yレンジが常に真実になるよう VM/View を修正し、critical 3 件（UX-01 捏造単位ペア／UX-02 新軸移動で曲線消失／UX-03 追加信号の無言不可視）を根治する。

**Architecture:** GraphPanelVM に「代表波形ラベルの一括再計算」と「per-axis auto フラグの可視和集合フィット」を導入し、全変異経路（spec §3.7 全数表）の末尾で適用。View は軸ラベル適用を共有ヘルパ化（2 サイト＋空クリア）し、手動レンジ時のオフスケールバッジを新設。

**Tech Stack:** PySide6 / pyqtgraph / pytest(-qt)。Layer A/B は headless CI、Layer C は `--realgui`（ローカル実ディスプレイ）。

**Spec:** [docs/superpowers/specs/2026-07-21-axis-identity-stage-a-design.md](../specs/2026-07-21-axis-identity-stage-a-design.md)（行番号は main@f6792d0 時点）

## Global Constraints

- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format` / `uv run mypy src/` を各コミット前に全通し（format は `--check` も CI 対象）。
- 色リテラル禁止: 色は `tokens.active().colors.*` 経由のみ（`tests/gui/test_theme_guard.py` が検出）。バッジ色は既存 `accent_active`・**新トークン追加なし**。
- ラベル規則（ユーザー決定 2026-07-21）: 複数波形の軸は**最初に登録された波形（代表）の name/unit を対で表示**。混在マーカーは作らない。
- auto フラグ遷移を `YAxisVM.set_range` / `_fit_axis` に置かない（オートフィット自身が同 funnel を通り自壊 — spec §3.1 注意）。
- Y フィット・ラベル再計算は base の `session.signal_map()` を使う（オフセット適用中の `_signal_map` 全チャンネル overlay 再構築を踏まない — spec §3.3 perf）。X 側は現状維持。
- realgui テストは実 OS 入力プリミティブ（`_realgui_input.at()` 等）のみ（合成は Layer C 契約ガードが落とす）。
- コメントは WHY のみ・日本語可。既存コメント密度に合わせる。

---

### Task 1: YAxisVM に `y_is_auto` フラグを追加

**Files:**
- Modify: `src/valisync/gui/viewmodels/y_axis_vm.py:13-29`
- Test: `tests/gui/test_y_axis_vm.py`

**Interfaces:**
- Produces: `YAxisVM(y_is_auto: bool = True)` コンストラクタ引数＋インスタンス属性 `y_is_auto`。後続タスクは `axis.y_is_auto` を読み書きする。`set_range` はフラグに**触れない**。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_y_axis_vm.py` に追記:

```python
def test_y_is_auto_defaults_true():
    assert YAxisVM().y_is_auto is True


def test_y_is_auto_constructor_override():
    assert YAxisVM(y_is_auto=False).y_is_auto is False


def test_set_range_does_not_touch_auto_flag():
    # auto フィットも手動 setter も同じ set_range funnel を通るため、
    # フラグ遷移をここに置くと初回フィットで恒久 manual 化する (spec §3.1)。
    axis = YAxisVM()
    axis.set_range(0.0, 1.0)
    assert axis.y_is_auto is True
    axis.y_is_auto = False
    axis.set_range(None, None)
    assert axis.y_is_auto is False
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_y_axis_vm.py -v`
Expected: FAIL（`y_is_auto` 属性なし / unexpected keyword）

- [ ] **Step 3: 最小実装**

`y_axis_vm.py` の `__init__` シグネチャ末尾に `y_is_auto: bool = True` を追加し、本体に:

```python
        # Y レンジが「自動フィット追従」か「手動固定」か (X の _x_range_is_auto の
        # per-axis 対称・Stage A 契約 §2.3)。遷移は GraphPanelVM の手動系メソッド側。
        self.y_is_auto = y_is_auto
```

- [ ] **Step 4: パスを確認** — Run: `uv run pytest tests/gui/test_y_axis_vm.py -v` → PASS
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(gui): YAxisVM に y_is_auto フラグ (Stage A §3.1)"`

---

### Task 2: 代表波形ラベルの一括再計算 `_recalc_axis_labels`

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`add_signal_to_axis:261-271` の増分更新を撤去・`overwrite_axis:293-296` の手動クリア撤去・新メソッド追加・remove 系 4 メソッド＋`prune_missing_signals` へ配線）
- Test: `tests/gui/test_graph_panel_multi_axis.py`

**Interfaces:**
- Consumes: `KEY_SEPARATOR`（`signal_group_manager.py:9` — 既 import 済みか確認し無ければ追加）
- Produces: `GraphPanelVM._recalc_axis_labels() -> None`（全軸の `name`/`unit` を現存代表から再導出）。後続タスク（move/insert/view）はこれを呼ぶ/前提にする。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_multi_axis.py` に追記（unit 注入は同ファイル `:458-461` の既存パターン `sig.metadata["unit"] = ...` を流用）:

```python
def test_axis_unit_stays_representative_on_mixed_join(session_two_signals_vm):
    # UX-01 根治: 異単位 join でも軸ラベルは代表 (1本目) の name/unit の対のまま。
    vm, key_a, key_b = session_two_signals_vm  # a=unit "V", b=unit "A" を注入済み想定
    vm.add_signal(key_a)
    vm.add_signal(key_b)  # 既定経路は軸0へ join
    assert vm.axes[0].name == key_a.split("::")[-1]
    assert vm.axes[0].unit == "V"  # 現行 last-wins は "A" になり fail


def test_axis_label_pair_succession_on_representative_removal(session_two_signals_vm):
    vm, key_a, key_b = session_two_signals_vm
    vm.add_signal(key_a)
    vm.add_signal(key_b)
    rep_id = next(e for e in vm._plotted if e.signal_key == key_a).entry_id
    vm.remove_entry(rep_id)
    # 代表交代は name/unit が「対で」次エントリへ (片方だけの残存は捏造ペア)
    assert vm.axes[0].name == key_b.split("::")[-1]
    assert vm.axes[0].unit == "A"


def test_axis_label_cleared_when_axis_emptied(session_two_signals_vm):
    vm, key_a, _ = session_two_signals_vm
    vm.add_signal(key_a)
    vm.remove_entry(vm._plotted[0].entry_id)
    assert vm.axes[0].name == ""
    assert vm.axes[0].unit == ""


def test_axis_label_recalc_on_prune_missing_signals(session_two_files_vm):
    # UXG-19 のアンロード経路: 代表信号のファイルを閉じたら残存名を許さない。
    vm, key_file1, key_file2 = session_two_files_vm  # 別グループの2信号・同軸0へ
    vm.add_signal(key_file1)
    vm.add_signal(key_file2)
    vm._session.remove_group(key_file1.split("::")[0], force=True)
    vm.prune_missing_signals()
    assert vm.axes[0].name == key_file2.split("::")[-1]
```

fixture が無ければ同ファイル既存 fixture（session＋CSV 2 信号）を複製し unit 注入・2 グループ版を作る（既存 `:450-471` のテストが使う構築コードをコピーして流用 — 新規共有 fixture 化までは不要）。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k "representative or mixed_join or emptied or prune" -v`
Expected: FAIL（unit が "A"＝last-wins / 残存名）

- [ ] **Step 3: 実装**

(a) 新メソッド（`_compact_axes` の直後あたりに配置）:

```python
    def _recalc_axis_labels(self) -> None:
        """全軸の name/unit を現存エントリから再導出する (Stage A 契約 §2.1-2).

        代表 = 軸上の最古 (追加順) エントリ。name/unit は常に代表信号の対 —
        増分更新 (name first-wins / unit last-wins) は別信号の捏造ペア (UX-01) を
        生むため全廃した。ラベルはオフセット非依存なので base の signal_map を
        使う (オフセット適用中の全チャンネル overlay 再構築を踏まない・spec §3.3)。
        O(axes×plotted) — プロット済みエントリ有界で無視できる。
        """
        sig_map = self._session.signal_map()
        for i, axis in enumerate(self._axes):
            rep = next((e for e in self._plotted if e.axis_index == i), None)
            if rep is None:
                axis.name = ""
                axis.unit = ""
                continue
            axis.name = rep.signal_key.split(KEY_SEPARATOR, 1)[-1]
            sig = sig_map.get(rep.signal_key)
            axis.unit = str(sig.metadata.get("unit", "")) if sig else ""
```

(b) `add_signal_to_axis` の `:261-271`（`# Propagate unit + representative name ...` ブロック全体）を削除し、`self._auto_fit_ranges()` の直前に `self._recalc_axis_labels()` を挿入。

(c) `overwrite_axis` の name/unit クリア 2 行（`:295-296`）を削除（再計算が担う。y_range リセットは Task 4）。

(d) `remove_signal` / `remove_entry` / `remove_axis` / `prune_missing_signals` の各 `self._compact_axes()` の直後に `self._recalc_axis_labels()` を挿入（`_invalidate_cache` より前）。

- [ ] **Step 4: パス確認＋既存無回帰**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py tests/gui/test_graph_panel_vm.py -v`
Expected: 全 PASS（既存 `test_axis_label_shows_first_signal_name_and_unit:450-471`・`test_unit_propagation:256-278` は同一 unit のため green のまま）

- [ ] **Step 5: Commit** — `git commit -am "fix(gui): 軸ラベルを代表波形の対で一括再計算 (UX-01/UXG-19)"`

---

### Task 3: 可視和集合フィット＋auto フラグ遷移

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`_auto_fit_ranges:1332-1351` の Y 部・`reset_axis_y:673-702`・`reset_y:763`・`set_axis_range:635`・`y_range` setter `:209-212`・`add_signal` docstring `:241-242`）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Produces: `GraphPanelVM._visible_union_range(axis_index: int) -> tuple[float | None, float | None]`。`_auto_fit_ranges` は `axis.y_is_auto` ゲート。`set_axis_range`/`y_range` setter は `y_is_auto=False`、`reset_axis_y`/`reset_y` は `y_is_auto=True`＋即フィット。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_vm.py` に追記:

```python
def test_auto_axis_refits_union_on_second_add(vm_with_two_scales):
    # UX-03 根治: 初回フィット後も auto の間は追加信号の和集合へ広がる。
    vm, key_big, key_small = vm_with_two_scales  # big=800..2275, small=0..118
    vm.add_signal(key_big)
    first = vm.axes[0].y_range
    assert first is not None and first[0] >= 799  # 初回は big のみ
    vm.add_signal(key_small)
    lo, hi = vm.axes[0].y_range
    assert lo <= 0.0 and hi >= 2275.0  # 現行は (800,2275) のまま fail


def test_manual_set_axis_range_stops_auto_and_add_respects_it(vm_with_two_scales):
    vm, key_big, key_small = vm_with_two_scales
    vm.add_signal(key_big)
    vm.set_axis_range(0, 1000.0, 2000.0)
    assert vm.axes[0].y_is_auto is False
    vm.add_signal(key_small)
    assert vm.axes[0].y_range == (1000.0, 2000.0)  # 手動は尊重


def test_reset_axis_y_restores_auto(vm_with_two_scales):
    vm, key_big, key_small = vm_with_two_scales
    vm.add_signal(key_big)
    vm.set_axis_range(0, 1000.0, 2000.0)
    vm.reset_axis_y(0)
    assert vm.axes[0].y_is_auto is True
    vm.add_signal(key_small)          # auto 復帰後は再び和集合追従
    assert vm.axes[0].y_range[0] <= 0.0


def test_auto_fit_excludes_invisible_entries(vm_with_two_scales):
    # reset_axis_y と同一規則へ統一 (可視のみ・spec §4 挙動変更)。
    vm, key_big, key_small = vm_with_two_scales
    vm.add_signal(key_big)
    vm.add_signal(key_small)
    big_id = next(e.entry_id for e in vm._plotted if e.signal_key == key_big)
    vm.toggle_entry_visibility(big_id)   # big を非表示 → small のみで再フィット
    lo, hi = vm.axes[0].y_range
    assert hi <= 120.0


def test_legacy_y_range_setter_marks_manual(vm_with_two_scales):
    vm, key_big, _ = vm_with_two_scales
    vm.add_signal(key_big)
    vm.y_range = (0.0, 10.0)
    assert vm.axes[0].y_is_auto is False
```

fixture `vm_with_two_scales`: 既存の CSV セッション fixture を流用し、値域 800..2275 と 0..118 の2信号を持つ `GraphPanelVM` を返す（既存 fixture 群に同型があるため複製最小で作る）。

- [ ] **Step 2: 失敗を確認** — Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "union or stops_auto or restores_auto or excludes_invisible or marks_manual" -v` → FAIL

- [ ] **Step 3: 実装**

(a) 共有ヘルパ（`reset_axis_y` の直前に配置）— `reset_axis_y:684-699` の走査を移設:

```python
    def _visible_union_range(
        self, axis_index: int
    ) -> tuple[float | None, float | None]:
        """軸上の可視エントリの整列ビュー有限値域の和集合 (reset_axis_y と同一規則).

        Y 値はオフセットで不変なので base の session.signal_map() を使う —
        オフセット適用中に _signal_map の全チャンネル overlay 再構築 (prod 330k)
        をフィットのたびに踏まない (spec §3.3 perf・設計レビュー捕捉)。
        """
        sig_map = self._session.signal_map()
        lo: float | None = None
        hi: float | None = None
        for entry in self._plotted:
            if entry.axis_index != axis_index or not entry.visible:
                continue
            sig = sig_map.get(entry.signal_key)
            if sig is None or len(sig.values) == 0:
                continue
            vs = sig.sorted_view()[1]
            finite_vals = vs[np.isfinite(vs)]
            if len(finite_vals) == 0:
                continue
            v_lo = float(finite_vals.min())
            v_hi = float(finite_vals.max())
            lo = v_lo if lo is None else min(lo, v_lo)
            hi = v_hi if hi is None else max(hi, v_hi)
        return lo, hi
```

(b) `reset_axis_y` の走査部をヘルパ呼出に置換し、`_fit_axis` の前に `self._axes[axis_index].y_is_auto = True` を追加（docstring に「auto へ復帰」を追記）。`reset_y:763` も同様（全軸ループで flag=True＋ヘルパ fit — 既存実装の構造に合わせる）。

(c) `_auto_fit_ranges` の Y 部（`:1332-1351`）を置換:

```python
        for i, axis in enumerate(self._axes):
            # Stage A: None ゲート (初回のみ) を廃し、auto の間は可視エントリの
            # 和集合へ常時追従 (X の RN-02 と対称・UX-03 根治)。手動 (auto=False)
            # は尊重 — レンジ外はオフスケールバッジが通知する (view 側)。
            if axis.y_is_auto:
                lo, hi = self._visible_union_range(i)
                self._fit_axis(axis, lo, hi)
```

（旧 `axis_to_sigs` 構築ループは不要になるため削除。）

(d) 手動遷移: `set_axis_range:639` の `set_range` 呼出の直前に `self._axes[axis_index].y_is_auto = False`。`y_range` setter（`:209-212`）の `set_range` 直前に `self._axes[0].y_is_auto = False`（`zoom_axis`/`set_y_range` は両 funnel 経由で自動カバー — spec §3.3 の全数確認済み）。

(e) `add_signal` docstring（`:241-242`）を「Auto-fits x_range and each auto axis's y_range to the union of its *visible* signals」へ更新。

- [ ] **Step 4: パス確認＋既存無回帰**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py tests/gui/test_graph_panel_multi_axis.py tests/gui/test_context_menus.py -v`
Expected: 全 PASS（reset 系の None クリア lock `:849-860`/`:207-215` は挙動維持で green）

- [ ] **Step 5: Commit** — `git commit -am "fix(gui): Y軸 per-axis auto フラグ＋可視和集合フィット (UX-03 auto 側)"`

---

### Task 4: 内容総入替時のレンジリセット（overwrite_axis / placeholder）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`overwrite_axis:285-297`・`_compact_axes:424-430`）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Produces: overwrite/全削除 placeholder 経路で `y_range=None`・`y_is_auto=True` に戻る保証（後続の add が必ずフィット）。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_overwrite_axis_resets_manual_range(vm_with_two_scales):
    # spec §3.5-1: 総入替後の軸は旧内容の手動レンジを引き継がない。
    vm, key_big, key_small = vm_with_two_scales
    vm.add_signal(key_big)
    vm.set_axis_range(0, 1000.0, 2000.0)
    vm.overwrite_axis(key_small, 0)
    assert vm.axes[0].y_is_auto is True
    lo, hi = vm.axes[0].y_range
    assert lo <= 0.0 and hi <= 200.0  # small にフィット (現行は 1000-2000 のまま fail)


def test_placeholder_collapse_resets_manual_range(vm_with_two_scales):
    # spec §3.5-2: 手動ズーム→全削除→追加で 1 本目が不可視にならない。
    vm, key_big, key_small = vm_with_two_scales
    vm.add_signal(key_big)
    vm.set_axis_range(0, 1000.0, 2000.0)
    vm.remove_entry(vm._plotted[0].entry_id)
    assert vm.axes[0].y_is_auto is True and vm.axes[0].y_range is None
    vm.add_signal(key_small)
    assert vm.axes[0].y_range[1] <= 200.0
```

- [ ] **Step 2: 失敗を確認** — Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "overwrite_axis_resets or placeholder_collapse" -v` → FAIL

- [ ] **Step 3: 実装**

`overwrite_axis` のエントリ除去直後に:

```python
        if 0 <= axis_index < len(self._axes):
            ax = self._axes[axis_index]
            # 内容総入替 — 旧内容に紐づく手動レンジは無意味 (spec §3.5-1)。
            ax.y_range = None
            ax.y_is_auto = True
```

`_compact_axes` の placeholder 分岐（`:426-428`）に:

```python
            # 全削除 = 内容総入替の対称 — 旧手動レンジ/フラグを持ち越すと
            # 空パネル 1 本目が off-scale で始まる (spec §3.5-2・レビュー捕捉)。
            keep.y_range = None
            keep.y_is_auto = True
```

- [ ] **Step 4: パス確認** — Run: `uv run pytest tests/gui/ -v` → 全 PASS
- [ ] **Step 5: Commit** — `git commit -am "fix(gui): 総入替/全削除時に手動Yレンジをリセット (spec §3.5)"`

---

### Task 5: 変異トリガ全数接続（move / insert / 可視性トグル / legacy）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`move_entry_to_new_axis:718-740`・`insert_axis:378-412`・`toggle_entry_visibility:566-573`・`toggle_axis_visibility:600-613`・`toggle_visibility:557-564`・`remove_signal`/`remove_entry`/`remove_axis`/`prune_missing_signals` の refit）
- Test: `tests/gui/test_graph_panel_vm.py`, `tests/gui/test_graph_panel_multi_axis.py`, `tests/gui/test_graph_area_vm.py`

**Interfaces:**
- Consumes: Task 2 `_recalc_axis_labels` / Task 3 `_auto_fit_ranges`（auto ゲート版）
- Produces: spec §3.7 全数表どおりの再計算＋refit（membership 変異 = recalc+refit / 可視性のみ = refit のみ）。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_move_entry_to_new_axis_fits_and_labels(vm_with_two_scales):
    # UX-02 根治: 移動先の新軸が 0-1 既定のままにならず、ラベルも付く。
    vm, key_big, key_small = vm_with_two_scales
    vm.add_signal(key_big)
    vm.add_signal(key_small)
    small_id = next(e.entry_id for e in vm._plotted if e.signal_key == key_small)
    vm.move_entry_to_new_axis(small_id)
    new_axis = vm.axes[-1]
    assert new_axis.y_range is not None          # 現行 None で fail
    assert new_axis.y_range[1] <= 200.0
    assert new_axis.name == key_small.split("::")[-1]
    # 移動元 (auto) も残存 big のみへ再フィット
    assert vm.axes[0].y_range[0] >= 799


def test_axis_visibility_toggle_refits_auto_axis(vm_with_two_scales):
    # H キー軸フォールバック経路 (spec レビュー捕捉: H×2 往復で UX-03 再発を防ぐ)。
    vm, key_big, key_small = vm_with_two_scales
    vm.add_signal(key_big)
    vm.add_signal(key_small)
    small_id = next(e.entry_id for e in vm._plotted if e.signal_key == key_small)
    vm.toggle_entry_visibility(small_id)         # small 非表示 → big のみ
    assert vm.axes[0].y_range[0] >= 799
    vm.toggle_axis_visibility(0)                 # 軸一括 OFF → 対象空 → クリア
    assert vm.axes[0].y_range is None
    vm.toggle_axis_visibility(0)                 # 軸一括 ON → 全可視で和集合
    lo, hi = vm.axes[0].y_range
    assert lo <= 0.0 and hi >= 2275.0


def test_remove_entry_refits_auto_axis(vm_with_two_scales):
    vm, key_big, key_small = vm_with_two_scales
    vm.add_signal(key_big)
    vm.add_signal(key_small)
    big_id = next(e.entry_id for e in vm._plotted if e.signal_key == key_big)
    vm.remove_entry(big_id)
    assert vm.axes[0].y_range[1] <= 200.0
```

クロスパネル軸移動（`tests/gui/test_graph_area_vm.py` へ）:

```python
def test_cross_panel_insert_axis_recalcs_and_fits(area_vm_two_panels_two_scales):
    # spec §3.7: YAxisVM はオブジェクトごと移送 (y_is_auto も運ばれる)。
    # auto 軸は挿入先で即フィット・手動軸は温存。
    area, src_vm, dst_vm, key_big = area_vm_two_panels_two_scales
    src_vm.add_signal(key_big)
    extracted = src_vm.extract_axis(0)
    assert extracted is not None
    axis, entries = extracted
    dst_vm.insert_axis(axis, entries, column=dst_vm.column_count - 1, position=None)
    assert dst_vm.axes[-1].name == key_big.split("::")[-1]
    assert dst_vm.axes[-1].y_range is not None
```

- [ ] **Step 2: 失敗を確認** — Run: `uv run pytest tests/gui -k "move_entry_to_new_axis_fits or visibility_toggle_refits or remove_entry_refits or cross_panel_insert" -v` → FAIL

- [ ] **Step 3: 実装**

(a) `move_entry_to_new_axis` 末尾（`_relayout_columns()` の後・`_invalidate_cache()` の前）に:

```python
        # UX-02: 作成系 (create_new_axis→add_signal_to_axis) と同経路 —
        # 新軸は y_is_auto=True で生まれ即フィット・ラベルも代表から再導出。
        self._recalc_axis_labels()
        self._auto_fit_ranges()
```

(b) `insert_axis` 末尾（`_notify("signals")` の前）に同 2 行（コメント: 「クロスパネル移送 — auto 軸は挿入先の文脈で即フィット (spec §3.7)」）。

(c) `toggle_entry_visibility` / `toggle_axis_visibility` / legacy `toggle_visibility` の `_invalidate_cache()` の前に `self._auto_fit_ranges()`（membership 不変なので recalc は不要 — その旨コメント）。

(d) Task 2 で recalc を入れた `remove_signal` / `remove_entry` / `remove_axis` / `prune_missing_signals` の recalc 直後に `self._auto_fit_ranges()` を追加。

- [ ] **Step 4: パス確認＋フル** — Run: `uv run pytest tests/gui -v` → 全 PASS（`test_graph_panel_multi_axis.py:1349-1390` の move 既存 assert は不変で green）
- [ ] **Step 5: Commit** — `git commit -am "fix(gui): 変異トリガ全数へ再計算+refit を接続 (UX-02・spec §3.7)"`

---

### Task 6: View ラベル共有ヘルパ（2 サイト＋空クリア）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（fast path `:1068-1075`・rebuild `:1195-1196`）
- Test: `tests/gui/test_graph_panel_multi_axis.py`

**Interfaces:**
- Produces: モジュール関数 `_apply_axis_label(axis_item, axis_vm) -> None`（両サイトの唯一のラベル適用経路）。

- [ ] **Step 1: 失敗するテストを書く**

fixture `built_view_two_units` を本タスクで新設する（Task 7 も使う）: 既存の
`test_graph_panel_multi_axis.py` の view 構築 fixture（`:450-471` のテストが使う型）を複製し、
(1) CSV 2 信号のセッション＋`GraphPanelVM`、(2) `sig.metadata["unit"]` に "V"/"A" を注入、
(3) `GraphPanelView(vm)` を qtbot 管理で構築し `vm.add_signal(key_a)`＋`view.refresh()` 済み、
の `(view, vm, key_a, key_b)` を返す。

```python
def test_label_updates_via_fast_path_on_join(qtbot, built_view_two_units):
    # UX-01 主経路: join は構造署名不変 = fast path。fresh 構築だけの assert は
    # rebuild 側しか通らず false-green (memory gui_diff_update_layout_key...)。
    view, vm, key_a, key_b = built_view_two_units  # 構築済み・key_a(unit V) 表示中
    vm.add_signal(key_b)                            # unit A を join (軸数不変)
    view.refresh()
    assert view._y_axes[0].labelUnits == "V"        # 代表維持 (last-wins なら "A")


def test_label_cleared_via_fast_path_on_last_removal(qtbot, built_view_two_units):
    view, vm, key_a, _ = built_view_two_units
    vm.remove_entry(vm._plotted[0].entry_id)        # 全削除 → placeholder (署名不変)
    view.refresh()
    # 旧ガード (name or unit のときのみ setLabel) は空への遷移で画面に
    # 死んだラベルを残した (spec レビュー blocker)。
    assert view._y_axes[0].labelText in ("", None) or not view._y_axes[0].label.isVisible()
```

- [ ] **Step 2: 失敗を確認** — Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k "fast_path" -v` → FAIL（clear 側）

- [ ] **Step 3: 実装**

モジュールレベルに（`GraphPanelView` クラス定義の前）:

```python
def _apply_axis_label(axis_item: pg.AxisItem, axis_vm: YAxisVM) -> None:
    """軸ラベル適用の唯一の経路 (fast path / rebuild 共有・spec §3.2).

    両方空のときも明示的にクリアする — 旧ガード (真のときのみ setLabel) は
    「空への遷移」(全削除→placeholder・構造署名不変) で古いラベルを画面に
    残した (Stage A 設計レビュー blocker)。
    """
    if axis_vm.name or axis_vm.unit:
        axis_item.setLabel(text=axis_vm.name or None, units=axis_vm.unit or None)
    else:
        axis_item.setLabel(text="", units=None)
        axis_item.showLabel(False)
```

fast path `:1068-1075` のループ本体と rebuild `:1195-1196` の条件付き setLabel を、どちらも `_apply_axis_label(self._y_axes[i], axis_vm)` / `_apply_axis_label(axis, axis_vm)` の無条件呼出に置換。

- [ ] **Step 4: パス確認** — Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py tests/gui/test_graph_panel_view.py -v` → 全 PASS
- [ ] **Step 5: Commit** — `git commit -am "fix(gui): 軸ラベル適用を共有ヘルパ化 (2サイト+空クリア・UX-01 view側)"`

---

### Task 7: オフスケールバッジ（判定純関数＋scene item＋クリック）

**Files:**
- Create: `src/valisync/gui/views/offscale_badge.py`
- Modify: `src/valisync/gui/views/graph_panel_view.py`（refresh の曲線描画後にバッジ同期・`_sync_overlay_geometry` で位置更新・クリック→`vm.reset_axis_y`）
- Test: `tests/gui/test_offscale_badge.py`（新規）

**Interfaces:**
- Produces:
  - 純関数 `offscale_directions(y_range: tuple[float, float], curve_windows: list[tuple[float, float] | None]) -> tuple[bool, bool]`（(上外れあり, 下外れあり)。`curve_windows` は**可視エントリごとの「render と同一 X 窓スライス済み RenderCurve.values の有限 min/max」**、サンプル無し/全 NaN は None で渡し判定対象外 — spec §3.6）
  - `OffscaleBadge(QGraphicsObject)`: `direction: str ("up"|"down")`・`clicked` シグナル・`boundingRect` ≥ 18×18px・tooltip「レンジ外の曲線あり — クリックでフィット」・色 `tokens.active().colors.accent_active`・`setZValue(30)`（曲線より上）
- Consumes: `vm.reset_axis_y(axis_index)`（Task 3 で auto 復帰＋フィット化済み）

- [ ] **Step 1: 判定純関数の失敗テスト**

```python
from valisync.gui.views.offscale_badge import offscale_directions


def test_offscale_above_and_below():
    assert offscale_directions((0.0, 10.0), [(20.0, 30.0)]) == (True, False)
    assert offscale_directions((0.0, 10.0), [(-9.0, -1.0)]) == (False, True)
    assert offscale_directions((0.0, 10.0), [(20.0, 30.0), (-9.0, -1.0)]) == (True, True)


def test_partial_clip_and_inside_are_not_offscale():
    # 部分クリップはレンジ内に手掛かりが残る — バッジ対象外 (spec §3.6)。
    assert offscale_directions((0.0, 10.0), [(5.0, 30.0)]) == (False, False)
    assert offscale_directions((0.0, 10.0), [(1.0, 9.0)]) == (False, False)


def test_none_windows_are_ignored():
    # X 窓内サンプル無し / 全 NaN は「フィットしても見えない」ため通知は嘘になる。
    assert offscale_directions((0.0, 10.0), [None, None]) == (False, False)
```

- [ ] **Step 2: 失敗を確認** — Run: `uv run pytest tests/gui/test_offscale_badge.py -v` → FAIL (import error)

- [ ] **Step 3: 実装（offscale_badge.py）**

```python
"""手動レンジ時のオフスケール通知バッジ (Stage A spec §3.6・UX-03 の手動側).

判定は純関数 (Layer A)・表示/クリックは QGraphicsObject (Layer B/C)。
判定母集合は「render と同一の X 窓スライス済み可視カーブの有限値域」—
全信号値域で判定すると窓内だけ範囲外を見逃し/窓内可視を誤点灯する
(設計レビュー捕捉)。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsObject

from valisync.gui.theme import tokens

_BADGE_PX = 18  # クリック可能な当たり判定 (24px 未満ターゲット批判 UX-38 を踏まえ最低 18)


def offscale_directions(
    y_range: tuple[float, float],
    curve_windows: list[tuple[float, float] | None],
) -> tuple[bool, bool]:
    """(上外れあり, 下外れあり) — 完全にレンジ外のカーブがある方向 (spec §3.6)."""
    lo, hi = min(y_range), max(y_range)
    above = any(w is not None and w[0] > hi for w in curve_windows)
    below = any(w is not None and w[1] < lo for w in curve_windows)
    return above, below


class OffscaleBadge(QGraphicsObject):
    """▲/▼ のクリック可能バッジ。クリック = この軸をオートフィット."""

    clicked = Signal()

    def __init__(self, direction: str) -> None:
        super().__init__()
        self._direction = direction
        self.setZValue(30)  # 曲線より上 — z 沈没は isVisible では検出できない
        self.setToolTip("レンジ外の曲線あり — クリックでフィット")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self) -> QRectF:  # noqa: N802 (Qt override)
        return QRectF(0, 0, _BADGE_PX, _BADGE_PX)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        c = tokens.active().colors.accent_active
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.r, c.g, c.b, c.a))
        r = self.boundingRect().adjusted(4, 4, -4, -4)
        if self._direction == "up":
            pts = [r.bottomLeft(), r.bottomRight(), QRectF(r).center() - type(r.center())(0, r.height() / 2)]
        else:
            pts = [r.topLeft(), r.topRight(), QRectF(r).center() + type(r.center())(0, r.height() / 2)]
        from PySide6.QtGui import QPolygonF

        painter.drawPolygon(QPolygonF([pts[0], pts[1], pts[2]]))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # accept してプロット内クリック (R15 カーソル設置等) へ流さない (spec §3.6)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        event.accept()
        self.clicked.emit()
```

（三角形の頂点計算は実装時に `QPointF` で素直に書き直してよい — 意図は「上向き/下向きの塗り三角」。）

- [ ] **Step 4: view 統合（graph_panel_view.py）**

refresh の曲線更新後に軸ごとのバッジ同期を追加。実装方針（正確な挿入点は refresh 内の RenderCurve 消費部）:

```python
    def _sync_offscale_badges(self, curves: list[RenderCurve]) -> None:
        """手動軸のオフスケールバッジを再評価する (spec §3.6).

        判定入力は render と同一の X 窓スライス済み RenderCurve — LOD は
        バケット min/max を保存するため値域判定に安全。評価は signals/axes/
        range 変異後の refresh のみ (cursor/offsets ドラッグでは呼ばれない)。
        """
        by_axis: dict[int, list[tuple[float, float] | None]] = {}
        for c in curves:
            finite = c.values[np.isfinite(c.values)]
            win = (float(finite.min()), float(finite.max())) if len(finite) else None
            by_axis.setdefault(c.axis_index, []).append(win)
        for i, axis_vm in enumerate(self.vm.axes):
            up = down = False
            if not axis_vm.y_is_auto and axis_vm.y_range is not None:
                up, down = offscale_directions(axis_vm.y_range, by_axis.get(i, []))
            self._set_badge(i, "up", up)
            self._set_badge(i, "down", down)
```

`_set_badge` はバッジ item の生成/破棄と scene 追加を管理し、`clicked` を `lambda i=i: self.vm.reset_axis_y(i)` へ接続。位置は `_sync_overlay_geometry` で**当該軸リージョン内・プロット矩形（全列ガターの右）の左縁の上端/下端**（列非依存 — spec §3.6）に配置。リージョン高が `3 * _BADGE_PX` 未満なら外れ方向優先で 1 個に集約。RenderCurve は不可視エントリを含まない（render_data が可視のみ返すことを確認し、含むなら visible フィルタを追加）。

Layer B テスト（同ファイルに追記）:

```python
def test_badge_click_calls_reset_axis_y(qtbot, built_view_two_units):
    view, vm, key_a, key_b = built_view_two_units
    vm.add_signal(key_b)
    vm.set_axis_range(0, 1000.0, 2000.0)   # 手動化 + 全カーブがレンジ外になる値
    view.refresh()
    badges = [it for it in view.plot_widget.scene().items() if isinstance(it, OffscaleBadge)]
    assert badges                            # 表示条件 (Layer A の状態側)
    badges[0].clicked.emit()                 # クリック配線の Layer B (実クリックは Task 9)
    assert vm.axes[0].y_is_auto is True
```

- [ ] **Step 5: パス確認** — Run: `uv run pytest tests/gui/test_offscale_badge.py tests/gui/test_graph_panel_view.py -v` → PASS
- [ ] **Step 6: ゲート** — `uv run ruff check && uv run ruff format && uv run mypy src/` → PASS
- [ ] **Step 7: Commit** — `git commit -am "feat(gui): オフスケールバッジ (手動レンジ×レンジ外曲線の通知・UX-03)"`

---

### Task 8: 既存 realgui 拡張（Layer C — UX-01 join / UX-02 move）

**Files:**
- Modify: `tests/realgui/test_signal_dnd_realclick.py`（H3 join へ unit 注入＋ラベル assert）
- Modify: `tests/realgui/test_axis_menu_offset.py`（fixture `_two_curve_one_axis_panel:210-248` の値域変更＋`test_real_curve_menu_move_to_new_axis:410-443` へ assert 追加＋docstring `:210-218` 追随）

**Interfaces:**
- Consumes: 既存 `_realgui_input`／`_open_menu_click_item:146-204`／`_curve_point_phys:131-143` ヘルパ（変更しない）

- [ ] **Step 1: H3 join テスト拡張** — fixture の 2 信号ロード直後に unit 注入（Layer B パターン `test_graph_panel_multi_axis.py:458-461` と同型）:

```python
    sig_map = window.app_vm.session.signal_map()
    sig_map[key_a].metadata["unit"] = "V"
    sig_map[key_b].metadata["unit"] = "A"
```

join 完了後の assert に追加:

```python
    # UX-01: 異単位 join でも軸ラベルは代表 (1本目) の対のまま
    axis_item = panel_view._y_axes[0]
    assert axis_item.labelUnits == "V"
```

- [ ] **Step 2: move テスト拡張** — fixture の信号 b を 0..1 → **-5..5**（`b = -5 + 10 * i / 49`）へ変更（現行値域は pyqtgraph 既定 0..1 と一致し、バグのままでもピクセルが出て Red にならない — spec レビュー捕捉）。`test_real_curve_menu_move_to_new_axis` の実クリック後に:

```python
    new_axis = panel_vm.axes[-1]
    assert new_axis.y_range is not None and new_axis.y_range[0] <= -4.9
    assert panel_view._y_axes[-1].labelText  # ラベル伝搬
    # FU-12 型: 移動曲線の色ピクセルが新リージョン内に実在 (grabWindow 走査)
```

ピクセル走査は `tests/realgui/test_fu12_boundary_data_visible.py` の QImage 走査ヘルパ実装を同型で移植（曲線色は `panel_vm` の entry color から取得）。docstring `:210-218` の「_auto_fit_ranges は y_range None の間のみフィット」を「auto フラグの間は可視和集合へ常時フィット (Stage A)」へ更新。

- [ ] **Step 3: 実行（ローカル実ディスプレイ）**

Run: `uv run pytest --realgui tests/realgui/test_signal_dnd_realclick.py tests/realgui/test_axis_menu_offset.py -v`
Expected: 全 PASS＋スクショ証拠保存（fixture 値域変更による同ファイル内の既存 assert への影響を確認・必要な期待値を新値域へ追随）

- [ ] **Step 4: Commit** — `git commit -am "test(realgui): UX-01 join ラベル/UX-02 move フィットの実OS検証を拡張"`

---

### Task 9: 新設 realgui（バッジ実クリック＋プロット内クリック非干渉）

**Files:**
- Create: `tests/realgui/test_offscale_badge.py`

**Interfaces:**
- Consumes: `_realgui_input.at()`（実 OS クリック）・`test_axis_menu_offset.py:462-503` の before/after レンジ assert 雛形・FU-12 型ピクセル走査

- [ ] **Step 1: テストを書く**（シナリオ）

1. 実アプリ（`build_main_window`・QSettings 隔離 conftest）に 2 スケール信号を同軸で表示 → 軸メニュー「ズームイン」実クリックで手動化＋片方をレンジ外へ
2. **ピクセル走査でバッジ出現を確認**（`isVisible` は z 沈没を見逃す嘘プロキシ — spec honest note）
3. バッジ位置（scene→viewport→スクリーン座標変換・widget 空間規約 memory `gui_realgui_zone_widgetspace_and_offscreen_clamp`）を実 OS クリック → `axes[0].y_range` が和集合値へ復帰・`y_is_auto is True`（before/after 数値 assert）
4. バッジ消滅をピクセルで確認
5. **非干渉**: バッジ非表示状態で同座標を実クリック → R15 カーソルが設置される（既存挙動の維持）／バッジ表示中はカーソルが設置されない（バッジが accept）

- [ ] **Step 2: 実行** — Run: `uv run pytest --realgui tests/realgui/test_offscale_badge.py -v` → PASS＋スクショ証拠
- [ ] **Step 3: 掴み点無回帰（バッジはプロット内クリック意味論と共存 — spec 監査差替え）**

Run: `uv run pytest --realgui tests/realgui/test_global_cursor.py tests/realgui/test_curve_direct_ops.py tests/realgui/test_axis_menu_offset.py tests/realgui/test_click_activate_axis.py -v`
Expected: 全 PASS（誤侵入は assert 失敗でなくハングとして現れるため watchdog 既定に従う）

- [ ] **Step 4: Commit** — `git commit -am "test(realgui): オフスケールバッジ実クリック+非干渉 (①ゲート)"`

---

### Task 10: 凍結ベースライン更新・full ゲート・①ゲート

**Files:**
- Modify: `design_export/`（gitignore — ローカル成果物）・必要なら `docs/design.md` 決定履歴

- [ ] **Step 1: full 品質ゲート** — `uv run pytest && uv run ruff check && uv run ruff format && uv run mypy src/` → 全 PASS
- [ ] **Step 2: 凍結スクショ（意図的差分の確認 — spec §5 末尾）**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_stage_a_dark --theme dark --catalog
uv run python scripts/compare_screenshots.py design_export/dark/ground_truth design_export/screenshots_stage_a_dark || true
```

- `01_welcome`・`06`/`07`/`08` は**完全一致**を要求。
- `02-05`・`09` は**意図的差分**: 差分内容が「軸レンジ [800,2275]→[0,2275]＋VehSpd の初可視化（＋目盛/曲線形状）」のみであることを目視確認（それ以外の差分は回帰として調査）。light も同様に撮影。
- 新ベースライン採用＋Ground Truth 再同期（DesignSync — docs/design.md 運用ループ手順4-5）は merge 後の反映作業としてユーザーへ提示。

- [ ] **Step 3: ①ゲート（/gui-verify）** — scoped realgui 全証拠＋体感確認:
  - `- [ ] uv run pytest --realgui tests/realgui/test_signal_dnd_realclick.py`＋証拠
  - `- [ ] uv run pytest --realgui tests/realgui/test_axis_menu_offset.py`＋証拠
  - `- [ ] uv run pytest --realgui tests/realgui/test_offscale_badge.py`＋証拠
  - `- [ ] quick_demo.mf4 実機: 追加・H トグル連打・オフセット適用中の追加で体感遅延なし（spec §3.3 perf・オフセット枝）`
- [ ] **Step 4: Commit（残差分）＋プランのチェックボックス更新**

---

## 実施順序と依存

Task 1 → 2 → 3 → 4 → 5（VM 完結）→ 6（view ラベル）→ 7（バッジ）→ 8/9（realgui・実ディスプレイ必須）→ 10（ゲート）。
Task 8/9 はローカルのみ（CI 除外）。PR は本ブランチ（CLAUDE.md/roadmap ポインタ 2 コミットを含む）で 1 本。
