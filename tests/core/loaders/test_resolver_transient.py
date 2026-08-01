"""export 専用 resolve が帳簿・pin・LRU を汚さないこと (E-4b Task 6・MG-1)。

全列エクスポートは 330,004 列を解決する。それを ``resolve()`` (帳簿つき) で
やると: 容量 512 の LRU に載って定常が 512 本 ≫ G2 上限になり、かつ選択列が
512 未満の範囲エクスポートでは **1 本も evict されず現状の 114.5 MiB 残留が
そのまま残る** (spec §5.3)。したがって「LRU に任せる」は機構レスであり、
専用経路が要る。

既存の D4 identity 契約 (tests/core/loaders/test_resolver.py) は**無編集で緑**の
ままでなければならない — transient resolve はその契約に触れない。
"""

from __future__ import annotations

import datetime
import weakref
from pathlib import Path

import numpy as np

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup


def _sig(name: str) -> Signal:
    return Signal(
        name=name,
        timestamps=np.arange(3, dtype=np.float64),
        values=np.zeros(3),
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )


def _group(*names: str) -> SignalGroup:
    return SignalGroup(
        signals=tuple(_sig(n) for n in names),
        source_path=Path("/x.mf4").resolve(),
        file_format="MDF4",
        loaded_at=datetime.datetime.now(),
    )


def _add_real(mgr: SignalGroupManager, tmp_path: Path) -> str:
    result = MdfLoader().load(write_mdf4_2d(tmp_path))
    sg = result.signal_group
    assert sg is not None
    return mgr.add(sg, column_records=result.column_records)


def _close(mgr: SignalGroupManager, key: str) -> None:
    group, _columns = mgr.remove(key)
    if group.handle is not None:
        group.handle.close()


def test_signal_supports_weakref() -> None:
    """G2/G5 の独立オラクルの前提条件 (__slots__ に __weakref__ が要る)。

    無いと ``weakref.ref(sig)`` が TypeError になり、帳簿以外の観測手段が
    1 つも無くなる (resolved_keys は transient に盲目・bytes_held は pin 前提)。

    M5 (レビュー): 旧 ``ref() is not None or ref() is None`` は真理値表そのものが
    恒真 (対象が存在しても TypeError で ``weakref.ref`` が例外を投げても、この式
    自体は評価に到達すれば必ず True になる) — ``__weakref__`` を消しても
    RED にならない空虚な assert だった。生成できることに加え、生きている間は
    ``()`` が対象そのものを返すことを直接 pin する。
    """
    sig = _sig("x")
    # 生成できる (weakref.ref(sig) が TypeError にならない) ことと、生存中は
    # ref() が対象そのものを返すことの両方をここで pin する。
    assert weakref.ref(sig)() is sig


def test_transient_resolve_mints_without_touching_the_ledger(tmp_path: Path) -> None:
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        col_key = f"{key}::Mat[2]"
        got = mgr.resolve_transient(col_key)
        assert got is not None
        assert got.name == col_key
        # 帳簿は 1 バイトも動かない
        assert mgr.resolved_keys(key) == frozenset()
        assert mgr.resolved_lru_keys() == ()
        assert mgr.mint_count == 0
        assert mgr.transient_mint_count == 1
    finally:
        _close(mgr, key)


def test_transient_resolve_values_match_the_ledger_resolve(tmp_path: Path) -> None:
    """「帳簿に載せない」は「別物を返す」ではない (誤データの排除)。"""
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        col_key = f"{key}::Mat[1]"
        transient = mgr.resolve_transient(col_key)
        ledger = mgr.resolve(col_key)
        assert transient is not None and ledger is not None
        assert np.array_equal(np.asarray(transient.values), np.asarray(ledger.values))
        assert transient.timestamps is ledger.timestamps  # master は同一オブジェクト
    finally:
        _close(mgr, key)


def test_transient_resolve_reuses_an_already_resolved_column(tmp_path: Path) -> None:
    """既に帳簿に在る列は**作り直さない** (二重実体化を避ける)。

    ただし recency は動かさない — 動かすと全列エクスポートが LRU の順序表を
    総なめし、GUI が次に読む列の追い出し順序が壊れる。
    """
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        col_key = f"{key}::Mat[1]"
        other = f"{key}::Mat[2]"
        first = mgr.resolve(col_key)
        mgr.resolve(other)  # MRU は other
        order_before = mgr.resolved_lru_keys()

        again = mgr.resolve_transient(col_key)

        assert again is first
        assert mgr.transient_mint_count == 0  # 鋳造していない
        assert mgr.resolved_lru_keys() == order_before  # recency も動かさない
    finally:
        _close(mgr, key)


def test_transient_resolve_returns_existing_physical_signal(tmp_path: Path) -> None:
    """物理チャンネルキーは既存 map をそのまま返す (鋳造経路に入らない)。"""
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        got = mgr.resolve_transient(f"{key}::Clean")
        assert got is not None
        assert mgr.transient_mint_count == 0
    finally:
        _close(mgr, key)


def test_transient_resolve_returns_none_for_unloaded_group() -> None:
    mgr = SignalGroupManager()
    assert mgr.resolve_transient("mf4_9::Nope") is None


def test_transient_resolve_returns_none_for_unresolvable_column() -> None:
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))  # 表もハンドルも無い合成グループ
    assert mgr.resolve_transient(f"{key}::Mat[7]") is None
    assert mgr.transient_mint_count == 0


def test_transient_resolve_never_evicts_pinned_or_unpinned_columns(
    tmp_path: Path,
) -> None:
    """**MG-1 の核心**: 容量 1 の LRU へ transient を 100 回流しても帳簿が動かない。

    ``resolve()`` でやると 1 回目で pin 外が落ち、以後 evict が回り続ける。
    """
    mgr = SignalGroupManager(resolved_capacity=1)
    key = _add_real(mgr, tmp_path)
    try:
        pinned_key = f"{key}::Mat[0]"
        assert mgr.resolve(pinned_key) is not None
        mgr.set_pinned_columns({pinned_key})
        evictions_before = mgr.resolved_evictions

        for _ in range(100):
            for col in ("Mat[1]", "Mat[2]"):
                assert mgr.resolve_transient(f"{key}::{col}") is not None

        assert mgr.resolved_evictions == evictions_before
        assert mgr.resolved_keys(key) == frozenset({pinned_key})
        assert mgr.resolved_lru_keys() == (pinned_key,)
        assert mgr.transient_mint_count == 200
    finally:
        _close(mgr, key)


def test_transient_columns_die_when_dropped(tmp_path: Path) -> None:
    """G5 の土台: 参照を落とせば**その場で**消える (帳簿が掴んでいない証明)。"""
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        col = mgr.resolve_transient(f"{key}::Mat[2]")
        assert col is not None
        ref = weakref.ref(col)
        assert ref() is not None  # 反 vacuous: 生きている状態を先に観測する
        del col
        assert ref() is None, "帳簿かキャッシュが transient 列を掴んでいる"
    finally:
        _close(mgr, key)


def test_session_delegates_resolve_signal_transient(tmp_path: Path) -> None:
    from valisync.core.session import Session

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    got = session.resolve_signal_transient(f"{key}::Mat[1]")
    assert got is not None
    assert session._groups.resolved_keys(key) == frozenset()


def test_channel_key_of_maps_every_column_of_a_channel_to_one_key(
    tmp_path: Path,
) -> None:
    """列 -> チャンネルの解決器 (**鋳造しない**)。幅 k の列は全部 1 チャンネルへ。

    見積 (T-UX) の読み項がチャンネル単位で数えられる根拠そのもの。ここが列ごとに
    別キーを返すと、幅 1,100 のチャンネルで読み時間が 1,100 倍に見える。
    """
    from valisync.core.session import Session

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    before = session._groups.transient_mint_count

    channels = {session.channel_key_of(f"{key}::Mat[{i}]") for i in range(3)}

    assert channels == {f"{key}::Mat"}
    assert session.channel_key_of(f"{key}::Clean") == f"{key}::Clean"
    assert session.channel_key_of(f"{key}::NoSuch") is None
    assert session.channel_key_of("bare_key_without_separator") is None
    assert session._groups.transient_mint_count == before, "解決器が列を鋳造した"


def test_channel_key_of_agrees_with_scan_masters_channel_runs(tmp_path: Path) -> None:
    """**2 つの真実を作らない**ことの pin (C-1)。

    ``scan_masters`` は ``(id(master), metadata["physical_channel"])`` の変化点で
    区切りを採り、見積は ``channel_key_of`` で数える。両者が同じチャンネルへ
    落ちなければ、見積の読み項とブロック割当が別のものを数えていることになる。
    """
    from valisync.core.export.csv_exporter import scan_masters
    from valisync.core.session import Session

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    keys = [f"{key}::Mat[{i}]" for i in range(3)] + [f"{key}::Clean"]

    scan = scan_masters([(k, None) for k in keys], session.resolve_signal_transient)

    # scan の runs が示す区切りを、channel_key_of の答えから独立に再構成する。
    resolved = [session.channel_key_of(k) for k in keys]
    runs: list[int] = []
    for channel in resolved:
        if runs and channel == resolved[sum(runs) - 1]:
            runs[-1] += 1
        else:
            runs.append(1)
    assert tuple(runs) == scan.runs, (runs, scan.runs, resolved)
