# FU-02 BusyOverlay 親 resize 追従 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ロード中オーバーレイ `BusyOverlay` が表示中の親ウィンドウ resize に追従せず、ラベル/進捗/キャンセルが旧矩形の中心にズレたまま残る問題（FU-02）を、親の Resize イベント購読＋`cover()` 再実行で根本解決する。

**Architecture:** 変更は `busy_overlay.py` に閉じる。`__init__` で親があれば `parent.installEventFilter(self)`、`eventFilter` で `QEvent.Type.Resize` かつ自身が可視のとき `cover()`（戻り値は常に False=イベント非消費）。非表示時は既存の `show()`→`cover()` が正すため何もしない。「親を覆う」責務が overlay 内で自己完結し親側変更ゼロ。Layer A/B は `parent.resize()`（実 QResizeEvent 配送）駆動、Layer C は repo 初の実 WM リサイズプリミティブ（`SetWindowPos`）を確立して WM_SIZE→QResizeEvent 実経路＋リサイズ後 Cancel 実クリック到達を実証する。

**Tech Stack:** PySide6 (eventFilter / QEvent), pytest-qt, realgui（Win32 `SetWindowPos`/`GetWindowRect` プリミティブを本プランで確立・実クリックは既存 `at()`）

**Spec:** [docs/superpowers/specs/2026-07-11-fu02-busy-overlay-resize-design.md](../specs/2026-07-11-fu02-busy-overlay-resize-design.md)（承認済み A 案・非目標・受け入れ基準の一次情報源）

## Global Constraints

- **ブランチ/worktree**: `worktree-fu02-busy-overlay-resize`（`.claude/worktrees/fu02-busy-overlay-resize`）。main 直接編集禁止。**全ファイル操作は worktree 配下の絶対パスで**（親チェックアウトへの書き込みは既知の事故パターン — 各タスク完了時に `git -C D:/Programming/projects/valisync status --short` clean を確認）。
- **品質ゲート（各コミット前に全て・出力を `| tail` 等に通さない）**: `uv run pytest` ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/`。
- **実装スコープ**: `src/valisync/gui/views/busy_overlay.py`・新規 `tests/gui/test_busy_overlay.py`・`tests/realgui/_realgui_input.py`（`set_window_pos`/`window_rect` 追加）・新規 `tests/realgui/test_busy_overlay_resize_realinput.py`・`.claude/skills/gui-verify/reference/realgui-recipe.md`（実 WM リサイズ節）・`docs/audit-findings-catalog.md` のみ。`LoadController`／背景 dim 化／`setParent` 張り直しは触らない（spec 非目標）。
- **Layer A/B は `parent.resize()` 駆動**（実 QResizeEvent が配送される）。`overlay.eventFilter(...)` を直接呼ぶハンドラ直叩きは実経路を迂回するため禁止。
- **realgui**: WM リサイズは `SetWindowPos`（Qt 外部からの実 OS ウィンドウ操作＝WM_SIZE→QResizeEvent 実経路）、クリックは実マウス `at()`。`widget.resize()`・合成 `QResizeEvent`・resize 後の手動 `cover()` 挟み込みは Layer C 偽装/バグ隠蔽。スクショ（`grabWindow(0)`）＋目視判定必須。「skipped」は「検証済み」ではない。
- **`isVisible()` を「画面内にある」証拠に使わない**（既知の罠）。本件の追従判定は `geometry() == parent.rect()` の直接比較で行う。
- **ruff confusables（RUF001-003）**: `…` リテラルは安全。`・` を ASCII 隣接で使わない。括弧は ASCII 優先。
- **`- [ ]` チェックボックスで進捗管理**。コミットメッセージ末尾に Co-Authored-By / Claude-Session フッタ。

---

### Task 1: eventFilter 実装と Layer A/B テスト（TDD）

**Files:**
- Modify: `src/valisync/gui/views/busy_overlay.py`（`__init__` に filter 設置＋`eventFilter` override）
- Create: `tests/gui/test_busy_overlay.py`（BusyOverlay 専用の Layer A/B — 既存は test_load_worker.py/test_main_window.py 経由のみで専用ファイルが無かった）

**Interfaces:**
- Consumes: `BusyOverlay.cover()`／`show()`（既存・変更しない）
- Produces: `BusyOverlay.eventFilter(watched: QObject, event: QEvent) -> bool`（Qt override・常に False 返し）。不変条件: `cover()`/`show()`/`set_message()`/`cancel_requested` 配線・`parent=None` 構築の no-op は従来どおり。

- [x] **Step 1: 失敗するテストを書く**

`tests/gui/test_busy_overlay.py` を新規作成:

```python
"""BusyOverlay の Layer A/B: 親 resize 追従 (FU-02) と表示契約。

resize は `parent.resize()` で駆動する (実 QResizeEvent が配送され eventFilter
の実経路を通る)。`overlay.eventFilter(...)` の直接呼び出しはハンドラ直叩き=
実経路の迂回になるため使わない。
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.busy_overlay import BusyOverlay


def _shown_parent(qtbot: QtBot, w: int = 400, h: int = 300) -> QWidget:
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(w, h)
    parent.show()
    qtbot.waitExposed(parent)
    return parent


def test_visible_overlay_tracks_parent_resize(qtbot: QtBot) -> None:
    """FU-02: 表示中の親 resize (拡大/縮小の両方向) に overlay が追従する。

    修正前は show() 時の cover() だけで resize 後も旧ジオメトリのまま RED
    (実測: window を 1400x844 から 1024x650 にしても overlay は 1400x844)。
    """
    parent = _shown_parent(qtbot)
    overlay = BusyOverlay(parent)
    overlay.show()
    assert overlay.geometry() == parent.rect()

    parent.resize(640, 480)  # 拡大
    QApplication.processEvents()
    assert parent.size() == QSize(640, 480)  # イベント非消費 (親の resize は成立)
    assert overlay.geometry() == parent.rect()  # 追従 (修正前はここで RED)

    parent.resize(320, 240)  # 縮小 (実機で観測された方向)
    QApplication.processEvents()
    assert overlay.geometry() == parent.rect()


def test_hidden_overlay_covers_on_next_show_after_resize(qtbot: QtBot) -> None:
    """非表示中の resize は無害 — 次回 show() の cover() で正す (既存挙動の回帰ガード)。"""
    parent = _shown_parent(qtbot)
    overlay = BusyOverlay(parent)
    parent.resize(640, 480)
    QApplication.processEvents()
    overlay.show()
    assert overlay.geometry() == parent.rect()


def test_parentless_overlay_show_does_not_crash(qtbot: QtBot) -> None:
    """parent なし構築でも show()/cover() は no-op で成立する (既存契約)。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    overlay.show()
    assert overlay.isVisible()
```

- [x] **Step 2: RED を確認**

Run: `uv run pytest tests/gui/test_busy_overlay.py -v`
Expected: 新規3テスト中1つが FAIL —
- `test_visible_overlay_tracks_parent_resize`: 拡大後の `overlay.geometry() == parent.rect()` で AssertionError（overlay は 400x300 のまま）
- `test_hidden_overlay_covers_on_next_show_after_resize` と `test_parentless_overlay_show_does_not_crash` は PASS（既存挙動の回帰ガードで最初から緑が正しい）

- [x] **Step 3: 最小実装（eventFilter）**

`src/valisync/gui/views/busy_overlay.py` — import 行を変更:

```python
from PySide6.QtCore import QEvent, QObject, Qt, Signal
```

`__init__` 末尾（`self.hide()` の直後）に追加:

```python
        # FU-02: 表示中に親が resize されると cover() が stale になり、透過
        # overlay のラベル/キャンセルが旧矩形の中心へズレて届きにくくなる。
        # 親の Resize を購読して追従する (親側の変更なしで自己完結)。
        if parent is not None:
            parent.installEventFilter(self)
```

クラス末尾にメソッド追加:

```python
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # 親の resize へ追従 (可視時のみ — 非表示時は show() が cover する)。
        # False を返しイベントは消費しない (親の通常の resize 処理を妨げない)。
        # filter は親にのみ install しているため watched は常に親。
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self.cover()
        return False
```

- [x] **Step 4: GREEN を確認**

Run: `uv run pytest tests/gui/test_busy_overlay.py tests/gui/test_load_worker.py -v`
Expected: 全 PASS（test_load_worker.py＝controller 駆動の show/hide/メッセージ既存挙動を含む）

- [x] **Step 5: 品質ゲート**

Run: `uv run pytest` → 0 failures ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/` → 全 clean。加えて `git -C D:/Programming/projects/valisync status --short` が clean（親チェックアウト非汚染）。

- [x] **Step 6: コミット**

```bash
git add src/valisync/gui/views/busy_overlay.py tests/gui/test_busy_overlay.py
git commit -m "fix(gui): FU-02 BusyOverlay が親の resize に追従するよう eventFilter 購読を追加"
```

---

### Task 2: realgui — 実 WM リサイズ→追従→Cancel 実クリック（SetWindowPos プリミティブ確立＋sabotage-RED）

**Files:**
- Modify: `tests/realgui/_realgui_input.py`（`set_window_pos`/`window_rect` プリミティブ）
- Create: `tests/realgui/test_busy_overlay_resize_realinput.py`
- Modify: `.claude/skills/gui-verify/reference/realgui-recipe.md`（実 WM リサイズ節を追記）
- （sabotage で一時変更→復元: `src/valisync/gui/views/busy_overlay.py` — コミットしない）

**Interfaces:**
- Consumes: Task 1 の `BusyOverlay.eventFilter`／`_realgui_input.py` の `at`/`LDOWN`/`LUP`/`skip_unless_real_display`／先行例 `tests/realgui/test_busy_cancel_realclick.py` の LoadController＋blocking callable パターン
- Produces: 共有プリミティブ `set_window_pos(hwnd: int, x: int, y: int, w: int, h: int) -> None` と `window_rect(hwnd: int) -> tuple[int, int, int, int]`（物理ピクセル・外枠基準）／realgui 証拠（①ゲート充足物）

- [ ] **Step 1: WM リサイズプリミティブを共有ヘルパへ追加**

`tests/realgui/_realgui_input.py` — module 冒頭の import 群はそのまま（`ctypes` は既存）。`wheel()` の下に追加:

```python
class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """トップレベルウィンドウの外枠 (left, top, width, height)・物理ピクセル。"""
    r = _RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def set_window_pos(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """実 OS の WM 経由でトップレベルウィンドウを移動/リサイズする。

    user32.SetWindowPos (SWP_NOZORDER) を Qt の外から発行し、WM_SIZE ->
    QResizeEvent の実変換経路を通す (widget.resize() は Qt 内部経路のため
    WM を経由しない・FU-02 で確立)。座標は物理ピクセル・外枠基準 —
    現在値は window_rect() で取得して差分リサイズすると DPR 換算が不要。
    """
    swp_nozorder = 0x0004
    _user32.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), swp_nozorder)
```

- [ ] **Step 2: realgui テストを書く**

`tests/realgui/test_busy_overlay_resize_realinput.py` を新規作成:

```python
"""Layer C: FU-02 — 表示中の BusyOverlay が実 WM リサイズに追従し、
リサイズ後のキャンセルボタンへ実クリックが届く (到達性の直接反証)。

`--realgui` opt-in・実ディスプレイ+Windows 必須。リサイズは Win32
`SetWindowPos` (repo 初のプリミティブ・Qt 外部からの実 OS ウィンドウ操作 =
WM_SIZE -> QResizeEvent の実変換経路) で駆動する — `widget.resize()` は
Qt 内部経路のため WM を経由せず、この経路の代理にならない。クリックは
実マウス (`at()`)。オーバーレイの表示は先行例
tests/realgui/test_busy_cancel_realclick.py と同じ LoadController +
blocking callable パターン (MainWindow と同一配線)。

honest-RED: `busy_overlay.py` の `parent.installEventFilter(self)` を一時的に
外す sabotage で、リサイズ後の geometry 一致 assert が実際に FAIL することを
実証済み (Task 2 Step 4)。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    at,
    set_window_pos,
    skip_unless_real_display,
    window_rect,
)

pytestmark = pytest.mark.realgui


def test_overlay_tracks_real_wm_resize_and_cancel_click_lands(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-02 受け入れ: 実 WM 縮小リサイズ後も overlay が親全域を覆い、
    キャンセル実クリックが cancel_requested を発火して overlay が隠れる。"""
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget

    from valisync.gui.views.busy_overlay import BusyOverlay
    from valisync.gui.workers.load_worker import LoadController

    release = threading.Event()
    cancel_event = threading.Event()
    discards: list[object] = []

    def slow_load() -> str:
        release.wait(timeout=10.0)  # クリックまでロードを「実行中」に保つ
        return "late_result"

    parent = QWidget()
    qtbot.addWidget(parent)
    overlay = BusyOverlay(parent)
    controller = LoadController()
    overlay.cancel_requested.connect(controller.cancel_active)  # main_window と同配線

    parent.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    parent.setGeometry(screen.x() + 60, screen.y() + 60, 900, 600)
    parent.show()
    qtbot.waitExposed(parent)
    for _ in range(3):
        QApplication.processEvents()

    controller.submit(
        slow_load,
        busy=overlay,
        cancel_event=cancel_event,
        label="a.mf4",
        on_discard=discards.append,
    )
    qtbot.waitUntil(lambda: not overlay.isHidden(), timeout=3000)
    assert overlay.geometry() == parent.rect()  # 表示直後は一致 (既存 cover)

    # 実 WM 経由で縮小 (実機で観測された方向)。座標は物理・外枠基準なので
    # 現在の実枠から差分で縮める (DPR 換算不要)。
    hwnd = int(parent.winId())
    left, top, w, h = window_rect(hwnd)
    old_client_w = parent.width()
    set_window_pos(hwnd, left, top, w - 300, h - 200)
    qtbot.waitUntil(lambda: parent.width() < old_client_w, timeout=3000)  # WM_SIZE 到達
    for _ in range(4):
        QApplication.processEvents()
        time.sleep(0.02)

    shot_resized = tmp_path / "fu02_after_wm_resize.png"
    QApplication.primaryScreen().grabWindow(0).save(str(shot_resized))
    # 修正の核: リサイズ後も overlay が親全域と一致 (sabotage 時ここで FAIL)。
    assert overlay.geometry() == parent.rect(), (
        f"FU-02 再発: WM リサイズ後 overlay={overlay.geometry()} が "
        f"parent={parent.rect()} に追従していない。screenshot: {shot_resized}"
    )

    # リサイズ後のキャンセルボタン実座標を実クリック -> 発火＋overlay 非表示。
    qtbot.waitUntil(lambda: overlay.cancel_button.rect().height() > 0, timeout=3000)
    center = overlay.cancel_button.rect().center()
    gp = overlay.cancel_button.mapToGlobal(center)
    dpr = overlay.devicePixelRatioF()
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)
    with qtbot.waitSignal(overlay.cancel_requested, timeout=3000):
        at(phys_x, phys_y, LDOWN)
        QApplication.processEvents()
        time.sleep(0.05)
        at(phys_x, phys_y, LUP)
        for _ in range(4):
            QApplication.processEvents()
            time.sleep(0.02)

    print(f"[FU-02] overlay tracked resize; cancel click landed. shot: {shot_resized}")
    assert overlay.isHidden(), (
        f"cancel_requested は発火したが overlay が隠れない。screenshot: {shot_resized}"
    )
    assert cancel_event.is_set(), "実クリックで hard-cancel が立っていない"

    release.set()  # キャンセル済みワーカーを排水しスレッドを残さない
    qtbot.waitUntil(lambda: discards == ["late_result"], timeout=3000)
```

- [ ] **Step 3: 契約ガード適合を確認**

Run: `uv run pytest tests/gui/test_realgui_layer_c_contract.py -v`
Expected: PASS（新ファイルは `at`＋`grabWindow` を使う実入力テストとして受理）

- [ ] **Step 4: sabotage honest-RED — filter 設置を一時的に外して実 FAIL を実証**

`src/valisync/gui/views/busy_overlay.py` の `parent.installEventFilter(self)` 行を一時的にコメントアウト（**コミット禁止**）:

```python
            pass  # SABOTAGE: parent.installEventFilter(self)  (コミット禁止)
```

Run: `uv run pytest --realgui tests/realgui/test_busy_overlay_resize_realinput.py -v`
Expected: **FAIL** — リサイズ後の `overlay.geometry() == parent.rect()` で AssertionError（overlay が旧サイズのまま＝catalog 実測と同型）。失敗 assert とメッセージを記録する。

- [ ] **Step 5: sabotage を復元**

```bash
git restore src/valisync/gui/views/busy_overlay.py
git diff --stat   # 差分ゼロ確認
```

- [ ] **Step 6: GREEN — realgui 実行＋スクショ目視**

Run: `uv run pytest --realgui tests/realgui/test_busy_overlay_resize_realinput.py -v`
Expected: PASS。スクショ `fu02_after_wm_resize.png` を Read で開き、**縮小後のウィンドウ内で「読み込み中」ラベル・進捗バー・キャンセルボタンが中央に位置している**ことを目視確認し、判定コメントを記録する。

- [ ] **Step 7: realgui レシピへ実 WM リサイズ節を追記**

`.claude/skills/gui-verify/reference/realgui-recipe.md` の末尾（実ホイール節の後）に追加:

```markdown

## 実 WM 経由のウィンドウリサイズ（SetWindowPos）

`_realgui_input.set_window_pos(hwnd, x, y, w, h)`＋`window_rect(hwnd)`（FU-02 で確立）: Qt の外から `user32.SetWindowPos`（SWP_NOZORDER）を発行し、WM_SIZE → QResizeEvent の実変換経路を通す。`widget.resize()` は Qt 内部経路のため WM を経由せず、この経路の代理にならない。

- hwnd は `int(widget.winId())`。座標は**物理ピクセル・外枠基準** — 現在値を `window_rect()` で取得して差分リサイズすると DPR 換算が不要。
- OLE ループは無い — `processEvents` の pump で配送される。到達確認は `qtbot.waitUntil(lambda: parent.width() が変化)` を挟んでからジオメトリを assert する。
- 実例: `tests/realgui/test_busy_overlay_resize_realinput.py`。
```

- [ ] **Step 8: ①証拠ゲート記録**

`- [ ] uv run pytest --realgui tests/realgui/test_busy_overlay_resize_realinput.py の pass ログ＋スクショ＋目視判定コメントを PR 説明/実行ログに残す（merge 前ゲート: (a) full pytest 0 fail ＋ (b) 本証拠 ＋ (c) CI 緑）`

- [ ] **Step 9: 品質ゲート**

Run: `uv run pytest` ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/` → 全 clean。親チェックアウト clean 確認。

- [ ] **Step 10: コミット**

```bash
git add tests/realgui/_realgui_input.py tests/realgui/test_busy_overlay_resize_realinput.py .claude/skills/gui-verify/reference/realgui-recipe.md
git commit -m "test(realgui): FU-02 実 WM リサイズ追従＋Cancel 実クリック E2E (SetWindowPos プリミティブ確立・sabotage-RED 実証済み)"
```

---

### Task 3: ドキュメント反映（catalog の FU-02 完了化）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（FU-02 行＋フォローアップ節の冒頭サマリ）

**Interfaces:**
- Consumes: Task 1/2 の結果
- Produces: FU-02 の完了記録（バケット③の不具合修正が全て完了）

- [ ] **Step 1: FU-02 行を ✅ 完了へ更新**

`docs/audit-findings-catalog.md` の FU-02 行（`| FU-02 | 🟡 |` で始まる行）の先頭2セルを `| FU-02 | ✅ |` に変え、**説明セル（第3セル）の冒頭に**次を追記する。既存の説明文は一字一句そのまま残し（歴史）、場所セル・影響セルは**変更しない**。テーブル行構造（`|` セル数・1行）を壊さない:

```
**✅解消（2026-07-11・PR #XX）**: `BusyOverlay` 自身が親を `installEventFilter` で購読し、親の `Resize` で（可視時のみ）`cover()` を再実行して追従（イベント非消費・`show()`→`cover()` 既存契約/cancel 配線/親側コードは不変）。Layer A/B=表示中 resize 追従（拡大/縮小・実 QResizeEvent 駆動）・非表示 resize 無害・イベント非消費、Layer C=実 WM リサイズ（repo 初の `SetWindowPos`/`window_rect` プリミティブ＝WM_SIZE→QResizeEvent 実経路）→追従→リサイズ後の Cancel 実クリック→`cancel_requested`＋overlay hide＋hard-cancel（sabotage-RED=eventFilter 除去で実証）。
```

（`#XX` は PR 作成後の追いコミットで実番号へ置換。）

- [ ] **Step 2: フォローアップ節の冒頭サマリを更新**

同ファイルのフォローアップ節冒頭段落の部分文字列 `FU-04/FU-01 は✅解消（2026-07-11・下記）。残る修正は FU-02` を `FU-04/FU-01/FU-02 は✅解消（2026-07-11・下記）。確定不具合の修正は完了（FU-03 は未再現・FU-05/06/09 は UX 要望）` へ置換する（これ以外は触らない）。

- [ ] **Step 3: 品質ゲート＋コミット**

Run: `uv run pytest` ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/`

```bash
git add docs/audit-findings-catalog.md
git commit -m "docs: FU-02 を catalog で完了マーク（BusyOverlay の親 resize 追従）"
```

---

## 完了後の手続き（プラン外・セッション本体で実施）

1. `superpowers:finishing-a-development-branch` — push・`gh pr create`（PR 本文に realgui 証拠）・`gh pr checks <num> --watch` で CI 緑確認・`gh pr merge <num> --squash`（`--delete-branch` は worktree 構成でローカル checkout に失敗するため使わず、remote 削除は後片付けで行う）。
2. catalog の `#XX` を実 PR 番号へ置換（PR 作成後の追いコミット）。
3. merge 前に `/gui-verify`（①ゲートの scoped 実行）。
4. merge 後の後片付けで**親チェックアウトの `git status` も確認**（memory `worktree_subagent_parent_checkout_leak`）。
5. CLAUDE.md / docs / memory への知見追記をユーザーに確認（候補: SetWindowPos 実 WM リサイズはレシピに Task 2 で記録済み）。
