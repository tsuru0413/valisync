# 折りたたみ可能ドック（collapsible-docks）設計

日付: 2026-07-20 ／ ステータス: 承認済み（brainstorming）
出自: UIUX 再設計プログラム**増分C** — claude.ai/design 検討の inbox 決定メモ③
（Diagnostics ドロワー化）＋ユーザー要望「File/Channel も折りたたみ可能に」。過去に
defer した **FU-14（ドックの最小化/折りたたみ）を実現**する。プログラム全体 A〜F の3番目。

## 1. 背景・問題

Diagnostics は下部の常設 QDockWidget で、空でも「診断はありません」の広い面積を占め
地位が過大（inbox メモ③・UIUX 監査）。当初は Diagnostics のみドロワー化する案だったが、
ユーザーが「File/Channel も折りたたみたい」と要望 → **3ドック共通の折りたたみ機構**へ拡張。
QDockWidget に最小化フラグは無く、FU-14 が「独自実装要」で defer された機能を今回実装する。

## 2. 要件（確定した設計判断）

- **対象**: File Browser / Channel Browser / Diagnostics の3ドックに共通の折りたたみを付ける
- **一様**: 3ドックとも畳むと**タイトルバーのみ**（Diagnostics に件数バッジ/最新メッセージ等の
  特別要約は**出さない** — ユーザー確定）
- **ドック機構は維持**: フロート/閉じるは残す（コンセプト 3a）。折りたたみトグルを足す
- **永続**: 折りたたみ状態を QSettings で保存し再起動後も復元（ユーザー確定）
- **トークン変更なし**: 畳んだ Diagnostics に色付きバッジを出さないため `warning` トークンは
  消費者がなく、**今回は導入しない**（消費者のいないトークン先行導入は避ける方針）
- **スコープ外**: 診断絵文字グリフ（⛔⚠ℹ）の SVG 置換（展開時のテーブル/カウントは現状維持・
  別 follow-up）・比較データモデル等

## 3. アーキテクチャ（§1）

QDockWidget に最小化フラグは無いので、**再利用可能なタイトルバーウィジェットを composition で
差す**（サブクラス化しない — File/Channel は MainWindow が素の QDockWidget で生成、Diagnostics は
既にサブクラスで不揃いのため、composition が3ドックに一様に効く）。

**新コンポーネント `CollapsibleDockTitleBar(QWidget)`**（新規1ファイル・`gui/views/`）:
- 構成: 折りたたみトグル（chevron ▶/▼・`theme/icons.py` の Lucide 基盤・着色 `chrome_text`）／
  タイトルラベル／フロートボタン／閉じるボタン
- 配線: `dock.setTitleBarWidget(self)`。setTitleBarWidget は Qt 既定タイトルバー（フロート/閉じる）
  を置換するため、フロート＝`dock.setFloating(not dock.isFloating())`・閉じる＝`dock.close()` を
  自前で実装する
- `collapse(collapsed: bool)`: True で `dock.widget().hide()`＋`dock.setMaximumHeight(タイトルバー高)`、
  False で `dock.setMaximumHeight(QWIDGETSIZE_MAX)`＋`dock.widget().show()`。QDockWidget の
  タイトルバーは常に水平・上端なので、右ドックも下ドックも「高さクランプ＝細い水平ストリップ」で
  一貫。状態変化を Signal で通知（MainWindow が永続化）
- `is_collapsed() -> bool` introspection

**MainWindow 側**: 3ドックそれぞれに `CollapsibleDockTitleBar` を差す。collapse 状態変化を購読して
QSettings へ保存。

**Qt の癖への留意**: QMainWindow のドックレイアウトは min/max サイズに素直に従わない場合があり
FU-14 が defer された所以 — **実際に縮むかは Layer C 実機で必ず検証**（memory
gui_isvisible_true_for_offscreen_hidden_dock: offscreen は隠しドックでも isVisible True・幅も縮まない）。

## 4. 永続化（§2）

collapse 状態は Qt の `saveState()` に含まれない（独自機能）ため別キーで保存する。

- **保存**: `MainWindow.save_state()`（closeEvent 経由）に `dockCollapsed` キーで
  `{dock.objectName(): collapsed_bool}` を QSettings へ保存する処理を追加
- **復元順序**: `_restore_state()` は `restoreState(windowState)` でドックのサイズ/配置を戻すが、
  collapse の実体（内容 hide＋maxHeight クランプ）は runtime プロパティで saveState に乗らない。
  よって **`_restore_state()` の後に保存済み collapse 状態を各タイトルバーへ再適用**する。これは
  corner 再適用（`_apply_dock_corners`）と同じ「restoreState 後に独自状態を再適用」パターン
  （memory gui_restorestate_resets_dock_corner_config の教訓）
- **Reset Layout**: `_reset_layout()` は既定配置へ戻すので collapse も**全展開へリセット**して再適用
- **float との直交**: collapse 状態はフロート/ドッキングと独立に保持（畳んだままフロートは細い
  タイトルバーウィンドウ — 稀だが異常でない・特別扱いしない）
- QSettings は conftest で隔離済み（`_ORG/_APP`）

## 5. 検証（§3）

**Layer B（CI）**:
- `CollapsibleDockTitleBar` 単体: collapse(True/False) で内容 hide/show・maxHeight クランプの
  設定/解除・状態 Signal 発火・フロートボタン→`setFloating`・閉じるボタン→`close`
- MainWindow 配線: 3ドックにタイトルバーが差さる・collapse 状態が QSettings ラウンドトリップ
  （collapse→`save_state`→新インスタンスで復元→畳まれたまま）・`_reset_layout` で全展開へ

**Layer C（realgui・/gui-verify ①ゲート）**: **collapse の実効は実機でしか確証できない**
（memory gui_isvisible_true_for_offscreen_hidden_dock）。実 OS クリックで折りたたみトグル→
**ドックが実際に縮む**（geometry 高さがタイトルバー高になる）＋内容非可視を実測。3ドック代表で
検証＋カスタムタイトルバーのフロート/閉じるが実動作＋journey smoke。

## 6. 成果物（§3）

- カスタムタイトルバーが Qt 既定タイトルバー（フロート/閉じる）を置換するため、**3ドックの
  タイトルバー見た目が変わる**＝凍結カタログ 01-05 に意図差分。前後差分で「タイトルバー領域の
  変化のみ」を確認→ベースライン差し替え・カタログ再撮影・DesignSync 再同期（Ground Truth 更新）。
  **折りたたみ状態の記録用にカタログへ collapsed 状態ショットを1枚追加**（`09_collapsed`）
- **トークン/エクスポート変更なし**（tokens.css/json/cards 不変）。DesignSync はスクショ更新のみ
- docs/design.md 決定履歴に運用反復4（構造変更・FU-14 実現・トークン変更なし・出典 inbox メモ③
  ＋File/Channel も畳む要望）。CLAUDE.md 更新は merge 後 docs PR

## 7. 進め方

**増分B（PR #129）マージ後**、更新後 main から `feature/collapsible-docks` を切って
subagent-driven development・ゲート4種（pytest / ruff check / ruff format --check / mypy src/）。
タスク4〜5個（タイトルバー component・MainWindow 配線＋永続・realgui・成果物）。
