"""Layer C: 辺対応の折りたたみ (edge-aware-dock-collapse) が実 OS クリックで
実際に中央スペースを回収する。

`--realgui` opt-in・実ディスプレイ+Windows 必須。この受け入れは Layer A/B で
再チェック不能: chevron クリック→`dock.hide()`+対応辺レールへのタブ追加、
レールタブクリック→`dock.show()`+`resizeDocks` による幅/高さ復元は、QMainWindow の
実ドックエリアレイアウトが実レイアウト/実ペイントを経ないと動かないため headless
では確証できない
(memory: gui_dock_toggle_width_change_needs_real_display_and_layout — dock
toggle が中央幅/高さを変えるかは offscreen では確認できずレイアウト依存でもある。
gui_isvisible_true_for_offscreen_hidden_dock — 内容の非可視判定は isVisible() に
頼らず、本テストは明示 hide() 経路なので isHidden() で見る)。

トグル/レールタブの物理座標はウィジェットの geometry から都度算出し、実 Win32
マウス入力 (`tests/realgui/_realgui_input`) でクリックする。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui

# QSettings 隔離 (実 ValiSync 設定汚染/テスト間漏れ防止) は
# tests/realgui/conftest.py の autouse fixture が全 realgui テストへ適用する。


def _shown_mw(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # _restore_state() が実レジストリから最大化状態を復元しうるため解除し、
    # availableGeometry 内の既知ジオメトリに固定する (オフスクリーン配置は
    # 座標計算がずれる既知の罠)。
    mw.showNormal()
    ag = QApplication.primaryScreen().availableGeometry()
    mw.setGeometry(
        ag.x() + 40,
        ag.y() + 40,
        min(1100, ag.width() - 80),
        min(760, ag.height() - 80),
    )
    mw.raise_()
    mw.activateWindow()
    qtbot.waitExposed(mw)
    qtbot.waitUntil(lambda: not mw.isMaximized() and mw.width() > 800, timeout=3000)
    QApplication.processEvents()
    return mw


def _phys(widget) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """widget 中心の物理スクリーンピクセル (DPR スケール) を呼び出し時点で算出。"""
    c = widget.rect().center()
    g = widget.mapToGlobal(c)
    dpr = widget.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _real_click(x: int, y: int) -> None:
    from PySide6.QtWidgets import QApplication

    at(x, y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(x, y, LUP)
    for _ in range(6):
        QApplication.processEvents()
        time.sleep(0.02)


def _settle(extra_pumps: int = 12) -> None:
    """dock hide/show 後の QMainWindowLayout 再計算が確定するまで追加ポンプする。"""
    from PySide6.QtWidgets import QApplication

    for _ in range(extra_pumps):
        QApplication.processEvents()
        time.sleep(0.02)


def _grab(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    path = tmp_path / name
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(path))
    return path


def test_collapse_both_right_docks_reclaims_width_and_expands(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """右カラムの file_dock/channel_dock は縦積み (`splitDockWidget` Vertical) の
    兄弟同士で同じカラム幅を分け合うため、片方だけ chevron で畳んでも兄弟がカラム
    幅を保持し中央幅は増えない (実測: initial 860 → file のみ畳み 860 → 両方畳み
    1120)。これは Qt の縦積みレイアウトどおりで実装バグではない
    (memory: gui_dock_toggle_width_change_needs_real_display_and_layout)。
    両方を chevron 実クリックで畳むと右レールに縦タブが2個出て中央
    (`_central_with_rails`) 幅が実際に増加し、各タブ実クリックで両方展開すると
    幅がほぼ元へ戻る。
    """
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    file_dock = mw.file_dock
    channel_dock = mw.channel_dock
    file_bar = mw._collapsible_bars["file_dock"]
    central = mw._central_with_rails
    rail = mw._collapse_rails[mw.dockWidgetArea(file_dock)]
    assert mw.dockWidgetArea(channel_dock) == mw.dockWidgetArea(file_dock), (
        "setup: file_dock/channel_dock が同じ辺レールを共有していない"
    )

    qtbot.waitUntil(
        lambda: (
            file_bar._toggle_button.isVisible() and file_bar._toggle_button.width() > 0
        ),
        timeout=3000,
    )
    assert not file_dock.isHidden(), "setup: file_dock が既に隠れている"
    assert not channel_dock.isHidden(), "setup: channel_dock が既に隠れている"
    assert rail.is_empty(), "setup: レールに既にタブがある"

    _settle()
    initial_width = central.width()
    shot_before = _grab(tmp_path, "edge_collapse_both_right_before.png")

    # --- 実クリック: file_dock を畳む (兄弟 channel_dock がカラム幅を保持する
    # ため、この時点ではまだ中央幅は増加しないはず — 次の channel_dock 畳みで
    # 初めて増加することを後段で確認する) ---
    _real_click(*_phys(file_bar._toggle_button))
    qtbot.waitUntil(lambda: file_dock.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: file_dock in rail._tabs, timeout=3000)
    _settle()

    after_file_only_width = central.width()
    print(
        f"[edge-collapse-both-right] initial={initial_width} "
        f"after_file_only={after_file_only_width}"
    )

    # --- 実クリック: channel_dock を畳む (chevron 座標は file_dock 畳みでレール
    # 上のレイアウトが動いた後に再取得する) ---
    channel_bar = mw._collapsible_bars["channel_dock"]
    qtbot.waitUntil(
        lambda: (
            channel_bar._toggle_button.isVisible()
            and channel_bar._toggle_button.width() > 0
        ),
        timeout=3000,
    )
    _real_click(*_phys(channel_bar._toggle_button))
    qtbot.waitUntil(lambda: channel_dock.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: channel_dock in rail._tabs, timeout=3000)
    _settle()

    collapsed_width = central.width()
    shot_collapsed = _grab(tmp_path, "edge_collapse_both_right_after.png")
    print(f"[edge-collapse-both-right] collapsed_width={collapsed_width}")
    print(f"[edge-collapse-both-right] screenshots: {shot_before} , {shot_collapsed}")

    assert file_dock.isHidden(), (
        f"実クリックで file_dock が隠れていない。screenshot: {shot_collapsed}"
    )
    assert channel_dock.isHidden(), (
        f"実クリックで channel_dock が隠れていない。screenshot: {shot_collapsed}"
    )
    assert file_dock in rail._tabs and channel_dock in rail._tabs, (
        f"両方畳み後に右レールへ2タブ出ていない (tabs={len(rail._tabs)})。"
        f"screenshot: {shot_collapsed}"
    )
    assert len(rail._tabs) == 2, (
        f"右レールのタブ数が2ではない (tabs={len(rail._tabs)})。"
        f"screenshot: {shot_collapsed}"
    )
    assert collapsed_width > initial_width + 20, (
        f"両方畳みで中央幅が有意に増加していない "
        f"(initial={initial_width}, after_file_only={after_file_only_width}, "
        f"collapsed={collapsed_width})。screenshot: {shot_collapsed}"
    )

    # --- 実クリック: 右レールの file_dock 縦タブで展開 ---
    file_tab = rail._tabs[file_dock]
    qtbot.waitUntil(
        lambda: file_tab.isVisible() and file_tab.width() > 0 and file_tab.height() > 0,
        timeout=3000,
    )
    _real_click(*_phys(file_tab))
    qtbot.waitUntil(lambda: not file_dock.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: file_dock not in rail._tabs, timeout=3000)
    _settle()

    # --- 実クリック: 残った channel_dock 縦タブで展開 (座標は file_dock 展開で
    # レール上のレイアウトが動いた後に再取得する) ---
    channel_tab = rail._tabs[channel_dock]
    qtbot.waitUntil(
        lambda: (
            channel_tab.isVisible()
            and channel_tab.width() > 0
            and channel_tab.height() > 0
        ),
        timeout=3000,
    )
    _real_click(*_phys(channel_tab))
    qtbot.waitUntil(lambda: not channel_dock.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: rail.is_empty(), timeout=3000)
    _settle()

    expanded_width = central.width()
    shot_expanded = _grab(tmp_path, "edge_collapse_both_right_expanded.png")
    print(f"[edge-collapse-both-right] expanded_width={expanded_width}")
    print(f"[edge-collapse-both-right] screenshot: {shot_expanded}")

    assert not file_dock.isHidden(), (
        f"タブ実クリックで file_dock が再表示されない。screenshot: {shot_expanded}"
    )
    assert not channel_dock.isHidden(), (
        f"タブ実クリックで channel_dock が再表示されない。screenshot: {shot_expanded}"
    )
    assert rail.is_empty(), (
        f"展開後もレールにタブが残っている。screenshot: {shot_expanded}"
    )
    assert expanded_width >= initial_width - 40, (
        f"展開で中央幅がほぼ元へ戻っていない "
        f"(initial={initial_width}, collapsed={collapsed_width}, "
        f"expanded={expanded_width})。screenshot: {shot_expanded}"
    )


def test_collapse_bottom_dock_horizontal(qtbot: QtBot, tmp_path: Path) -> None:
    """下ドック (diagnostics_dock) を chevron 実クリックで畳むと下レールに横チップが
    出て中央高さが実際に増加し、チップ実クリックで高さが元へ戻る。
    """
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    dock = mw.diagnostics_dock
    bar = mw._collapsible_bars["diagnostics_dock"]
    central = mw._central_with_rails
    rail = mw._collapse_rails[mw.dockWidgetArea(dock)]

    qtbot.waitUntil(
        lambda: bar._toggle_button.isVisible() and bar._toggle_button.width() > 0,
        timeout=3000,
    )
    assert not dock.isHidden(), "setup: diagnostics_dock が既に隠れている"
    assert rail.is_empty(), "setup: レールに既にタブがある"

    _settle()
    initial_height = central.height()
    shot_before = _grab(tmp_path, "edge_collapse_bottom_before.png")

    # --- 実クリック: chevron で畳む ---
    _real_click(*_phys(bar._toggle_button))
    qtbot.waitUntil(lambda: dock.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: dock in rail._tabs, timeout=3000)
    _settle()

    collapsed_height = central.height()
    shot_collapsed = _grab(tmp_path, "edge_collapse_bottom_after.png")
    print(
        f"[edge-collapse-bottom] initial_height={initial_height} "
        f"collapsed_height={collapsed_height}"
    )
    print(f"[edge-collapse-bottom] screenshots: {shot_before} , {shot_collapsed}")

    assert dock.isHidden(), (
        f"実クリックで diagnostics_dock が隠れていない。screenshot: {shot_collapsed}"
    )
    assert not rail.is_empty(), (
        f"畳み後にレールへタブが出ていない。screenshot: {shot_collapsed}"
    )
    assert collapsed_height > initial_height + 20, (
        f"畳みで中央高さが有意に増加していない "
        f"(initial={initial_height}, collapsed={collapsed_height})。"
        f"screenshot: {shot_collapsed}"
    )

    # --- 実クリック: レールの横チップで展開 ---
    tab = rail._tabs[dock]
    qtbot.waitUntil(
        lambda: tab.isVisible() and tab.width() > 0 and tab.height() > 0,
        timeout=3000,
    )
    _real_click(*_phys(tab))
    qtbot.waitUntil(lambda: not dock.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: rail.is_empty(), timeout=3000)
    _settle()

    expanded_height = central.height()
    shot_expanded = _grab(tmp_path, "edge_collapse_bottom_expanded.png")
    print(f"[edge-collapse-bottom] expanded_height={expanded_height}")
    print(f"[edge-collapse-bottom] screenshot: {shot_expanded}")

    assert not dock.isHidden(), (
        "タブ実クリックで diagnostics_dock が再表示されない。"
        f"screenshot: {shot_expanded}"
    )
    assert rail.is_empty(), (
        f"展開後もレールにタブが残っている。screenshot: {shot_expanded}"
    )
    assert expanded_height < collapsed_height - 20, (
        f"展開で中央高さが有意に減少していない (元に戻っていない) "
        f"(collapsed={collapsed_height}, expanded={expanded_height})。"
        f"screenshot: {shot_expanded}"
    )


def test_float_disables_collapse_toggle(qtbot: QtBot, tmp_path: Path) -> None:
    """フロートボタンの実クリックで file_dock がフロート化し、chevron (畳みトグル)
    が無効化される (フロート中は畳み先の辺が無いため)。
    """
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    dock = mw.file_dock
    bar = mw._collapsible_bars["file_dock"]

    qtbot.waitUntil(
        lambda: bar._float_button.isVisible() and bar._float_button.width() > 0,
        timeout=3000,
    )
    assert not dock.isFloating(), "setup: file_dock が既にフロートしている"
    assert bar._toggle_button.isEnabled(), "setup: chevron が既に無効"

    _real_click(*_phys(bar._float_button))
    qtbot.waitUntil(lambda: dock.isFloating(), timeout=3000)
    qtbot.waitUntil(lambda: not bar._toggle_button.isEnabled(), timeout=3000)

    shot = _grab(tmp_path, "edge_collapse_float.png")
    print(
        f"[edge-collapse-float] isFloating={dock.isFloating()} "
        f"chevron_enabled={bar._toggle_button.isEnabled()}"
    )
    print(f"[edge-collapse-float] screenshot: {shot}")

    assert dock.isFloating(), (
        f"フロートボタンの実クリックで file_dock がフロート化しない。screenshot: {shot}"
    )
    assert not bar._toggle_button.isEnabled(), (
        f"フロート中も chevron が有効なまま (畳み不可のはずが押せてしまう)。"
        f"screenshot: {shot}"
    )
