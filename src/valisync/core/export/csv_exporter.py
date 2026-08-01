from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from valisync.core.models import Signal

#: Header name for the leading timestamp column (Req 7.3).
_TIMESTAMP_HEADER = "timestamp"
#: 単位行を出力するときのタイムスタンプ列の単位(コアは秒に正規化済み)。
_TIMESTAMP_UNIT = "s"

#: 配列チャンネルの親を書き出そうとしたときのエラー文言。core に置くのは、GUI
#: ダイアログを通らない直呼び (scripted / realgui の Session.export_csv) まで守れる
#: 唯一の層だから (E-3 C-d)。gui.strings へは置かない — 本モジュールは core であり
#: gui を import しない (header_names の注記と同じ理由)。
EXPORT_MULTI_COLUMN_VALUES_ERROR_TMPL = (
    "信号 '{name}' は 1 時刻につき複数の値を持つ配列チャンネルのため CSV に"
    "書き出せません。展開された列を選択してください。"
)
EXPORT_CONTAINER_CHANNEL_ERROR_TMPL = (
    "信号 '{name}' は配列/構造体チャンネル本体のため CSV に書き出せません。"
    "展開された列 (例: '{example}') を選択してください。"
)


@dataclass(frozen=True)
class CsvExportOptions:
    """CSV 書式オプション。既定は現行挙動(round-trip・カンマ・単位行なし)。"""

    delimiter: str = ","
    decimal: str = "."
    unit_row: bool = False
    precision: int | None = None
    #: 表示用ヘッダ名 (signals と同順・任意)。None は従来どおり raw signal.name を
    #: 書く (無回帰)。GUI 側 (ExportCsvDialog) が display_names で計算して渡す —
    #: 本モジュールは core であり gui.display_names を import しない (層違反回避、
    #: E-0 spec §1.2)。長さは signals と一致すること (export() 側では未検証 —
    #: 呼び出し元の契約)。
    header_names: tuple[str, ...] | None = None
    #: 出力する時刻範囲 (生のタイムスタンプ座標・閉区間 [time_start, time_end])。
    #: None は無制限。R14 時間オフセットは適用しない — エクスポートは常に base
    #: 信号の生タイムスタンプ座標で書き出す (F-0 spec §2.1)。既定 None は既存
    #: 構築コードの後方互換のため末尾に追加 (F-0 spec §2.2)。
    time_start: float | None = None
    time_end: float | None = None

    def __post_init__(self) -> None:
        # 空区切り/空小数点は CSV 構造を壊す(列が融合する)ため核でも拒否。
        # ダイアログは固定候補コンボからしか到達しないが、公開 API としての
        # CsvExportOptions は直接構築されうるので堅牢化する。
        if not self.delimiter or not self.decimal:
            raise ValueError("区切り文字と小数点記号は空にできません")
        # 区切りと小数点が同一だと CSV が曖昧になる(ダイアログでも防ぐが核でも拒否)。
        if self.delimiter == self.decimal:
            raise ValueError("区切り文字と小数点記号に同じ文字は使えません")
        # `_quote` は `"` を RFC 4180 最小クォートの制御文字として新たに特別扱いする
        # (spec §5.1-3 [M-2])。delimiter/decimal に `"` を許すと `'"' in cell` の
        # 判定と衝突し、クォート開始位置が区切り文字と紛れて出力が壊れる。
        if self.delimiter == '"' or self.decimal == '"':
            raise ValueError("区切り文字と小数点記号に二重引用符は使えません")
        if self.precision is not None and self.precision < 0:
            raise ValueError("小数点以下の桁数は 0 以上を指定してください")
        if (
            self.time_start is not None
            and self.time_end is not None
            and self.time_start > self.time_end
        ):
            raise ValueError("time_start must be <= time_end")


def _in_range(t: float, opts: CsvExportOptions) -> bool:
    """行時刻 t が opts の閉区間 [time_start, time_end] に含まれるか (None=無制限)。"""
    return (opts.time_start is None or t >= opts.time_start) and (
        opts.time_end is None or t <= opts.time_end
    )


def _fmt(value: float, options: CsvExportOptions) -> str:
    """値を書式化。precision=None は round-trip(repr)、指定時は固定小数桁。"""
    if options.precision is None:
        s = repr(float(value))  # 再パースで float64 を厳密復元
    else:
        s = f"{float(value):.{options.precision}f}"
    if options.decimal != ".":
        s = s.replace(".", options.decimal)
    return s


def _fmt_value(value: float, options: CsvExportOptions) -> str:
    """値セルを書式化する。非有限 (NaN/±inf) は**空セル**にする (B1・spec §5.1-1)。

    欠測 (統合タイムラインでサンプルが無い) と同じ表現へ揃えるのが目的。裸の
    ``nan`` は Excel で文字列・pandas で NaN・CANape で不明の三者三様になり、
    analysis-correctness が ``Signal.finite_view()`` で確定させた「非有限は値と
    して扱わない」判断とエクスポートだけが逆を向いていた。

    ``_fmt`` を分岐させず**手前で**返すのは、``_fmt`` が時刻セル (:163/:194) と
    共用だから — 時刻は ``Signal.__init__`` (signal.py:80-82) が全構築経路で
    非有限を拒否しており、``_fmt`` 側の分岐は永久に到達しない死んだ枝になる。
    precision 指定時の ``f"{nan:.3f}"`` -> ``"nan"`` 漏れもここで同時に塞がる。
    """
    v = float(value)
    if not math.isfinite(v):
        return ""
    return _fmt(v, options)


def _quote(cell: str, delimiter: str) -> str:
    """RFC 4180 の**最小**クォート: 区切り/二重引用符/改行を含むときだけ囲む。

    「最小」であることが load-bearing — 常時クォートに変えると全セルのバイトが
    変わり、Task 2 のゴールデン全本が差分になる。それ以外のセルはバイト不変。

    判定に使うのは ``delimiter`` であって ``","`` ではない。``delimiter=";"`` +
    ``decimal=","`` の出力 (``0,5;1,5``) は**クォートしてはならない**
    (test_comma_decimal_with_semicolon_delimiter が pin)。
    """
    if delimiter in cell or '"' in cell or "\n" in cell or "\r" in cell:
        return '"' + cell.replace('"', '""') + '"'
    return cell


def _join(cells: list[str], opts: CsvExportOptions) -> str:
    """セル列を最小クォートしてから区切りで連結する — **join の唯一の出口**。

    ヘッダ行・単位行・データ行 (統合/共有) の 4 サイトすべてがここを通る。
    サイトごとに ``delimiter.join`` を直書きすると、信号名/単位だけクォートが
    抜ける非対称が入る (信号名と単位こそ区切り文字混入の主経路・spec §5.1-3
    [M-2])。
    """
    d = opts.delimiter
    return d.join(_quote(c, d) for c in cells)


class CsvExporter:
    """CSV exporter. Writes Signal data as a single CSV file.

    Columns are the timestamp (first) followed by one column per Signal value
    (Req 7.2, 7.3). Writing is atomic (Req 7.7). Formatting is governed by
    :class:`CsvExportOptions`; the default reproduces the original behavior.
    """

    def export(
        self,
        signals: list[Signal],
        output_path: Path,
        use_unified_timeline: bool = False,
        options: CsvExportOptions | None = None,
    ) -> None:
        opts = options if options is not None else CsvExportOptions()
        self._require_single_value_columns(signals)
        if use_unified_timeline:
            rows = self._rows_unified_timeline(signals, opts)
        else:
            rows = self._rows_shared_timeline(signals, opts)
        self._atomic_write(Path(output_path), rows)

    @staticmethod
    def _require_single_value_columns(signals: list[Signal]) -> None:
        """1 時刻 1 値でない Signal (配列チャンネルの親) を拒否する (E-3 C-d)。

        **値を読まずに**親を弾くのは ``Session.export_csv`` の役目 (ColumnRecord
        由来)。ここは CsvExporter を直接呼ぶ経路の最後の砦で、numpy の生 TypeError
        を意味の分かる日本語エラーへ変える。判定を ``sorted_view()`` の結果で行うのは、
        直後に同じ (キャッシュされた) ビューを読むため健全な経路には追加コストが
        無いから — 拒否される側だけが一度の読みを払う。
        """
        for sig in signals:
            # 判定は `sorted_view()` ではなく `values` で行う。**構造化の親では
            # sorted_view 自身が先に落ちる** — `astype(np.float64)` が複合 dtype を
            # キャストできず `TypeError: Cannot cast array data from
            # dtype([('x','<f8'),('y','<f8')])` になり、この層が置き換えるはずの
            # 生 numpy エラーがそのまま出てしまう。
            values = sig.values
            # **構造化の親は ndim == 1** — 複合は shape でなく dtype 側にある
            # (`[('x','f8'),('y','f8')]` の shape は (n,))。ndim だけを見ると
            # 配列の親しか捕まらない。
            if values.ndim != 1 or values.dtype.names is not None:
                raise ValueError(
                    EXPORT_MULTI_COLUMN_VALUES_ERROR_TMPL.format(name=sig.name)
                )

    def _header_rows(self, signals: list[Signal], opts: CsvExportOptions) -> list[str]:
        """ヘッダ行(+ unit_row 指定時は単位行)を返す。"""
        names = (
            list(opts.header_names)
            if opts.header_names is not None
            else [s.name for s in signals]
        )
        lines = [_join([_TIMESTAMP_HEADER, *names], opts)]
        if opts.unit_row:
            # None / キー欠落 / 空文字はすべて空セルへ畳む。production の
            # mdf_loader は truthy ガード (mdf_loader.py:159-161) で None を
            # 載せないが、手組み metadata (Derived・テスト) は None を持ちうる。
            # 畳まないと _quote の `delimiter in None` が TypeError になる
            # (spec §9-6 が T-G へ defer した点をここで確定させる)。
            units = [s.metadata.get("unit") or "" for s in signals]
            lines.append(_join([_TIMESTAMP_UNIT, *units], opts))
        return lines

    def _rows_unified_timeline(
        self, signals: list[Signal], opts: CsvExportOptions
    ) -> list[str]:
        """Align all signals onto the sorted union of their timestamps (Req 7.4)."""
        views = [s.sorted_view() for s in signals]
        unified = np.unique(np.concatenate([ts for ts, _vs in views]))
        lookups = [dict(zip(ts.tolist(), vs.tolist(), strict=True)) for ts, vs in views]

        lines = self._header_rows(signals, opts)
        # 範囲フィルタはタイムライン解決 (union) 後に適用する (F-0 spec §2.2)。
        for ts in unified.tolist():
            if not _in_range(ts, opts):
                continue
            cells = [_fmt(ts, opts)]
            cells.extend(_fmt_value(lk[ts], opts) if ts in lk else "" for lk in lookups)
            lines.append(_join(cells, opts))
        return lines

    def _rows_shared_timeline(
        self, signals: list[Signal], opts: CsvExportOptions
    ) -> list[str]:
        """Build CSV lines assuming all signals share one timestamp axis.

        Multi-rate signals (e.g. independent MDF channel rasters) do not
        share a timeline, so blindly indexing by position would silently
        truncate, misalign, or IndexError. Verify the shared-axis
        precondition up front and fail loudly instead of writing corrupt
        data (whole-branch review Important #1).
        """
        views = [s.sorted_view() for s in signals]
        base_ts = views[0][0]
        for ts, _vs in views:
            if ts.shape != base_ts.shape or not np.array_equal(ts, base_ts):
                raise ValueError(
                    "選択した信号が同一の時間軸を共有していません。"
                    "共有タイムラインで書き出すには統合タイムラインを有効にしてください。"
                )
        timestamps = base_ts
        sorted_values = [vs for _ts, vs in views]
        lines = self._header_rows(signals, opts)
        # 範囲フィルタはタイムライン共有検証 (loud-fail) 後に適用する (F-0 spec §2.2)。
        for i in range(len(timestamps)):
            if not _in_range(timestamps[i], opts):
                continue
            cells = [_fmt(timestamps[i], opts)]
            cells.extend(_fmt_value(vs[i], opts) for vs in sorted_values)
            lines.append(_join(cells, opts))
        return lines

    def _atomic_write(self, output_path: Path, lines: list[str]) -> None:
        """Write lines to a temp file in the target dir, then atomically rename."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(output_path.parent), prefix=".tmp_", suffix=".csv"
        )
        try:
            # UTF-8 BOM つきで書く (E-4b B1・spec §5.1-2)。ヘッダは
            # csv_header_names のファイルキー併記や日本語信号名を含みうるため、
            # BOM が無いと Excel(ja) が cp932 と誤認して化ける。pandas は
            # utf-8-sig 相当で自動除去し、自製品の CsvLoader は既に utf-8-sig
            # 読み (csv_loader.py:46) なので往復は無修正で生存する。
            # BOM はストリーム先頭の 1 回だけ (utf-8-sig の IncrementalEncoder が
            # first フラグを持つ) なので、write を 2 回に分けても二重に付かない。
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
                f.write("\n".join(lines))
                f.write("\n")
            os.replace(tmp_name, output_path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
