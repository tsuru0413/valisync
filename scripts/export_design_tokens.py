"""デザイントークンのエクスポート CLI (spec §5・増分2).

theme/export.py (純粋コア) の出力を design_export/ へ書き出す薄い層。
使い方:
    uv run python scripts/export_design_tokens.py
    (--out design_export --screenshots design_export/screenshots_catalog が既定。
     --sha 省略時は git rev-parse --short HEAD)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "design_export")
    parser.add_argument(
        "--screenshots",
        type=Path,
        default=REPO / "design_export" / "screenshots_catalog",
    )
    parser.add_argument("--sha", default=None)
    args = parser.parse_args()

    from valisync.gui.theme import export
    from valisync.gui.theme.tokens import DARK

    sha = (
        args.sha
        or subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO,
        ).stdout.strip()
    )

    written: list[str] = []

    _write(args.out / "tokens.css", export.build_css(DARK))
    written.append("tokens.css")
    tokens_json = export.build_json(DARK)
    _write(args.out / "tokens.json", tokens_json)
    written.append("tokens.json")

    for rel, html in export.build_token_cards(DARK).items():
        _write(args.out / rel, html)
        written.append(rel)

    cards_dir = REPO / "design" / "cards"
    for tpl in sorted(cards_dir.glob("*.html")):
        html = export.inject_tokens_css(tpl.read_text(encoding="utf-8"), DARK)
        _write(args.out / "cards" / tpl.name, html)
        written.append(f"cards/{tpl.name}")
    for tpl in sorted((REPO / "design" / "proposals").glob("*.html")):
        html = export.inject_tokens_css(tpl.read_text(encoding="utf-8"), DARK)
        _write(args.out / "proposals" / tpl.name, html)
        written.append(f"proposals/{tpl.name}")

    if args.screenshots.is_dir():
        for png in sorted(args.screenshots.glob("*.png")):
            html = export.build_ground_truth_card(png.stem, png.read_bytes())
            _write(args.out / "ground_truth" / f"{png.stem}.html", html)
            written.append(f"ground_truth/{png.stem}.html")
    else:
        print(
            f"screenshots 不在: {args.screenshots} — Ground Truth はスキップ",
            file=sys.stderr,
        )

    _write(
        args.out / "meta" / "manifest.html",
        export.build_manifest(sha, tokens_json, written),
    )
    written.append("meta/manifest.html")
    print(f"exported {len(written)} files -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
