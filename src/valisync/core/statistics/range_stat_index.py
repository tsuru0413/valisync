"""RangeStatIndex — finite_view 上の平方分割で範囲統計を O(√n) に。

設計 spec §4.2 参照。各ブロックに (count, mean, M2, min, max) を前計算し、任意の
closed range を「左部分スライス ⊎ 完全ブロック群 ⊎ 右部分スライス」に分解、各群の
統計を並列分散マージ(Chan/Welford の多群結合)で厳密結合する。M2 は非負項の和で
表せるためカタストロフィックキャンセルが起きず、np.std(ddof=0) と機械精度で一致する。
"""

from __future__ import annotations

import math

import numpy as np

from valisync.core.statistics.range_stats import StatisticsResult


class RangeStatIndex:
    def __init__(self, ts: np.ndarray, vs: np.ndarray) -> None:
        # ts: finite・狭義昇順(finite_view の保証)。vs: finite float64。
        self._ts = ts
        self._vs = vs
        n = len(vs)
        self._n = n
        # ブロックサイズ = ⌈√n⌉。n=0 でも 1 に丸めて空配列を持つ。
        block = max(1, math.isqrt(n))
        self._block = block
        if n == 0:
            self._b_count = np.empty(0, dtype=np.int64)
            self._b_mean = np.empty(0, dtype=np.float64)
            self._b_m2 = np.empty(0, dtype=np.float64)
            self._b_min = np.empty(0, dtype=np.float64)
            self._b_max = np.empty(0, dtype=np.float64)
            return
        nb = (n + block - 1) // block
        b_count = np.empty(nb, dtype=np.int64)
        b_mean = np.empty(nb, dtype=np.float64)
        b_m2 = np.empty(nb, dtype=np.float64)
        b_min = np.empty(nb, dtype=np.float64)
        b_max = np.empty(nb, dtype=np.float64)
        for bi in range(nb):
            s = bi * block
            e = min(s + block, n)
            seg = vs[s:e]
            m = float(seg.mean())
            b_count[bi] = e - s
            b_mean[bi] = m
            b_m2[bi] = float(((seg - m) ** 2).sum())
            b_min[bi] = float(seg.min())
            b_max[bi] = float(seg.max())
        self._b_count = b_count
        self._b_mean = b_mean
        self._b_m2 = b_m2
        self._b_min = b_min
        self._b_max = b_max

    def query(self, t_start: float, t_end: float) -> StatisticsResult:
        ts = self._ts
        lo = int(np.searchsorted(ts, t_start, side="left"))
        hi = int(np.searchsorted(ts, t_end, side="right"))
        if hi <= lo:
            nan = float("nan")
            return StatisticsResult(mean=nan, max=nan, min=nan, std=nan, count=0)

        # 収集した各群の (count, mean, M2, min, max) を多群結合する。
        counts: list[float] = []
        means: list[float] = []
        m2s: list[float] = []
        mins: list[float] = []
        maxs: list[float] = []

        def add_slice(a: int, b: int) -> None:
            if b <= a:
                return
            seg = self._vs[a:b]
            m = float(seg.mean())
            counts.append(float(b - a))
            means.append(m)
            m2s.append(float(((seg - m) ** 2).sum()))
            mins.append(float(seg.min()))
            maxs.append(float(seg.max()))

        block = self._block
        first_full = (lo + block - 1) // block  # 最初の完全内包ブロック index
        last_full = hi // block  # 最後の完全内包ブロックの次(排他)
        if first_full >= last_full:
            # 完全ブロックなし: 全体を1スライスで走査
            add_slice(lo, hi)
        else:
            left_end = first_full * block
            right_start = last_full * block
            add_slice(lo, left_end)
            # 完全ブロック群を1群にベクトル化結合(命題4の多群形)
            cb = self._b_count[first_full:last_full].astype(np.float64)
            mb = self._b_mean[first_full:last_full]
            m2b = self._b_m2[first_full:last_full]
            c_full = float(cb.sum())
            m_full = float((cb * mb).sum() / c_full)
            m2_full = float(m2b.sum() + (cb * (mb - m_full) ** 2).sum())
            counts.append(c_full)
            means.append(m_full)
            m2s.append(m2_full)
            mins.append(float(self._b_min[first_full:last_full].min()))
            maxs.append(float(self._b_max[first_full:last_full].max()))
            add_slice(right_start, hi)

        # 収集群を多群結合: C=Sum(c), M=Sum(c*mean)/C, M2=Sum(M2_g)+Sum(c_g*(mean_g-M)^2)
        c_arr = np.array(counts, dtype=np.float64)
        m_arr = np.array(means, dtype=np.float64)
        m2_arr = np.array(m2s, dtype=np.float64)
        total_count = float(c_arr.sum())
        total_mean = float((c_arr * m_arr).sum() / total_count)
        total_m2 = float(m2_arr.sum() + (c_arr * (m_arr - total_mean) ** 2).sum())
        var = total_m2 / total_count
        std = math.sqrt(var) if var > 0.0 else 0.0  # 非負項和ゆえ var>=0、負は丸め保険
        return StatisticsResult(
            mean=total_mean,
            max=max(maxs),
            min=min(mins),
            std=std,
            count=round(total_count),
        )
