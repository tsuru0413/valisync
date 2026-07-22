"""Tests for hue_variant (E-2c, spec §4.1) — lightness-variant colors.

Test-locks the delta_l=0.15 coefficient chosen via the CVD-simulation spike
(Machado et al. 2009 protan/deuteranopia/tritanopia matrices + CIE76 ΔE —
see color_variants.py's module docstring for the full rationale/numbers).
Any future recalibration of _DELTA_L must update the locked values below
deliberately, not by surprise.
"""

from __future__ import annotations

import re

import pytest

from valisync.gui.color_variants import hue_variant
from valisync.gui.theme.tokens import active

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")

# All 8 signal_palette colors x their 3 hue_variant steps (test-lock — spec
# §4.1's mandated CVD-verified coefficient, captured from the real function).
_LOCKED_VARIANTS: dict[str, tuple[str, str, str]] = {
    "#56b4e9": ("#56b4e9", "#9ad2f2", "#1c93d7"),
    "#e69f00": ("#e69f00", "#ffc033", "#9a6a00"),
    "#00c08b": ("#00c08b", "#0effbc", "#007454"),
    "#f0e442": ("#f0e442", "#f6ee89", "#d5c711"),
    "#ff6e4a": ("#ff6e4a", "#ffab97", "#fc3200"),
    "#d98bc0": ("#d98bc0", "#ecc5df", "#c651a1"),
    "#9a8cff": ("#9a8cff", "#ddd9ff", "#5740ff"),
    "#c8c8c8": ("#c8c8c8", "#eeeeee", "#a2a2a2"),
}


def test_signal_palette_matches_the_8_colors_this_test_locks() -> None:
    """Guards against a future palette change silently invalidating the
    CVD-verified coefficients this module locks in (they were verified
    specifically against THESE 8 colors)."""
    palette_hexes = [c.hex for c in active().colors.signal_palette]
    assert palette_hexes == list(_LOCKED_VARIANTS.keys())


@pytest.mark.parametrize("base_hex", list(_LOCKED_VARIANTS))
def test_hue_variant_step_0_is_identity(base_hex: str) -> None:
    """step 0 is the color unchanged -- a hue family's first-added entry
    renders identically to the plain palette color."""
    assert hue_variant(base_hex, 0) == base_hex


@pytest.mark.parametrize("base_hex", list(_LOCKED_VARIANTS))
def test_hue_variant_locked_values(base_hex: str) -> None:
    expected = _LOCKED_VARIANTS[base_hex]
    assert tuple(hue_variant(base_hex, s) for s in (0, 1, 2)) == expected


@pytest.mark.parametrize("base_hex", list(_LOCKED_VARIANTS))
def test_hue_variant_3_steps_are_pairwise_distinct(base_hex: str) -> None:
    variants = {hue_variant(base_hex, s) for s in (0, 1, 2)}
    assert len(variants) == 3


@pytest.mark.parametrize("base_hex", list(_LOCKED_VARIANTS))
def test_hue_variant_returns_well_formed_hex(base_hex: str) -> None:
    for step in (0, 1, 2):
        assert _HEX_RE.match(hue_variant(base_hex, step))


def test_hue_variant_rejects_invalid_step() -> None:
    with pytest.raises(ValueError):
        hue_variant("#56b4e9", 3)
    with pytest.raises(ValueError):
        hue_variant("#56b4e9", -1)


def test_hue_variant_clamps_near_white_without_error() -> None:
    """A near-white base pushed lighter (step 1) must clamp to white, not
    raise or overflow (HLS lightness + delta_l can exceed 1.0)."""
    result = hue_variant("#fefefe", 1)
    assert _HEX_RE.match(result)
    assert result == "#ffffff"


def test_hue_variant_clamps_near_black_without_error() -> None:
    """A near-black base pushed darker (step 2) must clamp to black, not
    raise or underflow (HLS lightness - delta_l can go below 0.0)."""
    result = hue_variant("#010101", 2)
    assert _HEX_RE.match(result)
    assert result == "#000000"
