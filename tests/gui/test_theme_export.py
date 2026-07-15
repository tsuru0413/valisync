"""theme/export.py — css/json ビルダー (Layer A・純粋関数・決定性)。"""

from __future__ import annotations

import json

from valisync.gui.theme import export
from valisync.gui.theme.tokens import DARK


def test_css_var_name_kebab_and_index():
    assert (
        export.css_var_name("color", "plot_background") == "--vs-color-plot-background"
    )
    assert (
        export.css_var_name("color", "signal_palette", 3)
        == "--vs-color-signal-palette-3"
    )
    assert (
        export.css_var_name("spacing", "chip_grid_hspace")
        == "--vs-spacing-chip-grid-hspace"
    )


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


def test_inject_tokens_css_replaces_placeholder_and_fails_loudly():
    import pytest

    out = export.inject_tokens_css("<html><!-- @TOKENS_CSS --><body/></html>", DARK)
    assert "<style>" in out and "--vs-color-cursor-a" in out
    assert "@TOKENS_CSS" not in out
    with pytest.raises(ValueError):
        export.inject_tokens_css("<html>no placeholder</html>", DARK)


def test_build_token_cards_structure():
    cards = export.build_token_cards(DARK)
    assert set(cards) == {
        "tokens/colors.html",
        "tokens/spacing.html",
        "tokens/typography.html",
    }
    for path, html in cards.items():
        first_line = html.splitlines()[0]
        assert first_line == '<!-- @dsCard group="Tokens" -->', path
        assert "<!doctype html>" in html
        assert "@TOKENS_CSS" not in html  # 注入済み
    colors = cards["tokens/colors.html"]
    # 全色フィールド名が見本に載る (palette は index 付き)
    assert "cursor_a" in colors and "signal_palette-0" in colors
    assert "var(--vs-color-cursor-a)" in colors
