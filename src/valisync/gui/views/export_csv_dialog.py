"""ExportCsvDialog - selected signals を CSV へ書き出すモーダル (SH-03).

CsvFormatDialog.ask を前例に、ファイル別の信号ツリー(初期チェック=プロット中)・
フィルタ・すべて/なし・統合タイムライン切替・CSV 形式(区切り/小数/単位行/精度)・
保存先を集め、ExportRequest を返す。実 export は呼び出し側がオフスレッドで行う。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
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
    QRadioButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from valisync.core.export.csv_exporter import CsvExportOptions
from valisync.core.models import Signal
from valisync.gui import strings as S
from valisync.gui.display_names import csv_header_names, display_names
from valisync.gui.theme import qss

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
        *,
        x_range: tuple[float, float] | None = None,
        cursor_a: float | None = None,
        cursor_b: float | None = None,
        offset_for: Callable[[str], float] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CSV エクスポート")
        self._app_vm = app_vm
        self._result: ExportRequest | None = None
        # 保存先取得フック(テストで差し替え可能)。空文字はキャンセル。
        self._save_path_provider: Callable[[], str] = self._default_save_path
        # F-0/UX-28: 出力範囲 DI — 呼び出し側 (main_window.export_csv) がダイアログ
        # 表示中不変のスナップショットとして注入する (View 分離・spec §2.3)。
        # ExportCsvDialog 自身は GraphAreaVM/AppViewModel のオフセットを直接読まない。
        self._x_range = x_range
        self._cursor_a = cursor_a
        self._cursor_b = cursor_b
        # I2 fix (task-3-review.md #1): unlike x_range/cursor_a/cursor_b above,
        # offset activity is NOT a static open-time snapshot — offsets are
        # app-global (spec §2.1) and the tree below lists every loaded file's
        # signals, not just the initial (plotted) selection, so a signal added
        # to the checked set in-dialog can carry an offset the initial snapshot
        # never saw. offset_for is a live resolver (main_window passes
        # GraphPanelVM.offset_for, which answers for ANY namespaced signal key
        # via the app-global signal/file offset dicts) re-evaluated against the
        # CURRENT checked set on every _validate() — see _update_range_radios().
        self._offset_for = offset_for

        layout = QVBoxLayout(self)

        # フィルタ
        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText(S.FILTER_PLACEHOLDER)
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        # 信号ツリー(ファイル別・チェックボックス)
        self._tree = QTreeWidget(self)
        self._tree.setObjectName("export_tree")
        self._tree.setHeaderHidden(True)
        self._sig_by_key: dict[str, Signal] = {}
        # E-0: 葉テキストは裸名(衝突時のみ qualified) — スコープ=ツリーに載る
        # 全信号(全ファイル横断・spec §1.2)。UserRole の選択キー (sig.name) は不変。
        by_file: list[tuple[str, list[Signal]]] = [
            (key, app_vm.session.group_signals(key)) for key in app_vm.loaded_file_keys
        ]
        names = display_names(sig.name for _key, sigs in by_file for sig in sigs)
        for key, sigs in by_file:
            top = QTreeWidgetItem(self._tree, [app_vm.session.source_name(key)])
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            for sig in sigs:
                child = QTreeWidgetItem(top, [names[sig.name]])
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
        none_btn = QPushButton(S.EXPORT_DESELECT_ALL)
        none_btn.clicked.connect(self._select_none)
        btn_row.addWidget(all_btn)
        btn_row.addWidget(none_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # 選択数フッター (F-0/UX-28): 総選択数 (フィルタ非依存・実出力集合と一致)。
        # 初期値は _validate() の相乗り更新で確定するので、ここではプレース
        # ホルダのみ設定する。
        self._selection_label = QLabel(self)
        layout.addWidget(self._selection_label)

        # 形式オプション
        form = QFormLayout()

        # 出力範囲 (F-0/UX-28・spec §2.3): [全期間] 既定 checked。表示由来2ラジオ
        # ([現在の表示範囲]・[カーソル A-B]) の x_range/cursor 側ガードは DI
        # スナップショットに基づく(ダイアログ内の選択変更やフィルタには反応しない
        # ・main_window.export_csv が開く瞬間のスナップショット・spec §2.3)。
        # オフセット側ガードのみ選択集合に対しリアクティブ (I2 fix・spec §2.1) —
        # setEnabled/tooltip の実適用は _update_range_radios() (_validate() から
        # 毎回呼ばれる) に委譲する。
        self._range_all = QRadioButton(S.EXPORT_RANGE_ALL, self)
        self._range_all.setChecked(True)
        self._range_visible = QRadioButton(S.EXPORT_RANGE_VISIBLE, self)
        cursor_label = (
            S.EXPORT_RANGE_CURSOR_TMPL.format(
                lo=min(cursor_a, cursor_b), hi=max(cursor_a, cursor_b)
            )
            if cursor_a is not None and cursor_b is not None
            else S.EXPORT_RANGE_CURSOR
        )
        self._range_cursor = QRadioButton(cursor_label, self)
        range_box = QVBoxLayout()
        range_box.addWidget(self._range_all)
        range_box.addWidget(self._range_visible)
        range_box.addWidget(self._range_cursor)
        form.addRow(S.EXPORT_RANGE_LABEL, range_box)

        self._unified = QCheckBox(self)
        # 既定 ON (安全側): 共有信号では union が同一 timestamps ゆえ出力バイト
        # 不変。マルチレート信号(独立ラスタ)では unified だけが安全な経路
        # (whole-branch review Important #1)。
        self._unified.setChecked(True)
        self._unified.setToolTip(S.EXPORT_UNIFIED_TIMELINE_TOOLTIP)
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
        self._round_trip = QCheckBox(S.EXPORT_ROUND_TRIP_LABEL, self)
        self._round_trip.setChecked(True)
        self._round_trip.setToolTip(S.EXPORT_ROUND_TRIP_TOOLTIP)
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
        self._error.setStyleSheet(qss.error_label())
        self._error.setWordWrap(True)
        layout.addWidget(self._error)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "エクスポート…"
        )
        # Ok が既にカスタム文言のため、対の Cancel も translator 非依存の明示文言に揃える。
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            S.EXPORT_CANCEL
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
        # blockSignals でバッチ化: per-child itemChanged→_validate の O(n) カスケード
        # を避け、完了後に一度だけ再計算する (spec §2.3 M)。
        self._tree.blockSignals(True)
        for c in self._iter_children():
            c.setCheckState(0, Qt.CheckState.Checked)
        self._tree.blockSignals(False)
        self._validate()

    def _select_none(self) -> None:
        self._tree.blockSignals(True)
        for c in self._iter_children():
            c.setCheckState(0, Qt.CheckState.Unchecked)
        self._tree.blockSignals(False)
        self._validate()

    def _apply_filter(self, text: str) -> None:
        # E-0: フィルタは表示テキスト(裸名)照合 — UserRole の raw key ではない
        # (spec §1.2)。leaf の text(0) は生成時に names[sig.name] を格納済み。
        t = text.strip().lower()
        for c in self._iter_children():
            c.setHidden(bool(t) and t not in c.text(0).lower())

    # --- 形式 ---------------------------------------------------------
    def _set_delimiter(self, ch: str) -> None:
        self._delim.setCurrentIndex(self._delim.findData(ch))

    def _set_decimal(self, ch: str) -> None:
        self._decimal.setCurrentIndex(self._decimal.findData(ch))

    def _current_range(self) -> tuple[float | None, float | None]:
        """Selected range radio -> (time_start, time_end) in raw/display seconds.

        [全期間] (or an unavailable radio somehow left checked) -> (None, None).
        Coordinates are the DI snapshot as-is (spec §2.1: no offset applied here
        — offset presence instead disables the two display-derived radios).
        """
        if self._range_visible.isChecked() and self._x_range is not None:
            return self._x_range
        if (
            self._range_cursor.isChecked()
            and self._cursor_a is not None
            and self._cursor_b is not None
        ):
            return min(self._cursor_a, self._cursor_b), max(
                self._cursor_a, self._cursor_b
            )
        return None, None

    def _current_options(self) -> CsvExportOptions | None:
        precision = None if self._round_trip.isChecked() else self._precision.value()
        time_start, time_end = self._current_range()
        try:
            return CsvExportOptions(
                delimiter=self._delim.currentData(),
                decimal=self._decimal.currentData(),
                unit_row=self._unit_row.isChecked(),
                precision=precision,
                time_start=time_start,
                time_end=time_end,
            )
        except ValueError as exc:
            self._error.setText(str(exc))
            return None

    def _offset_active_for_checked(self) -> bool:
        """True iff any *currently checked* signal carries a non-zero offset.

        I2 fix (task-3-review.md #1): reactive over the checked set, not a
        static open-time snapshot — the tree lists every loaded file/signal
        (spec §1.2), and offsets are app-global (spec §2.1), so a signal added
        to the selection in-dialog must be able to (re)trigger this guard.
        ``offset_for is None`` means the caller injected nothing (back-compat
        default) — treated as "no offsets exist" for every key.
        """
        if self._offset_for is None:
            return False
        return any(self._offset_for(k) != 0.0 for k in self._checked_keys())

    def _update_range_radios(self) -> None:
        """Re-apply [現在の表示範囲]/[カーソル A-B] enabled+tooltip state.

        Called from _validate() so every path that can change the checked
        selection (tree itemChanged, すべて選択/解除) re-evaluates the I2
        offset guard against the CURRENT checked set. x_range/cursor_a/
        cursor_b stay the fixed DI snapshot (spec §2.3) — only the offset
        half of the guard is dynamic.
        """
        offset_active = self._offset_active_for_checked()
        self._range_visible.setEnabled(self._x_range is not None and not offset_active)
        self._range_cursor.setEnabled(
            self._cursor_a is not None
            and self._cursor_b is not None
            and not offset_active
        )
        tooltip = S.EXPORT_RANGE_OFFSET_TOOLTIP if offset_active else ""
        self._range_visible.setToolTip(tooltip)
        self._range_cursor.setToolTip(tooltip)
        # A radio that just became disabled must not stay the checked one, or
        # _current_range() would keep reading a now-invalid selection (e.g. the
        # user had [現在の表示範囲] checked, then checked an offset signal).
        stranded = (
            self._range_visible.isChecked() and not self._range_visible.isEnabled()
        ) or (self._range_cursor.isChecked() and not self._range_cursor.isEnabled())
        if stranded:
            self._range_all.setChecked(True)

    def _validate(self) -> None:
        self._update_range_radios()
        opts = self._current_options()
        keys = self._checked_keys()
        has_sel = bool(keys)
        if opts is not None:
            self._error.setText("" if has_sel else S.EXPORT_NO_SELECTION_ERROR)
        ok = opts is not None and has_sel
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        # F-0/UX-28: N = 総選択数 (フィルタ非依存) — _checked_keys() は非表示
        # (フィルタで隠れた) 行も含めて全 UserRole チェック状態を数えるので、
        # 実出力集合 (_on_accept の keys) と常に一致する。
        self._selection_label.setText(S.EXPORT_SELECTION_COUNT_TMPL.format(n=len(keys)))

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
        # E-0: CSV ヘッダ名は選択集合(+ "timestamp" 母集合注入)内の衝突時のみ
        # qualified — core(csv_exporter)は名前を計算せず、渡された名前をそのまま
        # 書くだけ(core→gui import の層違反を作らない・spec §1.2)。
        header_map = csv_header_names(keys)
        opts = replace(opts, header_names=tuple(header_map[k] for k in keys))
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
        *,
        x_range: tuple[float, float] | None = None,
        cursor_a: float | None = None,
        cursor_b: float | None = None,
        offset_for: Callable[[str], float] | None = None,
    ) -> ExportRequest | None:
        dlg = cls(
            app_vm,
            initial_selected,
            parent,
            x_range=x_range,
            cursor_a=cursor_a,
            cursor_b=cursor_b,
            offset_for=offset_for,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._result
        return None
