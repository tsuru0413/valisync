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


_TOKENS_CSS_PLACEHOLDER = "<!-- @TOKENS_CSS -->"


def inject_tokens_css(template: str, t: ThemeTokens) -> str:
    if _TOKENS_CSS_PLACEHOLDER not in template:
        raise ValueError(f"テンプレートに {_TOKENS_CSS_PLACEHOLDER} がない")
    return template.replace(
        _TOKENS_CSS_PLACEHOLDER, "<style>\n" + build_css(t) + "</style>"
    )


def _card(group: str, title: str, body: str, t: ThemeTokens) -> str:
    c = t.colors
    template = (
        f'<!-- @dsCard group="{group}" -->\n'
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        "<!-- @TOKENS_CSS -->\n"
        f"<style>body{{background:{c.chrome_window.hex};color:{c.chrome_text.hex};"
        "font-family:sans-serif;margin:16px} table{border-collapse:collapse} "
        "td,th{padding:4px 10px;text-align:left;font-size:13px}</style>\n"
        f"</head><body>\n<h2>{title}</h2>\n{body}\n</body></html>\n"
    )
    return inject_tokens_css(template, t)


def _swatch_row(label: str, var: str, meta: str) -> str:
    return (
        f"<tr><td><div style='width:48px;height:24px;border:1px solid #555;"
        f"background:var({var})'></div></td>"
        f"<td><code>{label}</code></td><td><code>var({var})</code></td>"
        f"<td><code>{meta}</code></td></tr>"
    )


def build_token_cards(t: ThemeTokens, theme_label: str) -> dict[str, str]:
    rows: list[str] = []
    for f in dataclasses.fields(t.colors):
        v = getattr(t.colors, f.name)
        if f.name == "signal_palette":
            rows.extend(
                _swatch_row(
                    f"signal_palette-{i}", css_var_name("color", f.name, i), c.hex
                )
                for i, c in enumerate(v)
            )
        else:
            rows.append(_swatch_row(f.name, css_var_name("color", f.name), v.hex))
    colors_body = (
        "<table><tr><th></th><th>token</th><th>css var</th><th>hex</th></tr>"
        + "".join(rows)
        + "</table>"
    )

    sp_rows = []
    for f in dataclasses.fields(t.spacing):
        v = getattr(t.spacing, f.name)
        sp_rows.append(
            f"<tr><td><code>{f.name}</code></td><td><code>{v}</code></td></tr>"
        )
    for f in dataclasses.fields(t.radii):
        sp_rows.append(
            f"<tr><td><code>radius.{f.name}</code></td>"
            f"<td><code>{getattr(t.radii, f.name)}px</code></td></tr>"
        )
    sp_rows.append(
        f"<tr><td><code>grid_alpha</code></td><td><code>{t.grid_alpha}/255</code></td></tr>"
    )
    spacing_body = (
        "<table><tr><th>token</th><th>value</th></tr>" + "".join(sp_rows) + "</table>"
    )

    typo_body = (
        f"<p style='font-size:var(--vs-font-small)'>--vs-font-small ({t.typography.small_px}px) — "
        "readout 列見出し等の縮小ラベル</p>"
        "<p>本文フォントは OS 既定 (トークン未導入・spec §1)</p>"
    )

    return {
        "tokens/colors.html": _card(
            f"Tokens / {theme_label}", "Colors", colors_body, t
        ),
        "tokens/spacing.html": _card(
            f"Tokens / {theme_label}", "Spacing / Radii", spacing_body, t
        ),
        "tokens/typography.html": _card(
            f"Tokens / {theme_label}", "Typography", typo_body, t
        ),
    }


def build_ground_truth_card(name: str, png_bytes: bytes, theme_label: str) -> str:
    import base64

    uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    return (
        f'<!-- @dsCard group="Ground Truth / {theme_label}" -->\n'
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">\n'
        f"<title>{name}</title>\n"
        "<style>body{margin:0;background:#111}img{max-width:100%;display:block}</style>\n"
        f'</head><body>\n<img alt="{name}" src="{uri}">\n</body></html>\n'
    )


def build_icons_card(t: ThemeTokens, theme_label: str) -> str:
    """Icons カード — SVG 生テキストを埋め込み currentColor は CSS 継承で解決
    (Qt 非依存・spec §12.2)。Normal/Disabled をトークン var で並置する。"""
    from valisync.gui.theme.icons import ICONS, ICONS_DIR

    rows: list[str] = []
    for name, rel in sorted(ICONS.items()):
        svg = (ICONS_DIR / rel).read_text(encoding="utf-8")
        source = rel.split("/")[0]
        rows.append(
            "<tr>"
            f"<td><code>{name}</code></td>"
            f"<td><span style='color: var(--vs-color-chrome-text)'>{svg}</span></td>"
            f"<td><span style='color: var(--vs-color-chrome-disabled-text)'>{svg}</span></td>"
            f"<td><code>{source}</code></td>"
            "</tr>"
        )
    body = (
        "<table><tr><th>name</th><th>Normal</th><th>Disabled</th><th>出所</th></tr>"
        + "".join(rows)
        + "</table>"
        "<p>着色は実行時に currentColor をトークンへ置換 (theme/icons.py)。"
        "本カードは CSS 継承で同じトークンを解決している。</p>"
    )
    return _card(f"Icons / {theme_label}", "Icons", body, t)


def build_manifest(
    sha: str, tokens_json: str, paths: list[str], theme_label: str
) -> str:
    import hashlib

    digest = hashlib.sha256(tokens_json.encode("utf-8")).hexdigest()
    items = "".join(f"<li><code>{p}</code></li>" for p in sorted(paths))
    return (
        f'<!-- @dsCard group="Meta / {theme_label}" -->\n'
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8"><title>Sync Manifest</title>\n'
        "<style>body{font-family:sans-serif;font-size:13px;margin:16px}</style>\n"
        "</head><body>\n<h2>Sync Manifest</h2>\n"
        f"<p>git SHA: <code>{sha}</code></p>\n"
        f"<p>tokens.json sha256: <code>{digest}</code></p>\n"
        f"<ul>{items}</ul>\n</body></html>\n"
    )
