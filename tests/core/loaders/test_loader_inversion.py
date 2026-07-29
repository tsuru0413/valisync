# ruff: noqa: RUF003
"""E-3 反転: ローダーは物理チャンネル 1 本につき Signal を 1 個だけ発行する。

判定軸は 2 つ (spec の E-3 行):
  - **オブジェクト数**: 展開列は Signal にならない (prod 264,004 -> 4,324)。列は
    Session の解決器が ColumnRecord から要求時に鋳造する。
  - **診断**: 列ごとに増幅されていた warning を物理チャンネル 1 件へ集約し、
    1-D チャンネルの文言/件数/signal_name は byte-identical のまま。

demo_data 非依存 (CI 実行) — fixture は tests.mdf4_helpers の実 asammdf 往復。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tests.mdf4_helpers import (
    write_mdf4,
    write_mdf4_2d,
    write_mdf4_all_channels_bad,
    write_mdf4_non_monotonic,
    write_mdf4_non_monotonic_2d,
    write_mdf4_single_column_shapes,
    write_mdf4_structured,
    write_mdf4_value2text,
    write_mdf4_wide_2d,
)
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.session import Session


def _loaded(path: Path) -> tuple[Session, str, tuple]:
    """Session 経由でロードし (session, group_key, diagnostics) を返す。

    反転後は「列を見る」唯一の入口が鋳造つきの Session (resolve_signal) になる —
    SignalGroup.signals には物理チャンネルしか居ない。
    """
    session = Session()
    outcome = session.load(path)
    return session, outcome.key, outcome.diagnostics


def _orig_names(session: Session, key: str) -> list[str]:
    """グループの Signal 名を名前空間接頭辞なしで出現順に返す。"""
    return [s.name.split("::", 1)[1] for s in session.group_signals(key)]


def test_array_channel_is_one_signal_and_columns_are_minted(tmp_path: Path) -> None:
    """2D (Nx3) は Signal 1 個 (Mat)。列 Mat[0..2] は鋳造で同じ値を返す。"""
    session, key, _diags = _loaded(write_mdf4_2d(tmp_path))
    assert _orig_names(session, key) == ["Mat", "Clean"]
    parent = session.resolve_signal(f"{key}::Mat")
    assert parent is not None and parent.metadata["physical_channel"] == "Mat"

    m0 = session.resolve_signal(f"{key}::Mat[0]")
    m2 = session.resolve_signal(f"{key}::Mat[2]")
    assert m0 is not None and m2 is not None
    np.testing.assert_array_equal(m0.values, [0, 10, 20, 30])
    np.testing.assert_array_equal(m2.values, [2, 12, 22, 32])
    assert m0.values.dtype == np.uint8  # native dtype (FU-20) は鋳造経路でも保持
    assert np.shares_memory(m0.timestamps, m2.timestamps)  # 共有 master


def test_signal_count_is_physical_channels_not_columns(tmp_path: Path) -> None:
    """反転の主判定軸 (オブジェクト数): 1000 列の配列でも Signal は 2 個。

    prod の 264,004 -> 4,324 の CI 実行可能なプロキシ。母数 (列数) は U2 どおり
    列のまま残るので、両方を同時に見て「列が消えたから 2 個」ではないことを示す。
    """
    session, key, _d = _loaded(write_mdf4_wide_2d(tmp_path, cols=1000))
    assert len(session.group_signals(key)) == 2  # Wide + Clean
    assert session.total_column_count(key) == 1001  # 1000 列 + Clean
    assert session.resolve_signal(f"{key}::Wide[999]") is not None


def test_structured_channel_survives_leaf_level_numeric_gate(tmp_path: Path) -> None:
    """S2: 構造化の親 probe は dtype.kind == 'V' — 親でゲートすると全滅する。

    列単位ゲートをそのまま親に当てると「非数値型のためスキップ」で全構造化
    チャンネルが消える (この fixture では Pt が丸ごと消滅する)。
    """
    session, key, diags = _loaded(write_mdf4_structured(tmp_path))
    assert _orig_names(session, key) == ["Pt"]
    assert not any("非数値型" in d.message for d in diags)
    x = session.resolve_signal(f"{key}::Pt.x")
    y = session.resolve_signal(f"{key}::Pt.y")
    assert x is not None and y is not None
    np.testing.assert_array_equal(x.values, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(y.values, [10.0, 20.0, 30.0])


def test_expansion_info_counts_all_leaves_not_only_numeric_ones(
    tmp_path: Path,
) -> None:
    """混在構造 Q (x: f8 / tag: S2) の info は「2 本に展開」のまま (dtype-blind)。

    件数を column_names.leaf_count (数値のみ) へ替えると「1 本に展開」に変わる —
    _all_leaf_count を残す理由そのもの。列キー空間には数値リーフだけが載る。
    """
    session, key, diags = _loaded(write_mdf4_single_column_shapes(tmp_path))
    q_infos = [d for d in diags if d.level == "info" and d.signal_name == "Q"]
    assert [d.message for d in q_infos] == ["信号 'Q': 構造化チャンネルを 2 本に展開"]
    assert session.column_names_of(key, "Q") == ("Q.x",)
    assert session.resolve_signal(f"{key}::Q.x") is not None
    assert session.resolve_signal(f"{key}::Q.tag") is None  # 非数値リーフは列でない
    # 意図的 supersede (ここで固定する): 混在構造の非数値リーフ (Q.tag) は列単位の
    # warning を出さない — 列を作らないので「スキップ」を報告する主体が無い。反転前は
    # リーフ単位ループが「信号 'Q.tag': 非数値型のためスキップ（dtype |S2）」を 1 件
    # 出していた。1-D 非数値チャンネルの警告は不変
    # (test_non_numeric_channel_is_skipped_with_the_same_warning が別途固定)。
    assert not [d for d in diags if "非数値型" in d.message]


def test_non_numeric_channel_is_skipped_with_the_same_warning(tmp_path: Path) -> None:
    """1-D 非数値は今日どおり Signal ゼロ + 警告 1 件 (文言も据え置き)。"""
    result = MdfLoader().load(write_mdf4_all_channels_bad(tmp_path))
    assert result.signal_group is not None
    assert result.signal_group.signals == ()
    warns = [
        d
        for d in result.diagnostics
        if d.level == "warning" and "非数値型" in d.message
    ]
    assert len(warns) == 1
    assert warns[0].message.startswith(
        "信号 'raw_bytes': 非数値型のためスキップ（dtype "
    )


def test_one_dimensional_diagnostics_stay_byte_identical(tmp_path: Path) -> None:
    """保存契約: 1-D チャンネルの非単調警告は文言・件数・signal_name とも不変。"""
    result = MdfLoader().load(write_mdf4_non_monotonic(tmp_path))
    warns = [d for d in result.diagnostics if d.signal_name == "messy"]
    assert len(warns) == 1
    assert warns[0].level == "warning"
    assert warns[0].message == (
        "信号 'messy': 非単調 1 箇所・重複タイムスタンプ 1 点"
        "（表示/演算は整列ビューで補正）"
    )
    assert not [d for d in result.diagnostics if d.signal_name == "clean"]


def test_array_channel_emits_one_warning_not_one_per_column(tmp_path: Path) -> None:
    """診断 fan-out の集約: 3 列の配列でも非単調警告は物理チャンネル 1 件。"""
    session, key, diags = _loaded(write_mdf4_non_monotonic_2d(tmp_path))
    # 反 vacuous 前置: 列は 3 本実在する (列が消えたから 1 件、ではない)
    assert session.column_names_of(key, "Mat") == ("Mat[0]", "Mat[1]", "Mat[2]")

    mat_warns = [d for d in diags if d.level == "warning" and d.signal_name == "Mat"]
    assert len(mat_warns) == 1
    assert mat_warns[0].message == (
        "信号 'Mat': 非単調 1 箇所・重複タイムスタンプ 1 点"
        "（表示/演算は整列ビューで補正）"
    )
    assert not [d for d in diags if d.signal_name in ("Mat[0]", "Mat[1]", "Mat[2]")]
    # 同じ時刻軸の 1-D チャンネルは byte-identical のまま 1 件
    clean_warns = [d for d in diags if d.signal_name == "Clean"]
    assert len(clean_warns) == 1


def test_column_records_are_one_to_one_with_emitted_signals(tmp_path: Path) -> None:
    """表と SignalGroup.signals の 1:1。skip したチャンネルは表にも載らない。

    ブラウザ/エクスポートの母数はこの表なので、Signal を作らなかったチャンネルが
    表に残ると「見えるのに永久に描かれない行」が復活する (C1 と同じ壊れ方)。
    """
    session, key, _d = _loaded(write_mdf4_single_column_shapes(tmp_path))
    assert set(session._groups.column_records(key)) == {"Mono", "P", "Q", "Clean"}
    assert set(session._groups.column_records(key)) == set(_orig_names(session, key))
    # 集合等価だけでは**同名 Signal の重複発行**に盲目 (dedup 名が実チャンネル名と
    # 衝突する配置で到達しうる)。1:1 は今や「record キーの表示名が _mint_column へ
    # 降りない」ことの唯一の防波堤なので、多重集合の強さで押さえる。
    assert len(session.group_signals(key)) == len(session._groups.column_records(key))

    bad_session = Session()
    bad_key = bad_session.load(write_mdf4_all_channels_bad(tmp_path)).key
    assert bad_session._groups.column_records(bad_key) == {}
    assert bad_session.total_column_count(bad_key) == 0


def test_duplicate_names_stay_two_physical_signals_with_their_own_values(
    tmp_path: Path,
) -> None:
    """LD-08: 同名 2 本は sig[0]/sig[1] の 2 Signal。値は (gi, ci) ごとに正しい。"""
    session, key, _d = _loaded(
        write_mdf4(
            tmp_path / "dup.mf4",
            [
                {"name": "sig", "timestamps": [0.0, 1.0], "values": [1.0, 2.0]},
                {"name": "sig", "timestamps": [0.0, 1.0], "values": [3.0, 4.0]},
            ],
        )
    )
    assert _orig_names(session, key) == ["sig[0]", "sig[1]"]
    s0 = session.resolve_signal(f"{key}::sig[0]")
    s1 = session.resolve_signal(f"{key}::sig[1]")
    assert s0 is not None and s1 is not None
    np.testing.assert_array_equal(s0.values, [1.0, 2.0])
    np.testing.assert_array_equal(s1.values, [3.0, 4.0])
    assert s0.metadata["name_deduplicated"] is True


def test_exploded_parent_carries_no_conversion_metadata(tmp_path: Path) -> None:
    """LD-07: exploded 述語の帰結は不変 — 展開対象チャンネルは変換情報を持たず、
    1-D の enum チャンネルは従来どおり value_labels を持つ。"""
    session, key, _d = _loaded(write_mdf4_2d(tmp_path))
    mat = session.resolve_signal(f"{key}::Mat")
    assert mat is not None
    assert "value_labels" not in mat.metadata
    assert "conversion_info" not in mat.metadata

    enum_session = Session()
    enum_key = enum_session.load(write_mdf4_value2text(tmp_path)).key
    turn = enum_session.resolve_signal(f"{enum_key}::TurnSig")
    assert turn is not None
    assert turn.metadata["value_labels"] == {0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"}
