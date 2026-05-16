# CLAUDE.md

このファイルは **エントリポイント** — 詳細情報は別ファイルに分散し、ここではポインタと最小限の不変情報のみ保持する。本ファイルが肥大化してきたら積極的に `docs/` に分離する。

## 情報の探し方 (優先順位)

| 順位 | 場所 | 内容 |
|---|---|---|
| 1 | `.kiro/specs/<spec>/{requirements,design,tasks}.md` | 要件・設計・実装計画 (**一次情報源**) |
| 2 | `.kiro/steering/{product,tech,structure,spec-authoring}.md` | プロダクト原則・技術選定・ディレクトリ構造・spec 生成ルール |
| 3 | `docs/<topic>.md` | spec 化されていない実装ノート・運用メモ |
| 4 | このファイル | 上記で発見できないハマりどころと方針概要 |

**ルール**: `.kiro/` または `docs/` で確認可能な情報は本ファイルに重複させず、ポインタで繋ぐ。コードを読めば自明な事実 (ファイル名・関数シグネチャ等) も本ファイルには書かない。

## プロジェクト概要

<!-- TODO: 1-2行でプロジェクトの概要を記述 -->

詳細: `.kiro/steering/product.md`

## リポジトリ

- **Remote**: <!-- TODO: git remote URL -->
- **CI**: GitHub Actions (push to main / 全 PR で品質ゲート自動実行)

## 開発ワークフロー (Kiro + Claude Code 併用)

詳細: `docs/dual-agent-workflow.md`

- **Kiro Spec** で要件→設計→タスクを生成し、**Claude Code** で tasks.md を消化する
- CLAUDE.md はエントリポイント (薄く保つ)。詳細は `.kiro/` と `docs/` に分散
- steering/ は常時適用ルール、specs/ は機能単位の一次情報源、docs/ は横断的運用知識

## Phase 状況

| Phase | スコープ | 状況 | 一次情報源 |
|---|---|---|---|
| <!-- Phase名 --> | <!-- スコープ --> | <!-- 状況 --> | <!-- spec パス --> |

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

## 開発環境の落とし穴

<!-- TODO: 環境固有のハマりどころを記述 (例: Windows の python スタブ問題等) -->

詳細: `docs/development.md` 末尾参照。

## ファイル更新ルール

- **コメント**: 何 (WHAT) ではなく なぜ (WHY) を書く。自明なコードに説明を付けない
- **`.kiro/specs/`**: 仕様変更を伴うときは `tasks.md` のチェックボックスを更新し、要件にずれが出るなら `design.md` 更新をユーザーに確認
- **本ファイル (CLAUDE.md) の熟成**: タスク完了ごとに「CLAUDE.md / docs/ に追記すべき知見はあるか」をユーザーに確認する。本ファイル肥大化を検知したら積極的に `docs/` に分離 — トレーサビリティ (ポインタ・関連リンク) を必ず確保する
