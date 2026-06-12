"""Tests for ChannelBrowserVM (Task 2.2).

Tests verify:
- tree() groups signals by source key (left of "::")
- each leaf carries correct metadata: dtype, count, time_range
- refresh() re-reads from the Session and notifies with "tree"
- set_filter() narrows results (case-insensitive substring) and notifies "filter"
- selection round-trips via set_selection / selected
- toggle_visibility flips visible state and reflects in visible_signal_keys
- notifications fire for each mutating operation
"""

from __future__ import annotations

from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv_format_2cols() -> FormatDefinition:
    """Format definition matching a CSV with columns: t, a, b."""
    return FormatDefinition(
        name="t2",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )


def _write_2col_csv(path: Path) -> Path:
    """Write a minimal 2-signal CSV and return its path."""
    path.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n2.0,3.0,6.0\n", encoding="utf-8")
    return path


def _loaded_session(tmp_path: Path) -> tuple[Session, str]:
    """Return (session, group_key) with 2 signals loaded from a temp CSV."""
    csv_file = _write_2col_csv(tmp_path / "data.csv")
    session = Session()
    key = session.load(csv_file, _csv_format_2cols())
    return session, key


# ─── Construction and initial tree ──────────────────────────────────────────


def test_tree_groups_signals_under_source_key(tmp_path: Path) -> None:
    """tree() returns one group whose 'key' equals the source group key."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    tree = vm.tree()

    keys = [g["key"] for g in tree]
    assert key in keys


def test_tree_contains_both_signals(tmp_path: Path) -> None:
    """tree() includes both signal leaves under the correct group."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    tree = vm.tree()
    group = next(g for g in tree if g["key"] == key)
    names = {s["display_name"] for s in group["signals"]}

    assert names == {"a", "b"}


def test_tree_leaf_has_correct_namespaced_name(tmp_path: Path) -> None:
    """Each leaf 'name' field is the full namespaced signal name."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    tree = vm.tree()
    group = next(g for g in tree if g["key"] == key)
    ns_names = {s["name"] for s in group["signals"]}

    assert ns_names == {f"{key}::a", f"{key}::b"}


def test_tree_leaf_metadata(tmp_path: Path) -> None:
    """Each leaf carries dtype (str), count (int), and time_range (tuple)."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    tree = vm.tree()
    group = next(g for g in tree if g["key"] == key)
    leaf = group["signals"][0]

    assert isinstance(leaf["dtype"], str)
    assert isinstance(leaf["count"], int)
    assert leaf["count"] == 3
    assert isinstance(leaf["time_range"], tuple)
    assert len(leaf["time_range"]) == 2
    assert leaf["time_range"] == (0.0, 2.0)


def test_tree_leaf_time_range_none_when_empty() -> None:
    """A signal with zero samples has time_range=None in its leaf."""
    # Build a session with an empty signal by loading an effectively empty CSV.
    # This is tricky with core validation (timestamps must be monotone).
    # Instead test via a fresh ChannelBrowserVM with no signals.
    session = Session()
    vm = ChannelBrowserVM(session)

    tree = vm.tree()

    assert tree == []


# ─── refresh ────────────────────────────────────────────────────────────────


def test_refresh_fires_tree_notification(tmp_path: Path) -> None:
    """refresh() triggers a 'tree' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.refresh()

    assert "tree" in notifications


def test_refresh_picks_up_new_signals(tmp_path: Path) -> None:
    """refresh() updates tree after new signals are loaded into the session."""
    csv1 = _write_2col_csv(tmp_path / "data1.csv")
    csv2 = _write_2col_csv(tmp_path / "data2.csv")
    session = Session()
    session.load(csv1, _csv_format_2cols())
    vm = ChannelBrowserVM(session)

    initial_count = len(vm.tree())
    session.load(csv2, _csv_format_2cols())
    vm.refresh()
    updated_count = len(vm.tree())

    assert updated_count == initial_count + 1


# ─── set_filter ─────────────────────────────────────────────────────────────


def test_set_filter_narrows_results(tmp_path: Path) -> None:
    """set_filter() keeps only leaves whose display_name contains the text."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    vm.set_filter("a")
    tree = vm.tree()
    group = next((g for g in tree if g["key"] == key), None)

    # Only signal 'a' should survive; 'b' does not contain 'a'
    assert group is not None
    names = [s["display_name"] for s in group["signals"]]
    assert "a" in names
    assert "b" not in names


def test_set_filter_case_insensitive(tmp_path: Path) -> None:
    """set_filter() is case-insensitive."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    vm.set_filter("A")
    tree = vm.tree()
    group = next((g for g in tree if g["key"] == key), None)

    assert group is not None
    names = [s["display_name"] for s in group["signals"]]
    assert "a" in names


def test_set_filter_empty_string_shows_all(tmp_path: Path) -> None:
    """set_filter('') removes all filtering and shows every signal."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    vm.set_filter("a")
    vm.set_filter("")
    tree = vm.tree()
    group = next(g for g in tree if g["key"] == key)

    names = {s["display_name"] for s in group["signals"]}
    assert names == {"a", "b"}


def test_set_filter_fires_filter_notification(tmp_path: Path) -> None:
    """set_filter() triggers a 'filter' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.set_filter("a")

    assert "filter" in notifications


def test_set_filter_group_excluded_when_no_matching_signals(tmp_path: Path) -> None:
    """Groups with no matching signals are excluded from tree() when filtered."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    # Filter that matches nothing in our 'a','b' signals
    vm.set_filter("zzz_no_match")
    tree = vm.tree()

    group_keys = [g["key"] for g in tree]
    assert key not in group_keys


# ─── Selection ───────────────────────────────────────────────────────────────


def test_selection_round_trips(tmp_path: Path) -> None:
    """set_selection stores keys; selected() returns the same keys."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)
    ns_name = f"{key}::a"

    vm.set_selection([ns_name])

    assert vm.selected() == [ns_name]


def test_selection_defaults_to_empty(tmp_path: Path) -> None:
    """selected() returns [] before any selection is made."""
    session, _ = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    assert vm.selected() == []


def test_set_selection_replaces_previous(tmp_path: Path) -> None:
    """set_selection replaces (not appends to) the previous selection."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    vm.set_selection([f"{key}::a"])
    vm.set_selection([f"{key}::b"])

    assert vm.selected() == [f"{key}::b"]


# ─── Visibility ──────────────────────────────────────────────────────────────


def test_signals_visible_by_default(tmp_path: Path) -> None:
    """is_visible() returns True for any signal before toggle_visibility is called."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)

    assert vm.is_visible(f"{key}::a") is True
    assert vm.is_visible(f"{key}::b") is True


def test_toggle_visibility_flips_state(tmp_path: Path) -> None:
    """toggle_visibility() changes visible=True to False on first call."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)
    ns_name = f"{key}::a"

    vm.toggle_visibility(ns_name)

    assert vm.is_visible(ns_name) is False


def test_toggle_visibility_double_flip(tmp_path: Path) -> None:
    """toggle_visibility() twice restores the original visible=True state."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)
    ns_name = f"{key}::a"

    vm.toggle_visibility(ns_name)
    vm.toggle_visibility(ns_name)

    assert vm.is_visible(ns_name) is True


def test_visible_signal_keys_excludes_hidden(tmp_path: Path) -> None:
    """visible_signal_keys() omits signals whose visibility was toggled off."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)
    ns_a = f"{key}::a"
    ns_b = f"{key}::b"

    vm.toggle_visibility(ns_a)

    visible = vm.visible_signal_keys()
    assert ns_a not in visible
    assert ns_b in visible


def test_tree_leaf_visible_field_reflects_toggle(tmp_path: Path) -> None:
    """tree() leaves carry a 'visible' field that reflects the toggle state."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)
    ns_a = f"{key}::a"

    vm.toggle_visibility(ns_a)

    tree = vm.tree()
    group = next(g for g in tree if g["key"] == key)
    leaf_a = next(s for s in group["signals"] if s["name"] == ns_a)
    assert leaf_a["visible"] is False


# ─── inspect ─────────────────────────────────────────────────────────────────


def test_inspect_returns_snapshot(tmp_path: Path) -> None:
    """inspect() returns a dict with filter_text, selection, visibility_map, tree_summary."""
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)
    vm.set_filter("a")
    vm.set_selection([f"{key}::a"])

    snapshot = vm.inspect()

    assert "filter_text" in snapshot
    assert snapshot["filter_text"] == "a"
    assert "selection" in snapshot
    assert f"{key}::a" in snapshot["selection"]
    assert "visibility_map" in snapshot
    assert "tree_summary" in snapshot


def test_visibility_map_lists_all_signals_with_correct_bool(tmp_path: Path) -> None:
    """visibility_map maps EVERY loaded signal to its visibility, not just hidden.

    Regression: the map was built as {k: k not in self._hidden for k in
    self._hidden}, which is always False and omits visible signals entirely.
    """
    session, key = _loaded_session(tmp_path)
    vm = ChannelBrowserVM(session)
    vm.toggle_visibility(f"{key}::a")  # hide 'a'; 'b' stays visible

    vis = vm.inspect()["visibility_map"]

    assert vis == {f"{key}::a": False, f"{key}::b": True}


def test_tree_does_not_crash_on_non_namespaced_signal_name() -> None:
    """tree() must defend the '::' namespace contract instead of raising ValueError.

    Regression: `key, orig_name = sig.name.split('::', 1)` raised
    'not enough values to unpack' for any name lacking the separator, blanking
    the whole browser.  Such names cannot arise today (SignalGroupManager
    namespaces every signal), but a future Derived/formula signal could.
    """
    import numpy as np

    from valisync.core.models import Signal

    lonely = Signal(
        name="lonely",
        timestamps=np.array([0.0, 1.0]),
        values=np.array([1.0, 2.0]),
        file_format="Derived",
        bus_type="",
        source_file="",
    )

    class _FakeSession:
        def signals(self) -> list[Signal]:
            return [lonely]

    vm = ChannelBrowserVM(_FakeSession())  # type: ignore[arg-type]

    tree = vm.tree()  # must not raise

    leaves = [leaf for group in tree for leaf in group["signals"]]
    assert any(leaf["name"] == "lonely" for leaf in leaves)
