# デザイントークン増分3「クロムのトークン化（ダーク）」実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** アプリクロム（メニューバー・ツールバー・ドック・ダイアログ・item view 等）の配色を chrome トークン12個＋Fusion＋QPalette でトークン制御下に置く（テーマ三態の土台・ダーク値のみ）。

**Architecture:** spec §4.3 のスパイクで確定した方式 — `tokens.py` に `chrome_*` 12 フィールドを追加し、`apply.py` の `build_palette()` が QPalette の 12 role へ写像、`apply_theme()` が `Fusion` スタイル＋パレットを QApplication へ適用する。既存の widget 単位 QSS（チップ・エラーラベル・overlay 枠）とは共存（スパイクで実証済み）。エクスポート/見本カード/CSS 全域テストは `dataclasses.fields` 反復のため**自動追従**。spec: [2026-07-15-design-token-pipeline-design.md](../specs/2026-07-15-design-token-pipeline-design.md) §3（改訂）/§4.3/§8 増分3。

**Tech Stack:** Python 3.12 / PySide6（QPalette/QStyle）/ pytest(+pytest-qt)

## Global Constraints

- **QStyle 方式は Fusion＋QPalette で確定**（spec §4.3 スパイク 2026-07-16）。全面 QSS・windows11 style 追従は不採用。個別上書きが必要になったら `qss.py` 関数（本増分では追加しない — YAGNI）。
- **トークンは呼び出し時 `tokens.active()` 読み**。`tokens.py` は pure Python（Qt import 禁止）— QPalette 写像は `apply.py`（Qt 隔離層）に置く。
- **DARK の chrome 値はスパイクの Catppuccin 系を初期値とする**（確定配色は以降の Claude Design 反復でトークン値変更のみ）。値は Task 1 のコードが正。
- **これは意図した視覚変化** — 凍結ではない。前後比較は「クロムのみが変わり、プロット面・チップ・曲線色が不変」の目視確認に使う。確認後にベースラインを差し替える。
- **realgui 全数を merge 前ゲートに含める**（spec §8 増分3 — Fusion はコントロールの描画メトリクス〔行高・タブ高等〕を変えうるため、scoped 選定でなく全数）。
- **品質ゲート（コミット毎）**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過。
- **ブランチ**: `feature/design-tokens-r3-chrome`（spec 改訂コミット済み・Task 1 BASE=5ca6f2b）。

## GUI テスト分析（/gui-test-plan 判定）

- **変更種別**: 描画（クロム全域の配色・スタイル変更）＋純ロジック（トークン/パレット写像）。
- **触れるユーザージャーニー**: 全区間（クロムは常時可視）。操作の入力経路自体は不変更だが、**Fusion 化は itemview 行高・タブ高・ボタン寸法を変えうる** → realgui の掴み点前提に影響しうるため全数無回帰が必須（掴み点監査を全数実行で代替）。
- **E2E 受け入れ**: 効果=「クロムがトークン由来のダークで一貫描画」→ 描画 E2E: 実機スクショ目視（前後比較＋diff 画像でクロム領域限定を確認・カタログ 8 状態）。prod スケール不要（色は規模非依存）。
- **必要レイヤー**: A=必須（palette 写像の role↔token 全数・golden）/ B=必須（qapp への Fusion/palette 適用・冪等・build_main_window 経由）/ 入力経路 E2E(C)=**realgui 全数無回帰** / 描画 E2E=**要**（前後スクショ）。
- **②実質性**: role↔token は自動アサート。「一貫したダーククロム」はスクショ目視（PR 添付）。

## chrome トークン ↔ QPalette role 写像表（単一ビュー）

| トークン | QPalette role | DARK 初期値 | 用途 |
|---|---|---|---|
| `chrome_window` | Window | `#1e1e2e` | ウィンドウ/ドック/ダイアログ地 |
| `chrome_window_text` | WindowText | `#cdd6f4` | ラベル等の地の文 |
| `chrome_base` | Base | `#181825` | 入力欄/list/tree の地 |
| `chrome_alternate_base` | AlternateBase | `#1e1e2e` | 交互行 |
| `chrome_text` | Text | `#cdd6f4` | 入力欄/list/tree の文字 |
| `chrome_button` | Button | `#313244` | ボタン地 |
| `chrome_button_text` | ButtonText | `#cdd6f4` | ボタン文字 |
| `chrome_tooltip_base` | ToolTipBase | `#181825` | ツールチップ地 |
| `chrome_tooltip_text` | ToolTipText | `#cdd6f4` | ツールチップ文字 |
| `chrome_highlight` | Highlight | `#89b4fa` | 選択ハイライト |
| `chrome_highlight_text` | HighlightedText | `#11111b` | 選択中文字 |
| `chrome_placeholder` | PlaceholderText | `#7f849c` | プレースホルダ |

（`chrome_highlight`=cursor_b・`chrome_placeholder`=text_secondary 等と**同値だが役割別**トークン — spec §4.1 の原則どおり独立に動かせるようにする。消費者は `build_palette` の明示写像1箇所のみで、role↔token の対応は Task 2 のテストが全数 assert する。）

---

### Task 1: chrome トークン 12 個の追加（golden 先行の TDD）

**Files:**
- Modify: `src/valisync/gui/theme/tokens.py`（`Colors` 末尾に 12 フィールド＋`DARK` に値）
- Modify: `tests/gui/test_theme_tokens.py`（`test_dark_values_frozen_snapshot` の golden へ 12 エントリ追加）

**Interfaces:**
- Produces: `Colors.chrome_window` … `Colors.chrome_placeholder`（各 `Color` 型・上表の12個）。Task 2 の `build_palette` が消費。
- 自動追従（変更不要・確認のみ）: `export.build_css/build_json/build_token_cards`・`test_build_css_covers_every_token_field`・`test_dark_all_color_fields_are_color` は `dataclasses.fields` 反復のため新フィールドを自動で拾う。

- [ ] **Step 1: golden を先に拡張（RED）**

`tests/gui/test_theme_tokens.py` の `test_dark_values_frozen_snapshot` 内 `golden_colors` dict の末尾（`"preview_curve"` エントリの後）に追加:

```python
        # クロム (QPalette 写像・増分3 — 値はスパイクの Catppuccin 系初期値)
        "chrome_window": Color.from_hex("#1e1e2e"),
        "chrome_window_text": Color.from_hex("#cdd6f4"),
        "chrome_base": Color.from_hex("#181825"),
        "chrome_alternate_base": Color.from_hex("#1e1e2e"),
        "chrome_text": Color.from_hex("#cdd6f4"),
        "chrome_button": Color.from_hex("#313244"),
        "chrome_button_text": Color.from_hex("#cdd6f4"),
        "chrome_tooltip_base": Color.from_hex("#181825"),
        "chrome_tooltip_text": Color.from_hex("#cdd6f4"),
        "chrome_highlight": Color.from_hex("#89b4fa"),
        "chrome_highlight_text": Color.from_hex("#11111b"),
        "chrome_placeholder": Color.from_hex("#7f849c"),
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_theme_tokens.py::test_dark_values_frozen_snapshot -v`
Expected: FAIL（actual に chrome_* が無く dict 不一致）

- [ ] **Step 3: tokens.py に実装**

`Colors` dataclass の末尾（`preview_curve: Color` の後）に追加:

```python
    # クロム — QPalette の 12 role へ写像 (apply.build_palette・spec §4.3)。
    # cursor_b/text_secondary 等と同値の初期値があるが役割別トークン (spec §4.1)。
    chrome_window: Color
    chrome_window_text: Color
    chrome_base: Color
    chrome_alternate_base: Color
    chrome_text: Color
    chrome_button: Color
    chrome_button_text: Color
    chrome_tooltip_base: Color
    chrome_tooltip_text: Color
    chrome_highlight: Color
    chrome_highlight_text: Color
    chrome_placeholder: Color
```

`DARK` の `Colors(...)` 末尾（`preview_curve=...` の後）に追加:

```python
        chrome_window=Color.from_hex("#1e1e2e"),
        chrome_window_text=Color.from_hex("#cdd6f4"),
        chrome_base=Color.from_hex("#181825"),
        chrome_alternate_base=Color.from_hex("#1e1e2e"),
        chrome_text=Color.from_hex("#cdd6f4"),
        chrome_button=Color.from_hex("#313244"),
        chrome_button_text=Color.from_hex("#cdd6f4"),
        chrome_tooltip_base=Color.from_hex("#181825"),
        chrome_tooltip_text=Color.from_hex("#cdd6f4"),
        chrome_highlight=Color.from_hex("#89b4fa"),
        chrome_highlight_text=Color.from_hex("#11111b"),
        chrome_placeholder=Color.from_hex("#7f849c"),
```

- [ ] **Step 4: GREEN 確認＋自動追従の確認**

```bash
uv run pytest tests/gui/test_theme_tokens.py tests/gui/test_theme_export.py -v
```
Expected: 全 PASS（export 側は fields 反復で自動追従 — `test_build_css_covers_every_token_field` が新12変数を検証している）。

- [ ] **Step 5: 品質ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/theme/tokens.py tests/gui/test_theme_tokens.py
git commit -m "feat(theme): chrome トークン12個を追加 (QPalette 写像・ダーク初期値) (r3 Task 1)"
```

---

### Task 2: apply.py — build_palette＋Fusion 適用

**Files:**
- Modify: `src/valisync/gui/theme/apply.py`
- Modify: `tests/gui/test_theme_apply.py`

**Interfaces:**
- Consumes: Task 1 の `chrome_*` トークン。
- Produces: `build_palette(t: tokens.ThemeTokens) -> QPalette`（12 role を写像）。`apply_theme()` は従来の pg 設定に加え、QApplication が存在すれば `Fusion` スタイル（未適用時のみ）＋ `build_palette` のパレットを適用。QApplication 不在では pg 設定のみ（従来互換・落とさない）。

- [ ] **Step 1: 失敗するテストを書く（test_theme_apply.py へ追記・既存2テストは無変更）**

```python
def test_build_palette_maps_all_chrome_tokens(qapp):
    """role↔token の全数写像 — 同値別トークンの取り違えは QColor 比較で検出。"""
    from PySide6.QtGui import QColor, QPalette

    from valisync.gui.theme.apply import build_palette

    p = build_palette(DARK)
    c = DARK.colors
    roles = QPalette.ColorRole
    expected = {
        roles.Window: c.chrome_window,
        roles.WindowText: c.chrome_window_text,
        roles.Base: c.chrome_base,
        roles.AlternateBase: c.chrome_alternate_base,
        roles.Text: c.chrome_text,
        roles.Button: c.chrome_button,
        roles.ButtonText: c.chrome_button_text,
        roles.ToolTipBase: c.chrome_tooltip_base,
        roles.ToolTipText: c.chrome_tooltip_text,
        roles.Highlight: c.chrome_highlight,
        roles.HighlightedText: c.chrome_highlight_text,
        roles.PlaceholderText: c.chrome_placeholder,
    }
    for role, tok in expected.items():
        assert p.color(role) == QColor(*tok.rgba), role


def test_apply_sets_fusion_style_and_palette(qapp):
    from PySide6.QtGui import QColor, QPalette

    apply_theme()
    assert qapp.style().objectName() == "fusion"
    assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(
        *DARK.colors.chrome_window.rgba
    )
    apply_theme()  # 冪等 — 2度呼んでも fusion のまま・例外なし
    assert qapp.style().objectName() == "fusion"
```

さらに既存 `test_build_main_window_applies_theme` の末尾に 1 行追記:

```python
    assert pg.getConfigOption("foreground") == DARK.colors.plot_foreground.rgba
    # r3: build_main_window 経由でクロムも Fusion+トークンパレットになる
    import PySide6.QtWidgets as _qtw

    app = _qtw.QApplication.instance()
    assert app is not None and app.style().objectName() == "fusion"
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_theme_apply.py -v`
Expected: 新規2件 FAIL（`ImportError: build_palette` / style != fusion）

- [ ] **Step 3: apply.py を実装（全文置換）**

```python
"""テーマ適用フック (spec §4.3) — Qt/pyqtgraph 依存はここに隔離。

増分3: クロム = Fusion スタイル + トークン由来 QPalette (スパイクで確定)。
QPalette の 12 role を chrome_* トークンへ写像する。個別コンポーネントの
QSS 上書きが必要になったら qss.py に関数を足す (本増分では無し・YAGNI)。
冪等: 同値 set の繰り返しは安全 (Fusion は未適用時のみ setStyle)。
生成済みウィジェットの pg 設定へは遡及しないため build_main_window の先頭
(ウィジェット構築前) で呼ぶ。QApplication 不在の文脈では pg 設定のみ。
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from valisync.gui.theme import tokens


def build_palette(t: tokens.ThemeTokens) -> QPalette:
    """chrome_* トークン → QPalette (12 role の明示写像)。"""
    c = t.colors
    roles = QPalette.ColorRole
    mapping: list[tuple[QPalette.ColorRole, tokens.Color]] = [
        (roles.Window, c.chrome_window),
        (roles.WindowText, c.chrome_window_text),
        (roles.Base, c.chrome_base),
        (roles.AlternateBase, c.chrome_alternate_base),
        (roles.Text, c.chrome_text),
        (roles.Button, c.chrome_button),
        (roles.ButtonText, c.chrome_button_text),
        (roles.ToolTipBase, c.chrome_tooltip_base),
        (roles.ToolTipText, c.chrome_tooltip_text),
        (roles.Highlight, c.chrome_highlight),
        (roles.HighlightedText, c.chrome_highlight_text),
        (roles.PlaceholderText, c.chrome_placeholder),
    ]
    p = QPalette()
    for role, col in mapping:
        p.setColor(role, QColor(*col.rgba))
    return p


def apply_theme(t: tokens.ThemeTokens | None = None) -> None:
    tt = t if t is not None else tokens.active()
    pg.setConfigOption("background", tt.colors.plot_background.rgba)
    pg.setConfigOption("foreground", tt.colors.plot_foreground.rgba)
    app = QApplication.instance()
    if isinstance(app, QApplication):
        if app.style().objectName() != "fusion":
            app.setStyle("Fusion")
        app.setPalette(build_palette(tt))
```

- [ ] **Step 4: GREEN 確認 → full → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_apply.py -v
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/theme/apply.py tests/gui/test_theme_apply.py
git commit -m "feat(theme): Fusion+トークン由来 QPalette でクロムをトークン制御下に (r3 Task 2)"
```

（注: full 実行では build_main_window を使う既存テストが Fusion 化の影響を受ける。**落ちたテストは「Fusion 前提とずれた古い前提」か「実バグ」かを切り分けて報告** — 無断で数値をいじって黙らせない。）

---

### Task 3: 実機検証＋ベースライン/カタログ更新（意図した視覚変化の確定）

**Files:**
- なし（実行と成果物差し替えのみ。`design_export/` は gitignore）

**Interfaces:**
- Consumes: Task 1/2 の適用結果・既存 `scripts/capture_ui_screenshots.py` / `compare_screenshots.py` / `export_design_tokens.py`

- [ ] **Step 1: 新状態を撮影し旧ベースラインと比較（実ディスプレイ）**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_r3
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_r3 --diff-out design_export/diff_r3
```
Expected: **全5状態 NG（意図した変化）**。diff 画像と新スクショを開いて目視確認する観点:
- クロム（メニューバー・ツールバー・ドックタイトル・タブ・ボタン・item view・ステータスバー）が写像表の色で一貫
- **プロット面（黒）・曲線色（palette）・カーソル線・チップ（面/枠/文字）・アクティブ枠 amber が不変**（これらは既存トークン参照 — 変わっていたら Task 2 の副作用でバグ）
- 文字が □ になっていない

- [ ] **Step 2: デバッグテーマで chrome 写像の役割検証**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_r3_debug --debug-theme
```
`01_welcome.png`/`03_cursor.png` を開き、クロムの Window/Base/Button/Highlight 系が**相異なるデバッグ色**で塗り分けられていることを目視（`_debug_theme` は fields 反復生成のため chrome_* も自動で相異値になる）。

- [ ] **Step 3: ベースライン差し替え＋カタログ再撮影＋エクスポート**

```bash
Remove-Item -Recurse -Force design_export/screenshots_baseline
Copy-Item -Recurse design_export/screenshots_r3 design_export/screenshots_baseline
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog --catalog
uv run python scripts/export_design_tokens.py
```
Expected: catalog 8 枚＋export exit 0（tokens/colors.html に chrome 12 行が自動掲載される）。

- [ ] **Step 4: 記録コミット（成果物は gitignore のためコミット対象なし — 検証ログを report へ）**

コミット無し。比較ログ・目視所見を実装レポートに記載。

---

### Task 4: realgui 全数無回帰＋品質ゲート（①証拠ゲート）

**Files:** なし（検証のみ）

- [ ] **Step 1: 全品質ゲート**

```bash
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

- [ ] **Step 2: realgui 全数（実ディスプレイ・実 OS 入力・Fusion メトリクス変化の検出網）**

```bash
uv run pytest --realgui tests/realgui/ -v
```
（10分制限に収まらない場合はファイル群に分割して全ファイル消化。）Expected: 全 PASS。**FAIL が出たら Fusion の寸法変化で掴み点/ゾーン前提が崩れた可能性 — 修正せず全出力を添えて報告**（コントローラが「テストの座標前提更新」か「実バグ」かを判断）。

- [ ] **Step 3: 報告**（PR 作成はコントローラ）

---

### Task 5: PR・再同期・docs（コントローラ実施）

- [ ] **Step 1**: PR 作成（証拠: 前後スクショ・デバッグテーマ所見・realgui 全数結果）→ CI watch。
- [ ] **Step 2**: DesignSync 再同期（catalog 更新分・`list_files` 突合 → `finalize_plan` → `write_files`）。
- [ ] **Step 3**: merge 後、CLAUDE.md Phase 行の更新 docs PR（増分3 完了・spec 改訂〔三態・増分5〕込み）。

---

## Self-Review メモ（プラン作成時に実施済み）

- spec §4.3（Fusion＋QPalette 確定・12 role）→ Task 1/2、§8 増分3（クロムトークン・apply 実装・ベースライン/カタログ/再同期・realgui 全数）→ Task 1-5。増分4（LIGHT/オート/切替 UI）・増分5（アイコン）は対象外。
- 写像表の DARK 初期値はスパイク実測スクショ（fusion variant）で外観確認済みの値。役割写像は build_palette 1 箇所＋Task 2 の全数 assert で担保（ピクセル比較盲点の対策は不要 — 消費者が単一の明示写像のため）。
- 既知のリスク: Fusion 化で既存 headless/realgui の描画メトリクス前提が崩れる可能性 → Task 2 注記＋Task 4 全数ゲートで受け、失敗は無断修正せず報告に集約。
