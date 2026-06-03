"""Tests for minimal context menus — Task 9.3.

Each view exposes ``build_context_menu(...)`` returning a QMenu so the actions,
their enabled/disabled (grey-out) state, and their effects can be asserted
headlessly.  Cross-view actions (add-to-active-panel, add/remove panel) are
emitted as Qt signals and wired by the owning container.

TDD: written before the menus exist; all must FAIL first.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QModelIndex
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

# ─── Helpers ────────────────────────────────────────────────────────────────


def _texts(menu: object) -> list[str]:
    return [a.text() for a in menu.actions()]  # type: ignore[attr-defined]


def _action(menu: object, text: str) -> object:
    return next(a for a in menu.actions() if a.text() == text)  # type: ignore[attr-defined]


def _session_2sig(tmp_path: Path) -> tuple[Session, str]:
    path = tmp_path / "d.csv"
    path.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    session = Session()
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    return session, session.load(path, fmt)


# ─── Channel_Browser menu (R14.1) ──────────────────────────────────────────────


class TestChannelBrowserMenu:
    def _view(self, qtbot: QtBot, session: Session) -> object:
        from valisync.gui.views.channel_browser_view import ChannelBrowserView

        view = ChannelBrowserView(ChannelBrowserVM(session))
        qtbot.addWidget(view)
        return view

    def _select_first_leaf(self, view: object) -> None:
        model = view.tree_model  # type: ignore[attr-defined]
        group = model.index(0, 0, QModelIndex())
        leaf = model.index(0, 0, group)
        flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        view.tree.selectionModel().select(leaf, flags)  # type: ignore[attr-defined]

    def test_menu_has_add_to_panel_action(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _session_2sig(tmp_path)
        view = self._view(qtbot, session)
        self._select_first_leaf(view)
        assert "Add to Active Panel" in _texts(view.build_context_menu())  # type: ignore[attr-defined]

    def test_add_disabled_without_selection(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _session_2sig(tmp_path)
        view = self._view(qtbot, session)
        action = _action(view.build_context_menu(), "Add to Active Panel")  # type: ignore[attr-defined]
        assert not action.isEnabled()  # type: ignore[attr-defined]

    def test_add_enabled_with_selection(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _session_2sig(tmp_path)
        view = self._view(qtbot, session)
        self._select_first_leaf(view)
        action = _action(view.build_context_menu(), "Add to Active Panel")  # type: ignore[attr-defined]
        assert action.isEnabled()  # type: ignore[attr-defined]

    def test_triggering_add_emits_selected_keys(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, key = _session_2sig(tmp_path)
        view = self._view(qtbot, session)
        self._select_first_leaf(view)
        emitted: list[list[str]] = []
        view.add_to_panel_requested.connect(emitted.append)  # type: ignore[attr-defined]

        _action(view.build_context_menu(), "Add to Active Panel").trigger()  # type: ignore[attr-defined]

        assert emitted == [[f"{key}::a"]]


# ─── Data_Explorer menu (R14.2) ────────────────────────────────────────────────


class TestDataExplorerMenu:
    def _view(self, qtbot: QtBot, app_vm: AppViewModel) -> object:
        from valisync.gui.views.data_explorer_view import DataExplorerView

        view = DataExplorerView(app_vm)
        qtbot.addWidget(view)
        return view

    def _mf4(self, tmp_path: Path) -> Path:
        return write_mdf4(
            tmp_path / "log.mf4",
            [
                {
                    "name": "s",
                    "timestamps": [0.0, 1.0],
                    "values": [1.0, 2.0],
                    "bus_type": CAN,
                }
            ],
        )

    def test_menu_items_present(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = self._view(qtbot, AppViewModel())
        texts = _texts(view.build_context_menu(self._mf4(tmp_path)))  # type: ignore[attr-defined]
        assert "Load File" in texts
        assert "Remove from Data Sources" in texts

    def test_load_enabled_for_file(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = self._view(qtbot, AppViewModel())
        menu = view.build_context_menu(self._mf4(tmp_path))  # type: ignore[attr-defined]
        assert _action(menu, "Load File").isEnabled()  # type: ignore[attr-defined]

    def test_load_disabled_for_directory(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = self._view(qtbot, AppViewModel())
        menu = view.build_context_menu(tmp_path)  # type: ignore[attr-defined]  # a dir
        assert not _action(menu, "Load File").isEnabled()  # type: ignore[attr-defined]

    def test_remove_source_grey_unless_registered(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        app_vm = AppViewModel()
        view = self._view(qtbot, app_vm)
        folder = tmp_path / "logs"
        folder.mkdir()

        # Not a source yet → disabled.
        menu = view.build_context_menu(folder)  # type: ignore[attr-defined]
        assert not _action(menu, "Remove from Data Sources").isEnabled()  # type: ignore[attr-defined]

        view.add_source(folder)  # type: ignore[attr-defined]
        menu2 = view.build_context_menu(folder)  # type: ignore[attr-defined]
        assert _action(menu2, "Remove from Data Sources").isEnabled()  # type: ignore[attr-defined]

    def test_trigger_load_loads_file(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm = AppViewModel()
        view = self._view(qtbot, app_vm)
        _action(view.build_context_menu(self._mf4(tmp_path)), "Load File").trigger()  # type: ignore[attr-defined]
        assert len(app_vm.inspect()["loaded_keys"]) == 1

    def test_trigger_remove_source(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm = AppViewModel()
        view = self._view(qtbot, app_vm)
        folder = tmp_path / "logs"
        folder.mkdir()
        view.add_source(folder)  # type: ignore[attr-defined]

        _action(view.build_context_menu(folder), "Remove from Data Sources").trigger()  # type: ignore[attr-defined]

        assert str(folder) not in view.sources()  # type: ignore[attr-defined]


# ─── Graph_Panel menu (R14.3) ──────────────────────────────────────────────────


class TestGraphPanelMenu:
    def _panel(self, qtbot: QtBot) -> object:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        view = GraphPanelView(GraphPanelVM(Session()))
        qtbot.addWidget(view)
        return view

    def test_menu_items_present(self, qtbot: QtBot) -> None:
        texts = _texts(self._panel(qtbot).build_context_menu())  # type: ignore[attr-defined]
        assert "Add Panel" in texts
        assert "Remove Panel" in texts
        assert "Reset All Axes" in texts

    def test_remove_disabled_when_not_removable(self, qtbot: QtBot) -> None:
        panel = self._panel(qtbot)
        panel.set_removable(False)  # type: ignore[attr-defined]
        assert not _action(panel.build_context_menu(), "Remove Panel").isEnabled()  # type: ignore[attr-defined]

    def test_reset_all_axes_resets_ranges(self, qtbot: QtBot) -> None:
        panel = self._panel(qtbot)
        panel.vm.set_x_range(1.0, 2.0)  # type: ignore[attr-defined]
        panel.vm.set_y_range(3.0, 4.0)  # type: ignore[attr-defined]

        _action(panel.build_context_menu(), "Reset All Axes").trigger()  # type: ignore[attr-defined]

        # No signals plotted → reset clears to None (review finding ⑦).
        assert panel.vm.x_range is None  # type: ignore[attr-defined]
        assert panel.vm.y_range is None  # type: ignore[attr-defined]

    def test_add_panel_emits_signal(self, qtbot: QtBot) -> None:
        panel = self._panel(qtbot)
        fired: list[int] = []
        panel.add_panel_requested.connect(lambda: fired.append(1))  # type: ignore[attr-defined]
        _action(panel.build_context_menu(), "Add Panel").trigger()  # type: ignore[attr-defined]
        assert fired == [1]


# ─── Graph_Area wires panel add/remove requests (R14.3) ─────────────────────────


class TestGraphAreaPanelWiring:
    def _area(self, qtbot: QtBot) -> tuple[object, GraphAreaVM]:
        from valisync.gui.views.graph_area_view import GraphAreaView

        vm = GraphAreaVM(Session())
        view = GraphAreaView(vm)
        qtbot.addWidget(view)
        return view, vm

    def _panel(self, view: object, panel_index: int) -> object:
        return view.tabs.widget(0).widget(panel_index)  # type: ignore[attr-defined]

    def test_add_request_adds_panel(self, qtbot: QtBot) -> None:
        view, vm = self._area(qtbot)
        self._panel(view, 0).add_panel_requested.emit()  # type: ignore[attr-defined]
        assert len(vm.panels(0)) == 2

    def test_remove_request_removes_panel(self, qtbot: QtBot) -> None:
        view, vm = self._area(qtbot)
        vm.add_panel(0)  # 2 panels
        self._panel(view, 1).remove_panel_requested.emit()  # type: ignore[attr-defined]
        assert len(vm.panels(0)) == 1

    def test_sole_panel_marked_not_removable(self, qtbot: QtBot) -> None:
        view, _ = self._area(qtbot)
        menu = self._panel(view, 0).build_context_menu()  # type: ignore[attr-defined]
        assert not _action(menu, "Remove Panel").isEnabled()
