"""意味名アイコンレジストリ+実行時トークン着色 (spec §12.2)。

module import は pure (export.py が ICONS を Qt なしで参照するため) —
Qt/QtSvg の import は icon() 関数内に置く。SVG は currentColor のみ規約
(tests/gui/test_theme_icons.py が唯一の防波堤) で、呼び出し時に
Normal=chrome_text / Disabled=chrome_disabled_text へ置換して描画する。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from valisync.gui.theme import tokens

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon

ICONS_DIR = Path(__file__).resolve().parent / "icons"

# 意味名 → アセット相対パス (主 Lucide・補 Tabler は tabler/ に追加・spec §12.3)
ICONS: dict[str, str] = {
    "open": "lucide/folder-open.svg",
    "open_folder": "lucide/folder.svg",
    "export": "lucide/save.svg",
    "data_explorer": "lucide/folder-tree.svg",
    "chevron_down": "lucide/chevron-down.svg",
    "chevron_right": "lucide/chevron-right.svg",
    "chevron_left": "lucide/chevron-left.svg",
    "chevron_up": "lucide/chevron-up.svg",
}

# ツールバー(24)/メニュー(16)等の実寸を直接登録し QIcon の拡大ボケを避ける
_SIZES = (16, 20, 24, 32)


def icon(name: str) -> QIcon:
    """意味名からテーマ着色済み QIcon を生成する (未知 name は KeyError)。

    HiDPI: devicePixelRatio を乗じた物理ピクセルで描画し setDevicePixelRatio
    (QStyle.standardIcon のネイティブ HiDPI 対応からの退行防止・spec §12.2)。
    """
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    svg = (ICONS_DIR / ICONS[name]).read_text(encoding="utf-8")
    c = tokens.active().colors
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if isinstance(app, QGuiApplication) else 1.0

    ico = QIcon()
    for mode, color in (
        (QIcon.Mode.Normal, c.chrome_text),
        (QIcon.Mode.Disabled, c.chrome_disabled_text),
    ):
        data = QByteArray(svg.replace("currentColor", color.hex).encode("utf-8"))
        renderer = QSvgRenderer(data)
        for size in _SIZES:
            phys = max(1, round(size * dpr))
            pm = QPixmap(phys, phys)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            renderer.render(painter)
            painter.end()
            pm.setDevicePixelRatio(dpr)
            ico.addPixmap(pm, mode)
    return ico
