"""列キーから Signal を鋳造する経路 (_mint_column) の契約。

T6 の反転後は **これが列 Signal の唯一の供給経路**である。「鋳造した列 == 実データ
のリーフ」を独立オラクル (asammdf の ``select`` + ``_flatten`` 直叩き) で固定する —
反転前はローダーが発行した列 Signal をその参照に使えたが、いまは存在しない。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
from asammdf import MDF
from asammdf import Signal as ASignal

from tests.mdf4_helpers import (
    write_mdf4_2d,
    write_mdf4_dup_2d,
    write_mdf4_single_column_shapes,
    write_mdf4_structured,
)
from valisync.core.loaders.column_names import ColumnRecord
from valisync.core.loaders.mdf_loader import MdfLoader, _flatten
from valisync.core.loaders.signal_group_manager import (
    KEY_SEPARATOR,
    SignalGroupManager,
)
from valisync.core.models import Signal, SignalGroup

#: (SignalGroup, ColumnRecord 表) — 鋳造の材料は **両方**が要る。表は manager 側に
#: 持たせる設計 (Task 1) なので、group だけを持ち回すと add() で表が落ちて
#: _mint_column が常に None を返す (正しい実装でも全テストが RED のまま)。
_Loaded = tuple[SignalGroup, Mapping[str, ColumnRecord]]


def _load(path: Path) -> _Loaded:
    """実 mf4 をロードし (group, 列表) を返す。"""
    result = MdfLoader().load(path)
    sg = result.signal_group
    assert sg is not None
    return sg, result.column_records


def _manager(loaded: _Loaded) -> tuple[SignalGroupManager, str]:
    sg, records = loaded
    mgr = SignalGroupManager()
    return mgr, mgr.add(sg, column_records=records)


def _ns(key: str, name: str) -> str:
    return f"{key}{KEY_SEPARATOR}{name}"


def _mint(mgr: SignalGroupManager, key: str, name: str) -> Signal:
    got = mgr._mint_column(key, _ns(key, name))
    assert got is not None, f"{name} が鋳造されなかった"
    return got


def _eager_columns(path: Path, display: str, raw_name: str) -> dict[str, np.ndarray]:
    """物理チャンネル 1 本の {列キー: 値} を asammdf 直叩きで作る独立オラクル。

    T6 の反転で「ローダーが発行した列 Signal」という参照は消えた。列キーは
    **表示名** (LD-08 dedup 済み) から、値は **生名** で読んだ samples から作る —
    その 2 空間の食い違い自体が鋳造の契約なので、オラクルも両方を明示的に受ける。
    """
    with MDF(str(path), time_from_zero=False) as mdf:
        asig = mdf.select(
            [raw_name],
            raw=False,
            ignore_value2text_conversions=True,
            copy_master=False,
        )[0]
        return {name: np.array(col) for name, col in _flatten(display, asig.samples)}


def test_minted_column_equals_the_real_column_data(tmp_path: Path) -> None:
    """鋳造列は実データのリーフと等価 (値・dtype)、metadata は親から継承する。

    metadata を親と突き合わせるのは、physical_channel/unit/source 系の継承と
    変換系キーの非継承を 1 本の参照で同時に固定するため (LD-07 の非継承は
    test_minted_column_does_not_inherit_conversion_metadata が別に強制する)。
    """
    path = write_mdf4_2d(tmp_path)
    loaded = _load(path)
    sg, _records = loaded
    mgr, key = _manager(loaded)
    eager = _eager_columns(path, "Mat", "Mat")
    assert set(eager) == {"Mat[0]", "Mat[1]", "Mat[2]"}  # 反 vacuous 前置
    parent = next(s for s in sg.signals if s.metadata["physical_channel"] == "Mat")

    for name in ("Mat[0]", "Mat[1]", "Mat[2]"):
        minted = _mint(mgr, key, name)
        assert minted.name == _ns(key, name)
        assert minted._values_source.is_materialized is False  # 構築は読まない
        np.testing.assert_array_equal(minted.values, eager[name])
        # native dtype 保持 (float64 へ upcast すると uint8 の 8 倍膨張が戻る)
        assert minted.values.dtype == np.uint8
        assert minted.values.dtype == eager[name].dtype
        assert minted.metadata == parent.metadata


def test_minted_column_shares_the_group_master_object(tmp_path: Path) -> None:
    """timestamps は親と同一オブジェクト。

    コピーすると source_info の id(s.timestamps) dedup (session.py) が静かに劣化し、
    時間範囲の算出が unique master ごと 1 回から列ごと 1 回へ戻る。
    """
    loaded = _load(write_mdf4_2d(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    parent = next(s for s in sg.signals if s.metadata["physical_channel"] == "Mat")

    minted = _mint(mgr, key, "Mat[1]")
    assert minted.timestamps is parent.timestamps
    # 鋳造列は自分自身がその列の正典 -- namespaced ラッパーのような委譲を持たない
    assert getattr(minted, "_sorted_view_delegate", None) is None


def test_container_keys_are_not_columns(tmp_path: Path) -> None:
    """2-D / 構造化の**親**キーは列ではない (None)。

    親を鋳造すると 2-D 全体の float64 キャッシュ (prod で 96 MB/本) を掴む Signal が
    「プロットできる顔」で出てくる。
    """
    mgr, key = _manager(_load(write_mdf4_2d(tmp_path)))
    assert mgr._mint_column(key, _ns(key, "Mat")) is None
    # スカラーは「物理チャンネル == 列」なので鋳造対象にならない (map が先に当たる)。
    # 拒否の担い手は 2 つに分かれている: 容器 (配列/構造体) は parse_leaf が、
    # 数値スカラーは `if not rest: continue` **だけ** が落とす。後者は表に
    # スカラーのレコードが**在ること**が前提なので、反転後もそうであることを
    # 同じテスト内で固定する (レコードが消えると `is None` は別の理由で通る)。
    assert "Clean" in mgr.column_records(key)
    assert mgr.column_records(key)["Clean"].spec.kind == "leaf"
    assert mgr.has_column(key, "Clean") is True
    assert mgr._mint_column(key, _ns(key, "Clean")) is None

    mgr2, key2 = _manager(_load(write_mdf4_structured(tmp_path)))
    assert mgr2._mint_column(key2, _ns(key2, "Pt")) is None


def test_record_key_display_names_never_reach_the_minting_path(tmp_path: Path) -> None:
    """実チャンネル ``A[0]`` が配列 ``A`` の列 0 と字面衝突する「誤データ」クラス。

    ``_mint_column`` 単体はこの衝突で **黙って別チャンネルの値** を返す (実測):
    表示名 ``A[0]`` はレコードにヒットするが ``rest`` が空なので ``continue`` し、
    次に短い ``A`` (2-D) がヒットして ``A[0]`` を**その列 0** として解決してしまう。
    例外は出ない — 出るのは違う単位・違う dtype・違う値である。

    production で起きないのは ``resolve()`` が ``_namespaced_map`` を先に見るから
    で、それが効くのは **レコードのキー集合 == 発行された Signal 名** (1:1) だから。
    つまりこのテストが本当に守っているのは 1:1 の方 — 表に「Signal を作らなかった
    チャンネル」が残った瞬間、その名前は誤データを返す入口に変わる。

    **T7 で防波堤を二重化した**: 1:1 は不変条件であって述語ではない (壊れても何も
    検出されない) ため、``_mint_column`` 自身がレコード名そのものを列と見なさず
    打ち切るようにした。下の assert はその第 2 の防波堤を pin する。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]],
                        dtype=np.uint8,
                    ),
                    timestamps=ts,
                    name="A",
                    unit="mm",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([7.0, 8.0, 9.0, 10.0]),
                    timestamps=ts,
                    name="A[0]",
                    unit="deg",
                )
            ]
        )
        path = tmp_path / "collide.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()

    loaded = _load(path)
    sg, records = loaded
    mgr, key = _manager(loaded)
    # 1:1 — これが崩れた瞬間に下の resolve が鋳造経路へ落ちる
    assert set(records) == {s.name for s in sg.signals} == {"A", "A[0]"}

    got = mgr.resolve(_ns(key, "A[0]"))
    assert got is not None
    assert got.metadata["physical_channel"] == "A[0]"  # 親 "A" ではない
    assert got.metadata["unit"] == "deg"  # 親は "mm"
    np.testing.assert_array_equal(got.values, [7.0, 8.0, 9.0, 10.0])
    assert mgr.mint_count == 0  # 鋳造経路を **一度も通らない**

    # 第 2 の防波堤 (T7): 鋳造器を直接呼んでも誤データを返さない。ここが親 "A" の
    # 列 0 (unit "mm" / uint8 / [0,10,20,30]) を返す実装は、1:1 が崩れた瞬間に
    # 例外なしで別チャンネルのデータを配る。`is None` でなければならず、
    # 「親を返してもよい」という緩い形にはしない。
    assert mgr._mint_column(key, _ns(key, "A[0]")) is None


def test_structured_field_columns_are_minted(tmp_path: Path) -> None:
    path = write_mdf4_structured(tmp_path)
    mgr, key = _manager(_load(path))
    eager = _eager_columns(path, "Pt", "Pt")
    assert set(eager) == {"Pt.x", "Pt.y"}  # 反 vacuous 前置
    for name in ("Pt.x", "Pt.y"):
        np.testing.assert_array_equal(_mint(mgr, key, name).values, eager[name])


def test_non_numeric_leaf_is_not_minted(tmp_path: Path) -> None:
    """非数値リーフで Signal を作らない (Q.tag は S2)。

    数値ゲートは parse_leaf/_consume が持つ -- 鋳造側で作れてしまうと eager が
    「非数値型のためスキップ」した列が裏口から復活する。
    """
    mgr, key = _manager(_load(write_mdf4_single_column_shapes(tmp_path)))
    assert mgr._mint_column(key, _ns(key, "Q.tag")) is None
    assert mgr._mint_column(key, _ns(key, "Q.x")) is not None


def test_dedup_display_names_mint_from_the_right_channel(tmp_path: Path) -> None:
    """LD-08 dedup + LD-14 展開の合成: 表示名 W[1] の列 [1] は **生名** W の列 [1]。

    dedup 済み表示名のまま parse_leaf へ引くと "W[1][1]" の先頭 "[1]" を W 自身の
    配列インデックスとして消費し、解決不能になるか **別チャンネルの列** を返す。
    値だけでどのチャンネルのどの列かが判る fixture で直接殺す。

    期待値は write_mdf4_dup_2d の定義から**手で書き下す** — 生名 W を 2 本が共有
    するため asammdf の名前引き (select(["W"])) では正しい相方を区別できず、
    `_flatten` 経由のオラクルはここでだけ使えない (T6 の反転でローダー側の参照も
    消えた)。
    """
    mgr, key = _manager(_load(write_mdf4_dup_2d(tmp_path)))
    expected = {
        "W[0][0]": [0, 2, 4, 6],
        "W[0][1]": [1, 3, 5, 7],
        "W[1][0]": [100, 102, 104, 106],
        "W[1][1]": [101, 103, 105, 107],
    }
    for name, values in expected.items():
        minted = _mint(mgr, key, name)
        assert minted.values.dtype == np.uint8, name
        np.testing.assert_array_equal(minted.values, values, err_msg=name)


def test_minted_column_inherits_the_dedup_flag(tmp_path: Path) -> None:
    """physical_channel と name_deduplicated を継承する。

    落とすと E-2 比較モードが「同名信号」を跨ファイルで誤ペアリングする
    (name_deduplicated は自動重ねからの除外根拠)。
    """
    mgr, key = _manager(_load(write_mdf4_dup_2d(tmp_path)))
    minted = _mint(mgr, key, "W[1][0]")
    assert minted.metadata["physical_channel"] == "W[1]"
    assert minted.metadata["name_deduplicated"] is True

    mgr2, key2 = _manager(_load(write_mdf4_2d(tmp_path)))
    plain = _mint(mgr2, key2, "Mat[0]")
    assert plain.metadata["physical_channel"] == "Mat"
    assert "name_deduplicated" not in plain.metadata


def test_minted_column_does_not_inherit_conversion_metadata(tmp_path: Path) -> None:
    """LD-07: 変換情報と値ラベルは配列成分へ継承しない。

    展開チャンネルは raw_conversion=None で読まれるため、自然な fixture では親が
    そもそも変換 metadata を持たず assert が vacuous になる。契約を直接確かめる
    ために親の metadata dict へ強制的に載せる (metadata は可変 dict)。
    """
    loaded = _load(write_mdf4_2d(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    parent = next(s for s in sg.signals if s.metadata["physical_channel"] == "Mat")
    parent.metadata["conversion_info"] = "<ChannelConversion linear>"
    parent.metadata["value_labels"] = {0.0: "OFF", 1.0: "ON"}

    minted = _mint(mgr, key, "Mat[2]")
    assert "conversion_info" not in minted.metadata
    assert "value_labels" not in minted.metadata
    assert minted.metadata["physical_channel"] == "Mat"  # 他は継承する
    assert minted.metadata is not parent.metadata  # dict を共有しない


def test_resolve_mints_a_column_missing_from_the_map(tmp_path: Path) -> None:
    """E-1 の「未配線ゆえ None」(test_resolver の旧 test_e1_mint_is_not_wired_yet) の反転。

    map に無い実在の列キーは鋳造され、同じキーは同じオブジェクトを返す。
    T6 反転前はローダーが全列を発行していたため、代表 1 本だけを残す `_only`
    ヘルパで「map に無い実在の列キー」を人工的に作っていた。反転後は production が
    そのまま同じ状況なので、細工なしで鋳造経路を踏む (擬似反転は不要になった)。
    """
    mgr, key = _manager(_load(write_mdf4_2d(tmp_path)))

    col_key = _ns(key, "Mat[2]")
    got = mgr.resolve(col_key)
    assert got is not None
    assert mgr.mint_count == 1
    assert mgr.resolved_keys(key) == frozenset({col_key})
    assert mgr.resolve(col_key) is got  # 副テーブル経由で同一オブジェクト
    assert mgr.mint_count == 1
    np.testing.assert_array_equal(got.values, np.array([2, 12, 22, 32], dtype=np.uint8))


def test_resolve_still_returns_none_for_unresolvable_keys(tmp_path: Path) -> None:
    mgr, key = _manager(_load(write_mdf4_2d(tmp_path)))
    # 反 vacuous 前置: 解決できる列が実在する状態で「これらは None」を見る
    # (グループを空にすると全部 None になり、この 3 本が理由なく緑になる)。
    assert mgr.resolve(_ns(key, "Mat[2]")) is not None
    assert mgr.mint_count == 1
    assert mgr.resolve(_ns(key, "Mat[7]")) is None  # 幅 3 の範囲外
    assert mgr.resolve(_ns(key, "Nope")) is None  # 未知の物理チャンネル
    # 親コンテナ: 反転後は物理チャンネル Signal として map に居るので resolve は
    # それを返す — **鋳造** はしない (列ではない)。列でないことは has_column が答える。
    assert mgr._mint_column(key, _ns(key, "Mat")) is None
    assert mgr.has_column(key, "Mat") is False
    assert mgr.mint_count == 1  # 上の 1 本以外は鋳造していない
