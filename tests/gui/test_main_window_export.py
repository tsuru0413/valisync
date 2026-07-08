# tests/gui/test_main_window_export.py
from __future__ import annotations

from pathlib import Path

import numpy as np
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.export.csv_exporter import CsvExportOptions
from valisync.core.models import Signal
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views import main_window as mw_mod
from valisync.gui.views.export_csv_dialog import ExportRequest
from valisync.gui.views.main_window import MainWindow


def test_export_action_disabled_until_data(qtbot: QtBot) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    assert mw.shell_actions.action("export").isEnabled() is False
    mw.app_vm.register_loaded("csv_1")  # loaded 通知で有効化
    assert mw.shell_actions.action("export").isEnabled() is True


def test_export_csv_runs_export_with_request(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    target = tmp_path / "out.csv"
    sig = Signal(
        name="csv_1::a",
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="CSV",
        bus_type="",
        source_file="",
    )
    req = ExportRequest(
        signals=[sig],
        output_path=target,
        use_unified_timeline=False,
        options=CsvExportOptions(delimiter=";"),
    )
    # ダイアログを差し替え (要求を返す)
    monkeypatch.setattr(
        mw_mod.ExportCsvDialog, "ask", classmethod(lambda cls, *a, **k: req)
    )
    # export を捕捉 (実書出はここでは不要)
    calls: list[tuple] = []
    monkeypatch.setattr(
        mw.app_vm.session, "export_csv", lambda *a, **k: calls.append((a, k))
    )
    mw.export_csv()
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=3000)
    args, _kwargs = calls[0]
    assert args[0] == [sig] and args[1] == target


def test_export_csv_cancel_does_nothing(qtbot: QtBot, monkeypatch) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    monkeypatch.setattr(
        mw_mod.ExportCsvDialog, "ask", classmethod(lambda cls, *a, **k: None)
    )
    called: list[int] = []
    monkeypatch.setattr(
        mw.app_vm.session, "export_csv", lambda *a, **k: called.append(1)
    )
    mw.export_csv()
    assert called == []
