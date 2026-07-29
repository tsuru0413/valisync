"""遅延サンプルソースのテスト用スタブ (実 mf4 なしで遅延性を検証するため).

``demo_data/*.mf4`` は gitignore で CI に存在しないため、実ファイルに依存する
遅延テストはすべて skip される。遅延ソースの**共有・非展開**という増分の中核
不変条件は CI で守る必要があるので、read をカウントする最小スタブをここに置き
demo-gate なしのテストから使う。
"""

from __future__ import annotations

import numpy as np


class CountingLazy:
    """array() が呼ばれたら記録する遅延 SampleSource スタブ.

    ``reads`` が 0 のままであることが「値を展開していない」の honest observable。
    """

    def __init__(self, n: int) -> None:
        self._n = n
        self.reads = 0
        self._cache: np.ndarray | None = None

    @property
    def is_materialized(self) -> bool:
        return self._cache is not None

    @property
    def length(self) -> int:
        return self._n

    @property
    def nbytes_if_materialized(self) -> int:
        return 0 if self._cache is None else self._cache.nbytes

    def array_if_materialized(self) -> np.ndarray | None:
        return self._cache

    def array(self) -> np.ndarray:
        self.reads += 1
        self._cache = np.zeros(self._n, dtype=np.float64)
        return self._cache
