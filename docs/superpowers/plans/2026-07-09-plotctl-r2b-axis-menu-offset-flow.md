# plotctl 増分2b（Y軸右クリックメニュー＋オフセット導線）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 曲線・軸の直接操作の残り（PC-06/PC-03）を実装する — Y軸右クリックメニュー（オートフィット/範囲指定/削除/曲線一覧チェック式）、曲線メニュー拡張（新しい軸へ移動・時間オフセット…・オフセットをリセット…・情報行）、および時間オフセットのリセット導線を、`entry_id` 指名と DI 注入ダイアログの既存作法に乗せて追加する。

**Architecture:** MVVM 厳守（View → ViewModel → Session の一方向のみ・View から core 直接参照禁止）。VM に軸構造 API（`reset_axis_y`/`remove_axis`/`entries_on_axis`/`move_entry_to_new_axis`）とオフセット getter（`offset_for`）を追加し、`AppViewModel.reset_offset` を既存 `apply_offset` と対称に置いて既存 `'offsets'` ブロードキャスト経路にそのまま乗せる。View 側は `contextMenuEvent` のルーティングに軸分岐を挿入し、右クリックメニュー3種（曲線/軸/空白）を pos ベースのヒットテスト1箇所で振り分ける。全ダイアログ（軸範囲・オフセット数値・リセットスコープ）は DI 注入で headless テスト時にスタブ可能にする。

**Tech Stack:** Python 3.13 / PySide6 (Qt6) / pyqtgraph / MVVM。テストは pytest + pytest-qt（Layer A/B）＋ `--realgui` 実 OS 入力（Layer C）。品質ゲート: `uv run pytest` / `ruff check` + `ruff format --check` / `mypy src/`。

## Global Constraints

以下は全タスクに暗黙に適用される（spec より逐語）:

- **MVVM 境界**: View は VM 経由でのみ操作。View から `Session`/core を直接触らない。VM は `_notify(<topic>)` で View へ通知（Observable）。
- **cache invalidate + notify 規約**: VM の状態変更で描画が変わる操作は **`_invalidate_cache()` ＋ `_notify(...)` 必須**。特に **render cache-key は「可視 signal_key タプル」であり、色・軸割当（axis_index）は key に含まれない** — これらを変える操作（`set_color`・`move_entry_to_new_axis`）は明示的に `_invalidate_cache()` しないと古い RenderCurve が返る（2a `set_color` の先例・memory の教訓）。
- **entry_id 指名**: 曲線操作は `entry_id`（VM 採番の単調増分 int・VM 内一意）で指名。View 内部辞書（`_items`/`_item_vb`/`_item_signal_key`）は entry_id キー。offset は per-signal 適用なので emit 時に `signal_key_for_entry`/`_item_signal_key` で signal_key へ解決する。
- **ダイアログは DI 注入**: 軸範囲・オフセット数値・リセットスコープ・QColorDialog は全てコンストラクタ引数の DI シーム（既存 `apply_dialog_fn`(:660)・`color_dialog_fn`(:661) パターン）で注入し、テスト時スタブ・realgui でネイティブモーダルを駆動しない。
- **disabled 項目にツールチップを付ける場合は `menu.setToolTipsVisible(True)` 併設**（QMenu 既定で QAction ツールチップ非表示 — 文字列 assert だけの Layer B は false-green）。本増分では必須ではないが該当時は従う。
- **右クリックルーティング優先順（spec §4.3）**: カーソル線 → 曲線 → Y軸 → 空白（パネル）。カーソル線分岐は増分3で先頭に差し込むため、本増分では **曲線 → Y軸 → 空白** の3分岐を、カーソル分岐を後から先頭に挿せる形で実装する。
- **軸ヒットテストの 0-fallback 曖昧性**: `_axis_index_at`(:1411) は「軸0にヒット」も「どの軸にもヒットせず」も `0` を返す（`int`・`None` 非返却）。軸メニュー分岐は **必ず先に `_zone_at(pos) in (ZONE_Y_INNER, ZONE_Y_OUTER)` で gate** してから `_axis_index_at` を呼ぶ（`dropEvent`:1969 と同じ作法）。
- **品質ゲート**: 各コミット前に `uv run pytest` 全通過・`ruff check`・`ruff format --check`・`mypy src/` 全通過。ゲートを `| tail` 等に通さない（exit code 隠蔽防止）。
- **realgui は実 OS 入力のみ**: 新規 realgui は `_realgui_input` ヘルパの実 OS 入力＋スクショ AI 判定。`qtbot.mouseClick`/`trigger()` の合成は Layer C を名乗れない（Layer C 契約ガード `tests/gui/test_realgui_layer_c_contract.py` が CI で合成を検出して落とす）。

---

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `src/valisync/gui/viewmodels/graph_panel_vm.py` | パネル VM。軸構造 API とオフセット getter を追加 | Modify（新規メソッド5本追加） |
| `src/valisync/gui/viewmodels/app_viewmodel.py` | アプリ VM。`reset_offset` を追加 | Modify（`apply_offset`:58 と対称） |
| `src/valisync/gui/viewmodels/graph_area_vm.py` | エリア VM。`reset_offset` 転送を追加 | Modify（`apply_offset`:295 と対称） |
| `src/valisync/gui/views/graph_area_view.py` | エリア View。`offset_reset_requested` を配線 | Modify（`_wire_panel`:204） |
| `src/valisync/gui/views/graph_panel_view.py` | パネル View。軸メニュー・ルーティング軸分岐・曲線メニュー拡張・ダイアログ3種・DI シーム | Modify（主戦場） |
| `tests/gui/test_graph_panel_multi_axis.py` | 軸構造 API の Layer A | Modify |
| `tests/gui/test_graph_panel_vm.py` | offset_for の Layer A | Modify |
| `tests/gui/test_app_viewmodel.py` | reset_offset の Layer A | Modify |
| `tests/gui/test_graph_area_vm.py` | reset_offset 転送の Layer A | Modify |
| `tests/gui/test_graph_area_view.py` | offset_reset_requested 配線の Layer B | Modify |
| `tests/gui/test_graph_panel_view.py` | 軸/曲線メニュー・ルーティング・T4-c の Layer B | Modify |
| `tests/realgui/test_axis_menu_offset.py` | 軸/曲線メニューの実 OS 入力（Layer C） | Create |

新規テスト関数は既存ファイルへ追記（ファイルが無ければ作成）。実装者は各タスクの Files セクションの行番号を起点に周辺の既存パターンを確認すること。

---

### Task 1: GraphPanelVM 軸構造 API（`reset_axis_y`/`remove_axis`/`entries_on_axis`/`move_entry_to_new_axis`）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`set_axis_range`:575 の直後あたりに軸系メソッドを追記。`remove_entry`:533・`reset_y`:603・`create_new_axis`:261・`_compact_axes`:376・`_relayout_columns`:398 が踏襲元）
- Test: `tests/gui/test_graph_panel_multi_axis.py`

**Interfaces:**
- Consumes（既存・2a で確定）: `_PlottedEntry(signal_key, color, visible, axis_index, entry_id)`（:107）・`self._plotted: list[_PlottedEntry]`・`self._axes: list[YAxisVM]`・`self._column_count: int`・`_signal_map() -> dict[str, Signal]`（:1002・オフセット適用済み）・`_compact_axes()`（:376）・`_relayout_columns()`（:398）・`_invalidate_cache()`・`_notify(topic)`・`YAxisVM(column=...)`（y_axis_vm.py）・`Signal.sorted_view()`（`(ts, vs)` を返す）・`np.isfinite`
- Produces（後続タスクが依存）:
  - `reset_axis_y(self, axis_index: int) -> None`
  - `remove_axis(self, axis_index: int) -> None`
  - `entries_on_axis(self, axis_index: int) -> list[tuple[int, str, str, bool]]`（`(entry_id, signal_key, color, visible)`。signal_key を表示名として使う）
  - `move_entry_to_new_axis(self, entry_id: int) -> None`

**GUI テスト分析（gui-test-plan）:**
- 変更種別: 純 VM ロジック → **Layer A のみ**。realgui 不要。
- 実質性: 「どの軸がフィットされたか」「どの entry が残ったか」「新軸が増えて元 entry が移ったか」は VM の観測面（`vm.axes[i].y_range`・`vm.inspect()["axes"]`・`vm._plotted` 相当）で完全に自動アサート可。
- **`move_entry_to_new_axis` の invalidate は render 出力で検証する**（cache-key に axis_index が含まれないため、invalidate 漏れは「移動後も RenderCurve.axis_index が古いまま」という形で `render_data()` に現れる）。VM 内部だけ見る naive テストは invalidate 漏れを見逃す。

- [ ] **Step 1: 失敗するテストを書く（reset_axis_y）**

`tests/gui/test_graph_panel_multi_axis.py` に追記。既存ファイル冒頭の import・ヘルパ（`Session` にダミー信号を積む作法）は既存テストに倣う。

```python
def test_reset_axis_y_fits_only_target_axis(qtbot):
    """reset_axis_y は指定軸だけを可視値にフィットし、他軸の range は不変。"""
    session = _session_with_signals(  # 既存ヘルパ。無ければ既存テストの構築手順を再利用
        {"csv::a": ([0.0, 1.0, 2.0], [10.0, 30.0, 20.0]),
         "csv::b": ([0.0, 1.0, 2.0], [-5.0, -1.0, -3.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.create_new_axis("csv::b")  # -> axis 1
    # 軸1を故意に別レンジへ
    vm.set_axis_range(1, 100.0, 200.0)
    vm.reset_axis_y(0)
    assert vm.axes[0].y_range == (10.0, 30.0)
    assert vm.axes[1].y_range == (100.0, 200.0)  # 他軸不変


def test_reset_axis_y_excludes_invisible_entries(qtbot):
    session = _session_with_signals(
        {"csv::a": ([0.0, 1.0], [10.0, 30.0]),
         "csv::b": ([0.0, 1.0], [0.0, 999.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.add_signal_to_axis("csv::b", 0)  # 同じ軸0に2本
    # b を非表示にすると fit は a のみ
    eid_b = next(e for e, k, _c, _v in
                 [(e.entry_id, e.signal_key, e.color, e.visible) for e in vm._plotted]
                 if k == "csv::b")
    vm.toggle_entry_visibility(eid_b)
    vm.reset_axis_y(0)
    assert vm.axes[0].y_range == (10.0, 30.0)  # 999 は入らない


def test_reset_axis_y_out_of_range_is_noop(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.reset_axis_y(5)  # 範囲外 → 例外を投げず no-op
    vm.reset_axis_y(-1)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_reset_axis_y_fits_only_target_axis -v`
Expected: FAIL（`AttributeError: 'GraphPanelVM' object has no attribute 'reset_axis_y'`）

- [ ] **Step 3: `reset_axis_y` を実装**

`graph_panel_vm.py` の `set_axis_range`(:575) 直後に追加。`reset_y`(:603) の per-axis 本体を単一軸へ切り出す（可視性フィルタ・aligned view fit・None クリアを踏襲）。

```python
    def reset_axis_y(self, axis_index: int) -> None:
        """Fit one Y-axis to the visible values of the signals assigned to it.

        Single-axis version of reset_y (the axis-menu "この軸をオートフィット").
        Invisible entries are excluded and the fit uses the aligned (sorted,
        keep-last) view — the same window that is actually drawn. Clears to None
        when nothing is fittable so a later add_signal can auto-fit.
        """
        if not (0 <= axis_index < len(self._axes)):
            return
        sig_map = self._signal_map()
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
        self._axes[axis_index].set_range(lo, hi)
        self._invalidate_cache()
        self._notify("range")
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k reset_axis_y -v`
Expected: PASS（3件）

- [ ] **Step 5: 失敗するテストを書く（remove_axis）**

```python
def test_remove_axis_removes_all_entries_and_compacts(qtbot):
    session = _session_with_signals(
        {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0]), "csv::c": ([0.0], [3.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.create_new_axis("csv::b")  # axis 1
    vm.create_new_axis("csv::c")  # axis 2
    assert len(vm.axes) == 3
    vm.remove_axis(1)  # b の軸を削除
    remaining = {e.signal_key for e in vm._plotted}
    assert remaining == {"csv::a", "csv::c"}
    assert len(vm.axes) == 2  # compact 後


def test_remove_last_axis_collapses_to_placeholder(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.remove_axis(0)
    assert vm._plotted == []
    assert len(vm.axes) == 1  # 空プレースホルダへ collapse（_compact_axes 既存挙動）


def test_remove_axis_out_of_range_is_noop(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.remove_axis(9)
    assert {e.signal_key for e in vm._plotted} == {"csv::a"}
```

- [ ] **Step 6: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k remove_axis -v`
Expected: FAIL（`AttributeError: ... 'remove_axis'`）

- [ ] **Step 7: `remove_axis` を実装**

`reset_axis_y` の直後。`remove_entry`(:533)/`remove_signal`(:443) と同型（対象 axis_index の entry を除外 → `_compact_axes` → invalidate → notify）。

```python
    def remove_axis(self, axis_index: int) -> None:
        """Remove every entry on *axis_index* and reconcile axes (axis-menu 削除).

        Mirrors remove_entry but targets a whole axis: survivors keep their
        heights, the vacated band stays blank, and the panel collapses to a
        placeholder only when the last entry is removed (via _compact_axes).
        """
        if not (0 <= axis_index < len(self._axes)):
            return
        self._plotted = [e for e in self._plotted if e.axis_index != axis_index]
        self._compact_axes()
        self._invalidate_cache()
        self._notify("signals")
```

- [ ] **Step 8: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k remove_axis -v`
Expected: PASS（3件）

- [ ] **Step 9: 失敗するテストを書く（entries_on_axis）**

```python
def test_entries_on_axis_returns_tuples_for_that_axis(qtbot):
    session = _session_with_signals(
        {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.add_signal_to_axis("csv::b", 0)
    vm.create_new_axis("csv::b")  # b をもう1本、別軸1にも
    rows0 = vm.entries_on_axis(0)
    keys0 = {sk for _eid, sk, _c, _v in rows0}
    assert keys0 == {"csv::a", "csv::b"}
    # 返り値は (entry_id:int, signal_key:str, color:str, visible:bool)
    for eid, sk, color, visible in rows0:
        assert isinstance(eid, int)
        assert isinstance(sk, str)
        assert color.startswith("#")
        assert visible is True


def test_entries_on_axis_reflects_visibility(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    eid = vm._plotted[0].entry_id
    vm.toggle_entry_visibility(eid)
    rows = vm.entries_on_axis(0)
    assert rows[0][0] == eid
    assert rows[0][3] is False  # visible 反映
```

- [ ] **Step 10: 失敗を確認 → 実装 → 通過**

`entries_on_axis` を追加（純参照・notify なし）。`axis_of_entry`(:950) と同じ線形走査。

```python
    def entries_on_axis(self, axis_index: int) -> list[tuple[int, str, str, bool]]:
        """Return (entry_id, signal_key, color, visible) for every entry on *axis_index*.

        Drives the axis-menu curve list (checkable, includes hidden entries).
        signal_key doubles as the display label. Pure read — no notify.
        """
        return [
            (e.entry_id, e.signal_key, e.color, e.visible)
            for e in self._plotted
            if e.axis_index == axis_index
        ]
```

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k entries_on_axis -v` → PASS（2件）

- [ ] **Step 11: 失敗するテストを書く（move_entry_to_new_axis ＋ invalidate 検証）**

```python
def test_move_entry_to_new_axis_reassigns_and_compacts(qtbot):
    session = _session_with_signals(
        {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.add_signal_to_axis("csv::b", 0)  # a,b 同じ軸0
    assert len(vm.axes) == 1
    eid_b = next(e.entry_id for e in vm._plotted if e.signal_key == "csv::b")
    vm.move_entry_to_new_axis(eid_b)
    # b が新軸へ、a は元軸に残る → 2軸
    assert len(vm.axes) == 2
    ax_a = next(e.axis_index for e in vm._plotted if e.signal_key == "csv::a")
    ax_b = next(e.axis_index for e in vm._plotted if e.signal_key == "csv::b")
    assert ax_a != ax_b


def test_move_entry_to_new_axis_busts_render_cache(qtbot):
    """cache-key に axis_index は含まれない → invalidate 漏れは render_data の
    RenderCurve.axis_index が古いまま、という形で現れる（サボタージュ検出点）。"""
    session = _session_with_signals(
        {"csv::a": ([0.0, 1.0], [1.0, 2.0]), "csv::b": ([0.0, 1.0], [3.0, 4.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.add_signal_to_axis("csv::b", 0)
    _ = vm.render_data()  # キャッシュを温める
    eid_b = next(e.entry_id for e in vm._plotted if e.signal_key == "csv::b")
    vm.move_entry_to_new_axis(eid_b)
    curves = {c.entry_id: c for c in vm.render_data()}
    ax_a = next(e.axis_index for e in vm._plotted if e.signal_key == "csv::a")
    assert curves[eid_b].axis_index != curves[next(
        e.entry_id for e in vm._plotted if e.signal_key == "csv::a")].axis_index
    assert curves[eid_b].axis_index == next(
        e.axis_index for e in vm._plotted if e.signal_key == "csv::b")


def test_move_entry_unknown_id_is_noop(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.move_entry_to_new_axis(9999)
    assert len(vm.axes) == 1
```

- [ ] **Step 12: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k move_entry -v`
Expected: FAIL（メソッド未定義。もし空実装で invalidate 抜けを試すと `test_move_entry_to_new_axis_busts_render_cache` が RED）

- [ ] **Step 13: `move_entry_to_new_axis` を実装**

`create_new_axis`(:261) の骨格を再利用。**cache-key に axis_index が無いため `_invalidate_cache()` 必須**（create_new_axis は内部の add_signal_to_axis が invalidate するが、move は add しないので明示が要る）。

```python
    def move_entry_to_new_axis(self, entry_id: int) -> None:
        """Re-assign the entry with *entry_id* to a fresh Y-axis (曲線「新しい軸へ移動」).

        Mirrors create_new_axis's layout bookkeeping but moves an existing entry
        instead of adding a signal: a new axis is appended in the inner column,
        the entry is re-pointed to it, then _compact_axes prunes the now-empty
        source axis (no empty axes are left behind) and _relayout_columns re-splits
        equally. _invalidate_cache is explicit here because the render cache-key
        omits axis_index (a stale-cache curve would keep drawing on the old axis).
        """
        entry = next((e for e in self._plotted if e.entry_id == entry_id), None)
        if entry is None:
            return
        new_col = self._column_count - 1
        same_col = [a.top_ratio for a in self._axes if a.column == new_col]
        new_axis = YAxisVM(column=new_col)
        new_axis.top_ratio = (max(same_col) + 1.0) if same_col else 0.0
        self._axes.append(new_axis)
        entry.axis_index = len(self._axes) - 1
        self._compact_axes()
        self._relayout_columns()
        self._invalidate_cache()
        self._notify("axes")
```

- [ ] **Step 14: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k move_entry -v`
Expected: PASS（3件）

- [ ] **Step 15: フルスイート＋ゲート**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 16: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_multi_axis.py
git commit -m "feat(gui): GraphPanelVM 軸構造 API（reset_axis_y/remove_axis/entries_on_axis/move_entry_to_new_axis）"
```

---

### Task 2: オフセットのリセット end-to-end（`offset_for`＋`reset_offset`＋Signal＋配線）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`offset_for` を `set_offsets`:483 付近に追加）
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py`（`reset_offset` を `apply_offset`:58 の直後に。`_purge_signal_offsets_under`:83 を再利用）
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py`（`reset_offset` 転送を `apply_offset`:295 の直後に）
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`offset_reset_requested` Signal 宣言を `offset_apply_requested`:642 の直後に）
- Modify: `src/valisync/gui/views/graph_area_view.py`（`_wire_panel`:204 の `offset_apply_requested`(:220) 配線の直後に `offset_reset_requested` 配線）
- Test: `tests/gui/test_graph_panel_vm.py`・`tests/gui/test_app_viewmodel.py`・`tests/gui/test_graph_area_vm.py`・`tests/gui/test_graph_area_view.py`

**Interfaces:**
- Consumes: `AppViewModel._signal_offsets`/`_file_offsets`（:36）・`AppViewModel._purge_signal_offsets_under(group_key)`（:83）・`AppViewModel._notify("offsets")`・`AppViewModel.signal_offsets`/`file_offsets` プロパティ（:48）・`GraphAreaVM._app_vm`・`GraphPanelVM._signal_offsets`/`_file_offsets`（set_offsets が置換）・`GraphPanelView`（PySide6 `Signal`）
- Produces（後続タスクが依存）:
  - `GraphPanelVM.offset_for(self, signal_key: str) -> float`
  - `AppViewModel.reset_offset(self, signal_key: str, scope: str) -> None`
  - `GraphAreaVM.reset_offset(self, signal_key: str, scope: str) -> None`
  - `GraphPanelView.offset_reset_requested = Signal(str, str)`（`(signal_key, scope)`）— Task 4 の曲線メニューが emit

**GUI テスト分析（gui-test-plan）:**
- `offset_for`・`reset_offset`（加減算・`'offsets'` 通知）は **Layer A**（VM ロジック・主戦場）。
- `offset_reset_requested` → `GraphAreaVM.reset_offset` の配線は **Layer B**: `GraphPanelView` から実 emit → `_wire_panel` 経由で `AppViewModel` のオフセットが実際に 0 へ戻ることを、**spy だけでなく実配線で** end-to-end 検証（ルーティング破壊の false-green 防止）。
- honest layering note: `reset_offset` は独自の VM 通知経路を持たず、既存 `'offsets'` ブロードキャスト（`_on_app_change` の `elif change == "offsets"`:68）にそのまま乗る。従って `GraphPanelVM` 側に reset 専用メソッドは不要（`set_offsets` が dict 丸ごと置換 ＋ `_invalidate_cache`）。

- [ ] **Step 1: 失敗するテストを書く（offset_for）**

`tests/gui/test_graph_panel_vm.py` に追記。

```python
def test_offset_for_combines_signal_and_file_offsets(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.set_offsets({"csv::a": 0.25}, {"csv": 0.1})
    assert vm.offset_for("csv::a") == 0.35
    assert vm.offset_for("csv::b") == 0.1   # 同グループ file offset のみ
    assert vm.offset_for("other::x") == 0.0
```

- [ ] **Step 2: 失敗を確認 → 実装 → 通過**

`graph_panel_vm.py` に追加（`set_offsets`:483 の直後）:

```python
    def offset_for(self, signal_key: str) -> float:
        """Return the combined (signal + file) time offset applied to *signal_key*.

        Public getter over the private offset dicts set_offsets stores. Drives the
        curve menu's "オフセットをリセット…" enabled state and the "オフセット: +Xs"
        info row. Group key is the prefix before '::' (same convention as _signal_map).
        """
        group_key = signal_key.split("::", 1)[0]
        return self._file_offsets.get(group_key, 0.0) + self._signal_offsets.get(
            signal_key, 0.0
        )
```

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k offset_for -v` → PASS

- [ ] **Step 3: 失敗するテストを書く（AppViewModel.reset_offset）**

`tests/gui/test_app_viewmodel.py` に追記（`apply_offset` の既存テストに倣う）。

```python
def test_reset_offset_signal_scope_zeros_only_that_signal(qtbot):
    app = AppViewModel()
    app.apply_offset("csv::a", 0.5, "signal")
    app.apply_offset("csv::b", 0.3, "signal")
    events = []
    app.subscribe(events.append)
    app.reset_offset("csv::a", "signal")
    assert "offsets" in events                    # 通知が飛ぶ
    assert "csv::a" not in app.signal_offsets      # a は消える
    assert app.signal_offsets["csv::b"] == 0.3     # b は不変


def test_reset_offset_group_scope_zeros_file_and_purges_siblings(qtbot):
    app = AppViewModel()
    app.apply_offset("csv::a", 0.5, "signal")
    app.apply_offset("csv::a", 0.2, "group")   # file offset 付与＋兄弟 purge
    # group 適用で per-signal は purge 済み。念のため別 signal offset を足す
    app.apply_offset("csv::z", 0.9, "signal")
    app.reset_offset("csv::a", "group")
    assert "csv" not in app.file_offsets        # file offset 消える
    assert "csv::z" not in app.signal_offsets   # 同グループ per-signal も purge


def test_reset_offset_invalid_scope_raises(qtbot):
    app = AppViewModel()
    with pytest.raises(ValueError):
        app.reset_offset("csv::a", "bogus")
```

- [ ] **Step 4: 失敗を確認 → 実装 → 通過**

`app_viewmodel.py` の `apply_offset`(:58) 直後に、対称に追加:

```python
    def reset_offset(self, signal_key: str, scope: str) -> None:
        """Zero the time offset for *signal_key* and notify ('offsets').

        Symmetric to apply_offset: ``scope="signal"`` drops the per-signal offset;
        ``scope="group"`` drops the per-group (file) offset AND every sibling
        per-signal offset under the group prefix (whole group back to zero). Emits
        the same 'offsets' notification, so the existing GraphAreaVM broadcast
        re-renders every panel.
        """
        if scope == "signal":
            self._signal_offsets.pop(signal_key, None)
        elif scope == "group":
            group_key = signal_key.split("::", 1)[0]
            self._file_offsets.pop(group_key, None)
            self._purge_signal_offsets_under(group_key)
        else:
            raise ValueError(f"scope must be 'signal' or 'group', got {scope!r}")
        self._notify("offsets")
```

Run: `uv run pytest tests/gui/test_app_viewmodel.py -k reset_offset -v` → PASS（3件）

- [ ] **Step 5: 失敗するテストを書く（GraphAreaVM.reset_offset 転送 ＋ 配信）**

`tests/gui/test_graph_area_vm.py` に追記。

```python
def test_reset_offset_forwards_to_app_and_broadcasts(qtbot):
    session = _session_with_signals({"csv::a": ([0.0, 1.0], [1.0, 2.0])})
    app = AppViewModel(session=session)          # 既存構築作法に合わせる
    area = GraphAreaVM(app)
    panel = area.tabs[0].panels[0]               # 既存アクセサに合わせる
    panel.add_signal_to_axis("csv::a", 0)
    app.apply_offset("csv::a", 0.5, "signal")
    assert panel.offset_for("csv::a") == 0.5     # 配信済み
    area.reset_offset("csv::a", "signal")
    assert app.signal_offsets.get("csv::a") is None
    assert panel.offset_for("csv::a") == 0.0     # ブロードキャストで 0 へ
```

（`AppViewModel`/`GraphAreaVM` の構築・パネルアクセサは `test_graph_area_vm.py` の既存テストの作法をそのまま踏襲すること。）

- [ ] **Step 6: 失敗を確認 → 実装 → 通過**

`graph_area_vm.py` の `apply_offset`(:295) 直後に:

```python
    def reset_offset(self, signal_key: str, scope: str) -> None:
        """Forward an offset-reset request to the AppViewModel (View-layer wiring target).

        Symmetric to apply_offset; the resulting 'offsets' notification is handled
        by _on_app_change, which re-broadcasts the reduced offsets to every panel.
        """
        self._app_vm.reset_offset(signal_key, scope)
```

Run: `uv run pytest tests/gui/test_graph_area_vm.py -k reset_offset -v` → PASS

- [ ] **Step 7: 失敗するテストを書く（Signal 宣言 ＋ _wire_panel 配線・Layer B end-to-end）**

`tests/gui/test_graph_area_view.py` に追記（既存 `offset_apply_requested` 配線テストがあれば近くに）。

```python
def test_offset_reset_requested_reaches_app_viewmodel(qtbot):
    session = _session_with_signals({"csv::a": ([0.0, 1.0], [1.0, 2.0])})
    app = AppViewModel(session=session)
    area_view = GraphAreaView(GraphAreaVM(app))   # 既存構築作法に合わせる
    qtbot.addWidget(area_view)
    panel_view = area_view._first_panel_view()     # 既存アクセサ or tabs から取得
    panel_view.vm.add_signal_to_axis("csv::a", 0)
    app.apply_offset("csv::a", 0.5, "signal")
    assert panel_view.vm.offset_for("csv::a") == 0.5
    # 実 Signal を emit（曲線メニューが後で叩く経路と同一）
    panel_view.offset_reset_requested.emit("csv::a", "signal")
    assert app.signal_offsets.get("csv::a") is None
    assert panel_view.vm.offset_for("csv::a") == 0.0
```

（`GraphAreaView` 構築とパネル View 取得は `test_graph_area_view.py` の既存作法に合わせる。無ければ `area_view` の内部から最初の `GraphPanelView` を得るヘルパを既存テストに倣って用意。）

- [ ] **Step 8: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_area_view.py -k offset_reset_requested -v`
Expected: FAIL（`AttributeError: 'GraphPanelView' object has no attribute 'offset_reset_requested'`）

- [ ] **Step 9: Signal 宣言 ＋ 配線を実装**

`graph_panel_view.py` の `offset_apply_requested`(:640-642) の直後に:

```python
    # Emitted when the user confirms an offset-reset scope in the curve menu's
    # "オフセットをリセット…" dialog. GraphAreaView wires this to GraphAreaVM.reset_offset.
    offset_reset_requested = Signal(str, str)  # (signal_key, scope)
```

`graph_area_view.py` の `_wire_panel`(:204) 内、`offset_apply_requested` 配線(:220-222) の直後に:

```python
        widget.offset_reset_requested.connect(
            lambda k, sc: self.vm.reset_offset(k, sc)
        )
```

- [ ] **Step 10: 通過を確認 ＋ フルスイート＋ゲート**

Run: `uv run pytest tests/gui/test_graph_area_view.py -k offset_reset_requested -v`
Expected: PASS

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 11: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py src/valisync/gui/viewmodels/app_viewmodel.py src/valisync/gui/viewmodels/graph_area_vm.py src/valisync/gui/views/graph_panel_view.py src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_panel_vm.py tests/gui/test_app_viewmodel.py tests/gui/test_graph_area_vm.py tests/gui/test_graph_area_view.py
git commit -m "feat(gui): 時間オフセットのリセット導線（offset_for/reset_offset＋offset_reset_requested 配線）"
```

---

### Task 3: 軸右クリックメニュー＋ルーティング軸分岐＋範囲ダイアログ＋DI シーム

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（先頭 import に `import math`／コンストラクタ:656-666 に DI kwarg 3本／`build_axis_menu`・`_prompt_axis_range`・`_default_range_dialog` を `build_context_menu`:2079 付近に追加／`contextMenuEvent`:2116 に軸分岐挿入）
- Test: `tests/gui/test_graph_panel_view.py`

**Interfaces:**
- Consumes（Task 1）: `vm.reset_axis_y(axis_index)`・`vm.remove_axis(axis_index)`・`vm.entries_on_axis(axis_index)`・`vm.set_axis_range(axis_index, lo, hi)`（既存 :575）・`vm.toggle_entry_visibility(entry_id)`（既存 2a）・`vm.axes`（既存）
- Consumes（既存 View）: `_curve_at(pos) -> int | None`（:1560）・`_zone_at(pos) -> str`（:1406）・`_axis_index_at(pos) -> int`（:1411）・`ZONE_Y_INNER`/`ZONE_Y_OUTER`（:74-75）・`build_curve_menu`（:2053）・`build_context_menu`（:2079）
- Produces:
  - `build_axis_menu(self, axis_index: int) -> QMenu`
  - `_prompt_axis_range(self, axis_index: int) -> None`
  - `_default_range_dialog(self, axis_index: int, current: tuple[float, float] | None) -> tuple[float, float] | None`
  - コンストラクタ kwarg `range_dialog_fn`（DI シーム。`self._range_dialog_fn`）／`offset_input_dialog_fn`（`self._offset_input_dialog_fn`）／`reset_dialog_fn`（`self._reset_dialog_fn`）— **Task 4 が offset_input/reset を使う**。本タスクでは3本まとめて宣言し `range_dialog_fn` を配線する。

**GUI テスト分析（gui-test-plan）:**
- 変更種別: 入力イベント→ハンドラ（`contextMenuEvent` ルーティング）＋ウィジェット構成（メニュー構築）→ **Layer A（ルーティング純関数は無し）＋ Layer B 主戦場**。
- **ルーティングは実 `QContextMenuEvent` を送って検証**（ビルダー直呼びで済ませない — spec §11 Layer B の必須項目）。ただし `contextMenuEvent` は `menu.exec()`（モーダル）を呼ぶので、テストは **3ビルダーをスパイに差し替え、`.exec()` を no-op** にしてハングを避ける。分類器（`_curve_at`/`_zone_at`/`_axis_index_at`）は本テストではスタブして分岐だけを検証（幾何は既存 `_axis_index_at` テストが担保・2a の drop テストと同じ作法）。
- メニュー構築（項目・checkable・enabled・entries 反映）は Layer B。範囲ダイアログ本体（lo≥hi/非有限の OK 無効化）は DI シームのため headless では stub 経路のみ通し、default ダイアログの入力検証は realgui/手動で確認する旨を honest layering note に明記。
- realgui は Task 6 に集約。

- [ ] **Step 1: 失敗するテストを書く（ルーティング軸分岐）**

`tests/gui/test_graph_panel_view.py` に追記。ヘルパ:

```python
from types import SimpleNamespace
from PySide6.QtCore import QPoint
from PySide6.QtGui import QContextMenuEvent
from valisync.gui.views.graph_panel_view import ZONE_PLOT, ZONE_Y_INNER


def _spy_menus(view):
    """3ビルダーを記録スパイへ差し替え、.exec() を no-op にする。"""
    calls = []
    view.build_curve_menu = lambda eid: (  # type: ignore[method-assign]
        calls.append(("curve", eid)) or SimpleNamespace(exec=lambda *a: None)
    )
    view.build_axis_menu = lambda idx: (  # type: ignore[method-assign]
        calls.append(("axis", idx)) or SimpleNamespace(exec=lambda *a: None)
    )
    view.build_context_menu = lambda: (  # type: ignore[method-assign]
        calls.append(("panel", None)) or SimpleNamespace(exec=lambda *a: None)
    )
    return calls


def _ctx_event():
    return QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(10, 100))


def test_context_menu_routes_axis_when_on_y_zone(qtbot):
    view = _build_panel_view_with_axes(qtbot)   # 既存ヘルパ or 2軸構築
    view._curve_at = lambda pos: None           # type: ignore[method-assign]
    view._zone_at = lambda pos: ZONE_Y_INNER    # type: ignore[method-assign]
    view._axis_index_at = lambda pos: 1         # type: ignore[method-assign]
    calls = _spy_menus(view)
    view.contextMenuEvent(_ctx_event())
    assert calls == [("axis", 1)]


def test_context_menu_curve_wins_over_axis(qtbot):
    view = _build_panel_view_with_axes(qtbot)
    view._curve_at = lambda pos: 7              # type: ignore[method-assign]
    view._zone_at = lambda pos: ZONE_Y_INNER    # type: ignore[method-assign]
    calls = _spy_menus(view)
    view.contextMenuEvent(_ctx_event())
    assert calls == [("curve", 7)]              # 曲線が軸より優先


def test_context_menu_falls_back_to_panel_on_plot(qtbot):
    view = _build_panel_view_with_axes(qtbot)
    view._curve_at = lambda pos: None           # type: ignore[method-assign]
    view._zone_at = lambda pos: ZONE_PLOT       # type: ignore[method-assign]
    calls = _spy_menus(view)
    view.contextMenuEvent(_ctx_event())
    assert calls == [("panel", None)]
```

（`_build_panel_view_with_axes` は既存テストのパネル View 構築を再利用。無ければ `GraphPanelVM` に2信号を積んで `GraphPanelView(vm)` を `qtbot.addWidget` する最小ヘルパを既存作法で作る。）

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k context_menu_routes_axis -v`
Expected: FAIL（軸分岐が無く panel へ落ちる → `calls == [("panel", None)]` になり assert 失敗）

- [ ] **Step 3: `contextMenuEvent` に軸分岐を挿入**

`graph_panel_view.py`(:2116) を差し替え:

```python
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        # ルーティング優先順 (spec §4.3): 曲線 → Y軸 → 空白 (パネル)。
        # カーソル線分岐は 増分3 で先頭に差し込む。
        pos = QPointF(event.pos())
        eid = self._curve_at(pos)
        if eid is not None:
            self.build_curve_menu(eid).exec(event.globalPos())
            return
        if self._zone_at(pos) in (ZONE_Y_INNER, ZONE_Y_OUTER):
            self.build_axis_menu(self._axis_index_at(pos)).exec(event.globalPos())
            return
        self.build_context_menu().exec(event.globalPos())
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "context_menu_routes_axis or context_menu_curve_wins or context_menu_falls_back" -v`
Expected: PASS（3件。ただし `build_axis_menu` 未実装なので curve/panel は PASS・axis はスパイ差し替えで PASS）

- [ ] **Step 5: DI kwarg 3本と `import math` を追加**

先頭 import 群に（既存 import の並びに合わせて）:

```python
import math
```

コンストラクタ(:656-666) を差し替え（既存2本の直後に3本追加）:

```python
    def __init__(
        self,
        vm: GraphPanelVM,
        parent: QWidget | None = None,
        apply_dialog_fn: Callable[[str, float], str | None] | None = None,
        color_dialog_fn: Callable[[], str | None] | None = None,
        range_dialog_fn: Callable[
            [int, tuple[float, float] | None], tuple[float, float] | None
        ]
        | None = None,
        offset_input_dialog_fn: Callable[[str, float], tuple[float, str] | None]
        | None = None,
        reset_dialog_fn: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.vm = vm
        self._apply_dialog_fn = apply_dialog_fn
        self._color_dialog_fn = color_dialog_fn or self._default_color_dialog
        self._range_dialog_fn = range_dialog_fn
        self._offset_input_dialog_fn = offset_input_dialog_fn
        self._reset_dialog_fn = reset_dialog_fn
```

（以降の `self._items = ...` 以下は既存のまま。）

- [ ] **Step 6: 失敗するテストを書く（build_axis_menu 構築）**

```python
def test_build_axis_menu_items_and_entry_list(qtbot):
    session = _session_with_signals(
        {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.add_signal_to_axis("csv::b", 0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    menu = view.build_axis_menu(0)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "この軸をオートフィット" in texts
    assert "範囲を指定…" in texts
    assert "軸を削除" in texts
    # 曲線一覧（signal_key ラベル・checkable・checked=visible）
    entry_acts = [a for a in menu.actions() if a.text() in ("csv::a", "csv::b")]
    assert len(entry_acts) == 2
    assert all(a.isCheckable() and a.isChecked() for a in entry_acts)


def test_build_axis_menu_autofit_triggers_reset_axis_y(qtbot):
    session = _session_with_signals({"csv::a": ([0.0, 1.0], [10.0, 30.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.set_axis_range(0, 100.0, 200.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    menu = view.build_axis_menu(0)
    act = next(a for a in menu.actions() if a.text() == "この軸をオートフィット")
    act.trigger()
    assert vm.axes[0].y_range == (10.0, 30.0)


def test_build_axis_menu_delete_triggers_remove_axis(qtbot):
    session = _session_with_signals(
        {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.create_new_axis("csv::b")   # axis 1
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    menu = view.build_axis_menu(1)
    act = next(a for a in menu.actions() if a.text() == "軸を削除")
    act.trigger()
    assert {e.signal_key for e in vm._plotted} == {"csv::a"}


def test_build_axis_menu_entry_toggle_hides_curve(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    menu = view.build_axis_menu(0)
    act = next(a for a in menu.actions() if a.text() == "csv::a")
    act.trigger()   # checkable → toggled → toggle_entry_visibility
    assert vm.entries_on_axis(0)[0][3] is False


def test_build_axis_menu_range_uses_injected_dialog(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    view = GraphPanelView(vm, range_dialog_fn=lambda idx, cur: (2.0, 8.0))
    qtbot.addWidget(view)
    menu = view.build_axis_menu(0)
    act = next(a for a in menu.actions() if a.text() == "範囲を指定…")
    act.trigger()
    assert vm.axes[0].y_range == (2.0, 8.0)
```

- [ ] **Step 7: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k build_axis_menu -v`
Expected: FAIL（`build_axis_menu` 未定義）

- [ ] **Step 8: `build_axis_menu`・`_prompt_axis_range`・`_default_range_dialog` を実装**

`build_context_menu`(:2079) の直後に追加。checkable の `setChecked` は `toggled.connect` の**前**（初期セットでハンドラを発火させない — `build_context_menu` の既存作法）。

```python
    def build_axis_menu(self, axis_index: int) -> QMenu:
        """Right-click menu for one Y-axis (spec §4.3: オートフィット/範囲指定/削除/曲線一覧)."""
        menu = QMenu(self)
        menu.addAction("この軸をオートフィット").triggered.connect(
            lambda *_: self.vm.reset_axis_y(axis_index)
        )
        menu.addAction("範囲を指定…").triggered.connect(
            lambda *_: self._prompt_axis_range(axis_index)
        )
        menu.addAction("軸を削除").triggered.connect(
            lambda *_: self.vm.remove_axis(axis_index)
        )
        menu.addSeparator()
        for entry_id, name, _color, visible in self.vm.entries_on_axis(axis_index):
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(visible)  # BEFORE toggled.connect (no spurious fire)
            act.toggled.connect(
                lambda _checked, eid=entry_id: self.vm.toggle_entry_visibility(eid)
            )
        return menu

    def _prompt_axis_range(self, axis_index: int) -> None:
        """Open the range dialog for *axis_index* and apply the chosen [lo, hi]."""
        axes = self.vm.axes
        if not (0 <= axis_index < len(axes)):
            return
        fn = self._range_dialog_fn or self._default_range_dialog
        result = fn(axis_index, axes[axis_index].y_range)
        if result is not None:
            lo, hi = result
            self.vm.set_axis_range(axis_index, lo, hi)

    def _default_range_dialog(
        self, axis_index: int, current: tuple[float, float] | None
    ) -> tuple[float, float] | None:
        """Modal Y-range dialog (DI default). Returns (lo, hi) or None on cancel.

        OK is disabled while the inputs are non-finite or lo >= hi (§10). This
        validation is exercised via realgui/manual — Layer B injects a stub fn.
        """
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QLineEdit,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("Y軸の範囲を指定")
        form = QFormLayout(dlg)
        lo_edit = QLineEdit("" if current is None else f"{current[0]:g}")
        hi_edit = QLineEdit("" if current is None else f"{current[1]:g}")
        form.addRow("下限", lo_edit)
        form.addRow("上限", hi_edit)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)

        def _validate() -> None:
            try:
                lo = float(lo_edit.text())
                hi = float(hi_edit.text())
            except ValueError:
                ok_btn.setEnabled(False)
                return
            ok_btn.setEnabled(math.isfinite(lo) and math.isfinite(hi) and lo < hi)

        lo_edit.textChanged.connect(lambda *_: _validate())
        hi_edit.textChanged.connect(lambda *_: _validate())
        _validate()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return (float(lo_edit.text()), float(hi_edit.text()))
```

- [ ] **Step 9: 通過を確認 ＋ フルスイート＋ゲート**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "build_axis_menu or context_menu" -v`
Expected: PASS

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 10: コミット**

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_view.py
git commit -m "feat(gui): Y軸右クリックメニュー＋ルーティング軸分岐＋範囲ダイアログ（build_axis_menu）"
```

---

### Task 4: 曲線メニュー拡張（新しい軸へ移動・時間オフセット…・リセット…・情報行）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`build_curve_menu`:2053 を差し替え／`_prompt_offset_input`・`_default_offset_input_dialog`・`_prompt_offset_reset`・`_default_reset_dialog` を追加）
- Test: `tests/gui/test_graph_panel_view.py`

**Interfaces:**
- Consumes（Task 1/2）: `vm.move_entry_to_new_axis(entry_id)`・`vm.signal_key_for_entry(entry_id) -> str | None`（既存 :950）・`vm.offset_for(signal_key) -> float`・`self.offset_apply_requested`（既存 Signal :642）・`self.offset_reset_requested`（Task 2）・DI シーム `self._offset_input_dialog_fn`/`self._reset_dialog_fn`（Task 3 で宣言済み）
- Consumes（既存）: `vm.toggle_entry_visibility`・`vm.set_color`・`_color_icon`・`_pick_custom_color`・`_remove_curve`・`_PALETTE`
- Produces:
  - 拡張された `build_curve_menu(self, entry_id: int) -> QMenu`
  - `_prompt_offset_input(self, entry_id: int) -> None`
  - `_default_offset_input_dialog(self, signal_key: str, current: float) -> tuple[float, str] | None`
  - `_prompt_offset_reset(self, entry_id: int) -> None`
  - `_default_reset_dialog(self, signal_key: str) -> str | None`

**GUI テスト分析（gui-test-plan）:**
- 変更種別: ウィジェット構成（メニュー項目）＋入力→emit → **Layer B 主戦場**。
- 実質性: 項目の有無・順序・`isEnabled`（リセットは `offset_for != 0` のみ）・情報行の有無/文言（非ゼロ時のみ）・DI ダイアログ→ `offset_apply_requested`/`offset_reset_requested` emit を自動アサート。
- **色変更▸サブメニューへアクセスするテストは QAction を先にローカル束縛してから `.menu()` を取る**（memory [[gui_pyside_qaction_submenu_shiboken_lifetime]] — ジェネレータ式チェインは shiboken「already deleted」で落ちる）。本タスクでは色サブメニューを触らなくても検証可能なので、触る場合のみ従う。
- honest layering note: ダイアログ本体（Δt 非有限の OK 無効化）は DI シームのため Layer B は stub 経路のみ。実入力検証は realgui/手動。

- [ ] **Step 1: 失敗するテストを書く（曲線メニュー拡張）**

`tests/gui/test_graph_panel_view.py` に追記。

```python
def _curve_menu_texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_build_curve_menu_has_axis_move_and_offset_items(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    eid = vm._plotted[0].entry_id
    texts = _curve_menu_texts(view.build_curve_menu(eid))
    for expected in ("非表示", "色変更", "削除", "新しい軸へ移動",
                     "時間オフセット…", "オフセットをリセット…"):
        assert expected in texts


def test_curve_menu_move_to_new_axis_triggers_vm(qtbot):
    session = _session_with_signals(
        {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.add_signal_to_axis("csv::b", 0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    eid_b = next(e.entry_id for e in vm._plotted if e.signal_key == "csv::b")
    act = next(a for a in view.build_curve_menu(eid_b).actions()
               if a.text() == "新しい軸へ移動")
    act.trigger()
    assert len(vm.axes) == 2


def test_curve_menu_reset_disabled_when_no_offset(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    eid = vm._plotted[0].entry_id
    menu = view.build_curve_menu(eid)
    reset_act = next(a for a in menu.actions() if a.text() == "オフセットをリセット…")
    assert reset_act.isEnabled() is False
    # 情報行は非ゼロ時のみ → 存在しない
    assert not any(a.text().startswith("オフセット: ") for a in menu.actions())


def test_curve_menu_reset_enabled_and_info_row_when_offset_applied(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.set_offsets({"csv::a": 0.5}, {})
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    eid = vm._plotted[0].entry_id
    menu = view.build_curve_menu(eid)
    reset_act = next(a for a in menu.actions() if a.text() == "オフセットをリセット…")
    assert reset_act.isEnabled() is True
    info = next(a for a in menu.actions() if a.text().startswith("オフセット: "))
    assert info.isEnabled() is False
    assert "+0.5" in info.text()


def test_curve_menu_offset_input_emits_apply(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    view = GraphPanelView(vm, offset_input_dialog_fn=lambda sk, cur: (0.3, "signal"))
    qtbot.addWidget(view)
    eid = vm._plotted[0].entry_id
    emitted = []
    view.offset_apply_requested.connect(lambda k, dt, sc: emitted.append((k, dt, sc)))
    act = next(a for a in view.build_curve_menu(eid).actions()
               if a.text() == "時間オフセット…")
    act.trigger()
    assert emitted == [("csv::a", 0.3, "signal")]


def test_curve_menu_reset_emits_reset(qtbot):
    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.set_offsets({"csv::a": 0.5}, {})
    view = GraphPanelView(vm, reset_dialog_fn=lambda sk: "signal")
    qtbot.addWidget(view)
    eid = vm._plotted[0].entry_id
    emitted = []
    view.offset_reset_requested.connect(lambda k, sc: emitted.append((k, sc)))
    act = next(a for a in view.build_curve_menu(eid).actions()
               if a.text() == "オフセットをリセット…")
    act.trigger()
    assert emitted == [("csv::a", "signal")]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "curve_menu" -v`
Expected: FAIL（新項目・emit 経路が無い）

- [ ] **Step 3: `build_curve_menu` を差し替え、ダイアログ4メソッドを追加**

`build_curve_menu`(:2053) を spec §4.3 の順序（非表示／色変更▸／削除／新しい軸へ移動／──／時間オフセット…／オフセットをリセット…／情報行）へ差し替え。**2a の「色変更の後の separator＋削除」から、separator を offset ブロックの前へ移す**点に注意。

```python
    def build_curve_menu(self, entry_id: int) -> QMenu:
        """Right-click menu for one curve (spec §4.3).

        非表示／色変更▸／削除／新しい軸へ移動／──／時間オフセット…／
        オフセットをリセット…／オフセット情報行（非ゼロ時のみ・disabled）。
        """
        menu = QMenu(self)
        menu.addAction("非表示").triggered.connect(
            lambda *_: self.vm.toggle_entry_visibility(entry_id)
        )
        color_menu = menu.addMenu("色変更")
        for hex_color in _PALETTE:
            act = color_menu.addAction(hex_color)
            act.setIcon(self._color_icon(hex_color))
            act.triggered.connect(
                lambda *_, c=hex_color: self.vm.set_color(entry_id, c)
            )
        color_menu.addSeparator()
        color_menu.addAction("その他…").triggered.connect(
            lambda *_: self._pick_custom_color(entry_id)
        )
        menu.addAction("削除").triggered.connect(
            lambda *_: self._remove_curve(entry_id)
        )
        menu.addAction("新しい軸へ移動").triggered.connect(
            lambda *_: self.vm.move_entry_to_new_axis(entry_id)
        )
        menu.addSeparator()
        menu.addAction("時間オフセット…").triggered.connect(
            lambda *_: self._prompt_offset_input(entry_id)
        )
        signal_key = self.vm.signal_key_for_entry(entry_id)
        current_offset = (
            self.vm.offset_for(signal_key) if signal_key is not None else 0.0
        )
        reset_act = menu.addAction("オフセットをリセット…")
        reset_act.setEnabled(current_offset != 0.0)
        reset_act.triggered.connect(lambda *_: self._prompt_offset_reset(entry_id))
        if current_offset != 0.0:
            info = menu.addAction(f"オフセット: {current_offset:+.3g}s")
            info.setEnabled(False)
        return menu

    def _prompt_offset_input(self, entry_id: int) -> None:
        """Open the numeric offset dialog and emit offset_apply_requested (additive)."""
        signal_key = self.vm.signal_key_for_entry(entry_id)
        if signal_key is None:
            return
        fn = self._offset_input_dialog_fn or self._default_offset_input_dialog
        result = fn(signal_key, self.vm.offset_for(signal_key))
        if result is not None:
            delta_t, scope = result
            self.offset_apply_requested.emit(signal_key, delta_t, scope)

    def _default_offset_input_dialog(
        self, signal_key: str, current: float
    ) -> tuple[float, str] | None:
        """Modal numeric offset dialog (DI default). Returns (delta_t, scope) or None.

        Extends the scope-selection dialog (_default_apply_dialog) with a Δt input.
        OK is disabled while Δt is non-finite (§10). Enter applies the 'signal' scope.
        """
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QLineEdit,
            QRadioButton,
            QVBoxLayout,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("時間オフセット")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"現在のオフセット: {current:+.3g} s"))
        lay.addWidget(QLabel("追加する Δt (秒):"))
        dt_edit = QLineEdit("0")
        lay.addWidget(dt_edit)
        sig_radio = QRadioButton("この信号のみ")
        grp_radio = QRadioButton("同じファイルグループ全体")
        sig_radio.setChecked(True)
        lay.addWidget(sig_radio)
        lay.addWidget(grp_radio)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)

        def _validate() -> None:
            try:
                val = float(dt_edit.text())
            except ValueError:
                ok_btn.setEnabled(False)
                return
            ok_btn.setEnabled(math.isfinite(val))

        dt_edit.textChanged.connect(lambda *_: _validate())
        ok_btn.setDefault(True)
        _validate()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return (float(dt_edit.text()), "signal" if sig_radio.isChecked() else "group")

    def _prompt_offset_reset(self, entry_id: int) -> None:
        """Open the reset-scope dialog and emit offset_reset_requested."""
        signal_key = self.vm.signal_key_for_entry(entry_id)
        if signal_key is None:
            return
        fn = self._reset_dialog_fn or self._default_reset_dialog
        scope = fn(signal_key)
        if scope in ("signal", "group"):
            self.offset_reset_requested.emit(signal_key, scope)

    def _default_reset_dialog(self, signal_key: str) -> str | None:
        """Modal reset-scope dialog: 'signal' / 'group' / None (cancel).

        Same shape as _default_apply_dialog minus the Δt (reset zeroes the offset).
        """
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QRadioButton,
            QVBoxLayout,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("時間オフセットのリセット")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("オフセットを 0 に戻します。対象を選択してください。"))
        sig_radio = QRadioButton("この信号のみ")
        grp_radio = QRadioButton("同じファイルグループ全体")
        sig_radio.setChecked(True)
        lay.addWidget(sig_radio)
        lay.addWidget(grp_radio)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setDefault(True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return "signal" if sig_radio.isChecked() else "group"
```

- [ ] **Step 4: 通過を確認 ＋ フルスイート＋ゲート**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "curve_menu" -v`
Expected: PASS（6件）

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_view.py
git commit -m "feat(gui): 曲線メニュー拡張（新しい軸へ移動・時間オフセット…・リセット…・情報行）"
```

---

### Task 5: T4-c follow-up — 軸クリック解除の Layer B テスト

**Files:**
- Test: `tests/gui/test_graph_panel_view.py`（実装コードは変更しない — 2a の `_AlignedAxisItem.mouseClickEvent`:451 の wiring をカバーする穴埋め）

**Interfaces:**
- Consumes（2a 既存）: `_AlignedAxisItem.mouseClickEvent(ev)`（:451・左クリックで `set_active_axis` ＋ `_deactivate_curve`）・`view._y_axes[i]`（`_AlignedAxisItem`・`_vm_axis_index`/`_panel_view` 設定済み）・`view._activate_curve(entry_id)`（:1176）・`view._active_curve_id`・`view._active_axis_index`
- Produces: なし（テストのみ）

**背景（2a 繰越 Minor T4-c）:** 既存 `test_axis_click_deactivates_curve` は `_deactivate_curve` を直呼びしており、`_AlignedAxisItem.mouseClickEvent`(:465) の「軸クリック→曲線解除」wiring 自体は未カバー（その行を削除しても緑になる）。本タスクで `mouseClickEvent` を duck-type イベントで駆動し、wiring を assert する。

**GUI テスト分析（gui-test-plan）:**
- 変更種別: 入力イベント→ハンドラ（pyqtgraph scene の `mouseClickEvent`）→ **Layer B**（`QGraphicsSceneMouseEvent` の合成は重いので、`.button()/.accept()/.ignore()` を持つ duck-type で `mouseClickEvent` を直接駆動する。これは合成イベント配送ではなく「ハンドラの実引数駆動」だが、対象は View transient 状態の遷移でありモーダル/実 OS を要さないため Layer B で十分・honest layering note に明記）。
- サボタージュ: `mouseClickEvent` の `self._panel_view._deactivate_curve()` 行(:467) を消すと本テストが RED になること（＝wiring をカバーしている証拠）を実装者は手元で1回確認する。

- [ ] **Step 1: 失敗するテストを書く**

```python
class _FakeAxisClickEvent:
    """Duck-typed pyqtgraph mouseClickEvent (left button)."""

    def __init__(self, button):
        self._button = button
        self.accepted = False
        self.ignored = False

    def button(self):
        return self._button

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


def test_axis_click_event_deactivates_active_curve(qtbot):
    from PySide6.QtCore import Qt

    session = _session_with_signals(
        {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
    )
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    vm.create_new_axis("csv::b")   # axis 1
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    # 曲線 a（軸0）を活性化 → 次に軸1を実ハンドラで click
    eid_a = next(e.entry_id for e in vm._plotted if e.signal_key == "csv::a")
    view._activate_curve(eid_a)
    assert view._active_curve_id == eid_a
    axis1 = view._y_axes[1]
    assert axis1._vm_axis_index == 1          # reconcile で設定済み
    axis1.mouseClickEvent(_FakeAxisClickEvent(Qt.MouseButton.LeftButton))
    assert view._active_curve_id is None      # 軸クリックで曲線解除（wiring カバー）
    assert view._active_axis_index == 1       # 軸1が活性


def test_axis_click_right_button_is_ignored(qtbot):
    from PySide6.QtCore import Qt

    session = _session_with_signals({"csv::a": ([0.0], [1.0])})
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis("csv::a", 0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    eid = vm._plotted[0].entry_id
    view._activate_curve(eid)
    ev = _FakeAxisClickEvent(Qt.MouseButton.RightButton)
    view._y_axes[0].mouseClickEvent(ev)
    assert ev.ignored is True
    assert view._active_curve_id == eid       # 右クリックでは解除しない
```

- [ ] **Step 2: 失敗しないことを確認（wiring は既に実在）→ サボタージュで RED を実証**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k axis_click_event -v`
Expected: PASS（wiring は 2a で実在するため最初から緑）

wiring カバーの実証（手元で1回のみ）: `graph_panel_view.py`(:467) の `self._panel_view._deactivate_curve()` を一時コメントアウト → 上記 `test_axis_click_event_deactivates_active_curve` が FAIL することを確認 → 元に戻す。

- [ ] **Step 3: フルスイート＋ゲート**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 4: コミット**

```bash
git add tests/gui/test_graph_panel_view.py
git commit -m "test(gui): 軸クリック解除の Layer B カバー（T4-c follow-up・mouseClickEvent 駆動）"
```

---

### Task 6: realgui 証拠（Layer C・実 OS 入力＋スクショ AI 判定）

**Files:**
- Create: `tests/realgui/test_axis_menu_offset.py`
- Test: 既存 `tests/realgui/test_curve_direct_ops.py`・`tests/realgui/test_offset_drag.py` を①ゲートで再実行（無回帰）

**Interfaces:**
- Consumes: `tests/realgui/` 共有ヘルパ `_realgui_input`（実 OS 入力）・`drive_qdrag`・`_menu_hang_watchdog`（2a で確立した menu.exec ハング用 Escape watchdog）・`tests/realgui/conftest.py` の QSettings 隔離。DI ダイアログ注入（`GraphPanelView(vm, offset_input_dialog_fn=..., range_dialog_fn=..., reset_dialog_fn=...)`）で「realgui でネイティブモーダルを駆動しない」既存作法を踏襲。
- Produces: 実 OS 入力の証拠（pass/fail・スクショ）

**GUI テスト分析（gui-test-plan）:**
- spec §11 Layer C 増分2: 「曲線・軸の実右クリックメニュー実行」＋「既存 `test_offset_drag.py` の見直し（DP16 は 2a で確定・本増分は無回帰）」。
- 実質性: 右クリック→メニュー表示→項目クリックの経路と、その結果の視覚変化（軸削除で軸が消える・新しい軸へ移動で軸が増える・オフセット適用で曲線が水平シフト）は**スクショ AI 判定**でしか誠実に確認できない。メニュー**navigation** は実 OS 入力、**終端ダイアログ**は DI スタブ（spec §4.3）。
- **掴み点/クリック点はゾーン幾何から導出**（マジック比率禁止）。軸右クリックは軸ガター（`_Y_AXIS_FIXED_WIDTH=72` 内・plot 矩形外）で。右クリックがメニューを開かず外れた場合に備え `_menu_hang_watchdog` で Escape 送出（menu.exec 無限ハング防止・2a Task 8 の教訓）。
- ①証拠ゲート（下記チェックボックス）を本タスクで満たす。

- [ ] **Step 1: 軸メニューの realgui（軸を削除）を書く**

`tests/realgui/test_axis_menu_offset.py` を作成。既存 `test_curve_direct_ops.py` のスキャフォールド（`_realgui_input`・ウィンドウ前面化・`availableGeometry` 内配置・`_menu_hang_watchdog`）をそのまま踏襲する。

```python
"""Layer C (realgui) — 軸/曲線右クリックメニューとオフセット導線の実 OS 入力検証。"""

import pytest

pytestmark = pytest.mark.realgui


@pytest.mark.realgui
def test_real_right_click_axis_delete_removes_axis(realgui_app, screenshot_ai):
    """軸ガターを実右クリック → メニュー「軸を削除」を実クリック → 軸が1本消える。"""
    view = realgui_app.panel_with_two_axes()   # 既存ハーネスの2軸パネル構築に合わせる
    with _menu_hang_watchdog():                # メニュー未表示時に Escape 送出
        # 軸1のガター（plot 矩形外・列ジオメトリから算出）で右クリック
        target = _axis_gutter_point(view, axis_index=1)
        _realgui_input.right_click_at(target)
        _realgui_input.click_menu_item("軸を削除")
    before = screenshot_ai.count_axes()        # AI 判定 or vm.axes 併用
    assert len(view.vm.axes) == 1
    screenshot_ai.save("axis_menu_01_after_delete.png")
```

（`realgui_app`・`screenshot_ai`・`_axis_gutter_point`・`_realgui_input.right_click_at`/`click_menu_item` は `tests/realgui/` の既存ヘルパ命名に合わせる。無い操作は `reference/realgui-recipe.md` に従って追加し、Layer C 契約ガードを満たす実 OS 入力で実装する。）

- [ ] **Step 2: 曲線メニューのオフセット realgui を書く（時間オフセット… → 曲線シフト）**

```python
@pytest.mark.realgui
def test_real_curve_menu_offset_shifts_curve(realgui_app, screenshot_ai):
    """曲線を実右クリック → 「時間オフセット…」を実クリック → DI ダイアログが
    (0.5, 'signal') を返す → 曲線が水平シフトする（スクショ AI 判定）。"""
    view = realgui_app.panel_with_one_curve(
        offset_input_dialog_fn=lambda sk, cur: (0.5, "signal"),
    )
    screenshot_ai.save("curve_offset_00_before.png")
    with _menu_hang_watchdog():
        _realgui_input.right_click_at(_curve_point(view))
        _realgui_input.click_menu_item("時間オフセット…")
    screenshot_ai.save("curve_offset_01_after.png")
    assert screenshot_ai.judge(
        "curve_offset_00_before.png", "curve_offset_01_after.png",
        "2枚目は曲線が右へ水平シフトしている",
    )
```

- [ ] **Step 3: 新しい軸へ移動 realgui を書く（軸が増える）**

```python
@pytest.mark.realgui
def test_real_curve_menu_move_to_new_axis(realgui_app, screenshot_ai):
    view = realgui_app.panel_with_two_curves_one_axis()
    with _menu_hang_watchdog():
        _realgui_input.right_click_at(_curve_point(view, which="b"))
        _realgui_input.click_menu_item("新しい軸へ移動")
    assert len(view.vm.axes) == 2
    screenshot_ai.save("curve_move_01_two_axes.png")
```

- [ ] **Step 4: 新規 realgui を①ゲートで実行**

Run: `uv run pytest --realgui tests/realgui/test_axis_menu_offset.py -v`
Expected: PASS（3件）。スクショが `QT_QPA_PLATFORM=windows` で保存され、文字化けなし（memory [[gui_offscreen_grab_text_tofu]]）。

- [ ] **Step 5: 既存 realgui の無回帰を①ゲートで実行**

DP16・曲線活性化・既存オフセットドラッグに本増分の変更（曲線メニュー拡張・ルーティング軸分岐）が回帰を与えないことを実 OS 入力で確認。

Run: `uv run pytest --realgui tests/realgui/test_curve_direct_ops.py tests/realgui/test_offset_drag.py -v`
Expected: PASS（既存本数どおり）

- [ ] **Step 6: Layer C 契約ガード ＋ headless full**

Run: `uv run pytest tests/gui/test_realgui_layer_c_contract.py -v`
Expected: PASS（新規 realgui が合成でなく実 OS 入力であることを CI ガードが確認）

Run: `uv run pytest`
Expected: headless full 0 errors（realgui は自動スキップ）

- [ ] **Step 7: ①証拠ゲート判定（merge 前・`/gui-verify`）**
  - (a) headless full `uv run pytest` 0 errors
  - (b) realgui 証拠: `test_axis_menu_offset.py` 3本＋既存 `test_curve_direct_ops.py`/`test_offset_drag.py` 再実行 pass・スクショ添付・Layer C 契約ガード pass
  - (c) CI 緑（push 後 PR で確認）

- [ ] **Step 8: コミット**

```bash
git add tests/realgui/test_axis_menu_offset.py
git commit -m "test(realgui): 軸/曲線メニューとオフセット導線の実 OS 入力検証（Layer C ①ゲート）"
```

---

## Self-Review

**1. Spec coverage（§7 増分2 のうち 2b 帰属分）:**

| spec 要件 | 担当タスク |
|---|---|
| `reset_axis_y(axis_index)` | Task 1 |
| `remove_axis(axis_index)` | Task 1 |
| `entries_on_axis(axis_index)` | Task 1 |
| `move_entry_to_new_axis(entry_id)` | Task 1 |
| `offset_for(signal_key)` | Task 2 |
| `AppViewModel.reset_offset(...)`（対称・`'offsets'` 通知） | Task 2 |
| `GraphAreaVM.reset_offset` 転送 | Task 2 |
| `offset_reset_requested` Signal ＋ `_wire_panel` 配線 | Task 2 |
| `build_axis_menu`（オートフィット/範囲指定/削除/曲線一覧チェック式） | Task 3 |
| 右クリックルーティングに軸分岐挿入（曲線→軸→空白） | Task 3 |
| 軸範囲ダイアログ（DI・lo≥hi/非有限 OK 無効化 §10） | Task 3 |
| 曲線メニュー「新しい軸へ移動」 | Task 4 |
| 「時間オフセット…」＋数値ダイアログ（`_default_apply_dialog` 拡張・DI） | Task 4 |
| 「オフセットをリセット…」（適用中のみ enabled・スコープ選択ダイアログ→ `reset_offset`） | Task 4 |
| 「オフセット: +0.250s」情報行（非ゼロ時のみ・disabled） | Task 4 |
| T4-c 軸クリック解除 Layer B カバー | Task 5 |
| Layer C 実 OS 入力（軸/曲線メニュー・無回帰） | Task 6 |

増分2a で実装済み（本プラン対象外）: entry_id 基盤・曲線活性化+DP16・H キー・曲線右クリックメニュー基本（非表示/色変更/削除）・死蔵削除（PC-05）。カーソル線分岐・←/→・readout は増分3。

**2. Placeholder scan:** 各コード step に実コードあり。realgui（Task 6）のヘルパ名は既存 `tests/realgui/` 命名に合わせる旨を明示（ハーネス依存のため命名は実装時に既存へ整合）— これは placeholder ではなく既存資産への委譲。

**3. Type consistency:**
- `entries_on_axis` 返り値 `list[tuple[int, str, str, bool]]` を Task 1 で定義、Task 3 `build_axis_menu` で `for entry_id, name, _color, visible in ...` と一致。
- `offset_for(signal_key: str) -> float`（Task 2 定義）を Task 4 で `current_offset != 0.0` 判定・情報行に使用、型一致。
- `offset_reset_requested = Signal(str, str)`（Task 2）を Task 4 `_prompt_offset_reset` が `emit(signal_key, scope)` で一致。
- DI シーム3本を Task 3 コンストラクタで宣言、Task 3 が `range_dialog_fn`、Task 4 が `offset_input_dialog_fn`/`reset_dialog_fn` を消費 — 宣言と消費の名前一致。
- `move_entry_to_new_axis` の cache invalidate は Task 1 実装＋テストで担保（cache-key に axis_index 非包含の落とし穴を Global Constraints にも明記）。

**4. 依存順:** Task 1（VM 軸 API）→ Task 2（offset backend＋Signal）→ Task 3（軸メニュー＋DI シーム宣言＋ルーティング）→ Task 4（曲線メニュー拡張・Task 1/2/3 の産物を全消費）→ Task 5（T4-c・独立）→ Task 6（realgui・全実装後）。各タスクは独立にテスト可能な成果物で終わる。
