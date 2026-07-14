"""凍結検証用スクショ撮影 — 最小版 (design-token pipeline 増分1, spec §7).

実ディスプレイ必須 (offscreen は文字が全て□ — docs/development.md)。
QSettings を一時 dir へ隔離し、決定的な内蔵 CSV データで同一状態を再現、
QWidget.grab() で撮る (grabWindow(0) はタスクバー/背後ウィンドウが写るため不使用)。

使い方:
    uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_baseline
比較:
    uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_after
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import tempfile
import time
from pathlib import Path

_N_SAMPLES = 240  # 12s @ 20Hz — 波形の形が視認できる決定的データ


def _write_fixture_csv(path: Path) -> None:
    """決定的な内蔵データ (毎回同一バイト → 凍結比較の前提を満たす)。"""
    rows = ["t,EngineSpeed,VehSpd"]
    for i in range(_N_SAMPLES):
        t = i * 0.05
        rows.append(f"{t:.3f},{800 + (i % 60) * 25:.1f},{(i % 100) * 1.2:.2f}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--debug-theme",
        action="store_true",
        help="全 Color トークンを相異なる値にして撮影 (役割写像の目視検証・spec §7-6)",
    )
    args = parser.parse_args()

    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        print("offscreen では撮影不可 (文字が□になる)。", file=sys.stderr)
        return 2
    os.environ["QT_QPA_PLATFORM"] = "windows"
    # 物理マウスを画面隅へ退避 — hover 効果を撮影状態から排除 (spec §7-2)
    ctypes.windll.user32.SetCursorPos(5, 5)

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    # QSettings 隔離 — ユーザーの実ドック配置/ジオメトリ復元を遮断 (spec §6)
    tmp = Path(tempfile.mkdtemp(prefix="valisync_capture_"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp / "settings")
    )

    app = QApplication(sys.argv)

    if args.debug_theme:
        from valisync.gui.theme.tokens import set_active

        set_active(_debug_theme())

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.app import build_main_window

    window = build_main_window()
    screen = app.primaryScreen().availableGeometry()
    window.setGeometry(screen.x() + 60, screen.y() + 60, 1120, 760)
    window.show()
    window.raise_()
    window.activateWindow()

    def settle(secs: float = 0.4) -> None:
        deadline = time.monotonic() + secs
        while time.monotonic() < deadline:
            app.processEvents()

    args.out.mkdir(parents=True, exist_ok=True)

    def grab(name: str) -> None:
        settle()
        window.grab().save(str(args.out / f"{name}.png"))
        print(f"captured {name}.png")

    settle(1.0)
    grab("01_welcome")

    # --- データ読込 (同期 load — busy overlay/スピナーが写らない) --------------
    csv = tmp / "fixture.csv"
    _write_fixture_csv(csv)
    fmt = FormatDefinition(
        name="capture_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    outcome = window.app_vm.session.load(csv, fmt)
    window._on_loaded(outcome)
    settle()

    model = window.channel_browser_view.model
    keys = [model.signal_key_at(model.index(r, 0)) for r in range(model.rowCount())]
    panel_vm = window.graph_area_vm.panels(0)[0]
    for key in keys:
        assert key is not None
        panel_vm.add_signal(key)
    grab("02_plotted")

    # --- カーソル A+B → readout チップ (delta モード) --------------------------
    panel_vm.set_cursor(3.0)
    panel_vm.set_cursor_b(6.0)
    grab("03_cursor")

    # --- グリッド ---------------------------------------------------------------
    panel_vm.toggle_grid(True)
    grab("04_grid")
    panel_vm.toggle_grid(False)

    # --- QSS 系アフォーダンス強制表示 (アクティブ枠/ドロップ強調) ----------------
    # 撮影ツールとしての private 利用: 色は QSS 由来なので可視化さえすれば
    # ピクセルは production 経路の描画そのもの。
    panel_view = next(w for _t, _p, w in window.graph_area_view._panel_views)
    panel_view._active_frame.setVisible(True)
    panel_view._set_drop_highlight(True)
    window.graph_area_view._set_drop_highlight(True)
    grab("05_affordances")

    window.close()
    return 0


def _debug_theme():
    """全 Color トークンが相異なるテーマ — 各トークンの着地点を目視で検証する。

    alpha は元値を保持 (半透明チップ等のレイアウト/合成条件を変えないため)。
    golden-angle で hue を回すので隣接 index も視覚的に離れる。
    """
    import colorsys
    import dataclasses

    from valisync.gui.theme.tokens import DARK, Color

    def distinct(i: int, a: int) -> Color:
        r, g, b = colorsys.hsv_to_rgb((i * 0.61803) % 1.0, 1.0, 1.0)
        return Color(int(r * 255), int(g * 255), int(b * 255), a)

    c = DARK.colors
    names = [f.name for f in dataclasses.fields(c) if f.name != "signal_palette"]
    repl: dict = {name: distinct(i, getattr(c, name).a) for i, name in enumerate(names)}
    repl["signal_palette"] = tuple(
        distinct(100 + i, 255) for i in range(len(c.signal_palette))
    )
    return dataclasses.replace(DARK, colors=dataclasses.replace(c, **repl))


if __name__ == "__main__":
    sys.exit(main())
