# FU-01 修正設計 — ExpansionDialog のスクロール化と画面内クランプ

**日付**: 2026-07-11
**課題**: FU-01（[docs/audit-findings-catalog.md](../../audit-findings-catalog.md) FU-01 行）
**種別**: バグ修正（GUI レイアウト・根本解決）

## 問題

LD-14 の展開確認モーダル `ExpansionDialog` は、1024 列超チャンネルのチェックボックスを `QVBoxLayout` へ直接 `addWidget` するのみでスクロール領域がない。超過チャンネルが多数あるとダイアログが画面外へ伸び、**下方のチェックボックスと OK/Cancel ボタンにアクセス不能** → 展開/スキップ選択が事実上不能になる。

再現は確定済み（FU-07 の prod プロファイル調査・2026-07-10）: 広幅チャンネル 60 本で**ダイアログ全高 1940px > 画面 816px**・スクロール無し・OK/Cancel 画面外。

## 根本原因

`src/valisync/gui/views/expansion_dialog.py:42-47` — チェックボックス列がトップレベル layout に直接積まれ、ダイアログの高さ要求がチャンネル数に比例して無制限に伸びる（FU-04 と同族の「コンテンツ比例の無制限サイズ要求」。`docs/development.md` 落とし穴の QStackedWidget 節参照）。

## 設計方針（承認済み: A 案）

**チェックボックス列だけを `QScrollArea`（`widgetResizable=True`）に入れ、それ以外は常時可視に固定する。ダイアログ高は「内容が画面に収まるならコンパクトのまま・収まらない場合のみ画面内にクランプ」。**

- **スクロール内**: チェックボックス列のみ（内側 `QWidget`＋`QVBoxLayout` に載せ替え）。
- **スクロール外（常時可視）**: ヘッダ説明ラベル／「すべて展開」「すべてスキップ」ボタン行／合計ラベル（`展開後の追加列数: N`）／OK・Cancel（`QDialogButtonBox`）。
- **高さポリシー**: 少数チャンネル（内容ヒントが画面に収まる）では従来同等のコンパクト表示（不要なスクロールバーを出さない）。内容が画面高を超える場合のみ、対象スクリーンの `availableGeometry` 基準でダイアログ高を画面内にクランプしスクロールで全チェックボックスへ到達させる（クランプの厳密な機構・マージン値はプラン）。
- **API・挙動は不変**: `_checks` リスト／`toggled` 配線／`_update_total`／`_select_all`・`_select_none`／`ask()` の契約（Cancel＝空集合）／初期状態=全未チェック（慎重側）は一切変えない。既存テスト4本は無傷で通る。

### 別案と不採用理由（記録）

- **B. QListWidget（checkable items）置換**: スクロール内蔵・数千行スケールだが、widget 構造と既存テストの書き換えが必要で 60 本規模では実利差なし → 過剰。
- **C. 検索/ページング付きリッチダイアログ**: YAGNI。

### 非目標（Non-Goals）

- `ExpansionConfirmer`（ワーカースレッド委譲）・`mdf_loader` 側（`EXPANSION_COLUMN_LIMIT`・`ExpansionRequest`）は触らない。
- チェック初期値（全未チェック＝全スキップ）の方針変更はしない。
- 幅方向のクランプは扱わない（観測された不具合は高さのみ。チャンネル名由来の幅膨張が将来観測されたら別課題）。

## 変更するユニット

### `ExpansionDialog.__init__`（`src/valisync/gui/views/expansion_dialog.py:33-68`）

- チェックボックス生成ループの載せ先を、内側 widget の layout に変更し、`QScrollArea(widgetResizable=True)` でラップしてトップレベル layout の（ラベルとボタン行の間の）位置に追加する。スクロール領域には縦 stretch を与え、余白はスクロール領域が吸収する。
- ダイアログ高のクランプ: 対象スクリーン（親なしモーダルのため通常 `primaryScreen`。`screen()` が取れる場合はそれ）の `availableGeometry().height()` からマージンを引いた値を上限とし、内容ヒントがそれ以下なら内容どおり、超えるなら上限に制限する。

## テスト戦略（GUI テストレイヤー準拠・詳細は writing-plans 時に /gui-test-plan で確定）

### Layer A（決定的・CI）— 回帰の主ガード

1. **高さ有界性**: 60 チャンネルの `ExpansionRequest` でダイアログを構築・show した高さが `availableGeometry().height()` 以下（offscreen でも `availableGeometry` は定義されるためクランプロジックは検証可能）。修正前は ~1940px 相当で RED。
2. **ボタン到達性（構造）**: 60 チャンネル時に `QDialogButtonBox` の矩形がダイアログ矩形内に収まる。
3. **コンパクト性の保存**: 3 チャンネル時にスクロール不要（内側 widget 高 ≤ viewport 高）で従来同等の小さなダイアログ。
4. **既存挙動の無回帰**: 既存4テスト（checked indices／既定全未チェック／全選択・全解除／reject=空集合）がそのまま通る。スクロール内へ移動したチェックボックスでも `_checks`・合計ラベル・`ask()` 契約が不変。

### Layer C（realgui・ローカル `--realgui`）— 「アクセス不能」の直接反証

実ディスプレイで 60 チャンネルのダイアログを表示し:

1. ダイアログ矩形と OK ボタンが**画面内**（`visibleRegion` 非空＋グローバル矩形が screen 内。`isVisible()` は不使用 — FU-04 と同判定）。
2. **実スクロールで最下段チェックボックスへ到達 → 実クリックでチェック → OK を実クリック** → `ask()` の戻りに最下段インデックスが含まれる（到達性のエンドツーエンド実証）。実スクロール手段（実マウスホイール `MOUSEEVENTF_WHEEL` の新プリミティブ or スクロールバーの実ドラッグ）は realgui 手法として確立が必要 — プラン時に `/gui-test-plan` でレシピ化する。
3. スクリーンショット保存＋目視判定（ダイアログ全体が画面内・スクロールバー可視）。
4. **sabotage honest-RED**: スクロールラップ（またはクランプ）を一時的に外すと OK ボタンが画面外に出て 1. が FAIL することを実証してから GREEN を取る。

## 受け入れ基準

- 60 チャンネル（prod 相当の広幅60本）でもダイアログが画面内に収まり、全チェックボックスと OK/Cancel に到達・操作できる（Layer A 構造＋Layer C 実測）。
- 少数チャンネルでは従来どおりコンパクト（不要なスクロールなし）。
- 既存挙動（選択結果・全選択/全解除・Cancel=空集合・初期全未チェック）無回帰。
- 品質ゲート（pytest / ruff check / ruff format --check / mypy）通過。

## 影響範囲

- 変更: `src/valisync/gui/views/expansion_dialog.py` のみ。
- 新規テスト: 高さ有界性/コンパクト性/ボタン到達性の Layer A、到達性エンドツーエンドの realgui（＋実スクロール・プリミティブの共有化があれば `tests/realgui/_realgui_input.py`）。
- 他ファイル・他挙動への影響なし（`ExpansionConfirmer` 経由の呼び出し契約不変）。
