# valisync-gui-file-browser spec/実装 再レビュー 改善メモ

> 関連 spec: `valisync-gui-file-browser`（完了・PR #3 merged）。
> 発見の経緯: 「実装が別エージェント作成の可能性」を踏まえた実装レビュー → 続けて「spec 自体も別エージェント作成の可能性」を踏まえた**再レビュー**で、**実装の不具合の多くが spec(特に design)の欠陥に由来**すると判明した。本メモに再レビュー結果（S1–S5）を記録し、S1 を spec+コードのセット改訂として着手、S2–S5 を後続バックログとする。

## 課題（再レビューの要点）

実装は spec に**忠実**だが、その spec が**実コードベースの公開 API を検証せずに書かれた**疑いが濃い。design が実在しない API を前提とし、実装者が private アクセス/全走査で穴埋めしている。

## Spec 上の評価

本 spec のコア目的（master-detail / flat 表示）は満たすが、design の API 前提・性能要件・unload・トレーサビリティに欠陥がある。コード単体修正では不十分で、**spec(design/requirements/tasks)とコードをセットで改訂**する必要がある。

## 原因（spec 欠陥）と改善案

### S1（最優先・今回着手）: design が存在しない Session 公開 API を前提
- design「`ChannelBrowserVM` が active_file_key の SignalGroup を Session から取得」「`FileBrowserVM.files` を keys から basename 導出」→ **Session に key 指定の信号取得 / key→ソース名 の公開 API が無い**（`signals()` 全件のみ）。`SignalGroupManager` docstring は「ソース名復元は GUI 層へ委ねる」と書くが手段を公開していない。
- 結果: `FileBrowserVM` が `session._groups`(private) へ直接アクセス（アーキ違反）、`ChannelBrowserVM`/`SignalTableModel` が**セル毎に全信号を走査**（性能アンチパターン）。
- **改善案**: `Session.source_name(key)` と `Session.group_signals(key)` を公開 API 化（`SignalGroupManager` 側にも追加）。`FileBrowserVM` を public API に、`ChannelBrowserVM` を active group 直接取得に、`SignalTableModel` を reset 時スナップショットキャッシュに。design も実 API に合わせて訂正。

### S2: R5.2「100ms 以内更新」が裏付け無し
- 要件はあるが design/実装に担保機構が無く、検証テストも無い。S1 のキャッシュ化で実態は改善するが、要件として**検証可能化（テスト）or 緩和**が必要。

### S3: unload スレッドが spec 三層で不整合
- R5.3 が「all files unloaded」に言及、design が `"unloaded"` event に言及、実装は `"unloaded"` の死蔵リスナー。だが unload を課す要件は無く `Session.remove_group` も未接続。
- **改善案**: unload を要件化して実装（AppVM に `unload_file`+`"unloaded"` 通知→`remove_group`）するか、不要なら死蔵リスナー削除＋R5.3 文言修正。要ユーザー判断。

### S4: 要件が親 spec に未トレース / 暗黙要件
- axes が R8.6–8.18 を親 `valisync-gui` から抽出したのに対し、file-browser は独自 R1–R6（親 29 要件に未マップ）。D&D・context-menu の保持は success-criteria の散文のみで要件化されていない。
- **改善案**: 要件を親へトレース、D&D/context-menu を明示要件化。

### S5: tasks.md が spec-authoring 規約違反
- 「同じファイルを編集する複数タスクを同 wave に置かない」に対し Wave 0(0.1/0.2=AppViewModel)・Wave 3(3.1/3.2=MainWindow) が同居。全タスク `[ ]` 未チェック（merge 済み）。
- **改善案**: wave 再構成（同ファイル分離）＋チェックボックス更新。

## 採用方針（推奨）

- **今回（このブランチ/PR）**: S1 をセット改訂として実装（core 公開 API + VM/adapter 修正 + design.md 訂正 + tasks.md チェック更新）。
- **後続**: S2（検証テスト）, S3（unload 要否の判断→実装 or 削除）, S4（親トレース＋要件追記）, S5(残りの wave 再構成) を順次。spec 化が要るほどの規模ではなく、本 spec の design/requirements への追記で吸収可能。

## 関連リンク
- spec: `.kiro/specs/valisync-gui-file-browser/{requirements,design,tasks}.md`
- 改修対象(実装): `src/valisync/core/session.py`, `src/valisync/core/loaders/signal_group_manager.py`, `src/valisync/gui/viewmodels/{file_browser_vm,channel_browser_vm}.py`, `src/valisync/gui/adapters/qt_signal_models.py`
- 規約: `.kiro/steering/spec-authoring.md`
