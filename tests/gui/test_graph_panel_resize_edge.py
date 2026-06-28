from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.viewmodels.y_axis_vm import YAxisVM


def _panel_with(axes: list[YAxisVM]) -> GraphPanelVM:
    vm = GraphPanelVM.__new__(GraphPanelVM)  # bypass Session; we only test layout math
    vm._axes = axes
    vm._column_count = 1
    vm._notified: list[str] = []
    vm._notify = lambda topic: vm._notified.append(topic)  # type: ignore[assignment]
    return vm


def test_resize_bottom_grows_into_gap_below_others_unchanged() -> None:
    # A[0.0,0.3] B[0.3,0.3] gap[0.6,0.4]  -> drag B bottom down by 0.2
    a = YAxisVM(top_ratio=0.0, height_ratio=0.3)
    b = YAxisVM(top_ratio=0.3, height_ratio=0.3)
    vm = _panel_with([a, b])
    vm.resize_axis_edge(1, "bottom", 0.2)
    assert (b.top_ratio, round(b.height_ratio, 6)) == (
        0.3,
        0.5,
    )  # bottom moved, top fixed
    assert (a.top_ratio, a.height_ratio) == (0.0, 0.3)  # neighbour unchanged
    assert vm._notified == ["axes"]


def test_resize_bottom_does_not_push_neighbour() -> None:
    # A[0.0,0.5] B[0.5,0.5] flush -> drag A bottom down: cannot pass B.top (0.5)
    a = YAxisVM(top_ratio=0.0, height_ratio=0.5)
    b = YAxisVM(top_ratio=0.5, height_ratio=0.5)
    vm = _panel_with([a, b])
    vm.resize_axis_edge(0, "bottom", 0.3)
    assert (a.top_ratio, a.height_ratio) == (0.0, 0.5)  # clamped: no growth
    assert (b.top_ratio, b.height_ratio) == (0.5, 0.5)  # neighbour not pushed
    assert vm._notified == ["axes"]


def test_resize_bottom_shrink_clamped_to_min_height_top_fixed() -> None:
    a = YAxisVM(top_ratio=0.0, height_ratio=0.5)
    b = YAxisVM(top_ratio=0.5, height_ratio=0.5)
    vm = _panel_with([a, b])
    vm.resize_axis_edge(0, "bottom", -0.9)  # shrink far past min
    assert a.top_ratio == 0.0  # opposite (top) edge fixed
    assert round(a.height_ratio, 6) == 0.05  # clamped to MIN_H
    assert (b.top_ratio, b.height_ratio) == (0.5, 0.5)
    assert vm._notified == ["axes"]


def test_resize_top_grows_upward_into_gap_bottom_fixed() -> None:
    # gap[0.0,0.4] B[0.4,0.6] -> drag B top up by 0.4 (delta=-0.4)
    b = YAxisVM(top_ratio=0.4, height_ratio=0.6)
    vm = _panel_with([b])
    vm.resize_axis_edge(0, "top", -0.4)
    assert round(b.top_ratio, 6) == 0.0
    assert round(b.height_ratio, 6) == 1.0  # bottom (0.4+0.6=1.0) fixed
    assert vm._notified == ["axes"]


def test_resize_top_does_not_push_neighbour_above() -> None:
    a = YAxisVM(top_ratio=0.0, height_ratio=0.5)
    b = YAxisVM(top_ratio=0.5, height_ratio=0.5)
    vm = _panel_with([a, b])
    vm.resize_axis_edge(1, "top", -0.3)  # B top up: cannot pass A.bottom (0.5)
    assert (b.top_ratio, b.height_ratio) == (0.5, 0.5)
    assert (a.top_ratio, a.height_ratio) == (0.0, 0.5)
    assert vm._notified == ["axes"]


def test_set_axis_range_targets_that_axis_only() -> None:
    a = YAxisVM(top_ratio=0.0, height_ratio=0.5, y_range=(0.0, 10.0))
    b = YAxisVM(top_ratio=0.5, height_ratio=0.5, y_range=(0.0, 10.0))
    vm = _panel_with([a, b])
    vm.set_axis_range(1, 2.0, 4.0)  # zoom-in on axis b
    assert b.y_range == (2.0, 4.0)
    assert a.y_range == (0.0, 10.0)  # untouched (NOT the first-axis-fixed path)
    assert vm._notified == ["axes"]
