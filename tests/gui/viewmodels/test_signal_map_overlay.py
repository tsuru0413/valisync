"""offset overlay が O(loaded) でなく O(offset信号) であることを固定する。

`GraphPanelVM._signal_map()` は offset が立っている間、base map 全件を走査して
dict を作り直していた (prod 264k エントリ)。列キーを遅延解決する base map
(E-1 Task 6) とは構造的に両立しないため、ルックアップ時 overlay へ置換した。
ここは「全走査していない」ことを直接固定する — 結果の正しさだけを見るテストは
旧実装でも通ってしまい、退行を捕捉できない。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Mapping
from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal


class _CountingMap(Mapping[str, Signal]):
    """items()/__iter__ が呼ばれたら記録する base map スタブ."""

    def __init__(self, data: dict[str, Signal]) -> None:
        self._data = data
        self.full_scans = 0

    def __getitem__(self, k: str) -> Signal:
        return self._data[k]

    def __iter__(self) -> Iterator[str]:
        self.full_scans += 1
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _sig(name: str) -> Signal:
    ts = np.arange(3, dtype=np.float64)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.zeros(3),
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )


class _StubSession:
    """`_signal_map` が触る Session 面だけを持つスタブ (apply_offset の呼出を記録)."""

    def __init__(self, base: Mapping[str, Signal]) -> None:
        self._base = base
        self.offset_calls: list[tuple[str, float, float]] = []

    def signal_map(self) -> Mapping[str, Signal]:
        return self._base

    def apply_offset(
        self, sig: Signal, file_offset: float = 0.0, signal_offset: float = 0.0
    ) -> Signal:
        self.offset_calls.append((sig.name, file_offset, signal_offset))
        return Signal(
            name=sig.name,
            timestamps=sig.timestamps + file_offset + signal_offset,
            values=np.zeros(len(sig.timestamps)),
            file_format=sig.file_format,
            bus_type=sig.bus_type,
            source_file=sig.source_file,
        )


def _vm(
    base: Mapping[str, Signal],
    file_offsets: dict[str, float],
    signal_offsets: dict[str, float],
) -> tuple[object, _StubSession]:
    """生成コストを避けた最小組立て (`_signal_map` が読む3属性だけを与える).

    実コンストラクタは Session ロード済みの実データを要求し、そこに 500 件を
    積むと「全走査していない」という観測自体がロードコストに埋もれる。ここで
    見たいのは `_signal_map` の走査特性だけなので `__new__` で最小組立てする。
    """
    from valisync.gui.viewmodels import graph_panel_vm as mod

    session = _StubSession(base)
    vm = mod.GraphPanelVM.__new__(mod.GraphPanelVM)
    vm._session = session  # type: ignore[attr-defined]
    vm._file_offsets = file_offsets  # type: ignore[attr-defined]
    vm._signal_offsets = signal_offsets  # type: ignore[attr-defined]
    return vm, session


def test_offset_overlay_does_not_scan_the_whole_base_map() -> None:
    base = _CountingMap({f"g::s{i}": _sig(f"g::s{i}") for i in range(500)})
    vm, _session = _vm(base, {"g": 1.0}, {})

    result = vm._signal_map()  # type: ignore[attr-defined]
    assert result["g::s3"] is not None  # ルックアップは通る
    assert base.full_scans == 0  # base 全走査をしていない


def test_offset_overlay_applies_offset_only_to_looked_up_keys() -> None:
    """apply_offset は「実際に引かれたキー」の分しか呼ばれない (O(offset信号))."""
    base = _CountingMap({f"g::s{i}": _sig(f"g::s{i}") for i in range(500)})
    vm, session = _vm(base, {"g": 1.0}, {"g::s3": 0.5})

    sm = vm._signal_map()  # type: ignore[attr-defined]
    np.testing.assert_allclose(sm["g::s3"].timestamps, base["g::s3"].timestamps + 1.5)
    np.testing.assert_allclose(sm["g::s7"].timestamps, base["g::s7"].timestamps + 1.0)

    assert session.offset_calls == [("g::s3", 1.0, 0.5), ("g::s7", 1.0, 0.0)]
    assert base.full_scans == 0


def test_offset_overlay_leaves_unaffected_group_signals_identical() -> None:
    """合計ゼロのキーは base の Signal をそのまま返す (apply_offset を呼ばない)."""
    base = _CountingMap({"g::a": _sig("g::a"), "h::b": _sig("h::b")})
    vm, session = _vm(base, {"g": 1.0}, {})

    sm = vm._signal_map()  # type: ignore[attr-defined]
    assert sm["h::b"] is base["h::b"]  # 同一ラッパー
    assert session.offset_calls == []  # 触っていない

    assert sm["g::a"] is not base["g::a"]
    assert session.offset_calls == [("g::a", 1.0, 0.0)]


def test_offset_overlay_enumeration_delegates_to_base() -> None:
    """列挙は base に委譲する (遅延解決 base map の鋳造を誘発しないため)."""
    base = _CountingMap({"g::a": _sig("g::a"), "g::b": _sig("g::b")})
    vm, _session = _vm(base, {"g": 1.0}, {})

    sm = vm._signal_map()  # type: ignore[attr-defined]
    assert len(sm) == 2
    assert sorted(sm) == ["g::a", "g::b"]
    assert sorted(sm) == ["g::a", "g::b"]
    # 委譲なので列挙するたび base に届く。base をコピーした dict を返す旧実装では
    # 構築時の 1 回きり (以降は自前 dict) なので、この 2 が退行検出点になる。
    assert base.full_scans == 2


def test_offset_overlay_get_returns_none_for_unloaded_key() -> None:
    """`.get()` の欠損 → None を維持する (呼出側は全て `sig_map.get(key)` で
    アンロード済み信号を弾いており、KeyError が漏れると描画経路が落ちる)."""
    base = _CountingMap({"g::a": _sig("g::a")})
    vm, _session = _vm(base, {"g": 1.0}, {})

    sm = vm._signal_map()  # type: ignore[attr-defined]
    assert sm.get("g::missing") is None
    assert "g::missing" not in sm
    assert "g::a" in sm
    assert base.full_scans == 0  # 欠損判定も全走査しない


def test_offset_overlay_enumeration_methods_are_blocked() -> None:
    """`keys()`/`items()`/`values()`/`dict()` は TypeError で落ちる (M4).

    `Mapping` ABC の既定実装は全て `__getitem__` 経由なので、これらは物理チャンネル
    1 本につき apply_offset を 1 回呼び、全長 float64 タイムスタンプ配列を 1 本ずつ
    新規確保する (prod 264k 本)。docstring の禁止だけでは `dict(sig_map)` 1 行で
    再導入されるため、**構造的に使えない**ことを固定する。
    """
    base = _CountingMap({f"g::s{i}": _sig(f"g::s{i}") for i in range(5)})
    vm, session = _vm(base, {"g": 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    for call in (sm.keys, sm.items, sm.values):
        with pytest.raises(TypeError, match="列挙できない"):
            call()
    with pytest.raises(TypeError, match="列挙できない"):
        dict(sm)  # keys() 経由なので dict() も構造的に塞がる

    assert session.offset_calls == []  # 1 本も鋳造していない
    assert sm._cache == {}


def test_offset_overlay_membership_does_not_apply_offset() -> None:
    """`key in overlay` は Signal を 1 個も作らない (M4 — 最も鋭い刃).

    `Mapping` 既定の `__contains__` は `self[key]` を試すので、存在を尋ねるだけで
    apply_offset が走り全長タイムスタンプ配列が 1 本増える。真偽値は base への委譲
    でも同一 (オフセットはキー集合を変えない) なので、委譲でゼロコストにする。
    """
    base = _CountingMap({"g::a": _sig("g::a"), "g::b": _sig("g::b")})
    vm, session = _vm(base, {"g": 1.0}, {"g::b": 0.5})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    assert "g::a" in sm  # オフセット対象でも True
    assert "g::b" in sm
    assert "g::zz" not in sm

    assert session.offset_calls == [], "メンバシップ判定が offset Signal を作った"
    assert sm._cache == {}  # 鋳造そのものがゼロ
    assert base.full_scans == 0


def test_signal_map_fast_path_returns_base_object_when_no_offsets() -> None:
    base = _CountingMap({"g::a": _sig("g::a")})
    vm, _session = _vm(base, {}, {})

    assert vm._signal_map() is base  # type: ignore[attr-defined]
    assert base.full_scans == 0


# ─── 遅延解決 base map (_ResolvingMap) との合成 (Task 6) ────────────────────────


def _resolving_manager(tmp_path: Path) -> tuple[SignalGroupManager, str]:
    """実 mf4 の代表列 1 本だけを持つ manager (Mat[1]/Mat[2] が鋳造経路)。

    E-1 のテストダブル (常に Signal を返す `_mint_column` の上書き) は overlay の
    合成しか見ておらず、鋳造そのものが壊れても緑のままだった。T2 で実装が入ったので
    実 mf4 の鋳造へ差し替える。

    ``column_records`` を渡し忘れると表が空になり、正しい実装でも `_mint_column` が
    常に None を返す (overlay 側のテストが「解決できないだけ」で緑にならず全 RED)。
    """
    result = MdfLoader().load(write_mdf4_2d(tmp_path))
    sg = result.signal_group
    assert sg is not None
    mgr = SignalGroupManager()
    key = mgr.add(
        dataclasses.replace(
            sg, signals=tuple(s for s in sg.signals if s.name == "Mat[0]")
        ),
        column_records=result.column_records,
    )
    return mgr, key


def test_overlay_over_resolving_base_enumerates_physical_keys_only(
    tmp_path: Path,
) -> None:
    """`len()`/`iter()` は overlay 越しでも「物理キー」のままで鋳造しない。"""
    mgr, key = _resolving_manager(tmp_path)
    vm, _session = _vm(mgr.signal_map(), {key: 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    before = mgr.mint_count
    assert len(sm) == 1
    assert list(sm) == [f"{key}::Mat[0]"]
    assert mgr.mint_count == before  # 列挙は鋳造しない

    # 鋳造済みの列があっても列挙は物理キーのみ
    assert sm[f"{key}::Mat[2]"] is not None
    assert mgr.mint_count == before + 1
    assert len(sm) == 1
    assert list(sm) == [f"{key}::Mat[0]"]


def test_overlay_over_resolving_base_applies_offset_to_minted_column(
    tmp_path: Path,
) -> None:
    """overlay 越しのルックアップは列を解決し、その列にもオフセットを適用する。"""
    mgr, key = _resolving_manager(tmp_path)
    vm, session = _vm(mgr.signal_map(), {key: 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    col_key = f"{key}::Mat[2]"
    col = sm.get(col_key)
    assert col is not None  # 解決器へフォールスルーした
    np.testing.assert_allclose(col.timestamps, np.array([0.0, 0.1, 0.2, 0.3]) + 1.0)
    assert session.offset_calls == [(col_key, 1.0, 0.0)]


def test_overlay_over_resolving_base_returns_none_for_unresolvable_key(
    tmp_path: Path,
) -> None:
    """解決不能キーは overlay 越しでも None (KeyError を漏らさない)。"""
    mgr, key = _resolving_manager(tmp_path)
    vm, _session = _vm(mgr.signal_map(), {key: 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    assert sm.get("mf4_9::Nope") is None  # 未ロードグループ
    assert "mf4_9::Nope" not in sm
