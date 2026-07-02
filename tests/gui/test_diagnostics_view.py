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
