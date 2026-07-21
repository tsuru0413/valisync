"""オフスケールバッジのテスト (Task 7・spec §3.6・UX-03 の手動側)。

- Layer A: 判定純関数 ``offscale_directions`` (レンジ完全外れの方向)。
- Layer B: view 統合 — 手動レンジ + レンジ外曲線でバッジ表示・クリックで
  ``reset_axis_y`` (実クリックは Task 9 の realgui)。
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui.test_graph_panel_view import _keys, _loaded_session, _make_view
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView
from valisync.gui.views.offscale_badge import OffscaleBadge, offscale_directions

# ─── Layer A: 判定純関数 ──────────────────────────────────────────────────────


def test_offscale_above_and_below() -> None:
    assert offscale_directions((0.0, 10.0), [(20.0, 30.0)]) == (True, False)
    assert offscale_directions((0.0, 10.0), [(-9.0, -1.0)]) == (False, True)
    assert offscale_directions((0.0, 10.0), [(20.0, 30.0), (-9.0, -1.0)]) == (
        True,
        True,
    )


def test_partial_clip_and_inside_are_not_offscale() -> None:
    # 部分クリップはレンジ内に手掛かりが残る — バッジ対象外 (spec §3.6)。
    assert offscale_directions((0.0, 10.0), [(5.0, 30.0)]) == (False, False)
    assert offscale_directions((0.0, 10.0), [(1.0, 9.0)]) == (False, False)


def test_none_windows_are_ignored() -> None:
    # X 窓内サンプル無し / 全 NaN は「フィットしても見えない」ため通知は嘘になる。
    assert offscale_directions((0.0, 10.0), [None, None]) == (False, False)


def test_range_order_is_normalized() -> None:
    # y_range は (hi, lo) 逆順で渡っても min/max で正規化する (手動 set_axis_range は
    # 昇順化するが純関数は入力順に依存しない — 契約を明示)。
    assert offscale_directions((10.0, 0.0), [(20.0, 30.0)]) == (True, False)
    assert offscale_directions((10.0, 0.0), [(-9.0, -1.0)]) == (False, True)


def test_boundary_touching_is_not_offscale() -> None:
    # 境界に接するだけ (w[0]==hi / w[1]==lo) はレンジ内 — 厳密な外れのみ通知。
    assert offscale_directions((0.0, 10.0), [(10.0, 20.0)]) == (False, False)
    assert offscale_directions((0.0, 10.0), [(-10.0, 0.0)]) == (False, False)


# ─── Layer B: view 統合 ───────────────────────────────────────────────────────


@pytest.fixture
def built_view_two_units(
    qtbot: QtBot, tmp_path: Path
) -> tuple[GraphPanelView, GraphPanelVM, str, str]:
    """view 構築済み・key_a が既に表示中・key_b は未表示 (Task 6 の同名 fixture を
    ローカル再宣言 — badge テストは unit を使わないので構築のみ再現)。"""
    session, _ = _loaded_session(tmp_path, n_signals=2)
    key_a, key_b = _keys(session)
    vm = GraphPanelVM(session)
    view = cast(GraphPanelView, _make_view(qtbot, vm))
    vm.add_signal(key_a)
    view.refresh()
    return view, vm, key_a, key_b


def _badges(view: GraphPanelView) -> list[OffscaleBadge]:
    return [
        it for it in view.plot_widget.scene().items() if isinstance(it, OffscaleBadge)
    ]


def test_badge_click_calls_reset_axis_y(
    qtbot: QtBot,
    built_view_two_units: tuple[GraphPanelView, GraphPanelVM, str, str],
) -> None:
    view, vm, _key_a, key_b = built_view_two_units
    vm.add_signal(key_b)
    vm.set_axis_range(0, 1000.0, 2000.0)  # 手動化 + 全カーブがレンジ外になる値
    view.refresh()
    badges = _badges(view)
    assert badges  # 表示条件 (Layer A の状態側)
    badges[0].clicked.emit()  # クリック配線の Layer B (実クリックは Task 9)
    assert vm.axes[0].y_is_auto is True


def test_no_badge_while_auto(
    qtbot: QtBot,
    built_view_two_units: tuple[GraphPanelView, GraphPanelVM, str, str],
) -> None:
    # auto 軸 (オートフィット) はレンジがデータを内包するのでバッジは出ない。
    view, vm, _key_a, key_b = built_view_two_units
    vm.add_signal(key_b)
    view.refresh()
    assert vm.axes[0].y_is_auto is True
    assert _badges(view) == []


def test_badge_disappears_after_reset(
    qtbot: QtBot,
    built_view_two_units: tuple[GraphPanelView, GraphPanelVM, str, str],
) -> None:
    # レンジ外 → バッジ有り。クリック (=reset_axis_y) 後はオートフィットで
    # レンジがデータを内包し、次 refresh でバッジが消える。
    view, vm, _key_a, key_b = built_view_two_units
    vm.add_signal(key_b)
    vm.set_axis_range(0, 1000.0, 2000.0)
    view.refresh()
    assert _badges(view)
    vm.reset_axis_y(0)
    view.refresh()
    assert _badges(view) == []
