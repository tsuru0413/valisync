# Product

## 概要

ValiSync — ADAS ソフトウェア開発向けの時系列信号データ統合・同期・解析デスクトップ GUI アプリケーション。CAN・XCP・Ethernet・CSV フォーマットの信号を統一時間軸上で可視化・分析する。

## Target Users

- テストエンジニア: 信号データの読み込み・同期・波形分析を行う
- テスト設計者: フォーマット定義の管理、Formula の設定、時間オフセットの調整を行う
- 制御エンジニア: ECU 内部変数（XCP）の時系列データを解析する

## Architecture Principles

- Signal データは immutable（読み込み後の変更禁止）
- 入力ファイルへの書き込みは厳禁（データ改ざん防止）
- Protocol（typing.Protocol）でモジュール間インターフェースを定義し疎結合を維持
- 同期・Formula 等の変換処理は元データを変更せず新しいオブジェクトを生成する
- Strategy パターンでフォーマット別パーサーを差し替え可能にする
- コアロジック（データ処理）と GUI 層を分離し、コアは GUI に依存しない
- 将来の AD（完全自動運転）スコープ拡張を見据えた拡張性

## Key Capabilities

- マルチフォーマット信号読み込み（CAN, XCP, Ethernet, CSV）
- ユーザー定義可能な CSV フォーマット設定
- ファイル単位の Signal 管理（Signal_Group）
- マルチフォーマット時刻同期（Unified_Timeline）
- ファイル単位・信号単位の時間オフセット設定
- Formula による派生信号生成（入れ子対応）
- CSV エクスポート
- 高速波形可視化（別 spec: valisync-gui で定義）

## Implementation Phases

1. Phase 1 — valisync-core: データモデル、Signal_Loader、Time_Synchronizer、Formula エンジン
2. Phase 2 — valisync-gui: PySide6 + PyQtGraph による GUI 実装

## Language Note

- コード識別子（変数名・関数名・クラス名）は英語
- ドキュメント: 日本語（コード内コメントは英語可）
- Spec ドキュメント: 日本語

## Coding Standards

- Python 3.12+
- 型ヒント（type hints）を全関数に付与
- dataclass（frozen=True）で immutable データモデルを定義
- Protocol（typing.Protocol）でインターフェースを定義
- テストは pytest + Hypothesis（プロパティベーステスト）
- 依存管理は uv（pyproject.toml + uv.lock）
