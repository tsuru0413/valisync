"""GraphPanelView の Global_Cursor 配線 (R15) -- Layer B (headless).

実 OS 入力・カーソル線の実ドラッグは Layer C (tests/realgui/test_global_cursor.py) で検証。
ここでは VM 連携・アイテム可視・凡例撤去をヘッドレスで確認する。
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.interpolation import InterpolationMethod
from valisync.core.models import Delimiter, FormatDefinition, Signal, SignalGroup
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
    """Readout anchors to the plot-area top-left only on first show; subsequent
    cursor syncs must not reset a moved position. Clearing and re-setting the
    cursor re-anchors to the plot area on re-appearance (PC-21).
    """
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)

    # First cursor placement — readout anchors to the plot-area top-left + margin.
    vm.set_cursor(0.5)
    assert view.readout_visible()
    anchor = view._plot_area_top_left()
    assert anchor is not None
    assert view._readout.pos() == QPoint(anchor.x() + 8, anchor.y() + 8)

    # Move the readout elsewhere; a cursor-only update must NOT snap it back.
    view._readout.move(200, 120)
    assert view._readout.pos().x() == 200
    vm.set_cursor(0.7)
    assert view._readout.pos() == QPoint(200, 120)

    # Clear cursor and set again — readout re-anchors to the plot area.
    vm.set_cursor(None)
    assert not view.readout_visible()
    vm.set_cursor(0.3)
    assert view.readout_visible()
    anchor2 = view._plot_area_top_left()
    assert anchor2 is not None
    assert view._readout.pos() == QPoint(anchor2.x() + 8, anchor2.y() + 8)


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
    # Keep the OBJECT reference (not id()): id() is a memory address that CPython
    # reuses once the old ViewBox is freed, so `id(new) != id(old)` flakes (the
    # freed slot is reallocated to the new ViewBox → equal ids → spurious failure
    # seen on CI). Holding the object pins its memory and lets `is not` do a true
    # identity check.
    vb_before = view._view_boxes[0]

    # signature を変えてスローパス (実リビルド) を強制。set_column_count は "axes"
    # を notify し _on_vm_change -> refresh() を通る。
    vm.set_column_count(vm.column_count + 1)

    # master ViewBox が実際に作り直された (ファストパス早期 return ではない) こと。
    # これが無いと scene assertion は detach されず自明に通り、false-green になる。
    assert view._view_boxes[0] is not vb_before
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


# --- Task 5 (LD-07): カーソル readout の value_labels 併記 ---
#
# 直接登録ヘルパは tests/gui/test_graph_panel_vm.py の _register_signal と同じ
# パターン (session._groups.add) — CSV ローダーはまだ value_labels 付き Signal を
# 生成できないため、Session に Signal を直接注入する。


def _register_signal(session: Session, sig: Signal, tmp_path: Path) -> str:
    """*sig* を *session* に直接登録し(ローダーを経由しない)、名前空間化された名前を返す。"""
    key = session._groups.add(
        SignalGroup(
            signals=(sig,),
            source_path=tmp_path / f"{sig.name}.csv",
            file_format="CSV",
            loaded_at=datetime.now(),
        )
    )
    return session.group_signals(key)[0].name


def _enum_signal(session: Session, tmp_path: Path, key_name: str = "TurnSig") -> str:
    """value_labels 付き enum 信号を Session に直接登録するテストヘルパ."""
    sig = Signal(
        name=key_name,
        timestamps=np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64),
        values=np.array([0.0, 1.0, 2.0, 1.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
        metadata={"value_labels": {0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"}},
    )
    return _register_signal(session, sig, tmp_path)


def test_cursor_reading_label_on_exact_integer(tmp_path: Path) -> None:
    """カーソルがサンプル上 (値=1.0 ちょうど) のとき label='LEFT' が付く."""
    session = Session()
    sig_key = _enum_signal(session, tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(sig_key)

    vm.set_cursor(1.0)

    r = next(r for r in vm.cursor_readings() if "TurnSig" in r.name)
    assert r.value == 1.0
    assert r.label == "LEFT"


def test_cursor_reading_no_label_between_samples(tmp_path: Path) -> None:
    """線形補間の中間値 (1.5) には嘘ラベルを付けない."""
    session = Session()
    sig_key = _enum_signal(session, tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(sig_key)
    vm.interp_method = InterpolationMethod.LINEAR

    vm.set_cursor(1.5)

    r = next(r for r in vm.cursor_readings() if "TurnSig" in r.name)
    assert r.value == 1.5
    assert r.label is None


def test_cursor_reading_no_label_without_metadata(tmp_path: Path) -> None:
    """value_labels を持たない通常信号は label=None."""
    session = Session()
    sig = Signal(
        name="Plain",
        timestamps=np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64),
        values=np.array([0.0, 1.0, 2.0, 1.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )
    sig_key = _register_signal(session, sig, tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(sig_key)

    vm.set_cursor(1.0)

    r = next(r for r in vm.cursor_readings() if "Plain" in r.name)
    assert r.value == 1.0
    assert r.label is None


def test_cursor_reading_nan_value_yields_no_label_and_no_crash(tmp_path: Path) -> None:
    """NaN 隣接補間が返す NaN で readout がクラッシュしない (レビュー critical).

    NaN 隣接値の伝播 (Req 12.11) は正規の補間動作 — round(nan) の
    ValueError で cursor_readings() 全体が落ちないことを固定する。
    """
    session = Session()
    sig = Signal(
        name="TurnSig",
        timestamps=np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64),
        values=np.array([0.0, np.nan, 2.0, 1.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
        metadata={"value_labels": {0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"}},
    )
    sig_key = _register_signal(session, sig, tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(sig_key)

    vm.set_cursor(0.5)  # 線形補間: 0 と NaN の間 → NaN が正規に返る

    r = next(r for r in vm.cursor_readings() if "TurnSig" in r.name)
    assert r.label is None
