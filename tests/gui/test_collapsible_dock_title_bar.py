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


def test_expand_restores_captured_height_via_resizedocks(qtbot: QtBot):
    """展開時 resizeDocks に「畳む直前に控えた高さ」が渡る。

    タイトルバー高より大きい高さで畳んだ場合、展開時にその実高が復元引数に使われる。
    """
    from PySide6.QtCore import Qt

    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    dock.setTitleBarWidget(bar)
    win.resize(400, 600)
    win.show()
    qtbot.waitExposed(win)
    # resizeDocks 呼び出しを捕捉
    calls: list[tuple] = []
    original_resize_docks = win.resizeDocks
    win.resizeDocks = lambda docks, sizes, orient: (
        calls.append((list(docks), list(sizes), orient)),
        original_resize_docks(docks, sizes, orient),
    )[1]  # type: ignore[assignment]
    # 畳む直前の実高を記録 (タイトルバー高より大きいことを保証)
    initial_height = dock.height()
    assert initial_height > bar.sizeHint().height(), (
        "setup: dock高がタイトル高を超える必要"
    )
    # 畳んで→展開
    bar.set_collapsed(True)
    bar.set_collapsed(False)
    # resizeDocks が呼ばれたことを確認
    assert calls, "展開で resizeDocks が呼ばれていない"
    docks, sizes, orient = calls[-1]
    assert docks == [dock], f"expected [dock], got {docks}"
    assert orient == Qt.Orientation.Vertical
    # 控えた実高が復元に使われる
    assert sizes[0] == initial_height, f"expected {initial_height}, got {sizes[0]}"


def test_expand_without_prior_collapse_uses_default_height(qtbot: QtBot):
    """展開時に「未控え状態」または「小さい高さで畳んだ」場合は既定高180を使う。

    fresh 状態で set_collapsed(False) は idempotency ガードで no-op。
    dock 高がタイトルバー高以下の状態で畳む→展開すると既定180が渡る。
    """
    from PySide6.QtCore import Qt

    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    dock.setTitleBarWidget(bar)
    win.show()
    qtbot.waitExposed(win)
    # resizeDocks 呼び出しを捕捉
    calls: list[tuple] = []
    original_resize_docks = win.resizeDocks
    win.resizeDocks = lambda docks, sizes, orient: (
        calls.append((list(docks), list(sizes), orient)),
        original_resize_docks(docks, sizes, orient),
    )[1]  # type: ignore[assignment]
    # fresh set_collapsed(False) は no-op (既に展開状態)
    bar.set_collapsed(False)
    assert calls == [], "fresh set_collapsed(False) で resizeDocks が呼ばれてはいけない"
    # dock 高をタイトルバー高以下に強制 (setFixedHeight で物理的に制約)
    title_height = bar.sizeHint().height()
    dock.setFixedHeight(title_height)  # 小さい高さで固定
    # 確認: 現在高がタイトル高以下
    assert dock.height() <= title_height, (
        f"dock height {dock.height()} should be <= {title_height}"
    )
    # 畳んで→展開
    bar.set_collapsed(True)
    bar.set_collapsed(False)
    # resizeDocks が呼ばれたことを確認
    assert calls, "展開で resizeDocks が呼ばれていない"
    docks, sizes, orient = calls[-1]
    assert docks == [dock]
    assert orient == Qt.Orientation.Vertical
    # 既定180が渡される (小さい高さで畳んだため _expanded_height が更新されない)
    assert sizes[0] == 180, f"expected 180 (default), got {sizes[0]}"
