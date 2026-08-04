"""鋳造列 LRU と pin の規則 (E-4a spec §5.5 / D4)。

E-3 は `_resolved_by_key` を無制限に持っていた (決定 C-g で E-4 送り)。E-4a で
バイト予算つき LRU を入れる以上、「同一キー → 同一オブジェクト」は **pin 中のみ**
保証へ supersede される (D4)。本ファイルはその新しい機構 —— 古い順の evict・
pin の不可侵・pin 過多でも拒否しない・remove(key) での帳簿掃除 —— を固定する。
identity 契約そのものの supersede は test_resolver.py が担う。
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models.load_result import LoadResult


@pytest.fixture
def wide(tmp_path: Path) -> Iterator[LoadResult]:
    """幅 8 の 2-D uint8 チャンネル ``Wide`` を 1 本持つ実 mf4 のロード結果。

    列 j の値は ``[j, j, j]`` (write_mdf4_wide_2d の規則) なので、どの列を読んだかが
    値だけで判別できる。実ロードを使うのは、テストダブルで鋳造を偽装すると寿命は
    緑のまま鋳造の中身が壊れていても気づけないから (test_resolver.py と同じ方針)。

    **チャンネルキャッシュを明示的に渡す**のが必須 (T2 の配線): ``MdfLoader()`` を
    引数なしで作ると ``handle.cache is None`` になり、``LazyMdfValues.array()`` は
    キャッシュ分岐を 1 度も通らずに毎回 ``select`` する。すると
    ``test_evicted_column_reread_does_not_touch_the_file_again`` の
    ``assert calls == []`` は**実装が完全に正しくても成立しえず**、同テストを狙う
    sabotage S9 も「壊す前から RED」で識別力ゼロになる。production では
    ``Session.__init__`` がこの注入をしている (ここはその最小再現)。

    ハンドルは teardown で必ず閉じる — Windows は開いたままだと tmp_path の後始末が
    ファイルロックで失敗しうる。
    """
    result = MdfLoader(cache=ChannelSampleCache()).load(
        write_mdf4_wide_2d(tmp_path, cols=8)
    )
    assert result.signal_group is not None
    handle = result.signal_group.handle
    assert handle is not None and handle.cache is not None, (
        "fixture 前提: 読みがチャンネルキャッシュへ配線されていない"
    )
    yield result
    handle.close()


def _register(mgr: SignalGroupManager, result: LoadResult) -> str:
    """``column_records`` ごと登録する (渡さないと鋳造が常に None = 偽緑になる)。"""
    group = result.signal_group
    assert group is not None
    assert {s.name for s in group.signals} == {"Wide", "Clean"}, (
        "反転後の形 (setup 前提)"
    )
    return mgr.add(group, column_records=result.column_records)


def test_unpinned_columns_are_evicted_oldest_first(wide: LoadResult) -> None:
    mgr = SignalGroupManager(resolved_capacity=4)
    key = _register(mgr, wide)
    keys = [f"{key}::Wide[{i}]" for i in range(8)]
    for k in keys:
        assert mgr.resolve(k) is not None

    live = mgr.resolved_keys(key)
    assert keys[-1] in live, "直近に鋳造した列が自分自身を落とした"
    assert keys[0] not in live, "最古の列が落ちていない (evict していない)"
    assert len(live) <= mgr.resolved_capacity
    # 鋳造した 8 本は「生きている」か「evict された」かのどちらかしかない。
    assert mgr.resolved_evictions == len(keys) - len(live)


def test_pinned_columns_survive_eviction_pressure(wide: LoadResult) -> None:
    """pin は予算に関係なく残る (spec §5.5) —— これが 316 ms/列 停止の再発防止。"""
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    pinned = f"{key}::Wide[0]"
    first = mgr.resolve(pinned)
    assert first is not None
    mgr.set_pinned_columns({pinned})

    for i in range(1, 8):
        assert mgr.resolve(f"{key}::Wide[{i}]") is not None

    assert mgr.resolved_evictions > 0, "圧力が掛かっていない (setup 失敗 = 反 vacuous)"
    assert pinned in mgr.resolved_keys(key)
    assert mgr.resolve(pinned) is first, "pin 中の列が再鋳造された (D4 の保証違反)"
    assert mgr.mint_count == 8, "pin 済みの列を鋳造し直している"


def test_pins_are_never_refused_and_overflow_is_observable(wide: LoadResult) -> None:
    """pin は拒否しない。予算超過は落とすのではなく **観測可能** にする (D7 と同型)。"""
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    pins = {f"{key}::Wide[{i}]" for i in range(5)}
    mgr.set_pinned_columns(pins)
    for k in sorted(pins):
        assert mgr.resolve(k) is not None

    assert pins <= mgr.resolved_keys(key), "予算超で pin を拒否した"
    assert mgr.pinned_overflow == len(pins) - mgr.resolved_capacity

    # pin が予算を食い尽くしていても、LRU の最低容量は無条件に確保される
    # (0 にすると探索した列がその場で自分を落とし、毎回フル再読みになる)。
    probe = f"{key}::Wide[7]"
    assert mgr.resolve(probe) is not None
    assert probe in mgr.resolved_keys(key), "非 pin 用の最低容量が確保されていない"


def test_a_probe_column_is_not_evicted_by_its_own_minting(wide: LoadResult) -> None:
    """最低容量 (``_MIN_EVICTABLE_COLUMNS``) の **2 つ目の検出器**。

    上の ``test_pins_are_never_refused_and_overflow_is_observable`` は
    ``resolved_keys`` の**メンバシップ**だけを見ており、機構の防波堤がその 1 行しか
    無かった (T3 の sabotage S5 で実測: 31 本中 1 本しか赤くならない)。ここでは
    別の観測点 — **オブジェクト同一性と鋳造カウンタ** — で同じ機構を押さえる。
    どちらか一方の観測点だけを壊す回帰でも必ず捕まえるため。

    症状の形: 最低容量が 0 だと、pin が予算を食い尽くしている状態で鋳造した列が
    evict 走査の中で**自分自身**を落とす。resolve は返り値としては Signal を返す
    ので値は正しく、壊れているのは「2 度目も同じものが返る」だけ — つまりブラウザで
    列を覗くたびに毎回フルチャンネル再読み (316 ms/列) が走る形で、
    ``resolved_keys`` を見ないテストからは完全に不可視になる。
    """
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    mgr.set_pinned_columns({f"{key}::Wide[{i}]" for i in range(5)})
    for i in range(5):
        assert mgr.resolve(f"{key}::Wide[{i}]") is not None

    probe = f"{key}::Wide[7]"
    first = mgr.resolve(probe)
    assert first is not None
    before = mgr.mint_count
    assert mgr.resolve(probe) is first, "鋳造した列が自分自身を落とした"
    assert mgr.mint_count == before, "2 度目の解決が再鋳造になっている"


def test_pinned_column_bytes_counts_only_what_is_materialized(wide: LoadResult) -> None:
    """pin が抱える **実体** バイトだけを数える (Session が予算の裁定者へ渡す値)。

    鋳造しただけの列は 1 バイトも保持していない。「鋳造したから食っている」と
    数えると、ブラウザで覗いただけの列がチャンネルキャッシュの容量を削り、最低容量
    まで痩せて再描画ごとのフルチャンネル再読み (316 ms/列) が復活する。
    introspection が**展開を誘発しない**ことも同時に固定する — 誘発すると、
    pin を push するたびに全 pin 列のフル読みが走る。

    **値配列だけを数えてはならない** (E-4a T3 レビュー I1): プロットされた列は
    ``sorted_view()`` が ``astype(float64)`` で作った**別の実体**も抱えており、
    非 float64 チャンネルではそちらの方が大きい (この fixture の uint8 で 8 倍・
    prod の幅広チャンネルでは 12 KB に対し 96 KB)。取りこぼすと予約が過小になり、
    LRU は「まだ空きがある」と信じて pin + キャッシュの合計が予算を超える。
    """
    mgr = SignalGroupManager(resolved_capacity=8)
    key = _register(mgr, wide)
    pinned, unpinned = f"{key}::Wide[0]", f"{key}::Wide[1]"
    first, second = mgr.resolve(pinned), mgr.resolve(unpinned)
    assert first is not None and second is not None
    mgr.set_pinned_columns({pinned})

    assert mgr.pinned_column_bytes() == 0, "未展開の pin が予算を食っている"
    assert first._values_source.is_materialized is False, (
        "introspection が展開を誘発した"
    )
    assert getattr(first, "_sorted_view_cache", None) is None, (
        "introspection が sorted_view を誘発した"
    )

    values = np.asarray(first.values)  # ここで初めて実体を持つ
    assert values.nbytes == 3, values.nbytes  # 3 サンプル x uint8 (fixture の規則)
    assert mgr.pinned_column_bytes() == 3

    # render 相当。単調な信号なので sorted_view の時刻軸は master と同一オブジェクト
    # (= master 非計上の種まきで畳まれる) だが、値は float64 の別配列になる。
    _ts, vs64 = first.sorted_view()
    assert vs64.nbytes == 24, vs64.nbytes  # 3 サンプル x float64
    assert _ts is first.timestamps, "master が別配列になった (前提が崩れている)"
    assert mgr.pinned_column_bytes() == 27, "float64 ビューの実体を取りこぼしている"

    _ = second.values  # 非 pin を展開しても reserved は動かない
    second.sorted_view()
    assert mgr.pinned_column_bytes() == 27, "非 pin の実体を数えている"


def test_pinned_column_bytes_excludes_the_shared_master(wide: LoadResult) -> None:
    """master は pin の予約に **載せない** (グループ側の帳簿に属する)。

    鋳造列は親物理チャンネルの master を同一オブジェクトのまま共有する
    (``_mint_column``)。ここで数えると (a) 同じ配列を pin 列の本数だけ二重計上し
    (prod は 1 チャンネル 1,100 列)、(b) 「未展開の pin は 0」という契約も破れる
    (未展開でも master のバイトが立つ)。teardown 側は逆に master ごと解放するので
    数える — その 1 点だけが 2 つの呼び出し側の差で、共有ヘルパの ``seen`` 種まきで
    表現している。
    """
    mgr = SignalGroupManager(resolved_capacity=8)
    key = _register(mgr, wide)
    a, b = f"{key}::Wide[0]", f"{key}::Wide[1]"
    sig_a, sig_b = mgr.resolve(a), mgr.resolve(b)
    assert sig_a is not None and sig_b is not None
    assert sig_a.timestamps is sig_b.timestamps, "兄弟列は master を共有する (前提)"
    assert sig_a.timestamps.nbytes == 24, sig_a.timestamps.nbytes

    mgr.set_pinned_columns({a, b})
    assert mgr.pinned_column_bytes() == 0, "未展開なのに master を数えている"

    _ = sig_a.values
    _ = sig_b.values
    # master を数えていれば 3+3+24 = 30 になる (兄弟で共有なので 1 回だけ数えても)。
    assert mgr.pinned_column_bytes() == 6, "master を予約に載せている"


def test_lru_order_is_recency_not_insertion(wide: LoadResult) -> None:
    """ヒットは recency を更新する (プロット中の列は render のたびにここを通る)。"""
    mgr = SignalGroupManager(resolved_capacity=3)
    key = _register(mgr, wide)
    a, b, c, d = (f"{key}::Wide[{i}]" for i in range(4))
    first_a = mgr.resolve(a)
    mgr.resolve(b)
    mgr.resolve(c)
    assert mgr.resolve(a) is first_a  # ヒット = touch

    mgr.resolve(d)
    live = mgr.resolved_keys(key)
    assert a in live, "最近触れた列が最古扱いで落ちた (touch が効いていない)"
    assert b not in live, "最古の列が残っている (evict 順が recency でない)"


def test_removing_a_group_drops_its_columns_from_the_lru(wide: LoadResult) -> None:
    """remove(key) は recency 表からも外す (残すとアンロード済みキーが枠を食う)。"""
    mgr = SignalGroupManager(resolved_capacity=4)
    key = _register(mgr, wide)
    col = f"{key}::Wide[0]"
    minted = mgr.resolve(col)
    assert mgr.resolved_lru_keys() == (col,)

    _group, columns = mgr.remove(key)
    assert columns == (minted,)  # teardown 会計 (T4) の入口は不変
    assert mgr.resolved_lru_keys() == (), "アンロード済みキーが recency 表に残った"


def test_evicted_column_reread_does_not_touch_the_file_again(wide: LoadResult) -> None:
    """evict された列は **新しい Signal** になるが、読みは T2 のチャンネル
    キャッシュに当たるので ``select`` は 1 回も増えない。

    これが「pin されなかった列を落として良い」根拠そのもの: 落としたコストは
    「オブジェクトの作り直し」だけで、ファイル I/O は戻ってこない。
    """
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    group = wide.signal_group
    assert group is not None
    handle = group.handle
    assert handle is not None

    col = f"{key}::Wide[0]"
    first = mgr.resolve(col)
    assert first is not None
    expected = np.asarray(first.values)  # 1 回目の実読み (ここで select が走る)

    calls: list[Any] = []
    real_select = handle.mdf.select

    def counting_select(entries: Any, **kwargs: Any) -> Any:
        calls.append(entries)
        return real_select(entries, **kwargs)

    handle.mdf.select = counting_select  # type: ignore[method-assign]

    for i in range(1, 8):
        assert mgr.resolve(f"{key}::Wide[{i}]") is not None
    again = mgr.resolve(col)
    assert again is not None
    assert again is not first, "evict されていない (setup 失敗 = 反 vacuous)"
    assert np.array_equal(np.asarray(again.values), expected)
    assert calls == [], f"再鋳造がファイルを読み直した: {calls}"


# ─── 解放は _resolved_lock の外 (E-4c §5・E-4 親 spec §12-2) ───────────────────


class _LockProbe:
    """解放される瞬間に「``_resolved_lock`` が握られていたか」を記録する番人。

    ``threading.Lock`` は非再帰なので、保持中のスレッドが ``acquire(blocking=False)``
    しても False が返る — これが「今 lock 下か」の直接観測になる
    (``test_channel_cache.py`` の ``_LockProbeArray`` と同型)。

    **ndarray サブクラスにしないのは取り付け口が違うから**: あちらは追い出される
    実体が ndarray そのものなので観測子になれる。こちらで落ちるのは **Signal** で、
    ``__slots__`` を持つため属性を足せず、値配列は ``LazyMdfValues`` の私有キャッシュ
    の中にあって差し替えられない。Signal と寿命が完全に一致して外から書ける唯一の
    口が ``metadata`` dict である (鋳造列の metadata は ``_mint_column`` が毎回
    新しく作るので、親チャンネルと共有していない)。

    参照は lock と記録用リストだけに留める (manager を参照すると循環になり、解放が
    refcount でなく gc 任せ = 非決定になる)。
    """

    def __init__(self, lock: threading.Lock, observed: list[bool]) -> None:
        self._lock = lock
        self._observed = observed

    def __del__(self) -> None:
        acquired = self._lock.acquire(blocking=False)
        self._observed.append(not acquired)
        if acquired:
            self._lock.release()


def _probe_column(mgr: SignalGroupManager, column_key: str) -> list[bool]:
    """*column_key* を鋳造し、その Signal へ観測子を仕込んで記録先を返す。"""
    observed: list[bool] = []
    sig = mgr.resolve(column_key)
    assert sig is not None
    sig.metadata["lock_probe"] = _LockProbe(mgr._resolved_lock, observed)
    del sig  # 帳簿だけが持つ状態にする (以後の解放は必ず evict 由来)
    return observed


def _drop_via_resolve_minting(wide: LoadResult) -> list[bool]:
    """**ホットパス**: 鋳造が容量を超えて古い列を落とす経路 (GUI の render)。"""
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    observed = _probe_column(mgr, f"{key}::Wide[0]")
    for i in range(1, 8):
        assert mgr.resolve(f"{key}::Wide[{i}]") is not None
    assert mgr.resolved_evictions > 0, "evict が起きていない (setup 失敗 = 反 vacuous)"
    # probe 列自身が evict されていることを mgr 生存中に pin する。ここを欠くと
    # 「何かが evict された」しか見ておらず、probe 列だけが生き残って mgr の
    # フレーム破棄で lock 非保持下に __del__ すると observed == [False] のまま
    # 両 param とも vacuous に緑になる (レビュー I1・newest-first 改竄で実証済み)。
    assert observed, "probe 列が evict されていない (test が空回りしている)"
    return observed


def _drop_via_unpinning(wide: LoadResult) -> list[bool]:
    """pin 集合の差し替え (``Session.set_pinned_columns``) が落とす経路。

    ``resolve`` は鋳造のたびに evict するので、容量超過は **pin でしか作れない**:
    5 本を pin して帳簿を容量 2 の上へ押し上げ、pin を外した瞬間に
    ``set_pinned_columns`` 側の ``_evict_resolved`` が 4 本落とす。
    """
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    mgr.set_pinned_columns({f"{key}::Wide[{i}]" for i in range(5)})
    observed = _probe_column(mgr, f"{key}::Wide[0]")
    for i in range(1, 5):
        assert mgr.resolve(f"{key}::Wide[{i}]") is not None
    assert mgr.resolved_evictions == 0, "pin 中に落ちた (setup 前提が崩れている)"
    mgr.set_pinned_columns(set())
    assert mgr.resolved_evictions > 0, "unpin で落ちていない (反 vacuous)"
    # 同上 (resolve_minting 側と同じ反 vacuous ガード・レビュー I1)。
    assert observed, "probe 列が evict されていない (test が空回りしている)"
    return observed


@pytest.mark.parametrize(
    "drop",
    [_drop_via_resolve_minting, _drop_via_unpinning],
    ids=["resolve_minting", "unpinning"],
)
def test_evicted_columns_are_freed_outside_the_lock(
    drop: Callable[[LoadResult], list[bool]], wide: LoadResult
) -> None:
    """``_evict_resolved`` が外した列の解放は ``_resolved_lock`` の外で走る。

    lock 下で最後の参照が死ぬ形だと、列 1 本ぶんの実体 (値配列 + ``sorted_view``
    が作る float64 ビュー・prod 実測 ~108 KB/列) の dealloc がこの lock を握った
    まま走る。E-4b でエクスポートワーカーが同じ lock の取り手になった (spec F6 =
    defer 根拠の失効) ので、GUI の ``resolve()`` がその dealloc を待つ形になる。
    **症状は待ち時間だけで会計にも数字にも出ない** — だから会計ではなく解放の
    瞬間そのものを観測する。

    **2 経路とも回す** (E-4a の同型テストが踏んだ轍 ``test_channel_cache.py:473-477``:
    最初に塞いだ 1 経路だけを見ていて、残り 2 経路は両方 ``[True]`` だった)。
    """
    observed = drop(wide)

    assert observed == [False], (
        f"鋳造列の解放が _resolved_lock 保持下で走った: {observed}"
    )
