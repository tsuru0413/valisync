from __future__ import annotations

import numpy as np
import pytest

from valisync.core.models.sample_source import EagerValues, SampleReadError
from valisync.core.models.signal import Signal


def test_eager_values_returns_array_and_is_materialized() -> None:
    arr = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    src = EagerValues(arr)
    assert src.is_materialized is True
    assert src.length == 3
    got = src.array()
    np.testing.assert_array_equal(got, arr)
    assert got.flags.writeable is False  # 凍結される


def test_eager_values_copies_writeable_input_not_freezing_caller_array() -> None:
    # 呼び出し側の可変配列を in-place 凍結してはならない (現行 __post_init__ と同契約)
    caller = np.array([1.0, 2.0], dtype=np.float64)  # writeable
    EagerValues(caller)
    assert caller.flags.writeable is True  # 呼び出し側配列は不変のまま


def test_eager_values_shares_readonly_input_without_copy() -> None:
    ro = np.array([1.0, 2.0], dtype=np.float64)
    ro.flags.writeable = False
    src = EagerValues(ro)
    assert src.array() is ro  # read-only はコピーせず共有


def test_eager_values_nbytes_if_materialized() -> None:
    arr = np.zeros(10, dtype=np.float64)
    assert EagerValues(arr).nbytes_if_materialized == arr.nbytes


def test_sample_read_error_is_exception() -> None:
    assert issubclass(SampleReadError, Exception)


def _sig(values: np.ndarray) -> Signal:
    ts = np.arange(len(values), dtype=np.float64)
    return Signal(
        name="s",
        timestamps=ts,
        values=values,
        file_format="MDF4",
        bus_type="CAN",
        source_file="/x.mf4",
    )


def test_signal_wraps_array_values_in_eager_source() -> None:
    s = _sig(np.array([1.0, 2.0, 3.0]))
    assert isinstance(s._values_source, EagerValues)
    assert s._values_source.is_materialized is True
    np.testing.assert_array_equal(s.values, [1.0, 2.0, 3.0])


def test_signal_accepts_values_source_directly() -> None:
    src = EagerValues(np.array([4.0, 5.0]))
    ts = np.array([0.0, 1.0])
    s = Signal(
        name="s",
        timestamps=ts,
        values_source=src,
        file_format="MDF4",
        bus_type="CAN",
        source_file="/x.mf4",
    )
    assert s._values_source is src
    np.testing.assert_array_equal(s.values, [4.0, 5.0])


def test_signal_length_invariant_uses_source_length_not_values() -> None:
    # timestamps と source.length が食い違えば構築時に ValueError
    ts = np.array([0.0, 1.0, 2.0])
    with pytest.raises(ValueError, match="same length"):
        Signal(
            name="s",
            timestamps=ts,
            values=np.array([1.0, 2.0]),
            file_format="MDF4",
            bus_type="",
            source_file="",
        )


def test_signal_requires_exactly_one_of_values_or_source() -> None:
    ts = np.array([0.0])
    with pytest.raises(ValueError, match="exactly one"):
        Signal(name="s", timestamps=ts, file_format="MDF4", bus_type="", source_file="")


def test_signal_is_instance_write_protected() -> None:
    s = _sig(np.array([1.0]))
    with pytest.raises(AttributeError):
        s.name = "changed"  # type: ignore[misc]


def test_signal_is_monotonic_reads_master_only() -> None:
    s = _sig(np.array([1.0, 2.0, 3.0]))
    assert s.is_monotonic is True
    # values 未展開で is_monotonic が判定できる (EagerValues は常に materialized なので
    # LazyMdfValues 導入後の Task 2 で未展開判定は再検証する)
