"""ColumnRecord 表: 列の鋳造に要る (生名, gi, ci, ColumnSpec) をローダーが残す (E-3 T1).

鋳造器 _mint_column は列キー 1 本しか受け取らないが、列キーは LD-08 dedup 済みの
**表示名**由来 (metadata['physical_channel'] と同一キー空間) で、asammdf の select は
**生チャンネル名と (gi, ci)** を要求する。この 2 つのキー空間を橋渡しするレコードが
無いと鋳造そのものが書けない。

反転 (T6) 前なのでローダーはまだ列を展開している。よって「表から生成した列名」と
「実際にロードされた Signal 名」を突き合わせられる — この一致が T6 の受け入れ条件に
なり、反転後も同じ assert が生き残る。
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import (
    CAN,
    write_mdf4,
    write_mdf4_2d,
    write_mdf4_all_channels_bad,
    write_mdf4_flatten_fixture,
    write_mdf4_single_column_shapes,
)
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup
from valisync.core.session import Session


def _loaded(path: Path) -> tuple[SignalGroupManager, str, SignalGroup]:
    """実 mf4 をロードし、ローダーが出した表ごと manager へ登録する。

    ``confirm_expansion`` は既定 None なので**渡さない** — Task 8 が引数ごと退役させる
    ときに、このファイルが取りこぼされて ``TypeError`` で落ちるのを構造的に防ぐ。
    """
    result = MdfLoader().load(path)
    sg = result.signal_group
    assert sg is not None
    mgr = SignalGroupManager()
    key = mgr.add(sg, column_records=result.column_records)
    return mgr, key, sg


def _sig(name: str) -> Signal:
    ts = np.arange(3, dtype=np.float64)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.zeros(3),
        file_format="CSV",
        bus_type="",
        source_file="/x.csv",
    )


def _group(*names: str) -> SignalGroup:
    return SignalGroup(
        signals=tuple(_sig(n) for n in names),
        source_path=Path("/x.csv").resolve(),
        file_format="CSV",
        loaded_at=datetime.datetime.now(),
    )


def test_record_carries_raw_name_group_channel_and_spec(tmp_path: Path) -> None:
    """(1) ロード後に (生名, gi, ci, ColumnSpec) が引ける。"""
    mgr, key, sg = _loaded(write_mdf4_2d(tmp_path))
    records = mgr.column_records(key)
    # キーは物理チャンネル (列ではない) — Mat[0..2] は 1 レコードに畳まれる
    assert set(records) == {"Mat", "Clean"}

    mat = records["Mat"]
    assert mat.raw_base_name == "Mat"
    assert mat.spec.kind == "array"
    assert mat.spec.axis_len == 3
    clean = records["Clean"]
    assert clean.spec.kind == "leaf"
    assert clean.spec.dtype_kind == "f"

    # (gi, ci) は select の実引数。実ファイルで指し先を確認する
    # (int が 2 つ入っているだけでは何も保証しない)。
    handle = sg.handle
    assert handle is not None
    for name, record in records.items():
        channel = handle.mdf.groups[record.group_index].channels[record.channel_index]
        assert channel.name == record.raw_base_name, name

    # 表の構築は 1 レコードプローブ由来 — 値を展開してはならない (遅延契約)
    assert all(s._values_source.is_materialized is False for s in sg.signals)


def test_duplicate_raw_names_are_two_records_with_distinct_locations(
    tmp_path: Path,
) -> None:
    """(2) LD-08 の重複名 2 本が別レコードとして区別される。

    表を生名でキーすると 2 本が 1 レコードへ融合し、片方の構造/位置が黙って
    消える (どちらが勝つかは走査順まかせ)。
    """
    path = write_mdf4(
        tmp_path / "dup.mf4",
        [
            {
                "name": "sig",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            },
            {
                "name": "sig",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [3.0, 4.0],
            },
        ],
    )
    mgr, key, sg = _loaded(path)
    records = mgr.column_records(key)

    assert set(records) == {"sig[0]", "sig[1]"}
    assert {r.raw_base_name for r in records.values()} == {"sig"}  # 生名は共有
    locations = {(r.group_index, r.channel_index) for r in records.values()}
    assert len(locations) == 2, locations  # 指し先は別々

    handle = sg.handle
    assert handle is not None
    for record in records.values():
        channel = handle.mdf.groups[record.group_index].channels[record.channel_index]
        assert channel.name == "sig"

    # 列名の base は **表示名** (生名ではない) — 列キーは dedup 済み名から作る契約
    assert mgr.column_names_of(key, "sig[1]") == ("sig[1]",)


def test_column_names_of_scalar_is_the_display_name_itself(tmp_path: Path) -> None:
    """(3) スカラーは (display_name,) を返す。"""
    mgr, key, _sg = _loaded(write_mdf4_2d(tmp_path))
    assert mgr.column_names_of(key, "Clean") == ("Clean",)


def test_column_names_of_array_and_struct(tmp_path: Path) -> None:
    mgr, key, _sg = _loaded(write_mdf4_flatten_fixture(tmp_path))
    assert mgr.column_names_of(key, "Mat") == ("Mat[0]", "Mat[1]", "Mat[2]")
    assert mgr.column_names_of(key, "Pos") == ("Pos.xa", "Pos.xb", "Pos.yc")
    assert mgr.column_names_of(key, "ACC.Speed") == ("ACC.Speed",)


def test_has_column_distinguishes_columns_from_container_channels(
    tmp_path: Path,
) -> None:
    """(3b) 列の**存在判定**だけを鋳造せずに答える (T5 の行フィルタ / T7 の衝突判定)。

    列名タプルを作らずに済むのが要点: 広幅チャンネルで `column_names_of` を呼ぶと
    1,000 本の f-string が出る。呼び出し側 (フィルタ 1 打鍵ごと・表示名 1 件ごと) は
    「あるか」しか要らない。
    """
    mgr, key, _sg = _loaded(write_mdf4_flatten_fixture(tmp_path))
    assert mgr.has_column(key, "ACC.Speed") is True  # スカラー = 物理チャンネル兼列
    assert mgr.has_column(key, "Mat[1]") is True  # 展開列
    assert mgr.has_column(key, "Pos.xb") is True  # 構造化フィールド
    assert mgr.has_column(key, "Mat") is False  # 容器 (配列の親) は列ではない
    assert mgr.has_column(key, "Pos") is False  # 容器 (構造体の親)
    assert mgr.has_column(key, "Mat[9]") is False  # 幅の範囲外
    assert mgr.has_column(key, "Nope") is False  # 未知の物理チャンネル
    assert mgr.has_column("mf4_9", "Mat[1]") is False  # 未ロードグループ

    # 非数値リーフは列キー空間に載らない (leaf_names は数値リーフのみを生む)
    mgr2, key2, _sg2 = _loaded(write_mdf4_single_column_shapes(tmp_path))
    assert mgr2.has_column(key2, "Q.x") is True
    assert mgr2.has_column(key2, "Q.tag") is False


def test_has_column_falls_back_to_observed_signals_without_records() -> None:
    """CSV/Derived は表を持たない — 観測した Signal 名がそのまま列。"""
    mgr = SignalGroupManager()
    key = mgr.add(_group("Spd", "Arr[0]"))
    assert mgr.has_column(key, "Spd") is True
    assert mgr.has_column(key, "Arr[0]") is True  # 形だけを根拠に畳まない
    assert mgr.has_column(key, "Arr") is False  # 実在しない親を捏造しない


def test_generated_column_names_match_eager_expansion(tmp_path: Path) -> None:
    """反転前にしかできない突合: 表から作った列名 == 実際に載っている Signal 名。

    順序も含めて一致すること (leaf_names は _flatten と同順・ローダーはその順で
    Signal を append する)。T6 はこの一致を保ったまま Signal 側だけを減らす。
    """
    for path in (
        write_mdf4_flatten_fixture(tmp_path),
        write_mdf4_single_column_shapes(tmp_path),
    ):
        mgr, key, sg = _loaded(path)
        expected: dict[str, list[str]] = {}
        for s in sg.signals:
            phys = str((s.metadata or {}).get("physical_channel") or s.name)
            expected.setdefault(phys, []).append(s.name)
        assert expected, path.name
        for phys, names in expected.items():
            assert mgr.column_names_of(key, phys) == tuple(names), (path.name, phys)


@pytest.mark.parametrize(
    "writer",
    [
        write_mdf4_2d,
        write_mdf4_flatten_fixture,
        write_mdf4_single_column_shapes,
        write_mdf4_all_channels_bad,
    ],
)
def test_total_column_count_equals_eager_signal_count(
    writer: Callable[[Path], Path], tmp_path: Path
) -> None:
    """(4) 数値列総数が eager 展開後の Signal 数と一致する。

    single_column_shapes は非数値リーフ (Q.tag) を、all_channels_bad は非数値
    チャンネルのみを含む — dtype-blind に数えると両方 RED になる (数えるのは
    **数値リーフのみ** = leaf_count であって _all_leaf_count ではない)。
    """
    mgr, key, sg = _loaded(writer(tmp_path))
    assert mgr.total_column_count(key) == len(sg.signals)


def test_group_without_records_falls_back_to_one_column_per_signal() -> None:
    """CSV/Derived は列構造を持たない = 1 信号 1 列 (表が無くても答えを返す)。"""
    mgr = SignalGroupManager()
    key = mgr.add(_group("Spd", "Arr[0]"))
    assert mgr.column_records(key) == {}
    # 名前の形だけを根拠に畳まない: CSV の Arr[0] は展開列ではなく 1 本のチャンネル
    assert mgr.column_names_of(key, "Arr[0]") == ("Arr[0]",)
    assert mgr.total_column_count(key) == 2


def test_records_follow_group_lifetime(tmp_path: Path) -> None:
    """表の寿命は add/remove のみ — namespaced 無効化に相乗りさせない。

    相乗りさせると 2 ファイル目のロードごとに表が消え、鋳造 (T2) が
    ファイル全体の再走査に落ちる (_resolved_by_key と同じ機序)。
    """
    mgr, key, _sg = _loaded(write_mdf4_2d(tmp_path))
    other = mgr.add(_group("Other"))  # 2 ファイル目ロード相当
    assert "Mat" in mgr.column_records(key)
    mgr.remove(other)  # 2 ファイル目 unload 相当
    assert "Mat" in mgr.column_records(key)

    mgr.remove(key)  # 自グループの unload で捨てる
    assert mgr.column_records(key) == {}
    with pytest.raises(KeyError):
        mgr.total_column_count(key)


def test_column_records_view_is_read_only(tmp_path: Path) -> None:
    mgr, key, _sg = _loaded(write_mdf4_2d(tmp_path))
    view = mgr.column_records(key)
    assert not hasattr(view, "__setitem__")
    assert mgr.column_records("mf4_9") == {}  # 未知 key は空 (KeyError にしない)


def test_session_exposes_column_names_and_total(tmp_path: Path) -> None:
    """GUI 側 (T4/T5) が触るのは Session の 2 本だけ。"""
    session = Session()
    key = session.load(write_mdf4_flatten_fixture(tmp_path)).key
    assert session.column_names_of(key, "Mat") == ("Mat[0]", "Mat[1]", "Mat[2]")
    assert session.total_column_count(key) == len(session.group_signals(key))
    # U2: n_channels の単位は列数のまま (T7 がこの一致を保つ)
    assert session.source_info(key).n_channels == session.total_column_count(key)
