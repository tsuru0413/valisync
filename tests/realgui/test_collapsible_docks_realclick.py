"""Layer C: 折りたたみ可能ドックが実 OS クリックで実際に縮む/フロートする。

`--realgui` opt-in・実ディスプレイ+Windows 必須。この受け入れは Layer A/B で
再チェック不能: `CollapsibleDockTitleBar.set_collapsed` の効果 (dock の
`maximumHeight` クランプ→実レイアウトでの高さ縮小、`resizeDocks` による展開時の
高さ復元) は headless では実ジオメトリが動かず確証できない
(memory: gui_isvisible_true_for_offscreen_hidden_dock — QDockWidget.isVisible()
は画面外/縮んでいなくても True を返しうる偽陰性計器なので、内容の非可視判定は
`visibleRegion()` を使い isVisible() には頼らない)。

トグルボタンの物理座標はタイトルバー内ウィジェットの geometry から都度算出し、
実 Win32 マウス入力 (`tests/realgui/_realgui_input`) でクリックする。
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


def _content_hidden(widget) -> bool:  # type: ignore[no-untyped-def]
    """内容が実際に画面上へ描かれていないことの判定。

    isVisible() は隠蔽経路によっては偽陽性/偽陰性の罠がある計器
    (gui_isvisible_true_for_offscreen_hidden_dock) なので使わず、
    実際に描画対象になる visibleRegion の空判定で見る。
    """
    return widget.visibleRegion().isEmpty()


def _grab(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    path = tmp_path / name
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(path))
    return path


def test_real_click_toggle_collapses_file_dock_height_and_hides_content(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """トグルボタンの実クリックで file_dock の高さが実際に縮み、内容が非可視化する。"""
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    dock = mw.file_dock
    bar = mw._collapsible_bars["file_dock"]
    content = dock.widget()
    assert content is not None

    qtbot.waitUntil(
        lambda: bar._toggle_button.isVisible() and bar._toggle_button.width() > 0,
        timeout=3000,
    )

    # 前提: 初期状態は展開・内容可視・タイトルバー高より十分大きい実高を持つ。
    assert not bar.is_collapsed()
    assert not _content_hidden(content), "setup: 展開状態で内容が既に非可視"
    initial_height = dock.height()
    title_h = bar.sizeHint().height()
    assert initial_height > title_h + 40, (
        f"setup: dock 高 {initial_height}px がタイトルバー高 {title_h}px を"
        "十分超えていない (テスト前提が崩れている)"
    )

    shot_before = _grab(tmp_path, "collapsible_before.png")

    # --- 実クリック: 折りたたみトグル ---
    _real_click(*_phys(bar._toggle_button))
    qtbot.waitUntil(lambda: bar.is_collapsed(), timeout=3000)
    qtbot.waitUntil(lambda: dock.height() <= title_h + 8, timeout=3000)

    shot_collapsed = _grab(tmp_path, "collapsible_after_collapse.png")
    collapsed_height = dock.height()
    print(
        f"[collapsible] initial_height={initial_height} title_h={title_h} "
        f"collapsed_height={collapsed_height}"
    )
    print(f"[collapsible] screenshots: {shot_before} , {shot_collapsed}")

    assert bar.is_collapsed(), f"実クリックでトグルが効いていない。{shot_collapsed}"
    assert collapsed_height <= title_h + 8, (
        f"折りたたみ後の dock 高 {collapsed_height}px がタイトルバー高 "
        f"{title_h}px 付近まで縮んでいない。screenshot: {shot_collapsed}"
    )
    assert collapsed_height < initial_height * 0.5, (
        f"折りたたみで dock 高が有意に減少していない "
        f"(initial={initial_height}, collapsed={collapsed_height})。"
        f"screenshot: {shot_collapsed}"
    )
    assert _content_hidden(content), (
        f"折りたたみ後も内容が画面上に描画されている (visibleRegion 非空)。"
        f"screenshot: {shot_collapsed}"
    )

    # --- 実クリック: 再トグルで展開 ---
    _real_click(*_phys(bar._toggle_button))
    qtbot.waitUntil(lambda: not bar.is_collapsed(), timeout=3000)
    qtbot.waitUntil(lambda: dock.height() > title_h * 2, timeout=3000)

    shot_expanded = _grab(tmp_path, "collapsible_after_expand.png")
    expanded_height = dock.height()
    print(f"[collapsible] expanded_height={expanded_height}")
    print(f"[collapsible] screenshot: {shot_expanded}")

    assert not bar.is_collapsed(), f"再クリックで展開に戻らない。{shot_expanded}"
    assert expanded_height > title_h * 2, (
        f"展開後の dock 高 {expanded_height}px がタイトルバー高 {title_h}px の"
        f"2倍を超えて育っていない (実際に展開していない)。screenshot: {shot_expanded}"
    )
    assert expanded_height >= initial_height * 0.6, (
        f"展開で高さが復元されていない "
        f"(initial={initial_height}, expanded={expanded_height})。"
        f"screenshot: {shot_expanded}"
    )
    assert not _content_hidden(content), (
        f"展開後も内容が画面上に描画されていない (visibleRegion 空)。"
        f"screenshot: {shot_expanded}"
    )


def test_real_click_float_button_floats_file_dock(qtbot: QtBot, tmp_path: Path) -> None:
    """フロートボタンの実クリックで file_dock が isFloating()==True になる。"""
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    dock = mw.file_dock
    bar = mw._collapsible_bars["file_dock"]

    qtbot.waitUntil(
        lambda: bar._float_button.isVisible() and bar._float_button.width() > 0,
        timeout=3000,
    )
    assert not dock.isFloating()

    _real_click(*_phys(bar._float_button))
    qtbot.waitUntil(lambda: dock.isFloating(), timeout=3000)

    shot = _grab(tmp_path, "collapsible_float.png")
    print(f"[collapsible] isFloating after real click = {dock.isFloating()}")
    print(f"[collapsible] screenshot: {shot}")

    assert dock.isFloating(), (
        f"フロートボタンの実クリックで file_dock がフロート化しない。screenshot: {shot}"
    )


def test_real_click_close_button_closes_file_dock(qtbot: QtBot, tmp_path: Path) -> None:
    """閉じるボタンの実クリックで file_dock が isVisible()==False になる。"""
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    dock = mw.file_dock
    bar = mw._collapsible_bars["file_dock"]

    qtbot.waitUntil(
        lambda: bar._close_button.isVisible() and bar._close_button.width() > 0,
        timeout=3000,
    )
    assert dock.isVisible()

    _real_click(*_phys(bar._close_button))
    qtbot.waitUntil(lambda: not dock.isVisible(), timeout=3000)

    shot = _grab(tmp_path, "collapsible_close.png")
    print(f"[collapsible] isVisible after real click on close = {dock.isVisible()}")
    print(f"[collapsible] screenshot: {shot}")

    assert not dock.isVisible(), (
        f"閉じるボタンの実クリックで file_dock が閉じない。screenshot: {shot}"
    )
