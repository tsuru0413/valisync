# ruff: noqa: RUF001, RUF002
"""GUI 文言の単一の真実 (増分D-1 文言 OS)。

- pure Python・Qt 非依存 (theme/tokens.py と同じ隔離方針)。
- 定数は日本語一次 (spec 2026-07-22-incd-strings-os-design.md §3 対訳表が出典)。
- ニーモニクスはメニューバー面のみ (G-46)。2面共有文言は素形定数＋mn() 合成。
"""

from __future__ import annotations

import re
from typing import Final

_MNEMONIC_RE = re.compile(r"\(&[^)]\)")


def mn(text: str, key: str) -> str:
    """メニューバー掲載面のニーモニクス付与形を合成する (G-46 が割当の唯一の出典)。"""
    return f"{text}(&{key})"


def strip_mnemonic(text: str) -> str:
    """表示文言からニーモニクスを除いた素形 (テストの掴み点比較用)。"""
    text = _MNEMONIC_RE.sub("", text)
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


# ── ドック名 (3面共有: windowTitle・折りたたみタイトルバー・レールタブ — G-05/06/07) ──
# 素形 (& を含めない)。参照句 REF_DIAGNOSTICS も同じ素形の合成元 (Task 5 の
# channel_browser placeholder も同定数を合成する)。
DOCK_FILE_BROWSER: Final = "ファイルブラウザ"
DOCK_CHANNEL_BROWSER: Final = "チャンネルブラウザ"
DOCK_DIAGNOSTICS: Final = "診断"
REF_DIAGNOSTICS: Final = "「診断」ドックを参照"

# ── メニューバー: トップレベル (ニーモニクス込み・G-24) ──────────────────────
MENU_FILE: Final = mn("ファイル", "F")
MENU_VIEW: Final = mn("表示", "V")
MENU_ANALYZE: Final = mn("解析", "A")
MENU_HELP: Final = mn("ヘルプ", "H")
TOOLBAR_MAIN: Final = "メイン"

# ── File メニュー (G-46) ─────────────────────────────────────────────────────
ACTION_OPEN: Final = mn("開く", "O") + "…"
# データエクスプローラ導線は素形を toolbar QAction と File メニュー QAction が共有し
# (G-39 — 旧「フォルダを開く…」との別文言を解消)、メニュー面のみ mn() を適用する。
ACTION_DATA_EXPLORER: Final = "データエクスプローラ"
STATUS_OPEN_DATA_EXPLORER: Final = "データエクスプローラを開く"
MENU_RECENT: Final = mn("最近使ったファイル", "R")
ACTION_EXPORT: Final = mn("エクスポート", "E") + "…"
ACTION_EXIT: Final = mn("終了", "X")

# ── View メニュー (G-46) ─────────────────────────────────────────────────────
MENU_THEME: Final = mn("テーマ", "T")
THEME_LIGHT: Final = "ライト"
THEME_DARK: Final = "ダーク"
THEME_AUTO_MENU_LABEL: Final = "オート（OS に合わせる）"
ACTION_RESET_LAYOUT: Final = mn("レイアウトをリセット", "R")

# ── Analyze メニュー ─────────────────────────────────────────────────────────
# 素形 — Analyze メニュー (mn() 付与) とコンテキストメニュー (素形のまま、Task 4)
# が共有する。
INTERP_METHOD: Final = "補間方式"

# ── Help メニュー (G-26) ─────────────────────────────────────────────────────
# 素形 — ダイアログ表題そのもの (QMessageBox.about 第2引数)。メニュー項目は
# mn() で付与形を合成する。
ABOUT_TITLE: Final = "ValiSync について"
ABOUT_VERSION_UNKNOWN: Final = "（バージョン不明）"

# ── Welcome CTA (E-3) ────────────────────────────────────────────────────────
# ラベル部の素形。ショートカット表記部は WelcomeView.set_open_action() が
# QAction.shortcut() から動的合成する (action.text() は不使用 — ニーモニクス付与後
# 「開く(&O)…」になり食い違うため)。
WELCOME_OPEN_LABEL: Final = "計測ファイルを開く"

# ── BusyOverlay 実文言 (workers・G-41) ───────────────────────────────────────
BUSY_LOADING_TMPL: Final = "{label} を読み込み中…"
BUSY_LOADING_MULTI_TMPL: Final = "{n} ファイルを読み込み中…"
BUSY_EXPORTING_TMPL: Final = "{label} をエクスポート中…"

# ── ステータスバー: 読込完了時の診断誘導 (判断点 #13) ────────────────────────
STATUS_DIAG_ALERT_TMPL: Final = f" ・ ⚠ 警告/エラー {{n}} 件（{REF_DIAGNOSTICS}）"
STATUS_DIAG_INFO_TMPL: Final = f" ・ ℹ 情報 {{n}} 件（{REF_DIAGNOSTICS}）"
