"""Layer C 契約ガード: tests/realgui/ の各テストが実 OS 入力で駆動することを CI で強制。

`qtbot.mouseClick`/`keyClick` 等の合成入力(Layer B)を `tests/realgui/` に置き
`@pytest.mark.realgui` を付けて Layer C を騙る false-green を、機械的に防ぐ。
散文の警告(docs/gui-testing-layers.md)だけでは現に見落とされたため、CI で落ちる
ガードとして担保する。本テスト自体は headless(ソースを読むだけ)で CI で常時走る。

Layer C の定義境界は「入力の出所」: 実 OS 入力プリミティブ
(`tests/realgui/_realgui_input.py` の `at`/`key`/`drive_qdrag`)または画面取得
(`grabWindow`)を使うのが Layer C。合成入力しか使わないなら Layer B の偽装。
memory: gui_realgui_synthetic_click_mislabeled_layer_c。
"""

from __future__ import annotations

import re
from pathlib import Path

_REALGUI_DIR = Path(__file__).resolve().parent.parent / "realgui"

# 実 OS 入力プリミティブ(at/key/wheel/drive_qdrag)or 画面取得(grabWindow)を使っていれば
# Layer C とみなす。`\bkey\(` は実 key() にマッチし合成 `qtbot.keyClick(` には
# マッチしない(key の後が Click で ( が来ないため)。
_REAL_INPUT = re.compile(r"\b(?:at|key|wheel|drive_qdrag)\(|\.grabWindow\(")

# 実入力へ未移行の既知合成 realgui。新規追加は禁止・移行して空にするのが目標。
# 2026-07-08: open/export/tab_ui/panel_source_flow を実 OS 入力へ移行し空にした
# (ガード完全厳格化)。以後 tests/realgui/ に合成テストを置くと CI で落ちる。
_KNOWN_SYNTHETIC: set[str] = set()


def _realgui_test_files() -> list[Path]:
    return sorted(_REALGUI_DIR.glob("test_*.py"))


def test_realgui_tests_drive_real_os_input() -> None:
    """realgui テストは実 OS 入力(or grabWindow)を使うこと(allowlist を除く)。"""
    offenders = [
        f.name
        for f in _realgui_test_files()
        if not _REAL_INPUT.search(f.read_text(encoding="utf-8"))
        and f.name not in _KNOWN_SYNTHETIC
    ]
    assert not offenders, (
        f"tests/realgui/ の realgui テストが実 OS 入力(at/key/drive_qdrag)や "
        f"grabWindow を使わず合成入力(qtbot/QTest)に依存している: {offenders}. "
        "tests/realgui/ は Layer C(実 OS 入力). 合成入力の配線検証は tests/gui/(Layer B)へ "
        "移すか、_realgui_input の実入力プリミティブで駆動すること. "
        "詳細: docs/gui-testing-layers.md の Layer C 判定基準."
    )


def test_known_synthetic_allowlist_has_no_stale_entries() -> None:
    """allowlist の項目が実入力化(or 削除)されたら allowlist から外させ debt をゼロへ。"""
    existing = {f.name for f in _realgui_test_files()}
    stale = [
        name
        for name in _KNOWN_SYNTHETIC
        if name not in existing
        or _REAL_INPUT.search((_REALGUI_DIR / name).read_text(encoding="utf-8"))
    ]
    assert not stale, (
        f"_KNOWN_SYNTHETIC の項目が実入力化(or 削除)済み: {stale}. "
        "allowlist から外して Layer C ガードを厳格化してください."
    )
