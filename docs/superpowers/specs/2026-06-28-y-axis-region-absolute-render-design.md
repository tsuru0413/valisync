# Y軸リージョンの絶対レイアウト描画（空白ギャップ忠実描画）設計

> 関連 spec: `.kiro/specs/valisync-gui-axes/`（リージョンベース複数Y軸レイアウト）。
> 前段: 削除の高さ保持（PR #14）／移動・並べ替えの高さ保持（PR #16）— いずれも **VM 側**で絶対比率＋空白を計算する実装。
> 日付: 2026-06-28 / ブランチ: `worktree-axes-blank-gap-render`

## 背景

削除（PR #14・案B）と移動・並べ替え（PR #16）で「生存リージョンは絶対比率を保持し、抜けた帯は空白」を実装したが、**実アプリでは空白が描画されない**（リージョンが詰まって表示される）ことが判明した。

原因調査の結果、これらの機能は **`GraphPanelVM` の数値（`top_ratio`/`height_ratio`、合計<1.0 のギャップ）としては正しく計算されている**が、**View がそれを忠実に描画していない**ことが分かった。テスト（Layer A／および realgui）は **VM の値**を assert していたため、描画されていない不具合を検知できず false-green になっていた（教訓: 描画系は VM 値ではなく**実際の描画ジオメトリ**を検証する。`docs/gui-testing-layers.md` / メモ `feedback_gui_verify_real_input` の趣旨）。

## ゴール（確定）

View が **VM の絶対リージョンレイアウトを忠実に描画する**。各リージョンを絶対 `top_ratio`/`height_ratio` に配置し、削除/移動で抜けた帯は**本当の空白**（どの描画要素も置かれない）として表示する。そのために **Y軸スパイン・波形・ディバイダを同一の絶対配置に統一**する。

## 根本原因

`GraphPanelView` の列内レイアウトが **2つの異なる機構**に分裂している：

1. **波形 ViewBox**: 全面オーバーレイ（`_sync_overlay_geometry` がマスター rect に同期）＋ `YAxisVM.calculate_virtual_range()` による **絶対ストリップ配置**。→ ギャップを表現できる。
2. **Y軸スパイン（AxisItem）／ディバイダ**: 列ごとの `QGraphicsGridLayout` サブレイアウトに **行ストレッチ ∝ `height_ratio`** で積む（`graph_panel_view.py:392-393, 484`）。グリッドのストレッチは**必ず正規化して列を埋める**ため、合計<1.0（空白）でも詰めて描画する（例 0.5/0.2 → 0.714/0.286）。→ **空白を構造的に表現できない**。

結果、波形は絶対配置・軸は正規化配置で食い違い、「空白保持」は VM の数値内にしか存在しない。フラグ追加では直らない（機構そのものの不整合）。

## 設計（案B：絶対ジオメトリへ統一）

`top_ratio`/`height_ratio` を解釈する場所を**1つ（絶対同期）に統一**し、列内縦スタックのグリッド行ストレッチを**廃止**する。

### 1. ルートグリッドは「粗い構造」のみ担当（現状維持）
`plot_widget.ci.layout`：ガター列 0..N-1（各固定幅 `_Y_AXIS_FIXED_WIDTH`）＋プロット列 N（伸縮）＋ row 0（リージョン領域）/ row 1（固定 X軸）。**列内の縦スタックにはグリッドを使わない。**

### 2. 列コンテナで幅確保＋バンド基準
占有ガター列ごとに**軽量コンテナ**（空の `QGraphicsWidget`）を root grid のそのセル（row 0, col c）に1つ置く。役割：
- ガター列の固定幅 W を確保（軸アイテムをグリッドから外すと列が潰れてプロットが左に伸びるのを防ぐ）。
- その列の **X バンドと Y 基準**（`sceneBoundingRect()`）を提供。row 0 にあるためプロット領域と同じ Y ベースライン・高さ H を持つ。

### 3. 列内要素は絶対ストリップへ配置（`_sync_overlay_geometry` 拡張）
現在マスター rect へ波形 ViewBox を同期しているメソッドを拡張し（実質 `_sync_region_geometry`）、**AxisItem とディバイダも絶対ストリップへ `setGeometry`** する。各リージョン i（列 c, `top_ratio` t, `height_ratio` h）について：
```
band   = column_container[c].sceneBoundingRect()   # X バンド & Y 基準 (== row0 の高さ H)
strip  = QRectF(band.x(), band.y() + t*band.height(), band.width(), h*band.height())
_y_axes[i].setGeometry(strip)                       # 軸スパイン
# 波形 ViewBox は従来どおりマスター rect 全面 + virtual-range（絶対）。変更不要。
```
波形側の Y は既に `calculate_virtual_range()`（絶対）なので**計算式は不変**。軸スパインを同じ絶対ストリップに合わせることで両者が一致する。

### 4. `_reconcile_axes`（build 経路）の変更
- 列ごとの grid サブレイアウト行ストレッチ（`setRowStretchFactor(height_ratio*1000)`）を**廃止**。占有列の grid サブレイアウト（現 `_axis_layouts[col]`）は**列コンテナ（`_column_containers[col]`：幅確保のみの空 `QGraphicsWidget`）に置換**。
- AxisItem を grid に積む代わりに**シーンアイテム**として用意し（`_y_axes[i]`）、配置は `_sync_region_geometry` が列コンテナ rect を基準に委ねる。
- `_view_boxes[i]`/`_y_axes[i]` と `vm.axes[i]` のペアリングは維持（`refresh()` の index マッピングを保つ）。

### 5. ディバイダ（区切り線）
- **隣接する（境界を共有する）連続リージョン間にのみ**配置（絶対ストリップで上リージョンの下端 == 下リージョンの上端のとき）。
- **ギャップを跨ぐ位置にはディバイダを置かない**（空白を挟んだリージョン間は resize 対象でない）。削除で中央が抜けた A(0,0.5)/C(0.8,0.2) の間（0.5-0.8 空白）にはディバイダ無し。
- ヒットテスト/ドラッグ境界は既に `top_ratio` 基準（`graph_panel_view.py:638-643, 711`）なので絶対モデルと整合。`resize_axis`（VM）は不変。

### 6. リサイズ対応（既存配線で自動）
`_sync_*_geometry` は **refresh 時（`:322`）＋マスター ViewBox の `sigResized`（`:514`）** で発火する。拡張後はこの2経路で AxisItem/ディバイダも再配置されるため、**ウィンドウリサイズ時も絶対ストリップが追従**する（追加の resize ハンドラ不要）。

## 変更しないもの

- `GraphPanelVM` 全般（`top_ratio`/`height_ratio`/`column` の計算、`move_axis_to_column`/`remove_signal`/`prune_missing_signals`/`resize_axis`/`_layout_column_preserving`/`_relayout_columns`/`_compact_axes`）。本件は **View 描画のみ**の修正。
- 波形 ViewBox の virtual-range 計算（既に絶対）。
- ルートグリッドのガター列固定幅予約・プロット列・X軸行。
- `axis_columns()` / `plot_grid_column()` の公開セマンティクス（占有列・プロット列）は維持。

## テスト計画

`docs/gui-testing-layers.md` 準拠。**今回の主眼は「描画ジオメトリ検証」層の新設**（前回の false-green の是正）。

### Layer B — 描画ジオメトリ結合（必須・CI・headless/offscreen 可）
View をマウントし、実際の `sceneBoundingRect()` を測る。VM 値ではなく**描画結果**を assert する。
1. `test_region_renders_blank_gap_after_prune` — 3リージョン非等分（0.5/0.3/0.2）→ 中央 prune → 生存軸 A/C の `_y_axes[]` と `_view_boxes[]` の rect が絶対ストリップ（A=[0,0.5H], C=[0.8H,1.0H]）に一致し、**中間帯 [0.5H,0.8H] にどの軸/ViewBox の rect も無い**（空白）こと。
2. `test_axis_spine_and_waveform_aligned` — 各リージョンで `_y_axes[i]` の Y 範囲と対応 `_view_boxes[i]` のデータストリップが整列（軸スパインと波形がズレない）こと。
3. `test_blank_gap_after_cross_column_move` — 列またぎ移動後、移動元列に空白帯が描画される（rect 不在）こと。
4. `test_region_geometry_follows_resize` — ウィンドウリサイズ後も各 rect が絶対比率を保つ（`sigResized`→sync 経路）こと。
5. 既存 View 構造テスト（`test_view_builds_one_sublayout_per_column` 等、グリッドサブレイアウト/ディバイダ前提のもの）は新機構に合わせて**見直し・更新**（公開ヘルパのセマンティクスは維持しつつ、内部グリッド前提の assert を描画ジオメトリ基準へ）。

### Layer A — VM（変更なし・回帰維持）
VM ロジックは不変。既存の高さ保持テスト（移動/削除/並べ替え）はそのまま green を維持。

### Layer C — 実OS入力（書き換え・ローカル・Windows）
- `tests/realgui/test_multi_column_axis.py` の assert を **VM 値から描画ジオメトリへ置換**（実ドラッグ後に `_view_boxes[]`/`_y_axes[]` の rect で空白・整列を確認）。
- `tests/realgui/test_remove_file_preserves_proportions.py` も同様に描画ジオメトリ assert へ見直し（削除側の空白描画を実機で確認）。

## エッジケース
- 合計<1.0 → 抜けた帯はどの要素も配置されず**真の空白**。
- 単一リージョン（h=1.0）→ 全高。空の列（ガター幅は確保、軸なし）。
- リサイズ（`sigResized` 同期）。
- 列スコープのディバイダ（隣接連続のみ）。

## スコープ外
- VM の高さ計算・レイアウト方針（移動/削除/並べ替え/追加/列数変更）は一切変更しない。
- 「空白を残すか詰めるか」の方針自体（=空白を残す、で確定済み）。

## 関連リンク
- 改修対象: `src/valisync/gui/views/graph_panel_view.py`（`_reconcile_axes`, `_sync_overlay_geometry`→`_sync_region_geometry`, `_axis_placement`, ディバイダ生成）
- 不変: `src/valisync/gui/viewmodels/graph_panel_vm.py`, `src/valisync/gui/viewmodels/y_axis_vm.py`（`calculate_virtual_range`）
- テスト方針: `docs/gui-testing-layers.md`
- 前段: `docs/superpowers/specs/2026-06-28-y-axis-height-preserve-design.md`, `docs/superpowers/specs/2026-06-28-y-axis-move-height-preserve-design.md`
