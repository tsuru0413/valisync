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

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.loaders.mdf_loader import MdfLoader
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


def _add_real(mgr: SignalGroupManager, tmp_path: Path) -> str:
    """実 mf4 (物理チャンネル Mat / Clean) を **表ごと** 登録する。

    T6 反転前の eager ローダーは全列を発行したので、代表列 1 本だけを残す細工で
    ``Mat[1]``/``Mat[2]`` を「map に無い実在の列キー」に仕立てていた。反転後は
    production がそのままその形なので細工は不要 (むしろ細工を残すと signals が
    空になり、鋳造が「親が居ないから None」で偽緑になる)。副テーブルの寿命は
    **実装の鋳造** で検証する — テストダブルで鋳造を偽装すると、寿命は緑のまま
    鋳造の中身が壊れていても気づけない。

    ``column_records`` を渡すのが要点: 表は manager 側にあり、渡さないと
    ``_mint_column`` の先頭で表が空になって**正しい実装でも常に None** を返す
    (寿命テストが「鋳造できないから空」で通ってしまう)。
    """
    result = MdfLoader().load(write_mdf4_2d(tmp_path))
    sg = result.signal_group
    assert sg is not None
    assert {s.name for s in sg.signals} == {"Mat", "Clean"}, "反転後の形 (setup 前提)"
    return mgr.add(sg, column_records=result.column_records)


def test_resolve_returns_existing_signal_without_minting() -> None:
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    got = mgr.resolve(f"{key}::Mat[0]")
    assert got is not None
    assert mgr.mint_count == 0  # 既存キーは鋳造しない


def test_resolve_returns_none_for_unloaded_group() -> None:
    mgr = SignalGroupManager()
    assert mgr.resolve("mf4_9::Nope") is None


def test_synthetic_group_without_records_never_mints() -> None:
    """ColumnRecord 表もハンドルも無いグループ (CSV / 合成) は列を鋳造しない。

    E-1 では「実装が常に None を返す」ことの pin だったが、鋳造が配線された今は
    「MDF の列文法を持たないグループには当てない」という契約になる。
    """
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    assert mgr.resolve(f"{key}::Mat[7]") is None
    assert mgr.mint_count == 0
    assert mgr.resolved_keys(key) == frozenset()


def test_minting_requires_a_handle_even_with_column_records(tmp_path: Path) -> None:
    """``handle is None`` ガード単独の pin (CSV/Derived は LD-14 の列文法を持たない)。

    M-6: 既存の pin (``test_synthetic_group_without_records_never_mints`` /
    ``test_signal_map_unresolvable_lookup_returns_none``) は **表も持たない** グループを
    使うので、ガードを消しても空の records ループが同じ ``None`` に落ち **全部緑のまま**
    だった = docstring が名指しする契約が実は無防備。表を持たせると、ガードだけが
    「ハンドル無しのグループから列を鋳造しない」唯一の防波堤になる。

    sabotage: ``if handle is None: return None`` を落とすと、``LazyMdfValues(None, ...)``
    を抱えた Signal が鋳造されて RED (値を読んだ瞬間に落ちる遅延爆弾)。
    """
    result = MdfLoader().load(write_mdf4_2d(tmp_path))
    sg = result.signal_group
    assert sg is not None
    handle = sg.handle
    assert handle is not None  # setup 前提: 実ロードはハンドルを持つ
    try:
        mgr = SignalGroupManager()
        # 反 vacuous: 同じ表・同じ signals でも **ハンドルがあれば** 鋳造できる
        with_handle = mgr.add(sg, column_records=result.column_records)
        assert mgr.resolve(f"{with_handle}::Mat[1]") is not None

        headless = SignalGroup(
            signals=sg.signals,
            source_path=sg.source_path,
            file_format=sg.file_format,
            loaded_at=sg.loaded_at,
        )
        key = mgr.add(headless, column_records=result.column_records)
        assert mgr.resolve(f"{key}::Mat[1]") is None
        assert mgr.resolved_keys(key) == frozenset()
    finally:
        handle.close()


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


def test_resolved_table_survives_unrelated_add_and_remove(tmp_path: Path) -> None:
    # Critical 1: 無関係なファイルの load/remove で副テーブルを捨ててはならない
    mgr = SignalGroupManager()
    k1 = _add_real(mgr, tmp_path)
    col_key = f"{k1}::Mat[2]"  # 既存 map に無い列キー -> 鋳造経路
    first = mgr.resolve(col_key)
    assert first is not None
    assert mgr.mint_count == 1
    _ = first.values  # 実際に読ませる (再鋳造されると読み直しになる)
    assert first._values_source.is_materialized is True

    k2 = mgr.add(_group("Other"))  # 2 ファイル目ロード相当
    again = mgr.resolve(col_key)
    assert again is first  # 同一オブジェクト
    assert again._values_source.is_materialized is True  # 読み直していない
    assert mgr.mint_count == 1  # 再鋳造していない

    mgr.remove(k2)  # 2 ファイル目 unload 相当
    assert mgr.resolve(col_key) is first
    assert mgr.mint_count == 1


def test_removing_own_group_drops_its_resolved_table(tmp_path: Path) -> None:
    mgr = SignalGroupManager()
    k1 = _add_real(mgr, tmp_path)
    col_key = f"{k1}::Mat[2]"
    mgr.resolve(col_key)
    assert mgr.resolved_keys(k1) == frozenset({col_key})
    mgr.remove(k1)
    assert mgr.resolve(col_key) is None
    assert mgr.resolved_keys(k1) == frozenset()


def test_remove_returns_minted_columns_for_teardown(tmp_path: Path) -> None:
    """列 Signal は SignalGroup.signals の外に居るため remove() が返さないと
    TeardownService の会計・解放から漏れる。"""
    mgr = SignalGroupManager()
    k1 = _add_real(mgr, tmp_path)
    minted = mgr.resolve(f"{k1}::Mat[2]")
    group, columns = mgr.remove(k1)
    assert {s.name for s in group.signals} == {"Mat", "Clean"}  # 行は物理チャンネル
    assert columns == (minted,)  # 鋳造列は signals の外 = ここでしか返せない


def test_resolved_keys_does_not_mint(tmp_path: Path) -> None:
    mgr = SignalGroupManager()
    k1 = _add_real(mgr, tmp_path)
    before = mgr.mint_count
    _ = mgr.resolved_keys(k1)
    assert mgr.mint_count == before


# ─── signal_map() の非対称 Mapping 契約 (Task 6) ────────────────────────────────


def test_signal_map_lookup_falls_through_to_resolver(tmp_path: Path) -> None:
    """`[]`/`get` は既存 map に無いキーを解決器へ落とす (約20箇所の呼出を無改造にする要)。"""
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    m = mgr.signal_map()

    assert m.get(f"{key}::Mat") is not None  # 物理キー (E-3: 2-D の親チャンネル)
    assert mgr.mint_count == 0  # 物理キーは解決器を通さない

    minted = m.get(f"{key}::Mat[2]")  # 既存 map に無い列キー
    assert minted is not None
    assert mgr.mint_count == 1  # 解決器を通った
    assert m[f"{key}::Mat[2]"] is minted  # `[]` も同じ経路・同一オブジェクト
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


def test_signal_map_contains_falls_through_but_not_for_physical_keys(
    tmp_path: Path,
) -> None:
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    m = mgr.signal_map()

    assert f"{key}::Mat" in m
    assert mgr.mint_count == 0  # 既存キーの `in` は鋳造しない
    assert f"{key}::Mat[2]" in m  # 列キーは解決器へ落ちる
    assert mgr.mint_count == 1
    assert "mf4_9::Nope" not in m  # 未ロードグループ


def test_signal_map_enumeration_does_not_mint(tmp_path: Path) -> None:
    # 列挙は物理のみ: dict(m) が 330k 列を鋳造したら 390 MB を再導入してしまう
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    m = mgr.signal_map()
    before = mgr.mint_count
    physical = [f"{key}::Mat", f"{key}::Clean"]
    assert list(m) == physical
    assert len(m) == 2
    assert set(m.keys()) == set(physical)
    assert set(dict(m)) == set(physical)
    assert mgr.mint_count == before


def test_signal_map_enumeration_excludes_already_minted_columns(
    tmp_path: Path,
) -> None:
    """鋳造済みの列も列挙には現れない (物理キーのみ)。

    列挙を「物理 + 鋳造済み」に広げると、プロット中の列が増えるほど列挙結果が
    実行履歴に依存して揺れる。契約は「物理のみ」で固定する。
    """
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    m = mgr.signal_map()
    assert m.get(f"{key}::Mat[2]") is not None  # 鋳造させる
    assert mgr.mint_count == 1
    assert list(m) == [f"{key}::Mat", f"{key}::Clean"]
    assert len(m) == 2


def test_signal_map_is_read_only() -> None:
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()
    assert isinstance(m, Mapping)
    assert not hasattr(m, "__setitem__")
    with pytest.raises(TypeError):
        m[f"{key}::Mat[0]"] = _sig("x")  # type: ignore[index]
