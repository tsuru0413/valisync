"""Layer A: GraphAreaVM のオフセットブロードキャスト (R14.5)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM


def _area_with_signal() -> tuple[GraphAreaVM, AppViewModel, str]:
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1"] + [f"{i * 0.01:.3f},{i}.0" for i in range(30)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    app = AppViewModel()
    app.request_load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    signal_key = sorted(s.name for s in app.signals())[0]
    area = GraphAreaVM(app)
    return area, app, signal_key


def _plot_signal_on(panel, key: str) -> None:
    panel.add_signal_to_axis(key, 0)


def _curve_x(panel, key: str) -> np.ndarray:
    return next(c.timestamps for c in panel.render_data() if c.name == key)


def test_offsets_event_rerenders_all_panels_across_tabs() -> None:
    area, app, signal_key = _area_with_signal()
    area.add_tab()  # second tab, second panel
    p0 = area.panels(0)[0]
    p1 = area.panels(1)[0]
    _plot_signal_on(p0, signal_key)
    _plot_signal_on(p1, signal_key)
    base0 = _curve_x(p0, signal_key).copy()
    base1 = _curve_x(p1, signal_key).copy()
    # Wide viewport covers both original (0-0.29) and shifted (0.4-0.69) data.
    # Without this, auto-fit window 0-0.29 would exclude the shifted data and
    # mask a missing broadcast to either panel (false-green).
    p0.x_range = (0.0, 1.0)
    p1.x_range = (0.0, 1.0)

    app.apply_offset(signal_key, 0.4, "signal")

    np.testing.assert_allclose(_curve_x(p0, signal_key), base0 + 0.4)
    np.testing.assert_allclose(_curve_x(p1, signal_key), base1 + 0.4)


def test_apply_offset_proxy_updates_app_state() -> None:
    area, app, signal_key = _area_with_signal()
    area.apply_offset(signal_key, 0.25, "signal")
    assert app.signal_offsets == {signal_key: 0.25}


def test_reset_offset_forwards_to_app_and_broadcasts() -> None:
    area, app, signal_key = _area_with_signal()
    panel = area.panels(0)[0]
    _plot_signal_on(panel, signal_key)
    app.apply_offset(signal_key, 0.5, "signal")
    assert panel.offset_for(signal_key) == 0.5  # broadcast already delivered it
    area.reset_offset(signal_key, "signal")
    assert app.signal_offsets.get(signal_key) is None
    assert panel.offset_for(signal_key) == 0.0  # broadcast carries the reset to 0
