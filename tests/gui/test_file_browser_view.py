"""Tests for FileBrowserView.

Tests verify:
- contains a QListView
- selection in QListView calls select_file on VM
- model is correctly set
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QListView
from pytestqt.qtbot import QtBot

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui import strings as S
from valisync.gui.adapters.qt_signal_models import FileListModel
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.views.file_browser_view import FileBrowserView


def _fmt() -> FormatDefinition:
    """CSV format for tests."""
    return FormatDefinition(
        name="test_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )


def _write_csv(path: Path) -> Path:
    """Write a minimal valid CSV and return its path."""
    path.write_text("t,speed\n0.0,10.0\n1.0,20.0\n2.0,30.0\n")
    return path


def _two_file_app_vm_with_fake_teardown(
    tmp_path: Path,
) -> tuple[AppViewModel, str, str]:
    """AppViewModel with 2 loaded files and a fake teardown (no real GC drain).

    Modeled on test_releasing_file_stays_after_loaded_rows_until_released
    (tests/gui/test_file_browser_vm.py) — the fake teardown makes unload_file
    mark the group releasing without an actual background release, so tests
    can assert on the releasing row deterministically.
    """

    class _Fake:
        def enqueue(self, key: str, group: object) -> None:
            pass

    app_vm = AppViewModel()
    app_vm.set_teardown(_Fake())
    k1 = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    k2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    return app_vm, k1, k2


def _send_context_menu_event(list_view: QListView, pos: QPoint) -> None:
    """Deliver a real ``QContextMenuEvent`` to the list's viewport at *pos*.

    This drives the SAME path a real OS right-click takes — viewport →
    ``CustomContextMenu`` policy → ``customContextMenuRequested`` — instead of
    emitting the signal directly. A regression in that routing (e.g. the context
    menu policy being dropped) is therefore caught here, not silently passed by a
    direct ``emit`` (see .claude/skills/gui-test-plan/, Layer B).
    """
    global_pos = list_view.viewport().mapToGlobal(pos)
    QApplication.sendEvent(
        list_view.viewport(),
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, global_pos),
    )


def test_view_contains_list_view(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    assert isinstance(view.list_view, QListView)


def test_selection_triggers_vm_select(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    app_vm._loaded_keys = ["a.mf4", "b.csv"]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    # Select the second item (index 1)
    index = view.model.index(1, 0)
    view.list_view.selectionModel().select(
        index, view.list_view.selectionModel().SelectionFlag.Select
    )

    # VM should be updated
    assert app_vm.active_file_key == "b.csv"


def test_empty_selection_clears_vm(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    app_vm._loaded_keys = ["a.mf4"]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    # Select first
    index = view.model.index(0, 0)
    view.list_view.selectionModel().select(
        index, view.list_view.selectionModel().SelectionFlag.Select
    )
    assert app_vm.active_file_key == "a.mf4"

    # Clear selection
    view.list_view.selectionModel().clearSelection()

    assert app_vm.active_file_key is None


def test_context_menu_remove_unloads_file(qtbot: QtBot) -> None:
    from datetime import datetime
    from pathlib import Path

    from valisync.core.models import SignalGroup

    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)  # overlay action requires comparison mode
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/b.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    view._confirm_fn = lambda _name: True  # SH-08: skip the real modal, approve
    assert vm.files == ["a.csv", "b.csv"]

    menu = view.build_context_menu(0)
    actions = menu.actions()
    # E-2a/b: reference_file_key is None here (app_vm._loaded_keys was set
    # directly, bypassing register_loaded's auto-reference), so neither row is
    # "the reference" — both new items appear for row 0 too (spec §2/§3).
    assert [act.text() for act in actions] == [
        S.ACTION_REMOVE_FILE,
        S.ACTION_SET_REFERENCE,
        S.ACTION_OVERLAY_REFERENCE,
    ]
    actions[0].trigger()

    assert vm.files == ["b.csv"]


def test_list_uses_custom_context_menu_policy(qtbot: QtBot) -> None:
    """The list MUST use CustomContextMenu so Qt emits customContextMenuRequested
    on a real right-click.

    The previous contextMenuEvent-override-on-the-container approach relied on the
    right-click propagating up from the child QListView, which does not fire — so
    the menu never appeared in the real GUI. This asserts the policy that makes the
    real-right-click signal fire.
    """
    from PySide6.QtCore import Qt

    app_vm = AppViewModel()
    app_vm._loaded_keys = ["a.mf4"]
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)

    assert view.list_view.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_right_click_on_row_opens_remove_menu_and_unloads(
    qtbot: QtBot, monkeypatch
) -> None:
    """User-operation-equivalent: send a real ``QContextMenuEvent`` to the list's
    viewport at a row's position (the SAME routing a real OS right-click drives:
    viewport → CustomContextMenu policy → customContextMenuRequested), and assert
    the 'Remove File' menu is built for that row, the row is selected, and
    triggering the action unloads the file.

    Sending the event (not emitting the signal) is what makes this a Layer-B test:
    it exercises the policy + signal wiring, so dropping the context-menu policy —
    which would break the real GUI while a direct ``emit`` still passed — fails
    here. The modal .exec() is absorbed by spying build_context_menu.
    """
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import Mock

    from valisync.core.models import SignalGroup

    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)  # overlay action requires comparison mode
    k1 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/a.csv").absolute(), "CSV", datetime.now())
    )
    k2 = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/b.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k1, k2]
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    view._confirm_fn = lambda _name: True  # SH-08: skip the real modal, approve
    view.resize(200, 200)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(
        lambda: view.list_view.visualRect(view.model.index(0, 0)).height() > 0,
        timeout=2000,
    )

    captured: dict = {}
    real_build = view.build_context_menu

    def spy_build(row: int) -> object:
        captured["row"] = row
        captured["menu"] = real_build(row)
        return Mock()  # the slot calls .exec() on this -> no-op

    monkeypatch.setattr(view, "build_context_menu", spy_build)

    # Drive a real QContextMenuEvent over row 1 (b.csv) — the SAME routing a real
    # OS right-click uses, not a direct signal emit.
    pos = view.list_view.visualRect(view.model.index(1, 0)).center()
    _send_context_menu_event(view.list_view, pos)

    assert captured["row"] == 1
    assert view.list_view.currentIndex().row() == 1
    # E-2a/b: reference_file_key is None (see test_context_menu_remove_unloads_file),
    # so both new items appear here too.
    assert [a.text() for a in captured["menu"].actions()] == [
        S.ACTION_REMOVE_FILE,
        S.ACTION_SET_REFERENCE,
        S.ACTION_OVERLAY_REFERENCE,
    ]

    captured["menu"].actions()[0].trigger()
    assert vm.files == ["a.csv"]


def test_right_click_on_empty_area_shows_no_menu(qtbot: QtBot, monkeypatch) -> None:
    """A real right-click below the items (empty area) builds no menu."""
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import Mock

    from valisync.core.models import SignalGroup

    app_vm = AppViewModel()
    k = app_vm.session._groups.add(
        SignalGroup((), Path("/path/to/a.csv").absolute(), "CSV", datetime.now())
    )
    app_vm._loaded_keys = [k]
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)
    view.resize(200, 200)
    view.show()
    qtbot.waitExposed(view)

    built: list[int] = []
    monkeypatch.setattr(
        view, "build_context_menu", lambda row: built.append(row) or Mock()
    )

    _send_context_menu_event(view.list_view, QPoint(5, 10_000))

    assert built == []  # no menu for empty space


def _load_csv(app_vm: AppViewModel, tmp_path):
    """Load a minimal CSV file and return the group key."""
    import csv

    from valisync.core.models import Delimiter, FormatDefinition

    csv_path = tmp_path / "test.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "speed"])
        writer.writerow(["0.0", "10.0"])
        writer.writerow(["1.0", "20.0"])

    format_def = FormatDefinition(
        name="test",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )

    return app_vm.request_load(csv_path, format_def)


def test_placeholder_shown_when_no_files(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)
    assert view.is_showing_placeholder()
    assert "読み込まれていません" in view.placeholder_label.text()


def test_placeholder_hidden_after_load(qtbot: QtBot, tmp_path) -> None:
    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    _load_csv(app_vm, tmp_path)
    assert not view.is_showing_placeholder()


def test_model_provides_tooltip_role(qtbot: QtBot, tmp_path) -> None:
    from PySide6.QtCore import Qt

    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    _load_csv(app_vm, tmp_path)
    index = view.model.index(0, 0)
    tip = view.model.data(index, Qt.ItemDataRole.ToolTipRole)
    assert tip and "チャンネル:" in tip


def test_releasing_row_is_non_interactive(qtbot: QtBot, tmp_path: Path) -> None:
    """releasing 行は選択不可・有効フラグ無し(クリックしても選択/close されない)。"""
    app_vm, k1, _k2 = _two_file_app_vm_with_fake_teardown(tmp_path)
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    app_vm.unload_file(k1)  # k1 -> releasing(末尾行)

    releasing_row = 1
    idx = view.model.index(releasing_row, 0)
    flags = view.model.flags(idx)
    assert not (flags & Qt.ItemFlag.ItemIsSelectable)
    assert not (flags & Qt.ItemFlag.ItemIsEnabled)

    # 実 Qt クリック(Layer B): releasing 行を押しても選択されない。
    rect = view.list_view.visualRect(idx)
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        rect.center(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.list_view.viewport(), ev)
    assert not view.list_view.selectionModel().isSelected(idx)


def test_releasing_row_exposes_spinner_state(qtbot: QtBot, tmp_path: Path) -> None:
    """delegate が読む custom role が releasing 行で True・loaded 行で False。"""
    app_vm, k1, _k2 = _two_file_app_vm_with_fake_teardown(tmp_path)
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    app_vm.unload_file(k1)
    assert view.model.data(view.model.index(1, 0), FileListModel.ReleasingRole) is True
    assert view.model.data(view.model.index(0, 0), FileListModel.ReleasingRole) is False


# ─── E-2a/b: reference/overlay menu items (spec §2/§3) ───────────────────────


def test_menu_single_file_shows_disabled_set_reference_no_overlay(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """With only 1 loaded file, that row IS the (implicit) reference — "基準に
    設定" is disabled and "基準の同名信号を重ねる" never appears (needs 2+)."""
    app_vm = AppViewModel()
    app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    actions = view.build_context_menu(0).actions()
    assert [a.text() for a in actions] == [S.ACTION_REMOVE_FILE, S.ACTION_SET_REFERENCE]
    assert actions[1].isEnabled() is False


def test_menu_on_reference_row_disables_set_reference_hides_overlay(
    qtbot: QtBot, tmp_path: Path
) -> None:
    app_vm = AppViewModel()
    app_vm.set_comparison_mode(
        True
    )  # proves is_ref gates overlay even in comparison mode
    app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())  # becomes reference
    app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    actions = view.build_context_menu(0).actions()  # row 0 = a.csv = reference
    assert [a.text() for a in actions] == [S.ACTION_REMOVE_FILE, S.ACTION_SET_REFERENCE]
    assert actions[1].isEnabled() is False


def test_menu_on_non_reference_row_enables_set_reference_shows_overlay(
    qtbot: QtBot, tmp_path: Path
) -> None:
    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)  # overlay action requires comparison mode
    app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())  # becomes reference
    app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    actions = view.build_context_menu(1).actions()  # row 1 = b.csv = non-reference
    assert [a.text() for a in actions] == [
        S.ACTION_REMOVE_FILE,
        S.ACTION_SET_REFERENCE,
        S.ACTION_OVERLAY_REFERENCE,
    ]
    assert actions[1].isEnabled() is True


def test_menu_guards_releasing_row_to_remove_file_only(
    qtbot: QtBot, tmp_path: Path
) -> None:
    app_vm, k1, _k2 = _two_file_app_vm_with_fake_teardown(tmp_path)
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    app_vm.unload_file(k1)  # k1 -> releasing row (row 1, past the loaded rows)

    actions = view.build_context_menu(1).actions()
    assert [a.text() for a in actions] == [S.ACTION_REMOVE_FILE]


def test_set_reference_action_updates_app_vm(qtbot: QtBot, tmp_path: Path) -> None:
    app_vm = AppViewModel()
    key1 = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    key2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    assert app_vm.reference_file_key == key1

    actions = view.build_context_menu(1).actions()
    next(a for a in actions if a.text() == S.ACTION_SET_REFERENCE).trigger()

    assert app_vm.reference_file_key == key2


def test_overlay_action_emits_signal_with_target_key(
    qtbot: QtBot, tmp_path: Path
) -> None:
    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)  # overlay action requires comparison mode
    app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    key2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    seen: list[str] = []
    view.overlay_reference_requested.connect(seen.append)
    actions = view.build_context_menu(1).actions()
    next(a for a in actions if a.text() == S.ACTION_OVERLAY_REFERENCE).trigger()

    assert seen == [key2]


def test_set_reference_fires_model_reset_and_updates_badge_text(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """The reference change must actually reset the Qt model (data() reads
    through to the live VM state regardless, so that alone would be a
    false-green for a broken refresh wiring — spec §6 Layer B note)."""
    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)  # reference badge requires comparison mode
    key1 = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _fmt())
    key2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _fmt())
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)

    reset_count = 0

    def _on_reset() -> None:
        nonlocal reset_count
        reset_count += 1

    view.model.modelReset.connect(_on_reset)

    actions = view.build_context_menu(1).actions()
    next(a for a in actions if a.text() == S.ACTION_SET_REFERENCE).trigger()

    assert reset_count >= 1
    assert app_vm.reference_file_key == key2
    assert view.model.data(view.model.index(0, 0)) == app_vm.session.source_name(key1)
    assert (
        view.model.data(view.model.index(1, 0))
        == app_vm.session.source_name(key2) + S.FILE_REFERENCE_BADGE_SUFFIX
    )
