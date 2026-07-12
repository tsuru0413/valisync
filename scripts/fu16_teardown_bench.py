"""FU-16 teardown perf bench: prod スケールで close の同期時間と drain 中の UI 応答を実測.

実アプリ経路 (MainWindow._load_file オフスレッド + ExpansionConfirmer 全展開 -> 330,004ch)
で実 close を回し、(1) 同期 close 時間 (2) drain 中 heartbeat 最大 gap を測る。
内部 API・小データ・confirmer 未 patch は 6 秒を隠すため厳禁 (len(signals) を検証)。

honest-RED (現行同期 remove_group・TeardownService 未配線):
    reached_channels=330004 / sync_close_ms ~ 7000 / drain_* ~ 0
after (fix 後):
    sync_close_ms < 200 / drain_max_gap_ms < 150

Run:
    VALISYNC_PROD_MF4=demo_data/prod_demo.mf4 QT_QPA_PLATFORM=windows \
        uv run python scripts/fu16_teardown_bench.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

PROD = Path(os.environ.get("VALISYNC_PROD_MF4", "demo_data/prod_demo.mf4"))
EXPECTED_CHANNELS = 330_004


def _working_set_mb() -> float:
    """現在プロセスの working set (RSS) を MB で返す (診断用・Windows のみ)。"""
    try:
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE

        class _MEM(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        # 64bit で HANDLE が int へ切り詰められないよう restype/argtypes を明示。
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_MEM),
            wintypes.DWORD,
        ]
        counters = _MEM()
        counters.cb = ctypes.sizeof(_MEM)
        if psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return float("nan")


def main() -> None:
    if not PROD.exists():
        raise SystemExit(f"prod file not found: {PROD} (VALISYNC_PROD_MF4 を確認)")

    app = QApplication.instance() or QApplication(sys.argv)

    # QSettings 隔離 (実ユーザー設定/MRU を汚さない・tests/realgui/conftest 同型)。
    import valisync.gui.views.main_window as mw_mod
    import valisync.gui.views.recent_files as rf_mod

    mw_mod._ORG = rf_mod._ORG = "ValiSync-Bench"
    mw_mod._APP = rf_mod._APP = "fu16-teardown-bench"

    from valisync.core.session import Session
    from valisync.gui.app import build_main_window
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

    session = Session()
    app_vm = AppViewModel(session)
    window = build_main_window(app_vm)
    window.resize(1200, 800)
    window.show()

    # ExpansionConfirmer を全展開に差し替え (330k 到達に必須・小データ false-green 防止)。
    def _expand_all(request):
        return set(range(len(request.channels)))

    window._expansion_confirmer.confirm = _expand_all  # type: ignore[method-assign]

    # 実ロード経路 (オフスレッド LoadController 経由) でロード完了まで pump。
    print(f"loading {PROD} ... ws={_working_set_mb():.0f}MB", flush=True)
    window._load_file(str(PROD))
    deadline = time.perf_counter() + 300
    while not app_vm.loaded_file_keys:
        app.processEvents()
        if time.perf_counter() > deadline:
            raise TimeoutError("load did not complete within 300s")
        time.sleep(0.02)
    # session が namespaced view を張り終えるまで settle。
    while len(app_vm.session.signals()) == 0:
        app.processEvents()
        time.sleep(0.02)

    reached = len(app_vm.session.signals())
    if reached != EXPECTED_CHANNELS:
        raise SystemExit(
            f"reached {reached} ch (expected {EXPECTED_CHANNELS} -- expand-all 未達。"
            "小データ/未 patch で 6 秒フリーズを隠す false-green のため中止)"
        )
    print(
        f"loaded: reached_channels={reached} ws={_working_set_mb():.0f}MB", flush=True
    )

    # heartbeat: 20ms ごとに tick 間 gap を記録 (drain 中の UI 応答を実測)。
    gaps: list[float] = []
    last = [time.perf_counter()]
    hb = QTimer()
    hb.setInterval(20)

    def _beat() -> None:
        now = time.perf_counter()
        gaps.append((now - last[0]) * 1000)
        last[0] = now

    hb.timeout.connect(_beat)
    hb.start()

    # 実 close (確認ダイアログはスキップ = 直接 unload_file で close 経路を駆動)。
    ws_before = _working_set_mb()
    key = app_vm.loaded_file_keys[0]
    gaps.clear()
    last[0] = time.perf_counter()
    t0 = time.perf_counter()
    app_vm.unload_file(key)  # 同期部分 (fix 前は ~7s ここでブロック)
    sync_close_ms = (time.perf_counter() - t0) * 1000

    # drain 完了まで event loop を回す (fix 後は背景 drain。fix 前は teardown None で即抜け)。
    drain_start = time.perf_counter()
    teardown = getattr(window, "teardown_service", None)
    while teardown is not None and teardown.pending_bytes() > 0:
        app.processEvents()
        if time.perf_counter() - drain_start > 120:
            break
    drain_total_ms = (time.perf_counter() - drain_start) * 1000
    ws_after = _working_set_mb()

    drain_max_gap_ms = max(gaps) if gaps else 0.0
    print(f"reached_channels={reached}")
    print(f"sync_close_ms={sync_close_ms:.1f}")
    print(f"drain_max_gap_ms={drain_max_gap_ms:.1f}")
    print(f"drain_total_ms={drain_total_ms:.1f}")
    print(f"working_set_mb_before_close={ws_before:.0f}")
    print(f"working_set_mb_after_drain={ws_after:.0f}")

    # 隔離 QSettings を掃除。
    from PySide6.QtCore import QSettings

    QSettings("ValiSync-Bench", "fu16-teardown-bench").clear()


if __name__ == "__main__":
    main()
