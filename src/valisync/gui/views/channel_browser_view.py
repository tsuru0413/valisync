"""Channel_Browser view — refactored for master-detail (Task 2.3).

A search box atop a flat QTreeView. User gestures are forwarded to the VM.
Displays signals for the currently active file in AppViewModel.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEvent,
    QItemSelection,
    QMimeData,
    QObject,
    QPoint,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.adapters.qt_signal_models import (
    SignalTableModel,
    encode_signal_keys,
)
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

# Empty-state placeholder text (FB-05/08/09); no_match takes a format arg.
_EMPTY_MESSAGES = {
    "none_selected": "File Browser でファイルを選択すると\n信号一覧を表示します",
    "no_match": "「{query}」に一致する信号はありません",
    "no_channels": "このファイルに信号がありません\n（Diagnostics に詳細）",  # noqa: RUF001
}


class ChannelBrowserView(QWidget):
    """Search box + flat tree view bound to a :class:`ChannelBrowserVM`."""

    # Emitted with the selected signal keys; the integration connects this to
    # the active Graph_Panel's add_signal (R14.1).
    add_to_panel_requested = Signal(list)

    def __init__(self, vm: ChannelBrowserVM, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self.model = SignalTableModel(vm)
        # PC-20: ソート専用の proxy を挟む(フィルタは現行どおり VM 真実 = proxy は
        # accept-all のまま)。ヘッダクリックで Name/Unit 列ソート。
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        # Real channel names are mixed-case (EngineSpeed / vehSpd); sort
        # case-insensitively so an A-Z scan isn't split into upper/lower blocks.
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Filter signals…")
        self.search_box.setClearButtonEnabled(True)

        # PC-02: 可視の追加ボタン(FileBrowser の Open ボタンパターン踏襲)。
        # 文言は配送先(アクティブパネル)を正直に示す。
        self.add_button = QPushButton("アクティブパネルへ追加", self)
        self.add_button.setObjectName("channel_browser_add")
        self.add_button.setToolTip("選択中の信号をアクティブパネルへ追加")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._emit_add_selected)

        self.tree = QTreeView(self)
        self.tree.setModel(self.proxy)
        self.tree.setSortingEnabled(True)
        # setSortingEnabled(True) は「現在のソート指標」で即時 sortByColumn する。
        # 既定は源順(セッション/グループ順)を保ち、ヘッダクリックで初めてソート
        # する挙動にしたいので、proxy のソート列を -1(パススルー)へ戻す(spec DP2:
        # 「ヘッダクリックで名前/単位ソート」= 既定ソートは要求されていない)。
        self.tree.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.tree.setDragEnabled(True)
        self.tree.setUniformRowHeights(True)

        # Refactor for flat list appearance
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)

        # CustomContextMenu so a real right-click on the child tree emits
        # customContextMenuRequested. Overriding contextMenuEvent on this
        # container does not fire reliably from the child item view, so the
        # menu would not appear in the real GUI (mirrors FileBrowser PR#11).
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.header_label = QLabel(self)
        self.placeholder_label = QLabel(self)
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setWordWrap(True)
        # QLabel は既定で plain text — クエリ文字列を HTML 解釈させない (spec §6)
        self.placeholder_label.setTextFormat(Qt.TextFormat.PlainText)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.tree)  # index 0
        self._stack.addWidget(self.placeholder_label)  # index 1

        controls = QHBoxLayout()
        controls.addWidget(self.search_box, 1)
        controls.addWidget(self.add_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header_label)
        layout.addLayout(controls)
        layout.addWidget(self._stack)

        # ── Wiring ───────────────────────────────────────────────────────────
        # set_filter() synchronously notifies "filter" -> _on_vm_change() ->
        # _refresh_state(), so a second direct textChanged->_refresh_state
        # connection would double-call it on every keystroke; the VM notify
        # path alone is sufficient (see _on_vm_change below).
        self.search_box.textChanged.connect(self._vm.set_filter)
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        # PC-04: 最短追加操作。activated はダブルクリック専用 (Enter は eventFilter が
        # 消費して単発 emit を保証 -- Windows では activated も Enter で発火するため、
        # 両配線だと 1 打鍵で二重追加になる。spec §6 二重発火ガード)。
        self.tree.activated.connect(lambda _index: self._emit_add_selected())
        self.tree.installEventFilter(self)

        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        unsubscribe = self._vm.subscribe(self._on_vm_change)
        self.destroyed.connect(lambda *_: unsubscribe())

        self._refresh_state()

    # ─── VM reactions ──────────────────────────────────────────────────────────

    def is_showing_placeholder(self) -> bool:
        """True when the placeholder (not the tree) is visible (test-facing)."""
        return self._stack.currentWidget() is self.placeholder_label

    def _refresh_state(self) -> None:
        """Sync header + tree/placeholder switch with the VM (FB-05/08/09)."""
        self.header_label.setText(self._vm.header_text())
        state = self._vm.empty_state()
        if state == "has_rows":
            self._stack.setCurrentWidget(self.tree)
            return
        message = _EMPTY_MESSAGES[state]
        if state == "no_match":
            message = message.format(query=self._vm.filter_query())
        self.placeholder_label.setText(message)
        self._stack.setCurrentWidget(self.placeholder_label)

    def _on_vm_change(self, change: str) -> None:
        """Handle notifications from ChannelBrowserVM."""
        if change in ("signals", "filter"):
            self._refresh_state()

    def _on_selection_changed(
        self, _selected: QItemSelection, _deselected: QItemSelection
    ) -> None:
        keys = self.selected_signal_keys()
        self._vm.set_selection(keys)
        self.add_button.setEnabled(bool(keys))

    # ─── Queries ───────────────────────────────────────────────────────────────

    def selected_signal_keys(self) -> list[str]:
        """Return the namespaced keys of the currently-selected signal rows.

        Rows are proxy indexes (sort may reorder them), so each must be mapped
        back to the source model before resolving its key -- otherwise a sorted
        view would drag/select the wrong signal (PC-20).
        """
        keys: list[str] = []
        for index in self.tree.selectionModel().selectedRows(0):
            src = self.proxy.mapToSource(index)
            key = self.model.signal_key_at(src)
            if key is not None:
                keys.append(key)
        return keys

    def mime_data_for_selection(self) -> QMimeData:
        """Build the drag payload for the current selection (signal keys)."""
        return encode_signal_keys(self.selected_signal_keys())

    # ─── Commands ────────────────────────────────────────────────────────────--

    def _emit_add_selected(self) -> None:
        """Emit add_to_panel_requested for the current selection (PC-02/PC-04 共用)."""
        keys = self.selected_signal_keys()
        if keys:
            self.add_to_panel_requested.emit(keys)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Consume Return/Enter on the tree so activated cannot also fire it.

        QAbstractItemView.activated fires on Enter as well as double-click on
        Windows; without consuming the key here, a single key press would
        emit add_to_panel_requested twice (spec §6 二重発火ガード).
        """
        if (
            watched is self.tree
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._emit_add_selected()
            return True  # consumed: do not propagate to QAbstractItemView.activated
        return super().eventFilter(watched, event)

    # ─── Context menu (R14.1) ──────────────────────────────────────────────────

    def build_context_menu(self) -> QMenu:
        """Build the signal context menu, greyed out per current selection."""
        menu = QMenu(self)
        add = menu.addAction("Add to Active Panel")
        add.setEnabled(bool(self.selected_signal_keys()))
        # Route through _emit_add_selected so the empty-selection guard is shared
        # with the button/dblclick/Enter paths (action is already disabled when
        # empty; this keeps all four add paths symmetric).
        add.triggered.connect(lambda *_: self._emit_add_selected())
        return menu

    def _show_context_menu(self, pos: QPoint) -> None:
        """Show the signal menu on a real right-click (CustomContextMenu).

        Driven by ``QTreeView.customContextMenuRequested`` so the menu appears on
        the real OS path (overriding contextMenuEvent on this container does not
        fire from the child item view). The menu operates on the current
        multi-selection (R14.1 / H4), so this deliberately does NOT change the
        selection — right-clicking with several rows selected keeps them all for
        a bulk "Add to Active Panel".
        """
        global_pos = self.tree.viewport().mapToGlobal(pos)
        self.build_context_menu().exec(global_pos)
