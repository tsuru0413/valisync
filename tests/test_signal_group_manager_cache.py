from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup


def _sig(name: str, vs: list[float]) -> Signal:
    n = len(vs)
    return Signal(
        name=name,
        timestamps=np.arange(n, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={},
    )


def _group(signals: list[Signal]) -> SignalGroup:
    return SignalGroup(
        signals=tuple(signals),
        source_path=Path.cwd() / "f.mf4",
        file_format="MDF4",
        loaded_at=datetime.now(),
    )


def test_signal_map_content_and_namespacing() -> None:
    m = SignalGroupManager()
    key = m.add(_group([_sig("a", [1.0]), _sig("b", [2.0])]))
    sm = m.signal_map()
    assert set(sm.keys()) == {f"{key}::a", f"{key}::b"}
    assert [s.name for s in m.signals()] == [f"{key}::a", f"{key}::b"]


def test_signals_reflects_add_and_remove() -> None:
    m = SignalGroupManager()
    k1 = m.add(_group([_sig("a", [1.0])]))
    assert {s.name for s in m.signals()} == {f"{k1}::a"}
    k2 = m.add(_group([_sig("c", [3.0])]))
    assert {s.name for s in m.signals()} == {f"{k1}::a", f"{k2}::c"}
    m.remove(k1)
    assert {s.name for s in m.signals()} == {f"{k2}::c"}


def test_repeated_calls_reuse_same_wrapper() -> None:
    m = SignalGroupManager()
    key = m.add(_group([_sig("a", [1.0])]))
    assert m.signal_map()[f"{key}::a"] is m.signal_map()[f"{key}::a"]
    assert m.signals()[0] is m.signals()[0]


def test_signal_map_is_read_only() -> None:
    m = SignalGroupManager()
    key = m.add(_group([_sig("a", [1.0])]))
    sm = m.signal_map()
    assert isinstance(sm, MappingProxyType)
    with pytest.raises(TypeError):
        sm[f"{key}::a"] = _sig("x", [0.0])  # type: ignore[index]


def test_build_runs_once_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    m = SignalGroupManager()
    m.add(_group([_sig("a", [1.0]), _sig("b", [2.0])]))
    m.signals()  # ウォーム: 初回アクセスで構築を済ませる
    calls: list[str] = []
    orig = SignalGroupManager._namespaced

    def spy(key: str, group: SignalGroup) -> list[Signal]:
        calls.append(key)
        return orig(key, group)

    monkeypatch.setattr(SignalGroupManager, "_namespaced", staticmethod(spy))
    for _ in range(5):
        m.signals()
        m.signal_map()
    assert calls == []  # ウォーム済みキャッシュ→反復呼出で再構築ゼロ


def test_build_runs_once_at_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    # 大 group でも構築は1回のみ（O(N) 再構築の回帰を決定的に検出）
    m = SignalGroupManager()
    calls: list[str] = []
    orig = SignalGroupManager._namespaced

    def spy(key: str, group: SignalGroup) -> list[Signal]:
        calls.append(key)
        return orig(key, group)

    monkeypatch.setattr(SignalGroupManager, "_namespaced", staticmethod(spy))
    m.add(_group([_sig(f"s{i}", [float(i)]) for i in range(5000)]))
    for _ in range(10):
        m.signals()
        m.signal_map()
    assert len(calls) == 1  # 5000信号でも _namespaced 呼出は group あたり1回きり
