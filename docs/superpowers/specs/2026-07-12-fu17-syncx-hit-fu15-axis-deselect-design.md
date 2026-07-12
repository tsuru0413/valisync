# FU-17（Sync X ヒット域）＋ FU-15（アクティブ Y 軸のクロスエリア解除）設計 spec

Tier 1 の小 UX バグ2件を1ブランチで解消する。両者は独立（共通土台なし）だが、いずれも GraphArea/GraphPanel の入力経路の小修正で、実測で真因確定済み。

## FU-17: 「Sync X」チェックボックスのヒット域が右余白まで広すぎる

### 真因（実測確定・2026-07-12）
`graph_area_view.py:130-133` の `QVBoxLayout.addWidget(self.sync_checkbox)` が alignment/stretch 未指定のため、QCheckBox 本体がレイアウト幅いっぱい（container 900px）にストレッチされる。実測 `checkbox.geometry()=0,0,900,17`（sizeHint 96×17）・`childAt(x=136)`（content 端 40px 右）が checkbox 本体を返す＝**804px の dead margin がクリック判定に含まれ**、余白の誤クリックで X 同期が意図せずトグルされる。

### 修正
`layout.addWidget(self.sync_checkbox, 0, Qt.AlignmentFlag.AlignLeft)` に変更。stretch=0＋左寄せで QCheckBox が内容幅（sizeHint 96px）に固定され、右余白がヒット域から外れる。**独立・1行**。

### テスト
Layer B（headless・offscreen）: mount 後 `sync_checkbox.width()` が sizeHint.width() 近傍（≪ container 900px）であること、または `childAt(x=大きな余白位置)` が checkbox を返さないこと（＝dead margin 消失）をアサート。sabotage（alignment 除去）で RED。realgui は不要（描画変化なし・ヒット域はジオメトリで決定的に検証可能）。

## FU-15: アクティブ Y 軸を解除する手段がない → クロスエリア click-away 解除

### 真因（実測確定・2026-07-12）
`set_active_axis(None)` を渡す呼び出しが production（src/）に皆無で、`_active_axis_index`（`graph_panel_view.py:738`・view-transient）は一度セットされると None に戻る経路がない＝解除は別軸/曲線クリックでの**置換のみ**。空プロット面クリック（`mousePressEvent` の ZONE_PLOT no-curve 分岐 `:1919`）は `_deactivate_curve()`（`_active_curve_id` クリア）のみで**軸は不変**。ユーザーは「プロット領域から操作の焦点が離れたら軸選択を解除したい」（空プロット面・ChannelBrowser 等の他エリアクリック含む）。

### モデル
アクティブ Y 軸は「プロット領域が所有する一時選択（view-transient）」。**根本ルール = プロット subtree の外で押下が起きたら選択を解除する**（ChannelBrowser・他ドック・ツールバー・メニュー等、現在も将来も一律）。VM 非関与（transient のまま）＝ core は Qt 非依存を維持。

### 機構: centralized click-away protocol（単一介入点）

採用アプローチ（棄却案との対比込み）:
- **採用 = アプリレベル `MouseButtonPress` イベントフィルタ**（`GraphAreaView` が `QApplication` に設置）。単一の centralized 介入点で全エリアを一括処理。
- 棄却 = `QApplication.focusChanged` 監視: 非フォーカス型クリックの取りこぼし・メニュー/ポップアップ/QGraphicsView のフォーカス癖でエッジが多い。
- 棄却 = MainWindow 明示配線: 新エリア追加ごとに配線が要り脆い。

**実装骨子**:
1. `GraphAreaView.__init__` で `QApplication.instance().installEventFilter(self)` を設置し、`destroyed` で `removeEventFilter`（既存の hover `eventFilter` / `unsubscribe` 破棄パターンと同系のライフサイクル）。
2. `eventFilter(obj, event)`: `event.type() == QEvent.Type.MouseButtonPress` のみ処理（他は即 `return False`・O(1) 型ゲート）。押下ウィジェットを解決し（`QApplication.widgetAt(event.globalPosition().toPoint())` を優先・obj フォールバック）、**そのウィジェットが `self`（GraphAreaView）自身またはその子孫でなければ**（＝プロット subtree 外）`self.clear_active_axis()` を呼ぶ。フィルタは観測のみ＝常に `return False`（イベント非消費）。
3. `GraphAreaView.clear_active_axis()`: `self._panel_views` の全 `GraphPanelView` に `set_active_axis(None)`。解除を単一メソッドに集約（将来 active 曲線等を同じ click-away 契約へ載せる拡張点）。
4. `GraphPanelView.mousePressEvent` の空プロット分岐（`:1919`）に `self.set_active_axis(None)` を追加（app フィルタは subtree 内では発火しないため、パネル内の空白解除はローカルで担保）。

**subtree 内クリックは no-op**: パネル/軸/曲線の既存ハンドラが set/clear をローカル処理。GraphArea 自前 chrome（Sync X 行等・GraphAreaView の子）も「内」扱いで非解除＝プロット枠の一部。

**なぜ根本的/将来耐性**: 単一 centralized 介入点で**新ドック/エリアはゼロ配線で自動対応**。mouse-press 決定論的で**フォーカス方式のエッジを回避**。解除は単一 `clear_active_axis()` に集約＝拡張点。

### エッジケース
- **軸右クリックメニュー**: 押下は軸上（subtree 内）→ 非解除（軸に対する操作）。メニュー popup は別ウィンドウだがそれを開いた press は内側。
- **ChannelBrowser からの D&D**: press は ChannelBrowser（外）→ 解除。信号追加中なので無害。
- **タブ切替**: タブバーは QTabWidget（GraphAreaView の子）→ 内 → 非解除（タブごと transient を保持）。
- **別ウィンドウ（メニュー/ダイアログ）クリック**: subtree 外 → 解除されうるが、これらは transient で無害。
- **押下 obj が非 QWidget / 解決不能**: 曖昧なので**解除しない**（誤解除より安全側）。

### 影響範囲（負の契約）
- **active panel（`GraphAreaVM.active_panel_index`・PC-07）は変更しない**（本課題は axis のみ）。press で panel は従来どおり活性化される（`activate_requested.emit()` は不変）。
- **VM は変更しない**（active axis は view-transient のまま・core Qt 非依存維持）。
- 既存の軸クリック活性化・曲線活性化・zone ルーティングは不変。

### テスト（gui-test-plan ②）
- **Layer B**:
  - 空プロット面クリック（ZONE_PLOT no-curve）→ 対象パネルの `_active_axis_index is None`。
  - GraphAreaView にフィルタ設置後、**subtree 外のウィジェット**（テスト用の兄弟 QWidget または ChannelBrowser 相当）への合成 `MouseButtonPress` → 全 `_panel_views` の `_active_axis_index is None`。**subtree 内**（パネル/自身）への press では解除**されない**ことも対で確認（誤解除ガード）。
  - sabotage（フィルタ未設置 / ancestor 判定反転）で RED。
- **Layer C（realgui・実機）**: 軸クリックでアクティブ枠を出す → **実 ChannelBrowser クリックでアクティブ枠が消える**（クロスウィジェット実経路＝headless では兄弟合成でしか触れない実配送を裏取り）＋実空プロットクリックで消える。掴み点/zone への副作用がないこと（ヒット域不変）を無回帰確認。
- prod スケール不要（ヒット/選択のジオメトリはスケール非依存）。

## ファイル構成（変更予定）
- `src/valisync/gui/views/graph_area_view.py`: `addWidget` alignment（FU-17）／`installEventFilter`＋`eventFilter`＋`clear_active_axis()`＋`removeEventFilter` on destroy（FU-15）。
- `src/valisync/gui/views/graph_panel_view.py`: `mousePressEvent` 空プロット分岐（`:1919`）に `set_active_axis(None)`（FU-15）。
- テスト: `tests/gui/test_graph_area_view*.py`（FU-17 ヒット域・FU-15 フィルタ/クリア Layer B）・`tests/gui/test_graph_panel_view.py`（空プロット解除）・`tests/realgui/`（新規 FU-15 クロスウィジェット解除）。
- **不変**: VM（`graph_panel_vm.py`/`graph_area_vm.py`）・active panel/curve ロジック・zone/grip ヒットテスト。
