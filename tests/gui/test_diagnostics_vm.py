from valisync.core.models.load_result import Diagnostic
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel


def _diag(level, msg, signal=None):
    return Diagnostic(level=level, message=msg, signal_name=signal)


def test_add_appends_and_notifies():
    vm = DiagnosticsViewModel()
    seen = []
    vm.subscribe(seen.append)
    vm.add("a.mf4", [_diag("warning", "skip", "gps")])
    assert "diagnostics" in seen
    e = vm.entries()
    assert len(e) == 1
    assert e[0].source == "a.mf4"
    assert e[0].level == "warning"
    assert e[0].signal_name == "gps"


def test_counts_errors_and_warnings():
    vm = DiagnosticsViewModel()
    vm.add(
        "a", [_diag("error", "boom"), _diag("warning", "w1"), _diag("warning", "w2")]
    )
    assert vm.counts() == (1, 2)


def test_entries_filter_by_level():
    vm = DiagnosticsViewModel()
    vm.add("a", [_diag("error", "e"), _diag("warning", "w")])
    assert len(vm.entries("error")) == 1
    assert vm.entries("error")[0].message == "e"


def test_clear_empties_and_notifies():
    vm = DiagnosticsViewModel()
    vm.add("a", [_diag("warning", "w")])
    seen = []
    vm.subscribe(seen.append)
    vm.clear()
    assert vm.entries() == []
    assert "diagnostics" in seen


def test_seq_is_monotonic_across_adds():
    vm = DiagnosticsViewModel()
    vm.add("a", [_diag("warning", "w1")])
    vm.add("b", [_diag("warning", "w2")])
    seqs = [e.seq for e in vm.entries()]
    assert seqs == sorted(seqs) and len(set(seqs)) == 2
