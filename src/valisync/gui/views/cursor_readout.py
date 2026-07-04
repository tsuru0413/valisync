"""CursorReadout — プロット上にオーバーレイするカーソル読み取り面 (R15.2 -> R16/R17)。

既存凡例を置き換え、色↔信号名の識別とカーソル補間値を1つの表に集約する。
カーソル表示に連動して可視/不可視を切り替える (呼び出し側が setVisible)。
R16/R17: 時刻ヘッダ・Delta モード (A値/Δy/統計列)・列選択メニューを追加。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QMenu, QVBoxLayout, QWidget

from valisync.gui.viewmodels.graph_panel_vm import CursorReading, DeltaReading

_OUT_OF_RANGE = "範囲外"
_NO_DATA = "データなし"
_STAT_COLS: tuple[str, ...] = ("mean", "max", "min", "std", "count")


def _fmt(v: float | None) -> str:
    return _OUT_OF_RANGE if v is None else f"{v:.4g}"


def _fmt_labeled(v: float | None, label: str | None) -> str:
    """value_labels 命中時は「値 (ラベル)」形式で併記する (LD-07)。"""
    base = _fmt(v)
    return f"{base} ({label})" if label else base


def _fmt_dy(v: float | None) -> str:
    if v is None:
        return _OUT_OF_RANGE
    return f"{v:+.4g}"  # 符号付き


def _fmt_time(t: float) -> str:
    return f"{t:.4g} s"


class CursorReadout(QWidget):
    """Floating per-panel readout table.

    Global mode: rows [colour swatch | name | value].
    Delta mode: rows [colour swatch | name | A値 | Dy | <selected stats>].
    A time header label sits above the table in both set_global / set_delta modes.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CursorReadout")
        # Semi-opaque dark chip so it reads over the waveforms.
        self.setStyleSheet(
            "#CursorReadout { background: rgba(17,17,27,230);"
            " border: 1px solid #45475a; border-radius: 5px; }"
            " QLabel { color: #cdd6f4; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 5, 6, 5)
        outer.setSpacing(3)

        # Visible time-position header (rich text, hidden until set_global/set_delta called).
        self._header = QLabel()
        self._header.setTextFormat(Qt.TextFormat.RichText)
        self._header.hide()
        outer.addWidget(self._header)

        # Table grid — child of outer VBox, NOT directly of self.
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(2)
        outer.addLayout(self._grid)

        self._rows: list[tuple[str, str]] = []
        self._drag_offset: QPoint | None = (
            None  # for click-drag repositioning within parent
        )

        # R16/R17 state
        self._visible_stats: set[str] = set(_STAT_COLS)
        self._col_headers: list[str] = []
        self._header_text: str = ""
        self._last_delta: tuple[float, float, list[DeltaReading]] | None = None
        # Optional callback wired by GraphPanelView so stat-column toggles update
        # the VM (spec §7: VM is the source of truth for visible_stat_cols).
        # When None, _toggle_stat updates _visible_stats directly (test/legacy path).
        self._on_stat_toggled: Callable[[str, bool], None] | None = None

    # ── R15 backward-compatible API ────────────────────────────────────────────

    def set_readings(self, readings: list[CursorReading]) -> None:
        """Backward-compatible global readout (no header time)."""
        # Reset _last_delta so a subsequent _toggle_stat does not wrongly
        # re-render in delta mode (mirrors the pattern already in set_global).
        self._last_delta = None
        self._header.hide()
        self._header_text = ""
        self._col_headers = []
        self._rebuild(
            col_headers=[],
            rows=[
                (
                    r.name,
                    r.color,
                    [_fmt_labeled(r.value if r.in_range else None, r.label)],
                )
                for r in readings
            ],
        )

    # ── R16/R17 API ────────────────────────────────────────────────────────────

    def set_global(self, t_a: float, readings: list[CursorReading]) -> None:
        """Global mode: header = (dot) t_a, columns = [swatch|name|値]."""
        self._last_delta = None
        ta_str = _fmt_time(t_a)
        self._header_text = f"● {ta_str}"
        self._col_headers = []
        self._header.setText(f'<span style="color:#f9e2af">●</span> {ta_str}')
        self._header.show()
        self._rebuild(
            col_headers=[],
            rows=[
                (
                    r.name,
                    r.color,
                    [_fmt_labeled(r.value if r.in_range else None, r.label)],
                )
                for r in readings
            ],
        )

    def set_delta(self, t_a: float, t_b: float, readings: list[DeltaReading]) -> None:
        """Delta mode: header = (dot) t_a (dot) t_b · Dt, columns = A値/Dy/<stats>."""
        self._last_delta = (t_a, t_b, readings)
        dt = t_b - t_a
        ta_str = _fmt_time(t_a)
        tb_str = _fmt_time(t_b)
        dt_str = _fmt_time(dt)
        self._header_text = f"● {ta_str}  ● {tb_str} · Δt {dt_str}"
        stat_cols = [c for c in _STAT_COLS if c in self._visible_stats]
        self._col_headers = ["A値", "Δy", *stat_cols]
        self._header.setText(
            f'<span style="color:#f9e2af">●</span> {ta_str}'
            f'  <span style="color:#89b4fa">●</span> {tb_str}'
            f" · <b>Δt {dt_str}</b>"
        )
        self._header.show()
        rows = []
        for r in readings:
            cells: list[str] = [
                _fmt_labeled(r.value_a if r.in_range else None, r.label),
                _fmt_dy(r.dy),
            ]
            if r.stats.count == 0:
                cells += [_NO_DATA for _ in stat_cols]
            else:
                stat_map: dict[str, str] = {
                    "mean": f"{r.stats.mean:.4g}",
                    "max": f"{r.stats.max:.4g}",
                    "min": f"{r.stats.min:.4g}",
                    "std": f"{r.stats.std:.4g}",
                    "count": str(r.stats.count),
                }
                cells += [stat_map[c] for c in stat_cols]
            rows.append((r.name, r.color, cells))
        self._rebuild(col_headers=self._col_headers, rows=rows)

    # ── Introspection ──────────────────────────────────────────────────────────

    def header_text(self) -> str:
        """Plain-text version of the time header (test introspection)."""
        return self._header_text

    def column_headers(self) -> list[str]:
        """Current data column header labels (test introspection)."""
        return list(self._col_headers)

    def visible_stats(self) -> set[str]:
        """Currently visible stat columns (test introspection)."""
        return set(self._visible_stats)

    def row_texts(self) -> list[tuple[str, str]]:
        """Test introspection: [(name, value_text), ...] in row order.

        In delta mode the second element is all data cells joined by spaces
        (A値, Δy, and any visible stat columns), not just the first value.
        """
        return list(self._rows)

    # ── Column-selection menu ──────────────────────────────────────────────────

    def build_column_menu(self) -> QMenu:
        """Checkable menu (5 stat columns) for the 列▾ button — toggles re-render.

        We use QAction.toggled (reliable bool signal) instead of triggered so the
        slot fires both on user click and on programmatic setChecked() — consistent
        behaviour and works correctly in PySide6 6.x headless tests.
        """
        menu = QMenu(self)
        for c in _STAT_COLS:
            act = menu.addAction(c)
            act.setCheckable(True)
            act.setChecked(c in self._visible_stats)
            # toggled(bool) fires reliably when the checked state changes.
            act.toggled.connect(lambda on, col=c: self._toggle_stat(col, on))
        return menu

    def _toggle_stat(self, col: str, on: bool) -> None:
        if self._on_stat_toggled is not None:
            # VM-wired path: delegate to VM so it notifies 'delta' and the view
            # re-renders via _sync_cursor_from_vm (VM is source of truth).
            self._on_stat_toggled(col, on)
            return
        # Legacy / test path: update local state and re-render directly.
        if on:
            self._visible_stats.add(col)
        else:
            self._visible_stats.discard(col)
        if self._last_delta is not None:
            self.set_delta(*self._last_delta)  # 再描画

    def sync_visible_stats(self, cols: set[str]) -> None:
        """Overwrite local visible-stats from VM state without triggering a re-render.

        Called by GraphPanelView._sync_cursor_from_vm() before set_delta() so that
        the VM's visible_stat_cols (spec §7) governs which stat columns appear.
        """
        self._visible_stats = set(cols)

    # ── Internal grid builder ──────────────────────────────────────────────────

    def _rebuild(
        self,
        col_headers: list[str],
        rows: list[tuple[str, str, list[str]]],
    ) -> None:
        """(Re)build the grid: optional column-header row + one data row per signal."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._rows = []
        r0 = 0
        if col_headers:
            # 列見出し — swatch(col0)・name(col1) の上は空白、データ列(col2+) に col_headers を配置
            for c, head in enumerate(["", "", *col_headers]):
                lbl = QLabel(head)
                lbl.setStyleSheet("color:#7f849c; font-size:9px;")
                lbl.setAlignment(
                    Qt.AlignmentFlag.AlignRight
                    if c >= 2
                    else Qt.AlignmentFlag.AlignLeft
                )
                self._grid.addWidget(lbl, r0, c)
            r0 = 1
        for i, (name, color, cells) in enumerate(rows):
            swatch = QLabel()
            pix = QPixmap(10, 10)
            pix.fill(QColor(color))
            swatch.setPixmap(pix)
            self._grid.addWidget(swatch, r0 + i, 0)
            self._grid.addWidget(QLabel(name), r0 + i, 1)
            for c, text in enumerate(cells):
                v = QLabel(text)
                v.setAlignment(Qt.AlignmentFlag.AlignRight)
                self._grid.addWidget(v, r0 + i, 2 + c)
            self._rows.append((name, " ".join(cells)))
        self.adjustSize()

    # ── Drag to reposition within the parent plot (R15: フロート表は移動可) ────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(self.pos() + event.position().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
