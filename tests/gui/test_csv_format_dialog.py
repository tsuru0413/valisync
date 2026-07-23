from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.loaders.csv_format_detector import DetectedFormat
from valisync.core.models.format_def import Delimiter
from valisync.gui.theme import tokens
from valisync.gui.views.csv_format_dialog import _TINT_ALPHA, CsvFormatDialog


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


# ── Step 1/5/8: 0 始まりヘッダ+列ハイライト (UX-05) ────────────────────────


def _header_labels(dlg: CsvFormatDialog) -> list[str]:
    return [
        dlg._preview.horizontalHeaderItem(ci).text()
        for ci in range(dlg._preview.columnCount())
    ]


def test_preview_header_is_zero_based_with_names_matching_spin_values(
    qtbot: QtBot,
) -> None:
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    assert _header_labels(dlg) == ["0: t", "1: speed", "2: rpm"]
    # スピン値 (0 始まり) と表記の数字部が一致 (off-by-one 消滅)。
    assert dlg._ts_col.value() == 0
    assert dlg._sig_start.value() == 1 and dlg._sig_end.value() == 2


def test_preview_header_is_zero_based_without_names_when_no_header(
    qtbot: QtBot,
) -> None:
    dlg = CsvFormatDialog(_detected(has_header=False))
    qtbot.addWidget(dlg)
    assert _header_labels(dlg) == ["0", "1", "2"]


def test_preview_header_ragged_first_row_no_indexerror(qtbot: QtBot) -> None:
    # rows[0] (ヘッダ行) が他行より短い — IndexError なくラベルは列数に追従。
    dlg = CsvFormatDialog(
        _detected(preview_lines=("t,speed", "0.0,1.0,10", "1.0,2.0,20"))
    )
    qtbot.addWidget(dlg)
    assert _header_labels(dlg) == ["0: t", "1: speed", "2"]


def test_preview_header_toggle_updates_name_part_live(qtbot: QtBot) -> None:
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    assert _header_labels(dlg) == ["0: t", "1: speed", "2: rpm"]
    dlg._header.setChecked(False)
    assert _header_labels(dlg) == ["0", "1", "2"]  # stale なし
    dlg._header.setChecked(True)
    assert _header_labels(dlg) == ["0: t", "1: speed", "2: rpm"]


def _cell_bg(dlg: CsvFormatDialog, row: int, col: int) -> tuple[int, int, int, int]:
    item = dlg._preview.item(row, col)
    assert item is not None
    brush = item.background()
    if brush.style() == Qt.BrushStyle.NoBrush:
        return (0, 0, 0, 0)
    c = brush.color()
    return (c.red(), c.green(), c.blue(), c.alpha())


def _expected_tint(color: tokens.Color) -> tuple[int, int, int, int]:
    return (color.r, color.g, color.b, _TINT_ALPHA)


def test_signal_columns_are_tinted_with_signal_highlight(qtbot: QtBot) -> None:
    dlg = CsvFormatDialog(_detected())  # ts=0, sig=[1,2]
    qtbot.addWidget(dlg)
    expected = _expected_tint(tokens.active().colors.chrome_signal_highlight)
    assert _cell_bg(dlg, 0, 1) == expected
    assert _cell_bg(dlg, 0, 2) == expected
    assert _cell_bg(dlg, 1, 1) == expected
    assert _cell_bg(dlg, 1, 2) == expected


def test_time_column_tint_moves_with_spin_and_old_column_untinted(
    qtbot: QtBot,
) -> None:
    dlg = CsvFormatDialog(_detected(signal_start_column=2, signal_end_column=2))
    qtbot.addWidget(dlg)
    ts_expected = _expected_tint(tokens.active().colors.chrome_cursor_a)
    assert _cell_bg(dlg, 0, 0) == ts_expected
    dlg._ts_col.setValue(2)
    # 旧時間列 (0) はもう時間ティントでない (信号範囲でもないので非着色)。
    assert _cell_bg(dlg, 0, 0) == (0, 0, 0, 0)
    assert _cell_bg(dlg, 0, 2) == ts_expected


def test_time_column_wins_when_overlapping_signal_range_transiently(
    qtbot: QtBot,
) -> None:
    dlg = CsvFormatDialog(_detected())  # ts=0, sig=[1,2]
    qtbot.addWidget(dlg)
    ts_expected = _expected_tint(tokens.active().colors.chrome_cursor_a)
    dlg._ts_col.setValue(
        1
    )  # 信号範囲 [1,2] に重なる過渡状態 (FormatDefinition 的には無効)
    assert _cell_bg(dlg, 0, 1) == ts_expected  # ts_col 勝ち


def test_highlight_sabotage_would_be_caught_by_live_wiring(qtbot: QtBot) -> None:
    """接続漏れ (valueChanged/stateChanged→_refresh 未配線) を検出する経路の存在確認。

    このテスト自体は正配線を前提にした GREEN 確認 — sabotage (RED 実証) は
    report に別途記録 (接続を一時的にコメントアウトして本テストが RED になることを確認)。
    """
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    before = _cell_bg(dlg, 0, 0)
    dlg._ts_col.setValue(2)
    after = _cell_bg(dlg, 0, 0)
    assert before != after  # 配線が生きていれば旧セルの色は変わる (0,0,0,0 へ)
