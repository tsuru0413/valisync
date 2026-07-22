"""ドックトグルの三態化 (D-3 Task2/UX-45) — spec §2.3 の純ロジックと
§3 の状態機械 (Layer B) を検証する。

toggleViewAction (Qt 組込み) をカスタム checkable QAction へ置換した設計の
核心は「並行状態を作らない」こと (isHidden() ポーリング + dockWidgetArea()
再プローブ・シグナル引数は判定に使わない)。ここでのテストは主にその設計制約
が実際に守られていることを実 MainWindow で確認する。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolBar
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.app import build_main_window
from valisync.gui.strings import strip_mnemonic
from valisync.gui.views.main_window import _dock_toggle_state

# ---------------------------------------------------------------------------
# Step 1: 写像純ロジック — (is_hidden, collapsed, edge) の全域表 (2x2x3=12)
# ---------------------------------------------------------------------------

_EDGES = (
    Qt.DockWidgetArea.LeftDockWidgetArea,
    Qt.DockWidgetArea.RightDockWidgetArea,
    Qt.DockWidgetArea.BottomDockWidgetArea,
)
_SUFFIX = {
    Qt.DockWidgetArea.LeftDockWidgetArea: "left",
    Qt.DockWidgetArea.RightDockWidgetArea: "right",
    Qt.DockWidgetArea.BottomDockWidgetArea: "bottom",
}


@pytest.mark.parametrize("edge", _EDGES)
@pytest.mark.parametrize("is_hidden", [False, True])
@pytest.mark.parametrize("collapsed", [False, True])
def test_dock_toggle_state_full_domain(
    collapsed: bool, is_hidden: bool, edge: Qt.DockWidgetArea
) -> None:
    checked, icon_name = _dock_toggle_state(is_hidden, collapsed, edge)
    suffix = _SUFFIX[edge]
    if collapsed:
        # collapsed は is_hidden の値に関係なく最優先 (spec §2.3 の状態表)。
        assert checked is True
        assert icon_name == f"dock_panel_{suffix}_partial"
    elif not is_hidden:
        assert checked is True
        assert icon_name == f"dock_panel_{suffix}"
    else:
        assert checked is False
        assert icon_name == f"dock_panel_{suffix}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _view_menu(win: object):
    """ "表示" メニューを実メニューバーから解決する (_analyze_menu と同型)。

    submenu の生存は .menu() を呼んだ QAction ラッパの生存に紐づく (shiboken) —
    ラッパを保持しないと GC されて "already deleted" になる
    (memory gui_pyside_qaction_submenu_shiboken_lifetime)。
    """
    act = next(
        a
        for a in win.menuBar().actions()  # type: ignore[attr-defined]
        if strip_mnemonic(a.text()) == "表示"
    )
    menu = act.menu()
    menu._keepalive = act  # type: ignore[attr-defined]
    return menu


def _toolbar(win: object) -> QToolBar:
    tb = win.findChild(QToolBar, "main_toolbar")  # type: ignore[attr-defined]
    assert tb is not None
    return tb


# ---------------------------------------------------------------------------
# 文言・2面参照一致・TextBesideIcon
# ---------------------------------------------------------------------------


def test_dock_action_texts_match_dock_titles(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    assert win._dock_actions["file_dock"].text() == "ファイルブラウザ"
    assert win._dock_actions["channel_dock"].text() == "チャンネルブラウザ"
    assert win._dock_actions["diagnostics_dock"].text() == "診断"


def test_view_menu_and_toolbar_share_same_action_instances(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    menu = _view_menu(win)
    toolbar = _toolbar(win)
    for name in ("file_dock", "channel_dock", "diagnostics_dock"):
        action = win._dock_actions[name]
        assert action in menu.actions()
        assert action in toolbar.actions()


def test_toolbar_dock_buttons_use_text_beside_icon_others_do_not(
    qtbot: QtBot,
) -> None:
    """File/Channel は同一辺 (右) で三態アイコンが同一になり、テキスト無しでは
    区別できない (実測済みの退行) ため、ドック 3 ボタンだけ TextBesideIcon
    にする。他のツールバーボタンは既定のまま (spec §2.3)。"""
    win = build_main_window()
    qtbot.addWidget(win)
    toolbar = _toolbar(win)
    for name in ("file_dock", "channel_dock", "diagnostics_dock"):
        button = toolbar.widgetForAction(win._dock_actions[name])
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon

    open_button = toolbar.widgetForAction(win.shell_actions.action("open"))
    assert open_button.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonTextBesideIcon


def test_toggle_view_action_not_listed_on_either_face(qtbot: QtBot) -> None:
    """toggleViewAction はどこにも掲載しない (QDockWidget 組込み action 自体は
    生存 — spec §2.3)。"""
    win = build_main_window()
    qtbot.addWidget(win)
    menu = _view_menu(win)
    toolbar = _toolbar(win)
    for dock in (win.file_dock, win.channel_dock, win.diagnostics_dock):
        tva = dock.toggleViewAction()
        assert tva not in menu.actions()
        assert tva not in toolbar.actions()


# ---------------------------------------------------------------------------
# 基本 5 遷移
# ---------------------------------------------------------------------------


def test_toggle_show_hide_show(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    action = win._dock_actions["file_dock"]
    assert not win.file_dock.isHidden()
    assert action.isChecked() is True

    action.trigger()  # 展開 → クリック → 非表示

    assert win.file_dock.isHidden()
    assert action.isChecked() is False

    action.trigger()  # 非表示 → クリック → 展開 (+raise_ は別テストで確認)

    assert not win.file_dock.isHidden()
    assert action.isChecked() is True


def test_collapse_sets_action_checked_and_partial_icon(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    win._collapse_dock(win.file_dock)

    assert win._dock_actions["file_dock"].isChecked() is True
    assert win.dock_action_icon_name("file_dock") == "dock_panel_right_partial"


def test_action_trigger_from_rail_expands(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win._collapse_dock(win.file_dock)
    action = win._dock_actions["file_dock"]
    assert action.isChecked() is True  # レール状態も checked=True (partial)

    action.trigger()

    assert not win.file_dock.isHidden()
    rail = win._collapse_rails[win.dockWidgetArea(win.file_dock)]
    assert rail.is_empty()
    assert "file_dock" not in win._collapsed_docks
    assert action.isChecked() is True
    assert win.dock_action_icon_name("file_dock") == "dock_panel_right"


def test_action_trigger_from_expanded_hides(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    action = win._dock_actions["channel_dock"]
    assert not win.channel_dock.isHidden()

    action.trigger()

    assert win.channel_dock.isHidden()
    assert action.isChecked() is False


def test_action_trigger_from_hidden_shows_and_raises(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    win.file_dock.hide()
    action = win._dock_actions["file_dock"]
    assert action.isChecked() is False

    raised: list[bool] = []
    win.file_dock.raise_ = lambda: raised.append(True)  # type: ignore[method-assign]

    action.trigger()

    assert not win.file_dock.isHidden()
    assert raised == [True], "非表示→クリックは show() だけでなく raise_() も呼ぶこと"
    assert action.isChecked() is True


# ---------------------------------------------------------------------------
# tabify パリティ (レビュー Critical の検出網)
# ---------------------------------------------------------------------------


def test_tabify_behind_counts_as_expanded_both_actions_checked(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    win.tabifyDockWidget(win.file_dock, win.channel_dock)

    # tabify で背面化した側も isHidden()==False のまま (Qt の実測挙動・spec §2.3)
    # — シグナル引数ではなく isHidden() ポーリングで判定するため、両方とも
    # 「展開」扱いになり checked のまま。
    assert win._dock_actions["file_dock"].isChecked() is True
    assert win._dock_actions["channel_dock"].isChecked() is True
    assert not win.dock_action_icon_name("file_dock").endswith("_partial")
    assert not win.dock_action_icon_name("channel_dock").endswith("_partial")


def test_tabify_behind_action_click_hides(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.tabifyDockWidget(win.file_dock, win.channel_dock)

    action = win._dock_actions["channel_dock"]
    action.trigger()

    assert win.channel_dock.isHidden()
    assert action.isChecked() is False


# ---------------------------------------------------------------------------
# showMinimized/showNormal で不変
# ---------------------------------------------------------------------------


def test_minimize_and_restore_does_not_change_action_state(qtbot: QtBot) -> None:
    """最小化は dock 自体の isHidden() を変えない — シグナル引数ではなく
    isHidden() を再プローブする設計 (spec §2.3) がこの不変性を保証する。"""
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    action = win._dock_actions["file_dock"]
    before_checked = action.isChecked()
    before_icon = win.dock_action_icon_name("file_dock")

    win.showMinimized()
    qtbot.wait(50)
    assert action.isChecked() == before_checked
    assert win.dock_action_icon_name("file_dock") == before_icon

    win.showNormal()
    qtbot.wait(50)
    assert action.isChecked() == before_checked
    assert win.dock_action_icon_name("file_dock") == before_icon


# ---------------------------------------------------------------------------
# pre-show restoreState (非表示保存 → unchecked 収束・フラッピング耐性)
# ---------------------------------------------------------------------------


def test_prior_hidden_state_restores_to_unchecked_before_show(qtbot: QtBot) -> None:
    win1 = build_main_window()
    qtbot.addWidget(win1)
    win1.file_dock.hide()
    win1.save_state()

    # win2.__init__ は _restore_state() を実行する (起動時パスの再現)。show() は
    # 意図的に呼ばない — 「表示・レイアウトされる前」自体を再現するため。
    win2 = build_main_window()
    qtbot.addWidget(win2)

    assert win2.file_dock.isHidden()
    assert win2._dock_actions["file_dock"].isChecked() is False


# ---------------------------------------------------------------------------
# 起動時 collapse 復元 (dockCollapsed 保存 → 構築直後 checked+partial)
# ---------------------------------------------------------------------------


def test_startup_collapse_restore_sets_checked_partial_before_show(
    qtbot: QtBot,
) -> None:
    win1 = build_main_window()
    qtbot.addWidget(win1)
    win1.show()
    qtbot.waitExposed(win1)
    win1._collapse_dock(win1.file_dock)
    win1.save_state()

    win2 = build_main_window()  # pre-show; _apply_saved_collapse 経由で畳み復元
    qtbot.addWidget(win2)

    assert win2._dock_actions["file_dock"].isChecked() is True
    assert win2.dock_action_icon_name("file_dock") == "dock_panel_right_partial"


# ---------------------------------------------------------------------------
# _reset_layout 後に 3 action とも展開/checked へ復帰
# ---------------------------------------------------------------------------


def test_reset_layout_returns_all_actions_to_expanded(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win._collapse_dock(win.file_dock)
    win._collapse_dock(win.diagnostics_dock)

    win._reset_layout()

    for name in ("file_dock", "channel_dock", "diagnostics_dock"):
        assert win._dock_actions[name].isChecked() is True, name
        assert not win.dock_action_icon_name(name).endswith("_partial"), name


# ---------------------------------------------------------------------------
# float 往復 (不変) → 再ドックで edge 追随
# ---------------------------------------------------------------------------


def test_float_round_trip_then_redock_follows_new_edge(qtbot: QtBot) -> None:
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    before_icon = win.dock_action_icon_name("file_dock")  # dock_panel_right (既定)
    assert before_icon == "dock_panel_right"

    win.file_dock.setFloating(True)
    qtbot.wait(20)

    # フロート中も dockWidgetArea() は実領域 (Right) を返す (実測・spec §2.3) —
    # 辺が変わらないので icon/checked も不変。
    assert win._dock_actions["file_dock"].isChecked() is True
    assert win.dock_action_icon_name("file_dock") == before_icon

    win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, win.file_dock)

    assert win.dock_action_icon_name("file_dock") == "dock_panel_left"


def test_add_dock_widget_to_new_area_updates_icon(qtbot: QtBot) -> None:
    """辺移動: addDockWidget(Left) → アイコンが辺に追随する。"""
    win = build_main_window()
    qtbot.addWidget(win)
    assert win.dock_action_icon_name("file_dock") == "dock_panel_right"

    win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, win.file_dock)

    assert win.dock_action_icon_name("file_dock") == "dock_panel_left"


# ---------------------------------------------------------------------------
# 外部 show() → checked 追随 (_on_load_error 相当)
# ---------------------------------------------------------------------------


def test_external_show_raise_updates_checked(qtbot: QtBot) -> None:
    """visibilityChanged 駆動の sync を検証する — 既存の
    test_external_show_on_collapsed_diagnostics_dock_reconciles と同様、window
    が実際に show() されていないと visibilityChanged が信頼できないため show()
    する (offscreen でも top-level が未 show だと子の可視化シグナルが発火し
    ない)。"""
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.diagnostics_dock.hide()
    assert win._dock_actions["diagnostics_dock"].isChecked() is False

    # _on_load_error と同型の直接呼び出し (_on_dock_action_triggered を経由しない)。
    win.diagnostics_dock.show()
    win.diagnostics_dock.raise_()

    assert win._dock_actions["diagnostics_dock"].isChecked() is True


# ---------------------------------------------------------------------------
# 回帰ガード: handler は triggered 接続のみ (toggled 禁止)
# ---------------------------------------------------------------------------


def test_programmatic_setchecked_does_not_toggle_dock_visibility(
    qtbot: QtBot,
) -> None:
    """toggled 接続だとプログラム的 setChecked だけで handler (show()/hide())
    が起動してしまう (spec §2.3 の無限振動リスク)。setChecked 単独では dock の
    可視性が変化しないことで、triggered 接続であることを実証する。"""
    win = build_main_window()
    qtbot.addWidget(win)
    assert not win.file_dock.isHidden()

    win._dock_actions["file_dock"].setChecked(False)  # プログラム的変更

    assert not win.file_dock.isHidden(), (
        "setChecked だけで dock が hide された — toggled 接続の疑い"
        " (triggered のみを使うこと)"
    )
