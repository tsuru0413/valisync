# ruff: noqa: RUF002
"""viewport crop 比較モードのテスト (scripts/compare_screenshots.py --crop-meta を sys.path 経由で import).

合成 PNG＋メタ JSON で crop 一致/不一致の両方向を検証する (文言OS Task7 §Step1・
spec 2026-07-22-incd-strings-os-design.md §6 凍結検証)。honest — 不一致側が
本当に exit 1 になることを確認する（crop 判定が実際に機能している証明）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import compare_screenshots as cs


def _save_png(path: Path, arr: np.ndarray) -> None:
    from PySide6.QtGui import QImage

    h, w, _ = arr.shape
    img = QImage(arr.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888)
    assert img.save(str(path))


def _solid(w: int, h: int, rgb: tuple[int, int, int]) -> np.ndarray:
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[..., 0] = rgb[0]
    arr[..., 1] = rgb[1]
    arr[..., 2] = rgb[2]
    arr[..., 3] = 255
    return arr


def _make_pair(tmp_path: Path) -> tuple[Path, Path]:
    baseline = tmp_path / "baseline"
    after = tmp_path / "after"
    baseline.mkdir()
    after.mkdir()
    return baseline, after


def test_crop_match_ignores_diff_outside_viewport(tmp_path):
    """viewport 矩形内が一致すれば、矩形外の相違 (文言差分相当) があっても exit 0。"""
    baseline, after = _make_pair(tmp_path)
    w, h = 40, 40
    rect = {"x": 10, "y": 10, "w": 10, "h": 10}

    base_img = _solid(w, h, (0, 0, 0))
    base_img[rect["y"] : rect["y"] + rect["h"], rect["x"] : rect["x"] + rect["w"]] = (
        50,
        60,
        70,
        255,
    )
    after_img = base_img.copy()
    # viewport 矩形の外側だけを変える — テキスト差分によるコントロール寸法変化の代替
    after_img[0:5, 0:5] = (255, 0, 0, 255)

    _save_png(baseline / "02_plotted.png", base_img)
    _save_png(after / "02_plotted.png", after_img)
    (after / "02_plotted.viewport.json").write_text(json.dumps(rect), encoding="utf-8")

    rc = cs.main([str(baseline), str(after), "--crop-meta"])
    assert rc == 0


def test_crop_mismatch_fails(tmp_path):
    """viewport 矩形内に相違があれば exit 1 (crop 判定が実際に効いていることの証明)。"""
    baseline, after = _make_pair(tmp_path)
    w, h = 40, 40
    rect = {"x": 10, "y": 10, "w": 10, "h": 10}

    base_img = _solid(w, h, (0, 0, 0))
    after_img = base_img.copy()
    after_img[rect["y"] + 2, rect["x"] + 2] = (200, 10, 10, 255)  # crop 内 1px 相違

    _save_png(baseline / "02_plotted.png", base_img)
    _save_png(after / "02_plotted.png", after_img)
    (after / "02_plotted.viewport.json").write_text(json.dumps(rect), encoding="utf-8")

    rc = cs.main([str(baseline), str(after), "--crop-meta"])
    assert rc == 1


def test_crop_meta_falls_back_to_baseline_viewport_json(tmp_path):
    """after に viewport.json が無く baseline 側にのみあれば、それを流用して crop する。

    旧ベースライン (viewport.json 無し) と新撮影を比較する初回昇格シナリオの逆方向
    (baseline 側にのみメタがある場合) も比較器が扱えることの確認。
    """
    baseline, after = _make_pair(tmp_path)
    w, h = 40, 40
    rect = {"x": 5, "y": 5, "w": 8, "h": 8}

    base_img = _solid(w, h, (10, 20, 30))
    after_img = base_img.copy()
    after_img[0:3, 0:3] = (255, 255, 0, 255)  # crop 外のみ変える

    _save_png(baseline / "02_plotted.png", base_img)
    _save_png(after / "02_plotted.png", after_img)
    (baseline / "02_plotted.viewport.json").write_text(
        json.dumps(rect), encoding="utf-8"
    )

    rc = cs.main([str(baseline), str(after), "--crop-meta"])
    assert rc == 0


def test_crop_meta_skips_states_without_viewport_json(tmp_path):
    """viewport メタが無い状態 (Welcome 等プロット無し) は crop 判定の対象から除外される。"""
    baseline, after = _make_pair(tmp_path)
    w, h = 20, 20
    base_img = _solid(w, h, (0, 0, 0))
    after_img = _solid(w, h, (255, 255, 255))  # 全面相違だが viewport メタが無い

    _save_png(baseline / "01_welcome.png", base_img)
    _save_png(after / "01_welcome.png", after_img)

    rc = cs.main([str(baseline), str(after), "--crop-meta"])
    # 比較対象 0 件 (このケースのみ) は誤って green にしない — 明示的に失敗させる
    assert rc == 2


def test_crop_meta_off_compares_full_image_as_before(tmp_path):
    """--crop-meta 無指定時は従来どおり全面比較 (回帰確認)。"""
    baseline, after = _make_pair(tmp_path)
    w, h = 20, 20
    base_img = _solid(w, h, (0, 0, 0))
    after_img = base_img.copy()
    after_img[0, 0] = (255, 0, 0, 255)

    _save_png(baseline / "01_welcome.png", base_img)
    _save_png(after / "01_welcome.png", after_img)

    rc = cs.main([str(baseline), str(after)])
    assert rc == 1
