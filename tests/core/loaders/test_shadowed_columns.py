"""最長一致で影に隠れる列の検出と到達不能性 (E-4c spec §3・G1/G2)。

2-D チャンネル ``Mat`` と実在 1-D チャンネル ``Mat[0]`` が共存すると、最長一致規則
(E-3 の test-lock 済み意図的仕様) で実チャンネルが勝ち、**配列 ``Mat`` の第 0 列は
列キーでは二度と指せない**。データは正しく読めるので値のテストは全部緑のままで、
E-4c 以前は消えた列をユーザーが知る手段も、到達不能性そのものを assert する
テストも**存在しなかった**。

本モジュールは 2 つを**対で**固定する:

1. **到達不能性そのもの** (G2) — 全物理チャンネルの全列名を実際に resolve し、
   「生成元と別のチャンネルへ着地した列」を数え上げる。診断側が壊れても
   到達不能性側が壊れても、必ずどちらかが落ちる。
2. **info 診断** (G1) — 衝突ペアごとにちょうど 1 件。

**文言はテストへ直書きする**: production の f-string を import して組み立てると
文言変更で両側が同時に動き、assert が恒真化する (増分 D-1 で 4 件の silent
vacuous 化を実測した罠と同型)。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tests.mdf4_helpers import (
    write_mdf4_2d,
    write_mdf4_multistage_shadow,
    write_mdf4_out_of_range_leaf_name,
    write_mdf4_shadowed_leaf,
)
from valisync.core.loaders.column_names import owning_candidates, shadowed_leaf
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Diagnostic
from valisync.core.session import Session

#: 文言の**独立オラクル** (spec §3.3)。production の f-string を import しない。
_SHADOW_TMPL = (
    "信号 '{name}': 同名の実チャンネルが優先されるため、"
    "配列 '{parent}' の列 {position} は列キーでは参照できません"
)
#: 衝突 info を展開 info から選り分ける不変片 (文言が変われば expected 側と
#: 同時に落ちるので、ここが単独で恒真化することはない)。
_SHADOW_MARK = "列キーでは参照できません"


@dataclass(frozen=True)
class _Loaded:
    session: Session
    key: str
    diagnostics: tuple[Diagnostic, ...]


@contextmanager
def _loaded(path: Path) -> Iterator[_Loaded]:
    """``Session.load`` 経由で開く (ローダー直叩きでは診断 plumbing を通らない)。

    遅延ロードは MDF を開いたまま保持するので、必ず ``remove_group`` で閉じる —
    Windows は開いたままだと ``tmp_path`` の後始末がファイルロックで失敗しうる。
    """
    session = Session()
    outcome = session.load(path)
    try:
        yield _Loaded(session=session, key=outcome.key, diagnostics=outcome.diagnostics)
    finally:
        session.remove_group(outcome.key)


def _shadow_diags(diagnostics: tuple[Diagnostic, ...]) -> list[Diagnostic]:
    """衝突 info だけを取り出す (同じ level の展開 info と混ざらないように)。"""
    return [d for d in diagnostics if _SHADOW_MARK in d.message]


def _unreachable(loaded: _Loaded) -> list[tuple[str, str]]:
    """(生成元チャンネル, 列キー) — その列が **別の**チャンネルへ着地したもの。

    全物理チャンネルの全列名を実際に解決するので、「列が消えた」を主張でなく
    実測で数える。``column_names_of`` は鋳造を誘発せず列名だけを返し、
    ``physical_channel`` metadata は ``column_records`` のキー空間と同一なので、
    「生成元 != 着地先」がそのまま到達不能の定義になる。
    """
    session, key = loaded.session, loaded.key
    lost: list[tuple[str, str]] = []
    for sig in session.group_signals(key):
        physical = sig.metadata["physical_channel"]
        for column in session.column_names_of(key, physical):
            got = session.resolve_signal(f"{key}::{column}")
            owner = None if got is None else got.metadata.get("physical_channel")
            if owner != physical:
                lost.append((physical, column))
    return lost


def test_shadowed_leaf_emits_exactly_one_info(tmp_path: Path) -> None:
    """G1: 衝突ペアごとに info ちょうど 1 件 (level / signal_name / 文言まで固定)。"""
    with _loaded(write_mdf4_shadowed_leaf(tmp_path)) as loaded:
        hits = _shadow_diags(loaded.diagnostics)
        assert len(hits) == 1, [d.message for d in loaded.diagnostics]
        (diag,) = hits
        assert diag.level == "info"  # error ではない (データは正しく読める)
        assert diag.signal_name == "Mat[0]"  # 勝った側 = 診断ドックの「対象」列
        assert diag.message == _SHADOW_TMPL.format(
            name="Mat[0]", parent="Mat", position="[0]"
        )


def test_shadowed_leaf_is_actually_unreachable(tmp_path: Path) -> None:
    """G2: 到達不能性そのもの。

    **最後の 1 行だけが診断に依存する**: 上の 4 つは E-4c 以前から成立する
    characterization (最長一致の仕様そのもの) で、将来その規則を変えたら落ちる。
    最後の突き合わせが「診断の件数 == 実測した到達不能列の本数」を要求し、
    診断側だけ・実測側だけの片肺状態を落とす。
    """
    with _loaded(write_mdf4_shadowed_leaf(tmp_path)) as loaded:
        assert _unreachable(loaded) == [("Mat", "Mat[0]")]
        got = loaded.session.resolve_signal(f"{loaded.key}::Mat[0]")
        assert got is not None
        assert got.metadata["physical_channel"] == "Mat[0]"  # 親 "Mat" ではない
        assert got.metadata["unit"] == "deg"  # 親は "mm"
        assert got.values.dtype == np.float64  # 親の列は uint8
        # 母数 5 列 (Mat 3 + Mat[0] 1 + Clean 1) のうち 1 本が到達不能。
        assert loaded.session.total_column_count(loaded.key) == 5
        assert len(_shadow_diags(loaded.diagnostics)) == len(_unreachable(loaded))


def test_out_of_range_leaf_name_is_not_a_collision(tmp_path: Path) -> None:
    """範囲外 (幅 3 の配列に対する ``Mat[7]``) は到達不能列を作らない = 診断 0 件。"""
    with _loaded(write_mdf4_out_of_range_leaf_name(tmp_path)) as loaded:
        assert _shadow_diags(loaded.diagnostics) == []
        assert _unreachable(loaded) == []


def test_ordinary_file_emits_no_collision_info(tmp_path: Path) -> None:
    """非衝突ファイル (既存の 2-D fixture) では 1 件も出ない。"""
    with _loaded(write_mdf4_2d(tmp_path)) as loaded:
        assert _shadow_diags(loaded.diagnostics) == []
        assert _unreachable(loaded) == []
        # 反 vacuous: 展開 info そのものは出ている (診断経路が死んでいない)。
        assert any("本に展開" in d.message for d in loaded.diagnostics)


def test_multistage_names_are_detected_by_the_shared_walk(tmp_path: Path) -> None:
    """多段名も同一規則で検出する (``W[0][1]`` = dedup 済み親 / ``Nest.g[3]`` = 2 段)。"""
    with _loaded(write_mdf4_multistage_shadow(tmp_path)) as loaded:
        got = sorted(
            (d.signal_name, d.message) for d in _shadow_diags(loaded.diagnostics)
        )
        assert got == [
            (
                "Nest.g[3]",
                _SHADOW_TMPL.format(name="Nest.g[3]", parent="Nest", position=".g[3]"),
            ),
            (
                "W[0][1]",
                _SHADOW_TMPL.format(name="W[0][1]", parent="W[0]", position="[1]"),
            ),
        ]
        assert sorted(_unreachable(loaded)) == [
            ("Nest", "Nest.g[3]"),
            ("W[0]", "W[0][1]"),
        ]


def test_detection_and_resolution_share_one_walk(tmp_path: Path) -> None:
    """G5: 検出 (``shadowed_leaf``) と解決 (``_owning_channel``) が同じ walk を通る。

    ``owning_candidates`` は「長い順の候補列」で、解決側は**最初に受理された 1 本**で
    打ち切り、検出側は**自己ヒットの次**を取る。両者を同じ列に対して並べて固定して
    おくと、片方だけを書き換えた実装 (= 規則の二重化) が必ずここで落ちる。
    """
    result = MdfLoader().load(write_mdf4_shadowed_leaf(tmp_path))
    group = result.signal_group
    assert group is not None
    mgr = SignalGroupManager()
    key = mgr.add(group, column_records=result.column_records)
    try:
        records = mgr.column_records(key)
        hit = mgr._owning_channel(key, "Mat[0]")
        assert hit is not None
        assert (hit.display, hit.rest, hit.path) == ("Mat[0]", "", None)
        shadow = shadowed_leaf("Mat[0]", records)
        assert shadow is not None
        assert (shadow.display, shadow.rest) == ("Mat", "[0]")
        assert [(c.display, c.rest) for c in owning_candidates("Mat[0]", records)] == [
            ("Mat[0]", ""),
            ("Mat", "[0]"),
        ]
        # 実チャンネルでない名前は誰の影にもならない (呼び違いの防波堤)。
        assert shadowed_leaf("Mat[1]", records) is None
    finally:
        mgr.remove(key)
        if group.handle is not None:
            group.handle.close()
