"""Property-based tests for the Downsampler.

Property 21: Output invariants — count ≤ n, timestamps are a strictly-increasing
             subset within the input's time range.
Property 22: Pass-through — when n ≥ sample count the signal is returned intact.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.downsampler import Downsampler
from valisync.core.models import Signal

from .conftest import valid_signals

pytestmark = pytest.mark.property


@given(valid_signals(allow_nan_values=True), st.integers(min_value=2, max_value=500))
def test_downsample_output_invariants(signal: Signal, n: int) -> None:
    result = Downsampler().downsample(signal, n)

    assert len(result.timestamps) <= n
    assert np.all(np.isin(result.timestamps, signal.timestamps))  # subset
    if len(result.timestamps) > 1:
        assert np.all(np.diff(result.timestamps) > 0)  # strictly increasing
    if len(result.timestamps) > 0:
        assert result.timestamps[0] >= signal.timestamps[0]
        assert result.timestamps[-1] <= signal.timestamps[-1]


@given(valid_signals(allow_nan_values=True), st.integers(min_value=0, max_value=10))
def test_downsample_passthrough(signal: Signal, extra: int) -> None:
    n = len(signal.timestamps) + extra  # n ≥ sample count
    result = Downsampler().downsample(signal, n)
    np.testing.assert_array_equal(result.timestamps, signal.timestamps)
    assert np.array_equal(result.values, signal.values, equal_nan=True)
