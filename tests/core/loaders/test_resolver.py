"""列キー解決器と per-group 副テーブルの寿命 (Critical 1 の回帰ガード)。

無関係なファイルの load/remove で鋳造済み列 Signal が捨てられると、次の描画で
フルチャンネル再読み (実測 0.73-1.18 s/列) が走る純粋な回帰になる。
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pytest

from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup


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


def _group(*names: str) -> SignalGroup:
    return SignalGroup(
        signals=tuple(_sig(n) for n in names),
        source_path=Path("/x.mf4").resolve(),
        file_format="MDF4",
        loaded_at=datetime.datetime.now(),
    )


class _MintingManager(SignalGroupManager):
    """テスト専用: E-3 でローダーが per-channel Signal を出す状態を先取りする。

    E-1 の本体 ``_mint_column`` は ColumnSpec 未配線ゆえ常に None を返す (ローダーが
    まだ列を展開しているため、実キーは全て既存 map で解決できる)。しかし守るべき規則
    (Critical 1) は「**鋳造済み** Signal が ``_invalidate_namespaced()`` を生き延びる」
    ことなので、鋳造経路が無い実装のままでは寿命そのものを実証できない。ここで最小の
    鋳造だけを与え、副テーブルの寿命を単独で固定する。
    """

    def _mint_column(self, group_key: str, key: str) -> Signal:
        return _sig(key)


def test_resolve_returns_existing_signal_without_minting() -> None:
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    got = mgr.resolve(f"{key}::Mat[0]")
    assert got is not None
    assert mgr.mint_count == 0  # 既存キーは鋳造しない


def test_resolve_returns_none_for_unloaded_group() -> None:
    mgr = SignalGroupManager()
    assert mgr.resolve("mf4_9::Nope") is None


def test_e1_mint_is_not_wired_yet() -> None:
    """E-1 では ColumnSpec 未配線 — 未知の列キーは鋳造されず None (挙動不変)。"""
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    assert mgr.resolve(f"{key}::Mat[7]") is None
    assert mgr.mint_count == 0
    assert mgr.resolved_keys(key) == frozenset()


def test_namespaced_wrapper_is_rebuilt_by_unrelated_add() -> None:
    """副テーブルを namespaced 寿命に相乗りさせてはならない理由 (計測済み回帰の機序)。

    namespaced ラッパーは add()/remove() ごとに作り直される。列 Signal を同じ寿命に
    載せると、2 ファイル目のロードのたびに全プロット列が新オブジェクト (空キャッシュ)
    となり、次の render で全列がフル再読みになる。
    """
    mgr = SignalGroupManager()
    k1 = mgr.add(_group("Mat[0]"))
    first = mgr.resolve(f"{k1}::Mat[0]")
    mgr.add(_group("Other"))
    assert mgr.resolve(f"{k1}::Mat[0]") is not first  # ラッパーは作り直される


def test_resolved_table_survives_unrelated_add_and_remove() -> None:
    # Critical 1: 無関係なファイルの load/remove で副テーブルを捨ててはならない
    mgr = _MintingManager()
    k1 = mgr.add(_group("Mat[0]"))
    col_key = f"{k1}::Mat[7]"  # 既存 map に無い列キー -> 鋳造経路
    first = mgr.resolve(col_key)
    assert first is not None
    assert mgr.mint_count == 1
    k2 = mgr.add(_group("Other"))  # 2 ファイル目ロード相当
    assert mgr.resolve(col_key) is first  # 同一オブジェクト
    assert mgr.mint_count == 1  # 再鋳造していない
    mgr.remove(k2)  # 2 ファイル目 unload 相当
    assert mgr.resolve(col_key) is first
    assert mgr.mint_count == 1


def test_removing_own_group_drops_its_resolved_table() -> None:
    mgr = _MintingManager()
    k1 = mgr.add(_group("Mat[0]"))
    col_key = f"{k1}::Mat[7]"
    mgr.resolve(col_key)
    assert mgr.resolved_keys(k1) == frozenset({col_key})
    mgr.remove(k1)
    assert mgr.resolve(col_key) is None
    assert mgr.resolved_keys(k1) == frozenset()


def test_remove_returns_minted_columns_for_teardown() -> None:
    """列 Signal は SignalGroup.signals の外に居るため remove() が返さないと
    TeardownService の会計・解放から漏れる。"""
    mgr = _MintingManager()
    k1 = mgr.add(_group("Mat[0]"))
    minted = mgr.resolve(f"{k1}::Mat[7]")
    group, columns = mgr.remove(k1)
    assert group.signals[0].name == "Mat[0]"
    assert columns == (minted,)


def test_resolved_keys_does_not_mint() -> None:
    mgr = _MintingManager()
    k1 = mgr.add(_group("Mat[0]"))
    before = mgr.mint_count
    _ = mgr.resolved_keys(k1)
    assert mgr.mint_count == before


# ─── signal_map() の非対称 Mapping 契約 (Task 6) ────────────────────────────────


def test_signal_map_lookup_falls_through_to_resolver() -> None:
    """`[]`/`get` は既存 map に無いキーを解決器へ落とす (約20箇所の呼出を無改造にする要)。

    E-1 本体の `_mint_column` は常に None を返すため、フォールスルーが**実際に起きている**
    ことは鋳造可能な `_MintingManager` でしか観測できない。素の Manager で書くと
    「MappingProxy が None を返しただけ」でも通ってしまい、退行を捕捉できない。
    """
    mgr = _MintingManager()
    key = mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()

    assert m.get(f"{key}::Mat[0]") is not None  # 物理キー
    assert mgr.mint_count == 0  # 物理キーは解決器を通さない

    minted = m.get(f"{key}::Mat[7]")  # 既存 map に無い列キー
    assert minted is not None
    assert mgr.mint_count == 1  # 解決器を通った
    assert m[f"{key}::Mat[7]"] is minted  # `[]` も同じ経路・同一オブジェクト
    assert mgr.mint_count == 1


def test_signal_map_unresolvable_lookup_returns_none() -> None:
    """解決不能キーは `get` が None (例外にしない)・`[]` は KeyError。

    呼出側は一様に `sig_map.get(key)` で「アンロード済み/未知」を弾いており、
    ここが KeyError を漏らすと描画経路が落ちる。
    """
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()

    assert m.get(f"{key}::Nope") is None  # 解決不能は None
    assert m.get("mf4_9::Nope") is None  # 未ロードグループも None
    with pytest.raises(KeyError):
        m[f"{key}::Nope"]


def test_signal_map_contains_falls_through_but_not_for_physical_keys() -> None:
    mgr = _MintingManager()
    key = mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()

    assert f"{key}::Mat[0]" in m
    assert mgr.mint_count == 0  # 既存キーの `in` は鋳造しない
    assert f"{key}::Mat[7]" in m  # 列キーは解決器へ落ちる
    assert mgr.mint_count == 1
    assert "mf4_9::Nope" not in m  # 未ロードグループ


def test_signal_map_enumeration_does_not_mint() -> None:
    # 列挙は物理のみ: dict(m) が 330k 列を鋳造したら 390 MB を再導入してしまう
    mgr = _MintingManager()
    key = mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()
    before = mgr.mint_count
    assert list(m) == [f"{key}::Mat[0]"]
    assert len(m) == 1
    assert set(m.keys()) == {f"{key}::Mat[0]"}
    assert set(dict(m)) == {f"{key}::Mat[0]"}
    assert mgr.mint_count == before


def test_signal_map_enumeration_excludes_already_minted_columns() -> None:
    """鋳造済みの列も列挙には現れない (物理キーのみ)。

    列挙を「物理 + 鋳造済み」に広げると、プロット中の列が増えるほど列挙結果が
    実行履歴に依存して揺れる。契約は「物理のみ」で固定する。
    """
    mgr = _MintingManager()
    key = mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()
    assert m.get(f"{key}::Mat[7]") is not None  # 鋳造させる
    assert mgr.mint_count == 1
    assert list(m) == [f"{key}::Mat[0]"]
    assert len(m) == 1


def test_signal_map_is_read_only() -> None:
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()
    assert isinstance(m, Mapping)
    assert not hasattr(m, "__setitem__")
    with pytest.raises(TypeError):
        m[f"{key}::Mat[0]"] = _sig("x")  # type: ignore[index]
