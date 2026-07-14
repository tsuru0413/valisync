# FU-05: File Browser ヘッダボタン（開く/閉じる）廃止 設計

## 背景 / 課題

- **FU-05**（UX リファイン）: File Browser ヘッダの「開く...」「閉じる」ボタン（SH-07・増分1a／PR #51 で追加）を廃止したい。
- 当初これらは「空リストからの前進（開く）」「選択ファイルを閉じる」の可視導線として追加されたが、その後の増分で**同等の代替導線が全て揃った**ため、ヘッダのボタンは冗長になった。
- 直前の FU-06（ChannelBrowser 追加ボタン廃止）と同型の整理。

現状（`file_browser_view.py`）: ヘッダ行に `open_button`（"開く..."→`open_requested`→MainWindow.open_file）と `close_button`（"閉じる"→`_close_selected`→確認→`unload`）。リスト本体は右クリック "Remove File"（`build_context_menu`→`_confirm_and_unload`）と D&D ロードを持つ。空状態はプレースホルダ表示。

## ゴール

File Browser ヘッダの「開く」「閉じる」ボタンとヘッダ行を撤去し、追加/クローズ導線を既存の menu / toolbar / Ctrl+O / 右クリックに集約する。**空状態プレースホルダは変更しない**（ユーザー判断・2026-07-14）。

## 代替導線（発見性の担保）

| 操作 | 撤去するボタン | 残る代替導線 |
|---|---|---|
| 開く | ヘッダ「開く...」 | Welcome ビュー CTA「計測ファイルを開く (Ctrl+O)」＋ Recent MRU（未ロード時に中央表示）・**ツールバー「開く」**（常時可視）・File>Open メニュー・**Ctrl+O** |
| 閉じる | ヘッダ「閉じる」 | **右クリック "Remove File"**（同一粒度＝ロード済みファイルを確認付きで閉じる・直接代替）・DataExplorer「Remove Source」ボタン/右クリック（ソース粒度の隣接導線） |

開く/閉じるとも複数の可視導線が残るため、2ボタン廃止で発見性は失われない（FU-06 が右クリックメニューで click-add を担保したのと同型）。

## アーキテクチャ / 変更点

### `FileBrowserView`（`gui/views/file_browser_view.py`）
- `open_button`・`close_button` の生成と `header` QHBoxLayout（`layout.addLayout(header)`）を**撤去**。レイアウトは `_stack`（list/placeholder）のみになる。
- 死蔵化する配線を除去:
  - `_close_selected`（`close_button.clicked` 専用メソッド）を削除。
  - `open_requested` シグナル（`open_button` のみが emitter）を削除。
- **残す**: `_confirm_and_unload`・`build_context_menu`（右クリック "Remove File"）・`_default_confirm`・`confirm_fn` DI（クローズの直接代替として不変）。D&D ロード経路・スピナー・プレースホルダも不変。

### `MainWindow`（`gui/views/main_window.py`）
- `self.file_browser_view.open_requested.connect(self.open_file)`（現 `:223`）を撤去（シグナル削除に伴う）。他の Open 導線（`shell_actions.action("open")`・Welcome・ツールバー）は `open_file` に直結済みで不変。

### 空状態プレースホルダ
- **変更しない**。現行文言「ファイルが読み込まれていません / ウィンドウへファイルをドロップして追加」を据え置く（ユーザー判断）。

## データフロー（変更後）

- 開く: Welcome CTA / ツールバー / File>Open / Ctrl+O → `MainWindow.open_file`（不変）。
- 閉じる: File Browser 右クリック "Remove File" → `_confirm_and_unload` → `vm.unload(row)`（不変）／ DataExplorer Remove（不変）。

## エラーハンドリング

- 変更なし（クローズ確認ダイアログ `_default_confirm`／`confirm_fn` DI はそのまま）。

## テスト設計（gui-test-plan）

- **Layer A/B（`FileBrowserView`）**:
  - `open_button`・`close_button` 属性が**存在しない**（`hasattr` 否定）・ヘッダ行がレイアウトに無い。
  - `open_requested` シグナルが存在しない。
  - 右クリック "Remove File" が従来どおり確認経由で `vm.unload` を発火（無回帰）。
  - 空状態プレースホルダ文言が不変。
- **既存テストの更新**: `open_button`／`close_button`／`open_requested`／`_close_selected`／`file_browser_open`／`file_browser_close` を参照する既存テスト（headless / realgui）を grep し、新挙動へ更新/削除する。
- **gui-verify ①ゲート**（入力経路の削除）: 既存 realgui が File Browser の open/close ボタンを実クリックしていれば新挙動へ更新（該当を `grep -l` で特定）。右クリック "Remove File" と D&D ロードの無回帰＋ journey smoke。ボタン撤去は新規入力経路を増やさないため realgui は主に無回帰確認。

## YAGNI（除外）

- プレースホルダにクリック可能な埋め込みボタン/CTA を作らない（テキストも変更しない）。
- 閉じるの可視ボタンを別形で再導入しない（右クリック＋DataExplorer で足りる）。
- Open 導線の新規追加はしない（既存で多重に担保済み）。

## Global 制約

- 変更は `gui/views/` に閉じる。core は Qt 非依存維持。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過（unscoped・repo ルート）。
- Python コメント/文字列に全角約物 `()：+=` 禁止（RUF001/002/003）。ASCII を使う。
- 入力経路（ボタン撤去）変更ゆえ merge 前に gui-verify ①（realgui 無回帰＋ journey smoke）。
