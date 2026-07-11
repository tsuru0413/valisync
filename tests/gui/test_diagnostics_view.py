from PySide6.QtCore import Qt

from valisync.core.models.load_result import Diagnostic
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel
from valisync.gui.views.diagnostics_view import DiagnosticsView


def _mk(qtbot):
    vm = DiagnosticsViewModel()
    view = DiagnosticsView(vm)
    qtbot.addWidget(view)
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
    vm, view = _mk(qtbot)
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
    vm, view = _mk(qtbot)
    vm.add("a", [Diagnostic(level="error", message="e")])
    assert view._stack.currentWidget() is view._table

    view.clear_diagnostics()
    assert view._stack.currentWidget() is view._placeholder


def test_counts_chip_tracks_vm_counts_on_add_and_clear(qtbot):
    vm, view = _mk(qtbot)
    assert view._counts_label.text() == "⛔ 0 / ⚠ 0"

    vm.add(
        "a",
        [
            Diagnostic(level="error", message="e"),
            Diagnostic(level="warning", message="w"),
        ],
    )
    assert view._counts_label.text() == "⛔ 1 / ⚠ 1"

    view.clear_diagnostics()
    assert view._counts_label.text() == "⛔ 0 / ⚠ 0"


def test_order_column_shows_seq_for_each_row(qtbot):
    vm, view = _mk(qtbot)
    vm.add("a", [Diagnostic(level="error", message="e1")])
    vm.add("b", [Diagnostic(level="warning", message="e2")])

    # order column sits between the level icon (col 0) and source (col 2),
    # per spec §4.4's "レベルアイコン / 時刻 / ソース / メッセージ / 対象".
    assert view._table.item(0, 1).text() == "0"
    assert view._table.item(1, 1).text() == "1"


# ---------------------------------------------------------------------------
# Real input-event paths (Layer B) — qtbot.mouseClick / mouseDClick drive the
# SAME routing a real click/dblclick takes (QPushButton.clicked / QTableWidget
# viewport hit-test → cellDoubleClicked), not a programmatic .click()/.emit()
# (see .claude/skills/gui-test-plan/, Layer B honest-layering note).
# ---------------------------------------------------------------------------


def test_real_click_on_filter_buttons_filters_rows(qtbot):
    """Real QPushButton clicks (not ``.click()``) drive the filter bar."""
    vm, view = _mk(qtbot)
    vm.add(
        "a",
        [
            Diagnostic(level="error", message="e"),
            Diagnostic(level="warning", message="w"),
        ],
    )

    qtbot.mouseClick(view._btn_warn, Qt.MouseButton.LeftButton)
    assert view.row_count() == 1

    qtbot.mouseClick(view._btn_all, Qt.MouseButton.LeftButton)
    assert view.row_count() == 2

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
