"""Layer C (realgui): FU-12 -- 境界値データが実ディスプレイでプロット枠から浮く。

純描画テスト(実 OS 入力なし)。単一フルハイト軸に信号を1本載せ、set_axis_range で
軸レンジの min をデータの最小値そのものに固定する(境界条件を確定させる -- A や
_padded_range の自動 pad に頼らない)。ViewBox の mapViewToScene で「データの最下点
がプロット下枠から AXIS_INSET_MARGIN の半分以上浮いている」ことを実描画済みの
scene 幾何でアサートし、実 OS の grabWindow で実ディスプレイのスクショを保存する
(クリック等の合成入力は一切行わない -- 純粋な描画結果の記録であり、
memory gui_realgui_synthetic_click_mislabeled_layer_c が警告する
「合成クリックを Layer C と誤表示する」問題は該当しない。証拠は QWidget.grab()
(オフスクリーンでも動く Qt 内部レンダーで実ディスプレイを証明しない)ではなく
QScreen.grabWindow() -- 実 OS の画面バッファを読む -- を使い、Layer C 契約ガード
tests/gui/test_realgui_layer_c_contract.py の要求(実入力 or grabWindow)も満たす)。

headless 側の同値契約は test_boundary_data_lifts_off_frame_autofit /
test_boundary_data_lifts_off_frame_manual_range (tests/gui/test_graph_panel_render_geometry.py)
で ViewBox 幾何として証明済み -- 本テストはそれを実ディスプレイの実レンダーパイプライン
(実ウィンドウ・実ペイント・実スクリーンショット)で裏取りする。
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def _show_single_signal_panel(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_single_signal_panel

    view = make_single_signal_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # Fully on-screen (avoid off-screen clamp / partial paint on grab()).
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 80, screen.y() + 80, 800, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return view


def test_fu12_boundary_data_visible_on_real_display(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """境界値(軸レンジ min == データ最小値)が実ディスプレイでプロット下枠から浮く。

    合成入力は一切ない(mount -> auto-fit 確認 -> set_axis_range で境界固定 ->
    refresh -> geometry アサート -> 実 grabWindow スクショ保存、の純描画フロー)。
    """
    skip_unless_real_display()
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    from valisync.gui.views.graph_panel_view import AXIS_INSET_MARGIN

    view = _show_single_signal_panel(qtbot)
    vm = view.vm

    assert vm.axes[0].y_range is not None
    y_lo, y_hi = vm.axes[0].y_range
    vm.set_axis_range(0, y_lo, y_hi)  # min == データ値(境界条件を確定、pad なし)
    view.refresh()
    for _ in range(3):
        QApplication.processEvents()

    vb = view._view_boxes[0]
    R = vb.sceneBoundingRect()
    frame_bot_scene = R.y() + R.height()
    data_bot_scene = vb.mapViewToScene(QPointF(0.0, y_lo)).y()
    lift_px = frame_bot_scene - data_bot_scene

    screenshot = tmp_path / "fu12_boundary_data_visible.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(screenshot))

    assert lift_px >= 0.5 * AXIS_INSET_MARGIN * R.height(), (
        f"境界データがフレームから浮いていない(lift={lift_px:.1f}px). "
        f"screenshot: {screenshot}"
    )
