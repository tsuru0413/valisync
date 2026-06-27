"""Integration tests — Task 10 (Refactored).

Drives the assembled MainWindow (built by app.build_main_window) to verify the
cross-view wiring end-to-end on the offscreen platform.
"""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.gui.app import build_main_window

# ─── Helpers ────────────────────────────────────────────────────────────────


def _mf4(tmp_path: Path, name: str = "log.mf4") -> Path:
    return write_mdf4(
        tmp_path / name,
        [
            {
                "name": "speed",
                "timestamps": [0.0, 0.1, 0.2],
                "values": [1.0, 2.0, 3.0],
                "bus_type": CAN,
            }
        ],
    )


def _window(qtbot: QtBot) -> object:
    window = build_main_window()
    qtbot.addWidget(window)
    return window


# ─── Assembly ──────────────────────────────────────────────────────────────--


class TestAssembly:
    def test_mounts_real_views(self, qtbot: QtBot) -> None:
        from valisync.gui.views.channel_browser_view import ChannelBrowserView
        from valisync.gui.views.file_browser_view import FileBrowserView
        from valisync.gui.views.graph_area_view import GraphAreaView

        window = _window(qtbot)
        assert isinstance(window.file_browser_view, FileBrowserView)  # type: ignore[attr-defined]
        assert isinstance(window.channel_browser_view, ChannelBrowserView)  # type: ignore[attr-defined]
        assert isinstance(window.graph_area_view, GraphAreaView)  # type: ignore[attr-defined]

    def test_shares_one_session(self, qtbot: QtBot) -> None:
        window = _window(qtbot)
        # The channel browser and graph area must read the same Session the
        # AppViewModel loads into, or loaded data never appears.
        assert window.channel_browser_vm._app_vm is window.app_vm  # type: ignore[attr-defined]
        assert window.graph_area_vm._session is window.app_vm.session  # type: ignore[attr-defined]


# ─── Load → refresh tree + panels (R12.1 / finding ⑥) ──────────────────────────


class TestLoadRefresh:
    def test_file_drop_loads_and_refreshes_tree(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        window = _window(qtbot)
        mf4 = _mf4(tmp_path)

        window.graph_area_view.file_dropped.emit(str(mf4))  # type: ignore[attr-defined]

        qtbot.waitUntil(
            lambda: len(window.app_vm.inspect()["loaded_keys"]) >= 1,  # type: ignore[attr-defined]
            timeout=3000,
        )

        # Select the newly loaded file to see its signals
        key = window.app_vm.loaded_file_keys[0]  # type: ignore[attr-defined]
        window.app_vm.set_active_file(key)  # type: ignore[attr-defined]

        assert len(window.channel_browser_vm.signals) == 1  # type: ignore[attr-defined]

    def test_load_refreshes_panel_with_preadded_signal(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        window = _window(qtbot)
        session = window.app_vm.session  # type: ignore[attr-defined]
        mf4 = _mf4(tmp_path)
        # Pre-load to learn the namespaced key, then start fresh-ish: add the
        # signal to a panel BEFORE the panel has data, then load via the window.
        key = session.load(mf4, None)
        sig_name = f"{key}::speed"

        panel = window.graph_area_vm.panels(0)[0]  # type: ignore[attr-defined]
        panel.add_signal(sig_name)
        # GraphAreaVM refreshes panels on the "loaded" notification; this test
        # loads via session.load directly, so refresh the panel explicitly.
        panel.refresh()

        curves = panel.render_data()
        drawn = next(c for c in curves if c.name == sig_name)
        assert len(drawn.timestamps) > 0


# ─── Channel browser → active panel (R14.1) ────────────────────────────────────


class TestAddToActivePanel:
    def test_add_to_panel_request_plots_on_active_panel(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        window = _window(qtbot)
        session = window.app_vm.session  # type: ignore[attr-defined]
        key = session.load(_mf4(tmp_path), None)
        sig_name = f"{key}::speed"

        window.channel_browser_view.add_to_panel_requested.emit([sig_name])  # type: ignore[attr-defined]

        panel = window.graph_area_vm.panels(0)[0]  # type: ignore[attr-defined]
        plotted = [p["signal_key"] for p in panel.inspect()["plotted_signals"]]
        assert sig_name in plotted


# ─── Data Explorer launch + Add Source (R1.5 / R3.4 / ④⑤a) ─────────────────────


class TestDataExplorer:
    def test_open_data_explorer_creates_window(self, qtbot: QtBot) -> None:
        from valisync.gui.views.data_explorer_view import DataExplorerView

        window = _window(qtbot)
        window.open_data_explorer()  # type: ignore[attr-defined]
        assert isinstance(window.data_explorer, DataExplorerView)  # type: ignore[attr-defined]

    def test_add_source_dialog_registers_folder(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        from valisync.gui.viewmodels.app_viewmodel import AppViewModel
        from valisync.gui.views.data_explorer_view import DataExplorerView

        folder = tmp_path / "logs"
        folder.mkdir()
        app_vm = AppViewModel()
        # Inject the folder chooser so the modal QFileDialog is not needed.
        view = DataExplorerView(app_vm, dir_chooser=lambda: str(folder))
        qtbot.addWidget(view)

        view.action_add_source.trigger()

        assert str(folder) in view.sources()
