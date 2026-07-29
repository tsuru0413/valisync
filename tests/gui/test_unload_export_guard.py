"""エクスポート中の unload を **VM のチョークポイント**で拒否する (増分B・C1)。

実ユーザー経路は FileBrowserView._show_context_menu → build_context_menu →
_confirm_and_unload → FileBrowserVM.unload → **AppViewModel.unload_file** →
Session.remove_group。FileBrowserView も FileBrowserVM も ExportController に
到達できない (MainWindow が両者を別々に所有している) ため、ガードは
AppViewModel の 1 チョークポイントに置き、述語は MainWindow から duck-typed で
注入する (set_teardown と同型)。ここで assert しないと「MainWindow に unload
メソッドを新設してそれを assert」で実経路が無防備のまま緑になる。

拒否の機序 (WHY): close() は handle.lock を取るので、export ワーカーが select 中
だと GUI スレッドがその読み終了まで**同期ブロック**する (実測 cold 1.18s /
warm 0.73-0.83s)。in-flight の select は lock により完走し、SampleReadError に
なるのは _closed を見る「次の列」。BusyOverlay は MainWindow の子で cover() が
parent.rect() なので、フロートしたドック (トップレベル窓) は覆えない
= 「偶然の遮断」は今日も成立していない。
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel


def _loaded(tmp_path: Path) -> tuple[AppViewModel, str, MdfHandle]:
    path = tmp_path / "guard.mf4"
    write_mdf4(
        path,
        [
            {
                "name": "Spd",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            }
        ],
    )
    session = Session()
    key = session.load(path, confirm_expansion=None).key
    app_vm = AppViewModel(session=session)
    app_vm.register_loaded(key)
    handle = session._groups.group(key).handle
    assert handle is not None
    return app_vm, key, handle


def test_export_controller_is_busy_during_a_real_submit(qtbot: QtBot) -> None:
    """実 submit で busy になり、完了で戻ること (内部集合を直接いじらない)。"""
    from valisync.gui.workers.export_worker import ExportController

    ctrl = ExportController()
    assert ctrl.is_busy() is False
    release = threading.Event()
    done: list[str] = []
    ctrl.submit(lambda: release.wait(5.0), on_success=lambda: done.append("ok"))
    assert ctrl.is_busy() is True  # submit 直後から busy (pool 開始を待たない)
    release.set()
    qtbot.waitUntil(lambda: done == ["ok"], timeout=5000)
    assert ctrl.is_busy() is False


def test_unload_is_refused_while_the_busy_predicate_is_true(tmp_path: Path) -> None:
    app_vm, key, handle = _loaded(tmp_path)
    tags: list[str] = []
    app_vm.subscribe(tags.append)
    app_vm.set_busy_predicate(lambda: True)

    app_vm.unload_file(key)

    assert key in app_vm.loaded_file_keys, "拒否されたのにリストから消えた"
    assert app_vm.session.group_signals(key), "拒否されたのに session から消えた"
    assert handle.is_closed is False, "拒否されたのに handle が閉じられた"
    assert tags == ["unload_blocked"], f"通知が {tags}"
    assert app_vm.last_unload_refusal == ("export_busy", ())


def test_unload_proceeds_when_the_predicate_is_false(tmp_path: Path) -> None:
    """positive control — 「そもそも経路に到達していない」との区別。"""
    app_vm, key, handle = _loaded(tmp_path)
    app_vm.set_busy_predicate(lambda: False)

    app_vm.unload_file(key)

    assert key not in app_vm.loaded_file_keys
    assert handle.is_closed is True
    with pytest.raises(KeyError):
        app_vm.session.group_signals(key)


def test_main_window_wires_the_export_controller_into_the_vm(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """実配線を通す: 実 submit で busy → 実 VM 経路の unload が拒否される。

    述語の同一性 (is) ではなく **効果** を見る — 述語を差し替えても
    「エクスポート中は閉じられない」が保たれることだけが契約。

    文言は S.UNLOAD_BLOCKED_BY_EXPORT を参照せず実文言を直書きする
    (定数同士の比較は恒真化して独立オラクルにならない)。
    """
    from valisync.gui.views.main_window import MainWindow

    app_vm, key, handle = _loaded(tmp_path)
    win = MainWindow(app_vm)
    qtbot.addWidget(win)
    modals: list[str] = []
    win._notify_blocked = modals.append  # DI (既存 _default_confirm と同規約)

    release = threading.Event()
    win._export_controller.submit(lambda: release.wait(5.0))
    try:
        win.file_browser_vm.unload(0)  # 実 VM 経路 (View の確認モーダルの先)
        assert key in app_vm.loaded_file_keys
        assert handle.is_closed is False
        assert modals == ["エクスポート中はファイルを閉じられません"]
        assert win.status_message() == "エクスポート中はファイルを閉じられません"
    finally:
        release.set()
    qtbot.waitUntil(lambda: win._export_controller.is_busy() is False, timeout=5000)


def test_remove_action_is_disabled_and_explained_while_exporting(
    qtbot, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    """入口を塞ぐ: 実行不能な操作は確認モーダルを答えさせる前に disabled にする。"""
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
    from valisync.gui.views.file_browser_view import FileBrowserView

    app_vm, _key, _handle = _loaded(tmp_path)
    app_vm.set_busy_predicate(lambda: True)
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)

    menu = view.build_context_menu(0)
    remove = next(a for a in menu.actions() if a.text() == "ファイルを閉じる")
    assert remove.isEnabled() is False
    assert remove.toolTip() == "エクスポート中はファイルを閉じられません"
    # Qt はメニュー項目の tooltip を既定で抑制する — 有効化しないと説明が出ない。
    assert menu.toolTipsVisible() is True


def test_remove_action_is_enabled_when_not_exporting(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
    from valisync.gui.views.file_browser_view import FileBrowserView

    app_vm, _key, _handle = _loaded(tmp_path)
    app_vm.set_busy_predicate(lambda: False)
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)

    menu = view.build_context_menu(0)
    remove = next(a for a in menu.actions() if a.text() == "ファイルを閉じる")
    assert remove.isEnabled() is True


def test_dependent_signal_refusal_is_announced_not_silent(tmp_path: Path) -> None:
    """既存の唯一の無音拒否 (dependent_signals) を同じチャネルに載せる。

    確認モーダルに「はい」と答えた破壊的操作が何も起こさないのは、
    エクスポート中の拒否と同じ欠陥 (dependent_signals の GUI 消費者は grep でゼロ)。
    """
    app_vm, key, handle = _loaded(tmp_path)
    src = app_vm.session.signals()[0]
    derived = app_vm.session.evaluate_formula(f"{src.name} * 2", {src.name: src})
    tags: list[str] = []
    app_vm.subscribe(tags.append)

    app_vm.unload_file(key)

    assert key in app_vm.loaded_file_keys
    assert handle.is_closed is False
    assert tags == ["unload_blocked"]
    reason, names = app_vm.last_unload_refusal
    assert reason == "dependents"
    assert derived.name in names


def test_dependent_refusal_names_the_blocking_signals_to_the_user(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """「どの派生信号が邪魔しているか」まで見せる (理由コードや汎用文言で終わらせない)。

    文言は S.* を参照せず実文言を直書きする (定数同士の比較は恒真化する)。
    """
    from valisync.gui.views.main_window import MainWindow

    app_vm, key, handle = _loaded(tmp_path)
    src = app_vm.session.signals()[0]
    derived = app_vm.session.evaluate_formula(f"{src.name} * 2", {src.name: src})
    win = MainWindow(app_vm)
    qtbot.addWidget(win)
    modals: list[str] = []
    win._notify_blocked = modals.append  # DI (既存 _default_confirm と同規約)

    win.file_browser_vm.unload(0)  # 実 VM 経路 (View の確認モーダルの先)

    assert key in app_vm.loaded_file_keys
    assert handle.is_closed is False
    assert modals == [f"派生信号 {derived.name} が参照しているため閉じられません"]
    assert win.status_message() == modals[0]


def test_refusal_reason_is_not_a_latch(tmp_path: Path) -> None:
    """拒否理由は「直近の試行」の性質 — 成功した unload の後に残ってはいけない。

    latch のままだと、"unload_blocked" 通知以外の契機でこれを読む将来の
    consumer が「閉じられなかった」と誤って報告する。
    """
    app_vm, key, _handle = _loaded(tmp_path)
    busy = True
    app_vm.set_busy_predicate(lambda: busy)
    app_vm.unload_file(key)
    assert app_vm.last_unload_refusal == ("export_busy", ())

    busy = False
    app_vm.unload_file(key)

    assert key not in app_vm.loaded_file_keys, "positive control: 2 回目は成功する"
    assert app_vm.last_unload_refusal is None, "成功後も古い拒否理由が残っている"
