"""wheel パッケージングの package-data 検証 (Layer A・恒常防波堤)。

増分5 (アイコン刷新・PR #121) では pyproject の package-data 設定漏れで
editable install では無症状のまま wheel から SVG が黙って落ちる false-green が
実測された (`uv build --wheel` で初めて検出)。それまで wheel/package-data の
専用テストは存在しなかった — 本テストが恒久防波堤として新設 (spec §2.2)。

`uv build --wheel` は本リポジトリ規模で ~7 秒 (計測済み) — 既存の
`slow` マーカー慣行は本リポジトリに存在しないため素の常設テストとする。
"""

from __future__ import annotations

import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = REPO_ROOT / "src" / "valisync" / "gui" / "theme" / "icons"

# Task 1 で新規 vendor した 11 SVG (spec §2.2) — 個別に明示 assert する
# (総 svg 数の同梱チェックだけだと「新規追加分が漏れて既存分だけ入った」
# 退行を集合サイズの偶然一致で見逃しうるため、名前を明示して二重に守る)。
NEW_SVGS = {
    "lucide/circle-x.svg",
    "lucide/triangle-alert.svg",
    "lucide/info.svg",
    "lucide/x.svg",
    "lucide/copy.svg",
    "lucide/panel-left.svg",
    "lucide/panel-left-close.svg",
    "lucide/panel-right.svg",
    "lucide/panel-right-close.svg",
    "lucide/panel-bottom.svg",
    "lucide/panel-bottom-close.svg",
}

# 増分5 (PR #121) が最初に vendor した 4 SVG — wheel-drop バグの実測対象そのもの。
EXISTING_SVGS = {
    "lucide/folder-open.svg",
    "lucide/folder.svg",
    "lucide/save.svg",
    "lucide/download.svg",
}


@pytest.fixture(scope="module")
def wheel_svg_members() -> set[str]:
    """`uv build --wheel` で実際に生成された wheel 内の SVG エントリ一覧。"""
    with tempfile.TemporaryDirectory() as out_dir:
        result = subprocess.run(
            ["uv", "build", "--wheel", "-o", out_dir],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        wheels = list(Path(out_dir).glob("*.whl"))
        assert len(wheels) == 1, wheels

        with zipfile.ZipFile(wheels[0]) as z:
            names = z.namelist()

    prefix = "valisync/gui/theme/icons/"
    return {
        n[len(prefix) :] for n in names if n.startswith(prefix) and n.endswith(".svg")
    }


def test_new_svgs_are_packaged_in_wheel(wheel_svg_members: set[str]):
    """本増分で新規 vendor した 11 SVG が wheel に同梱される。"""
    missing = NEW_SVGS - wheel_svg_members
    assert not missing, f"新規 SVG が wheel から欠落: {sorted(missing)}"


def test_existing_svgs_are_packaged_in_wheel(wheel_svg_members: set[str]):
    """増分5 (PR #121) が最初に vendor した 4 SVG — 過去の false-green の実測対象。"""
    missing = EXISTING_SVGS - wheel_svg_members
    assert not missing, f"既存 SVG が wheel から欠落: {sorted(missing)}"


def test_all_disk_svgs_are_packaged_in_wheel(wheel_svg_members: set[str]):
    """theme/icons/ 配下の全 SVG (glob 発見) が wheel に同梱される (包括防波堤)。"""
    on_disk = {p.relative_to(ICONS_DIR).as_posix() for p in ICONS_DIR.rglob("*.svg")}
    assert on_disk, "theme/icons/ 配下に SVG が見つからない (テスト前提が崩れている)"
    missing = on_disk - wheel_svg_members
    assert not missing, f"ディスク上の SVG が wheel から欠落: {sorted(missing)}"
