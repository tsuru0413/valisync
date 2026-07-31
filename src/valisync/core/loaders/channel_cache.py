"""デコード済みチャンネル samples のプロセス単位 LRU (E-4a・spec §5)。

E-3 は Signal オブジェクト数を根治した (264,004 -> 4,324) が、列読みの対話コストは
1 ミリ秒も動いていない: LazyMdfValues.array() が列ごとに「全チャンネル select +
全リーフ _flatten」をやり直すままだから (実測 309-327 ms/列・5 列で 1,584 ms)。
兄弟列の比較 (Radar.ObjList.dx[0..k]) は同じ 1 本の物理チャンネルを何度も
デコードする形なので、デコード結果そのものをプロセス単位で持ち回す。

上限は時間でなく**バイト**にする (ユーザー決定 U2/U3・256 MB): 時間ベースは
テストが時計依存になる。**予算の裁定者はこのクラス 1 つだけ**にする (spec §5.2) —
2 人いると互いの解放を当てにして両方が上限を超える。
"""

from __future__ import annotations

import threading
from collections import OrderedDict

import numpy as np

CacheKey = tuple[int, int, int]
"""キー = ``(id(handle), group_index, channel_index)``。

**名前をキーにしない** (spec §5.3): 生名は LD-08 重複で一意でなく (mdf_loader の
``name_total[base_name] > 1`` — 既存 fixture ``Mat2`` がその形)、表示名はファイル間で
一意でない。``Session`` は 1 キャッシュを全ファイルで共有するので、handle を含めないと
2 ファイル比較で同じ曲線が 2 本描かれる (長さが同じなら sample_source の長さ検証も
通り、例外も出ない = サイレント誤データ)。

**前提条件**: ``id()`` は生存中のオブジェクト間でのみ一意で、閉じたハンドルの id は
次のロードが再利用しうる (実測 100% 再利用・memory gui_id_reuse_flake_object_recreation)。
``MdfHandle.close()`` の**前**に ``drop_handle()`` でそのファイルのエントリを外すことが
キー一意性の前提になる。
"""

_DEFAULT_BUDGET_BYTES = 256 * 1024 * 1024  # ユーザー決定 U3


class ChannelSampleCache:
    """デコード済みチャンネル samples のバイト予算つき LRU。

    **コピーも凍結もしない** — 呼び出し側が渡した配列そのものを保持し、そのまま返す
    (コピーすると予算が実質半分になる)。したがって載せた配列を呼び出し側が書き換えて
    はならない。命中パスのスライスが view を焼き付けないための所有権不変条件
    (spec §5.4) は**切り出す側** (``apply_path`` / 命中パス) の責務であって、ここではない。

    **``handle.lock`` は絶対に取らない** (spec §11 の保存契約: 「キャッシュヒットは
    handle.lock を取らない」は E-3 の test-lock)。予算はプロセス単位・``handle.lock`` は
    ファイル単位なので後者では守れない。このクラスが見るのは ``id(handle)`` の int だけで
    ハンドル自体を参照しないため、構造的に取りようがない。予算の増減は自前の小さな
    lock で守る (``MdfHandle._close_lock`` と同型・読み直列化 lock とは別物)。
    ロック順は ``handle.lock`` -> ``_lock`` の一方向のみで、逆順を作る API は置かない
    (このクラスは ndarray しか触らないので I/O を lock 下で呼ぶ経路が無い)。

    evict した配列は**その場で同期解放する** (unload の ``drop_handle`` と違い teardown へ
    渡さない)。実測 (spec §5.7 / §9) は **追い出される配列の出自ごとに分けて**記録する:

    - **実 asammdf デコード配列** (prod_demo の広幅チャンネル 12.6 MiB/本・キャッシュが
      唯一の所有者): 中央値 **1.2-1.7 ms** / 最大 1.5-4.2 ms (n=20 x 10 run)
    - **合成 ``np.ones`` 13.2 MB を空のキャッシュへ積んで追い出す**: 中央値
      **0.65-0.83 ms** / 最大 0.7-3.3 ms (n=20 x 6 run)

    **~2 倍の差は手法でなく主語の差である**: 合成側は free した 12 MB ブロックを次の
    ループが即座に再確保する warm-allocator バイアスが乗る (同一プロセスで実配列を
    出し切った直後から同じループの中央値が 1.4 ms -> 0.67 ms へ落ちることで分離できる)。
    サイズは効かない (合成 11.99 MiB と 12.59 MiB は同値)。**単価を記録するときは
    「何がそのバイトを作ったか」を必ず併記すること** — この系列は同じ罠を 3 度踏んで
    いる (T4 の未タッチページ 17-25 倍・増分B の 3.0-4.8 us/signal 対 実 8-27 us)。

    どちらの主語で読んでも E-3 T9 が実測した「最大単発解放 5.8 ms」より小さいので、
    ペーシングの構造的な床 (デッドライン + 最大単発解放) は押し上げない。
    **計測はページを dirty 化して行う**こと — ``np.zeros`` の未タッチページは
    lazily-zeroed で free が実体を伴わず、~17-25 倍の過小評価になる。
    """

    __slots__ = (
        "_budget",
        "_bytes_held",
        "_entries",
        "_evictions",
        "_hits",
        "_lock",
        "_misses",
        "_reserved",
        "_skipped_oversize",
    )

    def __init__(self, budget_bytes: int = _DEFAULT_BUDGET_BYTES) -> None:
        self._budget = budget_bytes
        # OrderedDict が LRU 順序そのもの (末尾 = 最近使用)。
        self._entries: OrderedDict[CacheKey, np.ndarray] = OrderedDict()
        self._bytes_held = 0
        self._reserved = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._skipped_oversize = 0
        self._lock = threading.Lock()

    def get(self, key: CacheKey) -> np.ndarray | None:
        """命中なら配列 (最近使用へ更新)、不在なら None。

        不在は ``misses`` を 1 増やす。**正しい関係は等式でなく ``misses >= select``**。
        production が select を呼ぶ唯一の理由がここの None なので下限は必ず立つが、
        **等号は「同一キーへの miss が直列化されているとき」に限る**: 兄弟列は別々の
        ``LazyMdfValues`` インスタンスなので per-instance の fast path では畳まれず、
        2 スレッドが同じ物理チャンネルの別列を読むと **miss は 2・select は 1**
        (``handle.lock`` 下の同一キー再チェックが 1 回に畳む) になる。これは E-4a が
        最適化しようとしているワークロードそのものなので、等式を仮定してはならない。

        **T6 の ①gate は上界 (``misses <= N``) で書くこと** — 直列でも並行でも健全な
        のは上界だけである (spec §8)。

        **等式が成り立つのはキャッシュが配線された経路 (``Session`` 経由) に限る**:
        ``MdfLoader()`` を引数なしで使う構成では ``MdfHandle.cache`` が None になり、
        ``LazyMdfValues.array()`` はここを一度も通らない — ``misses`` は 0 のまま
        ``select`` だけが毎回走る。観測点として使う側はその構成でないことを
        setup で確かめること (T6 は ``Session`` 経由・T3 の ``wide`` fixture は
        ``MdfLoader(cache=ChannelSampleCache())`` を明示的に渡している)。
        """
        with self._lock:
            arr = self._entries.get(key)
            if arr is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return arr

    def put(self, key: CacheKey, samples: np.ndarray) -> bool:
        """*samples* を載せる。載せたら True、oversize で見送ったら False。

        1 エントリが予算 (reserved を引く前の全体) を超える場合は**載せない** (D7):
        載せると他を全部追い出したうえで自分も次の put で落ちるだけで、キャッシュを
        空にする代償に何も得られない。静かに遅いままにするのは罠なので
        ``skipped_oversize`` で観測可能にする。
        """
        size = int(samples.nbytes)  # 会計は nbytes のみ (lock の外で済ませる)
        with self._lock:
            if size > self._budget:
                self._skipped_oversize += 1
                return False
            old = self._entries.pop(key, None)
            if old is not None:
                # 同一キーの入れ替え。差分加算でなく「引いてから足す」— サイズの違う
                # 配列で上書きされたときに会計が実体から乖離しないため。
                self._bytes_held -= int(old.nbytes)
            capacity = self._capacity_for(size)
            while self._entries and self._bytes_held + size > capacity:
                self._evict_oldest()
            self._entries[key] = samples
            self._bytes_held += size
            return True

    def set_reserved(self, reserved_bytes: int) -> None:
        """pin 済み (``_resolved_by_key`` が保持中) のバイト数を登録する。

        **production の呼び出し元は ``Session.set_pinned_columns`` ただ 1 つ** (T3)。
        pin した鋳造列は所有権不変条件 (spec §5.4) により**自前の独立配列**を抱えて
        おり、それは ``bytes_held`` とは別に同じ U3 256 MB を食う。予算の裁定者を
        1 人にする (spec §5.2) とは、その両方をこのクラスが同時に見るということで
        あり、pin 側を渡さなければ「2 人が互いの解放を当てにして両方が上限を超える」
        形に戻る。

        LRU が使えるのは ``budget - reserved``。**最低容量は「今 LRU が保持しようと
        している最も新しい 1 エントリ」のサイズ**で、reserved が予算を食い尽くしても
        そこまでは落とさない (spec §5.5: pin は拒否しない・LRU の最低容量 1 物理
        チャンネル分は無条件確保)。容量 0 にすると「載せて即落とす」往復になり、
        再描画ごとのフルチャンネル再読み (316 ms/列) が復活する。

        登録と同時に縮めるのは、次の ``put`` まで待つと「プロットしたまま放置」で
        超過が残り続け、飽和後 USS +256 MB 以内 (spec §9) が破れるから。
        """
        with self._lock:
            self._reserved = max(0, reserved_bytes)
            if not self._entries:
                return
            newest = int(next(reversed(self._entries.values())).nbytes)
            capacity = self._capacity_for(newest)
            while self._entries and self._bytes_held > capacity:
                self._evict_oldest()

    def drop_handle(self, handle_id: int) -> tuple[np.ndarray, ...]:
        """**ペーシングあり** — *handle_id* のエントリを外して**返す** (spec §5.7)。

        呼び出し側が正しく選ぶべき性質は「回収か解放か」ではなく**ペーシングを
        通るかどうか**である (:meth:`release_handle` は同期解放)。名前だけでは
        近義語に見えるので、この 1 行を契約の見出しとして置く。

        返すのは teardown へ渡すため: 2-D 配列は 1 本 13.2 MB あり、ここで参照を
        落とすと unload の同期解放へ戻る (FU-16 のフリーズ)。呼び出し側が
        ``RemovalResult.cached_arrays`` に載せ ``TeardownService`` の三軸ペーシングへ通す。

        **``MdfHandle.close()`` より前に呼ぶこと**: 逆順だと teardown へ渡す前に
        キャッシュだけが取り残され会計から漏れる。加えて ``CacheKey`` の一意性自体が
        「close 前に外すこと」を前提にしている (id 再利用)。

        eviction ではないので ``evictions`` は増やさない — 予算圧と unload を混ぜると
        予算の効きが読めなくなる。
        """
        with self._lock:
            return self._pop_handle_entries(handle_id)

    def release_handle(self, handle_id: int) -> None:
        """**同期解放** — *handle_id* のエントリを外してその場で捨てる (回収しない)。

        呼び出し側が正しく選ぶべき性質は**ペーシングを通るかどうか**である
        (:meth:`drop_handle` はペーシングあり)。名前だけでは近義語に見えるので、
        この 1 行を契約の見出しとして置く。

        :meth:`drop_handle` との違いは**所有権の行き先だけ**である。あちらは
        teardown へ渡すために配列を返すが、こちらは渡す相手が居ない
        (``MdfHandle.close()`` の backstop — 回収されない close 経路) ので参照を
        ここで落とす。``drop_handle`` を呼んで返り値を捨てる形にしないのは、
        「この経路は同期解放している」という事実がコード上から消えるため。
        エントリを外す会計そのものは :meth:`_pop_handle_entries` の 1 本だけ。

        通常の unload では ``Session.remove_group`` が先に ``drop_handle`` で回収済み
        なので空振りする。
        """
        with self._lock:
            dropped = self._pop_handle_entries(handle_id)
        # 解放 (最後の参照が死ぬ瞬間) を lock の**外**へ出す。``with`` の中で
        # ``dropped`` を捨てると 13.2 MB/本 の dealloc が ``_lock`` 保持下で走り、
        # 「キャッシュヒットは誰も待たない」(spec §5.8) が GUI スレッド側から
        # 破れる — ロック順 ``handle.lock -> _lock`` は保たれるので気付きにくい。
        del dropped

    # ─── introspection (非侵襲・spec §8) ──────────────────────────────────────
    # LRU 順序を動かさず lock も取らない: int の読みは GIL 下で atomic であり、
    # lock を取ると in-flight な put を待つ = 観測が挙動を変える。

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        """キャッシュミス回数。**``misses >= select 呼び出し回数``** (等式ではない)。

        等号は同一キーへの miss が直列化されているときだけ成り立つ — 詳細と
        「①gate は上界で書く」理由は ``get`` の docstring を参照。
        なお下限そのものが立つのは cache が配線された経路のみ (``cache is None`` の
        構成では ``get`` を通らないので 0 のまま select だけが走る)。
        """
        return self._misses

    @property
    def evictions(self) -> int:
        """予算圧で落とした本数 (``drop_handle`` の unload は含まない)."""
        return self._evictions

    @property
    def skipped_oversize(self) -> int:
        """予算超で載せなかった回数 (D7 — 静かに遅いままにしないための観測点)."""
        return self._skipped_oversize

    @property
    def reserved(self) -> int:
        """pin 済み分として登録されているバイト数 (``set_reserved`` の最後の値)。

        T3 が ``Session.set_pinned_columns`` からここへ配線したことを**直接**見る口。
        効果 (LRU 容量の縮み) だけを観測しようとすると、pin が予算に対して小さい
        production 相当の構成では何も起きず、配線が外れても緑のまま通る。
        """
        return self._reserved

    @property
    def bytes_held(self) -> int:
        """保持中のバイト数 (= 各エントリの ``samples.nbytes`` の総和)。

        **identity dedup (teardown の ``seen`` set) は要らない**: teardown があれを
        持つのは 1 グループの master 配列が全信号で identity 共有されるからで
        (prod_demo で実体 0.2 MiB を 10,316 MiB と誤計上した)、ここに載るのは
        物理チャンネル 1 本を select して得た専用の配列であり、キー (handle, gi, ci) が
        その 1 本を一意に指す。異なるキーが同じ配列オブジェクトを指す経路は
        production に無い。同一キーの再 put だけは起こりうるので ``put`` が
        「引いてから足す」で二重計上を防ぐ。
        """
        return self._bytes_held

    # ─── 内部 (すべて _lock 保持前提) ────────────────────────────────────────

    def _pop_handle_entries(self, handle_id: int) -> tuple[np.ndarray, ...]:
        """*handle_id* の全エントリを外して返す (回収と解放が共有する唯一の会計)。"""
        hit = [key for key in self._entries if key[0] == handle_id]
        dropped = []
        for key in hit:
            arr = self._entries.pop(key)
            self._bytes_held -= int(arr.nbytes)
            dropped.append(arr)
        return tuple(dropped)

    def _capacity_for(self, floor_bytes: int) -> int:
        """LRU が使ってよいバイト数。``floor_bytes`` は無条件に確保する最低容量。"""
        return max(self._budget - self._reserved, floor_bytes)

    def _evict_oldest(self) -> None:
        """LRU の先頭 (最も長く使われていない 1 本) を落とす。"""
        _key, arr = self._entries.popitem(last=False)
        self._bytes_held -= int(arr.nbytes)
        self._evictions += 1
