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


def _close_button_position(bar):  # type: ignore[no-untyped-def]
    """style-hint 解決位置 (D-3 §2.5: 実測 RightSide)。"""
    from PySide6.QtWidgets import QTabBar

    return QTabBar.ButtonPosition(
        bar.style().styleHint(
            bar.style().StyleHint.SH_TabBar_CloseButtonPosition, None, bar
        )
    )


def _has_pixel_near(image, expected_rgb, tol=40):  # type: ignore[no-untyped-def]
    """test_diagnostics_view.py/test_theme_icons.py と同型のピクセル走査ヘルパ
    (このファイルは自己完結の慣行に合わせローカル複製)。"""
    for y in range(image.height()):
        for x in range(image.width()):
            px = image.pixelColor(x, y)
            if px.alpha() > 200 and (
                abs(px.red() - expected_rgb[0]) < tol
                and abs(px.green() - expected_rgb[1]) < tol
                and abs(px.blue() - expected_rgb[2]) < tol
            ):
                return True
    return False


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
    """D-3 §2.5: setTabsClosable(False)+自前ボタンなので、単一タブは
    そもそも close ボタンを設置しない (旧 setTabButton(0,pos,None) による
    事後抑制ではない — 前提を自前ボタンへ書換)。"""
    view = _make_area(qtbot)
    assert view.tabs.count() == 1
    bar = view.tabs.tabBar()
    pos = _close_button_position(bar)
    assert bar.tabButton(0, pos) is None  # 最後の1枚は閉じるボタンなし
    # そして close 要求が来ても最後の1枚は残る (防御)
    view.tabs.tabCloseRequested.emit(0)
    assert view.tabs.count() == 1


def test_close_button_reappears_above_one_tab(qtbot: QtBot) -> None:
    """D-3 §2.5: 2 タブ以上は全タブへ自前 QToolButton (tab_close_button) が
    設置される (Qt 既定ボタンではない — 前提を自前ボタンへ書換)。"""
    view = _make_area(qtbot)
    view.add_tab()  # 2 タブ = close ボタンあり
    bar = view.tabs.tabBar()
    pos = _close_button_position(bar)
    btn = bar.tabButton(0, pos)
    assert isinstance(btn, QToolButton)
    assert btn.objectName() == "tab_close_button"


def test_tab_close_button_active_mode_consumes_close_hover_not_error(
    qtbot: QtBot,
) -> None:
    """タブ✕の hover (QIcon.Mode.Active) は close_hover トークンを消費する
    (D-3 §2.5・`_make_tab_close_button` の `active_color=c.close_hover`)。

    DARK では close_hover と error が同値 (#f38ba8) の三つ組であるため、値ベース
    の assert は `active_color=c.error` への誤配線を検出できない (LIGHT では
    close_hover=#d20f39 と error=#c0392b が分岐し実害になる — test_theme_qss.py
    の既存パターンと同型の盲点)。close_hover だけを識別可能な値へ分岐させた
    テーマを注入し、ボタンの Active ピクセルが分岐値へ追随し、error の元値
    (未分岐のまま #f38ba8) でないことを直接実証する。
    """
    import dataclasses

    from PySide6.QtGui import QIcon

    from valisync.gui.theme.tokens import DARK, Color, set_active

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, close_hover=Color(1, 2, 3))
    )
    set_active(alt)
    try:
        view = _make_area(qtbot)
        view.add_tab()  # 2 タブ = 自前✕ボタン設置
        bar = view.tabs.tabBar()
        pos = _close_button_position(bar)
        btn = bar.tabButton(0, pos)
        assert isinstance(btn, QToolButton)
        img = btn.icon().pixmap(16, 16, QIcon.Mode.Active).toImage()
        assert _has_pixel_near(img, (1, 2, 3))
        assert not _has_pixel_near(
            img, (DARK.colors.error.r, DARK.colors.error.g, DARK.colors.error.b)
        )
    finally:
        set_active(DARK)


def test_tab_close_button_click_resolves_current_index_after_earlier_removal(
    qtbot: QtBot,
) -> None:
    """D-3 §2.5: 自前✕ボタンはクリック時に tabBar 上の恒等走査で index を解決
    する (生成時の事前 capture は禁止) — 先頭タブが閉じてインデックスがずれた
    後、2番目の位置に来たボタンをクリックすると、そのボタンが指す(ずれた後の)
    タブ自身が正しく閉じることを検証する。

    Identity is tracked via tab NAME (VM state), not the QSplitter page widget
    -- ``_rebuild`` always discards and recreates every page's widget on every
    VM notify (see ``old_pages``), so widget identity does not survive a
    rebuild even for an unaffected tab; the tab's name does.
    """
    view = _make_area(qtbot)
    view.add_tab()
    view.add_tab()
    assert view.tabs.count() == 3
    name_1 = view.tabs.tabText(1)
    name_2 = view.tabs.tabText(2)

    bar = view.tabs.tabBar()
    pos = _close_button_position(bar)

    # 先頭タブを直接閉じる (別経路からの先行 close を模す) — 残り2枚が前へ詰まる。
    view.tabs.tabCloseRequested.emit(0)
    assert view.tabs.count() == 2
    assert view.tabs.tabText(0) == name_1
    assert view.tabs.tabText(1) == name_2

    # index=1 の✕ボタンをクリック — このボタンは (詰まった後の) name_2 の
    # タブに設置されたものであり、事前 capture された古い index ではなく
    # クリック時点の実位置を正しく解決しなければならない。
    btn = bar.tabButton(1, pos)
    assert isinstance(btn, QToolButton)
    btn.click()

    assert view.tabs.count() == 1
    assert view.tabs.tabText(0) == name_1  # name_2 のタブが閉じ、name_1 が残る


def test_tab_close_buttons_count_stable_after_many_rebuilds(qtbot: QtBot) -> None:
    """D-3 §2.5: 既定ボタンを setTabButton で事後に None 差し替えて抑制すると、
    置換前の widget が「setTabButton は置換しても削除しない」実測仕様により
    タブバーへ隠れ蓄積する実バグだった (旧 setTabsClosable(True) 経路)。多数回
    の add/remove 後もタブバーに寄生する孤児ボタンが残らないことを直接検証する
    (rebuild N 回後のボタン数不変ガード)。"""
    view = _make_area(qtbot)
    bar = view.tabs.tabBar()
    pos = _close_button_position(bar)

    for _ in range(15):
        view.add_tab()
    while view.tabs.count() > 4:
        view.remove_tab(0)
    for _ in range(10):
        view.add_tab()
        view.remove_tab(0)

    count = view.tabs.count()
    assert count > 1
    attached = [bar.tabButton(i, pos) for i in range(count)]
    assert all(isinstance(b, QToolButton) for b in attached)
    assert len(attached) == len({id(b) for b in attached})  # no duplicate identities

    # No orphaned custom close buttons remain parented anywhere under the tab
    # bar beyond the currently-attached set (the accumulating-leak regression:
    # setTabButton replacing/nulling a button on a live tab does not itself
    # delete the previous widget, so explicit disposal in _rebuild is load-
    # bearing here).
    orphans = [
        child
        for child in bar.findChildren(QToolButton)
        if child.objectName() == "tab_close_button" and child not in attached
    ]
    assert orphans == []


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
