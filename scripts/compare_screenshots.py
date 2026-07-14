"""スクショ前後比較 — 凍結検証 (spec §7)。差分ピクセル数と diff 画像を出力。

exit 0 = 全ファイル完全一致 / 1 = 相違あり / 2 = ファイル集合・サイズ不一致。
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline", type=Path)
    p.add_argument("after", type=Path)
    p.add_argument("--diff-out", type=Path, default=None)
    args = p.parse_args()

    names = sorted(f.name for f in args.baseline.glob("*.png"))
    if names != sorted(f.name for f in args.after.glob("*.png")) or not names:
        print("比較対象のファイル集合が不一致または 0 件", file=sys.stderr)
        return 2

    failed = False
    size_mismatch = False
    for name in names:
        a = _load_rgba(args.baseline / name)
        b = _load_rgba(args.after / name)
        if a.shape != b.shape:
            print(f"NG {name}: サイズ不一致 {a.shape} vs {b.shape}")
            size_mismatch = True
            continue
        diff = (a != b).any(axis=2)
        n = int(diff.sum())
        if n == 0:
            print(f"OK {name}: 完全一致")
            continue
        failed = True
        print(f"NG {name}: {n} px 相違")
        if args.diff_out:
            from PySide6.QtGui import QImage

            args.diff_out.mkdir(parents=True, exist_ok=True)
            h, w = diff.shape
            out = np.zeros((h, w, 4), dtype=np.uint8)
            out[..., 3] = 255
            out[diff] = (255, 0, 0, 255)
            QImage(out.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888).save(
                str(args.diff_out / name)
            )
    return 2 if size_mismatch else (1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main())
