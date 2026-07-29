"""Guard: the lazy loader must not retain a whole raw record block per group.

**This is the regression guard for the +1,099 MB ``get_master`` retention.**

The lazy loader keeps the ``MDF`` handle open after ``load()`` so values can be
read on demand. Under that condition ``mdf.get_master(gi)`` is a trap: asammdf
caches the group's ENTIRE raw record block on the open handle to serve the
master, and that cache is never released while the handle lives. Measured on
``demo_data/prod_demo.mf4`` (1.36 GB, 264k signals, 5 virtual groups) with the
handle kept open:

===================================================  ======  ============
approach                                             time    RSS retained
===================================================  ======  ============
``get_master(gi)`` per group (the regression)        1.31 s  **+1,296 MB**
``select([entry])[0].timestamps`` per group (fixed)  0.56 s  **+197 MB**
===================================================  ======  ============

The masters themselves total 0.20 MB — the other ~1.1 GB is pure raw-block
cache. ``select`` streams fragments and retains nothing, so the fix reads the
master through it instead.

Opt-in (slow, needs the 1.36 GB prod demo and psutil, neither in CI)::

    VALISYNC_MEMTEST=1 uv run --with psutil pytest \
        tests/core/loaders/test_mdf_loader_master_retention.py -q
"""

from __future__ import annotations

import gc
import os
from pathlib import Path

import pytest

from valisync.core.loaders.mdf_loader import MdfLoader

PROD_DEMO = Path("demo_data/prod_demo.mf4")

# Generous headroom over the measured ~197 MB fixed-path retention: well under
# the 1,296 MB regression, so the test is decisive without being flaky.
RETENTION_LIMIT_MB = 900.0

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("VALISYNC_MEMTEST"),
        reason="slow memory guard; set VALISYNC_MEMTEST=1 to run",
    ),
    pytest.mark.skipif(
        not PROD_DEMO.exists(),
        reason="prod_demo.mf4 not generated (scripts/generate_demo_mf4.py)",
    ),
]


def test_load_does_not_retain_raw_record_blocks() -> None:
    """RSS retained by a completed lazy ``load()`` stays far below the regression.

    Measures process RSS around ``MdfLoader().load()`` while the resulting
    ``SignalGroup`` (and therefore the open MDF handle) is still alive — that
    is exactly the state in which ``get_master`` leaked 1,296 MB. Nothing is
    materialized here, so a large retained RSS can only be raw-block cache.
    """
    psutil = pytest.importorskip("psutil")
    proc = psutil.Process()
    mb = 1024 * 1024

    gc.collect()
    before = proc.memory_info().rss / mb

    result = MdfLoader().load(PROD_DEMO)
    signal_group = result.signal_group
    assert signal_group is not None
    assert len(signal_group.signals) > 0
    # The leak only exists while the handle is open — assert we are measuring
    # that state, not a post-close one.
    assert signal_group.handle is not None and signal_group.handle.is_closed is False
    # No values were read: retained RSS is loader overhead only.
    assert all(s._values_source.is_materialized is False for s in signal_group.signals)

    gc.collect()
    retained = proc.memory_info().rss / mb - before

    try:
        assert retained < RETENTION_LIMIT_MB, (
            f"lazy load retained {retained:,.0f} MB (limit {RETENTION_LIMIT_MB:,.0f} MB)"
            " — a raw record block is being cached on the open MDF handle"
        )
    finally:
        signal_group.handle.close()
