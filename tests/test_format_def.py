"""Unit tests for FormatDefinition validation and FormatDefinitionManager CRUD.

Covers Task 10.3 (FormatDef portion): construction invariants (Req 3.2/3.6) and
the JSON persistence lifecycle save/load/delete with duplicate-name rejection
(Req 3.1/3.3/3.4/3.5/3.7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from valisync.core.loaders.format_def_manager import FormatDefinitionManager
from valisync.core.models import Delimiter, FormatDefinition


def _fmt(**overrides: object) -> FormatDefinition:
    base: dict[str, object] = {
        "name": "fmt",
        "delimiter": Delimiter.COMMA,
        "timestamp_column": 0,
        "timestamp_unit": "sec",
        "signal_start_column": 1,
        "signal_end_column": 3,
        "has_header": True,
    }
    base.update(overrides)
    return FormatDefinition(**base)  # type: ignore[arg-type]


# ─── Validation (Req 3.2 / 3.6) ───────────────────────────────────────────────


def test_valid_construction() -> None:
    fd = _fmt()
    assert fd.name == "fmt"
    assert fd.signal_start_column == 1


@pytest.mark.parametrize("name", ["", "x" * 65])
def test_name_length_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        _fmt(name=name)


@pytest.mark.parametrize("col", [-1, 256])
def test_timestamp_column_out_of_range_rejected(col: int) -> None:
    # place signal range away from the timestamp column under test
    with pytest.raises(ValueError):
        _fmt(timestamp_column=col, signal_start_column=1, signal_end_column=3)


def test_invalid_timestamp_unit_rejected() -> None:
    with pytest.raises(ValueError):
        _fmt(timestamp_unit="ns")


def test_signal_start_after_end_rejected() -> None:
    with pytest.raises(ValueError):
        _fmt(timestamp_column=0, signal_start_column=5, signal_end_column=3)


def test_signal_end_out_of_range_rejected() -> None:
    with pytest.raises(ValueError):
        _fmt(signal_start_column=1, signal_end_column=256)


def test_timestamp_column_overlaps_signal_range_rejected() -> None:
    with pytest.raises(ValueError):
        _fmt(timestamp_column=2, signal_start_column=1, signal_end_column=3)


# ─── Manager CRUD + JSON round-trip ───────────────────────────────────────────


def test_save_then_load_all(tmp_path: Path) -> None:
    mgr = FormatDefinitionManager(tmp_path)
    mgr.save(_fmt(name="alpha"))
    loaded = mgr.load_all()
    assert len(loaded) == 1
    assert loaded[0].name == "alpha"


def test_json_roundtrip_preserves_all_fields(tmp_path: Path) -> None:
    mgr = FormatDefinitionManager(tmp_path)
    original = _fmt(
        name="full",
        delimiter=Delimiter.TAB,
        timestamp_column=4,
        timestamp_unit="msec",
        signal_start_column=0,
        signal_end_column=3,
        has_header=False,
        has_unit_row=True,
    )
    mgr.save(original)
    (loaded,) = mgr.load_all()
    assert loaded == original


def test_save_duplicate_name_rejected(tmp_path: Path) -> None:
    mgr = FormatDefinitionManager(tmp_path)
    mgr.save(_fmt(name="dup"))
    with pytest.raises(ValueError):
        mgr.save(_fmt(name="dup"))


def test_delete_removes_definition(tmp_path: Path) -> None:
    mgr = FormatDefinitionManager(tmp_path)
    mgr.save(_fmt(name="gone"))
    mgr.delete("gone")
    assert mgr.load_all() == []


def test_delete_missing_raises(tmp_path: Path) -> None:
    mgr = FormatDefinitionManager(tmp_path)
    with pytest.raises(FileNotFoundError):
        mgr.delete("nope")


def test_load_all_sorted_by_name(tmp_path: Path) -> None:
    mgr = FormatDefinitionManager(tmp_path)
    for name in ("charlie", "alpha", "bravo"):
        mgr.save(_fmt(name=name))
    assert [fd.name for fd in mgr.load_all()] == ["alpha", "bravo", "charlie"]


def test_load_all_missing_dir_returns_empty(tmp_path: Path) -> None:
    mgr = FormatDefinitionManager(tmp_path / "does_not_exist")
    assert mgr.load_all() == []


def test_malformed_json_skipped(tmp_path: Path) -> None:
    mgr = FormatDefinitionManager(tmp_path)
    mgr.save(_fmt(name="good"))
    (tmp_path / "broken.json").write_text("{ not valid json", encoding="utf-8")
    loaded = mgr.load_all()
    assert [fd.name for fd in loaded] == ["good"]


@pytest.mark.parametrize("bad_name", ["a/b", "a\\b", "a:b"])
def test_save_forbidden_filename_chars_rejected(tmp_path: Path, bad_name: str) -> None:
    mgr = FormatDefinitionManager(tmp_path)
    with pytest.raises(ValueError):
        mgr.save(_fmt(name=bad_name))
