# FU-04 Recent ボタン最小幅有界化 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WelcomeView の Recent Files ボタンがフルパス長に比例した最小幅を要求してウィンドウ最小幅を画面幅超過まで膨張させる問題（FU-04: Diagnostics 切替でブラウザドックが画面外へ押し出され操作不能）を、ボタンラベルの中央省略（ElideMiddle）＋フルパス tooltip で根本解決する。

**Architecture:** 修正は `WelcomeView.refresh()` のボタン生成1箇所に閉じる。ラベルを `QFontMetrics.elidedText(path, ElideMiddle, _RECENT_LABEL_MAX_W)` で有界化し、フルパスは tooltip とクリック emit に完全保持。ウィンドウ/画面幅クランプ・QStackedWidget の「全ページ最大」抑制は**行わない**（非目標 — 意図的な大画面表示を殺さないため）。検証は Layer A（有界性・表示/保持の headless）＋ Layer C（realgui: 実 OS クリックで Diagnostics 実トグル→ドックが画面内に留まる）。

**Tech Stack:** PySide6 (QPushButton / QFontMetrics / QStackedWidget / QDockWidget), pytest-qt, realgui（Win32 実 OS 入力 `tests/realgui/_realgui_input.py`）

**Spec:** [docs/superpowers/specs/2026-07-11-fu04-recent-button-minwidth-design.md](../specs/2026-07-11-fu04-recent-button-minwidth-design.md)（根因の実測連鎖・設計判断・非目標はここが一次情報源）

## Global Constraints

- **ブランチ/worktree**: `worktree-fu04-dock-offscreen`（`.claude/worktrees/fu04-dock-offscreen`）。main 直接編集禁止。
- **品質ゲート（各コミット前に全て）**: `uv run pytest` ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/`。ゲート出力を `| tail` 等に通さない（exit code が隠れる）。
- **実装スコープは `src/valisync/gui/views/welcome_view.py` のみ**（spec 非目標: クランプ・stack 抑制・`_rebuild_recent_menu` のメニュー項目は触らない）。
- **超長パスは実ファイルを作らない**: Windows MAX_PATH(260) で作成不能。`existing()` だけを持つ duck-stub `_FakeRecent` をテスト側で注入する（WelcomeView は `_recent.existing()` しか呼ばない）。
- **`isVisible()` を「画面内にある」証拠に使わない**: QDockWidget は画面外でも `isVisible()==True`（FU-04 調査の偽陰性計器）。画面内判定は `visibleRegion` 非空＋グローバル矩形が screen 内。逆方向（`not isVisible()`＝隠れた）は健全なので使用可。
- **realgui は実 OS 入力のみ**: `_realgui_input.at()`（`SetCursorPos`+`mouse_event`）で駆動。`qtbot.mouseClick`/`action.trigger()` は Layer C 偽装であり `tests/gui/test_realgui_layer_c_contract.py` が CI で落とす。スクショ（`grabWindow(0)`）保存＋目視判定必須。
- **ruff の confusable 文字（RUF001-003）**: 省略記号 `…`（U+2026）はリテラルで安全（src 全域で実績あり）。一方 `・`（中黒）を ASCII 文字に隣接させると RUF001-003 に抵触しうる（`main_window.py` の `# noqa: RUF001` 実例）— コメント/文字列の記号は既存コードで実績のある表記に合わせ、括弧は ASCII を優先。
- **`- [ ]` チェックボックスで進捗管理**。コミットメッセージ末尾に Co-Authored-By / Claude-Session フッタ。

---

### Task 1: ラベル省略＋tooltip 化と Layer A 有界性テスト

> **実装ノート（Task 1 完了・commits 7778660+19cbfac）**: レビューで brief 内部の非整合（360px 予算 vs 15字サフィックス assert）を検出。production は仕様値 360 のまま、テスト側を頑健化（`_LONG_PATH` のファイル名を `m.mf4` 5字に短縮し `endswith("m.mf4")` へ）。ElideMiddle の末尾保持は約半予算（~180px）のため、長いファイル名の全文保持は保証されない。

**Files:**
- Modify: `src/valisync/gui/views/welcome_view.py`（`refresh()` のボタン生成＋モジュール定数）
- Test: `tests/gui/test_welcome_view.py`（有界性・省略/保持・短パス無変化）
- Test: `tests/gui/test_main_window.py`（ウィンドウ最小幅のパス長不変性＋大画面リサイズ回帰ガード）

**Interfaces:**
- Consumes: `WelcomeView._recent.existing() -> list[str]`（既存・変更しない）／`RecentFiles`（既存・変更しない）
- Produces: `valisync.gui.views.welcome_view._RECENT_LABEL_MAX_W: int = 360`（モジュール定数。テストが import して単一の真実として使う）。Recent ボタンの不変条件: `btn.text()` は省略済み（描画幅 ≤ `_RECENT_LABEL_MAX_W`）・`btn.toolTip() == フルパス`・クリックは `open_requested(フルパス)` を emit。

- [x] **Step 1: 定数だけ先に追加（挙動不変）**

`src/valisync/gui/views/welcome_view.py` の import 群の直後（`class WelcomeView` の前）に追加:

```python
# FU-04: Recent ボタンのラベル省略予算 (px)。フルパスをそのままラベルにすると
# minimumSizeHint がパス長に比例し、中央 QStackedWidget (全ページ最大) 経由で
# ウィンドウ最小幅が画面幅を超え、再レイアウト時に右側ドックが画面外へ
# 押し出される。ラベル側の有界化が根本解決 (spec 2026-07-11-fu04 参照)。
_RECENT_LABEL_MAX_W = 360
```

- [x] **Step 2: 失敗するテストを書く（WelcomeView 単体）**

`tests/gui/test_welcome_view.py` の import に `_RECENT_LABEL_MAX_W` を追加:

```python
from valisync.gui.views.welcome_view import _RECENT_LABEL_MAX_W, WelcomeView
```

ファイル末尾に追加:

```python
class _FakeRecent:
    """existing() だけを使う WelcomeView への duck-type 注入。

    超長パスは Windows MAX_PATH(260) で実ファイル化できないため、
    実在しないパス文字列を直接返して最小幅膨張(FU-04)を再現する。
    """

    def __init__(self, paths: list[str]) -> None:
        self._paths = paths

    def existing(self) -> list[str]:
        return list(self._paths)


_LONG_PATH = "C:/" + "d" * 400 + "/measurement.mf4"


def test_recent_button_min_width_bounded_for_long_path(qtbot: QtBot) -> None:
    """FU-04: 超長パスでもボタン/ビューの最小幅が省略予算+余白に収まる。

    修正前 (QPushButton(path)) はパス長に比例して ~2800px となり RED。
    """
    view = WelcomeView(_FakeRecent([_LONG_PATH]))  # type: ignore[arg-type]
    qtbot.addWidget(view)
    row0 = view._recent_box.itemAt(0).widget()
    assert isinstance(row0, QPushButton)
    assert row0.minimumSizeHint().width() <= _RECENT_LABEL_MAX_W + 100
    assert view.minimumSizeHint().width() <= _RECENT_LABEL_MAX_W + 150


def test_recent_button_label_elided_but_click_and_tooltip_keep_full_path(
    qtbot: QtBot,
) -> None:
    """表示は省略・保持は完全: tooltip とクリック emit はフルパスのまま。"""
    view = WelcomeView(_FakeRecent([_LONG_PATH]))  # type: ignore[arg-type]
    qtbot.addWidget(view)
    got: list[object] = []
    view.open_requested.connect(got.append)
    row0 = view._recent_box.itemAt(0).widget()
    assert isinstance(row0, QPushButton)
    assert row0.text() != _LONG_PATH  # 省略されている
    assert "…" in row0.text()  # ElideMiddle の省略記号
    assert row0.text().endswith("measurement.mf4")  # 末尾のファイル名は保持
    assert row0.toolTip() == _LONG_PATH  # フルパスは tooltip で提供
    row0.click()
    assert got == [_LONG_PATH]  # クリックは表示テキストでなくフルパスを emit


def test_short_recent_path_label_not_elided(qtbot: QtBot) -> None:
    """予算内の短パスは従来どおり全文表示 (省略の副作用ガード)。

    注意: tmp_path の実パスは 70-90 字 (~600px) で省略予算 360px を超えるため
    「短い」の代表に使えない。真に短い偽パスを stub で注入する。
    """
    short = "C:/data/a.mf4"
    view = WelcomeView(_FakeRecent([short]))  # type: ignore[arg-type]
    qtbot.addWidget(view)
    row0 = view._recent_box.itemAt(0).widget()
    assert isinstance(row0, QPushButton)
    assert row0.text() == short  # elidedText は予算内の文字列を無変更で返す
    assert row0.toolTip() == short
```

- [x] **Step 3: 失敗するテストを書く（MainWindow 最小幅の不変性）**

`tests/gui/test_main_window.py` の末尾に追加（`MainWindow` / `AppViewModel` はモジュール先頭で import 済みのものを使う。無ければ関数内 import）:

```python
class _FakeRecentForMinWidth:
    """existing() だけの duck-stub (test_welcome_view.py と同型。タスク独立性のため重複可)。"""

    def __init__(self, paths: list[str]) -> None:
        self._paths = paths

    def existing(self) -> list[str]:
        return list(self._paths)


def test_window_min_width_does_not_scale_with_recent_path_length(qtbot) -> None:
    """FU-04: Recent のパス長がウィンドウ最小幅を駆動しない。

    修正前は 150 文字→400 文字で最小幅が ~1700px 増える (RED)。修正後は
    どちらも同じ省略予算に収まり差は省略粒度 (数 px) 以内。絶対値でなく
    不変性で assert するのでスタイル/フォント差に頑健。
    """
    from PySide6.QtWidgets import QApplication

    def min_width_with(path: str) -> int:
        mw = MainWindow(AppViewModel())
        qtbot.addWidget(mw)
        mw.welcome_view._recent = _FakeRecentForMinWidth([path])  # type: ignore[assignment]
        mw.welcome_view.refresh()
        # spec の実シナリオ: グラフエリア表示中 (WelcomeView は QStackedWidget の
        # 隠れページ) でも「全ページ最大」経由で最小幅を支配する経路を再現する。
        mw._workbench_started = True
        mw._update_central()
        assert not mw.showing_welcome()
        QApplication.processEvents()
        return mw.minimumSizeHint().width()

    w_mid = min_width_with("C:/" + "d" * 150 + "/m.mf4")
    w_long = min_width_with("C:/" + "d" * 400 + "/m.mf4")
    assert w_long <= w_mid + 16


def test_window_can_still_be_resized_beyond_screen(qtbot) -> None:
    """spec 受け入れ 3: 意図的な大画面表示は不変 (最大幅制約を導入していない)。

    offscreen は WM クランプが無いので、resize がそのまま通る=コード側に
    上限が無いことの回帰ガード。
    """
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.resize(3000, 700)
    assert mw.width() == 3000
```

- [x] **Step 4: RED を確認**

Run: `uv run pytest tests/gui/test_welcome_view.py tests/gui/test_main_window.py -v`
Expected: 新規5テスト中4つが FAIL —
- `test_recent_button_min_width_bounded_for_long_path`: 幅 ~2800 > 460 で AssertionError
- `test_recent_button_label_elided_but_click_and_tooltip_keep_full_path`: `row0.text() != _LONG_PATH` で AssertionError（現状は text == フルパス）
- `test_short_recent_path_label_not_elided`: `row0.toolTip() == short` で AssertionError（現状は tooltip 未設定＝空文字。text の assert は現状も通る）
- `test_window_min_width_does_not_scale_with_recent_path_length`: 差 ~1700 > 16 で AssertionError
- `test_window_can_still_be_resized_beyond_screen` と既存テストは PASS（回帰ガードは最初から緑で正しい — 現状も上限は無いため）

- [x] **Step 5: 最小実装（elide + tooltip）**

`src/valisync/gui/views/welcome_view.py` の `refresh()` 内ループを変更:

```python
        for path in self._recent.existing():
            btn = QPushButton()
            btn.setFlat(True)
            # ラベルだけ中央省略で有界化 (FU-04)。ElideMiddle はドライブ名と
            # 末尾ファイル名を残す。フルパスは tooltip とクリック emit に保持。
            fm = btn.fontMetrics()
            btn.setText(
                fm.elidedText(path, Qt.TextElideMode.ElideMiddle, _RECENT_LABEL_MAX_W)
            )
            btn.setToolTip(path)
            btn.clicked.connect(lambda _=False, p=path: self._emit_recent(p))
            self._recent_box.addWidget(btn)
```

（変更点は `QPushButton(path)` → `QPushButton()`＋`setText(elidedText(...))`＋`setToolTip(path)` のみ。`clicked` 配線・`setFlat`・追加順は不変。）

- [x] **Step 6: GREEN を確認**

Run: `uv run pytest tests/gui/test_welcome_view.py tests/gui/test_main_window.py -v`
Expected: 全 PASS（既存の `test_recent_row_click_emits_its_path` 等の無回帰を含む）

- [x] **Step 7: 品質ゲート**

Run: `uv run pytest` → 0 failures ／ `uv run ruff check` → clean ／ `uv run ruff format --check` → clean（差分が出たら `uv run ruff format` 後に再確認）／ `uv run mypy src/` → clean

- [x] **Step 8: コミット**

```bash
git add src/valisync/gui/views/welcome_view.py tests/gui/test_welcome_view.py tests/gui/test_main_window.py
git commit -m "fix(gui): FU-04 Recent ボタンのラベルを ElideMiddle 省略しウィンドウ最小幅の膨張を根絶"
```

---

### Task 2: Layer C realgui — 実トグルでドックが画面内に留まる（honest-RED 実証込み）

**Files:**
- Create: `tests/realgui/test_dock_onscreen_after_toggle.py`
- （sabotage で一時変更→復元: `src/valisync/gui/views/welcome_view.py` — コミットしない）

**Interfaces:**
- Consumes: Task 1 の修正済み `WelcomeView.refresh()`／`MainWindow.diagnostics_dock`・`main_toolbar`（objectName）・`file_dock`・`channel_dock`（既存属性）／`tests/realgui/_realgui_input.py` の `at`/`LDOWN`/`LUP`/`skip_unless_real_display`／`tests/realgui/conftest.py` の autouse QSettings 隔離
- Produces: realgui 証拠（pass ログ＋スクショ2枚）— ①ゲートの充足物

- [x] **Step 1: realgui テストを書く**

`tests/realgui/test_dock_onscreen_after_toggle.py` を新規作成:

```python
"""Layer C: FU-04 — 超長 Recent パス登録時でも Diagnostics 実トグルで
File/Channel Browser ドックが画面内に留まる。

`--realgui` opt-in・実ディスプレイ+Windows 必須。この受け入れは Layer A/B で
再チェック不能: offscreen では geometry が実配置にならず、最小幅制約→OS の
画面幅クランプ→再レイアウトでドックが画面外へ押し出される連鎖は実ウィンドウ
マネージャ下でしか起きない (memory: gui_isvisible_true_for_offscreen_hidden_dock)。

判定は自動 assert (visibleRegion + 画面内グローバル矩形。isVisible() は画面外
でも True を返す FU-04 の偽陰性計器なので「画面内」の証拠に使わない) に加え、
各操作後のスクリーンショットを人/AI が目視確認する。

honest-RED: Task 2 Step 2 で elide を一時的に外し (btn.setText(path))、本テストが
実際に FAIL する (ウィンドウ最小幅が画面幅超過→ドック画面外) ことを実証済み。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


class _FakeRecent:
    """existing() だけの duck-stub。超長パスは MAX_PATH(260) で実ファイル化
    できないため文字列を直接注入する (入力=実 OS クリックは無傷のまま)。"""

    def __init__(self, paths: list[str]) -> None:
        self._paths = paths

    def existing(self) -> list[str]:
        return list(self._paths)


def _onscreen(dock) -> bool:  # type: ignore[no-untyped-def]
    """画面内判定: visibleRegion 非空 + グローバル矩形が screen 内 + 実幅。

    isVisible() は画面外/タブ裏でも True (FU-04 の偽陰性計器) のため使わない。
    """
    from PySide6.QtWidgets import QApplication

    scr = QApplication.primaryScreen().geometry()
    tl = dock.mapToGlobal(dock.rect().topLeft())
    br = dock.mapToGlobal(dock.rect().bottomRight())
    return (
        scr.contains(tl)
        and scr.contains(br)
        and not dock.visibleRegion().isEmpty()
        and dock.width() > 5
    )


def _phys(widget) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """widget 中心の物理スクリーンピクセル (DPR スケール) を呼び出し時点で算出。"""
    c = widget.rect().center()
    g = widget.mapToGlobal(c)
    dpr = widget.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _real_click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    at(x, y, LUP)


def _shown_mw_with_long_recent(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    # どの画面幅でも修正前は必ず膨張するよう、画面幅の ~2 倍の描画幅を要求する
    # パス長を画面幅から導出する (1 文字 ~6px の保守見積)。
    screen_w = QApplication.primaryScreen().geometry().width()
    n_chars = max(400, (screen_w * 2) // 6)
    long_path = "C:/" + "d" * n_chars + "/measurement.mf4"
    mw.welcome_view._recent = _FakeRecent([long_path])  # type: ignore[assignment]
    mw.welcome_view.refresh()

    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    mw.showNormal()
    # availableGeometry 内配置 (オフスクリーン配置は誤着地の既知罠)。
    ag = QApplication.primaryScreen().availableGeometry()
    mw.setGeometry(
        ag.x() + 40,
        ag.y() + 40,
        min(1100, ag.width() - 80),
        min(640, ag.height() - 80),
    )
    mw.raise_()
    mw.activateWindow()
    qtbot.waitExposed(mw)
    QApplication.processEvents()
    return mw


def test_docks_stay_onscreen_with_long_recent_after_real_diagnostics_toggle(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-04 受け入れ: 超長 Recent 登録 + Diagnostics 実トグル (hide→show) の
    前後で File/Channel Browser ドックが画面内に留まる。"""
    skip_unless_real_display()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

    mw = _shown_mw_with_long_recent(qtbot)
    screen = QApplication.primaryScreen().geometry()

    # 修正の核: 超長 Recent 登録後もウィンドウ最小幅が画面幅未満に収まる。
    # 修正前はここで画面幅の ~2 倍に膨張して即 FAIL する (honest-RED の第一関門)。
    min_w = mw.minimumSizeHint().width()
    assert min_w < screen.width(), (
        f"FU-04 再発: 超長 Recent でウィンドウ最小幅 {min_w}px が"
        f"画面幅 {screen.width()}px を超えて膨張している"
    )

    # トグル前からブラウザドックは画面内 (修正前は膨張ウィンドウで既に画面外)。
    assert _onscreen(mw.file_dock), "file_dock がトグル前から画面外"
    assert _onscreen(mw.channel_dock), "channel_dock がトグル前から画面外"
    assert mw.diagnostics_dock.isVisible()  # トグル対象の初期状態

    toolbar = mw.findChild(QToolBar, "main_toolbar")
    btn = toolbar.widgetForAction(mw.diagnostics_dock.toggleViewAction())
    assert isinstance(btn, QToolButton)
    qtbot.waitUntil(lambda: btn.isVisible() and btn.width() > 0, timeout=3000)

    shot_hidden = tmp_path / "fu04_after_hide.png"
    shot_reshown = tmp_path / "fu04_after_reshow.png"
    cap: dict[str, object] = {}

    def click_hide() -> None:
        # クリック直前に現在位置から座標を再計算 (再レイアウト後の実位置)。
        _real_click(*_phys(btn))

    def after_hide() -> None:
        QApplication.primaryScreen().grabWindow(0).save(str(shot_hidden))
        # not isVisible() は「隠れた」方向の証拠としては健全 (罠は True 側のみ)。
        cap["diag_hidden"] = not mw.diagnostics_dock.isVisible()
        cap["file_on_after_hide"] = _onscreen(mw.file_dock)
        cap["chan_on_after_hide"] = _onscreen(mw.channel_dock)

    def click_reshow() -> None:
        _real_click(*_phys(btn))

    def check() -> None:
        QApplication.primaryScreen().grabWindow(0).save(str(shot_reshown))
        cap["file_on_after_reshow"] = _onscreen(mw.file_dock)
        cap["chan_on_after_reshow"] = _onscreen(mw.channel_dock)
        loop.quit()

    loop = QEventLoop()
    QTimer.singleShot(500, click_hide)
    QTimer.singleShot(1200, after_hide)
    QTimer.singleShot(1600, click_reshow)
    QTimer.singleShot(2400, check)
    QTimer.singleShot(6000, loop.quit)  # safety net
    loop.exec()

    print(f"[FU-04] diag hidden after real click = {cap.get('diag_hidden')}")
    print(
        f"[FU-04] onscreen after hide: file={cap.get('file_on_after_hide')} "
        f"channel={cap.get('chan_on_after_hide')}"
    )
    print(
        f"[FU-04] onscreen after reshow: file={cap.get('file_on_after_reshow')} "
        f"channel={cap.get('chan_on_after_reshow')}"
    )
    print(f"[FU-04] screenshots: {shot_hidden} , {shot_reshown}")

    assert cap.get("diag_hidden") is True, (
        f"実クリックで Diagnostics トグルが効いていない (操作不達)。"
        f"screenshot: {shot_hidden}"
    )
    assert cap.get("file_on_after_hide") is True, (
        f"FU-04 再発: Diagnostics 非表示化で file_dock が画面外へ。{shot_hidden}"
    )
    assert cap.get("chan_on_after_hide") is True, (
        f"FU-04 再発: Diagnostics 非表示化で channel_dock が画面外へ。{shot_hidden}"
    )
    assert cap.get("file_on_after_reshow") is True, (
        f"FU-04 再発: Diagnostics 再表示で file_dock が画面外へ。{shot_reshown}"
    )
    assert cap.get("chan_on_after_reshow") is True, (
        f"FU-04 再発: Diagnostics 再表示で channel_dock が画面外へ。{shot_reshown}"
    )
```

- [x] **Step 2: Layer C 契約ガードの適合を確認**

Run: `uv run pytest tests/gui/test_realgui_layer_c_contract.py -v`
Expected: PASS（新ファイルは `at`＋`grabWindow` を使う実入力テストとして受理される）

- [x] **Step 3: sabotage honest-RED — 修正を一時的に外して実 FAIL を実証**

`src/valisync/gui/views/welcome_view.py` の `refresh()` 内、`btn.setText(fm.elidedText(...))` の行を一時的に次へ置換（**コミット禁止**）:

```python
            btn.setText(path)  # SABOTAGE: FU-04 再現用の一時変更 (コミット禁止)
```

Run: `uv run pytest --realgui tests/realgui/test_dock_onscreen_after_toggle.py -v`
Expected: **FAIL** — `mw.minimumSizeHint().width() < screen.width()` の第一関門（または `_onscreen(file_dock)` トグル前チェック）で AssertionError。失敗メッセージとログを記録する（= 本テストが FU-04 を実際に検出できる証拠）。

- [x] **Step 4: sabotage を復元**

```bash
git restore src/valisync/gui/views/welcome_view.py
git diff --stat   # welcome_view.py が差分ゼロであることを確認
```

- [x] **Step 5: GREEN — realgui 実行＋スクショ目視**

Run: `uv run pytest --realgui tests/realgui/test_dock_onscreen_after_toggle.py -v`
Expected: PASS。続けて出力されたスクショ2枚（`fu04_after_hide.png` / `fu04_after_reshow.png`）を Read で開き、**File Browser / Channel Browser ドックが画面内に映っている**ことを目視確認し、判定コメントを記録する。

- [x] **Step 6: ①証拠ゲート記録**

`- [x] uv run pytest --realgui tests/realgui/test_dock_onscreen_after_toggle.py の pass ログ＋スクショ2枚＋目視判定コメントを PR 説明/実行ログに残す（merge 前ゲート: (a) full pytest 0 fail ＋ (b) 本証拠 ＋ (c) CI 緑）`

- [x] **Step 7: 品質ゲート（headless 全体の無回帰）**

Run: `uv run pytest` ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/`
Expected: 全て clean（realgui は既定 skip のまま）

- [x] **Step 8: コミット**

```bash
git add tests/realgui/test_dock_onscreen_after_toggle.py
git commit -m "test(realgui): FU-04 実トグルでブラウザドックが画面内に留まる Layer C (sabotage-RED 実証済み)"
```

---

### Task 3: ドキュメント反映（catalog の FU-04 完了化）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（FU-04 行＋フォローアップ節の冒頭サマリ）

**Interfaces:**
- Consumes: Task 1/2 の結果（修正コミット・realgui 証拠）
- Produces: FU-04 の完了記録（後続の修正フェーズは FU-01→FU-02 が残り）

- [ ] **Step 1: FU-04 行を ✅ 完了へ更新**

`docs/audit-findings-catalog.md` の FU-04 行（`| FU-04 | 🟠 |` で始まる行）の先頭2セルを `| FU-04 | ✅ |` に変え、説明セルの冒頭に次を追記（既存の根因記述は歴史として残す）:

```
**✅解消（2026-07-11・PR #XX）**: 真因は `welcome_view.py` の Recent ボタンが**フルパスをラベルにして最小幅がパス長に比例**（中央 `QStackedWidget` の全ページ最大経由でウィンドウ最小幅を支配・smoke 110字で813px→実データ2009px>画面1920）。修正=ラベルを `ElideMiddle` 省略（`_RECENT_LABEL_MAX_W=360`）＋フルパス tooltip・クリック emit は不変。クランプ/stack 抑制はしない（意図的な大画面表示を保全）。Layer A=有界性＋パス長不変性、Layer C=実トグルでドック画面内（sabotage-RED 実証・`visibleRegion`+画面内ジオメトリ判定）。
```

（`#XX` は PR 作成後に実番号へ置換。旧「修正方向: central/ドックの最小幅を抑制…」の3案列挙は、実測で真因がボタンと確定したため上記が上書きする旨が読み取れる位置に置く。）

- [ ] **Step 2: フォローアップ節の冒頭サマリを更新**

同ファイルのフォローアップ節冒頭（`FU-01/02/04/08 は再現・根因確定` を含む段落）の「**残る修正は未着手＝修正フェーズ待ち（推奨順は FU-04→FU-01→FU-02）**」を「**FU-04 は✅解消（2026-07-11・下記）。残る修正は FU-01→FU-02**」へ更新する。

- [ ] **Step 3: 品質ゲート＋コミット**

Run: `uv run pytest` ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/`

```bash
git add docs/audit-findings-catalog.md
git commit -m "docs: FU-04 を catalog で完了マーク（Recent ボタン ElideMiddle 有界化）"
```

---

## 完了後の手続き（プラン外・セッション本体で実施）

1. `superpowers:finishing-a-development-branch` — push・`gh pr create`（PR 本文に realgui 証拠を含める）・CI 確認・`gh pr merge --auto`。
2. catalog の `#XX` を実 PR 番号へ置換（PR 作成後の追いコミットで可）。
3. merge 前に `/gui-verify`（①ゲートの scoped 実行が未充足なら充足させる）。
4. CLAUDE.md / docs / memory への知見追記をユーザーに確認（例: 「QStackedWidget の最小幅は全ページ最大＝隠れページがウィンドウ最小幅を支配する」）。
