from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Signal
from valisync.gui import strings as S
from valisync.gui.views.export_csv_dialog import ExportCsvDialog, ExportRequest


class _FakeSession:
    def __init__(self, groups: dict[str, list[Signal]], names: dict[str, str]) -> None:
        self._groups = groups
        self._names = names

    def source_name(self, key: str) -> str:
        return self._names[key]

    def group_signals(self, key: str) -> list[Signal]:
        return self._groups[key]


class _FakeAppVM:
    def __init__(self, session: _FakeSession, keys: list[str]) -> None:
        self.session = session
        self.loaded_file_keys = keys


def _sig(name: str) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="CSV",
        bus_type="",
        source_file="",
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
    assert {s.name for s in req.signals} == {"csv_1::a", "csv_1::b"}
    assert req.output_path == target
    assert req.options.delimiter == ";"
    assert req.options.unit_row is True
    # E-0: header_names carries the bare display names (no collision — both
    # are from the same file "csv_1"), same order as req.signals/_checked_keys.
    assert req.options.header_names == ("a", "b")


# --- E-0: 葉テキスト/フィルタは display name (UX-19) -------------------------


def _leaf_texts(dlg: ExportCsvDialog) -> set[str]:
    return {c.text(0) for c in dlg._iter_children()}


def test_leaf_text_shows_bare_name_no_collision(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected=set())
    qtbot.addWidget(dlg)
    assert _leaf_texts(dlg) == {"a", "b"}  # not "csv_1::a"/"csv_1::b"
    assert set(dlg._checked_keys()) <= {"csv_1::a", "csv_1::b"}  # UserRole 不変


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
