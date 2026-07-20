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
