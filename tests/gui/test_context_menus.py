"""Tests for minimal context menus — Task 9.3 (Refactored).

Each view exposes ``build_context_menu(...)`` returning a QMenu so the actions,
their enabled/disabled (grey-out) state, and their effects can be asserted
headlessly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QWidget
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


def _fmt() -> FormatDefinition:
    return FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )


def _setup_app_2sig(tmp_path: Path) -> tuple[AppViewModel, str]:
    path = tmp_path / "d.csv"
    path.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, _fmt())
    return app_vm, key


# ─── Channel_Browser menu (R14.1) ──────────────────────────────────────────────


class TestChannelBrowserMenu:
    def _view(self, qtbot: QtBot, app_vm: AppViewModel) -> object:
        from valisync.gui.views.channel_browser_view import ChannelBrowserView

        view = ChannelBrowserView(ChannelBrowserVM(app_vm))
        qtbot.addWidget(view)
        return view

    def _select_first_row(self, view: object) -> None:
        index = view.model.index(0, 0)  # type: ignore[attr-defined]
        flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        view.tree.selectionModel().select(index, flags)  # type: ignore[attr-defined]

    def test_menu_has_add_to_panel_action(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, key = _setup_app_2sig(tmp_path)
        app_vm.set_active_file(key)
        view = self._view(qtbot, app_vm)
        self._select_first_row(view)
        assert "Add to Active Panel" in _texts(view.build_context_menu())  # type: ignore[attr-defined]

    def test_add_disabled_without_selection(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, key = _setup_app_2sig(tmp_path)
        app_vm.set_active_file(key)
        view = self._view(qtbot, app_vm)
        action = _action(view.build_context_menu(), "Add to Active Panel")  # type: ignore[attr-defined]
        assert not action.isEnabled()  # type: ignore[attr-defined]

    def test_add_enabled_with_selection(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, key = _setup_app_2sig(tmp_path)
        app_vm.set_active_file(key)
        view = self._view(qtbot, app_vm)
        self._select_first_row(view)
        action = _action(view.build_context_menu(), "Add to Active Panel")  # type: ignore[attr-defined]
        assert action.isEnabled()  # type: ignore[attr-defined]

    def test_triggering_add_emits_selected_keys(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        app_vm, key = _setup_app_2sig(tmp_path)
        app_vm.set_active_file(key)
        view = self._view(qtbot, app_vm)
        self._select_first_row(view)
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
        assert "パネルを追加" in texts
        assert "パネルを削除" in texts
        assert "すべての軸をオートフィット" in texts

    def test_remove_disabled_when_not_removable(self, qtbot: QtBot) -> None:
        panel = self._panel(qtbot)
        panel.set_removable(False)  # type: ignore[attr-defined]
        assert not _action(panel.build_context_menu(), "パネルを削除").isEnabled()  # type: ignore[attr-defined]

    def test_reset_all_axes_resets_ranges(self, qtbot: QtBot) -> None:
        panel = self._panel(qtbot)
        panel.vm.set_x_range(1.0, 2.0)  # type: ignore[attr-defined]
        panel.vm.set_y_range(3.0, 4.0)  # type: ignore[attr-defined]

        _action(panel.build_context_menu(), "すべての軸をオートフィット").trigger()  # type: ignore[attr-defined]

        # No signals plotted → reset clears to None (review finding ⑦).
        assert panel.vm.x_range is None  # type: ignore[attr-defined]
        assert panel.vm.y_range is None  # type: ignore[attr-defined]

    def test_add_panel_emits_signal(self, qtbot: QtBot) -> None:
        panel = self._panel(qtbot)
        fired: list[int] = []
        panel.add_panel_requested.connect(lambda: fired.append(1))  # type: ignore[attr-defined]
        _action(panel.build_context_menu(), "パネルを追加").trigger()  # type: ignore[attr-defined]
        assert fired == [1]

    def test_viewbox_default_menu_disabled(self, qtbot: QtBot) -> None:
        # setMenuEnabled(False) on every ViewBox suppresses pyqtgraph's default
        # "Plot Options" menu so a real right-click only raises the panel's own
        # contextMenuEvent menu. Asserted headlessly because the realgui test
        # cannot isolate it: the own modal menu wins activePopupWidget regardless
        # (see tests/realgui/test_graph_panel_menu_realclick.py scope note).
        panel = self._panel(qtbot)
        assert panel._view_boxes, "panel should build at least one ViewBox"  # type: ignore[attr-defined]
        assert all(not vb.menuEnabled() for vb in panel._view_boxes)  # type: ignore[attr-defined]

    # ─── AnalysisActions sharing (計測 IA 刷新 spec §2.2) ──────────────────────

    def test_blank_menu_includes_shared_analysis_actions(self, qtbot: QtBot) -> None:
        texts = _texts(self._panel(qtbot).build_context_menu())  # type: ignore[attr-defined]
        assert "カーソル A" in texts
        assert "カーソル B（Δ）" in texts
        assert "カーソルを消す" in texts
        assert any(
            a.text() == "補間方式" and a.menu() is not None
            for a in self._panel(qtbot).build_context_menu().actions()  # type: ignore[attr-defined]
        )

    def test_repeated_build_context_menu_reuses_same_cursor_action(
        self, qtbot: QtBot
    ) -> None:
        """自パネルのローカル AnalysisActions は build のたび作り直さない — 同一
        QAction を addAction するだけなので、右クリックのたび checked 状態が新規
        object の既定値に巻き戻ることがない。"""
        panel = self._panel(qtbot)
        first = _action(panel.build_context_menu(), "カーソル A")  # type: ignore[attr-defined]
        second = _action(panel.build_context_menu(), "カーソル A")  # type: ignore[attr-defined]
        assert first is second


# ─── Graph_Area wires panel add/remove requests (R14.3) ─────────────────────────


class TestGraphAreaPanelWiring:
    def _area(self, qtbot: QtBot) -> tuple[object, GraphAreaVM]:
        from valisync.gui.views.graph_area_view import GraphAreaView

        vm = GraphAreaVM(AppViewModel(Session()))
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
        assert not _action(menu, "パネルを削除").isEnabled()


# ─── AnalysisActions dispatch targets the right-clicked panel (spec §2.2) ───────
#
# レビュー Important 1: 右クリックは activate しない (graph_panel_view.py の
# mousePressEvent は左ボタンのみ activate_requested を emit する) ため、複数
# パネル環境で非アクティブなパネルを右クリックした場合、配送先は「アクティブ
# パネル」ではなく「右クリックされたパネル自身」でなければならない
# (toggle_main_cursor(True) の中央設置はパネルの x_range 依存 -- 誤って
# アクティブパネル基準になると、右クリックしたパネルでは画面外/端に落ちる)。
#
# 本番と同じ「1つの AnalysisActions を全パネルへ注入 (MainWindow が作る 1 セット
# を panel_factory 経由で共有)」形を再現しないと、この退行は検出できない (bare
# GraphAreaView(vm) だけだと各パネルが独立にローカル生成してしまい、そもそも
# ターゲットの取り違えが起こり得ない自明ケースになる)。


class TestContextMenuDispatchTargetsRightClickedPanel:
    def _two_panel_area_with_shared_actions(
        self, qtbot: QtBot
    ) -> tuple[object, GraphAreaVM]:
        from valisync.gui.views.analysis_actions import build_analysis_actions
        from valisync.gui.views.graph_area_view import GraphAreaView

        vm = GraphAreaVM(AppViewModel(Session()))
        vm.add_panel(0)  # PC-07: 作った=使う -> 新規パネル (index 1) が active
        # MainWindow の役割 (共有 AnalysisActions の唯一の所有者) を模す独立
        # QObject。GraphAreaView へ注入し、その panel_factory が全パネルへ同一
        # インスタンスを配る (本番の main_window.py の配線と同型)。
        # qtbot.addWidget は weakref しか保持しないため、親を持たない owner の
        # 唯一の強参照はこの関数のローカル変数のみ -- 関数を抜けると Python 側の
        # 参照カウントで即座に破棄され、QAction (owner の子) も道連れになる。
        # view に貼り付けて view と同じ寿命にする (test_main_window.py の
        # _analyze_menu で使う _keepalive と同型の対策)。
        owner = QWidget()
        qtbot.addWidget(owner)
        shared_actions = build_analysis_actions(owner)
        view = GraphAreaView(vm, analysis_actions=shared_actions)
        qtbot.addWidget(view)
        view._owner_keepalive = owner  # type: ignore[attr-defined]
        return view, vm

    def _panel(self, view: object, panel_index: int) -> object:
        return view.tabs.widget(0).widget(panel_index)  # type: ignore[attr-defined]

    def test_cursor_a_from_non_active_panel_uses_its_own_x_range(
        self, qtbot: QtBot
    ) -> None:
        view, vm = self._two_panel_area_with_shared_actions(qtbot)
        assert vm.active_panel_index(0) == 1  # panel 1 が active、panel 0 は非active

        panel0 = self._panel(view, 0)
        panel1 = self._panel(view, 1)
        panel0.vm.x_range = (0.0, 1.0)  # type: ignore[attr-defined]
        panel1.vm.x_range = (100.0, 200.0)  # type: ignore[attr-defined]

        # 同一 QAction が両パネルの空白メニューへ共有されていることの前提確認。
        assert panel0._analysis_actions is panel1._analysis_actions  # type: ignore[attr-defined]

        # 非アクティブな panel0 を右クリック -> build_context_menu() -> 「カーソル A」。
        cursor_a = _action(panel0.build_context_menu(), "カーソル A")  # type: ignore[attr-defined]
        cursor_a.trigger()

        # CursorState はタブ内共有なので両パネルから見て同じ値になるが、その値は
        # 「右クリックされた panel0」自身の x_range 中心 (0.5) でなければならない
        # -- アクティブパネル (panel1, 中心 150) 基準になっていれば退行。
        assert panel0.vm.cursor_t == pytest.approx(0.5)  # type: ignore[attr-defined]
        assert panel1.vm.cursor_t == pytest.approx(0.5)  # type: ignore[attr-defined]

    def test_two_panel_menus_opened_in_sequence_each_target_themselves(
        self, qtbot: QtBot
    ) -> None:
        """メニューはモーダル (exec) で1つずつしか開かない -- 直前に build した
        パネルの build_context_menu() が常に「今開いているメニュー」のターゲット
        になる (再ターゲット可能な共有 dispatch の中核契約)。"""
        view, vm = self._two_panel_area_with_shared_actions(qtbot)
        panel0 = self._panel(view, 0)
        panel1 = self._panel(view, 1)
        panel0.vm.x_range = (0.0, 2.0)  # type: ignore[attr-defined]
        panel1.vm.x_range = (10.0, 20.0)  # type: ignore[attr-defined]

        # panel0 を右クリック -> 「カーソル A」-> panel0 の中心 (1.0) へ設置。
        cursor_a_0 = _action(panel0.build_context_menu(), "カーソル A")  # type: ignore[attr-defined]
        cursor_a_0.trigger()
        assert vm.panels(0)[0].cursor_t == pytest.approx(1.0)  # panel0 中心

        # 続けて panel1 を右クリック -> 共有 state で既に checked=True -> 一旦 OFF。
        cursor_a_1 = _action(panel1.build_context_menu(), "カーソル A")  # type: ignore[attr-defined]
        cursor_a_1.trigger()
        assert vm.panels(0)[1].cursor_t is None

        # もう一度 panel1 を右クリック -> ON -> panel1 自身の中心 (15.0) へ設置。
        cursor_a_1_reopened = _action(panel1.build_context_menu(), "カーソル A")  # type: ignore[attr-defined]
        cursor_a_1_reopened.trigger()
        assert vm.panels(0)[1].cursor_t == pytest.approx(15.0)  # panel1 中心
