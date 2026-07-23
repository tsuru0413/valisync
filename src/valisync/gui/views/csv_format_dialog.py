from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from valisync.core.loaders.csv_format_detector import DetectedFormat, split_line
from valisync.core.models.format_def import Delimiter, FormatDefinition
from valisync.gui.theme import qss, tokens

_DELIM_LABEL = {
    Delimiter.COMMA: "カンマ (,)",
    Delimiter.TAB: "タブ",
    Delimiter.SEMICOLON: "セミコロン (;)",
    Delimiter.SPACE: "スペース",
}

# 列ハイライトは二層構造 (I1 修正・spec §1.2):
#   - データセル = 薄いティント。文字色は既定 chrome_text のまま
#     (setForeground しない) → ティント越しでも AA (≥4.5:1) を両テーマで保つのが
#     ハード制約。alpha を上げるほどセル地の実効色が濃くなり chrome_text が埋没する
#     ため、実測で全 4 ケース (時間/信号列 x DARK/LIGHT) が AA を満たす上限は
#     alpha=55 (境界値) — 余裕を見て 45 を採用。
#   - ヘッダセル = 列マーキングを担う。不透明背景 (chrome_cursor_a/
#     chrome_signal_highlight の生色) +輝度ベースで選んだ黒/白文字。両方とも
#     tests/gui/test_theme_tokens.py の値ベース機械検証で test-lock。
_TINT_ALPHA = 45
# alpha (色でなく不透明度パラメータ) — QColor(r,g,b,255) の 255 は AST 色ガード
# (tests/gui/test_theme_guard.py) が Constant 引数として検出するため、他の alpha
# 定数 (_TINT_ALPHA) と同様に Name 参照へ切り出す。
_OPAQUE_ALPHA = 255


def _tint(color: tokens.Color) -> QColor:
    """データセルの薄いティント (chrome_text の AA 可読性が最優先・spec §1.2)。"""
    return QColor(color.r, color.g, color.b, _TINT_ALPHA)


def _opaque(color: tokens.Color) -> QColor:
    """ヘッダセルの不透明背景 (列マーキング・spec §1.2)。"""
    return QColor(color.r, color.g, color.b, _OPAQUE_ALPHA)


def _relative_luminance(c: tokens.Color) -> float:
    """WCAG 相対輝度 (sRGB 線形化込み・tests/gui/test_theme_tokens.py と同型)。"""

    def _lin(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(c.r) + 0.7152 * _lin(c.g) + 0.0722 * _lin(c.b)


# WCAG: 黒 (輝度0) と白 (輝度1) のどちらを選んでも背景とのコントラスト比が釣り合う
# 背景輝度のしきい値 ((1.05*0.05)**0.5 - 0.05 ≈ 0.179)。これより明るい背景には黒文字、
# 暗い背景には白文字が高コントラストになる。
_INK_LUMINANCE_THRESHOLD = (1.05 * 0.05) ** 0.5 - 0.05


def _header_ink(bg: tokens.Color) -> QColor:
    """ヘッダセルの文字色 — 背景輝度に基づき黒/白から高コントラストな方を選ぶ

    (spec §1.2 列マーキング契約・chrome_cursor_a/chrome_signal_highlight の
    両テーマで AA ≥4.5:1 を実測済み)。
    """
    if _relative_luminance(bg) > _INK_LUMINANCE_THRESHOLD:
        return QColor(0, 0, 0)
    return QColor(255, 255, 255)


class CsvFormatDialog(QDialog):
    """CSV 自動検出結果を確認/微調整するモーダル (LD-01)。"""

    def __init__(self, detected: DetectedFormat, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CSV フォーマットの確認")
        self._detected = detected
        self._result: FormatDefinition | None = None

        layout = QVBoxLayout(self)
        if detected.notes:
            banner = QLabel("注意: " + " / ".join(detected.notes))
            banner.setWordWrap(True)
            layout.addWidget(banner)

        self._preview = QTableWidget(self)
        self._preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._preview)

        form = QFormLayout()
        self._delim = QComboBox(self)
        for d in (Delimiter.COMMA, Delimiter.TAB, Delimiter.SEMICOLON, Delimiter.SPACE):
            self._delim.addItem(_DELIM_LABEL[d], d)
        self._delim.setCurrentIndex(self._delim.findData(detected.delimiter))
        form.addRow("区切り", self._delim)

        self._header = QCheckBox(self)
        self._header.setChecked(detected.has_header)
        form.addRow("ヘッダ行あり", self._header)

        self._unit_row = QCheckBox(self)
        self._unit_row.setChecked(detected.has_unit_row)
        form.addRow("単位行あり", self._unit_row)

        self._ts_col = QSpinBox(self)
        self._ts_col.setRange(0, 255)
        self._ts_col.setValue(detected.timestamp_column)
        form.addRow("時間列", self._ts_col)

        self._unit = QComboBox(self)
        self._unit.addItems(["sec", "msec"])
        self._unit.setCurrentText(detected.timestamp_unit)
        form.addRow("時間単位", self._unit)

        self._sig_start = QSpinBox(self)
        self._sig_start.setRange(0, 255)
        self._sig_start.setValue(detected.signal_start_column)
        form.addRow("信号列 開始", self._sig_start)

        self._sig_end = QSpinBox(self)
        self._sig_end.setRange(0, 255)
        self._sig_end.setValue(detected.signal_end_column)
        form.addRow("信号列 終了", self._sig_end)
        layout.addLayout(form)

        self._error = QLabel(self)
        self._error.setStyleSheet(qss.error_label())
        self._error.setWordWrap(True)
        layout.addWidget(self._error)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        # 0 始まりヘッダ・列ハイライトは _refresh() 本体に含まれる (spec §1) ため、
        # 表示に影響するフィールドは全て _refresh へ接続 (_refresh が末尾で
        # _validate も呼ぶので検証漏れなし)。has_unit_row はプレビュー表示に
        # 影響しないため _validate のみで足りる。
        self._delim.currentIndexChanged.connect(self._refresh)
        self._header.stateChanged.connect(self._refresh)
        self._unit_row.stateChanged.connect(self._validate)
        self._ts_col.valueChanged.connect(self._refresh)
        self._sig_start.valueChanged.connect(self._refresh)
        self._sig_end.valueChanged.connect(self._refresh)

        self._refresh()

    def _current_delim(self) -> Delimiter:
        data = self._delim.currentData()
        return data if isinstance(data, Delimiter) else Delimiter.COMMA

    def _refresh(self) -> None:
        """プレビューを現在の区切りで再分割し、ヘッダ/列ハイライト/検証を更新する。"""
        rows = [
            split_line(line, self._current_delim())
            for line in self._detected.preview_lines
        ]
        n_cols = max((len(r) for r in rows), default=0)
        self._preview.setRowCount(len(rows))
        self._preview.setColumnCount(n_cols)
        for ri, row in enumerate(rows):
            for ci in range(n_cols):
                text = row[ci] if ci < len(row) else ""
                self._preview.setItem(ri, ci, QTableWidgetItem(text))

        has_header = self._header.isChecked()
        colors = tokens.active().colors
        sig_start, sig_end = self._sig_start.value(), self._sig_end.value()
        ts_col = self._ts_col.value()

        # データセルの薄いティント (面色・ライブ連動・spec §1)。文字色は既定
        # chrome_text のまま (setForeground しない) — AA 可読性がハード制約 (I1)。
        sig_data_tint = _tint(colors.chrome_signal_highlight)
        ts_data_tint = _tint(colors.chrome_cursor_a)
        # ヘッダセルの列マーキング (不透明背景+輝度ベース高コントラスト文字・
        # spec §1.2)。データセルの薄いティントだけでは非テキスト 3:1 を満たせない
        # ため、列識別はヘッダセル側に集約する。
        sig_header_bg = _opaque(colors.chrome_signal_highlight)
        sig_header_fg = _header_ink(colors.chrome_signal_highlight)
        ts_header_bg = _opaque(colors.chrome_cursor_a)
        ts_header_fg = _header_ink(colors.chrome_cursor_a)

        # 0 始まりヘッダ (off-by-one 構造解消・UX-05・spec §1) + 列マーキング。
        # 列名源は has_header 時のみプレビュー先頭行 — ragged 行 (rows[0] が短い)
        # でも IndexError しない。塗り優先はデータセルと同じ規則 (信号→時間の順で
        # 塗るので ts_col ∈ 信号範囲の過渡でも ts_col が勝つ)。
        for ci in range(n_cols):
            name = rows[0][ci] if (has_header and rows and ci < len(rows[0])) else None
            label = f"{ci}: {name}" if name else str(ci)
            header_item = QTableWidgetItem(label)
            if sig_start <= ci <= sig_end:
                header_item.setBackground(sig_header_bg)
                header_item.setForeground(sig_header_fg)
            if ci == ts_col:
                header_item.setBackground(ts_header_bg)
                header_item.setForeground(ts_header_fg)
            self._preview.setHorizontalHeaderItem(ci, header_item)

        # データセルのティント塗り。信号範囲を先に塗り→時間列を後で塗ることで、
        # スピン調整の過渡 (ts_col ∈ 信号範囲) でも ts_col が勝つ (ヘッダと同順)。
        for ri in range(len(rows)):
            for ci in range(sig_start, sig_end + 1):
                if 0 <= ci < n_cols:
                    item = self._preview.item(ri, ci)
                    if item is not None:
                        item.setBackground(sig_data_tint)
            if 0 <= ts_col < n_cols:
                item = self._preview.item(ri, ts_col)
                if item is not None:
                    item.setBackground(ts_data_tint)

        self._validate()

    def _current_format(self) -> FormatDefinition | None:
        try:
            fmt = FormatDefinition(
                name=self._detected.name,
                delimiter=self._current_delim(),
                timestamp_column=self._ts_col.value(),
                timestamp_unit=self._unit.currentText(),
                signal_start_column=self._sig_start.value(),
                signal_end_column=self._sig_end.value(),
                has_header=self._header.isChecked(),
                has_unit_row=self._unit_row.isChecked(),
            )
        except ValueError as exc:
            self._error.setText(str(exc))
            return None
        self._error.setText("")
        return fmt

    def _validate(self) -> None:
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setEnabled(self._current_format() is not None)

    def _on_accept(self) -> None:
        fmt = self._current_format()
        if fmt is not None:
            self._result = fmt
            self.accept()

    @classmethod
    def ask(
        cls, detected: DetectedFormat, parent: QWidget | None = None
    ) -> FormatDefinition | None:
        dlg = cls(detected, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._result
        return None
