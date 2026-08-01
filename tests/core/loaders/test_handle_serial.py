"""キャッシュキーの第 1 成分を id(handle) から MdfHandle.serial へ (E-4b・spec §5.7-1)。

id() は **生存中のオブジェクト間でのみ** 一意で、閉じたハンドルのアドレスは次の
ロードが再利用する (実測 100% 再利用・memory gui_id_reuse_flake_object_recreation)。
今日は「close の前に drop_handle」という**手順**でしか守られておらず、手順を 1 箇所
忘れると別ファイルの 2-D を引き当てる (長さが合えば例外も出ない = サイレント誤データ)。
serial 化でこの窓が**構造的に**消えることを固定する。

demo_data に依存しない (ndarray と偽ハンドルだけで全経路を踏める)。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import numpy as np

from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.models.sample_source import LazyMdfValues


class _FakeMdf:
    def close(self) -> None:
        pass


class _Stub2D:
    """select が 4 レコード x 2 列の 2-D を **fill で識別できる値** で返す最小 MDF。

    **2-D であることが要件**: ``sample_source`` のスカラー除外
    (``samples.ndim > 1 or samples.dtype.names``) により 1-D 非構造化配列は
    そもそも ``put`` に到達しないので、1-D スタブだとキャッシュ経路を 1 行も
    踏まない (= キーの検証が構造的に不可能になる)。
    """

    def __init__(self, fill: float) -> None:
        self.fill = fill
        self.select_calls = 0

    def select(self, entries: Any, **kwargs: Any) -> list[Any]:
        self.select_calls += 1
        return [SimpleNamespace(samples=np.full((4, 2), self.fill, dtype=np.float64))]

    def close(self) -> None:
        pass


def test_serial_is_strictly_increasing_across_handles() -> None:
    a = MdfHandle(_FakeMdf())
    b = MdfHandle(_FakeMdf())
    assert b.serial > a.serial


def test_recycled_address_does_not_recycle_the_serial() -> None:
    """id 再利用を **強制再現** し、serial が follow しないことを見る。

    参照を落として同型のオブジェクトを作り直すと CPython はアドレスを再利用する。
    id ベースのキーではここで A のエントリを B が引く。

    **早期 return で核心 assert を素通しさせない** (spec §7.3「id 強制再現…で
    固定」): 1 回で再利用が起きないことはあるので、**同サイズを即時再確保**する
    形で N 回リトライし、**一度も再現しなければ fail** する。「再現しなかったので
    単調性だけ見た」を許すと、この test は id 再利用に対して恒久的に無力になる
    (memory `gui_id_reuse_flake_object_recreation` と同じ罠の裏返し)。
    """
    cache = ChannelSampleCache(budget_bytes=4096)
    reproduced = False
    for _ in range(50):
        a = MdfHandle(_FakeMdf(), cache=cache)
        a_id, a_serial = id(a), a.serial
        cache.put((a_serial, 0, 0), np.zeros(64, dtype=np.uint8))
        del a  # drop_handle を **わざと呼ばない** (手順に頼らないことの検証)

        b = MdfHandle(_FakeMdf(), cache=cache)  # 同サイズを即時再確保
        assert b.serial != a_serial  # 単調性は毎回見る
        if id(b) == a_id:
            reproduced = True
            assert cache.get((b.serial, 0, 0)) is None, "別ファイルの 2-D を引き当てた"
            break
        del b
    assert reproduced, (
        "50 回試して id 再利用が一度も起きなかった — 核心 assert "
        "(cache.get((b.serial, 0, 0)) is None) を一度も実行できていない"
    )


def test_a_recycled_address_does_not_serve_another_handles_channel() -> None:
    """**production の読み経路**を通した id 再利用 (上のテストの歯を実装側へ届かせる)。

    上の ``test_recycled_address_does_not_recycle_the_serial`` はキーを**テストが
    自分で組み立てて**いるので、``MdfHandle.serial`` さえ在れば
    ``sample_source.array()`` のキーを ``id(self._handle)`` へ戻す変異 (S1) でも
    緑のまま通る = 置換サイトそのものには盲目である。ここは
    ``LazyMdfValues.array()`` に**キーを組ませて**同じ窓を踏むので、置換サイトが
    1 つでも id へ戻ると「別ファイルの 2-D が例外なしで返る」形で RED になる。

    ハンドル A のブロックを B に確実に再利用させるため、**B のスタブを先に確保**
    してから A を解放する (A の dealloc がフリーリストの先頭に来た直後に
    ``MdfHandle.__new__`` が同サイズを要求する形)。
    """
    cache = ChannelSampleCache(budget_bytes=1 << 20)
    reproduced = False
    for _ in range(50):
        a = MdfHandle(_Stub2D(1.0), cache=cache)
        a_id = id(a)
        src_a = LazyMdfValues(a, "ch", 0, 0, length=4)
        np.testing.assert_array_equal(src_a.array(), np.full((4, 2), 1.0))
        assert cache.bytes_held > 0, "2-D がキャッシュに載っていない (setup 失敗)"

        stub_b = _Stub2D(2.0)  # A の解放より **前** に確保 (ブロックを奪わせない)
        del src_a  # LazyMdfValues が handle を握っているので先に落とす
        del a  # drop_handle も close も **わざと呼ばない** (手順に頼らない検証)

        b = MdfHandle(stub_b, cache=cache)
        if id(b) == a_id:
            reproduced = True
            got = LazyMdfValues(b, "ch", 0, 0, length=4).array()
            np.testing.assert_array_equal(
                got,
                np.full((4, 2), 2.0),
                err_msg="アドレスを再利用したハンドルが別ファイルの 2-D を引き当てた",
            )
            # 反 vacuous: 実際に読みが走ったこと (= キャッシュに当たらなかったこと)
            # を独立に見る。値だけだと「たまたま同じ値」で緑になる形を許す。
            assert stub_b.select_calls == 1
            break
        del b
    assert reproduced, (
        "50 回試して id 再利用が一度も起きなかった — 核心 assert "
        "(B が B 自身の 2-D を読む) を一度も実行できていない"
    )


def test_serials_are_unique_under_concurrent_construction() -> None:
    """2 スレッド同時ロード (実際に踏める形) でも serial は衝突しない。"""
    handles: list[MdfHandle] = []
    lock = threading.Lock()

    def make() -> None:
        local = [MdfHandle(_FakeMdf()) for _ in range(200)]
        with lock:
            handles.extend(local)

    threads = [threading.Thread(target=make) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    assert len({h.serial for h in handles}) == 400


def test_close_releases_by_serial_not_by_address() -> None:
    """close() の backstop (release_handle) も serial で引く。"""
    cache = ChannelSampleCache(budget_bytes=4096)
    handle = MdfHandle(_FakeMdf(), cache=cache)
    cache.put((handle.serial, 1, 2), np.zeros(64, dtype=np.uint8))
    assert cache.bytes_held == 64
    handle.close()
    assert cache.bytes_held == 0
