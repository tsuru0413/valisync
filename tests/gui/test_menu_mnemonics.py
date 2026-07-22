"""実メニュー walk によるニーモニクス検査 (spec §2.4 — タプル自己申告方式は不採用)。"""

import re
from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.app import build_main_window
from valisync.gui.strings import strip_mnemonic
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.channel_browser_view import ChannelBrowserView
from valisync.gui.views.cursor_readout import CursorReadout
from valisync.gui.views.data_explorer_view import DataExplorerView
from valisync.gui.views.file_browser_view import FileBrowserView
from valisync.gui.views.graph_panel_view import GraphPanelView

_MN = re.compile(r"&(?!&)(.)")

# G-46 の表 (spec §3) — メニュー名 → {付与項目の素形: キー}
G46 = {
    "ファイル": {
        "開く…": "o",
        "データエクスプローラ": "d",
        "最近使ったファイル": "r",
        "エクスポート…": "e",
        "終了": "x",
    },
    "表示": {"テーマ": "t", "レイアウトをリセット": "r"},
    "解析": {"補間方式": "i"},
    "ヘルプ": {"ValiSync について": "a"},
}
TOP_LEVEL = {"ファイル": "f", "表示": "v", "解析": "a", "ヘルプ": "h"}


def _mnemonics_of(menu):
    """QMenu 直下の {素形テキスト: ニーモニクス小文字 or None}。"""
    out = {}
    for act in menu.actions():
        if act.isSeparator():
            continue
        m = _MN.search(act.text())
        out[strip_mnemonic(act.text())] = m.group(1).lower() if m else None
    return out


def test_menubar_mnemonics_match_g46_and_unique(qtbot):
    win = build_main_window()
    qtbot.addWidget(win)
    # トップレベル QAction を明示的に生かしたまま保持する — サブメニュー QMenu の
    # shiboken ラッパ生存は .menu() を呼んだ QAction ラッパの生存に紐づくため、
    # for ループの一時変数のみに頼ると先行アクションが GC され後続で
    # "already deleted" になる (memory gui_pyside_qaction_submenu_shiboken_lifetime)。
    top_actions = win.menuBar().actions()
    menus = {}
    for act in top_actions:
        menus[strip_mnemonic(act.text())] = act.menu()
        m = _MN.search(act.text())
        assert m and m.group(1).lower() == TOP_LEVEL[strip_mnemonic(act.text())]
    for name, expected in G46.items():
        got = _mnemonics_of(menus[name])
        assigned = {t: k for t, k in got.items() if k is not None}
        # 付与集合が G-46 と一致 (漏れ・過剰の双方向検出)
        assert assigned == expected, f"{name}: {assigned} != {expected}"
        # メニュー内で一意
        keys = [k for k in assigned.values()]
        assert len(keys) == len(set(keys))


# ─── グラフ系コンテキストメニュー: ニーモニクス非付与 walk (spec §2.4) ─────────
#
# コンテキストメニュー9面 (共有 QAction 含む) はニーモニクス対象外 — G-28 の3面
# 共有定数がニーモニクス込みで同一である制約と realgui 掴み点破壊面の最小化から
# 付与しない (§2.4)。ここではグラフ系ビルダー全数を実際に構築し、全 action/
# サブメニュー title に "&" が無い (付与しない規約そのもの) ことを検査する —
# ビルダー新設時に本テストへの登録が漏れると「載せ忘れの見逃し」になるため、
# 「グラフ系メニューを追加したら必ずここへ足す」運用を実装プランに明記している。


def _assert_no_mnemonics(menu: object, path: str = "") -> None:
    """menu (再帰的にサブメニュー含む) の全 action title に & が無いことを検査する。

    "&&" は Qt 仕様上リテラル "&" 1 文字を表すため除外する。
    """
    for act in menu.actions():  # type: ignore[attr-defined]
        if act.isSeparator():
            continue
        text = act.text()
        assert "&" not in text or "&&" in text, f"{path}: unexpected '&' in {text!r}"
        sub = act.menu()
        if sub is not None:
            _assert_no_mnemonics(sub, path=f"{path}/{text}")


def _panel_with_curve(qtbot, tmp_path: Path) -> GraphPanelView:
    """1 信号を表示済みの最小 GraphPanelView (build_curve_menu/build_axis_menu の
    entry_id/axis_index を持たせるための共通土台 — tests/gui/test_context_menus.py
    の構築手順を流用)。"""
    csv_path = tmp_path / "d.csv"
    csv_path.write_text("t,a\n0.0,1.0\n1.0,2.0\n", encoding="utf-8")
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    session = Session()
    session.load(csv_path, fmt)
    vm = GraphPanelVM(session)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    sig_key = next(s.name for s in session.signals())
    vm.add_signal(sig_key)
    view.refresh()
    return view


def test_graph_context_menus_have_no_mnemonics(qtbot, tmp_path: Path) -> None:
    """グラフ系ビルダー全数 - build_context_menu (X軸同期注入あり/なし両分岐)・
    build_curve_menu・build_axis_menu・build_x_axis_menu・build_cursor_menu・
    build_readout_menu (build_column_menu 含む再帰) - を構築し、ニーモニクス非付与
    規約 (§2.4) を実メニューで検査する。"""
    view = _panel_with_curve(qtbot, tmp_path)

    # build_context_menu: X 軸同期 getter/setter 未注入 (bare ハーネス/単独構成)。
    _assert_no_mnemonics(view.build_context_menu())

    # build_context_menu: X 軸同期 getter/setter 注入あり (GraphAreaView 経由の
    # 本番配線相当 - X軸同期(タブ内全パネル)項目が追加される分岐)。
    view_synced = GraphPanelView(
        view.vm, x_sync_getter=lambda: True, x_sync_setter=lambda _v: None
    )
    qtbot.addWidget(view_synced)
    _assert_no_mnemonics(view_synced.build_context_menu())

    eid = view.curve_keys()[0]  # type: ignore[attr-defined]
    _assert_no_mnemonics(view.build_curve_menu(eid))
    _assert_no_mnemonics(view.build_axis_menu(0))
    _assert_no_mnemonics(view.build_x_axis_menu())
    _assert_no_mnemonics(view.build_cursor_menu("A"))
    _assert_no_mnemonics(view.build_cursor_menu("B"))

    readout = CursorReadout()
    qtbot.addWidget(readout)
    _assert_no_mnemonics(readout.build_readout_menu())
    _assert_no_mnemonics(readout.build_column_menu())


# ─── ブラウザ系コンテキストメニュー: ニーモニクス非付与 walk (spec §2.4) ───────
#
# コンテキストメニュー9面のうち、グラフ系6面(上記)に続くブラウザ3面
# (channel_browser_view / file_browser_view / data_explorer_view)。同じ
# §2.4 の非付与規約 (共有 QAction・realgui 掴み点破壊面の最小化) が適用される。


def test_browser_context_menus_have_no_mnemonics(qtbot, tmp_path: Path) -> None:
    """ChannelBrowserView/FileBrowserView/DataExplorerView の build_context_menu
    を実構築し、ニーモニクス非付与規約 (§2.4) を実メニューで検査する。"""
    app_vm = AppViewModel()

    channel_view = ChannelBrowserView(ChannelBrowserVM(app_vm))
    qtbot.addWidget(channel_view)
    _assert_no_mnemonics(channel_view.build_context_menu())

    file_view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(file_view)
    _assert_no_mnemonics(file_view.build_context_menu(0))

    data_explorer_view = DataExplorerView(app_vm)
    qtbot.addWidget(data_explorer_view)
    _assert_no_mnemonics(data_explorer_view.build_context_menu(tmp_path))
