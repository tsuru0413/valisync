# plotctl 増分3a（カーソル操作＋補間可視化）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** カーソルを「設置後に矢印キーでサンプルスナップ移動／線右クリックで時刻指定・消去」できるようにし、補間方式を排他チェック式メニュー＋readout ヘッダで可視化する（PC-08/PC-09）。

**Architecture:** MVVM 厳守。VM に `step_cursor`（隣接サンプル時刻へのスナップ・純ロジック）を新設し、View は「どのカーソル（A/B）がアクティブか」の transient 状態と基準曲線 entry_id の解決だけを担う。カーソル線の右クリックは既存の pos ベースルーティング（増分2b の 曲線→Y軸→空白）の**先頭にカーソル線分岐**を挿す。補間方式は既存の非排他サブメニューを `QActionGroup(exclusive)` の radio へ改造し、現在方式を readout ヘッダ右端へ常時表示する。全ダイアログは既存 DI シーム作法で注入。

**Tech Stack:** Python 3.13 / PySide6 (Qt6) / pyqtgraph / MVVM。テストは pytest + pytest-qt（Layer A/B）＋ `--realgui` 実 OS 入力（Layer C）。品質ゲート: `uv run pytest` / `ruff check` + `ruff format --check` / `mypy src/`。

## Global Constraints

以下は全タスクに暗黙適用（spec より逐語）:

- **MVVM 境界**: View は VM 経由のみ操作。VM は `_notify(<topic>)` で通知。カーソル系の notify topic は既存踏襲 — A 変更＝`"cursor"`／B・delta 変更＝`"delta"`。
- **アクティブカーソルは View transient**: A/B のどちらが操作対象かは View が持つ（`_active_axis_index`/`_active_curve_id` と同格）。VM は `step_cursor` の引数で `which`（"A"/"B"）と基準 `reference_entry_id` を受ける（§4.1・§4.4）。
- **基準 entry の解決**: 矢印キーは View がアクティブ曲線の entry_id を渡し、None または非表示なら VM が**先頭可視 entry** にフォールバック。可視ゼロは no-op（§4.4・§10）。
- **サンプルスナップは表示時刻基準**: `step_cursor` は基準信号の**オフセット適用後**の隣接サンプル時刻へスナップする（`_signal_map()` 経由で offset 適用済み Signal を得て `sorted_view()[0]` を使う）。端で clamp（§4.4・§10）。
- **右クリックルーティング優先順（spec §4.3）**: **カーソル線 → 曲線 → Y軸 → 空白（パネル）**。本増分でカーソル線分岐を先頭に挿す（増分2b が 曲線→Y軸→空白 を確立済み）。
- **checkable の `setChecked` は `triggered`/`toggled` connect の前**（初期セットでハンドラ発火させない — 既存 `build_context_menu`/`build_axis_menu` の作法）。補間方式は **`QActionGroup` で排他 radio**（現在値 `vm.interp_method` を checked）。
- **ダイアログは DI 注入**（既存 `apply_dialog_fn`/`color_dialog_fn`/`range_dialog_fn`/`offset_input_dialog_fn`/`reset_dialog_fn` パターン。None 既定→call 時に `_default_*` 解決）。カーソル時刻ダイアログの非有限 OK 無効化は default 側実装＝Layer B は DI stub。
- **カーソル消去スコープ（§4.3・§10）**: A 線メニュー＝全消去（B は VM 不変条件で道連れ）／B 線メニュー＝Δ のみ無効化。
- **品質ゲート**: 各コミット前に `uv run pytest` 全 PASS・`ruff check`・`ruff format --check`・`mypy src/` 0 errors。ゲートを `| tail` 等に通さない（exit code 隠蔽防止）。
- **realgui は実 OS 入力のみ**: 新規 realgui は `_realgui_input` の実 OS 入力＋スクショ。合成 `qtbot.keyClick`/`trigger` は Layer C を名乗れない（契約ガード `tests/gui/test_realgui_layer_c_contract.py` が CI で検出）。

---

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `src/valisync/gui/viewmodels/graph_panel_vm.py` | `step_cursor`＋`_reference_timestamps` を追加 | Modify |
| `src/valisync/gui/views/graph_panel_view.py` | アクティブカーソル状態・矢印キー配送・カーソル線メニュー＋ルーティング・`_cursor_line_at`・時刻ダイアログ・補間排他メニュー・補間ラベル受け渡し | Modify（主戦場） |
| `src/valisync/gui/views/cursor_readout.py` | `set_global`/`set_delta` に補間ラベル引数を追加 | Modify |
| `tests/gui/test_graph_panel_vm.py` | `step_cursor` の Layer A | Modify |
| `tests/gui/test_graph_panel_cursor.py` | アクティブカーソル・矢印キー・カーソルメニュー・補間排他の Layer B | Modify |
| `tests/gui/test_cursor_readout.py` | 補間ラベルの Layer B | Modify |
| `tests/realgui/test_global_cursor.py` | 実 ←/→・カーソル線右クリック・補間 radio の Layer C | Modify |

---

### Task 1: VM `step_cursor`（隣接サンプルへのスナップ）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`set_cursor_b`:960 付近の直後にカーソル系メソッドとして追加）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Consumes（既存）: `self.cursor_t`/`self.cursor_t_b`/`self.delta_enabled`（:146-156）・`self._plotted: list[_PlottedEntry]`（`entry_id`/`visible`/`signal_key`）・`signal_key_for_entry(entry_id)`（:1031）・`_signal_map() -> dict[str, Signal]`（:1095・オフセット適用済み）・`set_cursor(t)`（:888・notify "cursor"）・`set_cursor_b(t)`（:960・notify "delta"）・`Signal.sorted_view() -> (ts, vs)`（core・単調ソート済み）・`Signal.timestamps`・`np`
- Produces（後続タスクが依存）:
  - `step_cursor(self, which: str, direction: int, reference_entry_id: int | None = None) -> None`
  - `_reference_timestamps(self, reference_entry_id: int | None) -> np.ndarray | None`（private ヘルパ）

**GUI テスト分析（gui-test-plan）:**
- 変更種別: 純 VM ロジック → **Layer A のみ**。realgui 不要。
- 実質性: スナップ先時刻・端 clamp・基準 entry フォールバック・no-op 条件は `vm.cursor_t`/`cursor_t_b` の観測で完全に自動アサート可。
- honest layering note: スナップは「オフセット適用後の表示時刻」基準。テストはオフセット 0 の素直な CSV（`t=i*0.01`）で隣接サンプルを検証し、フォールバック（非表示基準 entry）と端 clamp を弁別ケースで押さえる。

- [ ] **Step 1: 失敗するテストを書く（前方/後方スナップ）**

`tests/gui/test_graph_panel_vm.py` に追記。既存 `_loaded_session`（:68・CSV `t=i*0.01, value=i`）と `_first_signal_key` を再利用。

```python
def test_step_cursor_forward_snaps_to_next_sample(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_cursor(0.005)  # between samples 0.00 and 0.01
    vm.step_cursor("A", 1)
    assert vm.cursor_t == pytest.approx(0.01)


def test_step_cursor_backward_snaps_to_prev_sample(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_cursor(0.005)
    vm.step_cursor("A", -1)
    assert vm.cursor_t == pytest.approx(0.0)


def test_step_cursor_from_exact_sample_moves_one(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_cursor(0.01)  # exactly on a sample
    vm.step_cursor("A", 1)
    assert vm.cursor_t == pytest.approx(0.02)
    vm.step_cursor("A", -1)
    assert vm.cursor_t == pytest.approx(0.01)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k step_cursor_forward -v`
Expected: FAIL（`AttributeError: 'GraphPanelVM' object has no attribute 'step_cursor'`）

- [ ] **Step 3: `_reference_timestamps` と `step_cursor` を実装**

`set_cursor_b`(:960) の直後に追加:

```python
    def _reference_timestamps(self, reference_entry_id: int | None) -> np.ndarray | None:
        """Displayed (offset-applied), sorted timestamps of the reference signal.

        Resolves *reference_entry_id* to its signal_key, honouring it only when
        that entry is currently visible; otherwise (None / absent / hidden) falls
        back to the first visible entry. Returns None when no visible signal is
        available. Uses sorted_view (all recorded samples, offset applied) so the
        snap targets exactly what is drawn.
        """
        key: str | None = None
        if reference_entry_id is not None:
            visible = any(
                e.entry_id == reference_entry_id and e.visible for e in self._plotted
            )
            if visible:
                key = self.signal_key_for_entry(reference_entry_id)
        if key is None:
            for e in self._plotted:
                if e.visible:
                    key = e.signal_key
                    break
        if key is None:
            return None
        sig = self._signal_map().get(key)
        if sig is None or len(sig.timestamps) == 0:
            return None
        return sig.sorted_view()[0]

    def step_cursor(
        self, which: str, direction: int, reference_entry_id: int | None = None
    ) -> None:
        """Move the A or B cursor to the reference signal's adjacent sample time.

        *which* is "A" or "B"; *direction* is +1 (right) or -1 (left). The cursor
        snaps to the neighbouring recorded timestamp of the reference signal on
        the DISPLAYED time axis (offsets applied), so arrow-key stepping lands
        exactly on samples. Clamps at the first/last sample. No-op when the
        relevant cursor is unset or no visible reference signal exists.
        """
        if which == "A":
            current = self.cursor_t
        elif which == "B":
            current = self.cursor_t_b if self.delta_enabled else None
        else:
            return
        if current is None:
            return
        ts = self._reference_timestamps(reference_entry_id)
        if ts is None or len(ts) == 0:
            return
        if direction > 0:
            idx = int(np.searchsorted(ts, current, side="right"))
            target = ts[idx] if idx < len(ts) else ts[-1]
        else:
            idx = int(np.searchsorted(ts, current, side="left")) - 1
            target = ts[idx] if idx >= 0 else ts[0]
        target_f = float(target)
        if which == "A":
            self.set_cursor(target_f)
        else:
            self.set_cursor_b(target_f)
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k step_cursor -v`
Expected: PASS（3件）

- [ ] **Step 5: 失敗するテストを書く（端 clamp・no-op・フォールバック・B・notify）**

```python
def test_step_cursor_clamps_at_ends(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=5, n_signals=1)  # t: 0.00..0.04
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_cursor(0.0)
    vm.step_cursor("A", -1)
    assert vm.cursor_t == pytest.approx(0.0)  # clamp at first
    vm.set_cursor(0.04)
    vm.step_cursor("A", 1)
    assert vm.cursor_t == pytest.approx(0.04)  # clamp at last


def test_step_cursor_noop_without_cursor(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.step_cursor("A", 1)  # A not set
    assert vm.cursor_t is None


def test_step_cursor_b_requires_delta_enabled(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_cursor(0.005)         # A set, delta off
    vm.step_cursor("B", 1)       # B disabled → no-op
    assert vm.cursor_t_b is None
    vm.toggle_delta(True)        # B at 75% of x_range
    before = vm.cursor_t_b
    vm.step_cursor("B", 1)
    assert vm.cursor_t_b is not None and vm.cursor_t_b >= before


def test_step_cursor_falls_back_to_first_visible_when_ref_hidden(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=2)
    vm = GraphPanelVM(session)
    k0, k1 = session.signals()[0].name, session.signals()[1].name
    vm.add_signal(k0)
    vm.add_signal(k1)
    # hide the first entry; ref points to it → fallback to next visible
    eid0 = vm._plotted[0].entry_id
    vm.toggle_entry_visibility(eid0)
    vm.set_cursor(0.005)
    vm.step_cursor("A", 1, reference_entry_id=eid0)
    assert vm.cursor_t == pytest.approx(0.01)  # still snaps (via visible k1, same grid)


def test_step_cursor_notifies_cursor(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_cursor(0.005)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.step_cursor("A", 1)
    assert "cursor" in changes
```

- [ ] **Step 6: 失敗を確認 → （実装済みなら）通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k step_cursor -v`
Expected: PASS（8件・Step 3 実装で全て緑になる。もし `test_step_cursor_falls_back...` が赤なら `_reference_timestamps` の可視判定を確認）

- [ ] **Step 7: フルスイート＋ゲート**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 8: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "feat(gui): GraphPanelVM.step_cursor（隣接サンプルへのスナップ・端 clamp・基準 entry フォールバック）"
```

---

### Task 2: アクティブカーソル状態＋活性化＋太線フィードバック

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`__init__` の transient 状態群:706-731 に `_active_cursor`/`_prev_showing_b` 追加／`_sync_cursor_from_vm`:1324 に活性管理＋ペン適用／`_on_cursor_line_dragged`/`_on_cursor_line_b_dragged`:1361 に活性化／introspection 追加）
- Test: `tests/gui/test_graph_panel_cursor.py`

**Interfaces:**
- Consumes（既存）: `self.vm.cursor_t`/`cursor_t_b`/`delta_enabled`・`self._cursor_line`/`self._cursor_line_b`（pg.InfiniteLine）・`_sync_cursor_from_vm`（:1324）・`_suppress_cursor_signal`・`pg.mkPen`・`Qt.PenStyle.DashLine`
- Produces（後続タスクが依存）:
  - `self._active_cursor: str | None`（"A"/"B"/None・View transient）
  - `active_cursor(self) -> str | None`（introspection）
  - `cursor_line_width(self, which: str) -> float`（introspection）
  - `_apply_cursor_pens(self) -> None`

**GUI テスト分析（gui-test-plan）:**
- 変更種別: ウィジェット状態＋イベント経路 → **Layer B**。
- 実質性: アクティブ遷移（設置で A・B 有効化で B・B 消去で A へ後退・A 消去で None）と太線化（アクティブ線が非アクティブ線より太い）を `active_cursor()`／`cursor_line_width()` で自動アサート。ドラッグ活性化は `_on_cursor_line_b_dragged` を直接呼ぶ Layer B（実ドラッグは Task 6 realgui）。
- honest layering note: pyqtgraph の実ドラッグ配送は Layer B の直呼びでは再現しないが、活性化は「dragged ハンドラが `_active_cursor` を設定する」配線を検証すれば十分（実 OS ドラッグでの活性化は Task 6 で担保）。

- [ ] **Step 1: 失敗するテストを書く（自動アクティブ遷移）**

`tests/gui/test_graph_panel_cursor.py` に追記。既存 `_vm_with_signal`（:28）＋パネル構築作法を再利用（`GraphPanelView(vm)` を `qtbot.addWidget`）。

```python
def test_placing_cursor_auto_activates_a(qtbot):
    view = _shown_cursor_panel(qtbot)   # 既存 helper or 最小構築
    view.vm.x_range = (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    assert view.active_cursor() == "A"


def test_enabling_delta_auto_activates_b(qtbot):
    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    view.vm.toggle_delta(True)
    assert view.active_cursor() == "B"


def test_disabling_delta_falls_back_to_a(qtbot):
    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    view.vm.toggle_delta(True)
    view.vm.toggle_delta(False)
    assert view.active_cursor() == "A"


def test_clearing_cursor_deactivates(qtbot):
    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    view.vm.toggle_main_cursor(False)
    assert view.active_cursor() is None
```

（`_shown_cursor_panel` が既存に無ければ、`_vm_with_signal` で VM を作り `GraphPanelView(vm)` を `qtbot.addWidget`＋`show()`＋`qtbot.waitExposed` する最小 helper を既存作法で用意。）

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k auto_activates_a -v`
Expected: FAIL（`AttributeError: ... 'active_cursor'`）

- [ ] **Step 3: 状態・遷移・ペン・introspection を実装**

`__init__`（:723 `_active_curve_id` 宣言の直後）に:

```python
        # Active cursor (A/B) — transient View state, drives thick-line feedback
        # and arrow-key routing. None when no cursor is placed.
        self._active_cursor: str | None = None
        # Tracks whether B was showing on the previous sync, to detect the
        # off→on transition that makes B the active cursor.
        self._prev_showing_b: bool = False
```

`_sync_cursor_from_vm`(:1324) の `if t is None:` ブロック末尾（`self._readout.reset_user_moved()` の直後・`return` の前）に:

```python
            self._active_cursor = None
            self._prev_showing_b = False
```

同メソッドの `self._suppress_cursor_signal = True` の**直前**（`t` が None でない経路）に活性管理＋ペン適用を挿入:

```python
        showing_b = self.vm.delta_enabled and self.vm.cursor_t_b is not None
        if self._active_cursor is None:
            self._active_cursor = "A"
        if showing_b and not self._prev_showing_b:
            self._active_cursor = "B"
        if not showing_b and self._active_cursor == "B":
            self._active_cursor = "A"
        self._prev_showing_b = showing_b
        self._apply_cursor_pens()
```

新メソッド（`_on_cursor_line_dragged`:1361 付近に）:

```python
    def _apply_cursor_pens(self) -> None:
        """Thicken the active cursor line (width 3.5) and normalise the other."""
        self._cursor_line.setPen(
            pg.mkPen("#f9e2af", width=3.5 if self._active_cursor == "A" else 2)
        )
        self._cursor_line_b.setPen(
            pg.mkPen(
                "#89b4fa",
                width=3.5 if self._active_cursor == "B" else 2,
                style=Qt.PenStyle.DashLine,
            )
        )

    def active_cursor(self) -> str | None:
        """Which cursor (A/B) is active — transient View state (tests/realgui)."""
        return self._active_cursor

    def cursor_line_width(self, which: str) -> float:
        """Pen width of the A/B cursor line (tests/realgui)."""
        line = self._cursor_line if which == "A" else self._cursor_line_b
        return float(line.pen.widthF())
```

ドラッグ活性化 — `_on_cursor_line_dragged`/`_on_cursor_line_b_dragged`(:1361-1369) の各先頭（`_suppress_cursor_signal` ガードの後）に活性化を追加:

```python
    def _on_cursor_line_dragged(self) -> None:
        if self._suppress_cursor_signal:
            return
        self._active_cursor = "A"
        self.vm.set_cursor(float(self._cursor_line.value()))

    def _on_cursor_line_b_dragged(self) -> None:
        if self._suppress_cursor_signal:
            return
        self._active_cursor = "B"
        self.vm.set_cursor_b(float(self._cursor_line_b.value()))
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k "auto_activates or falls_back or deactivates" -v`
Expected: PASS（4件）

- [ ] **Step 5: 失敗するテストを書く（太線化＋ドラッグ活性化）**

```python
def test_active_cursor_line_is_thicker(qtbot):
    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.toggle_main_cursor(True)   # A active
    assert view.cursor_line_width("A") > view.cursor_line_width("B")
    view.vm.toggle_delta(True)         # B active
    assert view.cursor_line_width("B") > view.cursor_line_width("A")


def test_dragging_b_line_activates_b(qtbot):
    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    view.vm.toggle_delta(True)
    # simulate the A line being active, then a B-line drag re-activates B
    view._active_cursor = "A"
    view._cursor_line_b.setValue(0.6)  # fires sigPositionChanged → handler
    assert view.active_cursor() == "B"
```

- [ ] **Step 6: 失敗を確認 → 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k "thicker or activates_b" -v`
Expected: PASS（Step 3 実装で緑。`setValue` 経由で `_on_cursor_line_b_dragged` が発火し B 活性化）

- [ ] **Step 7: フルスイート＋ゲート → コミット**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_cursor.py
git commit -m "feat(gui): アクティブカーソル(A/B)状態＋自動アクティブ＋太線フィードバック"
```

---

### Task 3: 矢印キー（←/→）でアクティブカーソルをサンプル移動

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`keyPressEvent`:1870-1891 に ←/→ 分岐）
- Test: `tests/gui/test_graph_panel_cursor.py`

**Interfaces:**
- Consumes（Task 1/2 ＋既存）: `self.vm.step_cursor(which, direction, reference_entry_id)`（Task 1）・`self._active_cursor`（Task 2）・`self._active_curve_id`（既存）・`self.vm.cursor_t`・`Qt.Key.Key_Left`/`Key_Right`・focus policy `ClickFocus`（:845）
- Produces: なし（keyPressEvent 拡張）

**GUI テスト分析（gui-test-plan）:**
- 変更種別: 入力イベント→ハンドラ → **Layer B（合成 `qtbot.keyClick`）＋ Layer C（実キー・Task 6）**。
- 実質性: キー→`step_cursor` 配送は合成 keyClick で実経路（keyPressEvent）を通せる。基準 entry_id にアクティブ曲線が渡ること、アクティブカーソルが対象になることを VM 状態で検証。
- honest layering note: `qtbot.keyClick` は実キーではないが keyPressEvent は実ハンドラを通る（Layer B として妥当）。実 OS キーの無回帰は Task 6 realgui が担保。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_arrow_right_steps_active_cursor(qtbot):
    from PySide6.QtCore import Qt

    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.set_cursor(0.005)   # A active (auto)
    view.setFocus()
    qtbot.keyClick(view, Qt.Key.Key_Right)
    assert view.vm.cursor_t == pytest.approx(0.01)
    qtbot.keyClick(view, Qt.Key.Key_Left)
    assert view.vm.cursor_t == pytest.approx(0.0)


def test_arrow_steps_active_b_cursor(qtbot):
    from PySide6.QtCore import Qt

    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.set_cursor(0.005)
    view.vm.toggle_delta(True)  # B active, at 0.75
    view.setFocus()
    b_before = view.vm.cursor_t_b
    qtbot.keyClick(view, Qt.Key.Key_Left)
    assert view.vm.cursor_t_b is not None and view.vm.cursor_t_b <= b_before
    assert view.vm.cursor_t == pytest.approx(0.005)  # A untouched


def test_arrow_noop_without_cursor(qtbot):
    from PySide6.QtCore import Qt

    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.setFocus()
    qtbot.keyClick(view, Qt.Key.Key_Right)  # no cursor set
    assert view.vm.cursor_t is None
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k arrow_right_steps -v`
Expected: FAIL（矢印キーが未配線 → `cursor_t` が 0.005 のまま）

- [ ] **Step 3: `keyPressEvent` に ←/→ 分岐を追加**

`keyPressEvent`(:1870) の `Key_H` ブロックの後・`super().keyPressEvent(event)` の前に:

```python
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if self.vm.cursor_t is not None:
                direction = 1 if event.key() == Qt.Key.Key_Right else -1
                which = self._active_cursor or "A"
                # active curve is the snap reference; VM falls back to first
                # visible entry when it is None/hidden.
                self.vm.step_cursor(which, direction, self._active_curve_id)
                event.accept()
                return
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k "arrow_right_steps or arrow_steps_active_b or arrow_noop" -v`
Expected: PASS（3件）

- [ ] **Step 5: フルスイート＋ゲート → コミット**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_cursor.py
git commit -m "feat(gui): ←/→ でアクティブカーソルをサンプルスナップ移動（step_cursor 配送）"
```

---

### Task 4: カーソル線右クリックメニュー＋ルーティング先頭分岐＋時刻ダイアログ

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（コンストラクタ:660-680 に `time_dialog_fn` DI／`_cursor_line_at` 新設＋`_curve_at`:1590-1600 のガードを DRY 化／`build_cursor_menu`/`_clear_cursor`/`_prompt_cursor_time`/`_default_time_dialog` 追加／`contextMenuEvent`:2333 先頭にカーソル分岐）
- Test: `tests/gui/test_graph_panel_cursor.py`

**Interfaces:**
- Consumes（既存）: `self._cursor_line`/`_cursor_line_b`（`isVisible`/`value`）・`self._view_boxes[0].mapViewToScene`・`self.plot_widget.mapToScene`・`CURSOR_LINE_HIT_PX`（:82）・`self.vm.set_cursor(t|None)`・`self.vm.set_cursor_b(t)`・`self.vm.toggle_delta(False)`・`self.vm.cursor_t`/`cursor_t_b`・`_curve_at`（:1574）・`_zone_at`/`_axis_index_at`・`ZONE_Y_INNER`/`ZONE_Y_OUTER`・`build_curve_menu`/`build_axis_menu`/`build_context_menu`・`math`（既存 import）
- Produces:
  - `_cursor_line_at(self, pos: QPointF) -> str | None`
  - `build_cursor_menu(self, which: str) -> QMenu`
  - `_clear_cursor(self, which: str) -> None`
  - `_prompt_cursor_time(self, which: str) -> None`
  - `_default_time_dialog(self, which: str, current: float) -> float | None`
  - コンストラクタ kwarg `time_dialog_fn`（`self._time_dialog_fn`）

**GUI テスト分析（gui-test-plan）:**
- 変更種別: 入力イベント→ハンドラ（ルーティング）＋メニュー構成 → **Layer B 主戦場**。
- **ルーティングは実 `QContextMenuEvent` を送って検証**（3ビルダー＋カーソルビルダーをスパイに差し替え `.exec()` を no-op でハング回避・分類器 `_cursor_line_at`/`_curve_at`/`_zone_at`/`_axis_index_at` をスタブして分岐だけ検証。増分2b のルーティングテスト作法を踏襲）。
- メニュー構築（項目・時刻ダイアログ DI→`set_cursor`・消去スコープ A=全消去/B=Δのみ）は Layer B。時刻ダイアログ本体（非有限 OK 無効化）は DI シームのため stub 経路のみ。
- **`_cursor_line_at` を切り出す際は `_curve_at` のカーソルガードの挙動を厳密保存**（near-cursor で None を返す既存挙動）。

- [ ] **Step 1: 失敗するテストを書く（ルーティング先頭分岐）**

`tests/gui/test_graph_panel_cursor.py` に追記（増分2b の spy 作法）:

```python
from types import SimpleNamespace
from PySide6.QtCore import QPoint
from PySide6.QtGui import QContextMenuEvent
from valisync.gui.views.graph_panel_view import ZONE_PLOT


def _spy_all_menus(view):
    calls = []
    view.build_cursor_menu = lambda which: (  # type: ignore[method-assign]
        calls.append(("cursor", which)) or SimpleNamespace(exec=lambda *a: None)
    )
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


def test_context_menu_routes_cursor_first(qtbot):
    view = _shown_cursor_panel(qtbot)
    view._cursor_line_at = lambda pos: "A"        # type: ignore[method-assign]
    view._curve_at = lambda pos: 7                # would-be curve, but cursor wins
    calls = _spy_all_menus(view)
    view.contextMenuEvent(_ctx_event())
    assert calls == [("cursor", "A")]


def test_context_menu_curve_when_no_cursor_line(qtbot):
    view = _shown_cursor_panel(qtbot)
    view._cursor_line_at = lambda pos: None       # type: ignore[method-assign]
    view._curve_at = lambda pos: 7                # type: ignore[method-assign]
    calls = _spy_all_menus(view)
    view.contextMenuEvent(_ctx_event())
    assert calls == [("curve", 7)]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k context_menu_routes_cursor_first -v`
Expected: FAIL（`AttributeError: ... 'build_cursor_menu'` もしくはカーソル分岐が無く curve へ落ちる）

- [ ] **Step 3: DI kwarg・`_cursor_line_at`・メニュー群・ルーティングを実装**

コンストラクタ(:660-680) に `time_dialog_fn` を追加（既存 kwarg 群の末尾）:

```python
        reset_dialog_fn: Callable[[str], str | None] | None = None,
        time_dialog_fn: Callable[[str, float], float | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.vm = vm
        self._apply_dialog_fn = apply_dialog_fn
        self._color_dialog_fn = color_dialog_fn or self._default_color_dialog
        self._range_dialog_fn = range_dialog_fn
        self._offset_input_dialog_fn = offset_input_dialog_fn
        self._reset_dialog_fn = reset_dialog_fn
        self._time_dialog_fn = time_dialog_fn
```

`_cursor_line_at` を追加（`_curve_at`:1574 の直前に）:

```python
    def _cursor_line_at(self, pos: QPointF) -> str | None:
        """Return "A"/"B" if *pos* is within CURSOR_LINE_HIT_PX of a visible cursor line.

        Scene-pixel proximity test — the same one the _curve_at guard uses so the
        cursor line wins over a nearby curve. Checks A before B. None otherwise.
        """
        if not self._view_boxes:
            return None
        try:
            scene_pos = self.plot_widget.mapToScene(pos.toPoint())
        except Exception:
            return None
        vb0 = self._view_boxes[0]
        for which, line in (("A", self._cursor_line), ("B", self._cursor_line_b)):
            try:
                if not line.isVisible():
                    continue
                line_scene_x = vb0.mapViewToScene(QPointF(float(line.value()), 0.0)).x()
            except Exception:
                continue
            if abs(scene_pos.x() - line_scene_x) <= CURSOR_LINE_HIT_PX:
                return which
        return None
```

`_curve_at`(:1590-1600) のカーソルガード（`# Cursor-line guard:` から `return None` までの for ループ）を `_cursor_line_at` 呼び出しへ差し替え（DRY・挙動不変）:

```python
        # Cursor-line guard: yield to a nearby visible cursor line.
        if self._cursor_line_at(pos) is not None:
            return None
```

（`vb0 = self._view_boxes[0]` を `_curve_at` の後段でも使っているか確認し、使っていれば残す。使っていなければ削除。）

`build_cursor_menu`・`_clear_cursor`・`_prompt_cursor_time`・`_default_time_dialog` を追加（`build_context_menu`:2217 付近に）:

```python
    def build_cursor_menu(self, which: str) -> QMenu:
        """Right-click menu for a cursor line (spec §4.3: 時刻を指定…／消去)."""
        menu = QMenu(self)
        menu.addAction("時刻を指定…").triggered.connect(
            lambda *_: self._prompt_cursor_time(which)
        )
        label = "カーソルを消す" if which == "A" else "サブカーソルを消す"
        menu.addAction(label).triggered.connect(lambda *_: self._clear_cursor(which))
        return menu

    def _clear_cursor(self, which: str) -> None:
        """A line → clear all (B follows via VM invariant); B line → disable Δ only."""
        if which == "A":
            self.vm.set_cursor(None)
        else:
            self.vm.toggle_delta(False)

    def _prompt_cursor_time(self, which: str) -> None:
        """Open the time dialog and move *which* cursor to the entered time."""
        current = self.vm.cursor_t if which == "A" else self.vm.cursor_t_b
        if current is None:
            return
        fn = self._time_dialog_fn or self._default_time_dialog
        t = fn(which, current)
        if t is not None:
            if which == "A":
                self.vm.set_cursor(t)
            else:
                self.vm.set_cursor_b(t)

    def _default_time_dialog(self, which: str, current: float) -> float | None:
        """Modal cursor-time dialog (DI default). Returns t or None on cancel.

        OK is disabled while the input is non-finite (§10).
        """
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QLineEdit,
            QVBoxLayout,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("カーソル時刻を指定")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"{which} カーソルの時刻 (秒):"))
        edit = QLineEdit(f"{current:.6g}")
        lay.addWidget(edit)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)

        def _validate() -> None:
            try:
                val = float(edit.text())
            except ValueError:
                ok_btn.setEnabled(False)
                return
            ok_btn.setEnabled(math.isfinite(val))

        edit.textChanged.connect(lambda *_: _validate())
        ok_btn.setDefault(True)
        _validate()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return float(edit.text())
```

`contextMenuEvent`(:2333) 先頭にカーソル分岐を挿入:

```python
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        # ルーティング優先順 (spec §4.3): カーソル線 → 曲線 → Y軸 → 空白 (パネル)。
        pos = QPointF(event.pos())
        which = self._cursor_line_at(pos)
        if which is not None:
            self.build_cursor_menu(which).exec(event.globalPos())
            return
        eid = self._curve_at(pos)
        if eid is not None:
            self.build_curve_menu(eid).exec(event.globalPos())
            return
        if self._zone_at(pos) in (ZONE_Y_INNER, ZONE_Y_OUTER):
            self.build_axis_menu(self._axis_index_at(pos)).exec(event.globalPos())
            return
        self.build_context_menu().exec(event.globalPos())
```

- [ ] **Step 4: 通過を確認（ルーティング）**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k "context_menu_routes_cursor_first or context_menu_curve_when_no_cursor" -v`
Expected: PASS（2件）

- [ ] **Step 5: 失敗するテストを書く（メニュー構築・時刻ダイアログ DI・消去スコープ・`_cursor_line_at`）**

```python
def test_build_cursor_menu_items(qtbot):
    view = _shown_cursor_panel(qtbot)
    menu = view.build_cursor_menu("A")
    texts = [a.text() for a in menu.actions()]
    assert texts == ["時刻を指定…", "カーソルを消す"]
    menu_b = view.build_cursor_menu("B")
    assert [a.text() for a in menu_b.actions()] == ["時刻を指定…", "サブカーソルを消す"]


def test_cursor_time_dialog_moves_a(qtbot):
    view = _shown_cursor_panel(qtbot, time_dialog_fn=lambda which, cur: 0.42)
    view.vm.x_range = (0.0, 1.0)
    view.vm.set_cursor(0.1)
    act = next(a for a in view.build_cursor_menu("A").actions() if a.text() == "時刻を指定…")
    act.trigger()
    assert view.vm.cursor_t == pytest.approx(0.42)


def test_clear_a_clears_everything(qtbot):
    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.set_cursor(0.1)
    view.vm.toggle_delta(True)
    next(a for a in view.build_cursor_menu("A").actions()
         if a.text() == "カーソルを消す").trigger()
    assert view.vm.cursor_t is None
    assert view.vm.delta_enabled is False


def test_clear_b_only_disables_delta(qtbot):
    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.set_cursor(0.1)
    view.vm.toggle_delta(True)
    next(a for a in view.build_cursor_menu("B").actions()
         if a.text() == "サブカーソルを消す").trigger()
    assert view.vm.cursor_t == pytest.approx(0.1)   # A survives
    assert view.vm.delta_enabled is False


def test_cursor_line_at_detects_visible_line(qtbot):
    view = _shown_cursor_panel(qtbot)
    view.show()
    qtbot.waitExposed(view)
    view.vm.x_range = (0.0, 1.0)
    view.vm.set_cursor(0.5)
    # scene x of the A line → widget pos, then _cursor_line_at should report "A"
    vb0 = view._view_boxes[0]
    scene_x = vb0.mapViewToScene(QPointF(0.5, 0.0)).x()
    widget_pt = view.plot_widget.mapFromScene(QPointF(scene_x, 10.0))
    assert view._cursor_line_at(QPointF(widget_pt)) == "A"
```

（`GraphPanelView` の `time_dialog_fn` を渡す `_shown_cursor_panel` の引数対応が必要 — helper に `**kwargs` を通すか、テスト内で直接 `GraphPanelView(vm, time_dialog_fn=...)` を構築。）

- [ ] **Step 6: 失敗を確認 → 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k "build_cursor_menu or cursor_time_dialog or clear_a or clear_b or cursor_line_at" -v`
Expected: PASS（5件）

- [ ] **Step 7: フルスイート＋ゲート → コミット**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors（`_curve_at` DRY 化で既存カーソルガードのテストも緑を維持）

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_cursor.py
git commit -m "feat(gui): カーソル線右クリックメニュー（時刻指定/消去）＋ルーティング先頭分岐＋_cursor_line_at DRY化"
```

---

### Task 5: 補間方式の排他チェックメニュー＋readout ヘッダ表示（PC-09）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`build_context_menu`:2243-2251 の interp ブロックを排他 radio へ／`_sync_cursor_from_vm`:1345-1348 の `set_global`/`set_delta` 呼び出しに補間ラベルを渡す／モジュール先頭に `_INTERP_LABELS`）
- Modify: `src/valisync/gui/views/cursor_readout.py`（`set_global`:127・`set_delta`:147 に `interp_label` 引数）
- Test: `tests/gui/test_graph_panel_cursor.py`・`tests/gui/test_cursor_readout.py`

**Interfaces:**
- Consumes（既存）: `self.vm.interp_method`（:148）・`self.vm.set_interp_method(m)`（:900）・`InterpolationMethod`（LINEAR/ZERO_ORDER_HOLD/NEAREST）・`CursorReadout.header_text()`（introspection :185）・`_sync_cursor_from_vm`
- Produces:
  - `build_context_menu` の interp が checkable＋`QActionGroup(exclusive)`＋現在値 checked
  - `CursorReadout.set_global(t_a, readings, interp_label="")` / `set_delta(t_a, t_b, readings, interp_label="")`
  - モジュール定数 `_INTERP_LABELS: dict[InterpolationMethod, str]`

**GUI テスト分析（gui-test-plan）:**
- 変更種別: メニュー構成＋ウィジェット表示 → **Layer B**（CursorReadout はほぼ Layer A 相当の純ウィジェット）。
- 実質性: interp action が checkable＋排他＋現在値 checked であること、方式変更で checked が移ること、readout ヘッダに現在方式が出ることを自動アサート。
- honest layering note: `QActionGroup` はコードベース初導入。排他は「1つ checked にすると他が解除される」を assert して確認（構築時 setChecked ではなく group 排他の効果を見る）。

- [ ] **Step 1: 失敗するテストを書く（interp 排他メニュー）**

`tests/gui/test_graph_panel_cursor.py` に追記:

```python
def _interp_submenu(view):
    menu = view.build_context_menu()
    act = next(a for a in menu.actions() if a.text() == "補間方式")
    return act.menu()


def test_interp_menu_is_checkable_and_reflects_current(qtbot):
    from valisync.core.interpolation import InterpolationMethod

    view = _shown_cursor_panel(qtbot)
    view.vm.set_interp_method(InterpolationMethod.ZERO_ORDER_HOLD)
    sub = _interp_submenu(view)
    acts = {a.text(): a for a in sub.actions()}
    assert all(a.isCheckable() for a in acts.values())
    assert acts["前値保持"].isChecked() is True
    assert acts["線形"].isChecked() is False


def test_interp_menu_is_exclusive(qtbot):
    view = _shown_cursor_panel(qtbot)
    sub = _interp_submenu(view)
    acts = {a.text(): a for a in sub.actions()}
    acts["最近傍"].setChecked(True)   # exclusive group unchecks the others
    assert acts["線形"].isChecked() is False
    assert acts["前値保持"].isChecked() is False


def test_interp_menu_action_sets_vm(qtbot):
    from valisync.core.interpolation import InterpolationMethod

    view = _shown_cursor_panel(qtbot)
    sub = _interp_submenu(view)
    next(a for a in sub.actions() if a.text() == "最近傍").trigger()
    assert view.vm.interp_method == InterpolationMethod.NEAREST
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k interp_menu_is_checkable -v`
Expected: FAIL（現状 interp は非 checkable → `isCheckable()` False）

- [ ] **Step 3: interp ブロックを排他 radio へ改造＋`_INTERP_LABELS`**

モジュール先頭の import 群付近（`_PALETTE` 等の定数の並び）に:

```python
from valisync.core.interpolation import InterpolationMethod

_INTERP_LABELS: dict[InterpolationMethod, str] = {
    InterpolationMethod.LINEAR: "線形",
    InterpolationMethod.ZERO_ORDER_HOLD: "前値保持",
    InterpolationMethod.NEAREST: "最近傍",
}
```

（既存 `build_context_menu` 内のローカル `from valisync.core.interpolation import InterpolationMethod` は残置してよいが、モジュール先頭 import があれば重複ローカル import は削除して差し支えない。ruff が未使用/重複を指摘したら整理。）

`build_context_menu`(:2243-2251) の interp ブロックを差し替え:

```python
        from PySide6.QtGui import QActionGroup

        interp = menu.addMenu("補間方式")
        interp_group = QActionGroup(interp)
        interp_group.setExclusive(True)
        for label, method in (
            ("線形", InterpolationMethod.LINEAR),
            ("前値保持", InterpolationMethod.ZERO_ORDER_HOLD),
            ("最近傍", InterpolationMethod.NEAREST),
        ):
            act = interp.addAction(label)
            act.setCheckable(True)
            act.setActionGroup(interp_group)
            act.setChecked(method == self.vm.interp_method)  # BEFORE triggered.connect
            act.triggered.connect(lambda *_, m=method: self.vm.set_interp_method(m))
```

- [ ] **Step 4: 通過を確認（interp メニュー）**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k "interp_menu_is_checkable or interp_menu_is_exclusive or interp_menu_action_sets_vm" -v`
Expected: PASS（3件）

- [ ] **Step 5: 失敗するテストを書く（readout 補間ラベル）**

`tests/gui/test_cursor_readout.py` に追記（既存の CursorReadout 単体テスト作法に合わせる）:

```python
def test_set_global_header_includes_interp_label(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(
        1.5, [CursorReading("csv::a", "#fff", 3.0, True)], interp_label="線形"
    )
    assert "線形" in ro.header_text()


def test_set_delta_header_includes_interp_label(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import DeltaReading
    from valisync.core.analysis import StatisticsResult

    ro = CursorReadout()
    qtbot.addWidget(ro)
    stats = StatisticsResult(mean=1.0, max=2.0, min=0.0, std=0.5, count=3)
    ro.set_delta(
        1.0, 2.0,
        [DeltaReading("csv::a", "#fff", 1.0, 0.5, stats, True)],
        interp_label="最近傍",
    )
    assert "最近傍" in ro.header_text()
```

（`StatisticsResult` の import 元は既存 `delta_readings` テストに合わせる。無ければ既存 `test_cursor_readout_diff.py` の import を流用。）

- [ ] **Step 6: 失敗を確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k interp_label -v`
Expected: FAIL（`set_global()` が `interp_label` 引数を受けない → TypeError）

- [ ] **Step 7: `CursorReadout.set_global`/`set_delta` に `interp_label` を追加**

`cursor_readout.py` の `set_global`(:127):

```python
    def set_global(
        self, t_a: float, readings: list[CursorReading], interp_label: str = ""
    ) -> None:
        """Global mode: header = ● t_a [ ─ interp], columns = [swatch|name|値]."""
        self._last_delta = None
        ta_str = _fmt_time(t_a)
        self._header_text = f"● {ta_str}"
        if interp_label:
            self._header_text += f"  ─ {interp_label}"
        self._col_headers = []
        header_html = f'<span style="color:#f9e2af">●</span> {ta_str}'
        if interp_label:
            header_html += f"  ─ {interp_label}"
        self._header.setText(header_html)
        self._header.show()
        self._rebuild(
            col_headers=[],
            rows=[
                (
                    r.name,
                    r.color,
                    [_fmt_labeled(r.value if r.in_range else None, r.label)],
                )
                for r in readings
            ],
        )
```

`set_delta`(:147) の header 組み立てに `interp_label` を追記:

```python
    def set_delta(
        self,
        t_a: float,
        t_b: float,
        readings: list[DeltaReading],
        interp_label: str = "",
    ) -> None:
        """Delta mode: header = ● t_a ● t_b · Δt [ ─ interp], columns = A値/Δy/<stats>."""
        self._last_delta = (t_a, t_b, readings)
        dt = t_b - t_a
        ta_str = _fmt_time(t_a)
        tb_str = _fmt_time(t_b)
        dt_str = _fmt_time(dt)
        self._header_text = f"● {ta_str}  ● {tb_str} · Δt {dt_str}"
        if interp_label:
            self._header_text += f"  ─ {interp_label}"
        stat_cols = [c for c in _STAT_COLS if c in self._visible_stats]
        self._col_headers = ["A値", "Δy", *stat_cols]
        header_html = (
            f'<span style="color:#f9e2af">●</span> {ta_str}'
            f'  <span style="color:#89b4fa">●</span> {tb_str}'
            f" · <b>Δt {dt_str}</b>"
        )
        if interp_label:
            header_html += f"  ─ {interp_label}"
        self._header.setText(header_html)
        self._header.show()
        rows = []
        for r in readings:
            cells: list[str] = [
                _fmt_labeled(r.value_a if r.in_range else None, r.label),
                _fmt_dy(r.dy),
            ]
            if r.stats.count == 0:
                cells += [_NO_DATA for _ in stat_cols]
            else:
                stat_map: dict[str, str] = {
                    "mean": f"{r.stats.mean:.4g}",
                    "max": f"{r.stats.max:.4g}",
                    "min": f"{r.stats.min:.4g}",
                    "std": f"{r.stats.std:.4g}",
                    "count": str(r.stats.count),
                }
                cells += [stat_map[c] for c in stat_cols]
            rows.append((r.name, r.color, cells))
        self._rebuild(col_headers=self._col_headers, rows=rows)
```

View 側 `_sync_cursor_from_vm`(:1345-1348) の呼び出しに補間ラベルを渡す:

```python
            self._readout.set_delta(
                t, self.vm.cursor_t_b, self.vm.delta_readings(),
                interp_label=_INTERP_LABELS.get(self.vm.interp_method, ""),
            )
        else:
            self._cursor_line_b.setVisible(False)
            self._readout.set_global(
                t, self.vm.cursor_readings(),
                interp_label=_INTERP_LABELS.get(self.vm.interp_method, ""),
            )
```

- [ ] **Step 8: 通過を確認（readout ラベル）＋ View 統合の確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k interp_label -v`
Expected: PASS（2件）

追加の View 統合テスト（`tests/gui/test_graph_panel_cursor.py`）:

```python
def test_readout_header_shows_current_interp(qtbot):
    from valisync.core.interpolation import InterpolationMethod

    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.set_interp_method(InterpolationMethod.NEAREST)
    view.vm.set_cursor(0.005)
    assert "最近傍" in view._readout.header_text()
```

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k readout_header_shows_current_interp -v`
Expected: PASS

- [ ] **Step 9: フルスイート＋ゲート → コミット**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

```bash
git add src/valisync/gui/views/graph_panel_view.py src/valisync/gui/views/cursor_readout.py tests/gui/test_graph_panel_cursor.py tests/gui/test_cursor_readout.py
git commit -m "feat(gui): 補間方式を排他チェックメニュー化＋readout ヘッダに現在方式を常時表示（PC-09）"
```

---

### Task 6: realgui 証拠（Layer C・実 OS 入力）

**Files:**
- Modify: `tests/realgui/test_global_cursor.py`（実 ←/→・カーソル線右クリック・補間 radio を追加）
- Test: 既存 `tests/realgui/test_global_cursor.py` を①ゲートで再実行（無回帰）

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input`（`at`/`key`/`LDOWN`/`LUP`/`MOVE`/`RDOWN`/`RUP`/`to_phys`/`skip_unless_real_display`）・既存 `_shown_panel`/`_scene_center` scaffolding・View introspection `cursor_line_visible()`/`cursor_line_value()`/`active_cursor()`（Task 2）・`_menu_hang_watchdog`（他 realgui から流用）・DI 注入（`GraphPanelView(vm, time_dialog_fn=...)`）
- Produces: 実 OS 入力の証拠（pass/fail・スクショ）

**GUI テスト分析（gui-test-plan）:**
- spec §11 Layer C 増分3: 「実 ←/→ でカーソル移動／readout ✕ 実クリック／readout 実右クリックメニュー」。本 3a は **実 ←/→ と カーソル線右クリックメニュー**（readout ✕/メニューは 3b）。
- 実質性: 実キー ←/→ でカーソル線 x が隣接サンプルへ動く（数値 `cursor_line_value` の変化＝load-bearing）／実右クリックでカーソルメニューが出て「時刻を指定…」（DI）/「カーソルを消す」が効く（VM 状態＋スクショ）／補間 radio が実クリックで現在方式に付く。メニュー navigation は実 OS 入力・終端ダイアログは DI スタブ。
- **クリック点はゾーン幾何から導出**（カーソル線の scene x → 物理座標）。menu.exec ハング回避に `_menu_hang_watchdog` 併設。

- [ ] **Step 1: 実 ←/→ の realgui を書く**

`tests/realgui/test_global_cursor.py` に追記（既存 `_shown_panel`・`skip_unless_real_display`・`key` を使用）。実キー送出のヘルパは `_realgui_input`（他 realgui＝増分2b/2a の実キー送出に倣う）。

```python
@pytest.mark.realgui
def test_real_arrow_keys_step_cursor(qtbot, tmp_path):
    """A 線をトグル設置→ウィンドウにフォーカス→実 → キーで cursor 値が増加。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible()
    view.setFocus()
    for _ in range(3):
        QApplication.processEvents()
    x_before = view.cursor_line_value()
    _press_key_right(view)   # 実 OS Key_Right（_realgui_input の実キー送出に準拠）
    for _ in range(5):
        QApplication.processEvents()
    assert view.cursor_line_value() > x_before
```

（`_press_key_right` は `tests/realgui/_realgui_input` の実キー送出 API に合わせて実装。既存 realgui の実キー送出〔増分2b の Ctrl+O/E 等〕を雛形にする。無ければ `reference/realgui-recipe.md` に従い追加し Layer C 契約ガードを満たすこと。）

- [ ] **Step 2: カーソル線右クリックメニューの realgui を書く**

```python
@pytest.mark.realgui
def test_real_right_click_cursor_line_clears(qtbot, tmp_path):
    """A 線を設置→線上を実右クリック→「カーソルを消す」実クリック→カーソル消滅。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    # A 線の scene x → 物理座標で実右クリック
    line_x = view.cursor_line_value()
    sx = view._view_boxes[0].mapViewToScene(QPointF(line_x, 0.0)).x()
    _sx, sy, _ = _scene_center(view)
    px, py = to_phys(view, sx, sy)
    with _menu_hang_watchdog():
        at(px, py, RDOWN)
        at(px, py, RUP)
        _click_menu_item(view, "カーソルを消す")   # 実 OS クリック
    for _ in range(5):
        QApplication.processEvents()
    assert not view.cursor_line_visible()
```

（`_menu_hang_watchdog`・`_click_menu_item`・`RDOWN`/`RUP` は既存 realgui〔増分2b `test_axis_menu_offset.py`〕の実 OS 右クリック＋メニュー実クリック作法をそのまま流用。`QPointF`/`to_phys` の import を追加。）

- [ ] **Step 3: 新規 realgui を①ゲートで実行**

Run: `uv run pytest --realgui tests/realgui/test_global_cursor.py -k "arrow_keys_step or right_click_cursor_line" -v`
Expected: PASS（2件）。スクショは `QT_QPA_PLATFORM=windows`（文字化けなし）。

- [ ] **Step 4: 既存 realgui の無回帰を①ゲートで実行**

カーソル線ドラッグ・delta・stats に本増分（アクティブカーソル太線化・ペン切替・ルーティング先頭分岐）が回帰を与えないことを実 OS 入力で確認。

Run: `uv run pytest --realgui tests/realgui/test_global_cursor.py -v`
Expected: PASS（既存＋新規全数）

- [ ] **Step 5: Layer C 契約ガード＋headless full**

Run: `uv run pytest tests/gui/test_realgui_layer_c_contract.py -v`
Expected: PASS（新規 realgui が実 OS 入力）

Run: `uv run pytest`
Expected: headless full 0 errors（realgui は自動スキップ）

- [ ] **Step 6: ①証拠ゲート判定（merge 前・`/gui-verify`）**
  - (a) headless full `uv run pytest` 0 errors
  - (b) realgui 証拠: 新規2本＋既存 `test_global_cursor.py` 再実行 pass・スクショ・Layer C 契約ガード pass
  - (c) CI 緑（push 後 PR で確認）

- [ ] **Step 7: コミット**

```bash
git add tests/realgui/test_global_cursor.py
git commit -m "test(realgui): 実 ←/→ カーソル移動＋カーソル線右クリックメニューの実 OS 入力検証（Layer C ①ゲート）"
```

---

## Self-Review

**1. Spec coverage（§8 のうち 3a 帰属分＝PC-08/PC-09）:**

| spec 要件 | 担当タスク |
|---|---|
| `step_cursor(which,direction,reference_entry_id)` サンプルスナップ・端 clamp・フォールバック | Task 1 |
| アクティブカーソル（A/B）活性化＋設置直後自動アクティブ＋太線化 | Task 2 |
| ←/→ でアクティブカーソル移動（基準 entry_id 解決・ClickFocus） | Task 3 |
| カーソル線右クリック `build_cursor_menu`（時刻を指定…数値ダイアログ DI／消去 A=全消去・B=Δのみ） | Task 4 |
| ルーティング先頭にカーソル線分岐（カーソル→曲線→Y軸→空白） | Task 4 |
| 補間方式サブメニュー checkable＋QActionGroup 排他＋現在値 checked（PC-09） | Task 5 |
| readout ヘッダ右端に現在補間方式を常時表示（PC-09） | Task 5 |
| realgui 実 ←/→・カーソル線右クリック・無回帰 | Task 6 |

**3b（次PR・本プラン対象外）**: readout 刷新（PC-10 単位・PC-11 精度・PC-12 統計列・PC-16 コピー・PC-17 ✕・PC-18 移動アフォーダンス）。

**2. Placeholder scan:** 各コード step に実コードあり。realgui（Task 6）の実キー送出／`_menu_hang_watchdog`／`_click_menu_item` は既存 `tests/realgui/` 資産への委譲（placeholder でなく既存 API 参照）で、実装者は既存 realgui を読んで準拠する旨を明記。

**3. Type consistency:**
- `step_cursor(which: str, direction: int, reference_entry_id: int | None)`（Task 1 定義）を Task 3 が `self.vm.step_cursor(which, direction, self._active_curve_id)` で一致呼び出し。
- `_active_cursor: str | None`（"A"/"B"）を Task 2 定義・Task 3 で `self._active_cursor or "A"` 使用・型一致。
- `_cursor_line_at(pos) -> str | None`（Task 4 定義）を `contextMenuEvent` と `_curve_at` ガードの両方で一致使用。
- `time_dialog_fn: Callable[[str, float], float | None]`（Task 4 コンストラクタ）と `_default_time_dialog(which, current) -> float | None` の型一致。
- `set_global(..., interp_label="")`/`set_delta(..., interp_label="")`（Task 5・CursorReadout）を View `_sync_cursor_from_vm` が `_INTERP_LABELS.get(...)` で渡す・型一致。
- `_INTERP_LABELS: dict[InterpolationMethod, str]`（Task 5）を Task 5 のみで使用。

**4. 依存順:** Task 1（VM step_cursor）→ Task 2（アクティブカーソル状態）→ Task 3（矢印キー・1+2 消費）→ Task 4（カーソルメニュー＋ルーティング）→ Task 5（補間 PC-09・独立）→ Task 6（realgui・全実装後）。各タスクは独立テスト可能な成果物で終わる。Task 4 の `_curve_at` DRY 化はカーソルガードの挙動を厳密保存（既存カーソル近傍テストで無回帰確認）。
