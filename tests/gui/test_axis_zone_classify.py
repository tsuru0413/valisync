from valisync.gui.views.graph_panel_view import (
    AXZONE_FRAME,
    AXZONE_GRIP_BOTTOM,
    AXZONE_GRIP_TOP,
    AXZONE_PAN,
    AXZONE_ZOOM,
    classify_axis_zone,
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
