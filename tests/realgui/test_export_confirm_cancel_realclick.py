"""Layer C (realgui・G8) — 確認 -> 完走 -> 実ファイル読み直し / 実キャンセル -> 何も残らない。

**fixture は確認閾値を確実に超える規模を明示指定する** (spec §6 G8 の空虚化防止):
閾値未満だと確認ダイアログが出ないまま (a) が「何も起きなかった」で緑になる。
超え方は **チャンネル数 x 行数** で作る — 見積は scalar/wide 別単価
(Task 11 レビュー C1 是正) を持ち、120 scalar チャンネル x 200,000 行では
推定 (read+write) ≈ 28.6 s (実測 wall 28.99 s と ~1.4% 差) となり閾値 5 s を
確実に超える。**C1 是正前**はここが単一単価 0.316 s/channel の一律適用で
推定 ~38 s だった — これは「小さいチャンネルへの既知の過大」ではなく読み項が
scalar/wide の区別を持たない桁違いのバグで、是正後は推定と実測がほぼ一致する
(旧コメントの「既知の性質」という記述は誤りだったので削除した)。
テストは「推定が本当に閾値を超えている」ことを assert してから進む — 係数が
再検定で下がったらここが loud-fail し、黙ってダイアログを飛ばさない。

**サイズ是正 (Task 11 実機発見)**: 当初の brief 値 (120 ch x 50,000 行) は実測
総 wall がわずか 7.3 s (単一ブロック) で、(b) の実キャンセルが「temp 出現待ち→
実クリック」の間に export が自然完走してしまい `test_real_cancel_midway_...`
が honest-RED でなく **偽陽性の RED** (キャンセルが効かなかったのではなく、
間に合わなかった) を出した。120 ch x 200,000 行 (実測 wall ~30 s・複数ブロック)
へ拡大し、実クリックが確実に in-flight 中に届く余裕を確保した。

**Task 11 レビュー是正 (I2/I3/I4/M6/M7)**:
- I2: (b) の失敗メッセージが「クリックが届いていない」(cancel Event 未発火)と
  「キャンセルが効いていない」(Event は発火したのにファイルが残った =
  production バグ) を分離するようにした — 旧 assert はレビュアーが 3 回中 1 回
  再現した「実クリックが cancel ボタンへ届かない」失敗を production バグの
  文言で報告していた (`busy_overlay.py:66-70` に記録済みの既往が真因)。加えて
  クリックは本リポジトリ確立プロトコル (押した効果を確認してから進む・
  `press_grip_and_confirm` と同型) の再試行ループへ強化した。
- I3: (a) の「全列読み直し」主張に非空セルの存在チェックを足した (共有
  `read_export_rows` — 同日に `test_export_range_realclick.py` の R4 で塞いだ
  穴と同型の欠落だった)。
- I4: (a) の確認ダイアログ検出を「0.4 秒待って 1 回だけ走査」から「デッドライン
  つきの再試行ループ + GUI スレッド上の watchdog タイマ」へ書き換えた。旧実装は
  ダイアログ表示が 0.4 秒を超えた回に `QMessageBox.exec()` (timeout 無し) が
  無期限ブロックし、`t.join(timeout=10.0)` は exec() が返った**後**にしか
  効かないため救済にならなかった (レビュー指摘)。
- M6: `_pump`/`_real_click`/`_read_rows` を
  `tests/realgui/_realgui_input`(`pump`/`pump_n`/`real_click_widget`/
  `read_export_rows`) へ共有昇格した。

エビデンス: design_export/evidence_e4b/ へ保存。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    pump,
    pump_n,
    read_export_rows,
    real_click_widget,
    skip_unless_real_display,
)

pytestmark = pytest.mark.realgui

_EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "design_export" / "evidence_e4b"
_CHANNELS = 120
_SAMPLES = 200_000

# I4 是正: ダイアログ検出の再試行ループ上限と、それでも見つからない場合に
# exec() を強制的に返らせる GUI スレッド watchdog の発火時刻。watchdog は
# clicker の自然な打ち切りより後にだけ発火させる (正常系を先に試させる)。
_CLICKER_DEADLINE_S = 8.0
_WATCHDOG_MS = 10_000


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


def test_confirm_then_export_completes_and_the_file_reads_back(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """(a) 実 OS クリックで [書き出す] -> 完走 -> 実ファイルを全列読み直し。"""
    skip_unless_real_display()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

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
            deadline = time.perf_counter() + _CLICKER_DEADLINE_S
            while time.perf_counter() < deadline:
                for w in QApplication.topLevelWidgets():
                    if isinstance(w, QMessageBox) and w.isVisible():
                        boxes.append(w)
                        btn = w.button(QMessageBox.StandardButton.Yes)
                        real_click_widget(btn)
                        return
                time.sleep(0.05)

        def watchdog() -> None:
            # exec() のネストイベントループ上 (GUI スレッド) で走る。clicker の
            # 再試行ループが尽きてもダイアログが見つからない場合の保険 (I4) —
            # activeModalWidget を強制的に reject して exec() を返らせ、
            # 「無期限ハング」を「boxes が空のままの明示的な RED」に変える。
            if boxes:
                return
            modal = QApplication.activeModalWidget()
            if modal is not None:
                modal.reject()

        t = threading.Thread(target=clicker)
        t.start()
        box_ready.set()
        QTimer.singleShot(_WATCHDOG_MS, watchdog)
        result = real_confirm(est_arg)
        # exec() が返った時点で正常系ならクリッカーは既に return 済み。
        # watchdog 経路でもクリッカー自身の deadline (< watchdog 発火) が
        # 先に尽きているので、ここは短い上限で十分 (I4: t.join は「exec() が
        # 返った後」にしか効かないが、その前提を watchdog がここまで運ぶ)。
        t.join(timeout=2.0)
        return result

    window._confirm_export_fn = capture
    request = ExportRequest(keys, out, CsvExportOptions(), list)
    window._run_export(request, est)
    qtbot.waitUntil(lambda: out.exists(), timeout=180_000)
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=10_000)

    assert boxes, "確認ダイアログが実際には出ていない (空虚化)"
    rows = read_export_rows(out)  # I3: 非空セルの存在まで検証する共有オラクル
    assert len(rows) == _SAMPLES, f"行数が想定外: {len(rows)}"
    assert len(rows[0]) == _CHANNELS + 1, f"列数が想定外: {len(rows[0])}"
    assert "エクスポートしました" in window.status_message()
    window.close()


def _click_cancel_with_retries(
    window, run, *, attempts: int = 6, settle_s: float = 0.3
) -> None:  # type: ignore[no-untyped-def]
    """実クリックを cancel Event が立つまで再試行する (Task 11 レビュー I2 是正)。

    本リポジトリの確立プロトコル (``press_grip_and_confirm`` 系: ジェスチャが
    効いたことを確認してから進む) と同型 — 1 発撃って祈るのではなく、
    ``run.cancel.is_set()`` という production の実観測点を毎回確認し、
    効いていなければ撃ち直す。``BusyOverlay`` は親追従の透過オーバーレイで
    親 resize 直後は ``cover()`` が stale になりうる (`busy_overlay.py:66-70`
    に記録済みの既往) ので、単発クリックはこの窓に当たると届かない。
    """
    for _ in range(attempts):
        if run.cancel.is_set():
            return
        real_click_widget(window.busy_overlay.cancel_button)
        settle_deadline = time.perf_counter() + settle_s
        while time.perf_counter() < settle_deadline:
            pump(0.03)
            if run.cancel.is_set():
                return
    # ここに来たら attempts 回とも届かなかった — 呼び出し元が
    # run.cancel.is_set() を明示 assert して「クリックが届いていない」と
    # 報告する (production の cancel 処理そのものは呼ばれていないので、
    # ここでは何も断定しない)。


def test_real_cancel_midway_leaves_no_file_and_no_temp(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """(b) 実 OS クリックでキャンセル -> ファイル無し・temp 無し。

    Task 11 レビュー I2 是正: cancel Event (``ExportRun.cancel`` —
    ``ExportController.cancel_active`` が set する production の協調キャンセル
    観測点) を独立に検証し、「クリックが届いていない」と「キャンセルが
    効いていない」を別メッセージで報告する。
    """
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

    # I2: cancel Event 自体を独立に観測するため ExportRun を横取りする
    # (production コードは変更しない — prepare() の返り値を記録するだけ)。
    export_controller = window._export_controller
    captured_runs: list[object] = []
    original_prepare = export_controller.prepare

    def _capturing_prepare():  # type: ignore[no-untyped-def]
        run = original_prepare()
        captured_runs.append(run)
        return run

    export_controller.prepare = _capturing_prepare  # type: ignore[method-assign]

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

    assert captured_runs, "ExportRun が準備されていない (エクスポートが開始していない)"
    run = captured_runs[-1]

    _click_cancel_with_retries(window, run)
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=120_000)

    assert seen_temp, "temp が一度も観測されず、消滅 assert が空虚形になっている"
    # I2: まずクリックが本当に届いたか (production の cancel 処理へ到達したか)
    # を production の実観測点で確認する。届いていなければ、以降のファイル
    # 消滅 assert が偶然 green になっても production の cancel の正しさとは
    # 無関係なので、ここで明確に区別して落とす。
    assert run.cancel.is_set(), (
        "実クリックが cancel を起動しなかった = クリックが届いていない "
        f"(既往: busy_overlay.py:66-70 の cover() stale 化)。証拠: {shot}"
    )
    assert not out.exists(), (
        f"cancel Event は発火した (クリックは届いた) のにファイルが存在する "
        f"= キャンセルが効いていない。証拠: {shot}"
    )
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
    pump_n(4)
