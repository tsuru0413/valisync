"""theme/tokens.py — Color 検証・DARK 完全性・純粋性 (Layer A)。"""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from valisync.gui.theme.tokens import (
    DARK,
    LIGHT,
    Color,
    ThemeMode,
    active,
    resolve_theme,
    set_active,
)


def _srgb_to_linear(channel_255: int) -> float:
    c = channel_255 / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(c: Color) -> float:
    """WCAG 相対輝度 (sRGB 線形化込み)。"""
    return (
        0.2126 * _srgb_to_linear(c.r)
        + 0.7152 * _srgb_to_linear(c.g)
        + 0.0722 * _srgb_to_linear(c.b)
    )


def contrast_ratio(c1: Color, c2: Color) -> float:
    """WCAG コントラスト比 (相対輝度ベース・tests 側ヘルパ — spec §2.1)。"""
    l1, l2 = _relative_luminance(c1), _relative_luminance(c2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _all_named_colors(colors: object) -> list[tuple[str, Color]]:
    """dataclass 全 Color フィールドを (名前, 値) で列挙 (signal_palette は展開)。"""
    result: list[tuple[str, Color]] = []
    for f in dataclasses.fields(colors):  # type: ignore[arg-type]
        v = getattr(colors, f.name)
        if f.name == "signal_palette":
            for i, c in enumerate(v):
                result.append((f"signal_palette[{i}]", c))
        else:
            result.append((f.name, v))
    return result


def test_color_hex_roundtrip():
    # 任意の hex 値 (旧 matplotlib tab10 パレット由来の値から置換 — このテストは
    # Color.from_hex の丸め/構成要素検証で、パレット値と無関係な純ユーティリティ)。
    c = Color.from_hex("#4b6fa5")
    assert (c.r, c.g, c.b, c.a) == (75, 111, 165, 255)
    assert c.hex == "#4b6fa5"
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
            assert len(v) == 8 and all(isinstance(c, Color) for c in v)
        else:
            assert isinstance(v, Color), f.name


def test_dark_values_frozen_snapshot():
    """DARK 全値の意図的 test-lock — 再デザイン反復で値を変えたらこの golden も更新する (spec §3)。

    dataclasses.fields 反復で全フィールドを照合するため、トークンの追加・
    削除・値変更はすべてここで RED になる (部分ロックのすり抜け防止)。
    """
    golden_colors = {
        "plot_background": Color(0, 0, 0),
        "plot_foreground": Color(150, 150, 150),
        "signal_palette": (
            Color.from_hex("#56b4e9"),
            Color.from_hex("#e69f00"),
            Color.from_hex("#00c08b"),
            Color.from_hex("#f0e442"),
            Color.from_hex("#ff6e4a"),
            Color.from_hex("#d98bc0"),
            Color.from_hex("#9a8cff"),
            Color.from_hex("#c8c8c8"),
        ),
        "cursor_a": Color.from_hex("#f9e2af"),
        "cursor_b": Color.from_hex("#74c7ec"),
        "surface_chip": Color(17, 17, 27, 230),
        "border_chip": Color.from_hex("#45475a"),
        "text_primary": Color.from_hex("#cdd6f4"),
        "text_secondary": Color.from_hex("#9399b2"),
        "close_hover": Color.from_hex("#f38ba8"),
        "warning": Color.from_hex("#fab387"),
        "info": Color.from_hex("#7aa2f7"),
        "accent_active": Color.from_hex("#f59e0b"),
        "accent_active_dark": Color.from_hex("#b45309"),
        "grip_fill": Color.from_hex("#ffffff"),
        "drop_highlight": Color.from_hex("#94e2d5"),
        "axis_move_indicator": Color.from_hex("#f59e0b"),
        "axis_move_fill": Color(245, 158, 11, 60),
        "error": Color.from_hex("#f38ba8"),
        "busy_spinner": Color(120, 160, 255),
        "text_releasing": Color(128, 128, 128),
        "preview_curve": Color.from_hex("#4FC3F7"),
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
        "chrome_disabled_text": Color.from_hex("#6c7086"),
        "chrome_frame": Color.from_hex("#45475a"),
        # ステータス即値 (計測 IA・spec §2.4) — DARK は cursor_a/cursor_b と同値
        "chrome_cursor_a": Color.from_hex("#f9e2af"),
        "chrome_cursor_b": Color.from_hex("#74c7ec"),
        "surface_readout_panel": Color.from_hex("#1e1e2e"),
        "delta_negative": Color.from_hex("#f38ba8"),
        "delta_positive": Color.from_hex("#a6e3a1"),
    }
    actual_colors = {
        f.name: getattr(DARK.colors, f.name) for f in dataclasses.fields(DARK.colors)
    }
    assert actual_colors == golden_colors

    assert {
        f.name: getattr(DARK.spacing, f.name) for f in dataclasses.fields(DARK.spacing)
    } == {
        "chip_margins": (6, 5, 6, 5),
        "chip_vspace": 3,
        "chip_header_hspace": 6,
        "chip_grid_hspace": 8,
        "chip_grid_vspace": 2,
    }
    assert {
        f.name: getattr(DARK.radii, f.name) for f in dataclasses.fields(DARK.radii)
    } == {
        "chip": 5,
        "active_frame": 2,
    }
    assert {
        f.name: getattr(DARK.typography, f.name)
        for f in dataclasses.fields(DARK.typography)
    } == {"small_px": 10}
    assert DARK.grid_alpha == 150


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


def test_theme_mode_values_are_settings_strings():
    assert ThemeMode.LIGHT.value == "light"
    assert ThemeMode.DARK.value == "dark"
    assert ThemeMode.AUTO.value == "auto"


def test_resolve_theme_all_branches():
    """AUTO のみ os を参照・LIGHT/DARK は os 無視 (spec §11.2)。"""
    assert resolve_theme(ThemeMode.AUTO, os_prefers_dark=True) is DARK
    assert resolve_theme(ThemeMode.AUTO, os_prefers_dark=False) is LIGHT
    assert resolve_theme(ThemeMode.LIGHT, os_prefers_dark=True) is LIGHT
    assert resolve_theme(ThemeMode.LIGHT, os_prefers_dark=False) is LIGHT
    assert resolve_theme(ThemeMode.DARK, os_prefers_dark=True) is DARK
    assert resolve_theme(ThemeMode.DARK, os_prefers_dark=False) is DARK


def test_light_plot_pinned_tokens_match_dark():
    """プロット面据え置きトークンは両テーマ同値 (spec §11.4 — 黒キャンバス上の視認性)。"""
    pinned = [
        "plot_background",
        "plot_foreground",
        "signal_palette",
        "cursor_a",
        "cursor_b",
        "accent_active",
        "accent_active_dark",
        "grip_fill",
        "drop_highlight",
        "axis_move_indicator",
        "axis_move_fill",
        "preview_curve",
    ]
    for name in pinned:
        assert getattr(LIGHT.colors, name) == getattr(DARK.colors, name), name
    assert LIGHT.spacing is DARK.spacing
    assert LIGHT.radii is DARK.radii
    assert LIGHT.typography is DARK.typography
    assert LIGHT.grid_alpha == DARK.grid_alpha


def test_warning_info_contrast_ge_3_to_1_against_chrome_surfaces():
    """warning/info は非テキスト UI 部品用途 (WCAG 1.4.11) — chrome_base/chrome_window
    の双方・両テーマで ≥3:1 を要求する (spec §2.1)。"""
    for theme_name, theme in (("DARK", DARK), ("LIGHT", LIGHT)):
        for token_name in ("warning", "info"):
            fg = getattr(theme.colors, token_name)
            for surface_name in ("chrome_base", "chrome_window"):
                bg = getattr(theme.colors, surface_name)
                ratio = contrast_ratio(fg, bg)
                assert ratio >= 3.0, (
                    f"{theme_name}.{token_name} vs {surface_name}: {ratio:.2f} < 3.0"
                )


def test_warning_info_do_not_collide_with_existing_tokens():
    """新 2 トークンが既存の全トークン値と同値でないことの総当たり確認
    (同値が生じたら値分岐テストへ昇格する規約 — spec §2.1)。"""
    for theme_name, theme in (("DARK", DARK), ("LIGHT", LIGHT)):
        named = _all_named_colors(theme.colors)
        for new_name in ("warning", "info"):
            new_color = getattr(theme.colors, new_name)
            for existing_name, existing_color in named:
                if existing_name == new_name:
                    continue
                assert existing_color != new_color, (
                    f"{theme_name}.{new_name} == {existing_name} ({new_color.hex})"
                )


def test_light_values_frozen_snapshot():
    """LIGHT 全テーマ化トークンの意図的 test-lock (Latte 初期値・再デザイン反復で更新)。"""
    c = LIGHT.colors
    golden = {
        "surface_chip": Color(220, 224, 232, 230),
        "border_chip": Color.from_hex("#bcc0cc"),
        "text_primary": Color.from_hex("#4c4f69"),
        "text_secondary": Color.from_hex("#8c8fa1"),
        "close_hover": Color.from_hex("#d20f39"),
        "error": Color.from_hex("#c0392b"),
        "warning": Color.from_hex("#b0741a"),
        "info": Color.from_hex("#1a5fb4"),
        "busy_spinner": Color(30, 102, 245),
        "text_releasing": Color(128, 128, 128),
        "chrome_window": Color.from_hex("#eff1f5"),
        "chrome_window_text": Color.from_hex("#4c4f69"),
        "chrome_base": Color.from_hex("#e6e9ef"),
        "chrome_alternate_base": Color.from_hex("#eff1f5"),
        "chrome_text": Color.from_hex("#4c4f69"),
        "chrome_button": Color.from_hex("#ccd0da"),
        "chrome_button_text": Color.from_hex("#4c4f69"),
        "chrome_tooltip_base": Color.from_hex("#e6e9ef"),
        "chrome_tooltip_text": Color.from_hex("#4c4f69"),
        "chrome_highlight": Color.from_hex("#1e66f5"),
        "chrome_highlight_text": Color.from_hex("#dce0e8"),
        "chrome_placeholder": Color.from_hex("#8c8fa1"),
        "chrome_disabled_text": Color.from_hex("#9ca0b0"),
        "chrome_frame": Color.from_hex("#bcc0cc"),
        # ステータス即値 (計測 IA・spec §2.4) — LIGHT は明面 AA 濃色 (実測選定)
        "chrome_cursor_a": Color.from_hex("#8a6100"),
        "chrome_cursor_b": Color.from_hex("#106a8f"),
        "surface_readout_panel": Color.from_hex("#eff1f5"),
        "delta_negative": Color.from_hex("#d20f39"),
        "delta_positive": Color.from_hex("#40a02b"),
    }
    for name, expected in golden.items():
        assert getattr(c, name) == expected, name
