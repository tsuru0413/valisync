from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from valisync.core.downsampler.downsampler import Downsampler
from valisync.core.export.csv_exporter import CsvExporter, CsvExportOptions
from valisync.core.formula.engine import FormulaEngine
from valisync.core.interpolation.interpolator import InterpolationMethod, Interpolator
from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.loaders.mdf_loader import (
    ConfirmExpansion,
    ExpansionRequest,
    MdfLoader,
    OversizedChannel,
)
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR, SignalGroupManager
from valisync.core.models import FormatDefinition, Signal
from valisync.core.models.load_result import Diagnostic, LoadCancelled
from valisync.core.statistics.range_stats import RangeStatistics, StatisticsResult
from valisync.core.sync.synchronizer import TimeSynchronizer

__all__ = [
    "ConfirmExpansion",
    "ExpansionRequest",
    "LoadCancelled",
    "LoadError",
    "LoadManyResult",
    "LoadOutcome",
    "OversizedChannel",
    "RemovalResult",
    "Session",
    "SourceInfo",
]


class LoadError(Exception):
    """Raised when a single-file load fails; carries the loader diagnostics."""

    def __init__(
        self,
        file_path: Path,
        messages: list[str],
        diagnostics: tuple[Diagnostic, ...] = (),
    ) -> None:
        self.file_path = file_path
        self.messages = messages
        self.diagnostics = tuple(diagnostics)
        super().__init__(f"failed to load {file_path}: {'; '.join(messages)}")


@dataclass(frozen=True)
class LoadOutcome:
    """Result of a successful single-file load: group key + loader diagnostics.

    ``diagnostics`` surfaces non-fatal issues (skipped channels, dropped enum
    labels, 0-channel files) that the GUI shows in the Diagnostics dock (FB-02).
    """

    key: str
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class LoadManyResult:
    """Outcome of a batch load: ``succeeded`` is a tuple of ``LoadOutcome`` (Req 5.4)."""

    succeeded: tuple[LoadOutcome, ...] = ()
    failed: tuple[tuple[Path, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class RemovalResult:
    """Outcome of a remove_group request (Req 4.5).

    ``removed`` is False when dependent Derived_Signals exist and removal was not
    forced; ``dependent_signals`` then names the blocking Derived_Signals.
    """

    removed: bool
    dependent_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceInfo:
    """Read-only metadata of a loaded file for GUI surfaces (FB-10 tooltip).

    ``size_bytes`` is None when the file no longer exists on disk;
    ``t_min``/``t_max`` are None for 0-channel groups.
    """

    full_path: Path
    size_bytes: int | None
    t_min: float | None
    t_max: float | None
    n_channels: int
    file_format: str


@dataclass(frozen=True)
class _DerivedRecord:
    """A Derived_Signal and the namespaced input signal names it depends on."""

    name: str
    input_names: frozenset[str] = field(default_factory=frozenset)


class Session:
    """Orchestration layer. The single gateway between the GUI and core modules.

    Coordinates loaders, synchronizer, formula engine, interpolation, statistics,
    downsampler and export, and manages loaded Signal_Groups by key.
    """

    def __init__(self) -> None:
        self._groups = SignalGroupManager()
        self._csv_loader = CsvLoader()
        self._mdf_loader = MdfLoader()
        self._formula = FormulaEngine()
        self._synchronizer = TimeSynchronizer()
        self._interpolator = Interpolator()
        self._statistics = RangeStatistics()
        self._downsampler = Downsampler()
        self._exporter = CsvExporter()
        self._derived: list[_DerivedRecord] = []

    def load(
        self,
        file_path: Path,
        format_def: FormatDefinition | None = None,
        cancel: Callable[[], bool] | None = None,
        confirm_expansion: ConfirmExpansion | None = None,
    ) -> LoadOutcome:
        """Load a file and return the group key plus any loader diagnostics.

        Dispatches to the CSV or MDF4 loader by file type. Raises LoadError when
        the loader reports failure. ``cancel`` is a cooperative callback the
        loader polls at checkpoints; when it returns True the loader raises
        LoadCancelled and no group is registered (FB-04 — user-initiated, not
        an error). ``confirm_expansion`` は多次元チャンネルの展開列数が上限を
        超えるとき MDF4 ローダーから呼ばれ、展開するチャンネルの選択を返す
        コールバック (LD-14・CSV では無視)。
        """
        file_path = Path(file_path)
        if self._csv_loader.supports(file_path):
            if format_def is None:
                raise ValueError("CSV files require a FormatDefinition")
            result = self._csv_loader.load(file_path, format_def, cancel=cancel)
        elif self._mdf_loader.supports(file_path):
            result = self._mdf_loader.load(
                file_path, cancel=cancel, confirm_expansion=confirm_expansion
            )
        else:
            raise ValueError(f"no loader supports file: {file_path}")

        if result.signal_group is None:
            messages = [d.message for d in result.diagnostics]
            raise LoadError(file_path, messages, diagnostics=result.diagnostics)
        key = self._groups.add(result.signal_group)
        return LoadOutcome(key=key, diagnostics=result.diagnostics)

    def is_csv(self, file_path: Path) -> bool:
        """*file_path* が CSV ローダー対象かを返す (GUI の開く経路分岐用・LD-01)。"""
        return self._csv_loader.supports(Path(file_path))

    def load_many(
        self, specs: list[tuple[Path, FormatDefinition | None]]
    ) -> LoadManyResult:
        """Load several files, keeping successes available and reporting failures.

        A failure on one file never aborts the batch (Req 5.4): each successful
        load is registered, each failure is reported with its diagnostics.
        """
        succeeded: list[LoadOutcome] = []
        failed: list[tuple[Path, tuple[str, ...]]] = []
        for file_path, format_def in specs:
            try:
                succeeded.append(self.load(file_path, format_def))
            except LoadError as exc:
                failed.append((Path(file_path), tuple(exc.messages)))
            except ValueError as exc:
                failed.append((Path(file_path), (str(exc),)))
        return LoadManyResult(succeeded=tuple(succeeded), failed=tuple(failed))

    def signals(self) -> list[Signal]:
        """Every loaded signal, name-spaced by its group key."""
        return self._groups.signals()

    def signal_map(self) -> Mapping[str, Signal]:
        """Read-only ``{namespaced_name: Signal}`` view over all loaded signals.

        Cached at the SignalGroupManager level and rebuilt only on load/unload
        (FU-08) — callers on the autofit hot path avoid re-walking every signal.
        """
        return self._groups.signal_map()

    def group_keys(self) -> list[str]:
        """Keys of all loaded groups, in insertion order.

        Delegates to SignalGroupManager.keys. Lets callers test whether a
        namespaced signal_key's group is still loaded without walking every
        signal (FU-16: prune reconciliation avoids forcing a namespaced
        rebuild at prod scale).
        """
        return self._groups.keys

    def source_name(self, key: str) -> str:
        """Original source filename (basename) for the group under ``key``.

        Public recovery point so the GUI never reaches into Session internals
        to display a file's name. Raises KeyError for an unknown key.
        """
        return self._groups.source_name(key)

    def group_signals(self, key: str) -> list[Signal]:
        """Namespaced signals for a single loaded file (KeyError if unknown).

        Lets callers fetch one file's signals without scanning every group.
        """
        return self._groups.group_signals(key)

    def source_info(self, key: str) -> SourceInfo:
        """Return read-only metadata for the group under *key* (KeyError if unknown)."""
        group = self._groups.group(key)
        try:
            size: int | None = group.source_path.stat().st_size
        except OSError:
            size = None  # moved/deleted after load — show what we still know
        t_mins = [s.sorted_view()[0][0] for s in group.signals if len(s.timestamps)]
        t_maxs = [s.sorted_view()[0][-1] for s in group.signals if len(s.timestamps)]
        return SourceInfo(
            full_path=group.source_path,
            size_bytes=size,
            t_min=min(t_mins) if t_mins else None,
            t_max=max(t_maxs) if t_maxs else None,
            n_channels=len(group.signals),
            file_format=group.file_format,
        )

    def evaluate_formula(
        self,
        expression: str,
        inputs: dict[str, Signal],
        max_depth: int = 100,
    ) -> Signal:
        """Evaluate a Formula and register the resulting Derived_Signal.

        Dependency tracking records the namespaced input signal names so that
        remove_group can detect Derived_Signals that would be orphaned (Req 4.5).
        """
        derived = self._formula.evaluate(expression, inputs, max_depth=max_depth)
        self._derived.append(
            _DerivedRecord(name=derived.name, input_names=frozenset(inputs.keys()))
        )
        return derived

    def remove_group(self, key: str, force: bool = False) -> RemovalResult:
        """Remove a Signal_Group, guarding Derived_Signals that depend on it.

        When a Derived_Signal references any signal in the group and ``force`` is
        False, removal is refused and the dependents are reported (Req 4.5).
        """
        prefix = f"{key}{KEY_SEPARATOR}"
        dependents = tuple(
            rec.name
            for rec in self._derived
            if any(name.startswith(prefix) for name in rec.input_names)
        )
        if dependents and not force:
            return RemovalResult(removed=False, dependent_signals=dependents)

        self._groups.remove(key)
        return RemovalResult(removed=True, dependent_signals=dependents)

    # ─── Pure-computation pass-throughs (Session is the only gateway) ──────────

    def apply_offset(
        self, signal: Signal, file_offset: float = 0.0, signal_offset: float = 0.0
    ) -> Signal:
        return self._synchronizer.apply_offset(signal, file_offset, signal_offset)

    def interpolate(
        self,
        signal: Signal,
        t: float,
        method: InterpolationMethod = InterpolationMethod.LINEAR,
    ) -> float | None:
        return self._interpolator.interpolate(signal, t, method)

    def compute_statistics(
        self, signal: Signal, t_start: float, t_end: float
    ) -> StatisticsResult:
        return self._statistics.compute(signal, t_start, t_end)

    def downsample(self, signal: Signal, n: int) -> Signal:
        return self._downsampler.downsample(signal, n)

    def export_csv(
        self,
        signals: list[Signal],
        output_path: Path,
        use_unified_timeline: bool = False,
        options: CsvExportOptions | None = None,
    ) -> None:
        self._exporter.export(signals, output_path, use_unified_timeline, options)

    def unified_timeline_signals(
        self,
        file_offsets: dict[str, float] | None = None,
        signal_offsets: dict[str, float] | None = None,
    ) -> list[Signal]:
        """Place every loaded signal on the Unified_Timeline (Req 8.1, 8.3).

        Applies a per-file offset (keyed by group key) and a per-signal offset
        (keyed by namespaced signal name) to each signal. No reordering or
        resampling is done, so inter-signal relative order is preserved (8.3) and
        sample counts are unchanged (8.4).
        """
        file_offsets = file_offsets or {}
        signal_offsets = signal_offsets or {}
        placed: list[Signal] = []
        for sig in self._groups.signals():
            key = sig.name.split(KEY_SEPARATOR, 1)[0]
            placed.append(
                self._synchronizer.apply_offset(
                    sig,
                    file_offset=file_offsets.get(key, 0.0),
                    signal_offset=signal_offsets.get(sig.name, 0.0),
                )
            )
        return placed

    # ─── Calcbar operations (Req 26 / 15) ─────────────────────────────────────

    def moving_average(self, signal: Signal, window: int) -> Signal:
        """Simple moving average with a shrinking head window (Req 26.1)."""
        t, v = self._require_min_samples(signal, "moving_average")
        n = len(v)
        if not (1 <= window <= n):
            raise ValueError(f"window must be in 1..{n} (signal length), got {window}")
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            start = max(0, i - window + 1)
            out[i] = v[start : i + 1].mean()
        return self._derive(signal, f"sma({signal.name})", out, t)

    def linear_regression(self, signal: Signal) -> Signal:
        """Least-squares line evaluated on the (sorted) input timestamps (Req 26.2)."""
        t, v = self._require_min_samples(signal, "linear_regression")
        slope, intercept = np.polyfit(t, v, 1)
        return self._derive(signal, f"linreg({signal.name})", slope * t + intercept, t)

    def differentiate(self, signal: Signal) -> Signal:
        """Numerical derivative: central difference, one-sided at ends (Req 26.3)."""
        t, v = self._require_min_samples(signal, "differentiate")
        d = np.empty(len(v), dtype=np.float64)
        d[1:-1] = (v[2:] - v[:-2]) / (t[2:] - t[:-2])
        d[0] = (v[1] - v[0]) / (t[1] - t[0])
        d[-1] = (v[-1] - v[-2]) / (t[-1] - t[-2])
        return self._derive(signal, f"diff({signal.name})", d, t)

    def integrate(self, signal: Signal) -> Signal:
        """Cumulative trapezoidal integral, starting at 0.0 (Req 26.4)."""
        t, v = self._require_min_samples(signal, "integrate")
        segments = (v[1:] + v[:-1]) / 2.0 * (t[1:] - t[:-1])
        cumulative = np.concatenate([[0.0], np.cumsum(segments)])
        return self._derive(signal, f"integ({signal.name})", cumulative, t)

    @staticmethod
    def _require_min_samples(signal: Signal, op: str) -> tuple[np.ndarray, np.ndarray]:
        """Return the sorted (timestamps, values), raising if fewer than 2 samples (Req 26.7).

        The "≥2 samples" check is against the aligned axis: non-monotonic
        input is dedup'd (keep-last) by sorted_view first, so the count that
        matters is the aligned length, not the raw (possibly duplicate-laden)
        input length.
        """
        t, v = signal.sorted_view()
        if len(v) < 2:
            raise ValueError(f"{op} requires at least 2 samples, got {len(v)}")
        return t, v

    def _derive(
        self, source: Signal, name: str, values: np.ndarray, timestamps: np.ndarray
    ) -> Signal:
        """Build a Derived_Signal on the sorted axis its values were computed on (Req 26.5).

        *timestamps* is expected to already be the aligned (sorted, dedup'd)
        axis returned by ``_require_min_samples`` — Derived_Signals always
        carry a strictly-increasing axis regardless of the source's ordering.
        """
        return Signal(
            name=name,
            timestamps=timestamps,
            values=values,
            file_format="Derived",
            bus_type="",
            source_file="",
            metadata={},
        )
