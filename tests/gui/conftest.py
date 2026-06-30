import os
from pathlib import Path

import pytest

# Set Qt platform to offscreen before Qt is imported.
# This allows Qt-based tests to run in headless environments (CI, remote sessions).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolate_qsettings(tmp_path: Path) -> None:
    """Redirect IniFormat QSettings to a per-test temp dir.

    main_window.py uses QSettings(IniFormat, UserScope, ...) so that settings are
    file-based and redirectable.  NativeFormat (registry on Windows) cannot be
    redirected via setPath, which is why IniFormat is used in production code too.
    This fixture ensures tests never read or write real ValiSync app state.
    """
    from PySide6.QtCore import QSettings

    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path),
    )
