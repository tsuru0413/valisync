"""キャンセルの配線・オフスレッド性・temp の後始末 (E-4b・G6/G7・spec §5.5-1)。

今日の欠陥: busy_overlay.cancel_requested は _load_controller.cancel_active へ
**恒久配線**されており、エクスポート中のキャンセルボタンは押しても何も起きない。
ここではボタンの下流 (MainWindow のルータ) を効果で固定する。

G6/G7 は実 CsvExporter を実ファイルへ走らせる (スタブでは temp も別スレッドも
存在しないので、どちらの契約も検証できない)。
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import LoadOutcome

# ブロックを **複数** 作るための注入幅 (48 列 / 8 = 6 ブロック)。動的決定に任せると
# 48 列は 1 ブロックに収まり、G6 の「途中でキャンセル」も G7 の「書きが複数回」も
# 観測窓ごと消える (Task 6/7 の block_cols 注入口を使う・spec §5.3)。
_BLOCK_COLS = 8


def _blocking_load(release: threading.Event) -> Callable[[], LoadOutcome]:
    def _run() -> LoadOutcome:
        release.wait(5.0)
        return LoadOutcome("late")

    return _run


def test_cancel_button_routes_to_every_active_controller(qtbot: QtBot) -> None:
    """load / export の **両方** が走っていれば両方が中止される。

    「今アクティブなのはどれか」を別に持たない設計の受け入れ: ルータに状態を作ると
    2 つ目の真実になり必ず腐る (旧実装が load へ恒久配線されていたのがまさにそれ)。
    """
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    load_cancel = threading.Event()
    export_release = threading.Event()

    window._load_controller.submit(
        _blocking_load(load_cancel),
        busy=window.busy_overlay,
        cancel_event=load_cancel,
        label="a.mf4",
    )
    run = window._export_controller.prepare()
    window._export_controller.submit(
        lambda: export_release.wait(5.0),
        run=run,
        busy=window.busy_overlay,
        label="out.csv",
    )

    window.busy_overlay.cancel_requested.emit()

    assert load_cancel.is_set(), "load へ届いていない"
    assert run.cancel.is_set(), "export へ届いていない (今日の欠陥そのもの)"
    export_release.set()
    qtbot.waitUntil(lambda: not window._export_controller.is_busy(), timeout=5000)


def test_cancelling_export_leaves_no_file_and_no_temp(tmp_path: Path) -> None:
    """G6: temp が **一度は存在した** ことを観測してから、消滅とファイル不在を assert。

    上界 0 だけ (temp が無い) を見ると、そもそも temp を作らない実装や 0 行で
    即終了した実装でも緑になる (空虚形)。
    """
    from valisync.core.export.csv_exporter import CsvExporter, ExportCancelled

    session, request = _big_request(tmp_path)
    out = request.output_path
    system_temp_before = set(Path(tempfile.gettempdir()).glob(".tmp_*"))
    seen: list[str] = []
    ticks: list[tuple[int, int]] = []
    cancel = threading.Event()

    def progress(done: int, total: int) -> None:
        ticks.append((done, total))
        seen.extend(p.name for p in out.parent.glob(".tmp_*"))
        # 最初の 1 単位 (時刻 temp) では止めない — ブロックを 1 本書いた後に
        # 止めることで「書きかけの temp」まで掃除対象に入る。
        if done >= 2:
            cancel.set()

    exporter = CsvExporter(block_cols=_BLOCK_COLS)
    raised = False
    try:
        exporter.export(
            request,
            session.resolve_signal_transient,
            progress=progress,
            cancel=cancel,
        )
    except ExportCancelled:
        raised = True

    assert raised, "cancel を立てたのに完走した (協調キャンセルが効いていない)"
    assert len(ticks) >= 2, f"ブロックが 1 本しかない fixture 規模不足 (ticks={ticks})"
    assert ticks[-1][0] < ticks[-1][1], "最終単位まで走ってからの中止 = 実質完走"
    assert seen, "temp が一度も観測されなかった — 消滅 assert が空虚形になっている"
    assert list(out.parent.glob(".tmp_*")) == [], "temp が残った (B6 違反)"
    assert not out.exists(), "キャンセルしたのに出力ファイルが存在する"
    # temp は **出力先と同一ディレクトリ** (os.replace の原子性と D5 の
    # ボリューム検査が同じボリュームであることの前提・spec §10)。
    assert set(Path(tempfile.gettempdir()).glob(".tmp_*")) == system_temp_before


def test_export_runs_off_the_gui_thread_at_resolve_and_at_write(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """G7: 捕捉点 2 箇所 (解決時・書き時)。部分インライン化を検出する。

    1 点だけだと「解決は GUI スレッドで先にやって書きだけ逃がす」実装が緑になり、
    E-4b が消そうとしている「保存を押した瞬間に固まる」体感が残る。
    """
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    session, request = _big_request(tmp_path)
    main_ident = threading.get_ident()
    at_resolve: list[int] = []
    at_write: list[int] = []
    base_resolver = session.resolve_signal_transient

    def resolve(key: str):  # type: ignore[no-untyped-def]
        at_resolve.append(threading.get_ident())
        return base_resolver(key)

    done: list[bool] = []
    errors: list[Exception] = []
    run = window._export_controller.prepare()

    def do_export() -> None:
        from valisync.core.export.csv_exporter import CsvExporter

        CsvExporter(block_cols=_BLOCK_COLS).export(
            request,
            resolve,
            progress=lambda d, t: at_write.append(threading.get_ident()),
            cancel=run.cancel,
        )

    window._export_controller.submit(
        do_export,
        run=run,
        busy=window.busy_overlay,
        on_success=lambda: done.append(True),
        on_error=errors.append,
    )
    qtbot.waitUntil(lambda: done == [True] or bool(errors), timeout=30000)

    assert errors == [], f"エクスポートが失敗した: {errors}"
    assert request.output_path.exists(), "反 vacuous: 実際には何も書けていない"
    assert len(at_write) >= 2, "ブロック 1 本では部分インライン化を見る解像度が無い"
    assert at_resolve
    assert main_ident not in at_resolve, "列解決が GUI スレッドで走っている"
    assert main_ident not in at_write, "書き出しが GUI スレッドで走っている"
    assert set(at_resolve) == set(at_write), "解決と書きが別スレッドに分かれている"


def test_second_export_is_rejected_while_the_first_is_mid_cancel(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    """I3 (T9 レビュー是正): cancel は Event を立てるだけで worker の停止を待たない
    非対称設計 (§1 衝突3) — ボタンを押した直後、worker がまだ ExportCancelled を
    返していない窓では `ExportController.is_busy()` が **まだ True**。この窓で
    `_run_export` をもう一度呼ぶと 2 本目の worker が受理されてしまっていた
    (reviewer 実測。task-9-report.md の「現状 GUI からは同時 export は起きない」
    という記述は実測に反する)。

    2 本目に渡す ``_tiny_request`` は未ロードのファイルを指すダミー鍵
    (実行されれば必ず解決失敗で ``on_error`` -> 本物の `QMessageBox.critical` へ
    落ちてテストがハングする — `test_cancel_callback_is_actually_wired_to_the_run_export_path`
    と同じ罠)。ガードが効いていれば submit 自体が起きないので無害だが、
    **ガードが壊れているケースを確かめるテストなので、壊れていても安全に RED で
    終わるよう** 先に潰しておく。
    """
    from valisync.core.export.csv_exporter import CsvExportOptions
    from valisync.gui import strings as S
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views import main_window as mw_mod
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    modals: list[object] = []
    monkeypatch.setattr(
        mw_mod.QMessageBox, "critical", lambda *a, **k: modals.append(a)
    )
    release = threading.Event()
    run = window._export_controller.prepare()
    window._export_controller.submit(
        lambda: release.wait(5.0), run=run, busy=window.busy_overlay, label="out.csv"
    )

    window._cancel_busy_operations()
    assert run.cancel.is_set(), "前提: 中止要求が届いている (worker はまだ停止前)"

    blocked: list[str] = []
    window._notify_blocked = blocked.append  # type: ignore[assignment]

    window._run_export(_tiny_request(tmp_path, CsvExportOptions()), _tiny_estimate())

    assert len(window._export_controller._active) == 1, "2 本目の export が投入された"
    assert blocked == [S.EXPORT_ALREADY_RUNNING]
    assert "中止" in window.busy_overlay.message(), "中止中の文言が上書きされた"

    release.set()
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=5000)


def test_run_export_captures_the_real_pipelines_thread_at_resolve_and_write(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    """M1 (T9 レビュー是正・G7 の再レビュー): G7 は `CsvExporter.export` を
    **直呼び**しており、捕捉点は G7 テスト自身が組んだ resolve/progress。
    `_run_export` が submit の **前**に列解決の一部を GUI スレッドでインライン
    化しても、その捕捉点は素通りして緑になる (production の捕捉点でないため)。

    ここでは `_run_export` を実際に走らせ、production 自身の捕捉点
    (`session.resolve_signal_transient` と `ExportRun.progress`) にスパイを
    刺して同じ性質 (2 点とも GUI スレッドでないこと・解決と書きが同一スレッド
    に揃うこと) を確かめる。
    """
    from valisync.core.export.csv_exporter import CsvExporter
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow
    from valisync.gui.workers import export_worker as ew_mod

    session, request = _big_request(tmp_path)
    session._exporter = CsvExporter(block_cols=_BLOCK_COLS)
    window = MainWindow(AppViewModel(session))
    qtbot.addWidget(window)

    main_ident = threading.get_ident()
    at_resolve: list[int] = []
    at_write: list[int] = []
    errors: list[Exception] = []
    base_resolve = session.resolve_signal_transient
    base_progress = ew_mod.ExportRun.progress

    def spy_resolve(key: str):  # type: ignore[no-untyped-def]
        at_resolve.append(threading.get_ident())
        return base_resolve(key)

    def spy_progress(self_run: ew_mod.ExportRun, done: int, total: int) -> None:
        at_write.append(threading.get_ident())
        base_progress(self_run, done, total)

    monkeypatch.setattr(session, "resolve_signal_transient", spy_resolve)
    monkeypatch.setattr(ew_mod.ExportRun, "progress", spy_progress)
    window._on_export_error = errors.append  # type: ignore[assignment]

    window._run_export(request, _tiny_estimate())
    qtbot.waitUntil(
        lambda: bool((request.output_path.exists() and len(at_write) >= 2) or errors),
        timeout=30000,
    )

    assert errors == [], f"エクスポートが失敗した: {errors}"
    assert at_resolve, "列解決が一度も呼ばれていない"
    assert main_ident not in at_resolve, "列解決が GUI スレッドで走っている"
    assert main_ident not in at_write, "書き出しが GUI スレッドで走っている"
    assert set(at_resolve) == set(at_write), "解決と書きが別スレッドに分かれている"


def test_cancelled_export_reports_the_pre_start_estimate(qtbot: QtBot) -> None:
    """B6: キャンセル後は開始前の見積値を再掲し、削り方を促す。"""
    from valisync.core.export.csv_exporter import ExportCancelled
    from valisync.core.export.estimate import ExportEstimate
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    est = ExportEstimate(1234, 5678, 0.66, 10_100_000_000, 600.0, 504.0)

    window._on_export_cancelled(ExportCancelled("cancelled"), est)

    msg = window.status_message()
    assert "1234" in msg and "5678" in msg
    assert "1,234" not in msg  # 桁区切りは付けない
    assert "狭め" in msg or "減らし" in msg


def test_cancel_callback_is_actually_wired_to_the_run_export_path(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    """`_on_export_cancelled` を**直呼び**するテストは `_run_export` の
    `on_cancelled=` 配線が消えても緑のまま (M-12)。**`_run_export` を実際に走らせて**
    配線そのものを効果で見る。
    """
    from valisync.core.export.csv_exporter import CsvExportOptions, ExportCancelled
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views import main_window as mw_mod
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    seen: list[tuple[Exception, object]] = []
    window._on_export_cancelled = lambda exc, est: seen.append((exc, est))  # type: ignore[assignment]
    window._confirm_export_fn = lambda _e: True
    # ExportCancelled が誤ってエラー面へ流れると本物のモーダルが開いてテストが
    # ハングする。記録に差し替えて「開かなかったこと」も同時に assert する。
    modals: list[object] = []
    monkeypatch.setattr(
        mw_mod.QMessageBox, "critical", lambda *a, **k: modals.append(a)
    )

    def boom(*_a: object, **_k: object) -> None:
        raise ExportCancelled("cancelled")

    monkeypatch.setattr(window.app_vm.session, "export_csv", boom)

    est = _tiny_estimate()
    req = _tiny_request(tmp_path, CsvExportOptions())
    window._run_export(req, est)

    qtbot.waitUntil(lambda: len(seen) == 1, timeout=5000)
    assert isinstance(seen[0][0], ExportCancelled)
    assert seen[0][1] is est, "開始前の見積が渡っていない (B6 の再掲値が別物になる)"
    # 反 vacuous: エラー面へは流れていない (ExportCancelled は正常系)。
    assert modals == []
    assert window.busy_overlay.isHidden()


def test_cancel_keeps_the_overlay_up_until_the_worker_stops(qtbot: QtBot) -> None:
    """export の cancel は load と **非対称** (即時 UI 解放をしない)。

    temp を消し切る前に「中止した」と見せると、ユーザーは残骸が消える前に次の
    エクスポートを始められ、「失敗ならファイルが存在しない」の観測窓が壊れる。

    load はアイドル (export だけが走っている) — ルータが load へ恒久配線された
    ままなら run.cancel は立たず、ここが最初に落ちる。
    """
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    release = threading.Event()
    run = window._export_controller.prepare()
    window._export_controller.submit(
        lambda: release.wait(5.0), run=run, busy=window.busy_overlay, label="out.csv"
    )
    assert not window.busy_overlay.isHidden()

    window._cancel_busy_operations()

    assert run.cancel.is_set()
    assert not window.busy_overlay.isHidden(), "worker 停止前に overlay を下ろした"
    assert window.busy_overlay.cancel_button.isEnabled() is False
    assert "中止" in window.busy_overlay.message()

    release.set()
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=5000)
    assert window.busy_overlay.cancel_button.isEnabled() is True, (
        "次の操作でキャンセルボタンが死んだまま残る"
    )


def test_run_export_hands_the_pipeline_the_progress_and_cancel_it_will_drive(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    """`_run_export` がパイプラインへ渡す progress/cancel が、**overlay とキャンセル
    ボタンに実際に繋がっている実体**であることを効果で見る。

    submit の配線 (run= / on_cancelled=) だけを見るテストは、callable の中で
    `progress=`/`cancel=` を渡し忘れても全部緑のまま — 実機では「バーが動かない」
    「押しても止まらない」が同時に起きるのに、誰も落ちない。
    """
    from valisync.core.export.csv_exporter import CsvExportOptions
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    captured: dict[str, object] = {}
    release = threading.Event()

    def fake_export(*_a: object, **kwargs: object) -> None:
        captured.update(kwargs)
        release.wait(5.0)

    monkeypatch.setattr(window.app_vm.session, "export_csv", fake_export)

    window._run_export(_tiny_request(tmp_path, CsvExportOptions()), _tiny_estimate())
    qtbot.waitUntil(lambda: "progress" in captured, timeout=5000)

    progress = captured["progress"]
    assert callable(progress), "進捗シンクがパイプラインへ渡っていない"
    progress(3, 8)  # type: ignore[operator]
    qtbot.waitUntil(
        lambda: window.busy_overlay.progress_bar.maximum() == 8, timeout=5000
    )
    assert window.busy_overlay.progress_bar.value() == 3

    cancel = captured["cancel"]
    assert isinstance(cancel, threading.Event), "キャンセル Event が渡っていない"
    assert not cancel.is_set(), "positive control: まだ立っていない"

    window.busy_overlay.cancel_requested.emit()  # 実ボタンの下流

    assert cancel.is_set(), "ボタンが立てる Event と渡した Event が別物"
    release.set()
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=5000)


def _tiny_estimate():  # type: ignore[no-untyped-def]
    from valisync.core.export.estimate import ExportEstimate

    return ExportEstimate(1, 1, 0.0, 10, 0.0, 0.0)


def _tiny_request(tmp_path: Path, options):  # type: ignore[no-untyped-def]
    from valisync.core.export.csv_exporter import ExportRequest

    return ExportRequest(
        keys=("csv_1::a",),
        output_path=tmp_path / "tiny.csv",
        options=options,
        header_resolver=list,
    )


def _big_request(tmp_path: Path):  # type: ignore[no-untyped-def]
    """進捗が 2 回以上出る規模 (ブロック境界を跨ぐ) の実セッションと ExportRequest。

    ブロック数 1 だと progress が 1 回しか呼ばれず、G6 の「done >= 2 で cancel」が
    「最後の 1 単位の直後」= 実質完走になる。**複数ブロック**が G6/G7 の前提で、
    _BLOCK_COLS の注入がそれを保証する。
    """
    from tests.mdf4_helpers import CAN, write_mdf4
    from valisync.core.export.csv_exporter import CsvExportOptions, ExportRequest
    from valisync.core.session import Session

    path = tmp_path / "big.mf4"
    ts = [round(i * 0.001, 6) for i in range(4000)]
    write_mdf4(
        path,
        [
            {
                "name": f"Ch{i:03d}",
                "bus_type": CAN,
                "timestamps": ts,
                "values": [float(i * 1000 + j) for j in range(len(ts))],
            }
            for i in range(48)
        ],
    )
    session = Session()
    key = session.load(path).key
    keys = tuple(f"{key}::Ch{i:03d}" for i in range(48))
    request = ExportRequest(
        keys=keys,
        output_path=tmp_path / "out.csv",
        options=CsvExportOptions(),
        header_resolver=list,
    )
    return session, request
