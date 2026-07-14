"""Tests for FileBrowserView delete confirmation (SH-08).

Verifies: a modal confirmation gate before unload (injected via `_confirm_fn`
for testability), the menu's "Remove File" action routes through it, and
the right-click 'Remove File' menu is the surviving close affordance.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM


def _make_browser_with_file(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from valisync.gui.views.file_browser_view import FileBrowserView

    app_vm = AppViewModel()
    # Seed one loaded file (row 0 valid) before the VM's refresh runs — the same
    # direct-_loaded_keys pattern test_file_browser_view.py uses; source_name()
    # falls back to the raw key when it is not a real session group.
    app_vm._loaded_keys = ["log.mf4"]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    return app_vm, vm, view


def test_confirm_yes_unloads(qtbot: QtBot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _app, vm, view = _make_browser_with_file(qtbot)
    calls: list[int] = []
    monkeypatch.setattr(vm, "unload", lambda i: calls.append(i))
    view._confirm_fn = lambda _name: True  # stub the modal
    view._confirm_and_unload(0)
    assert calls == [0]


def test_confirm_no_does_not_unload(qtbot: QtBot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _app, vm, view = _make_browser_with_file(qtbot)
    calls: list[int] = []
    monkeypatch.setattr(vm, "unload", lambda i: calls.append(i))
    view._confirm_fn = lambda _name: False
    view._confirm_and_unload(0)
    assert calls == []


def test_menu_remove_routes_through_confirm(qtbot: QtBot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _app, vm, view = _make_browser_with_file(qtbot)
    seen: list[str] = []
    view._confirm_fn = lambda name: seen.append(name) or False  # decline
    calls: list[int] = []
    monkeypatch.setattr(vm, "unload", lambda i: calls.append(i))
    # simulate FileBrowserVM having one file so files[0] is valid
    monkeypatch.setattr(type(vm), "files", property(lambda _self: ["log.mf4"]))
    menu = view.build_context_menu(0)
    menu.actions()[0].trigger()  # "Remove File"
    assert seen == ["log.mf4"] and calls == []  # confirm consulted, declined


def test_no_close_button(qtbot: QtBot) -> None:
    """FU-05: the header 'close' button is removed; closing a file is via the
    right-click 'Remove File' menu (still covered above)."""
    _app, _vm, view = _make_browser_with_file(qtbot)
    assert view.findChild(QPushButton, "file_browser_close") is None
