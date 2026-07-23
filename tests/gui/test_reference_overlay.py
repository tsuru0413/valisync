"""Tests for reference_overlay (E-2b — reference-file same-name auto-overlay).

Pure-Python VM-level logic (spec §3): the 5-step matching/skip-counting
algorithm, exercised directly via GraphPanelVM + Session (no MainWindow/Qt
widget needed — see module docstring in reference_overlay.py).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from valisync.core.models import Signal, SignalGroup
from valisync.core.session import Session
from valisync.gui.reference_overlay import (
    OverlayResult,
    file_display_name,
    format_overlay_summary,
    overlay_reference_signals,
)
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

_BASE_DIR = Path(__file__).resolve().parent


def _sig(name: str, unit: str | None = None, deduplicated: bool = False) -> Signal:
    metadata: dict[str, object] = {}
    if unit is not None:
        metadata["unit"] = unit
    if deduplicated:
        metadata["name_deduplicated"] = True
    return Signal(
        name=name,
        timestamps=np.array([0.0, 1.0, 2.0], dtype=np.float64),
        values=np.array([0.0, 10.0, 20.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
        metadata=metadata,
    )


def _add_group(session: Session, path_name: str, *signals: Signal) -> str:
    """Register *signals* as one SignalGroup (one "file") and return its key."""
    return session._groups.add(
        SignalGroup(
            signals=tuple(signals),
            source_path=_BASE_DIR / path_name,
            file_format="CSV",
            loaded_at=datetime.now(),
        )
    )


def _bare_key(session: Session, group_key: str, bare_name: str) -> str:
    """Namespaced key for *bare_name* within *group_key* (post-registration)."""
    return next(
        s.name
        for s in session.group_signals(group_key)
        if s.name.endswith(f"::{bare_name}")
    )


# ─── Matching / adding ──────────────────────────────────────────────────────


def test_overlay_adds_matching_signal_to_same_axis() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed", unit="km/h"))
    ref_speed = _bare_key(session, ref_key, "speed")
    tgt_speed = _bare_key(session, tgt_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result == OverlayResult(
        total=1, added=1, no_match=0, unit_mismatch=0, already_present=0, ambiguous=0
    )
    entries = panel.plotted_entries()
    assert {(sk, ax) for _eid, sk, ax in entries} == {(ref_speed, 0), (tgt_speed, 0)}


def test_overlay_only_scans_reference_group_entries() -> None:
    """total (母数) counts only entries whose group is the reference — an
    entry from some THIRD (unrelated) group already on the panel is ignored."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed", unit="km/h"))
    other_key = _add_group(session, "other.csv", _sig("rpm", unit="rpm"))
    ref_speed = _bare_key(session, ref_key, "speed")
    other_rpm = _bare_key(session, other_key, "rpm")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)
    panel.add_signal_to_axis(other_rpm, 1)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.total == 1  # the "other" entry is not counted
    assert result.added == 1


# ─── Skip: no match ─────────────────────────────────────────────────────────


def test_overlay_no_match_when_target_lacks_bare_name() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("rpm", unit="rpm"))
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result == OverlayResult(
        total=1, added=0, no_match=1, unit_mismatch=0, already_present=0, ambiguous=0
    )


def test_overlay_unknown_target_key_is_all_no_match() -> None:
    """An unknown target_key (KeyError from group_signals) behaves as an
    empty file — every reference entry is a no-match, nothing raises."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, "no_such_key")

    assert result.total == 1
    assert result.no_match == 1
    assert result.added == 0


# ─── Skip: unit mismatch ────────────────────────────────────────────────────


def test_overlay_unit_mismatch_skips() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed", unit="mph"))
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.unit_mismatch == 1
    assert result.added == 0


def test_overlay_both_units_empty_passes() -> None:
    """Exact-string comparison: both missing/empty units counts as a match
    (spec §3 判断点3 — real ADAS data commonly lacks unit metadata)."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed"))  # no unit metadata
    tgt_key = _add_group(session, "tgt.csv", _sig("speed"))  # no unit metadata
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.added == 1
    assert result.unit_mismatch == 0


def test_overlay_one_side_empty_unit_is_a_mismatch() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed"))  # no unit metadata
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.unit_mismatch == 1
    assert result.added == 0


# ─── Skip: already present ──────────────────────────────────────────────────


def test_overlay_already_present_is_not_re_added() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed", unit="km/h"))
    ref_speed = _bare_key(session, ref_key, "speed")
    tgt_speed = _bare_key(session, tgt_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)
    panel.add_signal_to_axis(tgt_speed, 0)  # already overlaid once

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result == OverlayResult(
        total=1, added=0, no_match=0, unit_mismatch=0, already_present=1, ambiguous=0
    )
    # Still exactly the 2 original entries — no duplicate third entry.
    assert len(panel.plotted_entries()) == 2


# ─── Skip: ambiguous (LD-08 dedup) ──────────────────────────────────────────


def test_overlay_ambiguous_when_reference_entry_is_deduplicated() -> None:
    session = Session()
    ref_key = _add_group(
        session, "ref.csv", _sig("spd[0]", unit="km/h", deduplicated=True)
    )
    tgt_key = _add_group(session, "tgt.csv", _sig("spd[0]", unit="km/h"))
    ref_spd = _bare_key(session, ref_key, "spd[0]")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_spd, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.ambiguous == 1
    assert result.added == 0
    assert result.no_match == 0  # excluded BEFORE the search, not "no match"


def test_overlay_ambiguous_when_candidate_is_deduplicated() -> None:
    """The reference's own name is un-flagged; a literal bare-name match
    happens to be a dedup-suffixed candidate in the target file. Checked on
    both sides (spec §3 step 5 — a silent bad pairing is undetectable)."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("spd[0]", unit="km/h"))
    tgt_key = _add_group(
        session, "tgt.csv", _sig("spd[0]", unit="km/h", deduplicated=True)
    )
    ref_spd = _bare_key(session, ref_key, "spd[0]")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_spd, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.ambiguous == 1
    assert result.added == 0


def test_overlay_array_expansion_name_is_not_ambiguous() -> None:
    """LD-14 array-expansion names (e.g. "Mat[0]") look identical to a LD-08
    dedup suffix but carry NO name_deduplicated flag — deterministic and
    cross-file comparable, so eligible for ordinary matching (spec §3 step 5)."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("Mat[0]", unit="m"))
    tgt_key = _add_group(session, "tgt.csv", _sig("Mat[0]", unit="m"))
    ref_mat = _bare_key(session, ref_key, "Mat[0]")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_mat, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.ambiguous == 0
    assert result.added == 1


# ─── Multi-entry partition ──────────────────────────────────────────────────


def test_overlay_partitions_multiple_reference_entries() -> None:
    session = Session()
    ref_key = _add_group(
        session,
        "ref.csv",
        _sig("speed", unit="km/h"),  # will match
        _sig("rpm", unit="rpm"),  # no match in target
        _sig("temp", unit="C"),  # unit mismatch
    )
    tgt_key = _add_group(
        session,
        "tgt.csv",
        _sig("speed", unit="km/h"),
        _sig("temp", unit="F"),
    )
    ref_speed = _bare_key(session, ref_key, "speed")
    ref_rpm = _bare_key(session, ref_key, "rpm")
    ref_temp = _bare_key(session, ref_key, "temp")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)
    panel.create_new_axis(ref_rpm)  # axis 1
    panel.create_new_axis(ref_temp)  # axis 2

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.total == 3
    assert result.added == 1
    assert result.no_match == 1
    assert result.unit_mismatch == 1
    assert result.already_present == 0
    assert result.ambiguous == 0


# ─── format_overlay_summary ─────────────────────────────────────────────────


def test_format_summary_no_reference_signals() -> None:
    result = OverlayResult(
        total=0, added=0, no_match=0, unit_mismatch=0, already_present=0, ambiguous=0
    )
    assert (
        format_overlay_summary(result, "b.csv") == "基準の信号がプロットされていません"
    )


def test_format_summary_all_done() -> None:
    result = OverlayResult(
        total=2, added=0, no_match=0, unit_mismatch=0, already_present=2, ambiguous=0
    )
    assert format_overlay_summary(result, "b.csv") == "すべて重ね済みです"


def test_format_summary_general_case_omits_zero_clauses() -> None:
    result = OverlayResult(
        total=1, added=1, no_match=0, unit_mismatch=0, already_present=0, ambiguous=0
    )
    assert (
        format_overlay_summary(result, "b.csv") == "b.csv の同名信号を 1 件重ねました"
    )


def test_format_summary_general_case_includes_nonzero_clauses() -> None:
    result = OverlayResult(
        total=4, added=1, no_match=1, unit_mismatch=1, already_present=1, ambiguous=0
    )
    msg = format_overlay_summary(result, "b.csv")
    assert (
        msg == "b.csv の同名信号を 1 件重ねました（同名なし 1・単位不一致 1・済み 1）"
    )


def test_format_summary_ambiguous_clause() -> None:
    result = OverlayResult(
        total=1, added=0, no_match=0, unit_mismatch=0, already_present=0, ambiguous=1
    )
    msg = format_overlay_summary(result, "b.csv")
    assert msg == "b.csv の同名信号を 0 件重ねました（曖昧 1）"


# ─── file_display_name ──────────────────────────────────────────────────────


def test_file_display_name_no_collision(tmp_path: Path) -> None:
    session = Session()
    k1 = session._groups.add(
        SignalGroup((), (tmp_path / "a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = session._groups.add(
        SignalGroup((), (tmp_path / "b.csv").absolute(), "CSV", datetime.now())
    )
    assert file_display_name(session, [k1, k2], k2) == "b.csv"


def test_file_display_name_qualifies_on_basename_collision(tmp_path: Path) -> None:
    """UXG-09: re-opening the same path twice yields distinct keys but the
    same basename — qualify with the key so the summary is unambiguous."""
    session = Session()
    k1 = session._groups.add(
        SignalGroup((), (tmp_path / "a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = session._groups.add(
        SignalGroup((), (tmp_path / "a.csv").absolute(), "CSV", datetime.now())
    )
    assert file_display_name(session, [k1, k2], k2) == f"a.csv ({k2})"
