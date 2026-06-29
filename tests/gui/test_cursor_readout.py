"""CursorReadout フロート表ウィジェット (R15.2 読み取り面)。"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.statistics.range_stats import StatisticsResult
from valisync.gui.viewmodels.graph_panel_vm import CursorReading, DeltaReading
from valisync.gui.views.cursor_readout import CursorReadout


def test_set_readings_builds_one_row_per_signal(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings(
        [
            CursorReading("csv::vCar", "#1f77b4", 12.34, True),
            CursorReading("csv::aLong", "#ff7f0e", 0.56, True),
        ]
    )
    texts = w.row_texts()
    assert len(texts) == 2
    assert texts[0][0] == "csv::vCar"
    assert "12.34" in texts[0][1]


def test_out_of_range_shows_label(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings([CursorReading("csv::vCar", "#1f77b4", None, False)])
    assert w.row_texts()[0][1] == "範囲外"


def test_empty_readings_clears_rows(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings([CursorReading("csv::vCar", "#1f77b4", 1.0, True)])
    w.set_readings([])
    assert w.row_texts() == []


# ── R16/R17 new tests ─────────────────────────────────────────────────────────


def _stats(
    mean: float, mx: float, mn: float, std: float, count: int
) -> StatisticsResult:
    return StatisticsResult(mean=mean, max=mx, min=mn, std=std, count=count)


def test_global_header_shows_time(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(0.5, [CursorReading("csv::vCar", "#1f77b4", 12.3, True)])
    assert "0.5" in w.header_text()
    assert w.row_texts()[0][0] == "csv::vCar"


def test_delta_header_shows_ta_tb_dt(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5,
        0.75,
        [
            DeltaReading(
                "csv::vCar", "#1f77b4", 12.3, 4.5, _stats(10, 20, 5, 3, 100), True
            )
        ],
    )
    h = w.header_text()
    assert "0.5" in h and "0.75" in h and "0.25" in h  # t_a, t_b, Dt


def test_delta_columns_present(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5,
        0.75,
        [
            DeltaReading(
                "csv::vCar", "#1f77b4", 12.3, 4.5, _stats(10, 20, 5, 3, 100), True
            )
        ],
    )
    cols = w.column_headers()
    for c in ("A値", "Δy", "mean", "max", "min", "std", "count"):
        assert c in cols


def test_column_menu_hides_a_stat(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5,
        0.75,
        [
            DeltaReading(
                "csv::vCar", "#1f77b4", 12.3, 4.5, _stats(10, 20, 5, 3, 100), True
            )
        ],
    )
    menu = w.build_column_menu()
    # "std" のチェックを外す。実装は toggled(bool) を使うので
    # setChecked(False) だけでスロットが発火する。
    act = next(a for a in menu.actions() if a.text() == "std")
    act.setChecked(False)
    assert "std" not in w.column_headers()
    assert "std" not in w.visible_stats()


def test_delta_no_data_label(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5,
        0.5,
        [
            DeltaReading(
                "csv::vCar",
                "#1f77b4",
                None,
                None,
                _stats(*([float("nan")] * 4), 0),
                False,
            )
        ],  # type: ignore[arg-type]
    )
    joined = " ".join(t for row in w.row_texts() for t in row)
    assert "データなし" in joined


def test_global_then_delta_then_global_resets_columns(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5, 0.75, [DeltaReading("s", "#1f77b4", 1.0, 0.5, _stats(1, 2, 0, 1, 9), True)]
    )
    w.set_global(0.5, [CursorReading("s", "#1f77b4", 1.0, True)])
    # Global では統計列ヘッダを出さない
    assert "mean" not in w.column_headers()
