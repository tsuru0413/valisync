"""スクショ前後比較 — 凍結検証 (spec §7)。差分ピクセル数と diff 画像を出力。

exit 0 = 全ファイル完全一致 / 1 = 相違あり / 2 = ファイル集合・サイズ不一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def _load_rgba(path: Path) -> np.ndarray:
    from PySide6.QtGui import QImage

    img = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
    buf = img.constBits()
    return (
        np.frombuffer(buf, dtype=np.uint8).reshape(img.height(), img.width(), 4).copy()
    )


def _load_viewport_rect(
    preferred_dir: Path, fallback_dir: Path, stem: str
) -> dict[str, int] | None:
    """`{stem}.viewport.json` の矩形 (image-pixel 空間)。

    プロット無し状態 (Welcome 等) はメタが存在せず None。preferred_dir (通常は
    after — 新撮影は必ず持つ) を優先し、無ければ fallback_dir (旧ベースライン等)
    を見る。旧ベースラインには viewport.json が無い場合があり、その際は新撮影の
    矩形をレイアウト不変の前提で流用する運用 (spec §6 凍結検証)。
    """
    for d in (preferred_dir, fallback_dir):
        meta = d / f"{stem}.viewport.json"
        if meta.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            return {k: int(v) for k, v in data.items()}
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline", type=Path)
    p.add_argument("after", type=Path)
    p.add_argument("--diff-out", type=Path, default=None)
    p.add_argument(
        "--crop-meta",
        action="store_true",
        help=(
            "各状態の {name}.viewport.json 矩形のみを比較する (プロット viewport の"
            "機械一致証明)。矩形の外側は無視。メタの無い状態 (プロット無し) は"
            "比較対象から除外する。"
        ),
    )
    args = p.parse_args(argv)

    names = sorted(f.name for f in args.baseline.glob("*.png"))
    if names != sorted(f.name for f in args.after.glob("*.png")) or not names:
        print("比較対象のファイル集合が不一致または 0 件", file=sys.stderr)
        return 2

    failed = False
    size_mismatch = False
    checked = 0
    for name in names:
        a = _load_rgba(args.baseline / name)
        b = _load_rgba(args.after / name)
        if a.shape != b.shape:
            print(f"NG {name}: サイズ不一致 {a.shape} vs {b.shape}")
            size_mismatch = True
            continue

        label = ""
        out_name = name
        if args.crop_meta:
            stem = name[: -len(".png")]
            rect = _load_viewport_rect(args.after, args.baseline, stem)
            if rect is None:
                print(f"SKIP {name}: viewport メタなし (プロット無し状態)")
                continue
            x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
            a = a[y : y + h, x : x + w]
            b = b[y : y + h, x : x + w]
            label = " (viewport crop)"
            out_name = f"{stem}.crop.png"

        checked += 1
        diff = (a != b).any(axis=2)
        n = int(diff.sum())
        if n == 0:
            print(f"OK {name}{label}: 完全一致")
            continue
        failed = True
        print(f"NG {name}{label}: {n} px 相違")
        if args.diff_out:
            from PySide6.QtGui import QImage

            args.diff_out.mkdir(parents=True, exist_ok=True)
            h, w = diff.shape
            out = np.zeros((h, w, 4), dtype=np.uint8)
            out[..., 3] = 255
            out[diff] = (255, 0, 0, 255)
            QImage(out.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888).save(
                str(args.diff_out / out_name)
            )

    if args.crop_meta and checked == 0:
        print("crop-meta: viewport メタを持つ状態が 0 件", file=sys.stderr)
        return 2

    return 2 if size_mismatch else (1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main())
