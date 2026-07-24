"""QSettings 保存レイアウトのスキーマバージョン管理 (退行防止)。

旧版で保存された windowState blob を新コードが restoreState で適用すると、
現行のドック構造 (candidate A のレールドック) と食い違い、show() 描画時に
ネイティブクラッシュ (0xC0000005) する退行があった。_STATE_VERSION の突合で
互換性のない古い状態を破棄して既定レイアウトで起動することを検証する。
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.app import build_main_window
from valisync.gui.views import main_window as mw
from valisync.gui.views.main_window import _STATE_VERSION


def _settings() -> QSettings:
    # conftest が mw._ORG/_APP を実行時に隔離用へ monkeypatch しているため、
    # 値コピーでなく実行時のモジュール属性を参照する (アプリと同じ store を見る)。
    return QSettings(mw._ORG, mw._APP)


def test_stale_state_without_version_is_discarded(qtbot: QtBot) -> None:
    """stateVersion 欠落 (旧版相当) の保存状態は復元されず、stale キーは除去される。"""
    # 旧版相当の保存を模擬: saveState() (version 引数なし=旧版) の blob を
    # stateVersion キーなしで書く。
    win0 = build_main_window()
    qtbot.addWidget(win0)
    win0.file_dock.hide()
    old_ws = win0.saveState()  # 旧版相当 (version 0)
    old_geo = win0.saveGeometry()
    s = _settings()
    s.setValue("windowState", old_ws)  # stateVersion は意図的に書かない (=欠落)
    s.setValue("geometry", old_geo)
    s.setValue("dockCollapsed", {"file_dock": True})
    s.sync()

    # 新コードの _restore_state: stateVersion 欠落 (=0) != _STATE_VERSION → 破棄。
    win = build_main_window()
    qtbot.addWidget(win)
    assert win._state_restored is False  # 旧状態は適用されない

    s2 = _settings()
    assert s2.value("windowState") is None
    assert s2.value("geometry") is None
    assert s2.value("dockCollapsed") is None


def test_matching_version_state_is_restored(qtbot: QtBot) -> None:
    """現行 _STATE_VERSION で保存した状態は次回起動で復元される (round-trip)。"""
    win1 = build_main_window()
    qtbot.addWidget(win1)
    win1.file_dock.hide()
    win1.save_state()  # stateVersion=_STATE_VERSION で保存

    win2 = build_main_window()
    qtbot.addWidget(win2)
    assert win2._state_restored is True  # 現行版の状態は復元される
    assert win2.file_dock.isHidden()  # hide 状態も復元される


def test_save_state_writes_current_version(qtbot: QtBot) -> None:
    """save_state は現行 _STATE_VERSION を QSettings へ書く。"""
    win = build_main_window()
    qtbot.addWidget(win)
    win.save_state()
    assert _settings().value("stateVersion", 0, type=int) == _STATE_VERSION
