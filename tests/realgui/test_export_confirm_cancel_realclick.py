"""Layer C (realgui・G8) — 確認 -> 完走 -> 実ファイル読み直し / 実キャンセル -> 何も残らない。

**fixture は確認閾値を確実に超える規模を明示指定する** (spec §6 G8 の空虚化防止):
閾値未満だと確認ダイアログが出ないまま (a) が「何も起きなかった」で緑になる。
超え方は **チャンネル数** で作る — 見積の読み項はチャンネル単価 0.316 s なので、
120 チャンネルで推定 ~38 s となり閾値 5 s を確実に超える一方、実際の書き出しは
数秒で終わる (推定は小さいチャンネルに対して過大に出る = 既知の性質)。
テストは「推定が本当に閾値を超えている」ことを assert してから進む — 係数が
Task 11 の検定で下がったらここが loud-fail し、黙ってダイアログを飛ばさない。

**サイズ是正 (Task 11 実機発見)**: 当初の brief 値 (120 ch x 50,000 行) は実測
総 wall がわずか 7.3 s (単一ブロック) で、(b) の実キャンセルが「temp 出現待ち→
実クリック」の間に export が自然完走してしまい `test_real_cancel_midway_...`
が honest-RED でなく **偽陽性の RED** (キャンセルが効かなかったのではなく、
間に合わなかった) を出した。120 ch x 200,000 行 (実測 wall ~30 s・複数ブロック)
へ拡大し、実クリックが確実に in-flight 中に届く余裕を確保した。

エビデンス: design_export/evidence_e4b/ へ保存。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui

_EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "design_export" / "evidence_e4b"
_CHANNELS = 120
_SAMPLES = 200_000


def _fixture_mf4(path: Path) -> None:
    from tests.mdf4_helpers import CAN, write_mdf4

    ts = [round(i * 0.001, 6) for i in range(_SAMPLES)]
    write_mdf4(
        path,
        [
            {
                "name": f"Ch{i:03d}",
                "bus_type": CAN,
                "timestamps": ts,
                "values": [float(i * 100 + (j % 97)) for j in range(_SAMPLES)],
            }
            for i in range(_CHANNELS)
        ],
    )


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _real_click(widget) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QPoint

    center = QPoint(widget.width() // 2, widget.height() // 2)
    gp = widget.mapToGlobal(center)
    dpr = widget.devicePixelRatioF()
    x, y = round(gp.x() * dpr), round(gp.y() * dpr)
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    for _ in range(4):
        _pump(0.02)


def test_confirm_then_export_completes_and_the_file_reads_back(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """(a) 実 OS クリックで [書き出す] -> 完走 -> 実ファイルを全列読み直し。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QMessageBox

    from valisync.core.export.csv_exporter import CsvExportOptions, ExportRequest
    from valisync.core.export.estimate import CONFIRM_THRESHOLD_S, estimate_export
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "confirm.mf4"
    _fixture_mf4(src)

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    session = window.app_vm.session
    outcome = session.load(src)
    window._on_loaded(outcome)
    keys = tuple(f"{outcome.key}::Ch{i:03d}" for i in range(_CHANNELS))
    out = tmp_path / "confirm_out.csv"

    est = estimate_export(session, list(keys), CsvExportOptions())
    # 空虚化防止: ダイアログ経路を本当に通ることを、進む前に確定させる。
    assert est.est_read_s + est.est_write_s >= CONFIRM_THRESHOLD_S, (
        f"fixture が確認閾値に届かない (推定 {est.est_read_s + est.est_write_s:.2f} s "
        f"< {CONFIRM_THRESHOLD_S} s) — このままでは (a) がダイアログを通らず空振りする"
    )

    _show_top(window, qtbot)
    boxes: list[QMessageBox] = []
    real_confirm = window._default_confirm_export

    def capture(est_arg):  # type: ignore[no-untyped-def]
        # 実 QMessageBox を出し、実 OS クリックで [書き出す] を押す。
        # exec() はモーダルなので、押下は別スレッドの実入力で行う。
        box_ready = threading.Event()

        def clicker() -> None:
            box_ready.wait(5.0)
            time.sleep(0.4)
            for w in __import__(
                "PySide6.QtWidgets", fromlist=["QApplication"]
            ).QApplication.topLevelWidgets():
                if isinstance(w, QMessageBox) and w.isVisible():
                    boxes.append(w)
                    btn = w.button(QMessageBox.StandardButton.Yes)
                    _real_click(btn)
                    return

        t = threading.Thread(target=clicker)
        t.start()
        box_ready.set()
        result = real_confirm(est_arg)
        t.join(timeout=10.0)
        return result

    window._confirm_export_fn = capture
    request = ExportRequest(keys, out, CsvExportOptions(), list)
    window._run_export(request, est)
    qtbot.waitUntil(lambda: out.exists(), timeout=180_000)
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=10_000)

    assert boxes, "確認ダイアログが実際には出ていない (空虚化)"
    rows = _read_rows(out)
    assert len(rows) == _SAMPLES, f"行数が想定外: {len(rows)}"
    assert len(rows[0]) == _CHANNELS + 1, f"列数が想定外: {len(rows[0])}"
    assert "エクスポートしました" in window.status_message()
    window.close()


def test_real_cancel_midway_leaves_no_file_and_no_temp(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """(b) 実 OS クリックでキャンセル -> ファイル無し・temp 無し。"""
    skip_unless_real_display()
    from valisync.core.export.csv_exporter import CsvExportOptions, ExportRequest
    from valisync.core.export.estimate import estimate_export
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    src = tmp_path / "cancel.mf4"
    _fixture_mf4(src)
    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    session = window.app_vm.session
    outcome = session.load(src)
    window._on_loaded(outcome)
    keys = tuple(f"{outcome.key}::Ch{i:03d}" for i in range(_CHANNELS))
    out = tmp_path / "cancel_out.csv"
    est = estimate_export(session, list(keys), CsvExportOptions())

    _show_top(window, qtbot)
    window._confirm_export_fn = lambda _e: True  # (b) の対象は確認ではなくキャンセル
    seen_temp: list[str] = []
    window._run_export(ExportRequest(keys, out, CsvExportOptions(), list), est)

    qtbot.waitUntil(lambda: not window.busy_overlay.isHidden(), timeout=10_000)
    qtbot.waitUntil(
        lambda: (
            seen_temp.extend(p.name for p in out.parent.glob(".tmp_*"))
            or bool(seen_temp)
        ),
        timeout=60_000,
    )
    shot = _EVIDENCE_DIR / "e4b_cancel_overlay.png"
    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(shot))

    _real_click(window.busy_overlay.cancel_button)
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=120_000)

    assert seen_temp, "temp が一度も観測されず、消滅 assert が空虚形になっている"
    assert not out.exists(), f"キャンセルしたのにファイルが存在する。証拠: {shot}"
    assert list(out.parent.glob(".tmp_*")) == [], "temp が残った (B6 違反)"
    assert "中止" in window.status_message()
    window.close()


def _show_top(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(
        screen.x() + 60,
        screen.y() + 60,
        min(1120, screen.width() - 120),
        min(760, screen.height() - 120),
    )
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(4):
        _pump(0.02)


def _read_rows(path: Path) -> list[list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    return [line.split(",") for line in text.splitlines()[1:] if line]
