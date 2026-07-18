"""増分1: クリック活性化 (Layer B - 合成入力で press→signal→VM の実経路を検証)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui.test_axis_interaction import _ClickEvent
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_area_view import GraphAreaView
from valisync.gui.views.graph_panel_view import GraphPanelView

# ─── Fixtures (module-level: reused by Task 4's frame tests) ────────────────


@pytest.fixture
def session() -> Session:
    return Session()


@pytest.fixture
def panel_view(qtbot: QtBot, session: Session) -> GraphPanelView:
    view = GraphPanelView(GraphPanelVM(session))
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)
    return view


@pytest.fixture
def area_with_two_panels(
    qtbot: QtBot, session: Session
) -> tuple[GraphAreaView, GraphAreaVM]:
    vm = GraphAreaVM(AppViewModel(session))
    area = GraphAreaView(vm, panel_factory=lambda p: GraphPanelView(p))
    qtbot.addWidget(area)
    vm.add_panel(0)
    area.resize(800, 600)
    area.show()
    qtbot.waitExposed(area)
    return area, vm


# ─── Left press activates ────────────────────────────────────────────────────


def test_left_press_on_panel_emits_activate_requested(
    qtbot: QtBot, panel_view: GraphPanelView
) -> None:
    emitted: list[bool] = []
    panel_view.activate_requested.connect(lambda *_: emitted.append(True))
    qtbot.mousePress(
        panel_view, Qt.MouseButton.LeftButton, pos=QPoint(panel_view.width() // 2, 10)
    )
    qtbot.mouseRelease(
        panel_view, Qt.MouseButton.LeftButton, pos=QPoint(panel_view.width() // 2, 10)
    )
    assert emitted  # 左 press で活性化要求が出る


def test_right_press_does_not_emit_activate(
    qtbot: QtBot, panel_view: GraphPanelView
) -> None:
    emitted: list[bool] = []
    panel_view.activate_requested.connect(lambda *_: emitted.append(True))
    qtbot.mousePress(
        panel_view, Qt.MouseButton.RightButton, pos=QPoint(panel_view.width() // 2, 10)
    )
    qtbot.mouseRelease(
        panel_view, Qt.MouseButton.RightButton, pos=QPoint(panel_view.width() // 2, 10)
    )
    assert not emitted  # 右クリックはメニュー専用 (活性化しない)


def test_press_on_second_panel_updates_vm(
    qtbot: QtBot, area_with_two_panels: tuple[GraphAreaView, GraphAreaVM]
) -> None:
    area, vm = area_with_two_panels
    vm.set_active_panel(0, 0)
    second = area.tabs.widget(0).widget(1)  # type: ignore[attr-defined]
    # QSplitter の 2 枚目 GraphPanelView
    qtbot.mousePress(
        second, Qt.MouseButton.LeftButton, pos=QPoint(second.width() // 2, 10)
    )
    qtbot.mouseRelease(
        second, Qt.MouseButton.LeftButton, pos=QPoint(second.width() // 2, 10)
    )
    assert vm.active_panel_index(0) == 1


def test_axis_click_also_activates_panel(
    area_with_two_panels: tuple[GraphAreaView, GraphAreaVM],
) -> None:
    """軸クリック経路 (_AlignedAxisItem.mouseClickEvent) もパネルを活性化する。

    scene 内アイテムへの合成クリックは不安定なため、経路の終端である
    mouseClickEvent をハンドラ経由 (duck-typed _ClickEvent, test_axis_interaction.py
    と同じ流儀) で直接駆動する — _emit_panel_activation を直呼びすると変更対象の
    ハンドラ本体を一切通らずに素通りしてしまうため、実際に変更されたメソッドを
    通す。実クリックは Task 7 の realgui が閉ループで証明する。
    """
    area, vm = area_with_two_panels
    vm.set_active_panel(0, 0)
    second = area.tabs.widget(0).widget(1)  # type: ignore[attr-defined]
    emitted: list[bool] = []
    second.activate_requested.connect(lambda *_: emitted.append(True))
    axis_item = second._y_axes[0]
    ev = _ClickEvent(Qt.MouseButton.LeftButton)
    axis_item.mouseClickEvent(
        ev
    )  # 実ハンドラ経由 (_emit_panel_activation を内部で呼ぶ)
    assert len(emitted) == 1, f"expected exactly one emit, got {len(emitted)}"


def test_axis_right_click_does_not_activate_panel(
    area_with_two_panels: tuple[GraphAreaView, GraphAreaVM],
) -> None:
    """軸右クリック (early-return ガード) は activate_requested を emit しない。"""
    area, vm = area_with_two_panels
    vm.set_active_panel(0, 0)
    second = area.tabs.widget(0).widget(1)  # type: ignore[attr-defined]
    emitted: list[bool] = []
    second.activate_requested.connect(lambda *_: emitted.append(True))
    axis_item = second._y_axes[0]
    ev = _ClickEvent(Qt.MouseButton.RightButton)
    axis_item.mouseClickEvent(ev)
    assert not emitted


# ─── Task 4: アクティブ枠 overlay + 軽量通知経路 ────────────────────────────


def test_active_frame_follows_vm_state(
    qtbot: QtBot, area_with_two_panels: tuple[GraphAreaView, GraphAreaVM]
) -> None:
    area, vm = area_with_two_panels
    first = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    second = area.tabs.widget(0).widget(1)  # type: ignore[attr-defined]
    # add_panel の自動アクティブで panel 1 がアクティブ
    assert second._active_frame.isVisible()
    assert not first._active_frame.isVisible()
    vm.set_active_panel(0, 0)
    assert first._active_frame.isVisible()
    assert not second._active_frame.isVisible()


def test_single_panel_hides_frame(qtbot: QtBot, session: Session) -> None:
    """増分A: パネル1枚なら枠を描かない — DP15「1枚でも枠(一貫性)」を意図的に
    supersede (spec 2026-07-18-active-frame-multi-panel)。1枚時のアクティブは
    自明で枠は情報を運ばず、波形から視線を奪うのみ (UIUX 監査 課題C)。
    追跡/配送 (Add/Export のアクティブ配送) は不変。"""
    vm = GraphAreaVM(AppViewModel(session))
    area = GraphAreaView(vm, panel_factory=lambda p: GraphPanelView(p))
    qtbot.addWidget(area)
    area.show()
    qtbot.waitExposed(area)
    only = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    assert not only._active_frame.isVisible()


def test_frame_does_not_shift_plot_origin(
    qtbot: QtBot, area_with_two_panels: tuple[GraphAreaView, GraphAreaVM]
) -> None:
    """honest-RED: 枠はレイアウト行でなく overlay (memory: 27px hit-test 破壊の再発防止)。"""
    area, _vm = area_with_two_panels
    second = area.tabs.widget(0).widget(1)  # type: ignore[attr-defined]
    assert second._active_frame.isVisible()
    assert second.plot_widget.pos().x() == 0
    assert second.plot_widget.pos().y() == 0


def test_activation_does_not_rebuild_widgets(
    qtbot: QtBot, area_with_two_panels: tuple[GraphAreaView, GraphAreaVM]
) -> None:
    """ "active_panel" 通知は軽量経路 — widget を破棄/再生成しない (参照保持で is 比較)。"""
    area, vm = area_with_two_panels
    first_before = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    second_before = area.tabs.widget(0).widget(1)  # type: ignore[attr-defined]
    vm.set_active_panel(0, 0)
    assert area.tabs.widget(0).widget(0) is first_before  # type: ignore[attr-defined]
    assert area.tabs.widget(0).widget(1) is second_before  # type: ignore[attr-defined]


def test_frame_reapplied_after_rebuild(
    qtbot: QtBot, area_with_two_panels: tuple[GraphAreaView, GraphAreaVM]
) -> None:
    area, vm = area_with_two_panels
    vm.set_active_panel(0, 0)
    vm.add_panel(0)  # "panels" -> _rebuild, 新パネル (index 2) が自動アクティブ
    third = area.tabs.widget(0).widget(2)  # type: ignore[attr-defined]
    assert third._active_frame.isVisible()
    assert not area.tabs.widget(0).widget(0)._active_frame.isVisible()  # type: ignore[attr-defined]


def test_frame_appears_when_second_panel_added(qtbot: QtBot, session: Session) -> None:
    """1→2枚: add_panel (自動アクティブ) で新パネルにのみ枠が出る。"""
    vm = GraphAreaVM(AppViewModel(session))
    area = GraphAreaView(vm, panel_factory=lambda p: GraphPanelView(p))
    qtbot.addWidget(area)
    area.show()
    qtbot.waitExposed(area)
    vm.add_panel(0)
    first = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    second = area.tabs.widget(0).widget(1)  # type: ignore[attr-defined]
    assert second._active_frame.isVisible()
    assert not first._active_frame.isVisible()


def test_frame_disappears_when_second_panel_removed(
    qtbot: QtBot, area_with_two_panels: tuple[GraphAreaView, GraphAreaVM]
) -> None:
    """2→1枚: remove_panel 後は残パネルがアクティブでも枠なし。"""
    area, vm = area_with_two_panels
    vm.remove_panel(0, 1)
    only = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    assert vm.active_panel_index(0) == 0
    assert not only._active_frame.isVisible()
