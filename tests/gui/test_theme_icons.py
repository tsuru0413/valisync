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


def test_licenses_md_covers_every_svg():
    """全 vendored SVG が LICENSES.md の出所一覧に載っている (帰属漏れ防止)。"""
    listing = (ICONS_DIR / "LICENSES.md").read_text(encoding="utf-8")
    for path in _svg_files():
        rel = path.relative_to(ICONS_DIR).as_posix()
        assert rel in listing, rel


def test_registry_paths_resolve():
    from valisync.gui.theme.icons import ICONS

    assert set(ICONS) == {"open", "open_folder", "export", "data_explorer"}
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
