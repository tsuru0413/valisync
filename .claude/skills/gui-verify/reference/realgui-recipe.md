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

## ハングは2種類ある — in-test watchdog では止められない方に注意

上の watchdog（ワーカーが ESC を注入）は「テストのドライバが release を撒けず固まる」**ドライバ起因**ハングを解く。だが**プロダクトコード側が `QDrag.exec` に再入して固まる**別種のハングはこれで止まらない（メインスレッドが OLE モーダルに wedge し、ワーカーの ESC も効かないことがある）。この場合:

- **外部プロセスの watchdog で殺す**。pytest をバックグラウンド起動し、別プロセス（PowerShell 等）で CPU/生存/ログ成長をポーリングし、絶対デッドライン超過 or ログ停滞で `taskkill /PID <pid> /T /F`。バックグラウンド化された pytest はツールの timeout が効かないため外部 kill が必須。
- 停止箇所の特定は **`faulthandler.dump_traceback_later(N, exit=True)`** を仕込む（N 秒後に全スレッドのスタックをダンプして強制 exit → メインスレッドが `mouseDragEvent`→`drag.exec` のどこで固まったか一発で判る）。zone 分類の `(lx,ly,w,h,zone)` ＋ `scene.dragButtons/dragItem` を print すれば「どのアイテムへ・どの座標で」誤配送されたかも観測できる。

## 再入 QDrag ハング: drop 中の rebuild が scene 参照を腐らせる

`mouseDragEvent` から `QDrag.exec()`（軸移動）を起動し、その drop（`dropEvent`）が **exec のモーダルスタック内で** scene アイテムを rebuild すると、pyqtgraph の `GraphicsScene` が press/drag/hover 参照（`dragItem`/`lastHoverEvent`/`clickEvents`/`dragButtons`）をドラッグ元アイテムに残したままそれを破棄する。pyqtgraph は次ドラッグの配送先を `lastHoverEvent.dragItems()`／`dragItem` から選ぶため、**移動後の最初のジェスチャが破棄済みアイテムへ誤配送**される（no-op、さらに stale 座標系で枠外と誤分類 → 再び `QDrag.exec` 再入 → **無限ハング**）。

- **修正**: drop の relayout を即時実行せず `QTimer.singleShot(0, ...)` で**次イベントループターンへ遅延**（QDrag が完全に巻き戻ってから rebuild）。rebuild 後に scene の `dragButtons/dragItem/clickEvents/lastDrag/lastHoverEvent` をクリアし、次ジェスチャを `itemsNearEvent` で実アイテムに再発見させる。
- **回帰ガード**: 「移動 → 直後に別ジェスチャ」を1テストに含める（実例: `tests/realgui/test_move_then_resize.py`）。移動単体・リサイズ単体では出ない。
- 詳細は memory `gui_realgui_qdrag_rebuild_stale_scene`。

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

## 実ホイールスクロール（MOUSEEVENTF_WHEEL）

`_realgui_input.wheel(x, y, delta)`（FU-01・PR #81 で確立）: カーソルを物理 (x, y) へ置き `mouse_event(0x0800, 0, 0, delta, 0)` を発行する。delta は WHEEL_DELTA(120) の倍数（負=下スクロール）。

- ホイールは**カーソル下のウィジェット**へ配送される — 対象 viewport 上に置いてから発行（`wheel()` が `SetCursorPos` を内包）。
- QDrag と違い OLE モーダルループは無い — `QApplication.processEvents()` の pump だけで配送され、別 OS スレッド・watchdog は不要。
- 到達判定は `visibleRegion()` 非空で行うが、**部分可視で抜けると中心クリックが viewport 外へ落ちる**ため、ループ後に念押しで 1 ノッチ回す（実例: `tests/realgui/test_expansion_dialog_realinput.py`）。
- 合成代替（`verticalScrollBar().setValue()`・`QWheelEvent` 送出）は Layer B であり Layer C を騙れない。契約ガード（`tests/gui/test_realgui_layer_c_contract.py`）の正規表現は `wheel(` を実入力プリミティブとして認識する。
