"""CursorReadout の差分更新: 行構成不変なら QLabel を再利用し setText で更新する(RN-06)。"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.statistics.range_stats import StatisticsResult
from valisync.gui.viewmodels.graph_panel_vm import DeltaReading
from valisync.gui.views.cursor_readout import CursorReadout


def _dr(name, color, va, dy, stats):
    return DeltaReading(name, color, va, dy, stats, True)


def _stats(mean, mx, mn, std, count):
    return StatisticsResult(mean=mean, max=mx, min=mn, std=std, count=count)


def test_diff_update_reuses_value_labels(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(0.0, 1.0, [_dr("s::a", "#111111", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10))])
    held = w._value_labels[0][0]  # 参照保持(id() 不使用)
    w.set_delta(0.0, 1.0, [_dr("s::a", "#111111", 2.0, 0.2, _stats(2, 3, 1, 0.6, 12))])
    assert w._value_labels[0][0] is held  # 再生成されず再利用
    assert "2" in w.row_texts()[0][1]  # 値は更新済み


def test_row_count_change_triggers_full_rebuild(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(0.0, 1.0, [_dr("s::a", "#111111", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10))])
    held = w._value_labels[0][0]
    w.set_delta(
        0.0,
        1.0,
        [
            _dr("s::a", "#111111", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10)),
            _dr("s::b", "#222222", 5.0, 0.3, _stats(5, 6, 4, 0.7, 10)),
        ],
    )
    assert w._value_labels[0][0] is not held  # 構造変化 → 全再構築


def test_color_change_updates_swatch_in_place(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(0.0, 1.0, [_dr("s::a", "#111111", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10))])
    held = w._swatch_labels[0]
    w.set_delta(0.0, 1.0, [_dr("s::a", "#f9e2af", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10))])
    assert w._swatch_labels[0] is held  # swatch も再利用(色だけ差し替え)
    assert w._row_colors[0] == "#f9e2af"
