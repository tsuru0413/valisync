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
    cache_mb_before: float = 0.0
    cache_mb_after: float = 0.0


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
            for tag, arr in (("prod", prod_arr), ("bulk", bulk_arr)):
                base = arr.base
                assert base is None or base.nbytes == arr.nbytes, (
                    f"{tag} 側が自分より大きい base を抱えている — 解放コストが違う",
                    arr.nbytes,
                    None if base is None else base.nbytes,
                )
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
        print(
            f"  cache bytes at unload   = {r.cache_mb_before:,.1f} -> "
            f"{r.cache_mb_after:,.1f} MB  (T4: close の前に回収して teardown へ渡す)"
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
# U3: キャッシュ合計の追加メモリ予算 (spec §5.1)。飽和後の USS 天井の判定に使う。
CACHE_BUDGET_MB = 256
# evict の同期解放時間を測るための合成エントリの handle id。実オブジェクトの id() は
# 0 にならないので、実ファイルのエントリと絶対に衝突しない。
_SYNTH_HANDLE_ID = 0
# M5: E-3 の獲得 (core 297 MB / USS +15 MB / load 1.43 s) の非回帰帯。
CORE_RESIDENT_LIMIT_MB = 310.0
CORE_USS_DELTA_LIMIT_MB = 20.0
CORE_LOAD_LIMIT_S = 1.6


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
    """グループの MdfHandle (キャッシュキー ``(id(handle), gi, ci)`` の第 1 成分)。"""
    return session.group_signals(key)[0]._values_source._handle


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
    ``cold_every_column=True``: 列ごとに冷たい = E-4a **以前**が構造的に踏んでいた
    経路。同一実行内の対照であり、これが無いと 380 ms に比較対象が無い (別マシンで
    測った 1,584 ms との A/B は環境差を吸えない)。
    """
    mgr = session._groups
    cache = _channel_cache(session)
    handle = _handle_of(session, key)
    hid = id(handle)

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
    label = "列ごとに冷 (E-4a 以前の経路・対照)"
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
            print(f"    column #{i}  {ms:,.0f} ms")
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
        "  reference (E-3 実測・キャッシュ無し): 309-327 ms/列・5 列 1,584 ms。\n"
        "  対照 (列ごとに冷) が cached 側と同程度なら、キャッシュが効いていないか\n"
        "  冷やす側が壊れている — どちらでも受け入れは成立しない。",
        flush=True,
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
    evict_ms: tuple[float, ...]
    evict_entry_mb: float


def evict_release_ms(
    cache: Any, entry_bytes: int, samples: int = 5
) -> tuple[float, ...]:
    """予算超の put が 1 エントリを追い出すときの**同期**解放時間 (ms)。

    LRU の evict は unload と違い TeardownService のペーシングを通らない (spec §5.7)
    ので、1 回の解放が呼び出しスレッドを止める時間そのものが受け入れ対象になる。
    合成配列で追加するのは、実チャンネルを読むと select のデコード時間が同じ窓に
    入って解放だけを取り出せないから。測っているのは **追い出される側** の解放で、
    ``np.ones`` で埋めるのは ``np.zeros``/``np.empty`` が OS の遅延マップで触られて
    いないページを返し、解放が実測より安く出るため。
    """
    import numpy as np

    out: list[float] = []
    for i in range(samples * 8):
        if len(out) >= samples:
            break
        arr = np.ones(max(1, entry_bytes), dtype=np.uint8)
        before = cache.evictions
        t0 = time.perf_counter()
        accepted = cache.put((_SYNTH_HANDLE_ID, 0, i), arr)
        elapsed = (time.perf_counter() - t0) * 1000.0
        del arr  # キャッシュを唯一の参照者にする (次の evict が実解放になる)
        if not accepted:
            break  # oversize: この予算では evict を起こせない
        if cache.evictions - before == 1:
            out.append(elapsed)
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
        evict_ms=evict_release_ms(cache, int(held / channels)),
        evict_entry_mb=held / channels / MB,
    )


def report_cache(sat: SaturationResult) -> None:
    delta_uss = sat.uss_mb - sat.base_uss_mb
    verdict = "OK" if delta_uss <= CACHE_BUDGET_MB else "OVER"
    held_verdict = "OK" if sat.bytes_held_mb <= CACHE_BUDGET_MB else "OVER"
    print("\n=== CHANNEL CACHE saturation (U3 予算 256 MB・spec §9 の USS 天井) ===")
    print(
        f"  channels read (widest first) = {sat.channels_read}  in {sat.wall_s:,.1f}s"
        f"   hits/misses = {sat.hits}/{sat.misses}"
    )
    print(
        f"  cache bytes_held = {sat.bytes_held_mb:,.1f} MB   [{held_verdict}]   "
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
        f"  USS delta [PRIMARY]    = +{delta_uss:,.0f} MB   [{verdict}]   "
        f"(目標 <= {CACHE_BUDGET_MB} MB)"
    )
    print(
        f"  LRU evict 同期解放 ({sat.evict_entry_mb:,.1f} MB/エントリ): "
        f"max {max(sat.evict_ms):,.2f} ms / "
        f"mean {sum(sat.evict_ms) / len(sat.evict_ms):,.2f} ms  (n={len(sat.evict_ms)})"
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
    held_before = cache.bytes_held
    session.remove_group(
        key
    )  # ハンドルを閉じる (計測プロセスがファイルを掴んだまま終わらない)
    leak = "OK" if cache.bytes_held == 0 else "LEAK"
    print(
        f"\n  cache bytes at remove_group = {held_before / MB:,.1f} -> "
        f"{cache.bytes_held / MB:,.1f} MB   [{leak}]"
    )
    print(
        "    (T4: remove_group は close の**前**に回収して teardown へ渡す。残ると\n"
        "     閉じたハンドルのデコード済み配列がプロセス寿命まで居座る)",
        flush=True,
    )


def main() -> None:
    if "--core" in sys.argv:
        core_footprint()
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
