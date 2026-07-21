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


def test_calculate_virtual_range_margin_zero_is_identity_backcompat() -> None:
    """margin 既定 0.0 では従来の恒等マッピング (後方互換)。"""
    axis = YAxisVM(y_range=(0.0, 100.0), top_ratio=0.0, height_ratio=1.0)
    v_lo, v_hi = axis.calculate_virtual_range()
    assert (v_lo, v_hi) == pytest.approx((0.0, 100.0))


def test_calculate_virtual_range_margin_insets_full_height_axis() -> None:
    """FU-12: margin>0 でフルハイト軸が恒等でなくなり、境界値データが仮想レンジの
    内側 (下端から m・上端から m) に着地する。"""
    axis = YAxisVM(y_range=(45.0, 100.0), top_ratio=0.0, height_ratio=1.0)
    v_lo, v_hi = axis.calculate_virtual_range(margin=0.03)
    assert v_lo < 45.0  # y_min は下フレームから浮く
    assert v_hi > 100.0  # y_max は上フレームから浮く
    span = v_hi - v_lo
    assert (45.0 - v_lo) / span == pytest.approx(0.03, abs=1e-6)
    assert (100.0 - v_lo) / span == pytest.approx(0.97, abs=1e-6)


def test_effective_region_multiplicative_survives_min_height() -> None:
    """MIN_H=0.05 (< 2*0.03) の軸で eff_height が負にならない (絶対値 height-2m の
    バグを乗算 height*(1-2m) で回避)。"""
    axis = YAxisVM(top_ratio=0.0, height_ratio=0.05)
    eff_top, eff_h = axis.effective_region(margin=0.03)
    assert eff_h > 0.0
    assert eff_h == pytest.approx(0.05 * (1.0 - 0.06))
    assert eff_top == pytest.approx(0.0 + 0.03 * 0.05)


def test_y_is_auto_defaults_true() -> None:
    assert YAxisVM().y_is_auto is True


def test_y_is_auto_constructor_override() -> None:
    assert YAxisVM(y_is_auto=False).y_is_auto is False


def test_set_range_does_not_touch_auto_flag() -> None:
    # auto フィットも手動 setter も同じ set_range funnel を通るため、
    # フラグ遷移をここに置くと初回フィットで恒久 manual 化する (spec §3.1)。
    axis = YAxisVM()
    axis.set_range(0.0, 1.0)
    assert axis.y_is_auto is True
    axis.y_is_auto = False
    axis.set_range(None, None)
    assert axis.y_is_auto is False
