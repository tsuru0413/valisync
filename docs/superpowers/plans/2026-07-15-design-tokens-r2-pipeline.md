# デザイントークン増分2「パイプライン構築」実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** トークン→エクスポート→撮影→Claude Design 同期の運用ループを成立させ、claude.ai/design 上に valisync の UI カタログ（Ground Truth / Tokens / Components / Meta）を立てる。

**Architecture:** 純粋関数のエクスポートコア `src/valisync/gui/theme/export.py`（css/json/見本カード/マニフェスト生成 — mypy/pytest ゲートに乗せる）＋薄い CLI `scripts/export_design_tokens.py`（パス・git SHA・ファイル IO）。カード HTML はテンプレート（`design/cards/`）へトークン CSS をビルド時にインライン注入（相対パス依存を排除）。Ground Truth は撮影 PNG を data URI で埋めた自己完結ラッパ HTML。初回同期は DesignSync（コントローラ実施 — 権限プロンプトがユーザーに出るため）。spec: [2026-07-15-design-token-pipeline-design.md](../specs/2026-07-15-design-token-pipeline-design.md) §5/§6。

**Tech Stack:** Python 3.12 / 標準ライブラリ（dataclasses・json・hashlib・base64）/ PySide6（撮影のみ）/ DesignSync（同期）

## Global Constraints

- **`theme/export.py` は PySide6/pyqtgraph を import 禁止**（tokens/qss と同じ pure Python 制約 — spec §4.1）。Qt 依存は撮影スクリプトのみ。
- **決定的出力**（spec §6）: 同じ tokens → バイト同一。全ファイル書き込みは `newline="\n"` 明示・JSON は `sort_keys=True, indent=2, ensure_ascii=False`・出力順は dataclass フィールド定義順。タイムスタンプ・乱数を出力に含めない（git SHA は引数で受ける）。
- **CSS 変数命名**: `--vs-<カテゴリ>-<フィールド名のkebab化>`（例 `--vs-color-plot-background`・palette は `--vs-color-signal-palette-0`〜`9`・`--vs-spacing-chip-margins: 6px 5px 6px 5px`・`--vs-radius-chip: 5px`・`--vs-font-small: 9px`・`--vs-grid-alpha: 60`）。色値は `Color.css()`（alpha 0-1）を使う。
- **カード HTML 規約**: 1行目に `<!-- @dsCard group="…" -->`（DesignSync のカード索引はこの1行目マーカーで構築される）。group は `Ground Truth` / `Tokens` / `Components` / `Proposals` / `Meta` のみ。2行目以降は自己完結の完全な HTML 文書（外部参照なし — トークン CSS は `<!-- @TOKENS_CSS -->` プレースホルダへの `<style>` 注入・画像は data URI）。
- **凍結セットの不変**: `capture_ui_screenshots.py` の既定5状態（01〜05）は凍結比較の契約 — 変更禁止。カタログ用の追加状態は `--catalog` フラグ配下のみ。
- **トークンは呼び出し時読み**: export 関数は `t: ThemeTokens` を引数で受ける（module レベルで DARK を焼き込まない）。
- **品質ゲート（コミット毎）**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過。`| tail` 禁止。
- **ブランチ**: `feature/design-tokens-r2-pipeline`（main d02f746 以降から分岐・Task 1 の前に作成）。
- **同期の一方向規約**: 真実は常にリポジトリ側。Claude Design 側での直接編集はしない。push 前に `get_project` で design-system 型を検証（spec §6）。

## GUI テスト分析（/gui-test-plan 判定）

- Task 1-5, 7: **非 GUI・可視挙動不変 → Layer A のみ・E2E 不要・標準 Red/Green**（純粋関数のエクスポート生成・文書）。
- Task 6（撮影 `--catalog` 拡張）: GUI を**駆動する**ツールだが GUI 自体は不変更。observable は生成 PNG そのもの（Task 9 の同期後に claude.ai/design 上で目視 — これが運用上の実 observable）。凍結セット（01-05）が不変であることは既存比較スクリプトで担保（Step 内に検証あり）。prod スケール不要（カタログは見た目の代表例であり規模非依存。実スケールの Ground Truth が欲しくなったら運用で `--data` 差し替え — 増分2 では YAGNI）。
- Task 9（初回同期）: 実 observable = claude.ai/design 上でカード群が閲覧できること（ユーザー確認）。

---

### Task 1: DARK 全域スナップショット（意図的 test-lock の完全化）

**Files:**
- Modify: `tests/gui/test_theme_tokens.py`（`test_dark_values_frozen_snapshot` を全フィールド網羅に拡張）

**Interfaces:**
- Consumes: `tokens.DARK` / `Color`（増分1）
- Produces: 全トークン値の変更が必ずこのテストを RED にする保証（増分3 の値変更は意図的にこの golden を更新する）

背景: 増分1 の snapshot は主要トークンのみで、未ロック側の事故編集が CI をすり抜ける（最終レビュー Minor 1）。`dataclasses.fields` 反復＋golden dict で全域ロックする。

- [ ] **Step 1: 失敗するテストを書く（既存 test を置換）**

`tests/gui/test_theme_tokens.py` の `test_dark_values_frozen_snapshot` を以下に**置換**（部分ロック版を削除し全域版へ）:

```python
def test_dark_values_frozen_snapshot():
    """DARK 全値の意図的 test-lock — 再デザイン反復で値を変えたらこの golden も更新する (spec §3)。

    dataclasses.fields 反復で全フィールドを照合するため、トークンの追加・
    削除・値変更はすべてここで RED になる (部分ロックのすり抜け防止)。
    """
    golden_colors = {
        "plot_background": Color(0, 0, 0),
        "plot_foreground": Color(150, 150, 150),
        "signal_palette": (
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
        "cursor_a": Color.from_hex("#f9e2af"),
        "cursor_b": Color.from_hex("#89b4fa"),
        "surface_chip": Color(17, 17, 27, 230),
        "border_chip": Color.from_hex("#45475a"),
        "text_primary": Color.from_hex("#cdd6f4"),
        "text_secondary": Color.from_hex("#7f849c"),
        "close_hover": Color.from_hex("#f38ba8"),
        "accent_active": Color.from_hex("#f59e0b"),
        "accent_active_dark": Color.from_hex("#b45309"),
        "grip_fill": Color.from_hex("#ffffff"),
        "drop_highlight": Color.from_hex("#1f77b4"),
        "axis_move_indicator": Color(255, 165, 0),
        "axis_move_fill": Color(255, 165, 0, 60),
        "error": Color.from_hex("#c0392b"),
        "busy_spinner": Color(120, 160, 255),
        "text_releasing": Color(128, 128, 128),
        "preview_curve": Color.from_hex("#4FC3F7"),
    }
    actual_colors = {f.name: getattr(DARK.colors, f.name) for f in dataclasses.fields(DARK.colors)}
    assert actual_colors == golden_colors

    assert {f.name: getattr(DARK.spacing, f.name) for f in dataclasses.fields(DARK.spacing)} == {
        "chip_margins": (6, 5, 6, 5),
        "chip_vspace": 3,
        "chip_header_hspace": 6,
        "chip_grid_hspace": 8,
        "chip_grid_vspace": 2,
    }
    assert {f.name: getattr(DARK.radii, f.name) for f in dataclasses.fields(DARK.radii)} == {
        "chip": 5,
        "active_frame": 2,
    }
    assert {
        f.name: getattr(DARK.typography, f.name) for f in dataclasses.fields(DARK.typography)
    } == {"small_px": 9}
    assert DARK.grid_alpha == 60
```

- [ ] **Step 2: RED を確認する sabotage → GREEN 確認**

Run: `uv run pytest tests/gui/test_theme_tokens.py::test_dark_values_frozen_snapshot -v`
Expected: PASS（値は現状どおりなので）。**検出力の確認**として、golden の `busy_spinner` を一時的に `Color(120, 160, 254)` に変えて FAIL を確認 → 戻す（このトークンは旧 snapshot が未ロックだった側 — 全域化の実証になる）。

- [ ] **Step 3: 品質ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add tests/gui/test_theme_tokens.py
git commit -m "test(theme): DARK snapshot を全フィールド網羅の golden へ拡張 (r2 Task 1)"
```

---

### Task 2: theme/export.py — tokens.css / tokens.json ビルダー

**Files:**
- Create: `src/valisync/gui/theme/export.py`
- Test: `tests/gui/test_theme_export.py`

**Interfaces:**
- Consumes: `tokens.ThemeTokens` / `Color`
- Produces（すべて純粋関数・文字列を返す）:
  - `css_var_name(category: str, field: str, index: int | None = None) -> str` — `--vs-color-plot-background` / `--vs-color-signal-palette-0` 形式
  - `build_css(t: ThemeTokens) -> str` — `:root { ... }`（末尾改行つき）
  - `build_json(t: ThemeTokens) -> str` — 決定的 JSON 文字列（末尾改行つき）

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_theme_export.py`:

```python
"""theme/export.py — css/json ビルダー (Layer A・純粋関数・決定性)。"""

from __future__ import annotations

import json

from valisync.gui.theme import export
from valisync.gui.theme.tokens import DARK


def test_css_var_name_kebab_and_index():
    assert export.css_var_name("color", "plot_background") == "--vs-color-plot-background"
    assert export.css_var_name("color", "signal_palette", 3) == "--vs-color-signal-palette-3"
    assert export.css_var_name("spacing", "chip_grid_hspace") == "--vs-spacing-chip-grid-hspace"


def test_build_css_contains_all_color_fields_and_values():
    css = export.build_css(DARK)
    assert css.startswith(":root {")
    assert css.endswith("}\n")
    # 色: Color.css() 形式 (alpha 0-1)
    assert "--vs-color-plot-background: rgba(0,0,0,1.000);" in css
    assert "--vs-color-surface-chip: rgba(17,17,27,0.902);" in css
    # palette 10 本が index 付きで展開される
    for i in range(10):
        assert f"--vs-color-signal-palette-{i}: rgba(" in css
    # spacing/radii/typography/grid_alpha
    assert "--vs-spacing-chip-margins: 6px 5px 6px 5px;" in css
    assert "--vs-spacing-chip-vspace: 3px;" in css
    assert "--vs-radius-chip: 5px;" in css
    assert "--vs-radius-active-frame: 2px;" in css
    assert "--vs-font-small: 9px;" in css
    assert "--vs-grid-alpha: 60;" in css


def test_build_css_is_deterministic():
    assert export.build_css(DARK) == export.build_css(DARK)


def test_build_json_roundtrips_all_tokens():
    data = json.loads(export.build_json(DARK))
    # 全色フィールドが hex/css/rgba を持つ
    assert data["colors"]["cursor_a"]["hex"] == "#f9e2af"
    assert data["colors"]["surface_chip"]["rgba"] == [17, 17, 27, 230]
    assert len(data["colors"]["signal_palette"]) == 10
    assert data["colors"]["signal_palette"][0]["hex"] == "#1f77b4"
    assert data["spacing"]["chip_margins"] == [6, 5, 6, 5]
    assert data["radii"]["chip"] == 5
    assert data["typography"]["small_px"] == 9
    assert data["grid_alpha"] == 60


def test_build_json_is_deterministic_and_sorted():
    s = export.build_json(DARK)
    assert s == export.build_json(DARK)
    assert s.endswith("\n")
    data = json.loads(s)
    assert list(data["colors"].keys()) == sorted(data["colors"].keys())


def test_export_module_is_qt_free():
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

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_theme_export.py -v`
Expected: FAIL（`ModuleNotFoundError: valisync.gui.theme.export`）

- [ ] **Step 3: 実装**

`src/valisync/gui/theme/export.py`:

```python
"""トークン→CSS/JSON エクスポートの純粋コア (spec §5・増分2).

pure Python (Qt import 禁止 — tokens/qss と同じ制約)。ファイル IO・
git SHA 取得は scripts/export_design_tokens.py (薄い CLI) が担う。
出力は決定的: 同じ ThemeTokens からバイト同一の文字列を返す (spec §6)。
"""

from __future__ import annotations

import dataclasses
import json

from valisync.gui.theme.tokens import Color, ThemeTokens


def css_var_name(category: str, field: str, index: int | None = None) -> str:
    base = f"--vs-{category}-{field.replace('_', '-')}"
    return base if index is None else f"{base}-{index}"


def _css_lines(t: ThemeTokens) -> list[str]:
    lines: list[str] = []
    for f in dataclasses.fields(t.colors):
        v = getattr(t.colors, f.name)
        if f.name == "signal_palette":
            lines.extend(
                f"  {css_var_name('color', f.name, i)}: {c.css()};"
                for i, c in enumerate(v)
            )
        else:
            lines.append(f"  {css_var_name('color', f.name)}: {v.css()};")
    for f in dataclasses.fields(t.spacing):
        v = getattr(t.spacing, f.name)
        value = " ".join(f"{n}px" for n in v) if isinstance(v, tuple) else f"{v}px"
        lines.append(f"  {css_var_name('spacing', f.name)}: {value};")
    for f in dataclasses.fields(t.radii):
        lines.append(f"  {css_var_name('radius', f.name)}: {getattr(t.radii, f.name)}px;")
    # typography.small_px は命名だけ特例 (--vs-font-small) — px 接尾辞をフィールド名から除く
    lines.append(f"  --vs-font-small: {t.typography.small_px}px;")
    lines.append(f"  --vs-grid-alpha: {t.grid_alpha};")
    return lines


def build_css(t: ThemeTokens) -> str:
    return ":root {\n" + "\n".join(_css_lines(t)) + "\n}\n"


def _color_json(c: Color) -> dict[str, object]:
    return {"rgba": list(c.rgba), "hex": c.hex, "css": c.css()}


def build_json(t: ThemeTokens) -> str:
    colors: dict[str, object] = {}
    for f in dataclasses.fields(t.colors):
        v = getattr(t.colors, f.name)
        colors[f.name] = (
            [_color_json(c) for c in v]
            if f.name == "signal_palette"
            else _color_json(v)
        )
    data = {
        "colors": colors,
        "spacing": {
            f.name: list(v) if isinstance(v := getattr(t.spacing, f.name), tuple) else v
            for f in dataclasses.fields(t.spacing)
        },
        "radii": {f.name: getattr(t.radii, f.name) for f in dataclasses.fields(t.radii)},
        "typography": {
            f.name: getattr(t.typography, f.name)
            for f in dataclasses.fields(t.typography)
        },
        "grid_alpha": t.grid_alpha,
    }
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
```

- [ ] **Step 4: GREEN 確認 → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_export.py -v
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/theme/export.py tests/gui/test_theme_export.py
git commit -m "feat(theme): export.py — tokens.css/tokens.json の決定的ビルダー (r2 Task 2)"
```

---

### Task 3: 見本カード（Tokens グループ）＋テンプレート注入

**Files:**
- Modify: `src/valisync/gui/theme/export.py`（カード生成関数を追加）
- Test: `tests/gui/test_theme_export.py`（追記）

**Interfaces:**
- Produces:
  - `inject_tokens_css(template: str, t: ThemeTokens) -> str` — テンプレート中の `<!-- @TOKENS_CSS -->` を `<style>\n{build_css(t)}</style>` に置換（プレースホルダ不在なら `ValueError` — loud-fail）
  - `build_token_cards(t: ThemeTokens) -> dict[str, str]` — `{"tokens/colors.html": ..., "tokens/spacing.html": ..., "tokens/typography.html": ...}`（各値は1行目 `<!-- @dsCard group="Tokens" -->` の完全な HTML）

- [ ] **Step 1: 失敗するテストを書く（test_theme_export.py へ追記）**

```python
def test_inject_tokens_css_replaces_placeholder_and_fails_loudly():
    import pytest

    out = export.inject_tokens_css("<html><!-- @TOKENS_CSS --><body/></html>", DARK)
    assert "<style>" in out and "--vs-color-cursor-a" in out
    assert "@TOKENS_CSS" not in out
    with pytest.raises(ValueError):
        export.inject_tokens_css("<html>no placeholder</html>", DARK)


def test_build_token_cards_structure():
    cards = export.build_token_cards(DARK)
    assert set(cards) == {"tokens/colors.html", "tokens/spacing.html", "tokens/typography.html"}
    for path, html in cards.items():
        first_line = html.splitlines()[0]
        assert first_line == '<!-- @dsCard group="Tokens" -->', path
        assert "<!doctype html>" in html
        assert "@TOKENS_CSS" not in html  # 注入済み
    colors = cards["tokens/colors.html"]
    # 全色フィールド名が見本に載る (palette は index 付き)
    assert "cursor_a" in colors and "signal_palette-0" in colors
    assert "var(--vs-color-cursor-a)" in colors
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_theme_export.py -v` — 新規2件 FAIL（AttributeError）

- [ ] **Step 3: 実装（export.py へ追記）**

```python
_TOKENS_CSS_PLACEHOLDER = "<!-- @TOKENS_CSS -->"


def inject_tokens_css(template: str, t: ThemeTokens) -> str:
    if _TOKENS_CSS_PLACEHOLDER not in template:
        raise ValueError(f"テンプレートに {_TOKENS_CSS_PLACEHOLDER} がない")
    return template.replace(_TOKENS_CSS_PLACEHOLDER, "<style>\n" + build_css(t) + "</style>")


def _card(group: str, title: str, body: str, t: ThemeTokens) -> str:
    template = (
        f'<!-- @dsCard group="{group}" -->\n'
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        "<!-- @TOKENS_CSS -->\n"
        "<style>body{background:#1e1e2e;color:#cdd6f4;font-family:sans-serif;"
        "margin:16px} table{border-collapse:collapse} td,th{padding:4px 10px;"
        "text-align:left;font-size:13px}</style>\n"
        f"</head><body>\n<h2>{title}</h2>\n{body}\n</body></html>\n"
    )
    return inject_tokens_css(template, t)


def _swatch_row(label: str, var: str, meta: str) -> str:
    return (
        f"<tr><td><div style='width:48px;height:24px;border:1px solid #555;"
        f"background:var({var})'></div></td>"
        f"<td><code>{label}</code></td><td><code>var({var})</code></td>"
        f"<td><code>{meta}</code></td></tr>"
    )


def build_token_cards(t: ThemeTokens) -> dict[str, str]:
    rows: list[str] = []
    for f in dataclasses.fields(t.colors):
        v = getattr(t.colors, f.name)
        if f.name == "signal_palette":
            rows.extend(
                _swatch_row(
                    f"signal_palette-{i}", css_var_name("color", f.name, i), c.hex
                )
                for i, c in enumerate(v)
            )
        else:
            rows.append(_swatch_row(f.name, css_var_name("color", f.name), v.hex))
    colors_body = "<table><tr><th></th><th>token</th><th>css var</th><th>hex</th></tr>" + "".join(rows) + "</table>"

    sp_rows = []
    for f in dataclasses.fields(t.spacing):
        v = getattr(t.spacing, f.name)
        sp_rows.append(f"<tr><td><code>{f.name}</code></td><td><code>{v}</code></td></tr>")
    for f in dataclasses.fields(t.radii):
        sp_rows.append(
            f"<tr><td><code>radius.{f.name}</code></td>"
            f"<td><code>{getattr(t.radii, f.name)}px</code></td></tr>"
        )
    sp_rows.append(f"<tr><td><code>grid_alpha</code></td><td><code>{t.grid_alpha}/255</code></td></tr>")
    spacing_body = "<table><tr><th>token</th><th>value</th></tr>" + "".join(sp_rows) + "</table>"

    typo_body = (
        f"<p style='font-size:var(--vs-font-small)'>--vs-font-small ({t.typography.small_px}px) — "
        "readout 列見出し等の縮小ラベル</p>"
        "<p>本文フォントは OS 既定 (トークン未導入・spec §1)</p>"
    )

    return {
        "tokens/colors.html": _card("Tokens", "Colors", colors_body, t),
        "tokens/spacing.html": _card("Tokens", "Spacing / Radii", spacing_body, t),
        "tokens/typography.html": _card("Tokens", "Typography", typo_body, t),
    }
```

- [ ] **Step 4: GREEN → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_export.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/export.py tests/gui/test_theme_export.py
git commit -m "feat(theme): 見本カード生成 (Tokens グループ) とテンプレート注入 (r2 Task 3)"
```

---

### Task 4: design/cards/ コンポーネントテンプレート＋design/proposals/ 新設

**Files:**
- Create: `design/cards/readout_chip.html` / `design/cards/affordances.html` / `design/cards/error_states.html`
- Create: `design/proposals/README.md`
- Test: `tests/gui/test_theme_export.py`（追記 — テンプレートの規約検証）

**Interfaces:**
- Produces: `design/cards/*.html` — 1行目 `<!-- @dsCard group="Components" -->`・`<!-- @TOKENS_CSS -->` プレースホルダ必須・`var(--vs-*)` のみで色指定（生 hex 禁止）。Task 5 の CLI が `inject_tokens_css` で注入して `design_export/cards/` へ出力する。

- [ ] **Step 1: テンプレート規約のテストを書く（test_theme_export.py へ追記）**

```python
def test_design_card_templates_follow_conventions():
    """design/cards/*.html: マーカー1行目・プレースホルダ必須・生 hex 禁止 (var(--vs-*) のみ)。"""
    import re
    from pathlib import Path

    cards_dir = Path(__file__).resolve().parents[2] / "design" / "cards"
    templates = sorted(cards_dir.glob("*.html"))
    assert templates, "design/cards/ にテンプレートが無い"
    for path in templates:
        text = path.read_text(encoding="utf-8")
        assert text.splitlines()[0] == '<!-- @dsCard group="Components" -->', path.name
        assert "<!-- @TOKENS_CSS -->" in text, path.name
        # 生 hex/rgba 禁止 — 色は必ず var(--vs-*) 経由 (トークン変更に自動追従させる)。
        # OS 既定 chrome の再現用グレーのみ 3桁 hex (#eee 等) を許容。
        assert not re.search(r"#[0-9a-fA-F]{6}\b|rgba?\(", text), path.name
        # 注入が通ることも検証
        out = export.inject_tokens_css(text, DARK)
        assert "--vs-color-plot-background" in out
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_theme_export.py::test_design_card_templates_follow_conventions -v`
Expected: FAIL（`design/cards/ にテンプレートが無い`）

- [ ] **Step 3: テンプレート3枚を作成**

`design/cards/readout_chip.html`:

```html
<!-- @dsCard group="Components" -->
<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>Cursor Readout チップ</title>
<!-- @TOKENS_CSS -->
<style>
  body { background: var(--vs-color-plot-background); margin: 24px; font-family: sans-serif; }
  .chip {
    display: inline-block;
    background: var(--vs-color-surface-chip);
    border: 1px solid var(--vs-color-border-chip);
    border-radius: var(--vs-radius-chip);
    padding: 5px 6px;
    color: var(--vs-color-text-primary);
    font-size: 13px;
  }
  .chip table { border-collapse: collapse; }
  .chip td { padding: 1px 8px 1px 0; }
  .dot-a { color: var(--vs-color-cursor-a); }
  .dot-b { color: var(--vs-color-cursor-b); }
  .head { display: flex; gap: 6px; margin-bottom: 3px; }
  .close { margin-left: auto; color: var(--vs-color-text-primary); cursor: pointer; }
  .close:hover { color: var(--vs-color-close-hover); }
  .colhead, .unit { color: var(--vs-color-text-secondary); font-size: var(--vs-font-small); }
  .sw { display: inline-block; width: 10px; height: 10px; }
  .val { text-align: right; }
</style>
</head><body>
<div class="chip">
  <div class="head"><span><span class="dot-a">●</span> 3.000 s&nbsp;&nbsp;<span class="dot-b">●</span> 6.000 s · <b>Δt 3.000 s</b> ─ 線形補間</span><span class="close">✕</span></div>
  <table>
    <tr><td></td><td></td><td class="colhead val">A値</td><td class="colhead val">Δy</td><td class="colhead val">mean</td></tr>
    <tr><td><span class="sw" style="background:var(--vs-color-signal-palette-0)"></span></td><td>EngineSpeed <span class="unit">[rpm]</span></td><td class="val">1425.000000</td><td class="val">+250.000000</td><td class="val">1391.2</td></tr>
    <tr><td><span class="sw" style="background:var(--vs-color-signal-palette-1)"></span></td><td>VehSpd <span class="unit">[km/h]</span></td><td class="val">72.000000</td><td class="val">-3.600000</td><td class="val">58.8</td></tr>
  </table>
</div>
</body></html>
```

`design/cards/affordances.html`:

```html
<!-- @dsCard group="Components" -->
<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>アクティブ/ドロップ アフォーダンス</title>
<!-- @TOKENS_CSS -->
<style>
  body { background: var(--vs-color-plot-background); color: var(--vs-color-text-primary); margin: 24px; font-family: sans-serif; font-size: 13px; }
  .panel { width: 320px; height: 120px; margin: 12px 0; position: relative; background: var(--vs-color-plot-background); }
  .active-frame { border: 1px solid var(--vs-color-accent-active); border-radius: var(--vs-radius-active-frame); }
  .panel-drop { border: 2px solid var(--vs-color-drop-highlight); }
  .area-drop { border: 2px dashed var(--vs-color-drop-highlight); }
  .grip { position: absolute; top: -4px; left: 140px; width: 28px; height: 8px; background: var(--vs-color-grip-fill); border: 1px solid var(--vs-color-accent-active-dark); border-radius: 3px; }
  .move-line { position: absolute; left: 60px; top: 0; width: 3px; height: 100%; background: var(--vs-color-axis-move-indicator); }
  .move-fill { position: absolute; left: 60px; top: 0; width: 80px; height: 100%; background: var(--vs-color-axis-move-fill); }
  label { display: block; margin-top: 16px; color: var(--vs-color-text-secondary); }
</style>
</head><body>
<label>アクティブパネル枠 + 軸グリップ (accent_active / grip_fill / accent_active_dark)</label>
<div class="panel active-frame"><div class="grip"></div></div>
<label>パネルへの信号ドロップ強調 (drop_highlight・実線)</label>
<div class="panel panel-drop"></div>
<label>エリアへのファイルドロップ強調 (drop_highlight・破線)</label>
<div class="panel area-drop"></div>
<label>軸移動インジケータ (axis_move_indicator / axis_move_fill=alpha60)</label>
<div class="panel"><div class="move-fill"></div><div class="move-line"></div></div>
</body></html>
```

`design/cards/error_states.html`:

```html
<!-- @dsCard group="Components" -->
<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>エラー/ステータス表示</title>
<!-- @TOKENS_CSS -->
<style>
  body { background: #eee; color: #222; margin: 24px; font-family: sans-serif; font-size: 13px; }
  .dialog { background: #fff; border: 1px solid #bbb; width: 360px; padding: 12px; margin: 12px 0; }
  .error-label { color: var(--vs-color-error); }
  .rename-error { border: 1px solid var(--vs-color-error); padding: 2px 6px; width: 120px; }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--vs-color-busy-spinner); border-top-color: transparent; border-radius: 50%; }
  .releasing { color: var(--vs-color-text-releasing); }
  .preview { color: var(--vs-color-preview-curve); }
  label { display: block; margin-top: 14px; color: #666; }
</style>
</head><body>
<p>注: ダイアログ chrome は OS 既定 (ライト・増分3で統一検討)。ここではトークン適用箇所のみ再現。</p>
<label>ダイアログのエラーラベル (error)</label>
<div class="dialog"><span class="error-label">少なくとも1信号を選択してください</span></div>
<label>タブ改名エディタの範囲外エラー枠 (error)</label>
<div class="dialog"><input class="rename-error" value="長すぎる名前..."></div>
<label>解放中スピナー (busy_spinner) と行グレーアウト (text_releasing)</label>
<div class="dialog"><span class="spinner"></span> <span class="releasing">closing_file.mf4 (解放中)</span></div>
<label>信号プレビュー線 (preview_curve)</label>
<div class="dialog" style="background:var(--vs-color-plot-background)"><svg width="320" height="60"><polyline points="0,50 40,20 80,40 120,10 160,35 200,15 240,45 280,25 320,30" fill="none" stroke="var(--vs-color-preview-curve)" stroke-width="1"/></svg></div>
</body></html>
```

`design/proposals/README.md`:

```markdown
# Proposals — 検討中のデザイン改善案カード

運用ループ (docs/design.md) の手順1で、改善案 A/B をここに HTML カードとして作成して
push し、claude.ai/design の Proposals グループで比較する。採用されたら tokens.py へ
反映し、このディレクトリと Claude Design 側の両方からカードを削除する。

カード規約: 1行目 `<!-- @dsCard group="Proposals" -->`・`<!-- @TOKENS_CSS -->` 注入
プレースホルダ・**提案で変える値のみ**生値で書き、他は `var(--vs-*)` を参照する
(現行との差分が読み取れるように)。
```

- [ ] **Step 4: GREEN 確認 → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_export.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add design/ tests/gui/test_theme_export.py
git commit -m "feat(design): Components カードテンプレート3枚と proposals/ 規約 (r2 Task 4)"
```

（注: `error_states.html` の `.dialog` 等の固定グレーは「OS 既定 chrome の再現」でありトークン対象外 — Step 1 のテストは **6桁 hex と rgba(** を禁止し、chrome 再現用の 3桁 hex（`#eee`/`#222`/`#fff`/`#bbb`/`#666`）のみ許容する。増分3 でクロムがトークン化されたらテンプレートも追従させる。）

---

### Task 5: CLI — scripts/export_design_tokens.py（Ground Truth ラッパ＋マニフェスト込み）

**Files:**
- Create: `scripts/export_design_tokens.py`
- Modify: `src/valisync/gui/theme/export.py`（`build_ground_truth_card` / `build_manifest` を追加）
- Test: `tests/gui/test_theme_export.py`（追記）

**Interfaces:**
- Consumes: Task 2/3 のビルダー・`design/cards/*.html`・`design_export/screenshots_catalog/*.png`（Task 6 が生成）
- Produces:
  - `export.build_ground_truth_card(name: str, png_bytes: bytes) -> str` — data URI 埋め込みの自己完結カード（group="Ground Truth"）
  - `export.build_manifest(sha: str, tokens_json: str, paths: list[str]) -> str` — group="Meta" カード（git SHA・tokens.json の sha256・カード一覧）
  - CLI: `uv run python scripts/export_design_tokens.py [--out design_export] [--screenshots design_export/screenshots_catalog] [--sha <git-sha>]` → `design_export/` に `tokens.css` / `tokens.json` / `tokens/*.html` / `cards/*.html` / `ground_truth/*.html` / `meta/manifest.html` を決定的に出力

- [ ] **Step 1: 失敗するテストを書く（test_theme_export.py へ追記）**

```python
def test_build_ground_truth_card_embeds_png_as_data_uri():
    png = b"\x89PNG\r\n\x1a\nfakebytes"
    html = export.build_ground_truth_card("02_plotted", png)
    assert html.splitlines()[0] == '<!-- @dsCard group="Ground Truth" -->'
    assert "data:image/png;base64," in html
    import base64

    assert base64.b64encode(png).decode("ascii") in html
    assert "02_plotted" in html


def test_build_manifest_records_sha_hash_and_paths():
    import hashlib

    tokens_json = export.build_json(DARK)
    html = export.build_manifest("abc1234", tokens_json, ["cards/readout_chip.html", "tokens/colors.html"])
    assert html.splitlines()[0] == '<!-- @dsCard group="Meta" -->'
    assert "abc1234" in html
    assert hashlib.sha256(tokens_json.encode("utf-8")).hexdigest() in html
    assert "cards/readout_chip.html" in html


def test_cli_writes_full_bundle(tmp_path):
    """CLI の統合テスト — 一時 out dir へ全成果物を決定的に出力する。"""
    import subprocess
    import sys
    from pathlib import Path

    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "01_welcome.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    out = tmp_path / "export"
    repo = Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        str(repo / "scripts" / "export_design_tokens.py"),
        "--out", str(out),
        "--screenshots", str(shots),
        "--sha", "deadbee",
    ]
    r1 = subprocess.run(cmd, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    for rel in [
        "tokens.css",
        "tokens.json",
        "tokens/colors.html",
        "tokens/spacing.html",
        "tokens/typography.html",
        "cards/readout_chip.html",
        "cards/affordances.html",
        "cards/error_states.html",
        "ground_truth/01_welcome.html",
        "meta/manifest.html",
    ]:
        assert (out / rel).is_file(), rel
    # 決定性: 再実行でバイト同一
    before = {p: p.read_bytes() for p in out.rglob("*.html")}
    r2 = subprocess.run(cmd, capture_output=True, text=True)
    assert r2.returncode == 0
    assert before == {p: p.read_bytes() for p in out.rglob("*.html")}
    # cards は注入済み (プレースホルダが残っていない)
    card = (out / "cards" / "readout_chip.html").read_text(encoding="utf-8")
    assert "@TOKENS_CSS" not in card and "--vs-color-surface-chip" in card
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_theme_export.py -v` — 新規3件 FAIL

- [ ] **Step 3: export.py へ追記**

```python
def build_ground_truth_card(name: str, png_bytes: bytes) -> str:
    import base64

    uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    return (
        '<!-- @dsCard group="Ground Truth" -->\n'
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">\n'
        f"<title>{name}</title>\n"
        "<style>body{margin:0;background:#111}img{max-width:100%;display:block}</style>\n"
        f"</head><body>\n<img alt=\"{name}\" src=\"{uri}\">\n</body></html>\n"
    )


def build_manifest(sha: str, tokens_json: str, paths: list[str]) -> str:
    import hashlib

    digest = hashlib.sha256(tokens_json.encode("utf-8")).hexdigest()
    items = "".join(f"<li><code>{p}</code></li>" for p in sorted(paths))
    return (
        '<!-- @dsCard group="Meta" -->\n'
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8"><title>Sync Manifest</title>\n'
        "<style>body{font-family:sans-serif;font-size:13px;margin:16px}</style>\n"
        "</head><body>\n<h2>Sync Manifest</h2>\n"
        f"<p>git SHA: <code>{sha}</code></p>\n"
        f"<p>tokens.json sha256: <code>{digest}</code></p>\n"
        f"<ul>{items}</ul>\n</body></html>\n"
    )
```

- [ ] **Step 4: CLI を作成**

`scripts/export_design_tokens.py`:

```python
"""デザイントークンのエクスポート CLI (spec §5・増分2).

theme/export.py (純粋コア) の出力を design_export/ へ書き出す薄い層。
使い方:
    uv run python scripts/export_design_tokens.py
    (--out design_export --screenshots design_export/screenshots_catalog が既定。
     --sha 省略時は git rev-parse --short HEAD)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "design_export")
    parser.add_argument(
        "--screenshots", type=Path, default=REPO / "design_export" / "screenshots_catalog"
    )
    parser.add_argument("--sha", default=None)
    args = parser.parse_args()

    from valisync.gui.theme import export
    from valisync.gui.theme.tokens import DARK

    sha = args.sha or subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO
    ).stdout.strip()

    written: list[str] = []

    _write(args.out / "tokens.css", export.build_css(DARK))
    written.append("tokens.css")
    tokens_json = export.build_json(DARK)
    _write(args.out / "tokens.json", tokens_json)
    written.append("tokens.json")

    for rel, html in export.build_token_cards(DARK).items():
        _write(args.out / rel, html)
        written.append(rel)

    cards_dir = REPO / "design" / "cards"
    for tpl in sorted(cards_dir.glob("*.html")):
        html = export.inject_tokens_css(tpl.read_text(encoding="utf-8"), DARK)
        _write(args.out / "cards" / tpl.name, html)
        written.append(f"cards/{tpl.name}")
    for tpl in sorted((REPO / "design" / "proposals").glob("*.html")):
        html = export.inject_tokens_css(tpl.read_text(encoding="utf-8"), DARK)
        _write(args.out / "proposals" / tpl.name, html)
        written.append(f"proposals/{tpl.name}")

    if args.screenshots.is_dir():
        for png in sorted(args.screenshots.glob("*.png")):
            html = export.build_ground_truth_card(png.stem, png.read_bytes())
            _write(args.out / "ground_truth" / f"{png.stem}.html", html)
            written.append(f"ground_truth/{png.stem}.html")
    else:
        print(f"screenshots 不在: {args.screenshots} — Ground Truth はスキップ", file=sys.stderr)

    _write(args.out / "meta" / "manifest.html", export.build_manifest(sha, tokens_json, written))
    written.append("meta/manifest.html")
    print(f"exported {len(written)} files -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: GREEN 確認 → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_export.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/export.py scripts/export_design_tokens.py tests/gui/test_theme_export.py
git commit -m "feat(design): エクスポート CLI — バンドル一式+Ground Truth ラッパ+マニフェスト (r2 Task 5)"
```

---

### Task 6: 撮影スクリプトのカタログ拡張（--catalog）

**Files:**
- Modify: `scripts/capture_ui_screenshots.py`

**Interfaces:**
- Consumes: `ExportCsvDialog(app_vm, initial_selected: set[str])`＋`_validate()`（エラー表示）/ `CsvFormatDetector().detect(path) -> DetectedFormat`＋`CsvFormatDialog(detected)` / `window.signal_preview_window.show_signal(key)`（すべて現行 API — 確認済み）
- Produces: `--catalog` 指定時、既定5状態に加えて `06_export_dialog_error.png` / `07_csv_format_dialog.png` / `08_signal_preview.png` を出力。**既定5状態（01-05）は不変**。

- [ ] **Step 1: argparse に `--catalog` を追加**

```python
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="カタログ用の追加状態 (ダイアログ/プレビュー) も撮影 (凍結比較の既定5状態は不変)",
    )
```

- [ ] **Step 2: `05_affordances` の grab 後（`window.close()` の前）に追加**

```python
    if args.catalog:
        # アフォーダンス強制表示を解除してからカタログ状態へ
        panel_view._active_frame.setVisible(False)
        panel_view._set_drop_highlight(False)
        window.graph_area_view._set_drop_highlight(False)
        settle()

        # --- 06: CSV エクスポートダイアログ (エラーラベル表示状態) -------------
        from valisync.gui.views.export_csv_dialog import ExportCsvDialog

        dlg = ExportCsvDialog(window.app_vm, initial_selected=set())
        dlg._validate()  # 撮影ツールとしての private 利用: エラー行を可視化
        dlg.show()
        settle()
        dlg.grab().save(str(args.out / "06_export_dialog_error.png"))
        print("captured 06_export_dialog_error.png")
        dlg.close()

        # --- 07: CSV フォーマット確認ダイアログ --------------------------------
        from valisync.core.loaders.csv_format_detector import CsvFormatDetector
        from valisync.gui.views.csv_format_dialog import CsvFormatDialog

        detected = CsvFormatDetector().detect(csv)
        fmt_dlg = CsvFormatDialog(detected)
        fmt_dlg.show()
        settle()
        fmt_dlg.grab().save(str(args.out / "07_csv_format_dialog.png"))
        print("captured 07_csv_format_dialog.png")
        fmt_dlg.close()

        # --- 08: 信号プレビュー窓 ----------------------------------------------
        window.signal_preview_window.show_signal(keys[0])
        settle()
        window.signal_preview_window.grab().save(str(args.out / "08_signal_preview.png"))
        print("captured 08_signal_preview.png")
        window.signal_preview_window.close()
```

（`csv`・`keys`・`panel_view` は既存コードの同名ローカル変数。`show_signal` は `app_vm.active_file_key` に依存する — 既定の load 経路で active になっているため `keys[0]` で描画される。）

- [ ] **Step 3: 実行検証（実ディスプレイ）＋凍結セット不変の確認**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog --catalog
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_catalog
```
Expected: catalog dir に PNG 8 枚。**比較は exit 2**（ファイル集合不一致 — 06-08 が余るため）だが、これは想定どおり。凍結セット不変の正しい検証は:
```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_freezecheck
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_freezecheck
```
Expected: `--catalog` なしの既定5状態が**全 OK 完全一致 exit 0**（フラグ追加が既定経路を変えていない証拠）。
さらに 06/07/08 の PNG を Read で開き、ダイアログのエラーラベル・フォーマット確認表・プレビュー線が写っていることを目視確認（文字が□でないこと）。

- [ ] **Step 4: 品質ゲート → コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add scripts/capture_ui_screenshots.py
git commit -m "feat(design): 撮影スクリプトに --catalog (ダイアログ/プレビュー3状態) を追加 (r2 Task 6)"
```

---

### Task 7: docs/design.md（デザインコンセプト＋運用手順）

**Files:**
- Create: `docs/design.md`
- Modify: `CLAUDE.md`（「情報の探し方」表の 2 行目 `docs/<topic>.md` 列挙に `design` を追加 — `product` / `development` / ... の並びへ1語追加のみ）

**Interfaces:**
- Consumes: spec §5 の運用ループ・増分1/2 の実装名

- [ ] **Step 1: docs/design.md を作成**

```markdown
# valisync デザインシステム

一次情報源。**値の真実は `src/valisync/gui/theme/tokens.py`（DARK）**であり、本書は
原則・トークンの意味・運用手順を持つ（値は書かない — 乖離を作らないため）。
設計の経緯は [spec](superpowers/specs/2026-07-15-design-token-pipeline-design.md)。

## 原則

1. **意味名トークン** — 役割ベース（`surface_chip`・`accent_active`）で命名し、値名
   （`catppuccin_blue` 等）にしない。役割が違えば値が同じでも別トークン
   （例: `drop_highlight` と `signal_palette[0]`）。
2. **単一の真実・一方向フロー** — tokens.py → コード/エクスポート/カタログ。
   Claude Design 側での直接編集はしない。
3. **色の直書き禁止** — `tests/gui/test_theme_guard.py` が CI で検出する。QSS/リッチ
   テキスト断片は `theme/qss.py` の生成関数を追加して使う。
4. **呼び出し時読み** — `tokens.active()` を使用時に読む。module 定数・default 引数へ
   束縛しない（デバッグテーマ・将来のテーマ切替が効かなくなる）。
5. **ダーク単一（拡張可能構造）** — 値セットは DARK のみ。ライトは将来 ThemeTokens
   インスタンス追加で対応（切替 UI は未実装・YAGNI）。

## トークンの意味（カテゴリ概要）

| カテゴリ | 代表トークン | 使い分け |
|---|---|---|
| プロット面 | `plot_background` / `plot_foreground` | pyqtgraph 全体（背景・軸/文字） |
| 信号 | `signal_palette`（10色巡回） | 曲線の自動色。ユーザー指定色はトークン外 |
| カーソル | `cursor_a` / `cursor_b` | プロット線と readout マーカーで共有 |
| readout チップ | `surface_chip` / `border_chip` / `text_primary` / `text_secondary` / `close_hover` | フロート表の面・枠・文字階層 |
| アクティブ強調 | `accent_active` / `accent_active_dark` / `grip_fill` | アクティブ軸/パネルの amber 系 |
| インタラクション | `drop_highlight` / `axis_move_indicator` / `axis_move_fill` | D&D・軸移動の一時表示 |
| フィードバック | `error` / `busy_spinner` / `text_releasing` / `preview_curve` | 検証エラー・非同期状態 |
| 寸法 | `spacing.*` / `radii.*` / `typography.small_px` / `grid_alpha` | チップ余白・角丸・縮小ラベル・グリッド透過 |

## 運用ループ（1 反復 = 1 feature ブランチ）

1. **検討**: claude.ai/design のプロジェクト「valisync-design」でカードを見ながら議論。
   改善案は `design/proposals/` に案A/案B カードを作り push して比較
   （規約は `design/proposals/README.md`）。
2. **承認**: 採用案を決める。
3. **反映**: `tokens.py` の値変更＋`tests/gui/test_theme_tokens.py` の golden 更新＋本書
   に決定理由を追記。クロム系の初回だけ `apply.py` の構造作業を伴う（spec §8 増分3）。
4. **再生成**:
   ```bash
   uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog --catalog
   uv run python scripts/export_design_tokens.py
   ```
   → DesignSync で増分同期（`list_files` でリモートと突合 → `finalize_plan` →
   `write_files`。常にコンポーネント単位・丸ごと置換しない・push 前に `get_project` で
   design-system 型を検証）。
5. **照合**: Ground Truth（新スクショ）と Components（意図したデザイン）を見比べ、
   「意図した変化のみか」を確認。採用済み Proposals はローカル・リモート両方から削除。

## 検証の道具

- **凍結比較**: `scripts/compare_screenshots.py BASELINE AFTER`（exit 0=完全一致）。
  リファクタ（値不変）の証明に使う。
- **デバッグテーマ**: `capture_ui_screenshots.py --debug-theme`（全トークン相異値）。
  役割写像（どのトークンがどこに着地するか）の目視検証。同値別トークンの誤配線は
  ピクセル比較で原理的に不可視 — 値分岐テーマのテストで補完する
  （memory: gui_freeze_tokenization_verification_pattern）。

## Do / Don't

- Do: 新しい色が必要になったら tokens.py に意味名で追加 → qss.py に生成関数 → golden 更新。
- Do: カードテンプレートの色は `var(--vs-*)` のみ（`tests/gui/test_theme_export.py` が検証）。
- Don't: view/VM に hex・`rgba(`・`QColor(リテラル)` を書く（ガードテストが落とす）。
- Don't: Claude Design 上でカードを直接編集する（次回 push で消える — 真実はリポジトリ）。
```

- [ ] **Step 2: CLAUDE.md の1箇所を更新**

「情報の探し方」表の `docs/<topic>.md`（`product` / `development` / `structure` / `policies` / `workflow`）の列挙に `design` を追加:
`（`product` / `development` / `structure` / `policies` / `workflow` / `design`）`

- [ ] **Step 3: 品質ゲート → コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add docs/design.md CLAUDE.md
git commit -m "docs: design.md — デザイン原則・トークン意味・運用ループの一次情報源 (r2 Task 7)"
```

---

### Task 8: 品質ゲート・PR

**Files:** なし（検証と PR のみ）

- [ ] **Step 1: 全ゲート＋実バンドル生成の通し確認**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog --catalog   # 実ディスプレイ
uv run python scripts/export_design_tokens.py
```
Expected: 全 exit 0・`design_export/` に tokens.css/json＋カード一式＋ground_truth 8 枚＋manifest。

- [ ] **Step 2: `/gui-verify`（GUI 実装変更なし — ツール/文書のみの確認）→ PR 作成**

```bash
git push -u origin feature/design-tokens-r2-pipeline
gh pr create --title "feat(design): エクスポート/カタログ/運用文書 — デザインパイプライン増分2" --body "<spec/プラン/バンドル内容/ゲート結果>"
gh pr checks <num> --watch
```

---

### Task 9: 初回同期（コントローラ実施 — サブエージェント不可）

**Files:** なし（DesignSync 呼び出しのみ。権限プロンプトがユーザーに出るためメインセッションで行う）

- [ ] **Step 1**: `DesignSync list_projects` — 既存の design-system プロジェクトを確認。無ければ `create_project name="valisync-design"`。
- [ ] **Step 2**: `get_project` で `type: PROJECT_TYPE_DESIGN_SYSTEM` を検証（spec §6 — 通常プロジェクトへの push はデザインシステムにならない）。
- [ ] **Step 3**: `list_files` でリモート現状を突合（初回は空のはず）。
- [ ] **Step 4**: `finalize_plan` — writes=`["tokens.css","tokens.json","tokens/**/*.html","cards/**/*.html","ground_truth/**/*.html","meta/manifest.html"]`・`localDir=<repo>/design_export`。
- [ ] **Step 5**: `write_files` — 全ファイルを `localPath` で upload（内容はコンテキストに載せない）。
- [ ] **Step 6**: ユーザーに claude.ai/design での閲覧確認を依頼（カードグループ Ground Truth/Tokens/Components/Meta が並ぶこと）— これが増分2 の受け入れ。

---

## Self-Review メモ（プラン作成時に実施済み）

- spec §5（データフロー・カードグループ・同期状態管理・運用ループ）→ Task 3/4/5/7/9、§6（決定的出力・get_file 256KiB cap→data URI 採用・ratchet）→ Task 2/5、§8 増分2 の全項目（エクスポータ・design/cards・撮影カタログ拡張・同期マニフェスト・docs/design.md・初回同期）に対応タスクあり。最終レビュー推奨（DARK 全域スナップショット）= Task 1。
- API 実在確認済み: `ExportCsvDialog(app_vm, initial_selected)`（:61）＋`_validate()`（:216）・`CsvFormatDetector().detect()`（csv_format_detector.py:78）・`CsvFormatDialog(detected)`（:32）・`MainWindow.signal_preview_window.show_signal(key)`（main_window.py:216-220・signal_preview_window.py:58）。
- 意図的な設計判断: Ground Truth は data URI 埋め込み（相対パス解決への依存を排除・get_file 256KiB cap は read-back のみの制約なので照合はローカル成果物で行う）。エクスポートコアを `theme/export.py` に置くのは mypy/pytest ゲートに乗せるため（scripts/ は薄い IO 層）。
