"""Layer C: Ctrl+E が export_csv へ到達するか (実 OS キー入力)。

実 OS キー(`keybd_event`)は前面ウィンドウへ届くため、実クリックで前面化/フォーカス
してから Ctrl+E を発行する。合成 QTest.keyClick は OS→Qt キー経路と focus/有効化を
迂回する(Layer B)。

honest RED: File メニュー/ツールバーに export を載せ忘れる、shortcut を外す、
またはデータ無しで無効のままだと Ctrl+E が届かず fired が空になる。

E-3 T5/T9: 加えて ExportCsvDialog の遅延展開の 2 契約を実 OS クリックで固定する
(``test_export_dialog_file_row_realclick_selects_all_columns_without_minting``):
**ファイル行のチェックは未展開の列まで含めて選択へ翻訳される** (C-b の一方通行
バグの回帰ガード) と **コンテナ行のクリックは何も変えない** (C-a)。どちらも
「鋳造カウンタが 0 のまま」であることを併せて assert する — チェックのために
列 Signal を作ると prod で 330k 鋳造の一撃になる。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import write_mdf4_flatten_fixture
from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    VK_CONTROL,
    at,
    key,
    skip_unless_real_display,
)

pytestmark = pytest.mark.realgui

VK_E = 0x45


def _focus_by_real_click(mw) -> None:  # type: ignore[no-untyped-def]
    """メニューバー右端の空き領域を実クリックしてウィンドウを前面/フォーカスへ。"""
    from PySide6.QtCore import QPoint

    mb = mw.menuBar()
    p = mb.mapToGlobal(QPoint(mb.width() - 8, mb.height() // 2))
    dpr = mw.devicePixelRatioF()
    x, y = round(p.x() * dpr), round(p.y() * dpr)
    at(x, y, LDOWN)
    at(x, y, LUP)


def test_ctrl_e_triggers_export(qtbot: QtBot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    fired: list[int] = []
    # 構築前にクラスを patch (connect が捕捉する bound method を stub 化)。
    monkeypatch.setattr(MainWindow, "export_csv", lambda self, *a: fired.append(1))
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    # export はデータ有りで有効。ロード成功を模擬して有効化する。
    mw.app_vm.register_loaded("csv_1")
    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    mw.setGeometry(200, 200, 900, 600)
    mw.show()
    mw.raise_()
    mw.activateWindow()
    qtbot.waitExposed(mw)
    QApplication.processEvents()

    _focus_by_real_click(mw)
    QApplication.processEvents()

    # 実 OS キー: Ctrl 保持 → E → Ctrl 解放。
    key(VK_CONTROL, up=False)
    key(VK_E)
    key(VK_CONTROL, down=False)

    qtbot.waitUntil(lambda: fired == [1], timeout=2000)
    assert fired == [1], (
        "Ctrl+E(実キー)が export_csv に届かない (export の shortcut/有効化/配線/focus を確認)"
    )


def _pump_n(n: int = 4) -> None:
    import time

    from PySide6.QtWidgets import QApplication

    for _ in range(n):
        QApplication.processEvents()
        time.sleep(0.02)


def _real_click_checkbox(tree, item) -> None:  # type: ignore[no-untyped-def]
    """アイテムの **チェックボックス標識** を実 OS クリックする。

    標識はアイテム矩形の左端 (ブランチ装飾の右) に描かれるので、矩形左端から
    数 px 内側を叩く。矩形中心 (テキスト上) を叩くと選択されるだけでチェックは
    変わらず、「クリックしたのに何も起きない」を C-a の期待と取り違える。
    """
    from PySide6.QtCore import QPoint

    tree.scrollToItem(item)
    _pump_n(3)
    rect = tree.visualItemRect(item)
    assert rect.height() > 0, "対象行が可視域に無い (実クリックできない)"
    vp = tree.viewport()
    local = QPoint(rect.left() + 8, rect.center().y())
    gp = vp.mapToGlobal(local)
    dpr = vp.devicePixelRatioF()
    x, y = round(gp.x() * dpr), round(gp.y() * dpr)
    at(x, y, LDOWN)
    _pump_n(1)
    at(x, y, LUP)
    _pump_n(4)


def test_export_dialog_file_row_realclick_selects_all_columns_without_minting(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """ファイル行の実チェック 2 回 (全選択 → 解除) + コンテナ行は実クリック不感。

    E-3 T5 の ①ゲート。固定するのは 3 つ:

      1. ファイル行のチェックボックスを実クリックすると、**未展開のコンテナの列まで
         含めて** 全列が選択される (`ItemIsAutoTristate` の伝播を選択へ翻訳する
         `_toggle_row` の回帰ガード — 表示だけ引き戻す実装は
         PartiallyChecked に貼り付いて「二度と Checked にならず解除にも使えない
         一方通行」になる)。
      2. もう一度実クリックすると全解除される (一方通行でないこと)。
      3. コンテナ行 (複数列の物理チャンネル) のチェックボックスを実クリックしても
         **何も変わらない** (C-a: ItemIsUserCheckable を外している)。

    そして全経路で **鋳造カウンタが 0**。チェックのために列 Signal を作ると prod で
    330k 鋳造 = ~390 MB の一撃になる (C-b)。
    """
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.export_csv_dialog import _ROW_ROLE, ExportCsvDialog
    from valisync.gui.views.main_window import MainWindow

    path = write_mdf4_flatten_fixture(tmp_path)
    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    session = window.app_vm.session
    outcome = session.load(path)
    window._on_loaded(outcome)
    mgr = session._groups  # C-e: Session には出さない introspection
    n_columns = session.total_column_count(outcome.key)
    assert n_columns > len(session.group_signals(outcome.key)), (
        f"コンテナの無い fixture では C-a/C-b を実証できない (列 {n_columns})"
    )

    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(screen.x() + 60, screen.y() + 60, 900, 600)
    window.show()
    qtbot.waitExposed(window)

    dlg = ExportCsvDialog(window.app_vm, set(), window)
    qtbot.addWidget(dlg)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dlg.move(screen.x() + 80, screen.y() + 80)
    dlg.resize(560, 620)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    qtbot.waitExposed(dlg)
    _pump_n(4)

    assert mgr.mint_count == 0, f"ダイアログを開くだけで鋳造された: {mgr.mint_count}"
    assert dlg._selected == {}, "初期選択が空でない (前提が崩れている)"

    tree = dlg._tree
    file_item = tree.topLevelItem(0)
    assert file_item is not None

    # ── (1) ファイル行のチェックボックスを実クリック → 全列が選択される ──
    _real_click_checkbox(tree, file_item)
    qtbot.waitUntil(lambda: len(dlg._selected) == n_columns, timeout=3000)
    assert len(dlg._selected) == n_columns, (
        f"ファイル行の実チェックで全列が選択されない: "
        f"{len(dlg._selected)}/{n_columns} (未展開コンテナの列が漏れている疑い)"
    )
    assert mgr.mint_count == 0, (
        f"ファイル行チェックが列を鋳造した (C-b 違反): {mgr.mint_count}"
    )

    # ── (2) もう一度実クリック → 全解除 (一方通行でない) ──
    _real_click_checkbox(tree, file_item)
    qtbot.waitUntil(lambda: len(dlg._selected) == 0, timeout=3000)
    assert dlg._selected == {}, (
        f"2 回目の実チェックで解除されない (PartiallyChecked 貼り付きの"
        f"一方通行バグ): 残 {len(dlg._selected)}"
    )
    assert mgr.mint_count == 0, f"解除が列を鋳造した: {mgr.mint_count}"

    # ── (3) コンテナ行の実クリックは何も変えない (C-a) ──
    container = next(
        (
            it
            for it in dlg._iter_rows()
            if dlg._rows[it.data(0, _ROW_ROLE)].single_key is None
        ),
        None,
    )
    assert container is not None, "複数列のコンテナ行が無い (fixture 前提が崩れた)"
    assert not (container.flags() & Qt.ItemFlag.ItemIsUserCheckable), (
        "コンテナ行が user-checkable — C-a が効いていない"
    )
    before = container.checkState(0)
    _real_click_checkbox(tree, container)
    assert container.checkState(0) == before, (
        f"コンテナ行の実クリックでチェックが変わった (C-a 違反): "
        f"{before} -> {container.checkState(0)}"
    )
    assert dlg._selected == {}, (
        f"コンテナ行の実クリックで選択が発生した: {sorted(dlg._selected)[:5]}"
    )
    assert mgr.mint_count == 0, (
        f"全経路を通して鋳造 0 でなければならない: {mgr.mint_count}"
    )
