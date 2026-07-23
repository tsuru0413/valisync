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
import json
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
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="カタログ用の追加状態 (ダイアログ/プレビュー) も撮影 (凍結比較の既定5状態は不変)",
    )
    parser.add_argument(
        "--theme",
        choices=["dark", "light"],
        default="dark",
        help="撮影テーマ (ホスト OS 設定に依存しない決定的撮影のため必須既定 dark)",
    )
    args = parser.parse_args()

    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        print("offscreen では撮影不可 (文字が□になる)。", file=sys.stderr)
        return 2
    os.environ["QT_QPA_PLATFORM"] = "windows"
    # 物理マウスを画面隅へ退避 — hover 効果を撮影状態から排除 (spec §7-2)
    ctypes.windll.user32.SetCursorPos(5, 5)

    from PySide6.QtCore import QCoreApplication, QEvent, QSettings
    from PySide6.QtWidgets import QApplication

    # QSettings 隔離 — 実 ValiSync 設定 (Recent Files / dockCollapsed / ドック配置 /
    # geometry) の漏れ込みを断つ。QSettings(org, app) は Windows で NativeFormat
    # (レジストリ) 固定で setDefaultFormat(IniFormat)+setPath では隔離できない
    # (2 引数コンストラクタは defaultFormat を無視する) ため、conftest と同型に
    # _ORG/_APP を撮影専用キーへ差し替え、毎回 clear して決定的な既定状態
    # (全ドック展開・Recent 空) から撮る。tmp は fixture CSV 置き場としてのみ使う。
    tmp = Path(tempfile.mkdtemp(prefix="valisync_capture_"))

    import valisync.gui.theme.settings as _theme_settings
    import valisync.gui.views.main_window as _main_window
    import valisync.gui.views.recent_files as _recent_files

    for _mod in (_main_window, _recent_files, _theme_settings):
        _mod._ORG = "ValiSync-Capture"
        _mod._APP = "ValiSync-Capture"
    QSettings("ValiSync-Capture", "ValiSync-Capture").clear()

    app = QApplication(sys.argv)
    # テキストキャレットの点滅を無効化 — blink 位相の撮影レースで focus 中の
    # QLineEdit に 1px 縦線の非決定差分が出る (region-frames T5 で 20px 実測)
    app.setCursorFlashTime(0)

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.app import build_main_window
    from valisync.gui.theme.tokens import ThemeMode

    mode = ThemeMode.LIGHT if args.theme == "light" else ThemeMode.DARK
    if args.debug_theme:
        from valisync.gui.theme.tokens import DARK, LIGHT

        base = LIGHT if args.theme == "light" else DARK
        window = build_main_window(theme=_debug_theme(base))
    else:
        window = build_main_window(theme=mode)
    screen = app.primaryScreen().availableGeometry()
    window.setGeometry(screen.x() + 60, screen.y() + 60, 1120, 760)
    window.show()
    window.raise_()
    window.activateWindow()

    def settle(secs: float = 0.4) -> None:
        deadline = time.monotonic() + secs
        while time.monotonic() < deadline:
            app.processEvents()
            # processEvents() 単独では QEvent.DeferredDelete が実 exec() ループ
            # (ここでは未使用) 経由でしか flush されず、deleteLater() 済みウィジェット
            # が生存し続ける (Qt の仕様 — 実アプリの app.exec() 下では自然に解消する
            # ため production バグではない)。readout の凡例→計測モード等の連続
            # full_rebuild で旧行が残存し重ね描画されるスクショ限定の artifact を
            # 明示的 flush で根治 (計測 IA Task 10 で発見)。
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    args.out.mkdir(parents=True, exist_ok=True)

    def panel_viewport_rect() -> dict[str, int] | None:
        """アクティブなグラフパネルの plot viewport 矩形 (grab 画像のピクセル空間)。

        `GraphPanelView.plot_widget`(QGraphicsView) の viewport を window 座標へ
        mapTo し、devicePixelRatioF で物理ピクセルへ換算する — window.grab() が
        保存する PNG は物理ピクセル寸法 (Windows 125% 等スケーリング時は論理サイズ
        と一致しない)。パネル無し/非可視状態 (Welcome 等 — central_stack が
        graph_area_view を裏に隠している) は None (呼び出し側で省略)。Welcome 到達
        時点でも既定タブ/空パネルは生成済みのため、isVisible() で実際に画面上へ
        出ているかを見る (QStackedWidget の非カレントページは hide() される)。
        """
        from PySide6.QtCore import QPoint

        panels = list(window.graph_area_view._panel_views)
        if not panels:
            return None
        _tab, _panel_id, panel_view = panels[0]
        if not panel_view.isVisible():
            return None
        viewport = panel_view.plot_widget.viewport()
        top_left = viewport.mapTo(window, QPoint(0, 0))
        dpr = window.devicePixelRatioF()
        return {
            "x": round(top_left.x() * dpr),
            "y": round(top_left.y() * dpr),
            "w": round(viewport.width() * dpr),
            "h": round(viewport.height() * dpr),
        }

    def grab(name: str) -> None:
        settle()
        window.grab().save(str(args.out / f"{name}.png"))
        rect = panel_viewport_rect()
        if rect is not None:
            (args.out / f"{name}.viewport.json").write_text(
                json.dumps(rect), encoding="utf-8"
            )
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

    if args.catalog:
        # アフォーダンス強制表示を解除してからカタログ状態へ
        panel_view._active_frame.setVisible(False)
        panel_view._set_drop_highlight(False)
        window.graph_area_view._set_drop_highlight(False)
        settle()

        # --- 06: CSV エクスポートダイアログ (エラーラベル表示状態) -------------
        # F-0/UX-28: 出力範囲 DI — 実際に main_window.export_csv が渡すのと同じ
        # 値 (アクティブパネルの x_range・カーソル A/B) を注入する。カーソルは
        # 03_cursor で既に設置済みの決定的な値 (3.0/6.0) をそのまま再利用する
        # (別の定数を重複させると値がずれるリスクがあるため単一の真実に揃える)。
        # 選択数は意図的に空のまま (既存のエラー行可視化状態を維持) — 範囲ラジオの
        # enabled/ラベルは選択集合と無関係に x_range/cursor スナップショットだけで
        # 決まるため、この状態のままでも [カーソル A-B] enabled + 実範囲ラベルが写る。
        from valisync.gui.views.export_csv_dialog import ExportCsvDialog

        export_panel = window.graph_area_vm.active_panel()
        export_cursor_state = window.graph_area_vm.active_tab().cursor_state
        dlg = ExportCsvDialog(
            window.app_vm,
            initial_selected=set(),
            x_range=export_panel.x_range,
            cursor_a=export_cursor_state.cursor_t,
            cursor_b=export_cursor_state.cursor_t_b,
            offset_for=export_panel.offset_for,
        )
        dlg._validate()  # 撮影ツールとしての private 利用: エラー行を可視化
        dlg.show()
        settle()
        dlg.grab().save(str(args.out / "06_export_dialog_error.png"))
        print("captured 06_export_dialog_error.png")
        dlg.close()

        # --- 07: CSV フォーマット確認ダイアログ --------------------------------
        from valisync.core.loaders.csv_format_detector import CsvFormatDetector
        from valisync.gui.views.csv_format_dialog import CsvFormatDialog

        detected = CsvFormatDetector().detect(csv)
        fmt_dlg = CsvFormatDialog(detected)
        fmt_dlg.show()
        settle()
        fmt_dlg.grab().save(str(args.out / "07_csv_format_dialog.png"))
        print("captured 07_csv_format_dialog.png")
        fmt_dlg.close()

        # --- 08: 信号プレビュー窓 ----------------------------------------------
        # F-0/UX-43: viewport.json はあえて出力しない — spec §6 M は 08 を他の
        # ダイアログ状態と同様に --crop-meta の比較対象から明示的に SKIP する設計
        # (main window プロット面 (02-05/09) への非波及証明とスコープを分離する
        # ため、viewport.json を持たせると 08 が crop-meta に巻き込まれてしまう)。
        # 軸ラベル追加によるプロット領域の幾何変化/波形データ不変は Task 5 で
        # design_export/screenshots_f0_{dark,light} と旧
        # screenshots_catalog_{dark,light} の 08 をフル画像比較+目視で個別確認する
        # (design.md 決定履歴・Task 5 report に記録)。
        window.signal_preview_window.show_signal(keys[0])
        settle()
        window.signal_preview_window.grab().save(
            str(args.out / "08_signal_preview.png")
        )
        print("captured 08_signal_preview.png")
        window.signal_preview_window.close()

        # --- 09: 辺対応の折りたたみ (右=縦レール+縦タブ / 下=横帯) --------------
        # 右ドックは両方畳んで初めて幅が空く (縦積み兄弟) — 目標の2行縦タブ姿を撮る。
        window._collapse_dock(window.file_dock)
        window._collapse_dock(window.channel_dock)
        window._collapse_dock(window.diagnostics_dock)
        settle()
        grab("09_collapsed")
        window._expand_dock(window.file_dock)
        window._expand_dock(window.channel_dock)
        window._expand_dock(window.diagnostics_dock)
        settle()

    window.close()
    return 0


def _debug_theme(base):
    """全 Color トークンが相異なるテーマ — 各トークンの着地点を目視で検証する。

    alpha は元値を保持 (半透明チップ等のレイアウト/合成条件を変えないため)。
    golden-angle で hue を回すので隣接 index も視覚的に離れる。
    """
    import colorsys
    import dataclasses

    from valisync.gui.theme.tokens import Color

    def distinct(i: int, a: int) -> Color:
        r, g, b = colorsys.hsv_to_rgb((i * 0.61803) % 1.0, 1.0, 1.0)
        return Color(int(r * 255), int(g * 255), int(b * 255), a)

    c = base.colors
    names = [f.name for f in dataclasses.fields(c) if f.name != "signal_palette"]
    repl: dict = {name: distinct(i, getattr(c, name).a) for i, name in enumerate(names)}
    repl["signal_palette"] = tuple(
        distinct(100 + i, 255) for i in range(len(c.signal_palette))
    )
    return dataclasses.replace(base, colors=dataclasses.replace(c, **repl))


if __name__ == "__main__":
    sys.exit(main())
