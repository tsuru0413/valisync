from __future__ import annotations

import math
import os
import tempfile
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from valisync.core.export.timeline import column_on_union
from valisync.core.models import Signal

# ブロック幅の下限/上限 (spec D3)。下限 16 は「予算を守れない」ではなく **進める**
# ための床で、union が極端に長い (= 1 列が予算を超える) ときでも 16 列ずつ進む。
# 上限 512 は E-4a の鋳造列 LRU 容量と同じ数で、1 ブロックの同時生存が
# 「プロット中の全列」を超えないための目安。
_MIN_BLOCK_COLS = 16
_MAX_BLOCK_COLS = 512
# 行ループ内でキャンセル要求を見る間隔 [I8]。``Event.is_set()`` は ~50 ns なので
# 毎行でも払えるが、1,024 行ごとにすると最も広いブロック (512 列 ~150 us/行) でも
# 応答は ~0.15 s に収まり、狭いブロックでは分岐そのものが消える。
_CANCEL_ROW_INTERVAL = 1024
# 何行ぶん溜めてから write するか。1 行ずつ write すると prod (12,012 行 x 8,253
# ブロック = 99M 回) で write のオーバーヘッドだけが積み上がる。1,024 行 x 512 列で
# バッファは ~2.4 MB に収まる。
_FLUSH_ROWS = 1024

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
#: 境界 API (ExportRequest) の失敗文言。core に置く理由は上の 2 本と同じ —
#: GUI ダイアログを通らない直呼び (scripted / realgui) まで守れる唯一の層。
EXPORT_EMPTY_REQUEST_ERROR = (
    "書き出す列が 1 つも指定されていません。信号を選択してください。"
)
EXPORT_HEADER_LENGTH_ERROR_TMPL = (
    "ヘッダ名の本数 ({got}) が列数 ({want}) と一致しません。"
)
EXPORT_UNRESOLVED_KEYS_ERROR_TMPL = "{n} 件の列を解決できませんでした (例: '{name}')。ファイルが閉じられた可能性があります。"
#: ブロック writer が 1 列を解決できなかったときの文言 (エクスポート中にファイルが
#: アンロードされた場合)。上の複数形と別なのは、writer が最初の 1 本で中断するため
#: (全列を数え上げてから報告すると、その数え上げ自体が 330,004 列の再走査になる)。
EXPORT_UNRESOLVABLE_KEY_ERROR_TMPL = (
    "列 '{key}' を解決できません (ファイルがアンロードされた可能性があります)。"
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
    #: 統合タイムライン (各信号のタイムスタンプの和集合へ整列) で書き出すか。
    #: E-4b spec §5.2 [M-1]: 新境界 (`ExportRequest`) では use_unified_timeline を
    #: 独立引数で運ばず options に載せる (`Session.export_csv` の第 3 位置引数が
    #: bool から options へ変わるため、bool を別に運ぶと 2 つの真実になる)。
    #: **旧 `CsvExporter.export(..., use_unified_timeline=...)` は Task 4 では
    #: 据え置き** (直呼び 56 サイトの契約) で、橋が options -> 旧引数へ写す。
    #: Task 7 で旧引数が消え、このフィールドが唯一の真実になる。
    #: 位置構築の後方互換のため必ず**末尾**に置く。
    use_unified_timeline: bool = False

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


def passthrough_header_names(keys: Sequence[str]) -> list[str]:
    """既定のヘッダ解決器 — キーをそのままヘッダ名にする。

    ``Session.export_csv`` を直呼びする経路 (テスト・scripted・realgui) の
    **現行ヘッダバイトを保存する**ための既定 (spec §5.2 / MG-7)。旧実装は
    ``header_names is None`` のとき ``signal.name`` を書いており、列キーは
    名前空間つき Signal 名と 1:1 なので ``list(keys)`` と同じバイトになる。
    GUI は ``gui.display_names.csv_header_names`` を束ねた resolver を注入する
    (core は gui を import しない契約 — C-5)。
    """
    return list(keys)


@dataclass(frozen=True)
class ExportRequest:
    """CSV 書き出しの確定要求 (E-4b spec §5.2 の境界 API)。

    **Signal のリストを受けない**のが D1 の核心: prod 330,004 列を Signal で
    運ぶと出口に立つ前に ~390 MB を確定させてしまう。列は *キー* で運び、
    実体化は書き手 (Task 6/7 の列ブロック) がブロック単位で行う。

    ``header_resolver`` を持たせるのは、ヘッダと値を**同じ keys から導出**する
    ため (別持ちの ``CsvExportOptions.header_names`` は「header_names 指定時
    =GUI 経路の対応崩しを守るテストがゼロ」という穴を構造的に持っていた —
    C1/M7)。core は gui を import しないので、表示名の計算は callable として
    注入する (C-5)。

    ``extra_signals`` は Derived 信号の escape hatch (spec §5.2 [I-3])。Derived は
    ``SignalGroupManager`` に登録されず keys では解決できないので、Signal 直渡しを
    維持する。出力列順は **keys -> extra_signals** (混ぜない)。
    """

    keys: tuple[str, ...]
    output_path: Path
    options: CsvExportOptions
    header_resolver: Callable[[Sequence[str]], list[str]]
    extra_signals: tuple[Signal, ...] = ()


class ExportCancelled(Exception):
    """協調キャンセルで中断した。

    **temp の削除と出力ファイルの不在は送出側でなく捕捉側の責務** — ブロック
    writer は自分が書いていた temp を消さない (temp 一式の寿命はエクスポート全体を
    束ねる ``export()`` が持ち、そこの ``finally`` が一括で消す)。個々の writer にも
    消させると「誰が消したか」が 2 か所になり、部分削除の競合が入る。
    """


@dataclass(frozen=True)
class MasterScan:
    """列を **値を読まずに** 前走査した結果 (union と割り当ての材料)。

    ``masters`` は identity dedup 済み (spec §5.4)・``runs`` は物理チャンネル
    ごとの列数 (keys の並び順)・``max_master_len`` はブロック幅の見積に使う
    「1 列が実体化しうる最大サンプル数」。
    """

    masters: tuple[np.ndarray, ...]
    runs: tuple[int, ...]
    max_master_len: int


def scan_masters(
    columns: Sequence[tuple[str, Signal | None]],
    resolve: Callable[[str], Signal | None],
) -> MasterScan:
    """列を 1 周して master と物理チャンネルの区切りを集める (**値を読まない**)。

    ここで解決した Signal は**その場で捨てる** — 保持すると 330,004 本が同時生存
    して E-4b が消そうとしているメモリがそのまま戻る。鋳造自体は I/O を伴わない
    (``LazyMdfValues`` は遅延) ので、この前走査は master と metadata しか触らない。

    区切りは ``(id(master), physical_channel)`` の変化点で採る。キー文字列を
    parse しないのは、``Mat[0]`` のような列名が実チャンネル名と字面衝突しうる
    から (E-3 の 1:1 契約が守るのは衝突の**拒否**であって、字面の一意性ではない)。
    """
    seen_masters: set[int] = set()
    masters: list[np.ndarray] = []
    runs: list[int] = []
    max_len = 0
    current: tuple[int, object] | None = None
    for key, direct in columns:
        sig = direct if direct is not None else resolve(key)
        if sig is None:
            raise ValueError(EXPORT_UNRESOLVABLE_KEY_ERROR_TMPL.format(key=key))
        master = sig.timestamps
        if id(master) not in seen_masters:
            seen_masters.add(id(master))
            masters.append(master)
            max_len = max(max_len, len(master))
        channel = (id(master), sig.metadata.get("physical_channel", sig.name))
        if channel == current:
            runs[-1] += 1
        else:
            runs.append(1)
            current = channel
        del sig  # 前走査は 1 本ずつ捨てる (同時生存 1 本)
    return MasterScan(tuple(masters), tuple(runs), max_len)


def block_columns(n_rows: int, max_master_len: int, budget_bytes: int) -> int:
    """1 ブロックに載せる列数 (D3 の動的決定)。

    1 列が同時に抱える実体は「union 行に整列した float64 値 (8 B/行) + 存在
    フラグ (1 B/行)」で、これは**ブロックの終わりまで**生きる (行ループが全列を
    横断するため)。加えて 1 列ぶんの ``sorted_view`` (時刻 + 値 = 16 B/サンプル)
    が整列の間だけ生きる。合計を予算で割ったものが上限。

    **値を ``tolist()`` してはならない**: Python float は 32 B/セルで、この式の
    3.5 倍を食う (512 列 x 12,012 行 = 200 MB)。numpy 配列のまま持ち、セル書式化は
    書き出しの瞬間に 1 セルずつ行う。
    """
    per_col = n_rows * 9 + max_master_len * 16
    if per_col <= 0:
        return _MAX_BLOCK_COLS  # 行 0 本 (範囲外エクスポート) — 幅は制約にならない
    return max(_MIN_BLOCK_COLS, min(_MAX_BLOCK_COLS, budget_bytes // per_col))


def plan_blocks(runs: Sequence[int], block_cols: int) -> tuple[tuple[int, int], ...]:
    """物理チャンネルの区切り ``runs`` を ``[start, stop)`` のブロックへ詰める。

    **1 チャンネルの列は同じブロックへ**入れる (spec §5.3): チャンネルを跨いで
    混ぜると、ブロックごとに別チャンネルの 2-D を読み直して evict 連鎖が
    チャンネル数ぶんでなく列数ぶんになる。

    ただし**単独で上限を超える run は分割する**。割ってよいのは E-4a の
    チャンネルキャッシュが 2-D を保持しており、2 ブロック目の切り出しが select
    ではなくヒットになるから — 「絶対に割らない」にすると幅 1,100 のチャンネルで
    1 ブロックが上限の 2 倍を実体化する。
    """
    blocks: list[tuple[int, int]] = []
    start = cur = 0
    for run in runs:
        if cur > start and cur - start + run > block_cols:
            blocks.append((start, cur))
            start = cur
        cur += run
        while cur - start > block_cols:
            blocks.append((start, start + block_cols))
            start += block_cols
    if cur > start:
        blocks.append((start, cur))
    return tuple(blocks)


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ExportCancelled("エクスポートはキャンセルされました")


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
        # I3 fix (T4 レビュー): 旧署名では位置引数 use_unified_timeline が唯一の
        # 真実 (options.use_unified_timeline は E-4b で新設した新境界向けフィールド
        # で、この経路では読まれない)。options 側だけ True にして位置引数を False
        # (既定) のまま呼ぶと、呼び出し元は「統合タイムラインで書き出した」つもりで
        # 実際は共有タイムライン(無警告)になる — 56 の旧署名直呼びサイトに実在する
        # 罠を無言で踏める形だったので loud-fail にする。このガードは旧署名ごと
        # Task 7 で消える。
        if (
            options is not None
            and options.use_unified_timeline
            and not use_unified_timeline
        ):
            raise ValueError(
                "options.use_unified_timeline=True と位置引数 "
                "use_unified_timeline=False が矛盾しています "
                "(旧署名では位置引数が唯一の真実 — E-4b Task 7 まで)"
            )
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

    # ─── 列ブロックパイプライン (E-4b spec §5.3・export() へは Task 7 で配線) ───

    @staticmethod
    def _require_single_value_column(sig: Signal) -> None:
        """1 時刻 1 値でない列 (配列/構造化の親) を拒否する (E-3 C-d)。

        判定を ``sorted_view()`` ではなく ``values`` で行う理由は
        ``_require_single_value_columns`` の docstring と同一 (構造化の親では
        ``astype(np.float64)`` が先に生 TypeError を出す)。
        """
        values = sig.values
        if values.ndim != 1 or values.dtype.names is not None:
            raise ValueError(
                EXPORT_MULTI_COLUMN_VALUES_ERROR_TMPL.format(name=sig.name)
            )

    def _write_time_temp(
        self,
        union_view: np.ndarray,
        opts: CsvExportOptions,
        temp_path: Path,
        cancel: threading.Event | None,
    ) -> None:
        """時刻列を **幅 1 のブロック** として書く (マージ器に特別扱いを作らない)。"""
        with open(temp_path, "w", encoding="utf-8", newline="") as f:
            buf: list[str] = []
            for i, ts in enumerate(union_view.tolist()):
                if i % _CANCEL_ROW_INTERVAL == 0:
                    _check_cancel(cancel)
                buf.append(_join([_fmt(ts, opts)], opts))
                if len(buf) >= _FLUSH_ROWS:
                    f.write("\n".join(buf) + "\n")
                    buf.clear()
            if buf:
                f.write("\n".join(buf) + "\n")

    def _write_block_temp(
        self,
        columns: Sequence[tuple[str, Signal | None]],
        *,
        resolve: Callable[[str], Signal | None],
        union_view: np.ndarray,
        opts: CsvExportOptions,
        temp_path: Path,
        cancel: threading.Event | None,
    ) -> list[str]:
        """1 ブロックぶんのセル断片を *temp_path* へ書き、単位の側帯を返す。

        1 行 = このブロックの列だけを区切りで繋いだ断片 (時刻も他ブロックも
        含まない)。行数は必ず ``len(union_view)`` になる — マージ器の行数一致
        assert (MG-6) が意味を持つのはこの不変条件があるから。

        列の参照はこの関数を出る時点で 1 本も残らない (``aligned`` は
        ``column_on_union`` が作った**新しい** numpy 配列だけを持ち、元 Signal を
        掴まない)。これが G2/G5 の「同時生存 <= block_cols」の実装上の根拠。
        """
        aligned: list[tuple[np.ndarray, np.ndarray]] = []
        units: list[str] = []
        for key, direct in columns:
            # ブロック境界だけでなく **各列の読みの前** で見る [I8]: cold な列は
            # ~316 ms/列かかるので、境界だけだと block_cols x 316 ms の間 Event を
            # 見ないことになる。
            _check_cancel(cancel)
            sig = direct if direct is not None else resolve(key)
            if sig is None:
                raise ValueError(EXPORT_UNRESOLVABLE_KEY_ERROR_TMPL.format(key=key))
            # 拒否は**行組み立ての前**に置く (E-3 C-d の位置)。行ループへ入って
            # からだと temp が既に開いており、部分的に書かれたファイルが残る。
            self._require_single_value_column(sig)
            ts, vs = sig.sorted_view()
            aligned.append(column_on_union(ts, vs, union_view))
            unit = sig.metadata.get("unit", "")
            # production の mdf_loader は truthy ガードで None を載せないが
            # (spec §13-2)、手組み metadata では None がありうる (§9-6)。
            units.append(unit if isinstance(unit, str) else "")
            del sig, ts, vs  # 明示解放 (次の列を読む前に落とす = 同時生存 1 本)
        with open(temp_path, "w", encoding="utf-8", newline="") as f:
            buf: list[str] = []
            for i in range(len(union_view)):
                if i % _CANCEL_ROW_INTERVAL == 0:
                    _check_cancel(cancel)
                buf.append(
                    _join(
                        [
                            _fmt_value(vals[i], opts) if present[i] else ""
                            for vals, present in aligned
                        ],
                        opts,
                    )
                )
                if len(buf) >= _FLUSH_ROWS:
                    f.write("\n".join(buf) + "\n")
                    buf.clear()
            if buf:
                f.write("\n".join(buf) + "\n")
        return units

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
