"""Tests for AppViewModel (Task 1.2).

Tests verify:
- load a temp CSV records the group key in state
- a "loaded" notification fires when request_load succeeds
- signals() exposes the namespaced signal after load
- inspect() reflects current state (keys, active tab, data sources)
- add_data_source / remove_data_source update state and emit notifications
"""

from __future__ import annotations

from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv_format() -> FormatDefinition:
    return FormatDefinition(
        name="test_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )


def _write_csv(path: Path) -> Path:
    """Write a minimal valid CSV and return its path."""
    path.write_text("t,speed\n0.0,10.0\n1.0,20.0\n2.0,30.0\n")
    return path


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_request_load_records_key(tmp_path: Path) -> None:
    """request_load returns the group key and adds it to loaded_file_keys."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")

    key = vm.request_load(csv_file, _csv_format())

    assert key in vm.inspect()["loaded_keys"]


def test_request_load_fires_loaded_notification(tmp_path: Path) -> None:
    """request_load calls _notify('loaded') after a successful load."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.request_load(csv_file, _csv_format())

    assert "loaded" in notifications


def test_signals_exposes_namespaced_signal_after_load(tmp_path: Path) -> None:
    """signals() returns a Signal with a namespaced name after load."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")

    key = vm.request_load(csv_file, _csv_format())

    names = [s.name for s in vm.signals()]
    assert any(name.startswith(f"{key}::") for name in names)


def test_inspect_reflects_initial_state() -> None:
    """inspect() snapshot matches the default initial state."""
    vm = AppViewModel()

    state = vm.inspect()

    assert state["loaded_keys"] == []
    assert state["active_tab"] == 0
    assert state["data_sources"] == []


def test_inspect_reflects_state_after_load(tmp_path: Path) -> None:
    """inspect() includes the new key and preserves other fields after load."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")

    key = vm.request_load(csv_file, _csv_format())
    state = vm.inspect()

    assert key in state["loaded_keys"]
    assert state["active_tab"] == 0


def test_add_data_source_updates_state_and_notifies(tmp_path: Path) -> None:
    """add_data_source appends the path and fires 'data_sources' notification."""
    vm = AppViewModel()
    notifications: list[str] = []
    vm.subscribe(notifications.append)
    folder = tmp_path / "logs"

    vm.add_data_source(folder)

    assert str(folder) in vm.inspect()["data_sources"]
    assert "data_sources" in notifications


def test_remove_data_source_updates_state_and_notifies(tmp_path: Path) -> None:
    """remove_data_source removes the path and fires 'data_sources' notification."""
    vm = AppViewModel()
    folder = tmp_path / "logs"
    vm.add_data_source(folder)
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.remove_data_source(folder)

    assert str(folder) not in vm.inspect()["data_sources"]
    assert "data_sources" in notifications


def test_remove_nonexistent_data_source_is_noop(tmp_path: Path) -> None:
    """Removing a path not in the list does not raise and still notifies."""
    vm = AppViewModel()
    notifications: list[str] = []
    vm.subscribe(notifications.append)
    ghost = tmp_path / "ghost"

    vm.remove_data_source(ghost)  # must not raise

    assert "data_sources" in notifications


def test_active_file_state_updates_and_notifies() -> None:
    """set_active_file updates the state and fires 'active_file' notification."""
    vm = AppViewModel()
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    assert vm.active_file_key is None
    assert vm.inspect()["active_file"] is None

    test_key = "some/file/path.mf4"
    vm.set_active_file(test_key)

    assert vm.active_file_key == test_key
    assert vm.inspect()["active_file"] == test_key
    assert "active_file" in notifications


def test_set_active_file_same_key_is_noop() -> None:
    """FU-22: 同一キー再選択は state 不変・'active_file' notify 無し (264k リビルド重複の根絶)."""
    vm = AppViewModel()
    vm.set_active_file("k")  # None -> k (genuine change)
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.set_active_file("k")  # same key -> guarded no-op

    assert notifications == []  # no 'active_file' re-fire
    assert vm.active_file_key == "k"  # state unchanged


def test_set_active_file_genuine_change_still_notifies() -> None:
    """FU-22 ガードが genuine 変更 (None->key, key->other, key->None) を塞がない無回帰."""
    vm = AppViewModel()
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.set_active_file("a")  # None -> a
    vm.set_active_file("b")  # a -> b
    vm.set_active_file(None)  # b -> None

    assert notifications.count("active_file") == 3


def test_reference_file_key_defaults_to_first_load(tmp_path: Path) -> None:
    """E-2a: the first ever load becomes the reference (spec §2)."""
    vm = AppViewModel()
    assert vm.reference_file_key is None

    key1 = vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    assert vm.reference_file_key == key1

    key2 = vm.request_load(_write_csv(tmp_path / "b.csv"), _csv_format())
    assert vm.reference_file_key == key1  # unchanged by the second load
    assert key2 != key1


def test_set_reference_file_notifies_and_same_key_is_noop() -> None:
    vm = AppViewModel()
    vm.register_loaded("k1")
    vm.register_loaded("k2")
    assert vm.reference_file_key == "k1"

    notifications: list[str] = []
    vm.subscribe(notifications.append)
    vm.set_reference_file("k2")

    assert vm.reference_file_key == "k2"
    assert "reference" in notifications

    notifications.clear()
    vm.set_reference_file("k2")  # same key -> guarded no-op
    assert notifications == []
    assert vm.reference_file_key == "k2"


def test_inspect_reflects_reference_file() -> None:
    vm = AppViewModel()
    vm.register_loaded("k1")
    assert vm.inspect()["reference_file"] == "k1"


def test_loaded_file_keys_exposes_list(tmp_path: Path) -> None:
    """loaded_file_keys property returns the list of group keys."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")

    key = vm.request_load(csv_file, _csv_format())

    assert vm.loaded_file_keys == [key]


def test_unload_file_removes_group_clears_active_and_notifies(tmp_path: Path) -> None:
    """unload_file removes the group, clears a matching active file, and notifies."""
    vm = AppViewModel()
    key = vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    vm.set_active_file(key)

    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.unload_file(key)

    assert key not in vm.loaded_file_keys
    assert vm.active_file_key is None
    assert vm.signals() == []
    assert "unloaded" in notifications
    assert "active_file" in notifications


def test_unload_reference_migrates_to_surviving_load_order_head(tmp_path: Path) -> None:
    """E-2a: unloading the reference migrates it to the surviving load-order
    head, completed (and notified) BEFORE 'unloaded' fires (spec §2)."""
    vm = AppViewModel()
    key1 = vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    key2 = vm.request_load(_write_csv(tmp_path / "b.csv"), _csv_format())
    vm.request_load(_write_csv(tmp_path / "c.csv"), _csv_format())  # 3rd survivor
    assert vm.reference_file_key == key1

    order: list[str] = []
    vm.subscribe(order.append)
    vm.unload_file(key1)

    assert vm.reference_file_key == key2  # surviving load-order head
    assert order.index("reference") < order.index("unloaded")


def test_unload_reference_with_no_survivors_clears_it(tmp_path: Path) -> None:
    vm = AppViewModel()
    key = vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    assert vm.reference_file_key == key

    vm.unload_file(key)

    assert vm.reference_file_key is None


def test_unload_non_reference_file_leaves_reference_unchanged(tmp_path: Path) -> None:
    vm = AppViewModel()
    key1 = vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    key2 = vm.request_load(_write_csv(tmp_path / "b.csv"), _csv_format())
    assert vm.reference_file_key == key1

    notifications: list[str] = []
    vm.subscribe(notifications.append)
    vm.unload_file(key2)

    assert vm.reference_file_key == key1
    assert "reference" not in notifications  # unaffected reference: no notify


class _FakeTeardown:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def enqueue(self, key, group) -> None:
        self.calls.append((key, group))


def test_unload_defers_removed_group_to_teardown_and_marks_releasing(tmp_path) -> None:
    app_vm = AppViewModel()
    fake = _FakeTeardown()
    app_vm.set_teardown(fake)
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    name = app_vm.session.source_name(key)

    app_vm.unload_file(key)

    # remove_group の削除グループが service へ渡る（core は同期解放しない）。  # noqa: RUF003
    assert len(fake.calls) == 1 and fake.calls[0][0] == key
    assert fake.calls[0][1] is not None
    # releasing にマーク（名前は unload 時にキャプチャ＝session から消えても表示可）。  # noqa: RUF003
    assert app_vm.releasing_files == [(key, name)]
    # 論理クローズは同期で完了（loaded から消える）。  # noqa: RUF003
    assert key not in app_vm.loaded_file_keys


def test_mark_released_removes_from_releasing(tmp_path) -> None:
    app_vm = AppViewModel()
    fake = _FakeTeardown()
    app_vm.set_teardown(fake)
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    app_vm.unload_file(key)
    seen: list[str] = []
    app_vm.subscribe(lambda tag: seen.append(tag) if tag == "releasing" else None)

    app_vm.mark_released(key)

    assert app_vm.releasing_files == []
    assert "releasing" in seen


def test_unload_without_teardown_frees_immediately_no_releasing(tmp_path) -> None:
    """teardown 未注入（ヘッドレス既定）では releasing にせず即時解放（現行挙動保存）。"""  # noqa: RUF002
    app_vm = AppViewModel()
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    app_vm.unload_file(key)
    assert app_vm.releasing_files == []
    assert key not in app_vm.loaded_file_keys


# ─── E-2c: file_hue_index / is_comparison_mode / file_hue_resolver ───────────


def test_is_comparison_mode_requires_2_files() -> None:
    vm = AppViewModel()
    assert vm.is_comparison_mode() is False

    vm.register_loaded("k1")
    assert vm.is_comparison_mode() is False

    vm.register_loaded("k2")
    assert vm.is_comparison_mode() is True


def test_file_hue_index_assigned_monotonically_on_every_load() -> None:
    """Assigned regardless of comparison mode (spec §4.1) — the 1st file
    already has a hue slot so the moment a 2nd file flips comparison mode on,
    reapply has a real hue to resolve for BOTH files."""
    vm = AppViewModel()
    vm.register_loaded("k1")
    assert vm.file_hue_index == {"k1": 0}

    vm.register_loaded("k2")
    assert vm.file_hue_index == {"k1": 0, "k2": 1}


def test_file_hue_index_never_reused_after_unload(tmp_path: Path) -> None:
    """Color stability over slot reuse (spec §4.1): unloading "k2" (slot 1)
    then loading a 3rd file assigns slot 2, not the freed slot 1."""
    vm = AppViewModel()
    key1 = vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    key2 = vm.request_load(_write_csv(tmp_path / "b.csv"), _csv_format())
    assert vm.file_hue_index[key1] == 0
    assert vm.file_hue_index[key2] == 1

    vm.unload_file(key2)
    key3 = vm.request_load(_write_csv(tmp_path / "c.csv"), _csv_format())

    assert vm.file_hue_index[key1] == 0
    assert vm.file_hue_index[key3] == 2  # NOT the freed slot 1


def test_file_hue_index_cycles_mod_palette_length() -> None:
    from valisync.gui.theme.tokens import active

    palette_len = len(active().colors.signal_palette)
    vm = AppViewModel()
    for i in range(palette_len + 1):
        vm.register_loaded(f"k{i}")

    assert vm.file_hue_index[f"k{palette_len}"] == 0  # wrapped back to slot 0


def test_file_hue_resolver_returns_none_below_2_files() -> None:
    vm = AppViewModel()
    vm.register_loaded("k1")
    resolver = vm.file_hue_resolver()

    assert resolver("k1") is None


def test_file_hue_resolver_returns_assigned_hue_in_comparison_mode() -> None:
    vm = AppViewModel()
    vm.register_loaded("k1")
    vm.register_loaded("k2")
    resolver = vm.file_hue_resolver()

    assert resolver("k1") == 0
    assert resolver("k2") == 1
    assert resolver("unknown") is None  # unassigned group


def test_file_hue_resolver_closure_reads_live_state() -> None:
    """One resolver instance created before the 2nd load must still see it —
    the closure reads AppViewModel state fresh on every call, not a snapshot
    at creation time (spec §4.1's "同一インスタンス注入で後続ロードも正しい")."""
    vm = AppViewModel()
    vm.register_loaded("k1")
    resolver = vm.file_hue_resolver()
    assert resolver("k1") is None  # still 1 file

    vm.register_loaded("k2")

    assert resolver("k1") == 0  # SAME resolver instance, now sees comparison mode
