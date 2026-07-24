from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


class SampleReadError(Exception):
    """遅延サンプル読み取りが I/O 等で失敗したことを表す (アプリは落とさず degrade)."""


@runtime_checkable
class SampleSource(Protocol):
    """Signal の値配列の供給源。EagerValues (即時) と LazyMdfValues (遅延) の共通契約."""

    @property
    def is_materialized(self) -> bool:
        """値配列が既にメモリ上にあるか (mechanism 観測。RSS プロキシではない)."""
        ...

    @property
    def length(self) -> int:
        """サンプル数。値を展開せずに既知 (長さ不変条件の検証に使う)."""
        ...

    @property
    def nbytes_if_materialized(self) -> int:
        """展開済みなら値配列の nbytes、未展開なら 0 (teardown 会計用)."""
        ...

    def array(self) -> np.ndarray:
        """値配列を返す (初回で展開+キャッシュ・read-only 凍結)。失敗時 SampleReadError."""
        ...


def _freeze(array: np.ndarray) -> np.ndarray:
    """現行 Signal.__post_init__ と同一の凍結: writeable ならコピーしてから read-only 化.

    呼び出し側が保持する可変配列を in-place で凍結しない (read-only はそのまま共有)."""
    frozen = array.copy() if array.flags.writeable else array
    frozen.flags.writeable = False
    return frozen


class EagerValues:
    """値配列を即時保持する SampleSource (CSV/Derived/downsampler/offset 前の既定)."""

    __slots__ = ("_array",)

    def __init__(self, array: np.ndarray) -> None:
        self._array = _freeze(array)

    @property
    def is_materialized(self) -> bool:
        return True

    @property
    def length(self) -> int:
        return len(self._array)

    @property
    def nbytes_if_materialized(self) -> int:
        return int(self._array.nbytes)

    def array(self) -> np.ndarray:
        return self._array
