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

    # Disabled グループ: 無効状態が有効時と見分けられること (グレーアウト回帰ガード)
    disabled = QPalette.ColorGroup.Disabled
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        assert p.color(disabled, role) == QColor(*c.chrome_disabled_text.rgba)
        assert p.color(disabled, role) != p.color(QPalette.ColorGroup.Active, role)


def test_apply_sets_fusion_style_and_palette(qapp):
    from PySide6.QtGui import QColor, QPalette

    apply_theme()
    assert qapp.style().objectName() == "fusion"
    assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(
        *DARK.colors.chrome_window.rgba
    )
    apply_theme()  # 冪等 — 2度呼んでも fusion のまま・例外なし
    assert qapp.style().objectName() == "fusion"


def test_build_palette_role_mapping_with_distinct_values():
    """同値クロムトークン群内の写像取り違えは DARK 値の比較では盲目 (r1 の教訓:
    memory gui_freeze_tokenization_verification_pattern)。全 chrome トークンを
    相異値にしたテーマで role↔token の対応を直接実証する。"""
    import dataclasses

    from PySide6.QtGui import QColor, QPalette

    from valisync.gui.theme.apply import build_palette
    from valisync.gui.theme.tokens import DARK, Color

    chrome_fields = [
        f.name for f in dataclasses.fields(DARK.colors) if f.name.startswith("chrome_")
    ]
    assert len(chrome_fields) == 13
    repl = {
        name: Color(i + 1, (i * 7 + 3) % 256, (i * 13 + 5) % 256)
        for i, name in enumerate(chrome_fields)
    }
    alt = dataclasses.replace(DARK, colors=dataclasses.replace(DARK.colors, **repl))
    p = build_palette(alt)
    roles = QPalette.ColorRole
    expected = {
        roles.Window: "chrome_window",
        roles.WindowText: "chrome_window_text",
        roles.Base: "chrome_base",
        roles.AlternateBase: "chrome_alternate_base",
        roles.Text: "chrome_text",
        roles.Button: "chrome_button",
        roles.ButtonText: "chrome_button_text",
        roles.ToolTipBase: "chrome_tooltip_base",
        roles.ToolTipText: "chrome_tooltip_text",
        roles.Highlight: "chrome_highlight",
        roles.HighlightedText: "chrome_highlight_text",
        roles.PlaceholderText: "chrome_placeholder",
    }
    for role, name in expected.items():
        assert p.color(role) == QColor(*repl[name].rgba), name
    assert p.color(QPalette.ColorGroup.Disabled, roles.WindowText) == QColor(
        *repl["chrome_disabled_text"].rgba
    )


def test_os_prefers_dark_maps_color_scheme(qapp, monkeypatch):
    """Light のみ False・Dark/Unknown は True (判定不能は一律 dark・spec §11.2)。"""
    from PySide6.QtCore import Qt

    from valisync.gui.theme import apply as apply_mod

    class _Hints:
        def __init__(self, scheme):
            self._scheme = scheme

        def colorScheme(self):
            return self._scheme

    for scheme, expected in [
        (Qt.ColorScheme.Light, False),
        (Qt.ColorScheme.Dark, True),
        (Qt.ColorScheme.Unknown, True),
    ]:
        monkeypatch.setattr(type(qapp), "styleHints", lambda self, s=scheme: _Hints(s))
        assert apply_mod.os_prefers_dark() is expected, scheme


def test_theme_mode_roundtrip_and_unknown_fallback(qapp):
    from valisync.gui.theme.apply import load_theme_mode, save_theme_mode
    from valisync.gui.theme.tokens import ThemeMode

    assert load_theme_mode() is ThemeMode.AUTO  # 未保存 → AUTO 既定
    save_theme_mode(ThemeMode.LIGHT)
    assert load_theme_mode() is ThemeMode.LIGHT
    # 未知値 (手編集/旧バージョン) は AUTO へ silent フォールバック
    from PySide6.QtCore import QSettings

    from valisync.gui.theme import settings as theme_settings

    QSettings(theme_settings._ORG, theme_settings._APP).setValue(
        "theme_mode", "solarized"
    )
    assert load_theme_mode() is ThemeMode.AUTO


def test_apply_startup_theme_resolves_saved_mode(qapp, monkeypatch):
    """再起動反映のインプロセス実証: 保存 light → 起動解決で LIGHT active＋Latte パレット。"""  # noqa: RUF002
    from PySide6.QtGui import QColor, QPalette

    from valisync.gui.theme import apply as apply_mod
    from valisync.gui.theme.apply import apply_startup_theme, save_theme_mode
    from valisync.gui.theme.tokens import DARK, LIGHT, ThemeMode, active, set_active

    save_theme_mode(ThemeMode.LIGHT)
    monkeypatch.setattr(
        apply_mod, "os_prefers_dark", lambda: True
    )  # os は無視されるはず
    try:
        apply_startup_theme()
        assert active() is LIGHT
        assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(
            *LIGHT.colors.chrome_window.rgba
        )
    finally:
        set_active(DARK)
        apply_mod.apply_theme()


def test_apply_startup_theme_forced_ignores_settings(qapp):
    """forced は QSettings を読まない (spec §11.3 — 撮影スクリプトの強制注入口)。"""
    from valisync.gui.theme import apply as apply_mod
    from valisync.gui.theme.apply import apply_startup_theme, save_theme_mode
    from valisync.gui.theme.tokens import DARK, LIGHT, ThemeMode, active, set_active

    save_theme_mode(ThemeMode.DARK)
    try:
        apply_startup_theme(forced=ThemeMode.LIGHT)
        assert active() is LIGHT
        # ThemeTokens 直接注入 (--debug-theme 経路)
        import dataclasses

        alt = dataclasses.replace(DARK)
        apply_startup_theme(forced=alt)
        assert active() is alt
    finally:
        set_active(DARK)
        apply_mod.apply_theme()
