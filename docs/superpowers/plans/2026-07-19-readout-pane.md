# カーソル読み値の常設ペイン化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** カーソル読み値を「パネルごとのフロートチップ」から「GraphAreaView 右ペインの常設テーブル（アクティブパネル束縛・表示/非表示トグル）」へ進化させ、行クリックで該当波形をハイライトする。

**Architecture:** 既存 `CursorReadout` を進化（フロート固有挙動を外し、プレースホルダ・ペイン背景・Δ符号着色・行クリックシグナルを足す）。GraphAreaView が `QSplitter(tabs, readout_pane)` で単一ペインを所有し、アクティブパネル VM の読み値を流す。読み値算出は VM 据え置き（`cursor_readings`/`delta_readings` に entry_id を追加するのみ）。

**Tech Stack:** PySide6（QSplitter・QGridLayout・QSS）・既存 theme パイプライン・realgui Layer C。

**Spec:** [docs/superpowers/specs/2026-07-19-readout-pane-design.md](../specs/2026-07-19-readout-pane-design.md)

## Global Constraints

- 色は tokens.py のみ（src に hex/rgba/QColor リテラル禁止・test_theme_guard 検出）。QSS/リッチテキスト断片は qss.py の生成関数経由。
- 新トークン値: `surface_readout_panel` DARK `#1e1e2e`/LIGHT `#eff1f5`（=chrome_alternate_base 同値の別役割）・`delta_negative` DARK `#f38ba8`/LIGHT `#d20f39`（=close_hover 同値の別役割）・`delta_positive` DARK `#a6e3a1`/LIGHT `#40a02b`（新規値）。同値別役割2件は値分岐テスト必須。
- 読み値算出ロジック（`GraphPanelVM.cursor_readings`/`delta_readings`）の意味論は不変 — entry_id を足すのみ。
- 集約はアクティブパネルの信号のみ（タブ内全集約しない）。カーソル未設置時はプレースホルダ（値表示は完全カーソル連動）。位置は右固定（左右切替は作らない）。
- 挙動値変更時は Layer B だけでなく同値を assert する並行 realgui も更新（memory gui_behavior_change_stale_parallel_realgui_test）。
- コミット前ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全て exit 0（全リポジトリでスコープせず実行）。

---

### Task 1: 3トークン＋qss ペイン背景＋golden/値分岐テスト

**Files:**
- Modify: `src/valisync/gui/theme/tokens.py`（Colors・DARK・LIGHT）
- Modify: `src/valisync/gui/theme/qss.py`（末尾に生成関数追加）
- Test: `tests/gui/test_theme_tokens.py`・`tests/gui/test_theme_qss.py`

**Interfaces:**
- Produces: `tokens.Colors.surface_readout_panel`/`delta_negative`/`delta_positive: Color`・`qss.readout_panel(t=None) -> str`・`qss.delta_value(color: tokens.Color) -> str`（Task 3 が消費）

- [ ] **Step 1: golden を先に更新（RED）**

`tests/gui/test_theme_tokens.py` の `test_dark_values_frozen_snapshot` の `golden_colors` の `"chrome_frame"` 行直後に追加:

```python
        "surface_readout_panel": Color.from_hex("#1e1e2e"),
        "delta_negative": Color.from_hex("#f38ba8"),
        "delta_positive": Color.from_hex("#a6e3a1"),
```

同ファイル `test_light_values_frozen_snapshot` の `golden` の `"chrome_frame"` 行直後に追加:

```python
        "surface_readout_panel": Color.from_hex("#eff1f5"),
        "delta_negative": Color.from_hex("#d20f39"),
        "delta_positive": Color.from_hex("#40a02b"),
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_theme_tokens.py -v`
Expected: `test_dark_values_frozen_snapshot`・`test_light_values_frozen_snapshot` FAIL（3フィールド不在）

- [ ] **Step 3: tokens.py に追加**

`Colors` の `chrome_frame: Color` 直後に:

```python
    surface_readout_panel: Color  # 読み値ペイン面 — chrome_alternate_base と同値の別役割
    delta_negative: Color  # Δ(B-A) 負値/基準比マイナス — close_hover と同値の別役割
    delta_positive: Color  # Δ(B-A) 正値/基準比プラス (Catppuccin green)
```

`DARK` の `chrome_frame=Color.from_hex("#45475a"),` 直後に:

```python
        surface_readout_panel=Color.from_hex("#1e1e2e"),
        delta_negative=Color.from_hex("#f38ba8"),
        delta_positive=Color.from_hex("#a6e3a1"),
```

`LIGHT` の `chrome_frame=Color.from_hex("#bcc0cc"),` 直後に:

```python
        surface_readout_panel=Color.from_hex("#eff1f5"),
        delta_negative=Color.from_hex("#d20f39"),
        delta_positive=Color.from_hex("#40a02b"),
```

- [ ] **Step 4: qss.py に生成関数を追加（末尾）**

```python
def readout_panel(t: tokens.ThemeTokens | None = None) -> str:
    """読み値ペインの面 (常設ドックテーブル背景)。"""
    return f"#ReadoutPane {{ background: {_t(t).colors.surface_readout_panel.hex}; }}"


def delta_value(color: tokens.Color) -> str:
    """Δ 値ラベルの符号着色 (delta_positive/delta_negative を呼び出し側が選ぶ)。"""
    return f"color: {color.hex};"
```

- [ ] **Step 5: 値分岐テストを追加**

`tests/gui/test_theme_qss.py` 末尾に追加:

```python
def test_readout_panel_uses_surface_readout_panel_not_chrome():
    """surface_readout_panel は chrome_alternate_base と同値の別トークン。
    値を分岐させたテーマで readout_panel がどちらを参照するか直接実証する。"""
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK,
        colors=dataclasses.replace(DARK.colors, surface_readout_panel=Color(1, 2, 3)),
    )
    s = qss.readout_panel(alt)
    assert "#ReadoutPane" in s
    assert Color(1, 2, 3).hex in s
    assert DARK.colors.chrome_alternate_base.hex not in s


def test_delta_value_uses_given_delta_token_not_close_hover():
    """delta_negative は close_hover と同値の別トークン。値分岐で誤配線を実証。"""
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, delta_negative=Color(1, 2, 3))
    )
    s = qss.delta_value(alt.colors.delta_negative)
    assert Color(1, 2, 3).hex in s
    assert DARK.colors.close_hover.hex not in s
    # delta_positive は新規値: 生成関数が受け取った色をそのまま出す
    assert DARK.colors.delta_positive.hex in qss.delta_value(DARK.colors.delta_positive)
```

- [ ] **Step 6: GREEN＋ゲート＋コミット**

```bash
uv run pytest tests/gui/test_theme_tokens.py tests/gui/test_theme_qss.py tests/gui/test_theme_export.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/tokens.py src/valisync/gui/theme/qss.py tests/gui/test_theme_tokens.py tests/gui/test_theme_qss.py
git commit -m "feat(theme): readout ペイン用3トークン+qss (readout-pane Task 1)"
```

（`test_build_css_covers_every_token_field` はフィールド走査で自動追随。FAIL したら想定を確認）

---

### Task 2: CursorReading/DeltaReading に entry_id＋CursorReading に min–max 値域

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（dataclass 2つ・`cursor_readings`・`delta_readings`）
- Test: `tests/gui/test_graph_panel_cursor.py`（または test_graph_panel_vm 系・既存の readings テストへ追記）

**Interfaces:**
- Consumes: `_PlottedEntry.entry_id`（既存）・`Signal.finite_view()`（既存・`(ts, vals)` を返す）
- Produces: `CursorReading.entry_id: int`・`CursorReading.range_lo: float | None`・`CursorReading.range_hi: float | None`・`DeltaReading.entry_id: int`（Task 3/4 が行→曲線逆引きと min–max 列に使う）

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_cursor.py` 末尾に追加（`session` fixture と `GraphPanelVM` は既存 import を使う。無ければ既存の readings を作るテストの構成に合わせる）:

```python
def test_cursor_readings_carry_entry_id(session) -> None:
    """行クリックの逆引き用に CursorReading.entry_id が plotted entry と一致する。"""
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

    vm = GraphPanelVM(session)
    key = session.signals()[0].key
    vm.add_signal(key)
    vm.set_cursor(0.5)
    reading = vm.cursor_readings()[0]
    assert reading.entry_id == vm._plotted[0].entry_id


def test_delta_readings_carry_entry_id(session) -> None:
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

    vm = GraphPanelVM(session)
    key = session.signals()[0].key
    vm.add_signal(key)
    vm.set_cursor(0.3)
    vm.enable_delta(True)
    vm.set_cursor_b(0.6)
    reading = vm.delta_readings()[0]
    assert reading.entry_id == vm._plotted[0].entry_id


def test_cursor_reading_carries_value_range(session) -> None:
    """min–max 列用に CursorReading が信号の finite 値域を運ぶ。"""
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

    vm = GraphPanelVM(session)
    key = session.signals()[0].key
    vm.add_signal(key)
    vm.set_cursor(0.5)
    r = vm.cursor_readings()[0]
    sig = session.signal(key)  # 実 API 名は既存テストに合わせる
    _ts, vals = sig.finite_view()
    assert r.range_lo == float(vals.min())
    assert r.range_hi == float(vals.max())
```

（`session` の信号キー取得・信号取得・delta 有効化 API は既存の同ファイル内テストと同じ呼び出しに合わせる。`enable_delta`/`set_cursor_b`/`session.signal(key)` の正確な名前は graph_panel_vm.py / session を確認して合わせること — 意味論「A/B 設置して delta_readings が返る」「finite 値域が読める」は不変。）

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k entry_id -v`
Expected: FAIL（`CursorReading` に entry_id が無い → TypeError or AttributeError）

- [ ] **Step 3: dataclass にフィールド追加**

`graph_panel_vm.py` の `CursorReading`（91行付近）の `unit: str = ""` の後に:

```python
    entry_id: int = 0  # 逆引き用 (行クリック→曲線ハイライト)。既定0は非プロット文脈
    range_lo: float | None = None  # 信号の finite 最小 (min–max 列)。None=値域不明
    range_hi: float | None = None  # 信号の finite 最大
```

`DeltaReading`（103行付近）の `unit: str = ""` の後に同じく:

```python
    entry_id: int = 0
```

- [ ] **Step 4: 生成側で entry_id＋値域を詰める**

`cursor_readings`（988行付近）の2箇所の `CursorReading(...)` 生成を改修。範囲外/信号なし側（値域も不明なので range は None のまま）:

```python
                out.append(
                    CursorReading(
                        entry.signal_key, entry.color, None, False,
                        entry_id=entry.entry_id,
                    )
                )
```

通常側（`sig.finite_view()` の値配列から min/max。空配列ガード付き）:

```python
            _fts, _fvals = sig.finite_view()
            r_lo = float(_fvals.min()) if _fvals.size else None
            r_hi = float(_fvals.max()) if _fvals.size else None
            out.append(
                CursorReading(
                    entry.signal_key,
                    entry.color,
                    val,
                    val is not None,
                    label=_resolve_value_label(sig, val),
                    unit=unit,
                    entry_id=entry.entry_id,
                    range_lo=r_lo,
                    range_hi=r_hi,
                )
            )
```

（`finite_view()` の戻り値タプル `(ts, vals)` の順は signal.py:97 を確認して合わせる。値配列側の min/max を使う。）

`delta_readings`（1139行付近）の `DeltaReading(...)` 生成にも同様に `entry_id=entry.entry_id` を追加（生成ループの entry 変数から取得。実装時に該当行を確認して詰める）。

- [ ] **Step 5: GREEN＋full suite＋ゲート＋コミット**

```bash
uv run pytest tests/gui/test_graph_panel_cursor.py -k entry_id -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_cursor.py
git commit -m "feat(vm): CursorReading/DeltaReading に entry_id (readout-pane Task 2)"
```

---

### Task 3: CursorReadout をペインへ進化

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`
- Test: `tests/gui/test_cursor_readout.py`・`tests/gui/test_cursor_readout_diff.py`

**Interfaces:**
- Consumes: `qss.readout_panel()`・`qss.delta_value(color)`（Task 1）・`DeltaReading.entry_id`/`CursorReading.entry_id`（Task 2）
- Produces: `CursorReadout` の新 API — `objectName == "ReadoutPane"`・`show_placeholder(text: str)`・`row_activated = Signal(int)`（entry_id）。撤去: `was_user_moved`/`reset_user_moved`/`close_button`/`mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`/`_drag_offset`/`_user_moved`

**削除する挙動（フロート固有）**:
- `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`（475-488行）・`_drag_offset`/`_user_moved` 属性・`was_user_moved`/`reset_user_moved`（291-297行）
- 常時✕ボタン `_close_btn`（95-101行の生成と header_row 追加）・`close_button`（299-301行）
- チップスタイル: `setAttribute(WA_StyledBackground)` の readout_chip 適用（78-80行）→ `setObjectName("ReadoutPane")`＋`qss.readout_panel()` へ。`setCursor(cursor(CursorKind.MOVE))`（104行）削除

**足す挙動**:
- プレースホルダ: `show_placeholder(text)` — グリッドを空にし中央にプレースホルダ QLabel を出す。`set_global`/`set_delta`/`set_readings` 呼び出しは通常テーブルに戻す
- **min–max 列（単一ファイル）**: `set_global` の列を `名前 ｜ A値 ｜ min–max` にする。min–max セルは `range_lo`/`range_hi` を精度反映で `f"{lo:.{p}g}–{hi:.{p}g}"`、None なら空欄。col_headers に `["A値", "min–max"]` を設定（現行 global は col_headers 空だが、min–max 列導入で見出し行が出る＝コンセプト 2a に一致）
- Δ符号着色: `set_delta` の Δy セル（`_fmt_dy` の値）を、`dy > 0` なら `delta_positive`・`dy < 0` なら `delta_negative`・0/None は既定色。着色は `_rebuild` に「セルごとの色」を渡す拡張が要る（下記）
- 行クリック: 名前ラベル/行クリックで `row_activated.emit(entry_id)`。各行に entry_id を保持

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_cursor_readout.py` 末尾に新規追加:

```python
def test_pane_object_name_and_no_close_button(qtbot: QtBot):
    """ペイン化: objectName=ReadoutPane・常時✕ボタンは撤去 (フロート廃止)。"""
    w = CursorReadout()
    qtbot.addWidget(w)
    assert w.objectName() == "ReadoutPane"
    assert not hasattr(w, "close_button")


def test_set_global_renders_minmax_column(qtbot: QtBot):
    """単一ファイル: 列 = 名前 | A値 | min–max (コンセプト 2a)。"""
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(
        1.0,
        [CursorReading("vCar", "#1f77b4", 12.3, True, entry_id=1,
                       range_lo=0.0, range_hi=100.0)],
    )
    assert w.column_headers() == ["A値", "min–max"]
    # row_texts()[i] = (name, joined cells) — A値と min–max の両方を含む
    _name, cells = w.row_texts()[0]
    assert "12.3" in cells and "0" in cells and "100" in cells


def test_show_placeholder_replaces_table(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings([CursorReading("csv::vCar", "#1f77b4", 12.3, True)])
    assert len(w.row_texts()) == 1
    w.show_placeholder("プロットをクリックしてカーソルを設置")
    assert w.row_texts() == []
    assert w.placeholder_text() == "プロットをクリックしてカーソルを設置"


def test_row_click_emits_entry_id(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(
        1.0,
        [CursorReading("csv::vCar", "#1f77b4", 12.3, True, entry_id=7)],
    )
    seen: list[int] = []
    w.row_activated.connect(seen.append)
    w.activate_row(0)  # プログラム的行トリガ (realgui は実クリックで検証)
    assert seen == [7]


def test_delta_dy_sign_colors_value_diverged(qtbot: QtBot):
    """Δy 正=delta_positive・負=delta_negative で着色。delta_negative は close_hover と
    同値の別役割なので、値を分岐させたテーマで set_delta の呼び出し経路が
    delta_negative(≠close_hover) を選ぶことを直接実証する(Task 1 レビュー Important
    対応: delta_value は恒等関数で誤配線は呼び出し側=このコードにあるため、ここが
    唯一の値分岐ガード)。"""
    import dataclasses

    from valisync.core.statistics.range_stats import StatisticsResult
    from valisync.gui.theme.tokens import DARK, Color, set_active

    # delta_negative を close_hover と別値へ分岐させたテーマを active に
    alt = dataclasses.replace(
        DARK,
        colors=dataclasses.replace(
            DARK.colors,
            delta_negative=Color(1, 2, 3),
            delta_positive=Color(4, 5, 6),
        ),
    )
    set_active(alt)
    try:
        w = CursorReadout()
        qtbot.addWidget(w)
        stats = StatisticsResult(mean=0, max=0, min=0, std=0, count=5)
        w.set_delta(
            1.0, 2.0,
            [
                DeltaReading("up", "#111", 1.0, 3.0, stats, True, entry_id=1),
                DeltaReading("dn", "#222", 1.0, -3.0, stats, True, entry_id=2),
            ],
        )
        styles = w.dy_cell_styles()  # [(row_index, style_str), ...] introspection
        joined = " ".join(s for _i, s in styles)
        assert Color(4, 5, 6).hex in joined  # 正 → delta_positive
        assert Color(1, 2, 3).hex in joined  # 負 → delta_negative
        assert DARK.colors.close_hover.hex not in joined  # close_hover 誤配線でない
    finally:
        set_active(DARK)
```

（`StatisticsResult` の実フィールドは既存 test_cursor_readout.py の import と生成に合わせる。`dy_cell_styles`/`placeholder_text`/`activate_row` は本タスクで導入する introspection/操作 API。この値分岐テストが Global Constraint「同値別役割2件は値分岐テスト必須」の delta_negative 分を担保する — Task 1 の恒等関数テストでは不足〔レビュー Important〕。）

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k "pane_object_name or show_placeholder or row_click or delta_dy_sign" -v`
Expected: 4本 FAIL（新 API 不在）

- [ ] **Step 3: 実装（cursor_readout.py の進化）**

3-1. `__init__`（73-146行）を改修:
- `setAttribute(WA_StyledBackground)`＋`setStyleSheet(qss.readout_chip())`（78-80行）を削除し、代わりに:
  ```python
  self.setObjectName("ReadoutPane")
  self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
  self.setStyleSheet(qss.readout_panel())
  ```
- header_row の `_close_btn` 生成と追加（95-101行）を削除。`_header` とストレッチのみ残す
- `self.setCursor(cursor(CursorKind.MOVE))`（104行）を削除（`cursor`/`CursorKind` の import が他で未使用になれば除去）
- `_drag_offset`/`_user_moved`（124-129行）を削除
- プレースホルダ用 QLabel を1つ用意: `self._placeholder = QLabel(); self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter); self._placeholder.hide(); outer.addWidget(self._placeholder)`。`self._placeholder_text = ""`
- `row_activated = Signal(int)` をクラス属性として追加（`from PySide6.QtCore import Signal` を import）
- 各行 entry_id 保持用: `self._row_entry_ids: list[int] = []`

3-2. メソッド撤去: `was_user_moved`/`reset_user_moved`（291-297行）・`close_button`（299-301行）・`mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`（475-488行）を削除。`_clear_cursors`（303-306行）は右クリックメニュー「カーソルを消す」から呼ばれるので残す。

3-3b. `set_global` の min–max 列化（173-204行）: 現行は `col_headers=[]`・cells=`[value]`。これを col_headers=`["A値", "min–max"]`・cells=`[a_value, minmax]` へ変更する。min–max 整形ヘルパを追加:
```python
def _fmt_range(lo: float | None, hi: float | None, precision: int = _DEFAULT_PRECISION) -> str:
    if lo is None or hi is None:
        return ""
    return f"{lo:.{precision}g}–{hi:.{precision}g}"
```
`set_global` の rows 生成:
```python
        self._col_headers = ["A値", "min–max"]
        self._rebuild(
            col_headers=self._col_headers,
            rows=[
                (
                    r.name, r.unit, r.color,
                    [
                        _fmt_labeled(r.value if r.in_range else None, r.label, precision),
                        _fmt_range(r.range_lo, r.range_hi, precision),
                    ],
                )
                for r in readings
            ],
            entry_ids=[r.entry_id for r in readings],
            dy_styles=[None for _ in readings],
        )
```
（`set_readings`〔後方互換〕は列見出しなし・単一値のままでよい — min–max は set_global 専用。テスト `test_set_readings_builds_one_row_per_signal` 等は set_readings 経路なので無変更。）

3-3. プレースホルダ API:
```python
def show_placeholder(self, text: str) -> None:
    """テーブルを空にしプレースホルダ文言を出す (信号ゼロ/カーソル未設置)。"""
    self._placeholder_text = text
    self._last_delta = None
    self._header.hide()
    self._header_text = ""
    self._col_headers = []
    self._full_rebuild([], [], (tuple(), tuple()))  # グリッドを空に
    self._placeholder.setText(text)
    self._placeholder.show()

def placeholder_text(self) -> str:
    return self._placeholder_text
```
`set_readings`/`set_global`/`set_delta` の先頭で `self._placeholder.hide(); self._placeholder_text = ""` を実行（テーブル表示に戻す）。

3-4. entry_id 保持＋行クリック: `_full_rebuild`/`_update_in_place` の rows タプルを `(name, unit, color, cells, entry_id, dy_styles)` の6要素へ拡張する代わりに、DRY のため rows は据え置き4要素とし、**別リスト**で entry_id と dy スタイルを渡す設計にする。`set_global`/`set_delta` が `_rebuild` を呼ぶ際に `entry_ids: list[int]` と `dy_styles: list[str | None]`（行ごと・None=無着色）を併せて渡す。`_rebuild`/`_full_rebuild`/`_update_in_place` のシグネチャに `entry_ids`/`dy_styles` を追加し、`_full_rebuild` で:
  - 各行の名前ラベルに `entry_id` を紐付け（`self._row_entry_ids` に格納）。名前ラベルをクリック可能にするため、行全体クリックを拾う: 各セル QLabel に対して行 index を持たせるのは煩雑なので、名前ラベルに `mousePressEvent` を付けるより、`self` の `mousePressEvent` で `childAt` から行を特定して `activate_row` を呼ぶ実装にする（フロートの mousePressEvent は撤去済みなので新規に「行クリック検出専用」の mousePressEvent を追加）:
    ```python
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            row = self._row_at(event.position().toPoint())
            if row is not None:
                self.activate_row(row)
        super().mousePressEvent(event)
    ```
  - `_row_at(pos)`: グリッドの行 y 範囲から行 index を求める（`self._value_labels` の各行先頭ラベルの geometry を使う）
  - `activate_row(row: int)`: `if 0 <= row < len(self._row_entry_ids): self.row_activated.emit(self._row_entry_ids[row])`
  - Δy セルの着色: `_full_rebuild` で cells の Δy 列（col_headers に "Δy" があればその位置）のラベルに `dy_styles[i]` があれば `setStyleSheet(dy_styles[i])` を適用。`dy_styles` は `set_delta` が算出:
    ```python
    dy_styles = []
    for r in readings:
        if r.dy is None or r.dy == 0:
            dy_styles.append(None)
        else:
            col = c.delta_positive if r.dy > 0 else c.delta_negative
            dy_styles.append(qss.delta_value(col))
    ```
  - introspection `dy_cell_styles(self) -> list[tuple[int, str]]`: 着色された行のみ `(row_index, style)` を返す（テスト用に保持リストを露出）

（実装は上記を満たす最小構成でよい。既存の差分更新〔`_update_in_place`〕は行数不変時に走るが、entry_id/dy_styles は set_global/set_delta のたび渡されるので stale にならないよう `_update_in_place` でも dy スタイルと entry_id を更新すること。）

- [ ] **Step 4: 既存テストの honest 更新**

Explore で棚卸し済みの以下を新挙動へ更新（削除でなく反映）:
- `test_cursor_readout.py::test_chip_background_paints_as_child_widget` → ペイン背景 `surface_readout_panel` を蛍光緑親パターンで検証（`#ReadoutPane` 背景・objectName ReadoutPane）
- `test_cursor_readout.py::test_readout_has_move_cursor` → 撤去（移動カーソルは廃止）
- `test_cursor_readout.py::test_close_button_fires_on_clear` → 撤去（常時✕廃止・クリアは右クリックメニュー `test_readout_menu_clear_fires_on_clear` が担保）
- `test_cursor_readout.py::test_header_markers_and_chip_use_tokens` → チップ styleSheet 検証部を `qss.readout_panel` 参照へ差し替え（ヘッダ色マーカー検証は残す）
- `test_cursor_readout_diff.py::test_drag_sets_user_moved_flag` → 撤去（ドラッグ移動廃止）
- 保持テスト（表描画・値整形・デルタ・統計・精度・CSV・差分更新）は無変更で PASS を確認

- [ ] **Step 5: GREEN＋full suite（この時点で graph_panel_view はまだ旧配線 — Task 4 で解消）**

Run: `uv run pytest tests/gui/test_cursor_readout.py tests/gui/test_cursor_readout_diff.py -v` → PASS
Run: `uv run pytest tests/gui/test_graph_panel_cursor.py tests/gui/test_graph_panel_readout_reposition.py -v`
Expected: **FAIL する**（GraphPanelView がまだ `_readout` のフロート API〔`was_user_moved` 等〕を呼ぶ）。この fallout は Task 4 で解消するため、ここでは「Task 4 で解消予定の既知 FAIL」としてレポートに列挙し、full suite は走らせて FAIL 一覧を記録（コミットは本タスク分のみ）。

**注意**: Task 3 単独では GraphPanelView が壊れるため、Task 3 と Task 4 は連続実行し、full-green は Task 4 完了時に達成する。Task 3 のコミットは cursor_readout.py＋その2テストに閉じる。

- [ ] **Step 6: ゲート（cursor_readout スコープ）＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/valisync/gui/views/cursor_readout.py
git add src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout.py tests/gui/test_cursor_readout_diff.py
git commit -m "feat(gui): CursorReadout をペイン化 (プレースホルダ/行クリック/Δ着色・readout-pane Task 3)"
```

---

### Task 4: GraphAreaView 統合＋GraphPanelView 配線移設

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py`（QSplitter・単一ペイン・_sync_readout・トグル・行ハイライト転送・callback 再配線）
- Modify: `src/valisync/gui/views/graph_panel_view.py`（自前 `_readout` 撤去・`readout_changed` シグナル追加・`activate_curve_by_id` 公開・カーソル線管理は残す）
- Test: `tests/gui/test_graph_panel_cursor.py`・`tests/gui/test_graph_panel_readout_reposition.py`・`tests/gui/test_active_panel.py`・新規 `tests/gui/test_readout_pane_binding.py`

**Interfaces:**
- Consumes: `CursorReadout.show_placeholder`/`set_global`/`set_delta`/`sync_visible_stats`/`row_activated`/`_on_clear`/`_on_precision`/`_on_stat_toggled`（Task 3）
- Produces: `GraphAreaView.readout_pane`（単一インスタンス）・`GraphAreaView.set_readout_visible(bool)`/`readout_visible() -> bool`・`GraphPanelView.readout_changed = Signal()`・`GraphPanelView.activate_curve_by_id(entry_id: int)`

- [ ] **Step 1: GraphPanelView から自前 readout を撤去し pull シグナルへ**

`graph_panel_view.py`:
- `_readout` 生成（862-880行）・`_readout_placed`（884行）・`_reposition_readout`（1388-1395行）・`_readout` を触る `_refresh_state` の追従ブロック（1044-1048行）を撤去
- `_sync_cursor`（1398-1454行）を改修: カーソル線の表示（`_cursor_line`/`_cursor_line_b`・`_apply_cursor_pens`・active_cursor 追跡）は**残す**。`_readout.set_global`/`set_delta`/`setVisible`/`_reposition_readout` 呼び出しを撤去し、末尾で `self.readout_changed.emit()` を発火
- クラスに `readout_changed = Signal()` を追加。`readout_visible()`（1504-1507行）は撤去（ペインは GraphAreaView 所有）
- 公開ハイライト: `def activate_curve_by_id(self, entry_id: int) -> None: self._activate_curve(entry_id)` を追加

- [ ] **Step 2: GraphAreaView に QSplitter＋単一ペイン**

`__init__`（143-146行のレイアウト）を改修:
```python
from PySide6.QtWidgets import QSplitter  # 既存 import にあり
from valisync.gui.views.cursor_readout import CursorReadout

self.readout_pane = CursorReadout()
self._readout_visible = True
self._readout_split = QSplitter(Qt.Orientation.Horizontal, self)
self._readout_split.addWidget(self.tabs)
self._readout_split.addWidget(self.readout_pane)
self._readout_split.setStretchFactor(0, 1)  # プロット側が伸びる
self._readout_split.setStretchFactor(1, 0)

layout = QVBoxLayout(self)
layout.setContentsMargins(0, 0, 0, 0)
layout.addWidget(self.sync_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
layout.addWidget(self._readout_split)
```

- [ ] **Step 3: `_sync_readout` と起動条件を配線**

```python
def _sync_readout(self) -> None:
    """アクティブタブのアクティブパネル VM を単一ペインへ反映。"""
    tab = self.tabs.currentIndex()
    if tab < 0:
        self.readout_pane.show_placeholder("表示中の信号がありません")
        return
    panels = self.vm.panels(tab)
    active = self.vm.active_panel_index(tab)
    if not panels or active < 0 or active >= len(panels):
        self.readout_pane.show_placeholder("表示中の信号がありません")
        return
    pvm = panels[active]
    if pvm.cursor_t is None:
        self.readout_pane.show_placeholder("プロットをクリックしてカーソルを設置")
        return
    if not pvm.cursor_readings():
        self.readout_pane.show_placeholder("表示中の信号がありません")
        return
    if pvm.delta_enabled and pvm.cursor_t_b is not None:
        self.readout_pane.sync_visible_stats(pvm.visible_stat_cols)
        self.readout_pane.set_delta(
            pvm.cursor_t, pvm.cursor_t_b, pvm.delta_readings(),
            interp_label=_interp_label(pvm), precision=pvm.value_precision,
        )
    else:
        self.readout_pane.set_global(
            pvm.cursor_t, pvm.cursor_readings(),
            interp_label=_interp_label(pvm), precision=pvm.value_precision,
        )
```

`_interp_label(pvm)` は graph_panel_view の `_INTERP_LABELS.get(pvm.interp_method, "")` と同義。DRY のため `graph_panel_view` から `_INTERP_LABELS` を import して `_INTERP_LABELS.get(pvm.interp_method, "")` を直接使う。

起動条件の配線:
- `_on_vm_change` の `"active_panel"` 分岐に `self._sync_readout()` を追加
- `_on_current_changed`（タブ切替）末尾に `self._sync_readout()` を追加
- `_rebuild` 末尾（`_sync_active_frames` を呼ぶ箇所）に `self._sync_readout()` を追加
- `_wire_panel`（229-256行）に `widget.readout_changed.connect(lambda *_: self._sync_readout())` を追加（全パネルを繋ぐが `_sync_readout` はアクティブのみ読むので安全）

- [ ] **Step 4: 表示/非表示トグル・行ハイライト転送・callback 再配線**

```python
def set_readout_visible(self, visible: bool) -> None:
    self._readout_visible = visible
    self.readout_pane.setVisible(visible)

def readout_visible(self) -> bool:
    return self._readout_visible
```

行ハイライト転送（`__init__` でペイン生成直後）:
```python
self.readout_pane.row_activated.connect(self._on_readout_row_activated)
```
```python
def _on_readout_row_activated(self, entry_id: int) -> None:
    tab = self.tabs.currentIndex()
    active = self.vm.active_panel_index(tab)
    for t, p, widget in self._panel_views:
        if t == tab and p == active:
            widget.activate_curve_by_id(entry_id)
            break
```

callback 再配線（ペイン生成直後・アクティブパネル VM へ委譲）:
```python
self.readout_pane._on_clear = lambda: self._active_pvm_call(lambda pvm: pvm.toggle_main_cursor(False))
self.readout_pane._on_precision = lambda p: self._active_pvm_call(lambda pvm: pvm.set_value_precision(p))
self.readout_pane._on_stat_toggled = lambda col, on: self._active_pvm_call(
    lambda pvm: pvm.set_stat_col_visible(col, on)
)
```
`_active_pvm_call(fn)`: アクティブタブ/パネルの VM を引いて `fn(pvm)` を呼ぶ（無ければ no-op）。`set_stat_col_visible` の正確な VM メソッド名は graph_panel_vm.py を確認して合わせる（現行 GraphPanelView の `_on_stat_toggled` が呼ぶものと同一）。

トグルボタンの UI 設置: `sync_checkbox` の行（`layout.addWidget(self.sync_checkbox,...)`）に、読み値表示トグルの `QToolButton`（objectName `readout_toggle_button`・チェック式・`toggled.connect(self.set_readout_visible)`・既定 checked）を並べる。

- [ ] **Step 5: 既存テストの honest 更新＋新規束縛テスト**

- `test_graph_panel_cursor.py`: `test_setting_cursor_shows_line_and_readout`/`test_clearing_cursor_hides_line_and_readout`/`test_readout_position_preserved_on_cursor_update`/`test_readout_close_clears_all_cursors` は所有関係が消えるため、**カーソル線の表示**を検証する形へ縮約 or GraphAreaView 経由のペイン検証へ移設（`view._readout` 参照は撤去）
- `test_graph_panel_readout_reposition.py`: ファイルごと撤去（`_reposition_readout`/`_readout_placed`/`was_user_moved` は全廃）。撤去理由を commit メッセージに明記
- `test_active_panel.py`: 既存の枠テストは無変更（Task 4 は枠に触れない）
- 新規 `tests/gui/test_readout_pane_binding.py`:

```python
def test_readout_binds_to_active_panel(qtbot, session) -> None:
    """アクティブパネル切替でペイン内容がそのパネルの信号へ入れ替わる。"""
    # 2パネル・各別信号・カーソル設置 → active 切替でペインの row 名が変わる

def test_readout_placeholder_without_cursor(qtbot, session) -> None:
    """カーソル未設置時はプレースホルダ (値表示は完全カーソル連動)。"""

def test_readout_toggle_hides_pane(qtbot, session) -> None:
    """set_readout_visible(False) でペイン非表示・True で再表示。"""

def test_readout_row_activates_curve(qtbot, session) -> None:
    """ペイン行クリック → アクティブパネルの該当 entry_id が active_curve に。"""
```
（各テストの具体は既存 test_active_panel.py の area/session fixture 構成を流用して実装。意味論は上記コメントどおり。）

- [ ] **Step 6: GREEN（full-green 達成）＋ゲート＋コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/graph_area_view.py src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_cursor.py tests/gui/test_readout_pane_binding.py
git rm tests/gui/test_graph_panel_readout_reposition.py
git commit -m "feat(gui): 読み値を GraphAreaView 右ペインへ統合 (readout-pane Task 4)"
```

---

### Task 5: realgui 移行＋新規行ハイライト（メインセッション/コントローラ駆動）

**Files:**
- Modify: `tests/realgui/test_readout_realclick.py`・`tests/realgui/test_global_cursor.py`
- Create: `tests/realgui/test_readout_pane_realclick.py`（行クリックハイライト）

- [ ] **Step 1: 既存 realgui の honest 更新**
- `test_readout_realclick.py::test_real_click_close_button_clears` → ✕撤去のため「右クリックメニュー→カーソルを消す」を実クリックする形へ移行（`build_readout_menu` の項目）
- `test_readout_realclick.py::test_real_right_click_readout_copy` → ペインを実右クリック→「表をコピー」（ペイン化後も維持・target をペイン矩形へ）
- `test_global_cursor.py::test_real_drag_b_cursor_stats_live_recalc` → `view._readout` を `graph_area_view.readout_pane` へ差し替え（`row_texts()` はペインでも有効）

- [ ] **Step 2: 新規 realgui（行クリック→ハイライト）**
`tests/realgui/test_readout_pane_realclick.py`: 2信号を1パネルへ→カーソル設置→ペインの2行目を実クリック→アクティブパネルの `active_curve_id()` がその行の entry_id になる＋スクショ。実 OS 入力（`at`/`LDOWN`/`LUP`）。

- [ ] **Step 3: realgui 全数＋journey smoke**
```bash
uv run pytest tests/realgui --realgui
```
Expected: 全 PASS。移行分＋新規＋無回帰。

- [ ] **Step 4: ゲート＋コミット**
```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/
git commit -m "test(realgui): 読み値ペインの行クリック/コピー/束縛を実機化 (readout-pane Task 5)"
```

---

### Task 6: 実機検証＋成果物更新（コントローラ）

コード変更なし（成果物）。実ディスプレイ必須。

- [ ] **Step 1: 前後差分で意図差分を確認**
```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_incrB_dark --theme dark
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_incrB_dark
```
Expected: exit 1。差分解析で「読み値がオーバーレイ→右ペインへ再配置＋プロット幅縮小」に整合することを目視/分布で確認（03_cursor/05_affordances が大きく変わる＝意図差分）。撮影スクリプト（`capture_ui_screenshots.py`）が `_readout` の直接操作をしていないか確認し、フロート強制表示（149-152行の `panel_view._active_frame`/`_set_drop_highlight`）はアクティブ枠/ドロップ枠のもので readout とは無関係 — ただし読み値ペインが常設化したので 03_cursor はカーソル設置で自然に出る。撮影が読み値を確実に出すよう、カーソル設置後にペインが可視であることを確認（必要なら撮影スクリプトを readout_pane 表示前提に微修正）。

- [ ] **Step 2: light＋debug-theme 目視**
```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_incrB_light --theme light
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_incrB_debug --debug-theme
```
`surface_readout_panel`/`delta_*` が意図位置に着地することを目視。

- [ ] **Step 3: ベースライン差し替え＋カタログ＋エクスポート＋カード更新**
```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_baseline --theme dark
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_dark --theme dark --catalog
uv run python scripts/export_design_tokens.py --theme dark --out design_export
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_light --theme light --catalog
uv run python scripts/export_design_tokens.py --theme light --out design_export
```
`design/cards/readout_chip.html` を「readout パネル」内容へ更新（チップ→ペイン・`var(--vs-surface-readout-panel)` 等 3新トークンを参照）。カード内 var 参照は実在トークン照合テスト（test_theme_export）が検証するので、新トークンの CSS 変数名（`--vs-surface-readout-panel`/`--vs-delta-negative`/`--vs-delta-positive`）が export に出ることを確認。

---

### Task 7: design.md＋realgui 全数確認＋最終レビュー・PR・再同期（コントローラ）

**Files:**
- Modify: `docs/design.md`（トークン表＋決定履歴）

- [ ] **Step 1: docs/design.md 更新**
トークン表「readout チップ」行の記述をペインへ更新し、新3トークンを追記（面/Δ着色）。決定履歴に運用反復3を追加:
```markdown
- 2026-07-19: カーソル読み値をフロートチップ→常設ペイン化（`surface_readout_panel`/
  `delta_negative`/`delta_positive` 新設）。アクティブパネル束縛・行クリックで波形
  ハイライト。出典: claude.ai/design 検討の持ち帰りメモ（2026-07-18）＋カード
  「コンセプトとメイン画面案」2a/2b/4b。設計は
  [readout-pane spec](superpowers/specs/2026-07-19-readout-pane-design.md)。PR #TBD。
```

- [ ] **Step 2: 最終ブランチレビュー（最上位モデル）→ 指摘対応**
- [ ] **Step 3: design.md PR 番号記入 → push → `gh pr create` → CI watch**
- [ ] **Step 4: DesignSync 再同期（dark/light 各18ファイル・readout カード更新反映）**
- [ ] **Step 5: ユーザーへ完了報告（merge はユーザー判断）。merge 後に CLAUDE.md docs PR。**
