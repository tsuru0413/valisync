"""Task 7 (遅延ロード 増分A): app レベル SampleReadError フックの Layer B ロジック。

MainWindow は構築時に ``sys.excepthook`` へ「最後の砦」を設置する: render 境界の
局所 degrade が届かない経路 (auto-fit / cursor-step / formula) で SampleReadError が
実イベントループへ抜けても、ダイアログでなく診断+ステータスへ落として握る。

ここでは Qt-free に近い形でフックの *ロジック* を検証する (フック関数を直接叩く /
sink の end-to-end 配線)。「実行時にプロセスが落ちない」ことそのものは実イベント
ループでしか再現できないため Layer C (tests/realgui/test_sample_read_error_realgui.py)
が担う (spec §Task 7 の honest layering)。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Signal, SignalGroup
from valisync.core.models.sample_source import SampleReadError
from valisync.core.session import LoadOutcome
from valisync.gui.viewmodels.app_viewmodel import AppViewModel


@pytest.fixture(autouse=True)
def _restore_excepthook():  # type: ignore[no-untyped-def]
    """フックがテスト間に leak しないよう sys.excepthook を保存/復元する。"""
    saved = sys.excepthook
    yield
    sys.excepthook = saved


def _make_window(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    return window


class _FailingSource:
    is_materialized = False
    length = 3
    nbytes_if_materialized = 0

    def array_if_materialized(self) -> None:
        return None

    def array(self) -> np.ndarray:
        raise SampleReadError("信号「bad」のサンプル読み取りに失敗しました: I/O")


def _register_bad_signal(session, name: str = "bad") -> str:  # type: ignore[no-untyped-def]
    sig = Signal(
        name=name,
        timestamps=np.array([0.0, 1.0, 2.0], dtype=np.float64),
        values_source=_FailingSource(),  # type: ignore[arg-type]
        file_format="MDF4",
        bus_type="",
        source_file="/net/x.mf4",
    )
    key = session._groups.add(
        SignalGroup(
            signals=(sig,),
            source_path=Path.cwd() / f"{name}.mf4",
            file_format="MDF4",
            loaded_at=datetime.now(),
        )
    )
    return session.group_signals(key)[0].name


def _register_group(session, name: str = "grp") -> str:  # type: ignore[no-untyped-def]
    """Session に最小グループを 1 つ足し、その**グループキー**を返す。"""
    sig = Signal(
        name=name,
        timestamps=np.array([0.0, 1.0], dtype=np.float64),
        values=np.array([1.0, 2.0], dtype=np.float64),
        file_format="MDF4",
        bus_type="",
        source_file="/net/x.mf4",
    )
    return session._groups.add(
        SignalGroup(
            signals=(sig,),
            source_path=Path.cwd() / f"{name}.mf4",
            file_format="MDF4",
            loaded_at=datetime.now(),
        )
    )


def _read_error(name: str, source_file: str) -> SampleReadError:
    """LazyMdfValues が実際に投げる形 (信号・ファイルのコンテキスト付き)。"""
    return SampleReadError(
        f"信号「{name}」のサンプル読み取りに失敗しました: I/O",
        signal_key=name,
        source_file=source_file,
    )


def test_hook_installed_at_construction(qtbot: QtBot) -> None:
    """MainWindow 構築で sys.excepthook が自身のフックへ差し替わる。"""
    window = _make_window(qtbot)
    assert sys.excepthook is window._sample_read_error_hook


def test_hook_records_diagnostic_and_status(qtbot: QtBot) -> None:
    """フックへ SampleReadError を渡すと診断1件+ステータスが出る (握って継続)。"""
    window = _make_window(qtbot)
    before_errors = window.diagnostics_vm.counts()[0]

    exc = SampleReadError("信号「spd」のサンプル読み取りに失敗しました: timeout")
    sys.excepthook(SampleReadError, exc, None)

    assert window.diagnostics_vm.counts()[0] == before_errors + 1
    entry = window.diagnostics_vm.entries("error")[-1]
    assert "spd" in entry.message
    assert "サンプル読み取り" in window.status_message()


def test_hook_dedupes_repeated_errors_for_one_signal(qtbot: QtBot) -> None:
    """同じ信号の SampleReadError を何度受けても診断は 1 件 (auto-fit ごとの flood 防止)。

    render 境界 (`GraphPanelVM._report_read_error`) は既に「1 信号 1 診断」だが、
    その外 (auto-fit / cursor-step / formula) から抜けたぶんは app フックが受ける。
    """
    window = _make_window(qtbot)
    before = window.diagnostics_vm.counts()[0]

    for _ in range(3):
        sys.excepthook(SampleReadError, _read_error("spd", "/net/logs/a.mf4"), None)

    assert window.diagnostics_vm.counts()[0] == before + 1

    # 対照: dedup は「1 信号 1 診断」であって「1 回だけ」ではない
    sys.excepthook(SampleReadError, _read_error("rpm", "/net/logs/a.mf4"), None)
    assert window.diagnostics_vm.counts()[0] == before + 2


def test_hook_labels_diagnostic_with_real_file_basename(qtbot: QtBot) -> None:
    """診断の source は固定文字列でなく実ファイル basename (render 境界と同じ規約)。"""
    window = _make_window(qtbot)

    sys.excepthook(SampleReadError, _read_error("spd", "/net/logs/drive_01.mf4"), None)

    entry = window.diagnostics_vm.entries("error")[-1]
    assert entry.source == "drive_01.mf4"
    assert entry.signal_name == "spd"


def test_hook_falls_back_to_generic_label_without_context(qtbot: QtBot) -> None:
    """コンテキストを持たない SampleReadError は従来どおり汎用ラベルで記録される。"""
    window = _make_window(qtbot)

    sys.excepthook(SampleReadError, SampleReadError("読めません"), None)

    entry = window.diagnostics_vm.entries("error")[-1]
    assert entry.source == "サンプル読み取り"
    assert entry.message == "読めません"


def test_hook_does_not_dedupe_when_recording_failed(qtbot: QtBot) -> None:
    """記録に失敗した回は dedup マークを立てない (握りが全抑制に化けない)。

    マークを try の**前**で立てると、シンクが投げた瞬間にその信号は診断ゼロのまま
    恒久的に無音になる — `except` は「1 回ぶんの抑制」のために置いてあるのに
    「全抑制」へ意味が変わる。変更前は診断 0 件で緑になった。
    """
    window = _make_window(qtbot)
    before = window.diagnostics_vm.counts()[0]
    calls: list[str] = []
    real_add = window.diagnostics_vm.add

    def _flaky_add(source, diags):  # type: ignore[no-untyped-def]
        calls.append(source)
        if len(calls) == 1:
            raise RuntimeError("シンクが一時的に死んだ")
        real_add(source, diags)

    window.diagnostics_vm.add = _flaky_add  # type: ignore[method-assign]

    sys.excepthook(SampleReadError, _read_error("spd", "/net/logs/a.mf4"), None)
    assert window.diagnostics_vm.counts()[0] == before, "1 回目は記録できていない前提"

    sys.excepthook(SampleReadError, _read_error("spd", "/net/logs/a.mf4"), None)

    assert len(calls) == 2, "2 回目が dedup で弾かれた (マークを早く立てている)"
    assert window.diagnostics_vm.counts()[0] == before + 1


def test_hook_dedup_marks_clear_on_load(qtbot: QtBot) -> None:
    """ロード完了はデータが変わりうる機会なので報告済みマークを解く。

    `GraphPanelVM.refresh()` が `_read_error_reported` をクリアするのと同じ理由 —
    直さなければ「一度壊れた信号は以後プロセス寿命いっぱい沈黙」になる。
    """
    window = _make_window(qtbot)
    sys.excepthook(SampleReadError, _read_error("spd", "/net/logs/a.mf4"), None)
    assert window.diagnostics_vm.counts()[0] == 1

    key = _register_group(window.app_vm.session)
    window._on_loaded(LoadOutcome(key=key))

    sys.excepthook(SampleReadError, _read_error("spd", "/net/logs/a.mf4"), None)
    assert window.diagnostics_vm.counts()[0] == 2, (
        "ロード後は再評価され、再び 1 回だけ報告されるべき"
    )


def test_hook_delegates_non_sample_read_error(qtbot: QtBot) -> None:
    """SampleReadError 以外は従来フックへ委譲する (握らない)。"""
    delegated: list[type[BaseException]] = []
    sys.excepthook = lambda t, v, tb: delegated.append(t)  # sentinel (先に設置)
    window = _make_window(qtbot)  # 直上の sentinel を prev として chain する

    before_errors = window.diagnostics_vm.counts()[0]
    err = ValueError("unrelated")
    sys.excepthook(ValueError, err, None)

    assert delegated == [ValueError], "non-SampleReadError は従来フックへ委譲されるべき"
    assert window.diagnostics_vm.counts()[0] == before_errors, (
        "SampleReadError 以外で診断を記録してはならない"
    )


def test_hook_uninstalled_on_close(qtbot: QtBot) -> None:
    """close() で sys.excepthook が構築前の値へ戻る (leak 防止)。"""
    sentinel = sys.excepthook
    window = _make_window(qtbot)
    assert sys.excepthook is not sentinel  # 設置された
    window.close()
    assert sys.excepthook is sentinel, "close 後は従来フックへ復元されるべき"


def test_render_boundary_diagnostic_flows_to_main_window(qtbot: QtBot) -> None:
    """render 境界 degrade → GraphAreaVM sink → MainWindow.diagnostics_vm の end-to-end。

    アクティブパネル VM に失敗信号をプロットし render_data() を呼ぶと、局所 degrade
    が注入済み sink 経由で MainWindow の DiagnosticsViewModel に error 診断を残す。
    (auto-fit を踏まないよう手動レンジで pin し render 境界だけを exercise する。)
    """
    window = _make_window(qtbot)
    session = window.app_vm.session
    bad_key = _register_bad_signal(session)

    panel = window.graph_area_vm.panels(0)[0]
    panel.set_x_range(0.0, 2.0)
    panel.set_axis_range(0, 0.0, 30.0)
    panel.add_signal(bad_key)

    curves = panel.render_data()  # must not raise

    assert len(curves) == 1 and len(curves[0].timestamps) == 0
    assert window.diagnostics_vm.counts()[0] == 1, (
        "render 境界の degrade 診断が MainWindow.diagnostics_vm に届いていない"
    )
    entry = window.diagnostics_vm.entries("error")[0]
    assert "bad" in entry.message
