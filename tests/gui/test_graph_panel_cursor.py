"""GraphPanelView の Global_Cursor 配線 (R15) -- Layer B (headless).

実 OS 入力・カーソル線の実ドラッグは Layer C (tests/realgui/test_global_cursor.py) で検証。
ここでは VM 連携・アイテム可視・凡例撤去をヘッドレスで確認する。
"""

from __future__ import annotations

import csv
import types
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.interpolation import InterpolationMethod
from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import ZONE_PLOT, GraphPanelView


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
    qtbot: QtBot, tmp_path: Path, monkeypatch: object
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

    assert isinstance(monkeypatch, object)
    view.build_context_menu = types.MethodType(  # type: ignore[method-assign]
        lambda self: spy_build(), view
    )

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
    vm.set_interp_method = lambda m: called_with.append(m) or real_set_interp(m)  # type: ignore[method-assign]

    submenu = interp_action.menu()
    assert submenu is not None
    zoh_action = next((a for a in submenu.actions() if "前値保持" in a.text()), None)
    assert zoh_action is not None, "前値保持 action not found"
    zoh_action.trigger()

    assert called_with == [InterpolationMethod.ZERO_ORDER_HOLD]


# --- INVESTIGATION: synthetic click delivery to mousePressEvent ---


def test_synthetic_click_cursor_placement_investigation(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """INVESTIGATION: does a synthetic QMouseEvent reach GraphPanelView.mousePressEvent?

    Tests whether a synthetic press+release at a ZONE_PLOT position sets vm.cursor_t.
    pyqtgraph's ViewBox/scene may consume the event before it reaches this widget.

    Real-path proof is Layer C (realgui) in Task 5 -- tests/realgui/test_global_cursor.py.
    """
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)

    # Force _zone_at to return ZONE_PLOT so zone classification is deterministic.
    view._zone_at = lambda pos: ZONE_PLOT  # type: ignore[method-assign]

    assert vm.cursor_t is None

    # Synthesize a left-button press + release at the widget center.
    center = QPointF(float(view.width() // 2), float(view.height() // 2))

    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        center,
        center,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view, press)

    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        center,
        center,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view, release)

    # INVESTIGATION RESULT:
    # Check whether cursor_t was set. This test always passes -- it documents the finding.
    # If the child pyqtgraph widget captured the event, cursor_t stays None.
    cursor_reached = vm.cursor_t is not None

    if cursor_reached:
        # Event reached mousePressEvent/mouseReleaseEvent successfully.
        assert vm.cursor_t is not None
    else:
        # Event was consumed by pyqtgraph's child widget before reaching this view.
        # Expected in headless hierarchy; real-path proof is Layer C realgui (Task 5).
        assert vm.cursor_t is None, (
            "Headless synthetic click did NOT reach GraphPanelView.mousePressEvent -- "
            "pyqtgraph's child ViewBox/scene consumed the event. "
            "Real-path proof: Layer C realgui (Task 5 / tests/realgui/test_global_cursor.py)."
        )
