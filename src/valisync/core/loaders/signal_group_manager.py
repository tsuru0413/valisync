from __future__ import annotations

from valisync.core.models import Signal, SignalGroup

_FORMAT_KEY_PREFIX: dict[str, str] = {"MDF4": "mf4", "CSV": "csv"}
KEY_SEPARATOR = "::"


class SignalGroupManager:
    """Manages loaded Signal_Groups under unique per-load keys.

    Each added group receives a key such as ``mf4_1`` / ``csv_2``, derived from
    its file format plus a per-format counter. The key namespaces every signal
    name (``mf4_1::speed``) so signals from different files — including re-loads
    of the same path — never collide. The counter never decrements, so a key is
    never reused after removal. Recovering the display name (original signal
    name and source file) is left to the GUI layer.
    """

    def __init__(self) -> None:
        self._groups: dict[str, SignalGroup] = {}
        self._counters: dict[str, int] = {}

    def add(self, group: SignalGroup) -> str:
        """Register a Signal_Group and return its assigned key.

        Duplicate source paths are allowed; each load receives a distinct key.
        """
        prefix = _FORMAT_KEY_PREFIX.get(group.file_format)
        if prefix is None:
            raise ValueError(f"unsupported file_format: {group.file_format!r}")
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        key = f"{prefix}_{self._counters[prefix]}"
        self._groups[key] = group
        return key

    def remove(self, key: str) -> SignalGroup:
        """Remove and return the Signal_Group registered under ``key``.

        Dependency checking against Derived_Signals (Req 4.5) is the Session's
        responsibility; this method removes unconditionally.
        """
        try:
            return self._groups.pop(key)
        except KeyError:
            raise KeyError(f"no Signal_Group registered under key: {key!r}") from None

    @property
    def keys(self) -> list[str]:
        """Keys of all registered groups, in insertion order."""
        return list(self._groups)

    def group(self, key: str) -> SignalGroup:
        """Return the Signal_Group registered under ``key`` (original signal names)."""
        return self._groups[key]

    def signals(self) -> list[Signal]:
        """Return every signal across all groups, name-spaced by its group key.

        The returned Signals share the stored timestamp/value arrays; only the
        name is rewritten to ``{key}{KEY_SEPARATOR}{original_name}``.
        """
        result: list[Signal] = []
        for key, group in self._groups.items():
            for sig in group.signals:
                result.append(
                    Signal(
                        name=f"{key}{KEY_SEPARATOR}{sig.name}",
                        timestamps=sig.timestamps,
                        values=sig.values,
                        file_format=sig.file_format,
                        bus_type=sig.bus_type,
                        source_file=sig.source_file,
                        metadata=sig.metadata,
                    )
                )
        return result
