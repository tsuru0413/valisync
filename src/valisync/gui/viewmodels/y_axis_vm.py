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
        if lo is None and hi is None:
            self.y_range = None
        else:
            self.y_range = (lo, hi)
        self._notify("range")

    def calculate_virtual_range(self) -> tuple[float, float]:
        """Calculate the virtual Y-range for a ViewBox to overlay this axis region.

        If a signal has a real range [Ymin, Ymax] and we want to show it in a
        region starting at `top_ratio` with `height_ratio` (relative to full
        panel height 1.0), we calculate a `virtual_range` [Vmin, Vmax] such
        that when the ViewBox maps [Vmin, Vmax] to [0, PixelHeight], the
        sub-range [Ymin, Ymax] lands exactly in the region
        [top_ratio, top_ratio + height_ratio].

        Math:
        Span = Ymax - Ymin
        VirtualSpan = Span / height_ratio
        Vmin = Ymin - (top_ratio / height_ratio) * Span
        Vmax = Vmin + VirtualSpan
        """
        y_min, y_max = self.y_range if self.y_range is not None else (0.0, 1.0)
        span = y_max - y_min

        # Avoid division by zero if height_ratio is somehow 0
        h_ratio = max(self.height_ratio, 1e-9)

        virtual_span = span / h_ratio
        v_min = y_min - (self.top_ratio / h_ratio) * span
        v_max = v_min + virtual_span

        return (v_min, v_max)
