# gui-shell-controls 増分2 詳細設計（タブ/パネル・データソース管理）

親 spec: [2026-07-07-gui-shell-controls-design.md](2026-07-07-gui-shell-controls-design.md) §5 増分計画の **増分2**。増分1（File I/O 導線・1a/1b）は完了（PR #51/#52 merged）。

## 1. 背景と原則

実ユーザージャーニー監査で確定した 7 課題（`docs/audit-findings-catalog.md`）を解消する。**共通点: ViewModel のロジックは Phase 2 で実装済みだが、それを起動する View 側アフォーダンスが欠落**（右クリック限定・不可視・到達不能）。よって本増分は主に**既存 VM メソッド/シグナルへの可視アフォーダンス配線＋確認フロー**であり、新規ドメインロジックはほぼ無い。

| 課題 | 優先 | 欠落 | 既存 VM | View 位置 |
|---|---|---|---|---|
| SH-02 | 🔴 | 新規タブ UI | `GraphAreaVM.add_tab()` | `graph_area_view.py:68` |
| SH-04 | 🟠 | タブを閉じる UI | `GraphAreaVM.remove_tab(i)`（最後は ValueError） | 同上 |
| SH-13 | 🟡 | タブ改名 UI（Tab N 固定） | `GraphAreaVM.rename_tab(i, name)`（1-32字） | 同上 |
| SH-06 | 🟠 | パネル追加/削除が右クリック限定・可視ボタン無 | `add_panel`/`remove_panel`（signal 配線済） | `graph_panel_view.py` |
| SH-08 | 🟠 | ファイル削除が右クリック限定・**確認無し** | `AppViewModel.unload_file(key)` | `file_browser_view.py:60,63` |
| SH-10 | 🟠 | 登録ソース**一覧が UI に無い** | `add/remove_data_source` | `data_explorer_view.py:137` |
| SH-15 | 🟡 | Remove Source が不可視「現在ルート」に作用・no-op 無反応 | `remove_data_source(path)` | `data_explorer_view.py:105` |

## 2. 決定事項（ユーザー承認済み 2026-07-08）

- **サブ増分分割**: **2a=タブ（SH-02/04/13・`graph_area_view.py` に集中）** → **2b=パネル可視化＋ファイル削除確認＋データソース一覧（SH-06/08/10/15）**。1a/1b と同じく各々独立レビュー・マージ可能。
- **データソース一覧の場所（SH-10/15）**: **DataExplorer ウィンドウを強化**（メイン FileBrowser ドックには置かない）。既に Add/Remove Source を持つ DataExplorer に可視な登録ソース一覧を足し、Remove/切替を選択に作用させる。
- 慣習に従い既定採用（下記詳細）: コーナー「＋」＋Ctrl+T・`setTabsClosable`・ダブルクリックでインライン改名・`QMessageBox.question` 確認。

## 3. 増分2a 詳細（タブ操作 — `graph_area_view.py`）

現行: `self.tabs = QTabWidget`（`currentChanged→_on_current_changed`・`_rebuild` が VM ツリーを再投影）。**`_rebuild` は毎回 clear→addTab で作り直す**ため、タブバーに載せる装飾（close ボタン・コーナー「＋」）は `_rebuild` の度に再適用が必要（コーナーウィジェットは QTabWidget に1度設定すれば保持されるが、close ボタンの last-tab 抑制は再適用要）。

### SH-02 新規タブ（🔴）
- `self.tabs.setCornerWidget(btn, TopRightCorner)` に「＋」QToolButton を1度設定 → clicked → `self.vm.add_tab()`（VM が active を新タブへ更新→`_notify("tabs")`→`_rebuild`）。
- **Ctrl+T**: `QShortcut(QKeySequence("Ctrl+T"), self, ...)` または ShellActions に `new_tab` を追加。スコープは `WidgetWithChildrenShortcut`（親 spec §5.1 のショートカット衝突方針）。pyqtgraph 束縛（現状 Escape のみ）と非衝突。
- 到達性: コーナー「＋」＋Ctrl+T の2経路。

### SH-04 タブを閉じる（🟠）
- `self.tabs.setTabsClosable(True)` → `tabCloseRequested(index)` → `self._close_tab(index)`。
- `_close_tab`: `self.vm.remove_tab(index)` を呼ぶ。**最後の1枚は VM が ValueError** → その前に**最後の1枚では close ボタンを抑制**（`_rebuild` 後に、タブ数==1 なら `tabBar().setTabButton(0, RightSide, None)`）。防御的に `_close_tab` も try/except ValueError で no-op。
- Layer C: close ボタン実クリック→タブ数減少。

### SH-13 タブ改名（🟡）
- `self.tabs.tabBarDoubleClicked(index)` → インライン編集: 対象タブ矩形（`tabBar().tabRect(index)`）に `QLineEdit` をオーバーレイ・現名で初期化・全選択。
  - `editingFinished`/Enter → `self.vm.rename_tab(index, text)`（ValueError=1-32字外は編集継続＋エラー表示）→ 成功で `_notify("tabs")`→`_rebuild`。
  - Escape → キャンセル（元名保持）。フォーカス喪失 → 確定。
- 単一責務のため小ヘルパ `_TabRenameEditor`（QLineEdit サブクラス or 補助関数）に切り出す。
- Layer C: 実ダブルクリック→編集→Enter で改名反映。

## 4. 増分2b 詳細（パネル可視化・ファイル削除確認・データソース一覧）

### SH-06 パネル追加/削除の可視化（🟠 — `graph_panel_view.py`）
- 現状: `add_panel_requested`/`remove_panel_requested` は**右クリックメニュー限定**（`graph_panel_view.py:1776` 付近）。`GraphAreaView._wire_panel` が既に signal→`add/remove_panel` を配線し `set_removable` を持つ。
- 追加: パネルの隅（例: 右上の小さな chrome 行）に**可視な「＋パネル」「✕パネル」QToolButton**を置き、既存シグナルを emit。`set_removable(False)`（最後の1枚）で「✕」を無効/非表示。右クリックメニューは併存（冗長アフォーダンス）。
- Layer C: 可視ボタン実クリック→パネル増減。

### SH-08 ファイル削除の確認（🟠 — `file_browser_view.py`）
- 現状: 読込済みファイルの削除は右クリック限定・**確認/取り消し無し**（誤操作で即消える・`file_browser_view.py:60,63`）。
- 追加: 削除実行前に `QMessageBox.question`（「<file> を閉じますか？ プロット中の信号も消えます。」Yes/No、既定 No）→ Yes のみ `unload_file`。可視な削除アフォーダンス（行の「✕」または明示メニュー文言）も検討。
- Layer C: 確認ダイアログの Yes/No 経路。

### SH-10/15 データソース一覧（🟠/🟡 — `data_explorer_view.py`）
- 現状: Add/Remove Source ツールバー＋現在ルートの単一ツリー。**登録ソースの一覧が不可視**で、Remove は「現在ルート」に暗黙作用（何が消えるか予測不能・no-op 無反応）。
- 追加: DataExplorer に**登録ソースの可視リスト**（`QListWidget`・`app_vm` の data_sources を反映）。
  - リスト選択 → その source をツリールートに切替。
  - **Remove Source は選択中の source に作用**（`remove_data_source(selected)`）・未選択や不在は明示フィードバック（ステータス/無効化）で no-op 無反応を解消。右クリック削除と操作モデルを一致。
  - 永続化（`persistence.data_sources` JSON）は既存経路を維持。
- Layer C: リスト選択→Remove で当該ソースのみ消える。

## 5. テスト戦略（親 spec の GUI テストレイヤー準拠）

- **Layer A/B（必須・CI）**: 各アフォーダンスのハンドラ/シグナル配線を headless で。VM メソッド（add/remove/rename_tab・add/remove_panel・unload_file・remove_data_source）は実装済みなので、View→VM の配線と確認フロー（QMessageBox スタブ・rename の ValueError 経路・last-tab 抑制）を検証。
- **Layer C（新入力経路ごとにスケルトン）**: コーナー「＋」/Ctrl+T・close ボタン・ダブルクリック改名・パネル可視ボタン・削除確認・ソースリスト選択+Remove。honest gate は構築前クラス patch 等の既存慣習（memory `gui_realgui_qaction_slot_patch_before_construction`）に従う。
- `_rebuild` が clear→addTab で作り直す点に注意: タブ装飾（close 抑制・改名 QLineEdit の後片付け）が rebuild を跨いで壊れないことを Layer B で固定。

## 6. 未対応（本増分外）

- 増分3（レイアウト/chrome: SH-05 ショートカット監査・SH-11・SH-12 ドックトグルボタン・SH-14）。
- コマンドパレット（親 spec §2 の将来 graft 余地）。
- タブのドラッグ並べ替え・タブごと x-sync 以外の設定。

## 7. 実装順

1. **増分2a**（writing-plans → subagent-driven）: SH-02 → SH-04 → SH-13（`graph_area_view.py` に集中・`_rebuild` 跨ぎの装飾保持に留意）。
2. **増分2b**（2a マージ後・別プラン）: SH-06 → SH-08 → SH-10/15。
