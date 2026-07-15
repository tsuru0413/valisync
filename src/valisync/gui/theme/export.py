"""トークン→CSS/JSON エクスポートの純粋コア (spec §5・増分2).

pure Python (Qt import 禁止 — tokens/qss と同じ制約)。ファイル IO・
git SHA 取得は scripts/export_design_tokens.py (薄い CLI) が担う。
出力は決定的: 同じ ThemeTokens からバイト同一の文字列を返す (spec §6)。
"""

from __future__ import annotations

import dataclasses
import json

from valisync.gui.theme.tokens import Color, ThemeTokens


def css_var_name(category: str, field: str, index: int | None = None) -> str:
    base = f"--vs-{category}-{field.replace('_', '-')}"
    return base if index is None else f"{base}-{index}"


def _css_lines(t: ThemeTokens) -> list[str]:
    lines: list[str] = []
    for f in dataclasses.fields(t.colors):
        v = getattr(t.colors, f.name)
        if f.name == "signal_palette":
            lines.extend(
                f"  {css_var_name('color', f.name, i)}: {c.css()};"
                for i, c in enumerate(v)
            )
        else:
            lines.append(f"  {css_var_name('color', f.name)}: {v.css()};")
    for f in dataclasses.fields(t.spacing):
        v = getattr(t.spacing, f.name)
        value = " ".join(f"{n}px" for n in v) if isinstance(v, tuple) else f"{v}px"
        lines.append(f"  {css_var_name('spacing', f.name)}: {value};")
    for f in dataclasses.fields(t.radii):
        lines.append(
            f"  {css_var_name('radius', f.name)}: {getattr(t.radii, f.name)}px;"
        )
    # typography.small_px は命名だけ特例 (--vs-font-small) — px 接尾辞をフィールド名から除く
    lines.append(f"  --vs-font-small: {t.typography.small_px}px;")
    lines.append(f"  --vs-grid-alpha: {t.grid_alpha};")
    return lines


def build_css(t: ThemeTokens) -> str:
    return ":root {\n" + "\n".join(_css_lines(t)) + "\n}\n"


def _color_json(c: Color) -> dict[str, object]:
    return {"rgba": list(c.rgba), "hex": c.hex, "css": c.css()}


def build_json(t: ThemeTokens) -> str:
    colors: dict[str, object] = {}
    for f in dataclasses.fields(t.colors):
        v = getattr(t.colors, f.name)
        colors[f.name] = (
            [_color_json(c) for c in v]
            if f.name == "signal_palette"
            else _color_json(v)
        )
    data = {
        "colors": colors,
        "spacing": {
            f.name: list(v) if isinstance(v := getattr(t.spacing, f.name), tuple) else v
            for f in dataclasses.fields(t.spacing)
        },
        "radii": {
            f.name: getattr(t.radii, f.name) for f in dataclasses.fields(t.radii)
        },
        "typography": {
            f.name: getattr(t.typography, f.name)
            for f in dataclasses.fields(t.typography)
        },
        "grid_alpha": t.grid_alpha,
    }
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
