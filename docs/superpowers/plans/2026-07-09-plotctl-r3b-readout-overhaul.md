# 増分3b: readout 刷新（PC-10/11/12/16/17/18）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CursorReadout（カーソル読み取り面）を刷新し、単位表示・可変精度・統計列選択・TSV コピー・常時 ✕・移動アフォーダンスを備えた計測 UI にする。

**Architecture:** 精度と単位は VM を source of truth にする（`value_precision` は既存 `visible_stat_cols` と同格の VM 状態、単位は `Signal.metadata` から readings へ注入）。CursorReadout は表示専用ウィジェットのまま（core 非依存）で、精度・単位・クリアは View 経由の callback / 引数で受け取る。散在フォーマッタを精度パラメータ付き単一フォーマッタへ集約し、TSV は構造化セルから生成する。

**Tech Stack:** Python 3.13 / PySide6（Qt6）/ pyqtgraph / MVVM（View → ViewModel → Session）。

## Global Constraints

- **MVVM 境界**: View → VM のみ。CursorReadout は core を import しない（単位は `str`、精度は `int` を View から受領）。精度変更→`vm.set_value_precision(p)`、統計列→既存 `vm.set_visible_stats(cols)`、クリア→`vm.toggle_main_cursor(False)`。
- **精度の適用範囲**（spec §8）: **値・統計列（mean/max/min/std）のみ**。`count` は整数のまま、時刻表示（●A/●B/Δt ヘッダ）は既存 `_fmt_time` の固定精度を維持。TSV コピーも同規則。既定精度 **6**（4/6/8 切替・DP9 承認済み）。
- **単位表示**（DP8）: 信号名の脇に 1 回 `[km/h]`（淡色 `#7f849c`）。1 行内の全列は同一単位。`sig.metadata.get("unit", "") if sig.metadata else ""`（既存パターン graph_panel_vm.py:227・channel_browser_vm.py:87）。
- **readout コントロール配置**（DP10）: **✕ のみ常時表示**（右上・クリック=全消去）。残り（統計列▸／精度▸／表をコピー／カーソルを消す）は右クリックメニュー。
- **コピーのスコープ**（DP12）: 表示中の列・現在精度・単位込みの **TSV をクリップボードへ**（ファイル保存なし）。
- **カーソル消去スコープ**（spec §4.3・§10）: readout ✕・readout メニュー「カーソルを消す」= **全消去**（`toggle_main_cursor(False)` 経由・A/B/Δ を落とす既存不変条件）。
- **disabled メニュー項目のツールチップ**: `menu.setToolTipsVisible(True)` を併設（QMenu 既定は QAction ツールチップ非表示 → 文字列 assert だけの Layer B は false-green・spec §5 注記）。
- **3a 繰越 followup を同時解消**: `CursorReadout._last_delta` を interp_label/precision 込みへ拡張し、legacy stat-toggle 再描画で欠落しないようにする（memory `followup_readout_last_delta_interp_label`）。
- **品質ゲート（コミット前に全通過必須）**: `uv run pytest`（exit 0・0 errors）／`uv run ruff check`／`uv run ruff format --check`／`uv run mypy src/`。
- **ruff 注意**: Python の文字列/コメント/docstring 内の全角記号（（）／＋・）は RUF001/002/003 を誘発 → ASCII 等価へ。ただし**ユーザー向け日本語ラベル文字列**（「表をコピー」「カーソルを消す」「統計列」「精度」等）は全角のまま維持。`§` は許容。
- **realgui は実 OS 入力のみ**（`_realgui_input.at()`/`key()`）。合成 `qtbot.mouseClick`/`QTest`/`trigger()` は Layer C 契約ガード `tests/gui/test_realgui_layer_c_contract.py` が CI で落とす。スクショは `QT_QPA_PLATFORM=windows`。

## File Structure

- `src/valisync/gui/viewmodels/graph_panel_vm.py`: `value_precision` 状態＋`set_value_precision`、`CursorReading`/`DeltaReading` に `unit` 追加＋`cursor_readings`/`delta_readings` で注入。
- `src/valisync/gui/views/cursor_readout.py`: 精度パラメータ付き単一フォーマッタ、単位表示（DP8）、構造化セル保持＋`table_tsv()`、✕ ボタン＋移動アフォーダンス＋クリア callback、右クリックメニュー`build_readout_menu`＋精度/コピー/クリア callback、`_last_delta` 拡張。
- `src/valisync/gui/views/graph_panel_view.py`: `_sync_cursor_from_vm` から precision を渡す、readout の `_on_clear`/`_on_precision`/copy 配線、サブカーソルメニュー項目 disabled 時ツールチップ＋`setToolTipsVisible`。
- Tests: `tests/gui/test_graph_panel_vm.py`（Layer A）・`tests/gui/test_cursor_readout.py`／`test_cursor_readout_diff.py`（Layer B）・`tests/gui/test_graph_panel_cursor.py`（View 統合 Layer B）・`tests/realgui/test_readout_realclick.py`（新規 Layer C）。

---

## Task 1: VM — 精度状態＋単位注入（Layer A）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`CursorReading`:66-74・`DeltaReading`:77-87 に `unit` 追加／`__init__` の状態群 :156 付近に `value_precision`／`set_visible_stats`:1028 付近の隣に `set_value_precision`／`cursor_readings`:905・`delta_readings`:1044 で unit 注入）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Consumes（既存）: `self.visible_stat_cols`・`self._notify("cursor")`／`_notify("delta")`・`self._signal_map()`・`sig.metadata`・`self._plotted`（`entry.signal_key`/`entry.color`/`entry.visible`）・`_resolve_value_label`。
- Produces:
  - `GraphPanelVM.value_precision: int`（既定 6）
  - `GraphPanelVM.set_value_precision(p: int) -> None`（設定＋`_notify("cursor")`）
  - `CursorReading.unit: str = ""` / `DeltaReading.unit: str = ""`
  - `cursor_readings()`/`delta_readings()` が各 reading に unit 注入

**GUI テスト分析（gui-test-plan）:** 純 VM ロジック → **Layer A のみ**。realgui 不要。実質性: 既定 6・set で値変更＋notify・unit が metadata から入る（metadata None でも空文字）を自動アサート。

- [ ] **Step 1: 失敗するテストを書く（精度状態）**

`tests/gui/test_graph_panel_vm.py` に追記（既存の VM フィクスチャ `_register_signal` 等に合わせる）:

```python
def test_value_precision_defaults_to_6(tmp_path):
    vm = _loaded_vm(tmp_path)
    assert vm.value_precision == 6


def test_set_value_precision_updates_and_notifies(tmp_path):
    vm = _loaded_vm(tmp_path)
    seen: list[str] = []
    vm.subscribe(lambda change: seen.append(change))
    vm.set_value_precision(8)
    assert vm.value_precision == 8
    assert "cursor" in seen
```

（`_loaded_vm` は既存ヘルパを流用。無ければ `_loaded_session`＋`GraphPanelVM(session)`＋`_register_signal` の既存作法で 1 信号を登録して返す小ヘルパを test モジュール先頭に追加。`subscribe` は既存の通知購読 API 名に合わせる〔`_notify` の購読側。既存テストが使う購読メソッド名を grep して合わせる〕。）

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k value_precision -v`
Expected: FAIL（`value_precision` 属性なし → AttributeError）

- [ ] **Step 3: 精度状態を実装**

`graph_panel_vm.py` の `__init__`、`self.visible_stat_cols` 定義（:156 付近）の直後に:

```python
        # 値・統計列の表示桁数（source of truth は VM。4/6/8 切替・既定 6・DP9）。
        # 時刻ヘッダと count には適用しない（spec 増分3 readout 刷新）。
        self.value_precision: int = 6
```

`set_visible_stats`（:1028 付近）の隣に:

```python
    def set_value_precision(self, p: int) -> None:
        """Set the displayed value/stat precision and notify so the readout re-renders."""
        self.value_precision = p
        self._notify("cursor")
```

- [ ] **Step 4: 通過を確認（精度）**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k value_precision -v`
Expected: PASS（2 件）

- [ ] **Step 5: 失敗するテストを書く（unit 注入）**

`tests/gui/test_graph_panel_vm.py` に追記。単位付き信号を登録する必要があるため、`Signal` を metadata 付きでハンドビルドする既存作法に合わせる:

```python
def test_cursor_readings_inject_unit(tmp_path):
    vm = _loaded_vm(tmp_path)  # 1 信号登録済み
    vm.x_range = (0.0, 1.0)
    vm.set_cursor(0.5)
    readings = vm.cursor_readings()
    assert readings, "expected at least one reading"
    # 登録信号の metadata['unit'] が各 reading に入る（未設定なら空文字）
    assert all(hasattr(r, "unit") for r in readings)
    assert readings[0].unit == _expected_unit_of_loaded_signal
```

（`_loaded_vm` の信号を metadata に `unit` を持つ形で構築する。CSV ローダー由来だと unit 空になるので、**単位付き `Signal` をハンドビルドして `vm` に登録するヘルパ** `_register_signal_with_unit(vm, unit="km/h")` を追加し `_expected_unit_of_loaded_signal = "km/h"` とする。ハンドビルド作法は既存 `test_graph_panel_vm.py` の `Signal(name=, timestamps=, values=, file_format=, bus_type=, source_file=, metadata={"unit": "km/h"})` に倣う。Signal のシグネチャに metadata 引数がある前提で grep 確認し、無ければ生成後 `sig.metadata = {"unit": "km/h"}` で付与。）

- [ ] **Step 6: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k readings_inject_unit -v`
Expected: FAIL（`CursorReading` に `unit` 属性なし）

- [ ] **Step 7: dataclass に unit 追加＋注入**

`CursorReading`（:66-74）:

```python
@dataclass
class CursorReading:
    """1 信号のカーソル位置読み取り(Global_Cursor 用)。value=None は範囲外。"""

    name: str
    color: str
    value: float | None
    in_range: bool
    label: str | None = None  # value_labels 命中時のみ (LD-07)
    unit: str = ""  # metadata['unit'] (PC-11)
```

`DeltaReading`（:77-87）に同様に末尾へ `unit: str = ""  # metadata['unit'] (PC-11)` を追加。

`cursor_readings()`（:905）内、単位を 1 度計算して両分岐へ渡す。`for entry in self._plotted:` ループの `sig = sig_map.get(...)` 直後を:

```python
            sig = sig_map.get(entry.signal_key)
            if sig is None:
                out.append(CursorReading(entry.signal_key, entry.color, None, False))
                continue
            unit = sig.metadata.get("unit", "") if sig.metadata else ""
            val = self._session.interpolate(sig, self.cursor_t, self.interp_method)
            out.append(
                CursorReading(
                    entry.signal_key,
                    entry.color,
                    val,
                    val is not None,
                    label=_resolve_value_label(sig, val),
                    unit=unit,
                )
            )
```

`delta_readings()`（:1044）内、`sig is None` でない分岐（:1078 付近）の `va = ...` 直前に `unit = sig.metadata.get("unit", "") if sig.metadata else ""` を挿入し、末尾の `DeltaReading(...)` に `unit=unit` を追加（`label=_resolve_value_label(sig, va)` の次）。

- [ ] **Step 8: 通過を確認＋フルスイート**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "value_precision or readings_inject_unit" -v`
Expected: PASS

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 9: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "feat(gui): readout 精度状態(value_precision)＋readings への単位注入(PC-11/PC-16 土台)"
```

---

## Task 2: Readout — 精度フォーマッタ集約＋単位表示（PC-11/PC-16）（Layer B）

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`（散在フォーマッタ `_fmt`:23/`_fmt_dy`:33/inline stat_map:190-197 を精度付き単一フォーマッタへ／`set_global`:127・`set_delta`:154 に `precision` 引数＋`_last_delta` 拡張／`_rebuild`系に unit を通し名前脇 `[unit]` 淡色表示）
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`_sync_cursor_from_vm`:1377/1385 の set_delta/set_global 呼び出しに `precision=self.vm.value_precision`）
- Test: `tests/gui/test_cursor_readout.py`・`tests/gui/test_cursor_readout_diff.py`

**Interfaces:**
- Consumes: Task 1 の `CursorReading.unit`/`DeltaReading.unit`・`GraphPanelVM.value_precision`。既存 `_STAT_COLS`・`_rebuild`/`_full_rebuild`/`_update_in_place`・`row_texts()`。
- Produces:
  - `_fmt_value(v, precision)` / `_fmt_labeled(v, label, precision)` / `_fmt_dy(v, precision)`（精度パラメータ付き）
  - `set_global(t_a, readings, interp_label="", precision=6)` / `set_delta(t_a, t_b, readings, interp_label="", precision=6)`
  - `_last_delta: tuple[float, float, list[DeltaReading], str, int] | None`（t_a, t_b, readings, interp_label, precision）
  - rows に unit を通し、名前セルは unit があれば `名前 [unit]`（unit 淡色 RichText）。`row_texts()` の name も `名前 [unit]` を反映。

**GUI テスト分析（gui-test-plan）:** ウィジェット表示（ほぼ Layer A 相当の純ウィジェット）→ **Layer B**。実質性: 精度切替で値の桁数が変わる（count は不変・時刻ヘッダ不変）／unit が名前脇に出る／`_last_delta` 再描画で interp_label が保持されることを自動アサート。honest layering note: 既定精度が 4g→6g へ上がるため既存 readout テストの期待値更新が必要（DP9 承認済み・退行ではない）。

- [ ] **Step 1: 失敗するテストを書く（精度・unit・interp 保持）**

`tests/gui/test_cursor_readout.py` に追記:

```python
def test_precision_controls_value_digits(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(
        0.0, [CursorReading("csv::a", "#fff", 1.23456789, True, unit="km/h")],
        precision=4,
    )
    v4 = ro.row_texts()[0][1]
    ro.set_global(
        0.0, [CursorReading("csv::a", "#fff", 1.23456789, True, unit="km/h")],
        precision=8,
    )
    v8 = ro.row_texts()[0][1]
    assert v4 == "1.235"          # .4g
    assert v8 == "1.2345679"      # .8g
    assert v4 != v8               # 精度が効いている


def test_unit_shown_beside_name(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(0.0, [CursorReading("spd", "#fff", 1.0, True, unit="km/h")])
    assert "[km/h]" in ro.row_texts()[0][0]  # 名前セルに単位


def test_stat_toggle_reretains_interp_label(qtbot):
    from valisync.core.analysis import StatisticsResult
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import DeltaReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    stats = StatisticsResult(mean=1.0, max=2.0, min=0.0, std=0.5, count=3)
    ro.set_delta(
        0.0, 1.0, [DeltaReading("a", "#fff", 1.0, 0.5, stats, True, unit="km/h")],
        interp_label="線形", precision=6,
    )
    # legacy stat-toggle 再描画（_on_stat_toggled 未 wire）で interp_label を欠落しない
    ro._toggle_stat("count", False)
    assert "線形" in ro.header_text()
```

（`StatisticsResult` の import 元は既存 `test_cursor_readout_diff.py` に合わせる。）

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k "precision_controls or unit_shown or reretains_interp" -v`
Expected: FAIL（`set_global` が `precision`/`unit` を扱わない・`_toggle_stat` 再描画で interp 欠落）

- [ ] **Step 3: 精度フォーマッタへ集約**

`cursor_readout.py` 冒頭のフォーマッタ群（:23-40）を差し替え:

```python
_DEFAULT_PRECISION = 6


def _fmt_value(v: float | None, precision: int = _DEFAULT_PRECISION) -> str:
    return _OUT_OF_RANGE if v is None else f"{v:.{precision}g}"


def _fmt_labeled(
    v: float | None, label: str | None, precision: int = _DEFAULT_PRECISION
) -> str:
    """value_labels 命中時は value (ラベル) 形式で併記する (LD-07)。"""
    base = _fmt_value(v, precision)
    return f"{base} ({label})" if label else base


def _fmt_dy(v: float | None, precision: int = _DEFAULT_PRECISION) -> str:
    if v is None:
        return _OUT_OF_RANGE
    return f"{v:+.{precision}g}"  # 符号付き


def _fmt_time(t: float) -> str:
    return f"{t:.4g} s"  # 時刻は固定精度（精度切替の対象外・spec 増分3）
```

（旧 `_fmt` の呼び出し元は `_fmt_labeled` のみ → 集約で削除。`_fmt_labeled` は `_fmt_value` を呼ぶ。）

- [ ] **Step 4: `set_global`/`set_delta` に precision＋unit＋`_last_delta` 拡張**

`_last_delta` の型注釈（:97）を:

```python
        self._last_delta: (
            tuple[float, float, list[DeltaReading], str, int] | None
        ) = None
```

`set_global`（:127）を:

```python
    def set_global(
        self,
        t_a: float,
        readings: list[CursorReading],
        interp_label: str = "",
        precision: int = _DEFAULT_PRECISION,
    ) -> None:
        """Global mode: header = (dot) t_a [ - interp], columns = [swatch|name|値]."""
        self._last_delta = None
        self._precision = precision
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
                    r.unit,
                    r.color,
                    [_fmt_labeled(r.value if r.in_range else None, r.label, precision)],
                )
                for r in readings
            ],
        )
```

`set_delta`（:154）を（stat_map と cells を精度付きへ・rows に unit を通す・`_last_delta` に 5 要素保存）:

```python
    def set_delta(
        self,
        t_a: float,
        t_b: float,
        readings: list[DeltaReading],
        interp_label: str = "",
        precision: int = _DEFAULT_PRECISION,
    ) -> None:
        """Delta mode: header = (dot)t_a (dot)t_b Dt [ - interp], columns = A値/Dy/<stats>."""
        self._last_delta = (t_a, t_b, readings, interp_label, precision)
        self._precision = precision
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
                _fmt_labeled(r.value_a if r.in_range else None, r.label, precision),
                _fmt_dy(r.dy, precision),
            ]
            if r.stats.count == 0:
                cells += [_NO_DATA for _ in stat_cols]
            else:
                stat_map: dict[str, str] = {
                    "mean": f"{r.stats.mean:.{precision}g}",
                    "max": f"{r.stats.max:.{precision}g}",
                    "min": f"{r.stats.min:.{precision}g}",
                    "std": f"{r.stats.std:.{precision}g}",
                    "count": str(r.stats.count),  # count は整数のまま
                }
                cells += [stat_map[c] for c in stat_cols]
            rows.append((r.name, r.unit, r.color, cells))
        self._rebuild(col_headers=self._col_headers, rows=rows)
```

`__init__` に精度キャッシュを追加（`self._last_delta = None` の隣・:97 付近）:

```python
        self._precision: int = _DEFAULT_PRECISION
```

`set_readings`（R15 後方互換・:105）の rows も 4-tuple 化（unit は空）:

```python
        self._rebuild(
            col_headers=[],
            rows=[
                (r.name, r.unit, r.color, [_fmt_labeled(r.value if r.in_range else None, r.label)])
                for r in readings
            ],
        )
```

- [ ] **Step 5: rows を 4-tuple（name, unit, color, cells）へ拡張し、名前脇に単位を淡色表示**

`_rebuild`（:273）・`_full_rebuild`（:288）・`_update_in_place`（:338）の rows 型を `list[tuple[str, str, str, list[str]]]`（name, unit, color, cells）へ。

`_rebuild`:

```python
    def _rebuild(
        self,
        col_headers: list[str],
        rows: list[tuple[str, str, str, list[str]]],
    ) -> None:
        """構造不変なら差分更新、構造が変わったら全再構築(RN-06)。"""
        sig = (
            tuple(col_headers),
            tuple((name, unit, len(cells)) for name, unit, _color, cells in rows),
        )
        if sig == self._layout_sig and len(rows) == len(self._value_labels):
            self._update_in_place(rows)
        else:
            self._full_rebuild(col_headers, rows, sig)
```

`_layout_sig` 型注釈（:83）を `tuple[tuple[str, ...], tuple[tuple[str, str, int], ...]] | None` へ更新。

`_full_rebuild` の行生成ループ（:318 の `for i, (name, color, cells) ...`）を:

```python
        for i, (name, unit, color, cells) in enumerate(rows):
            swatch = QLabel()
            pix = QPixmap(10, 10)
            pix.fill(QColor(color))
            swatch.setPixmap(pix)
            self._grid.addWidget(swatch, r0 + i, 0)
            name_lbl = QLabel()
            if unit:
                name_lbl.setTextFormat(Qt.TextFormat.RichText)
                name_lbl.setText(
                    f'{name} <span style="color:#7f849c">[{unit}]</span>'
                )
            else:
                name_lbl.setText(name)
            self._grid.addWidget(name_lbl, r0 + i, 1)
            vlabels: list[QLabel] = []
            for c, text in enumerate(cells):
                v = QLabel(text)
                v.setAlignment(Qt.AlignmentFlag.AlignRight)
                self._grid.addWidget(v, r0 + i, 2 + c)
                vlabels.append(v)
            self._value_labels.append(vlabels)
            self._swatch_labels.append(swatch)
            self._row_colors.append(color)
            disp_name = f"{name} [{unit}]" if unit else name
            self._rows.append((disp_name, " ".join(cells)))
            self._row_cells.append((disp_name, list(cells)))
```

`_full_rebuild` 冒頭のリセット群（:301-304 の `self._rows = []` 付近）に `self._row_cells = []` を追加。`__init__` にも `self._row_cells: list[tuple[str, list[str]]] = []` を宣言（`self._rows` 宣言 :77 の隣）。

`_update_in_place`（:338）の署名を `rows: list[tuple[str, str, str, list[str]]]` へ、ループを:

```python
        for i, (name, unit, color, cells) in enumerate(rows):
            for c, text in enumerate(cells):
                self._value_labels[i][c].setText(text)
            if self._row_colors[i] != color:
                pix = QPixmap(10, 10)
                pix.fill(QColor(color))
                self._swatch_labels[i].setPixmap(pix)
                self._row_colors[i] = color
            disp_name = f"{name} [{unit}]" if unit else name
            self._rows[i] = (disp_name, " ".join(cells))
            self._row_cells[i] = (disp_name, list(cells))
        self.adjustSize()
```

`_toggle_stat`（:249）の legacy 再描画 `self.set_delta(*self._last_delta)` は `_last_delta` が 5-tuple になったため、interp_label/precision も渡る（位置引数展開で `set_delta(t_a, t_b, readings, interp_label, precision)`）。**修正不要**（5-tuple → 5 位置引数）。

- [ ] **Step 6: View から precision を渡す**

`graph_panel_view.py` `_sync_cursor_from_vm`（:1377/1385）の set_delta/set_global 呼び出しに `precision` を追加:

```python
            self._readout.set_delta(
                t,
                self.vm.cursor_t_b,
                self.vm.delta_readings(),
                interp_label=_INTERP_LABELS.get(self.vm.interp_method, ""),
                precision=self.vm.value_precision,
            )
        else:
            self._cursor_line_b.setVisible(False)
            self._readout.set_global(
                t,
                self.vm.cursor_readings(),
                interp_label=_INTERP_LABELS.get(self.vm.interp_method, ""),
                precision=self.vm.value_precision,
            )
```

- [ ] **Step 7: 既存 readout テストの期待値を 6g 既定へ更新**

`tests/gui/test_cursor_readout.py`・`test_cursor_readout_diff.py` の値 assert のうち、`precision` 未指定（既定 6）で `.4g` を期待している箇所を `.6g` へ更新（DP9 で既定引き上げ承認済み）。まず Run で赤箇所を特定:

Run: `uv run pytest tests/gui/test_cursor_readout.py tests/gui/test_cursor_readout_diff.py -v`
Expected: 精度既定変更で値 assert が数件 FAIL → 各期待値を実際の `.6g` 出力へ更新（`count`・時刻ヘッダは不変なので触らない）。

- [ ] **Step 8: 通過を確認＋フルスイート**

Run: `uv run pytest tests/gui/test_cursor_readout.py tests/gui/test_cursor_readout_diff.py -v`
Expected: PASS

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 9: コミット**

```bash
git add src/valisync/gui/views/cursor_readout.py src/valisync/gui/views/graph_panel_view.py tests/gui/test_cursor_readout.py tests/gui/test_cursor_readout_diff.py
git commit -m "feat(gui): readout を精度パラメータ付き単一フォーマッタ化＋単位淡色表示（PC-11/PC-16）"
```

---

## Task 3: Readout — 構造化 TSV シリアライズ（PC-10 機構）（Layer B）

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`（`table_tsv()` 追加。`_row_cells`〔Task 2 で導入〕から構築）
- Test: `tests/gui/test_cursor_readout.py`

**Interfaces:**
- Consumes: Task 2 の `self._row_cells: list[tuple[str, list[str]]]`（表示名込み・表示整形済みセル）・`self._col_headers`。
- Produces: `CursorReadout.table_tsv() -> str`（1 行目=ヘッダ〔`信号` ＋ 列見出し。global は `値`〕・以降=各行 `表示名\tセル...`。表示中の列・現在精度・単位を反映）。

**GUI テスト分析（gui-test-plan）:** 純ウィジェット整形 → **Layer B**（Layer A 相当）。実質性: TSV がタブ区切りで表示中の列/精度/単位を反映することを文字列 assert。クリップボード実配線は Task 5（メニューの「表をコピー」）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_cursor_readout.py` に追記:

```python
def test_table_tsv_global(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(
        0.0,
        [
            CursorReading("spd", "#fff", 1.5, True, unit="km/h"),
            CursorReading("rpm", "#fff", 800.0, True),
        ],
        precision=6,
    )
    tsv = ro.table_tsv()
    lines = tsv.splitlines()
    assert lines[0].split("\t") == ["信号", "値"]
    assert lines[1].split("\t") == ["spd [km/h]", "1.5"]
    assert lines[2].split("\t") == ["rpm", "800"]


def test_table_tsv_delta_reflects_visible_stats(qtbot):
    from valisync.core.analysis import StatisticsResult
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import DeltaReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.sync_visible_stats({"mean"})   # count 等を非表示
    stats = StatisticsResult(mean=2.0, max=3.0, min=1.0, std=0.5, count=4)
    ro.set_delta(
        0.0, 1.0, [DeltaReading("a", "#fff", 1.0, 0.5, stats, True)],
        precision=6,
    )
    header = ro.table_tsv().splitlines()[0].split("\t")
    assert header == ["信号", "A値", "Δy", "mean"]  # 表示中の列のみ
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k table_tsv -v`
Expected: FAIL（`table_tsv` 未定義）

- [ ] **Step 3: `table_tsv()` を実装**

`row_texts()`（:215 付近）の隣に追加:

```python
    def table_tsv(self) -> str:
        """表示中の列・現在精度・単位を反映した TSV を返す (PC-10)。

        1 行目はヘッダ（信号列＋データ列見出し。global モードは列見出しが空なので
        単一の 値 列）。以降は各行 表示名(単位込み) ＋ 各セル。_row_cells は
        _rebuild 時点の表示整形済みデータ（精度・単位が既に反映済み）。
        """
        data_headers = self._col_headers if self._col_headers else ["値"]
        lines = ["\t".join(["信号", *data_headers])]
        for disp_name, cells in self._row_cells:
            lines.append("\t".join([disp_name, *cells]))
        return "\n".join(lines)
```

- [ ] **Step 4: 通過を確認＋フルスイート**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k table_tsv -v`
Expected: PASS（2 件）

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout.py
git commit -m "feat(gui): readout の構造化 TSV シリアライズ table_tsv（PC-10 機構）"
```

---

## Task 4: Readout — 常時 ✕＋移動アフォーダンス＋クリア配線（PC-17/PC-18）（Layer B）

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`（`__init__` のヘッダ行を HBox 化して ✕ ボタン追加／`_on_clear` callback／`setCursor(MOVE)`／`_clear_cursors`）
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`_readout._on_clear = lambda: self.vm.toggle_main_cursor(False)`／サブカーソルメニュー項目 disabled 時 `setToolTip`＋`setToolTipsVisible(True)`）
- Test: `tests/gui/test_cursor_readout.py`・`tests/gui/test_graph_panel_cursor.py`

**Interfaces:**
- Consumes: `cursor_shapes.cursor`/`CursorKind.MOVE`・`vm.toggle_main_cursor(False)`。
- Produces:
  - `CursorReadout._on_clear: Callable[[], None] | None`（View が wire）
  - ✕ ボタン（右上・クリック → `_on_clear`）・`close_button()` introspection
  - readout 本体に移動カーソル（`setCursor(cursor(CursorKind.MOVE))`）・✕ ボタンは `PointingHandCursor`

**GUI テスト分析（gui-test-plan）:** ウィジェット構成＋入力→callback → **Layer B**（✕ の実 OS クリックは Task 6）。実質性: ✕ が存在・クリックで `_on_clear` 発火・View 統合で VM 全消去（cursor_t が None）・本体カーソルが SizeAll。honest layering note: ✕ の合成 click は callback 発火の Layer B 証拠、実 OS クリックは Task 6。

- [ ] **Step 1: 失敗するテストを書く（✕）**

`tests/gui/test_cursor_readout.py` に追記:

```python
def test_close_button_fires_on_clear(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    fired: list[bool] = []
    ro._on_clear = lambda: fired.append(True)
    ro.set_global(0.0, [CursorReading("a", "#fff", 1.0, True)])
    ro.close_button().click()
    assert fired == [True]


def test_readout_has_move_cursor(qtbot):
    from PySide6.QtCore import Qt
    from valisync.gui.views.cursor_readout import CursorReadout

    ro = CursorReadout()
    qtbot.addWidget(ro)
    assert ro.cursor().shape() == Qt.CursorShape.SizeAllCursor
```

View 統合（全消去）は `tests/gui/test_graph_panel_cursor.py` に:

```python
def test_readout_close_clears_all_cursors(qtbot):
    view = _shown_cursor_panel(qtbot)
    view.vm.x_range = (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    view.vm.toggle_delta(True)
    assert view.vm.cursor_t is not None
    view._readout.close_button().click()
    assert view.vm.cursor_t is None            # 全消去（A/B/Δ）
    assert view._readout.isHidden()
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k "close_button or move_cursor" tests/gui/test_graph_panel_cursor.py -k readout_close -v`
Expected: FAIL（`close_button` 未定義・カーソル未設定）

- [ ] **Step 3: ✕ ボタン＋移動アフォーダンスを実装**

`cursor_readout.py` の import に追加:

```python
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.views.cursor_shapes import CursorKind, cursor
```

`__init__` のヘッダ生成（:64-68）を、ヘッダと ✕ を横並びにする HBox へ差し替え:

```python
        # Header row: time-position label (left) + always-visible close ✕ (right).
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        self._header = QLabel()
        self._header.setTextFormat(Qt.TextFormat.RichText)
        self._header.hide()
        header_row.addWidget(self._header)
        header_row.addStretch(1)
        self._close_btn = QToolButton()
        self._close_btn.setText("✕")
        self._close_btn.setToolTip("カーソルを消す")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(
            "QToolButton { color:#cdd6f4; border:none; padding:0 2px; }"
            " QToolButton:hover { color:#f38ba8; }"
        )
        self._close_btn.clicked.connect(self._clear_cursors)
        header_row.addWidget(self._close_btn)
        outer.addLayout(header_row)
        # 表全体は移動可能（PC-18 移動アフォーダンス）。✕ は PointingHand を維持。
        self.setCursor(cursor(CursorKind.MOVE))
```

（✕ ボタンは `setText`/`setToolTip`/`setCursor`/`setStyleSheet`/`clicked.connect` のみで構成。Qt では明示 `setCursor` した子ウィジェットは親のカーソルを継承しない（順序非依存）ため、本体=移動カーソル・✕=PointingHand で分離され、明示カーソル未設定のラベル群は本体の MOVE を継承する。）

`_on_clear` 状態を `__init__` の R16/R17 state 群（:101 付近）に追加:

```python
        # Wired by GraphPanelView: ✕ / メニュー「カーソルを消す」で全消去（全 A/B/Δ）。
        self._on_clear: Callable[[], None] | None = None
```

クリアハンドラと introspection を `build_column_menu` の手前あたりに追加:

```python
    def close_button(self) -> QToolButton:
        """The always-visible ✕ button (test introspection / realgui target)."""
        return self._close_btn

    def _clear_cursors(self) -> None:
        """✕ / メニュー「カーソルを消す」→ VM 全消去（wire 済みのときのみ）。"""
        if self._on_clear is not None:
            self._on_clear()
```

- [ ] **Step 4: View で `_on_clear` を配線＋サブカーソル tooltip**

`graph_panel_view.py` の readout 生成箇所（`self._readout._on_stat_toggled = _on_stat_toggled` の直後・:855 付近）に:

```python
        # ✕ / readout メニュー「カーソルを消す」→ 全消去（A/B/Δ・spec §4.3/§10）。
        self._readout._on_clear = lambda: self.vm.toggle_main_cursor(False)
```

`build_context_menu` のサブカーソル項目（メインカーソル無効時に disabled になる項目・`main_act.toggled.connect(...)` :2394 付近の周辺でサブカーソル `sub_act` を追加している箇所）へ、disabled 時にツールチップと `setToolTipsVisible` を付与。実装者はサブカーソル action を生成している行を特定し（`toggle_delta` を connect している action）、次を追加:

```python
        if not sub_act.isEnabled():
            sub_act.setToolTip("メインカーソルを有効化すると使えます")
            menu.setToolTipsVisible(True)
```

（`menu` はそのサブカーソル項目が属する QMenu 変数名に合わせる。QMenu 既定は QAction ツールチップ非表示のため `setToolTipsVisible(True)` 必須・spec §5。）

- [ ] **Step 5: 通過を確認＋フルスイート**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k "close_button or move_cursor" -v && uv run pytest tests/gui/test_graph_panel_cursor.py -k readout_close -v`
Expected: PASS

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 6: コミット**

```bash
git add src/valisync/gui/views/cursor_readout.py src/valisync/gui/views/graph_panel_view.py tests/gui/test_cursor_readout.py tests/gui/test_graph_panel_cursor.py
git commit -m "feat(gui): readout 常時 ✕（全消去）＋移動アフォーダンス＋サブカーソル tooltip（PC-17/PC-18）"
```

---

## Task 5: Readout — 右クリックメニュー（統計列/精度/コピー/消去）（PC-12/PC-10/DP10）（Layer B）

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`（`build_readout_menu()`／`contextMenuEvent`／`_on_precision` callback／`_copy_table`）
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`_readout._on_precision = lambda p: self.vm.set_value_precision(p)`）
- Test: `tests/gui/test_cursor_readout.py`

**Interfaces:**
- Consumes: 既存 `build_column_menu()`（統計列 checkable・PC-12）・Task 2 の `self._precision`・Task 3 の `table_tsv()`・Task 4 の `_clear_cursors`。
- Produces:
  - `CursorReadout.build_readout_menu() -> QMenu`（統計列 ▸／精度 ▸〔4/6/8 排他・現在値 checked〕／表をコピー／カーソルを消す）
  - `CursorReadout._on_precision: Callable[[int], None] | None`（View が wire）
  - `contextMenuEvent` で右クリック時に `build_readout_menu` を popup
  - `_copy_table()`（`QApplication.clipboard().setText(self.table_tsv())`）

**GUI テスト分析（gui-test-plan）:** メニュー構成＋クリップボード → **Layer B**。実質性: メニュー 4 項目・統計列サブ・精度サブが排他＋現在値 checked・精度 action で `_on_precision` 発火・コピー action で clipboard に TSV・「カーソルを消す」で `_on_clear` 発火を自動アサート。実 OS 右クリックは Task 6。honest layering note: `QActionGroup` 排他は「1 つ checked → 他 uncheck」で確認（memory `gui_qactiongroup_exclusive_radio_menu`）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_cursor_readout.py` に追記:

```python
def _readout_menu_items(ro):
    menu = ro.build_readout_menu()
    return menu, {a.text(): a for a in menu.actions()}


def test_readout_menu_has_expected_items(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout

    ro = CursorReadout()
    qtbot.addWidget(ro)
    _menu, acts = _readout_menu_items(ro)
    assert "統計列" in acts
    assert "精度" in acts
    assert "表をコピー" in acts
    assert "カーソルを消す" in acts


def test_precision_submenu_exclusive_reflects_current(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(0.0, [CursorReading("a", "#fff", 1.0, True)], precision=6)
    _menu, acts = _readout_menu_items(ro)
    sub = acts["精度"].menu()
    pacts = {a.text(): a for a in sub.actions()}
    assert pacts["6"].isChecked() is True
    assert pacts["4"].isChecked() is False
    pacts["8"].setChecked(True)             # 排他効果
    assert pacts["6"].isChecked() is False


def test_precision_action_fires_callback(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(0.0, [CursorReading("a", "#fff", 1.0, True)], precision=6)
    got: list[int] = []
    ro._on_precision = got.append
    _menu, acts = _readout_menu_items(ro)
    sub = acts["精度"].menu()
    next(a for a in sub.actions() if a.text() == "8").trigger()
    assert got == [8]


def test_copy_action_puts_tsv_on_clipboard(qtbot):
    from PySide6.QtWidgets import QApplication
    from valisync.gui.views.cursor_readout import CursorReadout
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(0.0, [CursorReading("spd", "#fff", 1.5, True, unit="km/h")])
    _menu, acts = _readout_menu_items(ro)
    acts["表をコピー"].trigger()
    assert "spd [km/h]" in QApplication.clipboard().text()


def test_readout_menu_clear_fires_on_clear(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout

    ro = CursorReadout()
    qtbot.addWidget(ro)
    fired: list[bool] = []
    ro._on_clear = lambda: fired.append(True)
    _menu, acts = _readout_menu_items(ro)
    acts["カーソルを消す"].trigger()
    assert fired == [True]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k "readout_menu or precision_submenu or precision_action or copy_action" -v`
Expected: FAIL（`build_readout_menu` 未定義）

- [ ] **Step 3: メニュー＋コピー＋精度 callback を実装**

`cursor_readout.py` の import に `QActionGroup`・`QApplication` を追加:

```python
from PySide6.QtGui import QActionGroup, QColor, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
```

`_on_precision` 状態を `_on_clear` の隣（:101 付近）へ:

```python
        # Wired by GraphPanelView: 精度メニュー選択 → vm.set_value_precision(p)。
        self._on_precision: Callable[[int], None] | None = None
```

`build_column_menu`（:233）の隣に readout メニュー・コピー・contextMenuEvent を追加:

```python
    def build_readout_menu(self) -> QMenu:
        """readout 右クリックメニュー: 統計列 ▸ / 精度 ▸ / 表をコピー / カーソルを消す。"""
        menu = QMenu(self)
        stat_sub = self.build_column_menu()
        stat_sub.setTitle("統計列")
        menu.addMenu(stat_sub)

        prec_sub = menu.addMenu("精度")
        group = QActionGroup(prec_sub)
        group.setExclusive(True)
        for p in (4, 6, 8):
            act = prec_sub.addAction(str(p))
            act.setCheckable(True)
            act.setActionGroup(group)
            act.setChecked(p == self._precision)  # BEFORE triggered.connect
            act.triggered.connect(lambda *_, val=p: self._emit_precision(val))

        menu.addAction("表をコピー", self._copy_table)
        menu.addAction("カーソルを消す", self._clear_cursors)
        return menu

    def _emit_precision(self, p: int) -> None:
        if self._on_precision is not None:
            self._on_precision(p)

    def _copy_table(self) -> None:
        QApplication.clipboard().setText(self.table_tsv())

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # type: ignore[override]
        self.build_readout_menu().exec(event.globalPos())
```

`contextMenuEvent` の引数型のため import に `QContextMenuEvent` を追加:

```python
from PySide6.QtGui import (
    QActionGroup,
    QColor,
    QContextMenuEvent,
    QMouseEvent,
    QPixmap,
)
```

- [ ] **Step 4: View で `_on_precision` を配線**

`graph_panel_view.py` の `self._readout._on_clear = ...`（Task 4）の直後に:

```python
        self._readout._on_precision = lambda p: self.vm.set_value_precision(p)
```

- [ ] **Step 5: 通過を確認＋フルスイート**

Run: `uv run pytest tests/gui/test_cursor_readout.py -k "readout_menu or precision_submenu or precision_action or copy_action" -v`
Expected: PASS（6 件）

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 6: コミット**

```bash
git add src/valisync/gui/views/cursor_readout.py src/valisync/gui/views/graph_panel_view.py tests/gui/test_cursor_readout.py
git commit -m "feat(gui): readout 右クリックメニュー（統計列/精度排他/表をコピー/カーソルを消す・PC-12/PC-10/DP10）"
```

---

## Task 6: realgui 証拠（Layer C・実 OS 入力）

**Files:**
- Create: `tests/realgui/test_readout_realclick.py`（readout ✕ 実クリック／readout 実右クリックメニュー→コピー・精度・消去）
- Test: 新規 realgui を①ゲートで実行＋既存カーソル realgui（`test_global_cursor.py`）の無回帰

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input`（`at`/`LDOWN`/`LUP`/`RDOWN`/`RUP`/`to_phys`/`skip_unless_real_display`）・既存 `test_global_cursor.py::_shown_panel`／`_scene_center` の作法・`test_axis_menu_offset.py` の `_menu_hang_watchdog`/`_open_menu_click_item` モーダルメニューパターン（module-local 忠実コピー）・View introspection `_readout.close_button()`／`cursor_line_visible()`／`_readout.table_tsv()`。
- Produces: 実 OS 入力の証拠（pass/fail・スクショ）。

**GUI テスト分析（gui-test-plan）:** spec §11 増分3 Layer C「readout ✕ 実クリック／readout 実右クリックメニュー」。実質性: ✕ を物理クリック → カーソル全消去（`cursor_line_visible()` False）／readout を実右クリック → メニュー実クリックで「表をコピー」→ clipboard に TSV・「カーソルを消す」→ 消滅・精度選択が反映。掴み点は readout の可視ジオメトリから導出し `availableGeometry` 内 clamp。メニュー実クリックは `_open_menu_click_item` パターン＋`_menu_hang_watchdog`。honest layering note: ✕/メニューの合成クリックは Task 4/5 の Layer B で callback 発火を証明済み。Layer C は「実ディスプレイに映って実 OS 入力で効く」ことのみを証拠化。

- [ ] **Step 1: 実 ✕ クリックの realgui を書く**

`tests/realgui/test_readout_realclick.py`（新規）。既存 realgui のヘッダ・`_shown_panel` 作法を `test_global_cursor.py` から流用:

```python
"""Layer C: CursorReadout の ✕ / 右クリックメニューを実 OS 入力で検証（増分3b）。"""

from __future__ import annotations

import contextlib
import threading
import time

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    at,
    skip_unless_real_display,
    to_phys,
)

pytestmark = pytest.mark.realgui


def _shown_panel(qtbot: QtBot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 60, screen.y() + 60, 820, 620)
    view.show()
    view.raise_()
    view.activateWindow()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return view


def _widget_center_phys(view, w) -> tuple[int, int]:
    """物理スクリーン中心座標（w は view の子ウィジェット）。"""
    from PySide6.QtCore import QPoint

    dpr = view.devicePixelRatioF()
    gp = w.mapToGlobal(QPoint(w.width() // 2, w.height() // 2))
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_real_click_close_button_clears(qtbot: QtBot, tmp_path) -> None:
    """A カーソル設置 → readout ✕ を実クリック → カーソル消滅。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible()
    btn = view._readout.close_button()
    for _ in range(3):
        QApplication.processEvents()
    px, py = _widget_center_phys(view, btn)
    at(px, py, LDOWN)
    at(px, py, LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "readout_closed.png")
        )
    assert not view.cursor_line_visible()
```

- [ ] **Step 2: 実右クリックメニュー→コピーの realgui を書く**

同ファイルに、`test_axis_menu_offset.py` の `_menu_hang_watchdog`/`_open_menu_click_item` を module-local 忠実コピーして追加（`tests/realgui/test_axis_menu_offset.py:64-204` を参照。`VK_ESCAPE`/`key as key_input`/`QEventLoop`/`QTimer`/`QMenu` の import 込み）。その上で:

```python
def test_real_right_click_readout_copy(qtbot: QtBot, tmp_path) -> None:
    """A カーソル設置 → readout 実右クリック → 「表をコピー」実クリック → clipboard に TSV。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    QApplication.clipboard().clear()
    ro = view._readout
    phys = _widget_center_phys(view, ro)
    shot = tmp_path / "readout_menu.png"
    captured = _open_menu_click_item(view, phys, "表をコピー", shot)
    for _ in range(5):
        QApplication.processEvents()
    assert captured.get("type") == "QMenu"
    assert "表をコピー" in (captured.get("actions") or [])
    assert QApplication.clipboard().text() != ""   # TSV がコピーされた
```

（`_open_menu_click_item` は右クリックを readout の中心へ送る。readout はプロット矩形左上 (8,8) 付近に可視配置されるため掴み点は可視域内。メニュー hang は watchdog がガード。）

- [ ] **Step 3: 新規 realgui を①ゲートで実行**

Run: `QT_QPA_PLATFORM=windows uv run pytest --realgui tests/realgui/test_readout_realclick.py -v`
Expected: PASS（2 件・実ディスプレイ時）。スクショ目視（✕ で readout 消滅・メニューに「表をコピー」）。
（実ディスプレイ無しなら `skip_unless_real_display()` でスキップ → その旨を正直に報告。skip を緑と誤認しない。）

- [ ] **Step 4: 既存カーソル realgui の無回帰＋Layer C 契約ガード＋headless full**

Run: `uv run pytest --realgui tests/realgui/test_global_cursor.py -v`
Expected: PASS（増分3a のカーソル realgui に無回帰なし）

Run: `uv run pytest tests/gui/test_realgui_layer_c_contract.py -v`
Expected: PASS（新規 realgui が実 OS 入力）

Run: `uv run pytest`
Expected: headless full 0 errors（realgui は自動スキップ）

- [ ] **Step 5: ①証拠ゲート判定（merge 前・`/gui-verify`）**
  - (a) headless full `uv run pytest` 0 errors
  - (b) realgui 証拠: 新規2本 pass・スクショ・既存 `test_global_cursor.py` 無回帰・Layer C 契約ガード pass
  - (c) CI 緑（push 後 PR で確認）

- [ ] **Step 6: コミット**

```bash
git add tests/realgui/test_readout_realclick.py
git commit -m "test(realgui): readout ✕ 実クリック＋実右クリックメニュー→コピーの実 OS 入力検証（Layer C ①ゲート）"
```

---

## Self-Review

**1. Spec coverage（§8 readout 刷新＝PC-10/11/12/16/17/18）:**

| spec 要件 | 担当タスク |
|---|---|
| 単位を readings へ注入＋名前脇 `[unit]` 淡色（PC-11・DP8） | Task 1（VM 注入）＋ Task 2（表示） |
| 可変精度（VM source of truth・既定 6・4/6/8・値/統計列のみ・count/時刻は不変）（PC-16・DP9） | Task 1（状態）＋ Task 2（フォーマッタ）＋ Task 5（精度メニュー） |
| 統計列 ▸ を右クリックメニューへ配線（既存 `build_column_menu`＝PC-12） | Task 5 |
| 表をコピー＝表示中の列/精度/単位の TSV をクリップボードへ（PC-10・DP12） | Task 3（機構）＋ Task 5（アクション配線） |
| ✕ 常時＝全消去＋サブカーソル項目 disabled tooltip（PC-17） | Task 4 |
| 移動アフォーダンス `setCursor(MOVE)`（PC-18） | Task 4 |
| 右クリックメニュー DP10（統計列/精度/コピー/消去） | Task 5 |
| realgui: readout ✕ 実クリック／実右クリックメニュー | Task 6 |
| 3a 繰越 followup: `_last_delta` 拡張で interp_label 保持 | Task 2 |

**2. Placeholder scan:** 各コード step に実コードあり。realgui（Task 6）の `_menu_hang_watchdog`/`_open_menu_click_item` は既存 `tests/realgui/test_axis_menu_offset.py` の確立パターンへの委譲（placeholder でなく既存 API 参照）で、実装者は既存 realgui を読んで module-local 忠実コピーする旨を明記。Task 4 Step 3 の `setCursorHint = None` は「書くな」と注記済み（誤記防止のガード注記）。

**3. Type consistency:**
- `value_precision: int`（Task 1 定義）→ Task 2 が `precision=self.vm.value_precision` で set_global/set_delta へ・Task 5 精度メニューが `self._precision` と比較・View が `set_value_precision(p)` 呼び出し（型一致 int）。
- `CursorReading.unit: str`/`DeltaReading.unit: str`（Task 1）→ Task 2 が rows 4-tuple の unit として消費（型一致 str）。
- `_last_delta: tuple[float, float, list[DeltaReading], str, int]`（Task 2）→ `_toggle_stat` 再描画で `set_delta(*self._last_delta)`（5 位置引数一致）。
- `table_tsv() -> str`（Task 3）→ Task 5 `_copy_table` が clipboard へ・Task 6 が clipboard assert（型一致 str）。
- `_on_clear: Callable[[], None] | None`（Task 4）→ View が lambda wire・`_clear_cursors` が呼ぶ。`_on_precision: Callable[[int], None] | None`（Task 5）→ View が lambda wire・`_emit_precision` が呼ぶ。
- `close_button() -> QToolButton`（Task 4）→ Task 6 realgui が物理クリック対象に使用。

**4. 依存順:** Task 1（VM 精度/unit）→ Task 2（フォーマッタ/表示・1 消費）→ Task 3（TSV・2 の `_row_cells` 消費）→ Task 4（✕/クリア）→ Task 5（メニュー・3 の table_tsv/4 の _clear_cursors 消費）→ Task 6（realgui・全実装後）。各タスクは独立テスト可能な成果物で終わる。

**5. honest layering:** ✕/メニューは Layer B で callback 発火・状態遷移を証明（合成 click/trigger）。実 OS クリックは Task 6（Layer C）でのみ「実ディスプレイに映って効く」ことを証拠化。TSV/精度/単位は純ウィジェット整形なので Layer B が主戦場。
