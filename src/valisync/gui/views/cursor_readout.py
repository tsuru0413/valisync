"""CursorReadout — プロット上にオーバーレイするカーソル読み取り面 (R15.2 -> R16/R17)。

既存凡例を置き換え、色↔信号名の識別とカーソル補間値を1つの表に集約する。
カーソル表示に連動して可視/不可視を切り替える (呼び出し側が setVisible)。
R16/R17: 時刻ヘッダ・Delta モード (A値/Δy/統計列)・列選択メニューを追加。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.viewmodels.graph_panel_vm import CursorReading, DeltaReading
from valisync.gui.views.cursor_shapes import CursorKind, cursor

_OUT_OF_RANGE = "範囲外"
_NO_DATA = "データなし"
_STAT_COLS: tuple[str, ...] = ("mean", "max", "min", "std", "count")


_DEFAULT_PRECISION = 6


def _fmt_value(v: float | None, precision: int = _DEFAULT_PRECISION) -> str:
    return _OUT_OF_RANGE if v is None else f"{v:.{precision}g}"


def _fmt_labeled(
    v: float | None, label: str | None, precision: int = _DEFAULT_PRECISION
) -> str:
    """value_labels 命中時は value (ラベル) 形式で併記する (LD-07)。"""
    base = _fmt_value(v, precision)
    return f"{base} ({label})" if label else base


def _fmt_dy(v: float | None, precision: int = _DEFAULT_PRECISION) -> str:
    if v is None:
        return _OUT_OF_RANGE
    return f"{v:+.{precision}g}"  # 符号付き


def _fmt_time(t: float) -> str:
    return f"{t:.4g} s"  # 時刻は固定精度 (精度切替の対象外・spec 増分3)


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

        # Header row: time-position label (left) + always-visible close X (right).
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        self._header = QLabel()
        self._header.setTextFormat(Qt.TextFormat.RichText)
        self._header.hide()
        header_row.addWidget(self._header)
        header_row.addStretch(1)
        self._close_btn = QToolButton()
        self._close_btn.setText("✕")
        self._close_btn.setToolTip("カーソルを消す")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(
            "QToolButton { color:#cdd6f4; border:none; padding:0 2px; }"
            " QToolButton:hover { color:#f38ba8; }"
        )
        self._close_btn.clicked.connect(self._clear_cursors)
        header_row.addWidget(self._close_btn)
        outer.addLayout(header_row)
        # 表全体は移動可能 (PC-18 移動アフォーダンス)。X ボタンは PointingHand を維持。
        self.setCursor(cursor(CursorKind.MOVE))

        # Table grid — child of outer VBox, NOT directly of self.
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(2)
        outer.addLayout(self._grid)

        self._rows: list[tuple[str, str]] = []
        # TSV エクスポート等の構造化アクセス用 (name [unit] 反映済み, セルはリストのまま)。
        self._row_cells: list[tuple[str, list[str]]] = []
        # 差分更新用: 構造(列見出し+各行 name/unit/セル数)が不変なら QLabel を再利用し
        # setText で値だけ更新する(毎移動の全 deleteLater/再生成を回避・RN-06)。
        self._value_labels: list[list[QLabel]] = []
        self._swatch_labels: list[QLabel] = []
        self._row_colors: list[str] = []
        self._layout_sig: (
            tuple[tuple[str, ...], tuple[tuple[str, str, int], ...]] | None
        ) = None
        self._drag_offset: QPoint | None = (
            None  # for click-drag repositioning within parent
        )
        # ユーザーが readout をドラッグ移動したか。GraphPanelView は True の間は
        # プロット矩形への自動再配置を抑止する(ユーザー配置を尊重・PC-21)。
        self._user_moved: bool = False

        # R16/R17 state
        self._visible_stats: set[str] = set(_STAT_COLS)
        self._col_headers: list[str] = []
        self._header_text: str = ""
        self._last_delta: tuple[float, float, list[DeltaReading], str, int] | None = (
            None
        )
        self._precision: int = _DEFAULT_PRECISION
        # Optional callback wired by GraphPanelView so stat-column toggles update
        # the VM (spec §7: VM is the source of truth for visible_stat_cols).
        # When None, _toggle_stat updates _visible_stats directly (test/legacy path).
        self._on_stat_toggled: Callable[[str, bool], None] | None = None
        # Wired by GraphPanelView: X / メニュー「カーソルを消す」で全消去 (全 A/B/Δ)。
        self._on_clear: Callable[[], None] | None = None

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
                    r.unit,
                    r.color,
                    [_fmt_labeled(r.value if r.in_range else None, r.label)],
                )
                for r in readings
            ],
        )

    # ── R16/R17 API ────────────────────────────────────────────────────────────

    def set_global(
        self,
        t_a: float,
        readings: list[CursorReading],
        interp_label: str = "",
        precision: int = _DEFAULT_PRECISION,
    ) -> None:
        """Global mode: header = (dot) t_a [ - interp], columns = [swatch|name|値]."""
        self._last_delta = None
        self._precision = precision
        ta_str = _fmt_time(t_a)
        self._header_text = f"● {ta_str}"
        if interp_label:
            self._header_text += f"  ─ {interp_label}"
        self._col_headers = []
        header_html = f'<span style="color:#f9e2af">●</span> {ta_str}'
        if interp_label:
            header_html += f"  ─ {interp_label}"
        self._header.setText(header_html)
        self._header.show()
        self._rebuild(
            col_headers=[],
            rows=[
                (
                    r.name,
                    r.unit,
                    r.color,
                    [_fmt_labeled(r.value if r.in_range else None, r.label, precision)],
                )
                for r in readings
            ],
        )

    def set_delta(
        self,
        t_a: float,
        t_b: float,
        readings: list[DeltaReading],
        interp_label: str = "",
        precision: int = _DEFAULT_PRECISION,
    ) -> None:
        """Delta mode: header = (dot) t_a (dot) t_b · Dt [ - interp], columns = A値/Dy/<stats>."""
        self._last_delta = (t_a, t_b, readings, interp_label, precision)
        self._precision = precision
        dt = t_b - t_a
        ta_str = _fmt_time(t_a)
        tb_str = _fmt_time(t_b)
        dt_str = _fmt_time(dt)
        self._header_text = f"● {ta_str}  ● {tb_str} · Δt {dt_str}"
        if interp_label:
            self._header_text += f"  ─ {interp_label}"
        stat_cols = [c for c in _STAT_COLS if c in self._visible_stats]
        self._col_headers = ["A値", "Δy", *stat_cols]
        header_html = (
            f'<span style="color:#f9e2af">●</span> {ta_str}'
            f'  <span style="color:#89b4fa">●</span> {tb_str}'
            f" · <b>Δt {dt_str}</b>"
        )
        if interp_label:
            header_html += f"  ─ {interp_label}"
        self._header.setText(header_html)
        self._header.show()
        rows = []
        for r in readings:
            cells: list[str] = [
                _fmt_labeled(r.value_a if r.in_range else None, r.label, precision),
                _fmt_dy(r.dy, precision),
            ]
            if r.stats.count == 0:
                cells += [_NO_DATA for _ in stat_cols]
            else:
                stat_map: dict[str, str] = {
                    "mean": f"{r.stats.mean:.{precision}g}",
                    "max": f"{r.stats.max:.{precision}g}",
                    "min": f"{r.stats.min:.{precision}g}",
                    "std": f"{r.stats.std:.{precision}g}",
                    "count": str(r.stats.count),  # count は整数のまま
                }
                cells += [stat_map[c] for c in stat_cols]
            rows.append((r.name, r.unit, r.color, cells))
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

    def table_tsv(self) -> str:
        """表示中の列・現在精度・単位を反映した TSV を返す (PC-10)。

        1 行目はヘッダ (信号列+データ列見出し。global モードは列見出しが空なので
        単一の 値 列)。以降は各行 表示名(単位込み) + 各セル。_row_cells は
        _rebuild 時点の表示整形済みデータ (精度・単位が既に反映済み)。
        """
        data_headers = self._col_headers if self._col_headers else ["値"]
        lines = ["\t".join(["信号", *data_headers])]
        for disp_name, cells in self._row_cells:
            lines.append("\t".join([disp_name, *cells]))
        return "\n".join(lines)

    def was_user_moved(self) -> bool:
        """True once the user has drag-repositioned the readout (PC-21)."""
        return self._user_moved

    def reset_user_moved(self) -> None:
        """Clear the user-moved flag so the readout re-anchors to the plot rect."""
        self._user_moved = False

    def close_button(self) -> QToolButton:
        """The always-visible X button (test introspection / realgui target)."""
        return self._close_btn

    def _clear_cursors(self) -> None:
        """X / メニュー「カーソルを消す」→ VM 全消去 (wire 済みのときのみ)。"""
        if self._on_clear is not None:
            self._on_clear()

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
        rows: list[tuple[str, str, str, list[str]]],
    ) -> None:
        """構造不変なら差分更新、構造が変わったら全再構築(RN-06)。"""
        sig = (
            tuple(col_headers),
            tuple((name, unit, len(cells)) for name, unit, _color, cells in rows),
        )
        if sig == self._layout_sig and len(rows) == len(self._value_labels):
            self._update_in_place(rows)
        else:
            self._full_rebuild(col_headers, rows, sig)

    def _full_rebuild(
        self,
        col_headers: list[str],
        rows: list[tuple[str, str, str, list[str]]],
        sig: tuple[tuple[str, ...], tuple[tuple[str, str, int], ...]],
    ) -> None:
        """全 QLabel を破棄・再生成し、差分更新用の参照を記録する。"""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._rows = []
        self._row_cells = []
        self._value_labels = []
        self._swatch_labels = []
        self._row_colors = []
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
        for i, (name, unit, color, cells) in enumerate(rows):
            swatch = QLabel()
            pix = QPixmap(10, 10)
            pix.fill(QColor(color))
            swatch.setPixmap(pix)
            self._grid.addWidget(swatch, r0 + i, 0)
            name_lbl = QLabel()
            if unit:
                name_lbl.setTextFormat(Qt.TextFormat.RichText)
                name_lbl.setText(f'{name} <span style="color:#7f849c">[{unit}]</span>')
            else:
                name_lbl.setText(name)
            self._grid.addWidget(name_lbl, r0 + i, 1)
            vlabels: list[QLabel] = []
            for c, text in enumerate(cells):
                v = QLabel(text)
                v.setAlignment(Qt.AlignmentFlag.AlignRight)
                self._grid.addWidget(v, r0 + i, 2 + c)
                vlabels.append(v)
            self._value_labels.append(vlabels)
            self._swatch_labels.append(swatch)
            self._row_colors.append(color)
            disp_name = f"{name} [{unit}]" if unit else name
            self._rows.append((disp_name, " ".join(cells)))
            self._row_cells.append((disp_name, list(cells)))
        self._layout_sig = sig
        self.adjustSize()

    def _update_in_place(
        self,
        rows: list[tuple[str, str, str, list[str]]],
    ) -> None:
        """既存 QLabel を setText で差分更新(色変化時のみ swatch を差し替え)。"""
        for i, (name, unit, color, cells) in enumerate(rows):
            for c, text in enumerate(cells):
                self._value_labels[i][c].setText(text)
            if self._row_colors[i] != color:
                pix = QPixmap(10, 10)
                pix.fill(QColor(color))
                self._swatch_labels[i].setPixmap(pix)
                self._row_colors[i] = color
            disp_name = f"{name} [{unit}]" if unit else name
            self._rows[i] = (disp_name, " ".join(cells))
            self._row_cells[i] = (disp_name, list(cells))
        self.adjustSize()

    # ── Drag to reposition within the parent plot (R15: フロート表は移動可) ────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(self.pos() + event.position().toPoint() - self._drag_offset)
            self._user_moved = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
