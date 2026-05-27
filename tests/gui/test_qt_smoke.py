"""Smoke test to verify PySide6 and Qt offscreen configuration."""

from PySide6.QtWidgets import QApplication, QWidget


def test_qapplication_creation(qapp: QApplication) -> None:
    """Verify QApplication can be created via qtbot fixture."""
    assert qapp is not None
    assert isinstance(qapp, QApplication)


def test_qwidget_creation(qapp: QApplication) -> None:
    """Verify a simple QWidget can be instantiated."""
    widget = QWidget()
    assert widget is not None
    assert isinstance(widget, QWidget)
