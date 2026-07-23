"""Display-name resolution for namespaced signal keys (E-0, UX-19).

Signal keys are namespaced as ``{group_key}{KEY_SEPARATOR}{orig}`` (e.g.
``mf4_1::VehSpd``) so every signal from every load stays unique — the offset
dictionaries, formula-engine dependency records, View reverse-lookups, and D&D
mime all depend on this exact key (spec §1). None of that changes here: this
module only computes what to *show* the user instead of the raw key. Callers
resolve a display string via one of the four functions below and use it purely
for rendering (readout rows, menu labels, CSV headers, preview text) — the
signal_key itself keeps flowing through every other code path unchanged.

Pure Python — no Qt/PySide6 imports (spec §1.1).
"""

from __future__ import annotations

from collections.abc import Iterable

from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR

#: Bare name injected into the csv_header_names collision population so an
#: actual signal named "timestamp" gets disambiguated from the leading
#: timestamp column (spec §1.1). Never collides with a real group_key.
_TIMESTAMP_POOL_GROUP = "\0timestamp"


def split_key(signal_key: str) -> tuple[str, str]:
    """Split a namespaced signal key into ``(group_key, bare_name)``.

    Splits on the FIRST ``KEY_SEPARATOR`` only, so a bare name that itself
    contains the separator (e.g. an original signal literally named
    ``"csv::a"``) is preserved verbatim in the second element.

    Contract: a *signal_key* with no separator at all returns ``("", signal_key)``
    — the whole string goes to the name side, matching the existing fallback
    convention in channel_browser_vm.py:113 / graph_panel_vm.py:479 (never
    degrade to an empty bare name).
    """
    parts = signal_key.split(KEY_SEPARATOR, 1)
    if len(parts) == 1:
        return ("", signal_key)
    return (parts[0], parts[1])


def qualified_name(signal_key: str) -> str:
    """Return the collision-disambiguated display form ``"{bare} ({group_key})"``.

    Uses the group key (not ``Session.source_name``'s basename) because two
    loads of the same file share a basename but always distinct keys
    (UXG-09) — qualifying by group_key stays unique even then.
    """
    group_key, bare = split_key(signal_key)
    return f"{bare} ({group_key})"


def display_names(keys: Iterable[str]) -> dict[str, str]:
    """Resolve each of *keys* to its display string, scoped to this key set.

    A bare name "collides" when it is shared by 2+ DISTINCT group_keys among
    *keys*. Colliding keys resolve to :func:`qualified_name`; every other key
    resolves to its bare name. Repeating the same signal_key more than once
    (e.g. the same signal plotted twice) does not count as a collision — only
    distinct group_keys sharing a bare name do (spec §1.1).
    """
    keys_list = list(keys)
    parsed: dict[str, tuple[str, str]] = {}
    groups_by_bare: dict[str, set[str]] = {}
    for key in keys_list:
        group_key, bare = split_key(key)
        parsed[key] = (group_key, bare)
        groups_by_bare.setdefault(bare, set()).add(group_key)

    result: dict[str, str] = {}
    for key in keys_list:
        group_key, bare = parsed[key]
        if len(groups_by_bare[bare]) >= 2:
            result[key] = f"{bare} ({group_key})"
        else:
            result[key] = bare
    return result


def csv_header_names(keys: Iterable[str]) -> dict[str, str]:
    """Resolve each of *keys* to a CSV header string, scoped to this key set.

    Same distinct-group_key collision rule as :func:`display_names`, but the
    collision population additionally contains a permanent ``"timestamp"``
    bare name (not a real signal_key — used only inside this function) so an
    actual signal literally named ``timestamp`` still gets disambiguated from
    the exporter's leading timestamp column. Colliding keys resolve to the
    compact, whitespace-free ``"{bare}({group_key})"`` form (the CSV export
    delimiter can itself be a space, so the space-separated *display_names*
    form would corrupt the column structure — spec §1.1).
    """
    keys_list = list(keys)
    parsed: dict[str, tuple[str, str]] = {}
    groups_by_bare: dict[str, set[str]] = {"timestamp": {_TIMESTAMP_POOL_GROUP}}
    for key in keys_list:
        group_key, bare = split_key(key)
        parsed[key] = (group_key, bare)
        groups_by_bare.setdefault(bare, set()).add(group_key)

    result: dict[str, str] = {}
    for key in keys_list:
        group_key, bare = parsed[key]
        if len(groups_by_bare[bare]) >= 2:
            result[key] = f"{bare}({group_key})"
        else:
            result[key] = bare
    return result
