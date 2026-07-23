# ruff: noqa: RUF003
"""Layer C: アクティブパネル閉ループの実 OS 入力実証 (PC-07 / PC-02 / FU-13)。

合成 qtbot ではなく実クリック / 実ダブルクリック / 実右クリックメニューで MainWindow
を駆動し、OS->Qt ヒットテスト/配送で以下の閉ループが成立することを検証する
(Layer B との違い):

- パネル 2 の実クリック -> パネル 2 が活性化し amber 枠が描画される (スクショ)
- パネル 1 の Y 軸ストリップを実クリック -> 軸クリック経路でパネル 1 に活性化が戻る
- 別ウィジェット (ChannelBrowser) の行を実クリック選択 -> 実右クリックメニューの
  "Add to Active Panel" を実クリック -> 信号がアクティブパネル (パネル 2) に着地し
  曲線が実描画される (スクショ)。FU-06 で追加ボタンは撤去され追加は menu/D&D のみ。
- 実ダブルクリック -> 信号プレビューウィンドウが開き波形が描画される (FU-13。旧挙動の
  ダブルクリック追加は撤去)。

自動 assert (VM 状態・_active_frame.isVisible()・plot item 数) は backstop、
スクショが判定の本体。追加経路の active-routing は D&D では検証できない (D&D は
drop 先パネル geometry ターゲットで active パネル指向でない) ため、右クリックメニュー
経由が active-routing の唯一の実経路。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    VK_ESCAPE,
    at,
    double_click,
    skip_unless_real_display,
    to_phys,
)
from tests.realgui._realgui_input import key as key_input
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui

_EVIDENCE_DIR_F0 = Path(__file__).resolve().parents[2] / "design_export" / "evidence_f0"


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int) -> None:
    for _ in range(n):
        _pump(0.02)


def _real_click(x: int, y: int) -> None:
    """純クリック: 同一点で press->release (MOVE なし)。"""
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    _pump_n(4)


def _phys_center(w, local_center) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    gp = w.mapToGlobal(local_center)
    dpr = w.devicePixelRatioF()
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _shot(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    p = tmp_path / f"{name}.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(p))
    return p


def _panel_widget(window, tab_index: int, panel_index: int):  # type: ignore[no-untyped-def]
    """GraphAreaView の QSplitter ページから panel_index 番目の GraphPanelView を返す。"""
    page = window.graph_area_view.tabs.widget(tab_index)  # QSplitter
    return page.widget(panel_index)


def _make_window_with_two_panels_and_signal(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    """MainWindow を構築し、CSV 1 信号を同期ロード・2 パネル化して表示する。

    QSettings 隔離は tests/realgui/conftest.py の autouse が効く。信号ロードは
    off-thread の LoadController を経由せず session.load->_on_loaded を直接呼んで
    同期化する (production の完走コールバックと同じ登録/活性化経路)。返り値の
    signal_key は ChannelBrowser の row0 に出る namespaced キー。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    csv = tmp_path / "sig.csv"
    rows = ["t,speed"]
    for i in range(24):
        rows.append(f"{i * 0.1:.3f},{10.0 + i * 0.8:.4f}")  # 明瞭な右肩上がりの直線
    csv.write_text("\n".join(rows) + "\n")
    fmt = FormatDefinition(
        name="rt_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    outcome = window.app_vm.session.load(csv, fmt)
    window._on_loaded(outcome)  # 登録+活性化+ChannelBrowser 反映+workbench 表示
    window.graph_area_vm.add_panel(0)  # 2 パネル化 (新パネルが自動アクティブ)

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    w = min(1120, screen.width() - 120)
    h = min(760, screen.height() - 120)
    window.setGeometry(screen.x() + 60, screen.y() + 60, w, h)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(3):
        QApplication.processEvents()

    model = window.channel_browser_view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=3000)
    signal_key = model.signal_key_at(model.index(0, 0))
    assert signal_key is not None, "ChannelBrowser に信号行が出ていない"
    return window, signal_key


def _real_menu_add_first_action(row_phys: tuple[int, int]) -> str | None:
    """行を実右クリック -> アプリの QMenu を待ち -> 先頭アクション ("Add to Active
    Panel") を実クリックする。クリックしたアクション文字列を返す。

    view は menu を ``QMenu.exec`` (ネストした Qt イベントループ) で表示するため、
    右クリックもメニュー項目クリックも QTimer で予約し、そのネストループ内で発火させる。
    項目クリックが外れてもハングしないよう ESC watchdog がメニューを閉じる (外れは
    assertion 失敗であってマシンハングではない)。
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    px, py = row_phys
    out: dict[str, object] = {}
    loop = QEventLoop()

    def right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def click_item() -> None:
        menu = QApplication.activePopupWidget()
        if isinstance(menu, QMenu) and menu.actions():
            act = menu.actions()[0]
            gc = menu.mapToGlobal(menu.actionGeometry(act).center())
            dpr = menu.devicePixelRatioF()
            mx, my = round(gc.x() * dpr), round(gc.y() * dpr)
            at(mx, my, LDOWN)
            at(mx, my, LUP)
            out["clicked"] = act.text()
        else:
            out["clicked"] = None

    def watchdog() -> None:
        # 項目クリックが外れていれば menu が残る -> ESC で閉じてから quit。
        if isinstance(QApplication.activePopupWidget(), QMenu):
            key_input(VK_ESCAPE)
        loop.quit()

    QTimer.singleShot(300, right_click)
    QTimer.singleShot(1000, click_item)
    QTimer.singleShot(1600, watchdog)
    QTimer.singleShot(5000, loop.quit)  # hard safety
    loop.exec()
    return out.get("clicked")  # type: ignore[return-value]


@pytest.mark.realgui
def test_click_activates_panel_and_add_routes_there(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """PC-07/PC-02 閉ループ: 実クリックで活性化 -> 右クリックメニューの追加がアクティブパネルへ着地。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    window, key = _make_window_with_two_panels_and_signal(qtbot, tmp_path)
    vm = window.graph_area_vm
    vm.set_active_panel(0, 0)  # 前提固定: パネル 1 (index 0) を active に
    QApplication.processEvents()

    panel0 = _panel_widget(window, 0, 0)
    panel1 = _panel_widget(window, 0, 1)
    qtbot.waitUntil(
        lambda: (
            bool(panel1._view_boxes)
            and panel1._view_boxes[0].sceneBoundingRect().height() > 40
        ),
        timeout=3000,
    )

    # 1) パネル 2 (index 1) の空白部を実クリック -> 活性化＋枠
    px, py = _phys_center(panel1, QPoint(panel1.width() // 2, 16))
    _real_click(px, py)
    shot1 = _shot(tmp_path, "01_panel2_active_frame")
    qtbot.waitUntil(lambda: vm.active_panel_index(0) == 1, timeout=2000)
    assert vm.active_panel_index(0) == 1, (
        f"パネル 2 の実クリックで active_panel が 1 にならない。screenshot: {shot1}"
    )
    assert panel1._active_frame.isVisible(), (
        f"パネル 2 に amber 枠が出ない。screenshot: {shot1}"
    )
    assert not panel0._active_frame.isVisible(), (
        f"パネル 1 の枠が残っている。screenshot: {shot1}"
    )

    # 2) [レビュー追加] パネル 1 (index 0) の Y 軸ストリップを実クリック -> active==0 に戻る
    #    (軸クリック経路 _AlignedAxisItem.mouseClickEvent -> set_active_axis/activate の実証)
    spine = panel0._y_axes[0].sceneBoundingRect()
    ax_x, ax_y = to_phys(panel0, spine.center().x(), spine.center().y())
    at(ax_x, ax_y, LDOWN)
    time.sleep(0.05)
    at(ax_x, ax_y, LUP)  # 同一点・MOVE なし -> 純クリック -> mouseClickEvent
    _pump_n(4)
    qtbot.waitUntil(lambda: vm.active_panel_index(0) == 0, timeout=2000)
    assert vm.active_panel_index(0) == 0, (
        "パネル 1 の Y 軸ストリップの実クリックで active_panel が 0 に戻らない "
        "(軸クリック活性化経路が実 OS で通らない)。"
    )
    assert panel0._active_frame.isVisible()

    # 3) Add 閉ループをパネル 2 へ着地させるため、パネル 2 を再活性化
    _real_click(px, py)
    qtbot.waitUntil(lambda: vm.active_panel_index(0) == 1, timeout=2000)

    # 4) ChannelBrowser の row0 を実クリックで選択 -> 実右クリックメニューの
    #    "Add to Active Panel" を実クリック (FU-06 でボタン撤去・追加は menu/D&D のみ)。
    tree = window.channel_browser_view.tree
    model = (
        window.channel_browser_view.model
    )  # FU-22 B: proxy dropped, tree is model-direct
    qtbot.waitUntil(
        lambda: tree.visualRect(model.index(0, 0)).height() > 0, timeout=3000
    )
    rect = tree.visualRect(model.index(0, 0))
    vp = tree.viewport()
    # visualRect 幅は viewport 幅を超えうる (center.x が右隣ペインに着弾)。x をクランプ。
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    row_phys = _phys_center(vp, local)
    _real_click(*row_phys)  # 行を選択 -> "Add to Active Panel" が有効化
    clicked = _real_menu_add_first_action(row_phys)
    assert clicked == S.ACTION_ADD_TO_ACTIVE_PANEL, (
        f"実右クリックメニューの先頭項目を実クリックできなかった (got {clicked!r})。"
    )

    # 5) メニュー経由の追加がアクティブパネル 2 に着地 (パネル 1 は空のまま)＋曲線が実描画
    panel1_vm = vm.panels(0)[1]
    panel0_vm = vm.panels(0)[0]
    qtbot.waitUntil(lambda: key in panel1_vm.plotted_signal_keys(), timeout=2000)
    shot2 = _shot(tmp_path, "02_curve_on_panel2")
    assert key in panel1_vm.plotted_signal_keys(), (
        f"Add がアクティブパネル 2 に着地しない。screenshot: {shot2}"
    )
    assert key not in panel0_vm.plotted_signal_keys(), (
        f"信号が非アクティブなパネル 1 に誤着地した。screenshot: {shot2}"
    )
    assert key in panel1.signal_keys_drawn(), (
        f"パネル 2 に曲線が実描画されていない。screenshot: {shot2}"
    )


@pytest.mark.realgui
def test_dblclick_opens_preview_window(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-13: 信号行の実ダブルクリックで単一プレビューウィンドウが開き、プレビュー
    タブに波形が描画される (入力経路が追加からプレビューへ変更)。"""
    skip_unless_real_display()

    window, _key = _make_window_with_two_panels_and_signal(qtbot, tmp_path)
    pw = window.signal_preview_window
    assert not pw.isVisible(), "プレビューウィンドウはダブルクリックまで閉じているべき"

    tree = window.channel_browser_view.tree
    model = (
        window.channel_browser_view.model
    )  # FU-22 B: proxy dropped, tree is model-direct
    qtbot.waitUntil(
        lambda: tree.visualRect(model.index(0, 0)).height() > 0, timeout=3000
    )
    rect = tree.visualRect(model.index(0, 0))
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    rx, ry = _phys_center(vp, local)

    # 実ダブルクリック (GetDoubleClickTime 窓内 2 連打) -> doubleClicked -> preview
    double_click(rx, ry)
    _pump_n(6)
    qtbot.waitUntil(lambda: pw.isVisible(), timeout=2000)
    shot = _shot(tmp_path, "03_dblclick_preview")
    assert pw.isVisible(), (
        f"実ダブルクリックでプレビューウィンドウが開かない。screenshot: {shot}"
    )
    # プレビュータブに波形が 1 本描画される (ユーザーが実際に見る終状態)。
    qtbot.waitUntil(lambda: len(pw.preview_plot.listDataItems()) == 1, timeout=2000)
    assert len(pw.preview_plot.listDataItems()) == 1, (
        f"プレビュータブに波形が描画されていない。screenshot: {shot}"
    )

    # ── T-C3 (F-0/UX-43): 軸ラベルが実描画パイプラインで実際に設定されている ──
    # (headless Layer B は setLabel 呼び出しの引数を直接検証済み — 本テストは
    # 実ダブルクリック -> show_signal -> _render という実経路の終状態を確認する)。
    _EVIDENCE_DIR_F0.mkdir(parents=True, exist_ok=True)
    shot_f0 = _EVIDENCE_DIR_F0 / "05_signal_preview_axis_labels.png"
    pw.grab().save(str(shot_f0))

    bottom_axis = pw.preview_plot.getAxis("bottom")
    assert bottom_axis.labelText == "Time", (
        f"下軸ラベルが 'Time' でない: {bottom_axis.labelText!r}. screenshot: {shot_f0}"
    )
    assert bottom_axis.labelUnits == "s", (
        f"下軸単位が 's' でない: {bottom_axis.labelUnits!r}. screenshot: {shot_f0}"
    )
    left_axis = pw.preview_plot.getAxis("left")
    assert left_axis.labelText == "speed", (
        f"左軸ラベルが display_name 'speed' でない (:: 内部キー露出の疑い): "
        f"{left_axis.labelText!r}. screenshot: {shot_f0}"
    )
    assert "::" not in left_axis.labelText, (
        f"左軸ラベルに内部キー '::' が露出: {left_axis.labelText!r}"
    )
    # E-0 (UX-19): windowTitle は生キー("csv_1::speed")でなく bare 表示名
    # ("speed" — 単一ファイル・衝突なしのため qualify されない) を表示する。
    assert pw.windowTitle().endswith("speed"), (
        f"プレビューウィンドウのタイトルに信号名がない (got {pw.windowTitle()!r})。"
    )
    assert "::" not in pw.windowTitle(), (
        f"プレビューウィンドウのタイトルに内部キーが露出 (got {pw.windowTitle()!r})。"
    )
