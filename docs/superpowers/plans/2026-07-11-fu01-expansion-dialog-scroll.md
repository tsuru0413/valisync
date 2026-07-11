# FU-01 ExpansionDialog スクロール化＋画面内クランプ 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LD-14 の展開確認モーダル `ExpansionDialog` が多数チャンネルで画面外へ伸び OK/Cancel と下方チェックボックスにアクセス不能になる問題（FU-01）を、チェックボックス列の `QScrollArea` 化＋画面内高さクランプで根本解決する。

**Architecture:** 変更は `expansion_dialog.py` の `__init__` に閉じる。チェックボックス列のみ内側 widget＋`QScrollArea(widgetResizable)` に載せ替え（ヘッダ・合計・全選択/全解除・OK/Cancel はスクロール外の常時可視）、`sizeAdjustPolicy=AdjustToContents` で少数時は従来同等のコンパクト表示を保ち、内容ヒントが `availableGeometry` を超えるときのみ明示 `resize` で画面内にクランプする。`_checks`／シグナル配線／`ask()` 契約（Cancel=空集合）／初期全未チェックは不変。

**Tech Stack:** PySide6 (QScrollArea / QAbstractScrollArea.SizeAdjustPolicy / QDialogButtonBox), pytest-qt, realgui（Win32 実 OS 入力 `tests/realgui/_realgui_input.py`・**実ホイール `wheel` プリミティブを本プランで確立**）

**Spec:** [docs/superpowers/specs/2026-07-11-fu01-expansion-dialog-scroll-design.md](../specs/2026-07-11-fu01-expansion-dialog-scroll-design.md)（承認済み A 案・非目標・受け入れ基準の一次情報源）

## Global Constraints

- **ブランチ/worktree**: `worktree-fu01-expansion-dialog-scroll`（`.claude/worktrees/fu01-expansion-dialog-scroll`）。main 直接編集禁止。
- **品質ゲート（各コミット前に全て・出力を `| tail` 等に通さない）**: `uv run pytest` ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/`。
- **実装スコープ**: `src/valisync/gui/views/expansion_dialog.py`・`tests/gui/test_expansion_dialog.py`・`tests/realgui/_realgui_input.py`（wheel 追加）・`tests/gui/test_realgui_layer_c_contract.py`（正規表現に wheel 追加）・新規 realgui 1ファイルのみ。`ExpansionConfirmer`／`mdf_loader`／チェック初期値方針は触らない（spec 非目標）。
- **`isVisible()` を「画面内にある」証拠に使わない**（画面外でも True）。画面内判定は `visibleRegion` 非空＋グローバル矩形が screen 内。
- **realgui は実 OS 入力のみ**: スクロールは実ホイール（`wheel()`）で行う。`verticalScrollBar().setValue()`・合成 `QWheelEvent`・`qtbot.mouseClick` は Layer C 偽装（契約ガードが CI で検査）。スクショ（`grabWindow(0)`）保存＋目視判定必須。「skipped」は「検証済み」ではない。
- **realgui のダイアログ表示は `show()`**（`exec()` のモーダルループはテストをブロックする）。`ask()`/exec 契約は Layer A の既存 reject テストが担保継続。
- **ruff confusables（RUF001-003）**: `…` リテラルは安全。`・` を ASCII 隣接で使わない。括弧は ASCII 優先。
- **`- [ ]` チェックボックスで進捗管理**。コミットメッセージ末尾に Co-Authored-By / Claude-Session フッタ。

---

### Task 1: QScrollArea 化＋画面内クランプと Layer A テスト（TDD）

**Files:**
- Modify: `src/valisync/gui/views/expansion_dialog.py`（`__init__` のチェック列生成＋モジュール定数）
- Test: `tests/gui/test_expansion_dialog.py`（クランプ・コンパクト性・buttonBox 内包＋既存4本無回帰）

**Interfaces:**
- Consumes: `ExpansionRequest(channels: tuple[OversizedChannel, ...])`／`OversizedChannel(name: str, column_count: int)`（frozen dataclass・`mdf_loader`・変更しない）
- Produces: `ExpansionDialog._scroll: QScrollArea`（Task 2 の realgui が viewport 座標取得に使う）／モジュール定数 `_SCREEN_MARGIN: int = 80`。不変条件: `_checks: list[QCheckBox]`・`result_indices`・`ask()` 契約・初期全未チェックは従来どおり。

- [x] **Step 1: 失敗するテストを書く**

`tests/gui/test_expansion_dialog.py` の import に `QScrollArea` を追加し、ファイル末尾に追加:

```python
def _many(n: int) -> ExpansionRequest:
    return ExpansionRequest(
        channels=tuple(
            OversizedChannel(name=f"Ch{i:03d}", column_count=2000) for i in range(n)
        )
    )


def test_dialog_height_clamped_to_screen_for_many_channels(qtbot: QtBot) -> None:
    """FU-01: 60 チャンネルでもダイアログ高が画面 (availableGeometry) 内に収まる。

    修正前はチェック行が layout へ直接積まれ全高 ~1900px 超で RED
    (offscreen も WM クランプが無いため sizeHint どおりに伸びる)。
    """
    dlg = ExpansionDialog(_many(60))
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    ag = dlg.screen().availableGeometry()
    assert dlg.height() <= ag.height()


def test_buttonbox_stays_within_dialog_for_many_channels(qtbot: QtBot) -> None:
    """クランプ後も OK/Cancel はダイアログ矩形内 (スクロール外の常時可視)。

    修正前も (ダイアログ自体が巨大なので) 通る — クランプが「内容あふれ」で
    なく「スクロール」で実現されていることの post-fix ガード。
    """
    from PySide6.QtWidgets import QDialogButtonBox

    dlg = ExpansionDialog(_many(60))
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    box = dlg.findChild(QDialogButtonBox)
    assert box is not None
    tl = box.mapTo(dlg, box.rect().topLeft())
    br = box.mapTo(dlg, box.rect().bottomRight())
    assert dlg.rect().contains(tl) and dlg.rect().contains(br)


def test_dialog_compact_for_few_channels(qtbot: QtBot) -> None:
    """少数チャンネルでは従来同等のコンパクト表示 (不要なスクロールを出さない)。

    修正前は QScrollArea 自体が無く findChild が None で RED (構造 RED)。
    """
    dlg = ExpansionDialog(_req())  # 既存ヘルパ: 2 チャンネル
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    scroll = dlg.findChild(QScrollArea)
    assert scroll is not None  # チェック列はスクロール領域内 (FU-01 構造)
    inner = scroll.widget()
    assert inner is not None
    assert inner.height() <= scroll.viewport().height() + 1  # スクロール不要
    ag = dlg.screen().availableGeometry()
    assert dlg.height() < ag.height() // 2  # コンパクト (画面の半分未満)
```

import 追加（既存 import 行に併合）:

```python
from PySide6.QtWidgets import QDialog, QScrollArea
```

- [x] **Step 2: RED を確認**

Run: `uv run pytest tests/gui/test_expansion_dialog.py -v`
Expected: 新規3テスト中2つが FAIL —
- `test_dialog_height_clamped_to_screen_for_many_channels`: 高さ ~1900px 超 > availableGeometry 高で AssertionError
- `test_dialog_compact_for_few_channels`: `findChild(QScrollArea)` が None で AssertionError
- `test_buttonbox_stays_within_dialog_for_many_channels` と既存4本は PASS（buttonBox テストは post-fix ガードであり最初から緑で正しい）

- [x] **Step 3: 最小実装（QScrollArea＋クランプ）**

`src/valisync/gui/views/expansion_dialog.py` — import へ `QAbstractScrollArea`・`QScrollArea` を追加し、モジュール定数を import 群の直後に追加:

```python
# FU-01: 画面内クランプ時にタイトルバー/タスクバーぶん残す余白 (px)。
# WM はモーダルの過大な高さをクランプしない (実測: 全高1940px > 画面816px で
# OK/Cancel が画面外) ため、ダイアログ側で availableGeometry 基準に収める。
_SCREEN_MARGIN = 80
```

`__init__` のチェックボックス生成ループ（現行 `self._checks: list[QCheckBox] = []` から `self._checks.append(cb)` のブロック）を次に置換:

```python
        self._checks: list[QCheckBox] = []
        checks_host = QWidget()
        checks_lay = QVBoxLayout(checks_host)
        checks_lay.setContentsMargins(0, 0, 0, 0)
        for ch in request.channels:
            cb = QCheckBox(f"{ch.name} — {ch.column_count} 列")
            cb.toggled.connect(self._update_total)
            checks_lay.addWidget(cb)
            self._checks.append(cb)
        checks_lay.addStretch(1)  # viewport が余るときチェック行を上詰めに保つ
        # FU-01: チェック列だけをスクロール領域へ。ヘッダ/合計/一括ボタン/OK は
        # スクロール外の常時可視。AdjustToContents で sizeHint が内容に追従し、
        # 少数チャンネルでは従来同等のコンパクト表示になる。
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        )
        self._scroll.setWidget(checks_host)
        layout.addWidget(self._scroll, 1)
```

`__init__` 末尾（`self._update_total()` の直後）に追加:

```python
        # FU-01: 内容が画面に収まらない場合のみ高さを画面内へクランプする。
        # 収まる場合は resize しない = sizeHint どおりのコンパクト表示を保つ。
        cap = self.screen().availableGeometry().height() - _SCREEN_MARGIN
        hint = self.sizeHint()
        if hint.height() > cap:
            # クランプで縦スクロールバーが出るぶん幅を足し横スクロールを防ぐ。
            vsb_w = self._scroll.verticalScrollBar().sizeHint().width()
            self.resize(hint.width() + vsb_w, cap)
```

- [x] **Step 4: GREEN を確認**

Run: `uv run pytest tests/gui/test_expansion_dialog.py tests/gui/test_expansion_confirmer.py -v`
Expected: 全 PASS（既存4本＝`_checks` 直接操作・`ask()` reject 契約を含む）

- [x] **Step 5: 品質ゲート**

Run: `uv run pytest` → 0 failures ／ `uv run ruff check` ／ `uv run ruff format --check`（差分が出たら `uv run ruff format` 後に再確認）／ `uv run mypy src/` → 全て clean

- [x] **Step 6: コミット**

```bash
git add src/valisync/gui/views/expansion_dialog.py tests/gui/test_expansion_dialog.py
git commit -m "fix(gui): FU-01 ExpansionDialog のチェック列をスクロール化し画面内へクランプ"
```

---

### Task 2: realgui — 実ホイールで最下段到達 E2E（wheel プリミティブ確立＋sabotage-RED）

**Files:**
- Modify: `tests/realgui/_realgui_input.py`（`WHEEL` フラグ＋`wheel()` プリミティブ）
- Modify: `tests/gui/test_realgui_layer_c_contract.py`（実入力プリミティブ正規表現に `wheel` を追加）
- Create: `tests/realgui/test_expansion_dialog_realinput.py`
- （sabotage で一時変更→復元: `src/valisync/gui/views/expansion_dialog.py` — コミットしない）

**Interfaces:**
- Consumes: Task 1 の `ExpansionDialog._scroll`・`_checks`・`result_indices`／`_realgui_input.py` の `at`/`LDOWN`/`LUP`/`skip_unless_real_display`
- Produces: 共有プリミティブ `wheel(x: float, y: float, delta: int) -> None`（物理座標へカーソルを置き `MOUSEEVENTF_WHEEL` を発行。delta は WHEEL_DELTA=120 の倍数・負=下スクロール）／realgui 証拠（pass ログ＋スクショ・①ゲート充足物）

- [x] **Step 1: wheel プリミティブを共有ヘルパへ追加**

`tests/realgui/_realgui_input.py` — フラグ定義行の下に追加:

```python
WHEEL = 0x0800  # MOUSEEVENTF_WHEEL — dwData に ±WHEEL_DELTA(120) の倍数 (正=上)
```

`key()` の下に追加:

```python
def wheel(x: float, y: float, delta: int) -> None:
    """カーソルを物理 (x, y) へ置き、実 OS ホイールを delta だけ回す。

    delta は WHEEL_DELTA(120) の倍数 (負=下スクロール)。ホイールはカーソル下の
    ウィジェットへ配送されるため、対象 viewport 上に置いてから発行する。QDrag と
    違い OLE モーダルループは無く、processEvents の pump だけで配送される
    (FU-01 で確立・repo 初の実ホイール)。
    """
    _user32.SetCursorPos(int(x), int(y))
    _user32.mouse_event(WHEEL, 0, 0, delta, 0)
```

- [x] **Step 2: 契約ガードの正規表現に wheel を追加**

`tests/gui/test_realgui_layer_c_contract.py` の

```python
_REAL_INPUT = re.compile(r"\b(?:at|key|drive_qdrag)\(|\.grabWindow\(")
```

を

```python
_REAL_INPUT = re.compile(r"\b(?:at|key|wheel|drive_qdrag)\(|\.grabWindow\(")
```

へ変更（コメント行 `# 実 OS 入力プリミティブ(at/key/drive_qdrag)or ...` も `at/key/wheel/drive_qdrag` へ追随）。
Run: `uv run pytest tests/gui/test_realgui_layer_c_contract.py -v` → PASS

- [x] **Step 3: realgui テストを書く**

`tests/realgui/test_expansion_dialog_realinput.py` を新規作成:

```python
"""Layer C: FU-01 — 多数チャンネルの ExpansionDialog が画面内に収まり、
実マウスホイールで最下段チェックボックスへ到達して操作できる (到達性 E2E)。

`--realgui` opt-in・実ディスプレイ+Windows 必須。offscreen には実 WM 配置が
無いため「ダイアログが画面外へ伸び OK/Cancel に届かない」現象の反証は実機
でしか成立しない。スクロールは実 OS ホイール (`_realgui_input.wheel`・repo 初出)
で駆動する — `verticalScrollBar().setValue()` や合成 QWheelEvent は Layer B
であり到達性の証明にならない。

isVisible() は画面外でも True を返すため「画面内」の証拠には使わない
(visibleRegion + グローバル矩形 in screen — FU-04 と同じ判定)。

honest-RED: クランプを一時的に外す sabotage で本テストが実際に FAIL する
(ダイアログ高が画面超) ことを実証済み (Task 2 Step 5)。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    at,
    skip_unless_real_display,
    wheel,
)

pytestmark = pytest.mark.realgui


def _many(n: int):  # type: ignore[no-untyped-def]
    from valisync.core.loaders.mdf_loader import ExpansionRequest, OversizedChannel

    return ExpansionRequest(
        channels=tuple(
            OversizedChannel(name=f"Ch{i:03d}", column_count=2000) for i in range(n)
        )
    )


def _onscreen(w) -> bool:  # type: ignore[no-untyped-def]
    """visibleRegion 非空 + グローバル矩形が画面内 (isVisible は不使用)。"""
    from PySide6.QtWidgets import QApplication

    scr = QApplication.primaryScreen().geometry()
    tl = w.mapToGlobal(w.rect().topLeft())
    br = w.mapToGlobal(w.rect().bottomRight())
    return (
        scr.contains(tl)
        and scr.contains(br)
        and not w.visibleRegion().isEmpty()
        and w.width() > 5
    )


def _phys(widget) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """widget 中心の物理ピクセル (DPR スケール) を呼び出し時点で算出。"""
    c = widget.rect().center()
    g = widget.mapToGlobal(c)
    dpr = widget.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _real_click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    at(x, y, LUP)


def test_bottom_checkbox_reachable_by_real_wheel_then_ok(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-01 受け入れ: 画面高を超える本数でもダイアログは画面内に収まり、
    実ホイール→最下段チェック実クリック→OK 実クリックが通る。"""
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from valisync.gui.views.expansion_dialog import ExpansionDialog

    screen = QApplication.primaryScreen().geometry()
    # どの画面高でも「スクロールしないと最下段に届かない」本数を画面から導出
    # (1 行 ~18px の保守見積で画面高の ~2 倍)。
    n = max(60, (screen.height() * 2) // 18)
    dlg = ExpansionDialog(_many(n))
    qtbot.addWidget(dlg)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dlg.show()  # exec() はモーダルループでテストをブロックするため show()
    dlg.raise_()
    dlg.activateWindow()
    qtbot.waitExposed(dlg)
    QApplication.processEvents()

    # 修正の核: ダイアログ高が画面内 (sabotage 時はここで FAIL = honest-RED)。
    assert dlg.height() <= screen.height(), (
        f"FU-01 再発: ダイアログ高 {dlg.height()}px > 画面 {screen.height()}px"
    )
    box = dlg.findChild(QDialogButtonBox)
    assert box is not None
    ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_btn is not None
    assert _onscreen(ok_btn), "OK ボタンが画面外 (FU-01 再発)"
    assert _onscreen(dlg._checks[0]), "先頭チェックボックスが画面外"
    assert dlg._checks[-1].visibleRegion().isEmpty(), (
        "前提不成立: 最下段が最初から可視 = チャンネル数が画面に対して少なすぎる"
    )

    # 実ホイールで最下段が可視になるまで下スクロール (カーソルは viewport 上)。
    vp_x, vp_y = _phys(dlg._scroll.viewport())
    last_cb = dlg._checks[-1]
    deadline = time.monotonic() + 10.0
    while last_cb.visibleRegion().isEmpty() and time.monotonic() < deadline:
        wheel(vp_x, vp_y, -120 * 5)
        for _ in range(4):
            QApplication.processEvents()
            time.sleep(0.02)
    shot_scrolled = tmp_path / "fu01_scrolled_bottom.png"
    QApplication.primaryScreen().grabWindow(0).save(str(shot_scrolled))
    assert not last_cb.visibleRegion().isEmpty(), (
        f"実ホイールで最下段へ到達できない。screenshot: {shot_scrolled}"
    )

    # 最下段を実クリック → チェックが入る (「アクセス不能」の直接反証)。
    _real_click(*_phys(last_cb))
    qtbot.waitUntil(last_cb.isChecked, timeout=3000)

    # OK を実クリック → accept され最下段インデックスが結果に含まれる。
    with qtbot.waitSignal(dlg.accepted, timeout=3000):
        _real_click(*_phys(ok_btn))

    print(f"[FU-01] n={n} result_indices contains last: {n - 1 in dlg.result_indices}")
    print(f"[FU-01] screenshot: {shot_scrolled}")
    assert n - 1 in dlg.result_indices, (
        f"OK 実クリック後の result_indices に最下段 {n - 1} が無い: "
        f"{sorted(dlg.result_indices)}。screenshot: {shot_scrolled}"
    )
```

- [x] **Step 4: 契約ガード適合を確認**

Run: `uv run pytest tests/gui/test_realgui_layer_c_contract.py -v`
Expected: PASS（新ファイルは `at`/`wheel`＋`grabWindow` を使う実入力テストとして受理）

- [x] **Step 5: sabotage honest-RED — クランプを一時的に外して実 FAIL を実証**

`src/valisync/gui/views/expansion_dialog.py` のクランプ分岐を一時的に置換（**コミット禁止**）:

```python
        if False:  # SABOTAGE: FU-01 再現用の一時変更 (コミット禁止)  # noqa: SIM108
```

（元の `if hint.height() > cap:` をこの行に置換）

Run: `uv run pytest --realgui tests/realgui/test_expansion_dialog_realinput.py -v`
Expected: **FAIL** — `dlg.height() <= screen.height()` の第一関門で AssertionError（ダイアログ高 ~数千 px > 画面高）。失敗 assert とメッセージを記録する。

**実装ノート（実態）**: この sabotage（`if False:` 化）では RED にならなかった（Qt の `QScrollArea.sizeHint()` bound により通常画面でクランプ分岐は非発火）。実際の honest-RED は**スクロール化解除**（チェック列を QScrollArea から外す pre-Task-1 相当）で `ダイアログ高 3020px > 画面 864px` の FAIL を実証 — spec 実装ノート・テスト docstring 参照。

- [x] **Step 6: sabotage を復元**

```bash
git restore src/valisync/gui/views/expansion_dialog.py
git diff --stat   # 差分ゼロ確認
```

- [x] **Step 7: GREEN — realgui 実行＋スクショ目視**

Run: `uv run pytest --realgui tests/realgui/test_expansion_dialog_realinput.py -v`
Expected: PASS。出力されたスクショ `fu01_scrolled_bottom.png` を Read で開き、**ダイアログが画面内・縦スクロールバー可視・最下段付近のチェック行と OK/Cancel が同時に見えている**ことを目視確認し、判定コメントを記録する。

- [x] **Step 8: ①証拠ゲート記録**

`- [x] uv run pytest --realgui tests/realgui/test_expansion_dialog_realinput.py の pass ログ＋スクショ＋目視判定コメントを PR 説明/実行ログに残す（merge 前ゲート: (a) full pytest 0 fail ＋ (b) 本証拠 ＋ (c) CI 緑）`

- [x] **Step 9: 品質ゲート**

Run: `uv run pytest` ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/` → 全 clean（realgui は既定 skip のまま）

- [x] **Step 10: コミット**

```bash
git add tests/realgui/_realgui_input.py tests/gui/test_realgui_layer_c_contract.py tests/realgui/test_expansion_dialog_realinput.py
git commit -m "test(realgui): FU-01 実ホイールで最下段到達 E2E (wheel プリミティブ確立・sabotage-RED 実証済み)"
```

---

### Task 3: ドキュメント反映（catalog の FU-01 完了化）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（FU-01 行＋フォローアップ節の冒頭サマリ）

**Interfaces:**
- Consumes: Task 1/2 の結果（修正コミット・realgui 証拠）
- Produces: FU-01 の完了記録（修正フェーズの残りは FU-02）

- [x] **Step 1: FU-01 行を ✅ 完了へ更新**

`docs/audit-findings-catalog.md` の FU-01 行（`| FU-01 | 🟠 |` で始まる行）の先頭2セルを `| FU-01 | ✅ |` に変え、**説明セル（第3セル）の冒頭に**次を追記する。既存の説明文は一字一句そのまま残し（歴史）、場所セル（第4セル）・影響セル（第5セル）は**変更しない**。テーブル行構造（`|` セル数・1行）を壊さない:

```
**✅解消（2026-07-11・PR #XX）**: チェックボックス列を `QScrollArea`（widgetResizable・AdjustToContents）でラップ（ヘッダ/合計/一括ボタン/OK-Cancel はスクロール外の常時可視）。Qt の `QScrollArea.sizeHint()` は約 36×24 × フォント高で bound されるため通常画面は**スクロール化だけで**画面内に収まり、bound が画面高を超える環境（大フォント/低解像度）向けの `availableGeometry − _SCREEN_MARGIN(80px)` 高さクランプを防御層として保持（純関数 `_clamped_size` で直接テスト・spec 実装ノート参照）。少数時は従来コンパクト・`ask()` 契約/初期全未チェック不変。Layer A=有界性/コンパクト性/buttonBox 内包/純関数、Layer C=実ホイール（repo 初のプリミティブ `wheel` を `_realgui_input` に確立・契約ガード正規表現へ追加）で最下段到達→実クリック→OK 実クリックの E2E（sabotage-RED=スクロール化解除で実証・`visibleRegion`+画面内ジオメトリ判定）。
```

（`#XX` は PR 作成後の追いコミットで実番号へ置換。）

- [x] **Step 2: フォローアップ節の冒頭サマリを更新**

同ファイルのフォローアップ節冒頭段落（`FU-04 は✅解消（2026-07-11・下記）。残る修正は FU-01→FU-02` を含む箇所）の部分文字列 `FU-04 は✅解消（2026-07-11・下記）。残る修正は FU-01→FU-02` を `FU-04/FU-01 は✅解消（2026-07-11・下記）。残る修正は FU-02` へ置換する（これ以外は触らない）。

- [x] **Step 3: 品質ゲート＋コミット**

Run: `uv run pytest` ／ `uv run ruff check` ／ `uv run ruff format --check` ／ `uv run mypy src/`

```bash
git add docs/audit-findings-catalog.md
git commit -m "docs: FU-01 を catalog で完了マーク（ExpansionDialog スクロール化）"
```

---

## 完了後の手続き（プラン外・セッション本体で実施）

1. `superpowers:finishing-a-development-branch` — push・`gh pr create`（PR 本文に realgui 証拠を含める）・`gh pr checks <num> --watch` で CI 緑確認・`gh pr merge <num> --squash --delete-branch`（auto-merge はリポジトリ設定で無効 — `docs/workflow.md` 参照）。
2. catalog の `#XX` を実 PR 番号へ置換（PR 作成後の追いコミット）。
3. merge 前に `/gui-verify`（①ゲートの scoped 実行が未充足なら充足させる）。
4. merge 後の後片付け時に**親チェックアウトの `git status` も確認**（subagent が親へ編集を漏らした実例あり — memory `worktree_subagent_parent_checkout_leak`）。
5. CLAUDE.md / docs / memory への知見追記をユーザーに確認（候補: realgui 実ホイールプリミティブの確立）。
