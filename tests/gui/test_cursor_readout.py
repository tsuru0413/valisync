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


def test_delta_column_headers_align_with_data_columns(qtbot: QtBot):
    """列見出しがデータセルと同一グリッド列に配置されることを検証する。

    以前のバグ: enumerate(["", *col_headers]) で見出しを col 0 から置いていたため
    "A値" ヘッダが col 1(name列)に落ち、データセルは col 2 にあるという1列ずれが発生。
    """
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
    grid = w._grid
    # ヘッダ行は row 0; データ列は grid col 2 から開始 (col 0=swatch, col 1=name)
    assert grid.itemAtPosition(0, 2) is not None, "A値 header widget missing at col 2"
    assert grid.itemAtPosition(0, 3) is not None, "Δy header widget missing at col 3"
    assert grid.itemAtPosition(0, 2).widget().text() == "A値"
    assert grid.itemAtPosition(0, 3).widget().text() == "Δy"
    # データ行 (row 1): A値 の値セルが見出しと同じ col 2 に置かれる
    assert grid.itemAtPosition(1, 2) is not None, (
        "A値 data cell missing at row 1, col 2"
    )
    assert grid.itemAtPosition(1, 2).widget().text() == "12.3"


# --- Task 5 (LD-07): value_labels 併記 ---


def test_readout_shows_label_alongside_value(qtbot: QtBot):
    """label が非 None のとき「値 (ラベル)」形式で併記される."""
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(
        1.0,
        [CursorReading("f::TurnSig", "#1f77b4", 1.0, True, label="LEFT")],
    )
    joined = " ".join(t for row in w.row_texts() for t in row)
    assert "1 (LEFT)" in joined


def test_readout_no_label_suffix_when_label_none(qtbot: QtBot):
    """label=None のときは従来どおり値だけ (括弧なし)."""
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(1.0, [CursorReading("csv::vCar", "#1f77b4", 1.0, True)])
    assert w.row_texts()[0][1] == "1"


def test_set_readings_after_set_global_hides_header(qtbot: QtBot):
    """set_global → set_readings 遷移で時刻ヘッダが非表示になることを検証する。

    isVisible() は親ウィジェットの表示状態に依存するため isHidden() で
    明示的な hide()/show() 状態を確認する。
    """
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(1.0, [CursorReading("csv::vCar", "#1f77b4", 5.0, True)])
    assert not w._header.isHidden()  # set_global が show() を呼んでいる
    w.set_readings([CursorReading("csv::vCar", "#1f77b4", 5.0, True)])
    assert w._header.isHidden()  # set_readings が hide() を呼んでいる
    assert w._header_text == ""


def test_delta_value_a_shows_label_dy_does_not(qtbot: QtBot):
    """Delta 表の A 値にラベル併記・Δy には付かない (spec §3.3)."""
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(
        0.5,
        0.75,
        [
            DeltaReading(
                "f::TurnSig",
                "#1f77b4",
                1.0,
                1.0,
                _stats(10, 20, 5, 3, 100),
                True,
                label="LEFT",
            )
        ],
    )
    joined = " ".join(w.row_texts()[0])
    assert "1 (LEFT)" in joined
    assert "+1 (LEFT)" not in joined  # dy 側には付かない


# --- Task 5 (PC-09): 補間方式ラベルの常時表示 ---


def test_set_global_header_includes_interp_label(qtbot: QtBot):
    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(
        1.5, [CursorReading("csv::a", "#fff", 3.0, True)], interp_label="線形"
    )
    assert "線形" in ro.header_text()


def test_set_delta_header_includes_interp_label(qtbot: QtBot):
    ro = CursorReadout()
    qtbot.addWidget(ro)
    stats = _stats(1.0, 2.0, 0.0, 0.5, 3)
    ro.set_delta(
        1.0,
        2.0,
        [DeltaReading("csv::a", "#fff", 1.0, 0.5, stats, True)],
        interp_label="最近傍",
    )
    assert "最近傍" in ro.header_text()


# --- Task 2 (PC-11/PC-16): 精度パラメータ・単位表示・interp_label 保持 ---


def test_precision_controls_value_digits(qtbot: QtBot):
    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(
        0.0,
        [CursorReading("csv::a", "#fff", 1.23456789, True, unit="km/h")],
        precision=4,
    )
    v4 = ro.row_texts()[0][1]
    ro.set_global(
        0.0,
        [CursorReading("csv::a", "#fff", 1.23456789, True, unit="km/h")],
        precision=8,
    )
    v8 = ro.row_texts()[0][1]
    assert v4 == "1.235"  # .4g
    assert v8 == "1.2345679"  # .8g
    assert v4 != v8  # 精度が効いている


def test_unit_shown_beside_name(qtbot: QtBot):
    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(0.0, [CursorReading("spd", "#fff", 1.0, True, unit="km/h")])
    assert "[km/h]" in ro.row_texts()[0][0]  # 名前セルに単位


def test_stat_toggle_reretains_interp_label(qtbot: QtBot):
    ro = CursorReadout()
    qtbot.addWidget(ro)
    stats = _stats(1.0, 2.0, 0.0, 0.5, 3)
    ro.set_delta(
        0.0,
        1.0,
        [DeltaReading("a", "#fff", 1.0, 0.5, stats, True, unit="km/h")],
        interp_label="線形",
        precision=6,
    )
    # legacy stat-toggle 再描画 (_on_stat_toggled 未 wire) で interp_label を欠落しない
    ro._toggle_stat("count", False)
    assert "線形" in ro.header_text()
