# gui-shell-controls 増分3 詳細設計（レイアウト/chrome — ショートカット・ドックトグル・Reset Layout・アイコン/バージョン）

親 spec: [2026-07-07-gui-shell-controls-design.md](2026-07-07-gui-shell-controls-design.md) §5 の **増分3**。増分1（File I/O・PR #51/#52）・増分2（タブ/パネル/ソース・PR #53/#54）は完了。本増分で gui-shell-controls の全 SH 課題を解消する。

## 1. 背景と原則

実ユーザージャーニー監査の残り4課題（`docs/audit-findings-catalog.md`）— いずれも `main_window.py` のシェル chrome。**共通点: `ShellActions`（QAction レジストリ・増分1a・docstring「SH-05/06/14 foundation」）が既に土台を用意済み**で、本増分はその上に不足分を配線・拡張する。新規ドメインロジックは無い（View 層のみ・MVVM 不変）。

| 課題 | 優先 | 欠落（現状） | 一次位置 |
|---|---|---|---|
| SH-05 | 🟠 | メニュー/アクションの mnemonic 皆無・Exit/open_folder にショートカット無し（open=Ctrl+O・export=Ctrl+E は ShellActions 済み） | `main_window.py:150-168`・`shell_actions.py` |
| SH-12 | 🟡★ | ドック `toggleViewAction()` が View メニュー限定（ツールバー導線なし）★ユーザー指摘 | `main_window.py:159-163` |
| SH-11 | 🟡 | 「Reset Layout」が無い（崩れたドック配置から復帰不能） | `main_window.py:439-462` |
| SH-14 | 🟡 | `action_data_explorer`（インライン QAction）にアイコン/ツールチップ無し・About にバージョン無し（open/export のアイコンは ShellActions 済み） | `main_window.py:176-178, 432-435` |

## 2. 決定事項（ユーザー承認済み 2026-07-08）

- **1増分でまとめて**消化（全4課題 `main_window.py`＋`shell_actions.py`・小粒・同一ファイル）。subagent-driven。
- **範囲外**: 永続化 footgun の QSettings→INI 移行（memory [[followup_settings_iniformat]] の別 follow-up・SH-11 は既存 saveState/restoreState の上に Reset を足すのみ）／空の `Analyze` メニュー（placeholder・監査課題でない）。

## 3. 詳細設計

### SH-05 キーボードショートカット/アクセラレータ（🟠）
- **mnemonic（Alt キー）**: メニュータイトルとアクション文言に `&` を付す — `&File` / `&View` / `&Analyze` / `&Help`、`E&xit`、`&About ValiSync`。日本語文言のアクション（ShellActions の「開く…」等）は Qt が末尾 `(&O)` 記法を受け付けるため、必要なら `開く(&O)…` 形式（ただし既存ショートカット Ctrl+O があるため mnemonic は menu 経由の副次導線）。**最小: 英語メニュータイトル＋Exit/About に mnemonic**。
- **不足ショートカット**: `Exit` に `Ctrl+Q`（当初 `StandardKey.Quit` を想定したが、Windows では押せない `Key_Exit` メディアキーに解決するため明示指定へ是正 — 実装時 opus review 指摘）。`open_folder` に `Ctrl+Shift+O`（`shell_actions.py` の `_add` 呼出しで付与）。既存 open=Ctrl+O・export=Ctrl+E・new tab=Ctrl+T（増分2a）は保持。
- ドックトグルのショートカットは任意（過剰付与を避け、mnemonic と可視ボタン=SH-12 を優先）。
- テスト: 各アクションの `shortcut()` が期待 QKeySequence を返す（Layer A）。mnemonic は文言に `&` を含むこと。

### SH-12 ドック表示トグルのツールバー化（🟡★）
- 3ドックの `toggleViewAction()`（既に checkable・View メニューにも表示）を**ツールバーにも `addAction`**。QToolBar 上で checkable ボタンとして表示され、押下でドック表示/非表示が切り替わる（View メニューと状態連動＝同一 QAction）。
- ツールバー構成: 既存（open/export/セパレータ/Data Explorer）の後にセパレータ＋3トグル。
- テスト: ツールバーの actions に3ドックの toggleViewAction が含まれる・トグルで `dock.isVisible()` が反転（Layer A/B）。Layer C で実クリック。

### SH-11 Reset Layout（🟡）
- **既定レイアウト捕捉**: `__init__` でドック/ツールバー構築後・`_restore_state()` の**前**に `self._default_state: QByteArray = self.saveState()` を保存（前回セッションの永続状態で上書きされる前の既定配置）。
- **Reset Layout アクション**: View メニュー（トグル群の後にセパレータ＋「Reset Layout」）→ `_reset_layout()`: `self.restoreState(self._default_state)`。saveState/restoreState は objectName 必須だが docks（`file_dock` 等）・toolbar（`main_toolbar`）とも設定済み。
- restoreState は隠れたドックも既定の可視状態へ戻す（toggleViewAction のチェックも連動）。
- テスト: ドックを移動/非表示 → `_reset_layout()` → 既定 area/可視に復帰（Layer A/B・`dock.isVisible()`／`dockWidgetArea`）。Layer C で実操作復帰。

### SH-14 ツールバーアイコン/ツールチップ・バージョン（🟡）
- **`action_data_explorer`**: 現在インライン `QAction("Data Explorer")` でアイコン/ツールチップ無し。`style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)`（or `SP_FileDialogDetailedView`）＋ `setToolTip`/`setStatusTip("データエクスプローラを開く")` を付与。open/export は ShellActions で付与済みのため、ツールバー全体でアイコン/ツールチップが揃う。
- **ツールバー表示様式**: 必要なら `toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)` でアイコン＋文言を明示（アイコンのみで意味不明を避ける）。
- **About バージョン**: `_show_about` を `importlib.metadata.version("valisync")` でバージョン取得し `ValiSync v{ver} — ADAS 信号解析デスクトップ` を表示（`PackageNotFoundError` は "unknown" にフォールバック）。
- テスト: `action_data_explorer.icon().isNull()` が False・toolTip 非空（Layer A）。About のバージョン文字列に version を含む（`_show_about` をリファクタして version 文字列を返す純関数 `_about_text()` を切り出しテスト）。

## 4. テスト戦略（親 spec の GUI テストレイヤー準拠）

- **Layer A/B（必須・CI）**: ショートカット `shortcut()` 値・mnemonic 文言・toggleViewAction のツールバー搭載＋トグルで可視反転・`_reset_layout()` の復帰・アイコン非 null・`_about_text()` の version。`QMainWindow` は headless で構築（既存 `test_main_window_*.py` パターン）。
- **Layer C（realgui・skip_unless_real_display）**: ツールバーのドックトグル実クリックで表示反転・Reset Layout 実操作復帰・実キー（Ctrl+Q 等）。
- 既存 `test_main_window_*.py`（central_stack 等）を壊さない。

## 5. 未対応（本増分外）

- 永続化 QSettings→INI 移行（memory follow-up・別タスク）。
- 空 `Analyze` メニューの中身（将来のカーソル/解析コマンド）。
- コマンドパレット（親 spec §2 将来 graft）。

## 6. 実装順（subagent-driven）

1. SH-05（ショートカット/mnemonic）— `shell_actions.py`＋`main_window.py` メニュー。
2. SH-12（ドックトグルのツールバー化）— `main_window.py` ツールバー。
3. SH-11（Reset Layout）— `main_window.py` 既定捕捉＋アクション。
4. SH-14（アイコン/ツールチップ/バージョン）— `main_window.py`＋`_about_text` 切り出し。
5. Layer C realgui スケルトン。
6. docs（catalog SH-05/11/12/14・roadmap 増分3＝gui-shell-controls 完結）。
