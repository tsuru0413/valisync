# ruff: noqa: RUF002
"""列 Signal は自分がどの物理チャンネル由来かを metadata で持つ。

ブラウザが「1 行＝1 物理チャンネル」を作るのに文字列解析を使えないため
(ドットはチャンネル名にもフィールド区切りにも現れる)、グループ化キーは
ローダー由来の真の同一性でなければならない。
"""

from __future__ import annotations

from pathlib import Path

from tests.mdf4_helpers import CAN, write_mdf4, write_mdf4_2d
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.session import Session


def test_expanded_columns_carry_physical_channel_name(tmp_path: Path) -> None:
    # E-3: 行は物理チャンネル (Mat / Clean)。列 Mat[0..2] は鋳造で得る。
    # 鋳造列も physical_channel を継承する (ブラウザのグループ化キー)。
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    cols = [session.resolve_signal(f"{key}::Mat[{i}]") for i in range(3)]
    assert all(c is not None for c in cols)
    assert {c.metadata["physical_channel"] for c in cols} == {"Mat"}
    parent = session.resolve_signal(f"{key}::Mat")
    assert parent is not None and parent.metadata["physical_channel"] == "Mat"
    clean = session.resolve_signal(f"{key}::Clean")
    assert clean is not None and clean.metadata["physical_channel"] == "Clean"


def test_scalar_channel_carries_its_own_name(tmp_path: Path) -> None:
    path = write_mdf4(
        tmp_path / "scalar.mf4",
        [
            {
                "name": "Spd",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            }
        ],
    )
    sg = MdfLoader().load(path, confirm_expansion=None).signal_group
    assert sg is not None
    sig = next(s for s in sg.signals if s.name == "Spd")
    assert sig.metadata["physical_channel"] == "Spd"


def test_duplicate_raw_names_are_two_distinct_physical_channels(tmp_path: Path) -> None:
    """LD-08: 同名チャンネル 2 本は別の物理チャンネル。生 base_name を刻むと
    両方 'sig' になり Task 2 が 1 行へ融合して死にキーを作る (I1)。"""
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
    sg = MdfLoader().load(path, confirm_expansion=None).signal_group
    assert sg is not None
    assert {s.metadata["physical_channel"] for s in sg.signals} == {"sig[0]", "sig[1]"}
