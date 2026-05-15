# Product

<!-- TODO: プロジェクト固有の内容に書き換える -->

## 概要

<!-- プロダクトの1-2行説明 -->

## Target Users

<!-- 対象ユーザーの説明 -->

## Architecture Principles

<!-- 設計原則を列挙 -->
<!-- 例:
- Strategy パターンで計算アルゴリズムを差し替え可能
- 純粋関数で計算ロジックを実装 (副作用なし)
- Open/Closed Principle: 新規追加時に既存コードを変更しない
-->

## Key Capabilities

<!-- 主要機能を箇条書き -->

## Implementation Phases

<!-- Phase 分割がある場合 -->
<!-- 例:
1. Phase 1 — コアロジック
2. Phase 2 — Web フロントエンド
-->

## Language Note

<!-- UI言語・コード言語・ドキュメント言語の方針 -->
- コード識別子（変数名・関数名・クラス名）は英語
- ドキュメント: <!-- 日本語 / 英語 / バイリンガル -->

## Coding Standards

<!-- 言語固有のコーディング規約 -->
- Python 3.12+
- 型ヒント（type hints）を全関数に付与
- dataclass でデータモデルを定義
- Protocol（typing.Protocol）でインターフェースを定義
- テストは pytest + Hypothesis（プロパティベーステスト）
- 依存管理は uv（pyproject.toml + uv.lock）
