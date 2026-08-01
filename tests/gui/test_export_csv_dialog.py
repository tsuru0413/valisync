from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
)
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.models import Delimiter, FormatDefinition, Signal
from valisync.gui import strings as S
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.export_csv_dialog import ExportCsvDialog, ExportRequest


class _FakeSession:
    """列展開の前後どちらのローダー形にもなれる最小 Session。

    group_signals が返す Signal は「反転前 = 列 1 本ごと」「反転後 = 物理チャンネル
    1 本」の 2 形を取りうる (T6)。ダイアログはどちらでも同じ行を出さなければ
    ならないので fixture 側でこの 2 形を切り替える。column_names_of は T1 の契約
    (未登録キー / スカラーは (display_name,)) をそのまま写す — CSV グループは
    ColumnRecord を持たないので、この既定分岐が CSV 経路そのものになる。
    """

    def __init__(
        self,
        groups: dict[str, list[Signal]],
        names: dict[str, str],
        columns: dict[tuple[str, str], tuple[str, ...]] | None = None,
        resolvable: dict[str, Signal] | None = None,
    ) -> None:
        self._groups = groups
        self._names = names
        self._columns = columns or {}
        # 反転後は列 Signal が group_signals に居ないので、鋳造先を別に持つ。
        self.resolvable = resolvable or {
            sig.name: sig for sigs in groups.values() for sig in sigs
        }
        self.resolve_calls = 0

    def source_name(self, key: str) -> str:
        return self._names[key]

    def group_signals(self, key: str) -> list[Signal]:
        return self._groups[key]

    def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]:
        return self._columns.get((key, display_name), (display_name,))

    def has_column(self, key: str, display_name: str) -> bool:
        # T1 と同じ契約: 物理チャンネル名がそれ自身 1 本の列なら True、
        # 複数列へ展開される親 (容器) なら False。
        return self._columns.get((key, display_name), (display_name,)) == (
            display_name,
        )

    def resolve_signal(self, key: str) -> Signal | None:
        self.resolve_calls += 1
        return self.resolvable.get(key)


class _FakeAppVM:
    def __init__(self, session: _FakeSession, keys: list[str]) -> None:
        self.session = session
        self.loaded_file_keys = keys


def _sig(name: str, phys: str | None = None) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="CSV",
        bus_type="",
        source_file="",
        metadata={"physical_channel": phys} if phys else None,
    )


def _app_vm() -> _FakeAppVM:
    sess = _FakeSession(
        groups={"csv_1": [_sig("csv_1::a"), _sig("csv_1::b")]},
        names={"csv_1": "run.csv"},
    )
    return _FakeAppVM(sess, ["csv_1"])


def _app_vm_two_files_same_bare() -> _FakeAppVM:
    """Two files, each with a signal literally named "speed" (E-0 collision)."""
    sess = _FakeSession(
        groups={
            "csv_1": [_sig("csv_1::speed"), _sig("csv_1::rpm")],
            "csv_2": [_sig("csv_2::speed")],
        },
        names={"csv_1": "run1.csv", "csv_2": "run2.csv"},
    )
    return _FakeAppVM(sess, ["csv_1", "csv_2"])


def _ok(dlg: ExportCsvDialog) -> bool:
    return dlg._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_initial_selection_is_plotted(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"})
    qtbot.addWidget(dlg)
    checked = dlg._checked_keys()
    assert checked == ["csv_1::a"]  # プロット中のみ初期チェック
    assert _ok(dlg) is True  # 1 件チェックで Ok 有効


def test_unified_timeline_defaults_checked(qtbot: QtBot) -> None:
    # マルチレート信号(独立ラスタ)を安全な既定にする(whole-branch review Important #1)。
    # 共有信号では unified も出力バイト同一なので既定 ON は無回帰。
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"})
    qtbot.addWidget(dlg)
    assert dlg._unified.isChecked() is True


def test_select_all_and_none(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected=set())
    qtbot.addWidget(dlg)
    assert _ok(dlg) is False  # 0 選択で Ok 無効
    dlg._select_all()
    assert set(dlg._checked_keys()) == {"csv_1::a", "csv_1::b"}
    assert _ok(dlg) is True
    dlg._select_none()
    assert dlg._checked_keys() == []
    assert _ok(dlg) is False


def test_delimiter_decimal_collision_disables_ok(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"})
    qtbot.addWidget(dlg)
    dlg._set_delimiter(",")
    dlg._set_decimal(",")  # 衝突
    assert _ok(dlg) is False
    assert dlg._error.text() != ""


def test_ask_builds_request_from_widgets(qtbot: QtBot, tmp_path: Path) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a", "csv_1::b"})
    qtbot.addWidget(dlg)
    dlg._set_delimiter(";")
    dlg._unit_row.setChecked(True)
    target = tmp_path / "out.csv"
    dlg._save_path_provider = lambda: str(target)  # 保存ダイアログを差し替え
    dlg._on_accept()
    req = dlg._result
    assert isinstance(req, ExportRequest)
    # E-4b Task 4 supersede: 要求は **列キー** を運ぶ (D1・spec §5.2)。右辺は不変。
    assert set(req.keys) == {"csv_1::a", "csv_1::b"}
    assert req.output_path == target
    assert req.options.delimiter == ";"
    assert req.options.unit_row is True
    # E-0: ヘッダは bare display name (no collision — both are from the same
    # file "csv_1"), same order as req.keys/_checked_keys.
    # E-4b Task 4 supersede: 名前は options.header_names に**先に詰めない**で
    # header_resolver として運ぶようになった (ヘッダと値を同じ keys から導出)。
    # 期待値 ("a", "b") は 1 文字も変えず、読み口だけを resolver 適用へ移す。
    assert req.header_resolver(req.keys) == ["a", "b"]


# --- E-0: 葉テキスト/フィルタは display name (UX-19) -------------------------


def _leaf_texts(dlg: ExportCsvDialog) -> set[str]:
    return {c.text(0) for c in dlg._iter_children()}


def test_leaf_text_shows_bare_name_no_collision(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected=set())
    qtbot.addWidget(dlg)
    assert _leaf_texts(dlg) == {"a", "b"}  # not "csv_1::a"/"csv_1::b"
    # M-3: 旧形の `set(_checked_keys()) <= {...}` は initial_selected=set() ゆえ
    # 空集合に対する部分集合判定 = 無条件に真だった。狙っていた契約 (表示名化が
    # 選択キーを汚さない) は _KEY_ROLE を **直接** 読み、かつアイテム駆動の
    # 選択経路 (ユーザーのクリックが通る唯一の経路) で確かめる。
    # sabotage: _KEY_ROLE に表示テキストを書くと 1 つ目の assert が RED
    # (_checked_keys() は _rows 由来なので、キーの等号だけでは捕まらない)。
    assert {c.data(0, Qt.ItemDataRole.UserRole) for c in dlg._iter_children()} == {
        "csv_1::a",
        "csv_1::b",
    }
    leaf = next(c for c in dlg._iter_children() if c.text(0) == "a")
    leaf.setCheckState(0, Qt.CheckState.Checked)
    assert dlg._checked_keys() == ["csv_1::a"]


def test_leaf_text_qualified_on_collision(qtbot: QtBot) -> None:
    """Two files each have "speed" -> both qualified with (group_key); the
    non-colliding "rpm" stays bare."""
    dlg = ExportCsvDialog(_app_vm_two_files_same_bare(), initial_selected=set())
    qtbot.addWidget(dlg)
    assert _leaf_texts(dlg) == {"speed (csv_1)", "speed (csv_2)", "rpm"}
    # UserRole selection keys are untouched by the display change.
    dlg._select_all()
    assert set(dlg._checked_keys()) == {"csv_1::speed", "csv_1::rpm", "csv_2::speed"}


def test_filter_matches_display_text_not_raw_key(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm_two_files_same_bare(), initial_selected=set())
    qtbot.addWidget(dlg)
    dlg._filter.setText("speed")
    visible = {c.text(0) for c in dlg._iter_children() if not c.isHidden()}
    assert visible == {"speed (csv_1)", "speed (csv_2)"}


# --- F-0/UX-28: 出力範囲ラジオ -----------------------------------------------


def test_range_all_is_default_checked_and_unbounded(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"})
    qtbot.addWidget(dlg)
    assert dlg._range_all.isChecked() is True
    opts = dlg._current_options()
    assert opts is not None
    assert opts.time_start is None
    assert opts.time_end is None


def test_range_visible_disabled_when_x_range_none(qtbot: QtBot) -> None:
    # 既定 (DI 未注入) では x_range=None -> [現在の表示範囲] は disabled (I3)。
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"})
    qtbot.addWidget(dlg)
    assert dlg._range_visible.isEnabled() is False


def test_range_visible_injects_x_range(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"}, x_range=(2.0, 9.0))
    qtbot.addWidget(dlg)
    assert dlg._range_visible.isEnabled() is True
    dlg._range_visible.setChecked(True)
    opts = dlg._current_options()
    assert opts is not None
    assert opts.time_start == 2.0
    assert opts.time_end == 9.0


@pytest.mark.parametrize("cursor_a,cursor_b", [(None, None), (3.0, None), (None, 3.0)])
def test_range_cursor_disabled_unless_both_ab_set(
    qtbot: QtBot, cursor_a: float | None, cursor_b: float | None
) -> None:
    dlg = ExportCsvDialog(
        _app_vm(), initial_selected=set(), cursor_a=cursor_a, cursor_b=cursor_b
    )
    qtbot.addWidget(dlg)
    assert dlg._range_cursor.isEnabled() is False


def test_range_cursor_injects_min_max_regardless_of_ab_order(qtbot: QtBot) -> None:
    # A/B は設置順で並ぶとは限らない (B をドラッグして A より前に移動できる) —
    # ラジオは常に min/max へ正規化する。
    dlg = ExportCsvDialog(
        _app_vm(), initial_selected={"csv_1::a"}, cursor_a=6.0, cursor_b=3.0
    )
    qtbot.addWidget(dlg)
    assert dlg._range_cursor.isEnabled() is True
    dlg._range_cursor.setChecked(True)
    opts = dlg._current_options()
    assert opts is not None
    assert opts.time_start == 3.0
    assert opts.time_end == 6.0


def test_range_cursor_label_shows_actual_range(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected=set(), cursor_a=3.0, cursor_b=6.0)
    qtbot.addWidget(dlg)
    assert dlg._range_cursor.text() == S.EXPORT_RANGE_CURSOR_TMPL.format(lo=3.0, hi=6.0)


def test_range_cursor_label_is_bare_when_not_both_set(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected=set())
    qtbot.addWidget(dlg)
    assert dlg._range_cursor.text() == S.EXPORT_RANGE_CURSOR


def test_range_offset_active_disables_display_derived_radios(qtbot: QtBot) -> None:
    # I2: 選択(checked)信号にオフセットがあると x_range/A-B が揃っていても
    # disabled。[全期間] は常に有効のまま。offset_for は checked 集合に対し
    # リアクティブに評価される (task-3-review.md I2 fix) — ここは初期選択
    # そのものにオフセットがある単純ケース。
    dlg = ExportCsvDialog(
        _app_vm(),
        initial_selected={"csv_1::a"},
        x_range=(2.0, 9.0),
        cursor_a=3.0,
        cursor_b=6.0,
        offset_for=lambda _k: 1.0,
    )
    qtbot.addWidget(dlg)
    assert dlg._range_all.isEnabled() is True
    assert dlg._range_visible.isEnabled() is False
    assert dlg._range_cursor.isEnabled() is False
    assert dlg._range_visible.toolTip() == S.EXPORT_RANGE_OFFSET_TOOLTIP
    assert dlg._range_cursor.toolTip() == S.EXPORT_RANGE_OFFSET_TOOLTIP


def test_range_offset_reactive_to_checked_selection(qtbot: QtBot) -> None:
    """I2 の穴の回帰テスト (task-3-review.md #1): オフセットガードは開いた瞬間の
    静的スナップショットでなく "現在チェック中の選択集合" に対しリアクティブ —
    初期選択にオフセットが無くても、in-dialog で別ファイルのオフセット信号を
    追加チェックすると即座に disabled になり、外すと再度 enabled に戻る。
    """
    offsets = {"csv_2::speed": 1.0}
    dlg = ExportCsvDialog(
        _app_vm_two_files_same_bare(),
        initial_selected={"csv_1::rpm"},  # オフセット無し信号のみ -> 初期は enabled
        x_range=(2.0, 9.0),
        cursor_a=3.0,
        cursor_b=6.0,
        offset_for=lambda k: offsets.get(k, 0.0),
    )
    qtbot.addWidget(dlg)
    assert dlg._range_visible.isEnabled() is True
    assert dlg._range_cursor.isEnabled() is True
    assert dlg._range_visible.toolTip() == ""
    assert dlg._range_cursor.toolTip() == ""

    target = next(c for c in dlg._iter_children() if c.text(0) == "speed (csv_2)")
    target.setCheckState(0, Qt.CheckState.Checked)  # in-dialog: 別ファイルの信号を追加
    assert dlg._range_visible.isEnabled() is False
    assert dlg._range_cursor.isEnabled() is False
    assert dlg._range_visible.toolTip() == S.EXPORT_RANGE_OFFSET_TOOLTIP
    assert dlg._range_cursor.toolTip() == S.EXPORT_RANGE_OFFSET_TOOLTIP

    target.setCheckState(
        0, Qt.CheckState.Unchecked
    )  # 外すと再び enabled (リアクティブ)
    assert dlg._range_visible.isEnabled() is True
    assert dlg._range_cursor.isEnabled() is True
    assert dlg._range_visible.toolTip() == ""
    assert dlg._range_cursor.toolTip() == ""


def test_range_offset_ignores_unchecked_signals_elsewhere(qtbot: QtBot) -> None:
    """過保護でないことの検証: 他ファイルの信号がオフセットを持っていても、
    それが checked でない限り表示由来ラジオは enabled のまま (Option B の
    「オフセットが1つでも存在すれば無条件 disable」ではないこと)。
    """
    offsets = {"csv_2::speed": 1.0}
    dlg = ExportCsvDialog(
        _app_vm_two_files_same_bare(),
        initial_selected={"csv_1::rpm"},
        x_range=(2.0, 9.0),
        cursor_a=3.0,
        cursor_b=6.0,
        offset_for=lambda k: offsets.get(k, 0.0),
    )
    qtbot.addWidget(dlg)
    assert dlg._range_visible.isEnabled() is True
    assert dlg._range_cursor.isEnabled() is True


def test_range_offset_newly_checked_strands_selected_radio_to_all(
    qtbot: QtBot,
) -> None:
    """[現在の表示範囲] が checked のまま、in-dialog でオフセット信号を追加
    チェックして disabled になった場合、選択が [全期間] へフォールバックし
    _current_range() が無効な (disabled な) ラジオの値を読み続けないこと。
    """
    offsets = {"csv_2::speed": 1.0}
    dlg = ExportCsvDialog(
        _app_vm_two_files_same_bare(),
        initial_selected={"csv_1::rpm"},
        x_range=(2.0, 9.0),
        cursor_a=3.0,
        cursor_b=6.0,
        offset_for=lambda k: offsets.get(k, 0.0),
    )
    qtbot.addWidget(dlg)
    dlg._range_visible.setChecked(True)

    target = next(c for c in dlg._iter_children() if c.text(0) == "speed (csv_2)")
    target.setCheckState(0, Qt.CheckState.Checked)

    assert dlg._range_all.isChecked() is True
    assert dlg._range_visible.isChecked() is False
    opts = dlg._current_options()
    assert opts is not None
    assert opts.time_start is None
    assert opts.time_end is None


# --- F-0/UX-28: DI 後方互換 (既定 None で従来動作) --------------------------


def test_dialog_constructs_without_range_kwargs(qtbot: QtBot) -> None:
    # 既存の直接構築 (撮影ツール・旧テスト) が TypeError にならないこと。
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"})
    qtbot.addWidget(dlg)
    assert dlg._range_all.isChecked() is True


def test_ask_accepts_no_range_kwargs(qtbot: QtBot, monkeypatch, tmp_path: Path) -> None:
    # .ask() も同様に既定 None のみで動作すること (キーワード引数を渡さない)。
    # exec() はモーダルループなので、accept 相当を注入して自動確定させる
    # (test_ask_builds_request_from_widgets と異なり .ask() 自体の署名を叩く
    # ため dlg インスタンスへ事前アクセスできない — exec を差し替える)。
    target = tmp_path / "out.csv"

    def _auto_accept(self: ExportCsvDialog) -> QDialog.DialogCode:
        self._save_path_provider = lambda: str(target)
        self._on_accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExportCsvDialog, "exec", _auto_accept)
    req = ExportCsvDialog.ask(_app_vm(), {"csv_1::a"})
    assert isinstance(req, ExportRequest)
    assert req.options.time_start is None
    assert req.options.time_end is None


# --- F-0/UX-28: 選択数フッター ------------------------------------------------


def test_selection_footer_shows_initial_count(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"})
    qtbot.addWidget(dlg)
    assert dlg._selection_label.text() == S.EXPORT_SELECTION_COUNT_TMPL.format(n=1)


def test_selection_footer_updates_on_select_all_and_none(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected=set())
    qtbot.addWidget(dlg)
    assert dlg._selection_label.text() == S.EXPORT_SELECTION_COUNT_TMPL.format(n=0)
    dlg._select_all()
    assert dlg._selection_label.text() == S.EXPORT_SELECTION_COUNT_TMPL.format(n=2)
    dlg._select_none()
    assert dlg._selection_label.text() == S.EXPORT_SELECTION_COUNT_TMPL.format(n=0)


def test_selection_footer_is_filter_independent(qtbot: QtBot) -> None:
    """sabotage anchor (Step 5): フッターは総選択数であり可視数ではない。

    _apply_filter は _validate() を再発火しないため、フィルタ直後の値据え置き
    だけでは可視数実装と総数実装を判別できない (両実装とも直前の _validate()
    値のまま)。判別するには「フィルタ中に _validate() を再発火させ、非表示行
    (rpm) が選択状態に寄与するか」を見る必要がある — 可視のチェック項目を1つ
    解除して再チェックする (itemChanged→_validate 相乗り・正味の選択数は不変)。
    可視数実装は非表示の rpm を勘定に入れず「2」を報告して RED になる
    (実装時に手動でこの書き換えを行い RED を実証した。report 参照)。
    """
    dlg = ExportCsvDialog(_app_vm_two_files_same_bare(), initial_selected=set())
    qtbot.addWidget(dlg)
    dlg._select_all()  # rpm・speed(csv_1)・speed(csv_2) の3件が選択済み
    dlg._filter.setText("speed")  # "rpm" は隠れるが選択状態はチェックのまま
    visible = [c for c in dlg._iter_children() if not c.isHidden()]
    assert len(visible) == 2  # 可視は "speed" 系の2件のみ (rpm は隠れる)
    visible[0].setCheckState(0, Qt.CheckState.Unchecked)
    visible[0].setCheckState(0, Qt.CheckState.Checked)  # 正味不変・_validate 再発火
    # 総選択数は不変 (3) のまま — 出力集合 (_checked_keys) と一致する。
    assert dlg._selection_label.text() == S.EXPORT_SELECTION_COUNT_TMPL.format(n=3)
    assert len(dlg._checked_keys()) == 3


# --- E-3/U1: 列の遅延展開 -----------------------------------------------------


def _array_app_vm(*, expanded: bool) -> _FakeAppVM:
    """Mat (3 列) + Clean (1 列) の 1 ファイル。

    expanded=True  … 反転前のローダー (列 Signal を 3 + 1 本)
    expanded=False … 反転後のローダー (物理チャンネル Signal を 1 + 1 本)
    どちらでもダイアログは「Mat (親・3 列) / Clean (葉)」を出さねばならない。
    この 2 形を両方 GREEN にできることが、T6 の反転を跨いでこのテストが
    生き残る根拠 (反転時に fixture を書き換えなくてよい)。
    """
    columns = {("mf4_1", "Mat"): ("Mat[0]", "Mat[1]", "Mat[2]")}
    clean = _sig("mf4_1::Clean", phys="Clean")
    if expanded:
        group = [
            _sig("mf4_1::Mat[0]", phys="Mat"),
            _sig("mf4_1::Mat[1]", phys="Mat"),
            _sig("mf4_1::Mat[2]", phys="Mat"),
            clean,
        ]
        resolvable = {s.name: s for s in group}
    else:
        group = [_sig("mf4_1::Mat", phys="Mat"), clean]
        resolvable = {
            "mf4_1::Mat[0]": _sig("mf4_1::Mat[0]", phys="Mat"),
            "mf4_1::Mat[1]": _sig("mf4_1::Mat[1]", phys="Mat"),
            "mf4_1::Mat[2]": _sig("mf4_1::Mat[2]", phys="Mat"),
            "mf4_1::Clean": clean,
        }
    sess = _FakeSession({"mf4_1": group}, {"mf4_1": "mat2d.mf4"}, columns, resolvable)
    return _FakeAppVM(sess, ["mf4_1"])


def _row_named(dlg: ExportCsvDialog, text: str) -> QTreeWidgetItem:
    return next(r for r in dlg._iter_rows() if r.text(0) == text)


def _child_texts(item: QTreeWidgetItem) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


def _delegate_toggle(tree: QTreeWidget, item: QTreeWidgetItem) -> bool:
    """チェックボックスを 1 回「クリック」する (実クリックと同じ Qt の経路)。

    `QStyledItemDelegate.editorEvent` は `ItemIsUserTristate` の無いアイテムに対し
    ``state = (state == Checked) ? Unchecked : Checked`` — つまり **今表示されて
    いる状態から** 次の状態を決める。テストが Checked/Unchecked を自分で決めて
    `setCheckState` すると、この決定規則ごと迂回してしまい「PartiallyChecked に
    貼り付いたチェックボックスが 2 回目以降も Checked を書き続ける = 一方通行に
    なる」というクラスのバグ (E-3 レビュー Important) を構造的に観測できない。
    ここでは Qt の実装をそのまま呼ぶ (規則を書き写さない)。

    入力は Key_Space — `editorEvent` が受理する入力の一つで、マウス版と違って
    チェックボックス矩形の座標計算 (スタイル依存) に結果が左右されない。
    戻り値は「トグルが受理されたか」= ItemIsUserCheckable の有無がそのまま出る
    ので、C-a (コンテナ行はクリックで変えられない) の検証にも同じ口を使える。
    """
    index = tree.indexFromItem(item, 0)
    option = QStyleOptionViewItem()
    option.rect = tree.visualRect(index)
    option.state |= QStyle.StateFlag.State_Enabled
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier
    )
    delegate = tree.itemDelegateForIndex(index)
    assert delegate is not None
    return bool(delegate.editorEvent(event, tree.model(), option, index))


@pytest.mark.parametrize("expanded", [True, False])
def test_container_row_synthesizes_columns_on_expand(
    qtbot: QtBot, expanded: bool
) -> None:
    """U1: 親は未展開のままプレースホルダ 1 個だけを持ち、展開した瞬間に列が出る。

    prod は 4,324 行 / 264,004 列。expandAll() で全列アイテムを同期構築するのが
    ダイアログを開くだけで固まる原因だった。
    """
    dlg = ExportCsvDialog(_array_app_vm(expanded=expanded), initial_selected=set())
    qtbot.addWidget(dlg)
    mat = _row_named(dlg, "Mat")
    assert mat.childCount() == 1  # プレースホルダのみ
    assert mat.child(0).data(0, Qt.ItemDataRole.UserRole) is None  # 実列ではない

    dlg._tree.expandItem(mat)

    assert _child_texts(mat) == ["Mat[0]", "Mat[1]", "Mat[2]"]
    assert [
        mat.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(mat.childCount())
    ] == ["mf4_1::Mat[0]", "mf4_1::Mat[1]", "mf4_1::Mat[2]"]


@pytest.mark.parametrize("expanded", [True, False])
def test_select_all_does_not_mint_any_column(qtbot: QtBot, expanded: bool) -> None:
    """C-b: 「すべて選択」は列キーを **名前だけ** で組む (resolve を呼ばない)。

    ここで鋳造すると prod で 264k 本の Signal = ~390 MB の一撃になる
    (E-3 が剥がしているコストそのもの)。
    """
    app_vm = _array_app_vm(expanded=expanded)
    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)
    assert app_vm.session.resolve_calls == 0  # 開くだけでは鋳造しない

    dlg._select_all()

    assert set(dlg._checked_keys()) == {
        "mf4_1::Mat[0]",
        "mf4_1::Mat[1]",
        "mf4_1::Mat[2]",
        "mf4_1::Clean",
    }
    assert app_vm.session.resolve_calls == 0


@pytest.mark.parametrize("expanded", [True, False])
def test_initial_selection_expands_the_owning_row(qtbot: QtBot, expanded: bool) -> None:
    """initial_selected の列を持つ親は開いた状態で開く (従来の「開いたら選択済み」)。"""
    dlg = ExportCsvDialog(
        _array_app_vm(expanded=expanded), initial_selected={"mf4_1::Mat[1]"}
    )
    qtbot.addWidget(dlg)
    mat = _row_named(dlg, "Mat")
    assert mat.isExpanded()
    assert _child_texts(mat) == ["Mat[0]", "Mat[1]", "Mat[2]"]
    assert [
        mat.child(i).text(0)
        for i in range(mat.childCount())
        if mat.child(i).checkState(0) == Qt.CheckState.Checked
    ] == ["Mat[1]"]
    assert dlg._checked_keys() == ["mf4_1::Mat[1]"]
    # C-a: 一部だけ選択されている親は部分チェック表示になる
    assert mat.checkState(0) == Qt.CheckState.PartiallyChecked
    # 他の行 (Clean) は開かない = 巻き込みで列を作らない
    assert _row_named(dlg, "Clean").childCount() == 0


@pytest.mark.parametrize("expanded", [True, False])
def test_channel_row_is_a_tristate_container_not_checkable(
    qtbot: QtBot, expanded: bool
) -> None:
    """C-a: 物理チャンネル行はチェック **不可**。三態表示だけを持つ。

    「親をチェック = 全列エクスポート」を許すと 264k 鋳造の一撃になる。

    I-2: ただし行は enabled のままチェック標識を普通の見た目で描くので、理由が
    無いと「押しても無反応」の無音拒否になる (`ItemIsUserCheckable` は
    `editorEvent` からしか参照されない)。増分B の規約 (拒否は理由つき) に合わせて
    ツールチップで説明する。sabotage: setToolTip を落とすと当該 assert が RED。
    """
    dlg = ExportCsvDialog(_array_app_vm(expanded=expanded), initial_selected=set())
    qtbot.addWidget(dlg)
    mat = _row_named(dlg, "Mat")
    clean = _row_named(dlg, "Clean")
    assert not (mat.flags() & Qt.ItemFlag.ItemIsUserCheckable)
    assert mat.data(0, Qt.ItemDataRole.UserRole) is None  # 親は列キーを持たない
    assert mat.checkState(0) == Qt.CheckState.Unchecked  # 三態表示自体は持つ
    assert mat.flags() & Qt.ItemFlag.ItemIsEnabled  # 灰色にはしない (展開できる行)
    assert mat.toolTip(0) == S.EXPORT_CONTAINER_ROW_TOOLTIP
    # 1 列の物理チャンネルは従来どおり葉 (チェック可能・実列キー)
    assert clean.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert clean.data(0, Qt.ItemDataRole.UserRole) == "mf4_1::Clean"
    assert clean.toolTip(0) == ""  # 押せる行に理由は要らない (assert の非空虚化)


@pytest.mark.parametrize("expanded", [True, False])
def test_file_row_check_cannot_fake_container_selection(
    qtbot: QtBot, expanded: bool
) -> None:
    """C-a の抜け道: ファイル行のチェックは Qt の三態伝播でコンテナ行まで届く。

    ファイル行は ItemIsAutoTristate なので、そのチェックボックスを押すと
    QTreeWidgetItem が「CheckState を持つ子」を **チェック可能かどうかに関係なく**
    書き換える。コンテナから ItemIsUserCheckable を外してもこの経路は塞げない
    ので、放置すると「親は Checked に見えるのに選択集合は空」という嘘になる
    (実測: 受け口が無いと Mat=Checked / _checked_keys()=['mf4_1::Clean'])。
    表示は常に選択の写像であること — これが本テストの不変条件。

    **supersede (E-3 レビュー Important)**: 旧版はこの伝播を「コンテナ行の表示を
    Unchecked へ引き戻す」ことで塞ぎ、`Mat == Unchecked` /
    `_checked_keys() == ['mf4_1::Clean']` を pin していた。それは写像としては
    正しいがファイル行を PartiallyChecked に貼り付かせ、チェックボックスを
    一方通行 (二度と Checked にならず解除にも使えない) にしていた。正しい塞ぎ方は
    伝播を **選択そのもの** へ翻訳すること = ファイル行チェックはそのファイルの
    全列を選ぶ。写像であることの検証は弱めず、両方向 (表示 -> 選択集合、
    選択集合 -> 表示) で見る。往復の pin は
    test_file_row_checkbox_toggles_both_ways_through_the_delegate。
    """
    dlg = ExportCsvDialog(_array_app_vm(expanded=expanded), initial_selected=set())
    qtbot.addWidget(dlg)
    top = dlg._tree.topLevelItem(0)
    assert top is not None

    top.setCheckState(0, Qt.CheckState.Checked)  # ファイル行のチェックボックス

    mat = _row_named(dlg, "Mat")
    assert mat.checkState(0) == Qt.CheckState.Checked
    # Checked と見えている以上、その 3 列は本当に選択集合に入っていること
    # (旧版が禁じていた「見た目だけ Checked」は依然として不可)。
    assert dlg._checked_keys() == [
        "mf4_1::Mat[0]",
        "mf4_1::Mat[1]",
        "mf4_1::Mat[2]",
        "mf4_1::Clean",
    ]
    assert dlg._selection_label.text() == S.EXPORT_SELECTION_COUNT_TMPL.format(n=4)


@pytest.mark.parametrize("expanded", [True, False])
def test_file_row_checkbox_toggles_both_ways_through_the_delegate(
    qtbot: QtBot, expanded: bool
) -> None:
    """ファイル行のチェックボックスは **二方向** に効く (押せば全選択・もう一度で全解除)。

    1 クリックだけでは正常と故障を区別できない。故障形は「1 回目は選ばれたように
    見えるが、ファイル行が PartiallyChecked に貼り付いて 2 回目以降も Checked を
    書き続ける = 解除に使えない一方通行」だったので、**2 回押して往復する** ことが
    このテストの核心 (E-3 レビュー Important)。

    配列/構造体チャンネル (コンテナ) と スカラー が混在するファイルでのみ再現する:
    スカラーだけのファイルは全ての葉がチェック可能なのでファイル行が Checked に
    到達でき、壊れていても往復してしまう。

    C-b も同時に固定する — 往復のどちらでも列 Signal は 1 本も鋳造しない。
    """
    app_vm = _array_app_vm(expanded=expanded)
    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)
    top = dlg._tree.topLevelItem(0)
    assert top is not None
    mat = _row_named(dlg, "Mat")  # 3 列コンテナ
    clean = _row_named(dlg, "Clean")  # 1 列 (葉)
    all_keys = [
        "mf4_1::Mat[0]",
        "mf4_1::Mat[1]",
        "mf4_1::Mat[2]",
        "mf4_1::Clean",
    ]

    assert _delegate_toggle(dlg._tree, top) is True  # 1 回目

    assert top.checkState(0) == Qt.CheckState.Checked
    assert mat.checkState(0) == Qt.CheckState.Checked  # 全列が選ばれた表示
    assert clean.checkState(0) == Qt.CheckState.Checked
    assert dlg._checked_keys() == all_keys
    assert dlg._selection_label.text() == S.EXPORT_SELECTION_COUNT_TMPL.format(n=4)
    assert app_vm.session.resolve_calls == 0  # C-b: 名前だけで組む

    assert _delegate_toggle(dlg._tree, top) is True  # 2 回目 = 解除

    assert top.checkState(0) == Qt.CheckState.Unchecked
    assert mat.checkState(0) == Qt.CheckState.Unchecked
    assert clean.checkState(0) == Qt.CheckState.Unchecked
    assert dlg._checked_keys() == []
    assert dlg._selection_label.text() == S.EXPORT_SELECTION_COUNT_TMPL.format(n=0)
    assert app_vm.session.resolve_calls == 0


@pytest.mark.parametrize("expanded", [True, False])
def test_file_row_check_from_partial_selects_everything(
    qtbot: QtBot, expanded: bool
) -> None:
    """部分選択のファイル行を押すと全列が選択される (途中状態からの復帰)。

    Qt の罠: `QTreeWidgetItem.setData` は保存済みの値と同じ値を書かれると
    **自分の itemChanged を出さずに return する** — が、子への伝播はその前に
    済んでいる。ファイル行自身の itemChanged に処理をぶら下げる実装はこの経路
    (保存値 Checked / 表示 PartiallyChecked で押された瞬間) だけ沈黙し、
    コンテナが Checked に見えるのに選択集合が空、という嘘が残る。
    """
    app_vm = _array_app_vm(expanded=expanded)
    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)
    top = dlg._tree.topLevelItem(0)
    assert top is not None
    mat = _row_named(dlg, "Mat")

    _delegate_toggle(dlg._tree, top)  # 全選択 (ファイル行の保存値 = Checked)
    dlg._tree.expandItem(mat)
    mat.child(1).setCheckState(0, Qt.CheckState.Unchecked)  # 1 列だけ外す
    assert mat.checkState(0) == Qt.CheckState.PartiallyChecked
    assert top.checkState(0) == Qt.CheckState.PartiallyChecked

    assert _delegate_toggle(dlg._tree, top) is True  # 部分状態から押し直す

    assert top.checkState(0) == Qt.CheckState.Checked
    assert mat.checkState(0) == Qt.CheckState.Checked
    assert dlg._checked_keys() == [
        "mf4_1::Mat[0]",
        "mf4_1::Mat[1]",
        "mf4_1::Mat[2]",
        "mf4_1::Clean",
    ]
    assert app_vm.session.resolve_calls == 0


@pytest.mark.parametrize("expanded", [True, False])
def test_offset_guard_follows_bulk_select_and_deselect(
    qtbot: QtBot, expanded: bool
) -> None:
    """I2 オフセットガードは一括操作 (ファイル行 / すべて選択 / 解除) にも追随する。

    `_offset_active_for_checked` は「毎回 `_selected` を走査」から「キーが入る
    瞬間に 1 度だけ問い合わせて覚える」へ変わった (ファイル行 1 クリックは行ごとに
    `_validate()` を通るので、走査したままだと prod で 行数 x 列数 回の
    `offset_for` 呼び出しになる)。覚え書きの取りこぼし / 消し忘れは、まとめて
    入れてまとめて出す経路にだけ現れる。
    """
    app_vm = _array_app_vm(expanded=expanded)
    dlg = ExportCsvDialog(
        app_vm,
        initial_selected=set(),
        x_range=(2.0, 9.0),
        cursor_a=3.0,
        cursor_b=6.0,
        offset_for=lambda k: 1.0 if k == "mf4_1::Mat[1]" else 0.0,
    )
    qtbot.addWidget(dlg)
    top = dlg._tree.topLevelItem(0)
    assert top is not None
    assert dlg._range_visible.isEnabled() is True  # 未選択 = ガード非作動

    _delegate_toggle(dlg._tree, top)  # ファイル行で全選択 (未展開の列も入る)
    assert dlg._range_visible.isEnabled() is False
    assert dlg._range_cursor.isEnabled() is False

    _delegate_toggle(dlg._tree, top)  # もう一度押して全解除
    assert dlg._range_visible.isEnabled() is True
    assert dlg._range_cursor.isEnabled() is True

    dlg._select_all()
    assert dlg._range_visible.isEnabled() is False

    dlg._select_none()
    assert dlg._range_visible.isEnabled() is True


@pytest.mark.parametrize("expanded", [True, False])
def test_container_row_checkbox_click_is_refused(qtbot: QtBot, expanded: bool) -> None:
    """C-a: 物理チャンネル行のチェックボックスは **直接クリックしても変わらない**。

    ファイル行経由の一括選択 (上の 2 テスト) を通した後も、コンテナ行そのものを
    押す経路は塞がれたままであること — `ItemIsUserCheckable` が無いので
    `editorEvent` が受理しない (False) = 選択集合も表示も動かない。
    """
    app_vm = _array_app_vm(expanded=expanded)
    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)
    mat = _row_named(dlg, "Mat")

    assert _delegate_toggle(dlg._tree, mat) is False

    assert mat.checkState(0) == Qt.CheckState.Unchecked
    assert dlg._checked_keys() == []
    assert app_vm.session.resolve_calls == 0


@pytest.mark.parametrize("expanded", [True, False])
def test_filter_matches_column_names_of_unexpanded_rows(
    qtbot: QtBot, expanded: bool
) -> None:
    """フィルタは列名にマッチする — 親が未展開でも (ChannelBrowser と同じ規則)。"""
    dlg = ExportCsvDialog(_array_app_vm(expanded=expanded), initial_selected=set())
    qtbot.addWidget(dlg)

    dlg._filter.setText("mat[1")

    mat = _row_named(dlg, "Mat")
    assert not mat.isHidden()  # 未展開でも列名で生き残る
    assert _row_named(dlg, "Clean").isHidden()
    dlg._tree.expandItem(mat)
    assert [
        mat.child(i).text(0)
        for i in range(mat.childCount())
        if not mat.child(i).isHidden()
    ] == ["Mat[1]"]


@pytest.mark.parametrize("expanded", [True, False])
def test_accept_resolves_only_the_selected_columns(
    qtbot: QtBot, tmp_path: Path, expanded: bool
) -> None:
    """C-b: 実体化は出口で 1 列ずつ。選んでいない列は鋳造しない。"""
    app_vm = _array_app_vm(expanded=expanded)
    dlg = ExportCsvDialog(app_vm, initial_selected={"mf4_1::Mat[1]"})
    qtbot.addWidget(dlg)
    target = tmp_path / "out.csv"
    dlg._save_path_provider = lambda: str(target)

    dlg._on_accept()

    req = dlg._result
    assert isinstance(req, ExportRequest)
    # E-4b Task 4 supersede: 要求は **列キー** を運ぶ (D1・spec §5.2)。右辺は不変。
    assert list(req.keys) == ["mf4_1::Mat[1]"]
    assert app_vm.session.resolve_calls == 1


def test_unresolvable_column_reports_instead_of_raising(qtbot: QtBot) -> None:
    """旧実装は self._sig_by_key[k] が素の KeyError でダイアログごと落ちた
    (spec「壊れる消費者」3 = 唯一のハード失敗)。無言で列を落とすのも
    「選んだのに出ていない CSV」になるので、出力せず理由を出す。
    """
    app_vm = _array_app_vm(expanded=False)
    app_vm.session.resolvable.pop("mf4_1::Mat[1]")
    dlg = ExportCsvDialog(app_vm, initial_selected={"mf4_1::Mat[1]"})
    qtbot.addWidget(dlg)
    asked: list[str] = []

    def _never() -> str:
        asked.append("asked")
        return ""

    dlg._save_path_provider = _never

    dlg._on_accept()

    assert dlg._result is None
    assert asked == []  # 保存先を訊く前に落とす
    assert "Mat[1]" in dlg._error.text()


def test_checked_keys_follow_tree_order_not_hash_order(qtbot: QtBot) -> None:
    """出力列順は木の並び (ファイル順 -> ローダー順 -> 列順)。

    選択の真実が set になったので、素の sorted()/ハッシュ順で出すと CSV の
    列順がアルファベット順に化ける (Clean が Mat より前に来る) — 実行ごとに
    変わる形にもなりうる。
    """
    dlg = ExportCsvDialog(_array_app_vm(expanded=False), initial_selected=set())
    qtbot.addWidget(dlg)
    dlg._select_all()
    assert dlg._checked_keys() == [
        "mf4_1::Mat[0]",
        "mf4_1::Mat[1]",
        "mf4_1::Mat[2]",
        "mf4_1::Clean",
    ]


def test_real_mdf_array_channel_is_one_row_with_lazy_columns(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """実ローダー経路 (合成 fake ではない) で行構造と列合成を固定する。

    T6 の反転前は group_signals が列 Signal を、反転後は物理チャンネル Signal を
    返すが、どちらでも 2 行 (Mat 親 / Clean 葉) にならねばならない。
    """
    app_vm = AppViewModel()
    app_vm.request_load(write_mdf4_2d(tmp_path))  # MDF4 は format_def 不要
    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)

    assert [r.text(0) for r in dlg._iter_rows()] == ["Mat", "Clean"]
    mat = _row_named(dlg, "Mat")
    assert mat.childCount() == 1  # 未展開
    dlg._tree.expandItem(mat)
    assert _child_texts(mat) == ["Mat[0]", "Mat[1]", "Mat[2]"]

    dlg._select_all()
    keys = dlg._checked_keys()
    assert keys == [
        "mf4_1::Mat[0]",
        "mf4_1::Mat[1]",
        "mf4_1::Mat[2]",
        "mf4_1::Clean",
    ]
    for k in keys:  # 合成したキーは全て実 Signal に当たる (葉キーの不変条件)
        assert app_vm.session.resolve_signal(k) is not None


def test_dialog_never_materializes_signal_values(qtbot: QtBot, tmp_path: Path) -> None:
    """不変条件 (E-3): ダイアログは **名前** だけを扱い、値は 1 本も読まない。

    行や列の判定に sig.values が混ざると prod (4,324 行 / 264,004 列) では
    「ダイアログを開く = ファイル全体を読む」に化ける。honest observable は
    `_values_source.is_materialized` (ロード直後は全て False)。開く/展開する/
    絞り込む/すべて選択/**ファイル行の往復クリック** の全経路を通しても False の
    ままであること (最後の経路は E-3 レビュー Important の修正で追加)。
    """
    app_vm = AppViewModel()
    key = app_vm.request_load(write_mdf4_2d(tmp_path))
    assert not any(
        s._values_source.is_materialized for s in app_vm.session.group_signals(key)
    ), "前提: ロード直後は未展開 (この assert が落ちるなら観測点が無効)"

    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)
    dlg._tree.expandItem(_row_named(dlg, "Mat"))
    dlg._filter.setText("mat")
    dlg._select_all()
    top = dlg._tree.topLevelItem(0)
    assert top is not None
    _delegate_toggle(dlg._tree, top)  # ファイル行で全解除
    _delegate_toggle(dlg._tree, top)  # もう一度押して全選択

    assert not any(
        s._values_source.is_materialized for s in app_vm.session.group_signals(key)
    )


def test_real_csv_file_stays_flat(qtbot: QtBot, tmp_path: Path) -> None:
    """CSV は ColumnRecord を持たない = 1 列 1 物理チャンネル (E-2 と同じ扱い)。

    T1 の「未登録キーは (display_name,)」契約を消費者側から固定する
    (ここが崩れると CSV ファイルの行が丸ごと消えるか例外になる)。
    """
    csv = tmp_path / "run.csv"
    csv.write_text("t,speed\n0.0,10.0\n1.0,20.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    app_vm.request_load(
        csv,
        FormatDefinition(
            name="t5_fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)

    rows = list(dlg._iter_rows())
    assert [r.text(0) for r in rows] == ["speed"]
    assert rows[0].childCount() == 0  # 葉 = 展開矢印を出さない
    assert rows[0].data(0, Qt.ItemDataRole.UserRole) == "csv_1::speed"
