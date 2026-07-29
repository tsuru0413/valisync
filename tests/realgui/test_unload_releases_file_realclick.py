"""Layer C: unload の実クリックでファイルロックが解放される (増分B・①ゲート)。

増分B の主張は「ファイルを閉じる = OS のファイルハンドルが決定的に解放される」。
これは headless では証明できない: ``handle.is_closed`` は *機序* の観測であって
OS ロックの観測ではなく、実経路は「行の実右クリック → メニュー → 確認モーダルの
実クリック」という 3 段の入力を通る。ここでは実 mf4 を実ロードし、実 OS 入力で
その 3 段を通し、**``os.remove`` が成功するか**という OS 由来のオラクルで
解放を判定する。

**恒真化しないための対照 assert** (単発の ``os.remove`` assert は無価値):

* ``FileBrowserVM.unload(index)`` は範囲外 index を**無言 no-op** にする。
* 実経路は確認モーダルを挟むので、ロード未完了/メニュー項目が無い/ダイアログの
  ボタンを取りこぼした、のいずれでもクリックは無音で通る。
* その場合ファイルはロックされていないので ``os.remove`` は成功し PASS する。

よって各段に対照 assert を置く — (1) ロードが実際に完了して行が実在する、
(2) クリック**前**に ``os.remove`` が PermissionError になる (= 今ハンドルが
開いている)、(3) メニューと確認ダイアログが実際に出た、(4) クリック後に
loaded_file_keys からキーが消えた。

**``MDF.__del__`` との弁別**: unload クリックの前にドレイン (TeardownService) を
止め、クリック後に ``pending_signals() > 0`` を assert する。ドレインが止まって
いる間は全 Signal が生存し、各 ``LazyMdfValues`` が ``MdfHandle`` (→ MDF) を
参照しているので ``MDF.__del__`` は走りえない。したがってロック解放の経路は
``Session.remove_group`` の明示 close (Task 1) しか無い —
**その 1 行を消すとファイルサイズに依らず RED になる** (sabotage 実証済み)。

エクスポートガードの脚 (2 本目) は **File ドックを実クリックでフロートさせてから**
行う。``BusyOverlay`` は MainWindow の子で ``cover()`` が ``parent.rect()``・
``show()`` が ``raise_()``・``WA_TransparentForMouseEvents`` 未設定・``submit`` が
エクスポート全期間 show なので、**ドッキング状態の行への実右クリックは全画面
オーバーレイに当たり** ``customContextMenuRequested`` が発火しない。しかも
MainWindow は ``contextMenuEvent`` を override しないので、その右クリックは
QMainWindow の**ドック切替メニュー**を開く。つまりガードのコードが 1 行も無くても
「メニューが出ない/グループが残る」は成立してしまう — フロートしたドックだけが
振る舞いをガードに帰属できる唯一の実入力構成である。

実マウスドラッグは使わない (共有マシンでハング・memory gui_realgui_drag_qtimer_hang)。
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import CAN, write_mdf4
from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
)
from tests.realgui._realgui_input import key as key_input
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui

_LOAD_TIMEOUT_MS = 30_000
# ドレインを「止める」には stop() だけでは足りない: TeardownService.enqueue() は
# `if not self._timer.isActive(): self._timer.start()` で**タイマを再始動する**ので、
# unload の中で必ず動き出す。実際に発火を抑えているのは interval の方なので、
# ここで巨大な interval を入れてから止める (再始動されても発火しない)。
_DRAIN_PAUSE_MS = 3_600_000


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int) -> None:
    for _ in range(n):
        _pump(0.02)


def _real_click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    _pump_n(6)


def _phys_center(w: Any, local: Any = None) -> tuple[int, int]:
    """widget (または widget 内 local 点) の物理スクリーンピクセル座標。"""
    point = w.rect().center() if local is None else local
    g = w.mapToGlobal(point)
    dpr = w.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _shot(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    p = tmp_path / f"{name}.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(p))
    return p


def _make_target(tmp_path: Path) -> Path:
    """実ロード可能な小さい mf4 (複数チャンネル = ドレイン待ち行列が非空になる)。

    ``demo_data/prod_demo.mf4`` は絶対に削除しない (gitignore された 1.36GB の
    デモ資産で他の realgui テストが依存している) ので、ここで生成した使い捨ての
    ファイルだけを ``os.remove`` の対象にする。ロック挙動 (Windows は開いている
    ハンドルがあると削除が PermissionError) はファイルサイズに依らない。
    """
    path = tmp_path / "lock_target.mf4"
    write_mdf4(
        path,
        [
            {
                "name": f"Sig{i}",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0, 2.0],
                "values": [float(i), float(i) + 1.0, float(i) + 2.0],
            }
            for i in range(6)
        ],
    )
    return path


def _shown_mw(qtbot: QtBot) -> Any:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # 実レジストリ由来の最大化復元を解除し、availableGeometry 内の既知ジオメトリへ。
    # オフスクリーン配置だと右クリックが OS のシステムメニューを開く
    # (memory: gui_realgui_offscreen_target_opens_os_system_menu)。
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
    _pump_n(3)
    return mw


def _load_and_settle(qtbot: QtBot, window: Any, path: Path) -> str:
    """実ロード経路 (off-thread LoadController + BusyOverlay) を通し key を返す。"""
    window._load_file(path)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )
    # オーバーレイが引くまで待つ — 引いていないと以後の実クリックが全て
    # オーバーレイに当たり、テストは「クリックしたつもり」で無音に流れる。
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=_LOAD_TIMEOUT_MS)
    _pump_n(6)
    return str(window.app_vm.loaded_file_keys[0])


def _row_point_phys(window: Any, row: int) -> tuple[int, int]:
    """FileBrowser の *row* 行の中心 (物理ピクセル)。行が無ければ AssertionError。"""
    view = window.file_browser_view.list_view
    index = view.model().index(row, 0)
    assert index.isValid(), f"FileBrowser に行 {row} が無い (ロード未完了の疑い)"
    rect = view.visualRect(index)
    assert rect.isValid() and rect.width() > 0 and rect.height() > 0, (
        f"行 {row} の visualRect が空 ({rect}) — 実クリックの掴み点が無い"
    )
    vp = view.viewport()
    from PySide6.QtCore import QPoint

    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    return _phys_center(vp, local)


def _hit_target_is_file_list(window: Any, phys: tuple[int, int]) -> bool:
    """物理点 *phys* に実際に描画されているのが FileBrowser 配下か。

    「メニューが出なかった」の原因が BusyOverlay の遮断ではないことを、
    z-order の実測 (``QApplication.widgetAt``) で切り分けるための対照
    (memory: gui_overlay_sibling_zorder_sinks_behind_later_children)。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    dpr = window.devicePixelRatioF()
    node = QApplication.widgetAt(QPoint(round(phys[0] / dpr), round(phys[1] / dpr)))
    while node is not None:
        if node is window.file_browser_view:
            return True
        node = node.parentWidget()
    return False


def _type_name(widget: Any) -> str | None:
    return None if widget is None else type(widget).__name__


def _drive_close_via_menu(
    px: int,
    py: int,
    *,
    click_item: bool,
    out: dict[str, Any],
    timeout_s: float = 12.0,
) -> None:
    """実右クリック → 行メニュー観測 → (任意で) 「ファイルを閉じる」実クリック →
    確認ダイアログ観測 → 「閉じる」実クリック、を入れ子の exec ループ内で駆動する。

    QMenu.exec / QMessageBox.exec はどちらも入れ子の Qt イベントループなので、段は
    タイマから送り込む。**固定オフセットではなくポーリングの状態機械**にしてある:
    ポップアップ/モーダルが立ち上がるまでの実時間は Windows のメニューアニメーション
    と実行時の負荷で振れ、固定オフセットだと「まだ出ていない時刻に観測して
    『出ていない』と記録する」偽 RED になる (フロートドック側で実際に踏んだ)。

    観測結果は *out* に記録し、呼び出し側が assert する — 段の中で assert すると
    モーダルを開いたままテストが落ち、共有マシンが固まる。
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

    loop = QEventLoop()
    phase = ["menu"]
    settle_at = [0.0]
    started = time.monotonic()

    def right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def real_click_widget(widget: Any, local: Any = None) -> None:
        cx, cy = _phys_center(widget, local)
        at(cx, cy, LDOWN)
        _pump(0.05)
        at(cx, cy, LUP)

    def escape_open_popups() -> None:
        for _ in range(3):
            if (
                QApplication.activePopupWidget() is None
                and QApplication.activeModalWidget() is None
            ):
                return
            key_input(VK_ESCAPE)
            _pump(0.05)

    def enter_settle(next_phase: str) -> None:
        phase[0] = next_phase
        settle_at[0] = time.monotonic()

    def on_menu_phase() -> None:
        popup = QApplication.activePopupWidget()
        if not isinstance(popup, QMenu):
            return  # まだ出ていない — 次のティックで再観測 (deadline が救う)
        out["menu_shown"] = True
        out["popup_type"] = type(popup).__name__
        out["menu_items"] = [a.text() for a in popup.actions()]
        action = next(
            (a for a in popup.actions() if a.text() == S.ACTION_REMOVE_FILE), None
        )
        out["item_found"] = action is not None
        if action is None:
            escape_open_popups()
            enter_settle("done")
            return
        out["item_enabled"] = action.isEnabled()
        out["item_tooltip"] = action.toolTip()
        if not click_item:
            escape_open_popups()  # disabled 項目は押しても閉じない — ESC で畳む
            enter_settle("done")
            return
        real_click_widget(popup, popup.actionGeometry(action).center())
        enter_settle("dialog")

    def on_dialog_phase() -> None:
        box = QApplication.activeModalWidget()
        if not isinstance(box, QMessageBox):
            return  # exec 前 / アニメーション中 — 再観測する
        out["dialog_shown"] = True
        out["modal_type"] = type(box).__name__
        out["dialog_text"] = box.text()
        button = next(
            (b for b in box.buttons() if b.text() == S.CONFIRM_CLOSE_YES), None
        )
        out["confirm_button_found"] = button is not None
        if button is None:
            escape_open_popups()
            enter_settle("done")
            return
        real_click_widget(button)
        out["confirm_clicked"] = True
        enter_settle("done")

    def tick() -> None:
        if time.monotonic() - started > timeout_s:
            out["timeout_phase"] = phase[0]
            out.setdefault("popup_type", _type_name(QApplication.activePopupWidget()))
            out.setdefault("modal_type", _type_name(QApplication.activeModalWidget()))
            escape_open_popups()
            loop.quit()
            return
        if phase[0] == "menu":
            on_menu_phase()
        elif phase[0] == "dialog":
            on_dialog_phase()
        elif time.monotonic() - settle_at[0] > 0.5:
            # 閉じ切る猶予 (メニューのフェードアウト・unload の同期処理)。
            out.setdefault("popup_type", _type_name(QApplication.activePopupWidget()))
            out.setdefault("modal_type", _type_name(QApplication.activeModalWidget()))
            escape_open_popups()
            loop.quit()

    timer = QTimer()
    timer.setInterval(80)
    timer.timeout.connect(tick)
    timer.start()
    QTimer.singleShot(300, right_click)
    loop.exec()
    timer.stop()
    out["elapsed_s"] = round(time.monotonic() - started, 2)
    _pump_n(6)


def _pause_drain(window: Any) -> None:
    """ドレインを止める (``MDF.__del__`` とロック解放を弁別するための前提)。"""
    timer = window.teardown_service._timer
    timer.setInterval(_DRAIN_PAUSE_MS)  # enqueue が start() し直しても発火しない
    timer.stop()


def _resume_drain_and_wait(qtbot: QtBot, window: Any) -> None:
    timer = window.teardown_service._timer
    timer.setInterval(0)
    timer.start()
    qtbot.waitUntil(
        lambda: (
            window.teardown_service.pending_signals() == 0
            and not window.app_vm.releasing_files
        ),
        timeout=10_000,
    )


def test_unload_by_real_click_releases_the_os_file_lock(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """実右クリック → 「ファイルを閉じる」→ 確認「閉じる」で OS ロックが解放される。"""
    skip_unless_real_display()

    path = _make_target(tmp_path)
    window = _shown_mw(qtbot)
    key = _load_and_settle(qtbot, window, path)

    # ── 対照 1: ロードが実際に完了し、行が実在する ────────────────────────
    group_signals = window.app_vm.session.group_signals(key)
    assert len(group_signals) == 6, (
        f"ロードが完了していない (信号数 {len(group_signals)}) — "
        "以後のクリックは no-op でも通ってしまう"
    )
    assert window.file_browser_vm.files == [path.name], (
        f"FileBrowser に行が無い: {window.file_browser_vm.files}"
    )
    px, py = _row_point_phys(window, 0)
    assert _hit_target_is_file_list(window, (px, py)), (
        "行の掴み点に描画されているのが FileBrowser でない "
        "(BusyOverlay 等が最前面 = 右クリックが行へ届かない)"
    )

    # ── 対照 2: 今まさにハンドルが開いている (OS ロックの実測) ─────────────
    handle = window.app_vm.session._groups.group(key).handle
    assert handle is not None and handle.is_closed is False
    with pytest.raises(PermissionError):
        os.remove(path)

    # ── MDF.__del__ との弁別: ドレインを止めてから閉じる ───────────────────
    _pause_drain(window)

    out: dict[str, Any] = {}
    _drive_close_via_menu(px, py, click_item=True, out=out)
    shot = _shot(tmp_path, "01_after_close_click")
    print(f"[unload-realgui] close-by-real-click: {out}")

    # ── 対照 3: メニューと確認ダイアログが実際に出た ───────────────────────
    assert out.get("menu_shown") is True, (
        f"実右クリックで行メニューが出ていない (popup={out.get('popup_type')}) — "
        f"以後の assert は空虚に通る。{shot}"
    )
    assert out.get("item_found") is True, (
        f"メニューに「ファイルを閉じる」が無い: {out.get('menu_items')}。{shot}"
    )
    assert out.get("item_enabled") is True, (
        f"エクスポートしていないのに項目が disabled。{shot}"
    )
    assert out.get("dialog_shown") is True, (
        f"確認ダイアログが出ていない (modal={out.get('modal_type')}) — "
        f"クリックを取りこぼした可能性。{shot}"
    )
    assert out.get("confirm_clicked") is True, (
        f"確認ダイアログの「閉じる」を押せていない: {out}。{shot}"
    )

    # ── 対照 4: クリックが実際に効いた (no-op でない) ──────────────────────
    qtbot.waitUntil(lambda: key not in window.app_vm.loaded_file_keys, timeout=5000)
    # 行はまだ残るが「解放中」(スピナー) 行になっている — ドレインを止めている
    # からで、これ自体が teardown へ実際に手渡された証拠 (FU-16 の仕様)。
    assert window.file_browser_vm.is_releasing(0) is True, (
        f"行が解放中になっていない: {window.file_browser_vm.files}。{shot}"
    )

    # ドレインは止まったまま = 全 Signal が生存 → LazyMdfValues が MdfHandle を
    # 参照している → MDF.__del__ は走りえない。ここでロックが解けているなら、
    # 解いたのは Session.remove_group の明示 close だけである。
    assert window.teardown_service.pending_signals() > 0, (
        "ドレインが進んでしまい MDF.__del__ と弁別できない "
        "(pending_signals == 0 では close の帰属が証明できない)"
    )
    assert handle.is_closed is True, f"handle が閉じられていない。{shot}"
    try:
        os.remove(path)
    except PermissionError as exc:  # pragma: no cover - 失敗時のみ
        pytest.fail(
            f"unload 後もファイルが OS ロックされたまま (ハンドル未解放): {exc}。{shot}"
        )
    assert not path.exists()

    _resume_drain_and_wait(qtbot, window)
    assert window.file_browser_vm.files == [], (
        f"ドレイン完了後も行が残っている: {window.file_browser_vm.files}"
    )


def test_export_blocks_unload_on_a_floated_dock_then_allows_it_after(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """エクスポート中は実クリックでも閉じられず、完了後は同じ実クリックで閉じられる。"""
    skip_unless_real_display()

    from PySide6.QtWidgets import QApplication

    path = _make_target(tmp_path)
    window = _shown_mw(qtbot)
    key = _load_and_settle(qtbot, window, path)
    handle = window.app_vm.session._groups.group(key).handle
    assert handle is not None and handle.is_closed is False

    # ── File ドックを実クリックでフロート化 ────────────────────────────────
    # BusyOverlay は MainWindow の子 (cover() が parent.rect()) なので、
    # フロートしたトップレベル窓は覆えない = 右クリックが行に届く唯一の構成。
    bar = window._collapsible_bars["file_dock"]
    float_button = bar._float_button
    qtbot.waitUntil(
        lambda: float_button.isVisible() and float_button.width() > 0, timeout=3000
    )
    assert not window.file_dock.isFloating(), "setup: file_dock が既にフロート"
    _real_click(*_phys_center(float_button))
    qtbot.waitUntil(lambda: window.file_dock.isFloating(), timeout=3000)

    # 画面内の既知位置へ (オフスクリーンの右クリックは OS システムメニューを開く)。
    ag = QApplication.primaryScreen().availableGeometry()
    window.file_dock.setGeometry(
        ag.x() + max(0, ag.width() - 440), ag.y() + 80, 400, 260
    )
    window.file_dock.raise_()
    window.file_dock.activateWindow()
    _pump_n(8)

    # ── ブロックするエクスポートを submit して in-flight を維持 ────────────
    # 実 quick_demo のエクスポートはミリ秒で終わるので、ブロックしないと
    # is_busy() が既に False になり「拒否」assert が空虚に通る。
    release = threading.Event()
    window._export_controller.submit(
        lambda: release.wait(60.0), busy=window.busy_overlay, label="guard.csv"
    )
    try:
        assert window._export_controller.is_busy() is True, "setup: busy になっていない"
        assert window.busy_overlay.isHidden() is False, (
            "setup: BusyOverlay が出ていない (エクスポート中の実状況を再現できていない)"
        )
        _pump_n(6)

        px, py = _row_point_phys(window, 0)
        assert _hit_target_is_file_list(window, (px, py)), (
            "フロート窓の行が最前面ヒットターゲットでない "
            "(BusyOverlay 遮断と区別できないため測定不能)"
        )

        out: dict[str, Any] = {}
        _drive_close_via_menu(px, py, click_item=False, out=out)
        shot_busy = _shot(tmp_path, "02_menu_while_exporting")
        print(f"[unload-realgui] menu while exporting (floated dock): {out}")

        # メニューは**出る** (「出ない」ならガード以外の理由 — 帰属できない)。
        assert out.get("menu_shown") is True, (
            f"エクスポート中に行メニューが出ない (popup={out.get('popup_type')}) — "
            f"ガードの効果と遮断を区別できない。{shot_busy}"
        )
        assert out.get("item_found") is True, (
            f"メニューに「ファイルを閉じる」が無い: {out.get('menu_items')}。{shot_busy}"
        )
        assert out.get("item_enabled") is False, (
            f"エクスポート中なのに「ファイルを閉じる」が有効のまま。{shot_busy}"
        )
        assert out.get("item_tooltip") == "エクスポート中はファイルを閉じられません", (
            f"disabled の理由が出ていない: {out.get('item_tooltip')!r}。{shot_busy}"
        )

        # ── backstop: プログラム経路 (View を迂回) でも拒否される ───────────
        modals: list[str] = []
        window._notify_blocked = modals.append  # DI (実モーダルはテストを止める)
        window.file_browser_vm.unload(0)
        assert modals == ["エクスポート中はファイルを閉じられません"], (
            f"拒否が無音 (モーダル {modals})"
        )
        assert window.status_message() == "エクスポート中はファイルを閉じられません"
        assert handle.is_closed is False, "拒否されたのに handle が閉じられた"
        assert key in window.app_vm.loaded_file_keys
    finally:
        release.set()
    qtbot.waitUntil(
        lambda: window._export_controller.is_busy() is False, timeout=10_000
    )
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=5000)
    _pump_n(6)

    # ── 完了後は **同じ実クリック** で閉じられる (「常に拒否」の退化を落とす) ──
    _pause_drain(window)
    px, py = _row_point_phys(window, 0)
    out2: dict[str, Any] = {}
    _drive_close_via_menu(px, py, click_item=True, out=out2)
    shot_after = _shot(tmp_path, "03_after_export_close")
    print(f"[unload-realgui] close after export finished: {out2}")

    assert out2.get("menu_shown") is True, f"メニューが出ない。{shot_after}"
    assert out2.get("item_enabled") is True, (
        f"エクスポート完了後も項目が disabled のまま (常に拒否する退化実装)。{shot_after}"
    )
    assert out2.get("dialog_shown") is True, (
        f"確認ダイアログが出ていない (modal={out2.get('modal_type')})。{shot_after}"
    )
    assert out2.get("confirm_clicked") is True, (
        f"「閉じる」を押せていない。{shot_after}"
    )

    qtbot.waitUntil(lambda: key not in window.app_vm.loaded_file_keys, timeout=5000)
    assert window.teardown_service.pending_signals() > 0, (
        "ドレインが進んでしまい MDF.__del__ と弁別できない"
    )
    assert handle.is_closed is True, f"閉じたのに handle が開いたまま。{shot_after}"
    try:
        os.remove(path)
    except PermissionError as exc:  # pragma: no cover - 失敗時のみ
        pytest.fail(
            f"エクスポート完了後の unload でロックが解けない: {exc}。{shot_after}"
        )
    assert not path.exists()

    _resume_drain_and_wait(qtbot, window)
    assert window.file_browser_vm.files == [], (
        f"ドレイン完了後も行が残っている: {window.file_browser_vm.files}"
    )
