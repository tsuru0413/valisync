"""E-4a 読み経路: チャンネル単位キャッシュ + 位置パスの契約。

**demo_data に依存しない**: 自然な宛先に見える ``test_lazy_mdf_values.py`` /
``test_mdf_loader_lazy.py`` は module-level の demo skipif を持ち、``demo_data/`` は
gitignore 済み・CI に生成ステップが無いため丸ごと skip される。読み経路の所有権
不変条件 (spec §5.4) とキー空間 (spec §5.3) はサイレント破壊の入口なので、
``tests/mdf4_helpers`` + ``tmp_path`` で CI 実行できる形にする
(``test_mdf_handle_concurrency.py`` の module docstring と同じ理由)。
"""

from __future__ import annotations

import gc
import threading
import weakref
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from tests.mdf4_helpers import (
    write_mdf4,
    write_mdf4_2d,
    write_mdf4_dup_2d,
    write_mdf4_shared_group,
    write_mdf4_single_column_shapes,
)
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.models.sample_source import LazyMdfValues, SampleReadError
from valisync.core.session import Session

# WHY (core テストから gui を引く): teardown のバイト軸は gui 側の関数が持つが、
# 会計が正しくなる条件 (列が 2-D のビューを掴んでいないこと) は core の不変条件
# である。会計式そのものを写経すると、実装が変わったときに写経側だけが緑になる。
from valisync.gui.workers.teardown_service import _retained_bytes


class _CountingLock:
    """acquire を数える lock ラッパ (``MdfHandle.__slots__`` の "lock" へ差し替える)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.acquires = 0

    def __enter__(self) -> _CountingLock:
        self.acquires += 1
        self._lock.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._lock.release()


class _StubMdf:
    """select が n サンプルの 1-D を返す最小 MDF スタブ.

    宣言 length と実読み列の不一致は実 mf4 では作れない (v4.20+ の
    remote-master/column-storage が要る) ので、``test_mdf_handle_concurrency.py`` と
    同じくスタブで作る。
    """

    def __init__(self, n: int) -> None:
        self.n = n
        self.select_calls = 0

    def select(self, entries: Any, **kwargs: Any) -> list[Any]:
        self.select_calls += 1
        return [SimpleNamespace(samples=np.arange(self.n, dtype=np.float64))]


def _handle_of(session: Session, key: str) -> MdfHandle:
    """ロード済みグループの MdfHandle (test_handle_release.py と同じ入口)."""
    handle = session._groups.group(key).handle
    assert handle is not None, "MDF グループなのに handle が無い (setup 失敗)"
    return handle


def _records(session: Session, key: str) -> Any:
    """{表示名: ColumnRecord} — fixture が持つ (gi, ci) の実測に使う."""
    return session._groups.column_records(key)


def _buffer_owner(arr: np.ndarray) -> np.ndarray:
    """*arr* のメモリを実際に所有している ndarray を返す (base 連鎖の終端)。

    **これが「解放されたか」の唯一の正しい観測点**である。numpy は view の view を
    作るとき ``base`` を**中間オブジェクトではなく終端の所有者へ畳む**ので、
    キャッシュのエントリ自身 (asammdf が返す ``samples``) も所有者の view でしかない。
    エントリ**オブジェクト**へ weakref を張ると、列がバッファを掴んだままでも
    エントリだけは死ぬ = **RSS が 1 バイトも下がっていないのにテストが緑になる**
    (S1 で実測: entry alive=False / owner alive=True)。所有者を見れば、列が
    ビューを焼き付けている限り生き続けるので変異が届く。
    """
    owner = arr
    while owner.base is not None:
        owner = owner.base
    return owner


# ─── 1 チャンネル 1 デコード (spec §9 の select 回数 / §5.8 の lock 契約) ──────


def test_sibling_column_hits_the_cache_without_select_or_lock(tmp_path: Path) -> None:
    """同一物理チャンネルの 2 本目の列は select も handle.lock も要らない。

    E-4a の出口 (5 列 1,584ms / select 5 回 -> select 1 回) の Layer A オラクル。
    lock を見るのは spec §5.8 — 「ヒット = ファイルに触らない」なので、別スレッドの
    in-flight select (prod 実測 316 ms) を待ってはならない。ヒットを lock 内へ
    入れる実装は値のテストでは緑のまま通る (だから acquires を数える)。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    try:
        handle = _handle_of(session, key)
        cache = session.channel_cache
        assert cache.misses == 0, "ロード自体がキャッシュ経路を通っている (setup 失敗)"

        lock = _CountingLock()
        handle.lock = lock  # type: ignore[assignment]
        real_select = handle.mdf.select
        selected: list[Any] = []

        def _counting_select(entries: Any, **kwargs: Any) -> Any:
            selected.append(entries)
            return real_select(entries, **kwargs)

        handle.mdf.select = _counting_select  # type: ignore[assignment]

        first = session.resolve_signal(f"{key}::Mat[0]")
        assert first is not None
        np.testing.assert_array_equal(first.values, [0, 10, 20, 30])
        assert len(selected) == 1, "初回読みで select が 1 回でない"
        assert lock.acquires == 1, "初回読みが lock を取っていない (setup 失敗)"
        assert (cache.hits, cache.misses) == (0, 1)

        second = session.resolve_signal(f"{key}::Mat[2]")
        assert second is not None
        np.testing.assert_array_equal(second.values, [2, 12, 22, 32])
        assert len(selected) == 1, "2 本目の列で select が再実行されている"
        assert cache.hits == 1, "2 本目の列がキャッシュヒットしていない"
        assert cache.misses == 1, "miss 数 == select 回数 が崩れている"
        assert lock.acquires == 1, "キャッシュヒットが handle.lock を取っている"
    finally:
        session.remove_group(key)


def test_column_read_never_builds_the_leaf_name_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """読み経路は ``_flatten`` を通らない (位置パスで引く・spec §5.6)。

    名前引きは全リーフ辞書を作るので、幅 1,100 のチャンネルでは 1 列読むために
    1,100 本の f-string と 1,100 本の ascontiguousarray を払う。E-4a の出口
    「_flatten 呼び出し回数 1 -> 0」の直接の観測点。
    """
    from valisync.core.loaders import mdf_loader

    def _boom(name: str, arr: np.ndarray) -> Any:
        raise AssertionError(f"読み経路が _flatten を呼んだ: {name}")

    monkeypatch.setattr(mdf_loader, "_flatten", _boom)

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    try:
        col = session.resolve_signal(f"{key}::Mat[1]")
        assert col is not None
        np.testing.assert_array_equal(col.values, [1, 11, 21, 31])
    finally:
        session.remove_group(key)


# ─── キー空間 (spec §5.3): handle / gi / ci の 3 軸を別々に殺す ───────────────


def test_cache_key_separates_channels_that_share_a_raw_name(tmp_path: Path) -> None:
    """生名を共有する 2 チャンネル (LD-08) が同じキーに落ちない — **gi 軸**。

    ``write_mdf4_dup_2d`` は生名 "W" の 2-D を 2 本持つ (roundtrip fixture の
    ``Mat2`` と同じ形をヘルパにしたもの)。名前をキーにする実装・gi を落とす実装は
    2 本目に 1 本目の配列を配り、長さも dtype も一致するので例外は出ない。
    """
    session = Session()
    key = session.load(write_mdf4_dup_2d(tmp_path)).key
    try:
        records = _records(session, key)
        # 変異の到達範囲を fixture の実測で固定する: 生名は同じ・ci は同じ・gi だけ違う
        # (= このテストが殺せるのは gi 軸)。ci 軸は別テストが担当する。
        assert records["W[0]"].raw_base_name == records["W[1]"].raw_base_name == "W"
        assert records["W[0]"].channel_index == records["W[1]"].channel_index
        assert records["W[0]"].group_index != records["W[1]"].group_index

        first = session.resolve_signal(f"{key}::W[0][0]")
        second = session.resolve_signal(f"{key}::W[1][0]")
        assert first is not None and second is not None
        np.testing.assert_array_equal(first.values, [0, 2, 4, 6])
        np.testing.assert_array_equal(second.values, [100, 102, 104, 106])
    finally:
        session.remove_group(key)


def test_cache_key_separates_two_channels_in_one_group(tmp_path: Path) -> None:
    """同一グループの 2 チャンネルが同じキーに落ちない — **ci 軸**。

    ``write_mdf4_dup_2d`` は gi が違うので ci を落とす変異に盲目である
    (fixture の実測を下の assert で固定する)。同一グループ 2ch の fixture が
    ci 軸の唯一の観測点。
    """
    session = Session()
    key = session.load(write_mdf4_shared_group(tmp_path)).key
    try:
        records = _records(session, key)
        assert records["A"].group_index == records["B"].group_index
        assert records["A"].channel_index != records["B"].channel_index

        a = session.resolve_signal(f"{key}::A")
        b = session.resolve_signal(f"{key}::B")
        assert a is not None and b is not None
        np.testing.assert_array_equal(a.values, np.arange(10.0))
        np.testing.assert_array_equal(b.values, np.arange(10.0) * 2.0)
    finally:
        session.remove_group(key)


def test_cache_key_separates_two_files_with_identical_positions(
    tmp_path: Path,
) -> None:
    """同じ (name, gi, ci) を持つ 2 ファイルが混ざらない — **handle 軸**。

    Session は 1 個のキャッシュを全ファイルで共有する。handle をキーに含めないと
    2 ファイル比較で同じ曲線が 2 本描かれる (長さが同じなので長さ検証も通り、
    例外は出ない — spec §5.3)。
    """
    first_path = write_mdf4(
        tmp_path / "a.mf4",
        [{"name": "Spd", "timestamps": [0.0, 1.0], "values": [1.0, 2.0]}],
    )
    second_path = write_mdf4(
        tmp_path / "b.mf4",
        [{"name": "Spd", "timestamps": [0.0, 1.0], "values": [11.0, 12.0]}],
    )
    session = Session()
    key_a = session.load(first_path).key
    key_b = session.load(second_path).key
    try:
        rec_a, rec_b = _records(session, key_a)["Spd"], _records(session, key_b)["Spd"]
        # 到達範囲の実測: 2 ファイルは (gi, ci) が完全に一致する = handle だけが
        # 両者を分けている。ここが違うと本テストは handle 軸に盲目になる。
        assert (rec_a.group_index, rec_a.channel_index) == (
            rec_b.group_index,
            rec_b.channel_index,
        )

        a = session.resolve_signal(f"{key_a}::Spd")
        b = session.resolve_signal(f"{key_b}::Spd")
        assert a is not None and b is not None
        np.testing.assert_array_equal(a.values, [1.0, 2.0])
        np.testing.assert_array_equal(b.values, [11.0, 12.0])
    finally:
        session.remove_group(key_a)
        session.remove_group(key_b)


# ─── 所有権の不変条件 (spec §5.4 = レビュー Critical 1) ───────────────────────


def test_leaf_view_of_these_shapes_is_already_contiguous() -> None:
    """下 2 本の fixture 選択が「歯」である理由を numpy レベルで固定する。

    ``ascontiguousarray`` は非連続スライスなら必ずコピーするので、幅 3 の
    ``Mat[1]`` (stride 3) では copy を外す変異が **RED にならない**。共有 2-D の
    ビューが素通りできるのは「リーフのビューが既に連続」= 幅 1 の配列と単一
    フィールド構造体だけである。``write_mdf4_single_column_shapes`` の
    ``Mono`` / ``P`` がまさにその 2 形状。

    **このテストは実装前から緑**である (numpy の性質の pin であって挙動テストでは
    ない)。役割は、下の 2 本が別の fixture へ書き換えられたときに、その書き換えが
    「歯を抜いた」ことを説明できる形で残すこと。
    """
    width_one = np.zeros((4, 1), dtype=np.uint8)
    assert np.ascontiguousarray(width_one[:, 0]).base is not None  # コピーされない
    single_field = np.zeros(4, dtype=[("x", "<f8")])
    assert np.ascontiguousarray(single_field["x"]).base is not None
    width_three = np.zeros((4, 3), dtype=np.uint8)
    assert np.ascontiguousarray(width_three[:, 1]).base is None  # 必ずコピー


def test_minted_column_owns_its_values_on_the_cache_hit_path(tmp_path: Path) -> None:
    """命中パスが返す列は base を持たない独立配列 (spec §5.4)。

    ``_freeze`` は **read-only 入力を素通しする** (docstring が機能として明記) ので、
    read-only な共有 2-D のビューは凍結を通り抜けて ``_cache`` に焼き付く。すると
    evict しても列 Signal がチャンネル全体を生かし、``nbytes_if_materialized`` は
    ビュー自身の nbytes を返して teardown のバイト軸が実体の 1/1000 を計上する。

    容器を先に読んでからその列を読むことで **必ず命中パスを通す** (``cache.hits``
    でそれを実証する)。単一リーフのチャンネルには兄弟列が無く、素直に列だけ読むと
    ミスパスしか踏めない。
    """
    session = Session()
    key = session.load(write_mdf4_single_column_shapes(tmp_path)).key
    try:
        cache = session.channel_cache
        container = session.resolve_signal(f"{key}::Mono")
        assert container is not None
        assert container.values.ndim == 2  # 2-D をここで 1 回だけデコードする
        assert (cache.hits, cache.misses) == (0, 1)

        col = session.resolve_signal(f"{key}::Mono[0]")
        assert col is not None
        values = col.values
        assert cache.hits == 1, "命中パスを通っていない (このテストの前提が崩れた)"
        np.testing.assert_array_equal(values, [0, 1, 2, 3])
        assert col._values_source.array_if_materialized() is values
        # 会計の形の pin。**この等式だけでは copy 除去に盲目**である
        # (ビューの .nbytes はコピーと同値) — 歯は下の base assert と
        # 下の weakref テストが持つ。ここが守るのは「列が 2-D 丸ごとを
        # _cache に入れていない」という別の変異。
        # **base assert より前に置く**: S1 (apply_path の copy ガード除去) を当てた
        # とき「等式は通ったうえで base assert だけが落ちる」= 等式の盲目性が同じ
        # 実行で観測できる。後ろに置くと base で止まって到達せず、盲点の実測が
        # できない (順序を入れ替えないこと)。
        assert _retained_bytes(col, set()) == values.nbytes + col.timestamps.nbytes
        assert values.base is None, "列が共有 2-D のビューのまま焼き付いている"

        # 単一フィールド構造体でも同じ (ビューが連続になる 2 つ目の形)。
        struct_col = session.resolve_signal(f"{key}::P.x")
        assert struct_col is not None
        assert struct_col.values.base is None
        np.testing.assert_array_equal(struct_col.values, [1.0, 2.0, 3.0, 4.0])
    finally:
        session.remove_group(key)


def test_dropping_the_channel_frees_the_2d_because_the_column_is_independent(
    tmp_path: Path,
) -> None:
    """evict でチャンネル 2-D が**実際に解放される** (spec §5.4 の帰結 1)。

    「値が一致する」テストはビューでも通る。RSS が下がるかどうかを CI で見られる
    唯一の honest observable が weakref の生死である (ビューなら base 経由で
    2-D が生き続ける)。id() ではなく参照で見るのは、死んだオブジェクトの
    アドレス再利用による非決定フレークを避けるため。

    **weakref を張る先は ``_buffer_owner``** (エントリ自身ではない): numpy の base
    連鎖の畳み込みにより、エントリ**オブジェクト**は列がバッファを掴んだままでも
    死ぬ。S1 (copy ガード除去) を素の ``weakref.ref(dropped[0])`` で測ると
    entry alive=False / owner alive=True — つまり**変異が届かず緑のまま通る**
    実測が出た。この 1 行の違いが本テストの歯そのものなので、
    ``_buffer_owner`` を外して「単純化」しないこと。
    """
    session = Session()
    key = session.load(write_mdf4_single_column_shapes(tmp_path)).key
    try:
        handle = _handle_of(session, key)
        col = session.resolve_signal(f"{key}::Mono[0]")
        assert col is not None
        np.testing.assert_array_equal(col.values, [0, 1, 2, 3])

        dropped = session.channel_cache.drop_handle(id(handle))
        assert len(dropped) == 1, "読んだチャンネルの 2-D が載っていない (setup 失敗)"
        ref = weakref.ref(_buffer_owner(dropped[0]))
        del dropped
        gc.collect()
        assert ref() is None, "列が 2-D を生かしている (evict しても RSS が下がらない)"
        # 列自身は生きている (解放したのはチャンネルだけ)
        np.testing.assert_array_equal(col.values, [0, 1, 2, 3])
    finally:
        session.remove_group(key)


# ─── 保存すべき契約: 長さ検証・アンロード ────────────────────────────────────


def test_a_length_mismatch_is_not_burned_into_the_shared_cache() -> None:
    """長さ不変条件は共有キャッシュへ載せる **前** に執行する。

    後ろに置くと、壊れた読みが 1 度でも起きたチャンネルの全列が以後その配列を
    見る (miss しないので再読みの余地も無い)。

    **診断の宛先も同時に固定する** (spec §5.6): 位置パス化で読みは名前を使わなく
    なったので、``SampleReadError`` に載る ``signal_key`` / ``source_file`` だけが
    診断の宛先になった。両者が落ちても例外の型と文言は変わらないため、app レベルの
    excepthook の「1 信号 1 診断」dedup と診断ラベルが**黙って**壊れる — 文言だけを
    見る ``match=`` では捕まらないので、値そのものを assert する。
    """
    cache = ChannelSampleCache()
    # source_path を渡すのが要点: 既定の "" だと source_file の assert が
    # 「空文字と空文字の比較」= 恒真になり、宛先を落とす変異に盲目になる。
    handle = MdfHandle(_StubMdf(3), "C:/x.mf4", cache=cache)  # select は 3 サンプル
    src = LazyMdfValues(handle, "ch", 0, 1, length=4)  # 宣言は 4

    with pytest.raises(SampleReadError, match="サンプル数") as exc:
        src.array()

    assert exc.value.signal_key == "ch", "診断の宛先 (信号名) が失われている"
    assert exc.value.source_file == "C:/x.mf4", "診断の宛先 (ファイル) が失われている"
    assert cache.bytes_held == 0, "長さ検証を通らない読みが共有キャッシュに載った"
    assert src.array_if_materialized() is None


def test_unload_drops_the_channel_entries_before_close(tmp_path: Path) -> None:
    """アンロードでキャッシュのエントリが残らない。

    キーは ``id(handle)`` を含むだけでハンドルを**所有しない**ので、残したまま
    ハンドルが死ぬと、新しいファイルのハンドルが同じアドレスを再利用したときに
    古いファイルの 2-D を引き当てる (値が黙って入れ替わる)。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    col = session.resolve_signal(f"{key}::Mat[1]")
    assert col is not None
    np.testing.assert_array_equal(col.values, [1, 11, 21, 31])
    assert session.channel_cache.bytes_held > 0, "読んだのに載っていない (setup 失敗)"

    session.remove_group(key)
    assert session.channel_cache.bytes_held == 0


def test_selector_and_path_must_be_given_as_a_pair() -> None:
    """片方だけの構築を loud-fail させる。

    ``selector`` だけを渡せる形にすると、列 Signal が容器分岐 (2-D 丸ごと) を
    通って「例外の出ない誤データ」になる。片側だけの構築サイトは production に
    無いので、ここは将来の追加を止めるための構造ガード。
    """
    handle = MdfHandle(_StubMdf(4))
    with pytest.raises(ValueError, match="selector"):
        LazyMdfValues(handle, "ch", 0, 1, length=4, selector=("ch[0]",))
