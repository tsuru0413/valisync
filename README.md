# ValiSync

ADAS ソフトウェア開発向けの時系列信号データ統合・同期・解析デスクトップ GUI アプリケーション。CAN・XCP・Ethernet・CSV フォーマットの信号を統一時間軸上で可視化・分析する。

## Overview

このリポジトリは [kiro-claude-template](https://github.com/tsuru0413/kiro-claude-template) から生成されました。

開発ワークフローは **Claude Code superpowers**（brainstorming → writing-plans → executing-plans）駆動です（旧 Kiro 併用フローから移行済み）。

## Quick Start

```bash
# 依存インストール
uv sync --extra dev

# テスト実行
uv run pytest

# 品質ゲート (コミット前に全て通す)
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

## Documentation

| ドキュメント | 内容 |
|---|---|
| `CLAUDE.md` | AI エージェント向けエントリポイント |
| `docs/workflow.md` | 開発ワークフロー（superpowers 計画・branch/PR） |
| `docs/development.md` | 開発コマンド・品質ゲート・技術スタック |
| `docs/policies.md` | プロジェクト方針・Architecture 原則 |
| `docs/superpowers/{specs,plans}/` | 設計 spec・実装プラン（新規の一次情報源） |
| `.kiro/specs/` | 完了済み Phase 1/2 spec のアーカイブ |

## Development Workflow

1. **brainstorming** で要件 → 設計を詰め、設計 spec を `docs/superpowers/specs/` に記録
2. **writing-plans** で実装プランを `docs/superpowers/plans/` に落とす
3. **executing-plans / subagent-driven-development** でタスク順に消化（各タスクで品質ゲート → commit）
4. **finishing-a-development-branch** で merge / PR

詳細は `docs/workflow.md` を参照。
