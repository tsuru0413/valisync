from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from valisync.core.statistics.range_stat_index import RangeStatIndex


@dataclass(frozen=True)
class Signal:
    """Immutable time-series signal. All invariants are enforced at construction time."""

    name: str
    timestamps: (
        np.ndarray
    )  # float64, shape=(n,), all finite; 記録どおり(非単調・重複あり得る)
    values: (
        np.ndarray
    )  # native 数値 dtype, shape=(n,); float64 化は sorted_view()/finite_view() が担う
    file_format: str  # "MDF4" | "CSV" | "Derived"
    bus_type: str  # "CAN" | "XCP" | "Ethernet" | "" (empty for CSV and Derived)
    source_file: str  # absolute path; empty string for Derived signals
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.timestamps) != len(self.values):
            raise ValueError(
                f"timestamps ({len(self.timestamps)}) and values ({len(self.values)}) "
                "must have the same length"
            )
        if len(self.timestamps) > 0 and not np.all(np.isfinite(self.timestamps)):
            idx = int(np.argmax(~np.isfinite(self.timestamps)))
            raise ValueError(f"timestamps contains non-finite value at index {idx}")
        object.__setattr__(
            self,
            "timestamps",
            self.timestamps.copy()
            if self.timestamps.flags.writeable
            else self.timestamps,
        )
        object.__setattr__(
            self,
            "values",
            self.values.copy() if self.values.flags.writeable else self.values,
        )
        self.timestamps.flags.writeable = False
        self.values.flags.writeable = False

    def sorted_view(self) -> tuple[np.ndarray, np.ndarray]:
        """Strictly-monotonic float64 view for computation and rendering (spec §4.1).

        Stable-sorts by timestamp and keeps the last-recorded value for equal
        timestamps (CAN "last received wins"). Values are upcast to float64
        here (the single computation boundary), so ``Signal.values`` can be
        stored in its native dtype (FU-20: avoids the 8x float64 inflation of
        wide uint8 array channels) while every consumer still receives float64.
        Timestamps are already float64 and are returned untouched, so
        ``is_monotonic`` (a timestamp-identity check) is unaffected. Cached
        after the first call; the computation is idempotent, so racing
        initialisations are harmless.
        """
        cache = getattr(self, "_sorted_view_cache", None)
        if cache is not None:
            return cache
        # 配列を共有するラッパー(namespaced コピー)は長寿命の元 Signal に
        # 委譲してキャッシュを共有する — ラッパーが毎回作り直されても
        # 単調性スキャンは元 Signal で1回しか走らない(render ホットパス対策)
        delegate = getattr(self, "_sorted_view_delegate", None)
        if delegate is not None:
            cache = delegate.sorted_view()
            object.__setattr__(self, "_sorted_view_cache", cache)
            return cache
        ts, vs = self.timestamps, self.values
        if len(ts) < 2 or bool(np.all(np.diff(ts) > 0)):
            # 値を float64 へ (既に float64 なら copy=False で無コピー)。
            vs64 = vs.astype(np.float64, copy=False)
            vs64.flags.writeable = False
            cache = (ts, vs64)
        else:
            order = np.argsort(ts, kind="stable")
            ts_s = ts[order]
            vs_s = vs[order]
            # keep-last: 安定ソートで同値 ts は記録順のまま並ぶので、各ランの
            # 末尾(次の ts が大きくなる位置)だけ残せば「最後の記録」が勝つ
            keep = np.concatenate((np.diff(ts_s) > 0, [True]))
            ts_s = ts_s[keep]
            vs_s = vs_s[keep].astype(np.float64, copy=False)
            ts_s.flags.writeable = False
            vs_s.flags.writeable = False
            cache = (ts_s, vs_s)
        object.__setattr__(self, "_sorted_view_cache", cache)
        return cache

    def finite_view(self) -> tuple[np.ndarray, np.ndarray]:
        """Finite-valued view for read-out and statistics (AN-01/02/03).

        Builds on ``sorted_view()`` and drops samples whose *value* is
        non-finite (NaN or +/-Inf), so cursor read-out and range statistics
        operate on real data only. All-finite signals get the sorted arrays
        back untouched (zero-copy). Cached; the computation is idempotent so
        racing initialisations are harmless. Timestamps are already finite by
        load-time guarantee (LD-03), so only values are filtered.
        """
        cache = getattr(self, "_finite_view_cache", None)
        if cache is not None:
            return cache
        # namespaced ラッパーは元 Signal に委譲し、非有限スキャンを元で1回だけ
        # 走らせる (render/カーソルのホットパスで毎回作り直されるラッパー対策)
        delegate = getattr(self, "_sorted_view_delegate", None)
        if delegate is not None:
            cache = delegate.finite_view()
            object.__setattr__(self, "_finite_view_cache", cache)
            return cache
        ts, vs = self.sorted_view()
        if len(vs) == 0 or bool(np.all(np.isfinite(vs))):
            cache = (ts, vs)  # zero-copy fast path
        else:
            mask = np.isfinite(vs)
            ts_f = ts[mask]
            vs_f = vs[mask]
            ts_f.flags.writeable = False
            vs_f.flags.writeable = False
            cache = (ts_f, vs_f)
        object.__setattr__(self, "_finite_view_cache", cache)
        return cache

    def range_stat_index(self) -> RangeStatIndex:
        """Sqrt-decomposition index over finite_view for O(sqrt n) range statistics.

        Built lazily on first query and cached; racing initialisations are
        harmless (idempotent). namespaced ラッパーは finite_view と同じく
        ``_sorted_view_delegate`` 経由で元 Signal のインデックスを共有し、
        カーソルドラッグのホットパスで毎回作り直されるラッパーでも構築は1回。
        """
        cache = getattr(self, "_range_stat_index_cache", None)
        if cache is not None:
            return cache
        # 循環 import 回避のためメソッド内 import(statistics -> models(Signal))。
        from valisync.core.statistics.range_stat_index import RangeStatIndex

        delegate = getattr(self, "_sorted_view_delegate", None)
        if delegate is not None:
            cache = delegate.range_stat_index()
            object.__setattr__(self, "_range_stat_index_cache", cache)
            return cache
        ts, vs = self.finite_view()
        cache = RangeStatIndex(ts, vs)
        object.__setattr__(self, "_range_stat_index_cache", cache)
        return cache

    @property
    def is_monotonic(self) -> bool:
        """True when the sorted view is the raw arrays (zero-copy fast path)."""
        return self.sorted_view()[0] is self.timestamps
