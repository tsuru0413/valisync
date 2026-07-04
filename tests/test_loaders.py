"""Unit tests for CsvLoader and Mdf4Loader (Task 10.1).

Covers the happy path plus the error cases from Requirements 1.4/1.6/1.7/1.8
(MDF4) and 2.5/2.6/2.8 (CSV): missing file, corrupt/invalid format, non-numeric
data, empty file, column-count mismatch.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.loaders.mdf4_loader import Mdf4Loader
from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import LoadCancelled

from .mdf4_helpers import (
    CAN,
    ETHERNET,
    NONE,
    write_mdf4,
    write_mdf4_2d,
    write_mdf4_all_channels_bad,
    write_mdf4_non_finite_ts,
    write_mdf4_non_monotonic,
    write_mdf4_shared_group,
    write_mdf4_structured,
    write_mdf4_value2text,
)


def _fmt(**overrides: object) -> FormatDefinition:
    base: dict[str, object] = {
        "name": "test",
        "delimiter": Delimiter.COMMA,
        "timestamp_column": 0,
        "timestamp_unit": "sec",
        "signal_start_column": 1,
        "signal_end_column": 2,
        "has_header": True,
        "has_unit_row": False,
    }
    base.update(overrides)
    return FormatDefinition(**base)  # type: ignore[arg-type]


def _write_csv(tmp_path: Path, text: str, name: str = "data.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ─── CsvLoader: happy path ────────────────────────────────────────────────────


def test_csv_basic_load_with_header(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,speed,rpm\n0.0,1.0,10.0\n1.0,2.0,20.0\n")
    result = CsvLoader().load(path, _fmt())

    assert result.signal_group is not None
    sg = result.signal_group
    assert sg.file_format == "CSV"
    assert [s.name for s in sg.signals] == ["speed", "rpm"]
    np.testing.assert_array_equal(sg.signals[0].timestamps, [0.0, 1.0])
    np.testing.assert_array_equal(sg.signals[0].values, [1.0, 2.0])
    np.testing.assert_array_equal(sg.signals[1].values, [10.0, 20.0])


def test_csv_no_header_uses_default_names(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "0.0,1.0,10.0\n1.0,2.0,20.0\n")
    result = CsvLoader().load(path, _fmt(has_header=False))

    assert result.signal_group is not None
    assert [s.name for s in result.signal_group.signals] == ["ch_1", "ch_2"]


def test_csv_msec_converted_to_sec(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,v\n0,5.0\n1000,6.0\n2000,7.0\n")
    result = CsvLoader().load(
        path, _fmt(timestamp_unit="msec", signal_start_column=1, signal_end_column=1)
    )

    assert result.signal_group is not None
    np.testing.assert_array_equal(
        result.signal_group.signals[0].timestamps, [0.0, 1.0, 2.0]
    )


def test_csv_unit_row_populates_metadata(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path, "t,speed,rpm\ns,km/h,1/min\n0.0,1.0,10.0\n1.0,2.0,20.0\n"
    )
    result = CsvLoader().load(path, _fmt(has_unit_row=True))

    assert result.signal_group is not None
    assert result.signal_group.signals[0].metadata["unit"] == "km/h"
    assert result.signal_group.signals[1].metadata["unit"] == "1/min"


def test_csv_semicolon_delimiter(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t;v\n0.0;1.0\n1.0;2.0\n")
    result = CsvLoader().load(
        path,
        _fmt(delimiter=Delimiter.SEMICOLON, signal_start_column=1, signal_end_column=1),
    )

    assert result.signal_group is not None
    np.testing.assert_array_equal(result.signal_group.signals[0].values, [1.0, 2.0])


def test_csv_blank_rows_skipped(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,v\n0.0,1.0\n\n1.0,2.0\n\n")
    result = CsvLoader().load(path, _fmt(signal_start_column=1, signal_end_column=1))

    assert result.signal_group is not None
    np.testing.assert_array_equal(result.signal_group.signals[0].timestamps, [0.0, 1.0])


def test_csv_supports_suffix() -> None:
    assert CsvLoader().supports(Path("a.csv")) is True
    assert CsvLoader().supports(Path("a.CSV")) is True
    assert CsvLoader().supports(Path("a.mf4")) is False


# ─── CsvLoader: error cases ───────────────────────────────────────────────────


def test_csv_file_not_found(tmp_path: Path) -> None:
    result = CsvLoader().load(tmp_path / "missing.csv", _fmt())
    assert result.signal_group is None
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].level == "error"


def test_csv_empty_file_with_header(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "")
    result = CsvLoader().load(path, _fmt())
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


def test_csv_non_numeric_timestamp(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,v\nabc,1.0\n")
    result = CsvLoader().load(path, _fmt(signal_start_column=1, signal_end_column=1))
    assert result.signal_group is None
    diag = result.diagnostics[0]
    assert diag.level == "error"
    assert diag.line_number == 2


def test_csv_non_numeric_value(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,v\n0.0,xyz\n")
    result = CsvLoader().load(path, _fmt(signal_start_column=1, signal_end_column=1))
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


def test_csv_too_few_columns(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,a,b\n0.0,1.0\n")
    result = CsvLoader().load(path, _fmt())
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


# ─── CsvLoader: 品質診断 (LD-04/06/08/09) ─────────────────────────────────────


def _load_csv_text(tmp_path: Path, text: str):
    # _fmt(): ts列0・信号列1-2・header あり — 下記テストの "t,a,b" 形状に合わせた
    # 既存ヘルパをそのまま流用(新規ヘルパを増やさない)。
    return CsvLoader().load(_write_csv(tmp_path, text), _fmt())


def test_csv_non_monotonic_is_accepted_with_file_warning(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,a,b\n0.0,1,2\n2.0,3,4\n1.0,5,6\n1.0,7,8\n")
    assert result.signal_group is not None  # 旧実装ではファイル全滅
    assert any(
        d.level == "warning" and "非単調" in d.message for d in result.diagnostics
    )
    assert not result.signal_group.signals[0].is_monotonic  # 生データ無改変


def test_csv_nan_inf_values_accepted_with_count_warning(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,a,b\n0.0,nan,1\n1.0,inf,2\n")
    assert result.signal_group is not None
    a = result.signal_group.signals[0]
    assert np.isnan(a.values[0]) and np.isinf(a.values[1])
    assert any("非有限値 2 個" in d.message for d in result.diagnostics)


def test_csv_duplicate_headers_disambiguated_like_mdf4(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,spd,spd\n0.0,1,2\n1.0,3,4\n")
    assert result.signal_group is not None
    names = [s.name for s in result.signal_group.signals]
    assert names == ["spd[0]", "spd[1]"]  # MDF4 と同一方式
    assert any("重複ヘッダ" in d.message for d in result.diagnostics)


def test_csv_header_only_succeeds_with_warning(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,a,b\n")
    assert result.signal_group is not None
    assert all(len(s.timestamps) == 0 for s in result.signal_group.signals)
    assert any("データ行が 0 行" in d.message for d in result.diagnostics)


def test_csv_non_finite_timestamp_fails_with_error(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,a,b\n0.0,1,2\nnan,3,4\n")
    assert result.signal_group is None
    assert any(
        d.level == "error" and "タイムスタンプ" in d.message for d in result.diagnostics
    )


def test_csv_failure_preserves_accumulated_diagnostics(tmp_path: Path) -> None:
    # 重複ヘッダ warning が発行された後に非有限 ts で失敗するケース:
    # 失敗 LoadResult にも集約済み warning が残ること - 後出し診断の防止
    result = _load_csv_text(tmp_path, "t,spd,spd\n0.0,1,2\nnan,3,4\n")
    assert result.signal_group is None
    assert any(
        d.level == "error" and "タイムスタンプ" in d.message for d in result.diagnostics
    )
    assert any(
        "重複ヘッダ" in d.message for d in result.diagnostics
    )  # fix 前は消えていた


# ─── CsvLoader: cooperative cancel (FB-04 hard side) ──────────────────────────


def test_csv_loader_cancel_checked_per_1000_rows(tmp_path: Path) -> None:
    # 2500 データ行 → チェックは概ね 1000 行ごと(毎行呼ばれないこと)を検証
    fmt = _fmt(signal_start_column=1, signal_end_column=1)
    path = tmp_path / "big.csv"
    rows = "\n".join(f"{i * 0.001},{i}" for i in range(2500))
    path.write_text("t,v\n" + rows + "\n", encoding="utf-8")

    calls: list[int] = []

    def cancel() -> bool:
        calls.append(1)
        return len(calls) >= 2  # 2回目のチェックで中断

    with pytest.raises(LoadCancelled):
        CsvLoader().load(path, fmt, cancel=cancel)
    assert 2 <= len(calls) <= 5  # 行数比例で毎行呼ばれていないこと


# ─── Mdf4Loader: happy path ───────────────────────────────────────────────────


def test_mdf4_basic_load_bus_type_detection(tmp_path: Path) -> None:
    ts = [0.0, 0.1, 0.2]
    path = write_mdf4(
        tmp_path / "x.mf4",
        [
            {
                "name": "speed",
                "timestamps": ts,
                "values": [1.0, 2.0, 3.0],
                "bus_type": CAN,
                "unit": "km/h",
            },
            {
                "name": "rpm",
                "timestamps": ts,
                "values": [4.0, 5.0, 6.0],
                "bus_type": NONE,
                "source_name": "XCP_daq",
            },
            {
                "name": "load",
                "timestamps": ts,
                "values": [7.0, 8.0, 9.0],
                "bus_type": ETHERNET,
            },
        ],
    )
    result = Mdf4Loader().load(path)

    assert result.signal_group is not None
    by_name = {s.name: s for s in result.signal_group.signals}
    assert by_name["speed"].bus_type == "CAN"
    assert by_name["rpm"].bus_type == "XCP"
    assert by_name["load"].bus_type == "Ethernet"
    assert by_name["speed"].metadata["unit"] == "km/h"
    np.testing.assert_array_equal(by_name["speed"].values, [1.0, 2.0, 3.0])


def test_mdf4_duplicate_names_disambiguated(tmp_path: Path) -> None:
    ts = [0.0, 1.0]
    path = write_mdf4(
        tmp_path / "dup.mf4",
        [
            {"name": "sig", "timestamps": ts, "values": [1.0, 2.0], "bus_type": CAN},
            {"name": "sig", "timestamps": ts, "values": [3.0, 4.0], "bus_type": CAN},
        ],
    )
    result = Mdf4Loader().load(path)

    assert result.signal_group is not None
    names = {s.name for s in result.signal_group.signals}
    assert names == {"sig[0]", "sig[1]"}


def test_mdf4_multiple_channel_groups_all_loaded(tmp_path: Path) -> None:
    path = write_mdf4(
        tmp_path / "multi.mf4",
        [{"name": f"ch{i}", "bus_type": CAN} for i in range(5)],
    )
    result = Mdf4Loader().load(path)
    assert result.signal_group is not None
    assert len(result.signal_group.signals) == 5


def test_mdf4_supports_suffix() -> None:
    assert Mdf4Loader().supports(Path("a.mf4")) is True
    assert Mdf4Loader().supports(Path("a.MF4")) is True
    assert Mdf4Loader().supports(Path("a.csv")) is False


# ─── Mdf4Loader: error cases ──────────────────────────────────────────────────


def test_mdf4_file_not_found(tmp_path: Path) -> None:
    result = Mdf4Loader().load(tmp_path / "missing.mf4")
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


def test_mdf4_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.mf4"
    path.write_bytes(b"this is not a valid MDF4 file" * 10)
    result = Mdf4Loader().load(path)
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


# ─── Mdf4Loader: 非単調/0ch 診断 (LD-03/05) ───────────────────────────────────


def test_mdf4_non_monotonic_channel_is_accepted_with_warning(tmp_path: Path) -> None:
    path = write_mdf4_non_monotonic(tmp_path)
    result = Mdf4Loader().load(path)
    assert result.signal_group is not None
    names = [s.name for s in result.signal_group.signals]
    assert "messy" in names  # 旧実装では skip されていた
    warnings = [d for d in result.diagnostics if d.level == "warning"]
    assert any("非単調" in d.message or "重複" in d.message for d in warnings)
    messy = next(s for s in result.signal_group.signals if s.name == "messy")
    assert not messy.is_monotonic  # 生データ無改変で受け入れ


def test_mdf4_non_finite_ts_channel_is_skipped_with_error(tmp_path: Path) -> None:
    """A NaN-timestamp channel is skipped with an error diagnostic (spec §7);
    the sibling clean channel still loads."""
    path = write_mdf4_non_finite_ts(tmp_path)
    result = Mdf4Loader().load(path)
    assert result.signal_group is not None
    names = [s.name for s in result.signal_group.signals]
    assert "broken" not in names
    assert "clean" in names
    errors = [d for d in result.diagnostics if d.level == "error"]
    assert any("非有限" in d.message and d.signal_name == "broken" for d in errors)


def test_mdf4_zero_channels_emits_warning(tmp_path: Path) -> None:
    path = write_mdf4_all_channels_bad(tmp_path)
    result = Mdf4Loader().load(path)
    assert result.signal_group is not None
    assert len(result.signal_group.signals) == 0
    assert any("0 本" in d.message for d in result.diagnostics)


# ─── Mdf4Loader: cooperative cancel (FB-04 hard side) ─────────────────────────


def test_mdf4_loader_cancel_raises(tmp_path: Path) -> None:
    path = write_mdf4(
        tmp_path / "x.mf4",
        [
            {
                "name": "speed",
                "timestamps": [0.0, 0.1],
                "values": [1.0, 2.0],
                "bus_type": CAN,
            }
        ],
    )
    with pytest.raises(LoadCancelled):
        Mdf4Loader().load(path, cancel=lambda: True)


# ─── Mdf4Loader: select() ベース読み取りパス (LD-13/LD-10, 第3弾 Task 2) ──────


def test_value2text_channel_survives_as_raw(tmp_path: Path) -> None:
    """LD-13: value2text 付きチャンネルが生値で生存する (現行は消滅=RED)."""
    path = write_mdf4_value2text(tmp_path)
    result = Mdf4Loader().load(path)
    names = {s.name for s in result.signal_group.signals}
    assert "TurnSig" in names
    turn = next(s for s in result.signal_group.signals if s.name == "TurnSig")
    assert np.array_equal(turn.values, [0.0, 1.0, 2.0, 1.0])
    assert not any(
        "non-numeric" in d.message and "TurnSig" in d.message
        for d in result.diagnostics
    )


def test_value_labels_extracted_to_metadata(tmp_path: Path) -> None:
    """LD-07: TABX 変換表が metadata['value_labels'] に構造化保持される."""
    result = Mdf4Loader().load(write_mdf4_value2text(tmp_path))
    turn = next(s for s in result.signal_group.signals if s.name == "TurnSig")
    assert turn.metadata.get("value_labels") == {0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"}
    clean = next(s for s in result.signal_group.signals if s.name == "Clean")
    assert "value_labels" not in clean.metadata


def test_same_group_signals_share_master(tmp_path: Path) -> None:
    """LD-10: 同一グループの信号はマスタ時刻軸を共有し read-only (現行は複製=RED)."""
    path = write_mdf4_shared_group(tmp_path)
    result = Mdf4Loader().load(path)
    a = next(s for s in result.signal_group.signals if s.name == "A")
    b = next(s for s in result.signal_group.signals if s.name == "B")
    assert np.shares_memory(a.timestamps, b.timestamps)
    assert not a.timestamps.flags.writeable
    assert np.array_equal(a.timestamps, b.timestamps)


# ─── Mdf4Loader: virtual_groups 走査 (Task 2 レビュー critical) ───────────────


def test_remote_master_style_virtual_groups_do_not_kill_load(tmp_path: Path) -> None:
    """v4.20 remote-master 相当 (follower gi が virtual_groups に無い) でも全滅しない.

    asammdf は v4.20+ の remote-master/column-storage 読込時、follower 物理
    グループを ``virtual_groups`` のキーに載せない (マスタ側 gi に統合される)。
    グループ走査を物理グループ数 (``range(len(mdf.groups))``) で回すと、
    follower の gi で ``included_channels(gi)`` が KeyError → 外側の broad
    except に飲まれ、正常なグループも含めファイル全体が signal_group=None に
    なる回帰を防止する (Task 2 レビュー critical)。ここでは実ファイルを
    remote-master 形式で書き出す代わりに、通常の 2 グループファイルに対して
    ``MDF.__init__`` 後の ``virtual_groups``/``virtual_groups_map`` を
    remote-master 相当の形へパッチし、同じ「follower gi が virtual_groups の
    キーに無い」状態を再現する。
    """
    from unittest.mock import patch

    from asammdf import MDF as _MDF

    path = write_mdf4(
        tmp_path / "remote_master_like.mf4",
        [
            {"name": "A", "timestamps": [0.0, 1.0], "values": [1.0, 2.0]},
            {"name": "B", "timestamps": [0.0, 1.0], "values": [3.0, 4.0]},
        ],
    )

    real_init = _MDF.__init__

    def patched_init(self: _MDF, *args: object, **kwargs: object) -> None:
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]
        if 1 in self.virtual_groups:
            vg0 = self.virtual_groups[0]
            vg0.groups = sorted({*vg0.groups, 1})
            self.virtual_groups_map[1] = 0
            del self.virtual_groups[1]

    with patch.object(_MDF, "__init__", patched_init):
        result = Mdf4Loader().load(path)

    assert result.signal_group is not None
    names = {s.name for s in result.signal_group.signals}
    assert {"A", "B"} <= names
    assert not any(d.level == "error" for d in result.diagnostics)


# ─── mdf4_helpers: 新規ヘルパの roundtrip 前提 (第3弾土台) ────────────────────


def test_helper_value2text_roundtrip(tmp_path: Path) -> None:
    from asammdf import MDF

    path = write_mdf4_value2text(tmp_path)
    with MDF(str(path)) as mdf:
        # 既定 (raw=False) は変換適用済みでテキスト化され conversion は None になる
        # (asammdf の get() 実測で確認済み) — raw=True で生値+変換テーブルを固定する。
        sig = mdf.get("TurnSig", raw=True)
        assert sig.conversion is not None
        np.testing.assert_array_equal(sig.samples, [0, 1, 2, 1])


def test_helper_2d_roundtrip(tmp_path: Path) -> None:
    from asammdf import MDF

    path = write_mdf4_2d(tmp_path)
    with MDF(str(path)) as mdf:
        sig = mdf.get("Mat")
        assert sig.samples.ndim == 2 and sig.samples.shape[1] == 3


# ─── Mdf4Loader: 多次元/構造化チャンネルの要素展開 (LD-12, 第3弾 Task 3) ──────


def test_2d_channel_explodes_into_columns(tmp_path: Path) -> None:
    """LD-12: 2D (Nx3) が Mat[0..2] の 1D 信号群へ展開され共有マスタを参照する."""
    result = Mdf4Loader().load(write_mdf4_2d(tmp_path))
    names = {s.name for s in result.signal_group.signals}
    assert {"Mat[0]", "Mat[1]", "Mat[2]", "Clean"} <= names
    m0 = next(s for s in result.signal_group.signals if s.name == "Mat[0]")
    m2 = next(s for s in result.signal_group.signals if s.name == "Mat[2]")
    assert np.array_equal(m0.values, [0.0, 10.0, 20.0, 30.0])
    assert np.array_equal(m2.values, [2.0, 12.0, 22.0, 32.0])
    assert np.shares_memory(m0.timestamps, m2.timestamps)
    infos = [d for d in result.diagnostics if d.level == "info" and "Mat" in d.message]
    assert len(infos) == 1 and "3 本に展開" in infos[0].message
    assert not any(
        "skipped" in d.message and "Mat" in d.message for d in result.diagnostics
    )


def test_structured_channel_fields_visible(tmp_path: Path) -> None:
    """LD-12: 構造化 (x,y) がフィールド単位で見える (Pt.x / Pt.y ないし成分ch)."""
    result = Mdf4Loader().load(write_mdf4_structured(tmp_path))
    names = {s.name for s in result.signal_group.signals}
    # 実装時確認 (Task 1 Task2-Step2 と本タスク Step1 で確定): select() 結果には
    # 構造化チャンネルの親 (Pt) のみが届き成分 (x/y) は included_channels から
    # 除外されている — フィールド展開は Pt.x/Pt.y として現れる。
    xs = [
        s
        for s in result.signal_group.signals
        if np.array_equal(s.values, [1.0, 2.0, 3.0])
    ]
    assert xs, f"x 成分が信号として見えない: {sorted(names)}"
    assert not any(d.level == "error" for d in result.diagnostics)


def test_explode_samples_subarray_field_one_level() -> None:
    """構造化フィールドが (N,k) サブ配列のとき Name.field[i] に1段展開される."""
    from valisync.core.loaders.mdf4_loader import _explode_samples

    rec = np.zeros(3, dtype=[("mat", "<f8", (2,)), ("s", "<f8")])
    rec["mat"] = [[1, 2], [3, 4], [5, 6]]
    rec["s"] = [7, 8, 9]
    diags: list = []
    pairs = _explode_samples("Obj", rec, diags)
    names = [n for n, _ in pairs]
    assert names == ["Obj.mat[0]", "Obj.mat[1]", "Obj.s"]
    assert np.array_equal(dict(pairs)["Obj.mat[1]"], [2.0, 4.0, 6.0])


def test_explode_samples_over_nested_field_skipped_with_reason() -> None:
    """ndim>2 のネストフィールドは理由の読める警告で skip・他フィールドは展開継続."""
    from valisync.core.loaders.mdf4_loader import _explode_samples

    rec = np.zeros(2, dtype=[("deep", "<f8", (2, 2)), ("s", "<f8")])
    diags: list = []
    pairs = _explode_samples("Obj", rec, diags)
    assert [n for n, _ in pairs] == ["Obj.s"]
    assert any("nested samples, skipped" in d.message for d in diags)
