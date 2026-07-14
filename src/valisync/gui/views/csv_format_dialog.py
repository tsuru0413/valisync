from __future__ import annotations

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
from valisync.gui.theme import qss

_DELIM_LABEL = {
    Delimiter.COMMA: "カンマ (,)",
    Delimiter.TAB: "タブ",
    Delimiter.SEMICOLON: "セミコロン (;)",
    Delimiter.SPACE: "スペース",
}


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

        self._delim.currentIndexChanged.connect(self._refresh)
        self._header.stateChanged.connect(self._validate)
        self._unit_row.stateChanged.connect(self._validate)
        self._ts_col.valueChanged.connect(self._validate)
        self._sig_start.valueChanged.connect(self._validate)
        self._sig_end.valueChanged.connect(self._validate)

        self._refresh()

    def _current_delim(self) -> Delimiter:
        data = self._delim.currentData()
        return data if isinstance(data, Delimiter) else Delimiter.COMMA

    def _refresh(self) -> None:
        """プレビューを現在の区切りで再分割し、検証を更新する。"""
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
