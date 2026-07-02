# 設計 spec: gui-feedback-errors（改善サブスペック②）

エラー・診断・状態フィードバックの可視化。実ユーザージャーニー監査で確定した「サイレント失敗の連鎖」を断つ改善サブスペックの設計。

- **作成**: 2026-07-02
- **ステータス**: 設計承認済み（実装プラン未作成）
- **一次情報源の課題**: [docs/audit-findings-catalog.md](../../audit-findings-catalog.md) の **FB-01〜FB-10**
- **俯瞰**: [docs/roadmap.md](../../roadmap.md) ②改善サブスペック
- **完成イメージ**: brainstorming で提示した3モック（全体レイアウト／モーダルエラー／Diagnostics 詳細＋データフロー）

---

## 1. 目的とゴール

現状、ファイル読み込みの失敗も、成功時のチャンネル skip 等の警告も、ユーザーに一切通知されない（`_on_load_error` が `pass`、`Session.load` が成功時の診断を破棄）。本サブスペックは **診断を運ぶ正準経路を一本化し、専用 Diagnostics ドック＋モーダル＋ステータスバーで可視化**する。

**成功の判定（受け入れの方向性）**
- 破損/非対応ファイルを開こうとすると、ユーザーが理由を伴った通知を必ず受け取る。
- 一部チャンネルが skip された成功ロードで、何がなぜ落ちたかが Diagnostics に残る。
- ロード直後に Channel Browser が対象ファイルの信号で埋まる。

## 2. スコープ

**第1弾（本 spec 最初の実装プラン）**: FB-01 / FB-02 / FB-03 / FB-06。

| ID | 課題（catalog より） |
|---|---|
| FB-01 | 全ロード失敗が無言（`_on_load_error` が `pass`） |
| FB-02 | `Session.load` が成功時 `diagnostics` を破棄→ch skip 警告が GUI へ到達不能 |
| FB-03 | ロード直後にアクティブファイル未設定で Channel Browser が空 |
| FB-06 | ステータスバー未使用（常設の状態サーフェスが無い） |

**同 spec の後続タスク（第2弾以降）**: FB-04（BusyOverlay のラベル/キャンセル）・FB-05（空検索フィードバック）・FB-07（ウィンドウタイトル反映）・FB-08（空状態ガイド）・FB-09（表示中ファイル表示）・FB-10（File Browser の情報/ツールチップ）。

**非ゴール（本サブスペック外）**: 診断のファイル永続化（Phase 3 persistence）／CSV フォーマットピッカーや拡張子拡張（`core-loaders-hardening`。ただし本サブスペックが「診断を見せる器」を用意することで、そちらの警告が可視化される）／File>Open 等のシェル操作（`gui-shell-controls`）。

## 3. サーフェス方針（確定）

**専用「Diagnostics」ドックパネル（診断履歴）＋ハードエラーはモーダル**（ユーザー選択）。

- **ハードエラー**（ロードが完全に失敗＝`LoadError`）: モーダル `QMessageBox.critical`（ファイル名＋平易な理由＋原文メッセージ）。同時に Diagnostics ドックへ記録し、ドックを自動 raise。ステータスバーにも要約。
- **警告**（成功したが注意あり＝`level="warning"` の Diagnostic。ch skip・enum ラベル喪失・重複名・0ch 等）: Diagnostics ドックへ追記＋ステータスバーに要約（例「⚠ 直近ロードで 3 ch スキップ」）。**モーダルは出さない・自動 raise しない**（作業を妨げない）。
- **常設状態**: ステータスバーが「準備完了／読み込み中: file／N files・M signals／⚠直近 K ch スキップ」を表示。ドック＝履歴、ステータスバー＝一行要約＋入口、と役割分担。
- 診断は**セッション内メモリのみ**（Clear で消える。永続化は Phase 3）。

## 4. アーキテクチャとコンポーネント

MVVM を維持し、Session を唯一のゲートウェイとする。

### 4.1 Core（案A — 診断伝播の正準化）

- `Session.load` の戻り値を `str`（key）から **`LoadOutcome(key: str, diagnostics: tuple[Diagnostic, ...])`**（`frozen` dataclass）へ変更。成功時に loader の `result.diagnostics` を破棄せず返す。
- `LoadError` に **`diagnostics: tuple[Diagnostic, ...]`** を追加（既存の `messages: list[str]` は後方互換のため維持）。失敗時も loader 診断を保持。
- `Session.load_many` は `LoadManyResult` の `succeeded` を key の列から `LoadOutcome` の列へ拡張（診断を保持）。
- `Diagnostic` / `LoadResult` の構造は既存のものを使用（`level`・`message`・`signal_name` 等。[load_result.py](../../../src/valisync/core/models/load_result.py)）。

> **注意**: これは core の公開 API 変更。呼び出し側（`main_window`・`app_viewmodel.request_load`・関連テスト）を追従させる。構造変更のため実装着手はユーザー承認済みであることを前提とする。

### 4.2 Worker

- `LoadWorkerSignals.finished` を `Signal(object)`（`LoadOutcome` を運ぶ）に、`failed` を `Signal(object)`（`LoadError` を運ぶ）に拡張（現状はどちらも `str`）。
- `LoadWorker.run` は成功時 `LoadOutcome` を、失敗時は捕捉した `LoadError`（または汎用例外）を emit。
- `LoadController._finish/_fail` は outcome/error を `on_success(LoadOutcome)` / `on_error(LoadError)` へ渡す。

### 4.3 新 ViewModel: `DiagnosticsViewModel`（Qt-free・Observable）

- 状態: `list[DiagnosticEntry]`。`DiagnosticEntry` = `Diagnostic` ＋ `source`（ファイル basename）＋ `timestamp`（表示用。壁時計時刻または受領順の連番。テストで決定的にするためクロックは注入可能にする）。
- API: `add(source, diagnostics)` / `clear()` / `entries(level_filter)` / `counts()`（error/warning 件数）。変更時 `_notify("diagnostics")`。
- テスト容易性のため純 Python。

### 4.4 新 View: `DiagnosticsView(QDockWidget)`

- `objectName="diagnostics_dock"`（saveState/restoreState 対応。既存ドックと整合）。既定は `BottomDockWidgetArea`。
- 中身: テーブル（列 = レベルアイコン / 時刻 / ソース / メッセージ / 対象[signal_name]）＋ヘッダのフィルタ（All / Errors / Warnings）＋ Clear ＋ 件数チップ。
- 行ダブルクリック → 該当ソース/信号へジャンプ（Channel Browser で選択）。選択行はハイライト。
- `View` メニューに `diagnostics_dock.toggleViewAction()` を追加。

### 4.5 MainWindow の配線変更

- Diagnostics ドックと `statusBar()` を構築。
- `_on_load_error(err: LoadError)`: `DiagnosticsVM.add(source, err.diagnostics or [messages...])` ＋ `QMessageBox.critical(...)` ＋ ステータスバー更新 ＋ ドック自動 raise（FB-01）。
- `_on_loaded(outcome: LoadOutcome)`: `register_loaded(outcome.key)` ＋ `DiagnosticsVM.add(source, outcome.diagnostics)` ＋ **アクティブファイル設定**（FB-03）＋ ステータスバー更新（警告があれば要約）。
- `_load_file` の submit で `on_success`/`on_error` の型が `LoadOutcome`/`LoadError` になる。

## 5. データフロー

```
Loader(LoadResult: group + diagnostics)
  → Session.load  →  LoadOutcome(key, diagnostics)      ← 案A で成功時も診断を返す
  → LoadWorker.finished(LoadOutcome) / failed(LoadError)
  → LoadController → on_success/on_error（GUIスレッド）
  → MainWindow → DiagnosticsViewModel.add(...)
  → DiagnosticsView（ドック）      ／ error は QMessageBox.critical も
  → statusBar 要約 ＋（FB-03）アクティブファイル設定
```

## 6. FB 項目 → 設計の対応

| ID | 対応 |
|---|---|
| FB-01 | `_on_load_error` を pass から「VM.add＋QMessageBox.critical＋status＋dock raise」へ |
| FB-02 | 案A（Session.load→LoadOutcome/LoadError に diagnostics）＋ DiagnosticsVM/View で成功時警告を表示 |
| FB-03 | `_on_loaded` でロードした key をアクティブ化（`app_vm.set_active_file`） |
| FB-06 | `statusBar()` を新設し、状態＋直近警告要約＋件数を常設表示 |

## 7. エラー処理・エッジケース

- LoadError に構造化 diagnostics が無い（汎用例外）場合は `messages`/`str(exc)` を1件の error Diagnostic として扱う。
- 診断が空の成功ロードは何も追記しない（ノイズを出さない）。
- 0ch 成功（`core-loaders-hardening` LD-05 が warning を出す前提）でも、本サブスペックのドックがそれを表示できる器を提供する（LD 側の診断発行はスコープ外）。
- ドックは診断ゼロでも存在（トグル可）。空時はプレースホルダ（「診断はありません」）。

## 8. テスト戦略（docs/gui-testing-layers.md 準拠）

- **Core 単体**: `Session.load` が `LoadOutcome`（key＋diagnostics）を返す／`LoadError.diagnostics` を保持する／`load_many` の追従。
- **Layer A（ロジック直叩き）**: `DiagnosticsViewModel`（add/clear/filter/counts/通知）。MainWindow 配線（`_on_load_error`→VM.add＋ダイアログ呼出、`_on_loaded`→診断反映＋アクティブファイル設定）。`QMessageBox` は monkeypatch で呼び出し引数を検証。
- **Layer B（合成イベント/レンダ）**: `DiagnosticsView` の描画（行・列・フィルタ・Clear・空プレースホルダ）。
- **入力経路（Layer B/C）**: フィルタボタン、行ダブルクリック→ジャンプ。着手時 `/gui-test-plan` で②実質的な受け入れ要件を設計し、merge 前 `/gui-verify` で①証拠ゲート。ダイアログ/ドック表示は隠しジェスチャではないため realgui 必須度は低いが、**ダブルクリック→該当信号ジャンプ**は Layer C 候補。

## 9. トレーサビリティ

本 spec は catalog の FB-01/02/03/06 を第1弾で満たす。FB-04/05/07-10 は同 spec の後続タスクとして writing-plans で番号付けする。実装プランは `docs/superpowers/plans/2026-07-02-gui-feedback-errors-*.md` に作成予定。
