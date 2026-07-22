"""Tests for GraphAreaView tab UI — SH-02 (corner + button & Ctrl+T).

Tests the affordances for adding a new tab:
- Corner widget "+" button
- Ctrl+T keyboard shortcut
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QLineEdit, QToolButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM


def _make_area(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from valisync.gui.views.graph_area_view import GraphAreaView

    vm = GraphAreaVM(AppViewModel(Session()))
    view = GraphAreaView(vm, panel_factory=lambda _vm: QLabel())
    qtbot.addWidget(view)
    return view


def test_corner_new_tab_button_adds_tab(qtbot: QtBot) -> None:
    # 計測 IA 刷新 spec §2.3: corner widget は「+」単体ではなく読み値トグルとの
    # 横並びコンテナ。cornerWidget() 自体の objectName ではなく子ボタンを探す。
    view = _make_area(qtbot)
    container = view.tabs.cornerWidget()
    btn = container.findChild(QToolButton, "new_tab_button")
    assert isinstance(btn, QToolButton)
    assert view.tabs.count() == 1
    btn.click()
    assert view.tabs.count() == 2
    assert view.vm.active_tab_index == 1  # add_tab is new tab active


def test_corner_container_holds_new_tab_and_readout_toggle(qtbot: QtBot) -> None:
    """spec §2.3: corner widget = 「+」と読み値トグルの横並びコンテナ (両方 findChild で見つかる)。"""
    view = _make_area(qtbot)
    container = view.tabs.cornerWidget()
    assert container.findChild(QToolButton, "new_tab_button") is not None
    assert container.findChild(QToolButton, "readout_toggle_button") is not None


def test_ctrl_t_shortcut_adds_tab(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    assert view._new_tab_shortcut.key() == QKeySequence("Ctrl+T")
    view._new_tab_shortcut.activated.emit()  # verify connection
    assert view.tabs.count() == 2


def test_close_button_removes_tab(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view.add_tab()
    view.add_tab()
    assert view.tabs.count() == 3
    view.tabs.tabCloseRequested.emit(1)  # close ボタン押下 = このシグナル
    assert view.tabs.count() == 2


def test_last_tab_close_button_suppressed(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QTabBar

    view = _make_area(qtbot)
    assert view.tabs.count() == 1
    bar = view.tabs.tabBar()
    pos = QTabBar.ButtonPosition(
        bar.style().styleHint(
            bar.style().StyleHint.SH_TabBar_CloseButtonPosition, None, bar
        )
    )
    assert bar.tabButton(0, pos) is None  # 最後の1枚は閉じるボタンなし
    # そして close 要求が来ても最後の1枚は残る (防御)
    view.tabs.tabCloseRequested.emit(0)
    assert view.tabs.count() == 1


def test_close_button_reappears_above_one_tab(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QTabBar

    view = _make_area(qtbot)
    view.add_tab()  # 2 タブ = close ボタンあり
    bar = view.tabs.tabBar()
    pos = QTabBar.ButtonPosition(
        bar.style().styleHint(
            bar.style().StyleHint.SH_TabBar_CloseButtonPosition, None, bar
        )
    )
    assert bar.tabButton(0, pos) is not None


def test_double_click_opens_rename_editor(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view._begin_rename(0)  # tabBarDoubleClicked の接続先
    editor = view._rename_editor
    assert isinstance(editor, QLineEdit)
    assert editor.text() == "タブ 1"


def test_rename_commit_updates_vm(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view._begin_rename(0)
    view._rename_editor.setText("速度ログ")
    view._rename_editor.committed.emit("速度ログ")
    assert view.vm.tabs()[0].name == "速度ログ"
    assert view._rename_editor is None  # 確定で editor 破棄


def test_rename_cancel_keeps_name(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view._begin_rename(0)
    view._rename_editor.setText("破棄される")
    view._rename_editor.cancelled.emit()
    assert view.vm.tabs()[0].name == "タブ 1"
    assert view._rename_editor is None


def test_rename_invalid_length_keeps_editor_open(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view._begin_rename(0)
    view._rename_editor.committed.emit("x" * 33)  # 32 字超
    assert view.vm.tabs()[0].name == "タブ 1"  # 変更されない
    assert view._rename_editor is not None  # 編集継続


def test_rename_double_commit_is_single_shot(qtbot: QtBot) -> None:
    # Focus loss re-entrancy で committed が2回飛んでも、例外なし・editor 破棄・
    # VM 名は一度だけ設定される (二重 rename/_rebuild を防ぐ単発ガードの回帰)。
    view = _make_area(qtbot)
    view._begin_rename(0)
    editor = view._rename_editor
    assert editor is not None
    editor.committed.emit("単発確認")
    editor.committed.emit("単発確認")  # 再入相当の2回目は no-op であるべき
    assert view.vm.tabs()[0].name == "単発確認"
    assert view._rename_editor is None
