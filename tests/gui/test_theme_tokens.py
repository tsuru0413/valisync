"""theme/tokens.py — Color 検証・DARK 完全性・純粋性 (Layer A)。"""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from valisync.gui.theme.tokens import DARK, Color, active, set_active


def test_color_hex_roundtrip():
    c = Color.from_hex("#1f77b4")
    assert (c.r, c.g, c.b, c.a) == (31, 119, 180, 255)
    assert c.hex == "#1f77b4"
    assert Color.from_hex("#4FC3F7").hex == "#4fc3f7"  # 小文字正規化


def test_color_rejects_out_of_range():
    with pytest.raises(ValueError):
        Color(256, 0, 0)
    with pytest.raises(ValueError):
        Color(0, 0, 0, -1)


def test_from_hex_rejects_malformed():
    with pytest.raises(ValueError):
        Color.from_hex("1f77b4")
    with pytest.raises(ValueError):
        Color.from_hex("#1f77b")


def test_color_qss_and_css_alpha_formats():
    c = Color(17, 17, 27, 230)
    assert c.qss() == "rgba(17,17,27,230)"  # Qt QSS: alpha 0-255
    assert c.css() == "rgba(17,17,27,0.902)"  # CSS: alpha 0-1 (spec §4.1 非互換吸収)
    assert c.rgba == (17, 17, 27, 230)


def test_dark_all_color_fields_are_color():
    for f in dataclasses.fields(DARK.colors):
        v = getattr(DARK.colors, f.name)
        if f.name == "signal_palette":
            assert len(v) == 10 and all(isinstance(c, Color) for c in v)
        else:
            assert isinstance(v, Color), f.name


def test_dark_values_frozen_snapshot():
    """DARK 値の意図的 test-lock — 再デザイン反復で値を変えたらここも更新 (spec §3)。"""
    c = DARK.colors
    assert c.signal_palette[0].hex == "#1f77b4"
    assert c.cursor_a.hex == "#f9e2af"
    assert c.cursor_b.hex == "#89b4fa"
    assert c.surface_chip == Color(17, 17, 27, 230)
    assert c.accent_active.hex == "#f59e0b"
    assert c.drop_highlight.hex == "#1f77b4"
    assert c.error.hex == "#c0392b"
    assert c.plot_background == Color(0, 0, 0)
    assert c.plot_foreground == Color(150, 150, 150)
    assert DARK.grid_alpha == 60
    assert DARK.spacing.chip_margins == (6, 5, 6, 5)
    assert DARK.radii.chip == 5
    assert DARK.typography.small_px == 9


def test_active_default_and_set():
    assert active() is DARK
    alt = dataclasses.replace(DARK)
    set_active(alt)
    try:
        assert active() is alt
    finally:
        set_active(DARK)


def test_tokens_module_is_qt_free():
    """純粋性ガード (spec §4.1) — fresh interpreter で tokens import 後も Qt 不在。"""
    code = (
        "import sys; import valisync.gui.theme.tokens; "
        "bad = [m for m in sys.modules if m.startswith(('PySide6', 'pyqtgraph'))]; "
        "sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
