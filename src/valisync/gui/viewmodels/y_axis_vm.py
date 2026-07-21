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
        name: str = "",
        y_is_auto: bool = True,
    ) -> None:
        super().__init__()
        self.y_range = y_range
        self.top_ratio = top_ratio
        self.height_ratio = height_ratio
        self.column = column
        self.unit = unit
        # Display name of the representative (first-added) signal on this axis.
        self.name = name
        # Y レンジが「自動フィット追従」か「手動固定」か (X の _x_range_is_auto の
        # per-axis 対称・Stage A 契約 §2.3)。遷移は GraphPanelVM の手動系メソッド側。
        self.y_is_auto = y_is_auto

    def set_range(self, lo: float | None, hi: float | None) -> None:
        """Set the vertical data range for this axis."""
        if lo is not None and hi is not None:
            self.y_range = (lo, hi)
        else:
            self.y_range = None
        self._notify("range")

    def effective_region(self, margin: float = 0.0) -> tuple[float, float]:
        """このリージョンを各辺 *margin* (自身の高さの割合) だけ内側へ寄せた
        ``(top, height)`` を返す。

        どの軸も真のフルハイトにしないことで、境界値データがプロット枠に乗らない
        (FU-12)。高さは**乗算** ``height*(1-2m)`` ── ``height-2m`` は
        ``height < 2*margin`` で負になり仮想スパンが爆発する。margin=0.0 は
        model 比率をそのまま返す (後方互換)。
        """
        eff_top = self.top_ratio + margin * self.height_ratio
        eff_height = max(self.height_ratio * (1.0 - 2.0 * margin), 1e-9)
        return (eff_top, eff_height)

    def calculate_virtual_range(self, margin: float = 0.0) -> tuple[float, float]:
        """Calculate the full ViewBox Y-range to map [y_lo, y_hi] to this region.

        This implements the 'unclipped overlay' mapping. The full ViewBox
        occupies the entire panel; we set its Y-range such that the data range
        [y_min, y_max] corresponds to the vertical strip [top_ratio, top_ratio+height].

        *margin* insets the strip (FU-12): with margin>0 the data band lands
        ``margin`` of the strip's height inside each edge, so boundary-valued
        data never coincides with the plot frame.

        top_ratio is 0.0 at the top of the panel and 1.0 at the bottom.
        Pyqtgraph Y-axis increases upwards (0.0 at bottom).
        """
        y_min, y_max = self.y_range if self.y_range is not None else (0.0, 1.0)
        span = max(y_max - y_min, 1e-9)
        eff_top, eff_height = self.effective_region(margin)

        v_hi = y_max + eff_top * span / eff_height
        v_lo = y_max - (1.0 - eff_top) * span / eff_height

        return (v_lo, v_hi)
