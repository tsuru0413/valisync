from __future__ import annotations

from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.loaders.mdf4_loader import ExpansionRequest, OversizedChannel
from valisync.gui.views.expansion_dialog import ExpansionDialog


def _req() -> ExpansionRequest:
    return ExpansionRequest(
        channels=(
            OversizedChannel(name="Wide", column_count=1025),
            OversizedChannel(name="Cube", column_count=4096),
        )
    )


def test_dialog_returns_checked_indices(qtbot: QtBot) -> None:
    """チェックした行のインデックス集合を返す (LD-14)."""
    dlg = ExpansionDialog(_req())
    qtbot.addWidget(dlg)
    dlg._checks[1].setChecked(True)  # Cube のみ展開
    dlg._on_accept()
    assert dlg.result_indices == {1}


def test_dialog_default_all_unchecked(qtbot: QtBot) -> None:
    """初期状態は全未チェック=全スキップ (慎重側の既定・LD-14)."""
    dlg = ExpansionDialog(_req())
    qtbot.addWidget(dlg)
    assert all(not c.isChecked() for c in dlg._checks)


def test_dialog_select_all_and_none(qtbot: QtBot) -> None:
    """全展開/全スキップ ボタンで一括トグルできる (LD-14)."""
    dlg = ExpansionDialog(_req())
    qtbot.addWidget(dlg)
    dlg._select_all()
    assert all(c.isChecked() for c in dlg._checks)
    dlg._select_none()
    assert all(not c.isChecked() for c in dlg._checks)


def test_ask_reject_returns_empty(qtbot: QtBot, monkeypatch) -> None:
    """Cancel (reject) は空集合を返す (LD-14)."""
    monkeypatch.setattr(
        ExpansionDialog, "exec", lambda self: QDialog.DialogCode.Rejected
    )
    assert ExpansionDialog.ask(_req()) == set()
