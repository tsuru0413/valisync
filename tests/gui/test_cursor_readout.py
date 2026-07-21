"""CursorReadout フロート表ウィジェット (R15.2 読み取り面)。"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.statistics.range_stats import StatisticsResult
from valisync.gui.viewmodels.graph_panel_vm import CursorReading, DeltaReading
from valisync.gui.views.cursor_readout import CursorReadout


def test_tall_pane_keeps_rows_compact(qtbot: QtBot):
    """常設ペインは背丈が高くても行を上部に詰める (行を縦に伸ばさない)。

    実機バグ (2026-07-20): splitter で縦に引き伸ばされると VBox 末尾の stretch 不在で
    余剰縦スペースが grid に配分され行が広がる。実プラットフォーム(Windows)では、
    伸びた行内で AlignRight の値セル(垂直センター喪失で top 揃え)と swatch/name
    (center 揃え)が縦に割れて崩れた。この行内割れは QGridLayout の既定 vcenter により
    headless では再現しない下流症状のため、ここでは**根因の行伸長**を「上部圧縮」で
    直接ガードする (addStretch で行が伸びない=割れも起きない)。縦中心一致は補助 assert。
    """
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    host = QWidget()
    QVBoxLayout(host).addWidget(w := CursorReadout())
    qtbot.addWidget(host)
    host.resize(320, 600)  # tall splitter pane を模す
    host.show()
    qtbot.waitExposed(host)
    w.set_global(
        1.0,
        [
            CursorReading(
                "A", "#111111", 10.0, True, entry_id=1, range_lo=0.0, range_hi=20.0
            ),
            CursorReading(
                "B", "#222222", 30.0, True, entry_id=2, range_lo=0.0, range_hi=40.0
            ),
        ],
    )
    for _ in range(3):
        qtbot.wait(1)
    # 行内整列: 同一行の swatch と値セルの縦中心が一致する (割れていない)
    sw_y = w._swatch_labels[0].geometry().center().y()
    val_y = w._value_labels[0][0].geometry().center().y()
    assert abs(sw_y - val_y) <= 4, f"row0 swatch({sw_y}) と値({val_y}) が縦にずれている"
    # 上部圧縮: 最終行の底が host 高さの半分より十分上 (縦に散らばっていない)
    assert w._swatch_labels[-1].geometry().bottom() < 250, (
        "行が縦に広がって散らばっている"
    )


def test_pane_background_paints_as_child_widget(qtbot: QtBot):
    """QSS 背景が『子ウィジェット』として実描画される (WA_StyledBackground)。

    素の QWidget サブクラスは属性なしだと子として QSS background/border を
    描かず親の背景が透ける (Qt 仕様 — top-level は背景消去経路で描かれるため
    単体 grab では見逃す)。増分1 のデバッグテーマ検証で発覚した実バグ。
    ペイン化後 (Task 3) は #ReadoutPane・surface_readout_panel が対象。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    from valisync.gui.theme.tokens import active

    parent = QWidget()
    parent.setStyleSheet("background: #00ff00;")  # 蛍光緑 — 透けたら即検出
    parent.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    parent.resize(400, 200)
    qtbot.addWidget(parent)
    w = CursorReadout(parent)
    assert w.objectName() == "ReadoutPane"
    w.set_global(1.0, [CursorReading("csv::vCar", "#1f77b4", 12.3, True)])
    w.move(50, 50)
    w.setVisible(True)
    w.adjustSize()
    parent.show()
    img = parent.grab().toImage()
    inner = img.pixelColor(50 + w.width() // 2, 50 + w.height() - 4)
    assert inner.name() != "#00ff00", "ペイン背景が描画されず親の緑が透けている"
    # surface_readout_panel は不透明 (alpha 255) — 緑を完全に覆う
    panel = active().colors.surface_readout_panel
    assert abs(inner.red() - panel.r) < 12 and abs(inner.blue() - panel.b) < 12


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


def test_delta_header_shows_ta_and_tb_labeled(qtbot: QtBot):
    """UX-48: ヘッダは 'A <t_a> ・ B <t_b>' のラベル付き書式。

    Δt はステータスバー左の即値 (spec §2.4) と重複するためヘッダから意図的に
    除外 (spec §2.5) -- ここで非表示を lock する (旧仕様への先祖返り防止)。
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
    h = w.header_text()
    assert h == "A 0.500 s ・ B 0.750 s"


def test_time_header_uses_fixed_3dp_and_subms_delta_rounds_to_zero(qtbot: QtBot):
    """時刻ヘッダは固定小数3桁 (.3f)。ヘッダに Δt ラベルは無いが、A/B いずれも同じ
    _fmt_time を通るため、サブ ms 差 (0.5ms 未満) の A/B は表示上 同一の丸め値
    になる -- 「Δt が 0.000 s に丸まる」の観測可能な現れ。意図的な許容であり
    バグではない (スナップ運用外のエッジ・spec §2.5)。"""
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(100.0345678, [CursorReading("csv::vCar", "#1f77b4", 1.0, True)])
    assert w.header_text() == "A 100.035 s"
    w.set_delta(
        1.0,
        1.0002,  # サブ ms 差分 (0.2ms)
        [DeltaReading("csv::vCar", "#1f77b4", 1.0, 0.0, _stats(1, 1, 1, 0, 1), True)],
    )
    assert w.header_text() == "A 1.000 s ・ B 1.000 s"


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


def test_table_tsv_global(qtbot: QtBot):
    """set_global の TSV は min/max 独立2列を含む (計測 IA spec §2.6: UX-25/33)。"""
    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(
        0.0,
        [
            CursorReading("spd", "#fff", 1.5, True, unit="km/h"),
            CursorReading("rpm", "#fff", 800.0, True),
        ],
        precision=6,
    )
    tsv = ro.table_tsv()
    lines = tsv.splitlines()
    assert lines[0].split("\t") == [
        "信号",
        "A値",
        "min（全区間）",
        "max（全区間）",
    ]
    assert lines[1].split("\t") == ["spd [km/h]", "1.5", "", ""]
    assert lines[2].split("\t") == ["rpm", "800", "", ""]


def test_table_tsv_delta_reflects_visible_stats(qtbot: QtBot):
    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.sync_visible_stats({"mean"})  # count 等を非表示
    stats = _stats(2.0, 3.0, 1.0, 0.5, 4)
    ro.set_delta(
        0.0,
        1.0,
        [DeltaReading("a", "#fff", 1.0, 0.5, stats, True)],
        precision=6,
    )
    header = ro.table_tsv().splitlines()[0].split("\t")
    assert header == ["信号", "A値", "Δy", "mean"]  # 表示中の列のみ


def _readout_menu_items(ro):
    menu = ro.build_readout_menu()
    return menu, {a.text(): a for a in menu.actions()}


def test_readout_menu_has_expected_items(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout

    ro = CursorReadout()
    qtbot.addWidget(ro)
    _menu, acts = _readout_menu_items(ro)
    assert "統計列" in acts
    assert "精度" in acts
    assert "表をコピー" in acts
    assert "カーソルを消す" in acts


def test_precision_submenu_exclusive_reflects_current(qtbot):
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading
    from valisync.gui.views.cursor_readout import CursorReadout

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(0.0, [CursorReading("a", "#fff", 1.0, True)], precision=6)
    _menu, acts = _readout_menu_items(ro)
    sub = acts["精度"].menu()
    pacts = {a.text(): a for a in sub.actions()}
    assert pacts["6"].isChecked() is True
    assert pacts["4"].isChecked() is False
    pacts["8"].setChecked(True)  # 排他効果
    assert pacts["6"].isChecked() is False


def test_precision_action_fires_callback(qtbot):
    from valisync.gui.viewmodels.graph_panel_vm import CursorReading
    from valisync.gui.views.cursor_readout import CursorReadout

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(0.0, [CursorReading("a", "#fff", 1.0, True)], precision=6)
    got: list[int] = []
    ro._on_precision = got.append
    _menu, acts = _readout_menu_items(ro)
    sub = acts["精度"].menu()
    next(a for a in sub.actions() if a.text() == "8").trigger()
    assert got == [8]


def test_copy_action_puts_tsv_on_clipboard(qtbot):
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.graph_panel_vm import CursorReading
    from valisync.gui.views.cursor_readout import CursorReadout

    ro = CursorReadout()
    qtbot.addWidget(ro)
    ro.set_global(0.0, [CursorReading("spd", "#fff", 1.5, True, unit="km/h")])
    _menu, acts = _readout_menu_items(ro)
    acts["表をコピー"].trigger()
    assert "spd [km/h]" in QApplication.clipboard().text()


def test_readout_menu_clear_fires_on_clear(qtbot):
    from valisync.gui.views.cursor_readout import CursorReadout

    ro = CursorReadout()
    qtbot.addWidget(ro)
    fired: list[bool] = []
    ro._on_clear = lambda: fired.append(True)
    _menu, acts = _readout_menu_items(ro)
    acts["カーソルを消す"].trigger()
    assert fired == [True]


def test_header_markers_and_pane_use_tokens(qtbot):
    """配線検証: readout がカーソル/ペインのトークンを消費する (凍結置換の対線)。"""
    from valisync.gui.theme import qss
    from valisync.gui.theme.tokens import active

    w = CursorReadout()
    qtbot.addWidget(w)
    c = active().colors
    w.set_delta(
        0.5, 0.75, [DeltaReading("s", "#123456", 1.0, 0.5, _stats(1, 2, 0, 1, 9), True)]
    )
    assert c.cursor_a.hex in w._header.text()
    assert c.cursor_b.hex in w._header.text()
    assert w.styleSheet() == qss.readout_panel()


# --- Task 3 (readout-pane 増分B): フロートチップ → 常設ペイン化 ---


def test_pane_object_name_and_no_close_button(qtbot: QtBot):
    """ペイン化: objectName=ReadoutPane・常時✕ボタンは撤去 (フロート廃止)。"""
    w = CursorReadout()
    qtbot.addWidget(w)
    assert w.objectName() == "ReadoutPane"
    assert not hasattr(w, "close_button")


def test_set_global_renders_minmax_column(qtbot: QtBot):
    """単一ファイル: 列 = 名前 | A値 | min(全区間) | max(全区間) (UX-25/33: 独立2列)。"""
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(
        1.0,
        [
            CursorReading(
                "vCar",
                "#1f77b4",
                12.3,
                True,
                entry_id=1,
                range_lo=0.0,
                range_hi=100.0,
            )
        ],
    )
    assert w.column_headers() == [
        "A値",
        "min（全区間）",
        "max（全区間）",
    ]
    # row_texts()[i] = (name, joined cells) - A値と min/max 両方を含む
    _name, cells = w.row_texts()[0]
    assert "12.3" in cells and "0" in cells and "100" in cells


def test_set_global_min_max_are_separate_right_aligned_columns(qtbot: QtBot):
    """min/max が独立2列で右揃えセルとして描かれることを grid 直接検査で確認する

    (row_texts() の joined 文字列だけでは「1列に融合 vs 2列独立」を区別できない
    ため、grid の列位置と alignment を直接見る)。
    """
    from PySide6.QtCore import Qt

    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(
        1.0,
        [
            CursorReading(
                "vCar", "#1f77b4", 12.3, True, entry_id=1, range_lo=0.0, range_hi=100.0
            )
        ],
    )
    a_cell = w._grid.itemAtPosition(1, 2).widget()
    min_cell = w._grid.itemAtPosition(1, 3).widget()
    max_cell = w._grid.itemAtPosition(1, 4).widget()
    assert a_cell.text() == "12.3"
    assert min_cell.text() == "0"
    assert max_cell.text() == "100"
    assert min_cell.alignment() & Qt.AlignmentFlag.AlignRight
    assert max_cell.alignment() & Qt.AlignmentFlag.AlignRight


def test_set_legend_renders_swatch_name_unit_no_columns(qtbot: QtBot):
    """凡例モード: 列ヘッダなし・値セルなし・スウォッチ+名前+[unit] のみ (spec §2.6)。"""
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_legend(
        [CursorReading("spd", "#1f77b4", None, False, unit="km/h", entry_id=3)]
    )
    assert w.column_headers() == []
    assert w._grid.itemAtPosition(0, 2) is None  # 列見出し行が無い
    assert w._grid.itemAtPosition(0, 1) is not None  # 名前セルは row 0
    name, cells = w.row_texts()[0]
    assert name == "spd [km/h]"
    assert cells == ""  # 値セルが無いので結合セルは空文字
    assert w._header.isHidden()  # 凡例モードは時刻ヘッダを表示しない


def test_legend_mode_hides_time_header(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(1.0, [CursorReading("a", "#fff", 1.0, True)])
    assert not w._header.isHidden()
    w.set_legend([CursorReading("a", "#fff", None, False)])
    assert w._header.isHidden()
    assert w.header_text() == ""


def test_legend_row_at_resolves_via_name_label(qtbot: QtBot):
    """凡例モード (値セルなし) でも _row_at が行を解決できる — 名前ラベルの
    geometry にフォールバックし、計測モードと同じ行クリック経路を共有する
    (spec §2.6: 行クリック→曲線ハイライトは両モードで機能)。
    """
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_legend([CursorReading("csv::vCar", "#1f77b4", None, False, entry_id=9)])
    pos = w._name_labels[0].geometry().center()
    assert w._row_at(pos) == 0


def test_legend_mode_row_click_activates_curve(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_legend([CursorReading("csv::vCar", "#1f77b4", None, False, entry_id=9)])
    seen: list[int] = []
    w.row_activated.connect(seen.append)
    w.activate_row(0)
    assert seen == [9]


def test_table_tsv_legend_has_no_value_column(qtbot: QtBot):
    """凡例モードの TSV は値列を持たない (計測モードの「値」フォールバックとの
    混同防止 — spec §2.6)。
    """
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_legend([CursorReading("spd", "#1f77b4", None, False, unit="km/h")])
    lines = w.table_tsv().splitlines()
    assert lines[0].split("\t") == ["信号"]
    assert lines[1].split("\t") == ["spd [km/h]"]


def test_show_placeholder_replaces_table(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings([CursorReading("csv::vCar", "#1f77b4", 12.3, True)])
    assert len(w.row_texts()) == 1
    w.show_placeholder("プロットをクリックしてカーソルを設置")
    assert w.row_texts() == []
    assert w.placeholder_text() == "プロットをクリックしてカーソルを設置"


def test_row_click_emits_entry_id(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_global(
        1.0,
        [CursorReading("csv::vCar", "#1f77b4", 12.3, True, entry_id=7)],
    )
    seen: list[int] = []
    w.row_activated.connect(seen.append)
    w.activate_row(0)  # プログラム的行トリガ (realgui は実クリックで検証)
    assert seen == [7]


def test_delta_dy_sign_colors_value_diverged(qtbot: QtBot):
    """Δy 正=delta_positive・負=delta_negative で着色。delta_negative は close_hover と
    同値の別役割なので、値を分岐させたテーマで set_delta の呼び出し経路が
    delta_negative(≠close_hover) を選ぶことを直接実証する(Task 1 レビュー Important
    対応: delta_value は恒等関数で誤配線は呼び出し側=このコードにあるため、ここが
    唯一の値分岐ガード)。"""
    import dataclasses

    from valisync.core.statistics.range_stats import StatisticsResult
    from valisync.gui.theme.tokens import DARK, Color, set_active

    # delta_negative を close_hover と別値へ分岐させたテーマを active に
    alt = dataclasses.replace(
        DARK,
        colors=dataclasses.replace(
            DARK.colors,
            delta_negative=Color(1, 2, 3),
            delta_positive=Color(4, 5, 6),
        ),
    )
    set_active(alt)
    try:
        w = CursorReadout()
        qtbot.addWidget(w)
        stats = StatisticsResult(mean=0, max=0, min=0, std=0, count=5)
        w.set_delta(
            1.0,
            2.0,
            [
                DeltaReading("up", "#111", 1.0, 3.0, stats, True, entry_id=1),
                DeltaReading("dn", "#222", 1.0, -3.0, stats, True, entry_id=2),
            ],
        )
        styles = w.dy_cell_styles()  # [(row_index, style_str), ...] introspection
        joined = " ".join(s for _i, s in styles)
        assert Color(4, 5, 6).hex in joined  # 正 → delta_positive
        assert Color(1, 2, 3).hex in joined  # 負 → delta_negative
        assert DARK.colors.close_hover.hex not in joined  # close_hover 誤配線でない
    finally:
        set_active(DARK)


def test_delta_negative_cell_uses_delta_negative_not_error(qtbot: QtBot):
    """delta_negative は error と同値の三つ組の一員 (spec §3・error==delta_negative)。

    error だけを分岐させたテーマで Δ負値セルの着色が delta_negative (未分岐の
    元値) のままであり、error 側へ誤配線していないことを直接実証する。
    """
    import dataclasses

    from valisync.core.statistics.range_stats import StatisticsResult
    from valisync.gui.theme.tokens import DARK, Color, set_active

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, error=Color(1, 2, 3))
    )
    set_active(alt)
    try:
        w = CursorReadout()
        qtbot.addWidget(w)
        stats = StatisticsResult(mean=0, max=0, min=0, std=0, count=5)
        w.set_delta(
            1.0,
            2.0,
            [DeltaReading("dn", "#222", 1.0, -3.0, stats, True, entry_id=1)],
        )
        styles = w.dy_cell_styles()
        joined = " ".join(s for _i, s in styles)
        assert DARK.colors.delta_negative.hex in joined  # 未分岐の元値のまま
        assert Color(1, 2, 3).hex not in joined  # error 誤配線でない
    finally:
        set_active(DARK)
