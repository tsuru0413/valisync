"""GraphAreaVM の Global_Cursor 全パネル同期 (R15.1)."""

from __future__ import annotations

import csv
from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM


def _loaded_session(tmp_path: Path) -> tuple[Session, str]:
    csv_file = tmp_path / "data.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "s1"])
        for i in range(100):
            w.writerow([i * 0.01, float(i)])
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    session = Session()
    key = session.load(csv_file, fmt)
    return session, key


def test_cursor_propagates_to_sibling_panels(tmp_path):
    session, _ = _loaded_session(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.add_panel()  # tab 0 に 2 枚目のパネル
    panels = area.panels(0)
    assert len(panels) == 2

    panels[0].set_cursor(0.42)

    assert panels[1].cursor_t == 0.42


def test_cursor_propagation_is_not_infinite(tmp_path):
    # 兄弟へ配信→兄弟が再 notify→再帰、を _propagating ガードが止める
    session, _ = _loaded_session(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.add_panel()
    panels = area.panels(0)
    panels[0].set_cursor(0.1)  # 無限再帰なら RecursionError
    assert panels[0].cursor_t == 0.1
    assert panels[1].cursor_t == 0.1


def test_cursor_propagates_when_x_sync_disabled(tmp_path):
    """Cursor broadcast is independent of the X-sync toggle (R15.1).

    Even when x_sync is off (ranges don't link), a cursor placement on one panel
    must still propagate to all sibling panels so the time marker stays aligned.
    """
    session, _ = _loaded_session(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.add_panel()  # tab 0 に 2 枚目のパネル
    panels = area.panels(0)
    assert len(panels) == 2

    area.set_x_sync(0, False)
    panels[0].set_cursor(0.55)

    assert panels[1].cursor_t == 0.55
