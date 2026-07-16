# デザイントークン増分5「アイコン刷新」実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Qt 標準アイコン4個を vendored Lucide SVG＋実行時トークン着色（Normal/Disabled・HiDPI・両テーマ追従）へ置換し、Icons カードで Claude Design の検討範囲に載せる。

**Architecture:** spec §12（brainstorming＋スパイク＋アドバーサリアルレビュー確定）。`theme/icons/`（vendored SVG＋LICENSES.md＋package-data）・`theme/icons.py`（意味名レジストリ＋`icon()` — **module import は pure・Qt import は関数内**に置き export.py からレジストリを pure に参照可能にする）・消費側4箇所置換・エクスポータ Icons カード（SVG 生埋め込み＋CSS `var(--vs-*)` 継承＝Qt 非依存）。

**Tech Stack:** Python 3.12 / PySide6（QtSvg — pyside6-addons に同梱）/ pytest(+pytest-qt)

## Global Constraints

- **アセットは Lucide v1.24.0 に固定**（`https://unpkg.com/lucide-static@1.24.0/...` — スパイクでユーザーが見たものと同一）。SVG は無改変で vendored（`@license` ヘッダコメント込み）。
- **SVG 規約: 色は `currentColor` のみ**（固定 hex/rgb 禁止 — 新規テストが唯一の防波堤・spec §12.2）。
- **package-data 必須**（spec §12.2 C1）: `[tool.setuptools.package-data]` を追加。理由コメント（editable install では欠落が無症状・wheel 配布で全滅）を pyproject に残す。
- **HiDPI**（spec §12.2 I3）: `devicePixelRatioF` を乗じた物理ピクセルで描画し `setDevicePixelRatio`。**複数論理サイズ（16/20/24/32）を QIcon に登録**（ツールバー iconSize=24 等への拡大ボケ防止）。
- **`theme/icons.py` は module import 時 pure**（Qt import は `icon()` 関数内）— export.py が `ICONS` を pure に import するため。purity テスト対象に追加。
- **トークンは呼び出し時 `tokens.active()` 読み**（Normal=`chrome_text`・Disabled=`chrome_disabled_text`）。
- **品質ゲート（コミット毎）**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過。
- **ブランチ**: `feature/design-tokens-r5-icons`（spec §12 コミット済み・Task 1 BASE=6cbf2ee）。

## GUI テスト分析（/gui-test-plan 判定）

- T1/T2/T4: 純ロジック＋アセット → Layer A（規約・レジストリ・着色・カード）／T2 は Layer B（pixmap ピクセル色）。
- T3（消費側）: ウィジェット構成 — 入力経路不変 → Layer B（アクションのアイコン非空＋ピクセル色）。
- T5: 描画 E2E — dark/light 撮影で**差分がツールバー領域に限定**（diff 画像目視）・prod スケール不要。
- T6: realgui **scoped**（journey smoke＋shell 系 — アイコンは視覚のみでクリック座標・入力経路は不変。Fusion のようなメトリクス変化なし）＋ゲート。

## 初期レジストリ（spec §12.3・主 Lucide）

| 意味名 | アセット | 消費箇所 |
|---|---|---|
| `open` | `lucide/folder-open.svg` | shell_actions.py:24 |
| `open_folder` | `lucide/folder.svg` | shell_actions.py:31 |
| `export` | `lucide/save.svg` | shell_actions.py:38 |
| `data_explorer` | `lucide/folder-tree.svg` | main_window.py:217 |

---

### Task 1: アセット vendoring＋package-data＋SVG 規約テスト

**Files:**
- Create: `src/valisync/gui/theme/icons/lucide/{folder-open,folder,save,folder-tree}.svg`（下記 URL から取得・無改変）
- Create: `src/valisync/gui/theme/icons/LICENSES.md`
- Modify: `pyproject.toml`
- Test: `tests/gui/test_theme_icons.py`（新規・規約部分）

**Interfaces:**
- Produces: vendored アセット一式。Task 2 の `ICONS` が相対パスで参照。

- [ ] **Step 1: SVG 4個＋LICENSE を pinned 取得**

```powershell
$d = "src/valisync/gui/theme/icons/lucide"
New-Item -ItemType Directory -Force $d | Out-Null
foreach ($n in @("folder-open", "folder", "save", "folder-tree")) {
  Invoke-WebRequest -Uri "https://unpkg.com/lucide-static@1.24.0/icons/$n.svg" -OutFile "$d/$n.svg"
}
Invoke-WebRequest -Uri "https://unpkg.com/lucide-static@1.24.0/LICENSE" -OutFile "$d/_LICENSE_upstream.txt"
```
取得後、各 SVG の1行目が `<!-- @license lucide-static v1.24.0 - ISC -->`・`stroke="currentColor"` を含むことを目視確認。

- [ ] **Step 2: LICENSES.md を作成**

`src/valisync/gui/theme/icons/LICENSES.md`:

```markdown
# Vendored icon licenses

本ディレクトリの SVG は以下の OSS アイコンセットから**アイコン単位で** vendored している
(spec §12 — 主 Lucide・補 Tabler)。SVG は無改変 (各ファイル先頭の @license ヘッダ参照)。
着色は実行時に `currentColor` をテーマトークンへ置換して行う (theme/icons.py)。

## 出所一覧

| ファイル | セット | ライセンス |
|---|---|---|
| lucide/folder-open.svg | Lucide v1.24.0 | ISC |
| lucide/folder.svg | Lucide v1.24.0 | ISC |
| lucide/save.svg | Lucide v1.24.0 | ISC |
| lucide/folder-tree.svg | Lucide v1.24.0 | ISC |

Tabler Icons (MIT) から補完追加する場合は `tabler/` サブディレクトリに置き、
本表と下記ライセンス全文に MIT を追記すること。

## Lucide — ISC License

(lucide/_LICENSE_upstream.txt の全文をここに貼付 — Copyright (c) 2026 Lucide Icons and Contributors)
```
`_LICENSE_upstream.txt` の内容を末尾セクションへ貼り付けて `_LICENSE_upstream.txt` は削除（LICENSES.md に一本化）。

- [ ] **Step 3: pyproject.toml に package-data を追加**

`[tool.setuptools.packages.find]` セクションの直後に:

```toml
[tool.setuptools.package-data]
# setuptools 既定は .py 以外を wheel から落とす。dev/CI は editable install のため
# 欠落が無症状 (false-green) だが、wheel 配布時にアイコン参照が全滅する (spec §12.2)。
"valisync.gui.theme" = ["icons/**/*.svg", "icons/LICENSES.md"]
```

- [ ] **Step 4: SVG 規約テストを書く（GREEN 想定 — RED なら取得物が規約違反）**

`tests/gui/test_theme_icons.py`:

```python
"""theme/icons — vendored SVG 規約とレジストリ (Layer A)。

AST ガード (test_theme_guard.py) は *.py のみ走査で theme/ を除外するため、
SVG の色規約はこのテストが唯一の防波堤 (spec §12.2)。
"""

from __future__ import annotations

import re
from pathlib import Path

ICONS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "valisync" / "gui" / "theme" / "icons"
)


def _svg_files() -> list[Path]:
    return sorted(ICONS_DIR.rglob("*.svg"))


def test_vendored_svgs_exist():
    assert len(_svg_files()) >= 4


def test_svgs_use_current_color_only():
    """テーマ追従の前提: 色は currentColor のみ・固定 hex/rgb を持ち込まない。"""
    for path in _svg_files():
        text = path.read_text(encoding="utf-8")
        assert "currentColor" in text, path.name
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(", text), path.name


def test_licenses_md_covers_every_svg():
    """全 vendored SVG が LICENSES.md の出所一覧に載っている (帰属漏れ防止)。"""
    listing = (ICONS_DIR / "LICENSES.md").read_text(encoding="utf-8")
    for path in _svg_files():
        rel = path.relative_to(ICONS_DIR).as_posix()
        assert rel in listing, rel
```

- [ ] **Step 5: 実行 → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_icons.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/icons/ pyproject.toml tests/gui/test_theme_icons.py
git commit -m "feat(theme): Lucide SVG 4個を vendored (LICENSES.md+package-data+規約テスト) (r5 Task 1)"
```

---

### Task 2: theme/icons.py — レジストリ＋icon()（HiDPI・Normal/Disabled）

**Files:**
- Create: `src/valisync/gui/theme/icons.py`
- Test: `tests/gui/test_theme_icons.py`（追記）

**Interfaces:**
- Produces: `ICONS: dict[str, str]`（module レベル・pure に import 可）／`icon(name: str) -> QIcon`（16/20/24/32 論理サイズ×dpr を Normal=`chrome_text`・Disabled=`chrome_disabled_text` で登録・未知 name は KeyError）。

- [ ] **Step 1: 失敗するテストを書く（test_theme_icons.py へ追記）**

```python
def test_registry_paths_resolve():
    from valisync.gui.theme.icons import ICONS

    assert set(ICONS) == {"open", "open_folder", "export", "data_explorer"}
    for name, rel in ICONS.items():
        assert (ICONS_DIR / rel).is_file(), f"{name} -> {rel}"


def test_icons_module_import_is_qt_free():
    """module import は pure (export.py が ICONS を pure に参照するため・spec §12.2)。"""
    import subprocess
    import sys

    code = (
        "import sys; import valisync.gui.theme.icons; "
        "bad = [m for m in sys.modules if m.startswith(('PySide6', 'pyqtgraph'))]; "
        "sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_icon_unknown_name_is_loud():
    import pytest as _pytest

    from valisync.gui.theme.icons import icon

    with _pytest.raises(KeyError):
        icon("no_such_icon")


def _has_pixel_near(image, expected_rgb, tol=40):
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() > 200 and (
                abs(c.red() - expected_rgb[0]) < tol
                and abs(c.green() - expected_rgb[1]) < tol
                and abs(c.blue() - expected_rgb[2]) < tol
            ):
                return True
    return False


def test_icon_pixels_use_theme_tokens(qtbot):
    """Normal=chrome_text・Disabled=chrome_disabled_text のトークン着色 (Layer B)。"""
    from PySide6.QtGui import QIcon

    from valisync.gui.theme.icons import icon
    from valisync.gui.theme.tokens import active

    c = active().colors
    ico = icon("open")
    assert not ico.isNull()
    normal = ico.pixmap(24, 24, QIcon.Mode.Normal).toImage()
    disabled = ico.pixmap(24, 24, QIcon.Mode.Disabled).toImage()
    ct = (c.chrome_text.r, c.chrome_text.g, c.chrome_text.b)
    cd = (c.chrome_disabled_text.r, c.chrome_disabled_text.g, c.chrome_disabled_text.b)
    assert _has_pixel_near(normal, ct), "Normal に chrome_text 系ピクセルが無い"
    assert _has_pixel_near(disabled, cd), "Disabled に chrome_disabled_text 系ピクセルが無い"
    # 同値でないテーマ前提の分離確認 (DARK: text #cdd6f4 / disabled #6c7086 は十分離れている)
    assert not _has_pixel_near(disabled, ct, tol=20)
```

- [ ] **Step 2: RED 確認 → 実装**

`src/valisync/gui/theme/icons.py`:

```python
"""意味名アイコンレジストリ＋実行時トークン着色 (spec §12.2)。

module import は pure (export.py が ICONS を Qt なしで参照するため) —
Qt/QtSvg の import は icon() 関数内に置く。SVG は currentColor のみ規約
(tests/gui/test_theme_icons.py が唯一の防波堤) で、呼び出し時に
Normal=chrome_text / Disabled=chrome_disabled_text へ置換して描画する。
"""

from __future__ import annotations

from pathlib import Path

from valisync.gui.theme import tokens

ICONS_DIR = Path(__file__).resolve().parent / "icons"

# 意味名 → アセット相対パス (主 Lucide・補 Tabler は tabler/ に追加・spec §12.3)
ICONS: dict[str, str] = {
    "open": "lucide/folder-open.svg",
    "open_folder": "lucide/folder.svg",
    "export": "lucide/save.svg",
    "data_explorer": "lucide/folder-tree.svg",
}

# ツールバー(24)/メニュー(16)等の実寸を直接登録し QIcon の拡大ボケを避ける
_SIZES = (16, 20, 24, 32)


def icon(name: str) -> "object":
    """意味名からテーマ着色済み QIcon を生成する (未知 name は KeyError)。

    HiDPI: devicePixelRatio を乗じた物理ピクセルで描画し setDevicePixelRatio
    (QStyle.standardIcon のネイティブ HiDPI 対応からの退行防止・spec §12.2)。
    """
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    svg = (ICONS_DIR / ICONS[name]).read_text(encoding="utf-8")
    c = tokens.active().colors
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if isinstance(app, QGuiApplication) else 1.0

    ico = QIcon()
    for mode, color in (
        (QIcon.Mode.Normal, c.chrome_text),
        (QIcon.Mode.Disabled, c.chrome_disabled_text),
    ):
        data = QByteArray(svg.replace("currentColor", color.hex).encode("utf-8"))
        renderer = QSvgRenderer(data)
        for size in _SIZES:
            phys = max(1, round(size * dpr))
            pm = QPixmap(phys, phys)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            renderer.render(painter)
            painter.end()
            pm.setDevicePixelRatio(dpr)
            ico.addPixmap(pm, mode)
    return ico
```

（mypy: 戻り値注釈は `"object"` でなく `QIcon` にしたいが Qt import が関数内のため、`from __future__ import annotations` の下で `if TYPE_CHECKING: from PySide6.QtGui import QIcon` を追加し `def icon(name: str) -> QIcon:` とする — 実装時はこの TYPE_CHECKING 形を採ること。）

- [ ] **Step 3: GREEN → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_icons.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/icons.py tests/gui/test_theme_icons.py
git commit -m "feat(theme): icons.py — 意味名レジストリ+トークン着色 QIcon (HiDPI/Disabled) (r5 Task 2)"
```

---

### Task 3: 消費側置換（shell_actions ×3・main_window ×1）

**Files:**
- Modify: `src/valisync/gui/views/shell_actions.py`
- Modify: `src/valisync/gui/views/main_window.py`（:216-220）
- Test: `tests/gui/test_theme_icons.py`（追記）

**Interfaces:**
- Consumes: `icons.icon(...)`（Task 2）。`QStyle.standardIcon` は src から消滅（grep で確認）。

- [ ] **Step 1: 失敗するテストを書く（追記）**

```python
def test_shell_actions_use_registry_icons(qtbot):
    """4アクション全てがレジストリ由来の非 null アイコンを持つ (Layer B)。"""
    from PySide6.QtWidgets import QWidget

    from valisync.gui.views.shell_actions import ShellActions

    parent = QWidget()
    qtbot.addWidget(parent)
    acts = ShellActions(parent)
    for key in ("open", "open_folder", "export"):
        assert not acts.action(key).icon().isNull(), key
    # ピクセルがトークン色 (QStyle 由来の多色アイコンからの置換確認)
    from valisync.gui.theme.tokens import active

    c = active().colors
    img = acts.action("open").icon().pixmap(24, 24).toImage()
    assert _has_pixel_near(img, (c.chrome_text.r, c.chrome_text.g, c.chrome_text.b))
```

- [ ] **Step 2: RED 確認 → 実装**

`shell_actions.py` — docstring の "standard icon" を "registry icon (theme/icons.py)" に更新し:
- import: `from PySide6.QtGui import QAction, QIcon, QKeySequence` はそのまま・`from PySide6.QtWidgets import QWidget`（QStyle 削除）・`from valisync.gui.theme import icons` を追加
- `style = parent.style()` 行を削除
- 3箇所: `style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)` → `icons.icon("open")`・`SP_DirOpenIcon` → `icons.icon("open_folder")`・`SP_DialogSaveButton` → `icons.icon("export")`

`main_window.py` :216-220:

```python
        self.action_data_explorer = QAction(
            icons.icon("data_explorer"),
            "Data Explorer",
            self,
        )
```
import へ `from valisync.gui.theme import icons` を追加。`QStyle` の他用途が無ければ import から除去（`git grep -n "QStyle" src/valisync/gui/views/main_window.py` で確認 — 残用途があれば残す）。

- [ ] **Step 3: `standardIcon` 残存ゼロ確認 → GREEN → full → ゲート → コミット**

```bash
git grep -n "standardIcon" -- src/
```
Expected: 0 件。

```bash
uv run pytest tests/gui/test_theme_icons.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/shell_actions.py src/valisync/gui/views/main_window.py tests/gui/test_theme_icons.py
git commit -m "feat(gui): Qt 標準アイコン4個をレジストリアイコンへ置換 (r5 Task 3)"
```

---

### Task 4: エクスポータ Icons カード（pure・SVG 生埋め込み）

**Files:**
- Modify: `src/valisync/gui/theme/export.py`
- Modify: `scripts/export_design_tokens.py`
- Test: `tests/gui/test_theme_export.py`（追記）

**Interfaces:**
- Produces: `export.build_icons_card(t: ThemeTokens, theme_label: str) -> str` — group=`Icons / {theme_label}`・レジストリ全アイコンの SVG 生テキストを `<svg>` として埋め込み、Normal/Disabled ラッパーに `style="color: var(--vs-color-chrome-text)"` / `var(--vs-color-chrome-disabled-text)` を指定（`currentColor` は CSS 継承で解決・Qt 非依存）・出所（lucide/tabler）表示。CLI は `root/icons/overview.html` に出力し `written` に追加（manifest 自動掲載）。

- [ ] **Step 1: 失敗するテストを書く（test_theme_export.py へ追記）**

```python
def test_build_icons_card_embeds_all_registry_svgs():
    from valisync.gui.theme.icons import ICONS

    html = export.build_icons_card(DARK, "Dark")
    assert html.splitlines()[0] == '<!-- @dsCard group="Icons / Dark" -->'
    assert "@TOKENS_CSS" not in html  # 注入済み
    assert html.count("<svg") >= len(ICONS) * 2  # Normal+Disabled
    for name, rel in ICONS.items():
        assert name in html
        assert rel.split("/")[0] in html  # 出所 (lucide 等)
    assert "var(--vs-color-chrome-text)" in html
    assert "var(--vs-color-chrome-disabled-text)" in html


def test_icons_card_import_stays_pure():
    """export.py が icons レジストリを読んでも Qt 非依存のまま (spec §12.2 I2)。"""
    import subprocess
    import sys

    code = (
        "import sys; import valisync.gui.theme.export; "
        "bad = [m for m in sys.modules if m.startswith(('PySide6', 'pyqtgraph'))]; "
        "sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
```

- [ ] **Step 2: RED → 実装（export.py へ追記）**

```python
def build_icons_card(t: ThemeTokens, theme_label: str) -> str:
    """Icons カード — SVG 生テキストを埋め込み currentColor は CSS 継承で解決
    (Qt 非依存・spec §12.2)。Normal/Disabled をトークン var で並置する。"""
    from valisync.gui.theme.icons import ICONS, ICONS_DIR

    rows: list[str] = []
    for name, rel in sorted(ICONS.items()):
        svg = (ICONS_DIR / rel).read_text(encoding="utf-8")
        source = rel.split("/")[0]
        rows.append(
            "<tr>"
            f"<td><code>{name}</code></td>"
            f"<td><span style='color: var(--vs-color-chrome-text)'>{svg}</span></td>"
            f"<td><span style='color: var(--vs-color-chrome-disabled-text)'>{svg}</span></td>"
            f"<td><code>{source}</code></td>"
            "</tr>"
        )
    body = (
        "<table><tr><th>name</th><th>Normal</th><th>Disabled</th><th>出所</th></tr>"
        + "".join(rows)
        + "</table>"
        "<p>着色は実行時に currentColor をトークンへ置換 (theme/icons.py)。"
        "本カードは CSS 継承で同じトークンを解決している。</p>"
    )
    return _card(f"Icons / {theme_label}", "Icons", body, t)
```

`scripts/export_design_tokens.py` — token cards の書き出しブロックの後に:

```python
    _write(root / "icons" / "overview.html", export.build_icons_card(t, theme_label))
    written.append("icons/overview.html")
```

- [ ] **Step 3: GREEN → full → ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_export.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/export.py scripts/export_design_tokens.py tests/gui/test_theme_export.py
git commit -m "feat(design): Icons カード (SVG 生埋め込み+CSS 継承・Qt 非依存) (r5 Task 4)"
```

---

### Task 5: 実機検証＋ベースライン/カタログ更新（意図した変化の確定）

**Files:** なし（実行・検証・成果物差し替え）

- [ ] **Step 1: dark 前後比較（実ディスプレイ）**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_r5_dark --theme dark
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_r5_dark --diff-out design_export/diff_r5
```
Expected: 全5状態 NG（意図した変化）だが **diff がツールバー領域（上部ストリップ）に限定**していることを diff 画像で目視確認。ツールバー外に差分があれば BLOCKED。新スクショでアイコンが Lucide 線画・トークン色（export は起動時 disabled でグレー）であることを目視。

- [ ] **Step 2: light 撮影＋目視 → ベースライン差し替え＋両テーマカタログ＋エクスポート**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_r5_light --theme light
Remove-Item -Recurse -Force design_export/screenshots_baseline
Copy-Item -Recurse design_export/screenshots_r5_dark design_export/screenshots_baseline
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_dark --theme dark --catalog
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_light --theme light --catalog
uv run python scripts/export_design_tokens.py --theme dark
uv run python scripts/export_design_tokens.py --theme light
```
light の 01 でアイコンが Latte の濃文字色で視認可を目視。export 出力に `icons/overview.html` が両テーマ分あることを確認（各18ファイルに増える）。

- [ ] **Step 3: 所見を report へ**（コミット無し）

---

### Task 6: docs＋realgui scoped＋ゲート（PR はコントローラ）

**Files:**
- Modify: `docs/design.md`（アイコン節を1項追加）

- [ ] **Step 1: docs/design.md — トークン表の後に追記**

```markdown
## アイコン

ツールバー/メニューのアイコンは `src/valisync/gui/theme/icons/` の vendored SVG
（主 Lucide・補 Tabler — 出所とライセンスは同ディレクトリの LICENSES.md）を、
実行時に `currentColor` → トークン（Normal=`chrome_text`・Disabled=`chrome_disabled_text`）
置換で着色する（`theme/icons.py` の意味名レジストリ）。テーマに自動追従し、
カタログの Icons カードで両モードを確認できる。SVG に固定色を持ち込まない
（`tests/gui/test_theme_icons.py` が検証）。
```

- [ ] **Step 2: realgui scoped＋ゲート**

```bash
uv run pytest --realgui tests/realgui/test_journey_smoke.py tests/realgui/test_shell_chrome_flow.py tests/realgui/test_open_realclick.py -q
```
（存在しないファイル名は `ls tests/realgui/ | grep -i "shell\|open\|journey"` で現物合わせ — 意図は「ツールバー/メニューを実クリックする系＋journey」の無回帰。）

```bash
uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add docs/design.md
git commit -m "docs: design.md にアイコン節 (r5 Task 6)"
```

- [ ] **Step 3: 報告**（PR 作成・再同期・merge 後 docs はコントローラ — Task 7）

---

### Task 7: PR・再同期・docs（コントローラ実施）

- [ ] PR 作成（証拠: 前後スクショ・diff 限定確認・Icons カード・realgui/ゲート）→ CI → merge 判断はユーザー
- [ ] DesignSync 再同期（両テーマ各18ファイル — icons/overview.html が新規）
- [ ] merge 後 CLAUDE.md Phase 行更新の docs PR

---

## Self-Review メモ（プラン作成時に実施済み）

- spec §12 全項目に対応: 12.2（vendored+LICENSES+package-data=T1・icons.py+HiDPI+複数サイズ=T2・消費側=T3・Icons カード pure 方式=T4・currentColor 唯一の防波堤=T1 テスト）・12.3 レジストリ=T2・12.4 検証=T5/T6・12.5 非スコープ遵守。
- 現物確認済み: shell_actions.py 全文（style 変数・_add シグネチャ）・main_window.py:216-220・Lucide v1.24.0 の SVG 構造（`stroke="currentColor"`・@license ヘッダ）・LICENSE 文言（ISC・Copyright (c) 2026 Lucide Icons and Contributors）。
- 意図的判断: icon() の複数サイズ登録（16/20/24/32）はツールバー iconSize=24 への拡大ボケ防止（単サイズ登録だと QIcon がスケールしてぼやける）。**spec §12.2 の `size: int = 20` 引数はこの複数サイズ登録で不要化**（サイズ選択は QIcon が描画時に行う — spec の意図〔要求サイズで鮮明に描く〕を上位互換で充足）。禁止色 regex `#[0-9a-fA-F]{3,8}\b` は SVG 内 id/class に hex 風文字列が無い Lucide/Tabler では偽陽性なし（Task 1 Step 4 で GREEN 確認）。
