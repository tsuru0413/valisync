"""列ブロックの計画と block-temp 書き (E-4b Task 6・spec §5.3)。

この時点で ``CsvExporter.export`` はまだ Task 4 の橋を通る。ブロック writer は
**独立に**駆動して観測する — 中間観測物は「block-temp のバイト内容」であり、
最終ファイルではない。
"""

from __future__ import annotations

import gc
import threading
import weakref
from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import (
    _CANCEL_ROW_INTERVAL,
    CsvExporter,
    CsvExportOptions,
    ExportCancelled,
    block_columns,
    plan_blocks,
    scan_masters,
)
from valisync.core.export.timeline import union_timeline
from valisync.core.models import Signal

_MIB = 1024 * 1024


def _sig(
    name: str, ts: list[float], vs: list[float], *, unit: str = "", phys: str = ""
) -> Signal:
    metadata: dict[str, object] = {}
    if unit:
        metadata["unit"] = unit
    if phys:
        metadata["physical_channel"] = phys
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="test",
        bus_type="",
        source_file="",
        metadata=metadata,
    )


def _columns(*signals: Signal) -> list[tuple[str, Signal | None]]:
    """(key, 直渡し Signal) の列リスト。直渡しは resolve を経由しない形の pin。"""
    return [(s.name, None) for s in signals]


def _resolver(*signals: Signal):  # type: ignore[no-untyped-def]
    table = {s.name: s for s in signals}
    return lambda key: table.get(key)


# ─── block_columns (D3 の動的決定) ────────────────────────────────────────────


def test_block_columns_is_clamped_to_the_maximum_when_the_budget_is_large() -> None:
    assert block_columns(n_rows=100, max_master_len=100, budget_bytes=256 * _MIB) == 512


def test_block_columns_is_clamped_to_the_minimum_when_the_budget_is_tiny() -> None:
    """**下限 16 は「予算を守れない」ではなく「進める」ための床** (spec D3)。"""
    assert (
        block_columns(n_rows=10_000_000, max_master_len=10_000_000, budget_bytes=1)
        == 16
    )


def test_block_columns_scales_with_the_remaining_budget() -> None:
    # per_col = 1000*9 + 1000*16 = 25,000 B -> 2,500,000 // 25,000 = 100
    assert (
        block_columns(n_rows=1000, max_master_len=1000, budget_bytes=2_500_000) == 100
    )


def test_block_columns_of_an_empty_range_does_not_divide_by_zero() -> None:
    assert block_columns(n_rows=0, max_master_len=0, budget_bytes=1024) == 512


# ─── plan_blocks (チャンネル局所の割り当て) ───────────────────────────────────


def test_plan_blocks_keeps_a_channel_whole() -> None:
    """1 チャンネルの全列は同一ブロックへ (spec §5.3: evict 連鎖の頭打ち)。"""
    assert plan_blocks([3, 3, 3], block_cols=4) == ((0, 3), (3, 6), (6, 9))


def test_plan_blocks_packs_channels_up_to_the_limit() -> None:
    assert plan_blocks([2, 2], block_cols=4) == ((0, 4),)


def test_plan_blocks_splits_a_channel_that_alone_exceeds_the_limit() -> None:
    """幅 1,100 の単独チャンネルは分割する。

    分割してよいのは E-4a のチャンネルキャッシュが 2-D を保持しており、
    2 ブロック目の切り出しが select ではなくヒットになるから。
    「絶対に割らない」にすると 1 ブロックが上限の 2 倍を実体化する。
    """
    assert plan_blocks([10], block_cols=4) == ((0, 4), (4, 8), (8, 10))


def test_plan_blocks_of_no_columns_is_empty() -> None:
    assert plan_blocks([], block_cols=4) == ()


# ─── scan_masters (値を読まない前走査) ────────────────────────────────────────


def test_scan_masters_dedups_by_identity_and_counts_channel_runs() -> None:
    master = np.array([0.0, 1.0, 2.0])
    a = Signal(
        name="mf4_1::W[0]",
        timestamps=master,
        values=np.zeros(3),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={"physical_channel": "W"},
    )
    b = Signal(
        name="mf4_1::W[1]",
        timestamps=a.timestamps,
        values=np.zeros(3),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={"physical_channel": "W"},
    )
    c = _sig("mf4_1::Other", [0.0, 0.5, 1.0], [1.0, 2.0, 3.0], phys="Other")

    scan = scan_masters(_columns(a, b, c), _resolver(a, b, c))

    assert len(scan.masters) == 2  # W の 2 列は master を共有
    assert scan.runs == (2, 1)
    assert scan.max_master_len == 3


def test_scan_masters_never_materialises_values(tmp_path: Path) -> None:
    """見積 (T-UX) が「値を読まない」でいられる根拠を writer 側でも pin する。"""
    from tests.mdf4_helpers import write_mdf4_2d
    from valisync.core.session import Session

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    keys = [f"{key}::Mat[{i}]" for i in range(3)]
    resolve = session.resolve_signal_transient

    scan = scan_masters([(k, None) for k in keys], resolve)

    assert scan.runs == (3,)  # 3 列は同一物理チャンネル = 1 run
    parent = next(s for s in session.group_signals(key) if s.name == f"{key}::Mat")
    assert parent._values_source.is_materialized is False


def test_scan_masters_raises_for_an_unresolvable_key() -> None:
    with pytest.raises(ValueError, match="解決できません"):
        scan_masters([("mf4_1::Nope", None)], lambda _k: None)


# ─── block-temp の中身 ────────────────────────────────────────────────────────


def _write_block(
    tmp_path: Path, signals: list[Signal], opts: CsvExportOptions | None = None
) -> tuple[list[str], list[str]]:
    """1 ブロックを書いて (行, 単位側帯) を返す。"""
    opts = opts or CsvExportOptions()
    union = union_timeline([s.timestamps for s in signals])
    temp = tmp_path / "block.tmp"
    units = CsvExporter()._write_block_temp(
        _columns(*signals),
        resolve=_resolver(*signals),
        union_view=union,
        opts=opts,
        temp_path=temp,
        cancel=None,
    )
    return temp.read_text(encoding="utf-8").splitlines(), units


def test_block_temp_holds_one_joined_fragment_per_row(tmp_path: Path) -> None:
    a = _sig("a", [0.0, 2.0], [10.0, 12.0])
    b = _sig("b", [1.0, 2.0], [21.0, 22.0])
    rows, _units = _write_block(tmp_path, [a, b])
    assert rows == ["10.0,", ",21.0", "12.0,22.0"]  # union = {0,1,2}


def test_block_temp_row_count_equals_the_union_view_length(tmp_path: Path) -> None:
    a = _sig("a", [0.0, 2.0], [10.0, 12.0])
    rows, _units = _write_block(tmp_path, [a])
    assert len(rows) == 2


def test_block_temp_of_zero_rows_is_an_empty_file(tmp_path: Path) -> None:
    """範囲外エクスポート (ヘッダのみのファイル) の中間形。"""
    a = _sig("a", [], [])
    rows, _units = _write_block(tmp_path, [a])
    assert rows == []
    assert (tmp_path / "block.tmp").read_bytes() == b""


def test_block_temp_collects_units_in_column_order(tmp_path: Path) -> None:
    a = _sig("a", [0.0], [1.0], unit="km/h")
    b = _sig("b", [0.0], [2.0])
    _rows, units = _write_block(tmp_path, [a, b])
    assert units == ["km/h", ""]


def test_block_temp_unit_of_none_becomes_an_empty_cell(tmp_path: Path) -> None:
    """手組み metadata の ``unit=None`` (spec §9-6)。join で TypeError にしない。"""
    a = Signal(
        name="a",
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="t",
        bus_type="",
        source_file="",
        metadata={"unit": None},
    )
    _rows, units = _write_block(tmp_path, [a])
    assert units == [""]


def test_block_temp_honours_delimiter_and_decimal(tmp_path: Path) -> None:
    a = _sig("a", [0.0], [1.5])
    b = _sig("b", [0.0], [2.5])
    rows, _units = _write_block(
        tmp_path, [a, b], CsvExportOptions(delimiter=";", decimal=",")
    )
    assert rows == ["1,5;2,5"]


def test_block_temp_rejects_a_container_column_before_reading_rows(
    tmp_path: Path,
) -> None:
    """1 時刻 1 値でない列は行組み立ての**前**に拒否する (E-3 C-d の位置)。"""
    parent = Signal(
        name="Mat",
        timestamps=np.arange(4.0),
        values=np.arange(12, dtype=np.uint8).reshape(4, 3),
        file_format="MDF4",
        bus_type="",
        source_file="",
    )
    with pytest.raises(ValueError, match="配列チャンネル"):
        _write_block(tmp_path, [parent])
    assert (tmp_path / "block.tmp").exists() is False


# ─── キャンセル (I8: 3 つのチェック点) ────────────────────────────────────────


def test_cancel_before_a_column_read_stops_within_that_block(tmp_path: Path) -> None:
    """ブロック境界だけでは cold ~316 ms/列 x block_cols の間 Event を見ない。"""
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    b = _sig("b", [0.0, 1.0], [3.0, 4.0])
    cancel = threading.Event()
    seen: list[str] = []

    def resolve(key: str) -> Signal | None:
        seen.append(key)
        cancel.set()  # 1 列目を渡した直後にキャンセル要求が立つ
        return {"a": a, "b": b}.get(key)

    with pytest.raises(ExportCancelled):
        CsvExporter()._write_block_temp(
            _columns(a, b),
            resolve=resolve,
            union_view=union_timeline([a.timestamps]),
            opts=CsvExportOptions(),
            temp_path=tmp_path / "block.tmp",
            cancel=cancel,
        )
    assert seen == ["a"], "2 列目を読み始めている (チェック点が列の前に無い)"


def test_cancel_inside_a_long_row_loop_stops_before_the_end(tmp_path: Path) -> None:
    n = 50_000
    a = _sig("a", np.arange(n).tolist(), np.arange(n).tolist())
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ExportCancelled):
        CsvExporter()._write_block_temp(
            _columns(a),
            resolve=_resolver(a),
            union_view=union_timeline([a.timestamps]),
            opts=CsvExportOptions(),
            temp_path=tmp_path / "block.tmp",
            cancel=cancel,
        )


def test_cancel_is_polled_inside_the_row_loop_not_only_at_its_start(
    tmp_path: Path,
) -> None:
    """行ループのポーリングは **i==0 だけではない** ことの唯一の番人。

    上の 2 本はどちらも**列ループ**のチェック点で止まる (前者は 2 列目の前、
    後者は 1 列目の前で Event が既に立っている) ため、行ループのチェック点を
    丸ごと削っても緑のまま通る — 実測で確認済み。prod のブロックは 12,012 行を
    回すので、行ループへ入った後に立った要求を拾う点が無いと、キャンセルは
    ブロック 1 つぶん (最大 ~1.8 s) 遅れる。

    ``is_set`` の呼び出し回数を数える stub で「いつ見たか」を直接観測する:
    1 回目 = 列ループ (1 列)・2 回目 = 行 i=0・3 回目 = 行 i=_CANCEL_ROW_INTERVAL。
    3 回目で初めて True にすると、**行 0 より後**のチェック点でしか止まれない。
    """

    class _LateCancel:
        """N 回目のポーリングから True を返す (threading.Event の duck-type)。"""

        def __init__(self, fire_after: int) -> None:
            self.polls = 0
            self._fire_after = fire_after

        def is_set(self) -> bool:
            self.polls += 1
            return self.polls > self._fire_after

    n = _CANCEL_ROW_INTERVAL * 2 + 1
    a = _sig("a", np.arange(n, dtype=np.float64).tolist(), [0.0] * n)
    cancel = _LateCancel(fire_after=2)

    with pytest.raises(ExportCancelled):
        CsvExporter()._write_block_temp(
            _columns(a),
            resolve=_resolver(a),
            union_view=union_timeline([a.timestamps]),
            opts=CsvExportOptions(),
            temp_path=tmp_path / "block.tmp",
            cancel=cancel,  # type: ignore[arg-type]
        )

    assert cancel.polls == 3, "行ループ内の周期チェックが無い (i==0 だけで見ている)"


# ─── G2/G5 の weakref オラクル ────────────────────────────────────────────────


def test_transient_columns_do_not_accumulate_across_blocks(tmp_path: Path) -> None:
    """**G2/G5 の形** (spec §6): 生存数はブロック内に閉じる。

    ``resolved_keys()`` / ``bytes_held`` は使わない — 前者は export 専用 resolve に
    構造的に盲目・後者は pin されない列に無関係 (spec §10)。
    """
    n_cols, block_cols = 12, 3
    master = np.arange(50, dtype=np.float64)
    master.flags.writeable = False
    refs: list[weakref.ref[Signal]] = []
    # **ブロック内**の生存数を採る (ブロック終端で採ると常に 0 になり、上界の
    # assert が恒真化する)。resolve が呼ばれた直後 = その列がまだ生きている瞬間。
    live_marks: list[int] = []

    def resolve(key: str) -> Signal | None:
        sig = Signal(
            name=key,
            timestamps=master,
            values=np.arange(50, dtype=np.float64),
            file_format="t",
            bus_type="",
            source_file="",
            metadata={"physical_channel": key},
        )
        refs.append(weakref.ref(sig))
        gc.collect()
        live_marks.append(sum(1 for r in refs if r() is not None))
        return sig

    exporter = CsvExporter()
    union = union_timeline([master])
    keys = [f"c{i}" for i in range(n_cols)]
    tails: list[int] = []
    for lo, hi in plan_blocks([1] * n_cols, block_cols):
        exporter._write_block_temp(
            [(k, None) for k in keys[lo:hi]],
            resolve=resolve,
            union_view=union,
            opts=CsvExportOptions(),
            temp_path=tmp_path / f"b{lo}.tmp",
            cancel=None,
        )
        gc.collect()
        tails.append(sum(1 for r in refs if r() is not None))

    assert len(refs) == n_cols  # 反 vacuous: 実際に 12 本鋳造している
    assert max(live_marks) >= 1, "1 本も生存を観測していない (上界 0 の空虚形)"
    assert max(live_marks) <= block_cols, live_marks  # G2: 同時生存 <= block_cols
    assert tails == [0] * len(tails), f"ブロック終端で参照が残った: {tails}"  # G5
