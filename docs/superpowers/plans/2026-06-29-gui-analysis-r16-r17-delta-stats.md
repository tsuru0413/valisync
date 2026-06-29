# R16 Delta_Cursor + R17 範囲統計 実装プラン（増分B）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** メイン(A)に加えサブ(Δ, B)カーソルを右クリックトグルで出し、A→B の Δt/Δy と範囲統計（mean/max/min/std/count）を読み取り面に表示する。表示の出入りはメニュートグル、移動は各線の D&D のみ（R15 の空クリック設置を撤去）。

**Architecture:** MVVM。`GraphPanelVM` が Delta 状態（`cursor_t_b`/`delta_enabled`）と Δ/統計（Session 委譲・A<B 正規化）を保持。`CursorReadout` が時刻ヘッダ＋Δy・統計列＋「列▾」選択を描画。`GraphPanelView` が 2 本目 `pg.InfiniteLine` とコンテキストメニューのチェック式トグルを配線し、click 設置を撤去。カーソル A は既存どおり兄弟パネルへ同期、Delta は各パネル局所（B は A が無いと成立しない不変条件を `set_cursor(None)` で強制）。

**Tech Stack:** Python 3.13 / uv / PySide6 / pyqtgraph / numpy / pytest(+pytest-qt)。

**設計 spec:** `docs/superpowers/specs/2026-06-29-gui-analysis-cursor-offset-design.md`（増分B 改訂反映済み・commit 084de42）。本プランは analysis 増分3本（A=R15 済 / **B=R16+R17 ＝本プラン** / C=R14）の Plan B。

## Global Constraints

- **MVVM 厳守**: `src/valisync/gui/viewmodels/` 配下は PySide6/pyqtgraph/Qt を import しない。コアは `Session` 経由のみ。
- **品質ゲート（各 commit 前に全通過）**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- **worktree 初回**: `uv sync --extra dev` 実行済み（本セッションで完了）。
- **GUI テストレイヤー**: Layer A/B は `tests/gui/`（headless・CI）。Layer C は `tests/realgui/`・`@pytest.mark.realgui`・`--realgui` オプトイン（CI 除外）。
- **カーソル/Delta 状態は非永続**（セッション/.vsproj に保存しない）。
- **InterpolationMethod 値**: `LINEAR` / `ZERO_ORDER_HOLD` / `NEAREST`。**StatisticsResult**: `mean/max/min/std/count`（`from valisync.core.statistics.range_stats import StatisticsResult`、`count==0` で全 float が NaN）。`compute_statistics` は `t_start>t_end` で ValueError → **必ず `min(A,B), max(A,B)` で呼ぶ**。
- **既定位置**: メイン A = 可視幅 50%、サブ B = 75%（`x_range` から算出・出現時のみ・非永続）。
- **コミット末尾トレーラ（全コミット必須）**:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
  ```
  以降の commit ステップは `-m "<subject>"` のみ示す。実行時に上記トレーラを必ず付与する。

---

## File Structure

- **Modify** `src/valisync/gui/viewmodels/graph_panel_vm.py` — `DeltaReading` dataclass、Delta 状態（`cursor_t_b`/`delta_enabled`）、`toggle_main_cursor`/`toggle_delta`/`set_cursor_b`/`delta_t`/`delta_readings`、`set_cursor(None)` で Delta を連動クリア。
- **Modify** `src/valisync/gui/views/cursor_readout.py` — `set_global`/`set_delta`、時刻ヘッダ（色ドット）、Δy・統計列、「列▾」列選択メニュー、`header_text`/`column_headers` introspection。
- **Modify** `src/valisync/gui/views/graph_panel_view.py` — 2 本目 `_cursor_line_b`、コンテキストメニューのチェック式トグル（メイン/サブ・依存グレーアウト）、click 設置撤去、`_sync_cursor_from_vm` 拡張、`"delta"` 購読、refresh 再アタッチ、introspection。
- **Tests**: `tests/gui/test_graph_panel_vm.py`(拡張) / `tests/gui/test_cursor_readout.py`(拡張) / `tests/gui/test_graph_panel_cursor.py`(拡張) / `tests/realgui/test_global_cursor.py`(改修：click 削除・drag 再構成・B ドラッグ追加)。
- **Docs(最終タスク)**: `docs/roadmap.md` / `CLAUDE.md` Phase 表 / 設計 spec ステータス。

---

## Task 1: GraphPanelVM — Delta 状態・Δt/Δy・範囲統計（Layer A）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Consumes: 既存 `cursor_t` / `interp_method` / `set_cursor` / `_signal_map()` / `_plotted` / `x_range` / `_session.interpolate` / `_session.compute_statistics` / `_notify`。
- Produces:
  - `@dataclass class DeltaReading: name:str; color:str; value_a:float|None; dy:float|None; stats:StatisticsResult; in_range:bool`
  - `GraphPanelVM.cursor_t_b: float | None`、`GraphPanelVM.delta_enabled: bool`
  - `toggle_main_cursor(on: bool) -> None`（on→`set_cursor(50%)` / off→`set_cursor(None)`）
  - `toggle_delta(on: bool) -> None`（main ON 時のみ有効・on→B=75%・notify `"delta"`）
  - `set_cursor_b(t: float) -> None`（notify `"delta"`）
  - `delta_t -> float | None`（`cursor_t_b - cursor_t`）
  - `delta_readings() -> list[DeltaReading]`
  - `set_cursor(None)` 改修: Delta も連動クリア（B は A が無いと成立しない不変条件）

**gui-test-plan 分析（Task 1）**
- 変更種別: VM/純ロジック。
- 必要レイヤー: **A=必須** / B=不要（Qt 非依存）/ C=不要。
- 入力経路の再現性: N/A（ロジック）。
- ②実質性: 数値・None・bool を直接アサート（realgui 不要）。
- honest layering: VM 直叩きで十分（入力イベント経路なし）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_vm.py` の import 群に追記:

```python
from valisync.core.statistics.range_stats import StatisticsResult
from valisync.gui.viewmodels.graph_panel_vm import DeltaReading
```

ファイル末尾に追記（CSV helper は t=i*0.01, value=i。A=0.2, B=0.6 の範囲統計を検証）:

```python
# ─── Delta cursor + range stats (R16/R17) ───────────────────────────────────


def test_toggle_main_cursor_places_at_50_percent(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    assert vm.cursor_t == pytest.approx(0.5)
    vm.toggle_main_cursor(False)
    assert vm.cursor_t is None


def test_toggle_delta_requires_main(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    # main OFF のとき delta は有効化されない
    vm.toggle_delta(True)
    assert vm.delta_enabled is False
    assert vm.cursor_t_b is None
    # main ON 後は B=75% に出る
    vm.toggle_main_cursor(True)
    vm.toggle_delta(True)
    assert vm.delta_enabled is True
    assert vm.cursor_t_b == pytest.approx(0.75)


def test_clearing_main_clears_delta(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    vm.toggle_delta(True)
    vm.set_cursor(None)  # メインを消すとサブも消える（不変条件）
    assert vm.delta_enabled is False
    assert vm.cursor_t_b is None


def test_delta_t_signed(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)  # A=0.5
    vm.toggle_delta(True)  # B=0.75
    assert vm.delta_t == pytest.approx(0.25)


def test_delta_readings_dy_and_stats(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    key = _first_signal_key(session)
    vm.add_signal(key)
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)  # A=0.5 → value≈50 (value=i, t=i/100)
    vm.set_cursor(0.2)  # A を 0.2 に（value≈20）
    vm.toggle_delta(True)  # B=0.75 (value≈75)
    vm.set_cursor_b(0.6)  # B=0.6 (value≈60)
    r = vm.delta_readings()[0]
    assert r.name == key
    assert r.value_a == pytest.approx(20.0)
    assert r.dy == pytest.approx(40.0)  # y(0.6)-y(0.2) = 60-20
    # 範囲 [0.2,0.6] の統計: 値 20..60
    assert r.stats.count > 0
    assert r.stats.min == pytest.approx(20.0)
    assert r.stats.max == pytest.approx(60.0)


def test_delta_readings_normalizes_when_b_before_a(tmp_path):
    # B<A でも compute_statistics は min/max 正規化で ValueError を出さない
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    vm.set_cursor(0.6)  # A=0.6
    vm.toggle_delta(True)
    vm.set_cursor_b(0.2)  # B=0.2 < A
    r = vm.delta_readings()[0]  # 例外なく計算できる
    assert r.stats.count > 0
    assert vm.delta_t == pytest.approx(-0.4)  # Δt は符号付き


def test_delta_readings_empty_when_delta_off(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    assert vm.delta_readings() == []  # delta 未有効


def test_set_cursor_b_notifies_delta(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    vm.toggle_delta(True)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.set_cursor_b(0.3)
    assert "delta" in changes
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "delta or main_cursor" -v`
Expected: FAIL（`ImportError: DeltaReading` / `AttributeError: toggle_main_cursor`）

- [ ] **Step 3: 最小実装を書く**

`graph_panel_vm.py` の import に追記:

```python
from valisync.core.statistics.range_stats import StatisticsResult
```

`CursorReading` dataclass の直後に追記:

```python
@dataclass
class DeltaReading:
    """1 信号の Delta 読み取り(R16/R17)。value_a=None は A 範囲外、dy=None は A/B どちらか範囲外。"""

    name: str
    color: str
    value_a: float | None
    dy: float | None
    stats: StatisticsResult  # count==0 はデータなし
    in_range: bool
```

`__init__` の cursor 状態（`self.interp_method = ...` の後）に追記:

```python
        # Delta cursor + range stats (R16/R17) — transient, never persisted.
        self.cursor_t_b: float | None = None
        self.delta_enabled: bool = False
```

既存 `set_cursor` を次に置換（None で Delta を連動クリア）:

```python
    def set_cursor(self, t: float | None) -> None:
        """Set the global (A) cursor time and notify.

        Clearing A (t=None) also clears the Delta cursor: B is meaningless
        without A (the invariant also fires when a sibling broadcast clears A).
        """
        self.cursor_t = t
        if t is None:
            self.delta_enabled = False
            self.cursor_t_b = None
        self._notify("cursor")
```

`cursor_readings` の直後（Global cursor セクション末尾）に追記:

```python
    # ─── Delta cursor + range stats (R16/R17) ────────────────────────────────

    def _default_cursor_x(self, frac: float) -> float:
        """Data-x at *frac* of the visible x-range (0.5=centre, 0.75=right-ish)."""
        if self.x_range is None:
            return 0.0
        lo, hi = self.x_range
        return lo + frac * (hi - lo)

    def toggle_main_cursor(self, on: bool) -> None:
        """Show A at the visible-width 50% (on) or clear A and Delta (off)."""
        self.set_cursor(self._default_cursor_x(0.5) if on else None)

    def toggle_delta(self, on: bool) -> None:
        """Show B at 75% (on) or remove it (off).  No-op when A is not set."""
        if on:
            if self.cursor_t is None:
                return  # B requires A (View greys this out; VM guards too)
            self.delta_enabled = True
            self.cursor_t_b = self._default_cursor_x(0.75)
        else:
            self.delta_enabled = False
            self.cursor_t_b = None
        self._notify("delta")

    def set_cursor_b(self, t: float) -> None:
        """Move the Delta (B) cursor and notify (local — not broadcast)."""
        self.cursor_t_b = t
        self._notify("delta")

    @property
    def delta_t(self) -> float | None:
        """Signed Δt = tB − tA (None unless both cursors are set)."""
        if self.cursor_t is None or self.cursor_t_b is None:
            return None
        return self.cursor_t_b - self.cursor_t

    def delta_readings(self) -> list[DeltaReading]:
        """Per-signal A値・Δy・range stats over [A,B] (Session-delegated).

        Returns [] unless Delta is enabled.  Stats use min/max(A,B) so a B<A
        drag never raises (compute_statistics rejects t_start>t_end).
        """
        if not self.delta_enabled or self.cursor_t is None or self.cursor_t_b is None:
            return []
        a, b = self.cursor_t, self.cursor_t_b
        lo, hi = (a, b) if a <= b else (b, a)
        sig_map = self._signal_map()
        out: list[DeltaReading] = []
        for entry in self._plotted:
            if not entry.visible:
                continue
            sig = sig_map.get(entry.signal_key)
            if sig is None:
                out.append(
                    DeltaReading(
                        entry.signal_key,
                        entry.color,
                        None,
                        None,
                        StatisticsResult(
                            float("nan"), float("nan"), float("nan"), float("nan"), 0
                        ),
                        False,
                    )
                )
                continue
            va = self._session.interpolate(sig, a, self.interp_method)
            vb = self._session.interpolate(sig, b, self.interp_method)
            dy = (vb - va) if (va is not None and vb is not None) else None
            stats = self._session.compute_statistics(sig, lo, hi)
            out.append(
                DeltaReading(entry.signal_key, entry.color, va, dy, stats, va is not None)
            )
        return out
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "delta or main_cursor" -v`
Expected: PASS（8 件）。回帰: `uv run pytest tests/gui/test_graph_panel_vm.py -v` 全 PASS。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "feat(gui): GraphPanelVM に Delta カーソル状態と Δt/Δy・範囲統計を追加（R16/R17）"
```

---

## Task 2: CursorReadout — 時刻ヘッダ・Δ/統計列・列選択メニュー（Layer A/B）

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`
- Test: `tests/gui/test_cursor_readout.py`

**Interfaces:**
- Consumes: Task 1 の `CursorReading` / `DeltaReading`。
- Produces:
  - `set_global(t_a: float, readings: list[CursorReading]) -> None` — ヘッダ `● {t_a} s`、行 [swatch|name|値]。
  - `set_delta(t_a: float, t_b: float, readings: list[DeltaReading]) -> None` — ヘッダ `● t_a  ● t_b · Δt`、行 [swatch|name|A値|Δy|<選択統計>]。
  - `header_text() -> str`、`column_headers() -> list[str]`、`visible_stats() -> set[str]`（introspection）。
  - 「列▾」メニュー（チェック式・統計5列）で `visible_stats` を切替え再描画。

**gui-test-plan 分析（Task 2）**
- 変更種別: ウィジェット構成・状態。
- 必要レイヤー: **A=必須**（行/列/ヘッダ文字列の introspection）/ **B=該当**（qtbot で widget 構築、「列▾」QMenu の action trigger で列が消える）/ C=不要。
- 入力経路の再現性: 「列▾」は `QMenu`／build → `action.trigger()` で検証可（OS popup は不要、`sendEvent` も不要）。描画色（Δy 符号色・ドット色）は視覚だが既存 R15 と同方式で **realgui 専用価値なし**。
- ②実質性: `header_text`/`row_texts`/`column_headers`/`visible_stats` を直接アサート。スクショ不要。
- honest layering: 列メニューは「build した QMenu の action を trigger」で検証（実 popup の OS 表示までは追わない＝Layer A/B で十分。配線/内容が壊れれば落ちる）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_cursor_readout.py` の import に追記し、末尾に追記:

```python
from valisync.core.statistics.range_stats import StatisticsResult
from valisync.gui.viewmodels.graph_panel_vm import DeltaReading


def _stats(mean, mx, mn, std, count):
    return StatisticsResult(mean=mean, max=mx, min=mn, std=std, count=count)


def test_global_header_shows_time(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(0.5, [CursorReading("csv::vCar", "#1f77b4", 12.3, True)])
    assert "0.5" in w.header_text()
    assert w.row_texts()[0][0] == "csv::vCar"


def test_delta_header_shows_ta_tb_dt(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5,
        0.75,
        [DeltaReading("csv::vCar", "#1f77b4", 12.3, 4.5, _stats(10, 20, 5, 3, 100), True)],
    )
    h = w.header_text()
    assert "0.5" in h and "0.75" in h and "0.25" in h  # t_a, t_b, Δt


def test_delta_columns_present(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5,
        0.75,
        [DeltaReading("csv::vCar", "#1f77b4", 12.3, 4.5, _stats(10, 20, 5, 3, 100), True)],
    )
    cols = w.column_headers()
    for c in ("A値", "Δy", "mean", "max", "min", "std", "count"):
        assert c in cols


def test_column_menu_hides_a_stat(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5,
        0.75,
        [DeltaReading("csv::vCar", "#1f77b4", 12.3, 4.5, _stats(10, 20, 5, 3, 100), True)],
    )
    menu = w.build_column_menu()
    # "std" のチェックを外す
    act = next(a for a in menu.actions() if a.text() == "std")
    act.setChecked(False)
    act.triggered.emit(False)
    assert "std" not in w.column_headers()
    assert "std" not in w.visible_stats()


def test_delta_no_data_label(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5,
        0.5,
        [DeltaReading("csv::vCar", "#1f77b4", None, None, _stats(*([float("nan")] * 4), 0), False)],
    )
    joined = " ".join(t for row in w.row_texts() for t in row)
    assert "データなし" in joined


def test_global_then_delta_then_global_resets_columns(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(0.5, 0.75, [DeltaReading("s", "#1f77b4", 1.0, 0.5, _stats(1, 2, 0, 1, 9), True)])
    w.set_global(0.5, [CursorReading("s", "#1f77b4", 1.0, True)])
    # Global では統計列ヘッダを出さない
    assert "mean" not in w.column_headers()
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k "delta or header or column or no_data" -v`
Expected: FAIL（`AttributeError: set_global` ほか）

- [ ] **Step 3: 最小実装を書く**

`cursor_readout.py` を次の方針で書き換える（既存 `set_readings`/`row_texts`/ドラッグ移動は保持しつつ拡張）。import に追記:

```python
from PySide6.QtWidgets import QGridLayout, QLabel, QMenu, QWidget

from valisync.core.statistics.range_stats import StatisticsResult
from valisync.gui.viewmodels.graph_panel_vm import CursorReading, DeltaReading
```

定数とフォーマッタを追記:

```python
_NO_DATA = "データなし"
_STAT_COLS = ("mean", "max", "min", "std", "count")


def _fmt(v: float | None) -> str:
    return _OUT_OF_RANGE if v is None else f"{v:.4g}"


def _fmt_dy(v: float | None) -> str:
    if v is None:
        return _OUT_OF_RANGE
    return f"{v:+.4g}"  # 符号付き


def _fmt_time(t: float) -> str:
    return f"{t:.4g} s"
```

`__init__` 末尾に追記（列選択状態と直近 Delta ペイロードを保持）:

```python
        self._visible_stats: set[str] = set(_STAT_COLS)
        self._col_headers: list[str] = []
        self._header_text: str = ""
        self._last_delta: tuple[float, float, list[DeltaReading]] | None = None
```

`set_readings` を保持しつつ、`set_global` / `set_delta` / introspection / 列メニューを追記:

```python
    def set_global(self, t_a: float, readings: list[CursorReading]) -> None:
        """Global mode: header = ● t_a, columns = [swatch|name|値]."""
        self._last_delta = None
        self._header_text = f"● {_fmt_time(t_a)}"
        self._col_headers = []
        self._rebuild(
            header_cells=[("●", "#f9e2af"), (_fmt_time(t_a), None)],
            col_headers=[],
            rows=[(r.name, r.color, [_fmt(r.value if r.in_range else None)]) for r in readings],
        )

    def set_delta(self, t_a: float, t_b: float, readings: list[DeltaReading]) -> None:
        """Delta mode: header = ● t_a ● t_b · Δt, columns = A値/Δy/<selected stats>."""
        self._last_delta = (t_a, t_b, readings)
        dt = t_b - t_a
        self._header_text = f"● {_fmt_time(t_a)}  ● {_fmt_time(t_b)} · Δt {_fmt_time(dt)}"
        stat_cols = [c for c in _STAT_COLS if c in self._visible_stats]
        self._col_headers = ["A値", "Δy", *stat_cols]
        rows = []
        for r in readings:
            cells = [_fmt(r.value_a if r.in_range else None), _fmt_dy(r.dy)]
            if r.stats.count == 0:
                cells += [_NO_DATA for _ in stat_cols]
            else:
                vals = {
                    "mean": r.stats.mean,
                    "max": r.stats.max,
                    "min": r.stats.min,
                    "std": r.stats.std,
                    "count": float(r.stats.count),
                }
                cells += [
                    (str(r.stats.count) if c == "count" else f"{vals[c]:.4g}")
                    for c in stat_cols
                ]
            rows.append((r.name, r.color, cells))
        self._rebuild(
            header_cells=[("●", "#f9e2af"), (_fmt_time(t_a), None), ("●", "#89b4fa"),
                          (f"{_fmt_time(t_b)} · Δt {_fmt_time(dt)}", None)],
            col_headers=self._col_headers,
            rows=rows,
        )

    def header_text(self) -> str:
        return self._header_text

    def column_headers(self) -> list[str]:
        return list(self._col_headers)

    def visible_stats(self) -> set[str]:
        return set(self._visible_stats)

    def build_column_menu(self) -> QMenu:
        """Checkable menu (5 stat columns) for the 列▾ button — toggles re-render."""
        menu = QMenu(self)
        for c in _STAT_COLS:
            act = menu.addAction(c)
            act.setCheckable(True)
            act.setChecked(c in self._visible_stats)
            act.triggered.connect(lambda checked, col=c: self._toggle_stat(col, checked))
        return menu

    def _toggle_stat(self, col: str, on: bool) -> None:
        if on:
            self._visible_stats.add(col)
        else:
            self._visible_stats.discard(col)
        if self._last_delta is not None:
            self.set_delta(*self._last_delta)  # 再描画
```

`_rebuild`（行/ヘッダ生成の共通化）を追記し、既存 `set_readings` はこの上で実装し直す。`set_readings` 互換のため残すが内部は `_rebuild` 経由:

```python
    def _rebuild(self, header_cells, col_headers, rows) -> None:
        """(re)build the grid: optional column-header row + one row per signal."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._rows = []
        r0 = 0
        if col_headers:
            # 列見出し（name 列の上は空）
            for c, head in enumerate(["", *col_headers]):
                lbl = QLabel(head)
                lbl.setStyleSheet("color:#7f849c; font-size:9px;")
                lbl.setAlignment(
                    Qt.AlignmentFlag.AlignRight if c >= 2 else Qt.AlignmentFlag.AlignLeft
                )
                self._grid.addWidget(lbl, r0, c)
            r0 = 1
        for i, (name, color, cells) in enumerate(rows):
            swatch = QLabel()
            pix = QPixmap(10, 10)
            pix.fill(QColor(color))
            swatch.setPixmap(pix)
            self._grid.addWidget(swatch, r0 + i, 0)
            self._grid.addWidget(QLabel(name), r0 + i, 1)
            for c, text in enumerate(cells):
                v = QLabel(text)
                v.setAlignment(Qt.AlignmentFlag.AlignRight)
                self._grid.addWidget(v, r0 + i, 2 + c)
            self._rows.append((name, " ".join(cells)))
        self.adjustSize()
```

既存 `set_readings` を `_rebuild` 利用に簡約（後方互換・既存 R15 テスト維持）:

```python
    def set_readings(self, readings: list[CursorReading]) -> None:
        """Backward-compatible global readout (no header time)."""
        self._col_headers = []
        self._rebuild(
            header_cells=[],
            col_headers=[],
            rows=[(r.name, r.color, [_fmt(r.value if r.in_range else None)]) for r in readings],
        )
```

> 注: ヘッダ行（時刻・色ドット）の実描画は `set_global`/`set_delta` 内で別レイアウト（例: 上部に水平の `QLabel` 群）に置く。本プランでは `header_text()` を introspection の真実源とし、視覚配置（ドット色・Δt 強調）は実装時に `_header_text` と一致させる（§12 open のレイアウト詳細）。

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -v`
Expected: PASS（既存3 + 新規6）。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout.py
git commit -m "feat(gui): CursorReadout に時刻ヘッダ・Δy/統計列・列選択メニューを追加（R16/R17）"
```

---

## Task 3: GraphPanelView — B 線・トグル・click 撤去・読み取り面配線（Layer A/B）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`
- Test: `tests/gui/test_graph_panel_cursor.py`

**Interfaces:**
- Consumes: Task 1（`vm.toggle_main_cursor`/`toggle_delta`/`set_cursor_b`/`cursor_t_b`/`delta_enabled`/`delta_readings`/`delta_t`）、Task 2（`CursorReadout.set_global`/`set_delta`）。既存 `_cursor_line`/`_sync_cursor_from_vm`/`build_context_menu`/`contextMenuEvent`/`_zone_at`/`ZONE_PLOT`/`_view_boxes`。
- Produces: `_cursor_line_b: pg.InfiniteLine`、コンテキストメニューのチェック式「メインカーソル」「サブカーソル（Δ）」、introspection `delta_line_visible()`/`delta_line_value()`。click 設置の撤去。

**gui-test-plan 分析（Task 3）**
- 変更種別: **入力イベント→ハンドラ**（＋ウィジェット構成）。
- 必要レイヤー: **A=必須**（introspection・build_context_menu 内容）/ **B=必須**（`sendEvent(QContextMenuEvent)` でメニュー実経路、click 撤去の挙動）/ **C=推奨**（Task 4：B 線の実ドラッグ2線ヒットテスト）。
- 入力経路の再現性: コンテキストメニュー＝`sendEvent(QContextMenuEvent)` で実経路再現可（`tests/gui/test_file_browser_view.py::_send_context_menu_event` と同方式、`QMenu.exec` を no-op パッチ）。InfiniteLine 実ドラッグ＝**Layer C 専用**（合成イベント不可）。
- ②実質性: メニュー内容・チェック/グレーアウト・B 線可視・読み取り面列＝自動アサート（Layer A/B）。線の実描画 x と2線掴み分けは Task 4。
- **realgui 掴み点監査: 不要**（frame/grip/軸幅などゾーン幾何は不変。カーソル線追加は軸ストリップのゾーン分類に影響しない）。
- honest layering: `build_context_menu()` 直呼びは Layer A（内容）。実経路は `contextMenuEvent`（`sendEvent`）で起動（Layer B）。click 撤去は handler 挙動＋属性非在で確認。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_cursor.py` 末尾に追記（`_vm_with_signal` ヘルパは既存）:

```python
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QMenu


def _send_context_menu(view) -> None:
    """contextMenuEvent 実経路を起動（QMenu.exec を no-op 化してモーダル回避）。"""
    orig = QMenu.exec

    def _noop(self, *a, **k):
        view._last_menu = self  # スパイ: 構築されたメニューを捕捉
        return None

    QMenu.exec = _noop  # type: ignore[method-assign]
    try:
        pos = QPoint(view.width() // 2, view.height() // 2)
        QApplication.sendEvent(
            view, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, view.mapToGlobal(pos))
        )
    finally:
        QMenu.exec = orig  # type: ignore[method-assign]


def test_context_menu_has_cursor_toggles(qtbot: QtBot, tmp_path):
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    menu = view.build_context_menu()
    labels = [a.text() for a in menu.actions()]
    assert "メインカーソル" in labels
    assert "サブカーソル（Δ）" in labels


def test_sub_toggle_disabled_until_main_on(qtbot: QtBot, tmp_path):
    vm = _vm_with_signal(tmp_path)
    vm.x_range = (0.0, 1.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    sub = next(a for a in view.build_context_menu().actions() if a.text() == "サブカーソル（Δ）")
    assert sub.isEnabled() is False  # main OFF
    vm.toggle_main_cursor(True)
    sub2 = next(a for a in view.build_context_menu().actions() if a.text() == "サブカーソル（Δ）")
    assert sub2.isEnabled() is True


def test_context_menu_real_path_builds_menu(qtbot: QtBot, tmp_path):
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    _send_context_menu(view)
    assert hasattr(view, "_last_menu")
    labels = [a.text() for a in view._last_menu.actions()]
    assert "メインカーソル" in labels


def test_toggling_main_then_delta_shows_both_lines(qtbot: QtBot, tmp_path):
    vm = _vm_with_signal(tmp_path)
    vm.x_range = (0.0, 1.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    vm.toggle_main_cursor(True)
    assert view.cursor_line_visible()
    assert not view.delta_line_visible()
    vm.toggle_delta(True)
    assert view.delta_line_visible()
    assert view.delta_line_value() == pytest.approx(0.75)


def test_plot_click_no_longer_places_cursor(qtbot: QtBot, tmp_path):
    # R15 改訂: 空クリック設置は撤去。属性も挙動も無い。
    vm = _vm_with_signal(tmp_path)
    vm.x_range = (0.0, 1.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    assert not hasattr(view, "_place_cursor_at")
    # ZONE_PLOT での press+release でも cursor_t は None のまま
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    center = QPointF(view.width() / 2, view.height() / 2)

    def _btn(kind):
        return QMouseEvent(
            kind, center, Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )

    view.mousePressEvent(_btn(QMouseEvent.Type.MouseButtonPress))
    view.mouseReleaseEvent(_btn(QMouseEvent.Type.MouseButtonRelease))
    assert vm.cursor_t is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -k "toggle or click or both_lines or real_path" -v`
Expected: FAIL（`delta_line_visible` 無し / メニューにトグル無し / click 撤去前は `_place_cursor_at` 在り）

- [ ] **Step 3: 最小実装を書く**

`__init__` の Global cursor ブロック（`self._cursor_line.sigPositionChanged.connect(...)` の後、`self._readout = ...` の前後）に B 線を追加:

```python
        self._cursor_line_b = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen("#89b4fa", width=2, style=Qt.PenStyle.DashLine),
        )
        self._cursor_line_b.setVisible(False)
        self._cursor_line_b.setZValue(10)
        if self._view_boxes:
            self._view_boxes[0].addItem(self._cursor_line_b, ignoreBounds=True)
        self._cursor_line_b.sigPositionChanged.connect(self._on_cursor_line_b_dragged)
```

`__init__` の click 設置状態 `self._cursor_press_pos: QPointF | None = None` を**削除**。

`_on_vm_change` を置換（`"delta"` も同期へ）:

```python
    def _on_vm_change(self, change: str) -> None:
        if change in ("cursor", "delta"):
            self._sync_cursor_from_vm()
            return
        self.refresh()
```

`_sync_cursor_from_vm` を置換（A+B 両線＋ Global/Delta 読み取り面）:

```python
    def _sync_cursor_from_vm(self) -> None:
        """Reflect A/B cursor + readout from full VM state."""
        t = self.vm.cursor_t
        if t is None:
            self._cursor_line.setVisible(False)
            self._cursor_line_b.setVisible(False)
            self._readout.setVisible(False)
            self._readout_placed = False
            return
        self._suppress_cursor_signal = True
        self._cursor_line.setValue(t)
        if self.vm.cursor_t_b is not None:
            self._cursor_line_b.setValue(self.vm.cursor_t_b)
        self._suppress_cursor_signal = False
        self._cursor_line.setVisible(True)
        if self.vm.delta_enabled and self.vm.cursor_t_b is not None:
            self._cursor_line_b.setVisible(True)
            self._readout.set_delta(t, self.vm.cursor_t_b, self.vm.delta_readings())
        else:
            self._cursor_line_b.setVisible(False)
            self._readout.set_global(t, self.vm.cursor_readings())
        if not self._readout_placed:
            self._readout.move(8, 8)
            self._readout_placed = True
        self._readout.setVisible(True)
        self._readout.raise_()

    def _on_cursor_line_b_dragged(self) -> None:
        if self._suppress_cursor_signal:
            return
        self.vm.set_cursor_b(float(self._cursor_line_b.value()))
```

既存 `_place_cursor_at` メソッドを**削除**。introspection を追記:

```python
    def delta_line_visible(self) -> bool:
        return bool(self._cursor_line_b.isVisible())

    def delta_line_value(self) -> float:
        return float(self._cursor_line_b.value())
```

`mousePressEvent` の `elif zone == ZONE_PLOT: self._cursor_press_pos = event.position()` 分岐を**削除**（X ゾーン処理は不変）。`mouseReleaseEvent` 冒頭の click 設置ブロック（`if self._cursor_press_pos is not None: ...`）を**削除**。

`refresh()` の A 線再アタッチ箇所（`if hasattr(self, "_cursor_line") ...`）の直後に B 線も再アタッチ:

```python
        if hasattr(self, "_cursor_line_b") and self._view_boxes:
            try:
                if self._cursor_line_b.scene() is None:
                    self._view_boxes[0].addItem(self._cursor_line_b, ignoreBounds=True)
            except RuntimeError:
                pass  # C++ object deleted; rebuilt by next init
```

`build_context_menu` の `interp = menu.addMenu("補間方式")` の**直前**にチェック式トグルを追記:

```python
        menu.addSeparator()
        main_act = menu.addAction("メインカーソル")
        main_act.setCheckable(True)
        main_act.setChecked(self.vm.cursor_t is not None)
        main_act.triggered.connect(lambda checked: self.vm.toggle_main_cursor(checked))
        sub_act = menu.addAction("サブカーソル（Δ）")
        sub_act.setCheckable(True)
        sub_act.setChecked(self.vm.delta_enabled)
        sub_act.setEnabled(self.vm.cursor_t is not None)  # メイン ON のときだけ
        sub_act.triggered.connect(lambda checked: self.vm.toggle_delta(checked))
```

- [ ] **Step 4: 回帰テスト更新＋通過確認**

R15 で `_cursor_press_pos`/`_place_cursor_at`/click を参照するテストがあれば削除/更新。
Run: `uv run pytest tests/gui/test_graph_panel_cursor.py tests/gui/test_graph_panel_view.py -v`
Expected: PASS。回帰: `uv run pytest tests/gui/ -q` 全 PASS。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_cursor.py
git commit -m "feat(gui): GraphPanelView に Delta 線・カーソルトグル・読み取り面配線を統合、空クリック設置を撤去（R16/R17・R15.1 改訂）"
```

---

## Task 4: realgui（Layer C）— click 設置撤去・線実ドラッグ再構成・2線ヒットテスト

**Files:**
- Modify: `tests/realgui/test_global_cursor.py`

**Interfaces:**
- Consumes: Task 1–3 の全成果。既存ヘルパ `_skip_unless_real_display`/`_to_phys`/`_at`/`_shown_panel`/`_scene_center`/`_x_span` を再利用。
- Produces: 実経路でしか出ない証拠＝①実ドラッグで A 線が動く（設置はトグル/プログラム経由に再構成）、②**2本の可動 InfiniteLine から B のみを実ヒットテストで掴み、B が動き A は不変**。

**gui-test-plan 分析（Task 4）**
- 変更種別: 入力イベント→ハンドラ（実 OS）。
- 必要レイヤー: **C=必須**（②実質）。
- 入力経路の再現性: InfiniteLine 実ドラッグ＝**Layer C 専用**（QDrag 無しの scene ドラッグ、メインスレッド `_at` ループ＋`processEvents` で駆動可。QDrag を伴う軸移動と違い別スレッド不要 ＝ memory `gui_realgui_drag_qtimer_hang` は QDrag 固有）。click 撤去で**既存2テストの設置手順（中央クリック）が壊れる**ため、設置を `view.vm.toggle_main_cursor(True)` 等プログラム経由へ再構成。
- ②実質性: 「2本の可動線から狙った線を掴めるか」は OS→Qt ヒットテスト＝**Layer A/B 再現不可**。`B.value` 変化だけでなく **`A.value` 不変も assert**（VM 再チェックだけの naive を回避）。スクショ保存のみは禁止。
- ①証拠ゲート: 下記 Step 4 の `/gui-verify` で scoped 実行＋証拠添付。
- honest layering: トグル/列メニュー/B 可視/統計値は Layer A/B で証明済み。realgui は「実ドラッグの線移動」と「2線ヒット分離」のみ（重複させない）。

- [ ] **Step 1: 既存 realgui を改修（click 削除・drag 設置を再構成）**

`tests/realgui/test_global_cursor.py`:
- `test_real_click_places_cursor_at_clicked_x` を**削除**（空クリック設置は撤去された）。
- `test_real_drag_cursor_line_moves_it` の**設置手順を置換**（中央クリック→プログラム的 ON）。冒頭の `_at(px, py, _LDOWN)/_LUP` 設置を次へ:

```python
    view = _shown_panel(qtbot)
    # 設置はトグル経由（空クリック設置は撤去済み）
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible()
    x_before = view.cursor_line_value()
    # A 線の現在位置を起点に右へ実ドラッグ（線上を掴む）
    sx, sy, _ = _scene_center(view)
```

（以降の「線位置から右へドラッグ」ロジックは既存のまま。`_scene_center` の中央 ≒ A の既定 50% に一致するので掴める。）

- [ ] **Step 2: 2 線ヒットテスト realgui を追加**

末尾に追記:

```python
def test_real_drag_sub_cursor_moves_only_b(qtbot: QtBot, tmp_path) -> None:
    """main+delta 表示 → B 線(75%)を実ドラッグ → B が動き A は不変(②: 実ヒットテスト)。"""
    _skip_unless_real_display()
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)  # A=50%
    view.vm.toggle_delta(True)  # B=75%
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible() and view.delta_line_visible()
    a_before = view.cursor_line_value()
    b_before = view.delta_line_value()

    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    # B(75%)の画面位置を起点に、さらに右(85%)へ実ドラッグ
    b_scene_x = rect.x() + rect.width() * 0.75
    sy = rect.y() + rect.height() * 0.5
    tgt_scene_x = rect.x() + rect.width() * 0.85
    gx, gy = _to_phys(view, b_scene_x, sy)
    tx, _ = _to_phys(view, tgt_scene_x, sy)
    _at(gx, gy, _LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        _at(gx + (tx - gx) * k // steps, gy, _MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    _at(tx, gy, _LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "sub_cursor_dragged.png")
        )
    assert view.delta_line_value() > b_before  # B は右へ動いた
    assert view.cursor_line_value() == pytest.approx(a_before)  # A は不変
```

- [ ] **Step 3: realgui 実行**

Run: `uv run pytest --realgui tests/realgui/test_global_cursor.py -v`
Expected: PASS（改修1 + 追加1 = 2件）。実ディスプレイ + Windows 必須。

- [ ] **Step 4: `/gui-verify` 証拠ゲート（①・ユーザー要請で明示）**

```
- [ ] /gui-verify を実行（scoped: tests/realgui/test_global_cursor.py）し、
      pass ログ＋スクショ（cursor_dragged.png / sub_cursor_dragged.png）を証拠添付。
- [ ] 環境制約（非 Windows・ディスプレイ無し）で実行不可なら「ゲート未充足」扱い
      （skipped を緑＝検証済みと誤認しない）。
```

`/gui-verify` で scoped 実行を自動化する。

- [ ] **Step 5: コミット**

```bash
git add tests/realgui/test_global_cursor.py
git commit -m "test(realgui): click 設置テストを撤去、A 線ドラッグを再構成、B 線の2線ヒットテストを追加（R16・R15.1 改訂・Layer C）"
```

---

## Task 5: ドキュメント反映＋最終検証ゲート

**Files:**
- Modify: `docs/roadmap.md` / `CLAUDE.md`（Phase 表）/ 設計 spec ステータス行。

**gui-test-plan 分析（Task 5）**: 非 GUI（ドキュメント）。Layer A のみ・realgui 不要・標準確認。

- [ ] **Step 1: ドキュメント更新**

- `CLAUDE.md` Phase 表 `valisync-gui-analysis` 行: 「増分B=R16 Delta+R17 範囲統計 完了（PR #__）」に更新。
- `docs/roadmap.md`: analysis の B 完了・残 C(R14) を反映。
- 設計 spec ステータス行: 増分B 実装完了を追記。

- [ ] **Step 2: 最終検証ゲート（merge 前・全充足が条件）**

`docs/gui-testing-layers.md` の merge ゲート（realgui 単独では不可）に従う:

```
- [ ] (a) full headless: `uv run pytest` が 0 failed / 0 errors（Layer A/B・テスト間汚染も検知）
- [ ] (b) realgui 証拠: Task 4 Step 4 の /gui-verify ゲート充足（pass ログ＋スクショ）
- [ ] (c) ruff check / ruff format --check / mypy src/ 全 pass
- [ ] (d) push → gh pr create → CI 緑
```

- [ ] **Step 3: コミット＋ PR**

```bash
git add docs/roadmap.md CLAUDE.md docs/superpowers/specs/2026-06-29-gui-analysis-cursor-offset-design.md
git commit -m "docs: 増分B（R16 Delta+R17 範囲統計）完了を Phase 表/roadmap/spec に反映"
```
その後 `superpowers:finishing-a-development-branch` で PR 化。

---

## Self-Review

**1. Spec coverage（設計 §2/§4/§5/§6/§9 と照合）:**
- R16 Delta（加算式2本目・Δt/Δy）→ Task1（`cursor_t_b`/`delta_t`/`dy`）＋Task3（B 線・トグル）✓
- R16.1 サブ表示トグル＋メイン依存 → Task1（`toggle_delta` ガード）＋Task3（メニュー enable）＋realgui 不要（Layer A/B）✓
- R16.4 B 線ドラッグ移動 → Task3（`set_cursor_b` 配線）＋Task4（実ドラッグ2線ヒット）✓
- R17 範囲統計（mean/max/min/std/count・Session 委譲・A<B 正規化・再計算）→ Task1（`delta_readings`/`compute_statistics`）✓
- R17.5 データなし（count=0）→ Task1（NaN/0）＋Task2（"データなし"）✓ / 範囲外 → Task1（None）＋Task2（"範囲外"）✓
- §6 時刻ヘッダ常時表示（Global=A / Delta=A・B・Δt、色ドット）→ Task2（`set_global`/`set_delta`/`header_text`）✓
- §6 8列フラット＋「列▾」選択（既定全列・非永続）→ Task2（`build_column_menu`/`visible_stats`）✓
- §4/§5 R15.1 改訂（空クリック設置撤去・トグル＋既定位置・移動は D&D のみ・Reset 不使用）→ Task1（`toggle_main_cursor`）＋Task3（click 撤去・トグル）＋Task4（realgui click 削除）✓
- §8 A は兄弟同期・Delta は局所 → `set_cursor`=notify"cursor"（AreaVM 配信）/ delta=notify"delta"（非配信）✓

**2. Placeholder scan:** 各ステップに実テスト/実装コードを記載。realgui は実在ヘルパで具体化。TBD/TODO なし（CursorReadout ヘッダの視覚配置のみ §12 open に委譲＝introspection の真実源 `header_text` は確定）。

**3. Type consistency:** `DeltaReading(name,color,value_a,dy,stats,in_range)`・`toggle_main_cursor(on)`・`toggle_delta(on)`・`set_cursor_b(t)`・`delta_t`・`delta_readings()`・`CursorReadout.set_global/set_delta/header_text/column_headers/visible_stats/build_column_menu`・`delta_line_visible/value`・`StatisticsResult(mean,max,min,std,count)` を全タスクで一貫使用。

**GUI テストレイヤー総括（/gui-test-plan 反映）:** Task1=A。Task2=A/B。Task3=A/B（トグル=contextMenuEvent 実経路、click 撤去=挙動＋属性非在）。Task4=C（②実質＝2線ヒットテスト＋実ドラッグ、①証拠ゲート＝/gui-verify 明示）。Task5=docs。merge ゲートは full pytest 0 errors ＋ realgui 証拠 ＋ CI 緑（realgui 単独不可）。
