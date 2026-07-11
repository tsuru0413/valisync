# FU-02 修正設計 — BusyOverlay の親 resize 追従

**日付**: 2026-07-11
**課題**: FU-02（[docs/audit-findings-catalog.md](../../audit-findings-catalog.md) FU-02 行）
**種別**: バグ修正（GUI レイアウト・根本解決）

## 問題

`BusyOverlay`（ロード中のメッセージ・不定進捗バー・キャンセルボタン）は親=MainWindow 全体を `cover()`＝`setGeometry(parent.rect())` で覆うが、**呼ばれるのは `show()` 時のみ**で親の resize を購読しない。表示中にウィンドウが resize されると overlay のジオメトリが stale になり、透過 overlay のためラベル/進捗/**キャンセルボタンが旧矩形の中心に浮いたままズレて届きにくくなる**。

再現は確定済み（ジオメトリ実測・2026-07-10）: 表示時 window=overlay=1400×844 一致 → window を 1024×650 に resize しても **overlay=1400×844 のまま**。手動 `cover()` 呼出で一致復帰＝**親 resize 購読で `cover()` を再実行すれば足りると実証済み**。

## 根本原因

`src/valisync/gui/views/busy_overlay.py:55-64` — `cover()` の呼び出し点が `show()` の1箇所のみで、表示中の親ジオメトリ変化に追従する経路が存在しない。

## 設計方針（承認済み: A 案）

**BusyOverlay 自身が親を `installEventFilter` で購読し、親の `Resize` イベントで（可視時のみ）`cover()` を再実行する。**「親を覆う」責務が overlay 内で自己完結し、親側の変更ゼロ・将来別の親で使っても自動で正しい。

- `__init__` で `parent` が与えられていれば `parent.installEventFilter(self)`（`parent=None` 構築は従来どおり filter なしの no-op）。
- `eventFilter(watched, event)` override: `event.type() == QEvent.Type.Resize` かつ**自身が可視**のとき `cover()`。戻り値は常に `False`（イベントを消費しない — 親の通常の resize 処理を妨げない）。不可視時は何もしない（既存の `show()`→`cover()` が次回表示時に正す）。
- `Move` は購読しない（子ウィジェットのジオメトリは親相対のため親の移動に影響されない）。

### 別案と不採用理由（記録）

- **B. `MainWindow.resizeEvent` override で `busy_overlay.cover()`**: 動くが overlay のジオメトリ責務が親へ漏れ、overlay を使う親が増えるたび再実装（忘れたら再発）。
- **C. タイマーポーリング**: 遅延・無駄・論外。

### 非目標（Non-Goals）

- 背景の dim/半透明化（overlay が透過なのは既存仕様 — 視認性の UX 改善は別課題）。
- `LoadController` の表示駆動（カウントベース show/hide）・`cover()`/`show()` の既存契約・`cancel_requested` 配線は変えない。
- 親の付け替え（`setParent`）後の filter 張り直しは扱わない（本アプリでは MainWindow 固定・YAGNI）。

## 変更するユニット

### `BusyOverlay`（`src/valisync/gui/views/busy_overlay.py`）

- `__init__`: 親があれば `parent.installEventFilter(self)` を1行追加。
- `eventFilter` override を追加（上記仕様・~5行）。

## テスト戦略（GUI テストレイヤー準拠・詳細は writing-plans 時に /gui-test-plan で確定）

### Layer A/B（決定的・CI）— 回帰の主ガード

1. **表示中 resize の追従**: 親 widget 上に overlay を show → 親を `resize()`（実 `QResizeEvent` が同期配送される）→ `overlay.geometry() == parent.rect()`。**修正前は旧サイズのまま残り RED**（catalog の実測 1400×844→1024×650 と同型）。
2. **非表示中 resize は無害**: overlay 非表示で親 resize → その後 `show()` で正しく cover（既存挙動の回帰ガード）。
3. **イベント非消費**: 親自身の resize 処理が阻害されない（`eventFilter` が False を返す — 親の resize 後サイズが要求どおりであることで検証）。
4. **既存挙動の無回帰**: 既存 BusyOverlay テスト（メッセージ・不定進捗・cancel_requested・show/cover）がそのまま通る。

### Layer C（realgui・ローカル `--realgui`）— 実 WM 経路と実クリック到達の反証

実ディスプレイの MainWindow で overlay を表示し:

1. **実 WM 経由のウィンドウリサイズ**（Win32 `SetWindowPos`/`MoveWindow`＝OS→Qt の `WM_SIZE` 変換を通る実経路。`widget.resize()` の Qt 内部経路とは別）→ overlay が新ジオメトリへ追従（`geometry == parent.rect()`）。実 WM リサイズの駆動は realgui 新手法 — プラン時に `/gui-test-plan` でレシピ化する。
2. **リサイズ後のキャンセルボタン実座標を実クリック → `cancel_requested` 発火**（FU-02 の実症状「ロード中に resize するとキャンセルが届きにくい」の直接反証。修正前はボタンが旧中心にズレるため新中心の実クリックが外れる）。
3. スクリーンショット保存＋目視判定（overlay の中身がリサイズ後ウィンドウの中央にあること）。
4. **sabotage honest-RED**: `installEventFilter` 行を一時的に外すと 1.（追従）が FAIL することを実証してから GREEN を取る。

## 受け入れ基準

- overlay 表示中に親が resize されても overlay が親全域を覆い続け、キャンセル/ラベル/進捗が新ジオメトリの中央に位置する（Layer A/B 構造＋Layer C 実測）。
- 非表示中の resize は無害（次回 show で正しく cover）。
- 既存挙動（メッセージ・不定進捗・cancel 配線・show/hide 駆動）無回帰。
- 品質ゲート（pytest / ruff check / ruff format --check / mypy）通過。

## 影響範囲

- 変更: `src/valisync/gui/views/busy_overlay.py` のみ。
- 新規テスト: resize 追従の Layer A/B、実 WM リサイズ＋Cancel 実クリックの realgui（＋実 WM リサイズ手法の共有化があれば `tests/realgui/_realgui_input.py`）。
- 他ファイル・他挙動への影響なし（`LoadController`/`ExportController` 経由の利用契約不変）。
