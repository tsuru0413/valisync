"""FileBrowserView — master file list view using QListView.

Binds to FileBrowserVM and FileListModel.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from valisync.gui import strings as S
from valisync.gui.adapters.qt_signal_models import FileListModel
from valisync.gui.views.file_row_spinner import ReleasingSpinnerDelegate

if TYPE_CHECKING:
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM

# gui-memo-ux-cleanup Task 5 (#14 拡張・spec §1.5) 実測で判明: QListView も
# QTreeView と同じ QAbstractScrollArea 経由で sizeHint() が中身非依存の
# QSize(256, 192) 固定値を返す (実測で確認済み)。file_dock と channel_dock は
# 同一カラムに縦積みのため、どちらか一方でもこの既定値が残っていると
# カラムの既定構築幅がそちらに引っ張られて 258px に張り付く — channel 側
# だけを直しても file 側がそのままでは効果が相殺される (Task 5 実測で発覚
# したブロッカー・当初のタスク範囲は channel_browser_view.py のみだったが
# 根本解決のため対で修正)。
#
# Task 5 追調整 (ユーザー決定): 既定構築幅は中間の ~200px にする (181px は
# minimumSizeHint 経由の真の最小幅として維持・ドラッグで到達可能なまま)。
# _ChannelTree と同じ 198 (実測: 198 -> file_dock.width()==200)。
_FILE_LIST_SIZEHINT_WIDTH = 198  # px -- _ChannelTree の同値と揃える


class _FileList(QListView):
    """sizeHint() の width 成分だけを差し替える薄い QListView 派生 (Task 5)。

    channel_browser_view._ChannelTree と同型の修正 -- height は super() の
    まま、width だけ Qt の汎用既定 256px から詰めた値へ差し替える。"""

    def sizeHint(self) -> QSize:
        return QSize(_FILE_LIST_SIZEHINT_WIDTH, super().sizeHint().height())


class FileBrowserView(QWidget):
    """View component for the FileBrowser list.

    Parameters
    ----------
    vm:
        The FileBrowser ViewModel providing the file list and handling selection.
    """

    # E-2b: emitted with the target file's group key when the user picks
    # "基準の同名信号を重ねる". The overlay handler needs the active panel /
    # Session (MainWindow-owned, outside FileBrowserVM's reach), so this view
    # only routes the request — same pattern as ChannelBrowserView's
    # add_to_panel_requested.
    overlay_reference_requested = Signal(str)

    def __init__(
        self,
        vm: FileBrowserVM,
        *,
        confirm_fn: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__()
        self._vm = vm
        self._confirm_fn: Callable[[str], bool] = confirm_fn or self._default_confirm
        self.model = FileListModel(vm, self)

        # UI Setup
        self.list_view = _FileList()
        self.list_view.setModel(self.model)
        # CustomContextMenu so a real right-click on the list emits
        # customContextMenuRequested (handled by _show_context_menu). Overriding
        # contextMenuEvent on this container does not fire reliably from the child
        # item view, so the menu would not appear in the real GUI.
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Spinner animation: advance an angle and repaint releasing rows only.
        self._spin_angle = 0
        self.list_view.setItemDelegate(
            ReleasingSpinnerDelegate(lambda: self._spin_angle, self)
        )
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(80)
        self._spin_timer.timeout.connect(self._advance_spinner)
        self._spin_timer.start()

        self.placeholder_label = QLabel(
            "ファイルが読み込まれていません\n\nウィンドウへファイルをドロップして追加",
            self,
        )
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setWordWrap(True)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.list_view)  # index 0
        self._stack.addWidget(self.placeholder_label)  # index 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        # Connect selection changes to VM
        self.list_view.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        self.list_view.customContextMenuRequested.connect(self._show_context_menu)

        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        unsubscribe = self._vm.subscribe(self._on_vm_change)
        self.destroyed.connect(lambda *_: unsubscribe())
        self._refresh_state()

    def _on_selection_changed(self) -> None:
        """Translate view selection to ViewModel selection."""
        indexes = self.list_view.selectionModel().selectedIndexes()
        if indexes:
            self._vm.select_file(indexes[0].row())
        else:
            self._vm.select_file(-1)

    def build_context_menu(self, row: int) -> QMenu:
        """Menu for list *row*: 'Remove File' + the E-2a/b reference actions.

        The comparison affordances ("基準に設定"/"基準の同名信号を重ねる")
        are gated as a pair on comparison mode (2+ loaded files AND the user
        toggle) — in single mode neither appears, since "基準に設定" would
        be visually inert there (no badge/chip to show for it) while
        "重ねる" alone stayed hidden; showing one without the other read as
        broken (spec 2026-07-23 §3.3 M7). Releasing/out-of-range rows resolve
        no key, so both are skipped regardless of mode. On the reference row
        itself, "基準に設定" is disabled and "基準の同名信号を重ねる" is
        omitted (spec §2/§3).
        """
        menu = QMenu(self)
        menu.addAction(S.ACTION_REMOVE_FILE).triggered.connect(
            lambda *_: self._confirm_and_unload(row)
        )
        key = self._vm.key_at(row)
        if key is not None and self._vm.is_comparison_mode():
            is_ref = self._vm.is_reference(row)
            set_ref_action = menu.addAction(S.ACTION_SET_REFERENCE)
            set_ref_action.setEnabled(not is_ref)
            set_ref_action.triggered.connect(lambda *_: self._vm.set_reference(row))
            if not is_ref:
                overlay_action = menu.addAction(S.ACTION_OVERLAY_REFERENCE)
                overlay_action.triggered.connect(
                    lambda *_: self.overlay_reference_requested.emit(key)
                )
        return menu

    def _default_confirm(self, filename: str) -> bool:
        # A plain QMessageBox.question(...) call returns only the pressed
        # StandardButton, giving no handle to relabel the buttons — build the
        # box explicitly so the standard Yes/No can be overridden to match the
        # body's verb (spec §2.2: setText overrides survive the qtbase
        # QTranslator's default "はい/いいえ").
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(S.ACTION_REMOVE_FILE)
        box.setText(S.CONFIRM_CLOSE_FILE_TMPL.format(filename=filename))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        yes_button = box.button(QMessageBox.StandardButton.Yes)
        no_button = box.button(QMessageBox.StandardButton.No)
        assert yes_button is not None
        assert no_button is not None
        yes_button.setText(S.CONFIRM_CLOSE_YES)
        no_button.setText(S.CONFIRM_CLOSE_NO)
        reply = box.exec()
        return reply == QMessageBox.StandardButton.Yes

    def _confirm_and_unload(self, row: int) -> None:
        files = self._vm.files
        if row < 0 or row >= len(files):
            return
        if self._confirm_fn(files[row]):
            self._vm.unload(row)

    def _show_context_menu(self, pos: QPoint) -> None:
        """Show the 'Remove File' menu for the row at *pos* (viewport coords).

        Wired to ``QListView.customContextMenuRequested`` — the signal Qt emits on
        a real right-click when the list uses CustomContextMenu policy. Driving the
        menu from this signal (rather than overriding contextMenuEvent on the
        container) is what makes it appear in the real GUI: it does not depend on
        the right-click event propagating up from the child item view (R7.1).
        """
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return
        self.list_view.setCurrentIndex(index)  # right-click selects the row
        global_pos = self.list_view.viewport().mapToGlobal(pos)
        self.build_context_menu(index.row()).exec(global_pos)

    def is_showing_placeholder(self) -> bool:
        """True when the placeholder (not the list) is visible (test-facing)."""
        return self._stack.currentWidget() is self.placeholder_label

    def _on_vm_change(self, change: str) -> None:
        if change == "files":
            self._refresh_state()

    def _refresh_state(self) -> None:
        if self._vm.files:
            self._stack.setCurrentWidget(self.list_view)
        else:
            self._stack.setCurrentWidget(self.placeholder_label)

    def _advance_spinner(self) -> None:
        self._spin_angle = (self._spin_angle + 30) % 360
        # releasing 行がある時だけ再描画(無ければ無駄描画しない)。
        if any(self._vm.is_releasing(r) for r in range(len(self._vm.files))):
            self.list_view.viewport().update()
