from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

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
        self._namespaced_list: list[Signal] | None = None
        self._namespaced_map: dict[str, Signal] | None = None

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
        self._invalidate_namespaced()
        return key

    def remove(self, key: str) -> SignalGroup:
        """Remove and return the Signal_Group registered under ``key``.

        Dependency checking against Derived_Signals (Req 4.5) is the Session's
        responsibility; this method removes unconditionally.
        """
        try:
            group = self._groups.pop(key)
        except KeyError:
            raise KeyError(f"no Signal_Group registered under key: {key!r}") from None
        self._invalidate_namespaced()
        return group

    @property
    def keys(self) -> list[str]:
        """Keys of all registered groups, in insertion order."""
        return list(self._groups)

    def group(self, key: str) -> SignalGroup:
        """Return the Signal_Group registered under ``key`` (original signal names)."""
        return self._groups[key]

    def source_name(self, key: str) -> str:
        """Original source filename (basename) for the group under ``key``.

        Public recovery point for the GUI display name (the class otherwise
        leaves display-name recovery to the GUI layer). Raises KeyError if the
        key is unknown.
        """
        return self._groups[key].source_path.name

    @staticmethod
    def _namespaced(key: str, group: SignalGroup) -> list[Signal]:
        """Rewrite a group's signal names to ``{key}{KEY_SEPARATOR}{name}``.

        The returned Signals share the stored timestamp/value arrays.
        """
        result: list[Signal] = []
        for sig in group.signals:
            ns_sig = Signal(
                name=f"{key}{KEY_SEPARATOR}{sig.name}",
                timestamps=sig.timestamps,
                values=sig.values,
                file_format=sig.file_format,
                bus_type=sig.bus_type,
                source_file=sig.source_file,
                metadata=sig.metadata,
            )
            # namespaced ラッパーは呼び出しごとに新規生成される(signals() は
            # 毎回リストを作り直す)ので、sorted_view の単調性スキャン結果を
            # 元の長寿命 Signal に委譲して共有する。委譲は timestamps/values の
            # 配列オブジェクトが元 Signal と同一であることが前提
            # (offset 適用後の別配列 Signal には絶対に付けないこと)。
            object.__setattr__(ns_sig, "_sorted_view_delegate", sig)
            result.append(ns_sig)
        return result

    def _invalidate_namespaced(self) -> None:
        """Drop the namespaced caches; rebuilt lazily on next access."""
        self._namespaced_list = None
        self._namespaced_map = None

    def _ensure_namespaced(self) -> None:
        """Build and cache the namespaced signal list/map once (idempotent).

        The expensive work — creating one namespaced Signal wrapper per signal
        across all groups — happens here a single time per load/unload, not on
        every ``signals()``/``signal_map()`` call (FU-08). The list preserves
        every signal (duplicate namespaced names included); the map is keyed by
        name with last-wins dedupe, matching the historical ``signals()``-to-dict
        behaviour its callers relied on.
        """
        if self._namespaced_list is not None:
            return
        result: list[Signal] = []
        for key, group in self._groups.items():
            result.extend(self._namespaced(key, group))
        self._namespaced_list = result
        self._namespaced_map = {sig.name: sig for sig in result}

    def group_signals(self, key: str) -> list[Signal]:
        """Namespaced signals for a single group (KeyError if key is unknown).

        Lets callers fetch one file's signals without scanning every group.
        """
        return self._namespaced(key, self._groups[key])

    def signals(self) -> list[Signal]:
        """Return every signal across all groups, name-spaced by its group key."""
        self._ensure_namespaced()
        assert self._namespaced_list is not None
        return list(self._namespaced_list)

    def signal_map(self) -> Mapping[str, Signal]:
        """Read-only ``{namespaced_name: Signal}`` view, cached (FU-08).

        Last-wins on duplicate namespaced names (same as building a dict from
        ``signals()``). Returned as a ``MappingProxyType`` so callers cannot
        mutate — and corrupt — the shared cache.
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        return MappingProxyType(self._namespaced_map)
