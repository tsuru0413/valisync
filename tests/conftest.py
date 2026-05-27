"""Shared test fixtures and Hypothesis configuration.

Strategies here are the common building blocks for the property-based tests:
``monotonic_timestamps`` (strictly increasing finite float64) and
``valid_signals`` (Signal objects satisfying every data-model invariant).
"""

from __future__ import annotations

import numpy as np
from hypothesis import assume, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from valisync.core.models import Signal

# Default profile: fast feedback during development
settings.register_profile("default", max_examples=200)

# CI profile: more thorough testing
settings.register_profile("ci", max_examples=500)

settings.load_profile("default")


# ─── Float element strategies ────────────────────────────────────────────────

#: Finite float64 within a moderate range — avoids overflow in mean/std/products
#: while still exercising negative values and a wide dynamic range.
finite_floats = st.floats(
    min_value=-1e6,
    max_value=1e6,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)

#: Finite offsets for apply_offset() tests.
finite_offsets = st.floats(
    min_value=-1e5,
    max_value=1e5,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)


def value_elements(allow_nan: bool) -> st.SearchStrategy[float]:
    """Element strategy for a Signal's values array, optionally injecting NaN."""
    if allow_nan:
        return st.one_of(finite_floats, st.just(float("nan")))
    return finite_floats


# ─── Composite strategies ────────────────────────────────────────────────────


@st.composite
def monotonic_timestamps(
    draw: st.DrawFn,
    min_size: int = 2,
    max_size: int = 50,
) -> np.ndarray:
    """Strictly increasing, all-finite float64 timestamp array.

    Built as a start value plus a cumulative sum of strictly positive gaps, so
    monotonicity holds by construction; an ``assume`` guards the rare case where
    float64 rounding would collapse a gap to zero.
    """
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    start = draw(
        st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False)
    )
    gaps = draw(
        st.lists(
            st.floats(
                min_value=1e-2,
                max_value=1e3,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=n - 1,
            max_size=n - 1,
        )
    )
    ts = np.concatenate([[start], start + np.cumsum(gaps)]).astype(np.float64)
    assume(np.all(np.diff(ts) > 0))
    return ts


@st.composite
def valid_signals(
    draw: st.DrawFn,
    min_size: int = 2,
    max_size: int = 50,
    allow_nan_values: bool = False,
) -> Signal:
    """A Signal satisfying all data-model invariants.

    ``file_format="Derived"`` keeps construction independent of loader concerns;
    values may include NaN when ``allow_nan_values`` is set (the data model only
    constrains timestamps, not values).
    """
    ts = draw(monotonic_timestamps(min_size=min_size, max_size=max_size))
    n = len(ts)
    values = draw(arrays(np.float64, n, elements=value_elements(allow_nan_values)))
    name = draw(
        st.text(
            alphabet=st.characters(min_codepoint=97, max_codepoint=122),
            min_size=1,
            max_size=8,
        )
    )
    return Signal(
        name=name,
        timestamps=ts,
        values=values,
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )
