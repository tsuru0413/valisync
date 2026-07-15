"""テーマ適用フック (spec §4.3) — Qt/pyqtgraph 依存はここに隔離。

増分1 は pyqtgraph 既定 ('k'/'d') と同値の明示固定のみ (見た目不変)。
QPalette / アプリ QSS / QStyle 切替は増分3 (クロム統一) — 非空 QSS が
native スタイルの描画パスを変える罠があるため増分1 では導入しない。
冪等: 同値 set の繰り返しは安全。生成済みウィジェットへは遡及しないため
build_main_window の先頭 (ウィジェット構築前) で呼ぶ。
"""

from __future__ import annotations

import pyqtgraph as pg

from valisync.gui.theme import tokens


def apply_theme(t: tokens.ThemeTokens | None = None) -> None:
    tt = t if t is not None else tokens.active()
    pg.setConfigOption("background", tt.colors.plot_background.rgba)
    pg.setConfigOption("foreground", tt.colors.plot_foreground.rgba)
