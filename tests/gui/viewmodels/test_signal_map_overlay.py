"""offset overlay が O(loaded) でなく O(offset信号) であることを固定する。

`GraphPanelVM._signal_map()` は offset が立っている間、base map 全件を走査して
dict を作り直していた (prod 264k エントリ)。列キーを遅延解決する base map
(E-1 Task 6) とは構造的に両立しないため、ルックアップ時 overlay へ置換した。
ここは「全走査していない」ことを直接固定する — 結果の正しさだけを見るテストは
旧実装でも通ってしまい、退行を捕捉できない。
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator, Mapping
from pathlib import Path

import numpy as np

from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup


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


def test_signal_map_fast_path_returns_base_object_when_no_offsets() -> None:
    base = _CountingMap({"g::a": _sig("g::a")})
    vm, _session = _vm(base, {}, {})

    assert vm._signal_map() is base  # type: ignore[attr-defined]
    assert base.full_scans == 0


# ─── 遅延解決 base map (_ResolvingMap) との合成 (Task 6) ────────────────────────


class _MintingManager(SignalGroupManager):
    """テスト専用: E-3 でローダーが per-channel Signal を出す状態を先取りする。

    E-1 本体の `_mint_column` は常に None を返すため、overlay 越しに鋳造経路が
    通っていることは鋳造可能なサブクラスでしか観測できない。
    """

    def _mint_column(self, group_key: str, key: str) -> Signal:
        return _sig(key)


def _manager_with(*names: str) -> tuple[_MintingManager, str]:
    mgr = _MintingManager()
    key = mgr.add(
        SignalGroup(
            signals=tuple(_sig(n) for n in names),
            source_path=Path("/x.mf4").resolve(),
            file_format="MDF4",
            loaded_at=datetime.datetime.now(),
        )
    )
    return mgr, key


def test_overlay_over_resolving_base_enumerates_physical_keys_only() -> None:
    """`len()`/`iter()` は overlay 越しでも「物理キー」のままで鋳造しない。

    overlay は列挙を base へ委譲する。base が遅延解決 Mapping になった今、その委譲が
    「全論理キーの列挙」に化けると 330k 列を鋳造して ~390 MB を再導入する。
    """
    mgr, key = _manager_with("Mat[0]")
    vm, _session = _vm(mgr.signal_map(), {key: 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    before = mgr.mint_count
    assert len(sm) == 1
    assert list(sm) == [f"{key}::Mat[0]"]
    assert mgr.mint_count == before  # 列挙は鋳造しない

    # 鋳造済みの列があっても列挙は物理キーのみ
    assert sm[f"{key}::Mat[7]"] is not None
    assert mgr.mint_count == before + 1
    assert len(sm) == 1
    assert list(sm) == [f"{key}::Mat[0]"]


def test_overlay_over_resolving_base_applies_offset_to_minted_column() -> None:
    """overlay 越しのルックアップは列を解決し、その列にもオフセットを適用する。"""
    mgr, key = _manager_with("Mat[0]")
    vm, session = _vm(mgr.signal_map(), {key: 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    col_key = f"{key}::Mat[7]"
    col = sm.get(col_key)
    assert col is not None  # 解決器へフォールスルーした
    np.testing.assert_allclose(col.timestamps, np.arange(3, dtype=np.float64) + 1.0)
    assert session.offset_calls == [(col_key, 1.0, 0.0)]


def test_overlay_over_resolving_base_returns_none_for_unresolvable_key() -> None:
    """解決不能キーは overlay 越しでも None (KeyError を漏らさない)。"""
    mgr, key = _manager_with("Mat[0]")
    vm, _session = _vm(mgr.signal_map(), {key: 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    assert sm.get("mf4_9::Nope") is None  # 未ロードグループ
    assert "mf4_9::Nope" not in sm
