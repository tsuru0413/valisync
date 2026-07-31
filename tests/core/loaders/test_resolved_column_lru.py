"""鋳造列 LRU と pin の規則 (E-4a spec §5.5 / D4)。

E-3 は `_resolved_by_key` を無制限に持っていた (決定 C-g で E-4 送り)。E-4a で
バイト予算つき LRU を入れる以上、「同一キー → 同一オブジェクト」は **pin 中のみ**
保証へ supersede される (D4)。本ファイルはその新しい機構 —— 古い順の evict・
pin の不可侵・pin 過多でも拒否しない・remove(key) での帳簿掃除 —— を固定する。
identity 契約そのものの supersede は test_resolver.py が担う。
"""

from __future__ import annotations

from collections.abc import Iterator
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


def test_pinned_column_bytes_counts_only_what_is_materialized(wide: LoadResult) -> None:
    """pin が抱える **実体** バイトだけを数える (Session が予算の裁定者へ渡す値)。

    鋳造しただけの列は 1 バイトも保持していない。「鋳造したから食っている」と
    数えると、ブラウザで覗いただけの列がチャンネルキャッシュの容量を削り、最低容量
    まで痩せて再描画ごとのフルチャンネル再読み (316 ms/列) が復活する。
    introspection が**展開を誘発しない**ことも同時に固定する — 誘発すると、
    pin を push するたびに全 pin 列のフル読みが走る。
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

    values = np.asarray(first.values)  # ここで初めて実体を持つ (render 相当)
    assert values.nbytes == 3, values.nbytes  # 3 サンプル x uint8 (fixture の規則)
    assert mgr.pinned_column_bytes() == values.nbytes

    _ = second.values  # 非 pin を展開しても reserved は動かない
    assert mgr.pinned_column_bytes() == values.nbytes, "非 pin の実体を数えている"


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
