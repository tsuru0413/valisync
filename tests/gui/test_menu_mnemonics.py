"""実メニュー walk によるニーモニクス検査 (spec §2.4 — タプル自己申告方式は不採用)。"""

import re

from valisync.gui.app import build_main_window
from valisync.gui.strings import strip_mnemonic

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
