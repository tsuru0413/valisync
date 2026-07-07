import os

import pytest

# Set Qt platform to offscreen before Qt is imported.
# This allows Qt-based tests to run in headless environments (CI, remote sessions).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolate_qsettings(request, monkeypatch):
    """Isolate QSettings from real ValiSync state AND from other tests.

    Redirect MainWindow's save/restore to a per-test-unique registry key (no
    real user data, no cross-test pollution), and clear it on teardown so the
    registry is not littered with stale test keys.
    """
    from PySide6.QtCore import QSettings

    import valisync.gui.views.main_window as mw

    test_org = "ValiSync-Test"
    # Per-test-unique app name so saved state from one test cannot leak into another.
    test_app = f"test-{abs(hash(request.node.nodeid)) & 0xFFFFFFFF:08x}"
    monkeypatch.setattr(mw, "_ORG", test_org)
    monkeypatch.setattr(mw, "_APP", test_app)

    import valisync.gui.views.recent_files as rf

    monkeypatch.setattr(rf, "_ORG", test_org)
    monkeypatch.setattr(rf, "_APP", test_app)
    yield
    QSettings(test_org, test_app).clear()
