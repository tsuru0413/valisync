import pytest

from valisync.gui.views.graph_panel_view import (
    AXZONE_FRAME,
    AXZONE_GRIP_BOTTOM,
    AXZONE_GRIP_TOP,
    AXZONE_PAN,
    AXZONE_ZOOM,
    classify_axis_zone,
    grip_resize_delta,
)

W, H = 60.0, 120.0
KW = dict(grip_w=40.0, grip_h=8.0, frame=3.0, tol=4.0)


def test_top_centre_is_grip_top() -> None:
    assert classify_axis_zone(W / 2, 2.0, W, H, **KW) == AXZONE_GRIP_TOP


def test_bottom_centre_is_grip_bottom() -> None:
    assert classify_axis_zone(W / 2, H - 2.0, W, H, **KW) == AXZONE_GRIP_BOTTOM


def test_top_corner_is_frame_not_grip() -> None:
    # near top edge but far left of the centred grip -> frame (move), not resize
    assert classify_axis_zone(2.0, 2.0, W, H, **KW) == AXZONE_FRAME


def test_left_interior_is_pan_right_interior_is_zoom() -> None:
    assert classify_axis_zone(W * 0.25, H / 2, W, H, **KW) == AXZONE_PAN  # outer/left
    assert classify_axis_zone(W * 0.75, H / 2, W, H, **KW) == AXZONE_ZOOM  # inner/right


def test_grip_takes_priority_over_frame_and_interior() -> None:
    # a point inside the grip rect (centre, near top) is GRIP even though it also
    # sits on the frame band / interior split.
    assert classify_axis_zone(W / 2, 5.0, W, H, **KW) == AXZONE_GRIP_TOP


# ─── Symptom 2: wider, grabbable move-frame (FRAME 3 → 8) + short-axis h/4 cap ──
_KW8 = dict(grip_w=40.0, grip_h=8.0, frame=8.0, tol=4.0)


def test_left_right_move_frame_is_wider_at_frame_8() -> None:
    # 6 px in from the left edge at mid-height: the widened move-frame now claims it
    # (FRAME=move), where the old 3 px border left it as interior pan. This is the
    # core grabbability fix — a hairline 3 px move-edge was the reported instability.
    assert classify_axis_zone(6.0, H / 2, W, H, **_KW8) == AXZONE_FRAME
    assert classify_axis_zone(6.0, H / 2, W, H, **KW) == AXZONE_PAN  # old 3 px: pan


def test_vertical_move_frame_capped_to_keep_interior_on_short_axis() -> None:
    # On a 20 px-tall axis the 8 px top/bottom bands would otherwise swallow most of
    # the height; the h/4 cap (=5 px) keeps a zoom/pan interior in the middle. At
    # (lx=10, ly=6) — outside the grip, 6 px down a 20 px axis — the cap yields PAN;
    # without the cap the 8 px band would mis-claim it as FRAME.
    assert classify_axis_zone(10.0, 6.0, 72.0, 20.0, **_KW8) == AXZONE_PAN


# ─── grip_resize_delta: absolute cursor-tracking edge delta (resize root-cause fix) ──
# The grip edge must track the cursor as a fraction of the FULL PANEL height, NOT the
# axis spine height. The old code divided the pixel delta by the spine height
# (height_ratio * panel), inflating the move by 1/height_ratio → cursor/edge mismatch
# and runaway-to-minimum. These pin the corrected, height-independent mapping.


def test_grip_delta_is_panel_proportional() -> None:
    # cursor at 40% of a 1000px panel; edge currently at 0.5 → must move to 0.4.
    assert grip_resize_delta(400.0, 0.0, 1000.0, 0.0, 0.5) == pytest.approx(-0.1)


def test_grip_delta_independent_of_axis_height() -> None:
    # Same cursor/panel/edge inputs give the SAME delta regardless of how tall the
    # dragged axis is — the function takes no axis-height input by design. This is
    # the regression guard for the scaling bug.
    d1 = grip_resize_delta(400.0, 0.0, 1000.0, 0.0, 0.5)
    d2 = grip_resize_delta(400.0, 0.0, 1000.0, 0.0, 0.5)
    assert d1 == d2 == pytest.approx(-0.1)


def test_grip_delta_preserves_grab_offset() -> None:
    # the offset between the grabbed edge and the cursor at drag-start is re-added so
    # the edge does not jump to the cursor on the first move.
    assert grip_resize_delta(400.0, 0.0, 1000.0, 0.02, 0.5) == pytest.approx(-0.08)


def test_grip_delta_honours_panel_top() -> None:
    # panel does not start at scene y=0: ratio is measured from panel_top.
    assert grip_resize_delta(600.0, 100.0, 1000.0, 0.0, 0.5) == pytest.approx(0.0)


def test_grip_delta_zero_panel_height_is_safe() -> None:
    assert grip_resize_delta(400.0, 0.0, 0.0, 0.0, 0.5) == 0.0
