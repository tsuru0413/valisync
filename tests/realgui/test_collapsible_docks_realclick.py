"""Layer C: 折りたたみレールを画面端(開ドックの外側)へ = レール最外ドック化 (#17)。

`--realgui` opt-in・実ディスプレイ+Windows 必須。この受け入れは Layer A/B で
再チェック不能: chevron クリック→`dock.hide()`+対応辺の「レールドック」表示、
レール最外配置 (`addDockWidget(area, rail, orientation)` の append=最外) は
QMainWindow の実ドックエリアレイアウトが実レイアウト/実ペイントを経ないと動かない
ため headless では確証できない
(memory: gui_dock_toggle_width_change_needs_real_display_and_layout /
gui_isvisible_true_for_offscreen_hidden_dock — 内容の非可視は isVisible() でなく
明示 hide()/isHidden() で見る / gui_overlay_sibling_zorder_sinks_behind_later_children
— 「外側」は単一 x 比較でなく widgetAt 実描画で確証する)。

トグル/レールタブの物理座標はウィジェットの geometry から都度算出し、実 Win32
マウス入力 (`tests/realgui/_realgui_input`) でクリックする。

candidate A: 旧「レール widget を中央 (CentralWithRails) の縁に置く」機構では片方
折りたたみでレールがプロットと開ドックの間に挟まった (honest-RED: rail.left() が
openDock.right() より小さい)。本機構ではレールを各辺の最外 QDockWidget に据え、
順序を「プロット / 開ドック / レール(画面端)」にする。
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


def _grect(widget) -> tuple[int, int, int, int]:  # type: ignore[no-untyped-def]
    """widget のグローバル (left, top, right, bottom) 論理ピクセル。"""
    tl = widget.mapToGlobal(widget.rect().topLeft())
    br = widget.mapToGlobal(widget.rect().bottomRight())
    return tl.x(), tl.y(), br.x(), br.y()


def _widget_at_center_in(widget) -> bool:  # type: ignore[no-untyped-def]
    """widget 中心のスクリーン点に実際に描画されているのが widget 自身または
    その子孫か (z-order 沈下 false-green を排除・logical 座標)。"""
    from PySide6.QtWidgets import QApplication

    center = widget.mapToGlobal(widget.rect().center())
    node = QApplication.widgetAt(center)
    while node is not None:
        if node is widget:
            return True
        node = node.parentWidget()
    return False


def _real_click(x: int, y: int) -> None:
    from PySide6.QtWidgets import QApplication

    at(x, y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(x, y, LUP)
    for _ in range(6):
        QApplication.processEvents()
        time.sleep(0.02)


def _settle(extra_pumps: int = 14) -> None:
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


def _rail_for(mw, dock):  # type: ignore[no-untyped-def]
    return mw._collapse_rails[mw.dockWidgetArea(dock)]


def _collapse_via_chevron(qtbot: QtBot, mw, dock, dock_name: str):  # type: ignore[no-untyped-def]
    """dock の chevron を実クリックで押し、hide+レールタブ化を待つ。"""
    bar = mw._collapsible_bars[dock_name]
    qtbot.waitUntil(
        lambda: bar._toggle_button.isVisible() and bar._toggle_button.width() > 0,
        timeout=3000,
    )
    rail = _rail_for(mw, dock)
    _real_click(*_phys(bar._toggle_button))
    qtbot.waitUntil(lambda: dock.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: dock in rail._tabs, timeout=3000)
    _settle()
    return rail


# ---------------------------------------------------------------------------
# T-C1: 片方折りたたみ — レールが開ドックの外側(画面端)へ非重なりで来る
# ---------------------------------------------------------------------------


def test_collapse_file_rail_outside_open_channel(qtbot: QtBot, tmp_path: Path) -> None:
    """file_dock を chevron 実クリックで畳むと、右レールドックが開いている
    channel_dock の**外側**(画面端)へ来る: グローバル `rail.left() >= channel.right()`
    (非重なり) かつ widgetAt(レール中心) が実際にレールを指す (z-order 沈下排除)。

    honest-RED: 旧機構ではレールが中央側 (rail.left() < channel.right()) で RED。
    """
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    file_dock = mw.file_dock
    channel_dock = mw.channel_dock
    assert mw.dockWidgetArea(channel_dock) == mw.dockWidgetArea(file_dock), (
        "setup: file_dock/channel_dock が同じ辺を共有していない"
    )
    _settle()

    rail = _collapse_via_chevron(qtbot, mw, file_dock, "file_dock")

    assert not channel_dock.isHidden(), "setup: channel_dock も畳まれてしまった"
    rl, _rt, rr, _rb = _grect(rail)
    cl, _ct, cr, _cb = _grect(channel_dock)
    shot = _grab(tmp_path, "collapse_file_rail_outside.png")
    print(f"[c1-file] rail L={rl} R={rr} | channel L={cl} R={cr} | shot={shot}")

    assert rl >= cr, (
        f"レールが開いている channel の外側に無い (rail.left={rl} < channel.right={cr})。"
        f"screenshot: {shot}"
    )
    assert _widget_at_center_in(rail), (
        f"widgetAt(レール中心) がレールを指さない (z-order 沈下 or 非描画)。"
        f"screenshot: {shot}"
    )


def test_collapse_channel_rail_outside_open_file(qtbot: QtBot, tmp_path: Path) -> None:
    """T-C1 対称: channel_dock を畳むと右レールが開いている file_dock の外側へ。"""
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    file_dock = mw.file_dock
    channel_dock = mw.channel_dock
    _settle()

    rail = _collapse_via_chevron(qtbot, mw, channel_dock, "channel_dock")

    assert not file_dock.isHidden(), "setup: file_dock も畳まれてしまった"
    rl, _rt, rr, _rb = _grect(rail)
    fl, _ft, fr, _fb = _grect(file_dock)
    shot = _grab(tmp_path, "collapse_channel_rail_outside.png")
    print(f"[c1-channel] rail L={rl} R={rr} | file L={fl} R={fr} | shot={shot}")

    assert rl >= fr, (
        f"レールが開いている file の外側に無い (rail.left={rl} < file.right={fr})。"
        f"screenshot: {shot}"
    )
    assert _widget_at_center_in(rail), (
        f"widgetAt(レール中心) がレールを指さない。screenshot: {shot}"
    )


# ---------------------------------------------------------------------------
# T-C1b: 候補 A の不変条件 — 順序破れの能動是正 / save→restore で最外復元
# ---------------------------------------------------------------------------


def test_order_break_reasserts_rail_outermost(qtbot: QtBot, tmp_path: Path) -> None:
    """開ドックがレールの外側へ回る「順序破れ」が起きても、`dockLocationChanged`→
    能動是正で右レールが最外へ戻る (guardrail 3)。

    実 OS のドックタイトルバー D&D はドロップ先が不定でフロート化しやすく
    (実測: channel が window 外へ float・座標再現不能) テストが本質的に不安定な
    ため、順序破れを `splitDockWidget(rail_dock, channel, Horizontal)` で決定的に
    起こす — これは channel をレールの**外側**へ回すと同時に**実ウィンドウ上で
    本物の `dockLocationChanged` を発火**する (実測: 同一辺の再配置でも
    `splitDockWidget` は発火するが `addDockWidget` は発火しない — 実ユーザーの
    ドラッグは Qt のドラッグ機構経由で必ず発火する)。是正は **実 QMainWindow
    レイアウト**で `_reassert_rail_now`(singleShot) を通す (合成 QMouseEvent 経路
    ではなく実 Qt シグナル + 実レイアウト)。実 OS 入力そのものは T-C1 の実
    chevron クリックで別途担保する。
    """
    skip_unless_real_display()
    from PySide6.QtCore import Qt

    mw = _shown_mw(qtbot)
    file_dock = mw.file_dock
    channel_dock = mw.channel_dock
    _settle()
    rail = _collapse_via_chevron(qtbot, mw, file_dock, "file_dock")
    right = mw.dockWidgetArea(channel_dock)
    rail_dock = mw._rail_docks[right]

    rl0 = _grect(rail)[0]
    cr0 = _grect(channel_dock)[2]
    assert rl0 >= cr0, "setup: 畳み直後にレールが最外でない"

    # 順序破れ: channel をレールの外側へ split する (rail が内側へ回る)。
    # dockLocationChanged が発火し singleShot 是正が走る。
    mw.splitDockWidget(rail_dock, channel_dock, Qt.Orientation.Horizontal)
    _settle(30)  # dockLocationChanged の singleShot 是正を汲む

    shot = _grab(tmp_path, "order_break_reassert.png")
    assert not channel_dock.isHidden() and not channel_dock.isFloating(), (
        f"setup: 順序破れ後に channel が非ドック化した。screenshot: {shot}"
    )
    rl, _rt, rr, _rb = _grect(rail)
    cl, _ct, cr, _cb = _grect(channel_dock)
    print(f"[c1b-reassert] rail L={rl} R={rr} | channel L={cl} R={cr} | shot={shot}")
    assert rl >= cr, (
        f"順序破れ後にレールが最外へ能動是正されていない "
        f"(rail.left={rl} < channel.right={cr})。screenshot: {shot}"
    )
    assert _widget_at_center_in(rail), f"レール非描画 (z-order)。screenshot: {shot}"


def test_broken_order_save_restore_restores_rail_outermost(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """順序を崩した状態を save→別ウィンドウで restore しても、レールが最外へ復元
    される (guardrail 4: restoreState 後の正規化)。

    file を畳んだ状態を保存 → 新ウィンドウで復元 → 復元後もレールが開いている
    channel の外側に来る (旧 blob 互換・objectName 安定を含む往復)。
    """
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    _settle()
    _collapse_via_chevron(qtbot, mw, mw.file_dock, "file_dock")
    mw.save_state()

    mw2 = _shown_mw(qtbot)
    _settle(20)
    assert mw2.file_dock.isHidden(), "復元後に file_dock が畳み状態でない"
    assert not mw2.channel_dock.isHidden(), "復元後に channel_dock まで隠れている"
    rail2 = _rail_for(mw2, mw2.file_dock)
    qtbot.waitUntil(lambda: not rail2.is_empty(), timeout=3000)
    _settle()

    rl, _, rr, _ = _grect(rail2)
    cl, _, cr, _ = _grect(mw2.channel_dock)
    shot = _grab(tmp_path, "restore_rail_outermost.png")
    print(f"[c1b-restore] rail L={rl} R={rr} | channel L={cl} R={cr} | shot={shot}")
    assert rl >= cr, (
        f"restore 後にレールが最外へ復元されていない "
        f"(rail.left={rl} < channel.right={cr})。screenshot: {shot}"
    )
    assert _widget_at_center_in(rail2), f"復元レール非描画。screenshot: {shot}"


def test_left_edge_rebuild_places_rail_outermost(qtbot: QtBot, tmp_path: Path) -> None:
    """左辺へ D&D 相当で移した file/channel を片方畳むと、左レールが最外
    (画面端=左端) へ来る (`_rebuild_left_edge_outermost`・Task 3 レビュー Minor 3)。

    既定レイアウトに左ドックは無い希少経路 (ユーザーが左へ D&D したときのみ)
    のため T-C1/T-C1b/T-C2 では未被覆だった。Right/Bottom は
    ``addDockWidget(area, rail, orientation)`` の append で足りるのに対し、
    Left は append が内側 (右) 着地のため `_rebuild_left_edge_outermost`
    (rail 単独→splitDockWidget→残り縦積み) を使う — この専用経路をここで
    1 点実機被覆する (headless は offscreen でドック位置の geometry が実
    レイアウトを経ないと更新されない既知の罠のため Layer C 必須)。
    """
    skip_unless_real_display()
    from PySide6.QtCore import Qt

    mw = _shown_mw(qtbot)
    file_dock = mw.file_dock
    channel_dock = mw.channel_dock
    left = Qt.DockWidgetArea.LeftDockWidgetArea

    # D&D で両方を左辺へ移した状態を模擬 (実 OS タイトルバー D&D は不安定な
    # ため、既存 T-C1b と同じ理由で実 QMainWindow API で決定的に配置する —
    # 実クリックそのものは chevron 側で担保する)。removeDockWidget を先に
    # 呼ぶと Qt がドックを hide してしまい (Qt の既知挙動)、実 D&D では
    # 起きない見せかけの非表示状態になる (デバッグで実証済み) ため、
    # addDockWidget/splitDockWidget だけで直接移す (Qt が内部で旧位置から
    # 移動させる — 明示 remove 不要)。
    mw.addDockWidget(left, file_dock)
    mw.splitDockWidget(file_dock, channel_dock, Qt.Orientation.Vertical)
    _settle(20)  # dockLocationChanged の singleShot 再アサートを汲む

    assert mw.dockWidgetArea(file_dock) == left
    assert mw.dockWidgetArea(channel_dock) == left

    rail = _collapse_via_chevron(qtbot, mw, file_dock, "file_dock")

    assert not channel_dock.isHidden(), "setup: channel_dock も畳まれてしまった"
    rl, _rt, rr, _rb = _grect(rail)
    cl, _ct, cr, _cb = _grect(channel_dock)
    shot = _grab(tmp_path, "collapse_left_rail_outside.png")
    print(f"[left-rebuild] rail L={rl} R={rr} | channel L={cl} R={cr} | shot={shot}")

    assert rr <= cl, (
        f"左レールが開いている channel の外側 (画面端=左) に無い "
        f"(rail.right={rr} > channel.left={cl})。screenshot: {shot}"
    )
    assert _widget_at_center_in(rail), (
        f"widgetAt(レール中心) がレールを指さない (z-order 沈下 or 非描画)。"
        f"screenshot: {shot}"
    )


# ---------------------------------------------------------------------------
# T-C2: 両方折りたたみ(09 相当) / 全展開ゼロ幅 / extent 復元の無回帰
# ---------------------------------------------------------------------------


def test_both_collapse_rail_at_edge_and_expand_restores_extent(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """右カラムの file/channel を両方畳むと右レールが**画面端**に来て中央プロットが
    広がり (09 相当)、各タブ実クリックで両方展開するとレールがゼロ幅で隠れ、各
    ドックの幅が畳む直前に控えた `_expanded_extent` と両側数 px で一致する。

    (旧テスト `..._reclaims_width_and_expands` の central.width reclaim assert と
    `_central_with_rails` 直参照を candidate A へ移行: central は centralWidget()、
    レール位置はグローバル矩形 x で確認・展開幅は extent 両側許容で厳格化。)
    """
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    file_dock = mw.file_dock
    channel_dock = mw.channel_dock
    central = mw.centralWidget()
    rail = _rail_for(mw, file_dock)
    rail_dock = mw._rail_docks[mw.dockWidgetArea(file_dock)]
    assert rail.is_empty(), "setup: レールに既にタブがある"

    _settle()
    initial_cwidth = central.width()
    win_right = _grect(mw)[2]
    _grab(tmp_path, "both_collapse_before.png")

    # 片方 (file) — 縦積みのため中央幅はまだ増えない (兄弟がカラム幅を保持)。
    _collapse_via_chevron(qtbot, mw, file_dock, "file_dock")
    after_file_cwidth = central.width()
    # spec §3/§6-#3: 片方畳みでは中央プロット幅がほぼ不変であるはず (レールは
    # 兄弟カラムから幅を奪う想定)。ここを未 assert のまま捕捉・print だけに
    # 留めると、`_pin_rail_thin` が壊れてレールが中央プロットから大きく幅を
    # 奪う回帰が green で通過してしまう (レビュー Important 1)。
    #
    # 実測 (実ディスプレイ・決定的): `_pin_rail_thin` の `resizeDocks` は
    # レール可視化直後の暫定サイズ (Qt がまず兄弟カラムから詰めた幅) を
    # sizeHint へ確定させる際、その差分 (数 px) を中央側からも僅かに借りる
    # (QMainWindow が central に高い stretch factor を与えるため — 兄弟
    # カラムのみから奪う、という spec の想定より僅かに漏れる)。実測で
    # ~24px・決定的 (同一ウィンドウ幅で再現) であり「ほぼ不変」の範囲。
    # slop はこの実測 + 余裕を許容しつつ、`_pin_rail_thin` の等分バグ級の
    # 大幅な取り分崩れ (100px 超) は確実に検出できる値に設定する。
    plot_width_slop = 40
    assert abs(after_file_cwidth - initial_cwidth) <= plot_width_slop, (
        f"片方畳みで中央プロット幅が有意に動いてしまった "
        f"(initial={initial_cwidth}, after_file={after_file_cwidth}, "
        f"slop={plot_width_slop})。レールが中央から幅を奪っている疑い。"
    )

    # 両方 (channel) — ここで右辺が空になり中央が広がる。
    _collapse_via_chevron(qtbot, mw, channel_dock, "channel_dock")
    collapsed_cwidth = central.width()
    # 畳んだ直後に控えた復元 extent。
    file_extent = mw._expanded_extent["file_dock"]
    channel_extent = mw._expanded_extent["channel_dock"]
    shot_collapsed = _grab(tmp_path, "both_collapse_after.png")
    print(
        f"[c2] cwidth initial={initial_cwidth} after_file={after_file_cwidth} "
        f"collapsed={collapsed_cwidth} | extents file={file_extent} ch={channel_extent}"
    )

    assert len(rail._tabs) == 2, (
        f"両方畳み後に右レールへ2タブ出ていない (tabs={len(rail._tabs)})。"
        f"screenshot: {shot_collapsed}"
    )
    assert collapsed_cwidth > initial_cwidth + 20, (
        f"両方畳みで中央プロット幅が有意に増えていない "
        f"(initial={initial_cwidth}, collapsed={collapsed_cwidth})。"
        f"screenshot: {shot_collapsed}"
    )
    # レールが画面端 (右端) に来ている: rail.right がウィンドウ右端の近傍。
    rl_c, _rt_c, rr, _rb_c = _grect(rail)
    rail_visible_w = rr - rl_c  # 展開幅の許容の基礎 (下記)
    assert rr >= win_right - 60, (
        f"レールが画面端に来ていない (rail.right={rr}, window.right={win_right})。"
        f"screenshot: {shot_collapsed}"
    )
    assert _widget_at_center_in(rail), (
        f"両方畳みレールが非描画。screenshot: {shot_collapsed}"
    )

    # --- 各タブ実クリックで両方展開 ---
    file_tab = rail._tabs[file_dock]
    qtbot.waitUntil(
        lambda: file_tab.isVisible() and file_tab.width() > 0 and file_tab.height() > 0,
        timeout=3000,
    )
    _real_click(*_phys(file_tab))
    qtbot.waitUntil(lambda: not file_dock.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: file_dock not in rail._tabs, timeout=3000)
    _settle()

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

    shot_expanded = _grab(tmp_path, "both_collapse_expanded.png")
    print(
        f"[c2] expanded file_w={file_dock.width()} ch_w={channel_dock.width()} "
        f"rail_dock_hidden={rail_dock.isHidden()} | shot={shot_expanded}"
    )

    assert not file_dock.isHidden() and not channel_dock.isHidden(), (
        f"タブ実クリックで両ドックが再表示されない。screenshot: {shot_expanded}"
    )
    # 全展開でレールドックはゼロ幅で隠れる (空時 setVisible(False))。
    assert rail.is_empty() and rail_dock.isHidden(), (
        f"全展開後もレールドックが可視 (ゼロ幅回収できていない)。"
        f"screenshot: {shot_expanded}"
    )
    # 展開後の各ドック幅が控えた extent と一致 (両側許容)。candidate A ではレール
    # 自体がドックで、可視時にカラムからレール幅ぶん (~27px) を奪うため、片方畳み
    # 時に控える extent はレール出現の前後で最大レール幅ぶん揺れる (file は畳む前=
    # レール前、channel は file 畳み後=レール後に控えるため)。よって許容はレールの
    # 実測可視幅 + 丸め (14px) に紐付ける。中央プロット幅は不変 (spec §3「片方畳みで
    # プロット幅は変わらず」を満たす — 幅の移動はレール x 位置のみ)。
    slop = rail_visible_w + 14
    assert abs(file_dock.width() - file_extent) <= slop, (
        f"file 展開幅が extent と一致しない (width={file_dock.width()}, "
        f"extent={file_extent}, slop={slop})。screenshot: {shot_expanded}"
    )
    assert abs(channel_dock.width() - channel_extent) <= slop, (
        f"channel 展開幅が extent と一致しない (width={channel_dock.width()}, "
        f"extent={channel_extent}, slop={slop})。screenshot: {shot_expanded}"
    )
    # 中央プロット幅もほぼ元へ戻る (両側許容)。
    assert abs(central.width() - initial_cwidth) <= 40, (
        f"展開で中央幅がほぼ元へ戻っていない "
        f"(initial={initial_cwidth}, expanded={central.width()})。"
        f"screenshot: {shot_expanded}"
    )


def test_collapse_bottom_dock_at_screen_bottom(qtbot: QtBot, tmp_path: Path) -> None:
    """下ドック (diagnostics_dock) を chevron 実クリックで畳むと下レールドックが
    **画面下端**の帯に出て中央高さが増え、チップ実クリックで高さが元へ戻る。
    """
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    dock = mw.diagnostics_dock
    central = mw.centralWidget()
    rail = _rail_for(mw, dock)
    rail_dock = mw._rail_docks[mw.dockWidgetArea(dock)]
    assert rail.is_empty(), "setup: レールに既にタブがある"

    _settle()
    initial_height = central.height()
    win_bottom = _grect(mw)[3]
    _grab(tmp_path, "collapse_bottom_before.png")

    _collapse_via_chevron(qtbot, mw, dock, "diagnostics_dock")
    collapsed_height = central.height()
    shot_collapsed = _grab(tmp_path, "collapse_bottom_after.png")
    print(f"[c2-bottom] cheight initial={initial_height} collapsed={collapsed_height}")

    assert not rail.is_empty(), f"畳み後にレールへタブが出ていない。{shot_collapsed}"
    assert collapsed_height > initial_height + 20, (
        f"畳みで中央高さが有意に増えていない "
        f"(initial={initial_height}, collapsed={collapsed_height})。{shot_collapsed}"
    )
    # レールが画面下端に来ている。
    _, _, _, rb = _grect(rail)
    assert rb >= win_bottom - 60, (
        f"下レールが画面下端に来ていない (rail.bottom={rb}, window.bottom={win_bottom})。"
        f"{shot_collapsed}"
    )
    assert _widget_at_center_in(rail), f"下レール非描画 (z-order)。{shot_collapsed}"

    # --- 横チップで展開 ---
    tab = rail._tabs[dock]
    qtbot.waitUntil(
        lambda: tab.isVisible() and tab.width() > 0 and tab.height() > 0, timeout=3000
    )
    _real_click(*_phys(tab))
    qtbot.waitUntil(lambda: not dock.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: rail.is_empty(), timeout=3000)
    _settle()

    shot_expanded = _grab(tmp_path, "collapse_bottom_expanded.png")
    assert not dock.isHidden(), f"展開でドックが戻らない。{shot_expanded}"
    assert rail.is_empty() and rail_dock.isHidden(), (
        f"全展開後も下レールドックが可視。{shot_expanded}"
    )
    assert central.height() < collapsed_height - 20, (
        f"展開で中央高さが元へ戻っていない (collapsed={collapsed_height}, "
        f"expanded={central.height()})。{shot_expanded}"
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

    shot = _grab(tmp_path, "collapse_float.png")
    print(
        f"[float] isFloating={dock.isFloating()} "
        f"chevron_enabled={bar._toggle_button.isEnabled()} | shot={shot}"
    )
    assert dock.isFloating(), (
        f"フロートボタンの実クリックで file_dock がフロート化しない。{shot}"
    )
    assert not bar._toggle_button.isEnabled(), (
        f"フロート中も chevron が有効なまま。{shot}"
    )
