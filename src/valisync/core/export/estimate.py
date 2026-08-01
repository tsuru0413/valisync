"""エクスポートの事前見積 (E-4b T-UX・spec §5.5 / ユーザー決定 B2)。

**この module は値を読まない** — ``Signal.values`` / ``.array()`` / ``sorted_view()``
をどの経路からも呼ばない (spec §6 の全タスク共通制約)。見積が値を読むと「見積のために
10 GB 読む」形になり、B2 が減らそうとしている待ちを見積自身が作る。触ってよいのは
master (``Signal.timestamps`` — ロード時点で既にメモリに在る) と列構造 (ColumnRecord)
だけ。列の**鋳造**もしない: 鋳造は E-4a の LRU 枠を食い、プロット中でない列を押し出す。

**係数は Task 11 (T-M) が prod_demo 1 点で検定するまで暫定**である (spec §5.5
「係数は quick_demo 由来のまま出荷しない」)。合成由来の単価はこのシリーズで 3 回
桁を外している (channel_cache.py の evict 単価コメント参照) ので、検定前の値を
受け入れ帯に使ってはならない。出典と算術を定数の隣に残すのは、検定のときに
「何を測り直せばよいか」が数字だけからは復元できないため。
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np

from valisync.core.export.csv_exporter import TEMP_AMPLIFICATION
from valisync.core.export.timeline import (
    canonical_master,
    hit_mask,
    row_range,
    union_timeline,
)

if TYPE_CHECKING:
    from valisync.core.export.csv_exporter import CsvExportOptions
    from valisync.core.session import Session

__all__ = [
    "CONFIRM_THRESHOLD_S",
    "TEMP_AMPLIFICATION",
    "ExportEstimate",
    "disk_shortfall",
    "estimate_export",
]

# 読み: E-4a T5 実測の cold 1 列 316 ms。E-4a 以降の読みは **物理チャンネル単位**
# (1 select + k スライス) なので、これは「列単価」ではなく **チャンネル単価** として
# 使う。spec §5.5 の字面 (cold 列数 x 列単価) をそのまま実装すると、幅 1,100 の
# チャンネルを 1,100 回読む前提になり prod 全列で ~29 時間 (§1 の外挿 18.4 分の
# ~95 倍) を提示する = 見積が桁で嘘をつく。逸脱を spec §5.5 へ追記するのは Task 11。
_READ_S_PER_COLD_CHANNEL: Final = 0.316

# 書き: spec §1 の prod 全列外挿 (出力 ~10.1 GB・純 Python ~18.4 分) と平均セル長
# 4.57 文字から 1,104 s / (10.1e9 B / 5.57 B) ~= 6.1e-7 s/セル。per-cell repr の
# 単価 (0.3-1 us) とも桁が合う。
_WRITE_S_PER_CELL: Final = 6.1e-7

# 値セルの平均文字数。spec §1 で「uint8 量子化の repr 長 4.57 文字」を実測済み
# (初版の 18.63 は反証された)。
_AVG_VALUE_CHARS: Final = 4.57

# 時刻セルは float64 の shortest round-trip repr で最長 17 文字 + 余裕 1。1 列しか
# 無いので過大評価の寄与は小さく、est_bytes は D5 の検査に使うため **安全側 (過大)**
# に倒す。
_AVG_TIME_CHARS: Final = 18.0

# ヘッダ 1 セルの平均文字数 (表示名 + 区切り)。単位行が有効ならもう 1 行ぶん。
_AVG_HEADER_CHARS: Final = 24.0

# 確認ダイアログを出す閾値。**時間ベース** (spec I10) — サイズ基準にすると
# 「カーソル A-B x 全列」(出力 2,057 B・読み 6.523 s の実測ケース) が素通りする。
CONFIRM_THRESHOLD_S: Final = 5.0

# 多段マージの中間 temp を含むディスクピーク係数 (spec §5.3) は `csv_exporter.py` の
# `TEMP_AMPLIFICATION` を **import して再輸出**している (上の import 行)。
# **定数の実体は 1 つだけ**: GUI 側 (disk_shortfall) と core 側 (_require_disk_space)
# が別々に 2.3 を持つと、片方だけ Task 11 の検定で更新されたときに
# 「GUI の D5 を通過 -> 確認 Yes -> core で ValueError」という UX 破綻窓が開く。
# ここへ再輸出するのは共有インターフェース契約が `estimate.TEMP_AMPLIFICATION` を
# 名指ししているため (テストも `from ...estimate import TEMP_AMPLIFICATION` で読む)。


@dataclass(frozen=True)
class ExportEstimate:
    """B2 が人に提示する 5 点 + 内訳 (共有契約の逐語形)。"""

    columns: int  # 正確
    rows: int  # 正確 (union 長・master のみで計算)
    empty_ratio: float  # 正確 (searchsorted ヒット数から)
    est_bytes: int  # 推定
    est_read_s: float  # 推定 (cold チャンネル数 x チャンネル単価)
    est_write_s: float  # 推定 (セル数 x セル単価)


def estimate_export(
    session: Session, keys: Sequence[str], options: CsvExportOptions
) -> ExportEstimate:
    """列キー集合から出力の規模を見積もる (**値を読まない・鋳造しない**)。

    ``keys`` だけを見る — ``ExportRequest.extra_signals`` (Derived の escape hatch・
    spec §5.2 [I-3]) は数えない。今日の GUI 経路 (``ExportCsvDialog``) は extras を
    1 本も作らないので B2 が提示する「正確値」は GUI 上では正確だが、直呼びで
    extras を渡すと行数/列数がその分だけ**過小**になる (Task 9/11 への繰越)。

    ``options.use_unified_timeline`` は見ない: 共有タイムライン形では全 master が
    同一内容なので union は master そのものと一致し、行数は同じになる (一致しない
    入力は書き手が ``_require_shared_timeline`` で拒否する)。
    """
    key_tuple = tuple(keys)
    columns = len(key_tuple)
    if columns == 0:
        return ExportEstimate(0, 0, 0.0, 0, 0.0, 0.0)

    # 1) 列 -> 物理チャンネル。channel_key_of は ColumnRecord の最長一致だけを見る
    #    (Task 6 のブロック割当と **同じ解決器** — 2 つ持つと見積と出力がずれる)。
    #    None へのフォールバックが `key` そのものなのは、ColumnRecord を持たない
    #    グループ (CSV/Derived) では 1 信号 = 1 列で列キーがそのままチャンネルキー
    #    だから — 書き手の `scan_masters` も同じ形のフォールバック
    #    (`metadata.get("physical_channel", sig.name)`) を持つ。ここで諦めると
    #    CSV だけの選択が「0 行 0 列」になる。
    cols_per_channel: dict[str, int] = {}
    for key in key_tuple:
        channel = session.channel_key_of(key) or key
        cols_per_channel[channel] = cols_per_channel.get(channel, 0) + 1

    # 2) チャンネル -> master。identity dedup は union と同じ規則 (spec §5.4)。
    masters: dict[int, np.ndarray] = {}
    cols_per_master: dict[int, int] = {}
    lazy_channels = 0
    for channel, n_cols in cols_per_channel.items():
        master = session.channel_master(channel)
        if master is None:
            continue  # アンロード済み / 未知キー: master を持たない
        mid = id(master)
        masters.setdefault(mid, master)
        cols_per_master[mid] = cols_per_master.get(mid, 0) + n_cols
        if session.is_lazy_channel(channel):
            # 実体化済み (CSV/Derived) のチャンネルは読み直さないので 0 秒。
            # **lazy を cold の代理にしている**: E-4a のチャンネルキャッシュに
            # 既に載っている (warm) チャンネルも lazy なので、読み項は安全側
            # (過大) へ倒れる。キャッシュを覗いて減算しないのは、pin の増減で
            # 見積が呼ぶたびに変わる数字になるより、常に上限を出す方が
            # 「思ったより早く終わった」に倒れて B2 の目的に合うため。
            lazy_channels += 1

    union = union_timeline(list(masters.values()))
    # 行範囲は **Task 5 の `row_range` をそのまま消費する** (自前で searchsorted を
    # 書き直さない — 見積と出力で行の切り方が 2 つになると、B2 が「正確値」と
    # 名乗る行数が出力とずれる)。sides は Task 5 のテストが pin 済み。
    lo, hi = row_range(union, options.time_start, options.time_end)
    rows_ts = union[lo:hi]
    rows = int(rows_ts.size)

    # 3) 空セル率は「各 master が union 窓の何行にヒットするか」の厳密和。
    #    **master ごとに 1 回**しか数えない (列ごとに hit_mask を呼ぶと prod で
    #    330,004 回 x 12,012 行の searchsorted になり、見積自身が perf バグになる)。
    filled = 0
    for mid, master in masters.items():
        # **canonical_master を通す**: `hit_mask` の契約は「昇順・重複なしの
        # sig_ts」で、生 master をそのまま渡すと `side='left'` が重複ランの先頭に
        # 当たり、書き手 (sorted_view の keep-last) と違う行を「在る」と数える。
        # 単調な master は同一オブジェクトが返るので支配的経路のコストはゼロ。
        # master ごとに 1 回だけ呼ぶのは canonical_master の docstring が要求する
        # 規約でもある (列ごとに呼ぶと非単調 master で identity dedup が全滅する)。
        filled += (
            int(np.count_nonzero(hit_mask(canonical_master(master), rows_ts)))
            * cols_per_master[mid]
        )
    total_cells = rows * columns
    empty_ratio = 0.0 if total_cells == 0 else 1.0 - filled / total_cells
    # master を持たない列 (アンロード済み) は filled に寄与しないので、僅かに
    # 過大へ倒れうる。率なので [0, 1] へ丸める (負の空セル率を人に見せない)。
    empty_ratio = min(1.0, max(0.0, empty_ratio))

    delimiter_len = len(options.delimiter)
    non_empty = 1.0 - empty_ratio
    per_row = (
        _AVG_TIME_CHARS
        + columns * (delimiter_len + _AVG_VALUE_CHARS * non_empty)
        + 1  # 行末 LF (据え置き・spec §5.1)
    )
    header_lines = 1 + (1 if options.unit_row else 0)
    header_bytes = 3 + header_lines * (  # 3 = UTF-8 BOM (spec §5.1-2)
        columns * (_AVG_HEADER_CHARS + delimiter_len) + 16
    )

    return ExportEstimate(
        columns=columns,
        rows=rows,
        empty_ratio=empty_ratio,
        est_bytes=int(header_bytes + per_row * rows),
        est_read_s=lazy_channels * _READ_S_PER_COLD_CHANNEL,
        est_write_s=total_cells * _WRITE_S_PER_CELL,
    )


def disk_shortfall(output_path: Path, est_bytes: int) -> int:
    """D5: 必要量 (``TEMP_AMPLIFICATION`` x 推定出力) に対する不足バイト数。

    足りていれば 0。**これがエクスポートの唯一の拒否**なので、検査できない状況
    (存在しないボリューム・権限) では 0 を返して通す — 誤拒否を作ると「書けるのに
    書けないアプリ」になり、B2 の「情報提示して人が決める」という方針に反する。
    """
    required = int(est_bytes * TEMP_AMPLIFICATION)
    probe = output_path.parent
    # 保存先がまだ存在しない (これから mkdir する) 場合があるので、実在する
    # 祖先まで遡ってから測る。ボリューム自体が無ければ except 側へ落ちる。
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = int(shutil.disk_usage(str(probe)).free)
    except OSError:
        return 0
    return max(0, required - free)
