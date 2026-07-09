"""Tests for the drag-and-drop workflow — Task 9.2 (Refactored).

Covers the three D&D paths and the drop-highlight feedback:
- Channel_Browser signals → Graph_Panel (SignalTableModel as drag source +
  GraphPanelView as sink), including multi-select (R12.2/12.3/12.4)
- OS file manager → Graph_Area / Data_Explorer (url drops load, R12.1)
- droppable-region highlight on drag enter/leave (R12.5)
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QModelIndex, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.adapters.qt_signal_models import (
    SIGNAL_KEYS_MIME,
    SignalTableModel,
    decode_signal_keys,
)
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

# ─── Helpers ────────────────────────────────────────────────────────────────


def _fmt(n: int = 2) -> FormatDefinition:
    return FormatDefinition(
        name="fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=n,
        has_header=True,
    )


def _setup_app_2sig(tmp_path: Path) -> tuple[AppViewModel, str]:
    path = tmp_path / "d.csv"
    path.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, _fmt(2))
    app_vm.set_active_file(key)
    return app_vm, key


def _row_indexes(model: SignalTableModel) -> list[QModelIndex]:
    return [model.index(r, 0) for r in range(model.rowCount())]


def _drop_event(mime: QMimeData) -> QDropEvent:
    return QDropEvent(
        QPointF(5.0, 5.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _drag_enter_event(mime: QMimeData) -> QDragEnterEvent:
    return QDragEnterEvent(
        QPointF(5.0, 5.0).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _url_mime(path: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


# ─── Channel_Browser drag source (R12.2/12.3) ──────────────────────────────────


class TestSignalDragSource:
    def test_model_advertises_signal_mime_type(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        app_vm, _ = _setup_app_2sig(tmp_path)
        model = SignalTableModel(ChannelBrowserVM(app_vm))
        assert SIGNAL_KEYS_MIME in model.mimeTypes()

    def test_mimedata_carries_all_selected_keys(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        app_vm, key = _setup_app_2sig(tmp_path)
        model = SignalTableModel(ChannelBrowserVM(app_vm))

        mime = model.mimeData(_row_indexes(model))

        assert set(decode_signal_keys(mime)) == {f"{key}::a", f"{key}::b"}

    def test_rows_are_drag_enabled(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, _ = _setup_app_2sig(tmp_path)
        model = SignalTableModel(ChannelBrowserVM(app_vm))
        index = model.index(0, 0)

        assert model.flags(index) & Qt.ItemFlag.ItemIsDragEnabled


# ─── Signal drop → Graph_Panel (R12.4) ─────────────────────────────────────────


class TestSignalDropToPanel:
    def test_dropping_model_mime_adds_curves(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        app_vm, key = _setup_app_2sig(tmp_path)
        model = SignalTableModel(ChannelBrowserVM(app_vm))
        mime = model.mimeData(_row_indexes(model))

        panel = GraphPanelView(GraphPanelVM(app_vm.session))
        qtbot.addWidget(panel)
        panel.dropEvent(_drop_event(mime))

        assert set(panel.signal_keys_drawn()) == {f"{key}::a", f"{key}::b"}

    def test_drag_enter_highlights_panel(self, qtbot: QtBot, tmp_path: Path) -> None:
        from valisync.gui.views.graph_panel_view import GraphPanelView

        app_vm, _ = _setup_app_2sig(tmp_path)
        model = SignalTableModel(ChannelBrowserVM(app_vm))
        mime = model.mimeData(_row_indexes(model))

        panel = GraphPanelView(GraphPanelVM(app_vm.session))
        qtbot.addWidget(panel)
        panel.dragEnterEvent(_drag_enter_event(mime))
        assert panel.is_drop_highlighted()

        panel.dragLeaveEvent(QDragLeaveEvent())
        assert not panel.is_drop_highlighted()


# ─── OS file drop → Graph_Area (R12.1) ──────────────────────────────────────────


class TestFileDropToGraphArea:
    def _make_area(self, qtbot: QtBot) -> object:
        from valisync.gui.views.graph_area_view import GraphAreaView

        view = GraphAreaView(GraphAreaVM(AppViewModel(Session())))
        qtbot.addWidget(view)
        return view

    def test_file_drop_emits_file_dropped(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = self._make_area(qtbot)
        mf4 = write_mdf4(
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
        dropped: list[str] = []
        view.file_dropped.connect(dropped.append)  # type: ignore[attr-defined]

        mime = _url_mime(mf4)  # keep alive: QDropEvent only borrows it
        view.dropEvent(_drop_event(mime))  # type: ignore[attr-defined]

        assert [Path(p) for p in dropped] == [mf4]

    def test_drag_enter_highlights_area(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = self._make_area(qtbot)
        mime = _url_mime(tmp_path / "x.mf4")  # keep alive
        view.dragEnterEvent(_drag_enter_event(mime))  # type: ignore[attr-defined]
        assert view.is_drop_highlighted()  # type: ignore[attr-defined]
        view.dragLeaveEvent(QDragLeaveEvent())  # type: ignore[attr-defined]
        assert not view.is_drop_highlighted()  # type: ignore[attr-defined]

    def test_non_url_drop_is_ignored(self, qtbot: QtBot) -> None:
        view = self._make_area(qtbot)
        dropped: list[str] = []
        view.file_dropped.connect(dropped.append)  # type: ignore[attr-defined]
        plain = QMimeData()
        plain.setText("not a file")
        view.dropEvent(_drop_event(plain))  # type: ignore[attr-defined]
        assert dropped == []


# ─── OS file drop → Data_Explorer (R12.1) ──────────────────────────────────────


class TestFileDropToDataExplorer:
    def test_file_drop_loads_via_app_vm(self, qtbot: QtBot, tmp_path: Path) -> None:
        from valisync.gui.views.data_explorer_view import DataExplorerView

        mf4 = write_mdf4(
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
        app_vm = AppViewModel()
        view = DataExplorerView(app_vm)
        qtbot.addWidget(view)

        mime = _url_mime(mf4)  # keep alive
        view.dropEvent(_drop_event(mime))

        assert len(app_vm.inspect()["loaded_keys"]) == 1
