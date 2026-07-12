# FU-19 ロードオーバーレイ z-order 背面沈み込み 修正プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** プロット/ドックがある状態で新規ロードすると `BusyOverlay` が不透明なプロット背景に隠れて見えない問題を、`BusyOverlay.show()` に `self.raise_()` を1行加えて解消する。

**Architecture:** overlay は MainWindow の子だが `central_stack`/ドックより先に生成され、Qt 兄弟 z-order（後生成が上）で永久背面に沈む。表示のたびに overlay を最前面へ持ち上げる（`raise_()`）ことで、`cover()` と同じく「表示契約」を `show()` 単一メソッドが所有する。load/export 両経路は同一 `busy_overlay` インスタンスなので1箇所で両方直る。

**Tech Stack:** PySide6（`QWidget.raise_()`）・pytest / pytest-qt・realgui Layer C（実 Win32 入力ヘルパ `tests/realgui/_realgui_input.py`・実ディスプレイ）。

## Global Constraints

- **VM は変更しない**（core は Qt 非依存を維持）。本修正は View 層（`busy_overlay.py`）のみ。
- `cover()`・`eventFilter`（FU-02 リサイズ追従）・`LoadController` のカウントベース可視性・MainWindow の生成順は**不変**。
- `BusyOverlay.isVisible()` を**合格 observable に使わない**（隠蔽されていても `True` を返すことを実機で実証済み＝false-green）。合格判定は「overlay が兄弟の最前面にある／プロット上に描画される」を実測する。
- realgui（Layer C）は実 MainWindow の z-order 経路を通す。素 QWidget 親（overlay が唯一の子＝常に最前面）では FU-19 を exercise できない。
- コミットメッセージ末尾に必須フッタ2行（`Co-Authored-By:` と `Claude-Session:`）を付ける。

---

### Task 1: `BusyOverlay.show()` に `raise_()` を追加（Layer B z-order テスト＋修正）

**Files:**
- Modify: `src/valisync/gui/views/busy_overlay.py`（`show()` メソッド）
- Test: `tests/gui/test_busy_overlay.py`（末尾に z-order テストを追加）

**Interfaces:**
- Consumes: `BusyOverlay(parent)`・`BusyOverlay.show()`（既存）。
- Produces: `show()` が `cover()→super().show()→raise_()` を実行し、overlay を親の子スタック最前面へ移す。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_busy_overlay.py` の末尾に追加。早期生成した overlay と、後生成の兄弟ウィジェットを同一親・同一矩形に置き、`overlay.show()` 後に overlay が兄弟より子スタックで上（＝`children().index` が大きい＝最前面）であることをアサートする。

```python
def test_show_raises_overlay_above_later_created_sibling(qtbot):
    """FU-19: overlay は central/dock より先に生成され兄弟 z-order で背面に沈む。
    show() は overlay を後生成の兄弟より前面へ raise しなければならない。"""
    from PySide6.QtWidgets import QWidget

    from valisync.gui.views.busy_overlay import BusyOverlay

    parent = QWidget()
    qtbot.addWidget(parent)
    overlay = BusyOverlay(parent)  # 先に生成（MainWindow の busy_overlay と同じ早期生成）
    sibling = QWidget(parent)  # 後で生成 = 既定では overlay より上に積まれる
    parent.setGeometry(0, 0, 400, 300)
    sibling.setGeometry(0, 0, 400, 300)  # overlay と同一矩形を覆う不透明兄弟の代役
    parent.show()
    qtbot.waitExposed(parent)

    overlay.show()

    kids = parent.children()
    assert kids.index(overlay) > kids.index(sibling), (
        "FU-19 再発: show() 後も overlay が後生成の兄弟の背面にある "
        f"(overlay idx={kids.index(overlay)}, sibling idx={kids.index(sibling)})"
    )
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/gui/test_busy_overlay.py::test_show_raises_overlay_above_later_created_sibling -v`
Expected: FAIL（`raise_()` 未追加のため overlay は生成順のまま sibling より前 = `index(overlay) < index(sibling)` で assert 失敗）。

- [ ] **Step 3: 最小の実装を書く**

`src/valisync/gui/views/busy_overlay.py` の `show()` を修正:

```python
    def show(self) -> None:
        """Show the overlay, covering the parent and raising it above siblings."""
        self.cover()
        super().show()
        # FU-19: central_stack/ドックは overlay より後に生成され Qt 兄弟 z-order で
        # 上に積まれる。表示のたび最前面へ持ち上げないと不透明なプロット背景に隠れる。
        self.raise_()
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/gui/test_busy_overlay.py -v`
Expected: PASS（新テスト＋既存 BusyOverlay テスト全て）。

- [ ] **Step 5: 品質ゲート**

Run: `uv run ruff check src/valisync/gui/views/busy_overlay.py tests/gui/test_busy_overlay.py && uv run ruff format --check src/valisync/gui/views/busy_overlay.py tests/gui/test_busy_overlay.py && uv run mypy src/valisync/gui/views/busy_overlay.py`
Expected: 全て pass。

- [ ] **Step 6: コミット**

```bash
git add src/valisync/gui/views/busy_overlay.py tests/gui/test_busy_overlay.py
git commit -m "fix(gui): FU-19 BusyOverlay.show() で raise_() し兄弟最前面化 (z-order 背面沈み解消)

..."  # フッタ2行必須
```

---

### Task 2: Layer C realgui — 実 MainWindow のプロット有りロードで overlay がプロット上に立つ

**Files:**
- Create: `tests/realgui/test_fu19_overlay_zorder.py`

**Interfaces:**
- Consumes: `MainWindow`・`window.busy_overlay`・`window._load_controller.submit(...)`（本番 off-thread ロード経路）・`window.graph_area_vm.add_panel`・`tests/realgui/_realgui_input.skip_unless_real_display`。
- Produces: なし（テストのみ）。

- [ ] **Step 1: Layer C テストを書く（新規ファイル）**

実 MainWindow に CSV を同期ロード＋2 パネル化して表示し、**本番の off-thread ロード経路**（`window._load_controller.submit` に blocking callable）を駆動する。ロード実行中に `QApplication.widgetAt(ウィンドウ中心)` が overlay かその子孫を返すこと（＝overlay が不透明プロット上に立つ）をアサートし、スクショを添付する。

```python
"""Layer C: FU-19 — 実 MainWindow でプロットがある状態のロード中に
BusyOverlay が兄弟の最前面へ立ち、プロット上に実描画される (z-order 背面沈み解消)。

`--realgui` opt-in・実ディスプレイ+Windows 必須。素 QWidget 親を使う
test_busy_cancel_realclick.py / test_busy_overlay_resize_realinput.py は overlay が
唯一の子=常に最前面のため FU-19 (central/dock との兄弟 z-order) を exercise できない。
本テストは実 MainWindow の子スタックを通し、隠蔽の有無を QApplication.widgetAt で読む。

observable に isVisible() は使わない — 実機で「隠蔽されても True」を実証済み。合格は
widgetAt(ウィンドウ中心) が overlay かその子孫 (最深子 QProgressBar) を返すこと。

honest-RED: busy_overlay.py の show() から self.raise_() を一時的に外す sabotage で、
widgetAt がプロット QWidget を返し assert が FAIL することを実証する (Step 2)。
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def _make_window_with_two_panels(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    """MainWindow を構築し CSV 1 信号を同期ロード・2 パネル化して実表示する。

    QSettings 隔離は tests/realgui/conftest.py の autouse が効く。ロードは
    session.load→_on_loaded を直接呼んで同期化 (production の完走経路と同じ登録/活性化)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    csv = tmp_path / "sig.csv"
    rows = ["t,speed"]
    for i in range(24):
        rows.append(f"{i * 0.1:.3f},{10.0 + i * 0.8:.4f}")
    csv.write_text("\n".join(rows) + "\n")
    fmt = FormatDefinition(
        name="rt_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    outcome = window.app_vm.session.load(csv, fmt)
    window._on_loaded(outcome)  # 登録+活性化+ChannelBrowser 反映+workbench 表示
    window.graph_area_vm.add_panel(0)  # 2 パネル化 (不透明 pyqtgraph 背景で中央を覆う)

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    w = min(1120, screen.width() - 120)
    h = min(760, screen.height() - 120)
    window.setGeometry(screen.x() + 60, screen.y() + 60, w, h)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(3):
        QApplication.processEvents()
    return window


def _is_overlay_or_descendant(w, overlay) -> bool:  # type: ignore[no-untyped-def]
    while w is not None:
        if w is overlay:
            return True
        w = w.parentWidget()
    return False


@pytest.mark.realgui
def test_overlay_raised_above_plots_during_real_load(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-19 受け入れ: プロット2枚がある実 MainWindow で本番ロード経路を駆動し、
    ロード中に overlay がプロット最前面 (widgetAt が overlay 子孫) に立つ。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    window = _make_window_with_two_panels(qtbot, tmp_path)
    overlay = window.busy_overlay

    release = threading.Event()
    cancel_event = threading.Event()
    discards: list[object] = []

    def slow_load() -> str:
        release.wait(timeout=10.0)  # widgetAt 観測までロードを「実行中」に保つ
        return "late_result"

    # 本番の off-thread ロード経路 (_refresh_busy -> show() -> raise_() を自然に exercise)。
    window._load_controller.submit(
        slow_load,
        busy=overlay,
        cancel_event=cancel_event,
        label="load.mf4",
        on_discard=discards.append,
    )
    qtbot.waitUntil(lambda: not overlay.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: overlay.progress_bar.rect().height() > 0, timeout=3000)
    for _ in range(4):
        QApplication.processEvents()
        time.sleep(0.02)

    # widgetAt は論理グローバル座標 (DPR 換算不要)。overlay が最前面なら中央に
    # 覆い被さる overlay の子 (QProgressBar) を、隠蔽時はプロット QWidget を返す。
    center_g = window.mapToGlobal(window.rect().center())
    w_at = QApplication.widgetAt(center_g)

    shot = tmp_path / "fu19_overlay_over_plots.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot))

    assert _is_overlay_or_descendant(w_at, overlay), (
        f"FU-19 再発: ロード中に widgetAt(中心)={type(w_at).__name__} が overlay "
        f"子孫でない = overlay が不透明プロット背面に隠れている。screenshot: {shot}"
    )

    print(f"[FU-19] overlay raised above plots; widgetAt={type(w_at).__name__}. shot: {shot}")

    release.set()  # blocking ワーカーを排水しスレッドを残さない
    qtbot.waitUntil(lambda: discards == ["late_result"], timeout=3000)
```

- [ ] **Step 2: honest-RED を sabotage で実証**

`src/valisync/gui/views/busy_overlay.py` の `show()` から `self.raise_()` を一時的にコメントアウトし、実行:

Run: `uv run pytest tests/realgui/test_fu19_overlay_zorder.py --realgui -v`
Expected: FAIL（`widgetAt(中心)` がプロット `QWidget` を返し assert 失敗）。確認後 `self.raise_()` を戻す。

- [ ] **Step 3: 修正込みで green を確認**

Run: `uv run pytest tests/realgui/test_fu19_overlay_zorder.py --realgui -v`
Expected: PASS（`widgetAt` が `QProgressBar`＝overlay 子孫）。スクショで overlay がプロット上に可視であることを目視添付。

- [ ] **Step 4: 品質ゲート**

Run: `uv run ruff check tests/realgui/test_fu19_overlay_zorder.py && uv run ruff format --check tests/realgui/test_fu19_overlay_zorder.py`
Expected: pass（realgui テストは mypy 対象外の慣習に従う）。

- [ ] **Step 5: コミット**

```bash
git add tests/realgui/test_fu19_overlay_zorder.py
git commit -m "test(realgui): FU-19 実 MainWindow のプロット有りロードで overlay 最前面を実証

..."  # フッタ2行必須
```

---

## Self-Review

- **Spec coverage**: 修正（`raise_()`）＝Task 1／Layer B z-order＝Task 1／Layer C 実 MainWindow・実ロード経路・widgetAt・スクショ・sabotage-RED＝Task 2。spec の全項目に対応タスクあり。
- **Placeholder scan**: コミットメッセージ本文（`...`）はフッタ必須の指示付きで意図的プレースホルダ。コード/テストは全て完全記述。
- **Type consistency**: `window._load_controller.submit` の引数（`busy`/`cancel_event`/`label`/`on_discard`）は `load_worker.py` の実シグネチャと一致。`overlay.progress_bar`（public 属性）は `busy_overlay.py` 実在。`_is_overlay_or_descendant` は両タスクで整合。
