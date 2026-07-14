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
    return (
        f"color:{tt.colors.text_secondary.hex}; font-size:{tt.typography.small_px}px;"
    )


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
