"""FU-16 teardown perf bench: prod スケールで close の同期時間と drain 中の UI 応答を実測.

実アプリ経路 (MainWindow._load_file オフスレッド -> 330,004ch) で実 close を回し、
(1) 同期 close 時間 (2) drain 中 heartbeat 最大 gap を測る。
内部 API・小データは 6 秒を隠すため厳禁 (len(signals) を検証)。

E-3 T8/T9: 1024 展開ガードと展開確認モーダルは退役した。到達チャンネル数を稼ぐために
展開確認を「全展開」へ差し替えていた行はもう無い (差し替え対象が存在しない)。
反転で session.signals() は **物理チャンネル** のみを返すので、到達検証は
物理 / 列の 2 軸で行う (物理だけを見ると 61 分の 1 の規模で「到達した」と誤判定し、
小データ false-green を落とす唯一の防波堤が無力化する)。

honest-RED (現行同期 remove_group・TeardownService 未配線):
    reached_columns=330004 / sync_close_ms ~ 7000 / drain_* ~ 0
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
# E-3 反転後の到達値 (小データ / 部分ロードでの false-green を落とすための固定値)。
# session.signals() は **物理チャンネル** のみを返すようになったので、列数は
# total_column_count() で別途検証する — 物理だけを見ると 61 分の 1 の規模で
# 「到達した」と誤判定し、6 秒フリーズを隠す元の false-green が戻る。
EXPECTED_PHYSICAL = 4_324
EXPECTED_COLUMNS = 330_004


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

    key = app_vm.loaded_file_keys[0]
    reached_physical = len(app_vm.session.signals())
    reached_columns = app_vm.session.total_column_count(key)
    if (reached_physical, reached_columns) != (EXPECTED_PHYSICAL, EXPECTED_COLUMNS):
        raise SystemExit(
            f"reached physical={reached_physical} columns={reached_columns} "
            f"(expected {EXPECTED_PHYSICAL}/{EXPECTED_COLUMNS} -- 小データ/部分ロードで"
            "フリーズを隠す false-green のため中止)"
        )
    print(
        f"loaded: physical={reached_physical} columns={reached_columns} "
        f"ws={_working_set_mb():.0f}MB",
        flush=True,
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
    gaps.clear()
    last[0] = time.perf_counter()
    t0 = time.perf_counter()
    app_vm.unload_file(key)  # 同期部分 (fix 前は ~7s ここでブロック)
    sync_close_ms = (time.perf_counter() - t0) * 1000

    # drain 完了まで event loop を回す (fix 後は背景 drain。fix 前は teardown None で即抜け)。
    # ポーリングは O(1) の pending_signals() で行う (pending_bytes() は残余を都度合算する
    # O(n) なので、drain-wait ループで呼ぶと drain_total_ms を汚染する)。
    drain_start = time.perf_counter()
    teardown = getattr(window, "teardown_service", None)
    while teardown is not None and teardown.pending_signals() > 0:
        app.processEvents()
        if time.perf_counter() - drain_start > 120:
            break
    drain_total_ms = (time.perf_counter() - drain_start) * 1000
    ws_after = _working_set_mb()

    drain_max_gap_ms = max(gaps) if gaps else 0.0
    print(f"reached_physical={reached_physical}")
    print(f"reached_columns={reached_columns}")
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
