# 領域境界フレーム（region frames）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** File Browser / Channel Browser / Diagnostics / 中央（プロット）エリアの境界を、separator 明色化＋各領域 1px 枠（新トークン `chrome_frame`）で視認可能にする。

**Architecture:** tokens.py に `chrome_frame` を追加 → qss.py に生成関数2つ（`main_window_separator` / `region_frame`）→ apply.py の `apply_theme` が app レベル stylesheet で separator を描き、新ヘルパ `frame_region` が領域ウィジェットへ枠を付ける → MainWindow が4領域に配線（view 無変更）。

**Tech Stack:** PySide6（Fusion＋QPalette＋部分 QSS）・既存 theme パイプライン（golden test-lock・撮影/比較スクリプト・realgui Layer C）。

**Spec:** [docs/superpowers/specs/2026-07-17-region-frames-design.md](../specs/2026-07-17-region-frames-design.md)

## Global Constraints

- qss.py は pure Python（Qt import 禁止・subprocess 純粋性テスト対象）。Qt 呼び出しは apply.py のみ。
- 色は呼び出し時に `tokens.active()` を読む（module 定数・default 引数への束縛禁止）。
- src に色リテラル（hex/rgba/QColor リテラル）を書かない — `tests/gui/test_theme_guard.py` が検出する。値は tokens.py のみ。
- `chrome_frame` 値: DARK `#45475a` / LIGHT `#bcc0cc`（**既存 `border_chip` と同値の別トークン** — 値ベース assert は誤配線に盲目のため値分岐テスト必須）。
- コミット前ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全て exit 0（touched-files にスコープせず全リポジトリで実行し出力をそのまま報告）。
- コメントは WHY のみ。ASCII 全角記号は ruff RUF001/RUF002 に注意（既存コードの noqa 流儀に合わせる）。

---

### Task 1: `chrome_frame` トークン追加＋golden 更新

**Files:**
- Modify: `src/valisync/gui/theme/tokens.py`（`Colors` フィールド・`DARK`・`LIGHT`）
- Test: `tests/gui/test_theme_tokens.py`（DARK/LIGHT golden）・`tests/gui/test_theme_apply.py`（chrome フィールド数）

**Interfaces:**
- Produces: `tokens.Colors.chrome_frame: Color`（Task 2/3 が `active().colors.chrome_frame` で消費）

- [ ] **Step 1: golden を先に更新（RED を作る）**

`tests/gui/test_theme_tokens.py` の `test_dark_values_frozen_snapshot` 内 `golden_colors` の `"chrome_disabled_text"` 行の直後に追加:

```python
        "chrome_frame": Color.from_hex("#45475a"),
```

同ファイル `test_light_values_frozen_snapshot` の `golden` の `"chrome_disabled_text"` 行の直後に追加:

```python
        "chrome_frame": Color.from_hex("#bcc0cc"),
```

`tests/gui/test_theme_apply.py` の `test_build_palette_role_mapping_with_distinct_values` 内:

```python
    assert len(chrome_fields) == 13
```

を次へ変更（chrome_frame は QSS 専用で QPalette role に写像しない — repl に含まれても無害）:

```python
    assert len(chrome_fields) == 14  # chrome_frame は QSS 専用 (palette 非写像)
```

- [ ] **Step 2: RED を確認**

Run: `uv run pytest tests/gui/test_theme_tokens.py tests/gui/test_theme_apply.py -v`
Expected: `test_dark_values_frozen_snapshot`・`test_light_values_frozen_snapshot`・`test_build_palette_role_mapping_with_distinct_values` が FAIL（chrome_frame 不在 / フィールド数 13）

- [ ] **Step 3: tokens.py に追加**

`Colors` の `chrome_disabled_text: Color` の直後に:

```python
    chrome_frame: Color  # 領域境界線 (separator+1px枠) — border_chip と同値だが別役割
```

`DARK` の `chrome_disabled_text=Color.from_hex("#6c7086"),` の直後に:

```python
        chrome_frame=Color.from_hex("#45475a"),
```

`LIGHT` の `chrome_disabled_text=Color.from_hex("#9ca0b0"),` の直後に:

```python
        chrome_frame=Color.from_hex("#bcc0cc"),
```

- [ ] **Step 4: GREEN を確認**

Run: `uv run pytest tests/gui/test_theme_tokens.py tests/gui/test_theme_apply.py tests/gui/test_theme_export.py -v`
Expected: 全 PASS（export のフィールド走査テスト `test_build_css_covers_every_token_field` は自動追随で PASS のはず — FAIL したら export.py でなくテスト側の想定を確認）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/tokens.py tests/gui/test_theme_tokens.py tests/gui/test_theme_apply.py
git commit -m "feat(theme): chrome_frame トークン追加 — 領域境界線 (region-frames Task 1)"
```

---

### Task 2: qss 生成関数 `main_window_separator` / `region_frame`

**Files:**
- Modify: `src/valisync/gui/theme/qss.py`（末尾に2関数追加）
- Test: `tests/gui/test_theme_qss.py`

**Interfaces:**
- Consumes: `tokens.Colors.chrome_frame`（Task 1）・既存 `_t(t)` ヘルパ
- Produces: `qss.main_window_separator(t: ThemeTokens | None = None) -> str`・`qss.region_frame(object_name: str, t: ThemeTokens | None = None) -> str`（Task 3 が消費）

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_theme_qss.py` の末尾に追加:

```python
def test_region_boundary_styles_use_chrome_frame():
    s = qss.main_window_separator(DARK)
    assert "QMainWindow::separator" in s
    assert DARK.colors.chrome_frame.hex in s
    assert "width: 4px" in s and "height: 4px" in s
    f = qss.region_frame("region_central", DARK)
    assert f.startswith("#region_central")
    assert f"border: 1px solid {DARK.colors.chrome_frame.hex}" in f


def test_region_frame_uses_chrome_frame_not_border_chip():
    """chrome_frame は border_chip と同値の別トークン (DARK #45475a / LIGHT #bcc0cc)。

    値ベース assert は誤配線 (builder が border_chip を参照) に盲目 — 値を
    分岐させたテーマで消費トークンを直接実証する (spec §4)。
    """
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, chrome_frame=Color(1, 2, 3))
    )
    for style in (qss.main_window_separator(alt), qss.region_frame("x", alt)):
        assert Color(1, 2, 3).hex in style
        assert DARK.colors.border_chip.hex not in style
```

- [ ] **Step 2: RED を確認**

Run: `uv run pytest tests/gui/test_theme_qss.py -v`
Expected: 新規2テストが FAIL（`AttributeError: module ... has no attribute 'main_window_separator'`）

- [ ] **Step 3: qss.py 末尾に実装**

```python
def main_window_separator(t: tokens.ThemeTokens | None = None) -> str:
    """ドック間/ドック↔中央のリサイズハンドルを境界線として描く (app レベル)。

    幅 4px は Fusion 既定より僅かに狭い (スパイクで目視承認・掴み幅は十分)。
    """
    return (
        f"QMainWindow::separator {{ background: {_t(t).colors.chrome_frame.hex};"
        " width: 4px; height: 4px; }"
    )


def region_frame(object_name: str, t: tokens.ThemeTokens | None = None) -> str:
    """領域コンテンツの 1px 境界枠 (ID セレクタで子への波及を遮断 — PR #116 の流儀)。"""
    return f"#{object_name} {{ border: 1px solid {_t(t).colors.chrome_frame.hex}; }}"
```

- [ ] **Step 4: GREEN を確認**

Run: `uv run pytest tests/gui/test_theme_qss.py -v`
Expected: 全 PASS（純粋性テストは qss import 連鎖に Qt が入らないことを既存 subprocess ガードで担保 — 新関数は tokens のみ参照なので影響なし）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/qss.py tests/gui/test_theme_qss.py
git commit -m "feat(theme): separator/領域枠の QSS 生成関数 (region-frames Task 2)"
```

---

### Task 3: `apply.frame_region` ヘルパ＋`apply_theme` の separator 適用

**Files:**
- Modify: `src/valisync/gui/theme/apply.py`
- Test: `tests/gui/test_theme_apply.py`

**Interfaces:**
- Consumes: `qss.main_window_separator()`・`qss.region_frame(name)`（Task 2）
- Produces: `apply.frame_region(widget: QWidget, name: str) -> None`（Task 4 が消費）・`apply_theme()` が app stylesheet に separator 規則を設定

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_theme_apply.py` の末尾に追加:

```python
def test_apply_theme_sets_separator_stylesheet(qapp):
    apply_theme()
    sheet = qapp.styleSheet()
    assert "QMainWindow::separator" in sheet
    assert DARK.colors.chrome_frame.hex in sheet
    apply_theme()  # 冪等 — 同一文字列の再設定で規則が重複しない
    assert qapp.styleSheet().count("QMainWindow::separator") == 1


def test_frame_region_sets_name_attribute_margins_and_qss(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from valisync.gui.theme.apply import frame_region

    w = QWidget()
    qtbot.addWidget(w)
    QVBoxLayout(w).setContentsMargins(0, 0, 0, 0)
    frame_region(w, "region_test")
    assert w.objectName() == "region_test"
    assert w.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    m = w.layout().contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (1, 1, 1, 1)
    assert "#region_test" in w.styleSheet()
    assert DARK.colors.chrome_frame.hex in w.styleSheet()


def test_frame_region_preserves_existing_name_and_margins(qtbot):
    """objectName 既設なら尊重・余白が非ゼロ (既定余白等) なら不変 (spec §6.2)。"""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from valisync.gui.theme.apply import frame_region

    w = QWidget()
    qtbot.addWidget(w)
    w.setObjectName("already_named")
    QVBoxLayout(w).setContentsMargins(9, 9, 9, 9)
    frame_region(w, "region_ignored")
    assert w.objectName() == "already_named"
    m = w.layout().contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (9, 9, 9, 9)
    assert "#already_named" in w.styleSheet()


def test_frame_region_border_paints_on_child_widget(qtbot):
    """honest ピクセル: 枠が『子ウィジェットとして』実描画される (PR #116 蛍光緑親パターン)。

    sabotage 構成: frame_region の WA_StyledBackground 行を外すと枠は描かれず
    RED になる (素の QWidget 子は QSS border を描かない Qt 仕様 — 増分1 で実証)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from valisync.gui.theme.apply import frame_region

    parent = QWidget()
    parent.setStyleSheet("background: #00ff00;")  # 蛍光緑 — 枠が透けたら即検出
    parent.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    parent.resize(200, 120)
    qtbot.addWidget(parent)
    child = QWidget(parent)
    QVBoxLayout(child).setContentsMargins(0, 0, 0, 0)
    child.setGeometry(20, 20, 100, 60)
    frame_region(child, "region_pixel_probe")
    parent.show()
    img = parent.grab().toImage()
    # grab() は物理ピクセル (DPR≠1 で論理座標の点打ちは枠線 1px を外す) —
    # 枠色ピクセルの計数で描画を実証する (この scene で chrome_frame 色は枠のみ)
    frame_color = QColor(*DARK.colors.chrome_frame.rgba).rgb()
    hits = sum(
        1
        for y in range(img.height())
        for x in range(img.width())
        if img.pixelColor(x, y).rgb() == frame_color
    )
    assert hits >= 100, f"枠線ピクセルが不足 ({hits}) — 枠が描画されていない"
```

- [ ] **Step 2: RED を確認**

Run: `uv run pytest tests/gui/test_theme_apply.py -v`
Expected: separator テストは stylesheet 空で FAIL・frame_region 3テストは ImportError で FAIL

- [ ] **Step 3: apply.py に実装**

import 追加（既存 `from PySide6.QtWidgets import QApplication` を変更）:

```python
from PySide6.QtWidgets import QApplication, QWidget

from valisync.gui.theme import qss
from valisync.gui.theme import settings as theme_settings
from valisync.gui.theme import tokens
```

`apply_theme` の palette 設定行の直後に追加:

```python
def apply_theme(t: tokens.ThemeTokens | None = None) -> None:
    tt = t if t is not None else tokens.active()
    pg.setConfigOption("background", tt.colors.plot_background.rgba)
    pg.setConfigOption("foreground", tt.colors.plot_foreground.rgba)
    app = QApplication.instance()
    if isinstance(app, QApplication):
        if app.style().objectName() != "fusion":
            app.setStyle("Fusion")
        app.setPalette(build_palette(tt))
        # 領域境界: separator は app レベル QSS でしか描けない (palette 非対応)
        app.setStyleSheet(qss.main_window_separator(tt))
```

モジュール末尾に `frame_region` を追加:

```python
def frame_region(widget: QWidget, name: str) -> None:
    """領域コンテンツに 1px 境界枠を付ける (region-frames spec §6.2)。

    どの領域に枠を付けるかはシェル (MainWindow) が選ぶ — view 自体は無変更で、
    同じ view を別文脈 (テスト・プレビュー) で使っても枠は付かない。
    """
    if not widget.objectName():
        widget.setObjectName(name)
    # 素の QWidget 子は QSS border を描かない (PR #116)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    lay = widget.layout()
    if lay is not None:
        m = lay.contentsMargins()
        if (m.left(), m.top(), m.right(), m.bottom()) == (0, 0, 0, 0):
            # margins-0 の子が枠を覆う罠 (PR #116) — 枠幅ぶんだけ空ける
            lay.setContentsMargins(1, 1, 1, 1)
    widget.setStyleSheet(qss.region_frame(widget.objectName()))
```

モジュール docstring の「個別コンポーネントの QSS 上書きが必要になったら qss.py に関数を足す (本増分では無し・YAGNI)」の行を実態に合わせ更新:

```python
QSS 上書きは qss.py の生成関数経由 (separator は app レベル・領域枠は frame_region)。
```

- [ ] **Step 4: GREEN＋sabotage 実証**

Run: `uv run pytest tests/gui/test_theme_apply.py -v` → 全 PASS

sabotage（一時的に `widget.setAttribute(...)` 行をコメントアウト）:
Run: `uv run pytest tests/gui/test_theme_apply.py::test_frame_region_border_paints_on_child_widget -v`
Expected: FAIL（枠不描画で親の緑 or 子の地色）→ 行を戻して PASS を再確認。結果をレビューへ報告。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/apply.py tests/gui/test_theme_apply.py
git commit -m "feat(theme): frame_region ヘルパ+separator app QSS (region-frames Task 3)"
```

---

### Task 4: MainWindow 4領域配線

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（central_stack 構築後）
- Test: `tests/gui/test_theme_apply.py`

**Interfaces:**
- Consumes: `theme_apply.frame_region(widget, name)`（Task 3・main_window.py は既に `from valisync.gui.theme import apply as theme_apply` 済み）

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_theme_apply.py` の末尾に追加:

```python
def test_main_window_regions_have_boundary_frames(qtbot):
    """4領域 (file/channel/diagnostics/central) に境界枠が配線される (spec §7)。"""
    from valisync.gui.app import build_main_window

    window = build_main_window()
    qtbot.addWidget(window)
    regions = {
        "region_file_browser": window.file_browser_view,
        "region_channel_browser": window.channel_browser_view,
        "region_diagnostics": window.diagnostics_dock.widget(),
        "region_central": window.central_stack,
    }
    for name, w in regions.items():
        assert w.objectName() == name, name
        assert f"#{name}" in w.styleSheet(), name
        assert DARK.colors.chrome_frame.hex in w.styleSheet(), name
```

- [ ] **Step 2: RED を確認**

Run: `uv run pytest tests/gui/test_theme_apply.py::test_main_window_regions_have_boundary_frames -v`
Expected: FAIL（objectName 空）

- [ ] **Step 3: main_window.py に配線**

`self._update_central()`（central_stack 構築ブロック末尾）の直後に追加:

```python
        # ── 領域境界フレーム (region-frames spec §7) — 対象はシェルが選ぶ ──────
        theme_apply.frame_region(self.file_browser_view, "region_file_browser")
        theme_apply.frame_region(self.channel_browser_view, "region_channel_browser")
        theme_apply.frame_region(self.diagnostics_dock.widget(), "region_diagnostics")
        theme_apply.frame_region(self.central_stack, "region_central")
```

- [ ] **Step 4: GREEN＋full suite**

Run: `uv run pytest tests/gui/test_theme_apply.py -v` → PASS
Run: `uv run pytest` → 全 PASS

**注意**: 余白 0→1px 化で file/channel/central の中身が 1px 内側へずれる（意図差分）。
もし既存テストが FAIL したら座標前提を確認し、実挙動に合わせて honest に更新する
（隠蔽・許容緩和で誤魔化さない）。FAIL したテスト名と対処をレビューへ報告。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/main_window.py tests/gui/test_theme_apply.py
git commit -m "feat(gui): 4領域へ境界フレーム配線 (region-frames Task 4)"
```

---

### Task 5: 実機検証＋ベースライン/カタログ/エクスポート更新（メインセッション駆動）

コード変更なし（成果物更新のみ）。実ディスプレイ必須（撮影中はマウス/キーボード非接触）。

- [ ] **Step 1: 前後差分で「意図差分のみ」を実証**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_regionframes_dark --theme dark
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_regionframes_dark
```

Expected: exit 1（差分あり）。差分ピクセルの位置分析（r5 と同型の ad-hoc スクリプト）で
**差分が (a) separator 位置の線 (b) 領域枠 1px (c) 余白化による 1px シフト帯に限定**
されることを確認。無関係な領域（プロット内部・チップ等）の差分ゼロ。

- [ ] **Step 2: light テーマ＋debug-theme の目視**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_regionframes_light --theme light
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_regionframes_debug --debug-theme
```

light で境界線が #bcc0cc で見えること、debug-theme で chrome_frame の相異値が
**境界（separator＋4領域の枠）にのみ**着地することを目視確認。

- [ ] **Step 3: ベースライン差し替え＋カタログ＋エクスポート再生成**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_baseline --theme dark
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_dark --theme dark --catalog
uv run python scripts/export_design_tokens.py --theme dark
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_light --theme light --catalog
uv run python scripts/export_design_tokens.py --theme light
```

Expected: 各テーマ `exported 18 files`。新ベースラインは region frames 込みの5状態。

---

### Task 6: docs/design.md＋realgui 全数＋ゲート

**Files:**
- Modify: `docs/design.md`（トークン表＋決定履歴）

- [ ] **Step 1: docs/design.md 更新**

「トークンの意味」表に行を追加（値は書かない — 本書の規約）:

```markdown
| 領域境界 | `chrome_frame` | separator と4領域の 1px 枠（`apply.frame_region` — 配線はシェルの責務） |
```

「決定履歴」の「（まだ無し — 最初の再デザイン反復で記録開始）」を置換:

```markdown
- 2026-07-17: `chrome_frame` 新設（surface1 系初期値・`border_chip` と同値の別役割）。
  4領域境界の視認性改善 — スパイク実機比較（現状/A separator のみ/B 1px 枠/C 背景差＋枠）
  でユーザーが B を選択（配色不変を優先・C は将来反復で再検討可）。PR #TBD（Task 7 で記入）。
```

- [ ] **Step 2: realgui 全数＋journey smoke（メインセッション/コントローラが実行）**

```bash
uv run pytest tests/realgui --realgui
```

Expected: 全 PASS。1px シフトに敏感なゾーン/グリップ/D&D 系を含む全数で無回帰
（/gui-verify ①ゲート — 入力経路の追加はないため contract は無回帰中心）。

- [ ] **Step 3: ゲート＋コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add docs/design.md
git commit -m "docs(design): chrome_frame をトークン表+決定履歴に記録 (region-frames Task 6)"
```

---

### Task 7: PR・Claude Design 再同期（コントローラ）

- [ ] Step 1: 最終ブランチレビュー（fable）→ 指摘対応
- [ ] Step 2: design.md 決定履歴の PR 番号を記入して commit → push → `gh pr create` → `gh pr checks --watch`
- [ ] Step 3: DesignSync 再同期（dark/light 各18ファイル・新規パスなし — chrome_frame は tokens.css/json/colors カード内に自動反映）
- [ ] Step 4: ユーザーへ完了報告（merge はユーザー判断）。merge 後に CLAUDE.md docs PR。
