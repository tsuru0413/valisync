"""Layer C: FU-19 — 実 MainWindow でプロットがある状態のロード中に
BusyOverlay が兄弟の最前面へ立ち、プロット上に実描画される (z-order 背面沈み解消)。

`--realgui` opt-in・実ディスプレイ+Windows 必須。素 QWidget 親を使う
test_busy_cancel_realclick.py / test_busy_overlay_resize_realinput.py は overlay が
唯一の子=常に最前面のため FU-19 (central/dock との兄弟 z-order) を exercise できない。
本テストは実 MainWindow の子スタックを通し、隠蔽の有無を QApplication.widgetAt で読む。

observable に isVisible() は使わない — 実機で「隠蔽されても True」を実証済み。合格は
widgetAt(ウィンドウ中心) が overlay かその子孫 (最深子 QProgressBar) を返すこと。

honest-RED: busy_overlay.py の show() から self.raise_() を一時的に外す sabotage で、
widgetAt がプロット QWidget を返し assert が FAIL することを実証する (Step 2)。
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def _make_window_with_two_panels(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    """MainWindow を構築し CSV 1 信号を同期ロード・2 パネル化して実表示する。

    QSettings 隔離は tests/realgui/conftest.py の autouse が効く。ロードは
    session.load→_on_loaded を直接呼んで同期化 (production の完走経路と同じ登録/活性化)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    csv = tmp_path / "sig.csv"
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

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    outcome = window.app_vm.session.load(csv, fmt)
    window._on_loaded(outcome)  # 登録+活性化+ChannelBrowser 反映+workbench 表示
    window.graph_area_vm.add_panel(0)  # 2 パネル化 (不透明 pyqtgraph 背景で中央を覆う)

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    w = min(1120, screen.width() - 120)
    h = min(760, screen.height() - 120)
    window.setGeometry(screen.x() + 60, screen.y() + 60, w, h)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(3):
        QApplication.processEvents()
    return window


def _is_overlay_or_descendant(w, overlay) -> bool:  # type: ignore[no-untyped-def]
    while w is not None:
        if w is overlay:
            return True
        w = w.parentWidget()
    return False


@pytest.mark.realgui
def test_overlay_raised_above_plots_during_real_load(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-19 受け入れ: プロット2枚がある実 MainWindow で本番ロード経路を駆動し、
    ロード中に overlay がプロット最前面 (widgetAt が overlay 子孫) に立つ。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    window = _make_window_with_two_panels(qtbot, tmp_path)
    overlay = window.busy_overlay

    release = threading.Event()
    cancel_event = threading.Event()
    discards: list[object] = []

    def slow_load() -> str:
        release.wait(timeout=10.0)  # widgetAt 観測までロードを「実行中」に保つ
        return "late_result"

    # 本番の off-thread ロード経路 (_refresh_busy -> show() -> raise_() を自然に exercise)。
    window._load_controller.submit(
        slow_load,
        busy=overlay,
        cancel_event=cancel_event,
        label="load.mf4",
        on_discard=discards.append,
    )
    qtbot.waitUntil(lambda: not overlay.isHidden(), timeout=3000)
    qtbot.waitUntil(lambda: overlay.progress_bar.rect().height() > 0, timeout=3000)
    for _ in range(4):
        QApplication.processEvents()
        time.sleep(0.02)

    # widgetAt は論理グローバル座標 (DPR 換算不要)。overlay が最前面なら中央に
    # 覆い被さる overlay の子 (QProgressBar) を、隠蔽時はプロット QWidget を返す。
    center_g = window.mapToGlobal(window.rect().center())
    w_at = QApplication.widgetAt(center_g)

    shot = tmp_path / "fu19_overlay_over_plots.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot))

    try:
        assert _is_overlay_or_descendant(w_at, overlay), (
            f"FU-19 再発: ロード中に widgetAt(中心)={type(w_at).__name__} が overlay "
            f"子孫でない = overlay が不透明プロット背面に隠れている。screenshot: {shot}"
        )
        print(
            f"[FU-19] overlay raised above plots; widgetAt={type(w_at).__name__}. shot: {shot}"
        )
    finally:
        # assert 失敗時も blocking ワーカーを必ず排水しスレッドを残さない。
        release.set()

    # このテストはキャンセルしない (cancel_active 未呼び出し) ため on_discard は
    # 発火しない — discards は本番シグネチャ整合のための wiring として残すのみ。
    # 排水完了の観測は count-based busy 解除 (_pop -> _refresh_busy が0件で hide)。
    qtbot.waitUntil(lambda: overlay.isHidden(), timeout=3000)
