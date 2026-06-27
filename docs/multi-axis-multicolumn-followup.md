# valisync-gui-axes R1（複数列 Y軸グリッド）未実装 follow-up

> 関連 spec: `valisync-gui-axes`（「完了」扱い・tasks 全 `[x]`・PR #4 merged）。
> 発見の経緯: 「multi-axis の要件に Y軸の複数列表示はあるか」という確認から、**R1（Multi-Column Y-Axis Grid）が spec/tasks 上は完了扱いだが、実コードのレンダリングでは未実装**であることが判明した。

## 課題（spec と実装の乖離）

`valisync-gui-axes` の **R1: Multi-Column Y-Axis Grid** は次を要求する:
- R1.1: プロット領域の左に **最低2列**の Y軸縦列を持つ。
- R1.2: 各列は独立した Y軸行数を持つ。

`design.md`（L52–53）も「Root Layout = 1行×**複数列**グリッド（最終列はプロット予約）」「各軸列は独立行高を持つ `GraphicsLayout`（Column Layouts）」と**複数列を前提**に設計している。しかし実装は **単一列の縦積み**にとどまり、複数列は描画されない。

## 根拠（コード実測）

- `src/valisync/gui/views/graph_panel_view.py`（レイアウト構築, 〜L388）:
  - root レイアウトは **col 0 = Y軸群 / col 1 = プロット領域**に固定（`setColumnFixedWidth(0, …)` / `setColumnStretchFactor(1, 1)`）。
  - 全 Y軸を単一サブレイアウト `_axis_layout`（`row=0, col=0`）へ `row = i*2, col=0` で**行方向のみ**に積む。列インデックスによる振り分けは無い。
- `src/valisync/gui/viewmodels/y_axis_vm.py:26`: `YAxisVM.column` フィールドは存在するが常に既定 `0`。
- `src/valisync/gui/viewmodels/graph_panel_vm.py:449`: `inspect()` に `"column": ax.column` を投影するが、**view は `column` を一切参照しない**（`grep` で確認）。
- `design.md` / `tasks.md` Task 1.2 の `AxisColumnLayout` クラスは実体として存在せず、単一 `_axis_layout` に置き換わっている。

## 実装済みの範囲（参考）

R2〜R6 は実装・テスト済み: 縦リージョン＋ドラッグ仕切り（R2）、Auto-Fit 縮尺（R3）、クリップなしオーバーレイ（R4）、文脈依存 D&D（R5）、削除時レイアウト安定（R6）。**未実装は R1（複数列）のみ。**

## 影響

- spec ステータス（「完了」）と tasks（全 `[x]`）が **R1 について過大**（実態は単一列）。
- `YAxisVM.column` はデータ側スキャフォールドのみで、UX（列の作成・割当）も未定義。

## 次アクション

1. R1 実装の**設計をブレインストーミング**（列作成・割当の UX、列数の上限、既存リージョン/Auto-Fit 系との関係、左配置レイアウトの描画方式）。
2. 設計確定後、`design.md` / `tasks.md` / Phase 表ステータスを実態に合わせて訂正し、実装する。

## 関連
- spec: `.kiro/specs/valisync-gui-axes/{requirements,design,tasks}.md`（R1 / Root Grid Layout / Task 0.1・1.2）
- 既存 follow-up: `docs/multi-axis-empty-region-followup.md`
- 実装: `src/valisync/gui/views/graph_panel_view.py`, `src/valisync/gui/viewmodels/{y_axis_vm,graph_panel_vm}.py`
