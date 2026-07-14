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
