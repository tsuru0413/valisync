"""Property-based tests for the Formula engine.

Property 15: Common-interval correctness — a derived signal's timestamps lie
             within the intersection of every referenced signal's time range.
Property 16: Derived_Signal conforms to the Signal data model (finite, strictly
             increasing timestamps; length match). The Calcbar half lives in
             test_pbt_calcbar.py.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.formula import FormulaEngine
from valisync.core.models import Signal

from .conftest import valid_signals

pytestmark = pytest.mark.property

_NAMES = ["a", "b", "c"]
_OPS = ["+", "-", "*", "/"]


def _draw_signal_set(data: st.DrawFn, n: int) -> dict[str, Signal]:
    return {
        name: data.draw(valid_signals(allow_nan_values=False)) for name in _NAMES[:n]
    }


@given(
    n=st.integers(min_value=1, max_value=3), op=st.sampled_from(_OPS), data=st.data()
)
def test_result_timestamps_within_common_interval(
    n: int, op: str, data: st.DrawFn
) -> None:
    signals = _draw_signal_set(data, n)
    refs = list(signals)
    expr = f" {op} ".join(refs)

    result = FormulaEngine().evaluate(expr, signals)

    if len(result.timestamps) == 0:
        # ranges did not overlap → empty derived signal is the correct outcome
        return
    t_start = max(signals[r].timestamps[0] for r in refs)
    t_end = min(signals[r].timestamps[-1] for r in refs)
    assert result.timestamps[0] >= t_start
    assert result.timestamps[-1] <= t_end


@given(
    n=st.integers(min_value=1, max_value=3), op=st.sampled_from(_OPS), data=st.data()
)
def test_derived_signal_conforms_to_model(n: int, op: str, data: st.DrawFn) -> None:
    signals = _draw_signal_set(data, n)
    expr = f" {op} ".join(signals)

    result = FormulaEngine().evaluate(expr, signals)

    assert result.file_format == "Derived"
    assert len(result.timestamps) == len(result.values)
    if len(result.timestamps) > 0:
        assert np.all(np.isfinite(result.timestamps))
        assert np.all(np.diff(result.timestamps) > 0)
