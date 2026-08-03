"""計測器 (scripts/measure_lazy_footprint.py) の E-4a 段が「ゼロ件でも合格」しないことの test-lock.

E-3 T9 のレビューで「``fresh`` の本数 assert が無いと ``TOTAL 0 columns = 0 ms`` を
刷って黙って合格する」が実際に指摘されている。E-4a で足す段 (キャッシュ冷熱の制御・
飽和・evict 解放時間) にも同じ穴が開きうる — かつ計測器は CI で回らないので、
**測定対象がゼロ件のときに loud-fail する**ことと、**計測器自身が数えられること**だけは
ここで固定する。

demo_data (gitignore・CI に無い) には依存しない: 冷熱と件数の判定は列構造だけで決まる
ので、合成 mf4 (幅広 2-D チャンネル 1 本) で全経路を踏める。

psutil は本番/dev いずれの依存にも無い (計測器は ``uv run --with psutil`` で回す) ため、
未インストールのときだけ import が通る最小スタブを差し込む。**その差し込みも
``sys.path`` への scripts 追加も module import 時にやってはならない** — どちらも
``sys.modules`` / ``sys.path`` を**セッション全体**に残す副作用で、実際に本環境では
psutil が未インストールなので (実測)、module-level でスタブを置くと
``tests/core/loaders/test_mdf_loader_master_retention.py`` の
``pytest.importorskip("psutil")`` が**スタブで成功し**、RSS 0 を実測値として読む
(今は VALISYNC_MEMTEST と prod_demo.mf4 の二重 gate に救われているだけで、gate が
1 つ外れた瞬間に「メモリ検証が常に合格する」形になる)。したがって差し込みは
``monkeypatch`` を使う ``mlf`` fixture に閉じ、テスト終了で必ず巻き戻す。
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.loaders import mdf_loader
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.session import Session

_SRC = str(Path(__file__).resolve().parents[1] / "src")
# この基準は **collection 時** = どの fixture も走る前に取る。走ったあとに取ると
# 「漏れた状態」を基準にしてしまい、恒真になる。
_SRC_COUNT_AT_IMPORT = sys.path.count(_SRC)


@pytest.fixture
def mlf(monkeypatch: pytest.MonkeyPatch) -> Any:
    """計測器モジュールを **このテストの間だけ** import 可能にして返す。

    ``monkeypatch.setitem(sys.modules, ...)`` と ``monkeypatch.syspath_prepend`` は
    どちらもテスト終了で自動的に巻き戻る (module-level の ``sys.modules[...] = stub``
    / ``sys.path.insert`` は巻き戻らない — module docstring の WHY 参照)。

    実 psutil があるならスタブは**作らない**。無いときだけ差し込み、その差し替えも
    このテストの外へは漏れない。

    ``sys.path`` も同様に漏れない — ただし理由は自明でない: 計測器モジュールは
    **自分自身の import 時に** ``sys.path.insert(0, <repo>/src)`` を実行する。それが
    残らないのは ``monkeypatch.syspath_prepend`` が **prepend の前に** ``sys.path``
    全体をスナップショットし、teardown でリスト丸ごと戻すためで、import を
    monkeypatch の窓の**中**で行っていることに依存している。窓の外へ出すと
    (module-level import・session fixture 化など) この巻き戻しは効かなくなる。
    ``test_the_import_does_not_leak_syspath_entries`` がその性質を pin している。
    """
    try:
        import psutil  # noqa: F401
    except ImportError:
        stub = types.ModuleType("psutil")

        class _StubProcess:
            def memory_info(self) -> types.SimpleNamespace:
                return types.SimpleNamespace(rss=0)

            def memory_full_info(self) -> types.SimpleNamespace:
                return types.SimpleNamespace(uss=0)

        stub.Process = _StubProcess  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "psutil", stub)

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    # NOTE: import した計測器モジュール自身は sys.modules に残る (残しても他テストへ
    # 影響しない — 影響するのは psutil という **共有された名前** の方だった)。
    # 残すことで 2 本目以降のテストが再 import のコストを払わずに済む。
    return importlib.import_module("measure_lazy_footprint")


def _loaded(tmp_path: Path, cols: int) -> tuple[Session, str]:
    session = Session()
    key = session.load(write_mdf4_wide_2d(tmp_path, cols=cols)).key
    return session, key


def _tiny_session(tmp_path: Path) -> Session:
    """列 0 件テスト用の最小セッション (中身は使わない — 引数検査だけを踏む)。"""
    session, _key = _loaded(tmp_path, cols=2)
    return session


def test_widest_channel_is_the_array_channel(mlf, tmp_path):
    """「同一広幅チャンネルの隣接 5 列」の主語 — 勝者が別チャンネルなら測定が別物になる。"""
    session, key = _loaded(tmp_path, cols=12)
    assert mlf._widest_channel(session, key) == ("Wide", 12)


def test_read_counters_count_and_restore(mlf, tmp_path):
    """計測器そのものの健全性 — 数えられないなら「select 1 回」は主張であって観測ではない。"""
    session, key = _loaded(tmp_path, cols=12)
    handle = mlf._handle_of(session, key)
    original_flatten = mdf_loader._flatten

    with mlf._ReadCounters(handle) as counters:
        col = session.resolve_signal(f"{key}::Wide[0]")
        assert col is not None and len(col.values) == 3
        mdf_loader._flatten("probe", np.zeros((3, 2)))

    assert counters.select_calls == 1, counters.select_calls
    assert counters.flatten_calls >= 1, counters.flatten_calls
    # 窓の外へ漏らさない (漏らすと以降の全計測が二重に数える)。
    assert mdf_loader._flatten is original_flatten
    assert "select" not in vars(handle.mdf)


def test_the_psutil_stub_does_not_leak_into_the_session():
    """スタブがセッションに残っていないこと (I-9 の回帰ガード)。

    残ると ``test_mdf_loader_master_retention.py`` の ``importorskip("psutil")`` が
    スタブで成功し、RSS 0 を実測値として読む。``mlf`` fixture を**要求しない**のが
    要点 — 要求すると差し込んだ状態で観測することになり、恒真になる。
    """
    stubbed = sys.modules.get("psutil")
    assert stubbed is None or getattr(stubbed, "__file__", None) is not None, (
        "テスト由来の psutil スタブが sys.modules に残っている"
    )


def test_the_import_does_not_leak_syspath_entries():
    """計測器の import が ``sys.path`` を**セッション全体**に汚していないこと。

    計測器は自分の import 時に ``sys.path.insert(0, <repo>/src)`` する。それが
    残ると、以降の全テストが「editable install 由来のパス」ではなく「先頭に挿された
    重複パス」から valisync を解決することになる (同じ木を指す限り無症状だが、
    worktree のように木が 2 つある状況では**別ブランチのコードを import する**)。
    残らないのは ``mlf`` fixture が ``monkeypatch`` の窓の中で import しているため
    (fixture docstring 参照) — その依存関係を検査に変えるのがこのテスト。

    観測は ``<repo>/src`` の**重複本数**で行う。``sys.path`` 全体の比較や scripts
    パスの有無では観測できない: 他のテストモジュール (``test_demo_mf4.py`` /
    ``test_compare_screenshots.py``) が module-level の ``sys.path.insert`` で
    ``<repo>/scripts`` をセッションに残しており、それは本ファイルの責務ではない。
    ``src`` を挿すのは計測器 1 つだけ (実測)。

    ``mlf`` fixture を要求しない — 要求すると窓の中で観測することになり恒真になる。
    """
    assert sys.path.count(_SRC) == _SRC_COUNT_AT_IMPORT, (
        f"<repo>/src が {sys.path.count(_SRC)} 回入っている "
        f"(このモジュールの import 時点では {_SRC_COUNT_AT_IMPORT} 回) — "
        "計測器の import が sys.path をセッションへ残した"
    )


def test_latency_starts_cold_even_when_the_channel_is_already_cached(mlf, tmp_path):
    """M5: 「未鋳造」は「キャッシュが冷たい」ではない — 測定側が明示的に冷やす。"""
    session, key = _loaded(tmp_path, cols=12)
    warm = session.resolve_signal(f"{key}::Wide[11]")  # 未鋳造の列を減らさずに温める
    assert warm is not None and len(warm.values) == 3
    assert session.channel_cache.bytes_held > 0  # 温まっていることの独立確認

    result = mlf.column_read_latency(session, key, cold_every_column=False)

    # 冷やし忘れると select は 1 度も呼ばれない (全列がキャッシュヒットで済む)。
    assert result.select_calls == 1, result
    assert result.misses >= 1, result
    assert result.hits >= mlf.LATENCY_COLUMNS - 1, result
    assert len(result.per_column_ms) == mlf.LATENCY_COLUMNS
    assert result.base_is_none  # C1: 命中パスが view を返していない


def test_latency_control_pays_one_decode_per_column(mlf, tmp_path):
    """対照 (E-4a 以前の経路) が本当に列ごとに冷たいこと — でなければ A/B が同じ物になる。"""
    session, key = _loaded(tmp_path, cols=12)

    result = mlf.column_read_latency(session, key, cold_every_column=True)

    assert result.select_calls == mlf.LATENCY_COLUMNS, result
    assert result.hits == 0, result


def test_latency_refuses_when_fewer_than_five_fresh_columns_remain(mlf, tmp_path):
    """ゼロ件 (件数不足) で「TOTAL 0 columns = 0 ms」を刷らず loud-fail する。"""
    session, key = _loaded(tmp_path, cols=6)
    for i in range(2):
        assert session.resolve_signal(f"{key}::Wide[{i}]") is not None

    with pytest.raises(AssertionError, match="未鋳造かつ隣接の列が"):
        mlf.column_read_latency(session, key, cold_every_column=False)


def test_evict_release_measures_only_puts_that_evicted(mlf):
    """evict が起きた put だけを標本にし、合成エントリを後始末する。"""
    cache = ChannelSampleCache(budget_bytes=4 * 1024)

    out = mlf.evict_release_ms(cache, entry_bytes=1024, samples=3)

    assert len(out) == 3
    # ``ms >= 0.0`` は経過時間なら何でも真になる恒真な「assert」だった。時計が
    # put の前後を挟めていなければ 0 に潰れ、逆に窓が壊れて別の作業を巻き込めば
    # 1 KiB の解放とは桁違いになる — その両側を締める。
    assert all(0.0 < s.ms < 100.0 for s in out), [s.ms for s in out]
    assert [s.evicted_bytes for s in out] == [1024, 1024, 1024], out
    assert cache.bytes_held == 0  # 合成エントリはキャッシュに残さない


def test_evict_release_attributes_the_subject_of_each_sample(mlf):
    """**何を追い出した標本か**を取り違えないこと (I1 の再発防止)。

    合成 ``np.ones`` を落とした標本と、外から載せた別ハンドルの配列を落とした標本は
    実測で ~2 倍違う。混ぜて 1 つの中央値にすると、次に測る人が主語の無い数値を
    読んで「速くなった」と誤読する。
    """
    cache = ChannelSampleCache(budget_bytes=4 * 1024)
    cache.put((999, 0, 0), np.ones(1024, dtype=np.uint8))  # 合成でない出自

    out = mlf.evict_release_ms(cache, entry_bytes=1024, samples=3)

    assert [s.evicted_real for s in out] == [True, False, False], out
    real, synth = mlf._split_evict(out)
    assert len(real) == 1 and len(synth) == 2, (real, synth)


def test_evict_release_refuses_when_nothing_is_evicted(mlf):
    """予算に余裕があり 1 件も追い出せなかった実行を「解放は速い」と読ませない。"""
    cache = ChannelSampleCache(budget_bytes=64 * 1024 * 1024)

    with pytest.raises(AssertionError, match="evict を 1 度も起こせなかった"):
        mlf.evict_release_ms(cache, entry_bytes=1024, samples=3)


def test_cache_saturation_refuses_when_the_budget_is_never_reached(mlf, tmp_path):
    """飽和しなかった実行は USS 天井を検証できない — 満点で通してはならない。"""
    session, key = _loaded(tmp_path, cols=12)

    with pytest.raises(AssertionError, match="予算に到達しなかった"):
        mlf.cache_saturation(session, key)


def test_export_full_run_refuses_a_zero_column_subject(mlf, tmp_path) -> None:
    """列 0 件で「完走した」と刷るのを禁止する (E-3 T9 の穴を --export 段でも塞ぐ)。"""
    with pytest.raises(AssertionError, match="測定対象"):
        mlf.export_full_run(_tiny_session(tmp_path), [], tmp_path / "o.csv", 1e9)


def test_export_full_run_requires_an_externally_supplied_limit(mlf) -> None:
    """USS 上限に既定値を持たせない (判定走行から閾値を得る循環の禁止・G4)。"""
    import inspect

    sig = inspect.signature(mlf.export_full_run)
    assert sig.parameters["uss_limit_mb"].default is inspect.Parameter.empty
