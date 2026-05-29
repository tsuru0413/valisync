"""Persistence helpers for registered data-source folder paths.

The on-disk format is a plain JSON array of strings so the file is
human-inspectable and easy to edit by hand.  Writes are atomic (temp file +
os.replace) to prevent half-written files from corrupting the saved state.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path


def save(paths: Sequence[str | Path], file: Path) -> None:
    """Persist *paths* to *file* as a JSON array of strings.

    Parent directories are created when they do not exist.  The write is
    atomic: data is written to a sibling temp file that is then renamed over
    *file*, so a crash mid-write never leaves a partially-written file.
    """
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)

    serialisable = [str(p) for p in paths]

    # Atomic write: write to a temp file in the same directory, then replace.
    fd, tmp_path = tempfile.mkstemp(dir=file.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(serialisable, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, file)
    except BaseException:
        # Clean up the temp file on any failure to avoid leaving debris.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def load(file: Path) -> list[str]:
    """Load the list of data-source paths from *file*.

    Returns an empty list when:
    - *file* does not exist
    - *file* contains invalid JSON
    - the JSON value is not a list

    Never raises.
    """
    file = Path(file)
    if not file.exists():
        return []

    try:
        text = file.read_text(encoding="utf-8")
        parsed = json.loads(text)
    except (OSError, json.JSONDecodeError, ValueError):
        return []

    if not isinstance(parsed, list):
        return []

    # Coerce every element to str; skip non-string entries gracefully.
    return [str(item) for item in parsed]
