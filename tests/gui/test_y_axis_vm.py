from __future__ import annotations

import pytest

from valisync.gui.viewmodels.y_axis_vm import YAxisVM


def test_y_axis_vm_construction() -> None:
    """YAxisVM stores range, top_ratio, height_ratio, column, unit."""
    axis = YAxisVM(
        y_range=(10.0, 20.0),
        top_ratio=0.1,
        height_ratio=0.5,
        column=1,
        unit="m/s",
    )
    assert axis.y_range == (10.0, 20.0)
    assert axis.top_ratio == 0.1
    assert axis.height_ratio == 0.5
    assert axis.column == 1
    assert axis.unit == "m/s"


def test_y_axis_vm_set_range_notifies() -> None:
    """set_range updates range and notifies."""
    axis = YAxisVM()
    events = []
    axis.subscribe(events.append)

    axis.set_range(0.0, 100.0)

    assert axis.y_range == (0.0, 100.0)
    assert "range" in events


@pytest.mark.parametrize(
    "y_range, top, height, expected_virtual",
    [
        ((0.0, 100.0), 0.0, 1.0, (0.0, 100.0)),  # Full height
        ((0.0, 100.0), 0.0, 0.5, (-100.0, 100.0)),  # Top half
        ((0.0, 100.0), 0.5, 0.5, (0.0, 200.0)),  # Bottom half
        ((10.0, 20.0), 0.0, 0.2, (-30.0, 20.0)),  # Small region at top
    ],
)
def test_calculate_virtual_range(y_range, top, height, expected_virtual) -> None:
    """calculate_virtual_range returns correct spans for overlay mapping."""
    axis = YAxisVM(y_range=y_range, top_ratio=top, height_ratio=height)
    v_min, v_max = axis.calculate_virtual_range()

    assert v_min == pytest.approx(expected_virtual[0])
    assert v_max == pytest.approx(expected_virtual[1])
