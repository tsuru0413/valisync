"""#17: 空のレール折りたたみドックは QDockAreaLayout の常在メンバにしない。

起動時 (折りたたみゼロ) に空のレールドック (`collapse_rail_{left,right,bottom}`)
をレイアウトのメンバに残すと、setCorner との不整合な dock-area ツリーを生み
`window.show()` の初回同期 relayout (Qt6Widgets) が 0xC0000005 でネイティブ
クラッシュする実機バグ (#17) の根治を「構造」で施錠する。クラッシュ自体は特定 PC
のタイミング依存で開発機では非再現のため、可視効果 (落ちないこと) ではなく
「空レールがレイアウト非メンバである」ことを直接 assert する
(`dockWidgetArea(rail_dock) == NoDockWidgetArea` が非メンバの機械判定 —
`removeDockWidget`/未追加のドックのみ NoDockWidgetArea を返す。member かつ hide の
実ドックは実領域を返す・main_window の `_DOCK_EDGE_SUFFIX` コメント参照)。

headless (offscreen) でも `dockWidgetArea` はレイアウトのメタデータであり実ペイントを
要さないため判定可能。
"""

from __future__ import annotations

from PySide6.QtCore import Qt


def _build_window(qtbot):  # type: ignore[no-untyped-def]
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    return win


def _is_layout_member(win, rail_dock) -> bool:  # type: ignore[no-untyped-def]
    return win.dockWidgetArea(rail_dock) != Qt.DockWidgetArea.NoDockWidgetArea


def test_all_rail_docks_are_non_members_on_fresh_start(qtbot):  # type: ignore[no-untyped-def]
    """起動直後 (折りたたみゼロ・fresh QSettings): 全 3 レールドックがレイアウト
    非メンバ。#17 の crash 根治 = 空ドックをメンバに残さない、を直接施錠する。

    sabotage: __init__ で全レールを `_place_rail_outermost` してから
    `setVisible(False)` する旧挙動を復活させると全レールがメンバ化し RED。
    """
    win = _build_window(qtbot)
    win.show()
    qtbot.waitExposed(win)
    for edge, rail_dock in win._rail_docks.items():
        assert not _is_layout_member(win, rail_dock), (
            f"edge={edge}: 起動直後にレールドックがレイアウトメンバになっている "
            f"(空ドックのメンバ化が #17 native crash の真因)"
        )


def test_collapse_makes_only_that_rail_a_member(qtbot):  # type: ignore[no-untyped-def]
    """1 ドック折りたたみ: その辺のレールドックがメンバ化して可視、他 2 辺のレール
    は非メンバのまま。"""
    win = _build_window(qtbot)
    win.show()
    qtbot.waitExposed(win)

    # file_dock は既定で Right 領域。折りたたんでも hide されるだけで領域は保持。
    right = win.dockWidgetArea(win.file_dock)
    win._collapse_dock(win.file_dock)

    right_rail = win._rail_docks[right]
    assert _is_layout_member(win, right_rail), (
        "折りたたんだ辺のレールドックがレイアウトメンバになっていない"
    )
    assert not right_rail.isHidden(), "折りたたんだ辺のレールドックが不可視"

    for edge, rail_dock in win._rail_docks.items():
        if edge == right:
            continue
        assert not _is_layout_member(win, rail_dock), (
            f"edge={edge}: 折りたたんでいない辺のレールがメンバ化している "
            f"(空ドックはメンバに残さない)"
        )


def test_expand_returns_rail_to_non_member(qtbot):  # type: ignore[no-untyped-def]
    """展開で空になったレールドックはレイアウトから完全除去され再び非メンバになる。"""
    win = _build_window(qtbot)
    win.show()
    qtbot.waitExposed(win)

    right = win.dockWidgetArea(win.file_dock)
    right_rail = win._rail_docks[right]
    win._collapse_dock(win.file_dock)
    assert _is_layout_member(win, right_rail), "setup: 折りたたみでメンバ化していない"

    win._expand_dock(win.file_dock)
    assert not _is_layout_member(win, right_rail), (
        "展開で空になったレールがレイアウトから除去されていない (メンバのまま残置)"
    )
    assert right_rail.isHidden(), "展開後もレールドックが可視 (ゼロ幅回収できていない)"


def test_show_and_save_restore_cycle_does_not_crash(qtbot):  # type: ignore[no-untyped-def]
    """実 build→show→collapse→save→再 build→show の往復が例外なく完了する。

    #17 の crash 経路 (show 初回同期 relayout) と restore→normalize→再畳みの
    blob 往復を headless で通す smoke。restore 後にレール blob が二重に入らず、
    畳み済みドックが正しく復元されることを確認する。
    """
    from PySide6.QtWidgets import QApplication

    win = _build_window(qtbot)
    win.show()
    qtbot.waitExposed(win)
    QApplication.processEvents()
    win._collapse_dock(win.file_dock)
    win._collapse_dock(win.diagnostics_dock)
    QApplication.processEvents()
    win.save_state()

    win2 = _build_window(qtbot)
    win2.show()
    qtbot.waitExposed(win2)
    QApplication.processEvents()

    assert win2.file_dock.isHidden(), "復元後に file_dock が畳み状態でない"
    assert win2.diagnostics_dock.isHidden(), (
        "復元後に diagnostics_dock が畳み状態でない"
    )
    assert not win2.channel_dock.isHidden(), "復元後に channel_dock まで隠れている"

    # 復元後: 非空レール (right=file / bottom=diag) はメンバ、空 left は非メンバ。
    right = win2.dockWidgetArea(win2.channel_dock)
    bottom = Qt.DockWidgetArea.BottomDockWidgetArea
    left = Qt.DockWidgetArea.LeftDockWidgetArea
    assert _is_layout_member(win2, win2._rail_docks[right]), (
        "復元後に右レール (file 畳み) が非メンバ"
    )
    assert _is_layout_member(win2, win2._rail_docks[bottom]), (
        "復元後に下レール (diagnostics 畳み) が非メンバ"
    )
    assert not _is_layout_member(win2, win2._rail_docks[left]), (
        "復元後に空の左レールがメンバ化している"
    )
