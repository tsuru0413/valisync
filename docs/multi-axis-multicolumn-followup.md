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

## ブレインストーミング結果（確定設計 — 2026-06-27）

複数列 Y軸の対話設計（visual companion 使用）で以下を確定:

1. **レイアウト**: 固定 N 列（既定 2・設定で可変）をプロット左に配置。軸はプロット側の列から埋め、軸が無い列／空きスペース＝「余白」。
2. **列内の高さ**: 各軸の上端・下端のリサイズハンドルでユーザーが任意に高さ調整（「行」概念は持たない）。
3. **信号ドロップ**: 既存軸の上＝**上書き**、**Ctrl+ドロップ＝追加**、軸以外＝新規軸（R5 を改訂）。
4. **新規軸の配置（案A）**: 内側列（プロット側）の末尾に追加・高さ均等割り。落とす位置は不問。後でハンドル／移動で調整。
5. **軸移動**: 軸自体を D&D で余白（空き列）や他列へ移動。元位置は余白化（R6 と整合）。
6. **軸移動のドロップ・フィードバック（案1 確定）**: ドラッグ中、ドロップ先を**挿入線**で提示する。
   - **挿入線**は対象列の境界候補（**軸数 + 1** = 先頭軸の上端〜末尾軸の下端）のうち、カーソル y に最も近いものへスナップ。**上端・間・下端**を同一語彙でカバー。
   - **空き列（余白）**は境界が無いので、線ではなく**列全体をハイライト**。
   - **軸の上に重ねた場合**は、その軸の最寄り上端/下端境界に挿入（**swap はしない** — ②）。
   - **移動元**はドラッグ中**淡色プレースホルダ**表示（③）、ドロップで余白化（R6 整合）。
   - **高さ**はドロップ先の列を**均等再分割**（① — `_normalize_axes`）。位置は `move_axis_to_column(axis_index, column, position)` の `position` が保持。

→ 実装計画: `docs/superpowers/plans/2026-06-27-multi-column-y-axis.md`（Task 0.5 / 1.4 に反映済み）

## 保留（follow-up — 本実装スコープ外）

- 軸の**左右（幅）方向ハンドル**の要否。
- **列数設定 UI** の置き場所（設定ダイアログ等）。

> 軸移動・並べ替え時の**ドロップ・フィードバック**（挿入線／ハイライト）は **2026-06-27 に確定**（上記「ブレインストーミング結果」6）— 保留から解除。

## 関連
- spec: `.kiro/specs/valisync-gui-axes/{requirements,design,tasks}.md`（R1 / R5 改訂 / Root Grid Layout）
- 実装計画: `docs/superpowers/plans/2026-06-27-multi-column-y-axis.md`
- 既存 follow-up: `docs/multi-axis-empty-region-followup.md`
- 実装: `src/valisync/gui/views/graph_panel_view.py`, `src/valisync/gui/viewmodels/{y_axis_vm,graph_panel_vm}.py`
