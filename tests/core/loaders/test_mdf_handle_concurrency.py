"""MdfHandle / LazyMdfValues の並行契約 (増分B Task 7)。

**demo_data に依存しない**: 自然な宛先に見える ``tests/core/loaders/test_lazy_mdf_values.py``
は module-level の demo skipif (``demo_data/quick_demo.mf4``) を持ち、``demo_data/`` は
gitignore 済み・CI に生成ステップが無いため**丸ごと skip される** (同じ gate を持つ
ファイルは 5 本)。固定ユーザー決定 (``_closed`` は読み直列化 lock の外で立て続ける) を
守る唯一の機構がそこに着地すると CI 執行力ゼロで main に乗るため、ここに置く。
``tests/lazy_stubs.py`` が同じ罠への既存対処。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from asammdf import MDF

from tests.mdf4_helpers import write_mdf4
from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.models.sample_source import LazyMdfValues, SampleReadError

_BOUND_S = 2.0  # 全ての待ちは有界 (デッドロック時にハングでなく失敗させる)


def _wait_until(pred: Any, timeout: float = _BOUND_S) -> bool:
    """*pred* が真になるまで有界待ちする (ポーリング — 待ち対象が複合条件のため)."""
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if pred():
            return True
        time.sleep(0.001)
    return pred()


# ─── 項目 2: `_closed` のアトミック化 ────────────────────────────────────────


class _CloseSpy:
    """mdf.close() の呼び出し回数だけを記録する最小スタブ."""

    def __init__(self) -> None:
        self.calls = 0

    def close(self) -> None:
        self.calls += 1


class _InterleavedHandle(MdfHandle):
    """基底 __slots__ の記述子を property で shadow し、``_closed`` の
    「読み」と「書き」の間に決定的な引き渡し点を作る。

    素朴な ``threading.Barrier`` 版は使えない: 実 MdfHandle に対する barrier 同期
    2 スレッド競合は 0/17,000 試行 (2/8 スレッド x ``sys.setswitchinterval``
    5ms/1e-5/1e-6/1e-9 x GIL 負荷 spinner 有無) で二重 close を再現できなかった
    (Windows の GIL 引き渡しはタイマー付き condvar 待ちで粒度が粗く、~4 バイトコードの
    check-and-set 窓に落ちない)。

    罠 (a): yield は基底スロットを **読んだ後** に置く。先頭で yield すると
            壊れたコードでも calls == 1 になり false-green (実測確認済み)。
    罠 (b): 引き渡しは **有界待ち** にする。素の join() だと修正後の実装が
            デッドロックしてテストがハングする。
    """

    def __init__(self, mdf: Any, gate: Any, resumed: Any) -> None:
        super().__init__(mdf)
        self._gate = gate
        self._resumed = resumed
        self._yielded = False

    @property  # type: ignore[override]
    def _closed(self) -> bool:
        value: bool = MdfHandle._closed.__get__(self)  # type: ignore[attr-defined] # ← 先に読む
        if not self._yielded:
            self._yielded = True
            self._gate.set()
            self._resumed.wait(0.5)
        return value

    @_closed.setter
    def _closed(self, value: bool) -> None:
        MdfHandle._closed.__set__(self, value)  # type: ignore[attr-defined]


def test_concurrent_close_calls_mdf_close_once() -> None:
    """production では二重 close は無害 (asammdf 8.8.22 の MDF4.close() 自身が
    ``if self._closed: return`` を持ち、MdfHandle.close() は self.lock 下で呼ぶ)。
    **これは固定ユーザー決定が要求する内部契約の pin であってバグ回帰テストではない** —
    将来「無害だから」と削除しないこと。
    """
    spy = _CloseSpy()
    gate, resumed = threading.Event(), threading.Event()
    handle = _InterleavedHandle(spy, gate, resumed)

    a = threading.Thread(target=handle.close)
    a.start()
    assert gate.wait(1.0), "A が _closed を読む前に止まった (setup 失敗)"
    b = threading.Thread(target=handle.close)
    b.start()
    time.sleep(0.05)  # 壊れた実装なら B がここで mdf.close() まで走り抜ける
    resumed.set()
    a.join(timeout=_BOUND_S)
    b.join(timeout=_BOUND_S)

    # 「専用 lock を使っているか」はこの assert では検出できない — check-and-set を
    # handle.lock 下へ入れた変異は A が lock を握ったまま gate で止まり B が待つだけで、
    # 再開後は calls == 1 になり **PASS する**。専用 lock の検証は
    # test_close_during_in_flight_reads_never_crashes が担う (in-flight read が
    # handle.lock を握ったまま is_closed が True になることを見る)。
    assert not a.is_alive() and not b.is_alive(), (
        "引き渡しがハングした — 有界待ちが効いていない"
    )
    assert spy.calls == 1, f"mdf.close() が {spy.calls} 回"


# ─── 項目 3: double-checked read ─────────────────────────────────────────────


class _FakeASignal:
    def __init__(self, samples: np.ndarray) -> None:
        self.samples = samples


class _FakeMdf:
    """select 呼び出しを数える最小 MDF スタブ (毎回 **別オブジェクト** を返す)."""

    def __init__(self, n: int = 4) -> None:
        self.select_calls = 0
        self.closed = False
        self._n = n
        self.before_select: Any = None  # 決定的インターリーブ用フック

    def select(self, entries: Any, **kwargs: Any) -> list[_FakeASignal]:
        self.select_calls += 1
        if self.before_select is not None:
            self.before_select()
        return [_FakeASignal(np.arange(self._n, dtype=np.float64))]

    def close(self) -> None:
        self.closed = True


class _CountingLock:
    """acquire を数えるラッパ (``MdfHandle.__slots__`` の "lock" へ差し替える).

    ``waiters`` は「``with handle.lock`` に到達したスレッド」の集合 — つまり
    array() の **lock 前の fast-path を通過済み**であることの観測点。set.add は
    GIL 下で不可分なので、素の ``+= 1`` と違って取りこぼさない。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.acquires = 0
        self.waiters: set[int] = set()

    def __enter__(self) -> _CountingLock:
        self.waiters.add(threading.get_ident())
        self.acquires += 1
        self._lock.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._lock.release()


def _fake_handle(n: int = 4) -> tuple[MdfHandle, _FakeMdf, _CountingLock]:
    mdf = _FakeMdf(n)
    handle = MdfHandle(mdf)
    lock = _CountingLock()
    handle.lock = lock  # type: ignore[assignment]
    return handle, mdf, lock


def test_concurrent_first_reads_select_once() -> None:
    """2 スレッドが同時に初回 array() へ到達しても select はちょうど 1 回。

    lock 内の再チェック (double-checked の "second check") を消すと 2 回になる。
    既存 ``assert src.array() is got`` は単一スレッドなので再チェックを消しても通り、
    ``test_lazy_reads_are_serialized_by_handle_lock`` は 8 個の別インスタンスなので
    同一インスタンスの二重初期化に盲目 (しかも同ファイルは CI で skip)。
    """
    handle, mdf, lock = _fake_handle()
    src = LazyMdfValues(handle, "ch", 0, 1, length=4)

    # 先行スレッドの select を「もう一方も lock 前の fast-path を抜けた」まで
    # 押さえることで、二重初期化の窓を決定的に開く (実時間 sleep に頼らない)。
    mdf.before_select = lambda: _wait_until(lambda: len(lock.waiters) >= 2)

    start = threading.Barrier(2, timeout=_BOUND_S)
    results: dict[int, Any] = {}

    def _read(idx: int) -> None:
        start.wait()
        results[idx] = src.array()

    threads = [threading.Thread(target=_read, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=_BOUND_S * 2)
    assert all(not t.is_alive() for t in threads), "読みスレッドが終わらない"

    assert mdf.select_calls == 1, f"select が {mdf.select_calls} 回 (再チェック消失?)"
    assert results[0] is results[1], "両スレッドが同じキャッシュ配列を得ていない"
    assert len(lock.waiters) >= 2, (
        "片方が lock 前の fast-path に到達していない (setup 失敗)"
    )


def test_cache_hit_takes_no_lock() -> None:
    """キャッシュヒットは handle.lock を取らない (タイミング assert は使わない)。

    ``MdfHandle.__slots__`` に "lock" があるので、取得回数を数えるラッパへ
    差し替えられる。
    """
    handle, _mdf, lock = _fake_handle()
    src = LazyMdfValues(handle, "ch", 0, 1, length=4)

    first = src.array()
    assert lock.acquires == 1, "初回 array() は lock を 1 回取るはず"

    lock.acquires = 0
    again = src.array()

    assert again is first
    assert lock.acquires == 0, "キャッシュヒットで lock を取っている"


def test_lazy_array_if_materialized_probes_without_materializing() -> None:
    """実 LazyMdfValues の ``array_if_materialized()`` 契約 (teardown の id-dedup の土台)。

    teardown 会計はこの API だけで共有配列を dedup するので、(a) 未展開では読みを
    誘発せず None、(b) 展開後は **同一オブジェクト** (コピーを返す実装だと dedup が
    無意味になる) の 2 点が要る。テスト double 経由でしか触られていなかったため
    実装本体を直接 pin する。
    """
    handle, mdf, _lock = _fake_handle()
    src = LazyMdfValues(handle, "ch", 0, 1, length=4)

    assert src.array_if_materialized() is None
    assert src.is_materialized is False
    assert mdf.select_calls == 0, "probe が遅延読みを誘発している"

    got = src.array()
    assert src.array_if_materialized() is got  # `==` では dedup の証明にならない


# ─── 長さ不変条件: 宣言 length と実読み列 ────────────────────────────────────


def test_lazy_read_length_mismatch_raises_sample_read_error() -> None:
    """実読み列が宣言 length と食い違ったら SampleReadError (黙って通さない)。

    ``Signal.__post_init__`` の長さ検証は展開を避けるため ``source.length`` しか
    見ない。遅延側では length は **宣言値** (``len(master)``) なので、follower の
    レコード数が master とずれる仮想グループ (v4.20+ remote-master/column-storage)
    では構築時検証を通り抜ける。render の ``ts[lo:hi]`` / ``vs[lo:hi]`` は numpy が
    黙って clamp するため、検出しなければ「エラーにならない誤った波形」になる。
    ここで SampleReadError にしてブランチ既設の degrade 機構 (診断 + ステータス)
    へ流す。

    このファイルへ置く理由は module docstring と同じ — ``test_lazy_mdf_values.py`` /
    ``test_mdf_loader_lazy.py`` は demo_data gate で CI では丸ごと skip される。
    """
    handle, mdf, _lock = _fake_handle(n=3)  # select は 3 サンプル返す
    src = LazyMdfValues(handle, "ch", 0, 1, length=4)  # 宣言は 4

    with pytest.raises(SampleReadError, match="サンプル数"):
        src.array()

    assert mdf.select_calls == 1, "select が呼ばれていない (setup 失敗)"
    # 壊れた列をキャッシュに焼き付けない (再読みの余地を残す・展開会計も汚さない)
    assert src.array_if_materialized() is None
    assert src.is_materialized is False


# ─── 並行契約: close と in-flight read ───────────────────────────────────────


def _channel_entries(mdf: MDF) -> list[tuple[str, int, int, int]]:
    """(name, gi, ci, length) を master 以外の全チャンネルについて返す."""
    out: list[tuple[str, int, int, int]] = []
    for gi, group in enumerate(mdf.groups):
        master_ci = mdf.masters_db.get(gi)
        for ci, ch in enumerate(group.channels):
            if ci == master_ci:
                continue
            out.append((ch.name, gi, ci, group.channel_group.cycles_nr))
    return out


def test_close_during_in_flight_reads_never_crashes(
    tmp_path: Path, request: Any
) -> None:
    """close() は mdf.close() を handle.lock 下で呼ぶので in-flight select を中断しない。

    待機中の reader は is_closed を **lock 内で** 見て SampleReadError。array() の
    lock 前にキャッシュ読みと closed 先行 bail を足したので、**lock 内の is_closed
    判定まで一緒に外へ出す TOCTOU** をこのテストが塞ぐ。

    順序は決定的に組む: reader #1 を select の中で止め、残り 39 が lock 待ちに
    入り切ってから close を要求する。よって「in-flight は完走」「待機中は
    閉鎖エラー」の両方が毎回成立し、lock 内判定を消すと待機中の reader が
    閉じた MDF を実際に読みに行って別種の失敗になる (= RED)。
    """
    path = write_mdf4(
        tmp_path / "concurrent.mf4",
        [
            {
                "name": f"ch{i:02d}",
                "timestamps": np.arange(64, dtype=np.float64),
                "values": np.arange(64, dtype=np.float64) + i,
            }
            for i in range(40)
        ],
    )
    mdf = MDF(str(path))
    handle = MdfHandle(mdf)
    lock = _CountingLock()
    handle.lock = lock  # type: ignore[assignment]

    entries = _channel_entries(mdf)
    assert len(entries) == 40, f"fixture が 40ch でない: {len(entries)}"

    in_select = threading.Event()
    release = threading.Event()
    real_select = mdf.select

    def _gated_select(*a: Any, **k: Any) -> Any:
        if not in_select.is_set():
            in_select.set()
            release.wait(_BOUND_S)  # 有界 — 取りこぼしてもハングさせない
        return real_select(*a, **k)

    mdf.select = _gated_select  # type: ignore[assignment]

    def _cleanup() -> None:
        # 4 つの setup assert のどれかで落ちると closer スレッドまで到達せず、
        # 実 mf4 が mmap されたまま残って tmp_path の後片付けが Windows で失敗し、
        # 1 件の正直な失敗が別のエラーに埋もれる。release を先に解放してから
        # close する (close は handle.lock を取るので、gated select を止めたままだと
        # 後片付け自身が待たされる)。close は冪等。
        release.set()
        handle.close()

    request.addfinalizer(_cleanup)

    outcomes: list[tuple[str, BaseException | None]] = []
    outcomes_lock = threading.Lock()

    def _read(name: str, gi: int, ci: int, length: int) -> None:
        src = LazyMdfValues(handle, name, gi, ci, length=length)
        try:
            src.array()
            err: BaseException | None = None
        except BaseException as exc:  # どんな失敗も記録して assert する
            err = exc
        with outcomes_lock:
            outcomes.append((name, err))

    readers = [threading.Thread(target=_read, args=e) for e in entries]
    for t in readers:
        t.start()

    assert in_select.wait(_BOUND_S), "reader #1 が select に入らない (setup 失敗)"
    assert _wait_until(lambda: len(lock.waiters) >= 40), (
        f"lock 待ちに入った reader が {len(lock.waiters)} 本 (setup 失敗)"
    )

    closer = threading.Thread(target=handle.close)
    closer.start()
    assert _wait_until(lambda: handle.is_closed), (
        "close 要求が届いていない (setup 失敗)"
    )
    release.set()

    for t in readers:
        t.join(timeout=_BOUND_S * 5)
    closer.join(timeout=_BOUND_S * 5)
    assert all(not t.is_alive() for t in readers) and not closer.is_alive()

    ok = [n for n, e in outcomes if e is None]
    failed = [(n, e) for n, e in outcomes if e is not None]
    assert len(outcomes) == 40
    assert ok, "in-flight の select が完走していない (close が読みを中断した)"
    # sabotage で最初に落ちるのはここ: lock 内 is_closed を消すと、先行 bail を
    # 通過済みの reader が「閉じる約束のハンドル」から読み切ってしまう (TOCTOU)。
    assert failed, (
        "close 要求後に lock を取った reader が 1 本も閉鎖エラーにならなかった "
        "— lock 内の is_closed 判定が無い (TOCTOU)"
    )
    for name, err in failed:
        assert isinstance(err, SampleReadError), f"{name}: {type(err).__name__} {err}"
        # 閉じた MDF を実際に読みに行くと、閉鎖エラーでなく生の I/O 例外を包んだ
        # 別文言になる (lock 取得順が close より後ろに回った reader の側の症状)。
        assert "閉じられています" in str(err), (
            f"{name}: 閉じた MDF を実際に読みに行っている (lock 内 is_closed 判定が無い): {err}"
        )

    # close 後の新規読みも閉鎖エラー (先行 bail)
    name, gi, ci, length = entries[0]
    with pytest.raises(SampleReadError, match="閉じられています"):
        LazyMdfValues(handle, name, gi, ci, length=length).array()
