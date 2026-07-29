"""2-D 親 (配列/構造体チャンネル本体) を CSV に書き出させない core の拒否 (E-3 C-d)。

拒否点を core に置くのは、GUI ダイアログを通らない直呼び (scripted / realgui の
``session.export_csv``) まで守れる唯一の層だから。素の numpy TypeError
("float() argument must be a string or a real number, not 'list'") は
ExportWorker -> QMessageBox にそのまま出て、ユーザーには何を選び直せばよいか
分からない。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.export import CsvExporter
from valisync.core.models import Signal
from valisync.core.session import Session


def _2d_signal(name: str = "Mat") -> Signal:
    ts = np.arange(4.0, dtype=np.float64)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.arange(12, dtype=np.uint8).reshape(4, 3),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={},
    )


def _scalar_signal(name: str = "Plain") -> Signal:
    # 時間軸は _2d_signal と **同一**にする。ずらすと共有タイムライン検証の
    # ValueError が先に出て test_exporter_writes_nothing_when_rejected が
    # 「拒否できていないのに緑」になる (実測: 揃える前は修正なしでも pass)。
    ts = np.arange(4.0, dtype=np.float64)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.array([1.0, 2.0, 3.0, 4.0]),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )


def test_exporter_rejects_multi_column_values_shared_timeline(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="配列チャンネル"):
        CsvExporter().export([_2d_signal()], tmp_path / "out.csv")


def test_exporter_rejects_multi_column_values_unified_timeline(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="配列チャンネル"):
        CsvExporter().export(
            [_2d_signal()], tmp_path / "out.csv", use_unified_timeline=True
        )


def test_exporter_writes_nothing_when_rejected(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    with pytest.raises(ValueError):
        CsvExporter().export([_2d_signal(), _scalar_signal()], out)
    assert not out.exists()


def test_session_rejects_container_channel_without_reading_values(
    tmp_path: Path,
) -> None:
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    parent = next(s for s in session.group_signals(key) if s.name == f"{key}::Mat")

    with pytest.raises(ValueError, match=r"Mat\[0\]"):
        session.export_csv([parent], tmp_path / "out.csv")

    # 判定に sig.values.ndim を使うとここが materialized になる
    # (prod では 1 本 96 MB のチャンネル全読み = 遅延展開の利得を捨てる)。
    assert parent._values_source.is_materialized is False


def test_session_exports_expanded_column(tmp_path: Path) -> None:
    """過剰拒否の pin: 列そのものは今までどおり書き出せる。"""
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    col = session.resolve_signal(f"{key}::Mat[0]")
    assert col is not None

    out = tmp_path / "col.csv"
    session.export_csv([col], out)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == f"timestamp,{key}::Mat[0]"
    assert len(lines) == 5  # ヘッダ + 4 行


def test_session_export_allows_signal_without_loaded_group(tmp_path: Path) -> None:
    """名前空間なし (Derived) は所属グループを引けない = 列構造を知りようがない。
    判定不能を拒否に倒すと Derived_Signal のエクスポートが全滅する。"""
    session = Session()
    out = tmp_path / "derived.csv"
    session.export_csv([_scalar_signal()], out)
    assert out.read_text(encoding="utf-8").splitlines()[0] == "timestamp,Plain"
