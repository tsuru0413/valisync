# Implementation Plan: valisync-core

## Overview

ValiSync Core のデータ処理ライブラリを実装する。MDF4（CAN/XCP/Ethernet 統合、asammdf 使用）および CSV の 2 フォーマットから信号データを読み込み、統一時間軸上で同期し、数式エンジン・補間・統計・ダウンサンプリング・Calcbar 演算を提供する。モジュール依存順（models → loaders → sync/formula/interpolation/statistics/downsampler → export → session）に従い段階的に実装する。

## Tasks

- [ ] 1. データモデル基盤の実装
  - [x] 1.1 Signal データモデルの実装
    - `src/valisync/core/models/signal.py` に Signal frozen dataclass を実装
    - `__post_init__` で不変条件検証（要素数一致、有限値、単調増加）
    - numpy 配列の `writeable = False` 設定
    - source_format, source_file メタデータフィールド
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 6.2, 6.3_
  - [x] 1.2 SignalGroup データモデルの実装
    - `src/valisync/core/models/signal_group.py` に SignalGroup frozen dataclass を実装
    - signals (tuple), source_path, source_format, loaded_at フィールド
    - _Requirements: 4.1, 4.2, 4.3_
  - [x] 1.3 FormatDefinition データモデルの実装
    - `src/valisync/core/models/format_def.py` に FormatDefinition frozen dataclass と Delimiter enum を実装
    - `__post_init__` でバリデーション（名前長、列範囲、重複チェック）
    - _Requirements: 3.2, 3.6_
  - [x] 1.4 LoadResult・Diagnostic データモデルの実装
    - `src/valisync/core/models/__init__.py` に LoadResult, Diagnostic frozen dataclass を実装
    - 全モデルの re-export を設定
    - _Requirements: 1.4, 1.6, 2.5, 2.6_

- [ ] 2. ローダー基盤と MDF4 ローダーの実装
  - [x] 2.1 SignalLoader Protocol の定義
    - `src/valisync/core/loaders/base.py` に SignalLoader Protocol を定義
    - `load()` と `supports()` メソッドのインターフェース
    - _Requirements: 1.1, 2.1_
  - [x] 2.2 Mdf4Loader の実装
    - `src/valisync/core/loaders/mdf4_loader.py` に Mdf4Loader クラスを実装
    - asammdf を使用して全チャンネルグループを一括解析
    - チャンネルグループメタデータからプロトコル種別（CAN/XCP/Ethernet）を判定
    - 同名信号の出現順インデックス付与
    - エラーハンドリング（不正フォーマット、ファイル不存在、空データ）
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 6.1_
  - [x] 2.3 CsvLoader の実装
    - `src/valisync/core/loaders/csv_loader.py` に CsvLoader クラスを実装
    - FormatDefinition に基づくパース処理
    - ヘッダー有無による信号名決定
    - エラーハンドリング（フォーマット不一致、非数値データ、空データ）
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 6.1_
  - [x] 2.4 FormatDefinitionManager の実装
    - `src/valisync/core/loaders/format_def_manager.py` に FormatDefinitionManager クラスを実装
    - JSON ファイルへの保存・読み込み・削除（data/ ディレクトリ）
    - 名前重複チェック
    - _Requirements: 3.1, 3.3, 3.4, 3.5, 3.7_

- [x] 3. チェックポイント — データモデルとローダー
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. 時刻同期モジュールの実装
  - [x] 4.1 TimeSynchronizer の実装
    - `src/valisync/core/sync/__init__.py` と `src/valisync/core/sync/synchronizer.py` を作成
    - `apply_offset()`: ファイル単位 + 信号単位オフセットの合算適用
    - NaN/Inf オフセットのバリデーション
    - 負のタイムスタンプの許容
    - Unified_Timeline はオフセット加算で創発する性質であり、専用 `synchronize()` メソッドは設けない。8.2（1 ULP 以内の変換）・8.4（サンプル数不変）・8.6（単調性保存）は `apply_offset()` と Signal 不変条件が保証する。コレクションレベルの 8.1・8.3 は Session（Task 8.2）が担う
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 8.2, 8.4, 8.6_
  - [x] 4.2 Signal_Group 管理ロジックの実装
    - `src/valisync/core/loaders/signal_group_manager.py` に SignalGroupManager を実装し `__init__.py` から re-export
    - ファイル単位キー（mf4_<n> / csv_<n>、フォーマット別連番、削除後も再利用しない）の割り当てによる add/remove
    - 全 Signal 名を `{key}::{原信号名}` に名前空間化（複数ファイル間の同名信号を一意化、Req 4.6）
    - 同一パスの重複読み込みを許可（各読み込みに一意キー、Req 4.7）。削除は key 指定
    - 依存チェック（Req 4.5）・一括読み込みの部分失敗処理（Req 5.4）は Session（Task 8.2）の責務。Req 5.1/5.3 はデータモデルで充足済み
    - _Requirements: 4.4, 4.6, 4.7, 5.2_

- [ ] 5. Formula エンジンの実装
  - [x] 5.1 Formula パーサーの実装
    - `src/valisync/core/formula/__init__.py` と `src/valisync/core/formula/engine.py` を作成
    - 再帰下降パーサー（四則演算、三角関数、対数、abs、sqrt、pow）
    - 構文検証（validate メソッド）
    - _Requirements: 10.1, 10.2, 10.9_
  - [x] 5.2 Formula 評価エンジンの実装
    - 複数 Signal 入力の共通区間計算（全参照信号のタイムスタンプを共通時間範囲内で union し result_ts を構成、他信号は np.interp で補間）
    - Derived_Signal 入れ子処理（max_depth ≤ 0 で ValueError、Session が階層ごとにデクリメント）
    - 演算エラー処理（ゼロ除算、定義域外 → NaN + Signal.metadata["formula_warnings"]）
    - _Requirements: 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.10_

- [x] 6. 補間・統計・ダウンサンプラーの実装
  - [x] 6.1 Interpolator の実装
    - `src/valisync/core/interpolation/__init__.py` と `src/valisync/core/interpolation/interpolator.py` を作成
    - InterpolationMethod enum（LINEAR, ZERO_ORDER_HOLD, NEAREST）
    - 3 方式の補間計算ロジック
    - 範囲外 → None、サンプル数不足 → None、NaN 隣接 → NaN
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10, 12.11_
  - [x] 6.2 RangeStatistics の実装
    - `src/valisync/core/statistics/__init__.py` と `src/valisync/core/statistics/range_stats.py` を作成
    - StatisticsResult frozen dataclass
    - numpy を使用した統計計算（mean, max, min, std ddof=0, count）
    - バリデーション（t_start > t_end、NaN/Inf）
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8_
  - [x] 6.3 Downsampler の実装
    - `src/valisync/core/downsampler/__init__.py` と `src/valisync/core/downsampler/downsampler.py` を作成
    - min-max ダウンサンプリングアルゴリズム
    - パススルー条件（サンプル数 ≤ n）
    - バリデーション（n < 2、非整数、NaN/Inf）
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7_

- [x] 7. チェックポイント — 純粋計算モジュール
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. エクスポートと Session の実装
  - [x] 8.1 CsvExporter の実装
    - `src/valisync/core/export/__init__.py` と `src/valisync/core/export/csv_exporter.py` を作成
    - タイムスタンプ第1列、信号値後続列のフォーマット
    - Unified_Timeline モード（欠損セルは空文字）
    - 原子性保証（一時ファイル → rename）
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_
  - [x] 8.2 Session クラスの実装
    - `src/valisync/core/session.py` に Session クラスを実装
    - ローダー・同期・Formula・補間・統計・ダウンサンプラー・エクスポートの統合
    - 各 Signal に `apply_offset()` を適用して全 Signal を Unified_Timeline 上に配置（8.1）。並べ替え・リサンプリングを行わないことで Signal 間の相対順序を保存（8.3）
    - SignalGroupManager を介した Signal_Group の追加・削除
    - 削除時の Derived_Signal 依存チェックと確認要求（4.5）
    - 複数ファイル一括読み込みの部分失敗処理（成功分を利用可能とし失敗をファイル単位で報告、5.4）
    - _Requirements: 8.1, 8.3, 4.4, 4.5, 5.4_
  - [x] 8.3 Calcbar 演算の実装
    - Session クラスに moving_average, linear_regression, differentiate, integrate メソッドを追加
    - 移動平均: 縮小ウィンドウ方式 SMA
    - 線形回帰: 最小二乗法（numpy.polyfit 相当）
    - 数値微分: 中心差分（端点は前方/後方差分）
    - 累積積分: 台形則（先頭 0.0）
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8_

- [x] 9. チェックポイント — 全モジュール統合
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. ユニットテスト
  - [x] 10.1 ローダーのユニットテスト
    - `tests/test_loaders.py` に MDF4/CSV ローダーの正常系・異常系テストを実装
    - エラーケース: 不正フォーマット、ファイル不存在、非数値データ、空ファイル
    - _Requirements: 1.4, 1.6, 1.7, 1.8, 2.5, 2.6, 2.8_
  - [x] 10.2 エクスポートのユニットテスト
    - `tests/test_export.py` に CSV エクスポートのフォーマット・エラー処理テストを実装
    - Unified_Timeline モード、書き込み失敗時の原子性
    - _Requirements: 7.2, 7.3, 7.4, 7.7_
  - [x] 10.3 Session・FormatDef のユニットテスト
    - `tests/test_session.py` に Signal_Group 操作・依存関係テストを実装
    - `tests/test_format_def.py` に FormatDefinition CRUD テストを実装
    - _Requirements: 3.1, 3.4, 3.7, 4.4, 4.5, 4.7_
  - [x] 10.4 補間・統計・ダウンサンプラー・Calcbar のユニットテスト
    - `tests/test_interpolation.py` に NaN 伝播、サンプル数不足、エッジケーステストを実装
    - `tests/test_statistics.py` に空範囲、バリデーションエラーテストを実装
    - `tests/test_downsampler.py` にバリデーション、境界値テストを実装
    - `tests/test_calcbar.py` に最小サンプル数、ウィンドウサイズ検証テストを実装
    - _Requirements: 12.7, 12.10, 12.11, 13.4, 13.5, 13.6, 14.4, 14.7, 15.7, 15.8_

- [x] 11. プロパティベーステスト（データモデル・ローダー）
  - [x]* 11.1 Signal データモデル不変条件のプロパティテスト
    - `tests/test_pbt_signal.py` を作成
    - **Property 1: Signal データモデル不変条件**
    - **Property 2: Signal の不変性（Immutability）**
    - **Validates: Requirements 11.1, 11.2, 11.4, 11.5, 11.6, 6.2, 6.3**
  - [x]* 11.2 変換処理の入力不変性プロパティテスト
    - `tests/test_pbt_signal.py` に追加
    - **Property 3: 変換処理の入力不変性**
    - **Validates: Requirements 6.4, 10.8, 12.9, 13.7, 14.5, 15.6**
  - [x]* 11.3 FormatDefinition バリデーション・ラウンドトリップのプロパティテスト
    - `tests/test_pbt_csv.py` を作成
    - **Property 4: FormatDefinition バリデーション**
    - **Property 5: FormatDefinition JSON ラウンドトリップ**
    - **Validates: Requirements 3.2, 3.3, 3.5, 3.6**
  - [x]* 11.4 MDF4 Signal ラウンドトリップのプロパティテスト
    - `tests/test_pbt_mdf4.py` を作成
    - **Property 6: MDF4 Signal ラウンドトリップ**
    - **Validates: Requirements 1.5**
  - [x]* 11.5 CSV ラウンドトリップのプロパティテスト
    - `tests/test_pbt_csv.py` に追加
    - **Property 7: CSV 読み込みラウンドトリップ**
    - **Property 8: CSV エクスポートラウンドトリップ**
    - **Validates: Requirements 2.7, 7.6**

- [x] 12. プロパティベーステスト（同期・Formula）
  - [x]* 12.1 同名信号一意性のプロパティテスト
    - `tests/test_pbt_sync.py` を作成
    - **Property 9: 同名信号の一意性保証**
    - **Validates: Requirements 4.6**
  - [x]* 12.2 オフセット加算・間隔保存のプロパティテスト
    - `tests/test_pbt_sync.py` に追加
    - **Property 10: オフセット加算の正確性**
    - **Property 11: オフセット適用後の間隔保存**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
  - [x]* 12.3 同期処理のプロパティテスト
    - `tests/test_pbt_sync.py` に追加
    - **Property 12: 同期後のサンプル数不変**
    - **Property 13: 同期後の単調性保存**
    - **Property 14: 同期の相対順序保存**
    - **Validates: Requirements 8.3, 8.4, 8.6**
  - [x]* 12.4 Formula エンジンのプロパティテスト
    - `tests/test_pbt_formula.py` を作成
    - **Property 15: 共通区間演算の正確性**
    - **Property 16: Derived_Signal のデータモデル準拠**
    - **Validates: Requirements 10.3, 10.5, 10.6, 15.5**

- [x] 13. プロパティベーステスト（補間・統計・ダウンサンプラー・Calcbar）
  - [x]* 13.1 補間計算のプロパティテスト
    - `tests/test_pbt_interpolation.py` を作成
    - **Property 17: 補間計算の正確性**
    - **Property 18: 補間の完全一致タイムスタンプ**
    - **Property 19: 補間の範囲外拒否**
    - **Validates: Requirements 12.1, 12.3, 12.4, 12.5, 12.7, 12.8**
  - [x]* 13.2 範囲統計のプロパティテスト
    - `tests/test_pbt_statistics.py` を作成
    - **Property 20: 範囲統計の正確性**
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.8**
  - [x]* 13.3 ダウンサンプリングのプロパティテスト
    - `tests/test_pbt_downsampler.py` を作成
    - **Property 21: ダウンサンプリング出力の不変条件**
    - **Property 22: ダウンサンプリングのパススルー**
    - **Validates: Requirements 14.1, 14.3, 14.4, 14.6**
  - [x]* 13.4 Calcbar 演算のプロパティテスト
    - `tests/test_pbt_calcbar.py` を作成
    - **Property 23: 移動平均の正確性**
    - **Property 24: 線形回帰の最小二乗特性**
    - **Property 25: 数値微分の正確性**
    - **Property 26: 数値積分の正確性**
    - **Validates: Requirements 15.1, 15.2, 15.3, 15.4**

- [x] 14. 最終チェックポイント
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- タスク 2.2 (Mdf4Loader) は `asammdf` ライブラリに依存する（`pyproject.toml` 追加済み）
- タスク 4.2 (Signal_Group 管理) は `core/loaders/` と `core/session.py` の両方に関わるが、コアロジックは `core/loaders/` に配置し `core/session.py` から呼び出す構造とする
- Wave 5 内の実装順: 5.1 (パーサー) → 5.2 (評価エンジン)。パーサーが先に必要
- Wave 8 内の実装順: 8.1 (エクスポート) → 8.2 (Session) → 8.3 (Calcbar)。Session が全モジュールを統合するため最後
- `core/formula/library.py` (FormulaLibraryManager) は Phase 3 (valisync-persistence spec) で実装する。Phase 1 ではスタブ不要
- Wave 11〜13 のプロパティテストは optional (`*` マーク)。MVP では省略可能だが、CI での品質保証に推奨
- `tests/conftest.py` に Hypothesis strategies（monotonic_timestamps, valid_signals 等）を定義し、全 PBT ファイルで共有する
- **テスト実装状況（A案: 計算モジュール先行）**: 実装済みモジュールに対し Unit + PBT を先行実装（完了: 10.1 / 11.1,11.3,11.4 / 12.1,12.2 / 13.1,13.2,13.3、計 103 テスト green）。Task 8 依存で**保留**: 10.2（export）, 13.4 + 10.4 Calcbar 部分, Property 8（CSV export 往復）, Property 14（Session 相対順序）。**部分完了**（実装済み範囲のみ検証、未チェックのまま）: 10.3（FormatDef 済 / Session 待ち）, 10.4（補間・統計・DS 済 / Calcbar 待ち）, 11.2（Property 3 を 5 変換でカバー / Calcbar 待ち）, 11.5（Property 7 済 / 8 待ち）, 12.3（Property 12,13 済 / 14 待ち）, 12.4（Property 15 済 / 16 の Calcbar 部分待ち）
- MDF4 テストは静的 fixture を持たず `tests/mdf4_helpers.py` で asammdf 書き込み API により動的生成する（CAN/XCP/Ethernet を Source で合成）
- **Wave 8 完了（2026-05-27）**: 8.1/8.2/8.3 実装、10.2/10.3/10.4/Property 8 完了。Session は load/load_many（部分失敗 5.4）・remove_group（Derived 依存チェック 4.5）・unified_timeline_signals（8.1/8.3）・純計算 pass-through・Calcbar を提供。
- **optional PBT 追加（2026-05-27）**: Property 14（Session 相対順序, test_pbt_sync.py）, Property 16 Calcbar 半 + 13.4 Property 23-26（test_pbt_calcbar.py 新規）, 11.2 Property 3 Calcbar 入力不変性（test_pbt_signal.py）を実装。**Phase 1 全タスク完了**（1〜14 すべて `[x]`）。quality gate: pytest/ruff/mypy 全通過
- **Downsampler O(N) 最適化（2026-05-27）**: GUI MVP の動的 LOD が 16ms 予算を満たすため、`downsampler.py` を per-bucket 全走査（O(n_buckets×N)）から、timestamp 単調性を利用した連続セグメント slice（O(N)）へ最適化。出力契約（min-max・厳密単調・不変条件）は不変、既存 PBT で再検証。性能ガードテスト（100万点 < 1s）を追加

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4"] },
    { "id": 2, "tasks": ["4.1", "4.2"] },
    { "id": 3, "tasks": ["5.1", "5.2"] },
    { "id": 4, "tasks": ["6.1", "6.2", "6.3"] },
    { "id": 5, "tasks": ["8.1", "8.2", "8.3"] },
    { "id": 6, "tasks": ["10.1", "10.2", "10.3", "10.4"] },
    { "id": 7, "tasks": ["11.1", "11.2", "11.3", "11.4", "11.5"] },
    { "id": 8, "tasks": ["12.1", "12.2", "12.3", "12.4"] },
    { "id": 9, "tasks": ["13.1", "13.2", "13.3", "13.4"] }
  ]
}
```
