"""ChannelSampleCache の LRU / 予算 / キー空間 / スレッド契約 (E-4a T0)。

**demo_data に依存しない**: 自然な宛先に見える ``test_lazy_mdf_values.py`` は
module-level の demo skipif (``demo_data/quick_demo.mf4``) を持ち、``demo_data/`` は
gitignore 済み・CI に生成ステップが無いため**丸ごと skip される** (同じ gate を持つ
ファイルは 5 本)。予算・LRU・キー空間はどれも ndarray を直接投入すれば検証でき、
実 mf4 を要さないので、CI 執行力のあるここに置く
(``test_mdf_handle_concurrency.py`` が同じ罠への既存対処)。

このファイルの時点でキャッシュは **production 未配線** — したがってここが
唯一の執行点であり、緑であることが「実装が効いている」の唯一の根拠になる。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np
import pytest

from valisync.core.loaders.channel_cache import CacheKey, ChannelSampleCache

_BOUND_S = 2.0  # 全ての待ちは有界 (デッドロック時にハングでなく失敗させる)


def _arr(nbytes: int) -> np.ndarray:
    """*nbytes* ちょうどの uint8 配列。

    uint8 は prod の広幅チャンネルと同じ dtype (spec §5.1: 12000x1100 = 13.2 MB。
    初版の float64 96 MB は 7.3 倍の誤り)。1 要素 = 1 バイトなので予算の境界を
    1 バイト単位で狙える。
    """
    return np.zeros(nbytes, dtype=np.uint8)


# ─── 基本 (ヒット/ミスと同一性) ────────────────────────────────────────────────


def test_get_on_absent_key_returns_none_and_counts_a_miss() -> None:
    cache = ChannelSampleCache(budget_bytes=1024)
    assert cache.get((1, 0, 0)) is None
    assert cache.misses == 1
    assert cache.hits == 0
    assert cache.bytes_held == 0


def test_put_then_get_returns_the_identical_array_and_counts_a_hit() -> None:
    """キャッシュはコピーしない — コピーすると予算が実質半分になる。

    同一性 (``is``) で pin するのが要点: 値一致だけだと「毎回コピーを返す」実装が
    緑のまま通り、予算の意味が消える。
    """
    cache = ChannelSampleCache(budget_bytes=1024)
    arr = _arr(64)
    assert cache.put((1, 0, 0), arr) is True
    assert cache.get((1, 0, 0)) is arr
    assert cache.hits == 1
    assert cache.misses == 0
    assert cache.bytes_held == 64


# ─── キー空間 (spec §5.3 / レビュー C2) ────────────────────────────────────────


def test_key_separates_handle_group_and_channel() -> None:
    """キーの 3 成分すべてが効いていること。

    生名は LD-08 重複で一意でなく (既存 fixture ``Mat2`` がその形)、表示名は
    ファイル間で一意でない。どれか 1 成分でも落とすと「別チャンネルの値を返す」=
    長さが同じなら sample_source の長さ検証も通り例外も出ない**サイレント誤データ**
    になる。3 つの変種はそれぞれ 1 成分だけを base から変えてある。
    """
    cache = ChannelSampleCache(budget_bytes=4096)
    keys: list[CacheKey] = [(7, 1, 2), (8, 1, 2), (7, 9, 2), (7, 1, 9)]
    arrays = {k: _arr(16) for k in keys}
    for key, arr in arrays.items():
        assert cache.put(key, arr) is True
    for key, arr in arrays.items():
        assert cache.get(key) is arr, key
    assert cache.bytes_held == 64


# ─── LRU 順序 ─────────────────────────────────────────────────────────────────


def test_lru_evicts_least_recently_used_not_first_inserted() -> None:
    """FIFO と LRU を区別する: ``get`` で温めた古いエントリは生き残る。

    予算 200 に 100 バイトが 2 本ちょうど入る形にしてある (3 本目で必ず 1 本落ちる)。
    """
    cache = ChannelSampleCache(budget_bytes=200)
    a, b, c = _arr(100), _arr(100), _arr(100)
    assert cache.put((1, 0, 0), a) is True
    assert cache.put((1, 0, 1), b) is True
    assert cache.get((1, 0, 0)) is a  # A を最近使用へ (FIFO ならここが効かない)
    assert cache.put((1, 0, 2), c) is True
    assert cache.evictions == 1
    assert cache.bytes_held == 200
    assert cache.get((1, 0, 1)) is None  # 最も長く使われていない B が落ちた
    assert cache.get((1, 0, 0)) is a  # 温めた A は残る


# ─── reserved (pin 済み分) ────────────────────────────────────────────────────


def test_reserved_bytes_shrink_the_lru_capacity() -> None:
    """pin 済みを引いた残りだけが LRU の容量 (spec §5.5)。

    ``set_reserved`` は登録と同時に縮める — 次の ``put`` まで待つと「プロットしたまま
    放置」のワークフローで超過が残り続け、飽和後 USS +256 MB 以内 (spec §9) が破れる。
    """
    cache = ChannelSampleCache(budget_bytes=300)
    a, b = _arr(100), _arr(100)
    cache.put((1, 0, 0), a)
    cache.put((1, 0, 1), b)
    assert cache.bytes_held == 200
    assert cache.evictions == 0

    cache.set_reserved(150)  # LRU が使えるのは 300-150 = 150

    assert cache.reserved == 150  # T3 の pin 配線が効いたかを見る唯一の直接観測点
    assert cache.evictions == 1
    assert cache.bytes_held == 100
    assert cache.get((1, 0, 0)) is None  # 古い方から落ちる
    assert cache.get((1, 0, 1)) is b


def test_reserved_bytes_also_bound_the_capacity_at_put_time() -> None:
    """``put`` 側も reserved を見る (set_reserved 時の trim だけでは不十分)。

    pin が先に立っている状態で新しい列を読む = プロット中にブラウザで別列を覗く
    経路であり、production ではこちらの方が多い。
    """
    cache = ChannelSampleCache(budget_bytes=300)
    cache.set_reserved(150)
    a, b = _arr(100), _arr(100)
    assert cache.put((1, 0, 0), a) is True
    assert cache.put((1, 0, 1), b) is True  # 容量 150 -> A を落として載る
    assert cache.evictions == 1
    assert cache.bytes_held == 100
    assert cache.get((1, 0, 0)) is None
    assert cache.get((1, 0, 1)) is b


def test_reserved_never_starves_the_lru_below_one_channel() -> None:
    """pin が予算を食い尽くしても LRU 容量を 0 にしない (spec §5.5: pin は拒否しない)。

    容量 0 にすると「載せて即落とす」無駄な往復になり、再描画ごとのフルチャンネル
    再読み (実測 316 ms/列) が復活する。最低容量の定義は「今 LRU が保持しようと
    している最も新しい 1 エントリ」。
    """
    cache = ChannelSampleCache(budget_bytes=300)
    cache.set_reserved(300)  # 予算を pin が使い切った

    first = _arr(100)
    assert cache.put((1, 0, 0), first) is True  # 拒否しない
    assert cache.skipped_oversize == 0  # oversize でもない
    assert cache.get((1, 0, 0)) is first  # 即落としもしない
    assert cache.bytes_held == 100

    second = _arr(100)
    assert cache.put((1, 0, 1), second) is True
    assert cache.bytes_held == 100  # 常に 1 本ぶんだけ
    assert cache.get((1, 0, 0)) is None
    assert cache.get((1, 0, 1)) is second


def test_set_reserved_keeps_the_newest_entry_even_when_pins_eat_the_budget() -> None:
    """最低容量の規則は ``set_reserved`` 側でも同じ (その時点の最新エントリ)。"""
    cache = ChannelSampleCache(budget_bytes=300)
    a, b = _arr(100), _arr(100)
    cache.put((1, 0, 0), a)
    cache.put((1, 0, 1), b)

    cache.set_reserved(1_000)  # 予算そのものを超える pin

    assert cache.bytes_held == 100
    assert cache.get((1, 0, 1)) is b  # 最近使用の 1 本は残る
    assert cache.get((1, 0, 0)) is None


# ─── oversize (D7) ───────────────────────────────────────────────────────────


def test_oversize_entry_is_not_cached_and_is_counted() -> None:
    """1 エントリが予算超なら載せない (D7)。

    載せると他を全部追い出したうえで自分も次の put で落ちるだけで、キャッシュを
    空にする代償に何も得られない。ただし静かに遅いままにするのは罠なので
    ``skipped_oversize`` で観測可能にする。
    """
    cache = ChannelSampleCache(budget_bytes=100)
    big = _arr(101)
    assert cache.put((1, 0, 0), big) is False
    assert cache.skipped_oversize == 1
    assert cache.bytes_held == 0
    assert cache.evictions == 0
    assert cache.get((1, 0, 0)) is None


def test_oversize_put_does_not_evict_the_existing_contents() -> None:
    """oversize は「入らない」だけ — 既にある席を空けさせてはならない。

    最低容量が「今入れようとしているエントリ」である以上、D7 のガードが無いと
    oversize が capacity を自分のサイズまで押し上げて既存を全部追い出す。
    """
    cache = ChannelSampleCache(budget_bytes=100)
    kept = _arr(60)
    cache.put((1, 0, 0), kept)
    assert cache.put((1, 0, 1), _arr(400)) is False
    assert cache.get((1, 0, 0)) is kept
    assert cache.bytes_held == 60
    assert cache.evictions == 0


# ─── バイト会計 ───────────────────────────────────────────────────────────────


def test_reput_of_the_same_key_replaces_without_double_counting() -> None:
    """同一キーの再投入は「引いてから足す」(差分加算でない)。

    素朴な ``self._bytes_held += size`` は、サイズの違う配列で上書きされた瞬間に
    会計が実体から乖離し、以後 evict が過剰/過少になる。
    """
    cache = ChannelSampleCache(budget_bytes=1000)
    first, second = _arr(100), _arr(250)
    cache.put((1, 0, 0), first)
    cache.put((1, 0, 0), second)
    assert cache.bytes_held == 250
    assert cache.get((1, 0, 0)) is second
    assert cache.evictions == 0


def test_hit_and_miss_counters_move_only_on_get() -> None:
    """hits/misses を動かすのは ``get`` だけ。

    「miss 数 == select 回数」が T6 ①gate の観測点なので、put/drop が混ざると
    数が読めなくなる (evictions は逆に put 側でだけ動く)。
    """
    cache = ChannelSampleCache(budget_bytes=100)
    cache.put((1, 0, 0), _arr(40))
    cache.put((1, 0, 1), _arr(40))
    cache.put((1, 0, 2), _arr(40))  # ここで 1 本落ちる
    cache.drop_handle(1)
    assert cache.hits == 0
    assert cache.misses == 0
    assert cache.evictions == 1


# ─── drop_handle (unload・spec §5.7) ─────────────────────────────────────────


def test_drop_handle_returns_the_arrays_and_leaves_other_files_alone() -> None:
    """unload は 2-D 配列を**捨てず返す** (spec §5.7)。

    1 本 13.2 MB を同期解放すると FU-16 のフリーズに戻るので、呼び出し側 (T4) が
    ``RemovalResult.cached_arrays`` 経由で teardown の三軸ペーシングへ渡す。
    予算圧ではないので ``evictions`` は増やさない (混ぜると予算の効きが読めなくなる)。
    """
    cache = ChannelSampleCache(budget_bytes=4096)
    a0, a1, other = _arr(16), _arr(32), _arr(64)
    cache.put((7, 0, 0), a0)
    cache.put((7, 1, 5), a1)
    cache.put((8, 0, 0), other)

    dropped = cache.drop_handle(7)

    assert {id(arr) for arr in dropped} == {id(a0), id(a1)}
    assert cache.bytes_held == 64
    assert cache.evictions == 0
    assert cache.get((8, 0, 0)) is other  # 別ファイルは無傷
    assert cache.get((7, 0, 0)) is None


def test_drop_handle_of_unknown_file_is_a_no_op() -> None:
    cache = ChannelSampleCache(budget_bytes=4096)
    kept = _arr(16)
    cache.put((7, 0, 0), kept)
    assert cache.drop_handle(9) == ()
    assert cache.bytes_held == 16
    assert cache.get((7, 0, 0)) is kept


def test_drop_handle_makes_a_recycled_handle_id_safe() -> None:
    """``drop_handle`` の後に**同じ第 1 成分**でエントリを載せ直せる。

    **supersede (E-4b)**: 旧 docstring は「``id()`` は生存中のオブジェクト間でのみ
    一意なので、close の前に drop_handle で外すことがキー一意性の前提」と書いて
    いた。キーが ``handle.serial`` (プロセス単調 int) になった今、同じ第 1 成分を
    2 つのハンドルが持つことは production では起こらない — この test が残って
    守るのは「``drop_handle`` が会計ごとエントリを外し切る (残骸が次の put を
    汚さない)」という **キャッシュ側の純粋な性質** だけである。
    id 再利用そのものの構造的閉鎖は
    ``test_handle_serial.py::test_a_recycled_address_does_not_serve_another_handles_channel``
    (production の読み経路を通す) が受け持つ。
    """
    cache = ChannelSampleCache(budget_bytes=1000)
    old = _arr(32)
    cache.put((7, 0, 0), old)

    dropped = cache.drop_handle(7)
    assert len(dropped) == 1
    assert dropped[0] is old
    assert cache.bytes_held == 0

    fresh = _arr(32)  # 同じ id を得た別ファイル
    cache.put((7, 0, 0), fresh)
    assert cache.get((7, 0, 0)) is fresh
    assert cache.bytes_held == 32


# ─── スレッド契約 (spec §5.8 / レビュー I6) ──────────────────────────────────


class _InterleavedCache(ChannelSampleCache):
    """``_bytes_held`` の「読み」と「書き」の間に決定的な引き渡し点を作る。

    lock が無いと 2 スレッドの read-modify-write が同じ古い値を読み、片方の加算が
    消える (lost update)。素朴な並行 put ではこの窓に落ちない — 同型の
    ``_InterleavedHandle`` (test_mdf_handle_concurrency.py) が 17,000 試行 0 ヒットを
    実測しており、Windows の GIL 引き渡しは数バイトコードの窓に入らない。だから
    窓を明示的に開ける。

    罠 (a): yield は基底スロットを**読んだ後**に置く。先頭で yield すると壊れた
            実装でも合計が合ってしまう。
    罠 (b): 引き渡しは**有界待ち**にする。素の wait() だと修正後の実装が
            デッドロックしたときテストがハングする。
    """

    def __init__(
        self, gate: threading.Event, resumed: threading.Event, budget_bytes: int
    ) -> None:
        # 基底 __init__ が _bytes_held を書く (= setter が走る) 前に用意する。
        self._gate = gate
        self._resumed = resumed
        self._yielded = False
        super().__init__(budget_bytes=budget_bytes)

    @property  # type: ignore[override]
    def _bytes_held(self) -> int:
        value: int = ChannelSampleCache._bytes_held.__get__(self)  # type: ignore[attr-defined] # ← 先に読む
        if not self._yielded:
            self._yielded = True
            self._gate.set()
            self._resumed.wait(0.5)
        return value

    @_bytes_held.setter
    def _bytes_held(self, value: int) -> None:
        ChannelSampleCache._bytes_held.__set__(self, value)  # type: ignore[attr-defined]


def test_byte_accounting_survives_concurrent_puts() -> None:
    """予算の増減はキャッシュ自身の lock で守る (spec §5.8)。

    予算は**プロセス単位**・``handle.lock`` は**ファイル単位**なので後者では守れない。
    かつ「キャッシュヒットは handle.lock を取らない」は E-3 の test-lock (spec §11)
    なので、ここで handle.lock を取る選択肢は最初から無い。
    """
    gate, resumed = threading.Event(), threading.Event()
    cache = _InterleavedCache(gate, resumed, budget_bytes=10_000)
    a, b = _arr(100), _arr(250)

    ta = threading.Thread(target=cache.put, args=((1, 0, 0), a))
    ta.start()
    assert gate.wait(1.0), "A が _bytes_held を読む前に止まった (setup 失敗)"
    tb = threading.Thread(target=cache.put, args=((1, 0, 1), b))
    tb.start()
    time.sleep(0.05)  # lock が無ければ B はここで加算まで走り抜ける
    resumed.set()
    ta.join(timeout=_BOUND_S)
    tb.join(timeout=_BOUND_S)

    assert not ta.is_alive() and not tb.is_alive(), (
        "引き渡しがハングした — 有界待ちが効いていない"
    )
    assert cache.bytes_held == 350, "lost update (A か B の加算が消えた)"


class _LockProbeArray(np.ndarray):
    """解放される瞬間に「キャッシュの lock が握られていたか」を記録する ndarray。

    ``threading.Lock`` は非再帰なので、保持中のスレッドが ``acquire(blocking=False)``
    しても False が返る — これが「今 lock 下か」の直接観測になる。参照はロック
    オブジェクトと記録用リストだけに留める (キャッシュを参照すると循環になり、
    解放が refcount でなく gc 任せ = 非決定になる)。
    """

    def __del__(self) -> None:
        lock = getattr(self, "probe_lock", None)
        if lock is None:  # numpy が作る view には属性が伝播しない
            return
        acquired = lock.acquire(blocking=False)
        self.probe_observed.append(not acquired)
        if acquired:
            lock.release()


def _probe_entry(cache: ChannelSampleCache, key: CacheKey, nbytes: int) -> list[bool]:
    """*key* へ「解放される瞬間の lock 状態」を記録する配列を載せ、記録先を返す。"""
    observed: list[bool] = []
    arr = _arr(nbytes).view(_LockProbeArray)
    arr.probe_lock = cache._lock
    arr.probe_observed = observed
    assert cache.put(key, arr) is True
    del arr  # キャッシュだけが持つ状態にする (以後の解放は必ずキャッシュ由来)
    return observed


def _drop_via_release_handle() -> list[bool]:
    """``MdfHandle.close()`` の backstop 経路 (同期解放)."""
    cache = ChannelSampleCache(budget_bytes=4096)
    observed = _probe_entry(cache, (7, 0, 0), 64)
    cache.release_handle(7)
    assert cache.bytes_held == 0  # 会計そのものは従来どおり
    return observed


def _drop_via_put_eviction() -> list[bool]:
    """**ホットパス**: 予算超の ``put`` が古いエントリを追い出す経路。

    production でこの形になるのは「未キャッシュのチャンネルを読んだ」瞬間であり、
    エクスポートワーカー (``QRunnable``) が最も踏む経路でもある。
    """
    cache = ChannelSampleCache(budget_bytes=128)
    observed = _probe_entry(cache, (7, 0, 0), 64)
    cache.put((7, 0, 1), _arr(96))  # 64 + 96 > 128 -> probe が落ちる
    assert (cache.evictions, cache.bytes_held) == (1, 96)
    return observed


def _drop_via_set_reserved_eviction() -> list[bool]:
    """pin 登録 (``Session.set_pinned_columns``) が容量を縮めて追い出す経路。"""
    cache = ChannelSampleCache(budget_bytes=4096)
    observed = _probe_entry(cache, (7, 0, 0), 64)
    cache.put((7, 0, 1), _arr(64))  # これが「最新 1 エントリ」= 最低容量になる
    cache.set_reserved(4096)  # 容量 = max(4096 - 4096, 64) -> 古い probe が落ちる
    assert (cache.evictions, cache.bytes_held) == (1, 64)
    return observed


@pytest.mark.parametrize(
    "drop",
    [_drop_via_release_handle, _drop_via_put_eviction, _drop_via_set_reserved_eviction],
    ids=["release_handle", "put_eviction", "set_reserved_eviction"],
)
def test_dropped_arrays_are_freed_outside_the_lock(
    drop: Callable[[], list[bool]],
) -> None:
    """参照を落とす**全ての**経路で、解放は ``_lock`` の外で走る (spec §5.8)。

    ``with self._lock:`` の中で最後の参照が死ぬ形だと、13.2 MB/本 の dealloc が
    キャッシュ lock 保持下で走り (実 asammdf 配列で中央値 1.2-1.7 ms・最大 4.2 ms)、
    その間 GUI スレッドのキャッシュヒットが ``get`` の入口でブロックする。ロック順
    (``handle.lock -> _lock``) は保たれたままなのでデッドロックにはならず、**症状は
    待ち時間だけ**で数字にも出ない — だから会計でなく解放の瞬間そのものを観測する。

    **3 経路すべてを回す** (レビュー I1): 最初にこの穴を塞いだのは ``release_handle``
    だけで、同じ probe を残り 2 経路へ向けたら両方 ``[True]`` だった (実測)。
    ``release_handle`` は close の backstop = 最も踏まれない経路で、**予算超の
    ``put`` こそがホットパス**である。1 経路だけを test-lock すると「直した経路だけが
    守られている」ことに気付けない。
    """
    observed = drop()

    assert observed == [False], f"配列の解放が _lock 保持下で走った: {observed}"
