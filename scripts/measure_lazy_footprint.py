"""Lazy-load acceptance: real GUI RSS footprint for prod_demo.mf4 (1 / 2 files).

Drives the REAL MainWindow load path (off-thread LoadController + busy overlay)
on a real display, exactly as a user does, and samples peak/steady RSS with a
background psutil thread. Proves the lazy-load memory win end-to-end at prod
scale — the mechanism proof (``_values_source.is_materialized``) lives in the
Layer C realgui test; this is the RSS half of the acceptance (both required —
``is_materialized`` is a mechanism observable, NOT an RSS proxy).

Why the real load path (not an internal API): FU-16/FU-18/FU-20 repeatedly
showed internal-API repros under-measure the real footprint. Only the real GUI
build + real ``_load_file`` reaches the true working set (memory
``gui_perf_e2e_repro_must_drive_real_load_path``).

- QT_QPA_PLATFORM defaults to "windows" — a real window is shown on screen.
- E-3 T8/T9: the 1024 expansion guard and its confirmation modal are retired, so
  there is no longer an "arrays skipped" knob to set here. Columns are no longer
  Signals at all; they are minted on demand, which is why every count below is
  split into TWO axes — physical channels (``group_signals``) and columns
  (``total_column_count``). Reading ``len(group_signals)`` as "columns" is a 61x
  misread post-inversion, and minted columns live OUTSIDE that enumeration (in
  ``SignalGroupManager._resolved_by_key``), so any materialization accounting
  that only walks ``group_signals`` silently reports zero (``_materialized_names``
  is the one that walks both).
- USS (``memory_full_info().uss``) is the PRIMARY metric: RSS includes the shared
  mmap pages of the opened file, so the lazy win drowns in an ~mmap floor.
- QSettings is isolated to a Measure org (never touches the real registry).
- The 2-file number loads prod_demo a second time into the SAME window (a
  compare-mode journey: keys mf4_1, mf4_2), so its steady RSS is the true
  two-file working set and its peak is the peak during the second load.

Run:
    uv run --with psutil python scripts/measure_lazy_footprint.py

Prints ASCII-only lines (safe when redirected without PYTHONUTF8=1).
"""

from __future__ import annotations

import gc
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PROC = psutil.Process()
MB = 1024 * 1024
TARGET = REPO / "demo_data" / "prod_demo.mf4"
LOAD_TIMEOUT_S = 180.0
SETTLE_S = 1.5
DRAIN_TIMEOUT_S = 300.0
# 増分B: 展開済み regime を実際に踏むためのリーフ数 (= _SIGNAL_BUDGET と同数以上)。
MATERIALIZE_TARGET = 8_000


def rss_mb() -> float:
    return PROC.memory_info().rss / MB


def uss_mb() -> float:
    """Unique Set Size (このプロセス固有の物理メモリ) = **E-3 の主指標**。

    RSS は mmap 済みの共有ページ (asammdf が開いたファイルのページキャッシュ) を
    含むので、遅延化の勝ち負けを RSS だけで読むと mmap フロア (~205 MiB) に埋もれる。
    memory_full_info() は working set を歩くぶん高価 — 20ms 周期の peak サンプラーでは
    使わず、settle 済みの計測点でだけ読む。
    """
    return PROC.memory_full_info().uss / MB


class PeakSampler(threading.Thread):
    """Background thread tracking the max process RSS while a load runs."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = rss_mb()
        self._running = True

    def run(self) -> None:
        while self._running:
            current = rss_mb()
            if current > self.peak:
                self.peak = current
            time.sleep(0.02)

    def stop(self) -> None:
        self._running = False


@dataclass
class LoadResult:
    n_files: int
    peak_mb: float
    steady_mb: float
    steady_uss_mb: float
    load_wall_s: float
    physical: int
    columns: int


def _pump(app: object, seconds: float) -> None:
    """Spin the real event loop for *seconds* wall-clock (model reset/paint)."""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()  # type: ignore[attr-defined]
        time.sleep(0.03)


def load_one_more(app: object, win: object, expect_files: int) -> LoadResult:
    """Load prod_demo once more into *win*; sample peak/steady for that state.

    Waits until ``loaded_file_keys`` reaches *expect_files* (the off-thread
    load has completed and been registered on the GUI thread), lets the model
    reset / paint settle, then reads the settled RSS/USS after a gc.
    """
    sampler = PeakSampler()
    sampler.start()
    t0 = time.perf_counter()
    win._load_file(TARGET)  # type: ignore[attr-defined]

    deadline = t0 + LOAD_TIMEOUT_S
    while (
        len(win.app_vm.loaded_file_keys) < expect_files  # type: ignore[attr-defined]
        and time.perf_counter() < deadline
    ):
        app.processEvents()  # type: ignore[attr-defined]
        time.sleep(0.03)
    load_wall = time.perf_counter() - t0

    _pump(app, SETTLE_S)  # settle model reset / paint before reading steady
    sampler.stop()
    sampler.join(timeout=1.0)

    gc.collect()
    steady = rss_mb()
    steady_uss = uss_mb()
    keys = win.app_vm.loaded_file_keys  # type: ignore[attr-defined]
    session = win.app_vm.session  # type: ignore[attr-defined]
    # 反転後 group_signals() は物理チャンネルのみ。列数は総数 API で別に取る
    # (この 2 つが 1 桁以上ずれるのが E-3 の勝ちそのもの)。
    physical = len(session.group_signals(keys[-1])) if keys else 0
    columns = session.total_column_count(keys[-1]) if keys else 0
    return LoadResult(
        n_files=expect_files,
        peak_mb=sampler.peak,
        steady_mb=steady,
        steady_uss_mb=steady_uss,
        load_wall_s=load_wall,
        physical=physical,
        columns=columns,
    )


# One alphanumeric keystroke, deliberately the WORST CASE for prod_demo: 'o'.
#
# The retained memo (`(fl, list[_TreeRow], int)` in ChannelBrowserVM) is
# O(surviving rows), never O(matched columns) -- per-row cost does NOT shrink
# as more columns match. Per channel_browser_vm.py's filter memo builder, a
# row with hits == 1 stores MORE than a row with hits > 1: it keeps an extra
# `single` tuple (the sliced orig name + resolved unit), while hits > 1 stores
# `None` in that slot. So the row-payload-MAXIMIZING case is the one where
# most rows match exactly one column, which is 'a': it matches only 4,003 of
# the 264,004 columns across 4,003 of the 4,264 rows (the generated channels
# are Prod<n>_<nnnn>), i.e. essentially every surviving row has hits == 1 and
# pays the extra tuple. Measured: FILTER MECHANISM COST +1.3 MB, wall 94.1 ms
# (scans=1). Row counts between 'a' (4,003) and 'o' (4,261) are near-identical
# out of 4,264 total, so switching from 'a' to 'o' does not add allocations --
# if anything it removes ~4,000 of the per-row `single` tuples, since 'o'
# rows mostly have hits > 1 and store None instead.
#
# What 'o' actually is, is the WALL-TIME worst case: the column-name scan
# walks every column regardless of match, but the `hits += 1` branch (and the
# `_matches` call feeding it) executes once per MATCHED column, 264,001 times
# for 'o' vs only 4,003 times for 'a'. Measured: filter wall 126.3 ms for 'o'
# vs 94.1 ms for 'a' (both scans=1) -- that additional per-hit work is why
# 'o', not 'a', is used as the reported worst-case timing figure.
BROWSER_FILTER_QUERY = "o"


def _orig(ns_name: str) -> str:
    """``mf4_1::Prod10_0000`` -> ``Prod10_0000`` (namespaced 名 → 表示名)。"""
    from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR

    return ns_name.split(KEY_SEPARATOR, 1)[1] if KEY_SEPARATOR in ns_name else ns_name


def _column_keys_of(session: object, key: str, display: str) -> list[str]:
    """物理チャンネル *display* の列キー (**名前だけで作る = 鋳造しない**)。

    ExportCsvDialog の「すべて選択」(C-b) と同じ規約: 列の列挙は ColumnSpec 由来の
    名前で行い、``resolve()`` は実際に値が要るときまで呼ばない。ここで鋳造すると
    計測器自身が測ろうとしている 264k オブジェクトを再導入する。
    """
    from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR

    return [
        f"{key}{KEY_SEPARATOR}{col}"
        for col in session.column_names_of(key, display)  # type: ignore[attr-defined]
    ]


def _materialized_names(session: object, key: str) -> list[str]:
    """値が展開済みの Signal 名 (**物理チャンネル + 鋳造列**)。

    鋳造列は ``SignalGroup.signals`` の外 (``_resolved_by_key``) に居るので、
    ``group_signals()`` だけを走査すると「8,000 列を展開したのに materialized=0」と
    いう静かに嘘の会計になる。副テーブルの列挙は ``resolved_keys()`` (非鋳造)、
    実体取得は ``resolve()`` (鋳造済みキーなのでキャッシュヒット)。
    """
    mgr = session._groups  # type: ignore[attr-defined]
    names = [
        s.name
        for s in session.group_signals(key)  # type: ignore[attr-defined]
        if s._values_source.is_materialized
    ]
    for col_key in mgr.resolved_keys(key):
        col = mgr.resolve(col_key)
        if col is not None and col._values_source.is_materialized:
            names.append(col.name)
    return names


def browser_residue(win: object, key: str) -> None:
    """Stage the CHANNEL BROWSER's own memory cost on top of the loaded session.

    The lazy-load win above is about the *session*; E-2 is about what the
    browser adds on top of it. Pre-E-2 that residue was measured at ~87 MB for
    prod_demo (``ChannelBrowserVM._prep`` 68 MB of per-column lowercased names
    + ``SignalTreeModel._Node.leaves`` 19 MB of eagerly-built leaf nodes).
    E-2 folds ``_prep`` to one row per physical channel and synthesizes the
    leaves only on expansion, so both terms should be gone.

    Measured on a FRESH ``ChannelBrowserVM`` / ``SignalTreeModel`` over the
    already-loaded session (the window's live browser has of course already
    built its own), so each stage's delta is the marginal cost of that step:

      1 loaded            -- settled baseline after the real load
      2 + signal_map()    -- the read-only resolving map (must NOT explode:
                             ``dict(signal_map())`` would re-cast every column)
      3 + group_signals() -- the defensive per-key list copy the browser holds
      4 + prep/tree_groups() + SignalTreeModel  -- THE E-2 target (was ~87 MB)
      5 + one filter applied through all three production consumers
                             (tree_groups / shown_count / header_text)

    Stage 5 - stage 4 is printed as an explicit label: it is the filter
    mechanism's own cost, and being a self-difference within one run it is far
    more robust than an A/B against a remembered number from another machine.
    The wall time of that one filter application is printed from the same run.
    """
    from valisync.gui.adapters.signal_tree_model import SignalTreeModel
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

    session = win.app_vm.session  # type: ignore[attr-defined]

    gc.collect()
    s1 = rss_mb()

    smap = session.signal_map()
    n_physical_keys = len(smap)  # enumeration is physical-keys-only by contract
    gc.collect()
    s2 = rss_mb()

    group_sigs = session.group_signals(key)
    n_physical = len(group_sigs)
    # 反転後は列 Signal が存在しない — 列数は ColumnSpec 由来の総数 API から取る
    # (len(group_sigs) を「列数」と読むと 61 倍の取り違えになる)。
    n_columns = session.total_column_count(key)
    gc.collect()
    s3 = rss_mb()

    vm = ChannelBrowserVM(win.app_vm)  # type: ignore[attr-defined]
    rows = vm.tree_groups()
    n_rows = len(rows)
    n_prep_columns = sum(row[3] for row in rows)
    gc.collect()
    s4a = rss_mb()

    model = SignalTreeModel(vm)  # eager top level only; children stay lazy
    n_top = model.rowCount()
    gc.collect()
    s4 = rss_mb()

    scans_before = vm.inspect()["filter_scans"]
    t0 = time.perf_counter()
    # set_filter notifies -> the model above rebuilds (tree_groups); the three
    # explicit calls are the other production consumers of the same notify
    # (header_text/empty_state both go through shown_count).
    vm.set_filter(BROWSER_FILTER_QUERY)
    shown = vm.shown_count()
    filtered_rows = len(vm.tree_groups())
    header = vm.header_text()
    filter_wall_ms = (time.perf_counter() - t0) * 1000.0
    scans = vm.inspect()["filter_scans"] - scans_before
    gc.collect()
    s5 = rss_mb()

    vm.set_filter("")
    vm.tree_groups()
    vm.shown_count()
    vm.header_text()
    gc.collect()
    s6 = rss_mb()

    # ブラウザの列数はローダーの列総数と一致していなければならない。ずれたら
    # ヘッダーの「N ch 中 M ch を表示」が静かに嘘になっている (U2 の単位契約)。
    assert n_prep_columns == n_columns, (n_prep_columns, n_columns)
    # ブラウザ行 = 物理チャンネル = group_signals の要素数 (反転後は 1:1)。
    assert n_rows == n_physical == n_top, (n_rows, n_physical, n_top)

    print("\n=== CHANNEL BROWSER residue (fresh VM+model over loaded session) ===")
    print(
        f"  columns={n_columns:,}  physical channels={n_physical:,}  "
        f"rows={n_rows:,}  model top rows={n_top:,}"
    )
    print(f"  signal_map keys (physical only)={n_physical_keys:,}")
    print(f"  1 loaded (settled)          = {s1:,.0f} MB")
    print(f"  2 + signal_map()            = {s2:,.0f} MB   (+{s2 - s1:,.1f} MB)")
    print(f"  3 + group_signals() [phys]  = {s3:,.0f} MB   (+{s3 - s2:,.1f} MB)")
    print(f"  4a+ VM prep/tree_groups()   = {s4a:,.0f} MB   (+{s4a - s3:,.1f} MB)")
    print(f"  4 + SignalTreeModel         = {s4:,.0f} MB   (+{s4 - s4a:,.1f} MB)")
    print(
        f"  5 + filter {BROWSER_FILTER_QUERY!r} x3 consumers = {s5:,.0f} MB   (+{s5 - s4:,.1f} MB)"
    )
    print(f"  6 + filter cleared          = {s6:,.0f} MB   (+{s6 - s5:,.1f} MB)")
    print(f"  BROWSER PREP RESIDUE  (stage 4 - stage 3) = {s4 - s3:,.1f} MB")
    print("    (pre-E-2 measured: _prep 68 MB + _Node.leaves 19 MB = ~87 MB)")
    print(f"  FILTER MECHANISM COST (stage 5 - stage 4) = {s5 - s4:,.1f} MB")
    print("    (target ~0 MB: no per-column lowercased name cache is kept)")
    print(f"  ONE FILTER APPLICATION wall = {filter_wall_ms:,.1f} ms  (scans={scans})")
    print("    (pre-E-2 measured 170-213 ms; scans==1 means the memo collapsed")
    print("     the 3 consumers of one notify into a single column-name pass)")
    print(f"  filter result: shown={shown:,} columns / rows={filtered_rows:,}")
    print(f"  header: {header}")

    del model, vm, rows, group_sigs, smap
    gc.collect()
    print(f"  released (browser objects dropped) = {rss_mb():,.0f} MB", flush=True)


@dataclass
class DrainResult:
    label: str
    physical: int
    minted: int
    materialized: int
    sync_close_ms: float
    ticks: int
    max_tick_ms: float
    mean_tick_ms: float
    total_drain_s: float
    # (index, ms, signals, bytes, gc passes)
    top_ticks: tuple[tuple[int, float, int, int, int], ...]
    # T4: remove_group が close の前にキャッシュを回収して teardown へ渡す (spec §5.7)。
    # **既定値を置かない**: 0.0 の既定は「配線し忘れた実行」を "0.0 -> 0.0" として
    # 刷り、回収を検証できていない実行が検証済みに見える (T5 レビュー Minor)。
    # 必須フィールドなら配線漏れは TypeError で止まる。
    cache_mb_before: float
    cache_mb_after: float
    # プロセス全体ではなく **この unload 対象ファイル** のぶん。(a) は 1 バイトも
    # キャッシュしていないファイルを unload するので、プロセス全体の行だけでは
    # 「回収できていない」と誤読される (実測 188.8 -> 188.8 は別ファイルのぶん)。
    handle_cache_mb_before: float
    handle_cache_mb_after: float


def instrument_teardown_ticks() -> list[tuple[float, int, int, int]]:
    """Wrap ``_drain``; record (seconds, signals, bytes, gc collections) per tick.

    MUST run BEFORE the window (and therefore the service) is built:
    ``QTimer.timeout`` captures a *bound method* at connect time, so patching the
    class afterwards leaves the live connection pointing at the original.

    The signal/byte counts are what attribute a slow tick to an axis: a tick that
    freed ~``_SIGNAL_BUDGET`` signals or ~``_BYTE_BUDGET`` bytes was stopped by
    that budget, while one that stopped well short of both was stopped by the
    deadline (and its overshoot is the ``_CLOCK_CHECK_EVERY`` granularity).
    The gc counter is the other candidate explanation for a slow tick: freeing
    hundreds of thousands of objects triggers generational collections, and a
    gen-2 pass over a still-live 264k-signal session is expensive. Attributing a
    spike to gc rather than to a budget matters -- one is a pacing defect, the
    other is not.

    Nothing production-side is touched: ``pending_signals()`` and
    ``last_tick_bytes`` are the service's own public observables.
    """
    from valisync.gui.workers import teardown_service as ts

    ticks: list[tuple[float, int, int, int]] = []
    original = ts.TeardownService._drain

    def gc_passes() -> int:
        return sum(int(stat["collections"]) for stat in gc.get_stats())

    def timed(self: object) -> None:
        before = self.pending_signals()  # type: ignore[attr-defined]
        gc_before = gc_passes()
        t0 = time.perf_counter()
        original(self)
        elapsed = time.perf_counter() - t0
        ticks.append(
            (
                elapsed,
                before - self.pending_signals(),  # type: ignore[attr-defined]
                self.last_tick_bytes,  # type: ignore[attr-defined]
                gc_passes() - gc_before,
            )
        )

    ts.TeardownService._drain = timed  # type: ignore[method-assign]
    return ticks


def _bulk_columns(name: str, samples: object) -> dict[str | None, object]:
    """Every leaf column of ONE physical channel, built with production code.

    ``LazyMdfValues.array()`` = ``select`` -> ``_flatten`` (leaf) /
    ``ascontiguousarray`` -> ``_freeze``. Only the ``select`` is shared here;
    everything that decides what the retained array *is* (dtype, shape,
    contiguity, read-only, ownership) is the production code, so the drained
    state is identical. The flatten is hoisted to once per CHANNEL (production
    re-flattens per leaf, which is O(leaves^2) when a channel carries 1,000 of
    them) -- the per-leaf arrays it yields are the same objects either way.
    Key = the leaf name production matches on (``selector[-1]``); ``None`` is
    the scalar (no-selector) branch.
    """
    import numpy as np

    from valisync.core.loaders.mdf_loader import _flatten
    from valisync.core.models.sample_source import _freeze

    leaves = _flatten(name, samples)
    if len(leaves) == 1 and leaves[0][0] == name:
        # scalar channel: production takes the ascontiguousarray branch directly
        return {None: _freeze(np.ascontiguousarray(samples))}
    return {leaf_name: _freeze(arr) for leaf_name, arr in leaves}


def _select_samples(handle: object, name: str, gi: int, ci: int) -> object:
    with handle.lock:  # type: ignore[attr-defined]
        return handle.mdf.select(  # type: ignore[attr-defined]
            [(name, gi, ci)],
            raw=False,
            ignore_value2text_conversions=True,
            copy_master=False,
        )[0].samples


def materialize_leaves(win: object, key: str, target: int) -> int:
    """>= *target* 列を「プロット済み + 範囲統計」状態にし、その列数を返す。

    反転後 (E-3) は列 Signal がロード時に存在しないので、まず production の解決器
    (``Session.resolve_signal``) で列を **鋳造** してから値を入れる。列キーは
    ColumnSpec の名前だけから作る (``_column_keys_of``) — 列挙のために鋳造しない。

    WHY not one ``sig.values`` per leaf (the literal production route): prod_demo's
    array channels carry 1,000+ leaves each and ``LazyMdfValues.array()`` re-selects
    (and re-decompresses) the WHOLE channel per leaf -- measured 383 ms per leaf,
    i.e. ~51 minutes for 8,000. Here each physical channel is selected ONCE and its
    leaves are built from that one read through the same ``_flatten``/``_freeze``
    production helpers, so every retained array is byte-identical to the lazy route
    (asserted below on BOTH branches -- scalar and LD-14 leaf -- against arrays
    materialized through the real ``sig.values``). ``range_stat_index()`` is then
    called through the production API, which also builds
    ``sorted_view``/``finite_view`` -- exactly the state a plotted signal with range
    statistics holds, which is the regime this input exists to measure.
    """
    import numpy as np

    session = win.app_vm.session  # type: ignore[attr-defined]
    physical = session.group_signals(key)
    handle = physical[0]._values_source._handle

    # 等価性の対照実験用の候補を 2 分岐ぶんだけ先に拾う (全チャンネルぶんの列キーを
    # 事前生成すると 330k 文字列を計測中ずっと抱えることになる)。
    single_col: str | None = None
    multi_col: str | None = None
    for sig in physical:
        cols = _column_keys_of(session, key, _orig(sig.name))
        if single_col is None and len(cols) == 1:
            single_col = cols[0]
        if multi_col is None and len(cols) > 1:
            multi_col = cols[0]
        if single_col is not None and multi_col is not None:
            break

    # Equivalence control: one signal per branch goes through the REAL lazy read
    # and the bulk route must reproduce that array exactly. Without it the fast
    # route could silently retain a differently shaped/typed array and the drain
    # numbers would describe a state the app never reaches.
    for col_key in (single_col, multi_col):
        if col_key is None:
            continue
        probe = session.resolve_signal(col_key)  # production の鋳造経路
        assert probe is not None, f"列キーが解決できない: {col_key}"
        src = probe._values_source
        branch = "scalar" if src._selector is None else "ld14-leaf"
        prod_arr = probe.values  # production LazyMdfValues.array()
        table = _bulk_columns(
            src._name, _select_samples(handle, src._name, src._gi, src._ci)
        )
        bulk_arr = table[None if src._selector is None else src._selector[-1]]
        assert prod_arr.dtype == bulk_arr.dtype, (prod_arr.dtype, bulk_arr.dtype)
        assert prod_arr.shape == bulk_arr.shape, (prod_arr.shape, bulk_arr.shape)
        assert prod_arr.flags.writeable == bulk_arr.flags.writeable is False
        assert prod_arr.flags.c_contiguous and bulk_arr.flags.c_contiguous
        assert np.array_equal(prod_arr, bulk_arr)
        # 測定の意味を決めるのはここ: dtype/shape/内容が一致していても、bulk 側の
        # リーフが 1 つの base 配列をエイリアスしていたら「解放」が桁違いに安くなり、
        # ティック時間を無言で低く見せる (上の 4 つはその失敗モードに盲目)。
        if src._selector is not None:
            # 列 (LD-14 リーフ): production は apply_path が独立配列を返す契約
            # (spec §5.4) なので、bulk 側にも同じ所有権を要求する。1 本の 2-D を
            # 1,000 リーフで共有されるとティック時間が桁違いに安く出る分岐。
            assert prod_arr.flags.owndata and bulk_arr.flags.owndata, (
                "リーフが base をエイリアスしている — 解放コストが production と違う"
            )
        else:
            # 容器 (スカラーチャンネル) に owndata を要求してはならない — E-4a T2 が
            # ``_freeze`` を ``put`` の前へ出した結果、production は read-only 化した
            # asammdf の samples を**そのまま**値にする (sample_source._column_of の
            # docstring)。実測 (prod_demo VehSpd): prod は owndata=False /
            # base=同サイズ (96,000 B) の ndarray でチェーンは 2 段、bulk は
            # ``_freeze`` が書き込み可能な入力をコピーするので owndata=True。
            # 解放コストで意味を持つのは所有権でなく**解放される実体の大きさ**なので、
            # 「自分より大きい base を生かし続けない」だけを両者に要求する
            # (裸の owndata assert は「production と違う物を保持しろ」になる)。
            # チェーンは**最後まで**歩く: 実測の 2 段は同サイズだが、深さ 1 だけ見る
            # 実装は「同サイズの view の先に巨大な実体がぶら下がる」形に盲目になる。
            for tag, arr in (("prod", prod_arr), ("bulk", bulk_arr)):
                base, hops = arr.base, 0
                while base is not None:
                    hops += 1
                    size = getattr(base, "nbytes", None)
                    # ndarray 以外 (bytes 等) が base に来た実績は無い。来たなら
                    # 大きさが読めない = 検証できていないので黙って通さない。
                    assert size is not None, (
                        f"{tag} の base チェーンに大きさの読めない要素",
                        hops,
                        type(base),
                    )
                    assert size == arr.nbytes, (
                        f"{tag} 側が自分より大きい base を抱えている — 解放コストが違う",
                        hops,
                        arr.nbytes,
                        size,
                    )
                    base = getattr(base, "base", None)
        print(
            f"  EQUIVALENCE ok [{branch}]: bulk route reproduces the lazy array "
            f"({prod_arr.dtype}, {prod_arr.shape}, {prod_arr.nbytes / 1024:,.0f} KiB)"
        )
        del table, bulk_arr, prod_arr

    done = 0
    # E-4a: T3 の鋳造列 LRU (既定容量 512 列) は非 pin の列を古い順に落とす。
    # ここは 8,000 本を鋳造するが 1 本もプロットしないので、pin を張らないと
    # _resolved_by_key に残るのは ~512 本だけになり、(b) のドレインが測る対象が
    # 消える (下の母数 assert が必ず失敗する) だけでなく、RemovalResult.removed_columns
    # が 8,000 -> ~512 になって E-3 が測った「展開済み regime」そのものを踏まなくなる。
    # pin は拒否されない (spec §5.5) ので、**鋳造の前**に張れば容量超でも全列が残る。
    # GUI がプロット中の列を push するのと同じ API を、測定側が「今から触る列」へ
    # 使うだけ (集合は置き換えなので、チャンネルごとに累積して押し直す)。
    pins: set[str] = set()
    t0 = time.perf_counter()
    for sig in physical:
        if done >= target:
            break
        psrc = sig._values_source
        col_keys = _column_keys_of(session, key, _orig(sig.name))
        pins.update(col_keys)
        session.set_pinned_columns(pins)
        table = _bulk_columns(
            psrc._name, _select_samples(handle, psrc._name, psrc._gi, psrc._ci)
        )
        for col_key in col_keys:
            col = session.resolve_signal(col_key)
            if col is None:
                continue
            src = col._values_source
            if src._cache is None:
                src._cache = table[None if src._selector is None else src._selector[-1]]
            col.range_stat_index()  # production API: sorted_view + finite_view + RSI
            done += 1
        del table, col_keys
    wall = time.perf_counter() - t0

    materialized = len(_materialized_names(session, key))
    print(
        f"  materialized {materialized:,} / {session.total_column_count(key):,} columns "
        f"(minted {len(session._groups.resolved_keys(key)):,}) "
        f"(+range_stat_index) in {wall:,.1f}s"
    )
    # (b) のドレインは「展開済み信号が実在すること」を前提にした計測なので、母数が
    # 目標に届かなかった実行を「MAX tick OK」と読ませない。E-4a では _resolved_by_key の
    # evict (D4) で鋳造列が測定中に消えうるため、この 1 本が唯一の観測点になる
    # (3-3a の pin が効いていないと、ここが最初に鳴る)。
    assert materialized >= target, (
        f"展開済み列が {materialized:,} 本しかない (目標 {target:,}) — "
        "(b) のドレインが測る対象が存在しない (鋳造列が evict された可能性)"
    )
    # 参照は関数の return で全て落ちるが、下の集計と gc を正しい状態で行うため
    # 明示的に落とす (ドレインは唯一の参照者でなければならない)。
    del physical
    gc.collect()
    return materialized


def drain_after_unload(app: object, win: object, key: str, label: str) -> DrainResult:
    """Unload *key* through the real VM path and time every teardown tick.

    The unload itself (``AppViewModel.unload_file``) is the same call the File
    Browser's confirmation dialog makes; the drain is then driven by pumping the
    real event loop, exactly as the running app does between user events.
    """
    session = win.app_vm.session  # type: ignore[attr-defined]
    mgr = session._groups
    # リストを名前に束縛しない: 束縛すると全 Signal を掴んだままになり、ドレインが
    # 何も解放できない (ティックが不当に速く見える)。
    n_physical = len(session.group_signals(key))
    n_minted = len(mgr.resolved_keys(key))
    materialized = len(_materialized_names(session, key))
    cache = _channel_cache(session)
    cache_before = cache.bytes_held
    # ハンドル id は unload の**前**に控える (unload 後は group_signals が引けない)。
    hid = id(_handle_of(session, key))
    handle_before = _handle_cache_bytes(cache, hid)
    gc.collect()

    ticks: list[tuple[float, int, int, int]] = win._tick_log  # type: ignore[attr-defined]
    ticks.clear()
    t0 = time.perf_counter()
    win.app_vm.unload_file(key)  # type: ignore[attr-defined]
    sync_close = time.perf_counter() - t0

    deadline = time.perf_counter() + DRAIN_TIMEOUT_S
    while (
        win.teardown_service.pending_signals() > 0  # type: ignore[attr-defined]
        and time.perf_counter() < deadline
    ):
        app.processEvents()  # type: ignore[attr-defined]
    total = time.perf_counter() - t0
    cache_after = cache.bytes_held
    handle_after = _handle_cache_bytes(cache, hid)
    app.processEvents()  # type: ignore[attr-defined]

    durations = [t[0] for t in ticks]
    top = sorted(enumerate(ticks), key=lambda pair: pair[1][0], reverse=True)[:5]
    return DrainResult(
        label=label,
        physical=n_physical,
        minted=n_minted,
        materialized=materialized,
        sync_close_ms=sync_close * 1000.0,
        ticks=len(ticks),
        max_tick_ms=max(durations) * 1000.0 if durations else 0.0,
        mean_tick_ms=(sum(durations) / len(durations)) * 1000.0 if durations else 0.0,
        total_drain_s=total,
        top_ticks=tuple((i, s * 1000.0, n, b, g) for i, (s, n, b, g) in top),
        cache_mb_before=cache_before / MB,
        cache_mb_after=cache_after / MB,
        handle_cache_mb_before=handle_before / MB,
        handle_cache_mb_after=handle_after / MB,
    )


def report_drain(results: list[DrainResult]) -> None:
    from valisync.gui.workers.teardown_service import (
        _BYTE_BUDGET,
        _CLOCK_CHECK_EVERY,
        _SIGNAL_BUDGET,
        _TICK_DEADLINE_S,
    )

    # 粒度: デッドラインは _CLOCK_CHECK_EVERY 信号おきにしか見ないので、超過は
    # 「デッドライン + 1 チェック間隔ぶん」までは設計どおり。
    budget_ms = _TICK_DEADLINE_S * 1000.0
    allowance_ms = 12.0
    print("\n=== TEARDOWN DRAIN tick time (prod_demo, real GUI unload path) ===")
    print(
        f"  budgets: {_SIGNAL_BUDGET:,} signals / {_BYTE_BUDGET / MB:,.0f} MiB / "
        f"{budget_ms:.0f} ms deadline per tick"
    )
    for r in results:
        verdict = "OK" if r.max_tick_ms <= allowance_ms else "OVER"
        print(f"  --- {r.label} ---")
        print(
            f"  physical={r.physical:,}  minted columns={r.minted:,}  "
            f"materialized at unload={r.materialized:,}"
        )
        print(f"  sync close (UI thread)  = {r.sync_close_ms:,.1f} ms")
        # 回収 (T4) の主語は **この unload 対象ファイル** である。プロセス全体の
        # bytes_held は別ファイルのぶんを含むので、それだけでは回収を証明も反証も
        # できない (T5 レビュー Minor)。
        if r.handle_cache_mb_before > 0.0:
            recovered = "OK" if r.handle_cache_mb_after == 0.0 else "LEAK"
            claim = (
                f"このファイル {r.handle_cache_mb_before:,.1f} -> "
                f"{r.handle_cache_mb_after:,.1f} MB  [{recovered}]"
                "  (T4: close の前に回収して teardown へ渡す)"
            )
        else:
            claim = (
                "このファイルはキャッシュ 0 本 = **回収の観測対象なし** "
                "(T4 の証拠にはならない)"
            )
        print(f"  cache bytes at unload   = {claim}")
        print(
            f"    プロセス全体の bytes_held = {r.cache_mb_before:,.1f} -> "
            f"{r.cache_mb_after:,.1f} MB  (他ファイルのぶんを含む)"
        )
        print(f"  ticks                   = {r.ticks:,}")
        print(f"  MAX tick                = {r.max_tick_ms:,.1f} ms   [{verdict}]")
        print(f"  mean tick               = {r.mean_tick_ms:,.2f} ms")
        print(f"  total drain             = {r.total_drain_s:,.2f} s")
        print("  top ticks (axis attribution):")
        # 最終ティックは _drain の中で on_finished (GUI 通知 -> FileBrowser の
        # モデルリセット) まで走るので、そこだけ性質が違う。どのティックが重いのかを
        # 出さないと「予算超過」と「最終ティックの GUI 通知」を取り違える。
        for i, ms, n, nbytes, gc_passes in r.top_ticks:
            last = (
                " (last: includes on_finished GUI notify)" if i == r.ticks - 1 else ""
            )
            print(
                f"    tick #{i:<3} {ms:5.1f} ms  freed {n:,} signals / "
                f"{nbytes / MB:,.1f} MiB  gc={gc_passes}{last}"
            )
    print(
        f"  acceptance: MAX tick <= {allowance_ms:.0f} ms "
        "(plan: deadline + 1 granularity)"
    )

    print(
        "  NOTE: E-3 反転後、(a) は 264k の未展開シェルではなく **4.3k の物理チャンネル**\n"
        "        ぶんしか無い (シェル 1 本 1.6us regime の母数が 61 分の 1)。ペーシングの\n"
        "        証拠は (b) — 鋳造列 + range stats — 側でしか取れない。"
    )
    print(
        "  NOTE: a deadline-bound tick can overrun by up to _CLOCK_CHECK_EVERY-1\n"
        f"        ({_CLOCK_CHECK_EVERY - 1}) signals' worth of work. Measured per-signal\n"
        "        free cost: 1.6 us (lazy shell) .. 8-27 us (materialized prod leaf\n"
        "        with sorted/finite view + range_stat_index), so the granularity is\n"
        "        sized against the 27 us case (31 * 27 us = 0.84 ms).\n"
        "  NOTE: the granularity is NOT what makes (b)'s single worst tick exceed the\n"
        "        band. Traced at granularity 1, exactly ONE free out of 264,004 costs\n"
        "        5.8 ms (rest <= 0.6 ms, p99 = 10 us, gc = 0) -- a heap-return stall.\n"
        "        Max tick is therefore floored at deadline + max single free ~= 14 ms\n"
        "        (measured worst 14.2; the stall magnitude varies run to run, so 13.8\n"
        "        is a lower bound, not a ceiling) for ANY _CLOCK_CHECK_EVERY.\n"
        "  NOTE: tightening _BYTE_BUDGET does NOT lower that floor -- the byte axis can\n"
        "        only end a tick EARLIER than the deadline, never shorten\n"
        "        'deadline + one atomic free'. Do not retry that lever.\n"
        "  context: 1 frame @60fps = 16.7 ms; pre-pacing measured freeze = 649 ms"
    )


# ─── E-4a: チャンネル単位キャッシュの観測 ─────────────────────────────────────
LATENCY_COLUMNS = 5
LATENCY_TARGET_MS = 380.0  # spec §9 (5 列合計)
# U3: キャッシュ合計の追加メモリ予算 (spec §5.1)。
#
# **一次判定はキャッシュ自身の会計 (bytes_held <= 予算)** であってプロセス USS では
# ない。LRU は「次の 1 本を載せると予算を超える」ところまで正当に保持する (実測
# 251.8 MB) ので、USS 側に残るヘッドルームは構造的に ~4 MB しかなく、アロケータと
# 一時分がそれを食う — 「プロセス USS delta <= 予算」は達成不能に近い帯の定義だった
# (T5 レビュー I4)。USS は「予算 + 実測オーバーヘッド」に対する**参考**として刷る。
CACHE_BUDGET_MB = 256
# 参考帯に足す実測オーバーヘッド (USS delta - bytes_held)。実測: headless --core
# n=4 で 2.5-3.5 MB / 実 GUI n=1 で 3.1 MB (いずれも gc.collect 後)。断片化の
# 揺れを吸える程度に丸めて 8 MB とする — ここを実測ぎりぎりにすると I4 と同じ
# 「構造的に達成不能な帯」を USS 側へ作り直すことになる。
CACHE_USS_OVERHEAD_MB = 8.0
# evict の同期解放時間を測るための合成エントリの handle id。実オブジェクトの id() は
# 0 にならないので、実ファイルのエントリと絶対に衝突しない。
_SYNTH_HANDLE_ID = 0
# M5: E-3 の獲得 (core 297 MB / USS +15 MB / load 1.43 s) の非回帰帯。
CORE_RESIDENT_LIMIT_MB = 310.0
CORE_USS_DELTA_LIMIT_MB = 20.0
# load wall の帯は**中央値の ~1.4 倍**に置く (T5 レビュー I3)。実測 (HEAD・warm・
# fresh process n=33): 中央値 1.42 s / 最小 1.33 / 最大 1.65 s。旧帯 1.6 s は
# 中央値の 1.13 倍しかなく、ページキャッシュが完全に温まった状態でも 1/33 が超えた
# (E-3 記録 1.43 s との差は測定ノイズであって回帰ではない)。加えてセッション初回の
# 冷たいページキャッシュでは 3.38 s を実測しており、1 実行の verdict は本質的に
# advisory である。2.0 s なら「E-3 比で実質倍」= 本物の回帰だけが鳴る。
CORE_LOAD_LIMIT_S = 2.0


class _ReadCounters:
    """1 回の測定窓で production が何回 select / ``_flatten`` したかを**直接**数える。

    ``cache.misses`` は「キャッシュが数えた miss」であって「select を呼んだ回数」では
    ない — 先に select してから cache を見る実装でも miss は 1 になりうるので、観測点
    1 本では中途半端実装 (M4) を区別できない。``_flatten`` を module 属性の差し替えで
    捕まえられるのは、呼び出し元が**呼び出しのたびに module から取り直す**形
    (関数内 ``from ... import _flatten``) しか無いため。**E-4a の読み経路は位置パス
    (``apply_path``) へ置き換わっており、期待値は 0** — 0 であること自体が「列 1 本の
    ために全リーフを flatten する」のをやめた観測点になる。
    """

    def __init__(self, handle: Any) -> None:
        self._mdf = handle.mdf
        self._real_select: Any = None
        self._real_flatten: Any = None
        self._had_own_select = False
        self.select_calls = 0
        self.flatten_calls = 0

    def __enter__(self) -> _ReadCounters:
        from valisync.core.loaders import mdf_loader

        self._real_select = self._mdf.select
        self._had_own_select = "select" in vars(self._mdf)
        self._real_flatten = mdf_loader._flatten

        def counting_select(*args: Any, **kwargs: Any) -> Any:
            self.select_calls += 1
            return self._real_select(*args, **kwargs)

        def counting_flatten(*args: Any, **kwargs: Any) -> Any:
            self.flatten_calls += 1
            return self._real_flatten(*args, **kwargs)

        self._mdf.select = counting_select
        mdf_loader._flatten = counting_flatten
        return self

    def __exit__(self, *exc: object) -> None:
        from valisync.core.loaders import mdf_loader

        mdf_loader._flatten = self._real_flatten
        if self._had_own_select:
            self._mdf.select = self._real_select
        else:
            del self._mdf.select  # クラス側の実装へ戻す


def _channel_cache(session: Any) -> Any:
    """Session が全ファイルで共有する 1 個の ChannelSampleCache (spec §5.3)。"""
    from valisync.core.loaders.channel_cache import ChannelSampleCache

    cache = session.channel_cache
    assert isinstance(cache, ChannelSampleCache), type(cache)
    return cache


def _handle_of(session: Any, key: str) -> Any:
    """グループの MdfHandle (キャッシュキー ``(handle.serial, gi, ci)`` の第 1 成分)。"""
    return session.group_signals(key)[0]._values_source._handle


def _handle_cache_bytes(cache: Any, handle_id: int) -> int:
    """*handle_id* **1 ファイルぶん**のキャッシュバイト数。

    キャッシュはファイル別の会計を公開していない (公開するのは予算の裁定に必要な
    プロセス全体の ``bytes_held`` だけ)。しかし「このファイルの回収が起きたか」は
    全体の合計では読めない — 他ファイルのぶんが残っていれば回収済みでも減らないし、
    1 バイトも載っていないファイルなら「変わらない」ことが回収の証拠にならない
    (T5 レビュー Minor)。観測点は内部辞書のキー第 1 成分しかないので、ここだけ
    private を読む。
    """
    return sum(
        int(arr.nbytes) for k, arr in cache._entries.items() if k[0] == handle_id
    )


def _widest_channel(session: Any, key: str) -> tuple[str, int]:
    """列数が最大の物理チャンネルとその列数 (**名前を 1 本も生成しない**)。

    探索は ColumnRecord の spec を数えるだけ (leaf_count は名前を 1 本も生成しない)。
    ここで column_names_of を全チャンネルに回すと prod では 330k 本の文字列を作って
    捨てることになり、計測器自身が測ろうとしているコストを踏む。
    """
    from valisync.core.loaders.column_names import leaf_count

    records = session._groups.column_records(key)
    widest_n, widest_display = 0, ""
    for display, record in records.items():
        n = leaf_count(record.spec)
        if n > widest_n:
            widest_n, widest_display = n, display
    assert widest_display, "ロード済みグループに列レコードが無い"
    return widest_display, widest_n


@dataclass
class LatencyResult:
    label: str
    channel: str
    columns_in_channel: int
    per_column_ms: tuple[float, ...]
    hits: int
    misses: int
    select_calls: int
    flatten_calls: int
    minted: int
    entries_left: int
    base_is_none: bool


def column_read_latency(
    session: Any, key: str, *, cold_every_column: bool
) -> LatencyResult:
    """同一広幅チャンネルの隣接 5 列を production 経路で読み、対話コストを実測する。

    **キャッシュの冷熱を測定側で決める** (レビュー M5): E-4a 以降「未鋳造」は
    「キャッシュが冷たい」を意味しない — 未鋳造の列でも同じ物理チャンネルが
    ``ChannelSampleCache`` に載っていれば読みはスライスだけで終わる。冷熱を制御
    しないと 1,584 ms → 380 ms がキャッシュの効果なのか呼び出し順序の偶然なのかを
    区別できない (先行する段が同じチャンネルを温めていれば 0 ms すら出せる)。

    ``cold_every_column=False``: 測定開始時だけ冷たい = ユーザーが広幅チャンネルの
    隣接 5 列をまとめて載せる journey。期待は select 1 回 / hit 4。
    ``cold_every_column=True``: 列ごとに 1 decode。同一実行内の対照であり、これが
    無いと 380 ms に比較対象が無い (別マシンで測った値との A/B は環境差を吸えない)。

    **対照は「E-4a 以前」ではなく その下限である** (T5 レビュー I5): merge-base
    (84a5a69) の読み経路は列ごとに select **に加えて** 全リーフの
    ``dict(_flatten(...))`` をやり直していたが、この対照は select だけを払う。
    同一マシン・同一ファイル・同一チャンネル (Prod10Wide_0000) ・同一位置
    (load 直後) で実測すると、対照 1,675 / 1,723 / 1,809 ms に対し merge-base を
    実際にチェックアウトして測った真の before は 2,033 / 2,102 / 2,177 ms
    (n=3 ずつ) で、**対照の方が中央値で ~380 ms 楽観的**である。したがってこの行は
    「以前はこうだった」ではなく「キャッシュ無しでも最低これだけ掛かる」を意味する。
    """
    mgr = session._groups
    cache = _channel_cache(session)
    handle = _handle_of(session, key)
    # 旧: id(handle)。serial 化 (E-4b) 後に id のまま残すと 1 件もヒットせず
    # **例外を出さずに 0** を刷る — 計測器の追随漏れは常にサイレントになる。
    hid = handle.serial

    display, width = _widest_channel(session, key)
    col_keys = _column_keys_of(session, key, display)
    # 安い数え方 (leaf_count) と、列キーを実際に作る唯一の真実 (column_names_of →
    # leaf_names) が食い違ったら「勝者チャンネル」の主張が黙って嘘になる。
    assert len(col_keys) == width, (len(col_keys), width, display)
    already = mgr.resolved_keys(key)
    fresh = [k for k in col_keys if k not in already][:LATENCY_COLUMNS]
    # 呼び出し位置が動いて先頭列が既に鋳造済みになるとループが 0 回になり
    # 「TOTAL 0 columns = 0 ms」を刷って**黙って合格**する (E-3 T9 の指摘)。
    assert len(fresh) == LATENCY_COLUMNS, (
        f"未鋳造かつ隣接の列が {len(fresh)} 本しかない (channel={display} / "
        f"鋳造済み {len(already)}) — 測定対象ゼロ件での黙った合格を防ぐ前提"
    )

    # 冷たい状態を作る唯一の行。drop_handle は落としたエントリを **返す** ので、
    # 戻り値を捨てた時点でキャッシュ側の参照は消える。
    cache.drop_handle(hid)
    # カウンタは drop の**後**に読む: 冷熱の確認に cache.get を使うと hits/misses が
    # 動いて測定対象そのものを汚すので、観測点は drop_handle の戻り本数側に置く。
    hits_before, misses_before = cache.hits, cache.misses
    mint_before = mgr.mint_count

    per_column: list[float] = []
    base_is_none = True
    with _ReadCounters(handle) as counters:
        for col_key in fresh:
            if cold_every_column:
                cache.drop_handle(hid)  # 解放は計測窓の外 (測るのは読みのコスト)
            t0 = time.perf_counter()
            col = session.resolve_signal(col_key)  # 鋳造 (production 経路)
            assert col is not None, f"列キーが解決できない: {col_key}"
            arr = col.values  # 実読み: miss なら select・hit ならスライス + コピー
            per_column.append((time.perf_counter() - t0) * 1000.0)
            assert len(arr) > 0
            # C1 所有権不変条件 (spec §5.4): 命中パスが view を焼き付けると evict しても
            # RSS が下がらず _retained_bytes も実体の 1/1000 になる。値一致は view でも
            # 通るので、ここが計測器側の唯一の観測点になる。
            base_is_none = base_is_none and arr.base is None

    dropped = cache.drop_handle(hid)
    label = "列ごとに 1 decode (E-4a 以前の**下限** — 列ごとの _flatten を含まない)"
    if not cold_every_column:
        label = "測定開始時のみ冷 (E-4a の journey)"
    return LatencyResult(
        label=label,
        channel=display,
        columns_in_channel=width,
        per_column_ms=tuple(per_column),
        hits=cache.hits - hits_before,
        misses=cache.misses - misses_before,
        select_calls=counters.select_calls,
        flatten_calls=counters.flatten_calls,
        minted=mgr.mint_count - mint_before,
        entries_left=len(dropped),
        base_is_none=base_is_none,
    )


def report_latency(results: list[LatencyResult]) -> None:
    print(
        "\n=== COLUMN READ latency (同一広幅チャンネルの隣接 5 列・E-4a 受け入れ) ==="
    )
    for r in results:
        total = sum(r.per_column_ms)
        print(f"  --- {r.label} ---")
        print(f"  channel={r.channel}  columns in channel={r.columns_in_channel:,}")
        for i, ms in enumerate(r.per_column_ms):
            # 小数 2 桁は飾りではない: この増分のヘッドライン (兄弟列 0.07-0.31 ms)
            # は :,.0f では全部 "0 ms" になり、自分の成果を別プローブで測り直す
            # 羽目になる (T5 レビュー Minor)。
            print(f"    column #{i}  {ms:,.2f} ms")
        verdict = "OK" if total <= LATENCY_TARGET_MS else "OVER"
        print(
            f"  TOTAL {len(r.per_column_ms)} columns = {total:,.0f} ms   [{verdict}]"
            f"   (目標 <= {LATENCY_TARGET_MS:,.0f} ms)"
        )
        print(
            f"  select calls = {r.select_calls}   _flatten calls = {r.flatten_calls}"
            "   (目標 select 1 / _flatten <= 1 — 位置パス経路なら 0)"
        )
        print(
            f"  cache hits/misses = {r.hits}/{r.misses}   "
            f"entries left for this file = {r.entries_left}   minted = {r.minted}"
        )
        own = "OK" if r.base_is_none else "VIEW LEAK"
        print(f"  minted values.base is None = {r.base_is_none}   [{own}]")
    print(
        "  reference (真の before = merge-base 84a5a69 を実際にチェックアウトして\n"
        "  実測・同一チャンネル Prod10Wide_0000 / n=3): 5 列 2,033 / 2,102 / 2,177 ms\n"
        "  (346-496 ms/列)。同一位置で測った上の対照 (列ごとに 1 decode) は\n"
        "  1,675-1,809 ms で、中央値 ~380 ms 楽観的な**下限**である\n"
        "  (merge-base は列ごとに全リーフ _flatten もやり直していた)。\n"
        "  対照が cached 側と同程度なら、キャッシュが効いていないか冷やす側が\n"
        "  壊れている — どちらでも受け入れは成立しない。",
        flush=True,
    )


@dataclass(frozen=True)
class EvictSample:
    """1 回の evict の同期解放時間と、**追い出された配列の出自**。

    出自を持ち回すのが本体である (T5 レビュー I1): 同じループ・同じサイズでも、
    実 asammdf デコード配列を落とすときと、直前に自分で置いた ``np.ones`` を
    落とすときで実測が ~2 倍違う。主語を書かずに数値だけ記録すると、次に合成で
    測った人が「速くなった」と誤読する。
    """

    ms: float
    evicted_real: bool  # False = このループが直前に置いた合成 np.ones
    evicted_bytes: int


def _split_evict(samples: tuple[EvictSample, ...]) -> tuple[list[float], list[float]]:
    """(実配列を落とした標本, 合成を落とした標本) の ms リスト。"""
    real = [s.ms for s in samples if s.evicted_real]
    synth = [s.ms for s in samples if not s.evicted_real]
    return real, synth


def _rewarm_one_channel(session: Any, key: str) -> int:
    """広幅チャンネル 1 本をキャッシュへ戻し、そのバイト数を返す。

    飽和 + evict 標本採取のあとキャッシュは空になる (標本を取るために自分で全部
    追い出す)。回収 (T4) の観測はそこに**何かが載っている**ことが前提なので、
    観測対象を明示的に作る段としてここに置く。

    **未鋳造の列を選ぶ**のが要点: 既に鋳造済みの列は ``LazyMdfValues._cache`` に
    自分の列配列を焼き付けているので、``values`` はチャンネルキャッシュを一度も
    触らずに返る (飽和段で読んだ「各チャンネルの先頭リーフ」がまさにそれ) —
    温め直したつもりで 0 バイトのまま進む。列名は見つかるまでしか作らない。
    """
    from valisync.core.loaders.column_names import leaf_names
    from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR

    display, _width = _widest_channel(session, key)
    records = session._groups.column_records(key)
    already = session._groups.resolved_keys(key)
    col = None
    for leaf in leaf_names(display, records[display].spec):
        col_key = f"{key}{KEY_SEPARATOR}{leaf}"
        if col_key in already:
            continue
        col = session.resolve_signal(col_key)
        break
    assert col is not None, f"未鋳造の列が無い (channel={display})"
    arr = col.values
    assert len(arr) > 0
    return int(
        _handle_cache_bytes(_channel_cache(session), id(_handle_of(session, key)))
    )


@dataclass
class SaturationResult:
    channels_read: int
    wall_s: float
    bytes_held_mb: float
    hits: int
    misses: int
    evictions: int
    skipped_oversize: int
    base_rss_mb: float
    base_uss_mb: float
    rss_mb: float
    uss_mb: float
    evict: tuple[EvictSample, ...]
    evict_entry_mb: float


def evict_release_ms(
    cache: Any, entry_bytes: int, samples: int = 32
) -> tuple[EvictSample, ...]:
    """予算超の put が 1 エントリを追い出すときの**同期**解放時間 (ms)。

    LRU の evict は unload と違い TeardownService のペーシングを通らない (spec §5.7)
    ので、1 回の解放が呼び出しスレッドを止める時間そのものが受け入れ対象になる。
    追加する側を合成配列にするのは、実チャンネルを読むと select のデコード時間が
    同じ窓に入って解放だけを取り出せないから。``np.ones`` で埋めるのは
    ``np.zeros``/``np.empty`` が OS の遅延マップで触られていないページを返し、
    解放が実測より安く出るため。

    **測っているのは追い出される側**なので、標本は出自で分けて返す (I1)。飽和済みの
    実キャッシュに対して呼ぶと、最初の n 本は実デコード配列を、それを出し切った
    あとは自分が直前に置いた ``np.ones`` を落とす — 後者は同じ 12 MiB ブロックが
    free 直後に再確保される warm-allocator バイアスが乗り、中央値が半分に出る。
    既定 32 は「記録の方法論と同じ n=20 を実配列側で確保し、残りで合成側を同じ実行の
    中に並べる」ための本数 (実キャッシュのエントリは実測 21 本)。
    """
    import numpy as np

    out: list[EvictSample] = []
    for i in range(samples * 8):
        if len(out) >= samples:
            break
        arr = np.ones(max(1, entry_bytes), dtype=np.uint8)
        before = cache.evictions
        # 次に落ちる 1 本 (LRU 先頭) を put の**前**に覗く。キャッシュはファイル別・
        # 出自別の会計を公開していないので、出自を知る観測点はここしかない。
        victim = next(iter(cache._entries), None)
        victim_bytes = 0 if victim is None else int(cache._entries[victim].nbytes)
        t0 = time.perf_counter()
        accepted = cache.put((_SYNTH_HANDLE_ID, 0, i), arr)
        elapsed = (time.perf_counter() - t0) * 1000.0
        del arr  # キャッシュを唯一の参照者にする (次の evict が実解放になる)
        if not accepted:
            break  # oversize: この予算では evict を起こせない
        if cache.evictions - before == 1 and victim is not None:
            out.append(
                EvictSample(
                    ms=elapsed,
                    evicted_real=victim[0] != _SYNTH_HANDLE_ID,
                    evicted_bytes=victim_bytes,
                )
            )
    cache.drop_handle(_SYNTH_HANDLE_ID)
    # 測定対象がゼロ件でも「解放は速い」と読めてしまう経路を塞ぐ。
    assert out, (
        "evict を 1 度も起こせなかった — 解放時間の測定対象がゼロ件 "
        f"(bytes_held={cache.bytes_held / MB:,.0f} MB / "
        f"entry={entry_bytes / MB:,.2f} MB)"
    )
    return tuple(out)


def cache_saturation(
    session: Any, key: str, max_channels: int = 64
) -> SaturationResult:
    """広い順にチャンネルを読んで予算を飽和させ、飽和後の USS と evict を実測する。

    広い順に読むのは D6 の裏返し: prod の広幅は 13.2 MB/本なので 256 MB を埋めるには
    ~19 本要る一方、スカラー (1.9 KB) から読むと 13 万本読んでも飽和しない。
    """
    from valisync.core.loaders.column_names import leaf_count, leaf_names
    from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR

    cache = _channel_cache(session)
    hid = id(_handle_of(session, key))
    records = session._groups.column_records(key)
    widest = sorted(
        ((leaf_count(rec.spec), display) for display, rec in records.items()),
        reverse=True,
    )[:max_channels]
    assert widest, "ロード済みグループに列レコードが無い"

    cache.drop_handle(hid)
    gc.collect()
    base_rss, base_uss = rss_mb(), uss_mb()
    hits0, misses0 = cache.hits, cache.misses
    ev0, over0 = cache.evictions, cache.skipped_oversize

    channels = 0
    t0 = time.perf_counter()
    for _n, display in widest:
        # 列名は 1 本だけ生成する: _column_keys_of は広幅 1 本で 1,100 本の f-string を
        # 作るので、64 チャンネルぶん回すと計測器自身が測ろうとしているコストを踏む。
        first = next(leaf_names(display, records[display].spec), None)
        if first is None:
            continue
        col = session.resolve_signal(f"{key}{KEY_SEPARATOR}{first}")
        if col is None:
            continue
        arr = col.values  # 1 列読む = そのチャンネル全体が 1 エントリとして載る
        if first != display:
            # C1 (spec §5.4): **列を読んだときだけ** 所有権を要求する。
            # first == display は「リーフが 1 本しかない物理チャンネル」(スカラーや
            # 単一フィールド) で、返るのは列ではなく**容器 Signal そのもの**。
            # 容器分岐は np.ascontiguousarray(samples) を返し、連続な samples では
            # 同一オブジェクトが返って _freeze も (read-only 済みなので) コピー
            # しない — したがって **values.base は非 None になりうる** (実測:
            # Clean (3,) float64 base=ndarray)。ここを裸で assert すると、広い順
            # 64 本の走査が最初のスカラーチャンネルに到達した瞬間に落ち、しかも
            # メッセージが無いので test_cache_saturation_refuses_when_the_budget_
            # is_never_reached の match= が「別の理由で」満たされなくなる。
            assert arr.base is None, first
        channels += 1
        if cache.evictions > ev0:
            break  # 予算超過 = 飽和した
    wall = time.perf_counter() - t0
    gc.collect()
    rss, uss = rss_mb(), uss_mb()
    held = cache.bytes_held

    # 測定対象がゼロ件でも「USS は予算内」に見える経路を塞ぐ (この 2 本が無いと
    # 1 本も載らなかった実行が満点で通る)。
    assert channels > 0, "1 チャンネルも読めていない (飽和計測が空)"
    assert cache.evictions > ev0, (
        "予算に到達しなかった — この入力では飽和後の天井を検証できない "
        f"(bytes_held={held / MB:,.0f} MB / 読んだチャンネル {channels})"
    )
    return SaturationResult(
        channels_read=channels,
        wall_s=wall,
        bytes_held_mb=held / MB,
        hits=cache.hits - hits0,
        misses=cache.misses - misses0,
        evictions=cache.evictions - ev0,
        skipped_oversize=cache.skipped_oversize - over0,
        base_rss_mb=base_rss,
        base_uss_mb=base_uss,
        rss_mb=rss,
        uss_mb=uss,
        # 追加サイズは実エントリと同程度にする: 小さすぎると 1 回の evict のあと
        # 何度 put しても予算に触れず、標本が集まらない。
        evict=evict_release_ms(cache, int(held / channels)),
        evict_entry_mb=held / channels / MB,
    )


def _ms_line(label: str, xs: list[float]) -> str:
    if not xs:
        return f"    {label}: n=0 (標本なし)"
    ordered = sorted(xs)
    median = ordered[len(ordered) // 2]
    if len(ordered) % 2 == 0:
        median = (ordered[len(ordered) // 2 - 1] + median) / 2.0
    return (
        f"    {label}: n={len(xs)}  median {median:,.2f} ms  "
        f"max {max(xs):,.2f} ms  min {min(xs):,.2f} ms"
    )


def report_cache(sat: SaturationResult) -> None:
    delta_uss = sat.uss_mb - sat.base_uss_mb
    overhead = delta_uss - sat.bytes_held_mb
    uss_band = CACHE_BUDGET_MB + CACHE_USS_OVERHEAD_MB
    # 一次判定は「予算の裁定が効いたか」= キャッシュ自身の会計。プロセス USS を
    # 同じ 256 と比べる帯は構造的に達成不能だった (T5 レビュー I4)。
    held_verdict = "OK" if sat.bytes_held_mb <= CACHE_BUDGET_MB else "OVER"
    uss_verdict = "OK" if delta_uss <= uss_band else "OVER"
    print("\n=== CHANNEL CACHE saturation (U3 予算 256 MB・spec §9) ===")
    print(
        f"  channels read (widest first) = {sat.channels_read}  in {sat.wall_s:,.1f}s"
        f"   hits/misses = {sat.hits}/{sat.misses}"
    )
    print(
        f"  cache bytes_held [PRIMARY] = {sat.bytes_held_mb:,.1f} MB   "
        f"[{held_verdict}]   (予算 <= {CACHE_BUDGET_MB} MB)   "
        f"evictions = {sat.evictions}   skipped_oversize = {sat.skipped_oversize}"
    )
    print(
        f"  baseline (cache empty) = {sat.base_rss_mb:,.0f} MB RSS / "
        f"{sat.base_uss_mb:,.0f} MB USS"
    )
    print(
        f"  saturated              = {sat.rss_mb:,.0f} MB RSS / {sat.uss_mb:,.0f} MB USS"
    )
    print(
        f"  USS delta (参考)       = +{delta_uss:,.1f} MB   [{uss_verdict}]   "
        f"(予算 {CACHE_BUDGET_MB} + オーバーヘッド許容 "
        f"{CACHE_USS_OVERHEAD_MB:,.0f} = {uss_band:,.0f} MB)"
    )
    print(
        f"    内訳: bytes_held {sat.bytes_held_mb:,.1f} + "
        f"アロケータ/一時分 {overhead:,.1f} MB"
    )
    print(
        "    (USS delta を予算 256 と直接比べてはならない: LRU は「次の 1 本が\n"
        "     入らない」ところまで正当に保持するので構造的に ~4 MB しか残らない)"
    )
    real, synth = _split_evict(sat.evict)
    print(f"  LRU evict 同期解放 (put するのは {sat.evict_entry_mb:,.1f} MB/エントリ):")
    print(_ms_line("実 asammdf デコード配列を追い出した put", real))
    print(_ms_line("リサイクルされた合成 np.ones を追い出した put", synth))
    print(
        "    (同じループ・同じサイズでも出自で ~2 倍違う。合成だけで測ると free 直後に\n"
        "     同じブロックを再確保する warm-allocator バイアスが乗る — 単価を記録する\n"
        "     ときは必ず「何がそのバイトを作ったか」を併記すること)"
    )
    print(
        "    (unload と違い evict はペーシングを通らない = この値がそのまま\n"
        "     呼び出しスレッドの停止時間。1 frame @60fps = 16.7 ms)",
        flush=True,
    )


def core_footprint() -> None:
    """spec の **core 常駐** 表を反転後に再実測する (``--core``)。

    docs/superpowers/specs/2026-07-24-deferred-column-expansion-design.md の
    到達目標 (``core 590 MB -> ~310 MB`` / ``USS +281 MiB -> +15 MiB``) は
    **Qt を一切構築しないヘッドレス core** で測った 4 段の表:

        baseline 87 MB / Session.load 後 471 MB / signal_map() 後 532 MB /
        group_signals() 後 590 MB

    下の GUI 計測 (``main()``) はチャンネルブラウザの列名タプル等 GUI 側の残渣を
    含むので、その数値を core の 590 MB と並べると別物の比較になる。到達判定を
    同じ土俵で行うためにこの段だけを別プロセスで測る (``--core``)。
    """
    from valisync.core.session import Session

    if not TARGET.exists():
        print(f"MISSING: {TARGET} (run scripts/generate_demo_mf4.py --profile hils)")
        raise SystemExit(1)

    gc.collect()
    base_rss, base_uss = rss_mb(), uss_mb()

    session = Session()
    t0 = time.perf_counter()
    outcome = session.load(TARGET)
    load_wall = time.perf_counter() - t0
    key = outcome.key
    gc.collect()
    s1_rss, s1_uss = rss_mb(), uss_mb()

    smap = session.signal_map()
    n_keys = len(smap)  # 列挙は物理キーのみ (非対称 Mapping・鋳造しない)
    gc.collect()
    s2_rss, s2_uss = rss_mb(), uss_mb()

    sigs = session.group_signals(key)
    n_physical = len(sigs)
    n_columns = session.total_column_count(key)
    mgr = session._groups
    n_records = len(mgr.column_records(key))
    gc.collect()
    s3_rss, s3_uss = rss_mb(), uss_mb()

    print("\n=== CORE resident (headless, no Qt) -- spec の 4 段表と同じ土俵 ===")
    print(f"  target={TARGET.name}  load wall={load_wall:.2f} s")
    print(f"  physical Signals   = {n_physical:,}   (eager baseline 264,004)")
    print(f"  columns            = {n_columns:,}")
    print(f"  column_records     = {n_records:,}   (= physical, 1:1)")
    print(f"  signal_map keys    = {n_keys:,}   (physical only, by contract)")
    print(f"  mint_count         = {mgr.mint_count}   (after load: must be 0)")
    print(f"  baseline               = {base_rss:,.0f} MB RSS / {base_uss:,.0f} MB USS")
    print(
        f"  + Session.load         = {s1_rss:,.0f} MB RSS / {s1_uss:,.0f} MB USS "
        f"(+{s1_rss - base_rss:,.0f} / +{s1_uss - base_uss:,.0f})"
    )
    print(
        f"  + signal_map()         = {s2_rss:,.0f} MB RSS / {s2_uss:,.0f} MB USS "
        f"(+{s2_rss - s1_rss:,.0f} / +{s2_uss - s1_uss:,.0f})"
    )
    print(
        f"  + group_signals()      = {s3_rss:,.0f} MB RSS / {s3_uss:,.0f} MB USS "
        f"(+{s3_rss - s2_rss:,.0f} / +{s3_uss - s2_uss:,.0f})"
    )
    # M5: E-4a が E-3 の獲得を削っていないことを同じ実行で読めるようにする。
    res_verdict = "OK" if s3_rss <= CORE_RESIDENT_LIMIT_MB else "OVER"
    uss_verdict = "OK" if s3_uss - base_uss <= CORE_USS_DELTA_LIMIT_MB else "OVER"
    load_verdict = "OK" if load_wall <= CORE_LOAD_LIMIT_S else "OVER"
    print(
        f"  CORE RESIDENT (final)  = {s3_rss:,.0f} MB RSS  [{res_verdict}]  "
        f"[eager 590 -> E-3 297 -> limit {CORE_RESIDENT_LIMIT_MB:,.0f} MB]"
    )
    print(
        f"  CORE USS delta         = +{s3_uss - base_uss:,.0f} MB  [{uss_verdict}]  "
        f"[eager +281 MiB -> E-3 +15 -> limit +{CORE_USS_DELTA_LIMIT_MB:,.0f} MB]"
        "  **primary metric**"
    )
    print(
        f"  CORE load wall         = {load_wall:.2f} s  [{load_verdict}]   "
        f"(E-3 1.43 s -> limit {CORE_LOAD_LIMIT_S:.1f} s)",
        flush=True,
    )
    # 列挙の戻り値を先に落とす: 抱えたままだと以下の USS がキャッシュ以外の分だけ
    # 底上げされ、飽和天井の判定が甘くなる。
    del sigs, smap
    gc.collect()

    # ── E-4a: 列読みの対話コストとキャッシュ会計 (Qt を構築しない同じ土俵) ──
    report_latency(
        [
            column_read_latency(session, key, cold_every_column=False),
            column_read_latency(session, key, cold_every_column=True),
        ]
    )
    report_cache(cache_saturation(session, key))

    cache = _channel_cache(session)
    hid = id(_handle_of(session, key))
    # 飽和段は evict の標本 (実配列 20 本) を取る過程でこのファイルのエントリを
    # **全部**追い出す。T4 の回収は「回収する物がある」ことが前提なので、1 本だけ
    # 読み直して母数を作る。
    _rewarm_one_channel(session, key)
    held_before = _handle_cache_bytes(cache, hid)
    # 母数ゼロで [OK] を刷らせない: 呼び出し順が変わって空のまま来ると
    # "0.0 -> 0.0 [OK]" という**恒真な合格**になる (このタスクが塞いでいる失敗
    # モードそのもの・T5 レビュー Minor)。
    assert held_before > 0, (
        "回収の観測対象がゼロ件 — キャッシュが空の状態で remove_group を測っている "
        "(再ウォームが効いていない)"
    )
    process_before = cache.bytes_held
    session.remove_group(
        key
    )  # ハンドルを閉じる (計測プロセスがファイルを掴んだまま終わらない)
    leak = "OK" if _handle_cache_bytes(cache, hid) == 0 else "LEAK"
    print(
        f"\n  cache bytes at remove_group = このファイル {held_before / MB:,.1f} -> "
        f"{_handle_cache_bytes(cache, hid) / MB:,.1f} MB   [{leak}]   "
        f"(プロセス全体 {process_before / MB:,.1f} -> {cache.bytes_held / MB:,.1f} MB)"
    )
    print(
        "    (T4: remove_group は close の**前**に回収して teardown へ渡す。残ると\n"
        "     閉じたハンドルのデコード済み配列がプロセス寿命まで居座る)",
        flush=True,
    )


# ─── E-4b: エクスポート書き込み経路の実測 (T-M・spec §11) ─────────────────────


def export_estimate_check(session: Any, keys: list[str], out: Path) -> dict[str, float]:
    """B2 の係数を **読み項と書き項に分けて** 検定する (spec §7.4)。

    分けて測るのが要点 (I10): 合算だけ合っていても、読み支配ケース (カーソル A-B x
    全列) と書き支配ケース (全期間 x 全列) のどちらかが桁で外れていることがある。

    **単価を記録するときは主語 (何がそのバイト/秒を作ったか) を必ず併記する** —
    この系列は同じ罠を 3 度踏んでいる (T4 の未タッチページ 17-25 倍 / 増分B の
    3.0-4.8 us/signal 対 実 8-27 us / channel_cache の warm-allocator 2 倍)。
    """
    from valisync.core.export.csv_exporter import (
        CsvExporter,
        CsvExportOptions,
        ExportRequest,
    )
    from valisync.core.export.estimate import estimate_export

    # prod_demo は複数レートの混在 (master が同一でないチャンネルを含む) — 素の
    # CsvExportOptions() は `_require_shared_timeline` に即座に拒否される
    # (較正の初回実行で実測済み: ValueError「選択した信号が同一の時間軸を共有して
    # いません」)。実 GUI (ExportCsvDialog) の統合タイムラインチェックボックスは
    # **既定 checked=True** なので、これが実ユーザーが踏む経路と一致する唯一の
    # 選択。est 側の数字には影響しない (`estimate_export` は use_unified_timeline
    # を見ない契約 — 単一 master の点 (b) では unified の有無で union が不変)。
    options = CsvExportOptions(use_unified_timeline=True)
    t0 = time.perf_counter()
    est = estimate_export(session, keys, options)
    estimate_wall = time.perf_counter() - t0

    request = ExportRequest(
        keys=tuple(keys), output_path=out, options=options, header_resolver=list
    )
    marks: list[tuple[int, float]] = []
    t1 = time.perf_counter()
    CsvExporter().export(
        request,
        session.export_resolver(),
        progress=lambda d, t: marks.append((d, time.perf_counter())),
    )
    wall = time.perf_counter() - t1
    actual_bytes = out.stat().st_size
    # 最初のブロックが終わるまでが「読み支配」区間の代理指標。
    first_block_s = (marks[0][1] - t1) if marks else wall
    return {
        "estimate_wall_s": estimate_wall,
        "est_rows": est.rows,
        "est_columns": est.columns,
        "est_empty_ratio": est.empty_ratio,
        "est_bytes": est.est_bytes,
        "actual_bytes": actual_bytes,
        "bytes_ratio": actual_bytes / max(1, est.est_bytes),
        "est_read_s": est.est_read_s,
        "est_write_s": est.est_write_s,
        "actual_wall_s": wall,
        "actual_first_block_s": first_block_s,
        "time_ratio": wall / max(1e-9, est.est_read_s + est.est_write_s),
    }


def export_full_run(
    session: Any, keys: list[str], out: Path, uss_limit_mb: float
) -> None:
    """G4: prod 全列エクスポートが OOM せず完走し、**中身が正しい**ことまで見る。

    「完走した」だけでは空のファイルでも緑になる (spec §6 G4)。行数 = union 長・
    列数 = keys 長・ランダム 100 セルの独立オラクル照合を併置する。

    ``uss_limit_mb`` は **判定走行とは別の走行から供給する** (同一走行から閾値を得る
    循環の禁止・G4)。呼び出し側 (main) が --uss-limit で受け取り、既定値を持たない。
    """
    import random

    from valisync.core.export.csv_exporter import (
        CsvExporter,
        CsvExportOptions,
        ExportRequest,
    )
    from valisync.core.export.timeline import union_timeline

    # ゼロ件で「完走した」と刷る黙った合格を禁止する (E-3 T9 の穴と同型)。
    assert len(keys) >= 1000, f"測定対象が {len(keys)} 列しかない — 全列走行ではない"

    peak = [uss_mb()]

    def progress(done: int, total: int) -> None:
        peak[0] = max(peak[0], uss_mb())

    request = ExportRequest(
        keys=tuple(keys),
        output_path=out,
        # 実 GUI 既定 (統合タイムライン checked=True) と揃える — export_estimate_check
        # の WHY コメント参照。全列 (prod_demo は複数レート混在) では必須。
        options=CsvExportOptions(use_unified_timeline=True),
        header_resolver=list,
    )
    t0 = time.perf_counter()
    CsvExporter().export(request, session.export_resolver(), progress=progress)
    wall = time.perf_counter() - t0

    # --- 内容検証 (「完走した」だけでは空ファイルでも緑) ---------------------
    masters = _distinct_masters(session, keys)
    union = union_timeline(masters)
    n_union = int(union.size)
    rng = random.Random(20260801)  # 固定 seed: 落ちたセルを再現できるようにする
    samples = [
        (rng.randrange(n_union), rng.randrange(1, len(keys) + 1)) for _ in range(100)
    ]
    header, n_rows, picked = _scan_output(out, {r for r, _c in samples})
    assert n_rows == n_union, (n_rows, n_union)
    assert len(header) == len(keys) + 1, (len(header), len(keys) + 1)

    for r, c in samples:
        got = picked[r][c]
        want = _oracle_cell(session, keys[c - 1], float(union[r]))
        assert got == want, (
            f"row={r} col={c} key={keys[c - 1]} got={got!r} want={want!r}"
        )

    print(
        f"G4 OK  columns={len(keys):,} rows={n_rows:,} "
        f"bytes={out.stat().st_size:,} wall={wall:.1f}s USS_peak={peak[0]:,.0f}MB "
        f"(limit {uss_limit_mb:,.0f}MB — 別走行から供給)",
        flush=True,
    )
    assert peak[0] <= uss_limit_mb, (peak[0], uss_limit_mb)


def _oracle_cell(session: Any, column_key: str, t: float) -> str:
    """列 *column_key* の時刻 *t* におけるセルを **名前引き経路** で独立に作る。

    E-3 以前の読み経路 (mdf.select + dict(_flatten(...))) をそのまま使うので、
    E-4a の位置パスにも E-4b のブロック機構にも依存しない。時刻が無い列は空セル
    (完全一致セマンティクス — tolerance を入れると照合が甘くなる)。

    **非有限値も空セル** (Task 1 の是正 1・1')。ここを ``repr(float(...))`` の
    ままにすると、demo データに NaN/±inf が 1 つでも乗った瞬間に
    ``'nan' != ''`` の**誤 RED** が出る (production が正しいのにゲートが落ちる)。
    """
    import math

    import numpy as np

    from valisync.core.loaders.mdf_loader import _flatten

    channel = session.channel_key_of(column_key)
    assert channel is not None, column_key
    group_key, _sep, display = channel.partition("::")
    record = session._groups.column_records(group_key)[display]
    handle = session._groups.group(group_key).handle
    with handle.lock:
        asig = handle.mdf.select(
            [(record.raw_base_name, record.group_index, record.channel_index)],
            raw=False,
            ignore_value2text_conversions=True,
            copy_master=False,
        )[0]
    leaf = column_key.split("::", 1)[1][len(display) :]
    columns = dict(_flatten(record.raw_base_name, asig.samples))
    values = columns[f"{record.raw_base_name}{leaf}"]
    ts = np.asarray(asig.timestamps)
    idx = int(np.searchsorted(ts, t, side="left"))
    if idx >= ts.size or ts[idx] != t:
        return ""  # このレートには当該時刻のサンプルが無い = 空セル
    value = float(values[idx])
    if not math.isfinite(value):
        return ""  # 非有限は欠測と同じ空セル (Task 1 の是正 1/1')
    return repr(value)


def export_range_residency(session: Any, keys: list[str], out: Path) -> tuple[int, int]:
    """G5: カーソル A-B (1 行) エクスポート後の鋳造列常駐を **weakref で** 数える。

    ``resolved_keys()`` も ``bytes_held`` も使わない (spec §10): 前者は LRU の帳簿で
    export 専用 resolve に構造的に盲目で、後者は pin されない列を数えない。実装自身の
    カウンタに頼らない独立オラクルが要る (E-4a の教訓)。
    """
    import gc
    import weakref

    from valisync.core.export.csv_exporter import (
        CsvExporter,
        CsvExportOptions,
        ExportRequest,
    )

    alive: weakref.WeakSet = weakref.WeakSet()
    base = session.export_resolver()
    minted_keys: set[str] = set()

    def watched(key: str):  # type: ignore[no-untyped-def]
        sig = base(key)
        # T11 prod 実測で発見: スカラー (LD-14 展開不要) チャンネルの
        # resolve_transient は「既に帳簿に在る列はそのまま返す」経路
        # (signal_group_manager.py) を通り、ロード時点から**恒久生存**する
        # 物理チャンネル容器 Signal をそのまま返す (鋳造しない・transient_mint_count
        # も動かない)。これはエクスポートが作った残留ではなく、ファイルを開いた瞬間
        # から常に「生きている」— 未選別の weakref オラクルは prod_demo (scalar
        # チャンネル 4,004 本) で必ず alive>=4,004 の床が乗り、G5 が測ろうとして
        # いる「ブロック終端の参照解放」を実測不能にする (実測: 未修正のまま judge
        # 走行で alive=4,004・block_cols=512 に対し常に OVER)。G5 が見たいのは
        # **LD-14 展開で鋳造された列** (`_selector` を持つ) の残留だけなので、
        # 恒久容器 (`_selector is None`) は対象から除く。
        if getattr(sig._values_source, "_selector", None) is not None:
            alive.add(sig)
            # M3 是正 (Task 11 レビュー): 「鋳造された列」を **キー単位の集合**
            # で数える (呼び出し回数ではない)。恒久容器を返すだけの scalar
            # キー (4,004 本ぶん) は鋳造していないので `len(keys)`
            # (=330,004・全選択列数) を "minted" と呼ぶのは誤称だった。
            # **単純なカウンタでは二重計上する**: `CsvExporter.export` は
            # `scan_masters` (前走査・master だけ見る) と実書き込みの 2 段で
            # 同じキーを 2 回 `resolve` するため、`resolve_transient` は
            # 呼び出しごとに毎回**再鋳造**する (`_resolved_by_key` へ登録
            # しない設計・E-4b MG-1) — カウンタ実装で実測したところ
            # 652,000 (= 326,000 の厳密 2 倍) になり、二重計上を機械的に
            # 実証した (`.superpowers/sdd/task-11-report.md` 修正ラウンド)。
            minted_keys.add(key)
        return sig

    # 1 行だけ出す範囲 (spec §1 の「カーソル A-B で 1 行 = 6.523 s / 114.5 MiB 常駐」
    # の再現形)。t0 を閉区間の両端に置くので出力は 1 行になる。
    masters = _distinct_masters(session, keys)
    t0 = float(masters[0][0])
    # unified=True: 全列 (複数レート混在) を渡すと `_require_shared_timeline` は
    # union の切り出し (row_range) より前に生 master を比較するため、範囲が 1 行に
    # 絞られていても素の CsvExportOptions() では拒否される (export_estimate_check
    # の WHY コメント参照)。
    options = CsvExportOptions(time_start=t0, time_end=t0, use_unified_timeline=True)
    CsvExporter().export(ExportRequest(tuple(keys), out, options, list), watched)
    gc.collect()
    # alive に残るのは「まだ誰かが参照している鋳造列」。block_cols + ε を超えたら
    # ブロック終端の参照解放が効いていない (G5 の判定は呼び出し側 main が行う)。
    return len(minted_keys), len(alive)


def _distinct_masters(session: Any, keys: list[str]) -> list[Any]:
    """列キー集合が触る master を identity dedup で集める (**値を読まない**)。"""
    seen: dict[int, Any] = {}
    for key in keys:
        channel = session.channel_key_of(key)
        if channel is None:
            continue
        master = session.channel_master(channel)
        if master is not None:
            seen.setdefault(id(master), master)
    return list(seen.values())


def _scan_output(
    path: Path, wanted: set[int]
) -> tuple[list[str], int, dict[int, list[str]]]:
    """~10 GB の CSV を **1 パスのストリームで** 走査し、ヘッダ・行数・指定行だけ返す。

    行を全部リストへ溜めると計測器自身が 10 GB を抱え、測ろうとしているピークを
    自分で作る (E-4a T5 の「対照が測定対象を汚す」と同型の罠)。保持するのは
    ``wanted`` の 100 行だけ。
    """
    picked: dict[int, list[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        header = f.readline().rstrip("\n").split(",")
        count = 0
        for line in f:
            if not line.strip():
                continue
            if count in wanted:
                picked[count] = line.rstrip("\n").split(",")
            count += 1
    return header, count, picked


def _export_all_keys(session: Any, key: str) -> list[str]:
    """全列のキー (この 1 ファイルの全物理チャンネル分。**名前だけで作る = 鋳造しない**)。

    ``ExportCsvDialog._select_all`` (C-b) と同じ規約 — 列挙は ColumnSpec 由来の
    名前で行い、``resolve()`` は実際に値が要るときまで呼ばない。
    """
    out: list[str] = []
    for sig in session.group_signals(key):
        out.extend(_column_keys_of(session, key, _orig(sig.name)))
    return out


class UssPeakSampler(threading.Thread):
    """USS ピークを粗い周期でサンプリングする背景スレッド (calibrate 走行専用)。

    ``PeakSampler`` (RSS・20ms 周期) と違い、USS の読み出しは working set を歩く
    ぶん高価 (module docstring 参照)。20-40 分級の全列書き出し中に張り続けるので、
    周期を秒オーダーへ粗くして計測対象そのものへの負荷を無視できる水準に保つ
    (n_units ~648 の progress コールバックそのものへ 20ms 周期のスレッドを重ねると
    サンプリング自体が観測対象を歪めかねない)。
    """

    def __init__(self, interval_s: float = 2.0) -> None:
        super().__init__(daemon=True)
        self.peak = uss_mb()
        self._interval = interval_s
        self._running = True

    def run(self) -> None:
        while self._running:
            current = uss_mb()
            if current > self.peak:
                self.peak = current
            time.sleep(self._interval)

    def stop(self) -> None:
        self._running = False


def read_class_calibration(
    session: Any, key: str, cls: str, sample_n: int, seed: int = 0
) -> None:
    """C1 是正 (レビュー): cold select 単価をチャンネルクラス別 (scalar/wide) に測る。

    旧 ``_READ_S_PER_COLD_CHANNEL`` (0.316 s/channel) は「幅 1,100 の最広チャンネル
    1 本」(``_widest_channel``) の cold select を **全チャンネル (4,004 scalar +
    320 wide) に一律適用**しており、scalar 側で ~21 倍の過大見積を生んでいた —
    scalar と wide は物理チャンネルの構造 (asammdf が 1 回の decode で読む単位) が
    根本的に違う (spike §9-4: prod scalar 0.67ms 対 prod wide 338.2ms・~480 倍差)。
    ここでは ``_select_samples`` (E-4a T5 が確立した測定手法 = ``handle.mdf.select``・
    ``copy_master=False``・チャンネルキャッシュを経由しない直接呼び出し) を同じ形で
    再現し、クラス別の単価を測り直す。

    **fresh process が必須**: 呼び出し側 CLI (``--read-class scalar`` /
    ``--read-class wide``) を**別プロセスで 2 回**起動して測る。同一プロセス内で
    両クラスを連続測定すると、先に測ったクラスの OS ページキャッシュ/asammdf
    内部バッファの温まりが後続クラスの計測へ漏れ、フェアな比較にならない
    (このシリーズが計測の鉄則で繰り返し踏んだ罠と同型)。
    """
    import random

    from valisync.core.loaders.column_names import leaf_count

    records = session._groups.column_records(key)
    assert records, f"{key} に列レコードが無い (ロード失敗?)"
    want_wide = cls == "wide"
    pool = [
        (display, record)
        for display, record in records.items()
        if (leaf_count(record.spec) > 1) == want_wide
    ]
    assert pool, f"クラス {cls} のチャンネルが 0 本 (records={len(records)})"
    handle = _handle_of(session, key)
    rng = random.Random(seed)
    sample = rng.sample(pool, min(sample_n, len(pool)))
    widths = [leaf_count(record.spec) for _display, record in sample]
    times: list[float] = []
    for _display, record in sample:
        t0 = time.perf_counter()
        _select_samples(
            handle, record.raw_base_name, record.group_index, record.channel_index
        )
        times.append(time.perf_counter() - t0)
    times.sort()
    n = len(times)
    mean = sum(times) / n
    print(
        f"READ_CLASS class={cls} n={n}/{len(pool)} mean_ms={mean * 1000:.4f} "
        f"median_ms={times[n // 2] * 1000:.4f} min_ms={times[0] * 1000:.4f} "
        f"max_ms={times[-1] * 1000:.4f} mean_leaf_count={sum(widths) / n:.1f} "
        "subject=prod_demo cold handle.mdf.select copy_master=False "
        "ignore_value2text_conversions=True (E-4a チャンネルキャッシュ非経由)",
        flush=True,
    )


def export_main() -> None:
    """``--export`` 段のディスパッチャ (spec §11・T-M)。``--core`` と同型の early return。

    子コマンド:
      ``--calibrate``       : 較正走行。書き項 2 項モデル (est.py の BASE/VALUE) は
                               1 点では 2 係数を決められない (T8 再レビュー) ので、
                               空セル率が異なる 2 点 (全列 ~66% / 単一 master 部分
                               集合 ~0%) で ``export_estimate_check`` を回す。点 (a)
                               (全列) の 1 回の書き出しに USS ピークサンプラーを
                               重ねて P_A も同時に得る (全列書き出しを 2 度払わない)。
      ``--uss-limit <MB>``  : 判定走行。G4 (全列完走+内容照合) を **較正走行とは
                               別の走行** として実行し (同一走行から閾値を得る循環
                               の禁止・G4)、続けて G5 (範囲エクスポート後の常駐) を
                               同じプロセス内で測る。
    """
    from valisync.core.export.csv_exporter import block_columns
    from valisync.core.session import Session

    if not TARGET.exists():
        print(f"MISSING: {TARGET} (run scripts/generate_demo_mf4.py --profile hils)")
        raise SystemExit(1)

    scratch = TARGET.parent / "export_scratch"  # demo_data 配下 = gitignore 済み
    scratch.mkdir(exist_ok=True)

    calibrate = "--calibrate" in sys.argv
    uss_limit: float | None = None
    if "--uss-limit" in sys.argv:
        idx = sys.argv.index("--uss-limit")
        uss_limit = float(sys.argv[idx + 1])
    read_class: str | None = None
    if "--read-class" in sys.argv:
        idx = sys.argv.index("--read-class")
        read_class = sys.argv[idx + 1]
        assert read_class in ("scalar", "wide"), read_class
    sample_n = 200
    if "--sample-n" in sys.argv:
        idx = sys.argv.index("--sample-n")
        sample_n = int(sys.argv[idx + 1])

    print(f"loading {TARGET.name} ...", flush=True)
    session = Session()
    t0 = time.perf_counter()
    outcome = session.load(TARGET)
    print(f"  loaded in {time.perf_counter() - t0:.2f}s", flush=True)
    key = outcome.key

    if read_class is not None:
        # C1 是正の再測定専用パス — 全列キーの列挙 (330,004 本の文字列生成) は
        # このパスでは不要なので飛ばす (計測対象そのものへ余計な前処理コストを
        # 足さない)。
        read_class_calibration(session, key, read_class, sample_n)
        return

    all_keys = _export_all_keys(session, key)
    print(f"  columns (all, 全物理チャンネル) = {len(all_keys):,}", flush=True)

    if calibrate:
        display, width = _widest_channel(session, key)
        subset_keys = _column_keys_of(session, key, display)
        print(
            f"\n=== CALIBRATE point (b): 単一 master 部分集合 "
            f"(channel={display}, cols={width}, 空セル率 ~0%) ===",
            flush=True,
        )
        res_b = export_estimate_check(session, subset_keys, scratch / "calib_b.csv")
        for k, v in res_b.items():
            print(f"  {k} = {v}")

        print(
            "\n=== CALIBRATE point (a): 全列 (空セル率 高) "
            "+ USS ピーク (P_A) 同時観測 ===",
            flush=True,
        )
        sampler = UssPeakSampler()
        sampler.start()
        res_a = export_estimate_check(session, all_keys, scratch / "calib_a.csv")
        sampler.stop()
        sampler.join(timeout=5.0)
        for k, v in res_a.items():
            print(f"  {k} = {v}")
        print(f"  USS_peak(P_A) = {sampler.peak:,.0f} MB", flush=True)
        return

    if uss_limit is None:
        print(
            "ERROR: --uss-limit <MB> が必要です "
            "(判定走行は較正走行 --calibrate の P_A から別途供給する)"
        )
        raise SystemExit(2)

    print(
        f"\n=== JUDGE G4: 全列完走 + 内容照合 (uss_limit={uss_limit:,.0f} MB) ===",
        flush=True,
    )
    export_full_run(session, all_keys, scratch / "judge_full.csv", uss_limit)

    print("\n=== JUDGE G5: カーソル A-B (1 行) 常駐 ===", flush=True)
    minted, alive = export_range_residency(
        session, all_keys, scratch / "judge_range.csv"
    )
    masters = _distinct_masters(session, all_keys)
    max_master_len = max((len(m) for m in masters), default=0)
    budget = _channel_cache(session).available_bytes
    bc = block_columns(1, max_master_len, budget)
    epsilon = 8  # ブロック終端の参照解放に僅かな遅延があっても許容する緩衝
    verdict = "OK" if alive <= bc + epsilon else "OVER"
    print(
        f"G5 residual columns = {alive} (<= block_cols={bc}+eps{epsilon})  "
        f"minted={minted}  [{verdict}]",
        flush=True,
    )
    assert alive <= bc + epsilon, (alive, bc, epsilon)


def main() -> None:
    if "--core" in sys.argv:
        core_footprint()
        return
    if "--export" in sys.argv:
        export_main()
        return

    # QSettings isolation (never touch the real registry) — must happen before
    # build_main_window reads any setting.
    from valisync.gui.views import main_window as mw

    mw._ORG = "ValiSync-Measure"
    mw._APP = "ValiSync-Measure"

    from PySide6.QtWidgets import QApplication

    from valisync.gui.app import build_main_window

    if not TARGET.exists():
        print(f"MISSING: {TARGET} (run scripts/generate_demo_mf4.py --profile hils)")
        raise SystemExit(1)

    # 増分B: ティック計測はサービス構築より前に仕掛ける (bound method 捕捉のため)。
    tick_log = instrument_teardown_ticks()

    gc.collect()
    base = rss_mb()

    app = QApplication.instance() or QApplication([])
    win = build_main_window()
    win._tick_log = tick_log
    win.resize(1400, 900)
    win.show()
    app.processEvents()
    after_win = rss_mb()
    after_win_uss = uss_mb()

    # E-3: 1024 ガード (展開確認モーダル) は退役済み — 差し替える confirmer は無く、
    # 全チャンネルが無条件にロードされる (そもそも列は展開されない)。

    disk_mb = TARGET.stat().st_size / MB
    print(
        f"baseline={base:,.0f}MB  after window+show={after_win:,.0f}MB "
        f"(USS {after_win_uss:,.0f}MB)  target={TARGET.name} ({disk_mb:,.0f}MB on disk)",
        flush=True,
    )

    r1 = load_one_more(app, win, expect_files=1)
    print(
        f"[1 file ] physical={r1.physical:,} columns={r1.columns:,}  "
        f"load_wall={r1.load_wall_s:.2f}s",
        flush=True,
    )
    # E-2: the browser-side residue, measured on the 1-file state (the objects
    # are dropped again before the 2nd load so the 2-file numbers stay
    # comparable with previous runs).
    browser_residue(win, win.app_vm.loaded_file_keys[0])

    r2 = load_one_more(app, win, expect_files=2)
    print(
        f"[2 files] physical(2nd)={r2.physical:,} columns={r2.columns:,}  "
        f"load_wall={r2.load_wall_s:.2f}s",
        flush=True,
    )

    print(
        "\n=== REAL GUI process memory (prod_demo.mf4, real load path) ===", flush=True
    )
    print(f"  Qt+window baseline   = {after_win:,.0f} MB (USS {after_win_uss:,.0f} MB)")
    print("  --- 1 file ---", flush=True)
    print(f"  PEAK during load     = {r1.peak_mb:,.0f} MB", flush=True)
    print(f"  steady RSS (settled) = {r1.steady_mb:,.0f} MB", flush=True)
    print(
        f"  steady USS [PRIMARY] = {r1.steady_uss_mb:,.0f} MB  "
        f"(vs baseline +{r1.steady_uss_mb - after_win_uss:,.0f} MB)",
        flush=True,
    )
    print(f"  load wall            = {r1.load_wall_s:.2f} s", flush=True)
    print("  --- 2 files (compare) ---", flush=True)
    print(f"  PEAK during 2nd load = {r2.peak_mb:,.0f} MB", flush=True)
    print(f"  steady RSS (settled) = {r2.steady_mb:,.0f} MB", flush=True)
    print(
        f"  steady USS [PRIMARY] = {r2.steady_uss_mb:,.0f} MB  "
        f"(vs baseline +{r2.steady_uss_mb - after_win_uss:,.0f} MB)",
        flush=True,
    )
    print(f"  2nd load wall        = {r2.load_wall_s:.2f} s", flush=True)
    print(
        "\n  OLD eager baseline (pre-lazy, 1 file): "
        "steady 1,201 MB / peak 1,369 MB / load 13.1s",
        flush=True,
    )
    print(
        "  pre-E-2 baseline   (1 file): steady   868 MB / peak 1,366 MB / load 13.1s",
        flush=True,
    )
    print(
        "  E-3 target (HEADLESS-CORE scope -- run with --core to compare on the\n"
        "  same footing; the GUI USS delta above is a different, larger scope):\n"
        "    core 590 -> ~310 MB / objects 264,004 -> 4,324 / USS +281 MiB -> +15 MiB",
        flush=True,
    )

    keys = list(win.app_vm.loaded_file_keys)

    # E-4a 受け入れ: 広幅チャンネルの隣接 5 列の実時間 (温 / 列ごと冷の対照つき) と
    # キャッシュ飽和後の USS。ドレイン計測より前に置く (ドレインはグループを消すため)。
    session = win.app_vm.session
    report_latency(
        [
            column_read_latency(session, keys[0], cold_every_column=False),
            column_read_latency(session, keys[0], cold_every_column=True),
        ]
    )
    report_cache(cache_saturation(session, keys[0]))

    # ── 増分B: unload -> teardown ドレインの最大ティック時間 (2 入力必須) ──
    #
    # (a) だけでは足りない: ロードは値を展開しないので (増分A の遅延契約)、
    # (a) は「全信号が未展開シェル」= 1 信号 1.6us regime しか踏まない。展開済み
    # 信号は 3 倍重く、かつ**バイト予算と信号数予算を両方満たしたまま**デッドラインを
    # 超えうる — 第 3 軸 (経過時間) が存在する理由そのものなので、両方測る。
    drains = [
        drain_after_unload(app, win, keys[1], "(a) loaded only (all columns lazy)")
    ]
    _pump(app, 0.5)

    materialize_leaves(win, keys[0], MATERIALIZE_TARGET)
    drains.append(
        drain_after_unload(
            app,
            win,
            keys[0],
            f"(b) >= {MATERIALIZE_TARGET:,} columns minted+materialized (+range stats)",
        )
    )
    report_drain(drains)

    # Hold the window briefly for on-screen / Task Manager confirmation.
    _pump(app, 3.0)
    win.close()


if __name__ == "__main__":
    main()
