"""意味名デザイントークン — 単一の真実 (spec §4.1).

pure Python (PySide6/pyqtgraph import 禁止) — pure-Python VM から import
されるため。Qt 依存の適用は theme/apply.py・QSS 生成は theme/qss.py。

トークンは必ず呼び出し時に active() で読む (module 定数・default 引数へ
束縛しない) — デバッグテーマ注入・将来のテーマ切替が効かなくなるため。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
    chrome_frame: Color  # 領域境界線 (separator+1px枠) — border_chip と同値だが別役割
    surface_readout_panel: (
        Color  # 読み値ペイン面 — chrome_alternate_base と同値の別役割
    )
    delta_negative: Color  # Δ(B-A) 負値/基準比マイナス — close_hover と同値の別役割
    delta_positive: Color  # Δ(B-A) 正値/基準比プラス (Catppuccin green)


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
            Color.from_hex("#56B4E9"),
            Color.from_hex("#E69F00"),
            Color.from_hex("#00C08B"),
            Color.from_hex("#F0E442"),
            Color.from_hex("#FF6E4A"),
            Color.from_hex("#D98BC0"),
            Color.from_hex("#9A8CFF"),
            Color.from_hex("#C8C8C8"),
        ),
        cursor_a=Color.from_hex("#f9e2af"),
        cursor_b=Color.from_hex("#74c7ec"),
        surface_chip=Color(17, 17, 27, 230),
        border_chip=Color.from_hex("#45475a"),
        text_primary=Color.from_hex("#cdd6f4"),
        text_secondary=Color.from_hex("#9399b2"),
        close_hover=Color.from_hex("#f38ba8"),
        accent_active=Color.from_hex("#f59e0b"),
        accent_active_dark=Color.from_hex("#b45309"),
        grip_fill=Color.from_hex("#ffffff"),
        # パレット外の teal — 一時表示がどの曲線とも紛れない (UX-35)
        drop_highlight=Color.from_hex("#94e2d5"),
        axis_move_indicator=Color.from_hex("#f59e0b"),
        axis_move_fill=Color(245, 158, 11, 60),
        error=Color.from_hex("#f38ba8"),
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
        chrome_frame=Color.from_hex("#45475a"),
        surface_readout_panel=Color.from_hex("#1e1e2e"),
        delta_negative=Color.from_hex("#f38ba8"),
        delta_positive=Color.from_hex("#a6e3a1"),
    ),
    spacing=Spacing(
        chip_margins=(6, 5, 6, 5),
        chip_vspace=3,
        chip_header_hspace=6,
        chip_grid_hspace=8,
        chip_grid_vspace=2,
    ),
    radii=Radii(chip=5, active_frame=2),
    typography=Typography(small_px=10),
    grid_alpha=150,
)


LIGHT = ThemeTokens(
    colors=Colors(
        # ── プロット面据え置き (spec §11.4 — 黒キャンバス上の視認性・両テーマ共通) ──
        plot_background=DARK.colors.plot_background,
        plot_foreground=DARK.colors.plot_foreground,
        signal_palette=DARK.colors.signal_palette,
        cursor_a=DARK.colors.cursor_a,
        cursor_b=DARK.colors.cursor_b,
        accent_active=DARK.colors.accent_active,
        accent_active_dark=DARK.colors.accent_active_dark,
        grip_fill=DARK.colors.grip_fill,
        drop_highlight=DARK.colors.drop_highlight,
        axis_move_indicator=DARK.colors.axis_move_indicator,
        axis_move_fill=DARK.colors.axis_move_fill,
        preview_curve=DARK.colors.preview_curve,
        # ── テーマ化 (Catppuccin Latte — Mocha との役割対応で写像) ──────────────
        surface_chip=Color(220, 224, 232, 230),
        border_chip=Color.from_hex("#bcc0cc"),
        text_primary=Color.from_hex("#4c4f69"),
        text_secondary=Color.from_hex("#8c8fa1"),
        close_hover=Color.from_hex("#d20f39"),
        error=Color.from_hex("#c0392b"),
        busy_spinner=Color(30, 102, 245),
        text_releasing=Color(128, 128, 128),
        chrome_window=Color.from_hex("#eff1f5"),
        chrome_window_text=Color.from_hex("#4c4f69"),
        chrome_base=Color.from_hex("#e6e9ef"),
        chrome_alternate_base=Color.from_hex("#eff1f5"),
        chrome_text=Color.from_hex("#4c4f69"),
        chrome_button=Color.from_hex("#ccd0da"),
        chrome_button_text=Color.from_hex("#4c4f69"),
        chrome_tooltip_base=Color.from_hex("#e6e9ef"),
        chrome_tooltip_text=Color.from_hex("#4c4f69"),
        chrome_highlight=Color.from_hex("#1e66f5"),
        chrome_highlight_text=Color.from_hex("#dce0e8"),
        chrome_placeholder=Color.from_hex("#8c8fa1"),
        chrome_disabled_text=Color.from_hex("#9ca0b0"),
        chrome_frame=Color.from_hex("#bcc0cc"),
        surface_readout_panel=Color.from_hex("#eff1f5"),
        delta_negative=Color.from_hex("#d20f39"),
        delta_positive=Color.from_hex("#40a02b"),
    ),
    spacing=DARK.spacing,
    radii=DARK.radii,
    typography=DARK.typography,
    grid_alpha=DARK.grid_alpha,
)


class ThemeMode(Enum):
    """テーマ選択 (値は QSettings 保存形の文字列・spec §11.2)。"""

    LIGHT = "light"
    DARK = "dark"
    AUTO = "auto"


def resolve_theme(mode: ThemeMode, os_prefers_dark: bool) -> ThemeTokens:
    """mode と OS スキームからテーマセットを解決する純関数 (spec §11.2)。

    AUTO のみ os_prefers_dark を参照する。LIGHT/DARK は明示選択なので無視。
    """
    if mode is ThemeMode.LIGHT:
        return LIGHT
    if mode is ThemeMode.DARK:
        return DARK
    return DARK if os_prefers_dark else LIGHT


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
