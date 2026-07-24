from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from valisync.core.models.sample_source import EagerValues, SampleSource

if TYPE_CHECKING:
    from valisync.core.statistics.range_stat_index import RangeStatIndex


class Signal:
    """Immutable time-series signal. Values are supplied lazily via a SampleSource.

    ``timestamps`` (グループ master・float64) は即時保持。``values`` は
    ``_values_source`` (EagerValues/LazyMdfValues) の背後で初回アクセス時に展開する。
    インスタンスは書込保護 (公開属性の再代入は AttributeError)。
    """

    __slots__ = (
        "_finite_view_cache",
        "_monotonic",
        "_range_stat_index_cache",
        "_sorted_view_cache",
        "_sorted_view_delegate",
        "_values_source",
        "bus_type",
        "file_format",
        "metadata",
        "name",
        "source_file",
        "timestamps",
    )

    # __slots__ 自体は mypy に型を教えないため、bare 注釈で属性型を宣言する
    # (代入は伴わない — ランタイムの記述子生成は __slots__ タプルのみが担う)。
    name: str
    timestamps: np.ndarray
    file_format: str
    bus_type: str
    source_file: str
    metadata: dict[str, Any]
    _values_source: SampleSource
    _monotonic: bool | None
    _sorted_view_cache: tuple[np.ndarray, np.ndarray] | None
    _finite_view_cache: tuple[np.ndarray, np.ndarray] | None
    _range_stat_index_cache: RangeStatIndex | None
    _sorted_view_delegate: Signal | None

    def __init__(
        self,
        name: str,
        timestamps: np.ndarray,
        file_format: str,
        bus_type: str,
        source_file: str,
        values: np.ndarray | None = None,
        values_source: SampleSource | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if (values is None) == (values_source is None):
            raise ValueError("exactly one of values / values_source must be given")
        # array-imported コンストラクションは EagerValues に包む (既存サイト無変更)
        source: SampleSource = (
            values_source if values_source is not None else EagerValues(values)  # type: ignore[arg-type]
        )
        # 長さ不変条件は values を展開せず source.length で検証する
        if len(timestamps) != source.length:
            raise ValueError(
                f"timestamps ({len(timestamps)}) and values ({source.length}) "
                "must have the same length"
            )
        if len(timestamps) > 0 and not np.all(np.isfinite(timestamps)):
            idx = int(np.argmax(~np.isfinite(timestamps)))
            raise ValueError(f"時刻列の {idx} 番目に非有限値が含まれています")
        ts = timestamps.copy() if timestamps.flags.writeable else timestamps
        ts.flags.writeable = False
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "timestamps", ts)
        object.__setattr__(self, "file_format", file_format)
        object.__setattr__(self, "bus_type", bus_type)
        object.__setattr__(self, "source_file", source_file)
        object.__setattr__(self, "metadata", metadata if metadata is not None else {})
        object.__setattr__(self, "_values_source", source)

    def __setattr__(self, name: str, value: Any) -> None:
        # インスタンス不変 (旧 frozen dataclass 相当)。内部は object.__setattr__ を使う。
        raise AttributeError(f"Signal is immutable; cannot set {name!r}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Signal is immutable; cannot delete {name!r}")

    @property
    def values(self) -> np.ndarray:
        """値配列 (初回アクセスで展開+キャッシュ)。失敗時 SampleReadError."""
        return self._values_source.array()

    def sorted_view(self) -> tuple[np.ndarray, np.ndarray]:
        """Strictly-monotonic float64 view for computation and rendering (spec §4.1).

        Stable-sorts by timestamp and keeps the last-recorded value for equal
        timestamps (CAN "last received wins"). Values are upcast to float64
        here (the single computation boundary), so ``Signal.values`` can be
        stored in its native dtype (FU-20: avoids the 8x float64 inflation of
        wide uint8 array channels) while every consumer still receives float64.
        Timestamps are already float64 and are returned untouched, so
        ``is_monotonic`` (computed independently from the master only) is
        unaffected. Cached after the first call; the computation is
        idempotent, so racing initialisations are harmless — once ``values``
        is I/O-backed (Task 2), the underlying read itself wins-once via
        ``handle.lock``, so a racing recompute here still only re-reads an
        already-materialized array.
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

    def time_range(self) -> tuple[float, float] | None:
        """Raw ``(min, max)`` timestamp without materialising ``sorted_view()``.

        Cheap time-range accessor for metadata surfaces (e.g. ``source_info``).
        Reads the raw timestamps deliberately — NOT ``sorted_view()[0][0]/[-1]``
        — so it never upcasts values to float64 or populates the per-Signal
        cache. That matters at prod scale: ``source_info`` walks every signal
        (264k), and routing that through ``sorted_view`` would re-inflate the
        native dtype 8x and undo FU-20 (FU-18). Timestamps are finite by
        construction (``__post_init__`` guard), so min/max are finite. Returns
        None for an empty signal.
        """
        ts = self.timestamps
        if len(ts) == 0:
            return None
        return (float(ts.min()), float(ts.max()))

    @property
    def is_monotonic(self) -> bool:
        """True when timestamps are strictly increasing (master のみ・値を展開しない)."""
        cached = getattr(self, "_monotonic", None)
        if cached is not None:
            return cached
        ts = self.timestamps
        result = len(ts) < 2 or bool(np.all(np.diff(ts) > 0))
        object.__setattr__(self, "_monotonic", result)
        return result
