"""Application entry point (Task 6.2).

``main()`` is registered as the ``valisync`` console-script in pyproject.toml.
The assembly (Session + ViewModels + MainWindow) is factored into
``build_main_window`` so it can be exercised in unit tests without blocking
on ``QApplication.exec()``.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def build_main_window(app_vm: AppViewModel | None = None) -> MainWindow:
    """Wire the ViewModel and View layers and return a ready-to-show MainWindow.

    Parameters
    ----------
    app_vm:
        An existing ``AppViewModel`` to use.  A fresh one (backed by a new
        ``Session``) is created when *None*.  Passing a custom VM is useful
        for integration tests.
    """
    if app_vm is None:
        session = Session()
        app_vm = AppViewModel(session)
    return MainWindow(app_vm)


def main() -> int:
    """Create the QApplication, build the window, run the event loop.

    Returns
    -------
    int
        The exit code returned by ``QApplication.exec()`` (0 on clean exit).
    """
    # Re-use an existing QApplication if one was already created (e.g. in tests
    # driven by pytest-qt's qapp fixture); otherwise create one.
    app = QApplication.instance() or QApplication(sys.argv)
    window = build_main_window()
    window.show()
    # QApplication.instance() returns QCoreApplication | None; we just
    # created/retrieved a QApplication so cast is safe.
    assert isinstance(app, QApplication)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
