"""列キーから Signal を鋳造する経路 (_mint_column) の契約。

T6 の反転後は **これが列 Signal の唯一の供給経路**になる。eager ローダーがまだ
全列を発行している今のうちに「鋳造した列 == eager が発行した列」を固定する
(反転後は独立オラクルが失われる)。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from tests.mdf4_helpers import (
    write_mdf4_2d,
    write_mdf4_dup_2d,
    write_mdf4_single_column_shapes,
    write_mdf4_structured,
)
from valisync.core.loaders.column_names import ColumnRecord
from valisync.core.loaders.mdf_loader import MdfLoader
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
    """実 mf4 をロードし (group, 列表) を返す。

    ``confirm_expansion`` は既定 None なので**渡さない** — Task 8 が引数ごと退役
    させるときに、このファイルが取りこぼされて ``TypeError`` で落ちるのを防ぐ。
    """
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


def _only(loaded: _Loaded, keep: str) -> _Loaded:
    """物理チャンネルの代表列 1 本だけを残した (group, 列表) (T6 反転後の形の近似)。

    反転前の eager ローダーは全列を発行するので、そのまま add すると列キーが既存の
    namespaced map に当たり resolve() が鋳造経路へ落ちない。代表を 1 本だけ残すと
    残りの列キーが「map に無い実在の列キー」になり、resolve() 経由の鋳造
    (mint_count・副テーブルの寿命) を **実装のまま** 踏める。代表列は物理チャンネルの
    metadata (master・physical_channel) を運ぶ。列表は**物理チャンネル単位**なので
    signals を絞っても `Mat` のレコードはそのまま残る (絞る対象は signals だけ)。
    """
    sg, records = loaded
    return (
        dataclasses.replace(sg, signals=tuple(s for s in sg.signals if s.name == keep)),
        records,
    )


def test_minted_column_equals_the_eager_column(tmp_path: Path) -> None:
    """鋳造列は eager ローダーの列と等価 (値・dtype・metadata)。

    metadata を丸ごと突き合わせるのは、physical_channel/unit/source 系の継承と
    変換系キーの非継承を 1 本の独立参照で同時に固定するため。
    """
    loaded = _load(write_mdf4_2d(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    eager = {s.name: s for s in sg.signals}
    assert {"Mat[0]", "Mat[1]", "Mat[2]", "Clean"} <= set(eager)

    for name in ("Mat[0]", "Mat[1]", "Mat[2]"):
        minted = _mint(mgr, key, name)
        assert minted.name == _ns(key, name)
        assert minted._values_source.is_materialized is False  # 構築は読まない
        np.testing.assert_array_equal(minted.values, eager[name].values)
        # native dtype 保持 (float64 へ upcast すると uint8 の 8 倍膨張が戻る)
        assert minted.values.dtype == np.uint8
        assert minted.values.dtype == eager[name].values.dtype
        assert minted.metadata == eager[name].metadata


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
    # スカラーは「物理チャンネル == 列」なので鋳造対象にならない (map が先に当たる)
    assert mgr._mint_column(key, _ns(key, "Clean")) is None

    mgr2, key2 = _manager(_load(write_mdf4_structured(tmp_path)))
    assert mgr2._mint_column(key2, _ns(key2, "Pt")) is None


def test_structured_field_columns_are_minted(tmp_path: Path) -> None:
    loaded = _load(write_mdf4_structured(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    eager = {s.name: s for s in sg.signals}
    for name in ("Pt.x", "Pt.y"):
        np.testing.assert_array_equal(_mint(mgr, key, name).values, eager[name].values)


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
    """
    loaded = _load(write_mdf4_dup_2d(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    eager = {s.name: s for s in sg.signals}
    assert set(eager) == {"W[0][0]", "W[0][1]", "W[1][0]", "W[1][1]"}

    for name in eager:
        np.testing.assert_array_equal(_mint(mgr, key, name).values, eager[name].values)
    np.testing.assert_array_equal(
        _mint(mgr, key, "W[1][1]").values,
        np.array([101, 103, 105, 107], dtype=np.uint8),
    )


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
    """
    mgr, key = _manager(_only(_load(write_mdf4_2d(tmp_path)), "Mat[0]"))

    col_key = _ns(key, "Mat[2]")
    got = mgr.resolve(col_key)
    assert got is not None
    assert mgr.mint_count == 1
    assert mgr.resolved_keys(key) == frozenset({col_key})
    assert mgr.resolve(col_key) is got  # 副テーブル経由で同一オブジェクト
    assert mgr.mint_count == 1
    np.testing.assert_array_equal(got.values, np.array([2, 12, 22, 32], dtype=np.uint8))


def test_resolve_still_returns_none_for_unresolvable_keys(tmp_path: Path) -> None:
    mgr, key = _manager(_only(_load(write_mdf4_2d(tmp_path)), "Mat[0]"))
    assert mgr.resolve(_ns(key, "Mat[7]")) is None  # 幅 3 の範囲外
    assert mgr.resolve(_ns(key, "Nope")) is None  # 未知の物理チャンネル
    assert mgr.resolve(_ns(key, "Mat")) is None  # 親コンテナ
    assert mgr.mint_count == 0
