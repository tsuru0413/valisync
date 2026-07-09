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

from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QSize, Qt
from PySide6.QtGui import QDropEvent, QMouseEvent, QResizeEvent
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.adapters.qt_signal_models import encode_signal_keys
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

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


def _keys(session: Session) -> list[str]:
    return [s.name for s in session.signals()]


def _make_view(qtbot: QtBot, vm: GraphPanelVM) -> object:
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    return view


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
