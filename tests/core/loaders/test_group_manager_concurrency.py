# ruff: noqa: RUF002
"""SignalGroupManager の並行性 (E-4b・spec §5.7-2/-3)。

E-4b は export worker の resolve を ~18 分走らせるので、親 spec §12-5 が「窓」と
記録した競合が **常態** になる。窓を自分で広げながら繰越にはできない (C-2/MG-5)。

demo_data 非依存 — 合成 SignalGroup で add/resolve/namespace 構築のすべてを踏める。
"""

from __future__ import annotations

import datetime
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup


def _sig(name: str, v: float) -> Signal:
    return Signal(
        name=name,
        timestamps=np.arange(2, dtype=np.float64),
        values=np.array([v, v + 1.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="x.csv",
    )


def _group(name: str, n: int = 2) -> SignalGroup:
    return SignalGroup(
        signals=tuple(_sig(f"{name}_{i}", float(i)) for i in range(n)),
        source_path=Path.cwd() / f"{name}.csv",
        file_format="CSV",
        loaded_at=datetime.datetime.now(),
    )


_BOUND_S = 10.0  # join の有界待ち (壊れた実装がハングしてもテストは終わる)


class _InterleavedCounters(dict):  # type: ignore[type-arg]
    """``_counters.get()`` の **読みの直後** に決定的な引き渡し点を作る。

    素朴な多スレッド add ではこの窓に落ちない — 下の
    ``test_concurrent_add_keeps_every_counter_and_key`` を **ロック無しの実装**
    (= 修正前) に対して 5 回回して 0 回 RED であることを実測した。同型の実測は
    ``_InterleavedCache`` (test_channel_cache.py) / ``_InterleavedHandle``
    (test_mdf_handle_concurrency.py・17,000 試行 0 ヒット) にも記録があり、
    Windows の GIL 引き渡しは数バイトコードの窓に入らない。だから窓を明示的に開ける。

    罠 (a): yield は ``dict.get`` を**読んだ後**に置く。先頭で yield すると壊れた
            実装でもキーが衝突せず緑になる。
    罠 (b): 引き渡しは**有界待ち**にする。素の wait() だと修正後の実装
            (B が lock で待つので誰も resumed を立てない) でハングする。

    **この probe は ``self._counters.get(prefix, 0)`` という書き方に依存する**。
    ``try: self._counters[prefix] ... except KeyError`` へ書き換えると窓の観測点が
    消えて黙って盲目になるので、書き換えるならここも一緒に動かすこと。
    """

    def __init__(self, gate: threading.Event, resumed: threading.Event) -> None:
        super().__init__()
        self._gate = gate
        self._resumed = resumed
        self._yielded = False

    def get(self, key, default=None):  # type: ignore[no-untyped-def, override]
        value = super().get(key, default)  # ← 先に読む (罠 a)
        if not self._yielded:
            self._yielded = True
            self._gate.set()
            self._resumed.wait(0.5)  # 有界 (罠 b)
        return value


def test_add_assigns_distinct_keys_when_the_counter_read_is_interleaved() -> None:
    """連番の read-modify-write と表の更新は**不可分**でなければならない (spec §5.7-2)。

    ロック外だと、A が counter を読んだ直後に B が同じ古い値を読み、**同じキーが
    2 グループへ割り当たる** — ``self._groups[key] = group`` は後勝ちなので片方の
    グループは辿れなくなり、その handle は ``remove -> close`` へ到達できない
    (= ファイルが開いたまま残る)。

    修正後は A が lock を保持したまま有界待ちに入り、B は lock で待たされるので
    ``time.sleep`` の間に走り抜けられない = 連番が正しく 2 つに割れる。
    """
    gate, resumed = threading.Event(), threading.Event()
    mgr = SignalGroupManager()
    mgr._counters = _InterleavedCounters(gate, resumed)
    keys: list[str] = []
    lock = threading.Lock()

    def add(tag: str) -> None:
        key = mgr.add(_group(tag))
        with lock:
            keys.append(key)

    ta = threading.Thread(target=add, args=("a",))
    ta.start()
    assert gate.wait(5.0), "A が counter を読む前に止まった (setup 失敗)"
    tb = threading.Thread(target=add, args=("b",))
    tb.start()
    time.sleep(0.05)  # lock が無ければ B はここでキー確定まで走り抜ける
    resumed.set()
    ta.join(timeout=_BOUND_S)
    tb.join(timeout=_BOUND_S)

    assert not ta.is_alive() and not tb.is_alive(), (
        "引き渡しがハングした — 有界待ちが効いていない"
    )
    assert sorted(keys) == ["csv_1", "csv_2"], (
        f"同じキーが 2 グループへ割り当たった: {keys}"
    )
    assert sorted(mgr.keys) == ["csv_1", "csv_2"], (
        "後勝ちでグループが 1 つ消えた (その handle は close へ到達できない)"
    )


def test_concurrent_add_keeps_every_counter_and_key() -> None:
    """4 スレッド同時 add で キー欠落ゼロ・連番の重複ゼロ (spec §5.7-2)。

    **これ単体では検出器にならない** (ロック無しの実装で 5/5 緑を実測)。窓を実際に
    踏ませるのは上の ``test_add_assigns_distinct_keys_when_the_counter_read_is_
    interleaved``。ここは「lock を入れたことで現実的な多重ロードが壊れていない」
    ことの粗い網として残す。

    今日 add() はロック外で counters を read-modify-write しており、2 ファイル
    同時ドロップで **同じキーが 2 グループに割り当たる** (後勝ちで 1 つ消える)。

    **supersede 記録 (spec §7.3「全 handle が close 到達」)**: ここは handle を
    持たない合成グループで駆動するので close 到達数は数えない。spec の要求は
    「キー欠落ゼロ → 到達可能」という等価性で満たす — `remove(key)` は
    `self._groups[key]` からグループを取り出して返す唯一の経路なので、キーが
    1 つも失われていなければ **すべての handle は remove -> close へ到達できる**。
    逆に旧実装のキー衝突では、後勝ちで消えたグループが `_groups` から辿れず
    handle が close 不能になる（それがこの assert が守っている実害そのもの）。
    実 handle 込みの close 到達は Task 11 の G4/G5 走行で実測する。
    """
    mgr = SignalGroupManager()
    keys: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def add_many(tag: str) -> None:
        barrier.wait(timeout=5.0)
        local = [mgr.add(_group(f"{tag}{i}")) for i in range(50)]
        with lock:
            keys.extend(local)

    threads = [threading.Thread(target=add_many, args=(f"t{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert len(keys) == 200
    assert len(set(keys)) == 200, "同じキーが 2 グループへ割り当たった"
    assert sorted(mgr.keys) == sorted(keys), "登録済みグループとキーが食い違う"


def test_resolve_right_after_add_sees_the_new_group() -> None:
    """add 直後の resolve が新グループを引ける (機能の粗い網)。

    **これは書き順 (I7b) の検出器ではない — 実測**: ``add()`` の中で
    ``_invalidate_namespaced()`` と ``self._groups[key] = group`` を入れ替える変異
    (S3) を入れても 11/11 緑のままだった。両方が **同じクリティカルセクション**に
    入った今、その順序は他スレッドから観測しようがないからである (再構築は
    ``_resolved_lock`` を取ってから gen と snapshot を**対で**読む)。
    書き順そのものを形として固定するのは下の
    ``test_add_writes_the_group_then_invalidates_inside_one_critical_section``。
    """
    mgr = SignalGroupManager()
    mgr.signal_map()  # 先にキャッシュを立てておく (invalidate の効果を可視化)
    key = mgr.add(_group("fresh"))
    assert mgr.signal_map().get(f"{key}::fresh_0") is not None


class _LockObservingGroups(dict):  # type: ignore[type-arg]
    """``_groups`` への書きの瞬間に ``_resolved_lock`` が握られていたかを記録する。

    ``threading.Lock.locked()`` は「誰かが保持中」しか答えないので、**単一スレッド**
    で使うこと (他に握る者が居なければ True = 自分が保持中と読める)。
    """

    def __init__(self, lock: threading.Lock, observed: list[tuple[str, bool]]) -> None:
        super().__init__()
        self._lock = lock
        self._observed = observed

    def __setitem__(self, key, value) -> None:  # type: ignore[no-untyped-def]
        self._observed.append(("groups", self._lock.locked()))
        super().__setitem__(key, value)


def test_add_writes_the_group_then_invalidates_inside_one_critical_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """書き順 (I7b) と不可分性を **コードの形** として固定する。

    今日この順序は他スレッドから観測できない (上のテストの docstring 参照) ので、
    振る舞いから導けるのは「両方が同じクリティカルセクションに居る」ことだけ。
    それでも順序を pin するのは、将来 lock を細かく割ったときに I7b の窓
    (invalidate 後・``_groups`` 書き前に走った再構築が新グループを欠いた map を
    焼き付け、次の invalidate までそのファイルが引けない) が**黙って**戻るのを
    防ぐため — 割った瞬間にここが RED になる。
    """
    mgr = SignalGroupManager()
    observed: list[tuple[str, bool]] = []
    mgr._groups = _LockObservingGroups(mgr._resolved_lock, observed)
    original = SignalGroupManager._invalidate_namespaced

    def probe(self: SignalGroupManager) -> None:
        observed.append(("invalidate", self._resolved_lock.locked()))
        original(self)

    monkeypatch.setattr(SignalGroupManager, "_invalidate_namespaced", probe)

    mgr.add(_group("a"))

    assert observed == [("groups", True), ("invalidate", True)], (
        "add() の書き順/不可分性が崩れた "
        f"(期待: _groups -> invalidate を lock 下で・実測: {observed})"
    )


def test_namespace_build_survives_a_concurrent_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """反復中の add で dict-changed-size を出さない (spec §5.7-3)。

    構築を人工的に遅らせて窓を確実に踏む (遅らせないと GIL の引き渡し粒度で
    ほぼ落ちない = sabotage しても緑になる)。
    """
    mgr = SignalGroupManager()
    for i in range(200):
        mgr.add(_group(f"pre{i}"))

    original = SignalGroupManager._namespaced
    started = threading.Event()

    def slow(key: str, group: SignalGroup) -> list[Signal]:
        started.set()
        time.sleep(0.001)
        return original(key, group)

    monkeypatch.setattr(SignalGroupManager, "_namespaced", staticmethod(slow))
    errors: list[BaseException] = []

    def build() -> None:
        try:
            mgr.signals()
        except BaseException as exc:
            errors.append(exc)

    t = threading.Thread(target=build)
    t.start()
    assert started.wait(timeout=5.0), "構築スレッドが _namespaced へ到達していない"
    late_key = mgr.add(_group("late"))
    t.join(timeout=60.0)
    # patch を戻す前にスレッドの終了を確かめる (生きたまま復元すると、後続の
    # テストが patch 済み/未済みの混ざった実装を踏む)。
    assert not t.is_alive(), "構築スレッドが終わらない (デッドロック/無限リトライ)"

    assert errors == [], f"反復中の add で例外: {errors!r}"
    # lost-update の閉鎖: 構築が古いスナップショットを焼き付けていない。
    assert mgr.signal_map().get(f"{late_key}::late_0") is not None


def test_group_signals_cache_is_not_resurrected_after_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """per-key キャッシュの世代ガード (同じ lost-update が group_signals にもある)。

    **競合形でなければ空虚**: 単一スレッドの「add -> remove -> group_signals」は
    新実装の `self._groups[key]` が無条件 KeyError を投げるので、世代照合と
    `key in self._groups` の再確認 (`if self._namespaced_gen == gen and
    key in self._groups:`) を**丸ごと削除しても緑**になる。守るべきなのは
    「ビルド中に remove が入った」窓なので、`test_namespace_build_survives_a_
    concurrent_add` と同じ slow-`_namespaced` フックで競合を作る。
    """
    mgr = SignalGroupManager()
    key = mgr.add(_group("g"))

    original = SignalGroupManager._namespaced
    started = threading.Event()
    proceed = threading.Event()

    def slow(k: str, group: SignalGroup) -> list[Signal]:
        started.set()
        proceed.wait(5.0)  # ビルド中に remove を差し込む窓
        return original(k, group)

    monkeypatch.setattr(SignalGroupManager, "_namespaced", staticmethod(slow))
    result: list[object] = []

    def build() -> None:
        try:
            result.append(mgr.group_signals(key))
        except KeyError:
            result.append(KeyError)

    t = threading.Thread(target=build)
    t.start()
    assert started.wait(timeout=5.0), "構築スレッドが _namespaced へ到達していない"
    mgr.remove(key)  # ビルド中に消える
    proceed.set()
    t.join(timeout=30.0)
    assert not t.is_alive(), "構築スレッドが終わらない"

    # ビルド自身は完走してよい (スナップショットに対して作っている)。禁じるのは
    # **消えたキーのキャッシュを書き戻すこと** — 書き戻すと「閉じたのに信号が
    # 引ける」状態が次の invalidate まで残る。
    assert key not in mgr._namespaced_by_key, (
        "remove 済みキーの namespaced キャッシュが復活した (世代照合が効いていない)"
    )
    with pytest.raises(KeyError):
        mgr.group_signals(key)
