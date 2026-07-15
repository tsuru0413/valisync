"""theme/apply.py — pg 設定注入・冪等・build_main_window 配線 (Layer A/B)。"""

from __future__ import annotations

import pyqtgraph as pg

from valisync.gui.theme.apply import apply_theme
from valisync.gui.theme.tokens import DARK


def test_apply_sets_pg_options_idempotently(qapp):
    apply_theme()
    assert pg.getConfigOption("background") == DARK.colors.plot_background.rgba
    assert pg.getConfigOption("foreground") == DARK.colors.plot_foreground.rgba
    apply_theme()  # 冪等 — 2 度呼んでも同じ結果・例外なし
    assert pg.getConfigOption("background") == DARK.colors.plot_background.rgba


def test_build_main_window_applies_theme(qtbot):
    """sabotage: 事前に別値を仕込み、build_main_window が上書きすることを確認。

    main() でなく build_main_window に置く理由 = pytest-qt/realgui/撮影
    スクリプトが同じ描画経路を通るため (spec §4.3)。
    """
    from valisync.gui.app import build_main_window

    pg.setConfigOption("background", "w")
    window = build_main_window()
    qtbot.addWidget(window)
    assert pg.getConfigOption("background") == DARK.colors.plot_background.rgba
    assert pg.getConfigOption("foreground") == DARK.colors.plot_foreground.rgba
    # r3: build_main_window 経由でクロムも Fusion+トークンパレットになる
    import PySide6.QtWidgets as _qtw

    app = _qtw.QApplication.instance()
    assert app is not None and app.style().objectName() == "fusion"


def test_build_palette_maps_all_chrome_tokens(qapp):
    """role↔token の全数写像 — 同値別トークンの取り違えは QColor 比較で検出。"""
    from PySide6.QtGui import QColor, QPalette

    from valisync.gui.theme.apply import build_palette

    p = build_palette(DARK)
    c = DARK.colors
    roles = QPalette.ColorRole
    expected = {
        roles.Window: c.chrome_window,
        roles.WindowText: c.chrome_window_text,
        roles.Base: c.chrome_base,
        roles.AlternateBase: c.chrome_alternate_base,
        roles.Text: c.chrome_text,
        roles.Button: c.chrome_button,
        roles.ButtonText: c.chrome_button_text,
        roles.ToolTipBase: c.chrome_tooltip_base,
        roles.ToolTipText: c.chrome_tooltip_text,
        roles.Highlight: c.chrome_highlight,
        roles.HighlightedText: c.chrome_highlight_text,
        roles.PlaceholderText: c.chrome_placeholder,
    }
    for role, tok in expected.items():
        assert p.color(role) == QColor(*tok.rgba), role


def test_apply_sets_fusion_style_and_palette(qapp):
    from PySide6.QtGui import QColor, QPalette

    apply_theme()
    assert qapp.style().objectName() == "fusion"
    assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(
        *DARK.colors.chrome_window.rgba
    )
    apply_theme()  # 冪等 — 2度呼んでも fusion のまま・例外なし
    assert qapp.style().objectName() == "fusion"
