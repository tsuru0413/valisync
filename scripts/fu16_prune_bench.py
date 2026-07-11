"""FU-16 prune perf bench: prod スケールで unloaded->全パネル prune を実測.

before(全走査 prune): session の全 330k 信号を N x P 回走査 + remove 後初回の
namespaced 全再構築で長時間。after(group_key フィルタ): O(#files) x entry 数。
体感は実 GUI close(/verify)が最終ゲートだが、本ベンチで decisive な数値を取る。

CI では走らせない(prod_demo.mf4 は非コミット・重い)。ローカル実測用:

    VALISYNC_PROD_MF4=/abs/path/to/prod_demo.mf4 QT_QPA_PLATFORM=offscreen \
        uv run python scripts/fu16_prune_bench.py
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM

# prod_demo.mf4 はワークツリー外(親リポジトリ demo_data/)に置かれることが多いため
# 環境変数で絶対パスを渡せるようにする(gitignore・非コミットの巨大ファイル)。
PROD = Path(os.environ.get("VALISYNC_PROD_MF4", "demo_data/prod_demo.mf4"))
TABS, PANELS_PER_TAB, SIGNALS_PER_PANEL = 3, 3, 5


def main() -> None:
    if not PROD.exists():
        raise SystemExit(
            f"prod demo mf4 not found: {PROD}\n"
            "Generate with: uv run python scripts/generate_demo_mf4.py --profile prod\n"
            "or point VALISYNC_PROD_MF4 at an existing one."
        )

    app_vm = AppViewModel()
    # MDF4 は format_def を無視する(Session.load が拡張子で MdfLoader に分岐)ため None でよい。
    key = app_vm.request_load(PROD)
    # プロットする実在の signal_key を先頭から少数採取(プロット数は真因に無関係 —
    # 遅さは「セッション全走査」に支配され「プロット数」には支配されない)。
    names = [s.name for s in app_vm.session.signals()][:SIGNALS_PER_PANEL]

    vm = GraphAreaVM(app_vm)
    for _ in range(TABS - 1):
        vm.add_tab()
    for tab in range(TABS):
        vm.set_active_tab(tab)
        while len(vm.panels(tab)) < PANELS_PER_TAB:
            vm.add_panel(tab)
        for panel in vm.panels(tab):
            for name in names:
                panel.add_signal(name)

    calls = 0
    real_signals = app_vm.session.signals

    def spy() -> list[object]:
        nonlocal calls
        calls += 1
        return real_signals()

    app_vm.session.signals = spy  # type: ignore[method-assign]

    t0 = time.perf_counter()
    app_vm.unload_file(key)  # unloaded broadcast → 全タブ全パネル prune
    dt_ms = (time.perf_counter() - t0) * 1000

    print(f"tabs={TABS} panels/tab={PANELS_PER_TAB} -> panels={TABS * PANELS_PER_TAB}")
    print(f"prune wall-clock: {dt_ms:.1f} ms")
    print(f"session.signals() call-count during prune: {calls}")


if __name__ == "__main__":
    main()
