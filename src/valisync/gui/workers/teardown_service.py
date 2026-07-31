"""Off-UI-thread graveyard for freeing a closed file's ~10 GB in byte-budget
slices (FU-16). A closed file's Signal_Group is stashed here and drained a
budget's worth of bytes per zero-interval QTimer tick, so the event loop keeps
running between ticks and the UI stays responsive during the ~seconds of frees.

Runs entirely on the GUI thread (no worker thread): the freeze is per-tick byte
volume, not GIL contention (PoC verified) -- naive offthread is a GIL trap.
Slicing by BYTES (not signal count) bounds a single huge array to one tick.

A tick is bounded on THREE axes -- bytes, signal COUNT and elapsed time --
whichever is hit first (see the budget constants below for the WHY of each).
Bytes alone stopped being sufficient once loading went lazy: an unmaterialized
lazy signal is ~0 bytes on the books, so a 330k-shell group would drain in a
single tick (measured 649 ms) -- exactly the FU-16 freeze the pacing exists to
prevent. The byte axis is still what keeps one huge array in its own tick.

enqueue() is O(1) in signal count: it stores each group's signals as one list
(a single C-level `list(tuple)` copy) and defers ALL per-signal work -- nbytes
accounting and the frees themselves -- to _drain(). Touching every signal at
enqueue time (summing nbytes over 330k signals) was itself a ~320 ms freeze on
the closing thread (measured at 264k), which partly defeated the handoff; the
perf E2E at prod scale caught it. Keeping that work in _drain keeps sync-close
independent of data size.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QObject, QTimer

from valisync.core.models import Signal, SignalGroup, retained_bytes

# teardown が解放する対象。E-4a で ChannelSampleCache から回収した**生 ndarray**
# (RemovalResult.cached_arrays) が加わった — Signal の皮を持たないので、会計は
# 型で分岐する (_retained_bytes)。同じキューへ載せるのは、ペーシングの三軸
# (バイト / 信号数 / 経過時間) を配列にもそのまま適用したいから。
_Freeable = Signal | np.ndarray

_BYTE_BUDGET = 64 * 1024 * 1024  # 64 MiB per tick
# 未展開の遅延シェルはバイト会計上ほぼ 0 なので、バイト予算だけでは 330k シェルが
# 1 ティックで解放され実測 649ms 固まる (FU-16 の再来)。解放コストは個数にも比例
# するため、信号数の上限を第 2 の軸として持つ。
_SIGNAL_BUDGET = 8_000  # ユーザー決定 3 (変更不可・ハード上限)
# WHY (第 3 軸): 予算はどちらもコストの proxy でしかない。1 信号の解放コストは状態で
# 1.6us (未展開シェル) → 4.8us (展開値 + sorted/finite + range_stat_index) と約 3 倍
# 動き、バイト軸は RangeStatIndex のブロック配列を数えないので補償できない。実測:
# 8,000 シェル = 13-17ms だが 8,000 展開信号 (240 サンプル) = 24ms・+RSI = 28ms、
# 1,200 サンプルでは 6,990 信号 / 64MiB で 36ms (両予算とも充足したまま)。
# frame budget と単調な唯一の軸は経過時間なので、それを実効の一次軸にする。
# NOTE: 上の 1.6→4.8us は合成 fixture 由来で、実データでは下の _CLOCK_CHECK_EVERY
# ブロックの 8-27us/本 に置き換わる (最初のブロックで読み終えると桁を小さく持ち帰る)。
# また 0.008 は**スケジューリング**デッドラインであって達成される最大ティックでは
# ない — 実測の最大は ~14ms (下記の構造的な床)。
_TICK_DEADLINE_S = 0.008  # 半フレーム (60fps = 16.7ms)
# クロックを見る粒度 = デッドラインの行き過ぎ幅そのもの (最悪 _CLOCK_CHECK_EVERY-1
# 信号ぶんの解放がデッドライン超過後に走る)。値は**実測**で決める:
#   - 未展開シェル       1.6 us/本 (合成 fixture)
#   - 展開済み合成 fixture 3.0-4.8 us/本
#   - 展開済み prod リーフ 8-27 us/本 <- values + sorted/finite view + RSI を持つ
#     実データ (prod_demo 264,004 信号を実 GUI の unload 経路で計測)
# 旧値 256 は合成 fixture の 3.0-4.8us だけを根拠にしていた (行き過ぎ ~1.2ms 想定)
# が、実データは 3-5 倍高く行き過ぎは 4-7ms ⇒ 最大ティック 11.2-16.8ms と、この軸が
# 守るはずの 1 フレーム (16.7ms) に到達していた。32 なら最悪 27us/本 でも
# 31 * 27us = 0.84ms に収まり、最大ティックは ~8.8ms。
# 1 (毎回読む) にしないのは、1.6us/本 の未展開シェル regime では perf_counter
# 呼び出し自体が解放コストに対して無視できないから。加えて 32 未満に下げても
# 最大ティックは縮まない: 粒度 1 で計測すると prod_demo 264,004 本のうち**1 本だけ**
# 5.8ms かかる解放があり (残り全て <=0.6ms・p99 10us・gc=0 でヒープ返却由来)、
# それが 8ms 直前に始まれば粒度に関係なくティックは ~14ms になる (実測の最悪は
# 14.2ms — ストールの大きさは run ごとに揺れるので 13.8 は下限であって上界ではない)。
# つまり 最大ティック = デッドライン + 最大単発解放 が構造的な床で、粒度が支配するのは
# その手前まで (実測: 展開済み regime の定常ティックは 8.6-8.8ms = 8ms + <=0.84ms)。
# **バイト予算を絞ってもこの床は下がらない**: バイト軸はティックをデッドラインより
# 早く終わらせることしかできず、`デッドライン + 単発解放` を短縮できない (唯一
# 関係するのは「1 信号が巨大配列 1 本」の場合だが、それがまさに単発解放の床)。
_CLOCK_CHECK_EVERY = 32


class TeardownService(QObject):
    def __init__(
        self,
        on_finished: Callable[[str], None] | None = None,
        *,
        byte_budget: int = _BYTE_BUDGET,
        signal_budget: int = _SIGNAL_BUDGET,
        tick_deadline_s: float = _TICK_DEADLINE_S,
        now: Callable[[], float] = time.perf_counter,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_finished = on_finished
        self._budget = byte_budget
        self._signal_budget = signal_budget
        self._deadline = tick_deadline_s
        # クロックは注入可能 — テストは実時間で assert しない (マシン依存フレーク回避)。
        self._now = now
        # FIFO across groups: the front group drains fully before the next, so
        # the oldest closed file releases first. Order WITHIN a group is
        # irrelevant (all its signals free before on_finished fires), so _drain
        # pops from each list's end (O(1), no shifting).
        self._groups: deque[tuple[str, list[_Freeable]]] = deque()
        self._pending_signals = 0
        self._last_tick_bytes = 0
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._drain)

    def pending_signals(self) -> int:
        return self._pending_signals

    @property
    def last_tick_bytes(self) -> int:
        """直近ティックで計上したバイト数 (バイト軸の唯一の観測点)."""
        return self._last_tick_bytes

    def pending_bytes(self) -> int:
        # Computed lazily over the still-held signals rather than tracked from
        # enqueue, so enqueue stays O(1). O(remaining) per call -- fine for the
        # small groups in tests; the prod drain-wait polls pending_signals().
        seen: set[int] = set()  # 呼び出しごとに新規 (寿命規約は _drain と同じ)
        return sum(
            _retained_bytes(item, seen)
            for _key, items in self._groups
            for item in items
        )

    def enqueue(
        self,
        key: str,
        group: SignalGroup,
        columns: tuple[Signal, ...] = (),
        cached_arrays: tuple[np.ndarray, ...] = (),
    ) -> None:
        """*key* のグループ信号 + 鋳造列 (E-3) + キャッシュ配列 (E-4a) を 1 エントリで積む。

        ``columns`` は ``SignalGroup.signals`` の外に居る鋳造列
        (``RemovalResult.removed_columns``)。``cached_arrays`` は
        ``ChannelSampleCache`` から回収したデコード済みチャンネル配列
        (``RemovalResult.cached_arrays``) で、``columns`` に相乗りできない —
        こちらは Signal の皮を持たない**生 ndarray** だから (spec §5.7)。

        **同一エントリへ連結する**のが要点: ``on_finished`` はエントリごとに発火し、
        その宛先の ``AppViewModel.mark_released`` は初回 pop で確定するため、同じ key を
        2 エントリに分けると 1 本目の完了で releasing 行が消え、まだ残っているのに
        「解放完了」に見える。

        O(1) 契約は維持する: ``list(group.signals)`` も ``extend`` も C レベルの
        ポインタコピーだけで、信号の配列にも ndarray の ``nbytes`` にも一切触らない
        (会計と解放は _drain の担当のまま)。``columns`` は解決済み列 = プロット/読み値/
        エクスポートで触れた列だけで、全論理列ではない。**ただし「常に少ない」と
        読まないこと** — 反転後は ``group.signals`` が物理チャンネル数 (prod 4,324) まで
        縮む一方、``_resolved_by_key`` は全列を選ぶワークフロー (全選択エクスポート等) で
        論理列数 (prod 264k) へ向かって伸びうるので、``columns`` が支配項になりうる。
        ``cached_arrays`` の本数は予算で上界がつく (256 MB / 13.2 MB ≈ 19 本) ので、
        そもそも支配項にならない。
        """
        items: list[_Freeable] = list(group.signals)  # single C-level copy
        # extend は**空判定より前**に置く。後ろだと「signals が空で列/配列だけ残る」
        # グループが下の即時 finish 分岐に落ち、ペーシングを迂回して同期解放される
        # (実体化済みの列も 13.2 MB のチャンネル配列もバイトが重い)。
        # エントリ内の順序は無関係 — _drain は末尾から pop する。
        items.extend(columns)
        items.extend(cached_arrays)
        if not items:
            if self._on_finished is not None:
                self._on_finished(key)
            return
        self._pending_signals += len(items)
        self._groups.append((key, items))
        # NOTE: caller must not keep a ref to `group` / `columns` / `cached_arrays`
        # after this (it does not -- all three hang off the RemovalResult local that
        # falls out of scope); `items` becomes the sole owner, so popping from it
        # frees the arrays.
        if not self._timer.isActive():
            self._timer.start()

    def _drain(self) -> None:
        t0 = self._now()
        # seen はティック単位 (freed_bytes と同じ寿命)。id は生存中のオブジェクト間で
        # のみ一意なので、記録した配列より長生きする set は以後の全確保をエイリアス
        # する (実測 100% 再利用・memory gui_id_reuse_flake_object_recreation) —
        # ティックを跨ぐと後続グループが 0 バイト計上になりバイト軸が黙って死ぬ。
        # ティック内は安全: 会計対象の配列は全て live な Signal が保持しており、
        # _drain 内に「このティックが計上する」ndarray を新規確保する経路も無い。
        # ただし無条件ではない — グループ完了時に呼ぶ self._on_finished は**注入
        # コールバック**で確保を禁じられないため、契約は「on_finished は再入で
        # enqueue しないこと」(再入すると新しい信号が同じティックの会計へ入る)。
        # コールバック内の無関係な確保が解放済み id を再利用した場合は後続 1 本の
        # 計上が漏れうるが、向きはティックが長引く側 (予算に達しにくい) であって
        # 解放漏れにはならない。
        # 共有 master がティックごと 1 回計上される過大分は prod_demo で
        # 64MiB 予算の 0.3% (direction-safe)。
        seen: set[int] = set()
        freed_bytes = 0
        freed_signals = 0
        deadline_hit = False
        while (
            self._groups
            and freed_bytes < self._budget
            and freed_signals < self._signal_budget
            and not deadline_hit
        ):
            key, items = self._groups[0]
            while (
                items
                and freed_bytes < self._budget
                and freed_signals < self._signal_budget
            ):
                item = items.pop()
                # カウンタを pop の直後に更新するのは、会計が raise してもキューと
                # pending_signals() が乖離しないための安価な保険。
                self._pending_signals -= 1
                freed_signals += 1
                freed_bytes += _retained_bytes(item, seen)
                del item  # drop the last strong ref -> the arrays free here
                # 読まない区間 (1 ティックが _CLOCK_CHECK_EVERY 信号未満) が
                # 安全なのは、バイト軸が毎イテレーション評価されるから: その
                # regime に入るのは 1 信号あたりが大きいときで、そのとき 64MiB
                # 予算が数信号で発火する。
                if (
                    freed_signals % _CLOCK_CHECK_EVERY == 0
                    and self._now() - t0 >= self._deadline
                ):
                    deadline_hit = True
                    break
            if not items:
                self._groups.popleft()
                if self._on_finished is not None:
                    self._on_finished(key)
        # バイト軸を直接 assert できる唯一の観測点。pending_bytes は生存集合から
        # 都度再計算するため、共有配列があると _drain の会計と乖離しても差分に現れない。
        self._last_tick_bytes = freed_bytes
        if not self._groups:
            self._timer.stop()


def _retained_bytes(obj: _Freeable, seen: set[int]) -> int:
    """この対象が解放で返すバイト数 (既に数えた配列は id で除外).

    *obj* が生 ndarray のときは ``ChannelSampleCache`` から回収したデコード済み
    チャンネル配列 (E-4a)。Signal の皮を持たないので直接数える。**id dedup は
    Signal 側と同じ ``seen`` を共有する** — 分岐ごとに別集合を持つと、共有された
    配列が二重計上されてティックが予算へ早く到達し、ペーシングの実効粒度が
    黙って粗くなる。

    会計そのものは ``valisync.core.models.retained_bytes`` に 1 本だけ置く — pin の
    予約会計 (``SignalGroupManager.pinned_column_bytes``) と同じ問いに答えるので、
    別々に書くと必ずずれる (E-4a レビューで実際にずれていた: 予約側が float64 の
    ``sorted_view`` を取りこぼし、非 float64 チャンネルで最大 8 倍の**過小**申告)。

    ここに残るのはこのラッパー 1 つ = **master を数える**という teardown 固有の判断。
    teardown は master ごと解放するので ``seen`` を種まきせずに渡す (予約側は master を
    グループ側の帳簿に残すため ``id(timestamps)`` を先に入れる — 両者の唯一の差)。
    master はグループ内で identity 共有されるので、``seen`` を通さずに信号ごとに
    数えると prod_demo で実体 0.2 MiB に対し 10,316 MiB (約 5 万倍) を計上してしまう。

    RangeStatIndex を計上しないことは時間問題の解決ではない — 実測で RSI を持たせても
    バイト計上は変わらないままティックが 24→36ms に増える (だから第 3 軸の
    デッドラインが要る)。

    **既知の過小計上 (M8・cross-task)**: ``isinstance(obj, np.ndarray)`` は
    ``np.ma.MaskedArray`` にも一致し、その ``nbytes`` はマスク配列を含まないので
    実体より小さく出る。向きは「ティックが長引く側」= 安全でない側だが、同じ性質は
    Signal の値配列についても ``models.retained_bytes`` に既に存在する既存事象で、
    E-4a の production 経路 (asammdf の select 結果) にマスク配列は現れない。
    """
    if isinstance(obj, np.ndarray):
        if id(obj) in seen:
            return 0
        seen.add(id(obj))
        return int(obj.nbytes)
    return retained_bytes(obj, seen)
