# ruff: noqa: RUF003
"""Layer A: _realgui_input ヘルパのディスプレイ非依存ロジックを headless 検証。"""

from __future__ import annotations

from tests.gui._panel_factory import make_single_signal_panel
from tests.realgui import _realgui_input as ri
from valisync.gui.views.graph_panel_view import GraphPanelView


def test_flag_and_vk_constants() -> None:
    assert (ri.MOVE, ri.LDOWN, ri.LUP) == (0x0001, 0x0002, 0x0004)
    assert (ri.RDOWN, ri.RUP) == (0x0008, 0x0010)
    assert (ri.KEYDOWN, ri.KEYUP) == (0x0000, 0x0002)
    assert ri.VK_RETURN == 0x0D and ri.VK_ESCAPE == 0x1B
    assert ri.VK_CONTROL == 0x11 and ri.VK_SHIFT == 0x10


def test_real_display_skip_reason_is_set_under_offscreen() -> None:
    # CI / local headless は QT_QPA_PLATFORM=offscreen or 非 win32 → 必ず理由が返る。
    assert ri.real_display_skip_reason() is not None


def test_to_phys_returns_int_pair(qtbot) -> None:
    # make_single_signal_panel() は .vm を持つ base を返す（test_graph_panel_offset_drag.py
    # 参照）。実 offscreen view を生成して to_phys の座標変換が int ペアを返すことを確認。
    view = GraphPanelView(make_single_signal_panel().vm)
    qtbot.addWidget(view)
    view.resize(400, 300)
    x, y = ri.to_phys(view, 50.0, 40.0)
    assert isinstance(x, int) and isinstance(y, int)
