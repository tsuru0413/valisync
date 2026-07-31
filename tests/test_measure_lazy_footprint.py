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


@pytest.fixture
def mlf(monkeypatch: pytest.MonkeyPatch) -> Any:
    """計測器モジュールを **このテストの間だけ** import 可能にして返す。

    ``monkeypatch.setitem(sys.modules, ...)`` と ``monkeypatch.syspath_prepend`` は
    どちらもテスト終了で自動的に巻き戻る (module-level の ``sys.modules[...] = stub``
    / ``sys.path.insert`` は巻き戻らない — module docstring の WHY 参照)。

    実 psutil があるならスタブは**作らない**。無いときだけ差し込み、その差し替えも
    このテストの外へは漏れない。
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
    assert all(ms >= 0.0 for ms in out)
    assert cache.bytes_held == 0  # 合成エントリはキャッシュに残さない


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
