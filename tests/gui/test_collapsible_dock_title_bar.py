"""CollapsibleDockTitleBar — ドック共通の折りたたみタイトルバー (増分C Task 2)。"""

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


def test_collapse_hides_content_and_clamps_maxheight(qtbot: QtBot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    dock.setTitleBarWidget(bar)
    win.show()
    qtbot.waitExposed(win)
    assert not bar.is_collapsed()
    bar.set_collapsed(True)
    assert bar.is_collapsed()
    assert not content.isVisible()  # 内容 hide
    assert dock.maximumHeight() <= bar.sizeHint().height() + 4  # タイトル高にクランプ
    bar.set_collapsed(False)
    assert not bar.is_collapsed()
    assert content.isVisible()
    assert dock.maximumHeight() >= 10000  # クランプ解除 (QWIDGETSIZE_MAX)


def test_toggle_emits_collapsed_changed(qtbot: QtBot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    win.show()
    seen: list[bool] = []
    bar.collapsed_changed.connect(seen.append)
    bar._toggle_button.click()  # トグルボタン実クリック相当
    bar._toggle_button.click()
    assert seen == [True, False]


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
