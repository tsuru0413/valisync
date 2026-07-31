# ruff: noqa: RUF002
"""Tests for reference_overlay (E-2b — reference-file same-name auto-overlay).

Pure-Python VM-level logic (spec §3): the 5-step matching/skip-counting
algorithm, exercised directly via GraphPanelVM + Session (no MainWindow/Qt
widget needed — see module docstring in reference_overlay.py).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4, write_mdf4_2d
from valisync.core.models import Signal, SignalGroup
from valisync.core.session import Session
from valisync.gui.reference_overlay import (
    OverlayResult,
    file_display_name,
    format_overlay_summary,
    overlay_reference_signals,
)
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

_BASE_DIR = Path(__file__).resolve().parent


def _sig(name: str, unit: str | None = None, deduplicated: bool = False) -> Signal:
    metadata: dict[str, object] = {}
    if unit is not None:
        metadata["unit"] = unit
    if deduplicated:
        metadata["name_deduplicated"] = True
    return Signal(
        name=name,
        timestamps=np.array([0.0, 1.0, 2.0], dtype=np.float64),
        values=np.array([0.0, 10.0, 20.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
        metadata=metadata,
    )


def _add_group(session: Session, path_name: str, *signals: Signal) -> str:
    """Register *signals* as one SignalGroup (one "file") and return its key."""
    return session._groups.add(
        SignalGroup(
            signals=tuple(signals),
            source_path=_BASE_DIR / path_name,
            file_format="CSV",
            loaded_at=datetime.now(),
        )
    )


def _bare_key(session: Session, group_key: str, bare_name: str) -> str:
    """Namespaced key for *bare_name* within *group_key* (post-registration)."""
    return next(
        s.name
        for s in session.group_signals(group_key)
        if s.name.endswith(f"::{bare_name}")
    )


# ─── Matching / adding ──────────────────────────────────────────────────────


def test_overlay_adds_matching_signal_to_same_axis() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed", unit="km/h"))
    ref_speed = _bare_key(session, ref_key, "speed")
    tgt_speed = _bare_key(session, tgt_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result == OverlayResult(
        total=1, added=1, no_match=0, unit_mismatch=0, already_present=0, ambiguous=0
    )
    entries = panel.plotted_entries()
    assert {(sk, ax) for _eid, sk, ax in entries} == {(ref_speed, 0), (tgt_speed, 0)}


def test_overlay_only_scans_reference_group_entries() -> None:
    """total (母数) counts only entries whose group is the reference — an
    entry from some THIRD (unrelated) group already on the panel is ignored."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed", unit="km/h"))
    other_key = _add_group(session, "other.csv", _sig("rpm", unit="rpm"))
    ref_speed = _bare_key(session, ref_key, "speed")
    other_rpm = _bare_key(session, other_key, "rpm")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)
    panel.add_signal_to_axis(other_rpm, 1)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.total == 1  # the "other" entry is not counted
    assert result.added == 1


# ─── Skip: no match ─────────────────────────────────────────────────────────


def test_overlay_no_match_when_target_lacks_bare_name() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("rpm", unit="rpm"))
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result == OverlayResult(
        total=1, added=0, no_match=1, unit_mismatch=0, already_present=0, ambiguous=0
    )


def test_overlay_unknown_target_key_is_all_no_match() -> None:
    """An unknown target_key (KeyError from group_signals) behaves as an
    empty file — every reference entry is a no-match, nothing raises."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, "no_such_key")

    assert result.total == 1
    assert result.no_match == 1
    assert result.added == 0


# ─── Skip: unit mismatch ────────────────────────────────────────────────────


def test_overlay_unit_mismatch_skips() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed", unit="mph"))
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.unit_mismatch == 1
    assert result.added == 0


def test_overlay_both_units_empty_passes() -> None:
    """Exact-string comparison: both missing/empty units counts as a match
    (spec §3 判断点3 — real ADAS data commonly lacks unit metadata)."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed"))  # no unit metadata
    tgt_key = _add_group(session, "tgt.csv", _sig("speed"))  # no unit metadata
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.added == 1
    assert result.unit_mismatch == 0


def test_overlay_one_side_empty_unit_is_a_mismatch() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed"))  # no unit metadata
    ref_speed = _bare_key(session, ref_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.unit_mismatch == 1
    assert result.added == 0


# ─── Skip: already present ──────────────────────────────────────────────────


def test_overlay_already_present_is_not_re_added() -> None:
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("speed", unit="km/h"))
    tgt_key = _add_group(session, "tgt.csv", _sig("speed", unit="km/h"))
    ref_speed = _bare_key(session, ref_key, "speed")
    tgt_speed = _bare_key(session, tgt_key, "speed")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)
    panel.add_signal_to_axis(tgt_speed, 0)  # already overlaid once

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result == OverlayResult(
        total=1, added=0, no_match=0, unit_mismatch=0, already_present=1, ambiguous=0
    )
    # Still exactly the 2 original entries — no duplicate third entry.
    assert len(panel.plotted_entries()) == 2


# ─── Skip: ambiguous (LD-08 dedup) ──────────────────────────────────────────


def test_overlay_ambiguous_when_reference_entry_is_deduplicated() -> None:
    session = Session()
    ref_key = _add_group(
        session, "ref.csv", _sig("spd[0]", unit="km/h", deduplicated=True)
    )
    tgt_key = _add_group(session, "tgt.csv", _sig("spd[0]", unit="km/h"))
    ref_spd = _bare_key(session, ref_key, "spd[0]")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_spd, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.ambiguous == 1
    assert result.added == 0
    assert result.no_match == 0  # excluded BEFORE the search, not "no match"


def test_overlay_ambiguous_when_candidate_is_deduplicated() -> None:
    """The reference's own name is un-flagged; a literal bare-name match
    happens to be a dedup-suffixed candidate in the target file. Checked on
    both sides (spec §3 step 5 — a silent bad pairing is undetectable)."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("spd[0]", unit="km/h"))
    tgt_key = _add_group(
        session, "tgt.csv", _sig("spd[0]", unit="km/h", deduplicated=True)
    )
    ref_spd = _bare_key(session, ref_key, "spd[0]")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_spd, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.ambiguous == 1
    assert result.added == 0


def test_overlay_array_expansion_name_is_not_ambiguous() -> None:
    """LD-14 array-expansion names (e.g. "Mat[0]") look identical to a LD-08
    dedup suffix but carry NO name_deduplicated flag — deterministic and
    cross-file comparable, so eligible for ordinary matching (spec §3 step 5)."""
    session = Session()
    ref_key = _add_group(session, "ref.csv", _sig("Mat[0]", unit="m"))
    tgt_key = _add_group(session, "tgt.csv", _sig("Mat[0]", unit="m"))
    ref_mat = _bare_key(session, ref_key, "Mat[0]")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_mat, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.ambiguous == 0
    assert result.added == 1


# ─── Multi-entry partition ──────────────────────────────────────────────────


def test_overlay_partitions_multiple_reference_entries() -> None:
    session = Session()
    ref_key = _add_group(
        session,
        "ref.csv",
        _sig("speed", unit="km/h"),  # will match
        _sig("rpm", unit="rpm"),  # no match in target
        _sig("temp", unit="C"),  # unit mismatch
    )
    tgt_key = _add_group(
        session,
        "tgt.csv",
        _sig("speed", unit="km/h"),
        _sig("temp", unit="F"),
    )
    ref_speed = _bare_key(session, ref_key, "speed")
    ref_rpm = _bare_key(session, ref_key, "rpm")
    ref_temp = _bare_key(session, ref_key, "temp")

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_speed, 0)
    panel.create_new_axis(ref_rpm)  # axis 1
    panel.create_new_axis(ref_temp)  # axis 2

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.total == 3
    assert result.added == 1
    assert result.no_match == 1
    assert result.unit_mismatch == 1
    assert result.already_present == 0
    assert result.ambiguous == 0


# ─── format_overlay_summary ─────────────────────────────────────────────────


def test_format_summary_no_reference_signals() -> None:
    result = OverlayResult(
        total=0, added=0, no_match=0, unit_mismatch=0, already_present=0, ambiguous=0
    )
    assert (
        format_overlay_summary(result, "b.csv") == "基準の信号がプロットされていません"
    )


def test_format_summary_all_done() -> None:
    result = OverlayResult(
        total=2, added=0, no_match=0, unit_mismatch=0, already_present=2, ambiguous=0
    )
    assert format_overlay_summary(result, "b.csv") == "すべて重ね済みです"


def test_format_summary_general_case_omits_zero_clauses() -> None:
    result = OverlayResult(
        total=1, added=1, no_match=0, unit_mismatch=0, already_present=0, ambiguous=0
    )
    assert (
        format_overlay_summary(result, "b.csv") == "b.csv の同名信号を 1 件重ねました"
    )


def test_format_summary_general_case_includes_nonzero_clauses() -> None:
    result = OverlayResult(
        total=4, added=1, no_match=1, unit_mismatch=1, already_present=1, ambiguous=0
    )
    msg = format_overlay_summary(result, "b.csv")
    assert (
        msg == "b.csv の同名信号を 1 件重ねました（同名なし 1・単位不一致 1・済み 1）"
    )


def test_format_summary_ambiguous_clause() -> None:
    result = OverlayResult(
        total=1, added=0, no_match=0, unit_mismatch=0, already_present=0, ambiguous=1
    )
    msg = format_overlay_summary(result, "b.csv")
    assert msg == "b.csv の同名信号を 0 件重ねました（曖昧 1）"


# ─── file_display_name ──────────────────────────────────────────────────────


def test_file_display_name_no_collision(tmp_path: Path) -> None:
    session = Session()
    k1 = session._groups.add(
        SignalGroup((), (tmp_path / "a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = session._groups.add(
        SignalGroup((), (tmp_path / "b.csv").absolute(), "CSV", datetime.now())
    )
    assert file_display_name(session, [k1, k2], k2) == "b.csv"


def test_file_display_name_qualifies_on_basename_collision(tmp_path: Path) -> None:
    """UXG-09: re-opening the same path twice yields distinct keys but the
    same basename — qualify with the key so the summary is unambiguous."""
    session = Session()
    k1 = session._groups.add(
        SignalGroup((), (tmp_path / "a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = session._groups.add(
        SignalGroup((), (tmp_path / "a.csv").absolute(), "CSV", datetime.now())
    )
    assert file_display_name(session, [k1, k2], k2) == f"a.csv ({k2})"


# ─── E-3: 列レベルのマッチ (spec C-c) ───────────────────────────────────────


def _mat2d_in(tmp_path: Path, sub: str) -> Path:
    """write_mdf4_2d は固定名 mat2d.mf4 を書くので 2 本目は別ディレクトリへ置く。"""
    directory = tmp_path / sub
    directory.mkdir()
    return write_mdf4_2d(directory)


def test_overlay_matches_expanded_column_across_files(tmp_path: Path) -> None:
    """反転後 group_signals は物理チャンネルしか返さない。列レベルで引かないと
    Mat[0] が全て no_match になり「0 件重ねました（同名なし 1）」という
    **正常に見える嘘**が出る (真の不一致と区別できない)。"""
    session = Session()
    ref_key = session.load(_mat2d_in(tmp_path, "ref")).key
    tgt_key = session.load(_mat2d_in(tmp_path, "tgt")).key
    ref_col = f"{ref_key}::Mat[0]"

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_col, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.added == 1
    assert result.no_match == 0
    assert {(sk, ax) for _eid, sk, ax in panel.plotted_entries()} == {
        (ref_col, 0),
        (f"{tgt_key}::Mat[0]", 0),
    }


def test_overlay_rerun_is_idempotent_for_minted_columns(tmp_path: Path) -> None:
    """同じ重ねを 2 回走らせても列は増えない (T7 レビュー: 議論のみで未 test-lock)。

    ``already_present`` は plotted entries の **列キー** で作られる (C-c)。1 回目で
    鋳造された列キーが 2 回目に別表記で戻ってくる、あるいは物理チャンネル単位で
    突き合わせるようになると、2 回目が ``added=1`` になって同じ列が二重に載る。
    ここが崩れても 1 回目のテストは全て緑のままなので、**再実行**そのものを固定する。
    """
    session = Session()
    ref_key = session.load(_mat2d_in(tmp_path, "ref")).key
    tgt_key = session.load(_mat2d_in(tmp_path, "tgt")).key
    ref_col = f"{ref_key}::Mat[0]"

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_col, 0)

    first = overlay_reference_signals(panel, session, ref_key, tgt_key)
    assert first == OverlayResult(
        total=1, added=1, no_match=0, unit_mismatch=0, already_present=0, ambiguous=0
    )
    after_first = {(sk, ax) for _eid, sk, ax in panel.plotted_entries()}

    second = overlay_reference_signals(panel, session, ref_key, tgt_key)
    assert second == OverlayResult(
        total=1, added=0, no_match=0, unit_mismatch=0, already_present=1, ambiguous=0
    ), f"再実行が冪等でない: {second}"
    assert {(sk, ax) for _eid, sk, ax in panel.plotted_entries()} == after_first, (
        "再実行でエントリが増えた (同じ列が二重に載っている)"
    )
    # 母数は基準エントリのみ — 1 回目で追加した対象側の列を数え始めると total が
    # 実行ごとに増える (「重ねるほど仕事が増える」自己増殖)。
    assert second.total == 1


def test_overlay_column_key_collision_prefers_real_channel(tmp_path: Path) -> None:
    """`Mat[0]` 衝突の pin: 参照側の配列列 `Mat[0]` は、対象ファイルに実在する
    1-D チャンネル `Mat[0]` と単位一致で偶然ペアリングされる。どちらが選ばれるかは
    parse_leaf の最長一致規則 (実チャンネルが展開列に優先) で決まる — 規則を変えると
    重ねる相手が黙って別物になるので、値まで含めて固定する。"""
    session = Session()
    ref_key = session.load(_mat2d_in(tmp_path, "ref")).key
    tgt_path = write_mdf4(
        tmp_path / "tgt.mf4",
        [
            {
                "name": "Mat[0]",
                "timestamps": [0.0, 0.1, 0.2, 0.3],
                "values": [7.0, 8.0, 9.0, 10.0],
            }
        ],
    )
    tgt_key = session.load(tgt_path).key
    ref_col = f"{ref_key}::Mat[0]"

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_col, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    added_key = f"{tgt_key}::Mat[0]"
    assert result.added == 1
    assert (added_key, 0) in {(sk, ax) for _eid, sk, ax in panel.plotted_entries()}
    # 実チャンネル (物理) が勝つ — 鋳造された展開列ではない
    assert added_key in {s.name for s in session.group_signals(tgt_key)}
    got = session.resolve_signal(added_key)
    assert got is not None
    assert got.sorted_view()[1].tolist() == [7.0, 8.0, 9.0, 10.0]


def test_overlay_does_not_touch_the_resolver_for_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-7: 鋳造せずに決まる却下 (同名なし / 構造不一致 / 済み) は解決器に触らない。

    ``resolve_signal`` は鋳造の入口で、ヒットした列は ``_resolved_by_key`` へ
    登録される。E-4a の LRU で恒久滞留はしなくなったが、存在判定に使うと
    「重ねなかった候補」が非 pin の枠を食ってプロット中でない列を押し出す
    (spec §5.5)。したがって存在は ``has_column`` /
    ``is_container_channel`` が答え、鋳造は metadata (曖昧フラグ・単位) が本当に
    必要になるまで遅らせる。

    観測点は ``SignalGroupManager.resolve`` — ``session.resolve_signal`` も
    ``signal_map()`` のフォールスルーも通る**唯一の鋳造の扉**なので、呼び出し方を
    別 API へ差し替える「直し方」でも逃げられない。
    sabotage: 3 つの却下判定を ``resolve_signal`` の後ろへ戻すと呼び出しが 3 件
    記録されて RED。
    """
    ref_path = write_mdf4(
        tmp_path / "ref.mf4",
        [
            {"name": "Solo", "timestamps": [0.0, 0.1], "values": [1.0, 2.0]},
            {"name": "Mat", "timestamps": [0.0, 0.1], "values": [3.0, 4.0]},
            {"name": "Clean", "timestamps": [0.0, 0.1], "values": [5.0, 6.0]},
        ],
    )
    session = Session()
    ref_key = session.load(ref_path).key
    tgt_key = session.load(_mat2d_in(tmp_path, "tgt")).key  # Mat は 2-D 容器

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(f"{ref_key}::Solo", 0)  # tgt に同名なし
    panel.add_signal_to_axis(f"{ref_key}::Mat", 1)  # tgt の Mat は容器
    panel.add_signal_to_axis(f"{ref_key}::Clean", 2)
    panel.add_signal_to_axis(f"{tgt_key}::Clean", 2)  # 既に重ね済み

    calls: list[str] = []
    original = session._groups.resolve

    def counting(key: str) -> Signal | None:
        calls.append(key)
        return original(key)

    monkeypatch.setattr(session._groups, "resolve", counting)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result == OverlayResult(
        total=3,
        added=0,
        no_match=1,
        unit_mismatch=0,
        already_present=1,
        ambiguous=0,
        container=1,
    )
    assert calls == [], f"却下だけの重ねが解決器 (鋳造の扉) を叩いた: {calls}"

    # 反 vacuous: スパイは実際に配線されている (metadata が要る経路では鋳造が起こる)
    assert session.resolve_signal(f"{tgt_key}::Mat[0]") is not None
    assert calls == [f"{tgt_key}::Mat[0]"]


def test_overlay_skips_container_channel_candidate(tmp_path: Path) -> None:
    """参照が 1-D スカラー `Mat`、対象が 2-D 配列チャンネル `Mat` のとき、候補は列
    ではなく **配列の親**。載せると sorted_view() が float64 へ 8 倍膨張した 2-D 配列を
    恒久キャッシュし (prod で 96 MB/本)、そもそも描画できない。"""
    session = Session()
    ref_path = write_mdf4(
        tmp_path / "ref.mf4",
        [
            {
                "name": "Mat",
                "timestamps": [0.0, 0.1, 0.2, 0.3],
                "values": [1.0, 2.0, 3.0, 4.0],
            }
        ],
    )
    ref_key = session.load(ref_path).key
    tgt_key = session.load(_mat2d_in(tmp_path, "tgt")).key

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(f"{ref_key}::Mat", 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.container == 1
    assert result.added == 0
    assert len(panel.plotted_entries()) == 1  # 親は載らない
    # 拒否は **値を読まずに** 決める (チャンネル全読みは遅延展開の利得を捨てる)
    parent = session.resolve_signal(f"{tgt_key}::Mat")
    assert parent is not None
    assert parent._values_source.is_materialized is False


def test_format_summary_container_clause() -> None:
    result = OverlayResult(
        total=1,
        added=0,
        no_match=0,
        unit_mismatch=0,
        already_present=0,
        ambiguous=0,
        container=1,
    )
    msg = format_overlay_summary(result, "b.mf4")
    assert msg == "b.mf4 の同名信号を 0 件重ねました（構造不一致 1）"
