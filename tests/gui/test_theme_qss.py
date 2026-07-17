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
    assert "#drop_highlight_frame" in qss.panel_drop_highlight(DARK)
    assert "solid" in qss.panel_drop_highlight(DARK)
    assert "#area_drop_highlight_frame" in qss.area_drop_highlight(DARK)
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


def test_drop_highlight_builders_reference_drop_highlight_not_palette0():
    """drop_highlight は palette[0] と同値の別トークン (tokens.py の deliberate 分離)。

    DARK では両者が同値のため、値ベースの assert は誤配線 (builder が palette[0]
    を参照) を検出できない。値を分岐させたテーマで builder がどちらのトークンを
    消費するかを直接実証する (Task 11 デバッグテーマ検証の盲点補完)。
    """
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, drop_highlight=Color(1, 2, 3))
    )
    for style in (qss.panel_drop_highlight(alt), qss.area_drop_highlight(alt)):
        assert Color(1, 2, 3).hex in style
        assert DARK.colors.signal_palette[0].hex not in style


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
