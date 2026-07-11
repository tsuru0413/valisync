from __future__ import annotations

from PySide6.QtWidgets import QDialog, QScrollArea
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.loaders.mdf_loader import ExpansionRequest, OversizedChannel
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


def _many(n: int) -> ExpansionRequest:
    return ExpansionRequest(
        channels=tuple(
            OversizedChannel(name=f"Ch{i:03d}", column_count=2000) for i in range(n)
        )
    )


def test_dialog_height_clamped_to_screen_for_many_channels(qtbot: QtBot) -> None:
    """FU-01: 60 チャンネルでもダイアログ高が画面 (availableGeometry) 内に収まる。

    修正前はチェック行が layout へ直接積まれ全高 ~1900px 超で RED
    (offscreen も WM クランプが無いため sizeHint どおりに伸びる)。
    """
    dlg = ExpansionDialog(_many(60))
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    ag = dlg.screen().availableGeometry()
    assert dlg.height() <= ag.height()


def test_buttonbox_stays_within_dialog_for_many_channels(qtbot: QtBot) -> None:
    """クランプ後も OK/Cancel はダイアログ矩形内 (スクロール外の常時可視)。

    修正前も (ダイアログ自体が巨大なので) 通る — クランプが「内容あふれ」で
    なく「スクロール」で実現されていることの post-fix ガード。
    """
    from PySide6.QtWidgets import QDialogButtonBox

    dlg = ExpansionDialog(_many(60))
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    box = dlg.findChild(QDialogButtonBox)
    assert box is not None
    tl = box.mapTo(dlg, box.rect().topLeft())
    br = box.mapTo(dlg, box.rect().bottomRight())
    assert dlg.rect().contains(tl) and dlg.rect().contains(br)


def test_dialog_compact_for_few_channels(qtbot: QtBot) -> None:
    """少数チャンネルでは従来同等のコンパクト表示 (不要なスクロールを出さない)。

    修正前は QScrollArea 自体が無く findChild が None で RED (構造 RED)。
    """
    dlg = ExpansionDialog(_req())  # 既存ヘルパ: 2 チャンネル
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    scroll = dlg.findChild(QScrollArea)
    assert scroll is not None  # チェック列はスクロール領域内 (FU-01 構造)
    inner = scroll.widget()
    assert inner is not None
    assert inner.height() <= scroll.viewport().height() + 1  # スクロール不要
    ag = dlg.screen().availableGeometry()
    assert dlg.height() < ag.height() // 2  # コンパクト (画面の半分未満)
