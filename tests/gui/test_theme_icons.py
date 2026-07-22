"""theme/icons — vendored SVG 規約とレジストリ (Layer A)。

AST ガード (test_theme_guard.py) は *.py のみ走査で theme/ を除外するため、
SVG の色規約はこのテストが唯一の防波堤 (spec §12.2)。
"""

from __future__ import annotations

import re
from pathlib import Path

ICONS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "valisync" / "gui" / "theme" / "icons"
)


def _svg_files() -> list[Path]:
    return sorted(ICONS_DIR.rglob("*.svg"))


def test_vendored_svgs_exist():
    assert len(_svg_files()) >= 4


def test_svgs_use_current_color_only():
    """テーマ追従の前提: 色は currentColor のみ・固定 hex/rgb を持ち込まない。"""
    for path in _svg_files():
        text = path.read_text(encoding="utf-8")
        assert "currentColor" in text, path.name
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(", text), path.name
        # fill/stroke 属性はホワイトリスト方式 — hsl()/named color も遮断
        for m in re.finditer(r'(?:fill|stroke)="([^"]+)"', text):
            assert m.group(1) in ("none", "currentColor"), (path.name, m.group(1))


def test_licenses_md_covers_every_svg():
    """全 vendored SVG が LICENSES.md の出所一覧に載っている (帰属漏れ防止)。"""
    listing = (ICONS_DIR / "LICENSES.md").read_text(encoding="utf-8")
    for path in _svg_files():
        rel = path.relative_to(ICONS_DIR).as_posix()
        assert rel in listing, rel


def test_registry_paths_resolve():
    from valisync.gui.theme.icons import ICONS

    assert set(ICONS) == {
        "open",
        "open_folder",
        "export",
        "data_explorer",
        "chevron_down",
        "chevron_right",
        "chevron_left",
        "chevron_up",
        "diag_error",
        "diag_warning",
        "diag_info",
        "close",
        "float_dock",
        "dock_panel_left",
        "dock_panel_left_partial",
        "dock_panel_right",
        "dock_panel_right_partial",
        "dock_panel_bottom",
        "dock_panel_bottom_partial",
    }
    for name, rel in ICONS.items():
        assert (ICONS_DIR / rel).is_file(), f"{name} -> {rel}"


def test_icons_module_import_is_qt_free():
    """module import は pure (export.py が ICONS を pure に参照するため・spec §12.2)。"""
    import subprocess
    import sys

    code = (
        "import sys; import valisync.gui.theme.icons; "
        "bad = [m for m in sys.modules if m.startswith(('PySide6', 'pyqtgraph'))]; "
        "sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_icon_unknown_name_is_loud():
    import pytest as _pytest

    from valisync.gui.theme.icons import icon

    with _pytest.raises(KeyError):
        icon("no_such_icon")


def _has_pixel_near(image, expected_rgb, tol=40):
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() > 200 and (
                abs(c.red() - expected_rgb[0]) < tol
                and abs(c.green() - expected_rgb[1]) < tol
                and abs(c.blue() - expected_rgb[2]) < tol
            ):
                return True
    return False


def test_icon_pixels_use_theme_tokens(qtbot):
    """Normal=chrome_text・Disabled=chrome_disabled_text のトークン着色 (Layer B)。"""
    from PySide6.QtGui import QIcon

    from valisync.gui.theme.icons import icon
    from valisync.gui.theme.tokens import active

    c = active().colors
    ico = icon("open")
    assert not ico.isNull()
    normal = ico.pixmap(24, 24, QIcon.Mode.Normal).toImage()
    disabled = ico.pixmap(24, 24, QIcon.Mode.Disabled).toImage()
    ct = (c.chrome_text.r, c.chrome_text.g, c.chrome_text.b)
    cd = (c.chrome_disabled_text.r, c.chrome_disabled_text.g, c.chrome_disabled_text.b)
    assert _has_pixel_near(normal, ct), "Normal に chrome_text 系ピクセルが無い"
    assert _has_pixel_near(disabled, cd), (
        "Disabled に chrome_disabled_text 系ピクセルが無い"
    )
    # 同値でないテーマ前提の分離確認 (DARK: text #cdd6f4 / disabled #6c7086 は十分離れている)
    assert not _has_pixel_near(disabled, ct, tol=20)


def test_icon_color_override_paints_normal_mode(qapp):
    """color 指定時は Normal をその色で上書き (spec §2.2)。"""
    from PySide6.QtGui import QIcon

    from valisync.gui.theme.icons import icon
    from valisync.gui.theme.tokens import Color

    red = Color(255, 0, 0)
    ico = icon("close", color=red)
    assert not ico.isNull()
    normal = ico.pixmap(24, 24, QIcon.Mode.Normal).toImage()
    assert _has_pixel_near(normal, (255, 0, 0))


def test_icon_active_and_selected_modes_paint_requested_colors(qapp):
    """active_color/selected_color 指定時は QIcon.Mode.Active/Selected へ着色
    (診断アイコンの選択セル可視性・タブ✕の hover 赤 — spec §2.2)。"""
    from PySide6.QtGui import QIcon

    from valisync.gui.theme.icons import icon
    from valisync.gui.theme.tokens import Color

    red = Color(255, 0, 0)
    green = Color(0, 255, 0)
    blue = Color(0, 0, 255)
    ico = icon("close", color=red, active_color=green, selected_color=blue)
    assert not ico.isNull()
    normal = ico.pixmap(24, 24, QIcon.Mode.Normal).toImage()
    active = ico.pixmap(24, 24, QIcon.Mode.Active).toImage()
    selected = ico.pixmap(24, 24, QIcon.Mode.Selected).toImage()
    assert _has_pixel_near(normal, (255, 0, 0))
    assert _has_pixel_near(active, (0, 255, 0))
    assert _has_pixel_near(selected, (0, 0, 255))
    # Active/Selected 未指定時と混同していないことの確認 (Normal に紛れていない)
    assert not _has_pixel_near(normal, (0, 255, 0), tol=20)
    assert not _has_pixel_near(normal, (0, 0, 255), tol=20)


def test_icon_active_selected_absent_when_not_requested(qapp):
    """active_color/selected_color 未指定時は既存呼出と同一 (現行互換)。"""
    from PySide6.QtGui import QIcon

    from valisync.gui.theme.icons import icon
    from valisync.gui.theme.tokens import active

    c = active().colors
    ico = icon("close")
    normal = ico.pixmap(24, 24, QIcon.Mode.Normal).toImage()
    assert _has_pixel_near(normal, (c.chrome_text.r, c.chrome_text.g, c.chrome_text.b))


def test_new_semantic_icons_registered_and_render(qapp):
    from valisync.gui.theme import icons

    for name in (
        "diag_error",
        "diag_warning",
        "diag_info",
        "close",
        "float_dock",
        "dock_panel_left",
        "dock_panel_left_partial",
        "dock_panel_right",
        "dock_panel_right_partial",
        "dock_panel_bottom",
        "dock_panel_bottom_partial",
    ):
        ico = icons.icon(name)
        assert not ico.isNull(), name


def test_chevron_icons_registered_and_render(qapp):
    from valisync.gui.theme import icons

    for name in ("chevron_down", "chevron_right"):
        ico = icons.icon(name)
        assert not ico.isNull(), name


def test_chevron_left_up_registered_and_render(qapp):
    from valisync.gui.theme import icons

    for name in ("chevron_left", "chevron_up"):
        ico = icons.icon(name)
        assert not ico.isNull(), name


def test_shell_actions_use_registry_icons(qtbot):
    """4アクション全てがレジストリ由来の非 null アイコンを持つ (Layer B)。"""
    from PySide6.QtWidgets import QWidget

    from valisync.gui.theme.tokens import active
    from valisync.gui.views.shell_actions import ShellActions

    parent = QWidget()
    qtbot.addWidget(parent)
    acts = ShellActions(parent)
    for key in ("open", "open_folder", "export"):
        assert not acts.action(key).icon().isNull(), key
    # ピクセルがトークン色 (QStyle 由来の多色アイコンからの置換確認)
    c = active().colors
    for key in ("open", "open_folder", "export"):
        img = acts.action(key).icon().pixmap(24, 24).toImage()
        assert _has_pixel_near(
            img, (c.chrome_text.r, c.chrome_text.g, c.chrome_text.b)
        ), key
