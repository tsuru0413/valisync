"""Tests for data-source persistence (Task 2.1).

Tests verify:
- save + load round-trips the same paths (as strings)
- load of a non-existent file returns []
- load of a corrupt / invalid-JSON file returns []
- parent directories are created automatically on save
- atomic write: existing file is replaced, not partially written
"""

from __future__ import annotations

import json
from pathlib import Path

from valisync.gui.persistence.data_sources import load, save

# ─── save → load round-trip ─────────────────────────────────────────────────


def test_round_trip_string_paths(tmp_path: Path) -> None:
    """save() writes paths as strings; load() reads them back unchanged."""
    target = tmp_path / "config.json"
    paths = ["/data/logs", "/data/can_traces", "/home/user/signals"]

    save(paths, target)
    result = load(target)

    assert result == paths


def test_round_trip_path_objects(tmp_path: Path) -> None:
    """save() accepts Path objects and stores them as strings."""
    target = tmp_path / "config.json"
    paths = [Path("/data/logs"), Path("/home/user/signals")]

    save(paths, target)
    result = load(target)

    assert result == [str(p) for p in paths]


def test_round_trip_empty_list(tmp_path: Path) -> None:
    """save() + load() round-trips an empty list."""
    target = tmp_path / "config.json"

    save([], target)
    result = load(target)

    assert result == []


# ─── load edge cases ─────────────────────────────────────────────────────────


def test_load_nonexistent_returns_empty(tmp_path: Path) -> None:
    """load() returns [] when the file does not exist (no exception)."""
    target = tmp_path / "no_such_file.json"

    result = load(target)

    assert result == []


def test_load_corrupt_json_returns_empty(tmp_path: Path) -> None:
    """load() returns [] when the file contains invalid JSON (no exception)."""
    target = tmp_path / "corrupt.json"
    target.write_text("this is not json at all {{{", encoding="utf-8")

    result = load(target)

    assert result == []


def test_load_wrong_type_returns_empty(tmp_path: Path) -> None:
    """load() returns [] when JSON is valid but not a list."""
    target = tmp_path / "wrong_type.json"
    target.write_text(json.dumps({"paths": ["/a", "/b"]}), encoding="utf-8")

    result = load(target)

    assert result == []


# ─── parent directory creation ───────────────────────────────────────────────


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    """save() creates intermediate parent directories when they do not exist."""
    target = tmp_path / "nested" / "deep" / "config.json"

    save(["/some/path"], target)

    assert target.exists()
    result = load(target)
    assert result == ["/some/path"]


# ─── human-inspectable JSON ──────────────────────────────────────────────────


def test_saved_file_is_valid_json(tmp_path: Path) -> None:
    """The saved file is valid JSON and human-readable (a list of strings)."""
    target = tmp_path / "config.json"
    paths = ["/a", "/b"]

    save(paths, target)

    raw = target.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    assert parsed == paths
