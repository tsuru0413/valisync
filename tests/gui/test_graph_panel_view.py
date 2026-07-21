"""Tests for GraphPanelView — Task 8.2.

The view is a thin pyqtgraph.PlotWidget wrapper bound to a GraphPanelVM.  It
projects vm.render_data() onto PlotDataItems (one per curve, coloured per the
VM), accepts signal drops (SIGNAL_KEYS_MIME → add_signal),
and reports its pixel width to the VM on resize.  All assertions read the
view's projected state, plus one QWidget.grab() smoke test.

Legend was removed in R15 (Task 4); cursor+readout replace it.

TDD: written before the view exists; all must FAIL first.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QContextMenuEvent, QDropEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition, Signal, SignalGroup
from valisync.core.session import Session
from valisync.gui.adapters.qt_signal_models import encode_signal_keys
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import ZONE_PLOT, ZONE_X_INNER, ZONE_Y_INNER

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv_format(n_signals: int = 1) -> FormatDefinition:
    return FormatDefinition(
        name="fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=n_signals,
        has_header=True,
    )


def _write_csv(path: Path, n_rows: int, n_signals: int) -> Path:
    headers = ["t"] + [f"s{i}" for i in range(1, n_signals + 1)]
    lines = [",".join(headers)]
    for i in range(n_rows):
        t = i * 0.01
        lines.append(
            ",".join([f"{t}"] + [f"{float(i % 50)}" for _ in range(n_signals)])
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _loaded_session(
    tmp_path: Path, n_rows: int = 100, n_signals: int = 1
) -> tuple[Session, str]:
    csv = _write_csv(tmp_path / "data.csv", n_rows, n_signals)
    session = Session()
    key = session.load(csv, _csv_format(n_signals)).key
    return session, key


def _multi_group_session(tmp_path: Path, n_groups: int) -> tuple[Session, list[str]]:
    """Load *n_groups* single-signal files into one Session — one group each.

    Returns the session and the per-group signal keys (``csv_1::s1`` …) in load
    order. Prune tests use this to simulate a real *group* unload
    (``session.remove_group``): prune drops a plotted entry only when its whole
    group is gone (files load/unload atomically), so each prunable signal needs
    its own group — a single multi-signal file cannot express "drop one, keep
    its siblings".
    """
    session = Session()
    keys: list[str] = []
    for i in range(n_groups):
        gkey = session.load(
            _write_csv(tmp_path / f"g{i}.csv", 100, 1), _csv_format(1)
        ).key
        keys.append(
            next(s.name for s in session.signals() if s.name.startswith(f"{gkey}::"))
        )
    return session, keys


def _keys(session: Session) -> list[str]:
    return [s.name for s in session.signals()]


def _make_view(qtbot: QtBot, vm: GraphPanelVM) -> object:
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    return view


def _make_panel_view(qtbot: QtBot, tmp_path: Path) -> object:
    """Minimal single-signal, qtbot-managed GraphPanelView (Grid tests, PC-15)."""
    session, _ = _loaded_session(tmp_path)
    key = _keys(session)[0]
    vm = GraphPanelVM(session)
    view = _make_view(qtbot, vm)
    vm.add_signal(key)
    return view


def _session_with_signals(
    specs: dict[str, tuple[list[float], list[float]]],
) -> tuple[Session, dict[str, str]]:
    """Build a Session with one directly-injected signal per (name, (ts, vs)).

    Mirrors ``_session_with_signals`` in test_graph_panel_multi_axis.py (Task 1)
    — duplicated locally rather than imported to avoid a circular import (that
    module imports helpers FROM this one). Bypasses the CSV loader so callers
    can hand-pick exact values. Returns (session, name_map) since the group key
    SignalGroupManager assigns is auto-generated, not the literal *specs* name.
    """
    session = Session()
    base_dir = Path(__file__).resolve().parent
    name_map: dict[str, str] = {}
    for i, (name, (ts, vs)) in enumerate(specs.items()):
        sig = Signal(
            name=name,
            timestamps=np.array(ts, dtype=np.float64),
            values=np.array(vs, dtype=np.float64),
            file_format="CSV",
            bus_type="",
            source_file="",
        )
        key = session._groups.add(
            SignalGroup(
                signals=(sig,),
                source_path=base_dir / f"_synthetic_{name}_{i}.csv",
                file_format="CSV",
                loaded_at=datetime.now(),
            )
        )
        name_map[name] = session.group_signals(key)[0].name
    return session, name_map


def _build_panel_view_with_axes(qtbot: QtBot) -> object:
    """Two-axis GraphPanelView (axis 0 = s1, axis 1 = s2), qtbot-managed.

    Reuses the shared Layer A/B/C factory (tests/gui/_panel_factory.py) instead
    of hand-rolling a session/VM so this helper stays in sync with how other
    axis-menu tests build their fixture.
    """
    from tests.gui._panel_factory import make_two_axis_panel

    panel = make_two_axis_panel()
    qtbot.addWidget(panel)
    return panel


# ─── Drawing curves ───────────────────────────────────────────────────────────


class TestDrawing:
    def test_adding_signal_draws_curve(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        vm.add_signal(key)

        assert key in view.signal_keys_drawn()  # type: ignore[attr-defined]
        x, y = view.curve_xy(view.entry_id_for(key))  # type: ignore[attr-defined]
        assert len(x) > 0
        assert len(x) == len(y)

    def test_curve_uses_vm_assigned_color(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        vm.add_signal(key)

        expected = vm.inspect()["plotted_signals"][0]["color"]
        assert (
            view.pen_color(view.entry_id_for(key)).lower()  # type: ignore[attr-defined]
            == expected.lower()
        )

    def test_overlay_multiple_signals(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=2)
        k0, k1 = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        vm.add_signal(k0)
        vm.add_signal(k1)

        assert set(view.signal_keys_drawn()) == {k0, k1}  # type: ignore[attr-defined]

    def test_remove_signal_removes_curve(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        vm.add_signal(key)
        vm.remove_signal(key)

        assert key not in view.signal_keys_drawn()  # type: ignore[attr-defined]

    def test_toggle_invisible_hides_curve(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        vm.add_signal(key)
        vm.toggle_visibility(key)

        # render_data omits invisible signals, so no curve is drawn for it.
        assert key not in view.signal_keys_drawn()  # type: ignore[attr-defined]

    def test_unclipped_rendering(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        vm.add_signal(key)

        # Verify that clipToView is False (R4)
        assert view.is_clipped(view.entry_id_for(key)) is False  # type: ignore[attr-defined]


# ─── Empty signal (R8.5) ──────────────────────────────────────────────────────


class TestEmptySignal:
    def test_empty_window_keeps_curve_registered(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        vm.add_signal(key)
        vm.set_x_range(1.0e9, 1.0e9 + 1.0)  # window with no samples

        assert key in view.signal_keys_drawn()  # type: ignore[attr-defined]  # curve still registered
        x, _y = view.curve_xy(view.entry_id_for(key))  # type: ignore[attr-defined]
        # RN-01: 境界サンプルが1点描かれ得るが、窓 [1e9, 1e9+1] 内には無い (可視域外)。
        xs = [] if x is None else list(x)
        assert all(not (1.0e9 <= xv <= 1.0e9 + 1.0) for xv in xs)


# ─── Drag-and-drop sink (R12.4) ────────────────────────────────────────────────


class TestDrop:
    def test_drop_adds_signals_and_draws(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        mime = encode_signal_keys([key])
        event = QDropEvent(
            QPointF(5.0, 5.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)  # type: ignore[attr-defined]

        assert any(p["signal_key"] == key for p in vm.inspect()["plotted_signals"])
        assert key in view.signal_keys_drawn()  # type: ignore[attr-defined]

    def test_first_drop_on_plot_fills_full_height(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Force ZONE_PLOT
        view._zone_at = lambda pos: "plot"  # type: ignore

        mime = encode_signal_keys([key])
        event = QDropEvent(
            QPointF(100.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)  # type: ignore[attr-defined]

        # First signal fills the whole panel — placeholder consumed, no 2nd axis.
        assert len(vm.axes) == 1
        plotted = vm.inspect()["plotted_signals"]
        assert plotted[0]["signal_key"] == key
        assert plotted[0]["axis_index"] == 0
        assert vm.axes[0].height_ratio == 1.0
        assert vm.axes[0].top_ratio == 0.0

    def test_drop_on_y_axis_joins_that_axis(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Force ZONE_Y_INNER and axis index 0
        view._zone_at = lambda pos: "y_inner"  # type: ignore
        view._axis_index_at = lambda pos: 0  # type: ignore

        mime = encode_signal_keys([key])
        event = QDropEvent(
            QPointF(10.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)  # type: ignore[attr-defined]

        # Still 1 axis
        assert len(vm.axes) == 1
        plotted = vm.inspect()["plotted_signals"]
        assert plotted[0]["signal_key"] == key
        assert plotted[0]["axis_index"] == 0

    def test_drop_multiple_signals_on_plot_creates_multiple_axes(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=2)
        k0, k1 = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Force ZONE_PLOT
        view._zone_at = lambda pos: "plot"  # type: ignore

        mime = encode_signal_keys([k0, k1])
        event = QDropEvent(
            QPointF(100.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)  # type: ignore[attr-defined]

        # Two signals -> two equal regions (the placeholder is consumed).
        assert len(vm.axes) == 2
        plotted = vm.inspect()["plotted_signals"]
        assert plotted[0]["axis_index"] == 0
        assert plotted[1]["axis_index"] == 1

        # Verify ratios (1/2 = 0.5)
        for ax in vm.axes:
            assert abs(ax.height_ratio - 0.5) < 1e-6

    def test_drag_enter_accepts_signal_mime(self, qtbot: QtBot, tmp_path: Path) -> None:
        from PySide6.QtGui import QDragEnterEvent

        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        mime = encode_signal_keys([key])
        event = QDragEnterEvent(
            QPointF(5.0, 5.0).toPoint(),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dragEnterEvent(event)  # type: ignore[attr-defined]
        assert event.isAccepted()


# ─── Resize → panel width ──────────────────────────────────────────────────────


class TestResize:
    def test_resize_updates_panel_width(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        view.resizeEvent(QResizeEvent(QSize(640, 480), QSize(800, 600)))  # type: ignore[attr-defined]

        assert vm.panel_width_px == 640


# ─── Screenshot smoke + lifecycle ──────────────────────────────────────────────


class TestSmokeAndLifecycle:
    def test_grab_screenshot_succeeds(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        view.resize(400, 300)  # type: ignore[attr-defined]

        pixmap = view.grab()  # type: ignore[attr-defined]

        assert not pixmap.isNull()
        assert pixmap.width() > 0

    def test_unsubscribes_when_destroyed(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        vm = GraphPanelVM(session)
        from valisync.gui.views.graph_panel_view import GraphPanelView

        view = GraphPanelView(vm)
        # 破棄時 unsubscribe の検証で view を意図的に deleteLater する。qtbot.addWidget で
        # 管理下に置くと teardown が破棄済みオブジェクトを二重削除して RuntimeError になり、
        # その teardown 破綻が次テストの isolation を壊す連鎖エラーを生む。だから登録しない。
        assert len(vm._callbacks) == 1

        view.deleteLater()
        qtbot.wait(50)

        assert len(vm._callbacks) == 0
        vm.set_x_range(0.0, 1.0)  # a notify after destruction must not raise


# ─── entry_id-keyed internals (PC-01 増分2a Task3) ─────────────────────────────


class TestEntryIdAccessors:
    def test_duplicate_signal_key_draws_independent_curves(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        # 同一 signal_key を 2 axis に載せると 2 本独立に描画される (entry_id 化の核心)
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        vm.add_signal(key)
        vm.create_new_axis(key)

        # curve_keys は entry_id 群 (2 本ぶん・重複しない)
        assert len(view.curve_keys()) == 2  # type: ignore[attr-defined]
        assert len(set(view.curve_keys())) == 2  # type: ignore[attr-defined]
        # signal_keys_drawn は signal_key 群 (同名 2 本ぶん)
        assert view.signal_keys_drawn() == [key, key]  # type: ignore[attr-defined]
        # 各 entry のデータを独立に読める
        for eid in view.curve_keys():  # type: ignore[attr-defined]
            x, _y = view.curve_xy(eid)  # type: ignore[attr-defined]
            assert len(x) > 0

    def test_set_color_on_one_entry_repaints_only_it(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        vm.create_new_axis(key)
        e0, e1 = view.curve_keys()  # type: ignore[attr-defined]
        vm.set_color(e1, "#123456")
        view.refresh()  # VM notify 経由でも呼ばれるが、テストは明示的に
        assert view.pen_color(e1).lower() == "#123456"  # type: ignore[attr-defined]
        assert view.pen_color(e0).lower() != "#123456"  # type: ignore[attr-defined]

    def test_entry_id_for_and_signal_keys_drawn(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=2)
        k0, k1 = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(k0)
        vm.add_signal(k1)
        assert set(view.signal_keys_drawn()) == {k0, k1}  # type: ignore[attr-defined]
        eid0 = view.entry_id_for(k0)  # type: ignore[attr-defined]
        assert view.signal_keys_drawn()[view.curve_keys().index(eid0)] == k0  # type: ignore[attr-defined]


# ─── DP16: curve press-hold candidate -> activate (thick pen) or offset drag ──


def _press_event(view: object, p: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        p,
        view.mapToGlobal(p.toPoint()),  # type: ignore[attr-defined]
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _release_event(view: object, p: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        p,
        view.mapToGlobal(p.toPoint()),  # type: ignore[attr-defined]
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _curve_click_setup(qtbot: QtBot, tmp_path: Path) -> tuple[object, int, QPointF]:
    """Build a one-signal panel and locate a widget-space point ON the curve.

    Reused by the DP16 activation tests: each needs a point that _curve_at
    resolves to the sole entry, obtained via its own drawn (x, y) data mapped
    ViewBox -> scene -> widget, so the hit-test tolerance is never guessed at.
    """
    session, _ = _loaded_session(tmp_path, n_signals=1)
    key = _keys(session)[0]
    vm = GraphPanelVM(session)
    view = _make_view(qtbot, vm)
    view.resize(400, 300)  # type: ignore[attr-defined]
    vm.add_signal(key)
    vm.set_x_range(0.0, 1.0)
    view.refresh()  # type: ignore[attr-defined]
    eid = view.curve_keys()[0]  # type: ignore[attr-defined]

    x, y = view.curve_xy(eid)  # type: ignore[attr-defined]
    vb = view._item_vb[eid]  # type: ignore[attr-defined]
    mid = len(x) // 2
    scene_pt = vb.mapViewToScene(QPointF(float(x[mid]), float(y[mid])))
    wpt = view.plot_widget.mapFromScene(scene_pt)  # type: ignore[attr-defined]
    pos = QPointF(view.plot_widget.mapTo(view, wpt))  # type: ignore[attr-defined]
    return view, eid, pos


class _FakeAxisClickEvent:
    """Duck-typed pyqtgraph mouseClickEvent (left button).

    ``_AlignedAxisItem.mouseClickEvent`` only calls ``.button()``, ``.accept()``,
    and ``.ignore()`` on its event argument (it never reads position), so a
    synthetic ``QGraphicsSceneMouseEvent`` is unnecessary — driving the handler
    with this duck-type directly exercises the wiring without a scene-level
    input simulation (Layer B, per the T4-c follow-up honest-layering note).
    """

    def __init__(self, button: Qt.MouseButton) -> None:
        self._button = button
        self.accepted = False
        self.ignored = False

    def button(self) -> Qt.MouseButton:
        return self._button

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class TestCurveActivation:
    """DP16 (spec §7): press holds a candidate; release within startDragDistance
    activates the curve (thick pen + its axis); a move past the threshold instead
    promotes to the R14 offset drag (covered in test_graph_panel_offset_drag.py).
    """

    def test_click_on_curve_activates_it_thick_pen(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        view, eid, pos = _curve_click_setup(qtbot, tmp_path)

        view.mousePressEvent(_press_event(view, pos))  # type: ignore[attr-defined]
        view.mouseReleaseEvent(_release_event(view, pos))  # type: ignore[attr-defined]

        assert view.active_curve_id() == eid  # type: ignore[attr-defined]
        assert view.pen_width(eid) == 2.5  # type: ignore[attr-defined]

    def test_click_within_threshold_does_not_offset(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        view, eid, pos = _curve_click_setup(qtbot, tmp_path)
        before = np.asarray(view.curve_xy(eid)[0]).copy()  # type: ignore[attr-defined]

        view.mousePressEvent(_press_event(view, pos))  # type: ignore[attr-defined]
        view.mouseReleaseEvent(_release_event(view, pos))  # type: ignore[attr-defined]

        after = np.asarray(view.curve_xy(eid)[0])  # type: ignore[attr-defined]
        assert np.array_equal(before, after)

    def test_axis_click_deactivates_curve(self, qtbot: QtBot, tmp_path: Path) -> None:
        # Exercise the same helper _AlignedAxisItem.mouseClickEvent calls (Step 10)
        # rather than the axis scene-click plumbing itself (covered by the
        # existing axis-activation tests) -- this isolates the DP16 deactivation
        # contract: once a curve is active, the axis-click path must clear it.
        view, eid, pos = _curve_click_setup(qtbot, tmp_path)
        view.mousePressEvent(_press_event(view, pos))  # type: ignore[attr-defined]
        view.mouseReleaseEvent(_release_event(view, pos))  # type: ignore[attr-defined]
        assert view.active_curve_id() == eid  # type: ignore[attr-defined]

        view._deactivate_curve()  # type: ignore[attr-defined]

        assert view.active_curve_id() is None  # type: ignore[attr-defined]

    def test_axis_click_event_deactivates_active_curve(self, qtbot: QtBot) -> None:
        """T4-c follow-up: drives ``_AlignedAxisItem.mouseClickEvent`` itself
        (rather than calling ``_deactivate_curve`` directly, as
        ``test_axis_click_deactivates_curve`` above does) so the axis-click ->
        curve-deactivation wiring inside the handler is actually covered — that
        line could previously be deleted without failing any test.
        """
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals(
            {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
        )
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        vm.create_new_axis(keys["csv::b"])  # axis 1
        view = GraphPanelView(vm)
        qtbot.addWidget(view)
        view.show()  # type: ignore[attr-defined]
        qtbot.waitExposed(view)  # type: ignore[attr-defined]

        # 曲線 a (軸0) を活性化 -> 次に軸1を実ハンドラで click
        eid_a = next(e.entry_id for e in vm._plotted if e.signal_key == keys["csv::a"])
        view._activate_curve(eid_a)  # type: ignore[attr-defined]
        assert view._active_curve_id == eid_a  # type: ignore[attr-defined]

        axis1 = view._y_axes[1]  # type: ignore[attr-defined]
        assert axis1._vm_axis_index == 1  # reconcile で設定済み
        axis1.mouseClickEvent(_FakeAxisClickEvent(Qt.MouseButton.LeftButton))

        assert view._active_curve_id is None  # type: ignore[attr-defined]
        assert view._active_axis_index == 1  # type: ignore[attr-defined]

    def test_axis_click_right_button_is_ignored(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals({"csv::a": ([0.0], [1.0])})
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        view = GraphPanelView(vm)
        qtbot.addWidget(view)
        view.show()  # type: ignore[attr-defined]
        qtbot.waitExposed(view)  # type: ignore[attr-defined]

        eid = vm._plotted[0].entry_id
        view._activate_curve(eid)  # type: ignore[attr-defined]

        ev = _FakeAxisClickEvent(Qt.MouseButton.RightButton)
        view._y_axes[0].mouseClickEvent(ev)  # type: ignore[attr-defined]

        assert ev.ignored is True
        assert view._active_curve_id == eid  # type: ignore[attr-defined]  # 右クリックでは解除しない

    def test_h_toggles_active_curve_visibility(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        view.refresh()  # type: ignore[attr-defined]
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        view._active_curve_id = eid  # type: ignore[attr-defined]  # 活性化済みとする
        view.setFocus()  # type: ignore[attr-defined]

        qtbot.keyClick(view, Qt.Key.Key_H)
        assert vm.inspect()["plotted_signals"][0]["visible"] is False
        # H は解除トリガーにしない -> 非表示後も active のまま再表示できる
        assert view.active_curve_id() == eid  # type: ignore[attr-defined]
        qtbot.keyClick(view, Qt.Key.Key_H)
        assert vm.inspect()["plotted_signals"][0]["visible"] is True

    def test_h_falls_back_to_axis_when_no_active_curve(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=2)
        k0, k1 = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(k0)  # axis 0
        vm.add_signal(k1)  # axis 0
        view.refresh()  # type: ignore[attr-defined]
        view._active_curve_id = None  # type: ignore[attr-defined]
        view.set_active_axis(0)  # type: ignore[attr-defined]
        view.setFocus()  # type: ignore[attr-defined]

        qtbot.keyClick(view, Qt.Key.Key_H)
        assert all(not e["visible"] for e in vm.inspect()["plotted_signals"])

    def test_empty_plot_click_deselects_active_axis(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """FU-15a: 曲線のない空プロット面をクリックするとアクティブ Y 軸が解除される
        (_active_axis_index -> None). 空プロットクリックが _deactivate_curve に
        届く既存経路 (mousePressEvent の ZONE_PLOT no-curve 分岐, :1919) に軸解除
        を追加する — 同じ分岐が到達する座標/イベント合成は _curve_click_setup /
        _press_event と同じパターン(widget 空間の QPointF・_press_event 経由の
        QMouseEvent)を流用する。
        """
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        vm.create_new_axis(key)
        view = _make_view(qtbot, vm)
        view.resize(800, 600)  # type: ignore[attr-defined]
        view.show()  # type: ignore[attr-defined]
        qtbot.waitExposed(view)  # type: ignore[attr-defined]
        view.refresh()  # type: ignore[attr-defined]

        view.set_active_axis(0)  # type: ignore[attr-defined]
        assert view._active_axis_index == 0  # type: ignore[attr-defined]

        # 曲線データは row index が中央付近 (i % 50 == 0) で値0付近になる
        # (_write_csv の生成規則) ため、widget 空間でのプロット矩形上端寄りの
        # 中央 x は _curve_at の許容誤差 (CURVE_HIT_TOL_PX) 圏外 = ZONE_PLOT
        # かつ曲線なし、の空点になる。_zone_at と同じ _plot_rect_in_widget()
        # を使って算出するので zone 判定と食い違わない。
        plot_rect = view._plot_rect_in_widget()  # type: ignore[attr-defined]
        empty_pt = QPointF(plot_rect.center().x(), plot_rect.top() + 3)
        assert view._curve_at(empty_pt) is None  # type: ignore[attr-defined]

        view.mousePressEvent(_press_event(view, empty_pt))  # type: ignore[attr-defined]

        assert view._active_axis_index is None, (  # type: ignore[attr-defined]
            "空プロットクリックで軸が解除されていない"
        )


# ─── Task 6: 曲線右クリックメニュー (非表示/色変更/削除) + ルーティング骨格 ────────


def _color_submenu(menu: object) -> tuple[object, object]:
    """Return (action, submenu) for the curve menu's "色変更" entry.

    PySide/shiboken ties a QAction.menu() wrapper's validity to the QAction
    object it was fetched from: chaining ``next(a.menu() for a in ...)`` in a
    single expression discards that QAction the instant next() returns, and
    the returned submenu is then reported "already deleted" on the next
    access -- even though the underlying (Qt-parented) QMenu is still alive.
    Keeping both the action and the submenu alive as separate locals avoids it.
    """
    action = next(a for a in menu.actions() if "色変更" in a.text())  # type: ignore[attr-defined]
    return action, action.menu()  # type: ignore[attr-defined]


class TestCurveContextMenu:
    """PC-01 (spec §4.3, 増分2a サブセット): build_curve_menu の各項目。

    軸移動・オフセット項目は 増分2b のため、ここでは意図的に含まない。
    """

    def test_right_click_on_curve_shows_curve_menu(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        # 曲線位置の右クリックで曲線メニューが構築される (項目内容の検証)
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        view.refresh()  # type: ignore[attr-defined]
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        labels = [a.text() for a in menu.actions() if a.text()]
        assert "非表示" in labels
        assert "削除" in labels
        assert any("色変更" in a.text() for a in menu.actions())

    def test_curve_menu_hide_toggles_visibility(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        view.refresh()  # type: ignore[attr-defined]
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        hide = next(a for a in menu.actions() if a.text() == "非表示")
        hide.trigger()
        assert vm.inspect()["plotted_signals"][0]["visible"] is False

    def test_curve_menu_color_swatch_sets_color(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        # パレットスウォッチのクリック相当 (trigger) が VM の set_color まで届く
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        view.refresh()  # type: ignore[attr-defined]
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        _color_action, color_menu = _color_submenu(menu)
        assert color_menu is not None
        swatch = color_menu.actions()[0]  # type: ignore[attr-defined]  # _PALETTE[0] の hex ラベル
        swatch.trigger()
        assert vm.inspect()["plotted_signals"][0]["color"] == swatch.text()

    def test_curve_menu_delete_removes_entry(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal(key)
        view.refresh()  # type: ignore[attr-defined]
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        view._active_curve_id = eid  # type: ignore[attr-defined]
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        delete = next(a for a in menu.actions() if a.text() == "削除")
        delete.trigger()
        assert vm.inspect()["plotted_signals"] == []
        assert view.active_curve_id() is None  # type: ignore[attr-defined]  # 削除で解除

    def test_curve_menu_custom_color_uses_injected_dialog(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = GraphPanelView(vm, color_dialog_fn=lambda: "#0a0b0c")
        qtbot.addWidget(view)
        vm.add_signal(key)
        view.refresh()  # type: ignore[attr-defined]
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        _color_action, color_menu = _color_submenu(menu)
        other = next(a for a in color_menu.actions() if a.text() == "その他…")  # type: ignore[attr-defined]
        other.trigger()
        assert vm.inspect()["plotted_signals"][0]["color"] == "#0a0b0c"

    def test_custom_color_dialog_cancel_leaves_color_unchanged(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        # DI スタブが None (キャンセル相当) を返すとき _pick_custom_color は
        # set_color を呼ばない (ガード確認)。
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, _ = _loaded_session(tmp_path, n_signals=1)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = GraphPanelView(vm, color_dialog_fn=lambda: None)
        qtbot.addWidget(view)
        vm.add_signal(key)
        view.refresh()  # type: ignore[attr-defined]
        eid = view.curve_keys()[0]  # type: ignore[attr-defined]
        before = vm.inspect()["plotted_signals"][0]["color"]
        menu = view.build_curve_menu(eid)  # type: ignore[attr-defined]
        _color_action, color_menu = _color_submenu(menu)
        other = next(a for a in color_menu.actions() if a.text() == "その他…")  # type: ignore[attr-defined]
        other.trigger()
        assert vm.inspect()["plotted_signals"][0]["color"] == before


def _curve_menu_texts(menu: object) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]  # type: ignore[attr-defined]


class TestCurveMenuAxisMoveAndOffset:
    """新しい軸へ移動・時間オフセット…・オフセットをリセット…・情報行 (増分2b Task 4)。

    signal_key には group-prefix が付く (_session_with_signals の name_map 経由
    で解決済みキーを使う — 文字列リテラル "csv::a" は実キーではない)。
    """

    def test_build_curve_menu_has_axis_move_and_offset_items(
        self, qtbot: QtBot
    ) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals({"csv::a": ([0.0], [1.0])})
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        view = GraphPanelView(vm)
        qtbot.addWidget(view)
        eid = vm._plotted[0].entry_id
        texts = _curve_menu_texts(view.build_curve_menu(eid))
        for expected in (
            "非表示",
            "色変更",
            "削除",
            "新しい軸へ移動",
            "時間オフセット…",
            "オフセットをリセット…",
        ):
            assert expected in texts

    def test_curve_menu_move_to_new_axis_triggers_vm(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals(
            {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
        )
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        vm.add_signal_to_axis(keys["csv::b"], 0)
        view = GraphPanelView(vm)
        qtbot.addWidget(view)
        eid_b = next(e.entry_id for e in vm._plotted if e.signal_key == keys["csv::b"])
        act = next(
            a
            for a in view.build_curve_menu(eid_b).actions()
            if a.text() == "新しい軸へ移動"
        )
        act.trigger()
        assert len(vm.axes) == 2

    def test_curve_menu_reset_disabled_when_no_offset(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals({"csv::a": ([0.0], [1.0])})
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        view = GraphPanelView(vm)
        qtbot.addWidget(view)
        eid = vm._plotted[0].entry_id
        menu = view.build_curve_menu(eid)
        reset_act = next(
            a for a in menu.actions() if a.text() == "オフセットをリセット…"
        )
        assert reset_act.isEnabled() is False
        # 情報行は非ゼロ時のみ → 存在しない
        assert not any(a.text().startswith("オフセット: ") for a in menu.actions())

    def test_curve_menu_reset_enabled_and_info_row_when_offset_applied(
        self, qtbot: QtBot
    ) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals({"csv::a": ([0.0], [1.0])})
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        vm.set_offsets({keys["csv::a"]: 0.5}, {})
        view = GraphPanelView(vm)
        qtbot.addWidget(view)
        eid = vm._plotted[0].entry_id
        menu = view.build_curve_menu(eid)
        reset_act = next(
            a for a in menu.actions() if a.text() == "オフセットをリセット…"
        )
        assert reset_act.isEnabled() is True
        info = next(a for a in menu.actions() if a.text().startswith("オフセット: "))
        assert info.isEnabled() is False
        # 固定小数で表示 (spec §182 の "+0.250s" 形式・sci-notation を避ける)
        assert info.text() == "オフセット: +0.500s"

    def test_curve_menu_offset_input_emits_apply(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals({"csv::a": ([0.0], [1.0])})
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        view = GraphPanelView(
            vm, offset_input_dialog_fn=lambda sk, cur: (0.3, "signal")
        )
        qtbot.addWidget(view)
        eid = vm._plotted[0].entry_id
        emitted: list[tuple[str, float, str]] = []
        view.offset_apply_requested.connect(
            lambda k, dt, sc: emitted.append((k, dt, sc))
        )
        act = next(
            a
            for a in view.build_curve_menu(eid).actions()
            if a.text() == "時間オフセット…"
        )
        act.trigger()
        assert emitted == [(keys["csv::a"], 0.3, "signal")]

    def test_curve_menu_reset_emits_reset(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals({"csv::a": ([0.0], [1.0])})
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        vm.set_offsets({keys["csv::a"]: 0.5}, {})
        view = GraphPanelView(vm, reset_dialog_fn=lambda sk: "signal")
        qtbot.addWidget(view)
        eid = vm._plotted[0].entry_id
        emitted: list[tuple[str, str]] = []
        view.offset_reset_requested.connect(lambda k, sc: emitted.append((k, sc)))
        act = next(
            a
            for a in view.build_curve_menu(eid).actions()
            if a.text() == "オフセットをリセット…"
        )
        act.trigger()
        assert emitted == [(keys["csv::a"], "signal")]


def _shown_curve_click_setup(
    qtbot: QtBot, tmp_path: Path
) -> tuple[object, int, QPointF]:
    """Like ``_curve_click_setup``, but the widget is shown before *pos* is
    computed (mirrors test_graph_panel_offset_drag.py's established real-event
    pattern), since these tests deliver a real ``QContextMenuEvent`` via
    ``QApplication.sendEvent`` rather than calling the handler directly.
    """
    session, _ = _loaded_session(tmp_path, n_signals=1)
    key = _keys(session)[0]
    vm = GraphPanelVM(session)
    view = _make_view(qtbot, vm)
    view.resize(400, 300)  # type: ignore[attr-defined]
    vm.add_signal(key)
    vm.set_x_range(0.0, 1.0)
    view.refresh()  # type: ignore[attr-defined]
    view.show()  # type: ignore[attr-defined]
    qtbot.waitExposed(view)  # type: ignore[attr-defined]
    for _ in range(3):
        QApplication.processEvents()
    eid = view.curve_keys()[0]  # type: ignore[attr-defined]

    x, y = view.curve_xy(eid)  # type: ignore[attr-defined]
    vb = view._item_vb[eid]  # type: ignore[attr-defined]
    mid = len(x) // 2
    scene_pt = vb.mapViewToScene(QPointF(float(x[mid]), float(y[mid])))
    wpt = view.plot_widget.mapFromScene(scene_pt)  # type: ignore[attr-defined]
    pos = QPointF(view.plot_widget.mapTo(view, wpt))  # type: ignore[attr-defined]
    return view, eid, pos


class TestContextMenuRouting:
    """contextMenuEvent の実イベント経路 (sendEvent) でのルーティング検証。

    build_curve_menu/build_context_menu を直接呼ぶだけのテストでは、Step 6 の
    ルーティング条件式 (_curve_at 分岐) 自体が壊れても検出できない
    (false-green)。ここでは実際に QContextMenuEvent を送って「どちらの
    builder が呼ばれたか」を monkeypatch したスパイで検証する。
    """

    def test_curve_position_routes_to_curve_menu(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        view, eid, pos = _shown_curve_click_setup(qtbot, tmp_path)

        curve_calls: list[int] = []
        blank_calls: list[None] = []
        real_curve_menu = view.build_curve_menu  # type: ignore[attr-defined]

        def spy_curve_menu(entry_id: int) -> object:
            curve_calls.append(entry_id)
            real_curve_menu(entry_id)  # exercise the real builder too
            m = Mock()
            m.exec = Mock(return_value=None)
            return m

        def spy_blank_menu() -> object:
            blank_calls.append(None)
            m = Mock()
            m.exec = Mock(return_value=None)
            return m

        monkeypatch.setattr(view, "build_curve_menu", spy_curve_menu)
        monkeypatch.setattr(view, "build_context_menu", spy_blank_menu)

        global_pos = view.mapToGlobal(pos.toPoint())  # type: ignore[attr-defined]
        QApplication.sendEvent(
            view,
            QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse, pos.toPoint(), global_pos
            ),
        )

        assert curve_calls == [eid]
        assert blank_calls == []

    def test_blank_position_routes_to_panel_menu(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # _shown_curve_click_setup と同じ土台を使い、曲線から十分離れた
        # 原点近傍 (_curve_at が None を返す) を対象点にする。
        view, _eid, _curve_pos = _shown_curve_click_setup(qtbot, tmp_path)
        pos = QPoint(2, 2)
        assert view._curve_at(QPointF(pos)) is None  # type: ignore[attr-defined]

        curve_calls: list[int] = []
        blank_calls: list[None] = []

        def spy_curve_menu(entry_id: int) -> object:
            curve_calls.append(entry_id)
            m = Mock()
            m.exec = Mock(return_value=None)
            return m

        def spy_blank_menu() -> object:
            blank_calls.append(None)
            m = Mock()
            m.exec = Mock(return_value=None)
            return m

        monkeypatch.setattr(view, "build_curve_menu", spy_curve_menu)
        monkeypatch.setattr(view, "build_context_menu", spy_blank_menu)

        global_pos = view.mapToGlobal(pos)  # type: ignore[attr-defined]
        QApplication.sendEvent(
            view, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, global_pos)
        )

        assert blank_calls == [None]
        assert curve_calls == []


# ─── Axis right-click menu (増分2b Task 3) ────────────────────────────────────


def _spy_menus(view: object) -> list[tuple[str, object]]:
    """3ビルダーを記録スパイへ差し替え、.exec() を no-op にする。"""
    calls: list[tuple[str, object]] = []
    view.build_curve_menu = lambda eid: (  # type: ignore[method-assign,attr-defined]
        calls.append(("curve", eid)) or SimpleNamespace(exec=lambda *a: None)
    )
    view.build_axis_menu = lambda idx: (  # type: ignore[method-assign,attr-defined]
        calls.append(("axis", idx)) or SimpleNamespace(exec=lambda *a: None)
    )
    view.build_context_menu = lambda: (  # type: ignore[method-assign,attr-defined]
        calls.append(("panel", None)) or SimpleNamespace(exec=lambda *a: None)
    )
    view.build_x_axis_menu = lambda: (  # type: ignore[method-assign,attr-defined]
        calls.append(("x_axis", None)) or SimpleNamespace(exec=lambda *a: None)
    )
    return calls


def _ctx_event() -> QContextMenuEvent:
    return QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(10, 100))


class TestAxisMenuRouting:
    """contextMenuEvent の軸分岐 (spec §4.3: 曲線 → Y軸 → 空白)。

    分類器 (_curve_at/_zone_at/_axis_index_at) はスタブして分岐だけを検証する
    (幾何は既存の _axis_index_at / TestContextMenuRouting のジオメトリテストが
    担保)。3ビルダーはスパイに差し替え .exec() を no-op にして
    contextMenuEvent のモーダル呼び出しによるハングを避ける。
    """

    def test_context_menu_routes_axis_when_on_y_zone(self, qtbot: QtBot) -> None:
        view = _build_panel_view_with_axes(qtbot)
        view._curve_at = lambda pos: None  # type: ignore[method-assign]
        view._zone_at = lambda pos: ZONE_Y_INNER  # type: ignore[method-assign]
        view._axis_index_at = lambda pos: 1  # type: ignore[method-assign]
        calls = _spy_menus(view)

        view.contextMenuEvent(_ctx_event())  # type: ignore[attr-defined]

        assert calls == [("axis", 1)]

    def test_context_menu_curve_wins_over_axis(self, qtbot: QtBot) -> None:
        view = _build_panel_view_with_axes(qtbot)
        view._curve_at = lambda pos: 7  # type: ignore[method-assign]
        view._zone_at = lambda pos: ZONE_Y_INNER  # type: ignore[method-assign]
        calls = _spy_menus(view)

        view.contextMenuEvent(_ctx_event())  # type: ignore[attr-defined]

        assert calls == [("curve", 7)]  # 曲線が軸より優先

    def test_context_menu_falls_back_to_panel_on_plot(self, qtbot: QtBot) -> None:
        view = _build_panel_view_with_axes(qtbot)
        view._curve_at = lambda pos: None  # type: ignore[method-assign]
        view._zone_at = lambda pos: ZONE_PLOT  # type: ignore[method-assign]
        calls = _spy_menus(view)

        view.contextMenuEvent(_ctx_event())  # type: ignore[attr-defined]

        assert calls == [("panel", None)]


class TestAxisContextMenu:
    """build_axis_menu: オートフィット/範囲指定/削除/曲線一覧 (spec §4.3)。"""

    def test_build_axis_menu_items_and_entry_list(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals(
            {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
        )
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        vm.add_signal_to_axis(keys["csv::b"], 0)
        view = GraphPanelView(vm)
        qtbot.addWidget(view)

        menu = view.build_axis_menu(0)  # type: ignore[attr-defined]

        texts = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert "この軸をオートフィット" in texts
        assert "範囲を指定…" in texts
        assert "軸を削除" in texts
        # 曲線一覧 (signal_key ラベル・checkable・checked=visible)
        entry_acts = [
            a for a in menu.actions() if a.text() in (keys["csv::a"], keys["csv::b"])
        ]
        assert len(entry_acts) == 2
        assert all(a.isCheckable() and a.isChecked() for a in entry_acts)

    def test_build_axis_menu_autofit_triggers_reset_axis_y(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals({"csv::a": ([0.0, 1.0], [10.0, 30.0])})
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        vm.set_axis_range(0, 100.0, 200.0)
        view = GraphPanelView(vm)
        qtbot.addWidget(view)

        menu = view.build_axis_menu(0)  # type: ignore[attr-defined]
        act = next(a for a in menu.actions() if a.text() == "この軸をオートフィット")
        act.trigger()

        assert vm.axes[0].y_range == (10.0, 30.0)

    def test_build_axis_menu_delete_triggers_remove_axis(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals(
            {"csv::a": ([0.0], [1.0]), "csv::b": ([0.0], [2.0])}
        )
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        vm.create_new_axis(keys["csv::b"])  # axis 1
        view = GraphPanelView(vm)
        qtbot.addWidget(view)

        menu = view.build_axis_menu(1)  # type: ignore[attr-defined]
        act = next(a for a in menu.actions() if a.text() == "軸を削除")
        act.trigger()

        assert {e.signal_key for e in vm._plotted} == {keys["csv::a"]}

    def test_build_axis_menu_entry_toggle_hides_curve(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals({"csv::a": ([0.0], [1.0])})
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        view = GraphPanelView(vm)
        qtbot.addWidget(view)

        menu = view.build_axis_menu(0)  # type: ignore[attr-defined]
        act = next(a for a in menu.actions() if a.text() == keys["csv::a"])
        act.trigger()  # checkable → toggled → toggle_entry_visibility

        assert vm.entries_on_axis(0)[0][3] is False

    def test_build_axis_menu_range_uses_injected_dialog(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        session, keys = _session_with_signals({"csv::a": ([0.0], [1.0])})
        vm = GraphPanelVM(session)
        vm.add_signal_to_axis(keys["csv::a"], 0)
        view = GraphPanelView(vm, range_dialog_fn=lambda idx, cur: (2.0, 8.0))
        qtbot.addWidget(view)

        menu = view.build_axis_menu(0)  # type: ignore[attr-defined]
        act = next(a for a in menu.actions() if a.text() == "範囲を指定…")
        act.trigger()

        assert vm.axes[0].y_range == (2.0, 8.0)


class TestAxisZoomMenu:
    """FU-09: build_axis_menu/build_x_axis_menu の zoom 項目とルーティング。"""

    def test_y_axis_menu_has_zoom_actions_routed_to_zoom_axis(
        self, qtbot: QtBot
    ) -> None:
        from unittest.mock import Mock, call

        panel = _build_panel_view_with_axes(qtbot)
        panel.vm.set_axis_range(0, 0.0, 100.0)  # ensure a concrete range
        panel.vm.zoom_axis = Mock()  # spy
        menu = panel.build_axis_menu(0)
        acts = {a.text(): a for a in menu.actions()}
        assert "ズームイン" in acts and "ズームアウト（引き）" in acts  # noqa: RUF001
        assert acts["ズームイン"].isEnabled()
        acts["ズームイン"].trigger()
        acts["ズームアウト（引き）"].trigger()  # noqa: RUF001
        assert panel.vm.zoom_axis.call_args_list == [call(0, 0.9), call(0, 1.1)]

    def test_y_axis_zoom_disabled_when_range_none(self, qtbot: QtBot) -> None:
        panel = _build_panel_view_with_axes(qtbot)
        panel.vm.axes[0].set_range(None, None)  # clear the range
        menu = panel.build_axis_menu(0)
        acts = {a.text(): a for a in menu.actions()}
        assert not acts["ズームイン"].isEnabled()
        assert not acts["ズームアウト（引き）"].isEnabled()  # noqa: RUF001

    def test_x_axis_menu_has_four_actions(self, qtbot: QtBot) -> None:
        from unittest.mock import Mock, call

        panel = _build_panel_view_with_axes(qtbot)
        panel.vm.set_x_range(0.0, 100.0)
        panel.vm.reset_x = Mock()
        panel.vm.zoom_x = Mock()
        menu = panel.build_x_axis_menu()
        texts = [a.text() for a in menu.actions()]
        assert texts == [
            "X軸をオートフィット",
            "範囲を指定…",
            "ズームイン",
            "ズームアウト（引き）",  # noqa: RUF001
        ]
        acts = {a.text(): a for a in menu.actions()}
        acts["X軸をオートフィット"].trigger()
        acts["ズームイン"].trigger()
        acts["ズームアウト（引き）"].trigger()  # noqa: RUF001
        assert panel.vm.reset_x.called
        assert panel.vm.zoom_x.call_args_list == [call(0.9), call(1.1)]

    def test_x_axis_zoom_disabled_when_x_range_none(self, qtbot: QtBot) -> None:
        panel = _build_panel_view_with_axes(qtbot)
        panel.vm.x_range = None
        menu = panel.build_x_axis_menu()
        acts = {a.text(): a for a in menu.actions()}
        assert not acts["ズームイン"].isEnabled()
        assert not acts["ズームアウト（引き）"].isEnabled()  # noqa: RUF001

    def test_context_menu_routes_x_axis_on_x_zone(self, qtbot: QtBot) -> None:
        panel = _build_panel_view_with_axes(qtbot)
        panel._curve_at = lambda pos: None  # type: ignore[method-assign]
        panel._zone_at = lambda pos: ZONE_X_INNER  # type: ignore[method-assign]
        calls = _spy_menus(panel)
        panel.contextMenuEvent(_ctx_event())  # type: ignore[attr-defined]
        assert calls == [("x_axis", None)]

    def test_prompt_x_range_applies_set_x_range(self, qtbot: QtBot) -> None:
        from unittest.mock import Mock

        panel = _build_panel_view_with_axes(qtbot)
        panel._range_dialog_fn = lambda axis_index, current: (2.0, 8.0)  # stub dialog
        panel.vm.set_x_range = Mock()
        panel._prompt_x_range()
        panel.vm.set_x_range.assert_called_once_with(2.0, 8.0)


# ─── Grid (PC-15/DP13) ───────────────────────────────────────────────────────


def test_grid_menu_toggles_x_axis_grid(qtbot, tmp_path):
    view = _make_panel_view(qtbot, tmp_path)  # 既存の最小 GraphPanelView 構築ヘルパ
    # メニューの「グリッド」項目
    menu = view.build_context_menu()
    grid_act = next(a for a in menu.actions() if a.text() == "グリッド")
    assert grid_act.isCheckable()
    assert grid_act.isChecked() is False
    # トグル ON → _x_axis に grid alpha が設定される
    grid_act.setChecked(True)
    assert view.vm.grid_enabled is True
    assert view._x_axis.grid  # AxisItem.grid は setGrid の値(False→alpha)
    # トグル OFF → grid 無効化
    grid_act.setChecked(False)
    assert view.vm.grid_enabled is False
    assert view._x_axis.grid is False


def test_grid_menu_reflects_current_state(qtbot, tmp_path):
    view = _make_panel_view(qtbot, tmp_path)
    view.vm.toggle_grid(True)
    menu = view.build_context_menu()
    grid_act = next(a for a in menu.actions() if a.text() == "グリッド")
    assert grid_act.isChecked() is True


def test_cursor_pens_and_frame_use_tokens(qtbot: QtBot, tmp_path: Path) -> None:
    """配線検証: カーソル線 A/B・アクティブ枠・ドロップ強調がトークンを消費する。"""
    from valisync.gui.theme.tokens import active

    view = _make_panel_view(qtbot, tmp_path)
    c = active().colors
    assert view._cursor_line.pen.color().name() == c.cursor_a.hex
    assert view._cursor_line_b.pen.color().name() == c.cursor_b.hex
    assert c.accent_active.hex in view._active_frame.styleSheet()
    view._set_drop_highlight(True)
    # 親 view は未 show — isVisible() は祖先非表示で常に False になるため
    # isVisibleTo(view) で「view 表示時に見える状態か」を検証する。
    assert view._drop_frame.isVisibleTo(view)
    assert c.drop_highlight.hex in view._drop_frame.styleSheet()
    view._set_drop_highlight(False)
    assert not view._drop_frame.isVisibleTo(view)


def test_axis_move_feedback_uses_axis_move_indicator_not_accent_active(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """axis_move_indicator は accent_active と同値 (DARK/LIGHT 双方 #f59e0b・spec §3)。

    値を分岐させたテーマで軸移動フィードバック線 (``_ensure_feedback_items``) が
    axis_move_indicator を、アクティブ枠 (``qss.active_panel_frame``) は
    accent_active を参照することを直接実証する — 双方向の誤配線ガード。
    """
    import dataclasses

    from valisync.gui.theme import qss
    from valisync.gui.theme.tokens import DARK, Color, set_active

    alt = dataclasses.replace(
        DARK,
        colors=dataclasses.replace(DARK.colors, axis_move_indicator=Color(1, 2, 3)),
    )
    set_active(alt)
    try:
        view = _make_panel_view(qtbot, tmp_path)
        view._ensure_feedback_items()
        assert view._axis_move_line is not None
        line_color = view._axis_move_line.pen().color().name()
        assert line_color == Color(1, 2, 3).hex  # axis_move_indicator (分岐値)
        assert line_color != DARK.colors.accent_active.hex  # accent_active 誤配線でない

        # アクティブ枠は accent_active のまま (未分岐の元値・axis_move への非追随)
        frame_style = qss.active_panel_frame(alt)
        assert DARK.colors.accent_active.hex in frame_style
        assert Color(1, 2, 3).hex not in frame_style
    finally:
        set_active(DARK)


def test_drop_highlight_border_paints_as_child(qtbot: QtBot, tmp_path: Path) -> None:
    """ドロップ強調の 2px 実線枠が子ウィジェットとして実ピクセル描画される。

    既存の realgui drop テストは is_drop_highlighted() (状態フラグ) を assert
    しており、枠が実際に描かれるかは検証していなかった。素の QWidget サブ
    クラスは WA_StyledBackground なしだと子として QSS border を描かない
    (増分1 デバッグテーマ検証で発覚した実バグ)。
    """
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from valisync.gui.theme.tokens import active
    from valisync.gui.views.graph_panel_view import GraphPanelView

    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_keys(session)[0])
    view = GraphPanelView(vm)
    parent = QWidget()
    qtbot.addWidget(parent)  # view は parent 所有 — 二重管理を避ける
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(view)
    parent.resize(400, 300)
    parent.show()
    view._set_drop_highlight(True)
    parent.repaint()
    img = parent.grab().toImage()
    expected = active().colors.drop_highlight
    hit = any(
        abs((p := img.pixelColor(1, y)).red() - expected.r) < 12
        and abs(p.green() - expected.g) < 12
        and abs(p.blue() - expected.b) < 12
        for y in range(4, img.height() - 4)
    )
    assert hit, f"左端列に枠色 {expected.hex} のピクセルが1つも無い (不描画)"
