# ruff: noqa: RUF002
"""Layer C (realgui, T-C1) — CSV 取込ダイアログの実機実証 (F-0/UX-05・design spec §1)。

実 CSV → CsvFormatDetector で実検出 → CsvFormatDialog を実表示 → 信号列スピン
(_sig_end) の実 OS クリック (up/down 矢印ボタン, 合成 setValue ではない) →
0 始まりヘッダ＋列ハイライト (時間列=chrome_cursor_a・信号列=chrome_signal_highlight)
の追従を実ピクセルで確認する。

headless (Layer A/B) は item.background()/setHorizontalHeaderLabels の値を直接検証
済み (tests/gui/test_csv_format_dialog.py) — 本テストは「実スピンボタンの実クリック
が Qt の QSpinBox::valueChanged -> _refresh -> ヘッダ/ハイライト再構築という実経路を
実際に通し、実描画された画面のピクセルに反映される」ことを実証する (Layer B の
setValue() 直接呼び出しは spin box の実クリック配送そのものを検証しない)。

エビデンス: design_export/evidence_f0/ へ保存 (Task 5 report からの目視参照用)。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui

_EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "design_export" / "evidence_f0"


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _write_csv(path: Path) -> None:
    lines = ["t,VehSpd,EngineSpeed,Torque"]
    for i in range(8):
        t = i * 0.5
        lines.append(f"{t:.3f},{10.0 + i:.2f},{800 + i * 10:.1f},{50.0 + i:.2f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _click_spin_button(spin, sub_control) -> None:  # type: ignore[no-untyped-def]
    """QSpinBox の up/down 矢印ボタンを実 OS クリック (幾何は QStyle から取得)。"""
    from PySide6.QtWidgets import QStyle, QStyleOptionSpinBox

    opt = QStyleOptionSpinBox()
    opt.initFrom(spin)
    rect = spin.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, opt, sub_control, spin
    )
    gp = spin.mapToGlobal(rect.center())
    dpr = spin.devicePixelRatioF()
    x, y = round(gp.x() * dpr), round(gp.y() * dpr)
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    _pump()


def _header_cell_pixel(dlg, preview, ci: int) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """列 ci のヘッダセル中心を dlg.grab() 画像の物理ピクセル座標へ変換。"""
    from PySide6.QtCore import QPoint

    header = preview.horizontalHeader()
    x = header.sectionViewportPosition(ci) + header.sectionSize(ci) // 2
    y = header.height() // 2
    local = header.viewport().mapTo(dlg, QPoint(x, y))
    dpr = dlg.devicePixelRatioF()
    return round(local.x() * dpr), round(local.y() * dpr)


def _find_pixel_near(
    image, col: int, row: int, expected_rgb: tuple[int, int, int], radius=10, tol=10
) -> bool:  # type: ignore[no-untyped-def]
    """expected_rgb 近傍のピクセルが (col,row) 周辺に存在するか (established pattern —
    tests/realgui/test_comparison_model_realclick.py)。厳密な中心1点一致は Fusion
    ヘッダの文字グリフ (アンチエイリアス縁) に当たると誤 RED になる (実測: 中心
    ±2-3px が黒テキストのアンチエイリアス縁と重なり配色と無関係な色が出る) ため、
    セル背景色そのものは近傍のどこかに残っていることを確認する近傍探索にする。
    """
    er, eg, eb = expected_rgb
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            c = image.pixelColor(col + dc, row + dr)
            if (
                abs(c.red() - er) <= tol
                and abs(c.green() - eg) <= tol
                and abs(c.blue() - eb) <= tol
            ):
                return True
    return False


def test_csv_import_dialog_realclick_spin_updates_header_and_highlight(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QStyle

    from valisync.core.loaders.csv_format_detector import CsvFormatDetector
    from valisync.gui.theme import tokens
    from valisync.gui.views.csv_format_dialog import CsvFormatDialog, _opaque

    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    csv = tmp_path / "import.csv"
    _write_csv(csv)
    detected = CsvFormatDetector().detect(csv)
    assert detected.has_header, "フィクスチャはヘッダ行ありのはず"

    dlg = CsvFormatDialog(detected)
    qtbot.addWidget(dlg)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    dlg.move(screen.x() + 80, screen.y() + 80)
    dlg.show()
    # プレビューの全4列が横スクロール無しで見えるよう明示的に広げる (既定幅は
    # QTableWidget の既定セクション幅で全列を賄えず、右側の列が viewport 外に
    # クリップされて実ピクセル確認が成立しない)。
    dlg.resize(900, 500)
    dlg.raise_()
    dlg.activateWindow()
    qtbot.waitExposed(dlg)
    _pump()

    preview = dlg._preview
    ts_col_before = dlg._ts_col.value()
    sig_start_before = dlg._sig_start.value()
    sig_end_before = dlg._sig_end.value()
    assert sig_end_before > sig_start_before, (
        "フィクスチャは信号列2本以上検出される前提 (spin down 操作の余地を作る)"
    )

    # ── 0 始まりヘッダ (off-by-one 構造解消) を実表示から確認 ──────────────
    header0 = preview.horizontalHeaderItem(ts_col_before)
    header1 = preview.horizontalHeaderItem(sig_start_before)
    assert header0 is not None and header0.text().startswith(f"{ts_col_before}:"), (
        f"時間列ヘッダが 0 始まり表記でない: {header0.text() if header0 else None!r}"
    )
    assert header1 is not None and header1.text().startswith(f"{sig_start_before}:"), (
        f"信号列ヘッダが 0 始まり表記でない: {header1.text() if header1 else None!r}"
    )

    shot_before = _EVIDENCE_DIR / "01_csv_dialog_before_spin.png"
    dlg.grab().save(str(shot_before))

    # ── 実 OS クリック: 信号列終了スピンの down 矢印を実クリック (sig_end を1減) ──
    _click_spin_button(dlg._sig_end, QStyle.SubControl.SC_SpinBoxDown)
    qtbot.waitUntil(lambda: dlg._sig_end.value() == sig_end_before - 1, timeout=2000)
    assert dlg._sig_end.value() == sig_end_before - 1, (
        "信号列終了スピンの down 矢印実クリックが値に反映されない"
    )
    _pump(0.05)

    # ── ライブ配線: valueChanged -> _refresh -> ヘッダラベル/ハイライト再構築 ──
    excluded_col = sig_end_before  # もう信号範囲外になったはずの列
    header_excluded = preview.horizontalHeaderItem(excluded_col)
    assert header_excluded is not None
    colors = tokens.active().colors
    sig_bg = _opaque(colors.chrome_signal_highlight)
    ts_bg = _opaque(colors.chrome_cursor_a)
    assert header_excluded.background().color() != sig_bg, (
        "spin down 後も除外されたはずの列が信号ハイライトのまま (ライブ配線が効いていない)"
    )

    shot_after = _EVIDENCE_DIR / "02_csv_dialog_after_spin.png"
    dlg.grab().save(str(shot_after))

    # ── 実ピクセル確認: 時間列ヘッダ/現在の信号列ヘッダが実描画で色分けされている ──
    img = dlg.grab().toImage()
    ts_px = _header_cell_pixel(dlg, preview, ts_col_before)
    sig_px = _header_cell_pixel(dlg, preview, dlg._sig_start.value())
    assert _find_pixel_near(img, *ts_px, (ts_bg.red(), ts_bg.green(), ts_bg.blue())), (
        f"時間列ヘッダの実ピクセル近傍に chrome_cursor_a ({ts_bg.name()}) が"
        f" 見つからない (col={ts_px[0]}, row={ts_px[1]}). screenshot: {shot_after}"
    )
    assert _find_pixel_near(
        img, *sig_px, (sig_bg.red(), sig_bg.green(), sig_bg.blue())
    ), (
        f"信号列ヘッダの実ピクセル近傍に chrome_signal_highlight ({sig_bg.name()}) が"
        f" 見つからない (col={sig_px[0]}, row={sig_px[1]}). screenshot: {shot_after}"
    )

    dlg.close()
