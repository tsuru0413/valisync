"""出力仕様 4 点是正の契約 (E-4b Task 1・spec §5.1・ユーザー決定 B1)。

ゴールデン (Task 2) はこの是正**後**のバイトを凍結する。ゴールデンは
「今こう出ている」を丸ごと固めるだけで**意図を語らない**ので、
「なぜ空セルなのか」「なぜ最小クォートなのか」を語る執行点がここに要る。
ゴールデンだけにすると、将来 nan を復活させた誰かが「ゴールデンを
supersede すればよい」で通せてしまう。

`CsvLoader` 側 (空セル受理) を同じファイルに置くのは、**対で 1 つの契約**
だから — エクスポータが空セルを書き、ローダーが空セルを読む。片方だけ直すと
自製品の出力を自製品が読めない状態が残る (spec §5.1-1)。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from valisync.core.export.csv_exporter import CsvExporter, CsvExportOptions
from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.models import Delimiter, FormatDefinition, Signal

_BOM = b"\xef\xbb\xbf"


def _sig(
    name: str,
    ts: list[float],
    vs: list[float],
    metadata: dict[str, object] | None = None,
) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata=dict(metadata) if metadata is not None else {},
    )


def _text(path: Path) -> str:
    """出力を**BOM を剥がして**読む (本増分以降の正しい読み口)。"""
    return path.read_text(encoding="utf-8-sig")


# ─── 1. 非有限値は空セル (B1・spec §5.1-1) ────────────────────────────────────


def test_nan_value_becomes_empty_cell_shared_timeline(tmp_path: Path) -> None:
    """裸の ``nan`` は Excel で文字列・pandas で NaN・CANape で不明の三者三様。

    欠測 (統合タイムラインでサンプルが無い) と**同じ**空セル表現へ揃える。
    """
    s = _sig("x", [0.0, 1.0], [1.5, float("nan")])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out).splitlines() == ["timestamp,x", "0.0,1.5", "1.0,"]


def test_positive_and_negative_inf_become_empty_cells(tmp_path: Path) -> None:
    """±inf も NaN と同じ扱い (spec §5.1-1 [I-5/I-6])。

    ``finite_view`` は NaN と inf を等価に「非有限」と扱う。片方だけ空セルに
    すると、その非対称を**ゴールデンが恒久化**してしまう。
    """
    s = _sig("x", [0.0, 1.0, 2.0], [float("inf"), float("-inf"), 3.0])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out).splitlines() == ["timestamp,x", "0.0,", "1.0,", "2.0,3.0"]


def test_nan_is_empty_in_the_precision_branch_too(tmp_path: Path) -> None:
    """precision 指定時の ``f"{nan:.3f}"`` -> ``"nan"`` 漏れ (spec §5.1-1 [I13])。

    repr 側だけ直すと、GUI で「小数点以下の桁数」を指定した瞬間に nan が復活する。
    """
    s = _sig("x", [0.0, 1.0], [1.5, float("nan")])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(precision=3))
    assert _text(out).splitlines() == ["timestamp,x", "0.000,1.500", "1.000,"]


def test_nonfinite_is_indistinguishable_from_a_missing_sample(tmp_path: Path) -> None:
    """統合タイムラインで「欠測」と「NaN」が**同一バイト**になること。

    これが B1 の決定そのもの。区別できる形 (例: ``nan`` を残す/``NA`` を書く) に
    戻すと、この assert が両者を見分けてしまい RED になる。
    """
    a = _sig("a", [0.0, 1.0], [10.0, float("nan")])  # t=1.0 は「値はあるが NaN」
    b = _sig("b", [0.0], [20.0])  # t=1.0 は「サンプルが無い」
    out = tmp_path / "d.csv"
    CsvExporter().export([a, b], out, use_unified_timeline=True)
    rows = _text(out).splitlines()
    assert rows == ["timestamp,a,b", "0.0,10.0,20.0", "1.0,,"]


# ─── 2. UTF-8 BOM (spec §5.1-2) ───────────────────────────────────────────────


def test_output_starts_with_a_single_utf8_bom(tmp_path: Path) -> None:
    """BOM は**先頭 1 回だけ**。

    ``_atomic_write`` は ``write`` を 2 回呼ぶ (本文 + 末尾改行)。utf-8-sig の
    IncrementalEncoder が first フラグを持つので 1 回で済むが、行ごとに
    ``open`` し直す実装へ変えると各行頭に BOM が入る — ``count`` で塞ぐ。
    """
    s = _sig("x", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    raw = out.read_bytes()
    assert raw.startswith(_BOM)
    assert raw.count(_BOM) == 1
    assert raw == _BOM + b"timestamp,x\n0.0,1.5\n"


def test_japanese_header_survives_as_utf8_after_the_bom(tmp_path: Path) -> None:
    """BOM を入れる理由そのもの: ヘッダは日本語/ファイルキー併記を含みうる。"""
    s = _sig("mf4_1::車速", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(header_names=("車速",)))
    raw = out.read_bytes()
    assert raw == _BOM + "timestamp,車速\n0.0,1.5\n".encode()


# ─── 3. RFC 4180 最小クォート (spec §5.1-3 [M-2]) ─────────────────────────────


def test_delimiter_in_header_name_is_quoted(tmp_path: Path) -> None:
    """信号名こそ区切り文字混入の主経路 — ヘッダ行にも適用する [M-2]。"""
    s = _sig("a,b", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out).splitlines() == ['timestamp,"a,b"', "0.0,1.5"]


def test_double_quote_in_name_is_doubled_inside_quotes(tmp_path: Path) -> None:
    s = _sig('say "hi"', [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out).splitlines()[0] == 'timestamp,"say ""hi"""'


def test_newline_in_name_is_quoted_and_stays_a_single_logical_row(
    tmp_path: Path,
) -> None:
    """改行入りの名前は囲まないと**列構造が壊れる** (行が 2 行に割れる)。"""
    s = _sig("line\nbreak", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out) == 'timestamp,"line\nbreak"\n0.0,1.5\n'


def test_delimiter_in_unit_is_quoted_in_the_unit_row(tmp_path: Path) -> None:
    """単位行にも適用する [M-2] — ``m,s`` のような単位は実在する。"""
    s = _sig("x", [0.0], [1.5], metadata={"unit": "m,s"})
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(unit_row=True))
    assert _text(out).splitlines() == ["timestamp,x", 's,"m,s"', "0.0,1.5"]


def test_quoting_is_minimal_not_unconditional(tmp_path: Path) -> None:
    """**最小**であることが load-bearing。

    常時クォートに変えると全セルが変わり、Task 2 のゴールデン 11 本が全滅する。
    「クォートを入れた」だけでは足りず「入れていないセルはバイト不変」まで縛る。
    """
    s = _sig("x", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out) == "timestamp,x\n0.0,1.5\n"  # 引用符ゼロ


def test_quote_decision_uses_the_configured_delimiter_not_a_literal_comma(
    tmp_path: Path,
) -> None:
    """``delimiter=";"`` + ``decimal=","`` のセル ``0,5`` はクォートしない。

    ``","`` を直書きした実装だと ``"0,5";"1,5"`` になり、既存の
    ``test_comma_decimal_with_semicolon_delimiter`` が RED になる。ここは
    その既存 pin を**新設側からも**明示するミラー。
    """
    s = _sig("speed", [0.5], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(delimiter=";", decimal=","))
    assert _text(out).splitlines() == ["timestamp;speed", "0,5;1,5"]


def test_empty_cell_is_not_quoted(tmp_path: Path) -> None:
    """空セルは区切り/引用符/改行のいずれも含まないのでクォート対象外。

    ここが崩れると欠測セルが全部 ``""`` になり、prod では出力の 66% が膨らむ。
    """
    a = _sig("a", [0.0, 1.0], [10.0, 11.0])
    b = _sig("b", [0.0], [20.0])
    out = tmp_path / "d.csv"
    CsvExporter().export([a, b], out, use_unified_timeline=True)
    assert _text(out).splitlines()[-1] == "1.0,11.0,"


# ─── 前提: unit=None (spec §9-6) ──────────────────────────────────────────────


def test_unit_none_is_written_as_an_empty_cell(tmp_path: Path) -> None:
    """production の mdf_loader は truthy ガードで None を載せない
    (mdf_loader.py:159-161・spec §13-2) が、手組み metadata (Derived・テスト・
    将来のローダー) は None を持ちうる。現状は ``join`` が TypeError を投げる。

    Task 2 のゴールデンが unit=None を軸に持つ (spec §9-6 が T-G へ defer した点)
    ので、ここで「空セルへ畳む」と決める。
    """
    s = _sig("x", [0.0], [1.5], metadata={"unit": None})
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(unit_row=True))
    assert _text(out).splitlines() == ["timestamp,x", "s,", "0.0,1.5"]


# ─── 対の修正: CsvLoader が空セルを NaN として受理する (spec §5.1-1) ───────────


def _fmt_def(n_signals: int) -> FormatDefinition:
    return FormatDefinition(
        name="rt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=n_signals,
        has_header=True,
    )


def test_loader_accepts_empty_signal_cell_as_nan(tmp_path: Path) -> None:
    """空セルは**欠測**であってエラーではない。

    現状は ``float("")`` の ValueError で LoadResult ごと失敗し、
    「自製品の統合タイムライン出力 (prod ではセルの 66% が空) を自製品が
    読めない」状態になっている。
    """
    src = tmp_path / "in.csv"
    src.write_text("t,a,b\n0.0,1.0,\n1.0,,2.0\n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(2))
    assert result.signal_group is not None, [d.message for d in result.diagnostics]
    a, b = result.signal_group.signals
    assert a.values[0] == 1.0 and math.isnan(float(a.values[1]))
    assert math.isnan(float(b.values[0])) and b.values[1] == 2.0


def test_loader_accepts_whitespace_only_cell_as_nan(tmp_path: Path) -> None:
    """他ツール由来の ``, ,`` も同じ意図 (欠測) なので同じ扱いにする。"""
    src = tmp_path / "in.csv"
    src.write_text("t,a\n0.0, \n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(1))
    assert result.signal_group is not None
    assert math.isnan(float(result.signal_group.signals[0].values[0]))


def test_loader_emits_no_diagnostic_for_empty_cells(tmp_path: Path) -> None:
    """空セルに警告を出さない。

    空セルは valisync 自身の出力における欠測の**正規表現**であり、prod の
    再取込では全信号に 1 件ずつ warning が出てノイズになる。値の破損を
    表明する ``'nan'``/``'inf'`` の**文字列**は LD-06 の警告を維持する
    (次のテストが反 vacuous 側)。
    """
    src = tmp_path / "in.csv"
    src.write_text("t,a\n0.0,\n1.0,\n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(1))
    assert result.signal_group is not None
    assert not [d for d in result.diagnostics if "非有限値" in d.message]


def test_loader_still_warns_for_literal_nan_and_inf_strings(tmp_path: Path) -> None:
    """反 vacuous: 空セルを黙らせても LD-06 の警告経路は生きている。"""
    src = tmp_path / "in.csv"
    src.write_text("t,a\n0.0,nan\n1.0,inf\n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(1))
    assert result.signal_group is not None
    assert any("非有限値 2 個" in d.message for d in result.diagnostics)


def test_loader_still_rejects_an_empty_timestamp(tmp_path: Path) -> None:
    """時刻列は対象外 — 時刻の欠測は時間軸そのものの破損。

    値セルの受理を ``row`` 全体へ広げると、時刻が空の行が t=NaN で通り
    ``Signal.__init__`` の非有限時刻拒否 (signal.py:80-82) まで潜る。
    """
    src = tmp_path / "in.csv"
    src.write_text("t,a\n,1.0\n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(1))
    assert result.signal_group is None
    assert any("タイムスタンプ" in d.message for d in result.diagnostics)


def test_export_then_reload_roundtrips_missing_cells_as_nan(tmp_path: Path) -> None:
    """自製品の出力を自製品が読み戻せる (spec §9-3 に valisync 自身を加えた根拠)。

    BOM (エクスポータ) と utf-8-sig 読み (csv_loader.py:46) の噛み合わせも
    ここで同時に効いている — BOM を剥がし損ねるとヘッダ名 ``timestamp`` が
    ``\\ufefftimestamp`` になり列検出がずれる。
    """
    a = _sig("a", [0.0, 1.0], [10.0, float("nan")])
    b = _sig("b", [0.0], [20.0])
    out = tmp_path / "out.csv"
    CsvExporter().export([a, b], out, use_unified_timeline=True)

    result = CsvLoader().load(out, _fmt_def(2))
    assert result.signal_group is not None, [d.message for d in result.diagnostics]
    la, lb = result.signal_group.signals
    assert la.name == "a" and lb.name == "b"
    np.testing.assert_array_equal(la.timestamps, np.array([0.0, 1.0]))
    assert la.values[0] == 10.0 and math.isnan(float(la.values[1]))
    assert lb.values[0] == 20.0 and math.isnan(float(lb.values[1]))
