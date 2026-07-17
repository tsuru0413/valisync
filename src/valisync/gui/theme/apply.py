"""テーマ適用フック (spec §4.3) — Qt/pyqtgraph 依存はここに隔離。

増分3: クロム = Fusion スタイル + トークン由来 QPalette (スパイクで確定)。
QPalette の 12 role を chrome_* トークンへ写像する。
QSS 上書きは qss.py の生成関数経由 (separator は app レベル・領域枠は frame_region)。
冪等: 同値 set の繰り返しは安全 (Fusion は未適用時のみ setStyle)。
生成済みウィジェットの pg 設定へは遡及しないため build_main_window の先頭
(ウィジェット構築前) で呼ぶ。QApplication 不在の文脈では pg 設定のみ。
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from valisync.gui.theme import qss, tokens
from valisync.gui.theme import settings as theme_settings


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
    # Disabled グループを明示 — setColor(role, color) は全グループに同色を
    # 設定するため、無効コントロールが有効時と見分け不能になる (最終レビューで
    # 実証された回帰)。テキスト系3 role を dim トークンでグレーアウトさせる。
    disabled = QPalette.ColorGroup.Disabled
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        p.setColor(disabled, role, QColor(*c.chrome_disabled_text.rgba))
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
        # 領域境界: separator は app レベル QSS でしか描けない (palette 非対応)
        # 冪等: 同一内容なら setStyleSheet を呼ばず (Qt 副作用回避)
        new_sheet = qss.main_window_separator(tt)
        if app.styleSheet() != new_sheet:
            app.setStyleSheet(new_sheet)


_THEME_MODE_KEY = "theme_mode"


def os_prefers_dark() -> bool:
    """OS カラースキーム検出 — 判定不能 (Unknown/QApplication 不在) は一律 dark
    (現行 DARK 運用との連続性・CI の Unknown でも安定・spec §11.2)。"""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return True
    return app.styleHints().colorScheme() != Qt.ColorScheme.Light


def load_theme_mode() -> tokens.ThemeMode:
    """保存 mode を読む。未保存・未知値は AUTO (silent — _restore_state と同パターン)。"""
    raw = QSettings(theme_settings._ORG, theme_settings._APP).value(
        _THEME_MODE_KEY, tokens.ThemeMode.AUTO.value
    )
    try:
        return tokens.ThemeMode(str(raw))
    except ValueError:
        return tokens.ThemeMode.AUTO


def save_theme_mode(mode: tokens.ThemeMode) -> None:
    QSettings(theme_settings._ORG, theme_settings._APP).setValue(
        _THEME_MODE_KEY, mode.value
    )


def apply_startup_theme(
    forced: tokens.ThemeMode | tokens.ThemeTokens | None = None,
) -> None:
    """起動時テーマ確定 (spec §11.3)。

    forced は撮影スクリプト等の強制注入口 — QSettings/OS を読まない
    (--debug-theme の set_active 事前注入が起動解決に上書きされる衝突を構造回避)。
    ThemeTokens 直接注入はデバッグテーマ用。
    """
    if isinstance(forced, tokens.ThemeTokens):
        tokens.set_active(forced)
    else:
        mode = forced if forced is not None else load_theme_mode()
        tokens.set_active(tokens.resolve_theme(mode, os_prefers_dark()))
    apply_theme()


def frame_region(widget: QWidget, name: str) -> None:
    """領域コンテンツに 1px 境界枠を付ける (region-frames spec §6.2)。

    どの領域に枠を付けるかはシェル (MainWindow) が選ぶ — view 自体は無変更で、
    同じ view を別文脈 (テスト・プレビュー) で使っても枠は付かない。
    """
    if not widget.objectName():
        widget.setObjectName(name)
    # 素の QWidget 子は QSS border を描かない (PR #116)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    lay = widget.layout()
    if lay is not None:
        m = lay.contentsMargins()
        if (m.left(), m.top(), m.right(), m.bottom()) == (0, 0, 0, 0):
            # margins-0 の子が枠を覆う罠 (PR #116) — 枠幅ぶんだけ空ける
            lay.setContentsMargins(1, 1, 1, 1)
    widget.setStyleSheet(qss.region_frame(widget.objectName()))
