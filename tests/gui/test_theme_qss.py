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


def test_error_label_and_border_use_error_not_shared_triple():
    """error は delta_negative/close_hover と同値の三つ組 (DARK #f38ba8・spec §3)。

    値を分岐させたテーマで error_label/rename_error_border が error を参照し、
    同値の delta_negative/close_hover 側へ誤配線していないことを直接実証する。
    """
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, error=Color(1, 2, 3))
    )
    for style in (qss.error_label(alt), qss.rename_error_border(alt)):
        assert Color(1, 2, 3).hex in style
        # delta_negative/close_hover は未分岐のまま元値 (#f38ba8) — 三つ組のどちら
        # へ誤配線しても同じ値なので、この一箇所の不在確認が両方向を防ぐ。
        assert DARK.colors.delta_negative.hex not in style
        assert DARK.colors.close_hover.hex not in style


def test_readout_close_button_uses_close_hover_not_error():
    """close_hover は error と同値の三つ組の一員 (spec §3・error==close_hover)。

    error だけを分岐させたテーマで readout_close_button の hover 色が
    close_hover (未分岐の元値) のままであり、error 側へ誤配線していないことを
    直接実証する。
    """
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, error=Color(1, 2, 3))
    )
    s = qss.readout_close_button(alt)
    assert DARK.colors.close_hover.hex in s
    assert Color(1, 2, 3).hex not in s


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


def test_readout_panel_uses_surface_readout_panel_not_chrome():
    """surface_readout_panel は chrome_alternate_base と同値の別トークン。
    値を分岐させたテーマで readout_panel がどちらを参照するか直接実証する。"""
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK,
        colors=dataclasses.replace(DARK.colors, surface_readout_panel=Color(1, 2, 3)),
    )
    s = qss.readout_panel(alt)
    assert "#ReadoutPane" in s
    assert Color(1, 2, 3).hex in s
    assert DARK.colors.chrome_alternate_base.hex not in s


def test_delta_value_uses_given_delta_token_not_close_hover():
    """delta_negative は close_hover と同値の別トークン。値分岐で誤配線を実証。"""
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, delta_negative=Color(1, 2, 3))
    )
    s = qss.delta_value(alt.colors.delta_negative)
    assert Color(1, 2, 3).hex in s
    assert DARK.colors.close_hover.hex not in s
    # delta_positive は新規値: 生成関数が受け取った色をそのまま出す
    assert DARK.colors.delta_positive.hex in qss.delta_value(DARK.colors.delta_positive)


def test_line_edit_frame_contains_base_rule_focus_and_carveout():
    """QLineEdit 常時枠 (UX-49)。base / :focus / qt_spinbox_lineedit carve-out の3規則。"""
    s = qss.line_edit_frame(DARK)
    # base rule: QLineEdit { border: 1px solid chrome_frame; }
    assert "QLineEdit {" in s
    assert DARK.colors.chrome_frame.hex in s
    assert "border: 1px solid" in s
    # :focus rule: QLineEdit:focus { border: 1px solid chrome_highlight; }
    assert "QLineEdit:focus {" in s
    assert DARK.colors.chrome_highlight.hex in s
    # carve-out: QLineEdit#qt_spinbox_lineedit { border: none; }
    assert "QLineEdit#qt_spinbox_lineedit" in s
    assert "border: none" in s


def test_line_edit_frame_uses_chrome_frame_not_border_chip():
    """chrome_frame は border_chip と同値の別トークン (spec §4)。
    値を分岐させたテーマで line_edit_frame がどちらを参照するか直接実証する。"""
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, chrome_frame=Color(1, 2, 3))
    )
    s = qss.line_edit_frame(alt)
    assert Color(1, 2, 3).hex in s
    assert DARK.colors.border_chip.hex not in s


def test_line_edit_frame_uses_chrome_highlight_not_close_hover():
    """chrome_highlight は close_hover と同値の別トークン (DARK #89b4fa)。
    値を分岐させたテーマで line_edit_frame:focus がどちらを参照するか直接実証する。"""
    import dataclasses

    from valisync.gui.theme.tokens import Color

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, chrome_highlight=Color(1, 2, 3))
    )
    s = qss.line_edit_frame(alt)
    assert Color(1, 2, 3).hex in s
    assert DARK.colors.close_hover.hex not in s
