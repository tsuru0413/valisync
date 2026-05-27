from __future__ import annotations

import math

from valisync.core.models import Signal


class TimeSynchronizer:
    """Time synchronization module. Pure computation, no I/O.

    The Unified_Timeline is an emergent property of offset addition, not a
    collection-wide transform. Applying apply_offset() to each Signal is the
    whole of synchronization; orchestrating it across a collection belongs to
    the Session.
    """

    def apply_offset(
        self,
        signal: Signal,
        file_offset: float = 0.0,
        signal_offset: float = 0.0,
    ) -> Signal:
        """Return a new Signal with the combined offset applied to timestamps.

        Both offsets are summed and added to each timestamp. The source Signal
        is never modified. Negative timestamps after offset are valid.

        Raises:
            ValueError: if either offset is NaN or infinite.
        """
        if not math.isfinite(file_offset):
            raise ValueError(f"file_offset must be a finite value, got {file_offset!r}")
        if not math.isfinite(signal_offset):
            raise ValueError(
                f"signal_offset must be a finite value, got {signal_offset!r}"
            )

        total = file_offset + signal_offset
        if total == 0.0:
            return signal

        return Signal(
            name=signal.name,
            timestamps=signal.timestamps + total,
            values=signal.values,
            file_format=signal.file_format,
            bus_type=signal.bus_type,
            source_file=signal.source_file,
            metadata=signal.metadata,
        )
