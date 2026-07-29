"""FU-20 E2E: wide uint8 チャンネルの実ロードで値 RAM が native 比例 (float64 の 1/8)。

prod 330k の ~10.8GB→~1.36GB (8x 削減) の CI 可能なプロキシ。展開上限 1024 を
超えると headless では全スキップされるため cols=1000 (<1024) を使う。
"""

from __future__ import annotations

import numpy as np

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.session import Session


def test_wide_uint8_channel_keeps_native_footprint(tmp_path):
    cols = 1000  # < EXPANSION_COLUMN_LIMIT(1024): 全列が展開対象
    path = write_mdf4_wide_2d(tmp_path, cols=cols)
    session = Session()
    key = session.load(path).key
    # E-3: 列は事前生成されない — 鋳造して値の footprint を測る。
    assert session.column_names_of(key, "Wide") == tuple(
        f"Wide[{i}]" for i in range(cols)
    )
    wide = [session.resolve_signal(f"{key}::Wide[{i}]") for i in range(cols)]
    assert all(s is not None for s in wide)

    # 各列は 3 サンプル (write_mdf4_wide_2d の ts は 3 点) の uint8。
    assert all(s.values.dtype == np.uint8 for s in wide)
    native_bytes = sum(s.values.nbytes for s in wide)
    # native: cols * 3 * 1。float64 に膨張していれば *8 になり FAIL。
    assert native_bytes == cols * 3 * 1
