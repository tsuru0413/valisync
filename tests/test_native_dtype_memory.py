"""FU-20 E2E: wide uint8 チャンネルの実ロードで値 RAM が native 比例 (float64 の 1/8)。

prod 330k の ~10.8GB→~1.36GB (8x 削減) の CI 可能なプロキシ。展開上限 1024 を
超えると headless では全スキップされるため cols=1000 (<1024) を使う。
"""

from __future__ import annotations

import numpy as np

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.loaders.mdf_loader import MdfLoader


def test_wide_uint8_channel_keeps_native_footprint(tmp_path):
    cols = 1000  # < EXPANSION_COLUMN_LIMIT(1024): 全列がロードされる
    path = write_mdf4_wide_2d(tmp_path, cols=cols)
    result = MdfLoader().load(path)
    wide = [s for s in result.signal_group.signals if s.name.startswith("Wide")]
    assert len(wide) == cols  # 展開された uint8 列

    # 各列は 3 サンプル (write_mdf4_wide_2d の ts は 3 点) の uint8。
    assert all(s.values.dtype == np.uint8 for s in wide)
    native_bytes = sum(s.values.nbytes for s in wide)
    # native: cols * 3 * 1。float64 に膨張していれば *8 になり FAIL。
    assert native_bytes == cols * 3 * 1
