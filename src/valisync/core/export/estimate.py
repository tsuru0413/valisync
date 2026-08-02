"""エクスポートの事前見積 (E-4b T-UX・spec §5.5 / ユーザー決定 B2)。

**この module は値を読まない** — ``Signal.values`` / ``.array()`` / ``sorted_view()``
をどの経路からも呼ばない (spec §6 の全タスク共通制約)。見積が値を読むと「見積のために
10 GB 読む」形になり、B2 が減らそうとしている待ちを見積自身が作る。触ってよいのは
master (``Signal.timestamps`` — ロード時点で既にメモリに在る) と列構造 (ColumnRecord)
だけ。列の**鋳造**もしない: 鋳造は E-4a の LRU 枠を食い、プロット中でない列を押し出す。

**係数は Task 11 (T-M・2026-08-02) が prod_demo 実測 2 点 (全列 ~66% 空セル・単一
master 部分集合 0% 空セル) で検定済み**である (spec §5.5「係数は quick_demo 由来の
まま出荷しない」)。合成由来の単価はこのシリーズで 3 回桁を外している
(channel_cache.py の evict 単価コメント参照) ので、検定前の値を受け入れ帯に使わない
という方針は据え置き — 検定後の現在値は実測の裏付けがある。出典と算術を定数の隣に
残すのは、次に測り直すときに「何を測り直せばよいか」が数字だけからは復元できない
ため。

**Task 11 レビュー是正 (2026-08-02・4 度目の罠)**: 初版の読み項は「幅 1,100 の
最広チャンネル 1 本」の cold select 単価を**全チャンネルへ一律適用**しており、
scalar チャンネル (4,004/4,324 本) で ~21 倍の過大見積になっていた
(旧「自己無矛盾性チェック」は read_a を仮定した恒等式で、読み単価そのものの
証拠ではなかった — レビュー C1)。読み項は scalar/wide の**チャンネルクラス**別に
分け、書き項の 2x2 較正はこの是正後の読み項で解き直した。詳細は各定数の直上
コメント。
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
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

# 読み: E-4a 以降の読みは **物理チャンネル単位** (1 select + k スライス) なので、
# これは「列単価」ではなく **チャンネル単価** として使う。spec §5.5 の字面
# (cold 列数 x 列単価) をそのまま実装すると、幅 1,100 のチャンネルを 1,100 回
# 読む前提になり prod 全列で ~29 時間 (330,004 列 x 旧単価 0.316 s ≈ 104,281 s ―
# **Task 11 実測 (46-48 分) の ~38 倍**。§1 の初版はここを未検証の 18.4 分
# 外挿と比較して「~95 倍」としていたが、その外挿自体が実測で反証されている
# ので比較基準は実測値に差し替える) を提示する = 見積が桁で嘘をつく。
#
# **Task 11 レビュー是正 (2026-08-02・C1)**: 初版はここを単一定数 0.316 s/channel
# (E-4a T5 が測った「幅 1,100 の最広チャンネル 1 本」の cold select) にして
# 全チャンネルへ一律適用していたが、scalar (1 リーフ) と wide (2+ リーフ) は
# asammdf の decode コストが構造的に別物 (~480 倍差・spike §9-4: prod scalar
# 0.67ms 対 prod wide 338.2ms) で、単一単価は scalar 側 (4,324 本中 4,004 本) を
# ~21 倍過大にしていた (旧「自己無矛盾性チェック」は read_a を仮定して VALUE を
# 逆算し、その VALUE で read_a を再現するだけの恒等式 — 読み単価そのものの
# 独立検証にはなっていなかった)。
#
# **再測定 (prod_demo・fresh process per class・全数 = サンプリング誤差ゼロ)**:
# ``handle.mdf.select`` を ``copy_master=False`` で直接呼ぶ (E-4a T5 の測定手法・
# チャンネルキャッシュを経由しない・``scripts/measure_lazy_footprint.py
# --export --read-class {scalar|wide}``)。
#   scalar (leaf_count==1・n=4,004/4,004 全数) 平均 5.5474 ms
#   wide   (leaf_count>1・n=320/320 全数・平均 leaf_count=1,018.8) 平均 160.61 ms
#   (レビュアーの 25/200 本サンプル実測 5.74ms/127.7ms と同じ桁・全数測定は
#   wide 側が右に裾を引く分布 (最大 575.8ms) なのでサンプル平均よりやや高い)。
#
# **適用域注記 (Task 11 再レビュー N1)**: wide 単価の母集団は prod_demo の
# leaf_count 分布に限られ、その内訳は {1000: 260 本, 1100: 60 本} — **2〜999
# leaves のチャンネルは母集団に 1 本も無い**。コストは幅にほぼ比例しない
# (leaf_count=1 → 1,019 で 28.9 倍・幅は 1,019 倍) ため固定費支配であり、
# 細い wide (leaf_count 2〜999 程度) にこの単価を適用すると過大請求になる:
# quick_demo の 8-leaf チャンネルは cold select 実測 1.293 ms だが、本単価は
# 161 ms を課金する (~124 倍過大)。過大方向の誤りは確認ダイアログを出す
# 閾値 (CONFIRM_THRESHOLD_S) に対しては安全側 (見積が実態より重く出て、
# 確認を余分に出す方向) だが、絶対時間の見積としては信頼できない。恒久対応は
# leaf_count (またはバイト数) による内挿だが、本増分の範囲外 (未着手)。
_READ_S_PER_COLD_SCALAR_CHANNEL: Final = 0.00555
_READ_S_PER_COLD_WIDE_CHANNEL: Final = 0.161

# 書き: **2 項モデル** (全セル基礎項 + 値セル増分項)。空セルと値セルは構造的に
# 単価が違う — `_write_block_temp` の行ループは `_fmt_value(vals[i], opts) if
# present[i] else ""` で、空セルは `present[i]` の索引と "" だけ、値セルはそれに
# 加えて `vals[i]` の索引・float 化・shortest round-trip repr・最小クォートを払う。
#
# **Task 11 (T-M・2026-08-02) 実測較正**: 空セル率が異なる 2 点を prod_demo 1 点
# 実走の副産物として同一ファイルから取った (I10 — 読み支配/書き支配の 2 形を
# 混ぜない)。
#   点 (a) 全列 (330,004 列・空セル率 65.89%・rows=12,012・total_cells=
#       3,964,008,048・nonempty=1,352,208,000)。実測 actual_wall = 2,903.69 s
#       (= 48.4 分。旧見積 (read+write) 合算 2,469.8 s に対し実測比 1.176)。
#   点 (b) 単一 master 部分集合 (Prod10Wide_0000 の全列 1,100・空セル率 0%・
#       rows=12,000・total_cells=nonempty=13,200,000)。実測 actual_wall =
#       15.51 s (旧見積合算 7.01 s に対し実測比 2.21-2.32 — **合算では近く見えた
#       点 (a) の裏で、書き支配の点 (b) は 2 倍以上外れていた** — I10 が警告した
#       とおり、合算だけの検定では見逃す桁のズレがここに出る)。
#
# **Task 11 レビュー是正 (2026-08-02・C1)**: 較正は 2x2 連立
# (total_cells*BASE + nonempty_cells*VALUE = write_time) を解く。write_time は
# 各点の actual_wall から読み時間 (点 (a) = 4,004*SCALAR + 320*WIDE ≈ 73.61 s・
# **丸め前の実測平均 5.5474ms/160.61ms を使用** — 上のコメントに残した丸め済み
# 定数 0.00555/0.161 で計算すると 73.74 s になる (Task 11 再レビュー N3: 較正は
# 丸め前の値を使ったので、電卓で再現したい場合はこちらの平均を使うこと)。
# 点 (b) = 1*WIDE ≈ 0.161 s — 上の再測定済みチャンネルクラス単価を使う) を
# 差し引いて得る。初版は read_a を旧の一律単価 (0.316 x 4,324 = 1,366.4 s) で
# 差し引いており、write_time_a が ~1,464 s 過小になって BASE が偽の負値
# (物理的に不能) に落ち、それを 0 へクランプしていた — **BASE=0 は読み項の
# 過大推定が書き項の較正へ漏れた結果**であって実測ではなかった (レビュー指摘)。
# 是正後の read_a (~73.6 s) で解き直すと:
#   BASE = 4.815e-7 s/セル ・ VALUE = 6.813e-7 s/セル (負値なし・クランプ不要)。
#   点 (a)/(b) の actual_wall を厳密に再現 (2x2 連立の定義上・残差 0)。
#   **削除済みだった独立 micro-bench** (空セル 333.6 ns・値セル増分 722.8 ns =
#   3.336e-7 / 7.228e-7 s/セル) と桁・比率とも近い (旧 BASE=0 が見せていた
#   「BASE は無視できる」という結論は読み項の仮定が言わせていたに過ぎない)。
#
# **既知の限界 (advisory)**: 2 点とも空セル率 0-66% の範囲でしか検証していない。
# 空セル率が 90% 超のような極端な出力では外挿誤差が広がりうる (受け入れ基準
# G4/G5 はこの範囲外を要求しないため出荷は妨げない)。
_WRITE_S_PER_CELL_BASE: Final = 4.815e-7
_WRITE_S_PER_CELL_VALUE: Final = 6.813e-7

# 値セルの平均文字数。spec §1 で「uint8 量子化の repr 長 4.57 文字」を実測済み
# (初版の 18.63 は反証された)。**Task 11 (T-M) が prod_demo 実測で再検定**:
# bytes_ratio (実バイト/推定バイト) は点 (a) 全列で 1.058・点 (b) 単一チャンネル
# 部分集合で 1.075 — いずれも 1.0±0.3 の帯に収まるため据え置き。
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
    est_write_s: float  # 推定 (2 項: 全セル x 基本単価 + 非空セル x 値単価)


def estimate_export(
    session: Session,
    keys: Sequence[str],
    options: CsvExportOptions,
    *,
    channel_columns: Mapping[str, int] | None = None,
) -> ExportEstimate:
    """列キー集合から出力の規模を見積もる (**値を読まない・鋳造しない**)。

    ``keys`` だけを見る — ``ExportRequest.extra_signals`` (Derived の escape hatch・
    spec §5.2 [I-3]) は数えない。今日の GUI 経路 (``ExportCsvDialog``) は extras を
    1 本も作らないので B2 が提示する「正確値」は GUI 上では正確だが、直呼びで
    extras を渡すと行数/列数がその分だけ**過小**になる (Task 9/11 への繰越)。
    この限界は **条件つき不変条件**として名前を付けておく: GUI が組んだ要求では
    ``est.columns == len(req.keys)`` が成り立ち、それが `_run_export` の D5 門番
    (``estimate_output_bytes(est.rows, est.columns)`` が core の門番を上界包含する)
    の前提になっている。extras が到達可能になった時点でこの前提は**無効**なので、
    Task 9/11 は D5 の門番を見直すこと (extras 込みの列数で上界を取り直す)。

    *channel_columns* は ``{名前空間つき物理チャンネルキー: 選択列数}``。渡されると
    列 -> チャンネルの解決 (``channel_key_of``) を **1 回も行わない**。prod で
    330,004 列を 1 本ずつ解決すると 2.6 s かかり、GUI スレッドで呼ぶ本経路が
    そのまま「エクスポートを押すと 3 秒固まる」になる。``ExportCsvDialog`` は
    選択を物理チャンネル 1 行 = 1 エントリで持っている (spec §5.6) ので、この表は
    そこでは**ただで手に入る** — 作るのでなく持っているものを渡す口。

    ``options.use_unified_timeline`` は見ない: 共有タイムライン形では全 master が
    同一内容なので union は master そのものと一致し、行数は同じになる (一致しない
    入力は書き手が ``_require_shared_timeline`` で拒否する)。
    """
    key_tuple = tuple(keys)
    columns = len(key_tuple)
    if columns == 0:
        return ExportEstimate(0, 0, 0.0, 0, 0.0, 0.0)

    # 1) 列 -> 物理チャンネル。呼び出し側が表を持っているならそれを使う (GUI の
    #    本経路)。合計が列数と一致しない表は**信用しない**: 空セル率と行数は B2 が
    #    「正確値」として提示するので、ヒントの取り違えで黙って嘘をつくより解決し
    #    直す方がよい (遅いが正しい)。空 dict (ask() を差し替えたテスト・表を持たない
    #    直呼び) もこの一致検査で自然にフォールバックへ落ちる。
    cols_per_channel: dict[str, int]
    used_hint = channel_columns is not None and sum(channel_columns.values()) == columns
    if used_hint and channel_columns is not None:
        cols_per_channel = dict(channel_columns)
    else:
        # フォールバック: channel_key_of は ColumnRecord の最長一致だけを見る
        # (Task 6 のブロック割当と **同じ解決器** — 2 つ持つと見積と出力がずれる)。
        # None へのフォールバックが `key` そのものなのは、ColumnRecord を持たない
        # グループ (CSV/Derived) では 1 信号 = 1 列で列キーがそのままチャンネルキー
        # だから — 書き手の `scan_masters` も同じ形のフォールバック
        # (`metadata.get("physical_channel", sig.name)`) を持つ。ここで諦めると
        # CSV だけの選択が「0 行 0 列」になる。
        # **この枝は prod の本経路ではない**: 実測 330,004 列で 2.6 s かかり、
        # GUI スレッドで呼ぶ `MainWindow.export_csv` がそのまま「エクスポートを
        # 押すと 3 秒固まる」になる。表を渡す経路 (GUI) はこの解決を 1 回も
        # 行わない。
        # **表を渡しても消えない別のコストがある**: ColumnRecord を持たない
        # グループ (CSV/Derived) では `channel_master` が信号名の線形走査へ
        # 落ちるので、列数 N の CSV は「チャンネル数 x 信号数」= O(N^2) になる
        # (本機実測・表あり/なしでほぼ同値: 500 列 5.9/5.3 ms・2,000 列
        # 74.8/67.5 ms・5,000 列 458/442 ms)。実 ADAS CSV の列幅 (数十〜数百)
        # では無視できるが、数千列の CSV が現れたら索引化が要る
        # (`signal_group_manager.channel_master` の走査側に同じ注記あり)。
        cols_per_channel = {}
        for key in key_tuple:
            channel = session.channel_key_of(key) or key
            cols_per_channel[channel] = cols_per_channel.get(channel, 0) + 1

    # 2) チャンネル -> master。identity dedup は union と同じ規則 (spec §5.4)。
    def _masters_of(
        table: dict[str, int],
    ) -> tuple[dict[int, np.ndarray], dict[int, int], int, int, int]:
        masters: dict[int, np.ndarray] = {}
        cols_per_master: dict[int, int] = {}
        lazy_scalar_channels = 0
        lazy_wide_channels = 0
        resolved_cols = 0
        for channel, n_cols in table.items():
            master = session.channel_master(channel)
            if master is None:
                continue  # アンロード済み / 未知キー: master を持たない
            resolved_cols += n_cols
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
                # **Task 11 レビュー C1 是正**: scalar/wide でチャンネル単価が
                # ~480 倍違うので、ここでクラスを分けて数える (単一単価一律の
                # 過大見積を再導入しない)。
                if session.channel_leaf_count(channel) > 1:
                    lazy_wide_channels += 1
                else:
                    lazy_scalar_channels += 1
        return (
            masters,
            cols_per_master,
            lazy_scalar_channels,
            lazy_wide_channels,
            resolved_cols,
        )

    (
        masters,
        cols_per_master,
        lazy_scalar_channels,
        lazy_wide_channels,
        resolved_cols,
    ) = _masters_of(cols_per_channel)
    if used_hint and resolved_cols != columns:
        # 関連性の破れ (T8 再レビュー Minor 1): 総和の一致は「量」しか見ておらず、
        # 総和が合っていてもキーが誤っていれば channel_master が解決できない列が
        # 出る — そのまま進むと B2 が「正確値」と名乗る行数/空セル率が黙って嘘に
        # なる (実測: 誤キーのヒントで rows=0)。解決不能が混ざったヒントは捨てて
        # 自己解決へ落とす (遅いが正しい)。happy path はこの分岐に入らないので
        # コストゼロ。なお「本当にアンロードされた列」もここでフォールバックする
        # が、フォールバック側も同じ列を解決できず同じ結果に収束するだけで害は
        # 無い (2 回目の _masters_of が僅かに走るのみ)。
        cols_per_channel = {}
        for key in key_tuple:
            channel = session.channel_key_of(key) or key
            cols_per_channel[channel] = cols_per_channel.get(channel, 0) + 1
        masters, cols_per_master, lazy_scalar_channels, lazy_wide_channels, _ = (
            _masters_of(cols_per_channel)
        )

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
    nonempty_cells = filled  # 正確値 (率と同じ 1 つの走査から出る)
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
        # クラス別単価 (レビュー C1 是正): 単一単価一律だと scalar 側が
        # ~21 倍過大になる (定数コメント参照)。
        est_read_s=(
            lazy_scalar_channels * _READ_S_PER_COLD_SCALAR_CHANNEL
            + lazy_wide_channels * _READ_S_PER_COLD_WIDE_CHANNEL
        ),
        # 全セルに掛かる基礎項 + 値セルにだけ掛かる増分項。1 項にすると空セルが
        # 支配的な出力 (prod は 66% が空) で過大/過小いずれかに桁で寄る。
        est_write_s=(
            total_cells * _WRITE_S_PER_CELL_BASE
            + nonempty_cells * _WRITE_S_PER_CELL_VALUE
        ),
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
