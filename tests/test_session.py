"""Unit tests for Session orchestration (Task 8.2, Requirements 4.4, 4.5, 5.4, 8.1, 8.3)."""

from __future__ import annotations

import gc
import weakref
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.interpolation import InterpolationMethod
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.models import Delimiter, FormatDefinition, Signal, SignalGroup
from valisync.core.session import (
    LoadCancelled,
    LoadError,
    LoadOutcome,
    Session,
    SourceInfo,
)


def _derived(name: str, ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )


def _group_of(signals: list[Signal], source_path: Path) -> SignalGroup:
    return SignalGroup(
        signals=tuple(signals),
        source_path=source_path,
        file_format="CSV",
        loaded_at=datetime.now(),
    )


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


_FMT = FormatDefinition(
    name="t1",
    delimiter=Delimiter.COMMA,
    timestamp_column=0,
    timestamp_unit="sec",
    signal_start_column=1,
    signal_end_column=1,
    has_header=True,
)


def test_load_csv_returns_key_and_exposes_namespaced_signals(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])

    session = Session()
    key = session.load(csv, format_def=_FMT).key

    assert key == "csv_1"
    signals = session.signals()
    assert len(signals) == 1
    assert signals[0].name == "csv_1::speed"
    np.testing.assert_array_equal(signals[0].values, np.array([10.0, 20.0]))


def test_load_csv_without_format_def_raises(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,v", ["0.0,1.0"])
    with pytest.raises(ValueError):
        Session().load(csv)


def test_source_name_returns_basename_for_key(tmp_path):
    """Public API for GUI to recover a file's display name from its group key."""
    csv = tmp_path / "drive.csv"
    _write_csv(csv, "t,speed", ["0.0,1.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key

    assert session.source_name(key) == "drive.csv"
    with pytest.raises(KeyError):
        session.source_name("nope_99")


def test_group_signals_returns_namespaced_signals_for_one_group(tmp_path):
    """Public API to fetch only one file's signals (avoids scanning all files)."""
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "t,speed", ["0.0,1.0"])
    _write_csv(b, "t,rpm", ["0.0,2.0"])
    session = Session()
    ka = session.load(a, format_def=_FMT).key
    kb = session.load(b, format_def=_FMT).key

    only_a = session.group_signals(ka)
    assert [s.name for s in only_a] == [f"{ka}::speed"]
    only_b = session.group_signals(kb)
    assert [s.name for s in only_b] == [f"{kb}::rpm"]
    with pytest.raises(KeyError):
        session.group_signals("nope_99")


def test_group_signals_caches_wrappers_until_invalidated(tmp_path):
    """FU-11: group_signals はキャッシュ済ラッパーを返し、呼び出し毎に 330k 個の
    Signal を再生成しない。オブジェクト同一性(連続呼び出しで同じ Signal)と、
    add() 無効化後の再構築で証明する。"""
    a = tmp_path / "a.csv"
    _write_csv(a, "t,speed", ["0.0,1.0"])
    session = Session()
    ka = session.load(a, format_def=_FMT).key

    first = session.group_signals(ka)
    second = session.group_signals(ka)
    # 防御コピー: リストオブジェクトは別物…
    assert first is not second
    # …だが中身の Signal ラッパーは同一(再構築されていない)。
    assert len(first) == len(second) == 1
    assert first[0] is second[0]

    # 別ファイルのロード(add)はキャッシュを無効化 → ラッパー再構築。
    b = tmp_path / "b.csv"
    _write_csv(b, "t,rpm", ["0.0,2.0"])
    session.load(b, format_def=_FMT)
    after = session.group_signals(ka)
    assert after[0] is not first[0]  # 無効化後は作り直される
    assert [s.name for s in after] == [f"{ka}::speed"]  # 内容は不変


def test_load_many_reports_partial_failure(tmp_path):
    good = tmp_path / "good.csv"
    _write_csv(good, "t,v", ["0.0,1.0", "1.0,2.0"])
    missing = tmp_path / "missing.csv"  # never created

    session = Session()
    result = session.load_many([(good, _FMT), (missing, _FMT)])

    assert len(result.succeeded) == 1  # the good file is usable (Req 5.4)
    assert result.succeeded[0].key == "csv_1"
    assert len(result.failed) == 1
    failed_path, messages = result.failed[0]
    assert failed_path == missing
    assert messages  # error reported per failed file
    assert len(session.signals()) == 1  # successful load available despite the failure


def test_remove_group_without_dependents_removes_immediately(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key

    outcome = session.remove_group(key)

    assert outcome.removed is True
    assert outcome.dependent_signals == ()
    assert session.signals() == []


def test_remove_group_with_dependent_derived_requires_confirmation(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    src = session.signals()[0]  # csv_1::speed
    derived = session.evaluate_formula("csv_1::speed * 2", {"csv_1::speed": src})

    # Req 4.5: a dependent Derived_Signal blocks removal until confirmed.
    blocked = session.remove_group(key)
    assert blocked.removed is False
    assert derived.name in blocked.dependent_signals
    assert session.signals()  # not removed

    forced = session.remove_group(key, force=True)
    assert forced.removed is True
    assert session.signals() == []


def test_remove_group_hands_off_group_and_defers_dealloc(tmp_path: Path) -> None:
    """remove_group returns the popped SignalGroup so the caller can defer its
    (potentially huge) dealloc off the calling thread. While the caller holds
    the returned group, core does NOT free it (FU-16)."""
    session = Session()
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    key = session.load(csv, format_def=_FMT).key
    result = session.remove_group(key)
    assert result.removed is True
    assert result.removed_group is not None
    ref = weakref.ref(result.removed_group)
    # Caller holds it -> alive (core did not synchronously dealloc it).
    assert ref() is not None
    # Dropping the only strong ref frees it (proves it was the caller's to free).
    del result
    gc.collect()
    assert ref() is None


def test_remove_group_refused_has_no_removed_group(tmp_path: Path) -> None:
    """When removal is refused (dependent Derived_Signal, not forced),
    removed_group is None."""
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    src = session.signals()[0]  # csv_1::speed
    session.evaluate_formula("csv_1::speed * 2", {"csv_1::speed": src})

    # Req 4.5: a dependent Derived_Signal blocks removal until confirmed.
    result = session.remove_group(key)
    assert result.removed is False
    assert result.removed_group is None
    assert result.removed_columns == ()


def test_resolve_signal_delegates_to_group_manager(tmp_path: Path) -> None:
    """Session は列キー解決の唯一の入口 (E-1)。既存キーは map から、未ロードは None。"""
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key

    got = session.resolve_signal(f"{key}::speed")
    assert got is not None
    assert got.name == f"{key}::speed"
    assert session.resolve_signal("csv_9::speed") is None  # 未ロードグループ


def test_remove_group_reports_minted_columns(tmp_path: Path) -> None:
    """鋳造済み列 Signal は SignalGroup.signals の外に居るため、削除時に
    RemovalResult 経由で呼び出し側 (GUI teardown) へ渡らないと会計から漏れる。"""
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    # E-1 ではローダーがまだ列を展開するため鋳造経路は走らない。副テーブルへ
    # 直接置いて、remove_group の受け渡し配線だけを検証する。
    column = _derived(f"{key}::speed[7]", [0.0], [1.0])
    session._groups._resolved_by_key.setdefault(key, {})[column.name] = column

    result = session.remove_group(key)

    assert result.removed is True
    assert result.removed_columns == (column,)


def _loaded_2d_with_a_cached_channel(tmp_path: Path) -> tuple[Session, str, MdfHandle]:
    """2-D チャンネルの列を 1 本読んで ChannelSampleCache を温めた Session を返す。

    列読みは物理チャンネルの 2-D 配列をデコードしてキャッシュへ載せる (E-4a)。
    温まっていない状態で会計を検証すると全 assert が「空タプル同士の比較」に化けて
    恒真になるので、前提そのものを assert しておく。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    col = session.resolve_signal(f"{key}::Mat[0]")
    assert col is not None
    np.testing.assert_array_equal(col.values, [0, 10, 20, 30])
    handle = session._groups.group(key).handle
    assert handle is not None
    # 「ハンドルが提げているキャッシュ」と「Session が裁定しているキャッシュ」が
    # **同一オブジェクト**であること。別物なら以下の会計は 2 つの帳簿を跨いで
    # 比較することになり、順序テストが偶然通る/偶然落ちるどちらにもなりうる。
    assert handle.cache is session.channel_cache, "ローダーへの注入が効いていない"
    assert handle.cache.bytes_held > 0, "前提が壊れている: 列読みがキャッシュを温めない"
    return session, key, handle


def _close_if_open(session: Session, key: str) -> None:
    """テスト後始末: グループが残っていれば閉じる (実 mf4 のハンドルを手放す)。

    前提 assert や順序 assert が close の**前**で落ちると、実 mf4 が開いたまま
    残って ``tmp_path`` の後片付けが Windows のファイルロックで失敗し、正直な
    assert 失敗が別のエラー (PermissionError) に埋もれる。remove_group 自体が
    テスト対象操作でもあるので、正常系ではここは no-op になる
    (``test_channel_cache_read_path.py`` が先に採った形と同型)。
    """
    if key in session.group_keys():
        session.remove_group(key)


def test_remove_group_recovers_the_cached_channel_arrays(tmp_path: Path) -> None:
    """デコード済みチャンネル配列は RemovalResult 経由で呼び出し側へ渡る (spec §5.7)。

    渡さないと 13.2 MB/本 (prod の広幅チャンネル) が teardown の三軸ペーシングを
    通らず、close() の中で GUI スレッドが同期解放する。``removed_columns`` に
    相乗りできないのは型が違うから (Signal ではなく生 ndarray)。
    """
    session, key, handle = _loaded_2d_with_a_cached_channel(tmp_path)
    try:
        result = session.remove_group(key)

        assert result.removed is True
        assert len(result.cached_arrays) == 1
        # 列 1 本 (長さ 4) ではなくチャンネル全体 (4 行 x 3 列) が渡る = キャッシュの実体。
        assert result.cached_arrays[0].shape == (4, 3)
        assert handle.cache is not None
        assert handle.cache.bytes_held == 0  # 予算からは外れている (回収 = 移譲)
    finally:
        _close_if_open(session, key)


def test_recovery_reads_the_cache_the_handle_actually_carries(tmp_path: Path) -> None:
    """回収先は**ハンドルが提げているキャッシュ**。Session 側で固定しない (M5)。

    Session 経由のロードでは両者は同一オブジェクトなので production の値は 1 ビットも
    変わらない。それでも固定してはならないのは、ずれた瞬間の degrade が**無症状**
    だから: drop が空振り → ``cached_arrays`` が空 → 実エントリは ``close()`` の中で
    GUI スレッドが同期解放する = 本タスクが防いだ退行そのものが、どの数字にも
    出ないまま戻る。
    """
    session, key, handle = _loaded_2d_with_a_cached_channel(tmp_path)
    try:
        other = ChannelSampleCache()
        arr = np.zeros((4, 3), dtype=np.uint8)
        # E-4b: キー第 1 成分は handle.serial (期待は不変・引き当て方だけ追随)。
        assert other.put((handle.serial, 999, 0), arr) is True
        handle.cache = other  # ハンドルだけが別帳簿を提げた状態

        result = session.remove_group(key)

        assert any(a is arr for a in result.cached_arrays), (
            "ハンドルが提げているキャッシュから回収していない (空振りしている)"
        )
        assert other.bytes_held == 0
    finally:
        _close_if_open(session, key)


def test_cached_arrays_are_recovered_before_the_handle_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回収は close() より**前**。順序が逆だと会計から丸ごと消える (spec §5.7)。

    close() は自ハンドルのエントリをキャッシュから落とす (= その場で解放する) ので、
    「close 時点で予算に残っていない」が順序の直接の観測点になる。cached_arrays の
    非空だけを見る形は、close 側の解放を将来やめたときに「順序は逆のまま偶然通る」
    テストへ劣化する。
    """
    session, key, _handle = _loaded_2d_with_a_cached_channel(tmp_path)
    try:
        held_at_close: list[int] = []
        real_close = MdfHandle.close

        def _spy(self: MdfHandle) -> None:
            assert self.cache is not None  # Session 経由のハンドルなので必ず配線済み
            held_at_close.append(self.cache.bytes_held)
            real_close(self)

        # MdfHandle は __slots__ なのでインスタンス属性を差し替えられない (クラス patch)。
        monkeypatch.setattr(MdfHandle, "close", _spy)

        result = session.remove_group(key)

        assert held_at_close == [0], (
            "close 時点でまだ予算に載っている = 回収が close の後"
        )
        assert len(result.cached_arrays) == 1  # 消えたのではなく移譲された
    finally:
        _close_if_open(session, key)


def test_close_releases_the_handles_cached_arrays_from_the_budget(
    tmp_path: Path,
) -> None:
    """回収されない close 経路 (ローダーのエラー/キャンセル) でも予算が返る。

    **supersede (E-4b)**: 旧理由は 2 つ (予算の目減り / id 再利用で別ファイルの
    配列を引く) だったが、キーが handle.serial になったので後者は構造的に消えた。
    残るのは **予算の恒久的な目減り** — 回収されない close 経路でエントリが滞留
    すると 256 MB 予算が黙って痩せる。期待 (bytes_held == 0) は変えない。
    """
    session, key, handle = _loaded_2d_with_a_cached_channel(tmp_path)
    try:
        assert handle.cache is not None and handle.cache.bytes_held > 0

        handle.close()

        assert handle.cache.bytes_held == 0
        assert session.signals()  # グループは残ったまま = close 単独の効果を見ている
    finally:
        _close_if_open(session, key)


def test_close_without_a_cache_is_still_a_plain_close(tmp_path: Path) -> None:
    """``cache is None`` のハンドルを閉じても落ちない (T2 が cache を任意にした帰結)。

    ``MdfLoader()`` を引数なしで使う経路 (ローダー単体テスト・エラー/キャンセル経路の
    finally・T3 の fixture) は ``cache=None`` のハンドルを作り、その全てが
    ``close()`` を呼ぶ。None ガードが無いと ``AttributeError: 'NoneType' object has
    no attribute 'release_handle'`` が**既存テストの広範囲**で出る — 本タスクの RED と
    区別できなくなるので、ここで正面から固定する。
    """
    handle = MdfLoader().load(write_mdf4_2d(tmp_path)).signal_group.handle
    try:
        assert handle is not None and handle.cache is None

        handle.close()  # 例外を出さないこと自体が assert

        assert handle.is_closed is True
    finally:
        # 前提 assert で落ちたときに実 mf4 が開いたまま残ると、tmp_path の後片付けが
        # Windows のファイルロックで失敗し正直な assert 失敗が埋もれる (M4)。
        # close は冪等なので正常系ではここは no-op。
        if handle is not None:
            handle.close()


# ─── Pure-computation pass-throughs ───────────────────────────────────────────


def test_downsample_delegates_to_core():
    ts = list(np.linspace(0.0, 99.0, 100))
    sig = _derived("x", ts, list(np.arange(100.0)))
    out = Session().downsample(sig, 10)
    assert isinstance(out, Signal)
    assert len(out.timestamps) <= 10


def test_interpolate_delegates_to_core():
    sig = _derived("x", [0.0, 1.0, 2.0], [0.0, 10.0, 20.0])
    assert Session().interpolate(sig, 0.5, InterpolationMethod.LINEAR) == 5.0


def test_compute_statistics_delegates_to_core():
    sig = _derived("x", [0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    stats = Session().compute_statistics(sig, 0.0, 2.0)
    assert stats.count == 3
    assert stats.mean == 2.0


def test_apply_offset_delegates_to_core():
    sig = _derived("x", [0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    out = Session().apply_offset(sig, file_offset=1.0)
    np.testing.assert_array_equal(out.timestamps, np.array([1.0, 2.0, 3.0]))


def test_export_csv_delegates_to_core(tmp_path):
    sig = _derived("speed", [0.0, 1.0], [10.0, 20.0])
    out = tmp_path / "e.csv"
    # E-4b Task 4 supersede: Derived は SignalGroupManager に登録されず keys で
    # 解決できないので escape hatch (extra_signals) 経由になる (spec §5.2 [I-3])。
    # 出力バイトの期待 ("timestamp,speed") は不変 (ヘッダは Signal 自身の名前)。
    Session().export_csv([], out, extra_signals=[sig])
    # supersede(E-4b §5.1-2): 出力に UTF-8 BOM が付いたため読み口のみ utf-8-sig 化 (期待値不変)
    assert out.read_text(encoding="utf-8-sig").splitlines()[0] == "timestamp,speed"


# ─── LoadOutcome / diagnostics (FB-02 foundation) ─────────────────────────────


def test_load_returns_outcome_with_key_and_diagnostics(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    outcome = session.load(csv, format_def=_FMT)
    assert isinstance(outcome, LoadOutcome)
    assert outcome.key == "csv_1"
    assert isinstance(outcome.diagnostics, tuple)


def test_load_error_carries_diagnostics(tmp_path):
    session = Session()
    bad = tmp_path / "nope.mf4"  # 存在しない → mdf4 ローダーが失敗
    bad.write_bytes(b"not an mdf")
    try:
        session.load(bad, None)
    except LoadError as exc:
        assert isinstance(exc.diagnostics, tuple)
    else:
        raise AssertionError("expected LoadError")


# ─── Cooperative cancel (FB-04 hard side) ─────────────────────────────────────


def test_load_cancel_raises_and_registers_nothing(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    with pytest.raises(LoadCancelled):
        session.load(csv, format_def=_FMT, cancel=lambda: True)
    assert session.signals() == []


def test_load_without_cancel_is_unchanged(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    outcome = session.load(csv, format_def=_FMT)
    assert outcome.key == "csv_1"


# ─── SourceInfo (FB-10 tooltip data) ─────────────────────────────────────────


def test_source_info_fields(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    info = session.source_info(key)
    assert isinstance(info, SourceInfo)
    assert info.full_path == csv.resolve()
    assert info.size_bytes == csv.stat().st_size
    assert info.n_channels >= 1
    assert info.file_format == "CSV"
    assert info.t_min is not None and info.t_max is not None
    assert info.t_min <= info.t_max


def test_source_info_size_none_when_file_gone(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    csv.unlink()
    info = session.source_info(key)
    assert info.size_bytes is None  # graceful degradation (spec §6)
    assert info.n_channels >= 1  # メモリ上の情報は生きている


def test_source_info_unknown_key_raises():
    with pytest.raises(KeyError):
        Session().source_info("nope_1")


def test_source_info_time_range_non_monotonic(tmp_path):
    # 非単調 CSV は Task 6 まで作れないため、group へ直接 Signal を積んで検証
    session = Session()
    messy = _derived("x", [5.0, 1.0, 3.0], [1.0, 2.0, 3.0])
    key = session._groups.add(_group_of([messy], tmp_path / "messy.csv"))
    info = session.source_info(key)
    assert info.t_min == 1.0 and info.t_max == 5.0


def test_source_info_does_not_pollute_sorted_view_cache(tmp_path):
    # source_info は範囲のみ必要 — sorted_view() を呼ぶと全信号の値を float64 へ
    # upcast + キャッシュし prod で +GB 膨張(FU-18)。sabotage(sorted_view()[0][0]
    # へ復帰)でこの assert が RED になる honest observable。
    master = np.arange(5.0, dtype=np.float64)
    master.flags.writeable = False  # __post_init__ は read-only 配列を共有保持
    sigs = [
        Signal(
            name=f"s{i}",
            timestamps=master,
            values=(np.arange(5, dtype=np.uint8) + i),
            file_format="Derived",
            bus_type="",
            source_file="",
            metadata={},
        )
        for i in range(4)
    ]
    session = Session()
    key = session._groups.add(_group_of(sigs, tmp_path / "shared.csv"))
    session.source_info(key)
    grp = session._groups.group(key)
    assert all(getattr(s, "_sorted_view_cache", None) is None for s in grp.signals)


def test_source_info_time_range_spans_multiple_masters(tmp_path):
    # 独立 master 2本 + 片方は非単調 → 全体の min/max を跨いで集計
    session = Session()
    a = _derived("a", [2.0, 5.0], [1.0, 2.0])
    b = _derived("b", [0.0, 3.0, 1.0], [3.0, 4.0, 5.0])
    key = session._groups.add(_group_of([a, b], tmp_path / "multi.csv"))
    info = session.source_info(key)
    assert info.t_min == 0.0 and info.t_max == 5.0


def test_source_info_ignores_empty_signals_but_counts_them(tmp_path):
    session = Session()
    empty = _derived("e", [], [])
    real = _derived("r", [1.0, 4.0], [10.0, 20.0])
    key = session._groups.add(_group_of([empty, real], tmp_path / "mix.csv"))
    info = session.source_info(key)
    assert info.t_min == 1.0 and info.t_max == 4.0
    assert info.n_channels == 2  # 空信号も channel 数には数える


def test_source_info_n_channels_counts_expanded_columns(tmp_path):
    """U2: 表示件数の単位は **列数**。反転後 group.signals は物理チャンネルのみ
    なので len(group.signals) では Mat の 3 列が 1 と数えられ、ChannelBrowser の
    「N ch 中 M ch を表示」と単位が食い違う (FileBrowser ツールチップも同様)。"""
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    info = session.source_info(key)
    assert info.n_channels == 4  # Mat[0..2] + Clean


def test_source_info_time_range_none_when_all_empty(tmp_path):
    session = Session()
    key = session._groups.add(_group_of([_derived("e", [], [])], tmp_path / "e.csv"))
    info = session.source_info(key)
    assert info.t_min is None and info.t_max is None


def test_namespaced_wrappers_share_sorted_view_cache(tmp_path):
    # signals() が返す namespaced ラッパーは FU-08 でキャッシュされ、無効化
    # (add/remove)までは呼び出しごとに同じオブジェクトを返す。無効化で作り直された
    # 「別オブジェクト」のラッパーでも、sorted_view の単調性スキャン結果は元の長寿命
    # Signal に委譲され共有される — これが render/カーソルのホットパスでラッパーが
    # 作り直されてもスキャンが1回で済む理由(委譲を外すと下の is 共有 assert が落ちる)。
    session = Session()
    messy = _derived("x", [0.0, 2.0, 1.0], [10.0, 30.0, 20.0])
    session._groups.add(_group_of([messy], tmp_path / "messy.csv"))

    sigs_a = session.signals()
    sigs_b = session.signals()
    # キャッシュされ、無効化までは同じオブジェクト(FU-08)
    assert sigs_a[0] is sigs_b[0]

    # 別グループ add でキャッシュ無効化 → 先頭ラッパーも作り直される
    other = _derived("y", [0.0, 1.0], [5.0, 6.0])
    session._groups.add(_group_of([other], tmp_path / "other.csv"))
    sigs_c = session.signals()

    # 無効化で作り直された「別オブジェクト」であること(tautology 回避の要)
    assert sigs_c[0] is not sigs_a[0]
    # それでも元 Signal への委譲で sorted_view のキャッシュ配列は共有される
    assert sigs_a[0].sorted_view()[0] is sigs_c[0].sorted_view()[0]


def test_session_is_csv_true_for_csv_false_for_mdf() -> None:
    """is_csv は CSV ローダー対象かを返す (GUI 開く経路分岐用・LD-01)。"""
    s = Session()
    assert s.is_csv(Path("a.csv")) is True
    assert s.is_csv(Path("a.CSV")) is True
    assert s.is_csv(Path("a.mf4")) is False


def test_group_keys_returns_loaded_group_keys_in_insertion_order(
    tmp_path: Path,
) -> None:
    """Session.group_keys() delegates to SignalGroupManager.keys: the keys of
    all loaded groups in insertion order. Used by prune to test signal
    membership by file without walking every signal (FU-16)."""
    session = Session()
    a = tmp_path / "a.csv"
    _write_csv(a, "t,speed", ["0.0,10.0"])
    k1 = session.load(a, format_def=_FMT).key
    b = tmp_path / "b.csv"
    _write_csv(b, "t,rpm", ["0.0,20.0"])
    k2 = session.load(b, format_def=_FMT).key
    assert session.group_keys() == [k1, k2]
    session.remove_group(k1)
    assert session.group_keys() == [k2]
