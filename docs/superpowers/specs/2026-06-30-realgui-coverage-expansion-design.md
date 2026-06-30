# realgui カバレッジ拡充 設計 spec

> 設計日: 2026-06-30 / 一次根拠: [docs/realgui-coverage-audit.md](../../realgui-coverage-audit.md)（gap 分析・全 GUI spec/実装/既存テスト突合）。
> テスト方針の規範: [docs/gui-testing-layers.md](../../gui-testing-layers.md)（②実質性ルール・①証拠ゲート）。

## ゴール

realgui(Layer C) カバレッジを拡充し、**headless が構造的に false-green を出す経路**（OS→Qt 配送・ヒットテスト・描画結果・押下中 move 駆動・QDrag D&D 配送）を実機で検証する。監査で判明した missing 23 項目（high/medium/low）を埋め、realgui が炙り出す production バグを修正し、付随する非 realgui の既知 false-green（dock 復元）と設計判断（クロスパネル軸移動）を解消する。

## アーキテクチャ概要

realgui テスト追加・production 修正・新機能（クロスパネル軸移動）が混在するため、**リスク順・テスト先行（honest TDD）** で進める。各 realgui は「配線破壊で RED → 修正/GREEN」を実証してから採用し、merge 前に `/gui-verify`（①証拠ゲート）を通す。共有 realgui 入力ヘルパを土台に、QDrag 系は背景 OS スレッド駆動＋watchdog でハングを構造的に回避する。

## 確定した設計判断（ユーザー承認済み）

| 論点 | 決定 |
|---|---|
| スコープ | **全部**（high + medium + low + 非realgui）を1 spec に（writing-plans でタスク分割） |
| inter-panel 軸 D&D | **許可** — 軸を別パネルへ移動する新機能として実装（拒否でも現状維持でもない） |
| 進め方 | **リスク順・テスト先行（honest TDD）** — realgui RED で実機バグを炙り出してから修正 |

## 共有基盤: `tests/realgui/_realgui_input.py`

既存 realgui に散在する実 OS 入力プリミティブを集約し、新規テストの土台とする。

- `skip_unless_real_display()` — 非 win32 / offscreen で skip（既存ロジックを共通化）。
- `to_phys(view, sx, sy) -> (int, int)` — scene 座標→物理ピクセル（DPR 換算）。
- `at(x, y, flag)` / `key(vk)` — Win32 `SetCursorPos`/`mouse_event`/`keybd_event` ラッパ。
- **`drive_qdrag(press_xy, target_xy, *, steps, modifiers=None, watchdog_s=3.0)`** — press 後、**別 OS スレッド**で move を小刻み駆動し release する。`QDrag.exec` の OLE モーダルループ中に GUI スレッドがブロックするため、`QTimer` 駆動では無限ハングする（memory `gui_realgui_drag_qtimer_hang`）。watchdog で Escape を送り、ハング時もテストが終了する。`modifiers` で Ctrl 等のライブ修飾キー保持（H3 用）に対応。
- **検証**: 既存 `test_multi_column_axis.py` / `test_move_then_resize.py` / `test_offset_drag.py` / `test_global_cursor.py` を本ヘルパへ載せ替え、無回帰で土台の正しさを実証する（リファクタ）。

## 作業クラス

詳細な missing 項目一覧と各 why_realgui / suggested_test は監査 doc を一次根拠とする。本 spec は設計判断とデータフローを規定する。

### クラス1: コンテナメニュー3経路（H5/H6/H7・production 修正＋realgui）

旧 `contextMenuEvent` コンテナ override は子アイテムビュー/子 QGraphicsView がイベントを伝播しないため実機でメニュー不発になりうる（PR#11 で FileBrowser のみ修正済み）。

- **ChannelBrowser / DataExplorer**: コンテナ override を撤去し、子 QTreeView に `setContextMenuPolicy(Qt.CustomContextMenu)` ＋ `customContextMenuRequested` シグナル→メニュー構築（FileBrowser 修正と同型）。
  - **DataExplorer / FileBrowser はパス/行ベース**: `indexAt(pos)` でカーソル下行を解決しメニューを構築（DataExplorer は `fs_model.filePath(index)`、有効 index のみ表示）。
  - **ChannelBrowser は選択ベース**（実装で確定・Phase 2）: メニューは現在の複数選択（ExtendedSelection）に対する一括「Add to Active Panel」なので、`_show_context_menu` は `indexAt`/`setCurrentIndex` で**選択を変更しない**（右クリックで複数選択を1行に潰さない）。
- **GraphPanel**: master `ViewBox.setMenuEnabled(False)` で pyqtgraph 既定メニューを抑止し、自前 `contextMenuEvent`（Add Panel / メインカーソル / サブカーソル(Δ) / 補間方式）が実右クリックで出ることを保証。
- **realgui**: 各ビューで実 OS 右クリック→`QApplication.activePopupWidget()` が正しいアクション付き自前 QMenu（pyqtgraph Plot Options でない）であることを assert。**honest 検証**: `setMenuEnabled(False)` 除去で既定メニュー競合 RED、コンテナ override に戻すと子非伝播で RED。
- **Layer A/B**: `build_menu(index)` のアクション内容・選択状態反映（grey-out）はヘッドレスで assert（既存 FileBrowser テスト同型）。

### クラス2: 信号 D&D 実配送（H1-H4・realgui）

ChannelBrowser 行起点に `drive_qdrag` で信号キー mime の QDrag を駆動し GraphPanel へ実ドロップ。子 `setAcceptDrops(False)`→親 `setAcceptDrops(True)` の非対称バブリングは合成 sendEvent で再現不可（memory `gui_drag_drop_not_sendevent_reproducible`）。

- H1: プロット中央(ZONE_PLOT)へドロップ→新規軸生成＋新 AxisItem 描画バンドを assert。
- H2: Y軸帯(ZONE_Y_INNER/OUTER)へドロップ→既存軸を上書き置換（旧曲線消失・新曲線描画）。
- H3: Ctrl 保持しながらドロップ→上書きでなく結合（既存＋新の両曲線重畳）。
- H4: ChannelBrowser 多選択（Ctrl/Shift）→複数信号の一括追加（H1 と統合可）。
- **C2 ハング誘発の事前確認**: 信号ドロップ先 `dropEvent` の rebuild が軸移動同様 `QTimer.singleShot` 遅延化されているか確認し、未対応なら遅延化する（`QDrag.exec` モーダル中の同期 rebuild は破棄済みアイテム誤配送→ハング: memory `gui_realgui_qdrag_rebuild_stale_scene`）。
- **honest 検証**: `setAcceptDrops` を外すと親 `dropEvent` 不到達で RED。

### クラス3: click_to_activate_axis（H8・realgui）

既存 realgui 4本は全て `view.set_active_axis(0)` 直叩きでアクティブ化を前提化＝全軸操作モデルの唯一の入口が実入力で未検証。

- 非アクティブ軸スパイン上で実 press+release（ドラッグ閾値未満の純クリック）→ pyqtgraph scene の click/drag 判別が `mouseClickEvent` を発火→`set_active_axis`。
- assert: アンバーフレーム描画＋後続実ジェスチャ（グリップ/ズーム）が当該軸に効くこと。

### 新機能: クロスパネル軸移動

軸フレームを別パネルへドラッグ&ドロップしたとき、軸を（その信号ごと）ターゲットパネルへ移動する。

**データフロー（MVVM・GraphAreaVM 統括）**
1. **View（source）**: 軸フレーム QDrag 起動時、mime を `{source_panel_index, axis_index}` に拡張（現状は axis_index のみ）。
2. **View（target）** `dropEvent`: 自パネル index と `source_panel_index` を比較。
   - 同一パネル → 既存の列移動/並べ替え（`_axis_drop_target`、**無変更**）。
   - 別パネル → `GraphAreaVM.move_axis_across_panels(src_panel, axis_index, dst_panel, drop_target)` を要求。
3. **GraphAreaVM**: パネル群を統括し、source VM から軸（信号群＋軸設定: ラベル/スケール）を除去 → target VM に `drop_target` の列/位置で追加 → 両パネルへ refresh 通知。View 同士は直接触らない（MVVM 維持）。
4. **両 View**: 再描画。移動軸が target に出現・source から消える。

**セマンティクス**
- **同一タブ内の可視パネル間のみ**（別タブは同時表示されずドロップ対象にならない）。
- 移動単位 = 軸＝その信号群＋軸設定。source が 0 軸化したら空リージョン許容（既存挙動）。
- ドロップ位置の列/順序は target 内で既存 `_axis_drop_target` を流用。
- target に容量上限は設けない（YAGNI）。

**テスト**
- Layer A/B: `move_axis_across_panels` の remove/add 純ロジック（source から消え target に同一信号で出現・冪等性・自パネル指定時は no-op か既存パスへ）。
- realgui: panel0 の軸フレームを `drive_qdrag` で panel1 へ実ドロップ→軸（信号ごと）が panel1 に描画され panel0 から消えることを assert。

### medium（M1-M13・多くは既存 realgui 拡張）

監査 doc の M1-M13。主に既存テストへの低コスト追加:
- offset（test_offset_drag.py）: M1 Escape キャンセル（grab 保持中の実 Escape 到達）・M2 カーソル線×曲線オーバーラップ押下ルーティング（線優先）。
- cursor（test_global_cursor.py）: M3 R17 統計ライブ再計算＋実フォント判読スクショ。
- multi_column（test_multi_column_axis.py）: M4 同一列内並べ替え（position 経路）・M7 mid-drag フィードバック描画（挿入線スナップ/空カラム帯/dimmed source）。
- 新規: M5 シェルファイルドロップ（Graph_Area / Data_Explorer の URL mime 実ドロップ）・M6 クロスパネル軸移動（上記新機能の realgui）・M10 X軸ズーム/パン実ドラッグ・M11 動的 LOD 描画・M12 X軸クロスパネル同期描画・M13 X軸/プロットゾーン hover カーソル（R14 同型 move 到達リスク）。

### low（専用テスト不要・相乗り）

ドラッグ enter/leave 青枠ハイライト・ドロップ可能枠・非アクティブ軸 hover 仮フレームは上位の高リスク D&D/hover テスト内で mid-drag/mid-hover スクショ＋`/verify` 観測として相乗り。grip_hit_area・Data_Explorer ファイルドロップは既存実質カバー/最終確認1度のみ。

### 非 realgui: dock 復元 false-green（C1）

`main_window.py` が `saveState/restoreState` を使うのに `file_dock/channel_dock` 等に `setObjectName` が無く、`restoreState` がドック配置を黙って no-op にする（実機でドック復元不発の公算大）。realgui ではなく **Layer A** が正しい道具:
- production: 各 dock に一意 `setObjectName` を付与。
- Layer A: 配置変更→`saveState`→新インスタンスで `restoreState`→`dockWidgetArea`/`isFloating` が一致するラウンドトリップを assert（現 `TestStatePersistence` は crash しない/title 一致しか見ていない）。

## テスト戦略

- **レイヤー割当**: false-green が構造的に出る経路は Layer C（realgui）。VM 純ロジック・ポリシー・ラウンドトリップは Layer A/B。視覚はスクショ＋`/verify`。
- **honest 検証（①②の核）**: 各新 realgui は配線破壊（`setAcceptDrops`/`contextMenuEvent`/`setMenuEnabled`/`grabMouse` 等）で RED になることを1度実証してから GREEN。「スクショ保存だけ・VM 再チェックだけ」は不可。
- **ハング安全**: 全 D&D realgui は背景スレッド駆動＋watchdog（`QTimer` 駆動禁止）。dropEvent rebuild は singleShot 遅延化。
- **証拠ゲート**: 新設 realgui は merge 前に `uv run pytest --realgui tests/realgui/test_X.py`（該当のみ）で pass ログ＋スクショ。視覚は `/verify` 観測。`/gui-verify` で scoped 自動化。

## リスク順フェーズ（実装順・writing-plans が番号順タスク化）

1. 共有 `_realgui_input` 抽出＋既存テスト載せ替え（無回帰）。
2. コンテナメニュー3経路（realgui RED→production 修正→GREEN）。
3. 信号 D&D 実配送 H1-H4（C2 ハング確認込み）。
4. click_to_activate_axis H8。
5. クロスパネル軸移動（VM Layer A/B→production→realgui）。
6. medium realgui M1-M13（既存拡張中心）。
7. low 相乗り＋非realgui dock 修正 C1。

## 成功基準（done の定義）

1. 新規 realgui が全て実 win32 で pass ＋ honest 検証済み（証拠ログ＋スクショ）。
2. realgui が炙り出した production バグ（メニュー不発等）を修正。
3. クロスパネル軸移動が機能（realgui ＋ VM の Layer A/B）。
4. dock 復元修正（Layer A ラウンドトリップ）。
5. headless full green・ruff/format/mypy クリーン・`/gui-verify` ①ゲート充足・CI 緑。

## 非ゴール（YAGNI）

- `realgui_required=false` 項目（純ロジック・VM 状態・dock 復元の realgui 版）に realgui を足さない。
- low 視覚項目に専用 realgui を作らず上位テストに相乗り。
- 既存 substantive テストの作り直しはしない（C3 の `first_resize_after_axis_move` は描画ジオメトリ assert への昇格を任意の improvement として記録のみ）。
