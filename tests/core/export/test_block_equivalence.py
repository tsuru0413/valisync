"""ブロック幅・fan-in を変えても出力バイトが変わらないこと (E-4b Task 7)。

**ゴールデンの補完**: ゴールデン (T-G) が「正しいバイト」を固定するのに対し、
ここは「どう分割しても同じバイト」を固定する。ブロック境界のオフバイワン・
マージ順の入れ替え・断片の取りこぼしはここで RED になる。

fixture 軸は spec §7.1 と同一 (単一/統合 x 範囲 x 欠測 x 非有限 x 非単調 x
重複 ts x len 0 x ULP 分裂 x unit x delimiter/decimal/precision)。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import (
    CsvExporter,
    CsvExportOptions,
    ExportRequest,
)
from valisync.core.models import Signal


def _sig(name: str, ts: list[float], vs: list[float], unit: str = "") -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="test",
        bus_type="",
        source_file="",
        metadata={"unit": unit} if unit else {},
    )


def _case_union() -> tuple[list[Signal], dict[str, object]]:
    return [
        _sig("a", [0.0, 2.0], [10.0, 12.0]),
        _sig("b", [1.0, 3.0], [21.0, 23.0]),
    ], {"use_unified_timeline": True}


def _case_range() -> tuple[list[Signal], dict[str, object]]:
    sigs, opts = _case_union()
    return sigs, {**opts, "time_start": 1.0, "time_end": 2.0}


def _case_shared() -> tuple[list[Signal], dict[str, object]]:
    return [
        _sig("c", [0.0, 1.0], [1.0, 2.0]),
        _sig("d", [0.0, 1.0], [3.0, 4.0]),
    ], {"use_unified_timeline": False}


def _case_non_monotonic() -> tuple[list[Signal], dict[str, object]]:
    return [_sig("x", [0.0, 2.0, 1.0], [10.0, 30.0, 20.0])], {
        "use_unified_timeline": True
    }


def _case_duplicate_ts() -> tuple[list[Signal], dict[str, object]]:
    return [_sig("dup", [0.0, 1.0, 1.0, 2.0], [1.0, 2.0, 3.0, 4.0])], {
        "use_unified_timeline": True
    }


def _case_non_finite() -> tuple[list[Signal], dict[str, object]]:
    return [_sig("e", [0.0, 1.0, 2.0], [np.nan, np.inf, -np.inf])], {
        "use_unified_timeline": True
    }


def _case_len_zero() -> tuple[list[Signal], dict[str, object]]:
    return [_sig("a", [0.0, 1.0], [1.0, 2.0]), _sig("z", [], [])], {
        "use_unified_timeline": True
    }


def _case_ulp() -> tuple[list[Signal], dict[str, object]]:
    slow = [i * 0.1 for i in range(12)]
    fast = [i * 0.01 for i in range(120)]
    return [
        _sig("slow", slow, [float(i) for i in range(12)]),
        _sig("fast", fast, [float(i) for i in range(120)]),
    ], {"use_unified_timeline": True}


def _case_units() -> tuple[list[Signal], dict[str, object]]:
    return [
        _sig("a", [0.0, 1.0], [1.0, 2.0], unit="km/h"),
        _sig("b", [0.0, 1.0], [3.0, 4.0]),
    ], {"unit_row": True}


def _case_formats() -> tuple[list[Signal], dict[str, object]]:
    sigs, opts = _case_union()
    return sigs, {**opts, "delimiter": ";", "decimal": ",", "precision": 3}


def _case_quoted_cells() -> tuple[list[Signal], dict[str, object]]:
    """区切りが数値の書式に現れる形 (delimiter='-')。

    断片はブロック writer が既にクォート済みなので、マージ器は**素の
    delimiter で繋ぐ**。再クォートすると既にクォート済みのセルの二重引用符が
    さらにエスケープされ、囲みが 1 重から 3 重へ膨らむ — ブロック数が変わると
    その出方まで変わるので、分割不変の形でしか捕まらない。
    """
    return [
        _sig("v", [0.0, 1.0], [-1.5, 1e300]),
        _sig("w", [0.0, 1.0], [-2.5, 3.0]),
    ], {"delimiter": "-"}


def _case_many_columns() -> tuple[list[Signal], dict[str, object]]:
    return [
        _sig(f"s{i}", [0.0, 1.0, 2.0], [float(i), float(i) * 2, float(i) * 3])
        for i in range(17)
    ], {}


_CASES = {
    "union": _case_union,
    "range": _case_range,
    "shared": _case_shared,
    "non_monotonic": _case_non_monotonic,
    "duplicate_ts": _case_duplicate_ts,
    "non_finite": _case_non_finite,
    "len_zero": _case_len_zero,
    "ulp": _case_ulp,
    "units": _case_units,
    "formats": _case_formats,
    "quoted_cells": _case_quoted_cells,
    "many_columns": _case_many_columns,
}


def _export(
    tmp_path: Path, name: str, block_cols: int | None, fan_in: int | None
) -> bytes:
    signals, overrides = _CASES[name]()
    out = tmp_path / f"{name}_{block_cols}_{fan_in}.csv"
    table = {s.name: s for s in signals}
    CsvExporter(block_cols=block_cols, merge_fan_in=fan_in).export(
        ExportRequest(
            keys=tuple(s.name for s in signals),
            output_path=out,
            options=CsvExportOptions(**overrides),  # type: ignore[arg-type]
            header_resolver=list,
        ),
        table.get,
    )
    return out.read_bytes()


@pytest.mark.parametrize("name", sorted(_CASES))
@pytest.mark.parametrize(
    ("block_cols", "fan_in"), [(1, 2), (2, 3), (16, 512), (512, 512)]
)
def test_output_bytes_are_independent_of_block_width_and_fan_in(
    tmp_path: Path, name: str, block_cols: int, fan_in: int
) -> None:
    reference = _export(tmp_path, name, None, None)
    assert _export(tmp_path, name, block_cols, fan_in) == reference


def test_reference_output_is_not_trivially_empty(tmp_path: Path) -> None:
    """反 vacuous: 参照側が空バイトなら上の全 parametrize が恒真になる。"""
    for name in _CASES:
        raw = _export(tmp_path, name, None, None)
        assert len(raw) > 0, name
        # ヘッダ + 最低 1 データ行 (「ヘッダだけ」でも上の比較は通ってしまう)。
        assert raw.decode("utf-8-sig").count("\n") >= 2, name


def test_narrow_blocks_really_produce_more_than_one_block(tmp_path: Path) -> None:
    """反 vacuous その 2: ``block_cols=1`` が実際に複数ブロックを作っている。

    実装が ``block_cols`` を無視 (下限 16 で握り潰す等) しても上の等価テストは
    全数緑になる — 分割していないのだから当然同じバイトになる。
    """
    from valisync.core.export import csv_exporter

    seen: list[tuple[tuple[int, int], ...]] = []
    original = csv_exporter.plan_blocks

    def spy(runs, block_cols):  # type: ignore[no-untyped-def]
        blocks = original(runs, block_cols)
        seen.append(blocks)
        return blocks

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(csv_exporter, "plan_blocks", spy)
        _export(tmp_path, "many_columns", 1, 2)
    assert len(seen[0]) == 17, seen  # 17 列 x block_cols=1
