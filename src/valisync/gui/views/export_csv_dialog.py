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
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
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

# ツリーアイテムのロール割り当て。UserRole (葉の列キー) は E-0 以前からの契約
# なので動かさない — 既存テストと realgui が選択キーとしてこれを読む。
# int() で包むのは +1/+2/+3 の派生ロールを作るためだけで、値は enum と同一。
# 読み出し側 (既存テスト・realgui の `data(0, Qt.ItemDataRole.UserRole)`) は
# **enum 表記のままでよい** — 書き込みと読み出しで同じ整数を指す。
_KEY_ROLE = int(Qt.ItemDataRole.UserRole)  # 葉のみ: 名前空間つき列キー
_ROW_ROLE = _KEY_ROLE + 1  # 物理チャンネル行と葉: _rows の添字
_COL_ROLE = _KEY_ROLE + 2  # 葉のみ: その行の中での列インデックス
_PLACEHOLDER_ROLE = _KEY_ROLE + 3  # 未展開コンテナのダミー子の目印


@dataclass(slots=True)
class _ChannelRow:
    """1 物理チャンネル行が展開前に知っている全て。**列名は保持しない**。

    列名を抱えないのが本増分の核心: prod は 4,324 行 / 264,004 列で、名前を
    持つだけでダイアログを開く限り数十 MB が常駐する (E-3 が剥がしたコスト
    そのもの)。必要になった瞬間に session.column_names_of() から作り直す。
    """

    file_key: str
    phys: str
    count: int
    single_key: str | None  # count == 1 のときだけ実列キー (合成ハンドルではない)
    # 直近に評価したフィルタ文字列とその結果 (_row_matches のメモ)。同一クエリの
    # 再評価で列名を作り直さないためだけの覚え書きで、行の同一性には関与しない。
    matched: str | None = None
    hit: bool = False


def _physical_channels(signals: list[Signal]) -> list[str]:
    """ローダー順の物理チャンネル名 (重複は最初の出現へ畳む)。

    グループ化キーは metadata['physical_channel'] — 文字列解析では ACC.Speed
    (チャンネル名) と P.x (構造化フィールド) を区別できない (E-2 と同じ根拠)。
    ローダーが列を展開している間は同じ物理チャンネルが複数回現れるので畳む
    必要があり、反転後は 1 回しか現れないので畳んでも同じ結果になる — この
    1 本の走査だけで新旧どちらのローダーでも同じ行が出る。
    CSV/Derived は physical_channel を持たない = 1 列 1 物理チャンネル。
    """
    out: list[str] = []
    seen: set[str] = set()
    for sig in signals:
        name = sig.name
        orig = name.split(KEY_SEPARATOR, 1)[1] if KEY_SEPARATOR in name else name
        phys = str((sig.metadata or {}).get("physical_channel") or orig)
        if phys not in seen:
            seen.add(phys)
            out.append(phys)
    return out


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

        # 選択の真実は **ダイアログ側の集合** (U1)。未展開の列は QTreeWidgetItem を
        # 持たないので「木を数えて選択集合を作る」実装は原理的に成立しない。
        # 値は (行, 列) — 出力列順を木の並びに保つための添字で、ハッシュ順に
        # 依存すると PYTHONHASHSEED ごとに CSV の列順が変わる。
        self._selected: dict[str, tuple[int, int]] = {}
        # 行ごとの選択列数。三態表示を O(1) で出すため (未展開の 262k 列を
        # 数え直さない唯一の手段)。
        self._selected_per_row: dict[int, int] = {}
        # 選択中でオフセットを持つキー。_offset_active_for_checked を O(1) にする
        # ためだけの覚え書き (_selected_per_row と同じ考え方)。ファイル行 1 クリックは
        # 行ごとに 1 回ずつ _validate() を通るので、そこで毎回 _selected 全体を
        # 走査すると prod (4,324 行 / 264,004 列) では行数 x 列数 = 10 億回の
        # offset_for 呼び出しになる。キーは追加時に 1 度だけ問い合わせる。
        self._offset_keys: set[str] = set()
        self._rows: list[_ChannelRow] = []
        # 表示同期中フラグ: 自分で setCheckState/setFlags した分を「ユーザー操作」
        # として拾い戻さないための門。複数経路から入るので受け口 1 箇所で弾く。
        self._syncing = False

        layout = QVBoxLayout(self)

        # フィルタ
        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText(S.FILTER_PLACEHOLDER)
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        # 信号ツリー(ファイル > 物理チャンネル > 列・チェックボックス)
        self._tree = QTreeWidget(self)
        self._tree.setObjectName("export_tree")
        self._tree.setHeaderHidden(True)
        # 接続は構築の **後**。構築中の setFlags/setCheckState は itemChanged を
        # 発火させるがユーザー操作ではない (先に繋ぐと、まだ CheckState を書いて
        # いない葉の setFlags が「未チェックにされた」と誤読され初期選択が消える)。
        self._build_tree(initial_selected)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemExpanded.connect(self._on_item_expanded)
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

    # --- ツリー構築 ---------------------------------------------------------
    def _build_tree(self, initial_selected: set[str]) -> None:
        """ファイル行と物理チャンネル行までを作る (列アイテムは要求時)。

        列の QTreeWidgetItem は作らない — prod 264,004 個の同期構築が
        「ダイアログを開くだけで固まる」の正体だった (U1)。
        ここで走る column_names_of は「列数」と「初期選択の所在」を確定する
        ための **一過性** の生成で、名前は 1 つも保持しない (行あたり int 1 個)。
        物理チャンネルごとの列数を返す API があれば消せる一過性コストだが、
        C-g と同じ理由で E-3 では増やさない。
        """
        session = self._app_vm.session
        items: list[QTreeWidgetItem] = []  # _rows と同じ添字
        # 表示名の衝突判定は **行の identity** で行う。列まで母集団に入れると
        # 264k 名の生成/保持が要り E-3 の成果が消える。1 列行は実列キーを
        # identity にするので、1 列 = 1 信号のファイル (CSV 等) では E-0 の
        # 従来挙動がそのまま保たれる。複数列の親配下の列テキストは裸名のまま
        # (親が既に qualified なので所属ファイルは文脈で一意) — 意図的逸脱。
        # identity は行ごとに一意とは限らない: 物理チャンネル名が文字どおり
        # "Mono[0]" のファイルと、"Mono" の 1 列展開が同居すると両行が同じ
        # identity になる (T0 が固定している Mat[0] 衝突と同型の配置)。影響は
        # **表示テキストだけ**で、選択キー (_KEY_ROLE = 実列キー) は常に一意。
        identities: list[str] = []
        tops: list[QTreeWidgetItem] = []
        auto_expand: list[int] = []
        for file_key in self._app_vm.loaded_file_keys:
            top = QTreeWidgetItem(self._tree, [session.source_name(file_key)])
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            tops.append(top)
            prefix = f"{file_key}{KEY_SEPARATOR}"
            # 初期選択はファイルごとに裸名へ落として突き合わせる (列 1 本ごとに
            # f"{prefix}{name}" を作ると prod で 264k 個の一過性文字列になる)。
            wanted = {
                k[len(prefix) :] for k in initial_selected if k.startswith(prefix)
            }
            for phys in _physical_channels(session.group_signals(file_key)):
                names = session.column_names_of(file_key, phys)
                row_index = len(self._rows)
                single = prefix + names[0] if len(names) == 1 else None
                self._rows.append(_ChannelRow(file_key, phys, len(names), single))
                if wanted:
                    for col_index, name in enumerate(names):
                        if name in wanted:
                            self._add_selection(row_index, col_index, prefix + name)
                    # 1 列行はコンテナではない (プレースホルダも子も持たない) ので
                    # 合成対象から外す — 展開すべき列がそもそも無い。
                    if single is None and self._selected_per_row.get(row_index):
                        auto_expand.append(row_index)
                item = QTreeWidgetItem(top, [""])  # テキストは display_names 確定後
                item.setData(0, _ROW_ROLE, row_index)
                items.append(item)
                identities.append(single if single is not None else prefix + phys)
        shown = display_names(identities)
        for row_index, item in enumerate(items):
            row = self._rows[row_index]
            item.setText(0, shown[identities[row_index]])
            if row.single_key is not None:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setData(0, _KEY_ROLE, row.single_key)
                item.setData(0, _COL_ROLE, 0)
            else:
                # C-a: 親はチェック **不可** の三態コンテナ。CheckStateRole を
                # 持つので部分チェックは描かれるが ItemIsUserCheckable を **外す**
                # のでクリックでは変わらない (「親をチェック = 全列」は 264k 鋳造の
                # 一撃)。QTreeWidgetItem の既定フラグは UserCheckable を **含む**
                # ため、付けないだけでは足りず明示的に落とす必要がある。
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                placeholder = QTreeWidgetItem(item, [S.EXPORT_COLUMN_PLACEHOLDER])
                placeholder.setData(0, _PLACEHOLDER_ROLE, True)
            self._refresh_row_state(item)
        for row_index in auto_expand:
            # itemExpanded はまだ繋がっていないので明示的に合成する
            # (プロット中の列を「開いたら選択済み」で見せる従来挙動の維持)。
            self._materialize(items[row_index], row_index)
            items[row_index].setExpanded(True)
        for top in tops:
            top.setExpanded(True)  # expandAll() の置き換え: ファイル行だけ開く

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        """コンテナ行を初めて開いた瞬間に列アイテムを合成する (U1)。"""
        row_index = item.data(0, _ROW_ROLE)
        if row_index is None:  # ファイル行 (子は構築済み)。0 は正当な行番号なので
            return  # 真偽値ではなく None で判定すること
        if self._needs_columns(item):
            self._materialize(item, row_index)

    @staticmethod
    def _needs_columns(item: QTreeWidgetItem) -> bool:
        first = item.child(0)
        return first is not None and bool(first.data(0, _PLACEHOLDER_ROLE))

    def _materialize(self, item: QTreeWidgetItem, row_index: int) -> None:
        """この行の列だけをアイテム化する (1 回だけ・他の行には触らない)。"""
        row = self._rows[row_index]
        prefix = f"{row.file_key}{KEY_SEPARATOR}"
        names = self._column_names(row_index)
        was, self._syncing = self._syncing, True
        try:
            children: list[QTreeWidgetItem] = []
            for col_index, name in enumerate(names):
                key = prefix + name
                child = QTreeWidgetItem([name])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setData(0, _KEY_ROLE, key)
                child.setData(0, _ROW_ROLE, row_index)
                child.setData(0, _COL_ROLE, col_index)
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if key in self._selected
                    else Qt.CheckState.Unchecked,
                )
                children.append(child)
            placeholder = item.child(0)
            assert placeholder is not None and placeholder.data(0, _PLACEHOLDER_ROLE)
            # 先に実列を足してからプレースホルダを外す — 子 0 個の瞬間を作ると
            # Qt が展開中の行を畳んでしまう。
            item.addChildren(children)
            item.takeChild(0)
        finally:
            self._syncing = was
        self._apply_filter_to_children(item, self._filter_query())

    # --- 選択 ---------------------------------------------------------
    def _iter_rows(self) -> Iterator[QTreeWidgetItem]:
        """全ファイルの物理チャンネル行 (トップレベルはファイル行)。"""
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            assert top is not None
            for j in range(top.childCount()):
                row_item = top.child(j)
                assert row_item is not None
                yield row_item

    def _iter_children(self) -> Iterator[QTreeWidgetItem]:
        """チェック可能な葉 (1 列行 + 合成済みの列)。

        **未展開の列は含まれない** — 選択の真実が _selected へ移ったのはこれが
        理由で、ここを数えて出力集合を作ってはならない。
        """
        for row_item in self._iter_rows():
            if row_item.data(0, _KEY_ROLE) is not None:
                yield row_item
            for j in range(row_item.childCount()):
                child = row_item.child(j)
                assert child is not None
                if child.data(0, _KEY_ROLE) is not None:
                    yield child

    def _column_names(self, row_index: int) -> tuple[str, ...]:
        """行の列名 (裸名・要求時生成)。"""
        row = self._rows[row_index]
        return self._app_vm.session.column_names_of(row.file_key, row.phys)

    def _column_keys(self, row_index: int) -> tuple[str, ...]:
        """行の列キー。**鋳造しない** (C-b) — 名前を組むだけで resolve は呼ばない。"""
        row = self._rows[row_index]
        if row.single_key is not None:
            return (row.single_key,)
        prefix = f"{row.file_key}{KEY_SEPARATOR}"
        return tuple(prefix + n for n in self._column_names(row_index))

    def _add_selection(self, row_index: int, col_index: int, key: str) -> None:
        if key in self._selected:
            return
        self._selected[key] = (row_index, col_index)
        self._selected_per_row[row_index] = self._selected_per_row.get(row_index, 0) + 1
        if self._offset_for is not None and self._offset_for(key) != 0.0:
            self._offset_keys.add(key)

    def _drop_selection(self, key: str) -> None:
        pos = self._selected.pop(key, None)
        if pos is None:
            return
        self._selected_per_row[pos[0]] -= 1
        self._offset_keys.discard(key)

    def _set_state(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        was, self._syncing = self._syncing, True
        try:
            item.setCheckState(0, state)
        finally:
            self._syncing = was

    def _refresh_row_state(self, item: QTreeWidgetItem) -> None:
        """行のチェック表示を選択数カウンタから作り直す (表示専用・O(1))。"""
        row_index = item.data(0, _ROW_ROLE)
        row = self._rows[row_index]
        n = self._selected_per_row.get(row_index, 0)
        if n == 0:
            state = Qt.CheckState.Unchecked
        elif n >= row.count:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        self._set_state(item, state)

    def _sync_row_children(self, row_item: QTreeWidgetItem) -> None:
        """1 行ぶんの表示 (合成済みの列 + 行自身の三態) を _selected から作り直す。"""
        for j in range(row_item.childCount()):
            child = row_item.child(j)
            assert child is not None
            key = child.data(0, _KEY_ROLE)
            if key is None:
                continue  # プレースホルダ
            self._set_state(
                child,
                Qt.CheckState.Checked
                if key in self._selected
                else Qt.CheckState.Unchecked,
            )
        self._refresh_row_state(row_item)

    def _sync_widget_states(self) -> None:
        """実在するアイテムの表示だけを _selected から作り直す。

        未展開の列にはアイテムが無い — そこが「ウィジェットは表示専用」の所以。
        """
        for row_item in self._iter_rows():
            self._sync_row_children(row_item)

    def _toggle_row(self, item: QTreeWidgetItem, row_index: int) -> None:
        """ファイル行のチェックが降ってきた物理チャンネル行を丸ごと選択/解除する。

        ファイル行は ItemIsAutoTristate なので、そのチェックボックスを押すと
        QTreeWidgetItem が「CheckState を持つ子」を **チェック可能かどうかに関係
        なく** 書き換える。コンテナから ItemIsUserCheckable を外してもこの経路は
        塞げない (C-a が塞ぐのはコンテナ行 *自身* のクリックだけ) ので、ここが
        ファイル行チェックの唯一の受け口になる。

        受け口で表示だけを引き戻す (コンテナを Unchecked へ戻す) と、ファイル行は
        `childrenCheckState()` = Unchecked ∧ Checked = PartiallyChecked に貼り付き、
        `QStyledItemDelegate.editorEvent` の二値トグル (Checked 以外は Checked へ)
        と噛み合って **二度と Checked にならず解除にも使えない一方通行** になる。
        なので表示を戻すのではなく、伝播を選択そのものへ翻訳する — 「ファイル行を
        チェック = そのファイルの全列」。列キーは `_select_all` と同じく **名前だけ**
        で組む (C-b: resolve は呼ばない) ので 264k 鋳造にはならない。
        """
        if item.checkState(0) == Qt.CheckState.Checked:
            for col_index, key in enumerate(self._column_keys(row_index)):
                self._add_selection(row_index, col_index, key)
        else:
            for key in self._column_keys(row_index):
                self._drop_selection(key)
        self._sync_row_children(item)
        self._validate()

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        """ユーザーがチェックを触ったときだけ選択集合へ反映する。"""
        if self._syncing:
            return
        key = item.data(0, _KEY_ROLE)
        if key is None:
            # ファイル行 (自身は何も持たない) / コンテナ行 (C-a: 直接は選択できない)。
            row_index = item.data(0, _ROW_ROLE)
            if row_index is not None:
                self._toggle_row(item, row_index)
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self._add_selection(item.data(0, _ROW_ROLE), item.data(0, _COL_ROLE), key)
        else:
            self._drop_selection(key)
        parent = item.parent()
        if parent is not None and parent.data(0, _ROW_ROLE) is not None:
            # コンテナの三態を更新 (そこから先はファイル行へ Qt が伝播する)。
            self._refresh_row_state(parent)
        self._validate()

    def _checked_keys(self) -> list[str]:
        """出力集合 (フィルタ非依存・木の並び順)。

        並びは (行, 列) = ファイル順 -> ローダー順 -> 列順。set のハッシュ順で
        並べると PYTHONHASHSEED ごとに CSV の列順が変わる。
        """
        return sorted(self._selected, key=lambda k: self._selected[k])

    def _select_all(self) -> None:
        """全列を選択する — **鋳造しない** (C-b)。

        列キーは名前だけを組む。ここで resolve_signal を呼ぶと prod で 264k 本の
        Signal 鋳造 = ~390 MB の一撃になる。実際の読みは _on_accept が
        選択列 1 本ずつ行う。
        """
        for row_index in range(len(self._rows)):
            for col_index, key in enumerate(self._column_keys(row_index)):
                self._add_selection(row_index, col_index, key)
        self._sync_widget_states()
        self._validate()

    def _select_none(self) -> None:
        self._selected.clear()
        self._selected_per_row.clear()
        self._offset_keys.clear()
        self._sync_widget_states()
        self._validate()

    def _filter_query(self) -> str:
        return self._filter.text().strip().lower()

    def _apply_filter(self, text: str) -> None:
        """行と (合成済みの) 列を絞り込む。

        照合は **表示テキスト** — E-0 の qualified 形 ("speed (csv_1)") ごと
        引っかかる従来挙動を保つ。加えて未展開のコンテナは自分の列名も見る
        (「フィルタは列名にマッチ」= ChannelBrowser と同じ規則)。列名走査は
        _row_matches だけで、名前は保持しない (行が覚えるのは直近のクエリ文字列と
        真偽値だけ)。
        """
        t = text.strip().lower()
        for row_item in self._iter_rows():
            row_item.setHidden(not self._row_matches(row_item, t))
            self._apply_filter_to_children(row_item, t)

    def _apply_filter_to_children(self, row_item: QTreeWidgetItem, t: str) -> None:
        for j in range(row_item.childCount()):
            child = row_item.child(j)
            assert child is not None
            child.setHidden(bool(t) and t not in child.text(0).lower())

    def _row_matches(self, row_item: QTreeWidgetItem, t: str) -> bool:
        """*t* がこの行 (表示テキスト または その列名) に当たるか。

        列名の再生成コストを 2 段で抑える。`_filter` の textChanged にはデバウンスが
        無く (ChannelBrowserView の 200ms シングルショットに相当するものがこの
        ダイアログには無い)、prod は 4,324 行 / 264,004 列なので、素直に書くと
        1 打鍵あたり 26 万本の f-string になる:

        1. 行テキストで決まるならそこで終わり。
        2. 物理チャンネル名が **それ自身 1 本の列** (スカラー / CSV) なら、その列名は
           行テキストそのものなので列名走査は要らない。`session.has_column()` は
           列名を 1 本も生成せずにこれを答える (T1)。
        3. 残る複数列の行だけが `column_names_of` を引き、結果を行へメモする
           (同一クエリの再評価では作り直さない)。

        それでも「複数列の行の列名は打鍵ごとに再生成される」コストは残る —
        **意図的受容**であり T9 の実測対象に含める。列名を保持すると E-3 が剥がした
        常駐メモリ (行あたり int 1 個で済ませている設計) がそのまま戻るため、ここは
        時間側で払う。
        """
        if not t:
            return True
        row_index = row_item.data(0, _ROW_ROLE)
        row = self._rows[row_index]
        if row.matched == t:
            return row.hit
        if t in row_item.text(0).lower():
            hit = True
        elif self._app_vm.session.has_column(row.file_key, row.phys):
            hit = False  # 1 列行: 列名は行テキストに含まれる = 上で決着済み
        else:
            hit = any(t in name.lower() for name in self._column_names(row_index))
        row.matched, row.hit = t, hit
        return hit

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

        オフセットの有無はキーが選択集合へ入る瞬間に 1 度だけ問い合わせて
        `_offset_keys` に覚える (_add_selection/_drop_selection)。ここで毎回
        `_selected` を走査すると、ファイル行 1 クリック (行ごとに _validate() を
        通る) が prod で 行数 x 列数 = 10 億回の offset_for 呼び出しになる。
        リアクティブ性 (選択集合の変化に追随) は集合の出入りで保たれる。
        """
        return bool(self._offset_keys)

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
        n = len(self._selected)
        if opts is not None:
            self._error.setText("" if n else S.EXPORT_NO_SELECTION_ERROR)
        ok = opts is not None and bool(n)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        # F-0/UX-28: N = 総選択数 (フィルタ非依存)。選択の真実が _selected に
        # あるので、フィルタで隠れた行も未展開の列も等しく数に入る = 実出力集合
        # (_on_accept の keys) と常に一致する。
        self._selection_label.setText(S.EXPORT_SELECTION_COUNT_TMPL.format(n=n))

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
        # 選択列を **ここで初めて** 実体化する (C-b: 選択は名前だけ・実体は出口で
        # 1 本ずつ)。鋳造は Signal オブジェクトを作るだけで値は読まない
        # (LazyMdfValues) ので、保存先を訊く前に失敗を確定させてよい。
        signals: list[Signal] = []
        missing: list[str] = []
        for k in keys:
            sig = self._app_vm.session.resolve_signal(k)
            if sig is None:
                missing.append(k)
            else:
                signals.append(sig)
        if missing:
            # 旧実装はここが素の KeyError でダイアログごとクラッシュしていた。
            # 無言で落とすと「選んだのに出ていない CSV」になるので、出力せずに
            # 理由を出す。
            self._error.setText(
                S.EXPORT_UNRESOLVED_ERROR_TMPL.format(
                    n=len(missing), name=display_names(missing)[missing[0]]
                )
            )
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
            signals=signals,
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
