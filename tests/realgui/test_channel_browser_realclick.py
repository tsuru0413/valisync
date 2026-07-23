"""Layer C: real-OS-input test for the ChannelBrowser "Add to Active Panel" menu.

Opt-in — run with ``--realgui`` on Windows + a real display. Issues a genuine
right-click via Win32 and asserts the application's own QMenu pops up (the OS →
Qt path a synthesized event cannot exercise). See ``.claude/skills/gui-verify/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import RDOWN, RUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _fmt():
    from valisync.core.models import Delimiter, FormatDefinition

    return FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )


def test_add_to_panel_menu_appears_on_real_os_right_click(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()

    from PySide6.QtCore import QEventLoop, QItemSelectionModel, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
    from valisync.gui.views.channel_browser_view import ChannelBrowserView

    path = tmp_path / "d.csv"
    path.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, _fmt())
    app_vm.set_active_file(key)

    view = ChannelBrowserView(ChannelBrowserVM(app_vm))
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 360, 240)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(
        lambda: view.tree.visualRect(view.model.index(0, 0)).height() > 0,
        timeout=3000,
    )

    # Select the first signal row so "Add to Active Panel" is enabled.
    # The tree is bound DIRECTLY to SignalTreeModel (FU-22 B: the sort proxy was
    # dropped -- it eagerly materialized all array children on reset, defeating the
    # lazy tree). Scalars are top-level leaves, so model.index(0,0) is the row.
    index = view.model.index(0, 0)
    view.tree.selectionModel().select(
        index,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )

    dpr = view.devicePixelRatioF()
    center = view.tree.visualRect(index).center()
    gp = view.tree.viewport().mapToGlobal(center)
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    captured: dict[str, object] = {}

    def do_real_right_click() -> None:
        at(phys_x, phys_y, RDOWN)
        at(phys_x, phys_y, RUP)

    loop = QEventLoop()

    def capture() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "ch.png"))
        if isinstance(popup, QMenu):
            captured["actions"] = [a.text() for a in popup.actions()]
            popup.close()
        loop.quit()

    QTimer.singleShot(300, do_real_right_click)
    QTimer.singleShot(900, capture)
    QTimer.singleShot(4000, loop.quit)  # safety net
    loop.exec()

    assert captured.get("type") == "QMenu", (
        "no context menu on a real OS right-click; "
        f"got {captured.get('type')!r}. screenshot: {tmp_path / 'ch.png'}"
    )
    # #15 (commit 03e7f79): 右クリックした行が leaf のとき、位置ベースの
    # 「信号プロパティを表示」がメニューへ追加される (build_context_menu の
    # pos 引数 → indexAt(pos) の hit leaf)。この実右クリックは選択済みの leaf
    # (index) をそのまま叩いているため hit leaf であり、2 項目とも出る。
    assert captured.get("actions") == [
        "アクティブパネルへ追加",
        "信号プロパティを表示",
    ]
