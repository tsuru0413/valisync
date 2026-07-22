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
    "export": "lucide/download.svg",
    "data_explorer": "lucide/folder-tree.svg",
    "chevron_down": "lucide/chevron-down.svg",
    "chevron_right": "lucide/chevron-right.svg",
    "chevron_left": "lucide/chevron-left.svg",
    "chevron_up": "lucide/chevron-up.svg",
    "diag_error": "lucide/circle-x.svg",
    "diag_warning": "lucide/triangle-alert.svg",
    "diag_info": "lucide/info.svg",
    "close": "lucide/x.svg",
    "float_dock": "lucide/copy.svg",
    "dock_panel_left": "lucide/panel-left.svg",
    "dock_panel_left_partial": "lucide/panel-left-close.svg",
    "dock_panel_right": "lucide/panel-right.svg",
    "dock_panel_right_partial": "lucide/panel-right-close.svg",
    "dock_panel_bottom": "lucide/panel-bottom.svg",
    "dock_panel_bottom_partial": "lucide/panel-bottom-close.svg",
}

# ツールバー(24)/メニュー(16)等の実寸を直接登録し QIcon の拡大ボケを避ける
_SIZES = (16, 20, 24, 32)


def icon(
    name: str,
    color: tokens.Color | None = None,
    active_color: tokens.Color | None = None,
    selected_color: tokens.Color | None = None,
) -> QIcon:
    """意味名からテーマ着色済み QIcon を生成する (未知 name は KeyError)。

    color=None: 現行互換 (Normal=chrome_text/Disabled=chrome_disabled_text・
    既存呼出は無変更)。color 指定時は Normal をその色で上書き (Disabled は
    引き続き chrome_disabled_text)。active_color/selected_color 指定時は
    QIcon.Mode.Active/Selected へ追加着色 (診断アイコンの選択セル可視性・
    タブ✕の hover 赤 — QSS はピクスマップ色を変えられない・spec §2.2)。

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

    modes: list[tuple[QIcon.Mode, tokens.Color]] = [
        (QIcon.Mode.Normal, color if color is not None else c.chrome_text),
        (QIcon.Mode.Disabled, c.chrome_disabled_text),
    ]
    if active_color is not None:
        modes.append((QIcon.Mode.Active, active_color))
    if selected_color is not None:
        modes.append((QIcon.Mode.Selected, selected_color))

    ico = QIcon()
    for mode, mode_color in modes:
        data = QByteArray(svg.replace("currentColor", mode_color.hex).encode("utf-8"))
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
