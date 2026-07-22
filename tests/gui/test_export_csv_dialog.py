from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Signal
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
