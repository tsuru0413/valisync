"""G3: ブロック k と k+1 の増分が「ブロック 1 個分」に対して +/-20% (spec §6)。

**計測は tracemalloc** (numpy のデータ確保も追跡される)。psutil は本番/dev いずれの
依存にも無いので、USS 版は VALISYNC_MEMTEST + importorskip の opt-in に留める
(tests/core/loaders/test_mdf_loader_master_retention.py と同型)。

2 ブロックでは傾き検定にならないので **ブロック数 >= 8** で測る。

**2 種類の観測点**を採る (どちらか一方だと空虚になる):

- ``progress`` (ブロック**境界** = 参照を落とした直後) の推移 -> **傾き**。
  ブロックを跨いで何かを溜め込む実装はここが右肩上がりになる。
- ``resolve`` (ブロック**内部** = その列がまだ生きている瞬間) のピーク ->
  **反 vacuous**。境界だけを見ると「実は 1 バイトも実体化していない」実装
  (= 全部 0 の傾き 0) と区別が付かない。
"""

from __future__ import annotations

import os
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import (
    CsvExporter,
    CsvExportOptions,
    ExportRequest,
)
from valisync.core.models import Signal

_N_COLUMNS = 16
_BLOCK_COLS = 2
_N_ROWS = 20_000
_N_BLOCKS = _N_COLUMNS // _BLOCK_COLS
# 1 ブロックが同時に抱える実体 (block_columns の式と同じ 9 B/セル)
_PER_BLOCK_BYTES = _BLOCK_COLS * _N_ROWS * 9


def _request(tmp_path: Path) -> ExportRequest:
    return ExportRequest(
        keys=tuple(f"c{i}" for i in range(_N_COLUMNS)),
        output_path=tmp_path / "big.csv",
        options=CsvExportOptions(),
        header_resolver=list,
    )


def _run(tmp_path: Path) -> tuple[list[int], list[int]]:
    """``(ブロック境界の推移, ブロック内部のピーク推移)``。"""
    master = np.arange(_N_ROWS, dtype=np.float64)
    master.flags.writeable = False
    values = np.arange(_N_ROWS, dtype=np.float64)

    inside: list[int] = []

    def resolve(key: str) -> Signal | None:
        # 呼ばれるのは前走査 (値を持たない) とブロック内部の 2 回。ブロック内部の
        # 呼び出し時点では、同じブロックの先行列の `aligned` がまだ生きている。
        inside.append(tracemalloc.get_traced_memory()[0])
        return Signal(
            name=key,
            timestamps=master,
            values=values.copy(),
            file_format="t",
            bus_type="",
            source_file="",
            metadata={"physical_channel": key},
        )

    boundaries: list[int] = []

    def progress(done: int, total: int) -> None:
        del done, total
        boundaries.append(tracemalloc.get_traced_memory()[0])

    tracemalloc.start()
    try:
        CsvExporter(block_cols=_BLOCK_COLS).export(
            _request(tmp_path), resolve, progress=progress
        )
    finally:
        tracemalloc.stop()
    # 先頭 1 件は時刻 temp、その後の _N_BLOCKS 件がブロック境界。
    return boundaries[1 : 1 + _N_BLOCKS], inside


def test_memory_per_block_does_not_grow_with_the_block_index(tmp_path: Path) -> None:
    marks, _inside = _run(tmp_path)
    assert len(marks) == _N_BLOCKS >= 8
    slope = (marks[-1] - marks[0]) / (len(marks) - 1)
    assert abs(slope) <= 0.2 * _PER_BLOCK_BYTES, (
        f"ブロックあたり {slope:,} B 積み上がっている "
        f"(許容 {0.2 * _PER_BLOCK_BYTES:,.0f} B): {marks}"
    )


def test_the_harness_actually_observes_a_block_sized_footprint(
    tmp_path: Path,
) -> None:
    """反 vacuous: 計測が全部 0 なら傾き検定は恒真になる。

    ブロック**内部**のピークが「ブロック 1 個分」の桁に達していることを見る。
    境界 (`marks`) は参照を落とした後なので、そこで同じ主張をすると
    「実は 1 セルも実体化していない」実装を見分けられない。
    """
    marks, inside = _run(tmp_path)
    assert min(marks) > 0, marks  # 計測器そのものが死んでいない
    assert max(inside) >= _PER_BLOCK_BYTES * 0.5, (
        f"ブロック内部のピークが {max(inside):,} B しかない "
        f"(1 ブロック分 = {_PER_BLOCK_BYTES:,} B)"
    )


def test_block_interior_peak_does_not_grow_with_the_block_index(
    tmp_path: Path,
) -> None:
    """内部ピークもブロック番号に対して伸びない (境界だけでは半分しか言えない)。

    ブロック終端で参照を落としていても、ブロック**内部**の同時生存が回を追って
    増える実装 (例: `aligned` を累積して最後にまとめて書く) はここでだけ RED。
    """
    _marks, inside = _run(tmp_path)
    # 前走査 (_N_COLUMNS 回) の後にブロック内部の _N_COLUMNS 回が来る。
    assert len(inside) == 2 * _N_COLUMNS, len(inside)
    per_block = [
        max(inside[_N_COLUMNS + i * _BLOCK_COLS : _N_COLUMNS + (i + 1) * _BLOCK_COLS])
        for i in range(_N_BLOCKS)
    ]
    slope = (per_block[-1] - per_block[0]) / (len(per_block) - 1)
    assert abs(slope) <= 0.2 * _PER_BLOCK_BYTES, (
        f"ブロック内部のピークが {slope:,} B/ブロックで伸びている: {per_block}"
    )


@pytest.mark.skipif(
    not os.environ.get("VALISYNC_MEMTEST"), reason="opt-in (USS 実測・psutil 要)"
)
def test_uss_per_block_does_not_grow(tmp_path: Path) -> None:
    """spec G3 の字義どおりの USS 版 (opt-in)。CI では tracemalloc 版が門番。"""
    psutil = pytest.importorskip("psutil")
    proc = psutil.Process()
    marks: list[int] = []
    master = np.arange(_N_ROWS, dtype=np.float64)
    master.flags.writeable = False

    def resolve(key: str) -> Signal | None:
        return Signal(
            name=key,
            timestamps=master,
            values=np.arange(_N_ROWS, dtype=np.float64),
            file_format="t",
            bus_type="",
            source_file="",
            metadata={"physical_channel": key},
        )

    def progress(done: int, total: int) -> None:
        del done, total
        marks.append(proc.memory_full_info().uss)

    CsvExporter(block_cols=_BLOCK_COLS).export(
        _request(tmp_path), resolve, progress=progress
    )
    block_marks = marks[1 : 1 + _N_BLOCKS]
    slope = (block_marks[-1] - block_marks[0]) / (len(block_marks) - 1)
    assert abs(slope) <= 0.2 * _PER_BLOCK_BYTES, block_marks
