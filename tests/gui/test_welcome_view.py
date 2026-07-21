from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.recent_files import RecentFiles
from valisync.gui.views.welcome_view import _RECENT_LABEL_MAX_W, WelcomeView


def _recent(tmp_path: Path) -> RecentFiles:
    return RecentFiles(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )


def test_cta_emits_open_requested_none(qtbot: QtBot, tmp_path: Path) -> None:
    view = WelcomeView(_recent(tmp_path))
    qtbot.addWidget(view)
    got: list[object] = []
    view.open_requested.connect(got.append)
    view.findChild(type(view.cta), "welcome_open_cta").click()
    assert got == [None]


def test_set_open_action_composes_label_and_shortcut(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """E-3: ラベル部を固定し、ショートカット部を action から動的合成する (二重スペース根治)。"""
    from PySide6.QtGui import QAction, QKeySequence

    view = WelcomeView(_recent(tmp_path))
    qtbot.addWidget(view)
    action = QAction()
    action.setShortcut(QKeySequence("Ctrl+O"))
    view.set_open_action(action)
    assert view.cta.text() == "計測ファイルを開く (Ctrl+O)"


def test_cta_tracks_shortcut_changes(qtbot: QtBot, tmp_path: Path) -> None:
    """action.changed でショートカット部のみ追随する (action.text() は使わない)。"""
    from PySide6.QtGui import QAction, QKeySequence

    view = WelcomeView(_recent(tmp_path))
    qtbot.addWidget(view)
    action = QAction()
    action.setShortcut(QKeySequence("Ctrl+O"))
    view.set_open_action(action)
    action.setShortcut(QKeySequence("Ctrl+Shift+O"))
    assert view.cta.text() == "計測ファイルを開く (Ctrl+Shift+O)"


def test_recent_row_click_emits_its_path(qtbot: QtBot, tmp_path: Path) -> None:
    # Seed 2 rows so a late-binding closure bug (every row emits the last path)
    # is caught: existing() is newest-first, so row 0 must emit the NEWEST path,
    # not the final loop value.
    a = tmp_path / "a.mf4"
    a.write_bytes(b"x")
    b = tmp_path / "b.mf4"
    b.write_bytes(b"x")
    rf = _recent(tmp_path)
    rf.add(str(a))
    rf.add(str(b))  # newest -> row 0
    view = WelcomeView(rf)
    qtbot.addWidget(view)
    view.refresh()
    assert view._recent_box.count() == 2  # rebuild produced both rows
    got: list[object] = []
    view.open_requested.connect(got.append)
    row0 = view._recent_box.itemAt(0).widget()
    assert isinstance(row0, QPushButton)
    row0.click()  # real button click -> per-row lambda -> _emit_recent
    assert got == [str(b)]  # row 0 = newest = b; late-binding bug would emit a


def test_refresh_with_no_recent_files_shows_no_rows(
    qtbot: QtBot, tmp_path: Path
) -> None:
    view = WelcomeView(_recent(tmp_path))  # empty MRU
    qtbot.addWidget(view)
    view.refresh()
    assert view._recent_box.count() == 0


def test_drop_emits_open_requested_per_file(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    a = tmp_path / "a.mf4"
    a.write_bytes(b"x")
    view = WelcomeView(_recent(tmp_path))
    qtbot.addWidget(view)
    got: list[object] = []
    view.open_requested.connect(got.append)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(a))])
    ev = QDropEvent(
        QPointF(5.0, 5.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.dropEvent(ev)
    assert [Path(p) for p in got] == [a]  # dropped file routed to open_requested


def test_drop_without_urls_emits_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtCore import QMimeData, QPointF, Qt
    from PySide6.QtGui import QDropEvent

    view = WelcomeView(_recent(tmp_path))
    qtbot.addWidget(view)
    got: list[object] = []
    view.open_requested.connect(got.append)
    mime = QMimeData()  # keep alive: QDropEvent only borrows it
    ev = QDropEvent(
        QPointF(5.0, 5.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.dropEvent(ev)
    assert got == []


class _FakeRecent:
    """existing() だけを使う WelcomeView への duck-type 注入。

    超長パスは Windows MAX_PATH(260) で実ファイル化できないため、
    実在しないパス文字列を直接返して最小幅膨張(FU-04)を再現する。
    """

    def __init__(self, paths: list[str]) -> None:
        self._paths = paths

    def existing(self) -> list[str]:
        return list(self._paths)


_LONG_PATH = "C:/" + "d" * 400 + "/m.mf4"


def test_recent_button_min_width_bounded_for_long_path(qtbot: QtBot) -> None:
    """FU-04: 超長パスでもボタン/ビューの最小幅が省略予算+余白に収まる。

    修正前 (QPushButton(path)) はパス長に比例して ~2800px となり RED。
    """
    view = WelcomeView(_FakeRecent([_LONG_PATH]))  # type: ignore[arg-type]
    qtbot.addWidget(view)
    row0 = view._recent_box.itemAt(0).widget()
    assert isinstance(row0, QPushButton)
    assert row0.minimumSizeHint().width() <= _RECENT_LABEL_MAX_W + 100
    assert view.minimumSizeHint().width() <= _RECENT_LABEL_MAX_W + 150


def test_recent_button_label_elided_but_click_and_tooltip_keep_full_path(
    qtbot: QtBot,
) -> None:
    """表示は省略・保持は完全: tooltip とクリック emit はフルパスのまま。"""
    view = WelcomeView(_FakeRecent([_LONG_PATH]))  # type: ignore[arg-type]
    qtbot.addWidget(view)
    got: list[object] = []
    view.open_requested.connect(got.append)
    row0 = view._recent_box.itemAt(0).widget()
    assert isinstance(row0, QPushButton)
    assert row0.text() != _LONG_PATH  # 省略されている
    assert "…" in row0.text()  # ElideMiddle の省略記号
    assert row0.text().endswith("m.mf4")  # 末尾のファイル名は保持
    assert row0.toolTip() == _LONG_PATH  # フルパスは tooltip で提供
    row0.click()
    assert got == [_LONG_PATH]  # クリックは表示テキストでなくフルパスを emit


def test_short_recent_path_label_not_elided(qtbot: QtBot) -> None:
    """予算内の短パスは従来どおり全文表示 (省略の副作用ガード)。

    注意: tmp_path の実パスは 70-90 字 (~600px) で省略予算 360px を超えるため
    「短い」の代表に使えない。真に短い偽パスを stub で注入する。
    """
    short = "C:/data/a.mf4"
    view = WelcomeView(_FakeRecent([short]))  # type: ignore[arg-type]
    qtbot.addWidget(view)
    row0 = view._recent_box.itemAt(0).widget()
    assert isinstance(row0, QPushButton)
    assert row0.text() == short  # elidedText は予算内の文字列を無変更で返す
    assert row0.toolTip() == short
