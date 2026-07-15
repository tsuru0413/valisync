"""テーマ適用フック (spec §4.3) — Qt/pyqtgraph 依存はここに隔離。

増分3: クロム = Fusion スタイル + トークン由来 QPalette (スパイクで確定)。
QPalette の 12 role を chrome_* トークンへ写像する。個別コンポーネントの
QSS 上書きが必要になったら qss.py に関数を足す (本増分では無し・YAGNI)。
冪等: 同値 set の繰り返しは安全 (Fusion は未適用時のみ setStyle)。
生成済みウィジェットの pg 設定へは遡及しないため build_main_window の先頭
(ウィジェット構築前) で呼ぶ。QApplication 不在の文脈では pg 設定のみ。
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from valisync.gui.theme import tokens


def build_palette(t: tokens.ThemeTokens) -> QPalette:
    """chrome_* トークン → QPalette (12 role の明示写像)。"""
    c = t.colors
    roles = QPalette.ColorRole
    mapping: list[tuple[QPalette.ColorRole, tokens.Color]] = [
        (roles.Window, c.chrome_window),
        (roles.WindowText, c.chrome_window_text),
        (roles.Base, c.chrome_base),
        (roles.AlternateBase, c.chrome_alternate_base),
        (roles.Text, c.chrome_text),
        (roles.Button, c.chrome_button),
        (roles.ButtonText, c.chrome_button_text),
        (roles.ToolTipBase, c.chrome_tooltip_base),
        (roles.ToolTipText, c.chrome_tooltip_text),
        (roles.Highlight, c.chrome_highlight),
        (roles.HighlightedText, c.chrome_highlight_text),
        (roles.PlaceholderText, c.chrome_placeholder),
    ]
    p = QPalette()
    for role, col in mapping:
        p.setColor(role, QColor(*col.rgba))
    return p


def apply_theme(t: tokens.ThemeTokens | None = None) -> None:
    tt = t if t is not None else tokens.active()
    pg.setConfigOption("background", tt.colors.plot_background.rgba)
    pg.setConfigOption("foreground", tt.colors.plot_foreground.rgba)
    app = QApplication.instance()
    if isinstance(app, QApplication):
        if app.style().objectName() != "fusion":
            app.setStyle("Fusion")
        app.setPalette(build_palette(tt))
