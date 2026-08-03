"""出力列順の全等号 pin (E-4b Task 3・spec §5.6 [I4] / §10)。

既存 `test_export_csv_dialog.py` の順序被覆は
`test_checked_keys_follow_tree_order_not_hash_order` (単一ファイル) 1 本だけで、
ファイル跨ぎの順序は `set(...) ==` 比較しか無い。`_selected` を
`dict[key, (row, col)]` から `dict[phys_key, ColumnSelection]` へ圧縮すると
**順序の運搬者そのもの** ((row, col) sort) が消えるので、退化形
(チェック順 = dict 挿入順で出す実装) を捕まえる網をここで先に張る。

このファイルは Task 3 の**実装前に緑**でなければならない (現行実装の挙動を
pin する)。緑にならないなら、それは現行実装が既に順序を守っていないという
発見なので、実装を進める前に報告する。
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Signal
from valisync.gui.views.export_csv_dialog import ExportCsvDialog


def _sig(name: str, phys: str) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="CSV",
        bus_type="",
        source_file="",
        metadata={"physical_channel": phys},
    )


class _Session:
    """3 ファイル / 混在幅 (1 列・3 列・2 列) の最小 Session。

    `test_export_csv_dialog._FakeSession` を import しない — あちらは
    「既存テストの契約」であり、こちらが弄れば向こうが動く二重の真実になる。
    列構造の契約 (未登録 = `(display_name,)`) だけを写す。
    """

    def __init__(self) -> None:
        self._groups: dict[str, list[Signal]] = {
            "csv_1": [_sig("csv_1::alpha", "alpha")],
            "mf4_1": [_sig("mf4_1::Mat", "Mat"), _sig("mf4_1::zeta", "zeta")],
            "csv_2": [_sig("csv_2::beta", "beta")],
        }
        self._columns: dict[tuple[str, str], tuple[str, ...]] = {
            ("mf4_1", "Mat"): ("Mat[0]", "Mat[1]", "Mat[2]"),
        }

    def source_name(self, key: str) -> str:
        return f"{key}.file"

    def group_signals(self, key: str) -> list[Signal]:
        return self._groups[key]

    def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]:
        return self._columns.get((key, display_name), (display_name,))

    def has_column(self, key: str, display_name: str) -> bool:
        return self.column_names_of(key, display_name) == (display_name,)

    def resolve_signal(self, key: str) -> Signal | None:
        return _sig(key, key.split("::", 1)[1])


class _AppVM:
    def __init__(self) -> None:
        self.session = _Session()
        # ツリーのファイル順はこのリスト順 — アルファベット順とは**わざと違える**
        # (sorted() 実装が偶然緑になるのを防ぐ)。
        self.loaded_file_keys = ["csv_1", "mf4_1", "csv_2"]


class _WideSession:
    """500 列の物理チャンネル 1 本だけを持つ Session (I1 レビュー指摘用)。

    幅 <= 8 程度の行では CPython の small-int frozenset が偶然昇順に反復する
    (hash(n) == n) ため、上の `_Session` (最大 3 列) では `sorted()` の削除を
    検出できない。500 列という幅そのものが検出器の一部 — 散らした添字を選ぶと
    frozenset の内部反復順が sorted() と食い違う。
    """

    def __init__(self) -> None:
        self._cols = tuple(f"Wide[{i}]" for i in range(500))

    def source_name(self, key: str) -> str:
        return f"{key}.file"

    def group_signals(self, key: str) -> list[Signal]:
        return [_sig("mf4_1::Wide", "Wide")]

    def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]:
        return self._cols

    def has_column(self, key: str, display_name: str) -> bool:
        return False  # 500 列に展開される行 (単一列ではない)

    def resolve_signal(self, key: str) -> Signal | None:
        return _sig(key, key.split("::", 1)[1])


class _WideAppVM:
    def __init__(self) -> None:
        self.session = _WideSession()
        self.loaded_file_keys = ["mf4_1"]


#: ツリー表示順の全列 (ファイル順 -> ローダー順 -> 列順)。
_TREE_ORDER = [
    "csv_1::alpha",
    "mf4_1::Mat[0]",
    "mf4_1::Mat[1]",
    "mf4_1::Mat[2]",
    "mf4_1::zeta",
    "csv_2::beta",
]


def _leaves(dlg: ExportCsvDialog) -> dict[str, QTreeWidgetItem]:
    """列キー -> チェック可能な葉アイテム (全コンテナを展開してから引く)。"""
    for row in dlg._iter_rows():
        dlg._tree.expandItem(row)
    return {
        c.data(0, Qt.ItemDataRole.UserRole): c
        for c in dlg._iter_children()
        if c.data(0, Qt.ItemDataRole.UserRole) is not None
    }


def test_select_all_orders_columns_across_files_by_tree_position(
    qtbot: QtBot,
) -> None:
    """ファイル跨ぎの全等号 pin (既存は set 比較しか無い)。

    ファイルキーの辞書順は csv_1 < csv_2 < mf4_1、列名の辞書順は
    alpha < beta < Mat[0]... なので、`sorted()` 退化・ハッシュ順退化・
    ファイル順無視のいずれも**この 1 本の等号**で落ちる。
    """
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)

    dlg._select_all()

    assert dlg._checked_keys() == _TREE_ORDER


def test_check_order_does_not_leak_into_output_order(qtbot: QtBot) -> None:
    """**チェック順 != ツリー順** (spec §5.6 [I4] の必須ケース)。

    ツリーの逆順にチェックしていく。順序を dict 挿入順 (= チェック順) で
    運ぶ実装はここで `_TREE_ORDER[::-1]` を返して RED になる。
    (row, col) sort も ColumnSelection + ツリー walk も、どちらも緑。
    """
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)
    leaves = _leaves(dlg)

    for key in reversed(_TREE_ORDER):
        leaves[key].setCheckState(0, Qt.CheckState.Checked)

    assert dlg._checked_keys() == _TREE_ORDER


def test_partial_selection_keeps_tree_order_within_and_across_rows(
    qtbot: QtBot,
) -> None:
    """部分選択でも順序はツリー順 (行内の列順まで)。

    列 index を降順にチェックしても `Mat[0], Mat[2]` の順で出る = 行内の順序が
    `frozenset` の反復順 (= 小さい int から、ただし CPython 実装依存) でなく
    **明示 sort / ツリー walk** から来ていることの pin。
    """
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)
    leaves = _leaves(dlg)

    for key in ("csv_2::beta", "mf4_1::Mat[2]", "mf4_1::Mat[0]"):
        leaves[key].setCheckState(0, Qt.CheckState.Checked)

    assert dlg._checked_keys() == ["mf4_1::Mat[0]", "mf4_1::Mat[2]", "csv_2::beta"]


def test_deselect_then_reselect_does_not_move_a_column_to_the_end(
    qtbot: QtBot,
) -> None:
    """外して入れ直しても位置は動かない (挿入順運搬の最も出やすい症状)。"""
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)
    dlg._select_all()
    leaves = _leaves(dlg)

    leaves["csv_1::alpha"].setCheckState(0, Qt.CheckState.Unchecked)
    leaves["csv_1::alpha"].setCheckState(0, Qt.CheckState.Checked)

    assert dlg._checked_keys() == _TREE_ORDER


@pytest.mark.parametrize("bulk", ["file_row", "select_all"])
def test_bulk_paths_produce_tree_order(qtbot: QtBot, bulk: str) -> None:
    """一括経路 (ファイル行 / すべて選択) はどちらもツリー順 `_TREE_ORDER` を出す。

    Minor 7 (task-3-review.md): 旧名 `..._as_individual_checks` は個別チェック
    との比較を示唆していたが、本体は両方の一括経路を `_TREE_ORDER` という
    **リテラル**とだけ比較しており、個別チェック経路は 1 度も駆動しない
    (それは `test_check_order_does_not_leak_into_output_order` 等が別途担う)。
    """
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)

    if bulk == "select_all":
        dlg._select_all()
    else:
        for i in range(dlg._tree.topLevelItemCount()):
            top = dlg._tree.topLevelItem(i)
            assert top is not None
            top.setCheckState(0, Qt.CheckState.Checked)

    assert dlg._checked_keys() == _TREE_ORDER


def test_partial_order_within_a_wide_row_is_sorted_not_frozenset_iteration(
    qtbot: QtBot,
) -> None:
    """500 列の行から散らした添字を選ぶと frozenset の反復順は昇順にならない。

    小さい行 (幅 <= 8 程度) では CPython の small-int frozenset が偶然昇順に
    反復するため、既存の partial-order テストは sorted() の削除に構造的に盲目
    (実測: sorted を消しても 1780 passed)。この幅とこの添字の散らしが
    「明示 sort が要る」ことの唯一の検出器。
    """
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)
    keys = dlg._column_keys(0)
    picked = [82, 130, 201, 288, 347, 411, 499]  # 散らし: 反復順 != sorted
    for c in picked:
        dlg._add_selection(0, c, keys[c])
    assert dlg._checked_keys() == [keys[c] for c in picked]
