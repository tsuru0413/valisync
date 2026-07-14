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
