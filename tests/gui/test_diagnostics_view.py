from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView

from valisync.core.models.load_result import Diagnostic
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel
from valisync.gui.views.diagnostics_view import DiagnosticsView


def _mk(qtbot):
    vm = DiagnosticsViewModel()
    view = DiagnosticsView(vm)
    qtbot.addWidget(view)
    return vm, view


def _mk_no_confirm(qtbot):
    """Same as _mk but with the Clear confirm dialog stubbed to always accept.

    B5 inserted a QMessageBox.exec() into clear_diagnostics(); every existing
    site that calls it (directly or via a real click) must inject this stub —
    otherwise offscreen Qt hangs the test indefinitely in the modal loop.
    """
    vm, view = _mk(qtbot)
    view._confirm_fn = lambda n: True
    return vm, view


def test_object_name_for_state_persistence(qtbot):
    _, view = _mk(qtbot)
    assert view.objectName() == "diagnostics_dock"


def test_rows_reflect_vm_entries(qtbot):
    vm, view = _mk(qtbot)
    vm.add("a.mf4", [Diagnostic(level="error", message="boom")])
    vm.add("b.mf4", [Diagnostic(level="warning", message="skip", signal_name="gps")])
    assert view.row_count() == 2


def test_filter_warnings_only(qtbot):
    vm, view = _mk(qtbot)
    vm.add(
        "a",
        [
            Diagnostic(level="error", message="e"),
            Diagnostic(level="warning", message="w"),
        ],
    )
    view.set_filter("warning")
    assert view.row_count() == 1


def test_clear_empties_view(qtbot):
    vm, view = _mk_no_confirm(qtbot)
    vm.add("a", [Diagnostic(level="warning", message="w")])
    view.clear_diagnostics()
    assert view.row_count() == 0


# ---------------------------------------------------------------------------
# Design spec §4.4/§7 conformance: order column, counts chip, empty
# placeholder — dropped when the implementation plan was written; restored
# here per the final-review Important-1 fix.
# ---------------------------------------------------------------------------


def test_empty_vm_shows_placeholder_then_hides_on_add(qtbot):
    vm, view = _mk(qtbot)
    assert view._stack.currentWidget() is view._placeholder
    assert view.row_count() == 0

    vm.add("a", [Diagnostic(level="error", message="e")])
    assert view._stack.currentWidget() is view._table


def test_placeholder_returns_when_cleared_back_to_empty(qtbot):
    vm, view = _mk_no_confirm(qtbot)
    vm.add("a", [Diagnostic(level="error", message="e")])
    assert view._stack.currentWidget() is view._table

    view.clear_diagnostics()
    assert view._stack.currentWidget() is view._placeholder


def test_counts_chip_tracks_vm_counts_on_add_and_clear(qtbot):
    vm, view = _mk_no_confirm(qtbot)
    assert view._counts_label.text() == "⛔ 0 / ⚠ 0 / ℹ 0"

    vm.add(
        "a",
        [
            Diagnostic(level="error", message="e"),
            Diagnostic(level="warning", message="w"),
            Diagnostic(level="info", message="i"),
        ],
    )
    assert view._counts_label.text() == "⛔ 1 / ⚠ 1 / ℹ 1"

    view.clear_diagnostics()
    assert view._counts_label.text() == "⛔ 0 / ⚠ 0 / ℹ 0"


def test_order_column_shows_seq_for_each_row(qtbot):
    vm, view = _mk(qtbot)
    vm.add("a", [Diagnostic(level="error", message="e1")])
    vm.add("b", [Diagnostic(level="warning", message="e2")])

    # order column sits between the level icon (col 0) and source (col 2),
    # per spec §4.4's "レベルアイコン / 時刻 / ソース / メッセージ / 対象".
    # Display is 1-based (E-2/UX-55); the underlying seq index is unchanged.
    assert view._table.item(0, 1).text() == "1"
    assert view._table.item(1, 1).text() == "2"


def test_message_column_stretches_other_columns_resize_to_contents(qtbot):
    """UX-07 応急 (spec §1.5-14): メッセージ列は残り幅いっぱいに広がり、他列は
    内容幅で詰まる。診断件数は有界のため ResizeToContents はここでは安全
    (ChannelBrowser の Unit 列とは前提が異なる -- prod 264k 行走査ではない)。"""
    _, view = _mk(qtbot)
    header = view._table.horizontalHeader()
    message_col = 3  # "メッセージ" -- see _HEADERS in diagnostics_view.py
    for col in range(view._table.columnCount()):
        expected = (
            QHeaderView.ResizeMode.Stretch
            if col == message_col
            else QHeaderView.ResizeMode.ResizeToContents
        )
        assert header.sectionResizeMode(col) == expected


# ---------------------------------------------------------------------------
# B2: checkable exclusive filter buttons — checked and _filter share a single
# truth source (spec §2.2). The three-point-combined tests below deliberately
# use an error=1/warning=2/info=3 seed (distinguishable row counts) so a
# mis-wired filter button cannot hide behind an accidental count collision;
# exclusivity itself (a QButtonGroup guarantee) is never asserted standalone.
# ---------------------------------------------------------------------------


def test_btn_all_checked_by_default(qtbot):
    _, view = _mk(qtbot)
    assert view._btn_all.isChecked()


def test_set_filter_programmatic_syncs_checked_button(qtbot):
    """A direct (non-click) ``set_filter`` call still re-syncs the checked
    button — the truth source is ``_filter``, not the button's own click."""
    _, view = _mk(qtbot)
    view.set_filter("warning")
    assert view._filter == "warning"
    assert view._btn_warn.isChecked()


def test_filtered_empty_shows_contextual_placeholder_with_total(qtbot):
    """Filtering to zero rows is textually distinct from a truly empty dock
    (B2/UX-06): it names the active filter and the unfiltered total."""
    vm, view = _mk(qtbot)
    vm.add("a", [Diagnostic(level="warning", message="w")])

    view.set_filter("error")
    assert view.row_count() == 0
    assert view._stack.currentWidget() is view._placeholder
    assert view._placeholder.text() == "エラーに該当する診断はありません（全 1 件）"


def test_message_cell_tooltip_shows_full_message(qtbot):
    """B3: the message cell carries the full text as a tooltip, independent
    of how much the Stretch column happens to clip on screen."""
    vm, view = _mk(qtbot)
    long_message = "非常に長い診断メッセージ" * 5
    vm.add("a", [Diagnostic(level="error", message=long_message)])
    message_col = 3
    item = view._table.item(0, message_col)
    assert item.toolTip() == long_message


# ---------------------------------------------------------------------------
# B5: Clear confirmation (UXG-27) — ``_confirm_fn`` attribute DI (same shape
# as file_browser_view.FileBrowserView._confirm_fn) covers the 3 branches
# without driving the real QMessageBox modal loop.
# ---------------------------------------------------------------------------


def test_clear_diagnostics_confirmed_clears(qtbot):
    vm, view = _mk(qtbot)
    vm.add(
        "a",
        [
            Diagnostic(level="warning", message="w"),
            Diagnostic(level="error", message="e"),
        ],
    )
    received_n = []
    view._confirm_fn = lambda n: received_n.append(n) or True
    view.clear_diagnostics()
    assert received_n == [2]
    assert vm.entries() == []


def test_clear_diagnostics_cancelled_keeps_entries(qtbot):
    vm, view = _mk(qtbot)
    vm.add("a", [Diagnostic(level="warning", message="w")])
    view._confirm_fn = lambda n: False
    view.clear_diagnostics()
    assert len(vm.entries()) == 1


def test_clear_diagnostics_empty_skips_confirm(qtbot):
    _, view = _mk(qtbot)
    confirm = Mock(return_value=True)
    view._confirm_fn = confirm
    view.clear_diagnostics()
    confirm.assert_not_called()


# ---------------------------------------------------------------------------
# Real input-event paths (Layer B) — qtbot.mouseClick / mouseDClick drive the
# SAME routing a real click/dblclick takes (QPushButton.clicked / QTableWidget
# viewport hit-test → cellDoubleClicked), not a programmatic .click()/.emit()
# (see .claude/skills/gui-test-plan/, Layer B honest-layering note).
# ---------------------------------------------------------------------------


def test_real_click_on_filter_buttons_syncs_filter_rows_and_checked(qtbot):
    """Three-point-combined (spec §4): a real click on each filter button
    must move ``_filter``, the displayed row count, and the button's checked
    state together. The error=1/warning=2/info=3 seed makes each level's row
    count distinguishable, so a swapped button<->level wire cannot hide
    behind equal counts. Also covers the real Clear-button click path (with
    the confirm dialog stubbed to accept — B5)."""
    vm, view = _mk_no_confirm(qtbot)
    vm.add(
        "a",
        [
            Diagnostic(level="error", message="e1"),
            Diagnostic(level="warning", message="w1"),
            Diagnostic(level="warning", message="w2"),
            Diagnostic(level="info", message="i1"),
            Diagnostic(level="info", message="i2"),
            Diagnostic(level="info", message="i3"),
        ],
    )

    qtbot.mouseClick(view._btn_err, Qt.MouseButton.LeftButton)
    assert view._filter == "error"
    assert view.row_count() == 1
    assert view._btn_err.isChecked()

    qtbot.mouseClick(view._btn_warn, Qt.MouseButton.LeftButton)
    assert view._filter == "warning"
    assert view.row_count() == 2
    assert view._btn_warn.isChecked()

    qtbot.mouseClick(view._btn_all, Qt.MouseButton.LeftButton)
    assert view._filter is None
    assert view.row_count() == 6
    assert view._btn_all.isChecked()

    qtbot.mouseClick(view._btn_clear, Qt.MouseButton.LeftButton)
    assert view.row_count() == 0
    assert vm.entries() == []


def test_real_double_click_on_row_emits_entry_activated(qtbot):
    """A real dblclick on a table row (not a direct ``.emit()``) fires
    ``entry_activated`` with the activated entry's source (file basename) —
    the activation target is always the file, even when the entry carries a
    ``signal_name`` (display-only; see diagnostics_view.py's
    ``_on_double_click``)."""
    vm, view = _mk(qtbot)
    vm.add("a.mf4", [Diagnostic(level="error", message="boom")])
    vm.add("b.mf4", [Diagnostic(level="warning", message="skip", signal_name="gps")])

    view.show()
    qtbot.waitExposed(view)
    table = view._table
    qtbot.waitUntil(
        lambda: table.visualItemRect(table.item(0, 0)).height() > 0, timeout=2000
    )

    pos = table.visualItemRect(table.item(1, 0)).center()
    # A lone qtbot.mouseDClick() on a freshly-shown QAbstractItemView does not
    # reliably fire cellDoubleClicked: QTest's synthetic dblclick event arrives
    # after Qt's internal pressedIndex was already cleared by the preceding
    # release, so it falls back to a plain press+click instead of a double
    # click. A real double click, whose first click lands on an already
    # up-to-date view (from prior interaction), does not hit this replay-order
    # quirk. A warm-up single click brings the view to that same state.
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    with qtbot.waitSignal(view.entry_activated, timeout=1000) as blocker:
        qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=pos)

    assert blocker.args == ["b.mf4"]
