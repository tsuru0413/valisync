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


# One alphanumeric keystroke, deliberately the WORST CASE for prod_demo: 'o'
# matches 264,001 of the 264,004 columns across 4,261 of the 4,264 rows (the
# generated channels are Prod<n>_<nnnn>). A selective letter would understate
# the residue -- 'a' for instance matches only 4,003 columns / 4,003 rows, so
# every surviving row would carry exactly one column and the memo would be at
# its smallest. The column-name scan itself walks every column either way, so
# only the retained result size varies -- which is precisely what the "no
# per-column name cache" claim is about.
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

    gc.collect()
    base = rss_mb()

    app = QApplication.instance() or QApplication([])
    win = build_main_window()
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

    # Hold the window briefly for on-screen / Task Manager confirmation.
    _pump(app, 3.0)
    win.close()


if __name__ == "__main__":
    main()
