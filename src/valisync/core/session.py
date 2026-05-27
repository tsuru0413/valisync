from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from valisync.core.downsampler.downsampler import Downsampler
from valisync.core.export.csv_exporter import CsvExporter
from valisync.core.formula.engine import FormulaEngine
from valisync.core.interpolation.interpolator import InterpolationMethod, Interpolator
from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.loaders.mdf4_loader import Mdf4Loader
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR, SignalGroupManager
from valisync.core.models import FormatDefinition, Signal
from valisync.core.statistics.range_stats import RangeStatistics, StatisticsResult
from valisync.core.sync.synchronizer import TimeSynchronizer


class LoadError(Exception):
    """Raised when a single-file load fails; carries the loader diagnostics."""

    def __init__(self, file_path: Path, messages: list[str]) -> None:
        self.file_path = file_path
        self.messages = messages
        super().__init__(f"failed to load {file_path}: {'; '.join(messages)}")


@dataclass(frozen=True)
class LoadManyResult:
    """Outcome of a batch load: keys of successes and per-file failures (Req 5.4)."""

    succeeded: tuple[str, ...] = ()
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
        self._mdf4_loader = Mdf4Loader()
        self._formula = FormulaEngine()
        self._synchronizer = TimeSynchronizer()
        self._interpolator = Interpolator()
        self._statistics = RangeStatistics()
        self._downsampler = Downsampler()
        self._exporter = CsvExporter()
        self._derived: list[_DerivedRecord] = []

    def load(self, file_path: Path, format_def: FormatDefinition | None = None) -> str:
        """Load a file and return the key of the registered Signal_Group.

        Dispatches to the CSV or MDF4 loader by file type. Raises LoadError when
        the loader reports failure.
        """
        file_path = Path(file_path)
        if self._csv_loader.supports(file_path):
            if format_def is None:
                raise ValueError("CSV files require a FormatDefinition")
            result = self._csv_loader.load(file_path, format_def)
        elif self._mdf4_loader.supports(file_path):
            result = self._mdf4_loader.load(file_path)
        else:
            raise ValueError(f"no loader supports file: {file_path}")

        if result.signal_group is None:
            messages = [d.message for d in result.diagnostics]
            raise LoadError(file_path, messages)
        return self._groups.add(result.signal_group)

    def load_many(
        self, specs: list[tuple[Path, FormatDefinition | None]]
    ) -> LoadManyResult:
        """Load several files, keeping successes available and reporting failures.

        A failure on one file never aborts the batch (Req 5.4): each successful
        load is registered, each failure is reported with its diagnostics.
        """
        succeeded: list[str] = []
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
    ) -> None:
        self._exporter.export(signals, output_path, use_unified_timeline)

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
        v = self._require_min_samples(signal, "moving_average")
        n = len(v)
        if not (1 <= window <= n):
            raise ValueError(f"window must be in 1..{n} (signal length), got {window}")
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            start = max(0, i - window + 1)
            out[i] = v[start : i + 1].mean()
        return self._derive(signal, f"sma({signal.name})", out)

    def linear_regression(self, signal: Signal) -> Signal:
        """Least-squares line evaluated on the input timestamps (Req 26.2)."""
        v = self._require_min_samples(signal, "linear_regression")
        t = signal.timestamps
        slope, intercept = np.polyfit(t, v, 1)
        predicted = slope * t + intercept
        return self._derive(signal, f"linreg({signal.name})", predicted)

    def differentiate(self, signal: Signal) -> Signal:
        """Numerical derivative: central difference, one-sided at ends (Req 26.3)."""
        v = self._require_min_samples(signal, "differentiate")
        t = signal.timestamps
        d = np.empty(len(v), dtype=np.float64)
        d[1:-1] = (v[2:] - v[:-2]) / (t[2:] - t[:-2])
        d[0] = (v[1] - v[0]) / (t[1] - t[0])
        d[-1] = (v[-1] - v[-2]) / (t[-1] - t[-2])
        return self._derive(signal, f"diff({signal.name})", d)

    def integrate(self, signal: Signal) -> Signal:
        """Cumulative trapezoidal integral, starting at 0.0 (Req 26.4)."""
        v = self._require_min_samples(signal, "integrate")
        t = signal.timestamps
        segments = (v[1:] + v[:-1]) / 2.0 * (t[1:] - t[:-1])
        cumulative = np.concatenate([[0.0], np.cumsum(segments)])
        return self._derive(signal, f"integ({signal.name})", cumulative)

    @staticmethod
    def _require_min_samples(signal: Signal, op: str) -> np.ndarray:
        """Return the values array, raising if fewer than 2 samples (Req 26.7)."""
        v = signal.values
        if len(v) < 2:
            raise ValueError(f"{op} requires at least 2 samples, got {len(v)}")
        return v

    def _derive(self, source: Signal, name: str, values: np.ndarray) -> Signal:
        """Build a Derived_Signal sharing the source timestamps (Req 26.5)."""
        return Signal(
            name=name,
            timestamps=source.timestamps,
            values=values,
            file_format="Derived",
            bus_type="",
            source_file="",
            metadata={},
        )
