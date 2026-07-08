"""realgui (Layer C) 共有 conftest。

MainWindow を構築する realgui テストは save_state / _restore_state / recent_files を
通じて実 ValiSync 設定 (QSettings レジストリ) を読み書きする。tests/gui/conftest.py の
autouse 隔離は tests/realgui/ には効かないため、ここで同等の隔離を再現し、
(1) ユーザーの実設定 (ウィンドウ最大化 / ドック可視 / Recent Files) を汚さない、
(2) テスト間で状態が漏れない (あるテストが隠したドックが次テストの _restore_state へ)
ようにする。

重要: tests/gui/conftest.py と違い QT_QPA_PLATFORM=offscreen は設定しない
(realgui は実ディスプレイ + 実 OS 入力が前提。offscreen にすると実クリックが
検証できず skip_unless_real_display で全 skip される)。
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_qsettings_realgui(request, monkeypatch):  # type: ignore[no-untyped-def]
    """MainWindow / recent_files の QSettings を per-test 固有キーへ隔離。

    MainWindow を構築しないテストでは patch 対象が未使用の no-op で無害。
    """
    from PySide6.QtCore import QSettings

    import valisync.gui.views.main_window as mw
    import valisync.gui.views.recent_files as rf

    test_org = "ValiSync-Test"
    # per-test 固有 app 名で保存状態のテスト間漏れを断つ。
    test_app = f"realgui-{abs(hash(request.node.nodeid)) & 0xFFFFFFFF:08x}"
    monkeypatch.setattr(mw, "_ORG", test_org)
    monkeypatch.setattr(mw, "_APP", test_app)
    monkeypatch.setattr(rf, "_ORG", test_org)
    monkeypatch.setattr(rf, "_APP", test_app)
    yield
    QSettings(test_org, test_app).clear()
