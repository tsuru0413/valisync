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

# ── BusyOverlay の ETA / エクスポート中止 (E-4b・spec §5.5-3 / B6) ────────────
# 「計測中…」は最初のブロックが終わるまでの表示 = 0 除算ガードの人向けの顔。
# 「仕上げ処理中…」は末尾のマージ段 — 進捗の単位は等重でないので、そこで線形
# 外挿の数字を出すと「残り 約 0 秒」と言いながら数分回る (csv_exporter の
# `n_units` コメントが根拠)。数字を出さないことが正しい表示。
BUSY_ETA_MEASURING: Final = "残り時間: 計測中…"
BUSY_ETA_TMPL: Final = "残り時間: 約 {eta}"
BUSY_ETA_FINISHING: Final = "仕上げ処理中…"
BUSY_EXPORT_CANCELLING: Final = "エクスポートを中止しています…"

# ── ステータスバー: 読込完了時の診断誘導 (判断点 #13) ────────────────────────
STATUS_DIAG_ALERT_TMPL: Final = f" ・ ⚠ 警告/エラー {{n}} 件（{REF_DIAGNOSTICS}）"
STATUS_DIAG_INFO_TMPL: Final = f" ・ ℹ 情報 {{n}} 件（{REF_DIAGNOSTICS}）"

# ── 遅延サンプル読み取り失敗 (graph_panel_vm render 境界 / main_window app フック・遅延ロード) ─
# render 境界の局所 degrade が付与する診断メッセージ (信号名を埋める)。app レベル
# フックが catch する SampleReadError は自身のメッセージ (LazyMdfValues 由来で信号名
# を含む) をそのまま出すため、SAMPLE_READ_ERROR_SOURCE のみ共有する。
SAMPLE_READ_ERROR_TMPL: Final = "信号「{name}」のサンプル読み取りに失敗しました"
SAMPLE_READ_ERROR_SOURCE: Final = "サンプル読み取り"
STATUS_SAMPLE_READ_ERROR_TMPL: Final = "⛔ {msg}"

# ── ダイアログ: CSV エクスポート (export_csv_dialog・G-19/G-38/E-1/R-07) ─────
EXPORT_DESELECT_ALL: Final = "すべて解除"
EXPORT_UNIFIED_TIMELINE_TOOLTIP: Final = "全信号を共通時間列に整列して 1 表で出力します"
EXPORT_ROUND_TRIP_LABEL: Final = "ラウンドトリップ（桁数指定なし）"
EXPORT_ROUND_TRIP_TOOLTIP: Final = "元値を損なわない最大精度で出力します"
EXPORT_CANCEL: Final = "キャンセル"
EXPORT_NO_SELECTION_ERROR: Final = "少なくとも 1 つの信号を選択してください"

# ── ダイアログ: CSV エクスポート — 出力範囲・選択数フッター (F-0・UX-28) ─────
EXPORT_RANGE_LABEL: Final = "出力範囲"
EXPORT_RANGE_ALL: Final = "全期間"
EXPORT_RANGE_VISIBLE: Final = "現在の表示範囲"
# カーソル A-B ラジオの素形 (未設置・disabled 時に表示) と、両設置時に実範囲を
# 併記するテンプレート (R-05 数値範囲=en ダッシュ・スペースなし。R-06 単位前
# スペース)。書式は file_browser_vm・signal_preview_vm の時間範囲表示と同じ
# `{:.3f}` 桁数に揃える。
EXPORT_RANGE_CURSOR: Final = "カーソル A–B"
EXPORT_RANGE_CURSOR_TMPL: Final = "カーソル A–B（{lo:.3f}–{hi:.3f} s）"
EXPORT_RANGE_OFFSET_TOOLTIP: Final = "オフセットをリセットすると範囲指定が使えます"
EXPORT_SELECTION_COUNT_TMPL: Final = "{n} 信号を選択中"

# ── ダイアログ: CSV エクスポート — 列の遅延展開 (E-3・U1) ────────────────────
# 未展開の物理チャンネル行に置くダミー子。展開した瞬間に実列へ置換されるので
# ユーザーにはほぼ見えないが、これが無いと Qt が展開矢印を描かない
# (= 列があることに気付けない)。
EXPORT_COLUMN_PLACEHOLDER: Final = "…"
# 複数列の物理チャンネル行のチェックボックスは C-a で押しても変わらない (親を
# チェック = 全列 は prod で 264k 鋳造の一撃)。ただし行は enabled のまま三態を
# 描くので、理由が無いと「押しても無反応」の無音拒否になる — 増分B が敷いた
# 「拒否は disabled 表示 + ツールチップ」の規約に合わせて理由を出す。
EXPORT_CONTAINER_ROW_TOOLTIP: Final = "展開して列を選択してください"
EXPORT_UNRESOLVED_ERROR_TMPL: Final = "選択した列を読み出せません（{n} 件・例: {name}）"

# ── エクスポート確認 (E-4b・B2 / spec §5.5) ──────────────────────────────────
# 桁区切りは付けない (既存決定・CHANNEL_HEADER_COUNT_TMPL と同規約)。列数/行数/
# 空セル率は **正確値**、サイズと時間は **推定値** — 読者がその区別を付けられるよう
# 推定側にだけ「推定」を冠する (B2)。空セル率は理由まで書かないと「壊れている」と
# 読まれる (spec §5.5 の文言例をそのまま採用)。
EXPORT_CONFIRM_TITLE: Final = "エクスポートの確認"
EXPORT_CONFIRM_BODY_TMPL: Final = (
    "{columns} 列 × {rows} 行を書き出します。\n"
    "推定サイズ: 約 {size}／推定時間: 約 {duration}\n"
    "出力の約 {empty} % は空セルです（信号ごとに記録周期が異なるため）。"
)
EXPORT_CONFIRM_YES: Final = "書き出す"  # 本文動詞と一致 (CONFIRM_CLOSE_YES と同規約)
EXPORT_CONFIRM_NO: Final = "キャンセル"
EXPORT_DISK_SHORT_TMPL: Final = (
    "保存先の空き容量が足りません（あと約 {shortfall} 必要です）。"
    "出力範囲を狭めるか列を減らしてください。"
)
# 中止後は **開始前の見積値** をそのまま再掲する (B6)。中止後に測り直さないのは、
# unload 済み/範囲変更後では値が変わってしまい「なぜ止めたのか」の手がかりに
# ならないため。桁区切りは付けない (EXPORT_CONFIRM_BODY_TMPL と同規約)。
EXPORT_CANCELLED_TMPL: Final = (
    "エクスポートを中止しました（{columns} 列 × {rows} 行・推定 {size}）。"
    "出力範囲を狭めるか列を減らして再実行してください。"
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
# 増分B: エクスポート実行中の unload 拒否 (AppViewModel.unload_file の述語ガード)。
UNLOAD_BLOCKED_BY_EXPORT: Final = "エクスポート中はファイルを閉じられません"
# 増分B: 派生信号が参照している場合の unload 拒否 (Session.remove_group の
# dependent_signals — 従来は GUI に消費者がおらず無音で何も起きなかった)。
UNLOAD_BLOCKED_BY_DEPENDENTS_TMPL: Final = (
    "派生信号 {names} が参照しているため閉じられません"
)

# ── 基準ファイル・同名重ね (E-2a/b・file_browser_view/vm・reference_overlay) ──
ACTION_SET_REFERENCE: Final = "基準に設定"
ACTION_OVERLAY_REFERENCE: Final = "基準の同名信号を重ねる"
# 表示テキスト接尾 (先頭スペース込み) — 比較モード (2 ファイル以上) のときのみ
# 基準ファイルの行に付与する (spec §2)。
FILE_REFERENCE_BADGE_SUFFIX: Final = " ◎基準"
# 重ね結果の要約 (set_status_message・timeout_ms=8000)。母数=基準エントリ。
STATUS_OVERLAY_SUMMARY_TMPL: Final = "{target} の同名信号を {n} 件重ねました{detail}"
OVERLAY_CLAUSE_NO_MATCH_TMPL: Final = "同名なし {n}"
OVERLAY_CLAUSE_UNIT_MISMATCH_TMPL: Final = "単位不一致 {n}"
OVERLAY_CLAUSE_ALREADY_TMPL: Final = "済み {n}"
OVERLAY_CLAUSE_AMBIGUOUS_TMPL: Final = "曖昧 {n}"
# E-3: 対象ファイル側の候補が配列/構造体チャンネル**本体**だった件数
# (スカラー vs 配列の構造ミスマッチ — 単位不一致と同じ粒度の語彙に揃える)。
OVERLAY_CLAUSE_CONTAINER_TMPL: Final = "構造不一致 {n}"
STATUS_OVERLAY_ALL_DONE: Final = "すべて重ね済みです"
STATUS_OVERLAY_NO_REFERENCE_SIGNALS: Final = "基準の信号がプロットされていません"

# ── 比較モード切替 (Analyze メニュー・comparison-mode-toggle spec §2/§5) ─────
# 兄弟の葉項目 (カーソル A/B・カーソルを消す) と同様ニーモニクス非付与 (spec §2 M5)。
ACTION_COMPARISON_MODE: Final = "比較モード"
TOOLTIP_COMPARISON_NEEDS_TWO: Final = (
    "設定は保持されます・2 つ以上のファイルを読み込むと再適用されます"
)
STATUS_COMPARISON_REFERENCE_TMPL: Final = (
    "比較モード: 基準ファイル={name}（右クリックで変更）"
)

# ── チャンネルブラウザ (channel_browser_view・G-16/G-18/FB-05等) ─────────────
FILTER_PLACEHOLDER: Final = "信号名でフィルタ…"  # G-16 — export_csv_dialog.py と共有
CHANNEL_PLACEHOLDER_NONE_SELECTED: Final = (
    f"{DOCK_FILE_BROWSER}でファイルを選択すると\n信号一覧を表示します"
)
CHANNEL_PLACEHOLDER_NO_CHANNELS: Final = (
    f"このファイルに信号がありません\n（詳細は「{DOCK_DIAGNOSTICS}」ドックへ）"
)
ACTION_ADD_TO_ACTIVE_PANEL: Final = "アクティブパネルへ追加"  # G-18
ACTION_SHOW_SIGNAL_PROPERTIES: Final = "信号プロパティを表示"  # 雑メモ #15

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

# ── 診断: プレースホルダ (diag-readout-consistency B2・UX-06) ─────────────────
# フィルタなし 0 件と、フィルタありの絞り込み 0 件を文言で区別する
# (2026-07-22-diag-readout-consistency-design.md §2.2)。
DIAG_EMPTY: Final = "診断はありません"
DIAG_EMPTY_FILTERED_TMPL: Final = "{level}に該当する診断はありません（全 {n} 件）"

# ── 診断: Clear 確認ダイアログ (diag-readout-consistency B5・UXG-27) ──────────
# file_browser_view の _confirm_fn 属性 DI と同型 (setText で Yes/No を上書き)。
DIAG_CLEAR_CONFIRM_TITLE: Final = "診断のクリア"
DIAG_CLEAR_CONFIRM_BODY_TMPL: Final = (
    "診断 {n} 件をクリアしますか？この操作は元に戻せません。"
)
DIAG_CLEAR_CONFIRM_YES: Final = "クリア"
DIAG_CLEAR_CONFIRM_NO: Final = "キャンセル"

# ── 信号ツリー列ヘッダ (adapters/signal_tree_model・G-43) ────────────────────
SIGNAL_TREE_COL_NAME: Final = "名前"
SIGNAL_TREE_COL_UNIT: Final = "単位"

# ── VM: チャンネルブラウザヘッダ (channel_browser_vm・G-42/R-07) ─────────────
# #14 (雑メモ解消): ファイル名プレフィックスは廃止 (件数のみ)。どのファイルかは
# 右上ファイルブラウザの選択で判別する (docs/superpowers/specs/2026-07-23-
# memo-ux-cleanup-design.md §1)。
# E-2 (列展開の遅延化): 数える単位が「信号」から **展開列** に変わったため助数詞を
# 「ch」へ (ユーザー決定 4)。1 行 = 1 物理チャンネルになった木に対し、件数だけが
# 「N 信号」のままだと行数と桁が合わず読者が数えられない。R-07 の単一パターン
# 「{n} 信号中 {m} 件を表示」と「ch は技術メタ情報に限定」を **当該箇所に限り
# 意図的に supersede** する (docs/design.md R-07・対訳表 G-42 に記録済み —
# 無記録だと次の文言スイープで「信号」へ差し戻される)。桁区切りは付けない。
CHANNEL_HEADER_NO_FILE: Final = "ファイル未選択"
CHANNEL_HEADER_EMPTY_TMPL: Final = "0 ch"
CHANNEL_HEADER_COUNT_TMPL: Final = "{total} ch 中 {shown} ch を表示"
