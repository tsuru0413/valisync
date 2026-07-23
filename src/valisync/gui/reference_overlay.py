"""Reference-file overlay (E-2b) — auto-overlay a target file's same-named
signals onto the reference file's plotted axes.

Pure Python (no Qt — same isolation tier as ``display_names.py``), so the
matching/skip-counting algorithm is Layer-A testable without constructing a
QMainWindow. MainWindow's handler (spec §3's "重ねハンドラ") is the thin
Qt-facing entry point: it resolves the active panel / reference key / target
key, calls :func:`overlay_reference_signals`, then renders the returned
:class:`OverlayResult` via :func:`format_overlay_summary`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from valisync.gui import strings as S
from valisync.gui.display_names import split_key

if TYPE_CHECKING:
    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


@dataclass(frozen=True)
class OverlayResult:
    """Outcome counts, partitioning the reference-file entries scanned.

    ``total`` is the denominator (spec §3: 母数=基準エントリ) and always
    equals ``added + no_match + unit_mismatch + already_present + ambiguous``.
    """

    total: int
    added: int
    no_match: int
    unit_mismatch: int
    already_present: int
    ambiguous: int


def overlay_reference_signals(
    panel: GraphPanelVM,
    session: Session,
    reference_key: str,
    target_key: str,
) -> OverlayResult:
    """Overlay *target_key*'s same-named signals onto *panel*'s reference entries.

    5 steps (spec §3, verbatim):

    1. Scan ``panel.plotted_entries()`` for entries whose group is
       *reference_key* (母数=基準エントリ — snapshotted upfront so the scan is
       unaffected by entries this same call adds).
    2. For each, look up the bare name in *target_key*'s ``group_signals``
       (bare names are unique within one file — loader-guaranteed via ``[idx]``
       LD-08 disambiguation).
    3. A match is added to the SAME axis via ``panel.add_signal_to_axis``.
    4. Skips (all counted, nothing raises):
       - no bare-name match → ``no_match``
       - unit mismatch (``sig.metadata`` exact string compare, missing
         treated as ``""`` — so both-empty passes, one-empty-one-not fails)
         → ``unit_mismatch``
       - an entry already at that exact ``(key, axis)`` pair → ``already_present``
       - the reference entry's OR the candidate's name involved a LD-08
         dedup suffix (``metadata["name_deduplicated"]``) → ``ambiguous``.
         The ``[idx]`` disambiguation is assigned independently per file, so
         the same literal suffix in two files is not safely comparable —
         checked on BOTH sides (matching this literal string can happen
         with the reference's own name un-flagged, purely by coincidence,
         while the target's candidate IS flagged) since a silent bad pairing
         would be undetectable by any later gate (spec §3 step 5 — 安全側).
    """
    reference_entries = [
        (signal_key, axis_index)
        for _entry_id, signal_key, axis_index in panel.plotted_entries()
        if split_key(signal_key)[0] == reference_key
    ]
    total = len(reference_entries)

    try:
        target_signals = session.group_signals(target_key)
    except KeyError:
        target_signals = []
    target_by_bare = {split_key(sig.name)[1]: sig for sig in target_signals}

    signal_map = session.signal_map()
    existing_pairs = {
        (signal_key, axis_index)
        for _eid, signal_key, axis_index in panel.plotted_entries()
    }

    added = no_match = unit_mismatch = already_present = ambiguous = 0
    for signal_key, axis_index in reference_entries:
        _, bare = split_key(signal_key)
        ref_sig = signal_map.get(signal_key)
        if ref_sig is not None and ref_sig.metadata.get("name_deduplicated"):
            ambiguous += 1
            continue

        candidate = target_by_bare.get(bare)
        if candidate is None:
            no_match += 1
            continue
        if candidate.metadata.get("name_deduplicated"):
            ambiguous += 1
            continue

        ref_unit = ref_sig.metadata.get("unit", "") if ref_sig is not None else ""
        cand_unit = candidate.metadata.get("unit", "")
        if ref_unit != cand_unit:
            unit_mismatch += 1
            continue

        pair = (candidate.name, axis_index)
        if pair in existing_pairs:
            already_present += 1
            continue

        panel.add_signal_to_axis(candidate.name, axis_index)
        existing_pairs.add(pair)
        added += 1

    return OverlayResult(
        total=total,
        added=added,
        no_match=no_match,
        unit_mismatch=unit_mismatch,
        already_present=already_present,
        ambiguous=ambiguous,
    )


def file_display_name(session: Session, loaded_keys: list[str], key: str) -> str:
    """Basename for *key*, qualified with its group key when 2+ loaded files
    share the same basename (UXG-09 — re-opening the same path yields distinct
    keys but an identical basename). Same disambiguation rule as
    ``display_names.qualified_name``, applied to file basenames instead of
    signal bare names (spec §3 判断点4).
    """
    name = session.source_name(key)
    collision = any(
        other != key and session.source_name(other) == name for other in loaded_keys
    )
    return f"{name} ({key})" if collision else name


def format_overlay_summary(result: OverlayResult, target_display_name: str) -> str:
    """Render *result* as the status-bar summary text (spec §3)."""
    if result.total == 0:
        return S.STATUS_OVERLAY_NO_REFERENCE_SIGNALS
    if result.already_present == result.total:
        return S.STATUS_OVERLAY_ALL_DONE

    clauses: list[str] = []
    if result.no_match:
        clauses.append(S.OVERLAY_CLAUSE_NO_MATCH_TMPL.format(n=result.no_match))
    if result.unit_mismatch:
        clauses.append(
            S.OVERLAY_CLAUSE_UNIT_MISMATCH_TMPL.format(n=result.unit_mismatch)
        )
    if result.already_present:
        clauses.append(S.OVERLAY_CLAUSE_ALREADY_TMPL.format(n=result.already_present))
    if result.ambiguous:
        clauses.append(S.OVERLAY_CLAUSE_AMBIGUOUS_TMPL.format(n=result.ambiguous))
    detail = f"（{'・'.join(clauses)}）" if clauses else ""  # noqa: RUF001

    return S.STATUS_OVERLAY_SUMMARY_TMPL.format(
        target=target_display_name, n=result.added, detail=detail
    )
