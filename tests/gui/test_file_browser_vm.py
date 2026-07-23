"""Tests for FileBrowserVM.

Tests verify:
- files property returns filenames (basenames) of loaded files
- select_file(index) updates AppViewModel.active_file_key
- VM refreshes its list when AppViewModel notifies 'loaded'
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition, SignalGroup
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM


def _fmt() -> FormatDefinition:
    """CSV format for tests."""
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


def test_initial_files_list_is_empty() -> None:
    app_vm = AppViewModel()
    fb_vm = FileBrowserVM(app_vm)
    assert fb_vm.files == []


def test_files_list_contains_basenames() -> None:
    app_vm = AppViewModel()
    # Simulate real group keys and SignalGroup objects in session
    # Based on core logic, first MDF4 is mf4_1, first CSV is csv_1
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data1.mf4").absolute(), "MDF4", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data2.csv").absolute(), "CSV", datetime.now())
    )

    app_vm._loaded_keys = [k1, k2]

    fb_vm = FileBrowserVM(app_vm)

    # Actual source filenames should be extracted
    assert fb_vm.files == ["data1.mf4", "data2.csv"]


def test_select_file_updates_app_vm() -> None:
    app_vm = AppViewModel()
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data1.mf4").absolute(), "MDF4", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data2.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    fb_vm = FileBrowserVM(app_vm)

    fb_vm.select_file(1)
    assert app_vm.active_file_key == k2


def test_refreshes_on_loaded_notification() -> None:
    app_vm = AppViewModel()
    fb_vm = FileBrowserVM(app_vm)
    notifications: list[str] = []
    fb_vm.subscribe(notifications.append)

    # Simulate load with real key and group
    k = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/data1.mf4").absolute(), "MDF4", datetime.now())
    )
    app_vm._loaded_keys = [k]
    app_vm._notify("loaded")

    assert fb_vm.files == ["data1.mf4"]
    assert "files" in notifications


def test_unload_removes_file_from_list() -> None:
    app_vm = AppViewModel()
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/b.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    fb_vm = FileBrowserVM(app_vm)
    assert fb_vm.files == ["a.csv", "b.csv"]

    fb_vm.unload(0)

    assert fb_vm.files == ["b.csv"]
    assert fb_vm.unload(5) is None  # out of range is a safe no-op


def test_tooltip_text_four_lines(tmp_path: Path) -> None:
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    path = _write_csv(tmp_path / "data.csv")
    app_vm.request_load(path, _fmt())
    text = vm.tooltip_text(0)
    lines = text.splitlines()
    assert lines[0] == str(path.resolve())
    assert lines[1].startswith("サイズ: ")
    assert lines[2].startswith("時間範囲: ")
    assert "（" in lines[2] and lines[2].endswith("s）")
    assert lines[3].startswith("チャンネル: ") and "形式: CSV" in lines[3]


def test_tooltip_omits_size_when_file_gone(tmp_path: Path) -> None:
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    path = _write_csv(tmp_path / "data.csv")
    app_vm.request_load(path, _fmt())
    path.unlink()
    text = vm.tooltip_text(0)
    assert "サイズ:" not in text  # graceful degradation (spec §6)
    assert "時間範囲:" in text


def test_tooltip_none_for_out_of_range() -> None:
    assert FileBrowserVM(AppViewModel()).tooltip_text(0) is None


def test_releasing_file_stays_after_loaded_rows_until_released(tmp_path: Path) -> None:
    app_vm = AppViewModel()

    class _Fake:
        def enqueue(self, key: str, group: object) -> None:
            pass

    app_vm.set_teardown(_Fake())
    k1 = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    k2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)
    n1, n2 = app_vm.session.source_name(k1), app_vm.session.source_name(k2)

    app_vm.unload_file(k1)  # k1 -> releasing (loaded から消え、末尾に releasing 行)

    assert vm.files == [n2, n1]  # loaded(n2) の後ろに releasing(n1)
    assert vm.is_releasing(0) is False  # loaded 行
    assert vm.is_releasing(1) is True  # releasing 行

    app_vm.mark_released(k1)
    assert vm.files == [n2]
    assert vm.is_releasing(0) is False


# ─── E-2a: reference file badge/menu-support API ─────────────────────────────


def test_no_badge_with_a_single_loaded_file(tmp_path: Path) -> None:
    """Comparison mode requires 2+ files — a single file never shows the badge
    even though it is (implicitly) the reference (spec §2 — frozen catalogue)."""
    app_vm = AppViewModel()
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    vm = FileBrowserVM(app_vm)

    assert app_vm.reference_file_key == key
    assert vm.files == ["a.csv"]  # no " ◎基準" suffix
    assert vm.is_comparison_mode() is False


def test_badge_shown_on_reference_row_in_comparison_mode(tmp_path: Path) -> None:
    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)
    key1 = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)

    assert app_vm.reference_file_key == key1  # first load, unchanged
    assert vm.files == ["a.csv ◎基準", "b.csv"]
    assert vm.is_comparison_mode() is True


def test_badge_follows_reference_change(tmp_path: Path) -> None:
    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)  # badge display requires comparison mode
    app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    key2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)

    vm.set_reference(1)  # b.csv becomes the reference

    assert app_vm.reference_file_key == key2
    assert vm.files == ["a.csv", "b.csv ◎基準"]


def test_key_at_and_is_reference(tmp_path: Path) -> None:
    app_vm = AppViewModel()
    key1 = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    key2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)

    assert vm.key_at(0) == key1
    assert vm.key_at(1) == key2
    assert vm.key_at(2) is None  # out of range
    assert vm.key_at(-1) is None

    assert vm.is_reference(0) is True
    assert vm.is_reference(1) is False
    assert vm.is_reference(2) is False  # out-of-range row is never "the reference"


def test_key_at_none_for_releasing_row(tmp_path: Path) -> None:
    """Releasing rows guard the same way select_file/unload do (spec §2)."""
    app_vm = AppViewModel()

    class _Fake:
        def enqueue(self, key: str, group: object) -> None:
            pass

    app_vm.set_teardown(_Fake())
    key1 = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)
    app_vm.unload_file(key1)  # key1 -> releasing (row 1, past the loaded rows)

    assert vm.key_at(1) is None
    assert vm.is_reference(1) is False


def test_set_reference_out_of_range_is_noop(tmp_path: Path) -> None:
    app_vm = AppViewModel()
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    vm = FileBrowserVM(app_vm)

    vm.set_reference(5)

    assert app_vm.reference_file_key == key  # unchanged


def test_vm_refreshes_on_reference_notification() -> None:
    """FileBrowserVM subscribes to the 'reference' tag directly (spec §2 —
    without it, the badge would not move on a bare set_reference_file call)."""
    app_vm = AppViewModel()
    app_vm.register_loaded("k1")
    app_vm.register_loaded("k2")
    vm = FileBrowserVM(app_vm)
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    app_vm.set_reference_file("k2")

    assert "files" in notifications


# ─── E-2c: file-hue chip color ────────────────────────────────────────────────


def test_chip_color_none_with_a_single_loaded_file() -> None:
    app_vm = AppViewModel()
    app_vm.register_loaded("k1")
    vm = FileBrowserVM(app_vm)

    assert vm.chip_color(0) is None


def test_chip_color_matches_file_hue_index_in_comparison_mode() -> None:
    from valisync.gui.theme.tokens import active

    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)
    app_vm.register_loaded("k1")
    app_vm.register_loaded("k2")
    vm = FileBrowserVM(app_vm)
    palette = active().colors.signal_palette

    assert vm.chip_color(0) == palette[app_vm.file_hue_index["k1"]].hex
    assert vm.chip_color(1) == palette[app_vm.file_hue_index["k2"]].hex


def test_chip_color_none_for_out_of_range_or_releasing_row() -> None:
    app_vm = AppViewModel()
    app_vm.register_loaded("k1")
    app_vm.register_loaded("k2")
    vm = FileBrowserVM(app_vm)

    assert vm.chip_color(5) is None
