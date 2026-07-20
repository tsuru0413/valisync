"""CursorReadout — 常設ペインのカーソル読み取り表 (R15.2 -> R16/R17 -> readout-pane)。

既存凡例を置き換え、色↔信号名の識別とカーソル補間値を1つの表に集約する。
カーソル表示に連動して可視/不可視を切り替える (呼び出し側が setVisible)。
R16/R17: 時刻ヘッダ・Delta モード (A値/Δy/統計列)・列選択メニューを追加。
readout-pane Task 3: フロートチップ(ドラッグ移動/常時✕)からペイン
(objectName=ReadoutPane・プレースホルダ・行クリック・Δ符号着色) へ進化。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QActionGroup,
    QColor,
    QContextMenuEvent,
    QMouseEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.theme import qss, tokens
from valisync.gui.viewmodels.graph_panel_vm import CursorReading, DeltaReading

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


def _fmt_range(
    lo: float | None, hi: float | None, precision: int = _DEFAULT_PRECISION
) -> str:
    """信号の値域セル (min-max)。値域不明 (None) は空欄 (コンセプト 2a)。"""
    if lo is None or hi is None:
        return ""
    return f"{lo:.{precision}g}–{hi:.{precision}g}"  # noqa: RUF001 EN DASH


class CursorReadout(QWidget):
    """常設ペインのカーソル読み取り表 (readout-pane 増分B Task 3)。

    Global mode: rows [colour swatch | name | A値 | min-max].
    Delta mode: rows [colour swatch | name | A値 | Dy | <selected stats>].
    A time header label sits above the table in both set_global / set_delta modes.
    信号ゼロ/カーソル未設置時は show_placeholder() でテーブルを空にし文言を出す。
    """

    row_activated = Signal(int)  # 行クリック → entry_id (曲線ハイライト用)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ReadoutPane")
        # 素の QWidget サブクラスは子ウィジェットとして QSS background/border を
        # 描かない (Qt 仕様) — ペイン面の実描画にこの属性が必須。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(qss.readout_panel())
        sp = tokens.active().spacing
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*sp.chip_margins)
        outer.setSpacing(sp.chip_vspace)

        # Header row: time-position label.
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(sp.chip_header_hspace)
        self._header = QLabel()
        self._header.setTextFormat(Qt.TextFormat.RichText)
        self._header.hide()
        header_row.addWidget(self._header)
        header_row.addStretch(1)
        outer.addLayout(header_row)

        # Table grid — child of outer VBox, NOT directly of self.
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(sp.chip_grid_hspace)
        self._grid.setVerticalSpacing(sp.chip_grid_vspace)
        outer.addLayout(self._grid)

        # プレースホルダ (信号ゼロ/カーソル未設置時にテーブルの代わりに表示)。
        self._placeholder = QLabel()
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.hide()
        outer.addWidget(self._placeholder)
        self._placeholder_text: str = ""
        # 常設ペインは splitter で縦に引き伸ばされる。末尾 stretch が無いと余剰縦
        # スペースが grid に配分され行が広がり、AlignRight の値セル(top 揃え)と
        # swatch/name(center 揃え)が1行内で縦に割れる。stretch で内容を上部へ詰める。
        outer.addStretch(1)

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
        # 行クリック(行アクティブ化)用: 行 index -> entry_id / Δy 着色 introspection。
        self._row_entry_ids: list[int] = []
        self._dy_cell_styles: list[tuple[int, str]] = []

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
        # Wired by GraphPanelView: 精度メニュー選択 -> vm.set_value_precision(p)。
        self._on_precision: Callable[[int], None] | None = None

    # ── R15 backward-compatible API ────────────────────────────────────────────

    def set_readings(self, readings: list[CursorReading]) -> None:
        """Backward-compatible global readout (no header time, no min-max column)."""
        self._placeholder.hide()
        self._placeholder_text = ""
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
            entry_ids=[r.entry_id for r in readings],
            dy_styles=[None for _ in readings],
        )

    # ── R16/R17 API ────────────────────────────────────────────────────────────

    def set_global(
        self,
        t_a: float,
        readings: list[CursorReading],
        interp_label: str = "",
        precision: int = _DEFAULT_PRECISION,
    ) -> None:
        """Global mode: header = (dot) t_a [ - interp], columns = [swatch|name|A値|min-max]."""
        self._placeholder.hide()
        self._placeholder_text = ""
        self._last_delta = None
        self._precision = precision
        ta_str = _fmt_time(t_a)
        self._header_text = f"● {ta_str}"
        if interp_label:
            self._header_text += f"  ─ {interp_label}"
        self._col_headers = ["A値", "min–max"]  # noqa: RUF001 EN DASH
        header_html = f"{qss.colored_dot(tokens.active().colors.cursor_a)} {ta_str}"
        if interp_label:
            header_html += f"  ─ {interp_label}"
        self._header.setText(header_html)
        self._header.show()
        self._rebuild(
            col_headers=self._col_headers,
            rows=[
                (
                    r.name,
                    r.unit,
                    r.color,
                    [
                        _fmt_labeled(
                            r.value if r.in_range else None, r.label, precision
                        ),
                        _fmt_range(r.range_lo, r.range_hi, precision),
                    ],
                )
                for r in readings
            ],
            entry_ids=[r.entry_id for r in readings],
            dy_styles=[None for _ in readings],
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
        self._placeholder.hide()
        self._placeholder_text = ""
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
        c = tokens.active().colors
        header_html = (
            f"{qss.colored_dot(c.cursor_a)} {ta_str}"
            f"  {qss.colored_dot(c.cursor_b)} {tb_str}"
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
        # Δy 符号着色 (delta_positive/delta_negative)。0/None は既定色 (無着色)。
        dy_styles: list[str | None] = []
        for r in readings:
            if r.dy is None or r.dy == 0:
                dy_styles.append(None)
            else:
                col = c.delta_positive if r.dy > 0 else c.delta_negative
                dy_styles.append(qss.delta_value(col))
        self._rebuild(
            col_headers=self._col_headers,
            rows=rows,
            entry_ids=[r.entry_id for r in readings],
            dy_styles=dy_styles,
        )

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
        Empty cells (e.g. min-max で値域不明) are omitted from the join.
        """
        return list(self._rows)

    def table_tsv(self) -> str:
        """表示中の列・現在精度・単位を反映した TSV を返す (PC-10)。

        1 行目はヘッダ (信号列+データ列見出し。set_readings 経由は列見出しが
        空なので単一の 値 列)。以降は各行 表示名(単位込み) + 各セル。_row_cells は
        _rebuild 時点の表示整形済みデータ (精度・単位が既に反映済み)。
        """
        data_headers = self._col_headers if self._col_headers else ["値"]
        lines = ["\t".join(["信号", *data_headers])]
        for disp_name, cells in self._row_cells:
            lines.append("\t".join([disp_name, *cells]))
        return "\n".join(lines)

    def show_placeholder(self, text: str) -> None:
        """テーブルを空にしプレースホルダ文言を出す (信号ゼロ/カーソル未設置)。"""
        self._placeholder_text = text
        self._last_delta = None
        self._header.hide()
        self._header_text = ""
        self._col_headers = []
        self._full_rebuild([], [], (tuple(), tuple()), [], [])  # グリッドを空に
        self._placeholder.setText(text)
        self._placeholder.show()

    def placeholder_text(self) -> str:
        """現在のプレースホルダ文言 (test introspection)。"""
        return self._placeholder_text

    def dy_cell_styles(self) -> list[tuple[int, str]]:
        """Δy 着色済みの (row_index, style_str) のみ (test introspection)。"""
        return list(self._dy_cell_styles)

    def activate_row(self, row: int) -> None:
        """行 index を entry_id へ解決し row_activated を発火する。

        名前ラベル/行クリック(mousePressEvent)からも、テストの直接呼び出し
        からも同じ経路を通る (プログラム的トリガ)。
        """
        if 0 <= row < len(self._row_entry_ids):
            self.row_activated.emit(self._row_entry_ids[row])

    def _row_at(self, pos: QPoint) -> int | None:
        """クリック位置 (self 座標系) から行 index を求める (先頭値セルの geometry)。"""
        for i, vlabels in enumerate(self._value_labels):
            if not vlabels:
                continue
            rect = vlabels[0].geometry()
            if rect.top() <= pos.y() <= rect.bottom():
                return i
        return None

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

    def build_readout_menu(self) -> QMenu:
        """readout 右クリックメニュー: 統計列 ▸ / 精度 ▸ / 表をコピー / カーソルを消す。"""
        menu = QMenu(self)
        stat_sub = self.build_column_menu()
        stat_sub.setTitle("統計列")
        menu.addMenu(stat_sub)

        prec_sub = menu.addMenu("精度")
        group = QActionGroup(prec_sub)
        group.setExclusive(True)
        for p in (4, 6, 8):
            act = prec_sub.addAction(str(p))
            act.setCheckable(True)
            act.setActionGroup(group)
            act.setChecked(p == self._precision)  # BEFORE triggered.connect
            act.triggered.connect(lambda *_, val=p: self._emit_precision(val))

        menu.addAction("表をコピー", self._copy_table)
        menu.addAction("カーソルを消す", self._clear_cursors)
        return menu

    def _emit_precision(self, p: int) -> None:
        if self._on_precision is not None:
            self._on_precision(p)

    def _copy_table(self) -> None:
        QApplication.clipboard().setText(self.table_tsv())

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.build_readout_menu().exec(event.globalPos())

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
        entry_ids: list[int],
        dy_styles: list[str | None],
    ) -> None:
        """構造不変なら差分更新、構造が変わったら全再構築(RN-06)。"""
        sig = (
            tuple(col_headers),
            tuple((name, unit, len(cells)) for name, unit, _color, cells in rows),
        )
        if sig == self._layout_sig and len(rows) == len(self._value_labels):
            self._update_in_place(rows, entry_ids, dy_styles)
        else:
            self._full_rebuild(col_headers, rows, sig, entry_ids, dy_styles)

    def _full_rebuild(
        self,
        col_headers: list[str],
        rows: list[tuple[str, str, str, list[str]]],
        sig: tuple[tuple[str, ...], tuple[tuple[str, str, int], ...]],
        entry_ids: list[int],
        dy_styles: list[str | None],
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
        self._row_entry_ids = []
        self._dy_cell_styles = []
        dy_col = col_headers.index("Δy") if "Δy" in col_headers else None
        r0 = 0
        if col_headers:
            # 列見出し — swatch(col0)・name(col1) の上は空白、データ列(col2+) に col_headers を配置
            for c, head in enumerate(["", "", *col_headers]):
                lbl = QLabel(head)
                lbl.setStyleSheet(qss.readout_small_label())
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
                name_lbl.setText(f"{name} {qss.unit_span(unit)}")
            else:
                name_lbl.setText(name)
            self._grid.addWidget(name_lbl, r0 + i, 1)
            vlabels: list[QLabel] = []
            for c, text in enumerate(cells):
                v = QLabel(text)
                v.setAlignment(Qt.AlignmentFlag.AlignRight)
                style = dy_styles[i] if i < len(dy_styles) else None
                if dy_col is not None and c == dy_col and style:
                    v.setStyleSheet(style)
                self._grid.addWidget(v, r0 + i, 2 + c)
                vlabels.append(v)
            self._value_labels.append(vlabels)
            self._swatch_labels.append(swatch)
            self._row_colors.append(color)
            disp_name = f"{name} [{unit}]" if unit else name
            self._rows.append((disp_name, " ".join(cell for cell in cells if cell)))
            self._row_cells.append((disp_name, list(cells)))
            self._row_entry_ids.append(entry_ids[i] if i < len(entry_ids) else 0)
            dy_style = dy_styles[i] if i < len(dy_styles) else None
            if dy_col is not None and dy_style:
                self._dy_cell_styles.append((i, dy_style))
        self._layout_sig = sig
        # updateGeometry (adjustSize でない): splitter 管理下でペインを sizeHint へ
        # 強制 resize すると次のレイアウトで splitter が再展開し、カーソル移動ごとに
        # 崩れ→正常のちらつきが出る。updateGeometry は sizeHint 変化を通知するのみ。
        self.updateGeometry()

    def _update_in_place(
        self,
        rows: list[tuple[str, str, str, list[str]]],
        entry_ids: list[int],
        dy_styles: list[str | None],
    ) -> None:
        """既存 QLabel を setText で差分更新(色変化時のみ swatch を差し替え)。"""
        dy_col = self._col_headers.index("Δy") if "Δy" in self._col_headers else None
        self._dy_cell_styles = []
        for i, (name, unit, color, cells) in enumerate(rows):
            dy_style = dy_styles[i] if i < len(dy_styles) else None
            for c, text in enumerate(cells):
                label = self._value_labels[i][c]
                label.setText(text)
                if dy_col is not None and c == dy_col:
                    label.setStyleSheet(dy_style or "")
            if self._row_colors[i] != color:
                pix = QPixmap(10, 10)
                pix.fill(QColor(color))
                self._swatch_labels[i].setPixmap(pix)
                self._row_colors[i] = color
            disp_name = f"{name} [{unit}]" if unit else name
            self._rows[i] = (disp_name, " ".join(cell for cell in cells if cell))
            self._row_cells[i] = (disp_name, list(cells))
            if i < len(entry_ids):
                self._row_entry_ids[i] = entry_ids[i]
            if dy_col is not None and dy_style:
                self._dy_cell_styles.append((i, dy_style))
        self.updateGeometry()  # adjustSize でない (ちらつき回避・_full_rebuild 参照)

    # ── Row click → activate (entry_id ハイライト) ─────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            row = self._row_at(event.position().toPoint())
            if row is not None:
                self.activate_row(row)
        super().mousePressEvent(event)
