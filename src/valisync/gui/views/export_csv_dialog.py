"""ExportCsvDialog - selected signals を CSV へ書き出すモーダル (SH-03).

CsvFormatDialog.ask を前例に、ファイル別の信号ツリー(初期チェック=プロット中)・
フィルタ・すべて/なし・統合タイムライン切替・CSV 形式(区切り/小数/単位行/精度)・
保存先を集め、ExportRequest を返す。実 export は呼び出し側がオフスレッドで行う。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from valisync.core.export.csv_exporter import CsvExportOptions
from valisync.core.models import Signal

if TYPE_CHECKING:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

# ラベル -> 実文字。タブ/スペースは表示名と実文字が異なる。
_DELIMS: tuple[tuple[str, str], ...] = (
    ("カンマ (,)", ","),
    ("セミコロン (;)", ";"),
    ("タブ", "\t"),
    ("スペース", " "),
)
_DECIMALS: tuple[tuple[str, str], ...] = (("ピリオド (.)", "."), ("カンマ (,)", ","))


@dataclass(frozen=True)
class ExportRequest:
    """ExportCsvDialog が返す確定要求。"""

    signals: list[Signal]
    output_path: Path
    use_unified_timeline: bool
    options: CsvExportOptions


class ExportCsvDialog(QDialog):
    def __init__(
        self,
        app_vm: AppViewModel,
        initial_selected: set[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CSV エクスポート")
        self._app_vm = app_vm
        self._result: ExportRequest | None = None
        # 保存先取得フック(テストで差し替え可能)。空文字はキャンセル。
        self._save_path_provider: Callable[[], str] = self._default_save_path

        layout = QVBoxLayout(self)

        # フィルタ
        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText("信号名でフィルタ…")
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        # 信号ツリー(ファイル別・チェックボックス)
        self._tree = QTreeWidget(self)
        self._tree.setObjectName("export_tree")
        self._tree.setHeaderHidden(True)
        self._sig_by_key: dict[str, Signal] = {}
        for key in app_vm.loaded_file_keys:
            top = QTreeWidgetItem(self._tree, [app_vm.session.source_name(key)])
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            for sig in app_vm.session.group_signals(key):
                child = QTreeWidgetItem(top, [sig.name])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                state = (
                    Qt.CheckState.Checked
                    if sig.name in initial_selected
                    else Qt.CheckState.Unchecked
                )
                child.setCheckState(0, state)
                child.setData(0, Qt.ItemDataRole.UserRole, sig.name)
                self._sig_by_key[sig.name] = sig
        self._tree.expandAll()
        self._tree.itemChanged.connect(lambda *_: self._validate())
        layout.addWidget(self._tree)

        # すべて/なし
        btn_row = QHBoxLayout()
        all_btn = QPushButton("すべて選択")
        all_btn.clicked.connect(self._select_all)
        none_btn = QPushButton("選択なし")
        none_btn.clicked.connect(self._select_none)
        btn_row.addWidget(all_btn)
        btn_row.addWidget(none_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # 形式オプション
        form = QFormLayout()
        self._unified = QCheckBox(self)
        # 既定 ON (安全側): 共有信号では union が同一 timestamps ゆえ出力バイト
        # 不変。マルチレート信号(独立ラスタ)では unified だけが安全な経路
        # (whole-branch review Important #1)。
        self._unified.setChecked(True)
        form.addRow("統合タイムライン", self._unified)
        self._delim = QComboBox(self)
        for label, ch in _DELIMS:
            self._delim.addItem(label, ch)
        form.addRow("区切り", self._delim)
        self._decimal = QComboBox(self)
        for label, ch in _DECIMALS:
            self._decimal.addItem(label, ch)
        form.addRow("小数点", self._decimal)
        self._unit_row = QCheckBox(self)
        form.addRow("単位行を出力", self._unit_row)
        self._round_trip = QCheckBox("ラウンドトリップ(無指定)", self)
        self._round_trip.setChecked(True)
        form.addRow("精度", self._round_trip)
        self._precision = QSpinBox(self)
        self._precision.setRange(0, 15)
        self._precision.setValue(6)
        self._precision.setEnabled(False)
        form.addRow("小数桁", self._precision)
        layout.addLayout(form)

        self._round_trip.toggled.connect(lambda on: self._precision.setEnabled(not on))
        self._delim.currentIndexChanged.connect(self._validate)
        self._decimal.currentIndexChanged.connect(self._validate)

        self._error = QLabel(self)
        self._error.setStyleSheet("color: #c0392b;")
        self._error.setWordWrap(True)
        layout.addWidget(self._error)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "エクスポート…"
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._validate()

    # --- 選択 ---------------------------------------------------------
    def _iter_children(self) -> Iterator[QTreeWidgetItem]:
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            assert top is not None
            for j in range(top.childCount()):
                child = top.child(j)
                assert child is not None
                yield child

    def _checked_keys(self) -> list[str]:
        return [
            c.data(0, Qt.ItemDataRole.UserRole)
            for c in self._iter_children()
            if c.checkState(0) == Qt.CheckState.Checked
        ]

    def _select_all(self) -> None:
        for c in self._iter_children():
            c.setCheckState(0, Qt.CheckState.Checked)

    def _select_none(self) -> None:
        for c in self._iter_children():
            c.setCheckState(0, Qt.CheckState.Unchecked)

    def _apply_filter(self, text: str) -> None:
        t = text.strip().lower()
        for c in self._iter_children():
            key = c.data(0, Qt.ItemDataRole.UserRole)
            c.setHidden(bool(t) and t not in key.lower())

    # --- 形式 ---------------------------------------------------------
    def _set_delimiter(self, ch: str) -> None:
        self._delim.setCurrentIndex(self._delim.findData(ch))

    def _set_decimal(self, ch: str) -> None:
        self._decimal.setCurrentIndex(self._decimal.findData(ch))

    def _current_options(self) -> CsvExportOptions | None:
        precision = None if self._round_trip.isChecked() else self._precision.value()
        try:
            return CsvExportOptions(
                delimiter=self._delim.currentData(),
                decimal=self._decimal.currentData(),
                unit_row=self._unit_row.isChecked(),
                precision=precision,
            )
        except ValueError as exc:
            self._error.setText(str(exc))
            return None

    def _validate(self) -> None:
        opts = self._current_options()
        has_sel = bool(self._checked_keys())
        if opts is not None:
            self._error.setText("" if has_sel else "少なくとも1信号を選択してください")
        ok = opts is not None and has_sel
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    # --- 確定 ---------------------------------------------------------
    def _default_save_path(self) -> str:
        from PySide6.QtWidgets import QFileDialog

        path, _sel = QFileDialog.getSaveFileName(
            self, "CSV の保存先", "", "CSV (*.csv);;すべてのファイル (*)"
        )
        return path

    def _on_accept(self) -> None:
        opts = self._current_options()
        keys = self._checked_keys()
        if opts is None or not keys:
            return
        path = self._save_path_provider()
        if not path:
            return  # 保存ダイアログをキャンセル
        self._result = ExportRequest(
            signals=[self._sig_by_key[k] for k in keys],
            output_path=Path(path),
            use_unified_timeline=self._unified.isChecked(),
            options=opts,
        )
        self.accept()

    @classmethod
    def ask(
        cls,
        app_vm: AppViewModel,
        initial_selected: set[str],
        parent: QWidget | None = None,
    ) -> ExportRequest | None:
        dlg = cls(app_vm, initial_selected, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._result
        return None
