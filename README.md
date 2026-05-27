# ValiSync

ADAS ソフトウェア開発向けの時系列信号データ統合・同期・解析デスクトップ GUI アプリケーション。CAN・XCP・Ethernet・CSV フォーマットの信号を統一時間軸上で可視化・分析する。

## Overview

このリポジトリは [kiro-claude-template](https://github.com/tsuru0413/kiro-claude-template) から生成されました。

**Kiro** (spec-driven 設計) と **Claude Code** (大規模実装) を併用する開発ワークフローを採用しています。

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
| `docs/dual-agent-workflow.md` | Kiro + Claude Code 併用開発ガイド |
| `docs/development.md` | 開発ワークフロー詳細 |
| `docs/policies.md` | プロジェクト方針 |
| `.kiro/steering/` | プロジェクトルール (Kiro 自動読込) |
| `.kiro/specs/` | 機能ごとの要件・設計・タスク |

## Development Workflow

1. **Kiro Spec** で要件 → 設計 → タスクを生成
2. **Claude Code** で tasks.md を番号順に消化
3. 品質ゲートを通してコミット
4. 知見を docs/ に蓄積

詳細は `docs/dual-agent-workflow.md` を参照。
