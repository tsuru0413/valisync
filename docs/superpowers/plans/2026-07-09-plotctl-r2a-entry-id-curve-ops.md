# 増分2a: entry_id 基盤＋曲線の直接操作 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 曲線を entry 単位の安定 ID で識別できるようにし、曲線への直接操作（クリック活性化＋太線化・H キー表示切替・右クリックメニューでの非表示/色変更/削除）を追加する（PC-01🔴・PC-05🟠）。

**Architecture:** VM 側に `_PlottedEntry.entry_id`（単調増分）を導入し `RenderCurve` に載せる。View の内部辞書（`_items`/`_item_vb`）を entry_id キーへ移行し、同一 signal_key を複数 axis に載せても独立描画・独立操作できるようにする。公開アクセサ（`curve_keys`/`curve_xy`/`pen_color`/`is_clipped`）も **entry_id キーへ全面移行**（spec §4.2 文言どおり）し、signal_key で曲線を指す既存テスト（9 ファイル・realgui 4 本含む）を `entry_id_for(signal_key)`/`signal_keys_drawn()` を介して entry_id 解決へ更新する。曲線右クリックは `contextMenuEvent` のヒットテスト分岐（曲線→空白。軸分岐は増分2b・カーソル線分岐は増分3 で差し込む）で振り分ける。オフセットドラッグは DP16 に従い「press=候補保持→`startDragDistance` 閾値超えでドラッグ開始／閾値内 release=曲線活性化」へ変更する（grabMouse は press 時点で取得）。

**Tech Stack:** Python 3.13 / PySide6 (QtWidgets/QtGui/QtCore) / pyqtgraph / MVVM。テストは pytest＋pytest-qt（Layer A/B）、realgui は `_realgui_input` 実 OS 入力＋スクショ AI 判定（Layer C）。

## Global Constraints

- **MVVM 境界**: View は VM のみ参照。core（Session/Signal）へ View から直接触れない。曲線操作はすべて entry_id を VM API へ渡して委譲する。
- **entry_id の同一性**: `entry_id` は VM が採番する単調増分 int。同一 signal_key の複数エントリを一意に区別する。View の内部キーも公開アクセサ（`curve_keys`/`curve_xy`/`pen_color`/`is_clipped`/`pen_width`）も entry_id（spec §4.2 文言どおりの全面移行）。signal_key での参照は `entry_id_for(signal_key)`（first-match）と `signal_keys_drawn()` で解決する。
- **`RenderCurve.name` の役割は不変**: `name` は namespaced signal_key（凡例・カーソル読み取り・データ参照キー）。entry_id は識別子として**追加**するだけで name の意味を変えない。
- **色変更・可視切替は cache invalidate 必須**: 色は `_make_cache_key` に含まれないため、`set_color`/`toggle_entry_visibility`/`remove_entry`/`toggle_axis_visibility` はすべて `_invalidate_cache()`＋`_notify("signals")`（既存 `toggle_visibility` が先例・graph_panel_vm.py:486-493）。
- **アクティブ曲線の可視フィードバック**: 太線化（通常 width 1.0 → アクティブ 2.5・**色は不変**）。`refresh` の setPen が唯一の権威的再描画。
- **DP16 ジェスチャ**: press 時に `grabMouse()`（押下中 move は子 QGraphicsView に消費され親に届かないため・memory `gui_realgui_move_not_reaching_parent_qwidget`）。閾値 = `QApplication.startDragDistance()`。閾値内 release=活性化／閾値超え=オフセットドラッグ。活性化・commit・Escape・全終了パスで `releaseMouse()`。
- **アクティブ曲線の解除規則**: 軸クリック・空白/X ゾーンのクリック・他曲線クリックで解除。**H による非表示化は解除トリガーにしない**（非表示曲線はクリック不可のため直後の H 再表示を保証）。曲線活性化は属する軸も活性化する。
- **ダイアログは DI 注入**: QColorDialog は `color_dialog_fn` で注入（既存 `apply_dialog_fn` パターン・graph_panel_view.py:656）。realgui でネイティブモーダルを駆動しない。
- **死蔵削除はテスト改変ゼロ**: `ChannelBrowserVM._hidden`/`toggle_visibility`/`is_visible`/`visible_signal_keys`・`SignalItem.visible`・`ChannelBrowserView.toggle_visibility_for_selection` はテスト参照ゼロ（監査済み）。削除は production のみ。
- **品質ゲート**: 各コミットで `uv run pytest` 全 pass（0 errors）／`ruff check`＋`ruff format --check`／`mypy src/` を通す。コード・コメントで全角記号（（）×＋ 等）を使わない（RUF003）。

**設計 spec**: [docs/superpowers/specs/2026-07-09-gui-plot-analysis-controls-design.md](../specs/2026-07-09-gui-plot-analysis-controls-design.md) §2・§4.2・§4.3・§4.4・§7・§10・§11。増分2 を 2a（本プラン＝PC-01/PC-05）と 2b（PC-06/PC-03＝軸メニュー・オフセット導線・新しい軸へ移動）に分割。

---

## gui-test-plan 分析（②実質的受け入れ要件・①証拠ゲート）

| タスク | 変更種別 | Layer A | Layer B | Layer C（realgui） |
|---|---|---|---|---|
| 1 VM entry_id 基盤 | 純 VM ロジック | **必須**（採番・搬送・逆引き） | 不要 | 不要 |
| 2 VM 操作 API | 純 VM ロジック | **必須**（entry 単位・重複安全・cache bust） | 不要 | 不要 |
| 3 View 再キー化＋アクセサ全面移行 | ウィジェット構成・状態 | 一部（重複独立描画） | **必須**（アクセサ entry_id 化＋既存9ファイルを entry_id 解決へ更新して green） | task 8 で touched realgui 4本を再実行 |
| 4 DP16＋曲線活性化 | 入力イベント→ハンドラ | 不要 | **必須**（合成 press/move/release で候補→閾値→活性化/ドラッグ分岐・太線） | **必須**（task 8: 実クリック活性化・実ドラッグ=offset の分岐は合成が false-green） |
| 5 H キー | 入力イベント→ハンドラ | VM 側で網羅 | **必須**（keyClick で曲線切替→軸フォールバック） | **必須**（task 8: 実 H キー） |
| 6 右クリックルーティング＋曲線メニュー | 入力イベント→ハンドラ | 不要 | **必須**（QContextMenuEvent sendEvent で曲線位置→曲線メニュー・空白→パネルメニューの分岐／各項目 emit・DI スタブ） | **必須**（task 8: 実右クリック→メニュー実行） |
| 7 死蔵削除 | 純ロジック削除 | 回帰（既存 signals テスト green 維持） | 不要 | 不要 |
| 8 realgui 証拠 | Layer C | — | — | **本体** |

### ②実質性ルーブリック（naive を避ける）
- **曲線活性化の太線化**（task 4）: 「人間はクリック後に線が太くなるのを見て合格と判断」。自動アサート = `pen_width(eid) == 2.5`（Layer B）。視覚確定 = 実クリック後のスクショ（Layer C）。**VM 状態の再チェックだけ・スクショ保存だけは naive** → 実際の pen 幅を測る。
- **DP16 分岐**（task 4）: 「閾値内クリック=活性化（オフセット不変）」「閾値超え=オフセット適用」。Layer B は sendEvent で move を親へ直送するため grabMouse タイミングの誤りを**検出できない**（memory `gui_realgui_move_not_reaching_parent_qwidget`）→ **実 OS ドラッグの Layer C が真のゲート**。閾値内クリックが `curve_xy` を変えないこと＋活性化することの両方を assert。
- **右クリックメニュー**（task 6）: 「正しい位置で正しいメニューが出る」。ビルダー直呼びだけで済ませない → **QContextMenuEvent を sendEvent し、曲線位置で曲線メニュー・空白でパネルメニューが構築される**ことをルーティング経由で検証（false-green 防止）。メニュー項目の enabled/emit は DI スタブで確認。

### honest layering note
- task 4 の「閾値内 release=活性化」を Layer B の合成 press+release だけで検証すると、grabMouse を取らなくても move が届くため**実機で壊れていても green**になりうる。合成テストは分岐ロジック（候補→閾値判定→活性化 or ドラッグ）の検証にとどめ、grabMouse を要する実 move 経路は Layer C を真のゲートとする（`docs/gui-testing-layers.md`）。
- 公開アクセサを entry_id キーへ全面移行するため、signal_key で曲線を指す既存テスト（9 ファイル）を `entry_id_for(signal_key)`/`signal_keys_drawn()` 経由へ更新する。これは観測 API のキー型変更であってハンドラ迂回ではない（実経路のテストは維持）。realgui 4 ファイル（active_panel_flow/cross_panel_axis/signal_dnd/offset_drag）の `curve_keys` アサートも更新対象で、①ゲートで再実行して無回帰を証拠化する。

### ①証拠ゲート（merge 前・`/gui-verify` で実行）
- [ ] 変更 GUI ファイル（`graph_panel_view.py`・`channel_browser_view.py`・`channel_browser_vm.py`・`graph_panel_vm.py`）に対応する realgui を scoped 実行し証拠添付。
- [ ] 新規 realgui（曲線活性化・H・右クリックメニュー）を `--realgui` で pass＋スクショ。
- [ ] **既存 `tests/realgui/test_offset_drag.py` を DP16 変更に対し再実行**（閾値超えドラッグ=オフセット適用が実 OS 入力で動くこと・memory `gui_realgui_move_not_reaching_parent_qwidget`）。
- [ ] **アクセサ全面移行で curve_keys アサートを更新した realgui 4 ファイル**（active_panel_flow/cross_panel_axis/signal_dnd/offset_drag）を `--realgui` 再実行し無回帰を証拠化。
- [ ] 挙動変更（offset drag 開始タイミング）に追随しない stale な並行 realgui/Layer B アサートが無いか `tests/` 全体を grep（memory `gui_behavior_change_stale_parallel_realgui_test`）。
- [ ] headless full `uv run pytest` が **0 errors**。

---

## File Structure

| ファイル | 変更 | 責務 |
|---|---|---|
| `src/valisync/gui/viewmodels/graph_panel_vm.py` | Modify | `_PlottedEntry.entry_id`・採番・`RenderCurve.entry_id`・`render_data` 搬送・逆引き（`signal_key_for_entry`/`axis_of_entry`）・操作 API（`toggle_entry_visibility`/`set_color`/`remove_entry`/`toggle_axis_visibility`）・`inspect` 拡張 |
| `src/valisync/gui/views/graph_panel_view.py` | Modify | 内部辞書の entry_id 化・`_item_signal_key`・`refresh` desired・`_curve_at→int`・オフセットドラッグ entry_id 化・公開アクセサの entry_id 全面移行＋`entry_id_for`/`signal_keys_drawn`・曲線活性化（`_active_curve_id`/`_activate_curve`/`_deactivate_curve`）・DP16 ジェスチャ・H キー・`contextMenuEvent` ルーティング・`build_curve_menu`・色ダイアログ DI |
| `src/valisync/gui/viewmodels/channel_browser_vm.py` | Modify | 死蔵 `_hidden`/`toggle_visibility`/`is_visible`/`visible_signal_keys` 削除・`SignalItem.visible` 削除 |
| `src/valisync/gui/views/channel_browser_view.py` | Modify | 死蔵 `toggle_visibility_for_selection` 削除 |
| `tests/gui/test_graph_panel_vm.py` | Modify | entry_id 採番・操作 API・重複独立の VM テスト追加 |
| `tests/gui/test_graph_panel_view.py` | Modify | 重複独立描画・活性化太線・H・右クリックルーティング・メニュー項目の view テスト追加 |
| `tests/realgui/test_curve_direct_ops.py` | Create | 実クリック活性化＋実 H＋実右クリックメニュー（Layer C） |

---

## Task 1: VM entry_id 基盤（採番・搬送・逆引き）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`_PlottedEntry` :106-113・`__init__` :125-159・`add_signal_to_axis` :205-226・`RenderCurve` :50-62・`render_data` :601-691・`inspect` :883-914）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Produces:
  - `_PlottedEntry.entry_id: int`（新フィールド・default 0）
  - `RenderCurve.entry_id: int`（新フィールド・default 0）
  - `GraphPanelVM.signal_key_for_entry(entry_id: int) -> str | None`
  - `GraphPanelVM.axis_of_entry(entry_id: int) -> int | None`
  - `inspect()["plotted_signals"][i]["entry_id"]`（追加キー）
  - 内部: `self._next_entry_id: int`（単調増分カウンタ）

- [ ] **Step 1: 失敗するテストを書く**（採番・逆引き・重複独立 ID）

`tests/gui/test_graph_panel_vm.py` の末尾付近に追記（`_loaded_session` 相当のヘルパは既存の CSV ロードを使う。既存テストの `GraphPanelVM(session)` + `vm.add_signal(key)` パターンに合わせる）:

```python
def test_entry_id_is_monotonic_and_unique(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    k0, k1 = [s.name for s in session.signals()][:2]
    vm = GraphPanelVM(session)
    vm.add_signal(k0)
    vm.add_signal(k1)
    ids = [e["entry_id"] for e in vm.inspect()["plotted_signals"]]
    assert ids == [0, 1]  # 単調増分・追加順


def test_same_signal_key_gets_distinct_entry_ids(tmp_path: Path) -> None:
    # 同一 signal_key を 2 axis に載せると別 entry として独立管理される（entry_id の核心）
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = [s.name for s in session.signals()][0]
    vm = GraphPanelVM(session)
    vm.add_signal(key)  # axis 0
    vm.create_new_axis(key)  # 別 axis
    entries = vm.inspect()["plotted_signals"]
    assert len(entries) == 2
    assert entries[0]["entry_id"] != entries[1]["entry_id"]
    assert entries[0]["signal_key"] == entries[1]["signal_key"] == key


def test_signal_key_and_axis_reverse_lookup(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = [s.name for s in session.signals()][0]
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.create_new_axis(key)
    e0, e1 = vm.inspect()["plotted_signals"]
    assert vm.signal_key_for_entry(e0["entry_id"]) == key
    assert vm.axis_of_entry(e1["entry_id"]) == e1["axis_index"]
    assert vm.signal_key_for_entry(999) is None
    assert vm.axis_of_entry(999) is None


def test_render_data_carries_entry_id(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = [s.name for s in session.signals()][0]
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.create_new_axis(key)
    curves = vm.render_data()
    plotted_ids = {e["entry_id"] for e in vm.inspect()["plotted_signals"]}
    assert {c.entry_id for c in curves} == plotted_ids
```

`_loaded_session` が `test_graph_panel_vm.py` に無ければ、既存の CSV ヘルパ（`_csv_format`/`_write_csv`）で作る同ファイル内ヘルパを流用する（既存テストの session 構築を踏襲）。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "entry_id or reverse_lookup or carries_entry_id" -v`
Expected: FAIL（`_PlottedEntry` に entry_id なし・`signal_key_for_entry` 未定義・`RenderCurve.entry_id` 未定義）

- [ ] **Step 3: `_PlottedEntry` と `RenderCurve` に entry_id を追加**

`_PlottedEntry`（現 :106-113）:

```python
@dataclass
class _PlottedEntry:
    """Internal record for one plotted signal."""

    signal_key: str
    color: str
    visible: bool = True
    axis_index: int = 0
    entry_id: int = 0  # 単調増分の安定 ID (同一 signal_key の複数エントリを区別)
```

`RenderCurve`（現 :50-62）に追記:

```python
    axis_index: int = 0  # Added for multi-axis support
    entry_id: int = 0  # 曲線の安定 ID (View の内部キー・per-entry 操作の指名に使う)
```

- [ ] **Step 4: 採番カウンタと逆引きを実装**

`__init__`（現 :128 付近、`self._plotted` 宣言の直後）に追加:

```python
        self._plotted: list[_PlottedEntry] = []
        self._next_entry_id: int = 0  # add ごとに払い出す単調増分 ID
```

`add_signal_to_axis`（現 :205-210）の append を採番付きに:

```python
    def add_signal_to_axis(self, signal_key: str, axis_index: int) -> None:
        """Add *signal_key* to a specific axis."""
        color = _PALETTE[len(self._plotted) % len(_PALETTE)]
        entry_id = self._next_entry_id
        self._next_entry_id += 1
        self._plotted.append(
            _PlottedEntry(
                signal_key=signal_key,
                color=color,
                axis_index=axis_index,
                entry_id=entry_id,
            )
        )
```

逆引きヘルパを `# ─── Introspection` の直前あたり（`inspect` の近く）に追加:

```python
    def signal_key_for_entry(self, entry_id: int) -> str | None:
        """Return the signal_key of the entry with *entry_id* (None if absent)."""
        for e in self._plotted:
            if e.entry_id == entry_id:
                return e.signal_key
        return None

    def axis_of_entry(self, entry_id: int) -> int | None:
        """Return the axis_index of the entry with *entry_id* (None if absent)."""
        for e in self._plotted:
            if e.entry_id == entry_id:
                return e.axis_index
        return None
```

- [ ] **Step 5: `render_data` の全 RenderCurve に entry_id を載せる**

`render_data`（:601-691）には RenderCurve 生成が 3 箇所（sig None :608・空スライス :642・通常 :676）。すべてに `entry_id=entry.entry_id` を追加し、sig None の箇所には欠けている `axis_index=entry.axis_index` も足す:

```python
            sig = sig_map.get(entry.signal_key)
            if sig is None:
                curves.append(
                    RenderCurve(
                        name=entry.signal_key,
                        color=entry.color,
                        timestamps=np.empty(0, dtype=np.float64),
                        values=np.empty(0, dtype=np.float64),
                        axis_index=entry.axis_index,
                        entry_id=entry.entry_id,
                    )
                )
                continue
```

空スライス（:642-650）と通常（:676-684）の RenderCurve にも `entry_id=entry.entry_id` を追加。

- [ ] **Step 6: `inspect` に entry_id を追加**

`inspect`（:889-897）の plotted_signals dict に追記:

```python
            "plotted_signals": [
                {
                    "signal_key": e.signal_key,
                    "color": e.color,
                    "visible": e.visible,
                    "axis_index": e.axis_index,
                    "entry_id": e.entry_id,
                }
                for e in self._plotted
            ],
```

- [ ] **Step 7: テストが通ることを確認＋既存 VM テスト無回帰**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -v`
Expected: PASS（新規4本＋既存全て）

- [ ] **Step 8: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "feat(gui): GraphPanelVM に entry_id 基盤 (採番・RenderCurve 搬送・逆引き・PC-01)"
```

---

## Task 2: VM 操作 API（entry 単位の可視/色/削除＋軸一括切替）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`toggle_visibility` :486-493 の近くに追加。`_compact_axes` :360・`_invalidate_cache` :1002 を再利用）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Consumes: Task 1 の `_PlottedEntry.entry_id`
- Produces:
  - `toggle_entry_visibility(entry_id: int) -> None`
  - `set_color(entry_id: int, color: str) -> None`
  - `remove_entry(entry_id: int) -> None`
  - `toggle_axis_visibility(axis_index: int) -> None`
  - すべて `_invalidate_cache()`＋`_notify("signals")`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_toggle_entry_visibility_targets_only_that_entry(tmp_path: Path) -> None:
    # 同一 signal_key の 2 エントリのうち片方だけを不可視にできる (先頭一致の曖昧さを解消)
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = [s.name for s in session.signals()][0]
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.create_new_axis(key)
    e0, e1 = vm.inspect()["plotted_signals"]
    vm.toggle_entry_visibility(e1["entry_id"])
    vis = {e["entry_id"]: e["visible"] for e in vm.inspect()["plotted_signals"]}
    assert vis[e0["entry_id"]] is True
    assert vis[e1["entry_id"]] is False


def test_set_color_changes_only_target_and_busts_cache(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = [s.name for s in session.signals()][0]
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    eid = vm.inspect()["plotted_signals"][0]["entry_id"]
    vm.render_data()  # prime cache
    vm.set_color(eid, "#123456")
    # 色は cache_key に含まれない → invalidate されていないと古い色が返る
    curves = vm.render_data()
    assert curves[0].color == "#123456"
    assert vm.inspect()["plotted_signals"][0]["color"] == "#123456"


def test_remove_entry_removes_only_that_entry(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = [s.name for s in session.signals()][0]
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.create_new_axis(key)
    e0, e1 = vm.inspect()["plotted_signals"]
    vm.remove_entry(e0["entry_id"])
    remaining = vm.inspect()["plotted_signals"]
    assert len(remaining) == 1
    assert remaining[0]["entry_id"] == e1["entry_id"]


def test_toggle_axis_visibility_flips_all_on_axis(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    k0, k1 = [s.name for s in session.signals()][:2]
    vm = GraphPanelVM(session)
    vm.add_signal(k0)  # axis 0
    vm.add_signal(k1)  # axis 0 (同 axis)
    # 1 本でも可視 → 全非表示
    vm.toggle_axis_visibility(0)
    assert all(not e["visible"] for e in vm.inspect()["plotted_signals"])
    # 全非表示 → 全表示
    vm.toggle_axis_visibility(0)
    assert all(e["visible"] for e in vm.inspect()["plotted_signals"])


def test_toggle_axis_visibility_empty_axis_is_noop(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = [s.name for s in session.signals()][0]
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.toggle_axis_visibility(5)  # 存在しない axis
    assert vm.inspect()["plotted_signals"][0]["visible"] is True


def test_entry_ops_notify_signals(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = [s.name for s in session.signals()][0]
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    eid = vm.inspect()["plotted_signals"][0]["entry_id"]
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.toggle_entry_visibility(eid)
    vm.set_color(eid, "#abcdef")
    assert changes == ["signals", "signals"]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "entry_visibility or set_color or remove_entry or axis_visibility or entry_ops_notify" -v`
Expected: FAIL（各 API 未定義）

- [ ] **Step 3: 4 API を実装**

`toggle_visibility`（:486-493）の直後に追加:

```python
    def toggle_entry_visibility(self, entry_id: int) -> None:
        """Flip the visibility of the entry with *entry_id* (entry-addressed)."""
        for e in self._plotted:
            if e.entry_id == entry_id:
                e.visible = not e.visible
                break
        self._invalidate_cache()
        self._notify("signals")

    def set_color(self, entry_id: int, color: str) -> None:
        """Set the colour of the entry with *entry_id* and bust the render cache.

        Colour is intentionally NOT part of _make_cache_key, so the cache must be
        invalidated here or render_data would return the stale-coloured curve.
        """
        for e in self._plotted:
            if e.entry_id == entry_id:
                e.color = color
                break
        self._invalidate_cache()
        self._notify("signals")

    def remove_entry(self, entry_id: int) -> None:
        """Remove the entry with *entry_id* and reconcile axes (entry-addressed).

        Mirrors remove_signal but targets one entry: survivors keep their
        heights, the vacated axis band stays blank, and the panel collapses to a
        placeholder only when the last entry is removed (via _compact_axes).
        """
        self._plotted = [e for e in self._plotted if e.entry_id != entry_id]
        self._compact_axes()
        self._invalidate_cache()
        self._notify("signals")

    def toggle_axis_visibility(self, axis_index: int) -> None:
        """Flip visibility of all entries on *axis_index* (H fallback, DP5).

        If any entry on the axis is visible, hide them all; otherwise show them
        all. No-op when the axis has no entries.
        """
        on_axis = [e for e in self._plotted if e.axis_index == axis_index]
        if not on_axis:
            return
        any_visible = any(e.visible for e in on_axis)
        for e in on_axis:
            e.visible = not any_visible
        self._invalidate_cache()
        self._notify("signals")
```

- [ ] **Step 4: テスト pass ＋既存無回帰**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "feat(gui): GraphPanelVM に entry 単位の可視/色/削除＋軸一括切替 API (PC-01)"
```

---

## Task 3: View 内部辞書の entry_id 化（アクセサ・ヒットテスト・オフセットドラッグを一括移行）

**このタスクは atomic。** `_items` を entry_id キーへ移すと、signal_key で `_items` を引くオフセットドラッグと公開アクセサが同時に壊れるため、すべてを 1 コミットで移行する。曲線ドラッグの**タイミングは変えない**（DP16 は Task 4）。公開アクセサ（`curve_keys`/`curve_xy`/`pen_color`/`is_clipped`）を entry_id キーへ全面移行し、signal_key で曲線を指す既存 9 テストファイル（headless 4＋realgui 4＝計 8。VM テストは `RenderCurve.name` を見るだけで不変）を `entry_id_for`/`signal_keys_drawn` 経由へ同一コミットで更新して green に保つ。

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`__init__` :661-664,684・`refresh` :832-876・rebuild clear :1049-1050・公開アクセサ :1179-1193・`_curve_at` :1495-1545・オフセットドラッグ :1549-1642・`mousePressEvent` :1701-1704）
- Test: `tests/gui/test_graph_panel_view.py`

**Interfaces:**
- Consumes: Task 1 の `RenderCurve.entry_id`・`GraphPanelVM.signal_key_for_entry`
- Produces:
  - 内部: `_items: dict[int, PlotDataItem]`・`_item_vb: dict[int, ViewBox]`・`_item_signal_key: dict[int, str]`・`_offset_drag_key: int | None`
  - `_curve_at(pos) -> int | None`（entry_id を返す・内部専用）
  - 公開アクセサ（**entry_id キーへ全面移行**）: `curve_keys() -> list[int]`（entry_id 群）・`curve_xy(entry_id)`・`pen_color(entry_id)`・`is_clipped(entry_id)`・`pen_width(entry_id) -> float`
  - signal_key 解決ヘルパ（新設）: `entry_id_for(signal_key) -> int`（first-match）・`signal_keys_drawn() -> list[str]`（描画順・重複可）

- [ ] **Step 1: 失敗するテストを書く**（重複独立描画＋entry_id アクセサ＋signal_key 解決）

`tests/gui/test_graph_panel_view.py` に追記:

```python
    def test_duplicate_signal_key_draws_independent_curves(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        # 同一 signal_key を 2 axis に載せると 2 本独立に描画される (entry_id 化の核心)
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        vm.add_signal(key)
        vm.create_new_axis(key)

        # curve_keys は entry_id 群 (2 本ぶん・重複しない)
        assert len(view.curve_keys()) == 2  # type: ignore[attr-defined]
        assert len(set(view.curve_keys())) == 2  # type: ignore[attr-defined]
        # signal_keys_drawn は signal_key 群 (同名 2 本ぶん)
        assert view.signal_keys_drawn() == [key, key]  # type: ignore[attr-defined]
        # 各 entry のデータを独立に読める
        for eid in view.curve_keys():  # type: ignore[attr-defined]
            x, y = view.curve_xy(eid)  # type: ignore[attr-defined]
            assert len(x) > 0

    def test_set_color_on_one_entry_repaints_only_it(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        vm.create_new_axis(key)
        e0, e1 = view.curve_keys()  # type: ignore[attr-defined]
        vm.set_color(e1, "#123456")
        view.refresh()  # VM notify 経由でも呼ばれるが、テストは明示的に
        assert view.pen_color(e1).lower() == "#123456"  # type: ignore[attr-defined]
        assert view.pen_color(e0).lower() != "#123456"  # type: ignore[attr-defined]

    def test_entry_id_for_and_signal_keys_drawn(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=2)
        k0, k1 = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(k0)
        vm.add_signal(k1)
        assert set(view.signal_keys_drawn()) == {k0, k1}  # type: ignore[attr-defined]
        eid0 = view.entry_id_for(k0)  # type: ignore[attr-defined]
        assert view.signal_keys_drawn()[view.curve_keys().index(eid0)] == k0  # type: ignore[attr-defined]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "duplicate_signal_key or set_color_on_one_entry or entry_id_for" -v`
Expected: FAIL（`signal_keys_drawn`/`entry_id_for` 未定義・現状 `{c.name: c}` で同名衝突し 1 本に collapse）

- [ ] **Step 3: `__init__` の辞書を entry_id 型へ**

`__init__`（:661-664）:

```python
        # Curve items keyed by VM entry_id (a stable per-entry ID), NOT signal_key,
        # so the same signal on two axes draws as two independent items.
        self._items: dict[int, pg.PlotDataItem] = {}
        # Which ViewBox each entry's curve lives in (kept in sync by refresh).
        self._item_vb: dict[int, pg.ViewBox] = {}
        # entry_id -> signal_key, for legacy signal_key-addressed accessors and for
        # resolving the offset-apply target (offsets apply per signal, not per entry).
        self._item_signal_key: dict[int, str] = {}
```

`_offset_drag_key`（:684）:

```python
        self._offset_drag_key: int | None = None  # entry_id of the dragged curve
```

- [ ] **Step 4: `refresh` を entry_id キーへ**

`refresh`（:832-876）:

```python
        # 2. Get render curves from VM
        curves = self.vm.render_data()
        desired = {c.entry_id: c for c in curves}

        # 3. Drop curves no longer present
        for eid in list(self._items):
            if eid not in desired:
                item = self._items.pop(eid)
                self._item_vb.pop(eid, None)
                self._item_signal_key.pop(eid, None)
                for vb in self._view_boxes:
                    if item in vb.addedItems:
                        vb.removeItem(item)
                        break

        # 4. Add or update remaining curves
        for curve in curves:
            item = self._items.get(curve.entry_id)
            if item is None:
                item = pg.PlotDataItem(name=curve.name)
                self._items[curve.entry_id] = item

            item.setClipToView(False)
            target_vb = self._view_boxes[
                min(curve.axis_index, len(self._view_boxes) - 1)
            ]
            if item not in target_vb.addedItems:
                for vb in self._view_boxes:
                    if vb != target_vb and item in vb.addedItems:
                        vb.removeItem(item)
                target_vb.addItem(item)
            self._item_vb[curve.entry_id] = target_vb
            self._item_signal_key[curve.entry_id] = curve.name

            item.setData(curve.timestamps, curve.values)
            item.setPen(pg.mkPen(curve.color))

        # R14: if a curve was rebuilt mid-offset-drag, keep the preview consistent.
        if self._offset_drag_key is not None:
            if self._offset_drag_key not in self._items:
                self._cancel_offset_drag()
            elif self._offset_orig_xy is not None:
                orig_xs, orig_ys = self._offset_orig_xy
                self._items[self._offset_drag_key].setData(
                    orig_xs + self._offset_last_delta, orig_ys
                )
```

rebuild clear（:1049-1051）に `_item_signal_key` クリアを追加:

```python
        self._items.clear()  # Clear items to force re-adding to new ViewBoxes
        self._item_vb.clear()  # No stale ViewBox refs after rebuild (spec §R14)
        self._item_signal_key.clear()
```

- [ ] **Step 5: 公開アクセサを entry_id キーへ全面移行＋signal_key 解決ヘルパを新設**

公開アクセサ（:1179-1193）を差し替え:

```python
    def curve_keys(self) -> list[int]:
        """Return the entry_ids of the curves currently drawn, in draw order."""
        return list(self._items)

    def curve_xy(self, entry_id: int) -> tuple[object, object]:
        """Return the (x, y) arrays currently set on *entry_id*'s curve."""
        return self._items[entry_id].getData()

    def pen_color(self, entry_id: int) -> str:
        """Return the hex colour of *entry_id*'s curve pen (e.g. ``#1f77b4``)."""
        return pg.mkPen(self._items[entry_id].opts["pen"]).color().name()

    def pen_width(self, entry_id: int) -> float:
        """Return the pen width of *entry_id*'s curve (active curve = 2.5)."""
        return float(pg.mkPen(self._items[entry_id].opts["pen"]).widthF())

    def is_clipped(self, entry_id: int) -> bool:
        """Return whether *entry_id*'s curve is clipped to its ViewBox."""
        return bool(self._items[entry_id].opts.get("clipToView", False))

    # ── signal_key resolution helpers (drawn curves are entry_id-addressed) ──
    def entry_id_for(self, signal_key: str) -> int:
        """Resolve the first drawn entry_id with *signal_key* (raises KeyError if none).

        Curves are addressed by entry_id; callers that only know a signal_key
        (tests, signal-level membership) resolve through here.  First-match is
        exact when a signal_key is drawn once, which is the common case.
        """
        for eid, sk in self._item_signal_key.items():
            if sk == signal_key:
                return eid
        raise KeyError(signal_key)

    def signal_keys_drawn(self) -> list[str]:
        """Return the signal_keys of the drawn curves, in draw order (may repeat)."""
        return [self._item_signal_key[eid] for eid in self._items]
```

- [ ] **Step 6: `_curve_at` を entry_id 返却に**

`_curve_at`（:1495-1545）の型注釈と `_items` イテレーションを entry_id へ:

```python
    def _curve_at(self, pos: QPointF) -> int | None:
        """Return the entry_id of the nearest curve within CURVE_HIT_TOL_PX of *pos*.

        Returns None near a visible cursor line (cursor line > curve priority) or
        when no curve is close enough.  entry_id (not signal_key) so duplicate
        signals on different axes are distinguishable.
        """
        if not self._view_boxes or not self._items:
            return None
        # ... (cursor-line guard は現状のまま) ...

        best_key: int | None = None
        best_dist = CURVE_HIT_TOL_PX
        for eid, item in self._items.items():
            vb = self._item_vb.get(eid)
            if vb is None:
                continue
            # ... (距離計算は現状のまま。best_key = eid に代入) ...
                if dist <= best_dist:
                    best_dist = dist
                    best_key = eid
        return best_key
```

（`best_key: str | None` を `int | None` に、ループ変数 `key` を `eid` に、`best_key = key` を `best_key = eid` に。距離計算ロジックは不変。）

- [ ] **Step 7: オフセットドラッグを entry_id 化（タイミングは不変）**

`mousePressEvent` の ZONE_PLOT 分岐（:1701-1704）— `key` が entry_id になるだけ:

```python
            elif zone == ZONE_PLOT:
                eid = self._curve_at(event.position())
                if eid is not None:
                    self._begin_offset_drag(eid, event.position())
```

`_begin_offset_drag`（:1549-1569）— 引数を entry_id に、pen 色は item から直接読む（`self.pen_color(key)` は signal_key 用のため使わない）:

```python
    def _begin_offset_drag(self, entry_id: int, pos: QPointF) -> None:
        """Activate offset drag on *entry_id*: capture origin, highlight, set cursor."""
        start_x = self._data_value(pos, "x")
        if start_x is None:
            return
        item = self._items[entry_id]
        xs, ys = item.getData()
        self._offset_drag_key = entry_id
        self._offset_drag_start_x = start_x
        self._offset_orig_xy = (np.asarray(xs).copy(), np.asarray(ys).copy())
        self._offset_orig_pen = item.opts.get("pen")
        self._offset_last_delta = 0.0
        cur_color = pg.mkPen(item.opts["pen"]).color().name()
        item.setPen(pg.mkPen(cur_color, width=3))
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.grabMouse()
```

`_finish_offset`（:1600-1617）— entry_id→signal_key 解決して emit:

```python
    def _finish_offset(self, entry_id: int, delta_t: float) -> None:
        """Show the apply dialog and emit / cancel based on the chosen scope."""
        if entry_id not in self._items:
            self._reset_offset_state()
            return
        signal_key = self._item_signal_key.get(entry_id)
        if signal_key is None:
            self._reset_offset_state()
            return
        fn = self._apply_dialog_fn or self._default_apply_dialog
        scope = fn(signal_key, delta_t)
        if scope in ("signal", "group"):
            self._reset_offset_state(restore_data=False)
            self.offset_apply_requested.emit(signal_key, delta_t, scope)
        else:
            self._cancel_offset_drag()
```

`_update_offset_preview`（:1571-1584）・`_reset_offset_state`（:1623-1642）は `key = self._offset_drag_key`（int になった）を `self._items[key]` で引くだけなので**ロジック不変**（`key in self._items` の型が int になるだけ）。`_end_offset_drag`（:1586-1598）の `QTimer.singleShot(0, lambda: self._finish_offset(key, delta_t))` も `key` が entry_id になるだけで不変。

- [ ] **Step 8: signal_key を渡す既存 8 テストファイルを entry_id 解決へ移行**

公開アクセサが entry_id を受け取るようになったため、`curve_keys`/`curve_xy`/`pen_color`/`is_clipped` に signal_key を直接渡している既存テストを機械的に更新する（**同一コミット内**。監査済みの箇所）。変換ルール:

- `key in view.curve_keys()` / `key not in view.curve_keys()` → `view.signal_keys_drawn()` に置換
- `set(view.curve_keys()) == {...}` → `set(view.signal_keys_drawn()) == {...}`
- `view.curve_xy(key)` → `view.curve_xy(view.entry_id_for(key))`
- `view.pen_color(key)` → `view.pen_color(view.entry_id_for(key))`
- `view.is_clipped(key)` → `view.is_clipped(view.entry_id_for(key))`

対象ファイルと箇所（監査値）:
- headless: `tests/gui/test_graph_panel_view.py`（curve_keys: :87,112,123,135,164,192／curve_xy: :88,165／pen_color: :101／is_clipped: :146。:132 は view 経由 toggle 後の curve_keys）／`tests/gui/test_dnd_workflow.py`（curve_keys: :131）／`tests/gui/test_graph_panel_offset_drag.py`（curve_xy: :70,72,99,105,112,118）／`tests/gui/test_graph_area_offset_wiring.py`（curve_xy: :62,76,117,137,138）
- realgui（`--realgui` gate のため headless では skip・lint/型は走る）: `tests/realgui/test_active_panel_flow.py`（:228）／`tests/realgui/test_cross_panel_axis_realclick.py`（:181,198,203）／`tests/realgui/test_signal_dnd_realclick.py`（:156,173,225,226,262,301,342）／`tests/realgui/test_offset_drag.py`（curve_xy: :123,124,161,162）

注: `tests/gui/test_graph_panel_vm.py` は `RenderCurve.name`（不変）と VM の `toggle_visibility`（signal_key・不変）を見るだけなので**更新不要**。

- [ ] **Step 9: headless 全体で無回帰（realgui は skip されるが view/dnd/offset は走る）**

Run: `uv run pytest tests/gui/test_graph_panel_view.py tests/gui/test_graph_panel_offset_drag.py tests/gui/test_graph_area_offset_wiring.py tests/gui/test_dnd_workflow.py -v`
Expected: PASS（新規3本＋移行済み既存すべて）

- [ ] **Step 10: mypy＋ruff（辞書型変更と移行に追随。realgui ファイルも lint/型対象）**

Run: `uv run mypy src/valisync/gui/views/graph_panel_view.py && uv run ruff check src/valisync/gui/views/graph_panel_view.py tests/realgui/`
Expected: Success / All checks passed

- [ ] **Step 11: コミット（realgui のアサート更新も同一コミット）**

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_view.py \
  tests/gui/test_dnd_workflow.py tests/gui/test_graph_panel_offset_drag.py \
  tests/gui/test_graph_area_offset_wiring.py tests/realgui/test_active_panel_flow.py \
  tests/realgui/test_cross_panel_axis_realclick.py tests/realgui/test_signal_dnd_realclick.py \
  tests/realgui/test_offset_drag.py
git commit -m "refactor(gui): GraphPanelView アクセサを entry_id キーへ全面移行＋既存テスト解決更新 (PC-01)"
```

> **realgui の①ゲート**: アサートを更新した realgui 4 ファイルは headless では skip される。DP16 変更（Task 4）とあわせ **Task 8 で `--realgui` 再実行**して無回帰を実機実証する（アサート更新だけで挙動不変だが、キー型変更が実クリック経路に効いていないことを証拠化）。

---

## Task 4: DP16 ジェスチャ＋曲線活性化（太線化・軸連動・解除）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`__init__` に活性化状態・`refresh` の setPen に active 幅・`mousePressEvent` :1691-1705・`mouseMoveEvent` :1732-1739・`mouseReleaseEvent` :1741-1755・`_AlignedAxisItem.mouseClickEvent` :448-465・`set_active_axis` :1138-1150 は不変再利用）
- Test: `tests/gui/test_graph_panel_view.py`

**Interfaces:**
- Consumes: Task 3 の `_curve_at -> int`・`curve_keys`（entry_id 群）・`pen_width`・`GraphPanelVM.axis_of_entry`
- Produces:
  - 内部: `_active_curve_id: int | None`・`_curve_press_candidate: tuple[int, QPointF] | None`
  - `_activate_curve(entry_id: int) -> None`・`_deactivate_curve() -> None`
  - `active_curve_id() -> int | None`（テスト観測用）

- [ ] **Step 1: 失敗するテストを書く**（合成 press/move/release で候補→閾値→分岐・太線）

pytest-qt の合成入力で DP16 分岐を検証。閾値内クリック=活性化（太線・オフセット不変）、閾値超え=オフセットドラッグ開始。座標は曲線が確実に載る点を `_curve_at` で逆算するのは難しいため、**曲線ヒットは `_curve_at` をスタブせず、実データ点近傍を狙う**。堅牢化のため、テストは「候補保持後の release で活性化」「move で閾値超え後にドラッグ開始」をハンドラ経由で検証する:

```python
    def test_click_on_curve_activates_it_thick_pen(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtGui import QMouseEvent

        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        view.resize(400, 300)
        vm.add_signal(key)
        vm.set_x_range(0.0, 1.0)
        view.refresh()
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]

        # 曲線上の一点を狙う: entry の描画データからビュー座標→ウィジェット座標を得る
        x, y = view.curve_xy(eid)  # type: ignore[attr-defined]
        vb = view._item_vb[eid]  # type: ignore[attr-defined]
        mid = len(x) // 2
        scene_pt = vb.mapViewToScene(QPointF(float(x[mid]), float(y[mid])))
        wpt = view.plot_widget.mapFromScene(scene_pt)  # type: ignore[attr-defined]
        pos = QPointF(view.plot_widget.mapTo(view, wpt))  # type: ignore[attr-defined]

        def _press(p: QPointF) -> QMouseEvent:
            return QMouseEvent(
                QEvent.Type.MouseButtonPress, p, view.mapToGlobal(p.toPoint()),
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

        def _release(p: QPointF) -> QMouseEvent:
            return QMouseEvent(
                QEvent.Type.MouseButtonRelease, p, view.mapToGlobal(p.toPoint()),
                Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )

        view.mousePressEvent(_press(pos))
        view.mouseReleaseEvent(_release(pos))  # 閾値内 → 活性化

        assert view.active_curve_id() == eid  # type: ignore[attr-defined]
        assert view.pen_width(eid) == 2.5  # type: ignore[attr-defined]

    def test_click_within_threshold_does_not_offset(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        # 閾値内クリックは curve_xy を変えない (活性化のみ・オフセットは発生しない)
        # （セットアップは上と同様に pos/eid を得る。x 配列を前後で比較）
        ...  # 上と同じセットアップ
        before = np.asarray(view.curve_xy(eid)[0]).copy()  # type: ignore[attr-defined]
        view.mousePressEvent(_press(pos))
        view.mouseReleaseEvent(_release(pos))
        after = np.asarray(view.curve_xy(eid)[0])  # type: ignore[attr-defined]
        assert np.array_equal(before, after)

    def test_axis_click_deactivates_curve(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        # 曲線活性化中に軸クリック → 曲線は非活性へ (§2 解除規則)
        ...  # 曲線を活性化後
        view._active_curve_id = eid  # type: ignore[attr-defined]
        view._deactivate_curve()  # 軸クリック経路がこれを呼ぶ
        assert view.active_curve_id() is None  # type: ignore[attr-defined]
```

（`test_click_within_threshold_does_not_offset` と `test_axis_click_deactivates_curve` は上のセットアップ（pos/eid/_press/_release 定義）を各テスト内に展開する。No Placeholders 方針に従い、実装時は上のブロックをコピーして冒頭に置く。）

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "activates_it_thick or within_threshold or axis_click_deactivates" -v`
Expected: FAIL（`active_curve_id`/`_deactivate_curve` 未定義・現状は press で即オフセットドラッグ開始し活性化しない）

- [ ] **Step 3: 活性化状態を `__init__` に追加**

`_active_axis_index`/`_hover_axis_index` の宣言（:694-695）の近くに:

```python
        # Active curve (entry_id) — transient View state, drives thick-pen feedback.
        self._active_curve_id: int | None = None
        # DP16: candidate captured on a curve press until the drag threshold is
        # crossed (entry_id, press position).  None when no candidate is pending.
        self._curve_press_candidate: tuple[int, QPointF] | None = None
```

- [ ] **Step 4: 活性化/解除ヘルパ＋観測アクセサを実装**

`set_active_axis`（:1138）の近くに:

```python
    def active_curve_id(self) -> int | None:
        """Return the currently active curve's entry_id (None if none)."""
        return self._active_curve_id

    def _activate_curve(self, entry_id: int) -> None:
        """Make *entry_id* the active curve: thick pen + activate its axis too.

        Per spec §2 the curve's axis is activated alongside so the amber frame
        and the thick curve always point at the same axis.  refresh() is the
        authoritative re-pen (applies width 2.5 to the active entry).
        """
        self._active_curve_id = entry_id
        axis = self.vm.axis_of_entry(entry_id)
        if axis is not None:
            self.set_active_axis(axis)
        self.refresh()

    def _deactivate_curve(self) -> None:
        """Clear the active curve (another target was clicked) and un-thicken it."""
        if self._active_curve_id is None:
            return
        self._active_curve_id = None
        self.refresh()
```

- [ ] **Step 5: `refresh` の setPen に active 幅を反映**

Task 3 で書いた `item.setPen(pg.mkPen(curve.color))`（refresh の step 4 相当）を差し替え:

```python
            item.setData(curve.timestamps, curve.values)
            width = 2.5 if curve.entry_id == self._active_curve_id else 1.0
            item.setPen(pg.mkPen(curve.color, width=width))
```

- [ ] **Step 6: `mousePressEvent` を DP16 候補保持に**

`mousePressEvent`（:1691-1705）:

```python
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activate_requested.emit()  # PC-07: どのゾーンでも押下=活性化
            zone = self._zone_at(event.position())
            if zone in (ZONE_X_INNER, ZONE_X_OUTER):
                self._deactivate_curve()  # X ゾーンは別対象 → 曲線解除
                self._drag_zone = zone
                self._drag_start = event.position()
            elif zone == ZONE_PLOT:
                eid = self._curve_at(event.position())
                if eid is not None:
                    # DP16: press では即ドラッグ開始せず候補として保持。move が
                    # startDragDistance を超えたらオフセットドラッグへ昇格、
                    # 閾値内 release なら活性化。押下中の move は子 QGraphicsView に
                    # 消費されるため、ここで grabMouse を取る (release/escape で解放)。
                    self._curve_press_candidate = (eid, event.position())
                    self.grabMouse()
                else:
                    self._deactivate_curve()  # 空プロットクリック → 曲線解除
            else:
                self._deactivate_curve()
        super().mousePressEvent(event)
```

- [ ] **Step 7: `mouseMoveEvent` に閾値昇格を追加**

`mouseMoveEvent`（:1732-1739）の先頭に候補処理を挿入。`QApplication` の import を確認（ファイル冒頭に無ければ追加）:

```python
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._curve_press_candidate is not None:
            eid, start = self._curve_press_candidate
            moved = (event.position() - start).manhattanLength()
            if moved >= QApplication.startDragDistance():
                self._curve_press_candidate = None  # 昇格したら候補は破棄
                self._begin_offset_drag(eid, start)
                self._update_offset_preview(
                    event.position(), event.globalPosition()
                )
            super().mouseMoveEvent(event)
            return
        if self._offset_drag_key is not None:
            self._update_offset_preview(event.position(), event.globalPosition())
            super().mouseMoveEvent(event)
            return
        if self._drag_zone is None:
            self.setCursor(cursor(self._hover_cursor(event.position())))
        super().mouseMoveEvent(event)
```

- [ ] **Step 8: `mouseReleaseEvent` に活性化を追加**

`mouseReleaseEvent`（:1741-1755）の先頭に候補 release 処理を挿入:

```python
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._curve_press_candidate is not None:
            eid, _ = self._curve_press_candidate
            self._curve_press_candidate = None
            self.releaseMouse()  # press で取った grab を解放
            self._activate_curve(eid)  # 閾値内 → 活性化
            super().mouseReleaseEvent(event)
            return
        if self._offset_drag_key is not None:
            self._end_offset_drag()
            super().mouseReleaseEvent(event)
            return
        if self._drag_zone is not None and self._drag_start is not None:
            axis = "x"
            start = self._data_value(self._drag_start, axis)
            end = self._data_value(event.position(), axis)
            if start is not None and end is not None:
                self.apply_zone_drag(self._drag_zone, start, end)
        self._drag_zone = None
        self._drag_start = None
        super().mouseReleaseEvent(event)
```

- [ ] **Step 9: Escape で候補もキャンセル**

`keyPressEvent`（:1757-1762）の Escape 分岐を拡張（H は Task 5）:

```python
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._curve_press_candidate is not None:
                self._curve_press_candidate = None
                self.releaseMouse()
                event.accept()
                return
            if self._offset_drag_key is not None:
                self._cancel_offset_drag()
                event.accept()
                return
        super().keyPressEvent(event)
```

- [ ] **Step 10: 軸クリックで曲線を解除**

`_AlignedAxisItem.mouseClickEvent`（:448-465）に曲線解除を追加（`set_active_axis` の後）:

```python
        if self._panel_view is not None and self._vm_axis_index is not None:
            self._panel_view.set_active_axis(self._vm_axis_index)
            self._panel_view._deactivate_curve()  # 軸クリックは別対象 → 曲線解除
        self._emit_panel_activation()
        ev.accept()
```

- [ ] **Step 11: テスト pass ＋既存無回帰（特にオフセットドラッグ）**

Run: `uv run pytest tests/gui/test_graph_panel_view.py tests/gui/test_graph_panel_offset_drag.py tests/gui/test_graph_area_offset_wiring.py -v`
Expected: PASS（新規＋既存すべて）

> **注記（レビュー観点）**: 既存 `test_graph_panel_offset_drag.py` は press→move→release を合成 sendEvent で駆動する。DP16 で press が即ドラッグ開始しなくなったため、これらのテストが「press 後に move してオフセットが動く」経路をハンドラ経由で通しているなら green のまま、「press だけでオフセット開始」を前提にしているなら要更新。**実装時にこれらのテストを読み、DP16 の候補→昇格経路に整合するよう必要なら更新**（合成 move が startDragDistance を超えるよう座標を調整）。挙動変更に伴うテスト更新は spec §11・memory `gui_behavior_change_stale_parallel_realgui_test` に沿う。

- [ ] **Step 12: mypy ＋コミット**

Run: `uv run mypy src/valisync/gui/views/graph_panel_view.py`
Expected: Success

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_view.py tests/gui/test_graph_panel_offset_drag.py
git commit -m "feat(gui): DP16 ジェスチャ＋曲線活性化 (閾値内クリック=活性化/太線・閾値超え=オフセット・PC-01)"
```

---

## Task 5: H キー（曲線表示切替→軸フォールバック）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`keyPressEvent` :1757-1762）
- Test: `tests/gui/test_graph_panel_view.py`

**Interfaces:**
- Consumes: Task 2 の `toggle_entry_visibility`/`toggle_axis_visibility`・Task 1 の `signal_key_for_entry`・Task 4 の `_active_curve_id`
- Produces: `keyPressEvent` の Key_H 分岐

- [ ] **Step 1: 失敗するテストを書く**

`qtbot.keyClick` で H を送る。ClickFocus 前提のため `view.setFocus()` を明示:

```python
    def test_h_toggles_active_curve_visibility(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        view.refresh()
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        view._active_curve_id = eid  # type: ignore[attr-defined]  # 活性化済みとする
        view.setFocus()

        qtbot.keyClick(view, Qt.Key.Key_H)
        assert vm.inspect()["plotted_signals"][0]["visible"] is False
        # H は解除トリガーにしない → 非表示後も active のまま再表示できる
        assert view.active_curve_id() == eid  # type: ignore[attr-defined]
        qtbot.keyClick(view, Qt.Key.Key_H)
        assert vm.inspect()["plotted_signals"][0]["visible"] is True

    def test_h_falls_back_to_axis_when_no_active_curve(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=2)
        k0, k1 = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(k0)  # axis 0
        vm.add_signal(k1)  # axis 0
        view.refresh()
        view._active_curve_id = None  # type: ignore[attr-defined]
        view.set_active_axis(0)
        view.setFocus()

        qtbot.keyClick(view, Qt.Key.Key_H)
        assert all(not e["visible"] for e in vm.inspect()["plotted_signals"])
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "h_toggles_active or h_falls_back" -v`
Expected: FAIL（H 未処理）

- [ ] **Step 3: `keyPressEvent` に H 分岐を実装**

Task 4 で拡張した `keyPressEvent` に H を追加:

```python
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._curve_press_candidate is not None:
                self._curve_press_candidate = None
                self.releaseMouse()
                event.accept()
                return
            if self._offset_drag_key is not None:
                self._cancel_offset_drag()
                event.accept()
                return
        if event.key() == Qt.Key.Key_H:
            aid = self._active_curve_id
            # active curve が非表示中でも entry として存在すれば再表示できる
            # (非表示曲線はクリック不可のため H の対象として維持する・§10)。
            if aid is not None and self.vm.signal_key_for_entry(aid) is not None:
                self.vm.toggle_entry_visibility(aid)
            elif self._active_axis_index is not None:
                self.vm.toggle_axis_visibility(self._active_axis_index)
            event.accept()
            return
        super().keyPressEvent(event)
```

- [ ] **Step 4: テスト pass**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "h_toggles_active or h_falls_back" -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_view.py
git commit -m "feat(gui): H キーで曲線表示切替→軸フォールバック (PC-01/DP5)"
```

---

## Task 6: 右クリックルーティング＋曲線メニュー（非表示/色変更/削除・色ダイアログ DI）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`__init__` に `color_dialog_fn` DI・`contextMenuEvent` :1950-1951・`build_curve_menu` 新設・`_PALETTE` import・QtGui import）
- Test: `tests/gui/test_graph_panel_view.py`

**Interfaces:**
- Consumes: Task 2 の `toggle_entry_visibility`/`set_color`/`remove_entry`・Task 3 の `_curve_at -> int`・Task 4 の `_active_curve_id`
- Produces:
  - `__init__(vm, parent=None, apply_dialog_fn=None, color_dialog_fn=None)`（`color_dialog_fn: Callable[[], str | None] | None`）
  - `build_curve_menu(entry_id: int) -> QMenu`
  - `contextMenuEvent` の曲線→空白ルーティング

- [ ] **Step 1: 失敗するテストを書く**（ルーティング＋各項目 emit・色 DI スタブ）

```python
    def test_right_click_on_curve_shows_curve_menu(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        # 曲線位置の右クリックで曲線メニューが構築される (ルーティング検証)
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        view.refresh()
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        labels = [a.text() for a in menu.actions() if a.text()]
        assert "非表示" in labels
        assert "削除" in labels
        assert any("色変更" in a.text() for a in menu.actions())

    def test_curve_menu_hide_toggles_visibility(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        ...  # eid まで上と同じ
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        hide = next(a for a in menu.actions() if a.text() == "非表示")
        hide.trigger()
        assert vm.inspect()["plotted_signals"][0]["visible"] is False

    def test_curve_menu_delete_removes_entry(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        ...  # eid まで上と同じ
        view._active_curve_id = eid  # type: ignore[attr-defined]
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        delete = next(a for a in menu.actions() if a.text() == "削除")
        delete.trigger()
        assert vm.inspect()["plotted_signals"] == []
        assert view.active_curve_id() is None  # type: ignore[attr-defined]  # 削除で解除

    def test_curve_menu_custom_color_uses_injected_dialog(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = GraphPanelView(vm, color_dialog_fn=lambda: "#0a0b0c")
        qtbot.addWidget(view)
        vm.add_signal(key)
        view.refresh()
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        color_menu = next(
            a.menu() for a in menu.actions() if "色変更" in a.text()
        )
        other = next(a for a in color_menu.actions() if a.text() == "その他…")
        other.trigger()
        assert vm.inspect()["plotted_signals"][0]["color"] == "#0a0b0c"

    def test_context_menu_routing_curve_vs_blank(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        # 空白位置は既存パネルメニュー (Add Panel 等) が出る = 非曲線ルート
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        view.refresh()
        # _curve_at が None を返す点 (曲線から十分離れた原点近傍) では
        # build_context_menu (パネル) が使われる = "Add Panel" を含む
        panel_menu = view.build_context_menu()
        assert any(a.text() == "Add Panel" for a in panel_menu.actions())
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "curve_menu or right_click_on_curve or context_menu_routing" -v`
Expected: FAIL（`build_curve_menu`/`color_dialog_fn` 未定義）

- [ ] **Step 3: QtGui import と `_PALETTE` import を確認/追加**

ファイル冒頭の import に（既存に無ければ）追加:

```python
from PySide6.QtGui import QColor, QIcon, QPixmap
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM, _PALETTE
```

（`GraphPanelVM` は既存 import 済み。`_PALETTE` を同 import 行に足す。QColor/QIcon/QPixmap が既存 QtGui import に無ければ追加。）

- [ ] **Step 4: `color_dialog_fn` DI を `__init__` に追加**

`__init__`（:652-660）のシグネチャと本体:

```python
    def __init__(
        self,
        vm: GraphPanelVM,
        parent: QWidget | None = None,
        apply_dialog_fn: Callable[[str, float], str | None] | None = None,
        color_dialog_fn: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.vm = vm
        self._apply_dialog_fn = apply_dialog_fn
        self._color_dialog_fn = color_dialog_fn or self._default_color_dialog
```

- [ ] **Step 5: `build_curve_menu` と色ダイアログ既定・削除ヘルパを実装**

`build_context_menu`（:1913）の直前に:

```python
    def _default_color_dialog(self) -> str | None:
        """Native colour picker (DI default). Returns hex or None on cancel."""
        from PySide6.QtWidgets import QColorDialog

        col = QColorDialog.getColor(parent=self)
        return col.name() if col.isValid() else None

    def _color_icon(self, hex_color: str) -> QIcon:
        """A 16x16 solid-colour swatch icon for a palette menu entry."""
        pix = QPixmap(16, 16)
        pix.fill(QColor(hex_color))
        return QIcon(pix)

    def _remove_curve(self, entry_id: int) -> None:
        """Delete a curve; clear active state if it was the active one."""
        if entry_id == self._active_curve_id:
            self._active_curve_id = None
        self.vm.remove_entry(entry_id)

    def _pick_custom_color(self, entry_id: int) -> None:
        """Open the injected colour dialog; apply the chosen colour if any."""
        hex_color = self._color_dialog_fn()
        if hex_color:
            self.vm.set_color(entry_id, hex_color)

    def build_curve_menu(self, entry_id: int) -> QMenu:
        """Right-click menu for one curve (PC-01: 非表示/色変更/削除).

        The axis-move and offset items (spec §4.3) are added in 增分2b.
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
        menu.addSeparator()
        menu.addAction("削除").triggered.connect(
            lambda *_: self._remove_curve(entry_id)
        )
        return menu
```

- [ ] **Step 6: `contextMenuEvent` を曲線→空白ルーティングに**

`contextMenuEvent`（:1950-1951）:

```python
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        # ルーティング優先順 (spec §4.3): 曲線 → 空白 (パネル)。
        # 軸分岐は 增分2b、カーソル線分岐は 增分3 で先頭に差し込む。
        pos = QPointF(event.pos())
        eid = self._curve_at(pos)
        if eid is not None:
            self.build_curve_menu(eid).exec(event.globalPos())
            return
        self.build_context_menu().exec(event.globalPos())
```

- [ ] **Step 7: テスト pass ＋既存 context-menu テスト無回帰**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -v`
Expected: PASS

- [ ] **Step 8: mypy ＋コミット**

Run: `uv run mypy src/valisync/gui/views/graph_panel_view.py`
Expected: Success

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_view.py
git commit -m "feat(gui): 曲線右クリックメニュー (非表示/色変更/削除)＋ルーティング骨格・色ダイアログ DI (PC-01)"
```

---

## Task 7: 死蔵コード削除（PC-05 吸収）

監査済み: 対象6シンボルはテスト参照ゼロ。削除は production のみ・テスト改変ゼロ。

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`（`_hidden` :62・`SignalItem.visible` :27,97・`toggle_visibility` :168-174・`is_visible` :176-178・`visible_signal_keys` :180-190）
- Modify: `src/valisync/gui/views/channel_browser_view.py`（`toggle_visibility_for_selection` :176-179）
- Test: 既存テストの green 維持のみ（新規なし）

**Interfaces:** なし（削除のみ）

- [ ] **Step 1: 削除前に既存テスト green を確認（ベースライン）**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py tests/gui/test_channel_browser_view.py -q`
Expected: PASS（削除後も同じであることの基準）

- [ ] **Step 2: `SignalItem.visible` フィールドと算出を削除**

`SignalItem`（:20-28）から `visible` を削除:

```python
@dataclass(frozen=True)
class SignalItem:
    """Represents a single signal entry in the browser list."""

    name: str  # Original name, e.g. "speed"
    unit: str  # Physical unit, e.g. "km/h"
    key: str  # Full namespaced key, e.g. "csv_1::speed"
    tooltip: str = ""  # value_labels のラベル行 (LD-07・空=ツールチップなし)
```

`signals` プロパティの `SignalItem(...)` 構築（:92-100）から `visible=...` を削除:

```python
            results.append(
                SignalItem(
                    name=orig_name,
                    unit=str(unit),
                    key=sig.name,
                    tooltip=_labels_tooltip(sig.metadata),
                )
            )
```

- [ ] **Step 3: `_hidden` と可視性メソッド群を削除**

`__init__` から `self._hidden: set[str] = set()`（:61-62 のコメント含む）を削除。`# ─── Visibility` セクション（:166-190）の `toggle_visibility`/`is_visible`/`visible_signal_keys` を丸ごと削除。

- [ ] **Step 4: View の死蔵メソッドを削除**

`channel_browser_view.py` の `toggle_visibility_for_selection`（:176-179）を削除。

- [ ] **Step 5: 既存テスト green 維持＋lint/型（未使用 import 掃除）**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py tests/gui/test_channel_browser_view.py -q`
Expected: PASS（Step 1 と同じ結果）

Run: `uv run ruff check src/valisync/gui/viewmodels/channel_browser_vm.py src/valisync/gui/views/channel_browser_view.py && uv run mypy src/valisync/gui/viewmodels/channel_browser_vm.py`
Expected: All checks passed / Success（`set` の未使用 import 等があれば掃除）

- [ ] **Step 6: コミット**

```bash
git add src/valisync/gui/viewmodels/channel_browser_vm.py src/valisync/gui/views/channel_browser_view.py
git commit -m "refactor(gui): ChannelBrowser の死蔵可視性コードを削除 (PC-05 を PC-01 に吸収)"
```

---

## Task 8: realgui 証拠（Layer C・実クリック活性化／H／右クリックメニュー＋オフセット無回帰）

**Files:**
- Create: `tests/realgui/test_curve_direct_ops.py`
- 参照（無回帰・書き換えなし）: `tests/realgui/test_offset_drag.py`

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input.py`（`at()` 実 OS クリック・キー入力・スクショ）、`tests/realgui/conftest.py`（QSettings 隔離）。既存 realgui（`test_active_panel_flow.py` 等）の起動・パネル取得パターンを踏襲。

- [ ] **Step 1: 対応 realgui のマッピングと駆動レシピ確認**

`docs/gui-testing-layers.md` と `.claude/skills/gui-verify/reference/realgui-recipe.md` を読み、`_realgui_input` の実クリック・実キー・スクショ AI 判定ヘルパの現行 API を確認。既存 `tests/realgui/test_offset_drag.py` の実ドラッグ駆動（別 OS スレッド＋watchdog・memory `gui_realgui_drag_qtimer_hang`）を再利用パターンとして把握。

- [ ] **Step 2: 曲線実クリック活性化＋実 H の realgui を書く**

`test_curve_direct_ops.py` に、実起動→信号を1本プロット→曲線上を実クリック→活性化（太線）のスクショ→実 H キーで非表示→再表示、を閉ループで検証。曲線ヒット座標は `curve_xy`＋`plot_widget.mapFromScene` で算出（memory `gui_realgui_zone_widgetspace_and_offscreen_clamp` の widget 空間座標算出）。活性化の視覚確定はスクショ AI 判定、状態確定は `view.active_curve_id()`＋`pen_width`。

- [ ] **Step 3: 曲線実右クリックメニュー実行の realgui を書く**

実右クリック→メニュー表示スクショ→「非表示」を実クリック→曲線が消えることを確認。QColorDialog はネイティブモーダルのため `color_dialog_fn` をテスト用スタブに差し替えて起動（realgui でネイティブモーダルを駆動しない・memory `gui_realgui_qaction_slot_patch_before_construction` の構築前 patch）。

- [ ] **Step 4: DP16 のオフセット無回帰を確認**

`uv run pytest --realgui tests/realgui/test_offset_drag.py -v` を実行。閾値超え実ドラッグでオフセットが適用されること（`curve_xy` の x 配列がシフト）を確認。DP16 変更で press 直後にドラッグが始まらなくなったため、既存 realgui が「press→即ドラッグ」を前提にしているなら実装時に閾値超え move を確実に含む駆動へ調整。あわせて「閾値内クリック=活性化（オフセット非発生）」を1ケース追加。

- [ ] **Step 5: 挙動変更に伴う stale テスト掃除**

`tests/` 全体を grep し、オフセットドラッグ開始タイミング（旧「press で即開始」）を前提にした Layer B / 並行 realgui のアサートが残っていないか確認・是正（memory `gui_behavior_change_stale_parallel_realgui_test`）。

- [ ] **Step 6: scoped realgui 実行＋証拠添付**

Run: `uv run pytest --realgui tests/realgui/test_curve_direct_ops.py tests/realgui/test_offset_drag.py -v`
Expected: PASS＋スクショ（活性化太線・右クリックメニュー・オフセット適用）

- [ ] **Step 7: コミット**

```bash
git add tests/realgui/test_curve_direct_ops.py
git commit -m "test(realgui): 曲線の実クリック活性化/H/右クリックメニュー＋DP16 オフセット無回帰 (Layer C・PC-01)"
```

---

## Self-Review（プラン→spec の突き合わせ）

**1. spec カバレッジ（増分2a スコープ = PC-01/PC-05）:**
- §4.2 entry_id 指名: Task 1（採番・搬送・逆引き）＋Task 3（View 再キー化・重複独立描画）✓
- §4.2 新 API `toggle_entry_visibility`/`set_color`/`remove_entry`: Task 2 ✓。色変更の cache invalidate: Task 2 で明記＋テスト ✓
- §7 曲線アクティブ化＋太線化: Task 4 ✓
- §7 DP16 ジェスチャ（press 候補＋grabMouse-at-press＋閾値）: Task 4 ✓
- §4.4 H キー（曲線→軸フォールバック）: Task 5 ✓（軸一括 `toggle_axis_visibility` は Task 2）
- §4.3 右クリックルーティング骨格（曲線→空白・軸/カーソルは後続増分で差込）＋`build_curve_menu`（非表示/色変更▸/削除）: Task 6 ✓。色ダイアログ DI ✓
- §2 解除規則（軸・空白・他曲線で解除／H は非解除／曲線活性化は軸も活性化）: Task 4（`_deactivate_curve` 呼び出し点）＋Task 5（H 非解除）✓
- 死蔵削除（PC-05 吸収）: Task 7 ✓
- §11 Layer A/B/C＋①ゲート: gui-test-plan 分析ブロック＋Task 8 ✓
- **増分2b へ後送り（本プラン外・意図的）**: 軸右クリックメニュー・`entries_on_axis`/`reset_axis_y`/`remove_axis`/`move_entry_to_new_axis`・「新しい軸へ移動」曲線項目・オフセット起動/リセット導線（`reset_offset`・数値ダイアログ）・オフセット情報行・PC-03 の起動導線/状態可視化。§4.3 の `build_curve_menu` フル項目（新しい軸へ移動・時間オフセット…・リセット…・情報行）も 2b で追加。

**2. Placeholder スキャン:** Task 4 のテスト2本（`test_click_within_threshold_does_not_offset`・`test_axis_click_deactivates_curve`）は共通セットアップを `...` で省略しているが、直前のテストからコピーする旨を明記（実装時に展開）。それ以外に TBD/「適切に処理」等の曖昧記述なし。全 code step に実コードあり。

**3. 型整合:** `entry_id: int` を VM（`_PlottedEntry`/`RenderCurve`）→View（`_items: dict[int,...]`/`_curve_at -> int | None`/`_offset_drag_key: int | None`）で一貫。公開アクセサ（`curve_keys -> list[int]`・`curve_xy`/`pen_color`/`pen_width`/`is_clipped` は `entry_id: int` 引数）と signal_key 解決ヘルパ（`entry_id_for -> int`・`signal_keys_drawn -> list[str]`）が Task 4/5/6/8 の消費側と一致。`signal_key_for_entry -> str | None`・`axis_of_entry -> int | None`・`color_dialog_fn: Callable[[], str | None]` も各消費側と一致。

**4. 既知の罠への対応（memory）:** grabMouse-at-press（`gui_realgui_move_not_reaching_parent_qwidget`）＝Task 4 で press 時取得を明記／挙動変更の stale テスト（`gui_behavior_change_stale_parallel_realgui_test`）＝Task 4 Step 11・Task 8 Step 5／overlay 原点非破壊（`gui_panel_chrome_layout_row_shifts_hittest_origin`）＝`_curve_at` の widget↔plot_widget 座標系は増分1 で plot_widget.pos()==(0,0) 保証済みを前提に利用。

---

## Execution Handoff

Plan complete。増分2b（PC-06/PC-03）は本プラン merge 後に別途 writing-plans → subagent-driven で。
