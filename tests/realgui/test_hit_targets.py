# ruff: noqa: RUF001, RUF002, RUF003
"""Layer C: UX-38 当たり判定（高さ 24px 保証）が実 OS クリックで効くこと。

`setMinimumHeight(24)` で縦方向へ拡張した常用ボタン（CollapsibleDockTitleBar の
フロート/✕・GraphPanel の +/×）のヒット領域を、**実行時 geometry から**
「旧 rect（natural height）の外 ∧ 新 rect（24px）の内」の点を導出して実 Win32
クリックし、効果（dock float/close・パネル増減）が発火することを検証する。
固定オフセットは使わない — DPR/フォント差でのフレークを避けるため
（spec §5 Task C・memory: gui_realgui_zone_widgetspace_and_offscreen_clamp）。

honest RED（sabotage・1 度実証済み）: src の `setMinimumHeight(24)` 呼出を一時
無効化すると、ボタンが自然高さ（~20px）へ縮み中央/上寄せへ再配置されるため、
同じ導出座標（旧 rect 下端の 1px 下）が縮んだボタンの外へ落ちてクリックが不発に
なる。chevron は現状 26x24（高さ既に 24px 充足）のため実測記録のみ（変更なし）。

`--realgui` opt-in・実ディスプレイ+Windows 必須。QSettings 隔離は
tests/realgui/conftest.py の autouse fixture が適用する。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _shown_mw(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
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


def _shown_mw_with_signal(qtbot: QtBot):  # type: ignore[no-untyped-def]
    """MainWindow を構築し CSV 1 信号を同期ロードして workbench（グラフ域）を
    表示する。無データだと central は Welcome ページ（QStackedWidget）でパネルの
    +/× が非可視のため、パネルボタン検証にはロードが必要。
    """
    import tempfile

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    tmp = Path(tempfile.mkdtemp())
    csv = tmp / "sig.csv"
    rows = ["t,speed"]
    for i in range(24):
        rows.append(f"{i * 0.1:.3f},{10.0 + i * 0.8:.4f}")
    csv.write_text("\n".join(rows) + "\n")
    fmt = FormatDefinition(
        name="rt_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )

    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    outcome = mw.app_vm.session.load(csv, fmt)
    mw._on_loaded(outcome)  # 登録+活性化+workbench 表示（production 完走経路）

    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
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


_REQUIRED_MIN_H = 24  # UX-38 の保証高さ（当たり判定の縦方向下限）。


def _extended_hit_point_phys(btn):  # type: ignore[no-untyped-def]
    """物理スクリーンピクセルの「旧 rect 外 ∧ 新 rect 内」クリック点を実行時算出。

    **ボタンの上端（安定）** から測った local_y を、保証高さ 24px と自然高さ
    old_h（minimumSizeHint — setMinimumHeight の影響を受けないウィジェット自身の
    hint）から導く。旧ボタンはセル内で中央寄せ（実測: 上端 (24-old_h)/2）または
    上寄せされ、いずれも下端は最大 (24+old_h)/2。その行 (24+old_h)//2 は
    「旧 rect 外 ∧ 保証 24px 内」の最初の行になる（old_h<24 が前提）。

    要点（honest-RED を成立させる設計）: **btn.height() を使わない**。live 高さで
    再計算すると、拡張を無効化（縮んで 20px）した際に local_y も縮んだボタン上へ
    再フィットして命中してしまい、sabotage が RED にならない。保証値 24 を基準に
    上端からのオフセットを固定することで、20px へ縮むと同 local_y は mapToGlobal で
    ボタン下端の外へ写り、実クリックが不発になる（＝拡張ロジック依存を実証）。
    固定「物理」オフセットではない — old_h/mapToGlobal/DPR は全て実行時由来。
    """
    from PySide6.QtCore import QPoint

    old_h = btn.minimumSizeHint().height()
    local_y = (_REQUIRED_MIN_H + old_h) // 2  # 24/20 -> 22（保証 24px 内・旧 20px 外）
    local_x = btn.width() // 2
    g = btn.mapToGlobal(QPoint(local_x, local_y))
    dpr = btn.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr), btn.height(), old_h, local_y


def _real_click(x: int, y: int) -> None:
    from PySide6.QtWidgets import QApplication

    at(x, y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(x, y, LUP)
    for _ in range(8):
        QApplication.processEvents()
        time.sleep(0.02)


def _grab(tmp_path: Path, name: str) -> Path:
    import contextlib

    from PySide6.QtWidgets import QApplication

    path = tmp_path / name
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(path))
    return path


def _wait_visible(qtbot: QtBot, btn) -> None:  # type: ignore[no-untyped-def]
    qtbot.waitUntil(
        lambda: btn.isVisible() and btn.width() > 0 and btn.height() > 0, timeout=3000
    )


def test_chevron_already_meets_24px_height(qtbot: QtBot, tmp_path: Path) -> None:
    """chevron は現状 26x24（高さ 24px 既充足）— 変更なし・実測記録のみ。"""
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    chevron = mw._collapsible_bars["file_dock"]._toggle_button
    _wait_visible(qtbot, chevron)
    g = chevron.geometry()
    shot = _grab(tmp_path, "hit_chevron.png")
    print(f"[hit-target chevron] geom={g.width()}x{g.height()} screenshot={shot}")
    assert chevron.height() >= 24, (
        f"chevron 高さ {chevron.height()} < 24（既充足の前提が崩れた）"
    )


def test_float_button_extended_hit_triggers_float(qtbot: QtBot, tmp_path: Path) -> None:
    """フロートボタンの拡張ヒット点（旧 rect 外・新 rect 内）実クリックで dock が
    フロート化し、隣接する ✕（閉じる）は誤爆しない（dock は可視のまま）。
    """
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    dock = mw.file_dock
    bar = mw._collapsible_bars["file_dock"]
    btn = bar._float_button
    _wait_visible(qtbot, btn)
    assert not dock.isFloating(), "setup: file_dock が既にフロート"

    px, py, new_h, old_h, ly = _extended_hit_point_phys(btn)
    print(
        f"[hit-target float] new_h={new_h} old_h={old_h} local_y={ly} phys=({px},{py})"
    )
    _real_click(px, py)
    qtbot.waitUntil(lambda: dock.isFloating(), timeout=3000)

    shot = _grab(tmp_path, "hit_float.png")
    assert dock.isFloating(), f"拡張ヒット点クリックでフロート化しない。shot={shot}"
    assert dock.isVisible(), f"✕ 誤爆で dock が閉じた（隣接ボタン誤爆）。shot={shot}"


def test_close_button_extended_hit_triggers_close(qtbot: QtBot, tmp_path: Path) -> None:
    """✕（閉じる）ボタンの拡張ヒット点実クリックで dock が閉じる（非可視化）。"""
    skip_unless_real_display()

    mw = _shown_mw(qtbot)
    dock = mw.file_dock
    bar = mw._collapsible_bars["file_dock"]
    btn = bar._close_button
    _wait_visible(qtbot, btn)
    assert dock.isVisible(), "setup: file_dock が既に非可視"

    px, py, new_h, old_h, ly = _extended_hit_point_phys(btn)
    print(
        f"[hit-target close] new_h={new_h} old_h={old_h} local_y={ly} phys=({px},{py})"
    )
    _real_click(px, py)
    qtbot.waitUntil(lambda: not dock.isVisible(), timeout=3000)

    shot = _grab(tmp_path, "hit_close.png")
    assert not dock.isVisible(), f"拡張ヒット点クリックで dock が閉じない。shot={shot}"


def test_add_panel_button_extended_hit_adds_panel(qtbot: QtBot, tmp_path: Path) -> None:
    """パネル + ボタンの拡張ヒット点実クリックでパネルが 1 枚増える。
    隣接する × は誤爆しない（増加分が減らない）。
    """
    from PySide6.QtWidgets import QToolButton

    skip_unless_real_display()

    mw = _shown_mw_with_signal(qtbot)
    gav = mw.graph_area_view
    qtbot.waitUntil(lambda: len(gav._panel_views) >= 1, timeout=3000)
    panel = gav._panel_views[0][2]
    add_btn = panel.findChild(QToolButton, "add_panel_button")
    _wait_visible(qtbot, add_btn)

    before = len(gav._panel_views)
    px, py, new_h, old_h, ly = _extended_hit_point_phys(add_btn)
    print(
        f"[hit-target add_panel] new_h={new_h} old_h={old_h} local_y={ly} "
        f"phys=({px},{py}) before={before}"
    )
    _real_click(px, py)
    qtbot.waitUntil(lambda: len(gav._panel_views) == before + 1, timeout=3000)

    shot = _grab(tmp_path, "hit_add_panel.png")
    assert len(gav._panel_views) == before + 1, (
        f"拡張ヒット点クリックでパネルが増えない "
        f"(before={before}, now={len(gav._panel_views)})。shot={shot}"
    )


def test_remove_panel_button_extended_hit_removes_panel(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """パネル × ボタンの拡張ヒット点実クリックでパネルが 1 枚減る（要 2 枚以上 —
    signal 経由で 1 枚追加してから、追加後レイアウトで geometry を再取得する）。
    """
    from PySide6.QtWidgets import QToolButton

    skip_unless_real_display()

    mw = _shown_mw_with_signal(qtbot)
    gav = mw.graph_area_view
    qtbot.waitUntil(lambda: len(gav._panel_views) >= 1, timeout=3000)
    # 削除可能にするため 2 枚へ（削除効果を観測するための前提づくり）。
    mw.graph_area_vm.add_panel(0)
    qtbot.waitUntil(lambda: len(gav._panel_views) >= 2, timeout=3000)

    panel = gav._panel_views[0][2]
    remove_btn = panel.findChild(QToolButton, "remove_panel_button")
    _wait_visible(qtbot, remove_btn)
    qtbot.waitUntil(lambda: remove_btn.isEnabled(), timeout=3000)

    before = len(gav._panel_views)
    px, py, new_h, old_h, ly = _extended_hit_point_phys(remove_btn)
    print(
        f"[hit-target remove_panel] new_h={new_h} old_h={old_h} local_y={ly} "
        f"phys=({px},{py}) before={before}"
    )
    _real_click(px, py)
    qtbot.waitUntil(lambda: len(gav._panel_views) == before - 1, timeout=3000)

    shot = _grab(tmp_path, "hit_remove_panel.png")
    assert len(gav._panel_views) == before - 1, (
        f"拡張ヒット点クリックでパネルが減らない "
        f"(before={before}, now={len(gav._panel_views)})。shot={shot}"
    )
