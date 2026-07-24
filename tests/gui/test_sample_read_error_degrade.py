"""Task 7 (遅延ロード 増分A): SampleReadError の render 境界 degrade (Layer A/B).

A lazy sample read (``Signal.values`` -> ``SampleSource.array()``) can raise
``SampleReadError`` on I/O failure (e.g. a file on a network drive). The render
boundary (``GraphPanelVM.render_data``) must NOT let that exception propagate:
the failing curve degrades to an empty ``RenderCurve`` and exactly ONE diagnostic
is recorded (via the injected sink → app's DiagnosticsViewModel), while healthy
curves still render normally.

This is the deterministic (Layer A/B) half of the acceptance; the app-level
survival under the real event loop is proved separately in
``tests/realgui/test_sample_read_error_realgui.py`` (Layer C — a headless direct
call cannot prove "the app doesn't crash", spec §Task 7).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from valisync.core.models import Signal, SignalGroup
from valisync.core.models.load_result import Diagnostic
from valisync.core.models.sample_source import SampleReadError
from valisync.core.session import Session
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


class _FailingSource:
    """A SampleSource whose value read always raises SampleReadError.

    length/is_materialized/nbytes_if_materialized stay trivial so Signal
    construction and the length-invariant check never touch ``array()``
    (they must not materialise the values — only ``sorted_view()`` does).
    """

    is_materialized = False
    length = 3
    nbytes_if_materialized = 0

    def array(self) -> np.ndarray:
        raise SampleReadError("boom")


def _register(session: Session, sig: Signal) -> str:
    """Inject *sig* directly into *session* and return its namespaced key.

    Mirrors the ``_register_signal`` pattern in test_graph_panel_vm.py: bypass
    the loader so a lazy-failing Signal (which no loader would produce) can be
    exercised through the real render path.
    """
    key = session._groups.add(
        SignalGroup(
            signals=(sig,),
            source_path=Path.cwd() / f"{sig.name}.mf4",
            file_format="MDF4",
            loaded_at=datetime.now(),
        )
    )
    return session.group_signals(key)[0].name


def _bad_signal(name: str = "bad") -> Signal:
    return Signal(
        name=name,
        timestamps=np.array([0.0, 1.0, 2.0], dtype=np.float64),
        values_source=_FailingSource(),  # type: ignore[arg-type]
        file_format="MDF4",
        bus_type="",
        source_file="/net/x.mf4",
    )


def _healthy_signal(name: str = "good") -> Signal:
    return Signal(
        name=name,
        timestamps=np.array([0.0, 1.0, 2.0], dtype=np.float64),
        values=np.array([10.0, 20.0, 30.0], dtype=np.float64),
        file_format="MDF4",
        bus_type="",
        source_file="/net/good.mf4",
    )


def _panel_with_sink() -> tuple[GraphPanelVM, str, str, DiagnosticsViewModel]:
    """Build a GraphPanelVM wired to a real DiagnosticsViewModel sink.

    Returns (vm, bad_key, good_key, diagnostics). The panel is pinned to manual
    x/y ranges so ``add_signal`` never auto-fits (auto-fit is a non-render
    trigger covered by the app-level hook, Layer C) — this test isolates the
    render boundary exactly.
    """
    session = Session()
    bad_key = _register(session, _bad_signal())
    good_key = _register(session, _healthy_signal())
    diagnostics = DiagnosticsViewModel()
    vm = GraphPanelVM(
        session,
        diagnostic_sink=lambda source, diag: diagnostics.add(source, [diag]),
    )
    # Pin ranges so add_signal's auto-fit is a no-op (no materialisation).
    vm.set_x_range(0.0, 2.0)
    vm.set_axis_range(0, 0.0, 30.0)
    return vm, bad_key, good_key, diagnostics


def test_render_data_degrades_on_sample_read_error() -> None:
    """render_data() plotting a failing signal returns an empty curve, not a raise."""
    vm, bad_key, _good, _diagnostics = _panel_with_sink()
    vm.add_signal(bad_key)

    curves = vm.render_data()  # MUST NOT raise SampleReadError

    assert len(curves) == 1
    bad_curve = curves[0]
    assert bad_curve.name == bad_key
    assert len(bad_curve.timestamps) == 0
    assert len(bad_curve.values) == 0


def test_render_data_records_exactly_one_diagnostic() -> None:
    """Exactly ONE error diagnostic is recorded for the failing signal."""
    vm, bad_key, _good, diagnostics = _panel_with_sink()
    vm.add_signal(bad_key)

    vm.render_data()

    errors, warnings, infos = diagnostics.counts()
    assert errors == 1, f"expected exactly one error diagnostic, got {errors}"
    assert warnings == 0 and infos == 0
    entry = diagnostics.entries("error")[0]
    assert "bad" in entry.message, (
        f"diagnostic should name the failing signal: {entry.message!r}"
    )


def test_render_data_healthy_signal_still_renders() -> None:
    """A healthy signal on the same panel renders normally (degrade is per-curve)."""
    vm, bad_key, good_key, diagnostics = _panel_with_sink()
    vm.add_signal(good_key)
    vm.add_signal(bad_key)

    curves = vm.render_data()

    by_name = {c.name: c for c in curves}
    assert len(by_name[good_key].timestamps) == 3, "healthy curve should render"
    assert len(by_name[bad_key].timestamps) == 0, "failing curve should be empty"
    assert diagnostics.counts()[0] == 1


def test_render_data_reports_failure_once_across_invalidations() -> None:
    """Re-rendering after a cache invalidation does not duplicate the diagnostic."""
    vm, bad_key, _good, diagnostics = _panel_with_sink()
    vm.add_signal(bad_key)

    vm.render_data()
    vm._invalidate_cache()  # simulate a state change that busts the render cache
    vm.render_data()
    vm._invalidate_cache()
    vm.render_data()

    assert diagnostics.counts()[0] == 1, "diagnostic should be recorded only once"


def test_render_data_no_sink_still_degrades() -> None:
    """Without a sink injected, render still degrades (no raise, empty curve)."""
    session = Session()
    bad_key = _register(session, _bad_signal())
    vm = GraphPanelVM(session)  # no diagnostic_sink
    vm.set_x_range(0.0, 2.0)
    vm.set_axis_range(0, 0.0, 30.0)
    vm.add_signal(bad_key)

    curves = vm.render_data()  # must not raise

    assert len(curves) == 1
    assert len(curves[0].timestamps) == 0


def test_render_data_sink_receives_diagnostic_object() -> None:
    """The sink is called with (source, Diagnostic) — the app's DiagnosticsVM shape."""
    session = Session()
    bad_key = _register(session, _bad_signal())
    received: list[tuple[str, Diagnostic]] = []
    vm = GraphPanelVM(session, diagnostic_sink=lambda s, d: received.append((s, d)))
    vm.set_x_range(0.0, 2.0)
    vm.set_axis_range(0, 0.0, 30.0)
    vm.add_signal(bad_key)

    vm.render_data()

    assert len(received) == 1
    source, diag = received[0]
    assert source == "x.mf4", "source should be the failing signal's file basename"
    assert isinstance(diag, Diagnostic)
    assert diag.level == "error"
    assert "bad" in diag.message
