# realgui 駆動レシピ（Layer C 実装の落とし穴と確立パターン）

> `/gui-verify` および手書きで `tests/realgui/` を書くときの**操作知識（HOW）**。方針（WHEN）は `docs/gui-testing-layers.md`。

## 実 D&D は別 OS スレッド＋watchdog で駆動する

`QDrag.exec()` は Windows で OLE `DoDragDrop` モーダルループに入り、Qt の single-shot タイマーを pump しない。LEFTDOWN 後の release を `QTimer.singleShot` で撒くと**一度も発火せず無限ハング**（実測: 約27分ブロック・スクショ0枚）。

確定パターン（PASS 実証）:
- マウス駆動を**別 OS スレッド**（`threading` ＋ `time.sleep` ＋ `ctypes` `user32.mouse_event`）で実時間注入する。
- メインスレッドは `QApplication.processEvents()` ループで GUI を pump（threshold move で `QDrag.exec` に入りブロック → ワーカーの実 OS 入力が OLE ループを駆動 → drop で復帰）。
- **watchdog**: N 秒で解決しなければワーカーが `keybd_event(VK_ESCAPE)` ＋ LEFTUP を強制注入して解放。
- drop 完了検知は `dropEvent` をフックして flag を立てる。
- 実例: `tests/realgui/test_multi_column_axis.py`。

## スクショは GUI スレッドで撮る

ワーカースレッドからの Qt `grabWindow` は不可。drag 中の絵は `dragMoveEvent` 内（＝GUI スレッド・drag 中）で撮る。

## offscreen の grab() は文字が□になる

`QT_QPA_PLATFORM=offscreen` の `QWidget.grab()` は全文字が豆腐（□＝フォント無し）。**読める画像は `QT_QPA_PLATFORM=windows` で撮る**。

## DPI 論理→物理変換

物理カーソル座標 = 論理座標 × `devicePixelRatioF()`。`mouse_event`/`SendInput` に渡す座標は物理。

## PySide6 の mapFromScene

`QGraphicsView.mapFromScene()` は PySide6 で `QPoint` を返す（`.toPoint()` を付けると AttributeError）。

## sendEvent では D&D 配送経路を再現できない

合成 `QApplication.sendEvent(QDropEvent)` は親 view / 子 plot_widget / viewport いずれに送っても `dropEvent` に届かない（このビューは「コンテナが DND 契約、子は `setAcceptDrops(False)`」設計で、実ドラッグは子→親バブリングで届くが合成イベントにはバブリング機構が無い）。

含意:
- ドロップ**ロジック**（ゾーン→VM メソッド）= ハンドラ直叩きで Layer A/B 検証可（`view.dropEvent(event)` を直接呼ぶ）。
- **実配送経路**（`QDrag.exec` ＋ヒットテスト＋子→親バブリング＋`setAcceptDrops` 配線）= **Layer C のみ**。
- context-menu（`QContextMenuEvent`）は viewport に届くので Layer B で再現可 — **D&D だけの特性**。
