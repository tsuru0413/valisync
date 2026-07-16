"""デザイントークンのエクスポート CLI (spec §5・増分2).

theme/export.py (純粋コア) の出力を design_export/ へ書き出す薄い層。
使い方:
    uv run python scripts/export_design_tokens.py --theme dark
    uv run python scripts/export_design_tokens.py --theme light
    (--out design_export・--theme dark が既定。--screenshots は
     design_export/screenshots_catalog_{theme} が既定。出力先は design_export/{theme}/。
     --sha 省略時は git rev-parse --short HEAD)
"""

from __future__ import annotations

import argparse
import shutil
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
    parser.add_argument("--screenshots", type=Path, default=None)
    parser.add_argument("--theme", choices=["dark", "light"], default="dark")
    parser.add_argument("--sha", default=None)
    args = parser.parse_args()
    args.screenshots = args.screenshots or (
        args.out / f"screenshots_catalog_{args.theme}"
    )

    from valisync.gui.theme import export
    from valisync.gui.theme.tokens import DARK, LIGHT

    theme_label = "Light" if args.theme == "light" else "Dark"
    t = LIGHT if args.theme == "light" else DARK

    if args.sha:
        sha = args.sha
    else:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        sha = proc.stdout.strip()
        if proc.returncode != 0 or not sha:
            print(
                f"git rev-parse --short HEAD 失敗 (exit {proc.returncode}): "
                f"{proc.stderr.strip()}",
                file=sys.stderr,
            )
            return 2

    root = args.out / args.theme

    # 自出力の purge — 改名/削除時の陳腐化ファイル残留(ゴーストカード)を防ぐ。
    # root (自テーマ subtree) 配下のみ消す: 他テーマ subtree・--screenshots
    # (撮影成果物) は --out 直下の兄弟のため巻き込まない。
    for sub in ("tokens", "cards", "proposals", "ground_truth", "meta"):
        shutil.rmtree(root / sub, ignore_errors=True)
    for top in ("tokens.css", "tokens.json"):
        (root / top).unlink(missing_ok=True)

    written: list[str] = []

    _write(root / "tokens.css", export.build_css(t))
    written.append("tokens.css")
    tokens_json = export.build_json(t)
    _write(root / "tokens.json", tokens_json)
    written.append("tokens.json")

    for rel, html in export.build_token_cards(t, theme_label).items():
        _write(root / rel, html)
        written.append(rel)

    cards_dir = REPO / "design" / "cards"
    for tpl in sorted(cards_dir.glob("*.html")):
        html = export.inject_tokens_css(tpl.read_text(encoding="utf-8"), t)
        _write(root / "cards" / tpl.name, html)
        written.append(f"cards/{tpl.name}")
    for tpl in sorted((REPO / "design" / "proposals").glob("*.html")):
        html = export.inject_tokens_css(tpl.read_text(encoding="utf-8"), t)
        _write(root / "proposals" / tpl.name, html)
        written.append(f"proposals/{tpl.name}")

    if args.screenshots.is_dir():
        for png in sorted(args.screenshots.glob("*.png")):
            html = export.build_ground_truth_card(
                png.stem, png.read_bytes(), theme_label
            )
            _write(root / "ground_truth" / f"{png.stem}.html", html)
            written.append(f"ground_truth/{png.stem}.html")
    else:
        print(
            f"screenshots 不在: {args.screenshots} — Ground Truth はスキップ",
            file=sys.stderr,
        )

    _write(
        root / "meta" / "manifest.html",
        export.build_manifest(sha, tokens_json, written, theme_label),
    )
    written.append("meta/manifest.html")
    print(f"exported {len(written)} files -> {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
