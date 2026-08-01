"""統合タイムライン (union) の合成と列の引き当て (E-4b spec §5.4)。

**純関数のみ**: ``Signal`` も ``Session`` も import しない。ここが触るのは numpy
配列だけで、値の実体化 (``sorted_view()`` / ``.values``) を誘発する経路を 1 本も
持たない — 見積 (T-UX) が「値を読まない」契約を守れるのは、行数と空セル率が
このモジュールだけで出るからである。

**union に NaN が入らないのは ``Signal.__init__`` (models/signal.py:80-82) の
非有限時刻拒否への依存**。あの拒否が緩むと ``np.unique`` は NaN を畳めず
(NaN != NaN)、末尾に NaN 行が並んで「ほぼ全列が空」の行が黙って増える。
依存を切るときは、tolerance ではない明示的な非有限除去をここへ入れること。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def union_timeline(masters: Sequence[np.ndarray]) -> np.ndarray:
    """*masters* の和集合 (昇順・重複なし・read-only)。

    **dedup は ``id()`` (identity) であって値比較ではない** (spec §5.4)。
    ``np.array_equal`` で畳むと ULP 差 (``3*0.1 == 0.30000000000000004`` と
    ``30*0.01 == 0.3``) の行が黙って畳まれ、時刻が静かにずれる (C3)。identity だけ
    だと「別オブジェクト・同値」の master で dedup が効かないが、**効かないのは
    コストだけで正しさは保たれる** — 安全側に倒す。

    prod で効くのは、ローダーが仮想グループごとに master を 1 本読んで全 Signal へ
    **同一オブジェクトのまま**渡すから (``mdf_loader``・``_mint_column`` は
    ``parent.timestamps`` をそのまま渡す)。330,004 列に対し master オブジェクトは
    5 個で、1.352e9 要素の concat が 25,680 要素 (205 KB) になる。
    **5 個は生成デモの人工事実** — 実 CANape の独立ラスタでは O(10^2-10^3) になり
    うる (spec §9-9)。

    入力は生の ``Signal.timestamps`` でよい (``sorted_view()[0]`` を要求しない):
    ``np.unique`` が昇順・一意へ畳むので、非単調/重複 ts があっても結果は
    ``sorted_view`` 由来の union と一致する (test-lock:
    ``test_union_from_raw_masters_equals_union_from_sorted_views``)。
    """
    seen: set[int] = set()
    uniques: list[np.ndarray] = []
    for master in masters:
        if id(master) in seen:
            continue
        seen.add(id(master))
        uniques.append(master)
    if not uniques:
        # 空選択 (列 0 本)。np.concatenate([]) は ValueError なのでここで返す。
        empty = np.empty(0, dtype=np.float64)
        empty.flags.writeable = False
        return empty
    # concatenate は必ず新配列を返すので、下の凍結が呼び出し側の master を
    # 巻き添えにすることはない (master は loader/GUI と共有の長寿命オブジェクト)。
    union = np.unique(np.concatenate(uniques))
    # 下流 (ブロック writer・マージ器) は行範囲のスライスを共有するだけで、
    # 誰も書き換えてよくない。凍結すると in-place 変形が loud-fail になる。
    union.flags.writeable = False
    return union


def canonical_master(master: np.ndarray) -> np.ndarray:
    """``Signal.sorted_view()[0]`` と同一内容の時刻軸を **値を読まずに** 返す。

    ``sorted_view`` は安定ソート + 同値 ts の keep-last で「昇順・重複なし」を
    作る。**時刻軸だけを見れば** 結果は ``np.unique`` と一致する (どちらも昇順・
    一意)。共有タイムライン前提の検証 (spec §5.2 MG-6・master のみで判定し値を
    読まない) はこれで足りる。

    単調な master は ``sorted_view`` が元配列をそのまま返すので、ここも
    **同一オブジェクト**を返す — ``union_timeline`` の identity dedup が
    canonical 化の後でも効き続けるための前提条件 (test-lock:
    ``test_canonical_master_preserves_identity_dedup_in_union``)。

    **逆側の罠 (T5 レビュー Minor 2)**: 非単調 master は呼び出しごとに
    **新しい** ``np.unique`` 配列を返す。列ごとに呼ぶと共有 master が N 個の
    別オブジェクトに化け、``union_timeline`` の identity dedup が全滅する
    (prod なら 1.35e9 要素 concat の復活)。**master ごとに 1 回だけ呼び、
    ``id(master)`` で結果を使い回すこと** — Task 6 の ``scan_masters`` と
    Task 8 の見積はどちらもこの規約に従う。
    """
    if len(master) < 2 or bool(np.all(np.diff(master) > 0)):
        return master
    return np.unique(master)


def _align(
    sig_ts: np.ndarray, union_ts: np.ndarray
) -> tuple[np.ndarray | None, np.ndarray]:
    """``(索引, 存在フラグ)`` — **存在判定の唯一の実装**。

    ``hit_mask`` (見積が使う) と ``column_on_union`` (書き手が使う) がここを共有する。
    2 つ持つと「見積が数えた非空セル数」と「出力に実際に出る値」がずれ、B2 が
    提示する空セル率が嘘になる。索引が ``None`` = len 0 の信号 (全行 absent)。
    """
    n_rows = len(union_ts)
    if len(sig_ts) == 0:
        # len 0 の信号 (LD-09 のヘッダのみ CSV)。素朴な sig_ts[idx] は idx == 0 でも
        # IndexError になる (空配列には 0 番目も無い) ので、構造的に断つ [M-4]。
        return None, np.zeros(n_rows, dtype=bool)
    idx = np.searchsorted(sig_ts, union_ts, side="left")
    # 末尾越え (union の最後が信号の最後より後) は idx == len(sig_ts) になり、
    # そのままでは IndexError。clip してから **値の一致で** 判定する: clip 先の
    # 要素は union_ts と一致しないので present は False に落ちる (先頭側の
    # underrun も同じ理屈で False)。
    np.clip(idx, 0, len(sig_ts) - 1, out=idx)
    return idx, sig_ts[idx] == union_ts


def hit_mask(sig_ts: np.ndarray, union_ts: np.ndarray) -> np.ndarray:
    """*union_ts* の各行に *sig_ts* のサンプルが**在るか** (bool・長さ len(union_ts))。

    **値を読まない** — 引数に値配列を取らないのが契約そのもの。見積 (T-UX) が
    空セル率を「推定」でなく「正確値」として出せるのは、この関数が master だけで
    答えるから。**完全一致セマンティクス** (tolerance 禁止・spec §5.4)。

    *sig_ts* は ``canonical_master`` 済み (昇順・重複なし) を渡すこと。重複を含む
    生 master を渡すと ``side='left'`` が重複ランの**先頭**に当たり、``sorted_view``
    の keep-last (CAN の「最後に受けた値が勝つ」) と食い違う。
    """
    _idx, present = _align(sig_ts, union_ts)
    present.flags.writeable = False
    return present


def column_on_union(
    sig_ts: np.ndarray, sig_vals: np.ndarray, union_ts: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """*union_ts* の各行に対する ``(値, 存在フラグ)`` を searchsorted で引き当てる。

    **完全一致セマンティクス** (親 spec §6 確定・tolerance 禁止): 値が出るのは
    ``sig_ts`` にその時刻が**ビット一致**で在る行だけで、無ければ空セル。旧実装の
    ``dict(zip(ts.tolist(), vs.tolist()))`` と判定は同じ (Python float の
    ハッシュ一致 == float64 の ``==``) で、実測 97 B/サンプル -> 8 B/サンプルになる。

    前提: *sig_ts* は ``Signal.sorted_view()[0]`` (昇順・重複なし)・*union_ts* は
    昇順。重複を含む生 master を渡すと ``side='left'`` が重複ランの**先頭**に当たり、
    ``sorted_view`` の keep-last (CAN の「最後に受けた値が勝つ」) が崩れる。

    返す値は行数が必ず ``len(union_ts)`` に揃う (存在しない行の値は未定義・
    呼び出し側はフラグを見てから読むこと)。dtype は ``sig_vals`` のまま
    (len 0 信号のみ float64 — 全行 absent なので値は読まれない前提。列をまたいで
    ``vals`` を stack する下流が現れたら LD-09 形で無言 upcast になる点に注意)。

    存在フラグは ``hit_mask`` と**同一の内部実装** (``_align``) から来る。
    ``hit_mask`` を呼び直さないのは、prod (union 12,012 行 x 330,004 列) で
    searchsorted が二重に走るのを避けるため — 共有しているのは実装であって
    呼び出しではない、という点だけが逸脱で、「存在判定は 1 実装」の契約は保たれる。
    """
    idx, present = _align(sig_ts, union_ts)
    vals = np.zeros(len(union_ts), dtype=np.float64) if idx is None else sig_vals[idx]
    vals.flags.writeable = False
    present.flags.writeable = False
    return vals, present


def row_range(
    union_ts: np.ndarray, time_start: float | None, time_end: float | None
) -> tuple[int, int]:
    """閉区間 ``[time_start, time_end]`` を覆う行範囲 ``[lo, hi)`` (None は無制限)。

    行ごとの ``_in_range`` 比較と**同じ行集合**を searchsorted 1 回で出す。sides は
    閉区間の保存則そのもの (spec M-3): lo は ``side='left'`` で time_start に一致
    する行を**含み**、hi は ``side='right'`` で time_end に一致する行を**含む**。
    取り違えると両端が 1 行ずつ欠ける (境界にサンプルが無い fixture では緑のまま)。
    """
    lo = (
        0
        if time_start is None
        else int(np.searchsorted(union_ts, time_start, side="left"))
    )
    hi = (
        len(union_ts)
        if time_end is None
        else int(np.searchsorted(union_ts, time_end, side="right"))
    )
    # CsvExportOptions.__post_init__ が start > end を拒否するので通常は起きないが、
    # 直接呼びで空範囲になっても負の長さを返さない。
    return lo, max(lo, hi)
