"""CollapsibleDockTitleBar — ドック共通の展開時タイトルバー。

畳み機構自体 (hide+辺レール) は MainWindow が担う (edge-aware-dock-collapse)。
ここは「chevron が collapse_requested を出す」「フロート中は無効化する」
「フロート/閉じるボタンが機能する」というタイトルバー単体の責務のみ検証する。
"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]


def _dock_in_window(qtbot: QtBot):
    from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow

    win = QMainWindow()
    dock = QDockWidget("D", win)
    dock.setObjectName("d")
    content = QLabel("content")
    dock.setWidget(content)
    from PySide6.QtCore import Qt

    win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    qtbot.addWidget(win)
    return win, dock, content


def test_float_and_close_buttons(qtbot: QtBot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    dock.setTitleBarWidget(bar)
    win.show()
    assert not dock.isFloating()
    bar._float_button.click()
    assert dock.isFloating()  # フロート トグル
    bar._close_button.click()
    assert not dock.isVisible()  # 閉じる


def test_chevron_emits_collapse_requested(qtbot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    win.show()
    seen: list = []
    bar.collapse_requested.connect(lambda: seen.append(True))
    bar._toggle_button.click()
    assert seen == [True]


def test_float_and_close_buttons_min_height_24(qtbot: QtBot):
    # UX-38: float/close の text ボタン (実測 44x19) は縦方向が不足していたため、
    # setMinimumHeight で当たり判定の高さを 24px 以上へ保証する [幅は縮めない]。
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    dock.setTitleBarWidget(bar)
    win.show()
    for btn in (bar._float_button, bar._close_button):
        assert btn.minimumHeight() >= 24, (
            f"{btn.text()!r} minimumHeight {btn.minimumHeight()} < 24 (UX-38)"
        )


def test_chevron_disabled_while_floating(qtbot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    dock.setTitleBarWidget(bar)
    win.show()
    assert bar._toggle_button.isEnabled()
    dock.setFloating(True)
    assert not bar._toggle_button.isEnabled()  # フロート中は無効
    dock.setFloating(False)
    assert bar._toggle_button.isEnabled()


# ---------------------------------------------------------------------------
# シェブロンの辺解決 (B4/UX-44・diag-readout-consistency Task 2)
# ---------------------------------------------------------------------------


def test_bottom_dock_chevron_is_down(qtbot):
    # 下端の診断ドックは「下方向へ畳む」— chevron_down。
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    bar = win._collapsible_bars["diagnostics_dock"]
    assert bar.chevron_icon_name() == "chevron_down"


def test_right_dock_chevron_is_right(qtbot):
    # 既定レイアウトの File/Channel は右ドック — chevron_right (現行同値・無回帰)。
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    bar = win._collapsible_bars["file_dock"]
    assert bar.chevron_icon_name() == "chevron_right"


def test_chevron_follows_dock_moved_to_left(qtbot):
    # 実行時の辺移動 (D&D 相当) に追随する — dockLocationChanged 経由。
    from PySide6.QtCore import Qt

    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    bar = win._collapsible_bars["file_dock"]
    assert bar.chevron_icon_name() == "chevron_right"
    win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, win.file_dock)
    assert bar.chevron_icon_name() == "chevron_left"


def test_chevron_name_unchanged_when_floating_starts(qtbot):
    # フロート開始は NoDockWidgetArea で発火 (実測) — 写像は None を返し、
    # 呼び出し側 (スロット) は早期 return して直前のシェブロンを維持する。
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    bar = win._collapsible_bars["file_dock"]
    before = bar.chevron_icon_name()
    win.file_dock.setFloating(True)
    assert bar.chevron_icon_name() == before


def test_chevron_cache_key_changes_only_on_area_transition(qtbot):
    # icons.icon() はキャッシュ無しで毎回新規 QIcon のため cacheKey の恒等比較は
    # 不成立 (実測)。同一ボタンに設定された QIcon インスタンスの cacheKey を
    # 遷移の前後で比較し、変化「検出」のみに用いる (§2.4 テスト方針)。
    from PySide6.QtCore import Qt

    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    bar = win._collapsible_bars["file_dock"]
    before_key = bar._toggle_button.icon().cacheKey()
    win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, win.file_dock)
    after_key = bar._toggle_button.icon().cacheKey()
    assert before_key != after_key
