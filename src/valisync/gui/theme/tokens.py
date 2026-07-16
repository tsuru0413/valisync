"""意味名デザイントークン — 単一の真実 (spec §4.1).

pure Python (PySide6/pyqtgraph import 禁止) — pure-Python VM から import
されるため。Qt 依存の適用は theme/apply.py・QSS 生成は theme/qss.py。

トークンは必ず呼び出し時に active() で読む (module 定数・default 引数へ
束縛しない) — デバッグテーマ注入・将来のテーマ切替が効かなくなるため。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Color:
    """正規化色 (RGBA 各 0-255)。消費側フォーマッタで Qt QSS / CSS 非互換を吸収。"""

    r: int
    g: int
    b: int
    a: int = 255

    def __post_init__(self) -> None:
        for name in ("r", "g", "b", "a"):
            v = getattr(self, name)
            if not 0 <= v <= 255:
                raise ValueError(f"Color.{name}={v} は 0-255 の範囲外")

    @classmethod
    def from_hex(cls, s: str, a: int = 255) -> Color:
        if len(s) != 7 or not s.startswith("#"):
            raise ValueError(f"hex 形式は '#rrggbb': {s!r}")
        return cls(int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), a)

    @property
    def hex(self) -> str:
        """`#rrggbb` (小文字・alpha 非包含)。"""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    @property
    def rgba(self) -> tuple[int, int, int, int]:
        """`QColor(*c.rgba)` / pyqtgraph 用タプル。"""
        return (self.r, self.g, self.b, self.a)

    def qss(self) -> str:
        """Qt スタイルシート形式 — alpha は 0-255 (CSS と非互換・spec §4.1)。"""
        return f"rgba({self.r},{self.g},{self.b},{self.a})"

    def css(self) -> str:
        """Web CSS 形式 — alpha は 0-1 (エクスポータ用・増分2)。"""
        return f"rgba({self.r},{self.g},{self.b},{self.a / 255:.3f})"


@dataclass(frozen=True)
class Colors:
    # プロット面 (pyqtgraph 既定 'k'/'d' と同値凍結 — spec §4.3)
    plot_background: Color
    plot_foreground: Color
    # 信号カーブ (matplotlib tab10)
    signal_palette: tuple[Color, ...]
    # カーソル A/B (プロット線 + readout マーカー)
    cursor_a: Color
    cursor_b: Color
    # readout チップ
    surface_chip: Color
    border_chip: Color
    text_primary: Color
    text_secondary: Color
    close_hover: Color
    # アクティブ軸/パネル強調 (amber 系)
    accent_active: Color
    accent_active_dark: Color
    grip_fill: Color
    # インタラクション表示
    drop_highlight: Color
    axis_move_indicator: Color
    axis_move_fill: Color
    # ステータス/フィードバック
    error: Color
    busy_spinner: Color
    text_releasing: Color
    preview_curve: Color
    # クロム — QPalette の 12 role へ写像 (apply.build_palette・spec §4.3)。
    # cursor_b/text_secondary 等と同値の初期値があるが役割別トークン (spec §4.1)。
    chrome_window: Color
    chrome_window_text: Color
    chrome_base: Color
    chrome_alternate_base: Color
    chrome_text: Color
    chrome_button: Color
    chrome_button_text: Color
    chrome_tooltip_base: Color
    chrome_tooltip_text: Color
    chrome_highlight: Color
    chrome_highlight_text: Color
    chrome_placeholder: Color
    chrome_disabled_text: Color


@dataclass(frozen=True)
class Spacing:
    chip_margins: tuple[int, int, int, int]
    chip_vspace: int
    chip_header_hspace: int
    chip_grid_hspace: int
    chip_grid_vspace: int


@dataclass(frozen=True)
class Radii:
    chip: int
    active_frame: int


@dataclass(frozen=True)
class Typography:
    small_px: int


@dataclass(frozen=True)
class ThemeTokens:
    colors: Colors
    spacing: Spacing
    radii: Radii
    typography: Typography
    grid_alpha: int  # X グリッド線アルファ (0-255)


DARK = ThemeTokens(
    colors=Colors(
        plot_background=Color(0, 0, 0),
        plot_foreground=Color(150, 150, 150),
        signal_palette=(
            Color.from_hex("#1f77b4"),
            Color.from_hex("#ff7f0e"),
            Color.from_hex("#2ca02c"),
            Color.from_hex("#d62728"),
            Color.from_hex("#9467bd"),
            Color.from_hex("#8c564b"),
            Color.from_hex("#e377c2"),
            Color.from_hex("#7f7f7f"),
            Color.from_hex("#bcbd22"),
            Color.from_hex("#17becf"),
        ),
        cursor_a=Color.from_hex("#f9e2af"),
        cursor_b=Color.from_hex("#89b4fa"),
        surface_chip=Color(17, 17, 27, 230),
        border_chip=Color.from_hex("#45475a"),
        text_primary=Color.from_hex("#cdd6f4"),
        text_secondary=Color.from_hex("#7f849c"),
        close_hover=Color.from_hex("#f38ba8"),
        accent_active=Color.from_hex("#f59e0b"),
        accent_active_dark=Color.from_hex("#b45309"),
        grip_fill=Color.from_hex("#ffffff"),
        # palette[0] と同値だが役割別トークン (spec §4.1 — 独立に動かせるように)
        drop_highlight=Color.from_hex("#1f77b4"),
        axis_move_indicator=Color(255, 165, 0),
        axis_move_fill=Color(255, 165, 0, 60),
        error=Color.from_hex("#c0392b"),
        busy_spinner=Color(120, 160, 255),
        text_releasing=Color(128, 128, 128),
        preview_curve=Color.from_hex("#4FC3F7"),
        chrome_window=Color.from_hex("#1e1e2e"),
        chrome_window_text=Color.from_hex("#cdd6f4"),
        chrome_base=Color.from_hex("#181825"),
        chrome_alternate_base=Color.from_hex("#1e1e2e"),
        chrome_text=Color.from_hex("#cdd6f4"),
        chrome_button=Color.from_hex("#313244"),
        chrome_button_text=Color.from_hex("#cdd6f4"),
        chrome_tooltip_base=Color.from_hex("#181825"),
        chrome_tooltip_text=Color.from_hex("#cdd6f4"),
        chrome_highlight=Color.from_hex("#89b4fa"),
        chrome_highlight_text=Color.from_hex("#11111b"),
        chrome_placeholder=Color.from_hex("#7f849c"),
        chrome_disabled_text=Color.from_hex("#6c7086"),
    ),
    spacing=Spacing(
        chip_margins=(6, 5, 6, 5),
        chip_vspace=3,
        chip_header_hspace=6,
        chip_grid_hspace=8,
        chip_grid_vspace=2,
    ),
    radii=Radii(chip=5, active_frame=2),
    typography=Typography(small_px=9),
    grid_alpha=60,
)

_active: ThemeTokens = DARK


def active() -> ThemeTokens:
    """現在のテーマ。呼び出し時に読むこと (module 定数へ束縛しない)。"""
    return _active


def set_active(t: ThemeTokens) -> None:
    """テーマ差し替え (デバッグテーマ撮影・将来のテーマ切替用)。

    生成済みウィジェットへは遡及しない — ウィンドウ構築前に呼ぶこと。
    """
    global _active
    _active = t
