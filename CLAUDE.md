# CLAUDE.md

このファイルは **エントリポイント** — 詳細情報は別ファイルに分散し、ここではポインタと最小限の不変情報のみ保持する。本ファイルが肥大化してきたら積極的に `docs/` に分離する。

## 情報の探し方 (優先順位)

| 順位 | 場所 | 内容 |
|---|---|---|
| 1 | `.kiro/specs/<spec>/{requirements,design,tasks}.md` | 要件・設計・実装計画 (**一次情報源**) |
| 2 | `.kiro/steering/{product,tech,structure,spec-authoring,workflow}.md` | プロダクト原則・技術選定・ディレクトリ構造・spec 生成ルール・ブランチ運用 |
| 3 | `docs/<topic>.md` | spec 化されていない実装ノート・運用メモ |
| 4 | このファイル | 上記で発見できないハマりどころと方針概要 |

**ルール**: `.kiro/` または `docs/` で確認可能な情報は本ファイルに重複させず、ポインタで繋ぐ。コードを読めば自明な事実 (ファイル名・関数シグネチャ等) も本ファイルには書かない。

## プロジェクト概要

ADAS ソフトウェア開発向けの時系列信号データ統合・同期・解析デスクトップ GUI アプリケーション。CAN・XCP・Ethernet・CSV フォーマットの信号を統一時間軸上で可視化・分析する。

詳細: `.kiro/steering/product.md`

## リポジトリ

- **Remote**: `git@github.com:tsuru0413/valisync.git`
- **CI**: GitHub Actions (push to main / 全 PR で品質ゲート自動実行)

## 開発ワークフロー (Kiro + Claude Code 併用)

詳細: `docs/dual-agent-workflow.md`

- **Kiro Spec** で要件→設計→タスクを生成し、**Claude Code** で tasks.md を消化する
- CLAUDE.md はエントリポイント (薄く保つ)。詳細は `.kiro/` と `docs/` に分散
- steering/ は常時適用ルール、specs/ は機能単位の一次情報源、docs/ は横断的運用知識

## ブランチ運用 (常時適用)

詳細: `.kiro/steering/workflow.md`

- **main は本番ブランチ** — 直接編集は禁止 (緊急 hotfix を除く)
- **新機能・修正は `feature/<spec-name>` ブランチで実装** — spec 単位でブランチを切るのが原則
- **フロー**: feature ブランチで実装 → ローカル品質ゲート通過 → push → `gh pr create` → CI 通過 → `gh pr merge --auto` → `git fetch --prune`
- **Claude Code / Kiro の振る舞い**: 新規 spec 実装に着手する際は最初に `git checkout -b feature/<spec-name>` する

## Phase 状況

| Phase | スコープ | 状況 | 一次情報源 |
|---|---|---|---|
| Phase 1 / valisync-core | Signal・Loader・Sync・Formula・補間・統計・Downsampler・Export・Session | 完了 (PR #2 merged) | `.kiro/specs/valisync-core/` |
| Phase 2 / valisync-gui-mvp | GUI 歩く骨格: シェル/ドッキング・データ取込/閲覧・タブ/パネル・Y-T 波形・X/Y ズーム/パン・動的 LOD・X 軸同期・D&D・コンテキストメニュー | 完了 (PR #2 merged) | `.kiro/specs/valisync-gui-mvp/` |
| Phase 2 / valisync-gui-file-browser | FileBrowser の分離: 読み込み済みファイルリストと選択ファイルごとの信号フラットリスト表示 | 完了 (PR #3 merged)。再レビュー S1–S5 すべて解決（S3=File Unload/R7 追加、S5=完了specのため再構成せず close）— 詳細は [docs/file-browser-spec-revision-followup.md](docs/file-browser-spec-revision-followup.md) | `.kiro/specs/valisync-gui-file-browser/` |
| Phase 2 / valisync-gui-axes | 複数Y軸レイアウト: リージョンベースのオーバーレイ・Auto-Fit 縮尺・複数列グリッド配置 | R1–R6 完了。R2–R6 は PR #4 merged。**R1（複数列グリッド）は PR #4 で完了扱いだったが未実装だったため再実装し PR #13 merged（2026-06-27）** — 詳細は [docs/multi-axis-multicolumn-followup.md](docs/multi-axis-multicolumn-followup.md) / [実装計画](docs/superpowers/plans/2026-06-27-multi-column-y-axis.md)。信号削除時の空リージョン残存は案A（PR #10）+ 案B（高さ保持＝絶対比率保持＋空白, PR #14 merged）で解決済み — 詳細は [docs/multi-axis-empty-region-followup.md](docs/multi-axis-empty-region-followup.md)。軸の移動・並べ替え時の高さ保持も同原理で対応（`_layout_column_preserving`、PR pending）— 設計 [docs/superpowers/specs/2026-06-28-y-axis-move-height-preserve-design.md](docs/superpowers/specs/2026-06-28-y-axis-move-height-preserve-design.md) | `.kiro/specs/valisync-gui-axes/` |

> Phase 2 `valisync-gui` は 6 sub-spec に分解済み（mvp / axes / analysis / derived / views / script）。詳細は `docs/roadmap.md`。

実装時は **必ず該当 spec の `tasks.md` に従って番号順 / 依存グラフ順** に進める。完了タスクは `tasks.md` のチェックボックスを `[x]` に更新。

## プロジェクト方針 (要約)

詳細: `docs/policies.md`

- **修正案は症状の隠蔽/緩和/根本解決を明示** — 根本解決を優先
- **リポジトリ構造はその都度最適化** — 責務分割のため新規ファイル/ディレクトリ作成を躊躇しない
- **CLAUDE.md はタスクごとに熟成** — 追記候補をユーザーに確認、肥大したら分離

## 主要コマンド (品質ゲート)

```bash
uv sync --extra dev          # 初回または依存変更後
uv run pytest                # 全テスト
uv run ruff check            # lint
uv run ruff format           # format
uv run mypy src/             # 型チェック
```

コミット前に上記全てを通すのが本プロジェクトの品質ゲート。詳細は `docs/development.md` を参照。

GUI 機能・操作を実装するときは **GUI テストレイヤー（Layer A/B 必須・CI / Layer C はローカル `--realgui`）** に従う。詳細: `docs/gui-testing-layers.md`（`.kiro/steering/workflow.md` §7 で必須化）。

## 開発環境の落とし穴

詳細: `docs/development.md` 末尾参照。

## ファイル更新ルール

- **コメント**: 何 (WHAT) ではなく なぜ (WHY) を書く。自明なコードに説明を付けない
- **`.kiro/specs/`**: 仕様変更を伴うときは `tasks.md` のチェックボックスを更新し、要件にずれが出るなら `design.md` 更新をユーザーに確認
- **本ファイル (CLAUDE.md) の熟成**: タスク完了ごとに「CLAUDE.md / docs/ に追記すべき知見はあるか」をユーザーに確認する。本ファイル肥大化を検知したら積極的に `docs/` に分離 — トレーサビリティ (ポインタ・関連リンク) を必ず確保する
