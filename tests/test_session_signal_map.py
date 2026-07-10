from pathlib import Path
from types import MappingProxyType

import pytest

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session

_FMT = FormatDefinition(
    name="fmt",
    delimiter=Delimiter.COMMA,
    timestamp_column=0,
    timestamp_unit="sec",
    signal_start_column=1,
    signal_end_column=2,
    has_header=True,
)


def _load_two(tmp_path: Path) -> Session:
    csv = tmp_path / "d.csv"
    rows = ["t,s1,s2"] + [f"{i * 0.1:.1f},{i}.0,{i * 2}.0" for i in range(5)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    session = Session()
    session.load(csv, _FMT)
    return session


def test_signal_map_matches_signals(tmp_path: Path) -> None:
    session = _load_two(tmp_path)
    sm = session.signal_map()
    assert set(sm.keys()) == {s.name for s in session.signals()}


def test_signal_map_is_read_only(tmp_path: Path) -> None:
    session = _load_two(tmp_path)
    sm = session.signal_map()
    assert isinstance(sm, MappingProxyType)
    with pytest.raises(TypeError):
        sm["x"] = None  # type: ignore[index]
