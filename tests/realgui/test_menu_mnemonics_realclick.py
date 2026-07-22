"""Layer C: Alt→ニーモニクスの実 OS キー到達 (UX-41 解消の実機証跡・G-46)。

増分D-1「文言 OS」でメニューバー面に付与したニーモニクス (§2.4 適用面規則) が
実 OS の Alt キー入力から実際に到達可能であることを実証する。合成
QTest.keyClick/action.trigger() は OS→Qt のキー経路と前面/フォーカスを迂回し
実証にならない (Layer B)。

実測で判明した経路: Windows の「Alt 単体を押離し→メニューバーがキーボードナビ
待受状態→文字キーでメニューを開く」二段階タップは、本環境の合成
``keybd_event`` では Qt に届かなかった (WM_SYSKEYUP(VK_MENU) 単体の投影だけでは
``QApplication.queryKeyboardModifiers()`` が OS レベルでは Alt 押下を確認する
一方、Qt 側のショートカット処理には反映されない)。Alt を押しっぱなしで文字
キーを叩く「保持アクセラレータ」形 (Windows のもう一つの正規経路 — 物理
キーボードで実際に人が Alt+F を叩く際の一般的な押下順序でもある) は確実に
Qt のメニューバーへ届く。以後このリポジトリで Alt メニューアクセラレータを
実 OS 入力で駆動する際は本ヘルパ (保持形) を参照する。

トップレベル4つ (File/View/Analyze/Help) + File 配下1つ (Recent Files — 送出
しても副作用が無い安全な項目) の実キー到達で足る
(spec 2026-07-22-incd-strings-os-design.md §9 受け入れ基準)。Open/Export/Exit の
ニーモニクスは実トリガーするとネイティブダイアログ/アプリ終了を起こすため
本テストでは到達確認の対象に選ばない — 到達性の構造は Recent Files と同一
(メニューバー→popup→mnemonic の同一配送経路) であり、個別に実行する意味は薄い。

判定は自動 assert に加え、各メニュー open のスクリーンショットを人/AI が目視
確認する (design_export/evidence_stringsos/ へ保存して証跡として残す —
文言OS Task7 ①ゲート)。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    at,
    key,
    skip_unless_real_display,
)
from valisync.gui.strings import strip_mnemonic

pytestmark = pytest.mark.realgui

VK_MENU = 0x12  # Alt
VK_ESCAPE = 0x1B

EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2] / "design_export" / "evidence_stringsos"
)


def _shown_mw(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    mw.showNormal()
    mw.setGeometry(120, 120, 1200, 760)
    mw.raise_()
    mw.activateWindow()
    qtbot.waitExposed(mw)
    qtbot.waitUntil(lambda: not mw.isMaximized() and mw.width() > 1000, timeout=3000)
    QApplication.processEvents()
    return mw


def _focus_by_real_click(mw) -> None:  # type: ignore[no-untyped-def]
    """メニューバー右端の空き領域を実クリックしてウィンドウを前面/フォーカスへ。"""
    from PySide6.QtCore import QPoint

    mb = mw.menuBar()
    p = mb.mapToGlobal(QPoint(mb.width() - 8, mb.height() // 2))
    dpr = mw.devicePixelRatioF()
    x, y = round(p.x() * dpr), round(p.y() * dpr)
    at(x, y, LDOWN)
    at(x, y, LUP)


def _open_top_level_menu(letter: str) -> None:
    """実 OS: Alt を保持しつつ letter を押離しして最上位メニューを開く。"""
    from PySide6.QtWidgets import QApplication

    key(VK_MENU, up=False)
    time.sleep(0.1)
    QApplication.processEvents()
    key(ord(letter.upper()))
    time.sleep(0.1)
    QApplication.processEvents()
    key(VK_MENU, down=False)
    time.sleep(0.15)
    QApplication.processEvents()


def _select_in_open_menu(letter: str) -> None:
    """実 OS: 既に開いているメニュー内で letter のニーモニクス項目を選択する。"""
    from PySide6.QtWidgets import QApplication

    key(ord(letter.upper()))
    time.sleep(0.15)
    QApplication.processEvents()


def _save_evidence(name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / name
    QApplication.primaryScreen().grabWindow(0).save(str(path))
    return path


def test_alt_mnemonics_reach_top_level_menus_and_recent_files_submenu(
    qtbot: QtBot,
) -> None:
    """Alt+F/V/A/H の各トップレベルメニュー到達 + File→R (最近使ったファイル) 到達。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication, QMenu

    mw = _shown_mw(qtbot)
    _focus_by_real_click(mw)
    QApplication.processEvents()

    top_level = [
        ("F", "ファイル"),
        ("V", "表示"),
        ("A", "解析"),
        ("H", "ヘルプ"),
    ]
    shots: dict[str, Path] = {}

    for letter, expected_label in top_level:
        _open_top_level_menu(letter)
        qtbot.waitUntil(
            lambda: QApplication.activePopupWidget() is not None, timeout=3000
        )
        popup = QApplication.activePopupWidget()
        assert isinstance(popup, QMenu), (
            f"Alt+{letter} でメニューが開かなかった (活性ポップアップ={popup!r})"
        )
        actual_label = strip_mnemonic(popup.title())
        # フライアウトの実描画がスクショに間に合うよう一呼吸置く (論理状態は
        # activePopupWidget で既に確定済みだが、ペイントは次の event loop ターン)。
        time.sleep(0.15)
        QApplication.processEvents()
        shots[letter] = _save_evidence(f"mnemonic_alt_{letter.lower()}.png")
        assert actual_label == expected_label, (
            f"Alt+{letter} で開いたメニューの表題が期待と不一致: "
            f"{actual_label!r} != {expected_label!r}. screenshot: {shots[letter]}"
        )
        # 次のメニューへ進む前に Escape で閉じる。
        key(VK_ESCAPE)
        qtbot.waitUntil(lambda: QApplication.activePopupWidget() is None, timeout=3000)

    # --- File 配下1つ: 最近使ったファイル (&R) — 送出しても副作用が無い ----------
    _open_top_level_menu("F")
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None, timeout=3000)
    file_menu = QApplication.activePopupWidget()
    assert isinstance(file_menu, QMenu)
    assert strip_mnemonic(file_menu.title()) == "ファイル"

    _select_in_open_menu("R")
    qtbot.waitUntil(
        lambda: (
            QApplication.activePopupWidget() is not None
            and QApplication.activePopupWidget() is not file_menu
        ),
        timeout=3000,
    )
    recent_menu = QApplication.activePopupWidget()
    assert isinstance(recent_menu, QMenu), (
        f"File→R (最近使ったファイル) のサブメニューが開かなかった "
        f"(活性ポップアップ={recent_menu!r})"
    )
    # フライアウトの実描画がスクショに間に合うよう一呼吸置く (論理状態は
    # activePopupWidget で既に確定済みだが、ペイントは次の event loop ターン)。
    time.sleep(0.2)
    QApplication.processEvents()
    shot_recent = _save_evidence("mnemonic_alt_f_then_r_recent_files.png")
    assert strip_mnemonic(recent_menu.title()) == "最近使ったファイル", (
        f"File→R で開いたサブメニューの表題が期待と不一致: "
        f"{strip_mnemonic(recent_menu.title())!r}. screenshot: {shot_recent}"
    )

    # 後始末: 全メニューを閉じる。
    key(VK_ESCAPE)
    key(VK_ESCAPE)
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is None, timeout=3000)

    print(f"[UX-41] mnemonic screenshots: {[*shots.values(), shot_recent]}")
