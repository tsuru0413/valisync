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
