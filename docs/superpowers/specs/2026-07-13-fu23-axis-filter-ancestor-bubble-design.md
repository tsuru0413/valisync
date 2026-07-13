# FU-23（FU-15 app フィルタの祖先バブル誤発火で軸ジェスチャ全滅）設計 spec

FU-15 で導入した centralized click-away（`GraphAreaView` が `QApplication` に `MouseButtonPress` フィルタを設置し、押下対象がプロット subtree 外なら全パネルのアクティブ Y 軸を解除）が、**実クリックの祖先バブル配送を「subtree 外」と誤判定**し、軸レーン上の押下で自らアクティブ軸を解除する。純クリック活性化だけ release 後勝ちで生存し、ドラッグ系ジェスチャ（grip リサイズ/フレーム移動/ズーム/パン）は全滅する＝ユーザー報告「軸のヒット判定がおかしい・解除しかできない」。

## 真因（実測確定・2026-07-13・実 MainWindow＋実 OS 入力＋計装トレース）

実クリック1回で `MouseButtonPress` は多段配送される。軸レーンの press は誰も accept しないため、配送は `GraphicsLayoutWidget → GraphPanelView → QSplitter → QStackedWidget(tab) → QTabWidget → GraphAreaView(self) → QStackedWidget(central) → MainWindow` と**GraphAreaView を通り越して祖先へバブル**する。`QApplication` フィルタは全配送を観測する。

`eventFilter` の内側判定は `target is self or self.isAncestorOf(target)`（＝target が GraphAreaView の**子孫**か）のみ。**GraphAreaView 自身の祖先（central `QStackedWidget`・`MainWindow`）へバブルした同一物理イベントの配送**は子孫でないため「subtree 外」と誤判定され `clear_active_axis()` を呼ぶ。計装トレース実測:

```
obj=GraphAreaView(self)          desc=True  ancestor=False → 非解除 ✓
obj=QStackedWidget(central)      desc=False ancestor=True  → clear_active_axis() 誤発火 ✗
obj=MainWindow                   desc=False ancestor=True  → clear_active_axis() 誤発火 ✗
```

一方、正当な click-away（ChannelBrowser 実クリック）は target=`viewport` で `desc=False ancestor=False` → 従来どおり解除（実測 STEP2 で確認）。

**症状の機序**: 純クリック活性化（press→release・移動なし）は上記誤解除が起きても release 時の `_AlignedAxisItem.mouseClickEvent` が最後に `set_active_axis` を書き戻し**偶然生存**。だが grip/zoom/pan/move は押下直後の誤解除（`_active_axis_index=None`）を `_begin_axis_drag` の前提チェック（`view._vm_axis_index != view._active_axis_index`）が拾って**ジェスチャ拒否**。STEP5 実測で zoom ドラッグ後 `y_range` 不変を確認。

## 修正: 祖先配送を内側判定に含める（案1・祖先除外）

`eventFilter` の subtree 判定に **`target.isAncestorOf(self)` を除外条件へ追加**:

```python
if isinstance(target, QWidget) and not (
    target is self
    or self.isAncestorOf(target)      # 子孫への配送（従来）
    or target.isAncestorOf(self)      # 祖先へのバブル配送（FU-23 追加）
):
    self.clear_active_axis()
```

**根拠（診断データが正しさを実証済み）**: 誤発火した2配送は `ancestor=True`＝この1条件で両方抑制される。正当な click-away は `ancestor=False & desc=False` のため影響なし＝FU-15 の解除意図は完全保存。ステートレス・1条件・症状隠蔽でない根本解決。

**負の契約**: 祖先（central stack/MainWindow）を直接クリックできる面は子ウィジェットが覆っており実質存在しない。仮にそこへ着地しても「非解除」は安全側（曖昧領域で誤って全解除しない）。`clear_active_axis`・空プロット面解除・FU-15 の click-away 意図・ゾーン幾何は不変。

### 案2（棄却）: `id(event)` デバウンス
同一物理イベントのいずれかの配送が内側着地したら以後の祖先配送で clear しない。ステートフル（per-event 状態＋GC 後の id 再利用リスク・[[gui_id_reuse_flake_object_recreation]] と同族の非決定性）で案1より複雑。祖先除外で同じ効果が単純・確定的に得られるため YAGNI。

## テスト（gui-test-plan ②・honest-RED ファースト）

グローバル介入変更＝**両方向＋実 MainWindow 組立てハーネスが必須構成要素**（更新後スキル gui-test-plan の「グローバル介入」行）。

- **`tests/realgui/test_journey_smoke.py`（新設・ゲート (e) の常設スモーク）**: 実 `MainWindow`＋実 OS 入力で基本ジャーニーを一気通貫し、**非発火側（活性化に続くジェスチャがユーザー可視の効果を生むまで）**を検証。核ステップ = 信号を1パネル2軸にプロット → **軸スパインを実クリックで活性化**（`_active_axis_index==0` assert）→ **軸 grip を実ドラッグ** → `_y_axes[0].sceneBoundingRect().height()` 比が**実際に変化**することを assert。**現 HEAD で本物のバグに RED**（診断で実測済み）→ 案1で GREEN。以後 (e) の常設ゲートとして GUI 変更 merge 前に毎回実行。
  - 「活性化状態が戻る」だけでは不足（純クリックは誤解除下でも生存するため）＝**続く操作が効果を生むまで**を observable にする（更新後スキルの「完遂」定義）。
  - realgui プリミティブは既存 `_realgui_input`（`at`/`LDOWN`/`LUP`/`MOVE`/`to_phys`）＋既存 `test_active_axis_resize.py` の grip 座標算出パターンを再利用（新規プリミティブ不要）。
- **Layer B 回帰（`tests/gui/test_graph_area_view.py`）**: 祖先ウィジェットへの合成 press（`QApplication.instance().notify(ancestor, ev)` で `ancestor.isAncestorOf(GraphAreaView)==True` な対象）で**clear しない**ことを assert（案1 の非発火を lock・sabotage で旧条件に戻すと RED）。既存の「正当な subtree 外 click-away は clear する」ケースは無回帰で維持。
  - 注意（更新後スキルの落とし穴）: 合成 `notify(target, ev)` は1配送のみで実クリックの多段バブル配送列を再現しない。この Layer B は**祖先判定ロジックの regression-lock**であり、非発火側の end-to-end 証明は journey smoke（Layer C）が担う。
- **既存軸 realgui クラスタ無回帰**: `test_click_activate_axis.py`・`test_active_axis_resize.py`・`test_active_axis_zoom_pan.py`（bare ハーネスで filter 非設置＝この変更に非曝露だが無回帰確認）＋`test_fu15_axis_deselect.py`（click-away 発火側が壊れていないこと）＋`test_active_panel_flow.py`・`test_cross_panel_axis_realclick.py`（実組立て）。
- prod スケール不要（ジオメトリ/状態遷移の検証でデータ量非依存）。

## ファイル構成（変更予定）
- `src/valisync/gui/views/graph_area_view.py`: `eventFilter` の1条件追加。
- `tests/realgui/test_journey_smoke.py`: 新設（(e) 常設スモーク・honest-RED）。
- `tests/gui/test_graph_area_view.py`: 祖先非発火の Layer B 追加。
- `docs/audit-findings-catalog.md`: FU-23 登録（別コミット・同ブランチ折込）。
- **不変**: `clear_active_axis`・空プロット面解除・FU-15 click-away 意図・ゾーン幾何・VM。
