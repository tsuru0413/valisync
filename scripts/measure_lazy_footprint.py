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

    # Hold the window briefly for on-screen / Task Manager confirmation.
    _pump(app, 3.0)
    win.close()


if __name__ == "__main__":
    main()
