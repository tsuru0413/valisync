# Product — ValiSync

## 概要

ADAS ソフトウェア開発向けの時系列信号データ統合・同期・解析デスクトップ GUI アプリケーション。CAN・XCP・Ethernet・CSV フォーマットの信号を統一時間軸上で可視化・分析する。

## 対象ユーザー

- テストエンジニア: 信号データの読み込み・同期・波形分析
- テスト設計者: フォーマット定義の管理、Formula の設定、時間オフセットの調整
- 制御エンジニア: ECU 内部変数（XCP）の時系列データ解析

## 主要機能

- マルチフォーマット信号読み込み（CAN / XCP / Ethernet / CSV）
- ユーザー定義可能な CSV フォーマット設定
- ファイル単位の Signal 管理（Signal_Group）
- マルチフォーマット時刻同期（Unified_Timeline）
- ファイル単位・信号単位の時間オフセット設定
- Formula による派生信号生成（入れ子対応）
- CSV エクスポート
- 高速波形可視化（GUI）

> Architecture 原則・Coding Standards は `policies.md` / `development.md`、Phase 進捗は `CLAUDE.md` / `roadmap.md` 参照。
