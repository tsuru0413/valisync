# デザイントークン増分1「凍結トークン化」実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 散在するハードコード色/寸法を `gui/theme/` トークン（単一の真実）へ**現状値のまま**移し、スクショ前後比較で「見た目不変」を実証、AST ガードで再混入を恒久防止する。

**Architecture:** pure-Python トークン（`tokens.py`）＋QSS フォーマッタ（`qss.py`）＋Qt 適用フック（`apply.py`）。凍結検証は「撮影スクリプト最小版でベースライン → 置換 → 再撮影 → ピクセル比較 diff=0」＋「全トークン相異値のデバッグテーマ撮影で役割写像を目視検証」の二層。spec: [2026-07-15-design-token-pipeline-design.md](../specs/2026-07-15-design-token-pipeline-design.md)

**Tech Stack:** Python 3.12 / PySide6 / pyqtgraph / pytest(+pytest-qt) / numpy（比較スクリプト）

## Global Constraints

- **見た目不変（凍結）**: 全置換は現状値と同一の色・寸法を tokens 経由で供給する。値の変更は一切禁止（変更は増分3以降）。
- **トークンは呼び出し時に `tokens.active()` で読む**。module 定数・default 引数・import 時評価への束縛は禁止（デバッグテーマ注入・将来のテーマ切替が効かなくなる）。唯一の例外は qss 関数の `t=None` センチネル（内部で active() を読む）。
- **`theme/tokens.py`・`theme/qss.py` は PySide6/pyqtgraph を import 禁止**（pure-Python VM の純粋性維持・spec §4.1）。Qt 依存は `theme/apply.py` のみ。
- **import 規約**: `from valisync.gui.theme import qss, tokens` のモジュール import（`tokens.active()` と書く）。`from ... import active` は既存の `active: bool` ローカル変数と衝突するため禁止。
- **品質ゲート（コミット毎）**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` を全て通す。`ruff format --check` は CI と同一（format 実行だけでは不足）。ゲート出力を `| tail` 等に通さない（exit code 隠蔽）。
- **凍結比較の環境固定（Task 1 のベースライン撮影以降）**: uv.lock 変更禁止・同一マシン/同一 DPI/OS テーマ・ClearType 不変・撮影スクリプトの状態定義変更禁止（変更が必要になったらベースライン再取得からやり直す）。
- **撮影・比較スクリプトは実ディスプレイで手動実行**（`QT_QPA_PLATFORM=windows` を script 内で強制。offscreen は全文字が□）。pytest は通常どおり offscreen。
- **ブランチ**: `feature/design-token-pipeline`（作成済み・spec コミット済み）。worktree で作業する場合は先に `uv sync --extra dev`。

## GUI テスト分析（/gui-test-plan 出力の織り込み）

- **変更種別**: ほぼ全タスクが「リファクタ・可視挙動不変」＋ツール新設。触れるユーザージャーニー: 全区間（色はどの画面にもある）だが挙動変更なし。
- **E2E 受け入れ（ブランチ横断・Task 11 で完結)**:
  - 見た目不変: E2E タイプ=**描画 E2E** / 実 observable=**比較スクリプトの diff=0（自動アサート）** ＋ ベースライン/事後スクショの目視。**prod スケール不要**（色値はデータ規模非依存。比較の本質は「同一データ・同一状態の前後一致」であり、決定的な内蔵 fixture データが正しい選択。実スケール系の回帰は既存 realgui 無回帰で担保）。
  - 役割写像の正しさ（ピクセル比較の盲点・spec §7-6）: **デバッグテーマ撮影のスクショ目視**（視覚判定）＋ mapping 表（本プランの置換対応そのもの）レビュー。
- **必要レイヤー**: A=必須（トークン検証・純粋性・qss/apply・wiring assert・ガードスキャン）/ B=要（apply の pg 設定 sabotage 検証・stylesheet 系 wiring）/ 入力経路 E2E(C)=**既存 realgui の無回帰のみ**（入力経路の新規/変更なし）/ perf E2E=不要（描画パス・データ走査の変更なし）/ 描画 E2E=**要**（凍結比較＋デバッグテーマ）。
- **②実質性**: 「diff=0」は exit code の自動アサート。「デバッグテーマで各トークンが意図した場所に着地」は視覚判定（スクショを PR 添付）。スクショ保存だけ・VM 再チェックだけの naive 検証は不可。
- **①証拠ゲート（Task 12）**: 凍結比較ログ＋デバッグテーマスクショ＋realgui 無回帰の証拠を PR に添付。merge 前に `/gui-verify`。
- **realgui 掴み点監査**: 不要（ゾーン幾何=frame 幅/grip 寸法/軸幅は一切変更しない）。
- **honest layering note**:
  - QPainter 直描画の 3 色（grip の amber 枠 `accent_active`・白 fill `grip_fill`・濃 amber `accent_active_dark`）は静止撮影に写らない（hover/active 依存）。`accent_active` は同一トークンを使う active_panel_frame の QSS で視覚検証できるが、`grip_fill`/`accent_active_dark` は**デバッグテーマでも視覚未検証**＝mapping 表と Layer A の wiring assert では担保できず、コードレビューで担保する（本プランの Task 6 レビュー観点に明記）。
  - ダイアログのエラーラベル/プレビュー線/スピナー色は最小版撮影の対象外 → `qss.error_label()` 等の Layer A 配線テスト（Task 3）＋一行置換の diff レビューで担保。グレーアウトのみ widget レベル assert（Task 8）。
  - `qss.*()` の出力をトークン参照で assert するのは値の正しさに対しては同義反復だが、**どのトークンを消費するか（配線）**の検証としては有効 — 同値別トークン誤配線ガード。値そのものの凍結は `test_dark_values_frozen_snapshot`（意図的 test-lock・再デザイン反復で更新する）1 箇所に集中させる。

## 置換マッピング表（凍結対応の単一ビュー・レビュー成果物）

| 現箇所 | 現値 | トークン |
|---|---|---|
| graph_panel_vm.py:32-43 `_PALETTE` | tab10 10色 | `colors.signal_palette` |
| cursor_readout.py:77 | `rgba(17,17,27,230)` | `colors.surface_chip` |
| cursor_readout.py:78 | `#45475a` / radius 5px | `colors.border_chip` / `radii.chip` |
| cursor_readout.py:79,99 | `#cdd6f4` | `colors.text_primary` |
| cursor_readout.py:100 | `#f38ba8` | `colors.close_hover` |
| cursor_readout.py:190,229 / graph_panel_view.py:843,1444 | `#f9e2af` | `colors.cursor_a` |
| cursor_readout.py:230 / graph_panel_view.py:846,1448 | `#89b4fa` | `colors.cursor_b` |
| cursor_readout.py:420,437 | `#7f849c` / 9px | `colors.text_secondary` / `typography.small_px` |
| cursor_readout.py:82-83,88,111-112 | margins(6,5,6,5)/3/6/8/2 | `spacing.chip_*` |
| graph_panel_view.py:427,821 | `#f59e0b` / radius 2px | `colors.accent_active` / `radii.active_frame` |
| graph_panel_view.py:434 / :435 | `#ffffff` / `#b45309` | `colors.grip_fill` / `colors.accent_active_dark` |
| graph_panel_view.py:2034 / graph_area_view.py:381 | `#1f77b4`（枠） | `colors.drop_highlight`（palette[0] と同値・役割別） |
| graph_panel_view.py:1586 / :1595 | `QColor(255,165,0)` / `(255,165,0,60)` | `colors.axis_move_indicator` / `colors.axis_move_fill` |
| graph_panel_view.py:108,889 `_GRID_ALPHA` | 60 | `grid_alpha` |
| export_csv_dialog.py:148 / csv_format_dialog.py:84 / graph_area_view.py:349 | `#c0392b` | `colors.error` |
| signal_preview_window.py:22 | `#4FC3F7` | `colors.preview_curve` |
| file_row_spinner.py:41 | `QColor(120,160,255)` | `colors.busy_spinner` |
| qt_signal_models.py:99 | `QColor(128,128,128)` | `colors.text_releasing` |
| （暗黙既定の明示固定） | pg `'k'` / `'d'` | `colors.plot_background` / `colors.plot_foreground` |
| **非トークン（構造色・allowlist）** | cursor_shapes.py:67 transparent, :98-99 白ハロー/黒線 | — （spec §4.1 の線引き） |
| **非トークン（レイアウト機構）** | `_Y_AXIS_FIXED_WIDTH=72`, GRIP_W/H, swatch QPixmap(10,10) 等 | — （spec §9） |

---

### Task 1: 撮影・比較スクリプト＋ベースライン撮影（src 無変更）

**Files:**
- Create: `scripts/capture_ui_screenshots.py`
- Create: `scripts/compare_screenshots.py`
- Modify: `.gitignore`（`design_export/` を追加）

**Interfaces:**
- Produces: `capture_ui_screenshots.py --out DIR [--debug-theme]`（--debug-theme は Task 11 で追加）が `01_welcome.png` `02_plotted.png` `03_cursor.png` `04_grid.png` `05_affordances.png` を DIR に出力。`compare_screenshots.py BASELINE AFTER [--diff-out DIR]` が全一致で exit 0 / 相違で exit 1。
- Consumes: 既存 `build_main_window` 相当の組立て（`MainWindow(AppViewModel())`・`session.load`・`_on_loaded`・`graph_area_vm.panels(0)`・`add_signal`・`set_cursor`/`set_cursor_b`/`toggle_grid` — すべて現行 API、tests/realgui/test_journey_smoke.py と同型）。

- [ ] **Step 1: `.gitignore` に追記**

```
design_export/
```

- [ ] **Step 2: 撮影スクリプトを作成**

`scripts/capture_ui_screenshots.py`:

```python
"""凍結検証用スクショ撮影 — 最小版 (design-token pipeline 増分1, spec §7).

実ディスプレイ必須 (offscreen は文字が全て□ — docs/development.md)。
QSettings を一時 dir へ隔離し、決定的な内蔵 CSV データで同一状態を再現、
QWidget.grab() で撮る (grabWindow(0) はタスクバー/背後ウィンドウが写るため不使用)。

使い方:
    uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_baseline
比較:
    uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_after
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import tempfile
import time
from pathlib import Path

_N_SAMPLES = 240  # 12s @ 20Hz — 波形の形が視認できる決定的データ


def _write_fixture_csv(path: Path) -> None:
    """決定的な内蔵データ (毎回同一バイト → 凍結比較の前提を満たす)。"""
    rows = ["t,EngineSpeed,VehSpd"]
    for i in range(_N_SAMPLES):
        t = i * 0.05
        rows.append(f"{t:.3f},{800 + (i % 60) * 25:.1f},{(i % 100) * 1.2:.2f}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        print("offscreen では撮影不可 (文字が□になる)。", file=sys.stderr)
        return 2
    os.environ["QT_QPA_PLATFORM"] = "windows"
    # 物理マウスを画面隅へ退避 — hover 効果を撮影状態から排除 (spec §7-2)
    ctypes.windll.user32.SetCursorPos(5, 5)

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    # QSettings 隔離 — ユーザーの実ドック配置/ジオメトリ復元を遮断 (spec §6)
    tmp = Path(tempfile.mkdtemp(prefix="valisync_capture_"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp / "settings")
    )

    app = QApplication(sys.argv)

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.app import build_main_window

    window = build_main_window()
    screen = app.primaryScreen().availableGeometry()
    window.setGeometry(screen.x() + 60, screen.y() + 60, 1120, 760)
    window.show()
    window.raise_()
    window.activateWindow()

    def settle(secs: float = 0.4) -> None:
        deadline = time.monotonic() + secs
        while time.monotonic() < deadline:
            app.processEvents()

    args.out.mkdir(parents=True, exist_ok=True)

    def grab(name: str) -> None:
        settle()
        window.grab().save(str(args.out / f"{name}.png"))
        print(f"captured {name}.png")

    settle(1.0)
    grab("01_welcome")

    # --- データ読込 (同期 load — busy overlay/スピナーが写らない) --------------
    csv = tmp / "fixture.csv"
    _write_fixture_csv(csv)
    fmt = FormatDefinition(
        name="capture_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    outcome = window.app_vm.session.load(csv, fmt)
    window._on_loaded(outcome)
    settle()

    model = window.channel_browser_view.model
    keys = [model.signal_key_at(model.index(r, 0)) for r in range(model.rowCount())]
    panel_vm = window.graph_area_vm.panels(0)[0]
    for key in keys:
        assert key is not None
        panel_vm.add_signal(key)
    grab("02_plotted")

    # --- カーソル A+B → readout チップ (delta モード) --------------------------
    panel_vm.set_cursor(3.0)
    panel_vm.set_cursor_b(6.0)
    grab("03_cursor")

    # --- グリッド ---------------------------------------------------------------
    panel_vm.toggle_grid(True)
    grab("04_grid")
    panel_vm.toggle_grid(False)

    # --- QSS 系アフォーダンス強制表示 (アクティブ枠/ドロップ強調) ----------------
    # 撮影ツールとしての private 利用: 色は QSS 由来なので可視化さえすれば
    # ピクセルは production 経路の描画そのもの。
    panel_view = next(w for _t, _p, w in window.graph_area_view._panel_views)
    panel_view._active_frame.setVisible(True)
    panel_view._set_drop_highlight(True)
    window.graph_area_view._set_drop_highlight(True)
    grab("05_affordances")

    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 比較スクリプトを作成**

`scripts/compare_screenshots.py`:

```python
"""スクショ前後比較 — 凍結検証 (spec §7)。差分ピクセル数と diff 画像を出力。

exit 0 = 全ファイル完全一致 / 1 = 相違あり / 2 = ファイル集合・サイズ不一致。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def _load_rgba(path: Path) -> np.ndarray:
    from PySide6.QtGui import QImage

    img = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    return np.frombuffer(buf, dtype=np.uint8).reshape(img.height(), img.width(), 4).copy()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline", type=Path)
    p.add_argument("after", type=Path)
    p.add_argument("--diff-out", type=Path, default=None)
    args = p.parse_args()

    names = sorted(f.name for f in args.baseline.glob("*.png"))
    if names != sorted(f.name for f in args.after.glob("*.png")) or not names:
        print("比較対象のファイル集合が不一致または 0 件", file=sys.stderr)
        return 2

    failed = False
    size_mismatch = False
    for name in names:
        a = _load_rgba(args.baseline / name)
        b = _load_rgba(args.after / name)
        if a.shape != b.shape:
            print(f"NG {name}: サイズ不一致 {a.shape} vs {b.shape}")
            size_mismatch = True
            continue
        diff = (a != b).any(axis=2)
        n = int(diff.sum())
        if n == 0:
            print(f"OK {name}: 完全一致")
            continue
        failed = True
        print(f"NG {name}: {n} px 相違")
        if args.diff_out:
            from PySide6.QtGui import QImage

            args.diff_out.mkdir(parents=True, exist_ok=True)
            h, w = diff.shape
            out = np.zeros((h, w, 4), dtype=np.uint8)
            out[..., 3] = 255
            out[diff] = (255, 0, 0, 255)
            QImage(out.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888).save(
                str(args.diff_out / name)
            )
    return 2 if size_mismatch else (1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 撮影の再現性を確認（同一コードで2回撮影→比較で完全一致）**

Run（実ディスプレイ・マウス非操作で）:
```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/repro_a
uv run python scripts/capture_ui_screenshots.py --out design_export/repro_b
uv run python scripts/compare_screenshots.py design_export/repro_a design_export/repro_b
```
Expected: 5 ファイルすべて `OK ...: 完全一致`・exit 0。**一致しない場合はここで止まり、原因（アニメーション残り・フォーカス差・タイミング）を settle 秒数/状態定義の修正で潰してから先へ進む**（ベースラインの土台が壊れていると以降の凍結検証全体が無意味になる）。

- [ ] **Step 5: ベースライン撮影**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_baseline
```
Expected: `design_export/screenshots_baseline/` に PNG 5 枚。**このベースラインはブランチ完了まで削除・再取得しない。**

- [ ] **Step 6: 品質ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add scripts/capture_ui_screenshots.py scripts/compare_screenshots.py .gitignore
git commit -m "chore(design): 凍結検証スクリプト(撮影/比較)＋ベースライン撮影 (r1 Task 1)"
```

---

### Task 2: theme パッケージ — tokens.py

**Files:**
- Create: `src/valisync/gui/theme/__init__.py`
- Create: `src/valisync/gui/theme/tokens.py`
- Test: `tests/gui/test_theme_tokens.py`

**Interfaces:**
- Produces:
  - `Color(r, g, b, a=255)` frozen dataclass — `Color.from_hex("#rrggbb", a=255) -> Color` / `.hex -> str`（小文字 `#rrggbb`）/ `.rgba -> tuple[int, int, int, int]` / `.qss() -> str`（`rgba(r,g,b,a)`・a は 0-255）/ `.css() -> str`（a は 0-1 小数3桁）。値域外は `ValueError`。
  - `Colors` / `Spacing` / `Radii` / `Typography` / `ThemeTokens` frozen dataclass 群と値セット `DARK: ThemeTokens`。
  - `active() -> ThemeTokens` / `set_active(t: ThemeTokens) -> None`（呼び出し時読みの相手方。既定は DARK）。
  - `theme/__init__.py` は **tokens のみ** re-export（`from valisync.gui.theme import tokens` を成立させる空 + docstring。apply/qss は明示 import — spec §4.1）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_theme_tokens.py`:

```python
"""theme/tokens.py — Color 検証・DARK 完全性・純粋性 (Layer A)。"""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from valisync.gui.theme.tokens import DARK, Color, active, set_active


def test_color_hex_roundtrip():
    c = Color.from_hex("#1f77b4")
    assert (c.r, c.g, c.b, c.a) == (31, 119, 180, 255)
    assert c.hex == "#1f77b4"
    assert Color.from_hex("#4FC3F7").hex == "#4fc3f7"  # 小文字正規化


def test_color_rejects_out_of_range():
    with pytest.raises(ValueError):
        Color(256, 0, 0)
    with pytest.raises(ValueError):
        Color(0, 0, 0, -1)


def test_from_hex_rejects_malformed():
    with pytest.raises(ValueError):
        Color.from_hex("1f77b4")
    with pytest.raises(ValueError):
        Color.from_hex("#1f77b")


def test_color_qss_and_css_alpha_formats():
    c = Color(17, 17, 27, 230)
    assert c.qss() == "rgba(17,17,27,230)"  # Qt QSS: alpha 0-255
    assert c.css() == "rgba(17,17,27,0.902)"  # CSS: alpha 0-1 (spec §4.1 非互換吸収)
    assert c.rgba == (17, 17, 27, 230)


def test_dark_all_color_fields_are_color():
    for f in dataclasses.fields(DARK.colors):
        v = getattr(DARK.colors, f.name)
        if f.name == "signal_palette":
            assert len(v) == 10 and all(isinstance(c, Color) for c in v)
        else:
            assert isinstance(v, Color), f.name


def test_dark_values_frozen_snapshot():
    """DARK 値の意図的 test-lock — 再デザイン反復で値を変えたらここも更新 (spec §3)。"""
    c = DARK.colors
    assert c.signal_palette[0].hex == "#1f77b4"
    assert c.cursor_a.hex == "#f9e2af"
    assert c.cursor_b.hex == "#89b4fa"
    assert c.surface_chip == Color(17, 17, 27, 230)
    assert c.accent_active.hex == "#f59e0b"
    assert c.drop_highlight.hex == "#1f77b4"
    assert c.error.hex == "#c0392b"
    assert c.plot_background == Color(0, 0, 0)
    assert c.plot_foreground == Color(150, 150, 150)
    assert DARK.grid_alpha == 60
    assert DARK.spacing.chip_margins == (6, 5, 6, 5)
    assert DARK.radii.chip == 5
    assert DARK.typography.small_px == 9


def test_active_default_and_set():
    assert active() is DARK
    alt = dataclasses.replace(DARK)
    set_active(alt)
    try:
        assert active() is alt
    finally:
        set_active(DARK)


def test_tokens_module_is_qt_free():
    """純粋性ガード (spec §4.1) — fresh interpreter で tokens import 後も Qt 不在。"""
    code = (
        "import sys; import valisync.gui.theme.tokens; "
        "bad = [m for m in sys.modules if m.startswith(('PySide6', 'pyqtgraph'))]; "
        "sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_theme_tokens.py -v`
Expected: FAIL（`ModuleNotFoundError: valisync.gui.theme`）

- [ ] **Step 3: 実装**

`src/valisync/gui/theme/__init__.py`:

```python
"""デザイントークン基盤 (spec 2026-07-15-design-token-pipeline).

tokens は pure Python (VM から安全に import 可)。Qt 依存の適用フックは
theme.apply、QSS 断片生成は theme.qss を明示 import する (eager re-export
すると pure-Python VM の純粋性が壊れるため、ここでは re-export しない)。
"""
```

`src/valisync/gui/theme/tokens.py`:

```python
"""意味名デザイントークン — 単一の真実 (spec §4.1).

pure Python (PySide6/pyqtgraph import 禁止) — pure-Python VM から import
されるため。Qt 依存の適用は theme/apply.py・QSS 生成は theme/qss.py。

トークンは必ず呼び出し時に active() で読む (module 定数・default 引数へ
束縛しない) — デバッグテーマ注入・将来のテーマ切替が効かなくなるため。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Color:
    """正規化色 (RGBA 各 0-255)。消費側フォーマッタで Qt QSS / CSS 非互換を吸収。"""

    r: int
    g: int
    b: int
    a: int = 255

    def __post_init__(self) -> None:
        for name in ("r", "g", "b", "a"):
            v = getattr(self, name)
            if not 0 <= v <= 255:
                raise ValueError(f"Color.{name}={v} は 0-255 の範囲外")

    @classmethod
    def from_hex(cls, s: str, a: int = 255) -> Color:
        if len(s) != 7 or not s.startswith("#"):
            raise ValueError(f"hex 形式は '#rrggbb': {s!r}")
        return cls(int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), a)

    @property
    def hex(self) -> str:
        """`#rrggbb` (小文字・alpha 非包含)。"""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    @property
    def rgba(self) -> tuple[int, int, int, int]:
        """`QColor(*c.rgba)` / pyqtgraph 用タプル。"""
        return (self.r, self.g, self.b, self.a)

    def qss(self) -> str:
        """Qt スタイルシート形式 — alpha は 0-255 (CSS と非互換・spec §4.1)。"""
        return f"rgba({self.r},{self.g},{self.b},{self.a})"

    def css(self) -> str:
        """Web CSS 形式 — alpha は 0-1 (エクスポータ用・増分2)。"""
        return f"rgba({self.r},{self.g},{self.b},{self.a / 255:.3f})"


@dataclass(frozen=True)
class Colors:
    # プロット面 (pyqtgraph 既定 'k'/'d' と同値凍結 — spec §4.3)
    plot_background: Color
    plot_foreground: Color
    # 信号カーブ (matplotlib tab10)
    signal_palette: tuple[Color, ...]
    # カーソル A/B (プロット線 + readout マーカー)
    cursor_a: Color
    cursor_b: Color
    # readout チップ
    surface_chip: Color
    border_chip: Color
    text_primary: Color
    text_secondary: Color
    close_hover: Color
    # アクティブ軸/パネル強調 (amber 系)
    accent_active: Color
    accent_active_dark: Color
    grip_fill: Color
    # インタラクション表示
    drop_highlight: Color
    axis_move_indicator: Color
    axis_move_fill: Color
    # ステータス/フィードバック
    error: Color
    busy_spinner: Color
    text_releasing: Color
    preview_curve: Color


@dataclass(frozen=True)
class Spacing:
    chip_margins: tuple[int, int, int, int]
    chip_vspace: int
    chip_header_hspace: int
    chip_grid_hspace: int
    chip_grid_vspace: int


@dataclass(frozen=True)
class Radii:
    chip: int
    active_frame: int


@dataclass(frozen=True)
class Typography:
    small_px: int


@dataclass(frozen=True)
class ThemeTokens:
    colors: Colors
    spacing: Spacing
    radii: Radii
    typography: Typography
    grid_alpha: int  # X グリッド線アルファ (0-255)


DARK = ThemeTokens(
    colors=Colors(
        plot_background=Color(0, 0, 0),
        plot_foreground=Color(150, 150, 150),
        signal_palette=(
            Color.from_hex("#1f77b4"),
            Color.from_hex("#ff7f0e"),
            Color.from_hex("#2ca02c"),
            Color.from_hex("#d62728"),
            Color.from_hex("#9467bd"),
            Color.from_hex("#8c564b"),
            Color.from_hex("#e377c2"),
            Color.from_hex("#7f7f7f"),
            Color.from_hex("#bcbd22"),
            Color.from_hex("#17becf"),
        ),
        cursor_a=Color.from_hex("#f9e2af"),
        cursor_b=Color.from_hex("#89b4fa"),
        surface_chip=Color(17, 17, 27, 230),
        border_chip=Color.from_hex("#45475a"),
        text_primary=Color.from_hex("#cdd6f4"),
        text_secondary=Color.from_hex("#7f849c"),
        close_hover=Color.from_hex("#f38ba8"),
        accent_active=Color.from_hex("#f59e0b"),
        accent_active_dark=Color.from_hex("#b45309"),
        grip_fill=Color.from_hex("#ffffff"),
        # palette[0] と同値だが役割別トークン (spec §4.1 — 独立に動かせるように)
        drop_highlight=Color.from_hex("#1f77b4"),
        axis_move_indicator=Color(255, 165, 0),
        axis_move_fill=Color(255, 165, 0, 60),
        error=Color.from_hex("#c0392b"),
        busy_spinner=Color(120, 160, 255),
        text_releasing=Color(128, 128, 128),
        preview_curve=Color.from_hex("#4FC3F7"),
    ),
    spacing=Spacing(
        chip_margins=(6, 5, 6, 5),
        chip_vspace=3,
        chip_header_hspace=6,
        chip_grid_hspace=8,
        chip_grid_vspace=2,
    ),
    radii=Radii(chip=5, active_frame=2),
    typography=Typography(small_px=9),
    grid_alpha=60,
)

_active: ThemeTokens = DARK


def active() -> ThemeTokens:
    """現在のテーマ。呼び出し時に読むこと (module 定数へ束縛しない)。"""
    return _active


def set_active(t: ThemeTokens) -> None:
    """テーマ差し替え (デバッグテーマ撮影・将来のテーマ切替用)。

    生成済みウィジェットへは遡及しない — ウィンドウ構築前に呼ぶこと。
    """
    global _active
    _active = t
```

- [ ] **Step 4: パスを確認**

Run: `uv run pytest tests/gui/test_theme_tokens.py -v`
Expected: 全 PASS

- [ ] **Step 5: 品質ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/theme/ tests/gui/test_theme_tokens.py
git commit -m "feat(theme): 意味名トークン tokens.py (Color/ThemeTokens/DARK/active) (r1 Task 2)"
```

---

### Task 3: theme パッケージ — qss.py フォーマッタ

**Files:**
- Create: `src/valisync/gui/theme/qss.py`
- Test: `tests/gui/test_theme_qss.py`

**Interfaces:**
- Consumes: `tokens.ThemeTokens` / `tokens.Color` / `tokens.active()`（Task 2）
- Produces（すべて `t: ThemeTokens | None = None`、None で `active()` を読む）:
  - `readout_chip(t) -> str` / `readout_close_button(t) -> str` / `readout_small_label(t) -> str`
  - `colored_dot(color: Color) -> str`（HTML `<span>` の●）/ `unit_span(unit: str, t) -> str`
  - `active_panel_frame(t) -> str` / `panel_drop_highlight(t) -> str` / `area_drop_highlight(t) -> str`
  - `rename_error_border(t) -> str` / `error_label(t) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_theme_qss.py`:

```python
"""theme/qss.py — 配線検証: 各断片が意図したトークンを消費する (Layer A)。

値そのものの凍結は test_theme_tokens.test_dark_values_frozen_snapshot に集中。
ここでの token 参照 assert は「同値別トークンの誤配線」ガード (spec §7-6)。
"""

from __future__ import annotations

from valisync.gui.theme import qss
from valisync.gui.theme.tokens import DARK


def test_readout_chip_uses_chip_tokens():
    s = qss.readout_chip(DARK)
    assert DARK.colors.surface_chip.qss() in s
    assert DARK.colors.border_chip.hex in s
    assert f"border-radius: {DARK.radii.chip}px" in s
    assert DARK.colors.text_primary.hex in s


def test_readout_close_button_uses_text_and_hover_tokens():
    s = qss.readout_close_button(DARK)
    assert DARK.colors.text_primary.hex in s
    assert DARK.colors.close_hover.hex in s


def test_readout_small_label_uses_secondary_and_small_px():
    s = qss.readout_small_label(DARK)
    assert DARK.colors.text_secondary.hex in s
    assert f"font-size:{DARK.typography.small_px}px" in s


def test_colored_dot_and_unit_span():
    assert qss.colored_dot(DARK.colors.cursor_a) == (
        f'<span style="color:{DARK.colors.cursor_a.hex}">●</span>'
    )
    assert DARK.colors.text_secondary.hex in qss.unit_span("km/h", DARK)
    assert "[km/h]" in qss.unit_span("km/h", DARK)


def test_frame_and_highlight_styles():
    assert DARK.colors.accent_active.hex in qss.active_panel_frame(DARK)
    assert f"border-radius: {DARK.radii.active_frame}px" in qss.active_panel_frame(DARK)
    assert "GraphPanelView" in qss.panel_drop_highlight(DARK)
    assert "solid" in qss.panel_drop_highlight(DARK)
    assert "GraphAreaView" in qss.area_drop_highlight(DARK)
    assert "dashed" in qss.area_drop_highlight(DARK)
    assert DARK.colors.drop_highlight.hex in qss.panel_drop_highlight(DARK)
    assert DARK.colors.drop_highlight.hex in qss.area_drop_highlight(DARK)


def test_error_styles_use_error_token():
    assert DARK.colors.error.hex in qss.rename_error_border(DARK)
    assert DARK.colors.error.hex in qss.error_label(DARK)


def test_default_arg_reads_active_at_call_time():
    """t=None は呼び出し時に active() を読む (default 束縛禁止の検証)。"""
    import dataclasses

    from valisync.gui.theme.tokens import DARK as dark
    from valisync.gui.theme.tokens import Color, set_active

    alt = dataclasses.replace(
        dark, colors=dataclasses.replace(dark.colors, error=Color(1, 2, 3))
    )
    set_active(alt)
    try:
        assert Color(1, 2, 3).hex in qss.error_label()
    finally:
        set_active(dark)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_theme_qss.py -v`
Expected: FAIL（`ImportError: cannot import name 'qss'`）

- [ ] **Step 3: 実装**

`src/valisync/gui/theme/qss.py`:

```python
"""トークン→QSS/リッチテキスト断片フォーマッタ (spec §4.2).

view ソースに色構文文字列 (rgba(...) / #hex) を残さないための集中生成点
(残すとガードスキャンと衝突する)。pure Python (Qt import 禁止)。
t=None は呼び出し時に active() を読む (default 引数への束縛は禁止)。
生成文字列は凍結置換前のリテラルと同一内容 (見た目不変)。
"""

from __future__ import annotations

from valisync.gui.theme import tokens


def _t(t: tokens.ThemeTokens | None) -> tokens.ThemeTokens:
    return t if t is not None else tokens.active()


def readout_chip(t: tokens.ThemeTokens | None = None) -> str:
    tt = _t(t)
    c, r = tt.colors, tt.radii
    return (
        f"#CursorReadout {{ background: {c.surface_chip.qss()};"
        f" border: 1px solid {c.border_chip.hex}; border-radius: {r.chip}px; }}"
        f" QLabel {{ color: {c.text_primary.hex}; }}"
    )


def readout_close_button(t: tokens.ThemeTokens | None = None) -> str:
    c = _t(t).colors
    return (
        f"QToolButton {{ color:{c.text_primary.hex}; border:none; padding:0 2px; }}"
        f" QToolButton:hover {{ color:{c.close_hover.hex}; }}"
    )


def readout_small_label(t: tokens.ThemeTokens | None = None) -> str:
    tt = _t(t)
    return f"color:{tt.colors.text_secondary.hex}; font-size:{tt.typography.small_px}px;"


def colored_dot(color: tokens.Color) -> str:
    """readout ヘッダのカーソルマーカー● (RichText)。"""
    return f'<span style="color:{color.hex}">●</span>'


def unit_span(unit: str, t: tokens.ThemeTokens | None = None) -> str:
    """信号名脇の淡色 [unit] (RichText・DP8)。"""
    return f'<span style="color:{_t(t).colors.text_secondary.hex}">[{unit}]</span>'


def active_panel_frame(t: tokens.ThemeTokens | None = None) -> str:
    tt = _t(t)
    return (
        "#active_panel_frame {"
        f" border: 1px solid {tt.colors.accent_active.hex};"
        f" border-radius: {tt.radii.active_frame}px; background: transparent; }}"
    )


def panel_drop_highlight(t: tokens.ThemeTokens | None = None) -> str:
    return f"GraphPanelView {{ border: 2px solid {_t(t).colors.drop_highlight.hex}; }}"


def area_drop_highlight(t: tokens.ThemeTokens | None = None) -> str:
    return f"GraphAreaView {{ border: 2px dashed {_t(t).colors.drop_highlight.hex}; }}"


def rename_error_border(t: tokens.ThemeTokens | None = None) -> str:
    return f"border: 1px solid {_t(t).colors.error.hex};"


def error_label(t: tokens.ThemeTokens | None = None) -> str:
    return f"color: {_t(t).colors.error.hex};"
```

- [ ] **Step 4: パスを確認 → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_qss.py -v
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/theme/qss.py tests/gui/test_theme_qss.py
git commit -m "feat(theme): qss.py フォーマッタ — view から色構文を排除する集中生成点 (r1 Task 3)"
```

---

### Task 4: apply.py＋build_main_window 配線

**Files:**
- Create: `src/valisync/gui/theme/apply.py`
- Modify: `src/valisync/gui/app.py`（`build_main_window` 先頭で `apply_theme()`）
- Test: `tests/gui/test_theme_apply.py`

**Interfaces:**
- Produces: `apply_theme(t: ThemeTokens | None = None) -> None` — pyqtgraph の `background`/`foreground` を既定と同値（`plot_background`/`plot_foreground`）で明示固定。冪等。QPalette/QSS/QStyle は増分3（spec §4.3 — 非空 QSS は native 描画パスを変える罠があるため増分1 では触らない）。
- Consumes: `tokens.active()`（Task 2）

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_theme_apply.py`:

```python
"""theme/apply.py — pg 設定注入・冪等・build_main_window 配線 (Layer A/B)。"""

from __future__ import annotations

import pyqtgraph as pg

from valisync.gui.theme.apply import apply_theme
from valisync.gui.theme.tokens import DARK


def test_apply_sets_pg_options_idempotently(qapp):
    apply_theme()
    assert pg.getConfigOption("background") == DARK.colors.plot_background.rgba
    assert pg.getConfigOption("foreground") == DARK.colors.plot_foreground.rgba
    apply_theme()  # 冪等 — 2 度呼んでも同じ結果・例外なし
    assert pg.getConfigOption("background") == DARK.colors.plot_background.rgba


def test_build_main_window_applies_theme(qtbot):
    """sabotage: 事前に別値を仕込み、build_main_window が上書きすることを確認。

    main() でなく build_main_window に置く理由 = pytest-qt/realgui/撮影
    スクリプトが同じ描画経路を通るため (spec §4.3)。
    """
    from valisync.gui.app import build_main_window

    pg.setConfigOption("background", "w")
    window = build_main_window()
    qtbot.addWidget(window)
    assert pg.getConfigOption("background") == DARK.colors.plot_background.rgba
    assert pg.getConfigOption("foreground") == DARK.colors.plot_foreground.rgba
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_theme_apply.py -v`
Expected: FAIL（`ModuleNotFoundError: valisync.gui.theme.apply`）

- [ ] **Step 3: 実装**

`src/valisync/gui/theme/apply.py`:

```python
"""テーマ適用フック (spec §4.3) — Qt/pyqtgraph 依存はここに隔離。

増分1 は pyqtgraph 既定 ('k'/'d') と同値の明示固定のみ (見た目不変)。
QPalette / アプリ QSS / QStyle 切替は増分3 (クロム統一) — 非空 QSS が
native スタイルの描画パスを変える罠があるため増分1 では導入しない。
冪等: 同値 set の繰り返しは安全。生成済みウィジェットへは遡及しないため
build_main_window の先頭 (ウィジェット構築前) で呼ぶ。
"""

from __future__ import annotations

import pyqtgraph as pg

from valisync.gui.theme import tokens


def apply_theme(t: tokens.ThemeTokens | None = None) -> None:
    tt = t if t is not None else tokens.active()
    pg.setConfigOption("background", tt.colors.plot_background.rgba)
    pg.setConfigOption("foreground", tt.colors.plot_foreground.rgba)
```

`src/valisync/gui/app.py` の `build_main_window` 先頭に追記（import は既存群に追加）:

```python
from valisync.gui.theme.apply import apply_theme
```

```python
def build_main_window(app_vm: AppViewModel | None = None) -> MainWindow:
    """(docstring 既存のまま)"""
    apply_theme()  # ウィジェット構築前に (spec §4.3 — テスト経路と実アプリで同一)
    if app_vm is None:
        session = Session()
        app_vm = AppViewModel(session)
    return MainWindow(app_vm)
```

- [ ] **Step 4: パスを確認 → 全テスト → 比較**

```bash
uv run pytest tests/gui/test_theme_apply.py -v
uv run pytest
```
実ディスプレイで:
```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_after
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_after
```
Expected: 全 `OK 完全一致`（'k'/'d' と同値固定＝ピクセル不変の実証）。NG が出たら**この Task の変更が原因**（例: 'd' が (150,150,150) でない等）— 値を修正して再比較。

- [ ] **Step 5: 品質ゲート＋コミット**

```bash
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/theme/apply.py src/valisync/gui/app.py tests/gui/test_theme_apply.py
git commit -m "feat(theme): apply.py — pg 既定の同値明示固定を build_main_window に配線 (r1 Task 4)"
```

---

### Task 5: cursor_readout.py の凍結置換

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`（:76-83, :88, :98-101, :111-112, :190, :229-231, :420, :437）
- Test: `tests/gui/test_cursor_readout.py`（wiring assert 追記）

**Interfaces:**
- Consumes: `qss.readout_chip/readout_close_button/readout_small_label/colored_dot/unit_span`（Task 3）・`tokens.active()`（Task 2）

- [ ] **Step 1: import 追加**

```python
from valisync.gui.theme import qss, tokens
```

- [ ] **Step 2: `__init__` の置換（:76-83, :88, :98-101, :111-112）**

```python
        # Semi-opaque dark chip so it reads over the waveforms.
        self.setStyleSheet(qss.readout_chip())
        sp = tokens.active().spacing
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*sp.chip_margins)
        outer.setSpacing(sp.chip_vspace)
```

```python
        header_row.setSpacing(sp.chip_header_hspace)
```

```python
        self._close_btn.setStyleSheet(qss.readout_close_button())
```

```python
        self._grid.setHorizontalSpacing(sp.chip_grid_hspace)
        self._grid.setVerticalSpacing(sp.chip_grid_vspace)
```

- [ ] **Step 3: マーカー/ラベルの置換（:190, :229-231, :420, :437）**

:190:
```python
        header_html = f"{qss.colored_dot(tokens.active().colors.cursor_a)} {ta_str}"
```

:228-232（set_delta のヘッダ）:
```python
        c = tokens.active().colors
        header_html = (
            f"{qss.colored_dot(c.cursor_a)} {ta_str}"
            f"  {qss.colored_dot(c.cursor_b)} {tb_str}"
            f" · <b>Δt {dt_str}</b>"
        )
```

:420:
```python
                lbl.setStyleSheet(qss.readout_small_label())
```

:437:
```python
                name_lbl.setText(f"{name} {qss.unit_span(unit)}")
```

- [ ] **Step 4: wiring assert を追記**

`tests/gui/test_cursor_readout.py` 末尾:

```python
def test_header_markers_and_chip_use_tokens(qtbot):
    """配線検証: readout がカーソル/チップのトークンを消費する (凍結置換の対線)。"""
    from valisync.gui.theme.tokens import active

    w = CursorReadout()
    qtbot.addWidget(w)
    c = active().colors
    w.set_delta(
        0.5, 0.75, [DeltaReading("s", "#123456", 1.0, 0.5, _stats(1, 2, 0, 1, 9), True)]
    )
    assert c.cursor_a.hex in w._header.text()
    assert c.cursor_b.hex in w._header.text()
    assert c.surface_chip.qss() in w.styleSheet()
```

- [ ] **Step 5: テスト → 比較 → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_cursor_readout.py tests/gui/test_cursor_readout_diff.py -v
uv run pytest
```
実ディスプレイで再撮影→比較（Task 4 Step 4 と同一コマンド）。Expected: 全 `OK 完全一致`（特に `03_cursor.png` — チップ/マーカーが写る）。

```bash
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout.py
git commit -m "refactor(gui): cursor_readout をトークン参照へ凍結置換 (r1 Task 5)"
```

---

### Task 6: graph_panel_view.py の凍結置換

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（:106-108, :427, :434-435, :819-822, :843, :846, :889, :1444, :1447-1451, :1586, :1595, :2033-2035）
- Test: `tests/gui/test_graph_panel_view.py`（wiring assert 追記)

**Interfaces:**
- Consumes: `qss.active_panel_frame/panel_drop_highlight`・`tokens.active()`

**レビュー観点（honest layering note）**: `grip_fill`/`accent_active_dark` は QPainter 直描画で静止撮影・デバッグテーマ撮影のどちらにも写らない — この 2 トークンの配線正しさは**このタスクの diff レビューで担保**する（マッピング表と突合）。

- [ ] **Step 1: import 追加＋`_GRID_ALPHA` 削除**

import 群に追加:
```python
from valisync.gui.theme import qss, tokens
```

:106-108 の `_GRID_ALPHA = 60  # X グリッド線のアルファ (0-255・淡色)` 行を削除（`_Y_AXIS_FIXED_WIDTH` は残す — レイアウト機構定数・spec §9）。

- [ ] **Step 2: grip/フレーム paint の置換（:427, :434-435）**

```python
        p.setPen(QPen(QColor(*tokens.active().colors.accent_active.rgba), 2))
```

```python
            p.setBrush(QColor(*tokens.active().colors.grip_fill.rgba))
            p.setPen(QPen(QColor(*tokens.active().colors.accent_active_dark.rgba), 1))
```

- [ ] **Step 3: アクティブ枠 QSS（:819-822）**

```python
        self._active_frame.setStyleSheet(qss.active_panel_frame())
```
（:816 のコメント `色はアクティブ軸 amber (#f59e0b) と同系` は `色はアクティブ軸 amber (accent_active) と同系` に更新 — hex をコメントにも残さない。）

- [ ] **Step 4: カーソル線ペン（:843, :846, :1444, :1447-1451）**

:842-848:
```python
        self._cursor_line = self._make_cursor_line(
            pg.mkPen(tokens.active().colors.cursor_a.hex, width=2),
            self._on_cursor_line_dragged,
        )
        self._cursor_line_b = self._make_cursor_line(
            pg.mkPen(
                tokens.active().colors.cursor_b.hex,
                width=2,
                style=Qt.PenStyle.DashLine,
            ),
            self._on_cursor_line_b_dragged,
        )
```

:1441-1452 `_apply_cursor_pens`:
```python
    def _apply_cursor_pens(self) -> None:
        """Thicken the active cursor line (width 3.5) and normalise the other."""
        c = tokens.active().colors
        self._cursor_line.setPen(
            pg.mkPen(c.cursor_a.hex, width=3.5 if self._active_cursor == "A" else 2)
        )
        self._cursor_line_b.setPen(
            pg.mkPen(
                c.cursor_b.hex,
                width=3.5 if self._active_cursor == "B" else 2,
                style=Qt.PenStyle.DashLine,
            )
        )
```

- [ ] **Step 5: グリッド（:889）・軸移動インジケータ（:1586, :1595）・ドロップ強調（:2033-2035）**

:889:
```python
        self._x_axis.setGrid(tokens.active().grid_alpha if self.vm.grid_enabled else False)
```

:1586:
```python
            pen = QPen(QColor(*tokens.active().colors.axis_move_indicator.rgba))
```
（`# orange` コメント削除 — トークン名が意味を持つ）

:1595:
```python
            rect_item.setBrush(QBrush(QColor(*tokens.active().colors.axis_move_fill.rgba)))
```
（`# translucent orange` コメント削除）

:2031-2035:
```python
    def _set_drop_highlight(self, active: bool) -> None:
        self._drop_active = active
        self.setStyleSheet(qss.panel_drop_highlight() if active else "")
```

- [ ] **Step 6: wiring assert を追記**

`tests/gui/test_graph_panel_view.py` 末尾（既存ヘルパ `_make_panel_view(qtbot, tmp_path)`〔:104〕を再利用）:

```python
def test_cursor_pens_and_frame_use_tokens(qtbot: QtBot, tmp_path: Path) -> None:
    """配線検証: カーソル線 A/B・アクティブ枠・ドロップ強調がトークンを消費する。"""
    from valisync.gui.theme.tokens import active

    view = _make_panel_view(qtbot, tmp_path)
    c = active().colors
    assert view._cursor_line.pen.color().name() == c.cursor_a.hex
    assert view._cursor_line_b.pen.color().name() == c.cursor_b.hex
    assert c.accent_active.hex in view._active_frame.styleSheet()
    view._set_drop_highlight(True)
    assert c.drop_highlight.hex in view.styleSheet()
    view._set_drop_highlight(False)
    assert view.styleSheet() == ""
```
（pyqtgraph `InfiniteLine.pen` は QPen 属性・`QColor.name()` は小文字 `#rrggbb` を返すので `.hex` と直接比較できる。`_make_panel_view` の返り値が view のみであることは :104-109 で確認済み。）

- [ ] **Step 7: `_GRID_ALPHA` の他参照が無いことを確認**

Run: `uv run python -c "import subprocess,sys; sys.exit(subprocess.run(['git','grep','-n','_GRID_ALPHA']).returncode == 0)"`
（`git grep _GRID_ALPHA` がヒット 0 = exit 1 → 上記は exit 0。tests/ にも参照が無いこと。）

- [ ] **Step 8: テスト → 比較 → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_graph_panel_view.py -v
uv run pytest
```
実ディスプレイで再撮影→比較。Expected: 全 `OK 完全一致`（`03_cursor`=カーソル線・`04_grid`=グリッド・`05_affordances`=枠/ドロップ強調が写る）。

```bash
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_view.py
git commit -m "refactor(gui): graph_panel_view をトークン参照へ凍結置換 (r1 Task 6)"
```

---

### Task 7: signal palette の tokens 移動（VM call-time 読み）＋graph_area_view 置換

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（:31-43 `_PALETTE` 削除・色付与箇所 :257 付近を call-time 読みへ）
- Modify: `src/valisync/gui/views/graph_panel_view.py`（:68 import・:2210-2213 カラーメニュー）
- Modify: `src/valisync/gui/views/graph_area_view.py`（:349, :380-382）
- Test: 既存 `tests/gui/test_graph_panel_vm.py` が凍結によりそのまま通る（移行は Task 9）

**Interfaces:**
- Consumes: `tokens.active().colors.signal_palette`（`tuple[Color, ...]`・`.hex` で str 化）
- Produces: `GraphPanelVM` の公開 API・`RenderCurve.color: str`（hex）は**不変**。`_PALETTE` は削除（越境参照の解消・spec §4.4）。

- [ ] **Step 1: graph_panel_vm.py の置換**

import（pure Python — tokens は Qt 非依存なので VM の純粋性宣言と両立・spec §4.1）:
```python
from valisync.gui.theme import tokens
```

:31-43 の `# Matplotlib tab10 palette — 10 visually distinct colours.` コメントと `_PALETTE` タプル定義を**削除**。

:257 の `color = _PALETTE[len(self._plotted) % len(_PALETTE)]`（`add_signal_to_axis` 内）を次へ置換:

```python
        palette = tokens.active().colors.signal_palette
        color = palette[len(self._plotted) % len(palette)].hex
```

:96 のコメント `# hex colour, e.g. "#1f77b4"` は `# hex colour (theme.tokens.signal_palette 由来 or ユーザー指定)` に更新。

- [ ] **Step 2: graph_panel_view.py の import とカラーメニュー**

:68:
```python
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
```

:2210-2213:
```python
        for c in tokens.active().colors.signal_palette:
            act = color_menu.addAction(c.hex)
            act.setIcon(self._color_icon(c.hex))
```
（後続の `act.triggered.connect(...)` は現行のまま — `hex_color` を使っている場合は `c.hex` を束縛するローカルへ合わせる。）

- [ ] **Step 3: graph_area_view.py の置換**

import 追加:
```python
from valisync.gui.theme import qss
```

:349:
```python
            self._rename_editor.setStyleSheet(qss.rename_error_border())
```

:378-382:
```python
    def _set_drop_highlight(self, active: bool) -> None:
        self._drop_active = active
        self.setStyleSheet(qss.area_drop_highlight() if active else "")
```

- [ ] **Step 4: `_PALETTE` 参照が残っていないことを確認**

Run: `git grep -n "_PALETTE" -- src tests`
Expected: ヒットは tests/realgui/test_fu12_boundary_data_visible.py:147 の**コメント 1 件のみ**（Task 9 で更新）。src/ は 0 件。

- [ ] **Step 5: テスト → 比較 → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_graph_panel_vm.py tests/gui/test_graph_panel_view.py -v
uv run pytest
```
（凍結なので `#1f77b4` を assert する既存テストはそのまま通るはず。落ちたら палitra 順序/値の取り違え＝凍結違反シグナル。）
実ディスプレイで再撮影→比較。Expected: 全 `OK 完全一致`（`02_plotted`=カーブ 2 色が写る）。

```bash
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/viewmodels/graph_panel_vm.py src/valisync/gui/views/graph_panel_view.py src/valisync/gui/views/graph_area_view.py
git commit -m "refactor(gui): signal palette を theme.tokens へ移動し call-time 読みに (r1 Task 7)"
```

---

### Task 8: 残件の凍結置換（ダイアログ/プレビュー/スピナー/グレーアウト）

**Files:**
- Modify: `src/valisync/gui/views/export_csv_dialog.py`（:148）
- Modify: `src/valisync/gui/views/csv_format_dialog.py`（:84）
- Modify: `src/valisync/gui/views/signal_preview_window.py`（:22 と使用箇所）
- Modify: `src/valisync/gui/views/file_row_spinner.py`（:41）
- Modify: `src/valisync/gui/adapters/qt_signal_models.py`（:99）
- Test: `tests/gui/test_file_list_model.py`（グレーアウトの配線 assert 追記）

**Interfaces:**
- Consumes: `qss.error_label()`・`tokens.active().colors.{preview_curve, busy_spinner, text_releasing}`

- [ ] **Step 1: ダイアログ 2 箇所**

両ファイルに `from valisync.gui.theme import qss` を追加し、
`self._error.setStyleSheet("color: #c0392b;")` → `self._error.setStyleSheet(qss.error_label())`

- [ ] **Step 2: signal_preview_window.py**

`from valisync.gui.theme import tokens` を追加。:22 の module 定数 `_PREVIEW_PEN = pg.mkPen("#4FC3F7", width=1)` を**削除**し、`_PREVIEW_PEN` の使用箇所（本ファイル内を grep）を次で置換（call-time 読み — Global Constraints）:

```python
pg.mkPen(tokens.active().colors.preview_curve.hex, width=1)
```

- [ ] **Step 3: file_row_spinner.py（:41）**

`from valisync.gui.theme import tokens` を追加し:
```python
        pen = QPen(QColor(*tokens.active().colors.busy_spinner.rgba), 2)
```

- [ ] **Step 4: qt_signal_models.py（:99）**

`from valisync.gui.theme import tokens` を追加し:
```python
            return QColor(*tokens.active().colors.text_releasing.rgba)  # 解放中の行はグレーアウト
```

- [ ] **Step 5: グレーアウトの配線 assert（既存テストファイルへ追記）**

`tests/gui/test_file_list_model.py` 末尾（同ファイルの既存テストと同じ組立て・releasing 状態は monkeypatch で直接与える — releasing 遷移の production ロジック自体は tests/gui/test_file_browser_vm.py:142-163 が既にカバー）:

```python
def test_releasing_row_foreground_uses_token(qtbot: QtBot, monkeypatch) -> None:
    """配線検証: 解放中行の ForegroundRole が text_releasing トークンを返す。"""
    from PySide6.QtGui import QColor

    from valisync.gui.theme.tokens import active

    app_vm = AppViewModel()
    k = app_vm.session._groups.add(
        SignalGroup((), Path("/a.mf4").absolute(), "MDF4", datetime.now())
    )
    app_vm._loaded_keys = [k]
    vm = FileBrowserVM(app_vm)
    model = FileListModel(vm)
    monkeypatch.setattr(vm, "is_releasing", lambda row: True)

    index = model.index(0, 0, QModelIndex())
    expected = QColor(*active().colors.text_releasing.rgba)
    assert model.data(index, Qt.ItemDataRole.ForegroundRole) == expected
```
（ダイアログのエラーラベルは `qss.error_label()` の一行置換であり、qss 側の配線は Task 3 のテストで担保済み — widget レベルの追加 assert は不要。プレビュー線/スピナーも同型の一行置換で、diff レビューで担保する。）

- [ ] **Step 6: テスト → 比較 → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_file_list_model.py -v
uv run pytest
```
実ディスプレイで再撮影→比較。Expected: 全 `OK 完全一致`（この Task の対象は撮影に写らないサーフェスだが、無関係箇所を壊していない確認として実施）。

```bash
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/views/export_csv_dialog.py src/valisync/gui/views/csv_format_dialog.py src/valisync/gui/views/signal_preview_window.py src/valisync/gui/views/file_row_spinner.py src/valisync/gui/adapters/qt_signal_models.py tests/gui/test_file_list_model.py
git commit -m "refactor(gui): ダイアログ/プレビュー/スピナー/グレーアウトの凍結置換 (r1 Task 8)"
```

---

### Task 9: 既存の色 assert テストをトークン導出へ移行

**Files:**
- Modify: `tests/gui/test_graph_panel_vm.py`（:145, :151, :175, :183）
- Modify: `tests/realgui/test_fu12_boundary_data_visible.py`（:146-151 の前提化）

**Interfaces:**
- Consumes: `tokens.active().colors.signal_palette`／`DARK`

背景（spec §4.4）: 「production 定数に由来する期待値」をリテラルで持つテストは、増分3 の最初の値変更で崩壊する。トークン導出にすると **配線（palette[0] が最初の信号に付く）を検証しつつ値変更に追従**する。`#123456`/`#0a0b0c` 等のカスタム色プラミングテストと、入力値がそのまま出てくるだけの `test_cursor_readout_diff.py:53-55` は**対象外（無変更）**。

- [ ] **Step 1: test_graph_panel_vm.py の 4 箇所**

import 追加:
```python
from valisync.gui.theme.tokens import active
```

:145 と :151（期待値 `"#1f77b4"`）→ `active().colors.signal_palette[0].hex`
:175 の docstring `First added signal gets the first palette color #1f77b4.` → `First added signal gets the first palette color (signal_palette[0]).`
:183 `assert snapshot["plotted_signals"][0]["color"] == "#1f77b4"` → `== active().colors.signal_palette[0].hex`

- [ ] **Step 2: test_fu12 のピクセル述語をトークン前提化**

`_is_curve_pixel` 定義（:146-151）の直前に前提 assert を追加し、コメントを更新:

```python
    # 判定ヒューリスティクスの前提: palette[0] が青優勢 (b が r/g を 20 以上上回る)。
    # 再デザイン反復で palette[0] が青でなくなったら、ここが先に落ちて
    # ヒューリスティクスの更新を要求する (無言のスキャン失敗にしない)。
    from valisync.gui.theme.tokens import active

    pen0 = active().colors.signal_palette[0]
    assert pen0.b > pen0.g + 20 and pen0.b > pen0.r + 20, (
        f"palette[0]={pen0.hex} が青優勢でない — _is_curve_pixel をトークン値に合わせて更新せよ"
    )

    def _is_curve_pixel(color: QColor) -> bool:
        # 背景 plot_background=黒、曲線ペンは signal_palette[0] (青優勢)。
        # 青チャンネルが赤・緑を明確に上回る特徴は黒背景との混色でも保たれる。
        r, g, b, _a = color.getRgb()
        return b > g + 20 and b > r + 20
```

- [ ] **Step 3: テスト → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_graph_panel_vm.py -v
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add tests/gui/test_graph_panel_vm.py tests/realgui/test_fu12_boundary_data_visible.py
git commit -m "test(gui): 色 assert をトークン導出へ移行 (palette[0]/fu12 前提化) (r1 Task 9)"
```
（realgui は CI 対象外 — fu12 の実行は Task 12 の①ゲートで。）

---

### Task 10: 色ハードコード再混入ガード（AST スキャン・常設）

**Files:**
- Test: `tests/gui/test_theme_guard.py`（新規）

**Interfaces:**
- Consumes: なし（純静的解析）。allowlist は本ファイル内 `_ALLOWLIST`（行パターン ratchet — path＋一致パターン＋理由、陳腐化検知つき・spec §6）。

- [ ] **Step 1: ガードテストを書く（このテストは置換完了後の現状で GREEN になるのが正**・**RED になったら置換漏れの列挙として扱う）**

`tests/gui/test_theme_guard.py`:

```python
"""色ハードコード再混入ガード (常設 Layer A・spec §7)。

src/valisync/gui/ (theme/ 除く) の AST を走査し、色直書き
(hex 文字列・rgba(/rgb(/hsl( 構文・QColor リテラル引数・Qt.GlobalColor)
を検出して fail する。コメント/docstring は対象外 (AST ベースの理由)。
正当な構造色 (デザイン色でないもの・spec §4.1) は _ALLOWLIST で管理。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_GUI = Path(__file__).resolve().parents[2] / "src" / "valisync" / "gui"

# (相対 path, 行内一致パターン, 理由) — 行パターン ratchet (spec §6):
# ファイル単位だと同一ファイル内の新規違反を隠すため、行内容で絞る。
# どこにも一致しなくなったエントリは陳腐化として fail する。
_ALLOWLIST: tuple[tuple[str, str, str], ...] = (
    (
        "views/cursor_shapes.py",
        "Qt.GlobalColor.transparent",
        "QPixmap 初期化の構造色 — デザイン色でない (spec §4.1)",
    ),
    (
        "views/cursor_shapes.py",
        "QColor(255, 255, 255)",
        "カーソル bitmap の白ハロー — OS カーソル慣行の構造色 (spec §4.1)",
    ),
    (
        "views/cursor_shapes.py",
        "QColor(0, 0, 0)",
        "カーソル bitmap の黒線 — 同上",
    ),
)

_COLOR_STR = re.compile(r"#[0-9a-fA-F]{6}\b|rgba?\(|hsla?\(")


def _iter_py_files() -> list[Path]:
    return [
        p
        for p in sorted(SRC_GUI.rglob("*.py"))
        if "theme" not in p.relative_to(SRC_GUI).parts
    ]


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _violations_in(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    doc_ids = _docstring_ids(tree)
    lines = source.splitlines()
    found: list[tuple[int, str]] = []

    def line_of(node: ast.AST) -> str:
        return lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in doc_ids
            and _COLOR_STR.search(node.value)
        ):
            found.append((node.lineno, line_of(node)))
        if isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
            if name == "QColor" and any(
                isinstance(a, ast.Constant) for a in node.args
            ):
                found.append((node.lineno, line_of(node)))
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "GlobalColor"
        ):
            found.append((node.lineno, line_of(node)))
    return found


def test_no_hardcoded_colors_outside_theme():
    used_allow: set[int] = set()
    violations: list[str] = []
    for path in _iter_py_files():
        rel = path.relative_to(SRC_GUI).as_posix()
        for lineno, line in _violations_in(path.read_text(encoding="utf-8")):
            allowed = False
            for i, (a_path, a_pat, _reason) in enumerate(_ALLOWLIST):
                if rel == a_path and a_pat in line:
                    used_allow.add(i)
                    allowed = True
                    break
            if not allowed:
                violations.append(f"{rel}:{lineno}: {line}")
    assert not violations, (
        "色の直書きを検出 — gui/theme/tokens.py のトークン (tokens.active()) 経由に"
        "すること。QSS 断片は theme/qss.py に生成関数を追加する:\n"
        + "\n".join(violations)
    )
    stale = [_ALLOWLIST[i] for i in range(len(_ALLOWLIST)) if i not in used_allow]
    assert not stale, f"allowlist の陳腐化エントリ (どこにも一致しない): {stale}"
```

- [ ] **Step 2: GREEN を確認（RED なら置換漏れ — 列挙された箇所を Task 5-8 の流儀でトークン化してから再実行）**

Run: `uv run pytest tests/gui/test_theme_guard.py -v`
Expected: PASS。FAIL の場合は出力が「残存ハードコードの完全リスト」になっている — 各行を qss/tokens 経由に置換して GREEN まで繰り返す。

- [ ] **Step 3: sabotage 検証（ガードが本当に検出することの確認・一時変更）**

任意の view（例 welcome_view.py）に一時的に `x = "#123456"` を足して `uv run pytest tests/gui/test_theme_guard.py` が FAIL することを確認 → 取り消す（`git checkout -- <file>`）。同様に `QColor(1, 2, 3)` でも FAIL を確認 → 取り消す。

- [ ] **Step 4: 品質ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add tests/gui/test_theme_guard.py
git commit -m "test(gui): 色ハードコード再混入ガード (AST スキャン+ratchet allowlist) (r1 Task 10)"
```

---

### Task 11: 凍結最終検証（比較＋デバッグテーマ）

**Files:**
- Modify: `scripts/capture_ui_screenshots.py`（`--debug-theme` 追加）

**Interfaces:**
- Consumes: `tokens.set_active`（Task 2）・`dataclasses.replace`

- [ ] **Step 1: `--debug-theme` フラグを追加**

argparse に追加:
```python
    parser.add_argument(
        "--debug-theme",
        action="store_true",
        help="全 Color トークンを相異なる値にして撮影 (役割写像の目視検証・spec §7-6)",
    )
```

`QApplication` 生成後・`build_main_window()` 呼び出し**前**に:

```python
    if args.debug_theme:
        from valisync.gui.theme.tokens import set_active

        set_active(_debug_theme())
```

module 末尾付近に追加:

```python
def _debug_theme():
    """全 Color トークンが相異なるテーマ — 各トークンの着地点を目視で検証する。

    alpha は元値を保持 (半透明チップ等のレイアウト/合成条件を変えないため)。
    golden-angle で hue を回すので隣接 index も視覚的に離れる。
    """
    import colorsys
    import dataclasses

    from valisync.gui.theme.tokens import DARK, Color

    def distinct(i: int, a: int) -> Color:
        r, g, b = colorsys.hsv_to_rgb((i * 0.61803) % 1.0, 1.0, 1.0)
        return Color(int(r * 255), int(g * 255), int(b * 255), a)

    c = DARK.colors
    names = [f.name for f in dataclasses.fields(c) if f.name != "signal_palette"]
    repl: dict = {
        name: distinct(i, getattr(c, name).a) for i, name in enumerate(names)
    }
    repl["signal_palette"] = tuple(
        distinct(100 + i, 255) for i in range(len(c.signal_palette))
    )
    return dataclasses.replace(DARK, colors=dataclasses.replace(c, **repl))
```

- [ ] **Step 2: 最終凍結比較（①ゲート証拠その1）**

実ディスプレイで:
```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_final
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_final --diff-out design_export/diff
```
Expected: 5 ファイル全て `OK 完全一致`・exit 0。**NG の場合**: diff 画像で相違箇所を特定→該当 Task の置換を修正（値の取り違え）→再比較。比較ログ出力を保存（PR 添付用）。

- [ ] **Step 3: デバッグテーマ撮影と役割写像の目視検証（①ゲート証拠その2）**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_debug_theme --debug-theme
```
5 枚を開き、**マッピング表（本プラン冒頭）と突合して目視検証**:
- `02_plotted`: カーブ 2 本が signal_palette[0]/[1] の新色・プロット背景/前景（軸文字）が plot_background/plot_foreground の新色
- `03_cursor`: カーソル線 A/B が cursor_a/cursor_b・チップ背景/枠/文字/淡色ラベルが surface_chip/border_chip/text_primary/text_secondary・ヘッダ●2 個が cursor_a/cursor_b
- `04_grid`: グリッド線が plot_foreground 系で表示（grid_alpha は輝度でなく透過）
- `05_affordances`: アクティブ枠が accent_active・パネル/エリアのドロップ枠が drop_highlight（**palette[0] と別色になっていること** — 同値別トークン分離の直接実証）
判定に迷う色があれば = 誤配線の疑い → 該当置換を修正して再撮影。
（限界の明示: grip_fill/accent_active_dark/エラーラベル/スピナー/グレーアウト/プレビュー線はこの撮影に写らない — Task 6 レビューと Task 8 の wiring assert が担保。）

- [ ] **Step 4: コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add scripts/capture_ui_screenshots.py
git commit -m "chore(design): --debug-theme 撮影で役割写像を目視検証可能に (r1 Task 11)"
```

---

### Task 12: 品質ゲート・realgui ①ゲート・PR

**Files:** なし（検証と PR のみ）

- [ ] **Step 1: 全品質ゲート**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
Expected: 全て exit 0。

- [ ] **Step 2: realgui 無回帰（①証拠ゲート — 実ディスプレイ・実 OS 入力）**

```bash
uv run pytest --realgui tests/realgui/ -v
```
Expected: 全 PASS（特に test_journey_smoke / test_fu12_boundary_data_visible / カーソル系 — 再着色サーフェスを実経路で exercise する）。時間都合で scoped にする場合も上記 3 系統は必須。

- [ ] **Step 3: `/gui-verify` スキルで merge 前点検**

`/gui-verify` を起動し、①realgui 証拠（凍結比較ログ・デバッグテーマスクショ・realgui 実行結果）と E2E 十分性 contract を点検。

- [ ] **Step 4: PR 作成（証拠添付）**

```bash
git push -u origin feature/design-token-pipeline
gh pr create --title "feat(theme): デザイントークン基盤+凍結トークン化 (design-tokens r1)" --body "<spec/計画リンク・凍結比較ログ・デバッグテーマスクショ・realgui 結果を添付>"
gh pr checks <num> --watch
```
PR 本文に含める証拠: (1) `compare_screenshots` の全 OK ログ、(2) デバッグテーマ 5 枚と目視検証の結論、(3) realgui 実行サマリ、(4) マッピング表への参照。

---

## Self-Review メモ（プラン作成時に実施済み）

- spec §4.1（Color 型/純粋性/意味名/線引き）→ Task 2・10、§4.2（qss 集中生成）→ Task 3、§4.3（apply/build_main_window/pg のみ）→ Task 4、§4.4（置換＋テスト移行）→ Task 5-9、§6（決定的比較/QSettings 隔離/ratchet allowlist）→ Task 1・10、§7（凍結検証成立条件 7 項目）→ Task 1（grab 単位/静止/隔離/比較機構/手順）・Task 11（デバッグテーマ/二層の区別）、§8 増分1 全項目に対応タスクあり。エクスポータ/design.md/Claude Design 同期は**増分2（本プラン対象外）**。
- 主要な組立てコードは現物確認済み: `_make_panel_view`（test_graph_panel_view.py:104）・FileListModel 組立て（test_file_list_model.py:23-36）・`add_signal_to_axis` の色付与式（graph_panel_vm.py:257）・撮影スクリプトの組立て（test_journey_smoke.py:63-89 と同型・`loaded` 系 API は `session.load`＋`_on_loaded` の同期経路）。
