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
    """信号ドロップ強調枠 — overlay QFrame 用 (素の QWidget への QSS border は
    子に覆われ見えないため、view 本体でなく _drop_frame overlay に適用する)。"""
    return (
        "#drop_highlight_frame {"
        f" border: 2px solid {_t(t).colors.drop_highlight.hex};"
        " background: transparent; }"
    )


def area_drop_highlight(t: tokens.ThemeTokens | None = None) -> str:
    """OS ファイルドロップの破線枠 — overlay QFrame 用 (同上)。"""
    return (
        "#area_drop_highlight_frame {"
        f" border: 2px dashed {_t(t).colors.drop_highlight.hex};"
        " background: transparent; }"
    )


def rename_error_border(t: tokens.ThemeTokens | None = None) -> str:
    return f"border: 1px solid {_t(t).colors.error.hex};"


def error_label(t: tokens.ThemeTokens | None = None) -> str:
    return f"color: {_t(t).colors.error.hex};"


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


def readout_panel(t: tokens.ThemeTokens | None = None) -> str:
    """読み値ペインの面 (常設ドックテーブル背景)。"""
    return f"#ReadoutPane {{ background: {_t(t).colors.surface_readout_panel.hex}; }}"


def delta_value(color: tokens.Color) -> str:
    """Δ 値ラベルの符号着色 (delta_positive/delta_negative を呼び出し側が選ぶ)。"""
    return f"color: {color.hex};"


def line_edit_frame(t: tokens.ThemeTokens | None = None) -> str:
    """QLineEdit の常時枠 (UX-49) — Fusion 導出色は未フォーカス枠を描かず
    プレースホルダだけの行と区別できないため app QSS で明示する。
    QSpinBox 内部の qt_spinbox_lineedit は自枠の内側に二重枠を作るため除外
    (spec §1.2 carve-out)。"""
    c = _t(t).colors
    return (
        f"QLineEdit {{ border: 1px solid {c.chrome_frame.hex}; }}\n"
        f"QLineEdit:focus {{ border: 1px solid {c.chrome_highlight.hex}; }}\n"
        "QLineEdit#qt_spinbox_lineedit { border: none; }"
    )
