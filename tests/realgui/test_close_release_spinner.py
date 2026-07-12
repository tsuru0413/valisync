"""Layer C: real-display verification of the FileBrowser releasing spinner (FU-16).

While a closed file's data drains in the background, its File Browser row shows a
rotating spinner and is dimmed + non-interactive. This drives the real unload
path, PAUSES the background drain so the releasing state persists long enough to
photograph, and captures real-display screenshots to confirm the spinner is
painted and rotates, the row is muted + non-selectable/non-enabled, and that
finishing the drain removes the row.

Spinner *rendering* is data-size-independent (it is gated on the releasing state,
not on how much is being freed), so a small in-memory group faithfully drives it.
The perf observables (sync-close <200 ms / drain heartbeat) are proven separately
at prod scale by scripts/fu16_teardown_bench.py and the 264k after-measurement.

Run deliberately on Windows with a real display::

    QT_QPA_PLATFORM=windows uv run pytest --realgui tests/realgui/test_close_release_spinner.py -v

Note: it briefly forces the window on top of other windows.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def _sig(name: str, n: int = 200):
    from valisync.core.models import Signal

    return Signal(
        name=name,
        timestamps=np.arange(n, dtype=np.float64),
        values=np.zeros(n, dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def test_releasing_row_shows_rotating_spinner_on_real_display(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import SignalGroup
    from valisync.gui.adapters.qt_signal_models import FileListModel
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
    from valisync.gui.views.file_browser_view import FileBrowserView
    from valisync.gui.workers.teardown_service import TeardownService

    app_vm = AppViewModel()
    # One file stays loaded (a normal row for contrast) + one we will close.
    keep = app_vm.session._groups.add(
        SignalGroup((_sig("keep"),), Path("keep.csv").absolute(), "CSV", datetime.now())
    )
    closing = app_vm.session._groups.add(
        SignalGroup(
            tuple(_sig(f"c{i}") for i in range(8)),
            Path("closing.csv").absolute(),
            "CSV",
            datetime.now(),
        )
    )
    app_vm._loaded_keys = [keep, closing]

    teardown = TeardownService(on_finished=app_vm.mark_released)
    app_vm.set_teardown(teardown)

    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(320, 320, 380, 200)
    view.show()
    qtbot.waitExposed(view)

    # Close the second file, then PAUSE the drain so the releasing state (and its
    # spinner) persists for the screenshots. Pausing does not alter the spinner's
    # look -- the view's own 80 ms timer animates the arc regardless.
    app_vm.unload_file(closing)
    teardown._timer.stop()

    releasing_row = 1  # loaded 'keep' at row 0, releasing 'closing' appended at 1
    # Wait for the releasing row to actually EXIST (2 rows). is_releasing() alone
    # is only a `row >= loaded_count` bound, so it would spuriously be True for an
    # out-of-range row -- without the teardown handoff, files stays at 1 row and
    # this times out (honest-RED: no handoff -> no spinner row).
    qtbot.waitUntil(
        lambda: len(vm.files) == 2 and vm.is_releasing(releasing_row), timeout=3000
    )
    qtbot.wait(200)  # let the row paint at least once

    screen = QApplication.primaryScreen()
    angle1 = view._spin_angle
    screen.grabWindow(0).save(str(tmp_path / "spinner_frame1.png"))
    qtbot.wait(320)  # ~4 spin ticks (80 ms each)
    angle2 = view._spin_angle
    screen.grabWindow(0).save(str(tmp_path / "spinner_frame2.png"))

    # The animation angle advanced while releasing (drives the visible rotation;
    # the arc is repainted on each tick because a releasing row is present).
    assert angle1 != angle2, f"spinner angle did not advance ({angle1} -> {angle2})"

    # The releasing row is muted + non-interactive (spinner placeholder).
    idx = view.model.index(releasing_row, 0)
    assert view.model.data(idx, FileListModel.ReleasingRole) is True
    # By design the dimmed *filename* stays (it says WHICH file is closing); the
    # spinner -- not a "releasing" label -- is what signals the release state.
    # ("テキスト無し" in the plan means "no 解放中 label", not "hide the name".)
    assert view.model.data(idx, Qt.ItemDataRole.DisplayRole) == "closing.csv"
    flags = view.model.flags(idx)
    assert not (flags & Qt.ItemFlag.ItemIsSelectable), "releasing row must not select"
    assert not (flags & Qt.ItemFlag.ItemIsEnabled), "releasing row must be disabled"
    # Contrast: the loaded row above stays a normal, selectable/enabled row.
    keep_idx = view.model.index(0, 0)
    assert view.model.data(keep_idx, FileListModel.ReleasingRole) is False
    assert view.model.flags(keep_idx) & Qt.ItemFlag.ItemIsSelectable

    # Resume the drain -> data frees -> mark_released -> the releasing row is gone.
    teardown._timer.start()
    qtbot.waitUntil(lambda: not app_vm.releasing_files, timeout=5000)
    qtbot.wait(150)
    screen.grabWindow(0).save(str(tmp_path / "spinner_gone.png"))
    assert not any(vm.is_releasing(r) for r in range(len(vm.files)))
    assert vm.files == ["keep.csv"]

    print(f"screenshots: {tmp_path}")
