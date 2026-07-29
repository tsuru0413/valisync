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
- Array expansion is skipped (the user's "arrays skipped" condition; keeps the
  dialog non-blocking) so nothing plotted stays lazy.
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
    load_wall_s: float
    signals: int


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
    reset / paint settle, then reads the settled RSS after a gc.
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
    keys = win.app_vm.loaded_file_keys  # type: ignore[attr-defined]
    signals = (
        len(win.app_vm.session.group_signals(keys[-1])) if keys else 0  # type: ignore[attr-defined]
    )
    return LoadResult(
        n_files=expect_files,
        peak_mb=sampler.peak,
        steady_mb=steady,
        load_wall_s=load_wall,
        signals=signals,
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
    n_columns = len(group_sigs)
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

    print("\n=== CHANNEL BROWSER residue (fresh VM+model over loaded session) ===")
    print(
        f"  columns={n_columns:,}  physical rows={n_rows:,}  model top rows={n_top:,}"
    )
    print(
        f"  prep column total={n_prep_columns:,}  signal_map keys={n_physical_keys:,}"
    )
    print(f"  1 loaded (settled)          = {s1:,.0f} MB")
    print(f"  2 + signal_map()            = {s2:,.0f} MB   (+{s2 - s1:,.1f} MB)")
    print(f"  3 + group_signals()         = {s3:,.0f} MB   (+{s3 - s2:,.1f} MB)")
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
    signals: int
    materialized: int
    sync_close_ms: float
    ticks: int
    max_tick_ms: float
    mean_tick_ms: float
    total_drain_s: float
    # (index, ms, signals, bytes, gc passes)
    top_ticks: tuple[tuple[int, float, int, int, int], ...]


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
    """Bring >= *target* leaves to the plotted+range-stats state; return the count.

    WHY not one ``sig.values`` per leaf (the literal production route): prod_demo's
    array channels carry 1,000 leaves each and ``LazyMdfValues.array()`` re-selects
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
    signals = session.group_signals(key)
    by_channel: dict[tuple[str, int, int], list[object]] = {}
    for sig in signals:
        src = sig._values_source
        by_channel.setdefault((src._name, src._gi, src._ci), []).append(sig)
    handle = signals[0]._values_source._handle

    # Equivalence control: one signal per branch goes through the REAL lazy read
    # and the bulk route must reproduce that array exactly. Without it the fast
    # route could silently retain a differently shaped/typed array and the drain
    # numbers would describe a state the app never reaches.
    probes = {}
    for sig in signals:
        branch = "scalar" if sig._values_source._selector is None else "ld14-leaf"
        probes.setdefault(branch, sig)
        if len(probes) == 2:
            break
    for branch, probe in probes.items():
        src = probe._values_source
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
        # production は _flatten の ascontiguousarray + _freeze でリーフごとに
        # 独立バッファを持つので、bulk 側にも同じ所有権を要求する。
        assert prod_arr.flags.owndata and bulk_arr.flags.owndata, (
            "リーフが base をエイリアスしている — 解放コストが production と違う"
        )
        print(
            f"  EQUIVALENCE ok [{branch}]: bulk route reproduces the lazy array "
            f"({prod_arr.dtype}, {prod_arr.shape}, {prod_arr.nbytes / 1024:,.0f} KiB)"
        )
        del table, bulk_arr, prod_arr

    done = 0
    t0 = time.perf_counter()
    for (name, gi, ci), sibs in by_channel.items():
        if done >= target:
            break
        table = _bulk_columns(name, _select_samples(handle, name, gi, ci))
        for sig in sibs:
            src = sig._values_source
            if src._cache is None:
                src._cache = table[None if src._selector is None else src._selector[-1]]
            sig.range_stat_index()  # production API: sorted_view + finite_view + RSI
            done += 1
        del table
    wall = time.perf_counter() - t0

    materialized = sum(1 for sig in signals if sig._values_source.is_materialized)
    print(
        f"  materialized {materialized:,} / {len(signals):,} leaves "
        f"(+range_stat_index) in {wall:,.1f}s"
    )
    # 参照は関数の return で全て落ちるが、下の集計と gc を正しい状態で行うため
    # 明示的に落とす (ドレインは唯一の参照者でなければならない)。
    del by_channel, probes
    gc.collect()
    return materialized


def drain_after_unload(app: object, win: object, key: str, label: str) -> DrainResult:
    """Unload *key* through the real VM path and time every teardown tick.

    The unload itself (``AppViewModel.unload_file``) is the same call the File
    Browser's confirmation dialog makes; the drain is then driven by pumping the
    real event loop, exactly as the running app does between user events.
    """
    session = win.app_vm.session  # type: ignore[attr-defined]
    signals = session.group_signals(key)
    n_signals = len(signals)
    materialized = sum(1 for sig in signals if sig._values_source.is_materialized)
    del signals  # holding the list would keep every array alive -> free ticks
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
    app.processEvents()  # type: ignore[attr-defined]

    durations = [t[0] for t in ticks]
    top = sorted(enumerate(ticks), key=lambda pair: pair[1][0], reverse=True)[:5]
    return DrainResult(
        label=label,
        signals=n_signals,
        materialized=materialized,
        sync_close_ms=sync_close * 1000.0,
        ticks=len(ticks),
        max_tick_ms=max(durations) * 1000.0 if durations else 0.0,
        mean_tick_ms=(sum(durations) / len(durations)) * 1000.0 if durations else 0.0,
        total_drain_s=total,
        top_ticks=tuple((i, s * 1000.0, n, b, g) for i, (s, n, b, g) in top),
    )


def report_drain(results: list[DrainResult]) -> None:
    from valisync.gui.workers.teardown_service import (
        _BYTE_BUDGET,
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
        print(f"  signals={r.signals:,}  materialized at unload={r.materialized:,}")
        print(f"  sync close (UI thread)  = {r.sync_close_ms:,.1f} ms")
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
    from valisync.gui.workers.teardown_service import _CLOCK_CHECK_EVERY

    print(
        "  NOTE: a deadline-bound tick can overrun by up to _CLOCK_CHECK_EVERY-1\n"
        f"        ({_CLOCK_CHECK_EVERY - 1}) signals' worth of work. Measured per-signal\n"
        "        free cost: 1.6 us (lazy shell) .. 8-27 us (materialized prod leaf\n"
        "        with sorted/finite view + range_stat_index), so the granularity is\n"
        "        sized against the 27 us case (31 * 27 us = 0.84 ms).\n"
        "  NOTE: the granularity is NOT what makes (b)'s single worst tick exceed the\n"
        "        band. Traced at granularity 1, exactly ONE free out of 264,004 costs\n"
        "        5.8 ms (rest <= 0.6 ms, p99 = 10 us, gc = 0) -- a heap-return stall.\n"
        "        Max tick is therefore floored at deadline + max single free = 13.8 ms\n"
        "        for ANY _CLOCK_CHECK_EVERY; only where it lands in a tick varies.\n"
        "  context: 1 frame @60fps = 16.7 ms; pre-pacing measured freeze = 649 ms"
    )


def main() -> None:
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

    # Skip every oversized array expansion (empty set = skip all).
    win._expansion_confirmer.confirm = lambda request: set()  # type: ignore[assignment]

    disk_mb = TARGET.stat().st_size / MB
    print(
        f"baseline={base:,.0f}MB  after window+show={after_win:,.0f}MB  "
        f"target={TARGET.name} ({disk_mb:,.0f}MB on disk)",
        flush=True,
    )

    r1 = load_one_more(app, win, expect_files=1)
    print(
        f"[1 file ] loaded signals={r1.signals:,}  load_wall={r1.load_wall_s:.2f}s",
        flush=True,
    )
    # E-2: the browser-side residue, measured on the 1-file state (the objects
    # are dropped again before the 2nd load so the 2-file numbers stay
    # comparable with previous runs).
    browser_residue(win, win.app_vm.loaded_file_keys[0])

    r2 = load_one_more(app, win, expect_files=2)
    print(
        f"[2 files] loaded signals(2nd)={r2.signals:,}  load_wall={r2.load_wall_s:.2f}s",
        flush=True,
    )

    print("\n=== REAL GUI process RSS (prod_demo.mf4, real load path) ===", flush=True)
    print(f"  Qt+window baseline   = {after_win:,.0f} MB", flush=True)
    print("  --- 1 file ---", flush=True)
    print(f"  PEAK during load     = {r1.peak_mb:,.0f} MB", flush=True)
    print(f"  steady (settled)     = {r1.steady_mb:,.0f} MB", flush=True)
    print(f"  load wall            = {r1.load_wall_s:.2f} s", flush=True)
    print("  --- 2 files (compare) ---", flush=True)
    print(f"  PEAK during 2nd load = {r2.peak_mb:,.0f} MB", flush=True)
    print(f"  steady (settled)     = {r2.steady_mb:,.0f} MB", flush=True)
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

    # ── 増分B: unload -> teardown ドレインの最大ティック時間 (2 入力必須) ──
    #
    # (a) だけでは足りない: ロードは値を展開しないので (増分A の遅延契約)、
    # (a) は「全信号が未展開シェル」= 1 信号 1.6us regime しか踏まない。展開済み
    # 信号は 3 倍重く、かつ**バイト予算と信号数予算を両方満たしたまま**デッドラインを
    # 超えうる — 第 3 軸 (経過時間) が存在する理由そのものなので、両方測る。
    keys = list(win.app_vm.loaded_file_keys)
    drains = [
        drain_after_unload(app, win, keys[1], "(a) loaded only (all leaves lazy)")
    ]
    _pump(app, 0.5)

    materialize_leaves(win, keys[0], MATERIALIZE_TARGET)
    drains.append(
        drain_after_unload(
            app,
            win,
            keys[0],
            f"(b) >= {MATERIALIZE_TARGET:,} leaves materialized (+range stats)",
        )
    )
    report_drain(drains)

    # Hold the window briefly for on-screen / Task Manager confirmation.
    _pump(app, 3.0)
    win.close()


if __name__ == "__main__":
    main()
