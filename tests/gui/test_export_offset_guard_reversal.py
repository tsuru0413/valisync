"""反転したオフセットガード (E-4b Task 3・spec §5.6 [I5])。

既存 `test_export_csv_dialog.py` の I2 系 6 本は **legacy 経路** (`offset_for`
のみ注入) を固定している。本ファイルは prod 経路 (`offset_keys` 注入) を固定し、
さらに「同じシナリオで両経路が同じ答えを出す」ことを直接突き合わせる —
二経路になった時点で、片方だけ壊れて緑、が最も出やすい壊れ方になる。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui.test_export_selection_order import _AppVM
from valisync.gui.views.export_csv_dialog import ExportCsvDialog


def _dlg(qtbot: QtBot, offsets: dict[str, float], *, fast: bool) -> ExportCsvDialog:
    kwargs: dict[str, object] = {
        "x_range": (2.0, 9.0),
        "cursor_a": 3.0,
        "cursor_b": 6.0,
        "offset_for": lambda k: offsets.get(k, 0.0),
    }
    if fast:
        kwargs["offset_keys"] = lambda: list(offsets)
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set(), **kwargs)  # type: ignore[arg-type]
    qtbot.addWidget(dlg)
    return dlg


@pytest.mark.parametrize("fast", [True, False], ids=["fast", "legacy"])
def test_select_all_trips_the_guard_for_a_container_column(
    qtbot: QtBot, fast: bool
) -> None:
    """コンテナ行の **未展開の列** にオフセットがあっても一括選択で作動する。

    fast 経路では `_row_of_key("mf4_1::Mat[1]")` の最長一致が `mf4_1::Mat` 行へ
    落ちて ALL で即 True になる (列名を作らない)。
    """
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 1.0}, fast=fast)
    assert dlg._range_visible.isEnabled() is True

    dlg._select_all()

    assert dlg._range_visible.isEnabled() is False
    assert dlg._range_cursor.isEnabled() is False


@pytest.mark.parametrize("fast", [True, False], ids=["fast", "legacy"])
def test_guard_releases_on_deselect_all(qtbot: QtBot, fast: bool) -> None:
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 1.0}, fast=fast)
    dlg._select_all()
    # in-test positive control: ガードが**一度も作動していない**実装でも
    # 「解除したら有効」は自明に緑になる。作動状態を先に観測してから解除する。
    assert dlg._range_visible.isEnabled() is False

    dlg._select_none()

    assert dlg._range_visible.isEnabled() is True
    assert dlg._range_cursor.isEnabled() is True


@pytest.mark.parametrize("fast", [True, False], ids=["fast", "legacy"])
def test_guard_is_not_overprotective_for_unselected_offsets(
    qtbot: QtBot, fast: bool
) -> None:
    """オフセット信号を **選ばなければ** ラジオは有効のまま (Option B ではない)。"""
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 1.0}, fast=fast)
    for row in dlg._iter_rows():
        dlg._tree.expandItem(row)
    leaf = next(
        c
        for c in dlg._iter_children()
        if c.data(0, Qt.ItemDataRole.UserRole) == "csv_1::alpha"
    )

    leaf.setCheckState(0, Qt.CheckState.Checked)

    assert dlg._range_visible.isEnabled() is True


@pytest.mark.parametrize("fast", [True, False], ids=["fast", "legacy"])
def test_partial_row_distinguishes_the_offset_column_from_its_siblings(
    qtbot: QtBot, fast: bool
) -> None:
    """PARTIAL の行では **その列** を選んだときだけ作動する (行単位に丸めない)。

    fast 経路の `_selection_touches` が ALL 早期 return だけで済ませ、PARTIAL の
    列 index 照合を落とすと Mat[0] を選んだだけで作動して RED。
    """
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 1.0}, fast=fast)
    for row in dlg._iter_rows():
        dlg._tree.expandItem(row)
    leaves = {
        c.data(0, Qt.ItemDataRole.UserRole): c
        for c in dlg._iter_children()
        if c.data(0, Qt.ItemDataRole.UserRole) is not None
    }

    leaves["mf4_1::Mat[0]"].setCheckState(0, Qt.CheckState.Checked)
    assert dlg._range_visible.isEnabled() is True

    leaves["mf4_1::Mat[1]"].setCheckState(0, Qt.CheckState.Checked)
    assert dlg._range_visible.isEnabled() is False


def test_file_offset_group_key_trips_the_guard(qtbot: QtBot) -> None:
    """ファイルオフセット (グループキー) も交差判定の対象 (fast 経路のみの形)。

    legacy 経路は `offset_for(列キー)` が合成値を返すので同じ答えになるが、
    fast 経路はグループキーを受け取るので、`_selection_touches` が
    「セパレータ無し = そのファイルの選択有無」を扱えないと素通しになる。
    """
    dlg = _dlg(qtbot, {"mf4_1": 1.0}, fast=True)
    assert dlg._range_visible.isEnabled() is True

    dlg._select_all()

    assert dlg._range_visible.isEnabled() is False


def test_zero_net_offset_is_not_an_offset(qtbot: QtBot) -> None:
    """相殺して 0 のキーはガードを作動させない (`offset_for` が値オラクル)。"""
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 0.0}, fast=True)

    dlg._select_all()

    assert dlg._range_visible.isEnabled() is True
