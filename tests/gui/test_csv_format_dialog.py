from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.loaders.csv_format_detector import DetectedFormat
from valisync.core.models.format_def import Delimiter
from valisync.gui.views.csv_format_dialog import CsvFormatDialog


def _detected(**over: object) -> DetectedFormat:
    base: dict[str, object] = {
        "format": None,
        "name": "d",
        "delimiter": Delimiter.COMMA,
        "has_header": True,
        "has_unit_row": False,
        "timestamp_column": 0,
        "timestamp_unit": "sec",
        "signal_start_column": 1,
        "signal_end_column": 2,
        "preview_lines": ("t,speed,rpm", "0.0,1.0,10", "1.0,2.0,20"),
        "notes": (),
    }
    base.update(over)
    return DetectedFormat(**base)  # type: ignore[arg-type]


def test_dialog_prefills_from_detected(qtbot: QtBot) -> None:
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    assert dlg._delim.currentData() is Delimiter.COMMA
    assert dlg._header.isChecked() is True
    assert dlg._ts_col.value() == 0
    assert dlg._sig_start.value() == 1 and dlg._sig_end.value() == 2


def test_dialog_builds_format_from_fields(qtbot: QtBot) -> None:
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    fmt = dlg._current_format()
    assert fmt is not None
    assert fmt.delimiter is Delimiter.COMMA
    assert fmt.timestamp_column == 0
    assert fmt.signal_start_column == 1 and fmt.signal_end_column == 2


def test_dialog_invalid_overlap_disables_ok(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    dlg._ts_col.setValue(1)  # 時間列を信号列範囲 [1,2] に重ねる → 不変条件違反
    ok = dlg._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok.isEnabled() is False
    assert dlg._current_format() is None


def test_dialog_accept_sets_result_cancel_none(qtbot: QtBot) -> None:
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    dlg._on_accept()
    assert dlg._result is not None

    dlg2 = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg2)
    dlg2.reject()
    assert dlg2._result is None
