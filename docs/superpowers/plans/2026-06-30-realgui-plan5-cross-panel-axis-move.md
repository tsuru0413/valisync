# クロスパネル軸移動 Implementation Plan (Phase 5・新機能)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 軸フレームを**同一タブ内の別パネル**へドラッグ&ドロップしたとき、軸を（その信号群＋軸設定ごと）ターゲットパネルへ移動する新機能。MVVM を守り `GraphAreaVM.move_axis_across_panels` が統括する。リスク順・テスト先行（Layer A/B → production → realgui）。

**Architecture:** axis-move QDrag の MIME を `{source_panel_index, axis_index}` に拡張。GraphPanelView は自パネル index を `set_panel_index` で知る。`dropEvent` は `source_panel_index != self._panel_index` のとき新シグナル `cross_panel_axis_move_requested(source_panel_index, axis_index, col, position)` を emit（QDrag モーダル巻き戻し後＝既存同様 `QTimer.singleShot` 遅延）。GraphAreaView が `_wire_panel` でそれを `GraphAreaVM.move_axis_across_panels(tab_index, src_panel, axis_index, dst_panel, col, position)` へ配線。VM は source GraphPanelVM から軸を `extract_axis` し target に `insert_axis` する（両 GraphPanelVM はセッション共有ゆえ信号キーが解決）。同一パネルは従来の `move_axis_to_column` パス（無変更）。

**Tech Stack:** PySide6 / pyqtgraph / pytest / pytest-qt / ctypes(Win32)。共有 realgui 入力ヘルパ `tests/realgui/_realgui_input.py`（`drive_qdrag`）。

## Global Constraints

- 設計 spec: `docs/superpowers/specs/2026-06-30-realgui-coverage-expansion-design.md`（新機能: クロスパネル軸移動 = lines 65-85）。
- **MVVM 厳守**: View 同士は直接触らない。移動は GraphAreaVM が統括し、両 GraphPanelVM を操作して通知。viewmodels に Qt/pyqtgraph を import しない（GraphAreaVM/GraphPanelVM/YAxisVM は純ロジック）。
- **同一タブ内の可視パネル間のみ**（別タブは同時表示されずドロップ対象にならない）。移動単位 = 軸＝その信号群（key/color/visible）＋軸設定（unit/name/y_range/height_ratio）。source が 0 軸化したら空リージョン許容（既存 `_compact_axes` 挙動）。drop 位置は target 内で既存 `_axis_drop_target`→`move_axis_to_column` の列/順序ロジックを流用。容量上限なし（YAGNI）。
- **同一パネル move は従来パス（無変更）**: dropEvent で `source_panel_index == self._panel_index` のときは既存 `_apply_deferred_axis_move`→`move_axis_to_column`。`move_axis_across_panels` は src≠dst 前提（src==dst は no-op ガード）。
- **C2（QDrag.exec モーダル中の rebuild ハング）**: 既存軸移動と同様 dropEvent は `QTimer.singleShot(0, ...)` で遅延（クロスパネルのシグナル emit もこの遅延ラムダ内）。memory `gui_realgui_qdrag_rebuild_stale_scene`。
- **QDrag 駆動は `drive_qdrag`（背景 OS スレッド＋watchdog）**。`QTimer` 駆動禁止（memory `gui_realgui_drag_qtimer_hang`）。
- realgui(Layer C) は `tests/realgui/`・module-level `pytestmark = pytest.mark.realgui`・`--realgui` opt-in。実装サブエージェントは headless（収集＋フルゲート）まで、`--realgui` の GREEN/honest RED はコントローラ ①ゲート。
- コミットメッセージ末尾に必須トレーラ（`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k`）。
- コミット前ゲート: `uv run pytest`（0 errors）/ `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。worktree なら先に `uv sync --extra dev`。

## File Structure

- Modify: `src/valisync/gui/adapters/qt_signal_models.py` — `encode_axis_index`→`encode_axis_move(source_panel_index, axis_index)` / `decode_axis_index`→`decode_axis_move`→`(int,int)|None`。
- Modify: `src/valisync/gui/views/graph_panel_view.py` — AxisItem の QDrag MIME 拡張・`GraphPanelView.set_panel_index`／`_panel_index`／`cross_panel_axis_move_requested` シグナル・dropEvent クロスパネル分岐。
- Modify: `src/valisync/gui/views/graph_area_view.py` — `_wire_panel` で `set_panel_index` 呼び＋`cross_panel_axis_move_requested` 配線。
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py` — `extract_axis` / `insert_axis`（移動の remove/add 部品）。
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py` — `move_axis_across_panels`。
- Create: `tests/gui/test_cross_panel_axis_move.py` — Layer A/B（VM ロジック＋配線）。
- Create: `tests/realgui/test_cross_panel_axis_realclick.py` — Layer C（実 QDrag panel0→panel1）。

**検証済みアンカー**: encode/decode=qt_signal_models.py:50-64／AxisItem QDrag=graph_panel_view.py:571-583／dropEvent 軸分岐=1656-1669／`_wire_panel`=graph_area_view.py:122-139（`add_panel`/`offset_apply_requested` パターン）／`_rebuild` の `_wire_panel(widget, tab_index, panel_index, ...)`=107-114／GraphPanelVM `move_axis_to_column`=238-265・`_compact_axes`=267-287・`_relayout_columns`=289-311・`_layout_column_preserving`=313-332・`_PlottedEntry`=87-93／YAxisVM(unit/name/y_range/column/top_ratio/height_ratio)=y_axis_vm.py／GraphAreaVM `_tabs`/`panels(tab)`/`add_panel`/`remove_panel`=graph_area_vm.py。参照 realgui: `tests/realgui/test_multi_column_axis.py`（軸 QDrag）。

---

### Task 1: MIME 拡張＋パネル index 配線（同一パネル挙動は無変更）

**Files:**
- Modify: `src/valisync/gui/adapters/qt_signal_models.py`
- Modify: `src/valisync/gui/views/graph_panel_view.py`
- Modify: `src/valisync/gui/views/graph_area_view.py`
- Test: `tests/gui/test_cross_panel_axis_move.py`（新規・Task 1 分）

**Interfaces:**
- Produces: `encode_axis_move(source_panel_index, axis_index) -> QMimeData` / `decode_axis_move(md) -> tuple[int,int] | None`。`GraphPanelView.set_panel_index(panel_index: int)` / `GraphPanelView._panel_index`。`GraphPanelView.cross_panel_axis_move_requested = Signal(int, int, int, int)`（source_panel, axis_index, col, position）。

**方針**: 全 axis-move ドラッグが `{source_panel_index, axis_index}` を運ぶよう MIME を拡張し、AxisItem が drag 起動時に自パネル index を載せる。同一パネル drop の挙動は**この Task では変えない**（dropEvent は decode 後 source==self を確認し従来 `_apply_deferred_axis_move` を呼ぶ。クロスパネル分岐は Task 3）。

- [ ] **Step 1: MIME の RED テスト**（`tests/gui/test_cross_panel_axis_move.py` 新規）

```python
"""Layer A/B: cross-panel axis move — MIME, VM logic, and view wiring."""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.adapters.qt_signal_models import decode_axis_move, encode_axis_move


def test_axis_move_mime_roundtrip() -> None:
    md = encode_axis_move(2, 5)
    assert decode_axis_move(md) == (2, 5)


def test_decode_axis_move_none_without_payload() -> None:
    from PySide6.QtCore import QMimeData

    assert decode_axis_move(QMimeData()) is None
```

- [ ] **Step 2: RED 確認** → `uv run pytest tests/gui/test_cross_panel_axis_move.py -q`（ImportError/AttributeError で fail）。

- [ ] **Step 3: MIME 実装**（`qt_signal_models.py`）。`encode_axis_index`/`decode_axis_index`（行 50-64）を置換:

```python
def encode_axis_move(source_panel_index: int, axis_index: int) -> QMimeData:
    """Pack a {source_panel_index, axis_index} axis-move payload under AXIS_INDEX_MIME."""
    md = QMimeData()
    md.setData(AXIS_INDEX_MIME, f"{source_panel_index},{axis_index}".encode())
    return md


def decode_axis_move(md: QMimeData) -> tuple[int, int] | None:
    """Extract (source_panel_index, axis_index) from *md*; None if absent/invalid."""
    if not md.hasFormat(AXIS_INDEX_MIME):
        return None
    try:
        src, axis = bytes(md.data(AXIS_INDEX_MIME).data()).decode("utf-8").split(",")
        return int(src), int(axis)
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 4: 呼び出し側を更新**（`graph_panel_view.py`）。
  - import を `decode_axis_index`/`encode_axis_index` → `decode_axis_move`/`encode_axis_move` に差し替え（旧名の全参照を一掃）。
  - `GraphPanelView.__init__`（~611-618）に `self._panel_index: int = 0` を追加（`_active_axis_index` 等の近く）。新メソッド `def set_panel_index(self, panel_index: int) -> None: self._panel_index = panel_index`。新シグナル（既存 `add_panel_requested` 等 605-609 の隣）`cross_panel_axis_move_requested = Signal(int, int, int, int)`。
  - `_AlignedAxisItem.mouseDragEvent` の QDrag 構築（行 582）: `drag.setMimeData(encode_axis_index(self._vm_axis_index))` → `drag.setMimeData(encode_axis_move(self._panel_view._panel_index, self._vm_axis_index))`（`_panel_view` は同 AxisItem の back-ref・行 277）。
  - `dropEvent` の軸分岐（行 1656-1669）: `axis_index = decode_axis_index(...)` → `decoded = decode_axis_move(event.mimeData())`; `if decoded is not None:` の中で `source_panel_index, axis_index = decoded`。**この Task では従来通り** `_apply_deferred_axis_move(axis_index, col, position)` を呼ぶ（source==self 前提の既存挙動を保持。クロスパネル分岐は Task 3）。

- [ ] **Step 5: `_wire_panel` で set_panel_index**（`graph_area_view.py`:122-139 の `_wire_panel`、`widget.set_removable(removable)` の隣）: `widget.set_panel_index(panel_index)`。

- [ ] **Step 6: Layer B 配線テストを追記**（同ファイル）。GraphPanelView が panel_index を保持し AxisItem が拡張 MIME を載せることを headless で確認:

```python
def test_panel_index_set_via_wire(qtbot: QtBot, tmp_path: Path) -> None:
    from tests.gui._panel_factory import make_two_axis_panel
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    assert isinstance(view, GraphPanelView)
    view.set_panel_index(3)
    assert view._panel_index == 3
```

- [ ] **Step 7: GREEN＋フルゲート＋無回帰**。`uv run pytest`（既存軸移動の合成テスト＝同一パネル挙動が無回帰なこと・realgui test_multi_column_axis は headless skip）／ruff/format/mypy。`encode_axis_index`/`decode_axis_index` の旧名参照が残ってないか grep。

- [ ] **Step 8: Commit** — `feat(gui): axis-move MIME を {source_panel,axis} へ拡張＋GraphPanelView パネル index 配線`。

---

### Task 2: GraphPanelVM.extract_axis/insert_axis ＋ GraphAreaVM.move_axis_across_panels（VM ロジック）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py`
- Test: `tests/gui/test_cross_panel_axis_move.py`（VM 分を追記）

**Interfaces:**
- Produces: `GraphPanelVM.extract_axis(axis_index) -> tuple[YAxisVM, list[_PlottedEntry]] | None`、`GraphPanelVM.insert_axis(axis, entries, column, position) -> None`、`GraphAreaVM.move_axis_across_panels(tab_index, src_panel_index, axis_index, dst_panel_index, column, position) -> None`。

- [ ] **Step 1: VM ロジックの RED テスト**（追記）。2軸パネル→別パネルへ軸移動で source から消え target に同一信号で出現、source 不在 axis は no-op、src==dst は no-op:

```python
def _area_two_panels(tmp_path: Path):
    """GraphAreaVM with one tab, two panels sharing a session; panel0 has 2 signals
    (axis0=k0, axis1=k1), panel1 empty. Returns (area_vm, k0, k1)."""
    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM

    csv = tmp_path / "d.csv"
    csv.write_text("t,a,b\n0,1,4\n1,2,5\n", encoding="utf-8")
    session = Session()
    session.load(
        csv,
        FormatDefinition(
            name="f", delimiter=Delimiter.COMMA, timestamp_column=0,
            timestamp_unit="sec", signal_start_column=1, signal_end_column=2,
            has_header=True,
        ),
    )
    keys = sorted(s.name for s in session.signals())
    area = GraphAreaVM(AppViewModel(session))
    area.add_panel(0)  # tab 0 now has 2 panels (panel0 default + panel1)
    p0, p1 = area.panels(0)[0], area.panels(0)[1]
    p0.add_signal_to_axis(keys[0], 0)
    p0.create_new_axis(keys[1])  # p0: axis0=k0, axis1=k1
    return area, p0, p1, keys


def test_move_axis_across_panels_moves_signal(tmp_path: Path) -> None:
    area, p0, p1, keys = _area_two_panels(tmp_path)
    assert keys[0] in [e.signal_key for e in p0._plotted]
    area.move_axis_across_panels(0, 0, 0, 1, column=0, position=None)  # move p0.axis0 → p1
    p0_keys = [e.signal_key for e in p0._plotted]
    p1_keys = [e.signal_key for e in p1._plotted]
    assert keys[0] not in p0_keys, "moved signal still in source"
    assert keys[0] in p1_keys, "moved signal absent from target"


def test_move_axis_across_panels_same_panel_noop(tmp_path: Path) -> None:
    area, p0, p1, keys = _area_two_panels(tmp_path)
    before = sorted(e.signal_key for e in p0._plotted)
    area.move_axis_across_panels(0, 0, 0, 0, column=0, position=None)  # src==dst
    assert sorted(e.signal_key for e in p0._plotted) == before


def test_move_axis_across_panels_stale_index_noop(tmp_path: Path) -> None:
    area, p0, p1, keys = _area_two_panels(tmp_path)
    area.move_axis_across_panels(0, 0, 99, 1, column=0, position=None)  # axis 99 absent
    assert [e.signal_key for e in p1._plotted] == []
```

- [ ] **Step 2: RED 確認**（AttributeError）。

- [ ] **Step 3: GraphPanelVM の extract/insert**（`graph_panel_vm.py`、`move_axis_to_column` 付近に追加）:

```python
def extract_axis(
    self, axis_index: int
) -> tuple[YAxisVM, list[_PlottedEntry]] | None:
    """Remove the axis at *axis_index* and its plotted signals from this panel.

    Returns the YAxisVM (carrying unit/name/y_range/height_ratio) and its
    _PlottedEntry list (signal_key/color/visible) so a sibling panel can
    re-create the axis verbatim. The vacated band stays blank (_compact_axes,
    mirroring removal). Stale index → None (no-op).
    """
    if not (0 <= axis_index < len(self._axes)):
        return None
    axis = self._axes[axis_index]
    entries = [e for e in self._plotted if e.axis_index == axis_index]
    self._plotted = [e for e in self._plotted if e.axis_index != axis_index]
    self._compact_axes()  # prune the now-signal-less moved axis, remap survivors
    self._invalidate_cache()
    self._notify("axes")
    return axis, entries


def insert_axis(
    self,
    axis: YAxisVM,
    entries: list[_PlottedEntry],
    column: int,
    position: int | None,
) -> None:
    """Insert a previously-extracted *axis* (with its *entries*) at *column*/*position*.

    The axis keeps its carried settings; signals keep their colors. The target
    column is re-stacked preserving heights (move_axis_to_column), so the moved
    axis lands at the requested vertical position.
    """
    new_index = len(self._axes)
    axis.column = max(0, min(column, self._column_count - 1))
    self._axes.append(axis)
    for e in entries:
        e.axis_index = new_index
        self._plotted.append(e)
    self.move_axis_to_column(new_index, axis.column, position)  # re-stack + notify "axes"
    self._invalidate_cache()
    self._notify("signals")
```

（注: `_invalidate_cache` の有無・正確なメソッド名は実コードで確認。`YAxisVM`/`_PlottedEntry` の import が graph_panel_vm.py 内に既にある前提。）

- [ ] **Step 4: GraphAreaVM.move_axis_across_panels**（`graph_area_vm.py`、`remove_panel` 付近）:

```python
def move_axis_across_panels(
    self,
    tab_index: int,
    src_panel_index: int,
    axis_index: int,
    dst_panel_index: int,
    column: int,
    position: int | None = None,
) -> None:
    """Move an axis (with its signals + settings) from one panel to another in
    the same tab. Same-panel (src==dst) is a no-op (the View routes same-panel
    drags to the panel's own move_axis_to_column). Stale indices are no-ops.
    """
    panels = self.panels(tab_index)
    if not (0 <= src_panel_index < len(panels) and 0 <= dst_panel_index < len(panels)):
        return
    if src_panel_index == dst_panel_index:
        return
    src, dst = panels[src_panel_index], panels[dst_panel_index]
    moved = src.extract_axis(axis_index)
    if moved is None:
        return
    axis, entries = moved
    dst.insert_axis(axis, entries, column, position)
```

- [ ] **Step 5: GREEN＋フルゲート**。`uv run pytest`（VM テスト pass・既存 GraphPanelVM/GraphAreaVM テスト無回帰）／ruff/format/mypy。`_PlottedEntry`/`YAxisVM` の型注釈で mypy 通過を確認。

- [ ] **Step 6: Commit** — `feat(gui): GraphAreaVM.move_axis_across_panels＋GraphPanelVM extract/insert_axis`。

---

### Task 3: dropEvent クロスパネル分岐＋GraphAreaView 配線

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（dropEvent 分岐）
- Modify: `src/valisync/gui/views/graph_area_view.py`（`_wire_panel` 配線）
- Test: `tests/gui/test_cross_panel_axis_move.py`（配線分を追記）

- [ ] **Step 1: dropEvent クロスパネル分岐**（`graph_panel_view.py` 軸分岐 1656-1669）。decode 済み `(source_panel_index, axis_index)` と `(col, position)=_axis_drop_target(...)` で:

```python
        decoded = decode_axis_move(event.mimeData())
        if decoded is not None:
            source_panel_index, axis_index = decoded
            col, position = self._axis_drop_target(event.position())
            self._clear_axis_move_feedback()
            event.acceptProposedAction()
            if source_panel_index == self._panel_index:
                # same panel → existing within-panel reorder (unchanged)
                QTimer.singleShot(
                    0, lambda: self._apply_deferred_axis_move(axis_index, col, position)
                )
            else:
                # cross-panel → ask GraphArea to relocate (deferred off the QDrag
                # modal stack, same C2 reason as the within-panel path).
                QTimer.singleShot(
                    0,
                    lambda: self.cross_panel_axis_move_requested.emit(
                        source_panel_index, axis_index, col, position
                    ),
                )
            return
```

- [ ] **Step 2: GraphAreaView 配線**（`graph_area_view.py` `_wire_panel`、offset 配線の隣）:

```python
        widget.cross_panel_axis_move_requested.connect(
            lambda src, ax, col, pos: self.vm.move_axis_across_panels(
                tab_index, src, ax, panel_index, col, pos
            )
        )
```

（`tab_index`/`panel_index` は `_wire_panel` 引数＝ドロップを受けた**ターゲット**パネルの位置。source は MIME 由来。同一タブ前提。）

- [ ] **Step 3: Layer B 配線テスト**（追記）。GraphAreaView 上で target パネルの `cross_panel_axis_move_requested` を emit→VM の軸が移動することを headless で確認（合成 emit で配線を検証。実 QDrag 配送は realgui）:

```python
def test_cross_panel_signal_routes_to_vm(qtbot: QtBot, tmp_path: Path) -> None:
    from valisync.gui.views.graph_area_view import GraphAreaView

    area, p0, p1, keys = _area_two_panels(tmp_path)
    view = GraphAreaView(area)
    qtbot.addWidget(view)
    # target = panel1; emit its cross-panel signal asking to pull p0.axis0.
    splitter = view.tabs.widget(0)
    panel1_widget = splitter.widget(1)
    panel1_widget.cross_panel_axis_move_requested.emit(0, 0, 0, None)
    assert keys[0] not in [e.signal_key for e in p0._plotted]
    assert keys[0] in [e.signal_key for e in p1._plotted]
```

- [ ] **Step 4: GREEN＋フルゲート＋無回帰**（同一パネル軸移動の合成テストが無回帰・realgui は skip）／ruff/format/mypy。

- [ ] **Step 5: Commit** — `feat(gui): dropEvent クロスパネル軸移動分岐＋GraphAreaView 配線`。

---

### Task 4: realgui（panel0 軸フレーム→panel1 実ドロップ）

**Files:**
- Create: `tests/realgui/test_cross_panel_axis_realclick.py`

**方針**: GraphAreaView で同一タブに2パネルを表示し、panel0 の軸フレームを `drive_qdrag` で panel1 のプロット/列へ実ドロップ→panel1 に軸（信号ごと）出現・panel0 から消失を assert。`_CapturingArea`/捕捉は test_multi_column_axis.py 同型。軸 QDrag は frame ゾーン起点（spine 左端 FRAME 帯）。

- [ ] **Step 1: realgui テスト作成**（`tests/realgui/test_cross_panel_axis_realclick.py`）。`make_*` で GraphAreaView に2パネル（panel0 に2軸・panel1 空）を構成し、panel0 の `_y_axes[0]` frame 点（`spine.x()+2, spine.center().y()`）を press、panel1 のプロット中央へ waypoints、drop。done 述語＝panel1 の curve_keys に移動キー出現。assert: 移動キーが panel1 に出現・panel0 から消失。frame ゾーン起点・drive_qdrag・skip_unless_real_display・module-level `pytestmark = pytest.mark.realgui`。座標は scene→`to_phys`。GraphAreaView の2パネル構築方法・panel ウィジェット取得（`view.tabs.widget(0).widget(i)`）・各 panel の `_y_axes`/`curve_keys` は test_multi_column_axis.py と GraphAreaView 実 API を読んで確定。

- [ ] **Step 2: ヘッドレス収集**（`--collect-only` 1 collected）＋フルゲート（realgui は skip）／ruff/format/mypy。

- [ ] **Step 3: Commit** — `test(realgui): クロスパネル軸移動の実 QDrag（panel0→panel1）`。

---

## コントローラ ①ゲート（実 win32・honest RED→GREEN）

実装完了後、コントローラが `/gui-verify` を実 win32 実行（**ユーザーに席を外す確認**・外部 watchdog 付き＝QDrag ハング保険）。

1. **GREEN**: `uv run pytest --realgui tests/realgui/test_cross_panel_axis_realclick.py -v` → pass・ハング無し。証拠ログ＋スクショ。
2. **honest RED**: `GraphAreaView._wire_panel` の `cross_panel_axis_move_requested` 配線行を一時 neuter（または dropEvent のクロスパネル分岐を同一パネルパスに固定）→ realgui RED（軸が移動しない）→ 復元。
3. **全 realgui 無回帰**: `uv run pytest --realgui tests/realgui/ -v` → Phase 1-4 の 22 件＋本 1 件＝**23 件 pass・ハング無し**（特に test_multi_column_axis の同一パネル軸移動が MIME 拡張後も無回帰なこと）。

ゲート判定: (a) headless full 0 errors (b) realgui 証拠（GREEN＋RED＋同一パネル無回帰） (c) CI 緑。3点充足で finishing（push + PR）。

---

## Self-Review

**1. Spec coverage（新機能・lines 65-85）**: MIME 拡張=Task1／VM `move_axis_across_panels`（remove/add・src≠dst・stale no-op）=Task2／dropEvent 分岐＋GraphArea 配線（同一タブ・同一パネルは従来パス）=Task3／realgui=Task4。Layer A/B（remove/add 純ロジック・同一パネル no-op・idempotency）＋realgui を網羅。honest RED＝配線 neuter（ゲート）。✔

**2. Placeholder scan**: 新規ユニット（encode/decode・extract/insert・move_axis_across_panels・signal・set_panel_index・Layer A/B テスト）は完全コード。既存コードの編集点は検証済み file:line アンカー＋新コードで指示（実装者が周辺を読んで統合）。realgui は参照テンプレ＋実 API 確認を明記。✔

**3. Type 整合**: `decode_axis_move -> tuple[int,int]|None`／`extract_axis -> tuple[YAxisVM,list[_PlottedEntry]]|None`／`insert_axis(axis, entries, column, position)`／`move_axis_across_panels(tab, src, axis, dst, col, pos)`／`cross_panel_axis_move_requested = Signal(int,int,int,int)` 一貫。✔

**4. リスク/注意（実装者向け）**: (a) `encode_axis_index`/`decode_axis_index` 旧名の**全参照**を一掃（grep）— 残ると同一パネル軸移動が壊れる。(b) 両パネルがセッション共有でなければ移動信号キーが target で解決しない＝GraphAreaVM が同一 AppViewModel/session から全パネルを生成することを確認（共有前提）。(c) `_invalidate_cache`/`_notify` の正確なメソッド名・YAxisVM/_PlottedEntry の import を実コードで確認。(d) 同一パネル drop は従来 `_apply_deferred_axis_move` パスのまま（無回帰必須＝test_multi_column_axis）。(e) C2: クロスパネルのシグナル emit も `QTimer.singleShot` 遅延ラムダ内（QDrag 巻き戻し後）。realgui の実 win32 GREEN/RED はコントローラ①ゲート。
