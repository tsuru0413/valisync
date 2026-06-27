# valisync-gui-file-browser spec/実装 再レビュー 改善メモ

> 関連 spec: `valisync-gui-file-browser`（完了・PR #3 merged）。
> 発見の経緯: 「実装が別エージェント作成の可能性」を踏まえた実装レビュー → 続けて「spec 自体も別エージェント作成の可能性」を踏まえた**再レビュー**で、**実装の不具合の多くが spec(特に design)の欠陥に由来**すると判明した。本メモに再レビュー結果（S1–S5）を記録。**S1–S5 はすべて解決済み**（S1/S2/S3=コード＋spec、S4=spec 要件化＋親トレース、S5=完了 spec のため再構成せず close）。

## 課題（再レビューの要点）

実装は spec に**忠実**だが、その spec が**実コードベースの公開 API を検証せずに書かれた**疑いが濃い。design が実在しない API を前提とし、実装者が private アクセス/全走査で穴埋めしている。

## Spec 上の評価

本 spec のコア目的（master-detail / flat 表示）は満たすが、design の API 前提・性能要件・unload・トレーサビリティに欠陥がある。コード単体修正では不十分で、**spec(design/requirements/tasks)とコードをセットで改訂**する必要がある。

## 原因（spec 欠陥）と改善案

### S1（最優先・今回着手）: design が存在しない Session 公開 API を前提
- design「`ChannelBrowserVM` が active_file_key の SignalGroup を Session から取得」「`FileBrowserVM.files` を keys から basename 導出」→ **Session に key 指定の信号取得 / key→ソース名 の公開 API が無い**（`signals()` 全件のみ）。`SignalGroupManager` docstring は「ソース名復元は GUI 層へ委ねる」と書くが手段を公開していない。
- 結果: `FileBrowserVM` が `session._groups`(private) へ直接アクセス（アーキ違反）、`ChannelBrowserVM`/`SignalTableModel` が**セル毎に全信号を走査**（性能アンチパターン）。
- **改善案**: `Session.source_name(key)` と `Session.group_signals(key)` を公開 API 化（`SignalGroupManager` 側にも追加）。`FileBrowserVM` を public API に、`ChannelBrowserVM` を active group 直接取得に、`SignalTableModel` を reset 時スナップショットキャッシュに。design も実 API に合わせて訂正。

### S2（完了）: R5.2「100ms 以内更新」が裏付け無し → 機構ベースに改訂＋構造テスト
- 要件はあるが design/実装に担保機構が無く、検証テストも無かった（反証不能の wall-clock 目標）。
- **対応**: R5.2 を「アクティブ切替は `group_signals(active)` のみで全 Session 走査をしない」機構ベースへ書き換え。`test_channel_browser_vm` に `session.signals`(全走査) を spy し**呼ばれない**ことをアサートする構造テストを追加（ハード非依存・回帰防止、flaky な実測の代替）。
- 関連コミット: `203035c`。

### S3（完了）: unload スレッドが spec 三層で不整合 → R7 として要件化＋root 実装
- R5.3 が「all files unloaded」に言及、design が `"unloaded"` event に言及、実装は `"unloaded"` の死蔵リスナー。だが unload を課す要件は無く `Session.remove_group` も未接続だった。
- **対応（このブランチ）**: unload を **R7（File Unload）として要件化**し、root 設計（option C）で実装。`AppViewModel.unload_file`→`Session.remove_group`→`"unloaded"` 通知。**`GraphAreaVM` が `AppViewModel` を購読してパネル整合（load=refresh / unload=prune）を所有**し、MainWindow からパネル調整を撤去。`GraphPanelVM.prune_missing_signals` ＋ `remove_signal` の `_normalize_axes` で曲線除去と空リージョン解消（信号追加と対称）。FileBrowserView に「Remove File」コンテキストメニュー。死蔵だった `"unloaded"` リスナーは本要件で駆動される実リスナーになった。
- **副次**: 信号削除時の空リージョン残存 follow-up（`docs/multi-axis-empty-region-followup.md`）も同時に解消。
- 関連コミット: `eab395b`/`d664402`/`a976eab`/`e891b01`/`2354324`/`5d28d60`/`cf70c9b`。spec: requirements R7 ＋ design「Unload (R7)」節。実装計画: `docs/superpowers/plans/2026-06-27-file-unload.md`。

### S4（完了）: 要件が親 spec に未トレース / 暗黙要件 → 要件化＋トレース表
- axes が親 `valisync-gui`（29要件）から抽出したのに対し、file-browser は独自 R1–R7 で親に未マップ。D&D・context-menu 保持は success-criteria の散文のみだった。
- **対応**: D&D を **R8**、ChannelBrowser「Add to Active Panel」を **R9** として明示要件化（既存 `test_dnd_workflow`/`test_context_menus` で検証済み）。requirements に **親 valisync-gui への対応表**を追加（R1→親R1、R4→R4.1/4.4、R8→R4.5/4.6・R22、R9→R29.4 等）。実装変更なし（spec ドキュメントのみ）。
- 関連コミット: `5a05c54`。

### S5（close・再構成しない）: tasks.md が spec-authoring 規約違反
- 「同じファイルを編集する複数タスクを同 wave に置かない」に対し Wave 0(0.1/0.2=AppViewModel)・Wave 3(3.1/3.2=MainWindow) が同居（違反は事実）。※ 全タスクは現状 `[x]`（S1 改訂時に更新済み — 旧メモの「未チェック」は陳腐化）。
- **判断**: 本 spec は完了・PR #3 merged。spec-authoring.md は「**進行中の spec は wave 番号の振り直しをしない（進捗整合のため）**」と定めるため、完了済み spec の再構成は便益ゼロかつ規約違反。よって**再構成せず close**（tasks.md に「Revision S5」として明記）。
- **教訓（再発防止）**: 同一ファイル＝別 wave（spec-authoring に明文化済み）を今後の新規 spec で遵守。過去 spec の負債は遡及修正しない。

## 採用方針（推奨）

- **今回（このブランチ/PR）**: S1 をセット改訂として実装（core 公開 API + VM/adapter 修正 + design.md 訂正 + tasks.md チェック更新）。
- **後続（すべて処理済み）**: S2 ✅（機構ベース改訂＋構造テスト）/ S3 ✅（R7 unload・root 実装）/ S4 ✅（R8/R9 要件化＋親トレース表）/ S5 ✅ close（完了 spec は wave 再構成しない）。**再レビュー S1–S5 はこれで全て解決。**

## 関連リンク
- spec: `.kiro/specs/valisync-gui-file-browser/{requirements,design,tasks}.md`
- 改修対象(実装): `src/valisync/core/session.py`, `src/valisync/core/loaders/signal_group_manager.py`, `src/valisync/gui/viewmodels/{file_browser_vm,channel_browser_vm}.py`, `src/valisync/gui/adapters/qt_signal_models.py`
- 規約: `.kiro/steering/spec-authoring.md`
