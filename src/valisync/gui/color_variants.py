"""hue_variant — lightness-shift variant of a palette hue (E-2c).

Pure Python (no Qt/PySide6 imports) — consumed from GraphPanelVM, a pure
ViewModel. Produces the "明度バリアント 3 段" (spec §4.1/§4.3) that lets
several signals from the SAME file render as visibly-related shades of one
hue, while different files land on different hues (``file_hue_index`` in
AppViewModel picks the hue; this module only picks the shade within it).
"""

from __future__ import annotations

import colorsys

from valisync.gui.theme.tokens import Color

# Lightness delta applied for variant_step in {1, 2} (step 0 = the base color,
# unchanged — so a hue family's first-added entry renders identically to the
# plain palette color).
#
# Value chosen via a one-off CVD-simulation spike (not checked in): Machado,
# Oliveira & Fernandes (2009) severity-1.0 protanopia/deuteranopia/tritanopia
# matrices (applied in linear RGB, coefficients from colour-science's
# machado2010 dataset) + CIE76 ΔE in Lab (D65). Swept delta_l in
# [0.08, 0.25] across all 8 `signal_palette` colors:
#   - 0.15 gives a worst-case *within-family* separation (any two of a base's
#     3 variants, across normal vision + all 3 CVD types, over all 8 base
#     colors) of ΔE 6.89 (#F0E442 under tritanopia, step0 vs step1) — well
#     above the ~2.3 CIE76 "just noticeable difference" floor, and with ZERO
#     HLS-lightness clipping (clipping starts appearing at delta_l=0.22 for
#     the lightest/palest palette entries).
#   - Checked against design.md's two documented tight cross-token margins
#     (#E69F00 vs accent_active ΔE7.2 normal-vision; #56B4E9 vs preview_curve
#     ΔE6.6 normal-vision): at delta_l=0.15 every hue_variant step (1 and 2)
#     of those two base colors only ever INCREASES the ΔE to those tokens
#     (never erodes it), in all 4 vision lenses tested.
#   - Known minor residual (recorded for the increment-4 docs pass, not a
#     blocker): the achromatic 8th palette entry (#C8C8C8) darkened (step 2)
#     lands at ΔE 4.54 from `plot_foreground` (#969696, axis/tick text) — a
#     narrower-than-usual but still-perceptible margin, reached only when a
#     3rd same-file signal on the gray hue needs the darkest variant.
_DELTA_L = 0.15


def _clamp255(v: float) -> int:
    """Round to the nearest int and clamp to [0, 255] (guards float rounding)."""
    return max(0, min(255, round(v * 255)))


def hue_variant(hex_color: str, step: int) -> str:
    """Return a lightness-shifted variant of *hex_color* for *step*.

    ``step`` must be 0 (unchanged), 1 (lighter), or 2 (darker) — the HLS
    lightness is shifted by +/- :data:`_DELTA_L` and clamped to [0, 1];
    hue and saturation are preserved so all 3 variants read as the same
    hue family. Any other *step* raises ``ValueError`` — callers only ever
    pass a ``_PlottedEntry.variant_step``, which the allocation rule (spec
    §4.1) keeps within {0, 1, 2}.
    """
    if step not in (0, 1, 2):
        raise ValueError(f"step must be 0, 1, or 2, got {step!r}")
    if step == 0:
        return hex_color
    c = Color.from_hex(hex_color)
    h, lightness, s = colorsys.rgb_to_hls(c.r / 255.0, c.g / 255.0, c.b / 255.0)
    new_l = (
        min(1.0, lightness + _DELTA_L) if step == 1 else max(0.0, lightness - _DELTA_L)
    )
    r, g, b = colorsys.hls_to_rgb(h, new_l, s)
    return Color(_clamp255(r), _clamp255(g), _clamp255(b)).hex
