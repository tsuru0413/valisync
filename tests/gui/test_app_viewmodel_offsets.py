"""Layer A: AppViewModel のオフセット状態 (R14)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel


def _app_with_csv() -> tuple[AppViewModel, str]:
    """1 グループ (csv_1) を読み込んだ AppViewModel と、その名前空間付き信号キーを返す。"""
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1"] + [f"{i * 0.01:.3f},{i % 10}.0" for i in range(20)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    app = AppViewModel()
    app.request_load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    signal_key = sorted(s.name for s in app.signals())[0]
    return app, signal_key


def test_apply_offset_signal_scope_accumulates() -> None:
    app = AppViewModel()
    app.apply_offset("csv_1::speed", 0.10, "signal")
    app.apply_offset("csv_1::speed", 0.05, "signal")
    assert app.signal_offsets == pytest.approx({"csv_1::speed": 0.15})
    assert app.file_offsets == {}


def test_apply_offset_group_scope_keys_on_group_prefix() -> None:
    app = AppViewModel()
    app.apply_offset("csv_1::speed", 0.20, "group")
    assert app.file_offsets == {"csv_1": 0.20}
    assert app.signal_offsets == {}


def test_group_apply_resets_sibling_signal_offsets() -> None:
    app = AppViewModel()
    # A sibling in the same group already has a per-signal offset.
    app.apply_offset("csv_1::speed", 0.3, "signal")
    # Applying a group offset must discard sibling per-signal offsets (user
    # decision): the group lands on one uniform offset.
    app.apply_offset("csv_1::rpm", 0.2, "group")
    assert app.file_offsets == {"csv_1": 0.2}
    assert app.signal_offsets == {}


def test_apply_offset_notifies_offsets() -> None:
    app = AppViewModel()
    seen: list[str] = []
    app.subscribe(seen.append)
    app.apply_offset("csv_1::speed", 0.1, "signal")
    assert "offsets" in seen


def test_offset_properties_return_copies() -> None:
    app = AppViewModel()
    app.apply_offset("csv_1::speed", 0.1, "signal")
    snapshot = app.signal_offsets
    snapshot["csv_1::speed"] = 999.0
    assert app.signal_offsets == {"csv_1::speed": 0.1}


def test_unload_purges_offsets_for_group() -> None:
    app, signal_key = _app_with_csv()
    group_key = signal_key.split("::", 1)[0]
    # Apply group first, then signal so both dicts are non-empty for the
    # pre-condition check (group scope would clear signal offsets if applied
    # second, leaving signal_offsets empty).
    app.apply_offset(signal_key, 0.2, "group")
    app.apply_offset(signal_key, 0.1, "signal")
    assert app.signal_offsets and app.file_offsets
    app.unload_file(group_key)
    assert app.signal_offsets == {}
    assert app.file_offsets == {}


def test_inspect_includes_offsets() -> None:
    app = AppViewModel()
    app.apply_offset("csv_1::speed", 0.1, "signal")
    snap = app.inspect()
    assert snap["signal_offsets"] == {"csv_1::speed": 0.1}
    assert snap["file_offsets"] == {}
