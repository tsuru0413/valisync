from __future__ import annotations

import contextlib
import math
import os
import shutil
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO

import numpy as np

from valisync.core.export.timeline import (
    canonical_master,
    column_on_union,
    row_range,
    union_timeline,
)
from valisync.core.models import Signal
from valisync.core.models.sample_source import SampleReadError

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
# 多段マージの fan-in。同時 open = F + 1 本。**本環境実測の FD 天井は 8,189 本**
# (OSError errno 24・CPython 3.13.7 / Win11) で、prod 3 ファイル比較の全列
# エクスポートは block 数 ~8,253 = 単段では確実に超える (MG-2)。512 なら 8,254 本が
# 2 段で畳める。
_MERGE_FAN_IN = 512
# 中間 temp を含むディスクピークの見積係数 (spec §5.3: 出力 x (1 + 1/F の等比和 +
# 安全率))。**設計値であって実測値ではない** — T-M で検証する (§9-5)。
#
# **この 1 つが唯一の実体** (`_DISK_HEADROOM` という private 名は作らない):
# GUI 側の門番 (`estimate.disk_shortfall`) が同じ係数を別に持つと、Task 11 の検定で
# 片方だけ更新されたときに「GUI の D5 を通過 -> 確認 Yes -> core で ValueError」
# という UX 破綻窓が開く。`estimate.py` はこれを import して再輸出する。
TEMP_AMPLIFICATION = 2.3
# 1 セルあたりの推定バイト (区切り込み)。spec §1 の訂正済み見積 (uint8 量子化の
# repr 長 4.57 文字・float64 は ~17 文字) の中間を採った**開始前の粗い門番**。
# Task 11 が単価 3 定数 (estimate.py) と同時にこれも prod 1 点で検定する — core の
# 門番 (ここ) が GUI の門番より緩いと、GUI が通した要求を core が弾く順序逆転が
# 起きる。
_EST_BYTES_PER_CELL = 12
# `budget_fn` が注入されなかったときのブロック幅予算 (直接 `CsvExporter()` を組む
# 経路 = テスト・scripted 用の代替値)。`ChannelSampleCache` の既定予算と同値に
# 揃えてある — production は `Session.__init__` が `budget_fn` を注入するので、
# ここが読まれるのは Session を経由しない呼び出しだけ。
_DEFAULT_EXPORT_BUDGET_BYTES = 256 * 1024 * 1024

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
#: ブロック writer が 1 列を解決できなかったときの文言。上の複数形と別なのは、
#: writer が最初の 1 本で中断するため (全列を数え上げてから報告すると、その
#: 数え上げ自体が 330,004 列の再走査になる)。
#:
#: Minor 6 (Task 10b レビュー是正): 旧文言「(ファイルがアンロードされた可能性が
#: あります)」は `EXPORT_SOURCE_LOST_TMPL` (decay の文言) と近すぎて、読み手が
#: 「同じ失敗の 2 通りの言い方」と誤読しかねなかった。この ValueError は
#: **`Session` を経由しない直呼び (呼び出し規約違反)** でしか到達しない
#: (`Session.export_resolver()` が先に `ExportSourceLost` を投げるため) —
#: 文言でその違いを名指しし、2 つの近い文言が指す事象が別物であることを
#: 明示する。
EXPORT_UNRESOLVABLE_KEY_ERROR_TMPL = (
    "列 '{key}' を解決できません"
    "（呼び出し規約違反: resolve が None を返しました。"  # noqa: RUF001
    "Session 経由の呼び出しでは ExportSourceLost になります）。"  # noqa: RUF001
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


#: 列が解決できなくなった (= 元ファイルがアンロードされた) ときの decay 文言。
#: `EXPORT_UNRESOLVABLE_KEY_ERROR_TMPL` と別なのは**宛先が違う**から — あちらは
#: 「解決器が None を返した」という writer 内部の loud-fail (ValueError = 想定外)
#: で、こちらは Session が張る「エクスポート中の unload」という**想定内の decay**
#: (spec §5.7 [I7c]) の文言。同じ文字列を使い回すと GUI 側の出し分け
#: (isinstance) と文言が二重管理になる。
#: Minor 2 (Task 10b レビュー是正・表記規約 R-02): 括る内容に日本語 ("列") を
#: 含むため全角括弧が正 — 半角のままだと R-02 違反 (lint 回避で表記を歪めない、
#: 全角は noqa 既定)。
EXPORT_SOURCE_LOST_TMPL = (
    "エクスポート中に元ファイルが閉じられたため中止しました（列: '{key}'）。"  # noqa: RUF001
)


class ExportSourceLost(ExportCancelled):
    """エクスポート中に元ファイルが閉じられ、列が読めなくなった (decay)。

    ``ExportCancelled`` を **継承する** のは、temp 削除と「失敗ならファイルが存在
    しない」契約 (spec §10) の経路を 1 本に保つため — 別系統の例外にすると
    ``_export_request`` の ``finally`` の網から漏れて残骸が出るうえ、
    ``ExportController._fail`` の ``isinstance(exc, ExportCancelled)`` 分岐から
    外れてエラーモーダルへ流れる。GUI は逆向きの isinstance で「ユーザーが押した」
    と「ファイルが消えた」を出し分ける (前者はステータスのみ・後者は診断 1 件)。

    *key* は失われた列キー、*source_file* は元ファイルのパス (分かる範囲で)。
    診断の宛先を決めるためのコンテキストで、``SampleReadError`` が
    ``signal_key`` / ``source_file`` を提げているのと同じ規約 — 投げ手だけが
    知っている情報なので、ここへ載せないと GUI 側では復元できない。
    """

    def __init__(
        self,
        message: str,
        *,
        key: str | None = None,
        source_file: str | None = None,
    ) -> None:
        super().__init__(message)
        self.key = key
        self.source_file = source_file


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
    if block_cols < 1:
        # ガード無しでは `cur - start > block_cols` が block_cols<=0 のとき常に真になり、
        # while ループが `start` を進めないまま空区間 (0, 0) を無限 append する
        # (レビュー実測: 無限ループ + blocks の無限リスト成長)。唯一の生産者
        # `block_columns` は下限 16 でクランプするので今日は到達しないが、
        # 別経路 (Task 7 が block_cols を公開注入にする) から 0 以下が渡ると
        # ループへ入る**前**に落とす必要がある。
        raise ValueError(f"block_cols は 1 以上が必要です (got {block_cols})")
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


def merge_stage_count(n_inputs: int, fan_in: int) -> int:
    """*n_inputs* 本を fan-in *fan_in* で畳むのに要する段数 (最低 1 段)。

    最低 1 段なのは、**ヘッダ行と単位行を書くのが最終段の役目**だから。入力が
    1 本でも 1 段走らせて先頭に付ける (最終段の後に別パスを足すと出力全体を
    もう 1 回コピーすることになり、prod の 10 GB では丸ごと 1 往復になる)。

    ``fan_in < 2`` を**ループへ入る前に**弾くのは、``fan_in == 1`` だと
    ``remaining`` が永久に減らず無限ループになるから (``plan_blocks`` の
    ``block_cols < 1`` ガードと同型の理由)。``merge_fan_in`` は Task 7 で
    ``CsvExporter.__init__`` の公開注入口になったので、別経路から 1 以下が渡る。
    """
    if fan_in < 2:
        raise ValueError(f"merge の fan-in は 2 以上が必要です (got {fan_in})")
    stages = 0
    remaining = n_inputs
    while remaining > 1:
        remaining = -(-remaining // fan_in)  # ceil
        stages += 1
    return max(1, stages)


def estimate_output_bytes(n_rows: int, n_columns: int) -> int:
    """出力サイズの粗い推定 (時刻列を含む)。T-UX が係数を実測で差し替える起点。"""
    return n_rows * (n_columns + 1) * _EST_BYTES_PER_CELL


def _require_disk_space(out_dir: Path, n_rows: int, n_columns: int) -> None:
    """D5: 中間 temp を含むピーク (`TEMP_AMPLIFICATION` x 推定出力) が入らないなら開始しない。"""
    need = int(estimate_output_bytes(n_rows, n_columns) * TEMP_AMPLIFICATION)
    free = shutil.disk_usage(out_dir).free
    if free < need:
        raise ValueError(
            f"出力先の空き容量が不足しています (推定 {need:,} バイト必要・"
            f"空き {free:,} バイト)。範囲を狭めるか列を減らしてください。"
        )


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ExportCancelled("エクスポートはキャンセルされました")


class CsvExporter:
    """CSV exporter. Writes Signal data as a single CSV file.

    Columns are the timestamp (first) followed by one column per Signal value
    (Req 7.2, 7.3). Writing is atomic (Req 7.7). Formatting is governed by
    :class:`CsvExportOptions`; the default reproduces the original behavior.

    書きパイプラインは **列ブロック x 行ストリーム x 多段マージ** (spec §5.3)。
    コンストラクタの 3 つの注入口はいずれも**テストと Session からの配線専用**で、
    既定 (すべて None) が production の振る舞い:

    - ``block_cols``: ブロック幅を固定する (既定は ``block_columns`` の動的決定)。
      ゴールデンを**複数ブロック・境界跨ぎ**で駆動するための口 (spec G1)。
    - ``budget_fn``: ブロック幅の予算を**呼び出し時に**読む (D3「予算 - 現在の
      pin 済み」)。値でなく callable なのは、pin の増減 (プロット操作) を次の
      エクスポートへ反映させるため。
    - ``merge_fan_in``: マージの fan-in を固定する (既定 ``_MERGE_FAN_IN``)。
      小さな fixture で**多段**を実際に走らせるための口。
    """

    def __init__(
        self,
        *,
        block_cols: int | None = None,
        budget_fn: Callable[[], int] | None = None,
        merge_fan_in: int | None = None,
    ) -> None:
        # 下限は `plan_blocks` / `merge_stage_count` 側にもあるが、**注入の瞬間に**
        # 落とす: ブロック writer を 1 本も走らせてから無限ループ/例外になるより、
        # 構築時に原因の分かる形で止める方が診断が短い。
        if block_cols is not None and block_cols < 1:
            raise ValueError(f"block_cols は 1 以上が必要です (got {block_cols})")
        if merge_fan_in is not None and merge_fan_in < 2:
            raise ValueError(f"merge_fan_in は 2 以上が必要です (got {merge_fan_in})")
        self._block_cols_override = block_cols
        self._budget_fn = budget_fn
        self._merge_fan_in = merge_fan_in

    def export(
        self,
        request: ExportRequest | list[Signal],
        resolve: Callable[[str], Signal | None] | Path | None = None,
        use_unified_timeline: bool = False,
        options: CsvExportOptions | None = None,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        """CSV を書き出す (2 形の dispatch)。

        正準形は ``export(request, resolve, progress=..., cancel=...)``。
        legacy 形 ``export(signals, output_path, use_unified_timeline, options)``
        は**同じパイプラインへ落とす** — 旧一括実装を残すと
        ``dict(zip(...tolist()))`` (実測 97 B/サンプル・20 列で Win32 working set
        2.14 GiB) が legacy 経路にだけ生き残り、既存テスト 40 サイトが全部緑の
        ままそこを通り続ける。落としたことで、その 40 サイトが**そのまま**
        ブロックパイプラインの回帰網になる。

        *progress* の単位は等重でない — マージ段 1 単位は実時間でブロック多数分に
        相当しうる。ETA を線形で出すなら段の重みを入力本数で補正すること (Task 9)。
        """
        if isinstance(request, ExportRequest):
            if not callable(resolve):
                raise TypeError(
                    "ExportRequest 形の第 2 引数は resolve (列キー -> Signal) です"
                )
            self._export_request(request, resolve, progress, cancel)
            return

        # ─ legacy 形 ─────────────────────────────────────────────────────────
        # I3 (T4 レビュー): 旧署名では位置引数 use_unified_timeline が唯一の真実。
        # options 側だけ True にして位置引数を False (既定) のまま呼ぶと、呼び出し元は
        # 「統合タイムラインで書き出した」つもりで実際は共有タイムライン(無警告)に
        # なる — 旧署名直呼びサイトに実在する罠なので loud-fail のまま残す
        # (旧署名は 36 サイト + ゴールデン駆動が使うので Task 7 でも撤去しない)。
        if (
            options is not None
            and options.use_unified_timeline
            and not use_unified_timeline
        ):
            raise ValueError(
                "options.use_unified_timeline=True と位置引数 "
                "use_unified_timeline=False が矛盾しています "
                "(旧署名では位置引数が唯一の真実)"
            )
        if resolve is None or callable(resolve):
            raise TypeError("legacy 形の第 2 引数は出力パスです")
        signals = list(request)
        opts = options if options is not None else CsvExportOptions()
        # 名前の重複 (同名 Signal 2 本) が dict で潰れないよう、**位置**をキーにする。
        keys = tuple(f"#{i}" for i in range(len(signals)))
        table = dict(zip(keys, signals, strict=True))
        # **`options.header_names` を読む**のがここの要点 (旧 `_header_rows` の
        # 「header_names があればそれ・無ければ signal.name」を逐語で保存する)。
        # 読まないと golden driver が GUI 形ヘッダを header_names へ詰めている
        # 10 本 (g01/g03-g11) が raw 名へ退行し、既存
        # test_csv_export_options.py:158-171 も RED になる。header_names は
        # **legacy overload の唯一のヘッダ搬送路**として残置する
        # (spec §5.1-4 [MG-7] の「別持ちを廃止」は ExportRequest 経路に限って達成
        # と読み替える — 新境界では header_resolver が唯一の真実で header_names は
        # 1 度も読まれない)。
        resolver: Callable[[Sequence[str]], list[str]]
        if opts.header_names is not None:
            fixed = list(opts.header_names)
            resolver = lambda _ks: list(fixed)  # noqa: E731
        else:
            resolver = lambda ks: [table[k].name for k in ks]  # noqa: E731
        self._export_request(
            ExportRequest(
                keys=keys,
                output_path=Path(resolve),
                options=replace(opts, use_unified_timeline=use_unified_timeline),
                header_resolver=resolver,
            ),
            table.get,
            progress,
            cancel,
        )

    def _export_request(
        self,
        request: ExportRequest,
        resolve: Callable[[str], Signal | None],
        progress: Callable[[int, int], None] | None,
        cancel: threading.Event | None,
    ) -> None:
        opts = request.options
        # **空リクエストの loud-fail はここが本体** (橋の撤去で消える検査の移設)。
        # 無いと `union_timeline([])` が長さ 0 を返し -> ブロック 0 本 -> 「ヘッダ
        # だけのファイルを成功として書く」へ degrade する。
        # 注: 「列 >= 1 本だが範囲外 = ヘッダのみのファイル」は**別契約**で、
        # 現行どおり成功として書く (空**列**とは区別する)。
        if not request.keys and not request.extra_signals:
            raise ValueError(EXPORT_EMPTY_REQUEST_ERROR)
        output_path = Path(request.output_path)
        out_dir = output_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        columns: list[tuple[str, Signal | None]] = [(k, None) for k in request.keys]
        columns.extend((s.name, s) for s in request.extra_signals)

        # Minor 3 (Task 10b レビュー是正): temps は scan_masters より**前**に
        # 用意し、scan_masters 自体を try の内側へ移す。今日の scan_masters は
        # 値を読まない (I/O を伴わない) ので無害だが、将来 lazy master
        # (union/走査を値から導く実装) が入ると SampleReadError を投げうる —
        # その呼び出しが try の外にあると、下の `except SampleReadError` の網から
        # 漏れて decay ではなく**エラーモーダル**へ戻る穴が黙って開く。temps を
        # 先に空リストで用意しておけば、scan_masters 段の例外 (今日の
        # ValueError・将来の SampleReadError とも) は `finally` で「temps が
        # 空だから何もしない」no-op を通るだけで、既存の失敗経路 (ヘッダ長
        # 不一致等) の挙動は変わらない。
        token = uuid.uuid4().hex[:12]
        temps: list[Path] = []
        try:
            # --- 前走査 -> union -> 前提検証 -> 行範囲 (すべて値を読まない) ----
            scan = scan_masters(columns, resolve)
            # **ヘッダ長の検査は temp を 1 バイトも書く前** (橋の撤去で消える
            # 検査の移設)。resolver 呼び出しを最終段まで遅らせると、ヘッダ長
            # 不一致が「全ブロックを書き切ってから落ちる」形になり、prod では
            # ~18 分の無駄と temp 生成を伴う。
            names = list(request.header_resolver(request.keys))
            if len(names) != len(request.keys):
                raise ValueError(
                    EXPORT_HEADER_LENGTH_ERROR_TMPL.format(
                        got=len(names), want=len(request.keys)
                    )
                )
            union = union_timeline(scan.masters)
            if not opts.use_unified_timeline:
                self._require_shared_timeline(scan.masters)
            lo, hi = row_range(union, opts.time_start, opts.time_end)
            union_view = union[lo:hi]

            budget = (
                self._budget_fn()
                if self._budget_fn is not None
                else _DEFAULT_EXPORT_BUDGET_BYTES
            )
            block_cols = self._block_cols_override or block_columns(
                len(union_view), scan.max_master_len, budget
            )
            fan_in = self._merge_fan_in or _MERGE_FAN_IN
            blocks = plan_blocks(scan.runs, block_cols)
            _require_disk_space(out_dir, len(union_view), len(columns))

            # 単位は等重でない (M3 レビュー): マージ段 1 単位は実時間で
            # ブロック多数分に相当しうる。prod 形 (§5.3 コメント参照) では 2 段の
            # マージが ~10 GB の全列を 2 回フル読み書きするのに、単位数で見ると
            # 全体 (時刻 1 + ブロック ~8,253 + マージ 2 = 8,256) の 0.024% しか
            # 占めない。今は reweight しない (ETA は Task 9 が作る) が、線形 ETA
            # を出すならここで段の重みを入力本数で補正すること。
            n_units = 1 + len(blocks) + merge_stage_count(1 + len(blocks), fan_in)
            done = 0

            def tick() -> None:
                nonlocal done
                done += 1
                if progress is not None:
                    progress(done, n_units)

            # --- 時刻列 (幅 1 のブロック・マージ器に特別扱いを作らない) --------
            time_temp = out_dir / f".tmp_export_{token}_time.csv"
            temps.append(time_temp)
            self._write_time_temp(union_view, opts, time_temp, cancel)
            tick()

            # --- 列ブロック -----------------------------------------------------
            units: list[str] = []
            for i, (start, stop) in enumerate(blocks):
                _check_cancel(cancel)  # ブロック境界 [I8]
                temp = out_dir / f".tmp_export_{token}_b{i:05d}.csv"
                temps.append(temp)
                units.extend(
                    self._write_block_temp(
                        columns[start:stop],
                        resolve=resolve,
                        union_view=union_view,
                        opts=opts,
                        temp_path=temp,
                        cancel=cancel,
                    )
                )
                tick()

            # --- ヘッダ/単位行 (keys から導出・単位は側帯から) -----------------
            # `names` は temp を書く**前**に解決済み (長さ検査も済み)。ここで
            # resolver を呼び直さない — 2 回呼ぶと副作用つき resolver でヘッダと
            # 検査対象がずれる。単位はブロックパス中の側帯 (`units`) から取り、
            # マージ段で再 resolve しない (330k 再解決 = ~390 MB の一撃・MG-4)。
            names.extend(s.name for s in request.extra_signals)
            prefix = [_join([_TIMESTAMP_HEADER, *names], opts)]
            if opts.unit_row:
                prefix.append(_join([_TIMESTAMP_UNIT, *units], opts))

            # --- 多段マージ -----------------------------------------------------
            stages = merge_stage_count(len(temps), fan_in)
            current = list(temps)
            for stage in range(stages):
                is_last = stage == stages - 1
                outputs: list[Path] = []
                for chunk_start in range(0, len(current), fan_in):
                    chunk = current[chunk_start : chunk_start + fan_in]
                    merged = (
                        out_dir / f".tmp_export_{token}_s{stage}_{len(outputs):05d}.csv"
                    )
                    # **作らせる前に登録する**。`_merge_one_stage` の内側で
                    # 名前を決めさせて戻り値で受け取る形にすると、マージ途中の
                    # 例外 (キャンセル・行数不一致) で「既に open 済みだが誰も
                    # 知らない temp」が残る — 実測で 1 本残った (B6 違反)。
                    # 時刻/ブロック temp と同じく**経路を束ねる側が全パスを持つ**。
                    temps.append(merged)
                    self._merge_one_stage(
                        chunk,
                        merged_path=merged,
                        stage=stage,
                        prefix_lines=tuple(prefix) if is_last else (),
                        opts=opts,
                        cancel=cancel,
                    )
                    outputs.append(merged)
                    for spent in chunk:
                        spent.unlink(missing_ok=True)
                        temps.remove(spent)
                current = outputs
                tick()
            # `merge_stage_count` の算術と実ループがずれると `current[0]` が
            # **列を落としたファイル**になる (残りは finally で消えるので誰も
            # 気付かない)。段数の一致は出力の正しさそのものなので loud-fail。
            if len(current) != 1:
                raise ValueError(
                    f"内部エラー: マージ段数の算術が実際と一致しません "
                    f"(残 {len(current)} 本・段数 {stages}・fan-in {fan_in})"
                )
            final_temp = current[0]
            os.replace(final_temp, output_path)
            temps.remove(final_temp)
        except SampleReadError as exc:
            # **decay の第 2 の入口** (spec §5.7 [I7c])。`Session.export_resolver`
            # が閉じるのは「解決が None を返す」窓だけで、production の実レースは
            # ここ — `Session.remove_group` は _groups.remove -> handle.close の順
            # なので、既に解決済みの列を `sorted_view()` で**読む**瞬間に閉じられる
            # (session.py の WHY: in-flight の select は lock で完走し、
            # SampleReadError になるのは「次の列」)。解決と読みは
            # `_write_block_temp` で隣接しており窓は狭いが、~18 分走る prod では
            # 常態になる。
            #
            # 包まないと SampleReadError がそのまま外へ出て、GUI の
            # `ExportController._fail` の `isinstance(exc, ExportCancelled)` を
            # 外れ、B6 の decay 経路 (ステータス + 診断 1 件) ではなく
            # **エラーモーダル**になる (temp 削除だけは下の finally で成立するので、
            # 症状はユーザー向けの出方だけ = 数字にもテストにも出ない)。
            #
            # 文言は差し替えず `str(exc)` を運ぶ: SampleReadError は「閉じられた」
            # 以外に I/O 失敗・長さ不一致でも上がるので、`EXPORT_SOURCE_LOST_TMPL`
            # で上書きすると原因を誤って断定した診断が残る。型 (= 扱い) だけを
            # decay へ寄せ、理由は元の文言のまま伝える。
            raise ExportSourceLost(
                str(exc),
                key=exc.signal_key,
                source_file=exc.source_file,
            ) from exc
        finally:
            # B6「何も残さない」: 成功でも失敗でもキャンセルでも temp は残さない。
            # **束ねる側 (ここ) が唯一の掃除役** — 個々の writer にも消させると
            # 「誰が消したか」が 2 か所になり部分削除の競合が入る
            # (`ExportCancelled` の docstring が記録している契約)。
            for leftover in temps:
                # OSError を握り潰すのは、掃除の失敗 (Windows で別プロセスが
                # 掴んでいる等) で**元の例外を差し替えない**ため。1 本消せなくても
                # 残りは消す。
                with contextlib.suppress(OSError):
                    leftover.unlink(missing_ok=True)

    @staticmethod
    def _require_shared_timeline(masters: Sequence[np.ndarray]) -> None:
        """全 master が同一時間軸であることを **値を読まずに** 検証する (MG-6)。

        比較は ``canonical_master`` 同士 — 旧実装は ``sorted_view()[0]`` を比べて
        いたので、生 master のまま比べると「非単調だが整列すれば同じ」信号を
        誤って拒否する。

        ``masters`` は ``scan_masters`` の identity dedup 済みなので、prod の
        「全列が同一 master オブジェクト」構成では 1 本しか来ず比較が 0 回になる。
        """
        if not masters:
            return
        base = canonical_master(masters[0])
        for master in masters[1:]:
            other = canonical_master(master)
            if other.shape != base.shape or not np.array_equal(other, base):
                raise ValueError(
                    "選択した信号が同一の時間軸を共有していません。"
                    "共有タイムラインで書き出すには統合タイムラインを有効にしてください。"
                )

    def _merge_one_stage(
        self,
        inputs: Sequence[Path],
        *,
        merged_path: Path,
        stage: int,
        prefix_lines: Sequence[str],
        opts: CsvExportOptions,
        cancel: threading.Event | None,
    ) -> None:
        """*inputs* を横に繋いで *merged_path* を作る (同時 open = len(inputs) + 1)。

        **出力パスは受け取る** (自分で決めない): 途中で落ちたときに残る temp を
        掃除できるのは、パスを**呼ぶ前から**知っている ``_export_request`` だけ。

        **全入力の行数一致を assert する** (MG-6): ずれたまま繋ぐと、ある列から
        先が 1 行ずれた別時刻の値になる — 例外も長さ検証も出ないサイレント誤データ
        なので、ここで loud-fail させて B6 (全 temp 削除) へ倒す。

        断片に改行は入りえない (値セルは数値であり、クォートが要る文字を含むのは
        ヘッダ/単位行だけで、それは最終段でここへ prefix として渡される) ので、
        行単位の読み出しで正しい。

        断片同士は ``opts.delimiter`` で**素に**繋ぐ — クォートは断片を作った
        ブロック writer の ``_join`` が既に適用済みで、ここで再適用すると
        既にクォート済みのセルの二重引用符がさらにエスケープされ、囲みが 1 重から
        3 重へ膨らむ (ブロック数で重複の出方が変わるので、分割不変テストでしか
        捕まらない)。
        """
        # utf-8-sig は**最終段のみ**が付ける BOM。中間 temp は素の utf-8。
        encoding = "utf-8-sig" if prefix_lines else "utf-8"
        # SIM115 抑止: 同時に F 本開いて**行ごとに横断する**のがこの関数の要点で、
        # 個々を `with` に入れることはできない (ExitStack を使っても閉じる責務が
        # 分散するだけ)。下の `finally` が全数 close の唯一の出口。
        handles: list[IO[str]] = []
        try:
            for path in inputs:
                handles.append(open(path, encoding="utf-8", newline=""))  # noqa: SIM115
            with open(merged_path, "w", encoding=encoding, newline="") as out:
                for line in prefix_lines:
                    out.write(line + "\n")
                buf: list[str] = []
                row = 0
                while True:
                    if row % _CANCEL_ROW_INTERVAL == 0:
                        _check_cancel(cancel)
                    fragments = [h.readline() for h in handles]
                    if all(f == "" for f in fragments):
                        break
                    if any(f == "" for f in fragments):
                        raise ValueError(
                            "内部エラー: 列ブロックの行数が一致しません "
                            f"(段 {stage}・行 {row})"
                        )
                    # CR も防御的に剥ぐ (T7 再レビューの 18 件目): CRLF 断片は
                    # readline() が 1 行と数えるため行数 assert (MG-6) が構造的に
                    # 盲目で、CR がセル内に残ると下流の universal-newline 読みが
                    # 行を倍化させる (実測: 4 行が 7 行に見える・例外なし)。
                    # 今日の writer は全て newline="" + 数値セルなので到達しないが、
                    # 到達したときの症状が「黙って壊れた CSV」なのでここで断つ。
                    buf.append(opts.delimiter.join(f.rstrip("\r\n") for f in fragments))
                    if len(buf) >= _FLUSH_ROWS:
                        out.write("\n".join(buf) + "\n")
                        buf.clear()
                    row += 1
                if buf:
                    out.write("\n".join(buf) + "\n")
        finally:
            for handle in handles:
                handle.close()

    # ─── 列ブロックパイプライン (E-4b spec §5.3) ───────────────────────────────

    @staticmethod
    def _require_single_value_column(sig: Signal) -> None:
        """1 時刻 1 値でない列 (配列/構造化の親) を拒否する (E-3 C-d)。

        ここは ``CsvExporter`` を直接呼ぶ経路の最後の砦で、numpy の生 TypeError
        ("float() argument must be ... not 'list'") を意味の分かる日本語エラーへ
        変える (値を読まずに親を弾くのは ``Session._reject_container_channels``
        の役目)。

        判定は ``sorted_view()`` ではなく ``values`` で行う。**構造化の親では
        sorted_view 自身が先に落ちる** — ``astype(np.float64)`` が複合 dtype を
        キャストできず ``TypeError: Cannot cast array data from
        dtype([('x','<f8'),('y','<f8')])`` になり、この層が置き換えるはずの生
        numpy エラーがそのまま出てしまう。**構造化の親は ndim == 1** (複合は
        shape でなく dtype 側にある) ので、``ndim`` だけを見ると配列の親しか
        捕まらない。

        呼び出し位置は ``_write_block_temp`` の**行組み立ての前**。E-4b Task 7 で
        「export 冒頭の全信号一括検査 (旧 ``_require_single_value_columns``)」が
        消えたが、拒否が ``sorted_view`` より前に来る不変条件は保たれている
        (``test_exporter_writes_nothing_when_rejected`` の spy が pin)。
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
            # `tolist()` は union 全体 (行数ぶん) を Python float のリストへ一括
            # 実体化する唯一の非ストリーミング箇所。prod 実測 ~25.7k union 行
            # なら無視できるサイズ (数百 KB) だが、ULP 分裂 (spec §1・C-1) が
            # 多いデータセットは union が信号本数に近い倍率まで膨らみうるので、
            # そこだけはこの一括変換のコストが目立ちうる。列ブロック側
            # (`_write_block_temp`) は numpy 配列のまま持ち回るのと非対称。
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
