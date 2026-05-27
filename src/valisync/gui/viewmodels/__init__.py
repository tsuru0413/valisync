"""ViewModel layer for Valisync GUI.

ViewModels are pure Python — no Qt imports — so they are testable headless.
"""

from valisync.gui.viewmodels.observable import Observable

__all__ = ["Observable"]
