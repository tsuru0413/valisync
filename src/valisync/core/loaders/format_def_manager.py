from __future__ import annotations

import json
from pathlib import Path

from valisync.core.models.format_def import Delimiter, FormatDefinition

# Characters forbidden in filenames on Windows and Unix.
_FORBIDDEN_NAME_CHARS = frozenset("\\/:\x00")


def _validate_name_for_fs(name: str) -> None:
    """Raise ValueError if name contains characters unsafe for use as a filename."""
    bad = _FORBIDDEN_NAME_CHARS.intersection(name)
    if bad:
        raise ValueError(
            f"FormatDefinition name contains forbidden characters {sorted(bad)}: {name!r}"
        )


def _to_dict(fd: FormatDefinition) -> dict[str, object]:
    return {
        "name": fd.name,
        "delimiter": fd.delimiter.value,
        "timestamp_column": fd.timestamp_column,
        "timestamp_unit": fd.timestamp_unit,
        "signal_start_column": fd.signal_start_column,
        "signal_end_column": fd.signal_end_column,
        "has_header": fd.has_header,
        "has_unit_row": fd.has_unit_row,
    }


def _from_dict(data: dict[str, object]) -> FormatDefinition:
    return FormatDefinition(
        name=str(data["name"]),
        delimiter=Delimiter(data["delimiter"]),
        timestamp_column=int(str(data["timestamp_column"])),
        timestamp_unit=str(data["timestamp_unit"]),
        signal_start_column=int(str(data["signal_start_column"])),
        signal_end_column=int(str(data["signal_end_column"])),
        has_header=bool(data["has_header"]),
        has_unit_row=bool(data.get("has_unit_row", False)),
    )


class FormatDefinitionManager:
    """CRUD operations and JSON persistence for FormatDefinition objects."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def _path_for(self, name: str) -> Path:
        return self._data_dir / f"{name}.json"

    def save(self, format_def: FormatDefinition) -> None:
        """Persist FormatDefinition to JSON. Raises ValueError on duplicate name."""
        _validate_name_for_fs(format_def.name)

        existing_names = {fd.name for fd in self.load_all()}
        if format_def.name in existing_names:
            raise ValueError(
                f"FormatDefinition '{format_def.name}' already exists;"
                " delete it first to overwrite"
            )

        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(format_def.name)
        path.write_text(
            json.dumps(_to_dict(format_def), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_all(self) -> list[FormatDefinition]:
        """Return all persisted FormatDefinitions sorted by name."""
        if not self._data_dir.exists():
            return []
        result: list[FormatDefinition] = []
        for path in sorted(self._data_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result.append(_from_dict(data))
            except (KeyError, ValueError, json.JSONDecodeError):
                pass  # skip malformed files silently
        return result

    def delete(self, name: str) -> None:
        """Delete the FormatDefinition with the given name. Raises FileNotFoundError if absent."""
        _validate_name_for_fs(name)
        path = self._path_for(name)
        if not path.exists():
            raise FileNotFoundError(
                f"FormatDefinition '{name}' not found in {self._data_dir}"
            )
        path.unlink()
