"""Tests for display_names.py (E-0, UX-19) — pure-function contract (spec §1.1).

Covers the 4 APIs' full contract: separator-less input, distinct-group_key
collision, same-key-repeated-is-not-a-collision, the injected "timestamp"
population for csv_header_names, and the whitespace-free CSV header form.
"""

from __future__ import annotations

from valisync.gui.display_names import (
    csv_header_names,
    display_names,
    qualified_name,
    split_key,
)

# ─── split_key ────────────────────────────────────────────────────────────────


def test_split_key_splits_on_first_separator() -> None:
    assert split_key("mf4_1::VehSpd") == ("mf4_1", "VehSpd")


def test_split_key_no_separator_returns_empty_group() -> None:
    """Contract: no KEY_SEPARATOR at all -> ("", whole input) — never an empty bare."""
    assert split_key("VehSpd") == ("", "VehSpd")


def test_split_key_splits_only_first_occurrence() -> None:
    """A bare name that itself contains '::' keeps it verbatim in the 2nd element."""
    assert split_key("csv_1::csv::a") == ("csv_1", "csv::a")


# ─── qualified_name ───────────────────────────────────────────────────────────


def test_qualified_name_format() -> None:
    assert qualified_name("mf4_1::VehSpd") == "VehSpd (mf4_1)"


# ─── display_names ────────────────────────────────────────────────────────────


def test_display_names_no_collision_uses_bare_name() -> None:
    result = display_names(["mf4_1::VehSpd"])
    assert result == {"mf4_1::VehSpd": "VehSpd"}


def test_display_names_distinct_group_keys_collide() -> None:
    """Same bare name from 2 DIFFERENT group_keys -> both qualified."""
    result = display_names(["mf4_1::VehSpd", "mf4_2::VehSpd"])
    assert result == {
        "mf4_1::VehSpd": "VehSpd (mf4_1)",
        "mf4_2::VehSpd": "VehSpd (mf4_2)",
    }


def test_display_names_non_colliding_signal_stays_bare_alongside_collision() -> None:
    result = display_names(["mf4_1::VehSpd", "mf4_2::VehSpd", "mf4_1::EngSpd"])
    assert result["mf4_1::EngSpd"] == "EngSpd"


def test_display_names_same_key_repeated_is_not_a_collision() -> None:
    """The exact same signal_key appearing twice (plotted twice) must NOT
    trigger qualification — only distinct group_keys sharing a bare name do."""
    result = display_names(["mf4_1::VehSpd", "mf4_1::VehSpd"])
    assert result == {"mf4_1::VehSpd": "VehSpd"}


def test_display_names_empty_input() -> None:
    assert display_names([]) == {}


def test_display_names_separator_less_keys_with_same_bare_collide() -> None:
    """Two separator-less keys share group_key "" -> NOT a collision (same group)."""
    result = display_names(["VehSpd", "VehSpd"])
    assert result == {"VehSpd": "VehSpd"}


# ─── csv_header_names ─────────────────────────────────────────────────────────


def test_csv_header_names_no_collision_uses_bare_name() -> None:
    result = csv_header_names(["mf4_1::VehSpd", "mf4_1::EngSpd"])
    assert result == {"mf4_1::VehSpd": "VehSpd", "mf4_1::EngSpd": "EngSpd"}


def test_csv_header_names_collision_uses_whitespace_free_form() -> None:
    """Collision form has NO space, unlike display_names' "{bare} ({group_key})"."""
    result = csv_header_names(["mf4_1::VehSpd", "mf4_2::VehSpd"])
    assert result == {
        "mf4_1::VehSpd": "VehSpd(mf4_1)",
        "mf4_2::VehSpd": "VehSpd(mf4_2)",
    }


def test_csv_header_names_timestamp_population_disambiguates_real_timestamp_signal() -> (
    None
):
    """A real signal literally named 'timestamp' collides with the injected
    pseudo-column population, even when it is the only such signal in the
    selection (spec §1.1)."""
    result = csv_header_names(["mf4_1::timestamp"])
    assert result == {"mf4_1::timestamp": "timestamp(mf4_1)"}


def test_csv_header_names_non_timestamp_signal_unaffected_by_population() -> None:
    result = csv_header_names(["mf4_1::VehSpd"])
    assert result == {"mf4_1::VehSpd": "VehSpd"}


def test_csv_header_names_same_key_repeated_is_not_a_collision() -> None:
    result = csv_header_names(["mf4_1::VehSpd", "mf4_1::VehSpd"])
    assert result == {"mf4_1::VehSpd": "VehSpd"}
