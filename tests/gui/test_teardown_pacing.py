"""ドレインは 1 ティックで予算を超えない (増分B・FU-16 の再来防止)。

バイト会計を正直にすると未展開の遅延グループは実質 0 バイトになり、330,004
シェルが 1 ティックで解放されて実測 649ms のフリーズになる。信号数の上限は
オプションではなく必須。**時間ではなく信号数で assert する** (マシン依存回避) —
デッドライン軸だけは注入した偽クロックで assert する (実時間は使わない)。
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from valisync.core.models import Signal, SignalGroup
from valisync.core.models.sample_source import EagerValues
from valisync.gui.workers.teardown_service import (
    _CLOCK_CHECK_EVERY,
    _TICK_DEADLINE_S,
    TeardownService,
)


class _ZeroByteSource:
    """未展開の遅延ソース相当: 会計上 0 バイト."""

    is_materialized = False
    nbytes_if_materialized = 0

    def __init__(self, n: int) -> None:
        self.length = n

    def array(self) -> np.ndarray:  # pragma: no cover - 呼ばれてはいけない
        raise AssertionError("teardown must not materialize")

    def array_if_materialized(self) -> np.ndarray | None:
        # Task 5 で SampleSource に追加されるメンバ (会計の id-dedup 用)。
        # 会計は getattr フォールバックを使わず直接呼ぶので、ここに無いと
        # AttributeError で loud-fail する。
        return None


def _group_of(sigs: tuple[Signal, ...]) -> SignalGroup:
    return SignalGroup(
        signals=sigs,
        source_path=Path("/x.mf4").resolve(),
        file_format="MDF4",
        loaded_at=datetime.datetime.now(),
    )


def _lazy_group(n_signals: int, *, freeze_master: bool = True) -> SignalGroup:
    ts = np.arange(4, dtype=np.float64)
    if freeze_master:
        # 本番は Signal 構築前に master を凍結する (mdf_loader.py:487)。凍結しないと
        # Signal.__init__ (signal.py:77) が writeable な配列を信号ごとに copy するため
        # グループは master を共有せず、Task 5 の dedup テストが原理的に通らない。
        ts.flags.writeable = False
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,
            values_source=_ZeroByteSource(4),  # type: ignore[arg-type]
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i in range(n_signals)
    )
    return _group_of(sigs)


def _eager_group(n_signals: int, length: int) -> SignalGroup:
    """展開済み値を持つグループ (1 信号あたりの解放コストが約 3 倍の regime)。"""
    ts = np.arange(length, dtype=np.float64)
    ts.flags.writeable = False
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,
            values_source=EagerValues(np.arange(length, dtype=np.float64)),
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i in range(n_signals)
    )
    return _group_of(sigs)


def test_one_tick_never_frees_more_than_the_signal_budget(qtbot) -> None:  # type: ignore[no-untyped-def]
    # now を固定してデッドライン軸を無効化し、信号数軸だけを測る
    svc = TeardownService(signal_budget=100, now=lambda: 0.0)
    svc.enqueue("k", _lazy_group(1000))
    before = svc.pending_signals()
    svc._drain()  # 1 ティックぶんだけ回す
    freed = before - svc.pending_signals()
    assert freed == 100, f"1 ティックで {freed} 信号を解放した (上限 100)"


def test_drain_completes_across_ticks(qtbot) -> None:  # type: ignore[no-untyped-def]
    finished: list[str] = []
    svc = TeardownService(on_finished=finished.append, signal_budget=100)
    svc.enqueue("k", _lazy_group(1000))
    qtbot.waitUntil(lambda: finished == ["k"], timeout=5000)
    assert svc.pending_signals() == 0


def test_default_signal_budget_is_8000(qtbot) -> None:  # type: ignore[no-untyped-def]
    """count 軸の既定値 (ユーザー決定 3・ハード上限)。

    now を固定するのは必須 — 既定のまま実クロックで走らせるとデッドライン軸
    (8ms) が先に効いて 8,000 に届かず、count 軸を測れない。
    """
    svc = TeardownService(now=lambda: 0.0)
    svc.enqueue("k", _lazy_group(20000))
    before = svc.pending_signals()
    svc._drain()
    assert before - svc.pending_signals() == 8000


def test_tick_stops_at_the_deadline_with_a_fake_clock(qtbot) -> None:  # type: ignore[no-untyped-def]
    """デッドライン軸は偽クロックで assert する (実時間で assert しない)。

    spec の「時間で assert しない」制約はテストのオラクルについての制約であり、
    production 機構を時間軸にすることは禁じていない。
    """
    ticks = iter(range(10_000))
    svc = TeardownService(
        byte_budget=1 << 62,  # バイト軸を実質無効化
        signal_budget=10_000,  # 信号軸も 1 ティックで足りる大きさ
        # tick_deadline_s は**渡さない** — 既定 (_TICK_DEADLINE_S) を使わせることで
        # 既定値そのものをロックする。明示で渡すと既定を 1.0 に書き換えても緑のままで、
        # production は 8,000 信号ティック (実測 24-38ms) に静かに戻る。
        now=lambda: next(ticks) * 0.001,  # 呼ばれるたび +1ms
    )
    svc.enqueue("k", _lazy_group(10_000))
    before = svc.pending_signals()
    svc._drain()
    freed = before - svc.pending_signals()
    # 偽クロックは完全決定的 (t0 で 1 回 + _CLOCK_CHECK_EVERY 信号ごとに 1 回) なので
    # 停止点は機械的に確定する: 8 回目の読み = 8ms = 既定デッドライン ⇒ 32*8 = 256 信号。
    # 「何らかの停止がある」ではなく既定デッドラインと粒度の両方を pin する
    # (粒度が 256 のままだと 2,048 が出て RED — 実測 8-27us/本 の展開済み prod
    # リーフでは 255 本の行き過ぎが 4-7ms になり最大ティックが 16.8ms へ膨らむ)。
    assert freed == 256, f"既定 8ms を 32 信号粒度で見た停止点のはず (freed={freed})"
    # 上の pin は**積** (粒度 x デッドライン) しか縛らない — 粒度 64 かつ
    # デッドライン 0.004 のような相殺変更でも 256 が出る。2 定数を独立に縛る。
    assert _TICK_DEADLINE_S == 0.008
    assert _CLOCK_CHECK_EVERY == 32


def test_shared_master_is_counted_once_per_group(qtbot) -> None:  # type: ignore[no-untyped-def]
    """master はグループ内で identity 共有。信号ごとに数えると 5 万倍過大になる。"""
    svc = TeardownService()
    group = _lazy_group(100)
    assert len({id(s.timestamps) for s in group.signals}) == 1, (
        "fixture premise broken: master が凍結されておらず共有されていない"
    )
    m = group.signals[0].timestamps.nbytes
    svc.enqueue("k", group)
    assert svc.pending_bytes() == m  # 0 も 100*m も不合格


def test_distinct_masters_are_each_counted(qtbot) -> None:  # type: ignore[no-untyped-def]
    """CSV 形状 (writeable master => 信号ごとにコピー) では dedup が効かないこと。

    csv_loader は master を凍結せず writeable な配列を全 Signal に渡す
    (csv_loader.py:234/281) ので、Signal.__init__ が信号ごとにコピーする。
    CSV の会計は今日すでに正直 — 「CSV も dedup されていない」と後から
    直してはならない。
    """
    svc = TeardownService()
    group = _lazy_group(10, freeze_master=False)
    assert len({id(s.timestamps) for s in group.signals}) == 10, "前提が壊れている"
    m = group.signals[0].timestamps.nbytes
    svc.enqueue("k", group)
    assert svc.pending_bytes() == 10 * m


def test_materialized_value_is_added_to_the_master(qtbot) -> None:  # type: ignore[no-untyped-def]
    """共有 master + 展開済み値 1 本の合算を pin (timestamps 項の脱落を落とす)。"""
    ts = np.arange(1024, dtype=np.float64)
    ts.flags.writeable = False
    src = EagerValues(np.zeros(1024, dtype=np.float64))
    sig = Signal(
        name="s",
        timestamps=ts,
        values_source=src,
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )
    svc = TeardownService()
    svc.enqueue("k", _group_of((sig,)))
    assert svc.pending_bytes() == ts.nbytes + src.nbytes_if_materialized


def test_shared_value_array_is_counted_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    """同一 EagerValues を共有する 2 信号の値配列は 1 回だけ計上される。

    array_if_materialized() を getattr フォールバックで書くと実ソースで dedup が
    無言で消えるが、master dedup テストは sig.timestamps しか見ないので検知できない。
    このテストがその穴を塞ぐ。
    """
    src = EagerValues(np.zeros(4096, dtype=np.float64))
    ts = np.arange(4096, dtype=np.float64)
    ts.flags.writeable = False
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,
            values_source=src,
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i in range(2)
    )
    svc = TeardownService()
    svc.enqueue("k", _group_of(sigs))
    assert svc.pending_bytes() == ts.nbytes + src.nbytes_if_materialized


def test_master_is_charged_every_tick_not_once_per_service(qtbot) -> None:  # type: ignore[no-untyped-def]
    """`seen` はティック単位 — サービス寿命にすると 2 ティック目が 0 バイトになる。

    id は生存中のオブジェクト間でのみ一意なので、記録した配列より長生きする set は
    以後の全確保をエイリアスする (実測 100% 再利用・memory
    gui_id_reuse_flake_object_recreation)。この assert は id 再利用に依存せず
    決定的に RED になる。
    """
    svc = TeardownService(signal_budget=10, byte_budget=1 << 62, now=lambda: 0.0)
    group = _lazy_group(35)  # 4 ティック必要
    m = group.signals[0].timestamps.nbytes
    svc.enqueue("k", group)
    charged: list[int] = []
    while svc.pending_signals() > 0:
        svc._drain()
        charged.append(svc.last_tick_bytes)
    assert len(charged) >= 3
    assert all(b >= m for b in charged), (
        f"{charged} — master を計上しないティックがある"
    )


def test_a_later_group_is_charged_in_full(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A を完走ドレイン後に確保した B が 0 バイト計上にならない (id 再利用ガード)。"""
    svc = TeardownService(signal_budget=10_000, byte_budget=1 << 62, now=lambda: 0.0)
    svc.enqueue("a", _lazy_group(200))
    svc._drain()
    assert svc.pending_signals() == 0
    group_b = _lazy_group(5)
    expected = group_b.signals[0].timestamps.nbytes  # 共有 master 1 本ぶん
    svc.enqueue("b", group_b)
    svc._drain()
    assert svc.last_tick_bytes == expected


def test_one_tick_stops_over_materialized_signals_too(qtbot) -> None:  # type: ignore[no-untyped-def]
    """展開済み値 + sorted/finite/range_stat_index を持つ信号でも上限で止まる。

    シェルだけを流す他のテストは 1.6us regime しか通らない (実測: 展開済みは
    3.0us、+range_stat_index で 3.9-4.8us — 同じ予算でティックは 24-38ms になる)。
    """
    svc = TeardownService(signal_budget=100, byte_budget=1 << 62, now=lambda: 0.0)
    group = _eager_group(300, length=64)
    for sig in group.signals:
        sig.sorted_view()
        sig.finite_view()
        sig.range_stat_index()
    svc.enqueue("k", group)
    before = svc.pending_signals()
    svc._drain()
    assert before - svc.pending_signals() == 100


def test_cached_channel_array_bytes_are_counted_by_the_byte_axis(qtbot) -> None:  # type: ignore[no-untyped-def]
    """生 ndarray (Signal の皮を持たない) が会計のバイト軸に載る。

    載らないと 13.2 MB のチャンネル配列が 0 バイト扱いになり、1 ティックに何本でも
    詰め込まれて 64 MiB 予算が黙って効かなくなる — 未展開シェルで一度踏んだ
    「バイト会計が正直でないと予算が死ぬ」regime そのもの (FU-16)。
    """
    svc = TeardownService()
    group = _lazy_group(1)
    m = group.signals[0].timestamps.nbytes
    arr = np.zeros((1024, 16), dtype=np.uint8)

    svc.enqueue("k", group, cached_arrays=(arr,))

    assert svc.pending_bytes() == m + arr.nbytes  # m のみ (= 0 バイト扱い) は不合格


def test_a_cached_array_shared_with_a_signal_is_counted_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    """identity dedup は新しい ndarray 分岐にも効く (会計の保存すべき契約)。

    今日の production は C1 の所有権不変条件により列の値配列とキャッシュ配列が
    別オブジェクトなので、これは再現ではなく**契約ガード**である: 分岐が共通の
    ``seen`` を使わなくなる変異 (C1 の copy を外す / 非セレクタ経路をキャッシュ
    配列の素通しにする) を入れた瞬間に二重計上が始まり、ティックが予算へ早く
    到達してペーシングの実効粒度が黙って粗くなる。
    """
    arr = np.zeros(4096, dtype=np.uint8)
    # _freeze は read-only 入力を素通しする (sample_source.py) ので、凍結してから
    # 渡さないと EagerValues がコピーを持ち、同一オブジェクトの共有を作れない。
    arr.flags.writeable = False
    src = EagerValues(arr)
    assert src.array_if_materialized() is arr, "fixture 前提: 値配列が共有されていない"
    ts = np.arange(4096, dtype=np.float64)
    ts.flags.writeable = False
    sig = Signal(
        name="s",
        timestamps=ts,
        values_source=src,
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )
    svc = TeardownService()

    svc.enqueue("k", _group_of((sig,)), cached_arrays=(arr,))

    assert svc.pending_bytes() == ts.nbytes + arr.nbytes  # 2*arr.nbytes は不合格


def test_derived_view_arrays_are_counted_by_the_byte_axis(qtbot) -> None:  # type: ignore[no-untyped-def]
    """sorted_view/finite_view が抱える**別の**配列も会計に載る。

    値 dtype を uint8 にするのが要点。float64 値 + 単調 master という既存 fixture
    (`_eager_group`) の形では ``sorted_view()`` が ``astype(copy=False)`` で
    **同一オブジェクト**を返し ``finite_view()`` も zero-copy なので、派生ビューの
    寄与が構造的に 0 バイトになる — その形で書いた assert は「派生ビューを 1 本も
    数えない実装」でも緑のまま通る (実測: 共有ヘルパから派生ビュー計上を削っても
    test_teardown_pacing.py は 11/11 緑・全スイートも緑だった)。
    非 float64 のチャンネル値は prod の広幅 uint8 そのもので、そこでは派生ビューが
    値配列の 8 倍を追加で抱える = 会計が落とすと最も痛い regime である。
    """
    vs = np.zeros(4096, dtype=np.uint8)
    vs.flags.writeable = False
    ts = np.arange(4096, dtype=np.float64)
    ts.flags.writeable = False
    sig = Signal(
        name="s",
        timestamps=ts,
        values_source=EagerValues(vs),
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )
    view_ts, view_vs = sig.finite_view()  # sorted_view 経由で float64 の別配列が生える
    assert view_ts is ts and view_vs is not vs, "fixture 前提: 派生ビューが別配列でない"
    svc = TeardownService()

    svc.enqueue("k", _group_of((sig,)))

    # ts (32 KB) + 値 uint8 (4 KB) + float64 へ upcast した派生ビュー (32 KB)。
    assert svc.pending_bytes() == ts.nbytes + vs.nbytes + view_vs.nbytes
