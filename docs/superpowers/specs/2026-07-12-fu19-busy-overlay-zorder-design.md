# FU-19（ロードオーバーレイが z-order でプロット/ドックの背面に沈む）設計 spec

Tier 1 の UX バグ。プロット/ドックが表示されている状態で新規ファイルを読み込むと `BusyOverlay`（読み込み中インジケータ）が見えない。実機で真因を締めた。

## 真因（実機確定・2026-07-12）

`main_window.py:96` の `self.busy_overlay = BusyOverlay(self)` が、`central_stack`（`:145`）・File/Channel/Diagnostics ドック（`:109-138`）より**先に生成**される。Qt の兄弟 z-order は「後で生成した兄弟が上に積まれる」ため、overlay は MainWindow の子スタックで**永久に背面**に沈む。overlay を最前面へ持ち上げる `raise_()` はコードのどこにも無い（`raise_()` は他ドックの `:301`/`:452` のみ）。

実機再現（`QT_QPA_PLATFORM=windows`・実 MainWindow）で確定した観測:
- プロット有り: `busy_overlay.show()` 後も `overlay.isVisible()==True` かつ `geometry()==window.rect()`（全面）だが、`QApplication.widgetAt(ウィンドウ中心)` は overlay ではなく `QWidget`（pyqtgraph プロット）を返す＝overlay は不透明なプロット背景に完全に隠蔽。スクショで「読み込み中」ラベル・プログレスバー・キャンセルが**一切見えない**。
- 「空状態の初回ロードでは出る」という当初の疑いは**錯覚**だった。空状態の `WelcomeView` は背景が透明なので背面の overlay の子が隙間から透けて見えるだけ。プロット有りでは不透明な pyqtgraph 背景が全面を覆い、overlay は完全に隠れる。
- 疑い#2（2回目で未起動）・#3（`cover()` 矩形ずれ）は**反証**（overlay は `show()` され `isVisible()==True`・geometry は全面一致）。

GraphPanel が native window（`WA_NativeWindow`）なら `raise_()` でも最前面化しないが、実測で `internalWinId()==0`（QGraphicsView も viewport も非 native）を確認済み。よってオクルージョンは純粋な兄弟 z-order のみが原因で、`raise_()` で解消できる。

## 修正

`BusyOverlay.show()` の `super().show()` 直後に `self.raise_()` を1行追加する。

```python
def show(self) -> None:
    """Show the overlay, covering the parent and raising it above siblings."""
    self.cover()
    super().show()
    self.raise_()  # FU-19: central/dock は overlay より後生成で兄弟 z-order 上。
                   # 表示のたび最前面へ持ち上げないと不透明プロット背景に隠れる。
```

### なぜこの設計か（採用理由と棄却案）
- **採用 = `show()` 内で `raise_()`**。overlay 自身が「親を覆う（`cover()`）＋兄弟の最前面に立つ（`raise_()`）」という**表示契約を単一メソッドで所有**する。load 経路（`:249`）と export 経路（`:430`）は**同一 `busy_overlay` インスタンス**を使うので1箇所の修正で両方直る。表示のたびに再 `raise_` するため、**将来 MainWindow に別の兄弟ウィジェットが追加されても再発しない**（band-aid ではなく根本修正）。
- 棄却 = **生成順の入れ替え**（`BusyOverlay` を `central_stack` 生成後へ移動）。将来ウィジェットが追加されるたびに順序制約が再導入され脆い。
- 棄却 = **`LoadController._refresh_busy` で `raise_`**。汎用の load コントローラを Qt のスタッキング事情に結合させる。`show()`（既に `cover()` を所有）が自然な所有者。

### 影響範囲（負の契約）
- **VM は不変**（core Qt 非依存維持）。
- `cover()`・`eventFilter`（FU-02 のリサイズ追従）・カウントベース可視性（`LoadController`）は不変。
- フォーカス・マウスイベント経路は不変（`raise_()` は描画スタッキングの再順序のみで、フォーカス移動やイベント横取りの副作用はない）。
- フローティング状態のドック（別トップレベルウィンドウ）は overlay がカバーしないが、本課題スコープ外の稀ケースで許容。

## テスト（gui-test-plan ②）

`BusyOverlay.isVisible()` は隠蔽されていても `True` を返す（実機で実証）ため、**observable に使わない**。ユーザーが実際に見る終状態＝「overlay が兄弟の最前面にあり、プロット上に描画される」ことを検証する。

- **Layer B（headless・offscreen）**: 早期生成した overlay と、後生成の不透明な兄弟ウィジェットを同一親・同一矩形に置き、`overlay.show()` 後に `parent.children().index(overlay) > parent.children().index(sibling)`（＝overlay が子スタックの上）をアサート。`raise_()` が実際に `children()` 順を変えることは実測確認済み（idx 2→末尾）。sabotage（`raise_()` 除去）で RED。
- **Layer C（realgui・実機・新規）**: 決定打。**実 MainWindow にプロット2パネルがある状態**で、`window._load_controller.submit(blocking_callable, busy=window.busy_overlay, …)`＝**本番の off-thread ロード経路**を駆動し（`_refresh_busy→show()→raise_()` を自然に exercise）、ロード実行中に:
  - `QApplication.widgetAt(ウィンドウ中心のグローバル座標)` が **overlay かその子孫**（`widgetAt` は最深子 `QProgressBar` を返すので子孫許容が正）を返すことをアサート。
  - スクショで「読み込み中」バー/ラベル/キャンセルがプロット上に可視であることを添付。
  - blocking callable を解放してワーカーを排水（スレッドを残さない）。
  - sabotage（`raise_()` 除去）で `widgetAt` がプロットを返し RED。
  - **FU-02 の素 QWidget 親テスト**（overlay が唯一の子＝常に最前面）が構造的に見逃した false-green を、実 MainWindow の z-order 経路で潰す。
- prod スケール不要（z-order/ヒットテストはデータ規模非依存）。

## ファイル構成（変更予定）
- `src/valisync/gui/views/busy_overlay.py`: `show()` に `self.raise_()` 追加（FU-19）。
- テスト: `tests/gui/test_busy_overlay.py`（Layer B z-order）・`tests/realgui/test_fu19_overlay_zorder.py`（新規 Layer C 実 MainWindow）。
- **不変**: VM・`LoadController`・`cover()`/`eventFilter`・MainWindow の生成順。
