"""GraphPanelView の Global_Cursor 配線 (R15) -- Layer B (headless).

実 OS 入力・カーソル線の実ドラッグは Layer C (tests/realgui/test_global_cursor.py) で検証。
ここでは VM 連携・アイテム可視・凡例撤去をヘッドレスで確認する。
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.interpolation import InterpolationMethod
from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView


def _vm_with_signal(tmp_path: Path) -> GraphPanelVM:
    csv_file = tmp_path / "d.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "s1"])
        for i in range(100):
            w.writerow([i * 0.01, float(i)])
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    session = Session()
    session.load(csv_file, fmt)
    # Use the namespaced signal name (e.g. "csv_1::s1"), not the group key.
    signal_key = session.signals()[0].name
    vm = GraphPanelVM(session)
    vm.add_signal(signal_key)
    return vm


def test_setting_cursor_shows_line_and_readout(qtbot: QtBot, tmp_path: Path) -> None:
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    assert not view.cursor_line_visible()  # no cursor set yet

    vm.set_cursor(0.5)

    assert view.cursor_line_visible()
    assert view.cursor_line_value() == 0.5
    assert view.readout_visible()
    assert vm.cursor_readings()[0].value is not None


def test_clearing_cursor_hides_line_and_readout(qtbot: QtBot, tmp_path: Path) -> None:
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    vm.set_cursor(0.5)
    vm.set_cursor(None)
    assert not view.cursor_line_visible()
    assert not view.readout_visible()


def test_readout_position_preserved_on_cursor_update(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Readout snaps to (8,8) only on first show; subsequent cursor syncs must not
    reset a user-dragged position.  Clearing and re-setting the cursor resets to (8,8).
    """
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)

    # First cursor placement — readout should appear at (8,8).
    vm.set_cursor(0.5)
    assert view.readout_visible()
    assert view._readout.pos().x() == 8
    assert view._readout.pos().y() == 8

    # Simulate a user drag by moving the readout to a different position.
    view._readout.move(100, 50)
    assert view._readout.pos().x() == 100

    # Update cursor to a new value (readout stays visible) — position must NOT snap back.
    vm.set_cursor(0.7)
    assert view._readout.pos().x() == 100
    assert view._readout.pos().y() == 50

    # Clear cursor and set again — readout must return to (8,8) on re-appearance.
    vm.set_cursor(None)
    assert not view.readout_visible()
    vm.set_cursor(0.3)
    assert view.readout_visible()
    assert view._readout.pos().x() == 8
    assert view._readout.pos().y() == 8


def test_legend_item_removed(qtbot: QtBot, tmp_path: Path) -> None:
    # Legend was removed in R15; GraphPanelView must not have _legend attribute.
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    assert not hasattr(view, "_legend")


def test_context_menu_has_interp_methods(qtbot: QtBot, tmp_path: Path) -> None:
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    menu = view.build_context_menu()
    labels = [a.text() for a in menu.actions()]
    assert any("補間" in label for label in labels)


# --- Layer B: interp menu via real contextMenuEvent path ---


def test_context_menu_event_real_path_interp_triggers_vm(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QContextMenuEvent -> contextMenuEvent -> build_context_menu real path.

    Spy build_context_menu to prevent modal .exec() while capturing the real
    menu; then trigger a submenu action and verify vm.set_interp_method is called.
    Layer B: validates the contextMenuEvent routing, not just a direct call.
    """
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)

    captured: dict = {}
    real_build = view.build_context_menu

    def spy_build() -> object:
        menu = real_build()
        captured["menu"] = menu
        # Return a mock so .exec() is a no-op (prevents modal dialog in headless).
        m = Mock()
        m.exec = Mock(return_value=None)
        return m

    # Use monkeypatch so the spy is auto-reverted after the test.
    monkeypatch.setattr(view, "build_context_menu", spy_build)

    pos = QPoint(view.width() // 2, view.height() // 2)
    global_pos = view.mapToGlobal(pos)
    QApplication.sendEvent(
        view,
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, global_pos),
    )

    assert "menu" in captured, "build_context_menu must be called via contextMenuEvent"
    menu = captured["menu"]

    # Find the submenu for interpolation method selection.
    interp_action = None
    for action in menu.actions():
        if "補間" in action.text() and action.menu() is not None:
            interp_action = action
            break
    assert interp_action is not None, "interp submenu not found in context menu"

    # Trigger "前値保持" and verify vm.set_interp_method is called.
    called_with: list[InterpolationMethod] = []
    real_set_interp = vm.set_interp_method
    monkeypatch.setattr(
        vm,
        "set_interp_method",
        lambda m: called_with.append(m) or real_set_interp(m),  # type: ignore[return-value]
    )

    submenu = interp_action.menu()
    assert submenu is not None
    zoh_action = next((a for a in submenu.actions() if "前値保持" in a.text()), None)
    assert zoh_action is not None, "前値保持 action not found"
    zoh_action.trigger()

    assert called_with == [InterpolationMethod.ZERO_ORDER_HOLD]


# --- R16/R17: context menu cursor toggles, B line, click-place removal ---


def test_context_menu_has_cursor_toggles(qtbot: QtBot, tmp_path: Path) -> None:
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    menu = view.build_context_menu()
    labels = [a.text() for a in menu.actions()]
    assert "メインカーソル" in labels
    assert "サブカーソル（Δ）" in labels  # noqa: RUF001


def test_sub_toggle_disabled_until_main_on(qtbot: QtBot, tmp_path: Path) -> None:
    vm = _vm_with_signal(tmp_path)
    vm.x_range = (0.0, 1.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    sub = next(
        a
        for a in view.build_context_menu().actions()
        if a.text() == "サブカーソル（Δ）"  # noqa: RUF001
    )
    assert sub.isEnabled() is False  # main OFF → sub disabled
    vm.toggle_main_cursor(True)
    sub2 = next(
        a
        for a in view.build_context_menu().actions()
        if a.text() == "サブカーソル（Δ）"  # noqa: RUF001
    )
    assert sub2.isEnabled() is True


def test_context_menu_real_path_builds_menu(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real contextMenuEvent path builds menu containing cursor toggles (Layer B).

    Mirrors test_context_menu_event_real_path_interp_triggers_vm: spy on
    build_context_menu to capture the live menu object while returning a Mock
    so contextMenuEvent's .exec() call is a no-op (avoids modal hang in headless).
    """
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)

    captured: dict = {}
    real_build = view.build_context_menu

    def spy_build() -> object:
        menu = real_build()
        captured["menu"] = menu
        m = Mock()
        m.exec = Mock(return_value=None)
        return m

    monkeypatch.setattr(view, "build_context_menu", spy_build)

    pos = QPoint(view.width() // 2, view.height() // 2)
    QApplication.sendEvent(
        view,
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, view.mapToGlobal(pos)),
    )

    assert "menu" in captured, "build_context_menu must be called via contextMenuEvent"
    labels = [a.text() for a in captured["menu"].actions()]
    assert "メインカーソル" in labels


def test_toggling_main_then_delta_shows_both_lines(
    qtbot: QtBot, tmp_path: Path
) -> None:
    vm = _vm_with_signal(tmp_path)
    vm.x_range = (0.0, 1.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    vm.toggle_main_cursor(True)
    assert view.cursor_line_visible()
    assert not view.delta_line_visible()
    vm.toggle_delta(True)
    assert view.delta_line_visible()
    assert view.delta_line_value() == pytest.approx(0.75)


def test_delta_line_survives_axis_rebuild(qtbot: QtBot, tmp_path: Path) -> None:
    """Layer B: 実際の軸構造リビルドを跨いで A/B カーソル線が生存する回帰防止。

    set_column_count は signature を変え _reconcile_axes のスローパス (master
    ViewBox を作り直し、カーソル線を detach -> 再アタッチ) を強制する。delta 表示中
    の rebuild で B 線が消える/未同期になる回帰を捕捉する。
    """
    vm = _vm_with_signal(tmp_path)
    vm.x_range = (0.0, 1.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    vm.toggle_main_cursor(True)
    vm.toggle_delta(True)
    assert view.delta_line_visible()
    a_before = view.cursor_line_value()
    b_before = view.delta_line_value()
    vb_before = id(view._view_boxes[0])

    # signature を変えてスローパス (実リビルド) を強制。set_column_count は "axes"
    # を notify し _on_vm_change -> refresh() を通る。
    vm.set_column_count(vm.column_count + 1)

    # master ViewBox が実際に作り直された (ファストパス早期 return ではない) こと。
    # これが無いと scene assertion は detach されず自明に通り、false-green になる。
    assert id(view._view_boxes[0]) != vb_before
    assert view.cursor_line_visible()
    assert view.delta_line_visible()  # B 線は rebuild を生き延びる
    assert view.cursor_line_value() == pytest.approx(a_before)
    assert view.delta_line_value() == pytest.approx(b_before)
    # detach 後、新しい master ViewBox に再アタッチ済み (scene が None でない)。
    assert view._cursor_line.scene() is not None
    assert view._cursor_line_b.scene() is not None


def test_plot_click_no_longer_places_cursor(qtbot: QtBot, tmp_path: Path) -> None:
    """R15 改訂: 空クリック設置は撤去。属性も挙動も無い。"""
    vm = _vm_with_signal(tmp_path)
    vm.x_range = (0.0, 1.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    assert not hasattr(view, "_place_cursor_at")
    assert not hasattr(view, "_cursor_press_pos")
    # ZONE_PLOT での press+release でも cursor_t は None のまま
    center = QPointF(view.width() / 2, view.height() / 2)

    def _btn(kind: QMouseEvent.Type) -> QMouseEvent:
        return QMouseEvent(
            kind,
            center,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    view.mousePressEvent(_btn(QMouseEvent.Type.MouseButtonPress))
    view.mouseReleaseEvent(_btn(QMouseEvent.Type.MouseButtonRelease))
    assert vm.cursor_t is None


# Layer B wiring tests: guard that toggled(bool) actually reaches vm methods
def test_main_toggle_action_drives_vm(qtbot: QtBot, tmp_path: Path) -> None:
    vm = _vm_with_signal(tmp_path)
    vm.x_range = (0.0, 1.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    main = next(
        a for a in view.build_context_menu().actions() if a.text() == "メインカーソル"
    )
    main.setChecked(True)  # fires toggled(True) → vm.toggle_main_cursor(True)
    assert vm.cursor_t == pytest.approx(0.5)


def test_sub_toggle_action_drives_vm(qtbot: QtBot, tmp_path: Path) -> None:
    vm = _vm_with_signal(tmp_path)
    vm.x_range = (0.0, 1.0)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    vm.toggle_main_cursor(True)  # main on → sub enabled
    sub = next(
        a
        for a in view.build_context_menu().actions()
        if a.text() == "サブカーソル（Δ）"  # noqa: RUF001
    )
    sub.setChecked(True)  # fires toggled(True) → vm.toggle_delta(True)
    assert vm.delta_enabled is True
    assert vm.cursor_t_b == pytest.approx(0.75)
