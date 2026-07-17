"""theme/apply.py — pg 設定注入・冪等・build_main_window 配線 (Layer A/B)。"""

from __future__ import annotations

import subprocess
import sys

import pyqtgraph as pg
from PySide6.QtWidgets import QWidget

from valisync.gui.theme.apply import apply_theme
from valisync.gui.theme.tokens import DARK


class _RegionProbe(QWidget):
    """素の QWidget サブクラス — plain QWidget は Qt が特別扱いし WA なしでも
    QSS を描くため、WA_StyledBackground の sabotage 検出には subclass が必須
    (PR #116 の対象条件・production の配線先 view もサブクラス)。"""


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
    from PySide6.QtGui import QColor, QPalette

    from valisync.gui.app import build_main_window

    pg.setConfigOption("background", "w")
    window = build_main_window()
    qtbot.addWidget(window)
    assert pg.getConfigOption("background") == DARK.colors.plot_background.rgba
    assert pg.getConfigOption("foreground") == DARK.colors.plot_foreground.rgba
    # r3: build_main_window 経由で palette と separator stylesheet が適用
    import PySide6.QtWidgets as _qtw

    app = _qtw.QApplication.instance()
    assert app is not None
    # palette の特性で Fusion style の適用を検証 (setStyleSheet 副作用対応)
    assert app.palette().color(QPalette.ColorRole.Window) == QColor(
        *DARK.colors.chrome_window.rgba
    )
    assert "QMainWindow::separator" in app.styleSheet()


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
    # style の特性検証: palette が正しく適用されているか (setStyleSheet の副作用対応)
    assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(
        *DARK.colors.chrome_window.rgba
    )
    # separator stylesheet が app に設定されている
    assert "QMainWindow::separator" in qapp.styleSheet()
    apply_theme()  # 冪等 — 2度呼んでも palette 一貫・stylesheet 重複なし
    assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(
        *DARK.colors.chrome_window.rgba
    )
    assert qapp.styleSheet().count("QMainWindow::separator") == 1


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
    assert len(chrome_fields) == 14  # chrome_frame は QSS 専用 (palette 非写像)
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


def test_build_main_window_theme_override(qtbot):
    """build_main_window(theme=...) が QSettings より優先される (spec §11.3)。"""
    from valisync.gui.app import build_main_window
    from valisync.gui.theme import apply as apply_mod
    from valisync.gui.theme.apply import save_theme_mode
    from valisync.gui.theme.tokens import DARK, LIGHT, ThemeMode, active, set_active

    save_theme_mode(ThemeMode.DARK)
    try:
        window = build_main_window(theme=ThemeMode.LIGHT)
        qtbot.addWidget(window)
        assert active() is LIGHT
    finally:
        set_active(DARK)
        apply_mod.apply_theme()


def test_apply_theme_does_not_rebuild_style_on_repeat(qapp):
    """2回目の apply_theme が setStyle を再実行しない (QSS 設定後 objectName が
    '' になる実測に対する property フラグ判定の回帰ガード)。setStyle が走ると
    style() が別インスタンスに置き換わるため、参照保持＋is で観測する。"""  # noqa: RUF002
    apply_theme()
    style_before = qapp.style()  # 参照保持 (id 再利用フレーク回避)
    apply_theme()
    assert qapp.style() is style_before


def test_apply_theme_sets_separator_stylesheet(qapp):
    apply_theme()
    sheet = qapp.styleSheet()
    assert "QMainWindow::separator" in sheet
    assert DARK.colors.chrome_frame.hex in sheet
    apply_theme()  # 冪等 — 同一文字列の再設定で規則が重複しない
    assert qapp.styleSheet().count("QMainWindow::separator") == 1


def test_frame_region_sets_name_attribute_margins_and_qss(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from valisync.gui.theme.apply import frame_region

    w = QWidget()
    qtbot.addWidget(w)
    QVBoxLayout(w).setContentsMargins(0, 0, 0, 0)
    frame_region(w, "region_test")
    assert w.objectName() == "region_test"
    assert w.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    m = w.layout().contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (1, 1, 1, 1)
    assert "#region_test" in w.styleSheet()
    assert DARK.colors.chrome_frame.hex in w.styleSheet()


def test_frame_region_preserves_existing_name_and_margins(qtbot):
    """objectName 既設なら尊重・余白が非ゼロ (既定余白等) なら不変 (spec §6.2)。"""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from valisync.gui.theme.apply import frame_region

    w = QWidget()
    qtbot.addWidget(w)
    w.setObjectName("already_named")
    QVBoxLayout(w).setContentsMargins(9, 9, 9, 9)
    frame_region(w, "region_ignored")
    assert w.objectName() == "already_named"
    m = w.layout().contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (9, 9, 9, 9)
    assert "#already_named" in w.styleSheet()


def test_frame_region_border_paints_on_child_widget(qtbot):
    """honest ピクセル: 枠が『子ウィジェットとして』実描画される (PR #116 蛍光緑親パターン)。

    probe は QWidget サブクラス (_RegionProbe) — 素の QWidget は Qt が特別扱いし
    WA_StyledBackground なしでも QSS を描いてしまうため sabotage を検出できない。
    production の配線先 (FileBrowserView 等) もサブクラスであり、この条件が
    PR #116 の対象そのもの。

    sabotage 構成: frame_region の WA_StyledBackground 行を外すと枠は描かれず
    RED になる (増分1 で実証)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from valisync.gui.theme.apply import frame_region

    parent = QWidget()
    parent.setStyleSheet("background: #00ff00;")  # 蛍光緑 — 枠が透けたら即検出
    parent.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    parent.resize(200, 120)
    qtbot.addWidget(parent)
    child = _RegionProbe(parent)
    QVBoxLayout(child).setContentsMargins(0, 0, 0, 0)
    child.setGeometry(20, 20, 100, 60)
    frame_region(child, "region_pixel_probe")
    parent.show()
    img = parent.grab().toImage()
    # grab() は物理ピクセル (DPR≠1 で論理座標の点打ちは枠線 1px を外す) —
    # 枠色ピクセルの計数で描画を実証する (この scene で chrome_frame 色は枠のみ)
    frame_color = QColor(*DARK.colors.chrome_frame.rgba).rgb()
    hits = sum(
        1
        for y in range(img.height())
        for x in range(img.width())
        if img.pixelColor(x, y).rgb() == frame_color
    )
    assert hits >= 100, f"枠線ピクセルが不足 ({hits}) — 枠が描画されていない"


def test_apply_theme_applies_fusion_style_fresh_process():
    """Fusion 適用の回帰ガード (レビュー Important 対応)。

    QSS 設定後は style().objectName() が '' に壊れるため既存 qapp では検証不能。
    fresh interpreter で separator QSS を空に patch し (styleSheet ガードが
    素通りしてラップが起きない)、初回適用の Fusion を直接観測する。
    setStyle コード路が実行されたことは property vs_fusion_applied で検証
    (offscreen は fusion が default ゆえ objectName 検査は不十分)。
    """
    code = (
        "import os; os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen'); "
        "import sys; from PySide6.QtWidgets import QApplication; "
        "app = QApplication(sys.argv); "
        "from valisync.gui.theme import apply as apply_mod, qss; "
        "qss.main_window_separator = lambda t=None: ''; "
        "apply_mod.apply_theme(); "
        "sys.exit(0 if app.property('vs_fusion_applied') else 1)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_main_window_regions_have_boundary_frames(qtbot):
    """4領域 (file/channel/diagnostics/central) に境界枠が配線される (spec §7)。"""
    from valisync.gui.app import build_main_window

    window = build_main_window()
    qtbot.addWidget(window)
    regions = {
        "region_file_browser": window.file_browser_view,
        "region_channel_browser": window.channel_browser_view,
        "region_diagnostics": window.diagnostics_dock.widget(),
        "region_central": window.central_stack,
    }
    for name, w in regions.items():
        assert w.objectName() == name, name
        assert f"#{name}" in w.styleSheet(), name
        assert DARK.colors.chrome_frame.hex in w.styleSheet(), name
