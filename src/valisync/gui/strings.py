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

# ── ダイアログ: CSV エクスポート (export_csv_dialog・G-19/G-38/E-1/R-07) ─────
EXPORT_DESELECT_ALL: Final = "すべて解除"
EXPORT_UNIFIED_TIMELINE_TOOLTIP: Final = "全信号を共通時間列に整列して 1 表で出力します"
EXPORT_ROUND_TRIP_LABEL: Final = "ラウンドトリップ（桁数指定なし）"
EXPORT_ROUND_TRIP_TOOLTIP: Final = "元値を損なわない最大精度で出力します"
EXPORT_CANCEL: Final = "キャンセル"
EXPORT_NO_SELECTION_ERROR: Final = "少なくとも 1 つの信号を選択してください"

# ── ダイアログ: 展開確認 (expansion_dialog・R-02 半角括弧) ────────────────────
EXPANSION_OVER_LIMIT_TMPL: Final = (
    "以下の信号は展開すると列数が上限 ({limit}) を超えます。\n"
    "展開するものを選択してください（未選択はスキップ）。"
)

# ── ダイアログ: 信号プレビュー (signal_preview_window・R-05 em ダッシュ) ─────
PREVIEW_UNAVAILABLE: Final = "この信号はプレビューできません"
PREVIEW_TITLE_TMPL: Final = "信号プレビュー — {key}"

# ── タブ既定名 (graph_area_vm・G-40・UX-40) ───────────────────────────────────
TAB_DEFAULT_TMPL: Final = "タブ {n}"

# ── グラフパネル: 空白右クリックメニュー (graph_panel_view・G-15/G-18/G-20/★#6) ─
ACTION_ADD_PANEL: Final = "パネルを追加"
ACTION_REMOVE_PANEL: Final = "パネルを削除"
ACTION_RESET_ALL_AXES: Final = "すべての軸をオートフィット"

# ── 軸メニュー: ズーム対称対 (graph_panel_view・G-21 — build_axis_menu と
# build_x_axis_menu の2面共有・UX-51 注記削除) ────────────────────────────────
ACTION_ZOOM_OUT: Final = "ズームアウト"

# ── オフセット表示 (graph_panel_view・R-06 単一テンプレート・E-4 — ドラッグ
# tooltip/適用確認/入力ダイアログ/情報行の4画面が同じ数値書式を共有する) ───────
_OFFSET_VALUE: Final = "{delta_t:+.3f} s"
OFFSET_PREVIEW_TMPL: Final = f"Δt = {_OFFSET_VALUE}"
OFFSET_APPLY_CONFIRM_TMPL: Final = (
    f"Δt = {_OFFSET_VALUE} を適用します。対象を選択してください。"
)
OFFSET_CURRENT_TMPL: Final = f"現在のオフセット: {_OFFSET_VALUE}"
OFFSET_INFO_TMPL: Final = f"オフセット: {_OFFSET_VALUE}"

# ── ダイアログ入力ラベル (graph_panel_view・R-02 全角括弧 — 括り内容が日本語) ──
LABEL_OFFSET_ADD_DELTA: Final = "追加する Δt（秒）:"
LABEL_CURSOR_TIME_TMPL: Final = "{which} カーソルの時刻（秒）:"

# ── カーソル A/B・消去系 (analysis_actions/cursor_readout/graph_panel_view の
# 3面共有・G-28 — ニーモニクス非付与・§2.4 適用面規則) ────────────────────────
CURSOR_A: Final = "カーソル A"
CURSOR_B_DELTA: Final = "カーソル B（Δ）"
CURSOR_CLEAR: Final = "カーソルを消す"
CURSOR_B_CLEAR: Final = "カーソル B（Δ）を消す"

# ── ファイルブラウザ (file_browser_view・G-14/R-10) ───────────────────────────
# 右クリックメニュー項目・確認ダイアログ表題は同語 (spec §2.2 の setText 上書き方式)。
ACTION_REMOVE_FILE: Final = "ファイルを閉じる"
CONFIRM_CLOSE_FILE_TMPL: Final = "{filename} を閉じますか？プロット中の信号も消えます。"
CONFIRM_CLOSE_YES: Final = "閉じる"  # QMessageBox.Yes の setText (本文動詞と一致)
CONFIRM_CLOSE_NO: Final = "キャンセル"  # QMessageBox.No の setText

# ── チャンネルブラウザ (channel_browser_view・G-16/G-18/FB-05等) ─────────────
FILTER_PLACEHOLDER: Final = "信号名でフィルタ…"  # G-16 — export_csv_dialog.py と共有
CHANNEL_PLACEHOLDER_NONE_SELECTED: Final = (
    f"{DOCK_FILE_BROWSER}でファイルを選択すると\n信号一覧を表示します"
)
CHANNEL_PLACEHOLDER_NO_CHANNELS: Final = (
    f"このファイルに信号がありません\n（詳細は「{DOCK_DIAGNOSTICS}」ドックへ）"
)
ACTION_ADD_TO_ACTIVE_PANEL: Final = "アクティブパネルへ追加"  # G-18

# ── データエクスプローラ (data_explorer_view・G-09/G-12) ─────────────────────
DATA_EXPLORER_SOURCES: Final = "データソース"  # ツールバー名 (G-09)
ACTION_ADD_SOURCE: Final = "データソースを追加"
ACTION_REMOVE_SOURCE: Final = "データソースを削除"
DATA_EXPLORER_SELECT_FOLDER: Final = "データソースフォルダを選択"
ACTION_LOAD_FILE: Final = "ファイルを開く"  # G-12 — File>開く…と同一操作 (★#9)
ACTION_REMOVE_FROM_SOURCES: Final = "データソースから削除"

# ── 診断 (diagnostics_view・G-04/G-22/G-27) ───────────────────────────────────
# 他列 (レベル/#/メッセージ/対象) は不変 — ここに含めるのは変更対象のみ。
DIAG_COL_SOURCE: Final = "データソース"  # G-04
DIAG_FILTER_ALL: Final = "すべて"
DIAG_FILTER_ERRORS: Final = "エラー"
DIAG_FILTER_WARNINGS: Final = "警告"
DIAG_CLEAR: Final = "クリア"

# ── 信号ツリー列ヘッダ (adapters/signal_tree_model・G-43) ────────────────────
SIGNAL_TREE_COL_NAME: Final = "名前"
SIGNAL_TREE_COL_UNIT: Final = "単位"

# ── VM: チャンネルブラウザヘッダ (channel_browser_vm・G-42/R-07) ─────────────
CHANNEL_HEADER_EMPTY_TMPL: Final = "{name} — 0 信号"
CHANNEL_HEADER_COUNT_TMPL: Final = "{name} — {total} 信号中 {shown} 件を表示"
