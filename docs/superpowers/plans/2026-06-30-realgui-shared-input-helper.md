# realgui 共有入力ヘルパ抽出 Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存 realgui テストに散在する実 OS 入力プリミティブと QDrag 背景スレッドドライバを `tests/realgui/_realgui_input.py` に集約し、既存テストを無回帰で載せ替える（以降の全 realgui 拡充フェーズの土台）。

**Architecture:** Win32 `SetCursorPos`/`mouse_event`/`keybd_event` ラッパ＋scene→物理ピクセル変換＋背景 OS スレッドで駆動する QDrag ドライバ（`QDrag.exec` の OLE モーダルループは Qt タイマを汲まないため `QTimer` 駆動はハングする＝実 OS 入力を別スレッドで発行し watchdog で ESC+LEFTUP キャンセル）を1モジュールに集約。既存 realgui を載せ替えて土台の正しさを実機で実証する。

**Tech Stack:** PySide6 / pyqtgraph / pytest / pytest-qt / ctypes(Win32)。

## Global Constraints

- 設計 spec: `docs/superpowers/specs/2026-06-30-realgui-coverage-expansion-design.md`（一次根拠: `docs/realgui-coverage-audit.md`）。
- MVVM: viewmodels に Qt/pyqtgraph を import しない（本プランは tests のみ変更で該当なし）。
- realgui(Layer C) は `@pytest.mark.realgui`＋`--realgui` オプトイン、配置は `tests/realgui/`（offscreen 強制を継承しない）。実 win32 ＋実ディスプレイ必須。
- ヘルパの**ヘッドレス単体テストは `tests/gui/` 配下**に置く（offscreen 強制・CI 実行可）。`tests/realgui/` 直下に非 realgui テストを置かない（CI Linux でディスプレイ無し起動エラーを避ける）。
- QDrag 駆動は**必ず別 OS スレッド＋watchdog**（`QTimer` 駆動禁止＝memory `gui_realgui_drag_qtimer_hang`）。
- 既存 realgui の挙動・アサートは**変えない**（純粋な重複除去リファクタ）。各テストの `done` 述語・faulthandler 診断は保持する。
- コミットメッセージ末尾に必須トレーラ（`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k`）。
- コミット前ゲート: `uv run pytest`（headless 0 errors）/ `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。realgui 無回帰は実 win32 で `uv run pytest --realgui tests/realgui/`（`/gui-verify` ①ゲート）。

## File Structure

- Create: `tests/realgui/_realgui_input.py` — 共有入力プリミティブ＋`drive_qdrag`。
- Create: `tests/gui/test_realgui_input_helper.py` — ヘルパのディスプレイ非依存ロジックの headless 単体テスト。
- Modify: `tests/realgui/test_multi_column_axis.py`, `test_move_then_resize.py`, `test_remove_file_preserves_proportions.py` — 内蔵 QDrag bg ドライバを `drive_qdrag` へ載せ替え。
- Modify: `tests/realgui/test_global_cursor.py`, `test_active_axis_zoom_pan.py`, `test_active_axis_resize.py`, `test_offset_drag.py`, `test_file_browser_realclick.py` — ローカル `_at/_to_phys/_key/_skip_*` 定義を削除し helper から import。

---

### Task 1: 共有入力ヘルパ `_realgui_input.py` を作成

**Files:**
- Create: `tests/realgui/_realgui_input.py`
- Test: `tests/gui/test_realgui_input_helper.py`

**Interfaces:**
- Produces:
  - 定数 `MOVE=0x0001, LDOWN=0x0002, LUP=0x0004, KEYDOWN=0x0000, KEYUP=0x0002, VK_RETURN=0x0D, VK_ESCAPE=0x1B, VK_CONTROL=0x11, VK_SHIFT=0x10`
  - `real_display_skip_reason() -> str | None`
  - `skip_unless_real_display() -> None`
  - `to_phys(view, sx: float, sy: float) -> tuple[int, int]`
  - `at(x: float, y: float, flag: int) -> None`
  - `key(vk: int, *, down: bool = True, up: bool = True) -> None`
  - `drive_qdrag(press_phys, waypoints_phys, *, done, modifier_vk=None, threshold_dy=15, pump_deadline_s=15.0, watchdog_s=3.0) -> None`

- [ ] **Step 1: Write the failing headless test**

`tests/gui/test_realgui_input_helper.py`（offscreen・非 realgui）:

```python
"""Layer A: _realgui_input ヘルパのディスプレイ非依存ロジックを headless 検証。"""

from __future__ import annotations

import pytest

from tests.gui._panel_factory import make_single_signal_panel
from tests.realgui import _realgui_input as ri
from valisync.gui.views.graph_panel_view import GraphPanelView


def test_flag_and_vk_constants() -> None:
    assert (ri.MOVE, ri.LDOWN, ri.LUP) == (0x0001, 0x0002, 0x0004)
    assert (ri.KEYDOWN, ri.KEYUP) == (0x0000, 0x0002)
    assert ri.VK_RETURN == 0x0D and ri.VK_ESCAPE == 0x1B
    assert ri.VK_CONTROL == 0x11 and ri.VK_SHIFT == 0x10


def test_real_display_skip_reason_is_set_under_offscreen() -> None:
    # CI / local headless は QT_QPA_PLATFORM=offscreen or 非 win32 → 必ず理由が返る。
    assert ri.real_display_skip_reason() is not None


def test_to_phys_returns_int_pair(qtbot) -> None:
    # make_single_signal_panel() は .vm を持つ base を返す（test_graph_panel_offset_drag.py
    # 参照）。実 offscreen view を生成して to_phys の座標変換が int ペアを返すことを確認。
    view = GraphPanelView(make_single_signal_panel().vm)
    qtbot.addWidget(view)
    view.resize(400, 300)
    x, y = ri.to_phys(view, 50.0, 40.0)
    assert isinstance(x, int) and isinstance(y, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_realgui_input_helper.py -v`
Expected: FAIL（`ModuleNotFoundError: tests.realgui._realgui_input` 等）。

- [ ] **Step 3: Create the helper module**

`tests/realgui/_realgui_input.py`:

```python
"""Layer C 共有: 実 OS 入力プリミティブ＋背景スレッド QDrag ドライバ。

QDrag.exec は Windows の OLE DoDragDrop モーダルループに入り Qt タイマを汲まない
ため、QTimer 駆動の move/release は無限ハングする（memory: gui_realgui_drag_qtimer_hang）。
本ドライバは別 OS スレッドが実マウス入力を wall-clock で発行してモーダルループを
駆動し、watchdog が停滞時に ESC+LEFTUP でキャンセルする。
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

# Win32 mouse_event / keybd_event フラグ
MOVE, LDOWN, LUP = 0x0001, 0x0002, 0x0004
KEYDOWN, KEYUP = 0x0000, 0x0002
VK_RETURN, VK_ESCAPE, VK_CONTROL, VK_SHIFT = 0x0D, 0x1B, 0x11, 0x10

_user32 = ctypes.windll.user32 if sys.platform == "win32" else None


def real_display_skip_reason() -> str | None:
    """実ディスプレイが無ければ skip 理由文字列、あれば None（テスト可能なロジック）。"""
    if sys.platform != "win32":
        return "real OS input is Windows-only"
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() == "offscreen":
        return "requires a real display — run: uv run pytest --realgui tests/realgui/"
    return None


def skip_unless_real_display() -> None:
    import pytest

    reason = real_display_skip_reason()
    if reason:
        pytest.skip(reason)


def to_phys(view, sx: float, sy: float) -> tuple[int, int]:
    """view の scene 座標 (sx, sy) → 物理スクリーンピクセル（DPR スケール）。"""
    vp = view.plot_widget.mapFromScene(QPoint(int(sx), int(sy)))
    g = view.plot_widget.viewport().mapToGlobal(vp)
    dpr = view.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def at(x: float, y: float, flag: int) -> None:
    _user32.SetCursorPos(int(x), int(y))
    _user32.mouse_event(flag, 0, 0, 0, 0)


def key(vk: int, *, down: bool = True, up: bool = True) -> None:
    if down:
        _user32.keybd_event(vk, 0, KEYDOWN, 0)
    if up:
        _user32.keybd_event(vk, 0, KEYUP, 0)


def drive_qdrag(
    press_phys: tuple[int, int],
    waypoints_phys: list[tuple[int, int]],
    *,
    done: Callable[[], bool],
    modifier_vk: int | None = None,
    threshold_dy: int = 15,
    pump_deadline_s: float = 15.0,
    watchdog_s: float = 3.0,
) -> None:
    """実 OS QDrag を別スレッドで駆動し、GUI スレッドを done() まで pump する。

    press_phys: 物理ピクセルの press 点（ドラッグ元）。
    waypoints_phys: 閾値 move 後の物理ピクセル move 停止点列（末尾＝ドロップ点）。
    done: GUI スレッドで poll する述語（例 lambda: view.drop_seen）。
    modifier_vk: ジェスチャ全体で保持する修飾キー VK（例 VK_CONTROL で Ctrl 結合）。
    threshold_dy: 最初の move を press_y+threshold_dy（垂直）にしてドラッグ閾値を超える。
    """
    finished = threading.Event()
    sx, sy = press_phys
    dx, dy = waypoints_phys[-1]

    def drive() -> None:
        time.sleep(0.3)  # GUI スレッドが pump に到達するのを待つ
        if modifier_vk is not None:
            _user32.keybd_event(modifier_vk, 0, KEYDOWN, 0)
        at(sx, sy, LDOWN)
        time.sleep(0.1)
        at(sx, sy + threshold_dy, MOVE)  # 閾値超え → QDrag.exec 開始
        time.sleep(0.2)
        for wx, wy in waypoints_phys:
            at(wx, wy, MOVE)
            time.sleep(0.2)
        time.sleep(0.1)
        at(dx, dy, LUP)  # drop
        if modifier_vk is not None:
            _user32.keybd_event(modifier_vk, 0, KEYUP, 0)
        if not finished.wait(timeout=watchdog_s):  # 停滞 → キャンセル
            _user32.keybd_event(VK_ESCAPE, 0, KEYDOWN, 0)
            _user32.keybd_event(VK_ESCAPE, 0, KEYUP, 0)
            at(dx, dy, LUP)

    worker = threading.Thread(target=drive, daemon=True)
    worker.start()
    deadline = time.monotonic() + pump_deadline_s
    while not done() and worker.is_alive() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    finished.set()
    worker.join(timeout=4.0)
```

- [ ] **Step 4: Run the headless test to verify it passes**

Run: `uv run pytest tests/gui/test_realgui_input_helper.py -v`
Expected: PASS（3 件）。`uv run ruff check tests/realgui/_realgui_input.py && uv run mypy src/`（src 不変）もクリーン。

- [ ] **Step 5: Commit**

```bash
git add tests/realgui/_realgui_input.py tests/gui/test_realgui_input_helper.py
git commit -m "test(realgui): 共有入力ヘルパ _realgui_input を追加（プリミティブ＋drive_qdrag）"
```

---

### Task 2: QDrag テストを `drive_qdrag` へ載せ替え

**Files:**
- Modify: `tests/realgui/test_multi_column_axis.py`, `tests/realgui/test_move_then_resize.py`, `tests/realgui/test_remove_file_preserves_proportions.py`

**Interfaces:**
- Consumes: Task 1 の `drive_qdrag`, `to_phys`, `at`, `skip_unless_real_display`, 定数。

各ファイルの**内蔵 QDrag bg スレッドドライバ**（`def drive()` + `threading.Thread` + pump ループ + watchdog）を `drive_qdrag(...)` 呼び出しへ置換する。`done` 述語は各テストの既存条件（`lambda: view.drop_seen` 等）を渡す。`test_remove_file_preserves_proportions.py` の `faulthandler.dump_traceback_later`/`cancel_dump_traceback_later` 診断は**保持**（drive_qdrag の前後に残す）。座標計算（src/target の物理ピクセル算出）は各テスト固有なので残し、駆動部のみ helper 化する。

- [ ] **Step 1: 載せ替え（test_multi_column_axis.py）**

`drive()`/`worker`/pump ループ（旧 line ~211-256）を以下へ置換:

```python
from tests.realgui._realgui_input import at, drive_qdrag, skip_unless_real_display, to_phys

drive_qdrag(
    (src_phys_x, src_phys_y),
    [(mid_phys_x, mid_phys_y), (tgt_phys_x, tgt_phys_y)],
    done=lambda: view.drop_seen,
)
```

ローカルの `_at`/`_skip`/`_to_phys` 定義と未使用 import（`threading`, `time` が他で不要なら）を削除。`_VK_ESCAPE` 等のローカル定数も helper 由来に統一。

- [ ] **Step 2: 載せ替え（test_move_then_resize.py / test_remove_file_preserves_proportions.py）**

同様に内蔵ドライバを `drive_qdrag` へ置換。`test_move_then_resize.py` は移動 QDrag のみ helper 化し、その後の**リサイズ実ドラッグ**（plain mouse・QDrag でない）は `at()` のループのまま残す。`test_remove_file_preserves_proportions.py` は faulthandler 診断を保持し、QDrag 駆動のみ置換。

- [ ] **Step 3: ヘッドレス collection 確認**

Run: `uv run pytest tests/realgui/ --collect-only -q`
Expected: 全 realgui テストが import/収集でき（構文・import エラー無し）、`--realgui` 未指定で skip 対象として列挙。

- [ ] **Step 4: realgui 無回帰（実 win32・/gui-verify ①ゲート）**

Run: `uv run pytest --realgui tests/realgui/test_multi_column_axis.py tests/realgui/test_move_then_resize.py tests/realgui/test_remove_file_preserves_proportions.py -v`（実ディスプレイでカーソル占有）
Expected: 載せ替え前と同一 pass（無回帰）。ハング無し。`QT_QPA_PLATFORM=windows` で実行。

- [ ] **Step 5: Commit**

```bash
git add tests/realgui/test_multi_column_axis.py tests/realgui/test_move_then_resize.py tests/realgui/test_remove_file_preserves_proportions.py
git commit -m "test(realgui): QDrag テスト3本を共有 drive_qdrag へ載せ替え（無回帰）"
```

---

### Task 3: plain-drag テストをプリミティブへ載せ替え

**Files:**
- Modify: `tests/realgui/test_global_cursor.py`, `tests/realgui/test_active_axis_zoom_pan.py`, `tests/realgui/test_active_axis_resize.py`, `tests/realgui/test_offset_drag.py`

**Interfaces:**
- Consumes: Task 1 の `at`, `key`, `to_phys`, `skip_unless_real_display`, 定数（`MOVE/LDOWN/LUP/VK_RETURN/VK_ESCAPE`）。

これらは QDrag ではない plain mouse ドラッグ（同期 move ループ）。ローカルの `_MOVE/_LDOWN/_LUP` 定数・`_skip_unless_real_display`/`_to_phys`/`_at`/`_key` 定義を削除し、helper から import。呼び出し名を helper の `at`/`key`/`to_phys`/`skip_unless_real_display` に統一。move ループ本体（`for ... at(...)`）と各テストのアサートは**不変**。`test_offset_drag.py` の `_dialog_dismisser`（modal Enter）はオフセット固有なのでローカル保持し、内部の `_key` 呼びを `key` に置換。

- [ ] **Step 1: 4ファイルの定義削除＋import 差し替え**

各ファイル冒頭のローカル定義を削除し:

```python
from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    MOVE,
    VK_ESCAPE,
    VK_RETURN,
    at,
    key,
    skip_unless_real_display,
    to_phys,
)
```

呼び出し箇所の `_at`→`at`, `_to_phys`→`to_phys`, `_skip_unless_real_display`→`skip_unless_real_display`, `_key`→`key`, `_MOVE/_LDOWN/_LUP`→`MOVE/LDOWN/LUP` に置換。

- [ ] **Step 2: ヘッドレス collection 確認**

Run: `uv run pytest tests/realgui/ --collect-only -q`
Expected: import/収集成功・skip 列挙。

- [ ] **Step 3: realgui 無回帰（実 win32）**

Run: `uv run pytest --realgui tests/realgui/test_global_cursor.py tests/realgui/test_active_axis_zoom_pan.py tests/realgui/test_active_axis_resize.py tests/realgui/test_offset_drag.py -v`
Expected: 載せ替え前と同一 pass（無回帰）。

- [ ] **Step 4: Commit**

```bash
git add tests/realgui/test_global_cursor.py tests/realgui/test_active_axis_zoom_pan.py tests/realgui/test_active_axis_resize.py tests/realgui/test_offset_drag.py
git commit -m "test(realgui): plain-drag テスト4本を共有プリミティブへ載せ替え（無回帰）"
```

---

### Task 4: 右クリックテストをプリミティブへ載せ替え＋最終ゲート

**Files:**
- Modify: `tests/realgui/test_file_browser_realclick.py`

**Interfaces:**
- Consumes: Task 1 の `at`, `to_phys`, `skip_unless_real_display`, 定数。

`test_file_browser_realclick.py` の右クリック（`_RDOWN/_RUP` 等のローカル定数・`_at`/`_skip`）を helper へ寄せる。右クリック用フラグ（`RDOWN=0x0008, RUP=0x0010`）が helper に無ければ **Task 1 の helper に追記**（`RDOWN, RUP = 0x0008, 0x0010` を定数に足し、ヘルパ単体テストに1アサート追加）してから本ファイルを載せ替える。

- [ ] **Step 1: 右クリック定数を helper に追加（必要時）＋ファイル載せ替え**

helper に右クリックフラグが無ければ追加し、`tests/file_browser_realclick.py` のローカル入力定義を削除して import 差し替え。

- [ ] **Step 2: ヘッドレス full 検証**

Run: `uv run pytest`
Expected: headless 全 pass / 0 errors（リファクタで増減なし＋ヘルパ単体3-4件増）。

- [ ] **Step 3: lint/format/type**

Run: `uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全てクリーン。

- [ ] **Step 4: realgui 全体 無回帰（実 win32・/gui-verify ①ゲート）**

Run: `uv run pytest --realgui tests/realgui/ -v`
Expected: 全 realgui pass（載せ替え前と同数・無回帰）・ハング無し。証拠ログを残す。

- [ ] **Step 5: Commit**

```bash
git add tests/realgui/test_file_browser_realclick.py tests/realgui/_realgui_input.py tests/gui/test_realgui_input_helper.py
git commit -m "test(realgui): 右クリックテストを共有プリミティブへ載せ替え＋ヘルパ完成"
```

## Self-Review 反映

- spec の「共有基盤」節（`_realgui_input` の構成・`drive_qdrag` の背景スレッド/watchdog）を全て Task でカバー。
- 載せ替え対象は spec の「既存テストを本ヘルパへ載せ替え無回帰で土台を実証」に対応。
- 型/シグネチャ整合: `drive_qdrag`/`to_phys`/`at`/`key`/`skip_unless_real_display` を Task 1 で定義し Task 2-4 で同名 import。
- honest 検証: 本プランはリファクタ（新規 realgui 無し）のため「配線破壊で RED」は次フェーズ。本プランのゲートは realgui **無回帰**（同数 pass）＋ headless full + lint/type。
