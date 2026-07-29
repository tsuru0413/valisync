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
