# realgui カバレッジ監査（gap 分析）

> **進捗（拡充実施・2026-06-30）**: 本監査を基に realgui を 6→22 件へ拡充中。Phase 1 共有ヘルパ抽出（PR #27）／Phase 2 コンテナメニュー3経路 H5-H7（PR #28）／Phase 3 信号 D&D 実配送 H1-H4（PR #29）／Phase 4 click_to_activate_axis H8（PR #30、付随フレーク修正 #31）完了＝**high クラスタ H1-H8 充足**。残: 新機能クロスパネル軸移動（Phase 5）・medium M1-M13／low（Phase 6-7）・非 realgui dock 復元 C1。各 honest RED→GREEN は実 win32 ①ゲートで実証済み。設計: `docs/superpowers/specs/2026-06-30-realgui-coverage-expansion-design.md`、プラン: `docs/superpowers/plans/2026-06-30-realgui-plan{1-4}-*.md`。
>
> 生成: 2026-06-30 / workflow `realgui-coverage-audit`（11 エージェント・並列マッピング→棚卸し→突合→完全性クリティック）＋ 1 ドメインをインライン補完。
> 基準: `docs/gui-testing-layers.md` の ②実質性ルール（realgui は「実経路でしか証明できない結果」= OS→Qt 配送・ヒットテスト・描画/視覚結果・押下中 move 駆動ジェスチャ・QDrag D&D 配送 を検証）。

## サマリ

| 指標 | 値 |
|---|---|
| realgui 必須項目（7ドメイン、重複2除く） | 39 |
| **covered**（substantive な既存テストあり） | 16 |
| **missing**（未カバー or naive のみ） | 23 |
| weak（既存だが naive） | 0 |
| 既存 realgui テスト | 12（全て substantive） |

**粒度差の評価**: 「通常 ~600 / realgui 12」の桁違いは *誤り* ではなく「過去事故（PR#11 メニュー false-green、R14 move 不達）を踏んだ高リスク経路への集中投資」として正しい。問題は **偏り** — 既存12本は軸操作とカーソル線に集中し、**headless が構造的に false-green を出す3クラスに穴がある**:
1. **信号 D&D 実配送（realgui ゼロ）** — 本アプリ最頻ワークフロー
2. **コンテナ `contextMenuEvent` override × 子アイテムビュー/子 QGraphicsView 非伝播**（PR#11 で FileBrowser のみ修正、他3経路放置）
3. **`click_to_activate_axis`** — 全軸操作モデルの唯一の入口が実クリックで未検証

realgui 増設は **数を追わず、この3クラス（high 実質7テーマ）に限定**して質を担保する方針。

## 既存 realgui（12本・covered 16項目）

軸ごとリサイズ/ズーム/パン/ホバーカーソル（test_active_axis_resize.py・test_active_axis_zoom_pan.py: 5）／軸移動 QDrag＋post-drag stale-scene 無回帰（test_multi_column_axis.py・test_move_then_resize.py: 2）／FileBrowser 右クリック＋Remove 比率保持（test_file_browser_realclick.py・test_remove_file_preserves_proportions.py: 2）／Global・Delta カーソル線ドラッグ（test_global_cursor.py: 2）／R14 オフセット move 駆動＋実 modal（test_offset_drag.py: 1）。

## missing — 優先度 high（最優先で埋める）

| # | 項目 | ドメイン | なぜ realgui | 推奨テスト |
|---|---|---|---|---|
| H1 | 信号→プロット実ドロップ→新規軸＋描画 | D&D | 子`setAcceptDrops(False)`→親非対称バブリング。合成 sendEvent は親 dropEvent に届かない。直叩きは PR#11 同型 false-green | ChannelBrowser 行起点に別OSスレッド QDrag（QTimer 駆動は OLE モーダルでハング）→プロット中央へ実ドロップ、新規 AxisItem 描画を assert。test_multi_column_axis.py を雛形 |
| H2 | 信号→Y軸帯実ドロップ→上書き置換＋描画差替 | D&D | 上書きはデータ破壊。実座標→`_zone_at` 軸帯ヒットテスト誤判定が誤上書き/誤新規軸に直結。直叩きは固定 QPointF で実座標分類を迂回 | 軸スパイン帯座標へ実ドロップ、対象軸の曲線差替＋他軸不変を assert |
| H3 | Ctrl 押下しながら実ドロップ→結合（非破壊重畳） | D&D | Ctrl 有無が破壊的上書き vs 非破壊結合の正反対分岐。実 QDrag 中のライブ修飾キーは実経路依存 | QDrag 駆動中に Ctrl 保持（keybd_event/SetKeyState）し Y軸帯へドロップ、両曲線重畳を assert |
| H4 | ChannelBrowser→GraphPanel 信号 D&D（多選択含む） | FileBrowser | QListView QDrag 起動＋クロスウィジェット実配送は合成非再現。realgui ゼロ＋QDrag ハング事故歴 | 信号行（単一/Ctrl・Shift 複数）から QDrag→GraphPanel ドロップ、namespaced キー解決＋波形追加を assert。H1 と統合可 |
| H5 | GraphPanel 右クリック→自前カーソル/パネルメニュー出現 | コンテキストメニュー | コンテナ override＋子 pyqtgraph、`ViewBox.setMenuEnabled(False)` 未呼び出し（既定メニュー競合）。実右クリックは子へ先に配送＝親メニュー不発の恐れ。Layer B は子を迂回 | 実右クリック→`activePopupWidget` が自前 QMenu（Add Panel/メインカーソル/サブカーソル(Δ)/補間方式）で pyqtgraph Plot Options でないことを assert |
| H6 | ChannelBrowser 右クリック→「Add to Active Panel」出現 | コンテキストメニュー | コンテナ override＋子 QTreeView = PR#11 で実証された壊れパターン。FileBrowser のみ修正済・本ビュー未修正＝R9 信号メニュー実機機能ゼロの可能性 | **CustomContextMenu 化修正とセット**で、信号行で実右クリック→メニュー出現＋選択状態反映を assert |
| H7 | DataExplorer 右クリック→カーソル下パス解決メニュー | コンテキストメニュー | コンテナ override＋子 QTreeView＋`globalPos→indexAt` のパス解決も実 OS ヒットテスト依存。Layer A はパス直渡しで両方バイパス | ファイル行で実右クリック→メニュー出現＋パス対応（Load File enabled/disabled 等）を assert |
| H8 | `click_to_activate_axis`（実クリック→アクティブ化） | 軸操作 | 既存 realgui 4本が全て `set_active_axis(0)` 直叩きで前提化＝**全軸操作モデルの唯一の入口が実入力で未検証**。`mouseClickEvent` は scene の click/drag 判別＋親 forwarding でのみ発火 | 非アクティブ軸スパイン上で実 press+release（閾値未満）→アンバーフレーム描画＋後続ジェスチャ受付を assert |

## missing — 優先度 medium（多くは既存 realgui への低コスト拡張で塞げる）

- **M1 Escape キャンセル（R14.7）**: 曲線実ドラッグ中（grab 保持中）に実 Escape が届くか。test_offset_drag.py 拡張。
- **M2 カーソル線×曲線オーバーラップ押下ルーティング（§4）**: InfiniteLine(scene) と親オフセットドラッグの実押下奪い合い。sendEvent 単一ターゲットでは再現不可。test_offset_drag.py 拡張。
- **M3 R17 統計のライブ再計算＋判読**: B 線ドラッグ中の readout 統計更新＋実フォント判読（offscreen は tofu）。test_global_cursor.py 拡張。
- **M4 同一列内 D&D 並べ替え**: 既存は inner→outer 列間のみ。`_axis_drop_target` の position 分岐＋ソート後描画が未検証。test_multi_column_axis.py 雛形。
- **M5 シェル ファイルドロップ（Graph_Area / Data_Explorer）**: コンテナ DND 契約のバブリング配線破壊が headless 緑になりうる。アプリ内 QDrag で URL mime を実ドロップ。
- **M6 inter_panel_axis_drag**: `AXIS_INDEX_MIME` がパネル識別子を持たず、ターゲットがソース由来 index を未ガード適用。**クロスパネル移動を許すか拒否するかは設計判断未確定（要ユーザー/spec 確認）**。
- **M7 軸移動 D&D 中フィードバック描画**: 挿入線スナップ・空カラム帯ハイライト・移動元 dimmed(opacity 0.35)。既存 test_multi_column_axis.py の視覚アサート強化。
- **M8 GraphPanel 右クリック→カーソルトグルで線描画**: H5 と同一テストに連結（メニュー到達＋A50%/B75% 線描画）。
- **M9 R15.1 カーソルメニュー起動経路**: 空クリック設置撤去で右クリックトグルが唯一の起動経路。H5 と統合可。

### medium（インライン補完: 失敗ドメイン「波形/ズーム/パン/LOD/X同期」）

> workflow agent が schema リトライ上限で失敗したため当該ドメインをインライン確認。`grep` で realgui ゼロを実証（`tests/realgui/` で X ズーム/パン・LOD・X 同期にヒットなし）。

- **M10 X軸ズーム/パン実ドラッグ（ZONE_X_INNER/OUTER）**: `GraphPanelView` widget レベルの apply-on-release（press+release は実経路で親到達＝R14 で実証済、構造的には機能するはず）だが realgui 皆無＝実座標→ゾーン分類＋ズーム/パン描画が未検証。
- **M11 動的 LOD 描画**: 実ズームイン時に viewport 連動ダウンサンプリングが細部/スパイクを描画するか（描画結果＝realgui のみ）。
- **M12 X軸クロスパネル同期描画**: 1パネルの X 操作→他パネルの X 追従＋再描画。クロスパネル描画でブロードキャストに move 到達/描画問題があれば headless 緑のまま壊れる（中〜高リスク）。
- **M13 X軸/プロットゾーンの hover カーソル（critique 検出）**: `graph_panel_view.py` の `cursor_for_zone(_zone_at)` が親 `mouseMoveEvent` 依存。Y軸 hover は AxisItem `hoverMoveEvent`(scene) で covered だが、X/プロットゾーンの押下なし hover move が親 QWidget に届くかは **R14『押下中 move 不達』と同型の move 到達リスク**。視覚のみ＝低〜中。

## missing — 優先度 low（専用テスト不要・上位テストに相乗り）

- ドラッグ enter/leave の青枠ハイライト描画、ドロップ可能ハイライト枠、非アクティブ軸 hover 仮フレーム描画 → 上位の高リスク D&D/hover テスト内で mid-drag/mid-hover スクショ＋`/verify` 観測で相乗り。
- grip_hit_area_grabbability → 既存 resize/zoom/move が具体点掴みで実質カバー済み。新規不要・記録のみ。
- OS ファイルドロップ Data_Explorer（DataExplorer は QGraphicsView 子無しで構造リスク低）→ 経路最終確認用に低優先で1度。

## クリティック検出（非 realgui だが要記録の false-green）

完全性クリティックが追加検出。**realgui では塞げないが headless が構造的に false-green を出す既知欠陥** ＝ 後続修正計画から漏らさないよう別枠保持:

- **C1 ドック配置の保存→再起動復元 false-green（高重大度）**: `main_window.py` が `saveState/restoreState` を使うのに `file_dock/channel_dock` 等に `setObjectName` が**一切無い**（grep 確認）。objectName 無しでは `restoreState` がドック配置を**黙って no-op**＝実機でドック復元が機能しない公算大。`test_main_window.py::TestStatePersistence` は crash しない/title 一致しか assert せず復元結果未検証。→ **realgui ではなく Layer A の save→restore ラウンドトリップ＋`dockWidgetArea`/`isFloating` assert で検証すべき**（realgui は誤った道具）。
- **C2 信号 D&D realgui の QDrag rebuild stale-scene ハング誘発**: 新設する H1/H4 で、ドロップ先 GraphPanel の `dropEvent` が `QDrag.exec` モーダル中に同期 rebuild すると memory `gui_realgui_qdrag_rebuild_stale_scene` 同型事故。軸移動は `QTimer.singleShot` 遅延 rebuild で回避済だが、信号ドロップ経路が同様に遅延化されているか未確認＝**実装前にハング誘発ゾーンとして要確認**。
- **C3 covered の caveat**: `test_move_then_resize.py::test_first_resize_after_axis_move_works` は load-bearing assert が描画ジオメトリでなく VM `height_ratio`＝②的に borderline（描画ジオメトリ assert への昇格余地）。

## 推奨ロードマップ（実装フェーズ）

1. **最優先（high・信号 D&D 実配送ゼロ）**: H1〜H4 を別OSスレッド＋watchdog QDrag で新設（test_multi_column_axis.py 雛形）。C2 のハング誘発を実装前に確認。
2. **high・コンテナ override メニュー3経路**: H6/H7 は **CustomContextMenu 化の production 修正とセット**、H5 は `ViewBox.setMenuEnabled(False)` 競合確認とセット。
3. **high・軸操作の入口**: H8 `click_to_activate_axis` 新設。
4. **medium・既存 realgui への低コスト拡張**: M1/M2（offset）・M3（cursor 統計）・M4/M7（multi_column）。
5. **medium・シェル/X軸系**: M5（ファイルドロップ）・M6（inter_panel、設計判断要確認）・M10〜M13（X ズーム/パン・LOD・X 同期・X hover）。
6. **low**: 視覚専用は上位テストに相乗り。C1 は別途 Layer A テストで修正。
7. **honest 検証**: 各新設 realgui は「配線破壊で赤くなる」（setAcceptDrops を外す/contextMenuEvent を戻すと落ちる）ことを一度確認して false-green でないことを実証。merge 前に `/gui-verify`（①証拠ゲート）。
