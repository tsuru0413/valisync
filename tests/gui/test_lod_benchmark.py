"""LOD rendering performance benchmark — Task 11.1.

A guard/characterisation test for the dynamic-LOD pipeline (already implemented
in GraphPanelVM, Task 3.1): with a 1,000,000-sample signal it verifies that
``render_data()``

- bounds the drawn point count to ``~2 * panel_width_px`` regardless of source
  size (R11.1/R11.4),
- preserves the min-max envelope so spikes survive downsampling (R11.3),
- completes well within a generous wall-clock budget and is served instantly
  from cache on repeat (R11.2),

so a future regression that drops the LOD reduction or its O(N) cost is caught.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

_N = 1_000_000
_WIDTH = 800
_BOUND = 2 * _WIDTH + 4  # n_target plus a tiny slack for boundary samples


def _million_point_session(tmp_path: Path) -> tuple[Session, str, float, float]:
    """Load a 1M-sample MDF4 with planted global extremes; return its bounds."""
    ts = np.linspace(0.0, 1000.0, _N)
    vs = np.sin(ts).astype(np.float64)
    vs[123_456] = 5.0  # global max — must survive downsampling
    vs[789_012] = -5.0  # global min — must survive downsampling
    mf4 = write_mdf4(
        tmp_path / "big.mf4",
        [{"name": "sig", "timestamps": ts, "values": vs, "bus_type": CAN}],
    )
    session = Session()
    key = session.load(mf4, None).key
    return session, f"{key}::sig", float(vs.min()), float(vs.max())


def test_render_one_million_points_is_bounded_and_fast(tmp_path: Path) -> None:
    session, sig_name, vmin, vmax = _million_point_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.set_panel_width(_WIDTH)  # n_target = 2 * 800 = 1600
    vm.add_signal(sig_name)  # auto-fits to the full extent

    t0 = time.perf_counter()
    curves = vm.render_data()
    cold_ms = (time.perf_counter() - t0) * 1000.0

    # ── Bounded output (R11.1) ───────────────────────────────────────────────
    assert vm.lod_active is True
    assert vm.last_rendered_points <= _BOUND
    drawn = curves[0]
    assert len(drawn.timestamps) <= _BOUND
    assert len(drawn.timestamps) == len(drawn.values)

    # ── Min-max envelope preserved (R11.3) ───────────────────────────────────
    assert float(drawn.values.max()) == vmax  # planted spike survives
    assert float(drawn.values.min()) == vmin

    # ── Within budget + cached repeat is instant (R11.2) ─────────────────────
    assert cold_ms < 1000.0, f"cold render took {cold_ms:.1f} ms"
    t1 = time.perf_counter()
    vm.render_data()
    cached_ms = (time.perf_counter() - t1) * 1000.0
    assert cached_ms < cold_ms  # cache hit must be cheaper than a cold render

    print(f"\nLOD 1M render: cold={cold_ms:.1f}ms cached={cached_ms:.3f}ms")


def test_zoom_in_stays_bounded(tmp_path: Path) -> None:
    """Zooming to a sub-window re-downsamples and stays bounded (R11.4)."""
    session, sig_name, _vmin, _vmax = _million_point_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.set_panel_width(_WIDTH)
    vm.add_signal(sig_name)
    vm.render_data()

    vm.set_x_range(0.0, 10.0)  # ~1% of the full range
    t0 = time.perf_counter()
    curves = vm.render_data()
    zoom_ms = (time.perf_counter() - t0) * 1000.0

    assert vm.last_rendered_points <= _BOUND
    assert len(curves[0].timestamps) <= _BOUND
    assert zoom_ms < 1000.0, f"zoom render took {zoom_ms:.1f} ms"
