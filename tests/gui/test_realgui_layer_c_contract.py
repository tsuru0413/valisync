"""Layer C 契約ガード: tests/realgui/ の各テストが実 OS 入力で駆動することを CI で強制。

`qtbot.mouseClick`/`keyClick` 等の合成入力(Layer B)を `tests/realgui/` に置き
`@pytest.mark.realgui` を付けて Layer C を騙る false-green を、機械的に防ぐ。
散文の警告(.claude/skills/gui-verify/)だけでは現に見落とされたため、CI で落ちる
ガードとして担保する。本テスト自体は headless(ソースを読むだけ)で CI で常時走る。

Layer C の定義境界は「入力の出所」: 実 OS 入力プリミティブ
(`tests/realgui/_realgui_input.py` の `at`/`key`/`wheel`/`set_window_pos`/
`drive_qdrag`)または画面取得(`grabWindow`)を使うのが Layer C。
合成入力しか使わないなら Layer B の偽装。
memory: gui_realgui_synthetic_click_mislabeled_layer_c。

**Task 11 レビュー M6 是正**: `real_click_widget`/`double_click` は
`_realgui_input.py` 内でプリミティブ (`at`) を組んだ**共有コンポーズ関数**
(旧: 各 realgui ファイルが `_real_click`/`_real_click_widget` を module-local
に重複実装していた — 重複を解消して共有昇格した)。呼び出し側ファイルの
ソーステキストにはプリミティブが直接現れなくなるため、これらもプリミティブ
と同格の Layer C 証拠として認識する (実体は `_realgui_input.py` 側で
プリミティブへ委譲しているので、判定基準「入力の出所」自体は変わらない)。

**Task 11 再レビュー N4 是正**: 上記 M6 の名前 widen は呼び出しテキストの
正規表現一致だけで判定しており、`real_click_widget`/`double_click` という
**名前**が現れさえすれば Layer C 証拠として認めてしまっていた。これだと
realgui ファイルが `_realgui_input` から import せず同名のローカル合成
スタブ (例: `def real_click_widget(w): qtbot.mouseClick(...)`) を定義して
呼び出しても素通りする — ガードの存在意義 (Layer B の Layer C 偽装を機械的
に落とす) を骨抜きにする抜け道になる。是正: 呼び出し名のマッチを「実際に
`tests.realgui._realgui_input` から import された名前 (エイリアス後の
ローカル束縛名)」の集合へ限定する (`_imported_real_input_names` — AST の
`ImportFrom` ノードだけを見るので、ローカル定義はここに現れない)。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REALGUI_DIR = Path(__file__).resolve().parent.parent / "realgui"
_INPUT_MODULE = "tests.realgui._realgui_input"

# 実 OS 入力プリミティブ(at/key/wheel/set_window_pos/drive_qdrag)、または
# `_realgui_input.py` の共有コンポーズ関数(real_click_widget/double_click —
# 内部でプリミティブへ委譲する)。**この名前が使われているだけでは Layer C
# 証拠にしない** — `_imported_real_input_names` で `_INPUT_MODULE` からの
# import 出所を確認した名前だけを対象にする(N4)。
_PRIMITIVE_NAMES = frozenset(
    {
        "at",
        "key",
        "wheel",
        "set_window_pos",
        "drive_qdrag",
        "real_click_widget",
        "double_click",
    }
)

# 実入力へ未移行の既知合成 realgui。新規追加は禁止・移行して空にするのが目標。
# 2026-07-08: open/export/tab_ui/panel_source_flow を実 OS 入力へ移行し空にした
# (ガード完全厳格化)。以後 tests/realgui/ に合成テストを置くと CI で落ちる。
_KNOWN_SYNTHETIC: set[str] = set()


def _realgui_test_files() -> list[Path]:
    return sorted(_REALGUI_DIR.glob("test_*.py"))


def _imported_real_input_names(path: Path) -> set[str]:
    """`_INPUT_MODULE` から import されたプリミティブ名(エイリアス後のローカル
    束縛名)を返す。ローカルで同名定義された偽装スタブは `ImportFrom` に現れ
    ないためここには含まれない(N4 の核心)。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _INPUT_MODULE:
            for alias in node.names:
                if alias.name in _PRIMITIVE_NAMES:
                    names.add(alias.asname or alias.name)
    return names


def _uses_real_input(path: Path) -> bool:
    """実 OS 入力プリミティブの呼び出し(import 出所を確認済みの名前のみ)、
    または画面取得(grabWindow)を使っていれば True。"""
    text = path.read_text(encoding="utf-8")
    if ".grabWindow(" in text:
        return True
    # `\bkey\(` は実 key() にマッチし合成 `qtbot.keyClick(` にはマッチしない
    # (key の後が Click で ( が来ないため)。
    return any(
        re.search(rf"\b{re.escape(name)}\(", text)
        for name in _imported_real_input_names(path)
    )


def test_realgui_tests_drive_real_os_input() -> None:
    """realgui テストは実 OS 入力(or grabWindow)を使うこと(allowlist を除く)。"""
    offenders = [
        f.name
        for f in _realgui_test_files()
        if not _uses_real_input(f) and f.name not in _KNOWN_SYNTHETIC
    ]
    assert not offenders, (
        f"tests/realgui/ の realgui テストが実 OS 入力(at/key/wheel/set_window_pos/"
        f"drive_qdrag)や grabWindow を使わず合成入力(qtbot/QTest)に依存している、"
        f"または real_click_widget/double_click を名乗るが _realgui_input からの"
        f"import が確認できない: {offenders}. "
        "tests/realgui/ は Layer C(実 OS 入力). 合成入力の配線検証は tests/gui/(Layer B)へ "
        "移すか、_realgui_input の実入力プリミティブで駆動すること. "
        "詳細: .claude/skills/gui-verify/ の Layer C 判定基準."
    )


def test_known_synthetic_allowlist_has_no_stale_entries() -> None:
    """allowlist の項目が実入力化(or 削除)されたら allowlist から外させ debt をゼロへ。"""
    existing = {f.name for f in _realgui_test_files()}
    stale = [
        name
        for name in _KNOWN_SYNTHETIC
        if name not in existing or _uses_real_input(_REALGUI_DIR / name)
    ]
    assert not stale, (
        f"_KNOWN_SYNTHETIC の項目が実入力化(or 削除)済み: {stale}. "
        "allowlist から外して Layer C ガードを厳格化してください."
    )
