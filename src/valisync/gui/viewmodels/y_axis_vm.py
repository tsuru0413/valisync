from __future__ import annotations

from valisync.gui.viewmodels.observable import Observable


class YAxisVM(Observable):
    """ViewModel for a single Y-axis region.

    Each axis defines a vertical region within a GraphPanel using top_ratio
    and height_ratio (0.0 to 1.0).
    """

    def __init__(
        self,
        y_range: tuple[float, float] | None = None,
        top_ratio: float = 0.0,
        height_ratio: float = 1.0,
        column: int = 0,
        unit: str = "",
    ) -> None:
        super().__init__()
        self.y_range = y_range
        self.top_ratio = top_ratio
        self.height_ratio = height_ratio
        self.column = column
        self.unit = unit

    def set_range(self, lo: float | None, hi: float | None) -> None:
        """Set the vertical data range for this axis."""
        if lo is not None and hi is not None:
            self.y_range = (lo, hi)
        else:
            self.y_range = None
        self._notify("range")

    def calculate_virtual_range(self) -> tuple[float, float]:
        """Calculate the full ViewBox Y-range to map [y_lo, y_hi] to this region.

        This implements the 'unclipped overlay' mapping. The full ViewBox
        occupies the entire panel; we set its Y-range such that the data range
        [y_min, y_max] corresponds to the vertical strip [top_ratio, top_ratio+height].

        top_ratio is 0.0 at the top of the panel and 1.0 at the bottom.
        Pyqtgraph Y-axis increases upwards (0.0 at bottom).
        """
        y_min, y_max = self.y_range if self.y_range is not None else (0.0, 1.0)
        span = max(y_max - y_min, 1e-9)
        h_ratio = max(self.height_ratio, 1e-9)

        # Formula:
        # full_hi = y_hi + top_ratio * span / height_ratio
        # full_lo = y_hi - (1 - top_ratio) * span / height_ratio
        v_hi = y_max + self.top_ratio * span / h_ratio
        v_lo = y_max - (1.0 - self.top_ratio) * span / h_ratio

        return (v_lo, v_hi)
