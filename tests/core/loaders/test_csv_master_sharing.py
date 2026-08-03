"""CSV グループの master が列間で共有されること (E-4b Task 5・spec §5.4 [I-9])。

``csv_loader`` が writeable な timestamps を渡していた間、``Signal.__init__``
(signal.py:83) は信号ごとに master をコピーしていた。結果、CSV では
``union_timeline`` の identity dedup が**構造的に 1 件も効かない** (畳めるはずの
n_signals 本がそのまま concat される)。read-only 化が dedup の前提条件。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.timeline import union_timeline
from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.models import Delimiter, FormatDefinition, Signal


def _fmt(**overrides: object) -> FormatDefinition:
    base: dict[str, object] = {
        "name": "test",
        "delimiter": Delimiter.COMMA,
        "timestamp_column": 0,
        "timestamp_unit": "sec",
        "signal_start_column": 1,
        "signal_end_column": 3,
        "has_header": True,
        "has_unit_row": False,
    }
    base.update(overrides)
    return FormatDefinition(**base)  # type: ignore[arg-type]


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "data.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_csv_group_signals_share_one_master_object(tmp_path: Path) -> None:
    path = _write(tmp_path, "t,a,b,c\n0.0,1,2,3\n1.0,4,5,6\n")
    group = CsvLoader().load(path, _fmt()).signal_group
    assert group is not None
    masters = [s.timestamps for s in group.signals]
    assert len(masters) == 3
    assert all(m is masters[0] for m in masters), "列ごとに master がコピーされている"


def test_signal_shares_master_only_when_the_input_is_read_only() -> None:
    """共有の**機構**を pin する (signal.py:83 — read-only 入力だけが共有される)。

    元の計画は「``group.signals[0].timestamps.flags.writeable is False``」で
    loader の凍結を検出するつもりだったが、これは**恒真**だった:
    ``Signal.__init__`` は writeable な入力を copy してから凍結するので、loader の
    1 行が無くても各 Signal の ``timestamps`` は必ず read-only になる (実測:
    loader 未修正の状態で緑のまま通った)。loader 側の凍結が観測できるのは
    **identity の共有だけ**なので、read-only 化と共有を繋ぐ機構はここで直接 pin する
    — ``Signal.__init__`` の共有規則が変わると、loader の 1 行は無症状で効果を失う。
    """
    ts = np.array([0.0, 1.0], dtype=np.float64)
    writeable_case = Signal(
        name="w",
        timestamps=ts,
        values=np.array([1.0, 2.0]),
        file_format="test",
        bus_type="",
        source_file="",
    )
    assert writeable_case.timestamps is not ts, "writeable 入力はコピーされる"

    ts.flags.writeable = False
    read_only_case = Signal(
        name="r",
        timestamps=ts,
        values=np.array([1.0, 2.0]),
        file_format="test",
        bus_type="",
        source_file="",
    )
    assert read_only_case.timestamps is ts, "read-only 入力は共有される"


def test_csv_master_sharing_makes_union_dedup_effective(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """loader の 1 行と union の dedup を繋ぐ紐 (どちらが欠けても RED)。"""
    path = _write(tmp_path, "t,a,b,c\n0.0,1,2,3\n1.0,4,5,6\n2.0,7,8,9\n")
    group = CsvLoader().load(path, _fmt()).signal_group
    assert group is not None

    sizes: list[int] = []
    real = np.concatenate

    def spy(arrays, *args, **kwargs):  # type: ignore[no-untyped-def]
        sizes.append(sum(len(a) for a in arrays))
        return real(arrays, *args, **kwargs)

    monkeypatch.setattr(np, "concatenate", spy)
    union_timeline([s.timestamps for s in group.signals])
    assert sizes == [3], "3 列ぶん (9 要素) concat している = master が共有されていない"


def test_csv_header_only_file_still_loads_with_read_only_master(
    tmp_path: Path,
) -> None:
    """LD-09 (データ行 0)。長さ 0 配列でも flags 操作が通ることの pin。

    判定は **identity の共有**で行う: ``flags.writeable is False`` は
    ``Signal.__init__`` が必ず満たすので loader の凍結を検出できない
    (``test_signal_shares_master_only_when_the_input_is_read_only`` 参照)。
    """
    result = CsvLoader().load(_write(tmp_path, "t,a,b,c\n"), _fmt())
    assert result.signal_group is not None
    masters = [s.timestamps for s in result.signal_group.signals]
    assert len(masters[0]) == 0
    assert all(m is masters[0] for m in masters)
