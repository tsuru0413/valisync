# valisync-gui-mvp 画面レイアウト修正 — 要件メモ

> Kiro spec 生成用の要件整理。`.kiro/specs/<spec-name>/{requirements,design,tasks}.md` をこのメモを起点に生成する想定。

## 1. 背景
MVP（Phase 2）の機能実装において、`ChannelBrowserView` と `GraphAreaView` を共に `QDockWidget` として配置したが、メインウィンドウに `CentralWidget` が指定されていないため、Qtのレイアウトエンジンの制約によりドックを左右に並べることができないバグが発生した。
また、将来の Requirement 5（複数の Graph_Area をタブで切り替える機能）を見据えると、Graph_Area 自体をメインの作業領域（CentralWidget）として扱う設計が正当である。

## 2. 要件サマリー (確定済み項目の表)
| ID | 要件 | 内容 |
|---|---|---|
| R1 | 中央ウィジェット化 | `GraphAreaView` を `QDockWidget` ではなく `CentralWidget` として設定する。 |
| R2 | ドック初期配置 | `ChannelBrowserView` を初期状態で右側 (`RightDockWidgetArea`) に配置する。 |
| R3 | テスト整合性 | 既存のドックに関するテストを修正し、中央ウィジェットの配置を検証するテストを追加する。 |

## 3. 対象範囲 (In scope / Out of scope)
- **In scope**: `MainWindow` の初期化ロジックの変更、関連するユニットテストの修正。
- **Out scope**: `ChannelBrowserView` や `GraphAreaView` 内部のロジック変更、新機能（カーソル等）の追加。

## 4. 一次情報 (現状実装の場所、関連ファイル)
- 対象ソース: `src/valisync/gui/views/main_window.py`
- 対象テスト: `tests/gui/test_main_window.py`

## 5. アーキテクチャ (現状 → 移行後の図)
* 現状: `MainWindow` (CentralWidget: None) + Left Dock (`ChannelBrowser`) + Right Dock (`GraphArea`)
* 移行後: `MainWindow` (CentralWidget: `GraphAreaView`) + Right Dock (`ChannelBrowser`)

## 6. 採用しない選択肢と理由 (議論経過の記録)
- **案**: `setDockNestingEnabled(True)` を使用し、両方をDockのままにする。
- **理由**: Requirement 5 (Graph_Areaのタブ化) のアーキテクチャ要件と矛盾が生じるため不採用。Graph_Areaを主軸（Central）とする設計が妥当と判断した。
