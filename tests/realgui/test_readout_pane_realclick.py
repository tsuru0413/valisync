"""Layer C: readout ペインの行クリック→曲線ハイライトを実 OS 入力で検証 (readout-pane Task 5)。

readout-pane Task 4 で CursorReadout がペイン化され、``GraphAreaView.readout_pane``
がアクティブパネルの状態を pull する。行クリック(``CursorReadout.mousePressEvent``
→ ``activate_row`` → ``row_activated`` シグナル → ``GraphAreaView.
_on_readout_row_activated`` → アクティブパネルの ``GraphPanelView.
activate_curve_by_id``)という配送経路は Layer B
(tests/gui/test_readout_pane_binding.py::test_readout_row_activates_curve)が
``activate_row()`` のプログラム的直接呼び出しで証明済み。ここは「実クリックが該当行の
値セル(QLabel)に着弾し、その未 accept press が親 CursorReadout へバブルして
mousePressEvent に届く」実 OS 経路のみを証拠化する(memory
gui_realgui_synthetic_click_mislabeled_layer_c)。QLabel 自体は press を accept
しないため親へバブルする挙動は同一コードベースの実 Qt 挙動として確立済み
(memory gui_app_filter_ancestor_bubble_false_clear — FU-23 で実 OS 入力により
実証済みの祖先バブル配送)。

再利用: tests/gui/_panel_factory.make_two_axis_area・test_readout_realclick.py の
_shown_area/_widget_center_phys 作法(module-local 忠実コピー — cross-test-module
import を避ける確立済みの流儀)。
"""

from __future__ import annotations

import contextlib

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _shown_area(qtbot: QtBot):
    """Real-display GraphAreaView (one tab/panel, two signals/axes) + its panel."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_area

    area = make_two_axis_area()
    qtbot.addWidget(area)
    area.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    area.setGeometry(screen.x() + 60, screen.y() + 60, 900, 620)
    area.show()
    area.raise_()
    area.activateWindow()
    qtbot.waitExposed(area)
    for _ in range(3):
        QApplication.processEvents()
    panel = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    qtbot.waitUntil(
        lambda: panel._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return area, panel


def _widget_center_phys(view, w) -> tuple[int, int]:
    """物理スクリーン中心座標(w は view と同じトップレベルウィンドウ内の子ウィジェット)。"""
    from PySide6.QtCore import QPoint

    dpr = view.devicePixelRatioF()
    gp = w.mapToGlobal(QPoint(w.width() // 2, w.height() // 2))
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_real_click_readout_row_activates_curve(qtbot: QtBot, tmp_path) -> None:
    """2信号を1パネルへ → A カーソル設置 → ペイン2行目(index 1)を実クリック
    → アクティブパネルの active_curve_id() がその行の entry_id になる。

    行の順序は VM の描画順(curve_keys())と読み値の行順(cursor_readings())が同じ
    _plotted 走査を共有するため一致する — row 1 は2番目に追加した信号(2本目の軸)。

    honest RED gate: CursorReadout.mousePressEvent の activate_row(row) 呼び出しを
    削るか GraphAreaView._on_readout_row_activated の配送を外すと、実クリック後も
    active_curve_id() が None のまま残り RED になる。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    area, panel = _shown_area(qtbot)
    panel.vm.x_range = panel.vm.x_range or (0.0, 1.0)
    panel.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert panel.cursor_line_visible()

    qtbot.waitUntil(lambda: len(area.readout_pane.row_texts()) == 2, timeout=3000)
    row_texts = area.readout_pane.row_texts()
    assert len(row_texts) == 2, f"expected 2 signal rows, got {row_texts!r}"

    target_entry_id = panel.curve_keys()[1]
    assert panel.active_curve_id() is None

    row1_label = area.readout_pane._value_labels[1][0]
    phys = _widget_center_phys(area, row1_label)
    at(*phys, LDOWN)
    at(*phys, LUP)
    for _ in range(6):
        QApplication.processEvents()

    shot = tmp_path / "readout_row_click.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot))

    assert panel.active_curve_id() == target_entry_id, (
        "real click on readout row 1 did not activate its curve (expected "
        f"entry_id={target_entry_id!r}, got {panel.active_curve_id()!r}). "
        f"screenshot: {shot}"
    )
