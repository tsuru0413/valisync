from __future__ import annotations

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
        if use_unified_timeline:
            rows = self._rows_unified_timeline(signals, opts)
        else:
            rows = self._rows_shared_timeline(signals, opts)
        self._atomic_write(Path(output_path), rows)

    def _header_rows(self, signals: list[Signal], opts: CsvExportOptions) -> list[str]:
        """ヘッダ行(+ unit_row 指定時は単位行)を返す。"""
        names = (
            list(opts.header_names)
            if opts.header_names is not None
            else [s.name for s in signals]
        )
        lines = [opts.delimiter.join([_TIMESTAMP_HEADER, *names])]
        if opts.unit_row:
            units = [s.metadata.get("unit", "") for s in signals]
            lines.append(opts.delimiter.join([_TIMESTAMP_UNIT, *units]))
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
            cells.extend(_fmt(lk[ts], opts) if ts in lk else "" for lk in lookups)
            lines.append(opts.delimiter.join(cells))
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
            cells.extend(_fmt(vs[i], opts) for vs in sorted_values)
            lines.append(opts.delimiter.join(cells))
        return lines

    def _atomic_write(self, output_path: Path, lines: list[str]) -> None:
        """Write lines to a temp file in the target dir, then atomically rename."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(output_path.parent), prefix=".tmp_", suffix=".csv"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write("\n".join(lines))
                f.write("\n")
            os.replace(tmp_name, output_path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
