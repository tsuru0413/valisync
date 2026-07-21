"""GraphAreaView の読み値ペイン束縛 (readout-pane Task 4) — Layer B (headless).

CursorReadout 自体の描画/フォーマットは tests/gui/test_cursor_readout.py が担当する。
ここは GraphAreaView が「どのタブの、どのアクティブパネルの状態を」単一ペインへ
pull するかの配線 — アクティブパネル切替・プレースホルダ・表示トグル・行クリック
ハイライト・callback (clear/precision/stat-toggle) の委譲 — を検証する。

実 OS 入力での実クリック検証は Layer C (tests/realgui) へ別途移行する (Task 5)。
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.interpolation import InterpolationMethod
from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.views.graph_area_view import GraphAreaView
from valisync.gui.views.graph_panel_view import GraphPanelView


def _session_with_two_signals(tmp_path: Path) -> tuple[Session, str, str]:
    """A session with two distinctly-named signals, so two panels can each
    hold one and the readout pane's row names discriminate them unambiguously.
    """
    csv_file = tmp_path / "d.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "sigA", "sigB"])
        for i in range(100):
            w.writerow([i * 0.01, float(i), float(i) * 2.0])
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    session = Session()
    session.load(csv_file, fmt)
    names = sorted(s.name for s in session.signals())
    sig_a = next(n for n in names if "sigA" in n)
    sig_b = next(n for n in names if "sigB" in n)
    return session, sig_a, sig_b


@pytest.fixture
def area_two_panels_two_signals(
    qtbot: QtBot, tmp_path: Path
) -> tuple[GraphAreaView, GraphAreaVM, str, str]:
    """One tab, two panels: panel 0 holds sigA, panel 1 holds sigB.

    ``add_panel`` auto-activates the new panel (established convention — see
    test_active_panel.py's area_with_two_panels), so panel 1 (sigB) starts active.
    """
    session, sig_a, sig_b = _session_with_two_signals(tmp_path)
    vm = GraphAreaVM(AppViewModel(session))
    area = GraphAreaView(vm, panel_factory=lambda p: GraphPanelView(p))
    qtbot.addWidget(area)
    vm.add_panel(0)
    panels = vm.panels(0)
    panels[0].add_signal(sig_a)
    panels[1].add_signal(sig_b)
    area.resize(900, 600)
    area.show()
    qtbot.waitExposed(area)
    return area, vm, sig_a, sig_b


# ─── Step 5 binding tests (brief stubs) ──────────────────────────────────────


def test_readout_binds_to_active_panel(
    area_two_panels_two_signals: tuple[GraphAreaView, GraphAreaVM, str, str],
) -> None:
    """アクティブパネル切替でペイン内容がそのパネルの信号へ入れ替わる。"""
    area, vm, _sig_a, _sig_b = area_two_panels_two_signals
    panels = vm.panels(0)
    panels[0].set_cursor(0.5)
    panels[1].set_cursor(0.5)

    # panel 1 (sigB) is active by default (add_panel auto-activation).
    rows_b = area.readout_pane.row_texts()
    assert any("sigB" in name for name, _ in rows_b)
    assert not any("sigA" in name for name, _ in rows_b)

    vm.set_active_panel(0, 0)  # switch active -> panel 0 (sigA)
    rows_a = area.readout_pane.row_texts()
    assert any("sigA" in name for name, _ in rows_a)
    assert not any("sigB" in name for name, _ in rows_a)


def test_readout_shows_legend_without_cursor(
    area_two_panels_two_signals: tuple[GraphAreaView, GraphAreaVM, str, str],
) -> None:
    """カーソル未設置+信号ありは凡例モード (計測 IA spec §2.6)。

    supersede 記録: この意図的反転は
    tests/gui/test_readout_pane_binding.py::test_readout_placeholder_without_cursor
    (readout-pane 増分B・spec-B 案b「カーソル未設置時はプレースホルダ文言」) を
    計測 IA design spec (docs/superpowers/specs/2026-07-21-measurement-ia-design.md
    §2.6) が supersede した結果。旧テストは「プレースホルダ文言が出る」を assert
    していたが、新仕様では信号がある限りプレースホルダは出ず凡例行が出る。
    """
    area, _vm, _sig_a, sig_b = area_two_panels_two_signals
    assert area.readout_pane.placeholder_text() == ""
    assert not area.readout_stowed()
    rows = area.readout_pane.row_texts()
    assert any(sig_b in name for name, _ in rows)  # panel 1 (sigB) がアクティブ


def test_readout_stows_when_active_panel_has_no_signals(
    area_two_panels_two_signals: tuple[GraphAreaView, GraphAreaVM, str, str],
) -> None:
    """信号ゼロ (アクティブパネルの信号を全削除) → ペイン自動収納 (spec §2.6)。

    トグル状態 (readout_visible) はユーザーの表示意思として不変 — 信号が戻れば
    ペインは自動的に再表示される (readout_stowed が両者を分離する第3状態)。
    """
    area, vm, _sig_a, sig_b = area_two_panels_two_signals
    panels = vm.panels(0)
    assert not area.readout_stowed()
    assert area.readout_pane.isVisible()

    panels[1].remove_signal(sig_b)  # panel 1 (アクティブ) の信号がゼロになる

    assert area.readout_stowed()
    assert area.readout_visible() is True  # トグル状態は不変
    assert not area.readout_pane.isVisible()

    panels[1].add_signal(sig_b)  # 信号が戻る → 自動的に再表示

    assert not area.readout_stowed()
    assert area.readout_pane.isVisible()


def test_readout_toggle_hides_pane(
    area_two_panels_two_signals: tuple[GraphAreaView, GraphAreaVM, str, str],
) -> None:
    """set_readout_visible(False) でペイン非表示・True で再表示。"""
    area, _vm, _sig_a, _sig_b = area_two_panels_two_signals
    assert area.readout_visible() is True
    assert area.readout_pane.isVisible()

    area.set_readout_visible(False)
    assert area.readout_visible() is False
    assert not area.readout_pane.isVisible()

    area.set_readout_visible(True)
    assert area.readout_visible() is True
    assert area.readout_pane.isVisible()


def test_readout_row_activates_curve(
    area_two_panels_two_signals: tuple[GraphAreaView, GraphAreaVM, str, str],
) -> None:
    """ペイン行クリック → アクティブパネルの該当 entry_id が active_curve に。"""
    area, vm, _sig_a, sig_b = area_two_panels_two_signals
    panels = vm.panels(0)
    panels[1].set_cursor(0.5)  # panel 1 (sigB) already active

    second_widget = area.tabs.widget(0).widget(1)  # type: ignore[attr-defined]
    entry_id = second_widget.entry_id_for(sig_b)
    assert second_widget.active_curve_id() is None

    area.readout_pane.activate_row(0)  # single-row table -> row 0 == sigB's entry

    assert second_widget.active_curve_id() == entry_id


# ─── Honest replacements for coverage removed from test_graph_panel_cursor.py
# (the readout table — and its clear/interp-label affordances — moved from
# GraphPanelView to this single GraphAreaView-owned pane) ────────────────────


def test_readout_clear_callback_clears_active_panel_cursor(
    area_two_panels_two_signals: tuple[GraphAreaView, GraphAreaVM, str, str],
) -> None:
    """readout の _on_clear callback (旧「カーソルを消す」導線) がアクティブパネルの
    VM へ委譲される — replaces the removed
    test_graph_panel_cursor.py::test_readout_close_clears_all_cursors."""
    area, vm, _sig_a, _sig_b = area_two_panels_two_signals
    panels = vm.panels(0)
    panels[1].set_cursor(0.5)  # panel 1 already active
    assert panels[1].cursor_t is not None

    area.readout_pane._on_clear()  # type: ignore[misc]

    assert panels[1].cursor_t is None


def test_sync_readout_calls_cursor_readings_once(
    area_two_panels_two_signals: tuple[GraphAreaView, GraphAreaVM, str, str],
) -> None:
    """perf 回帰ガード (readout-pane I1 dedup): _sync_readout() の1呼び出しにつき
    pvm.cursor_readings() は高々1回しか呼ばれない — drag hot path (VM "cursor" ->
    readout_changed -> _sync_readout) での min/max リダクション二重実行を防ぐ。"""
    area, vm, _sig_a, _sig_b = area_two_panels_two_signals
    panels = vm.panels(0)
    pvm = panels[1]  # active by default
    pvm.set_cursor(0.5)

    calls = 0
    original = pvm.cursor_readings

    def counting_cursor_readings() -> list:  # type: ignore[type-arg]
        nonlocal calls
        calls += 1
        return original()

    pvm.cursor_readings = counting_cursor_readings  # type: ignore[method-assign]

    area._sync_readout()

    assert calls == 1


def test_readout_shows_active_panel_interp_label(
    area_two_panels_two_signals: tuple[GraphAreaView, GraphAreaVM, str, str],
) -> None:
    """アクティブパネルの補間方式ラベルがペインのヘッダに反映される — replaces the
    removed test_graph_panel_cursor.py::test_readout_header_shows_current_interp."""
    area, vm, _sig_a, _sig_b = area_two_panels_two_signals
    panels = vm.panels(0)
    panels[1].set_interp_method(InterpolationMethod.NEAREST)  # panel 1 active
    panels[1].set_cursor(0.5)

    assert "最近傍" in area.readout_pane.header_text()
