"""Property-based test for the MDF4 load path.

Property 6: MDF4 Signal round-trip — for any valid signal data on any protocol
            (CAN / XCP / Ethernet), writing via asammdf and re-reading through
            Mdf4Loader reproduces every timestamp, value and bus type.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from valisync.core.loaders.mdf4_loader import Mdf4Loader

from .conftest import finite_floats, monotonic_timestamps
from .mdf4_helpers import CAN, ETHERNET, NONE, write_mdf4

pytestmark = pytest.mark.property

# (asammdf bus constant, source name, expected Signal.bus_type)
_BUS_CASES = [
    (CAN, "CAN1", "CAN"),
    (ETHERNET, "ETH1", "Ethernet"),
    (NONE, "XCP_daq", "XCP"),  # XCP detected from the source-name heuristic
]


@settings(deadline=None, max_examples=50)
@given(
    ts=monotonic_timestamps(min_size=2, max_size=20),
    n_channels=st.integers(min_value=1, max_value=4),
    data=st.data(),
)
def test_mdf4_signal_roundtrip(
    ts: np.ndarray, n_channels: int, data: st.DrawFn
) -> None:
    channels: list[dict[str, object]] = []
    expected: list[tuple[str, np.ndarray, str]] = []
    for i in range(n_channels):
        vs = data.draw(arrays(np.float64, len(ts), elements=finite_floats))
        bus_const, src_name, bus_str = data.draw(st.sampled_from(_BUS_CASES))
        name = f"ch{i}"
        channels.append(
            {
                "name": name,
                "timestamps": ts,
                "values": vs,
                "bus_type": bus_const,
                "source_name": src_name,
            }
        )
        expected.append((name, vs, bus_str))

    with tempfile.TemporaryDirectory() as d:
        path = write_mdf4(Path(d) / "rt.mf4", channels)
        result = Mdf4Loader().load(path)

    assert result.signal_group is not None
    by_name = {s.name: s for s in result.signal_group.signals}
    for name, vs, bus_str in expected:
        sig = by_name[name]
        np.testing.assert_array_equal(sig.timestamps, ts)
        np.testing.assert_array_equal(sig.values, vs)
        assert sig.bus_type == bus_str
