# 軸ごとリサイズ ＋ アクティブ軸統一操作モデル 設計

- 日付: 2026-06-28
- 対象 spec: `valisync-gui-axes`（リサイズ操作の刷新）
- 関連: [高さ保持](2026-06-28-y-axis-move-height-preserve-design.md) / [絶対ジオメトリ描画](2026-06-28-y-axis-region-absolute-render-design.md) / `docs/multi-axis-empty-region-followup.md`

## 1. 背景・目的

### 現状
- **リサイズ**: 隣接ペアの間に置いた連動ディバイダー（`RegionDividerItem`）をドラッグし、上下2軸が**ゼロサム連動**で変化（`GraphPanelVM.resize_axis`）。
- **ズーム/パン**: Y軸ストリップを widget レベルの「ゾーン」方式で受付（`classify_zone` / `apply_zone_drag` / `wheelEvent`）。だが実機では **カーソル形状が変わらない・受付エリアが極狭・パンが効かない・軸ドラッグで移動(QDrag)が暴発** という壊れ方をしている（ヘッドレステストが実イベント経路を迂回するため検知できていなかった）。

### 目的（根本修正を最優先）
1. 各軸を独立にリサイズできる **「軸ごとリサイズ」** を導入する（連動を廃止）。
2. **パン・ズーム・リサイズ・移動をすべて「アクティブ軸」に集約**した統一操作モデルへ刷新する。壊れたゾーン方式を **症状隠蔽でなく根本から作り直す**（AxisItem 側で確実に hover/cursor/ヒット判定を行う）。

## 2. 用語

| 用語 | 意味 |
|---|---|
| アクティブ軸 | 操作対象として選択された1軸。**全操作はアクティブ軸のみ受付**。 |
| フレーム | アクティブ軸のスパインに描く枠線（案C：軸内に収め、プロットに被せない）。 |
| グリップ | フレーム上端中央／下端中央に出る小バー。リサイズの掴み手。 |
| ゾーン | アクティブ軸スパイン内の操作領域区分（グリップ／枠線／内側／外側）。 |
| モデルB | リサイズ方式。対象軸のみ伸縮し、空白を直下/直上に出し入れ。他軸は位置も高さも不動。 |
| 空白(gap) | 列内で軸が占めない帯。`height_ratio` の合計 < 1 のとき生じる。 |
| `top_ratio` / `height_ratio` | 軸の列内縦位置・高さ（0.0–1.0、パネル全高比）。`YAxisVM` が保持。 |

## 3. 受け入れ要件（対話で合意）

1. **連動ディバイダー（`RegionDividerItem`）は完全廃止**。
2. **全操作（パン/ズーム/リサイズ/移動）はアクティブ軸のみ受付**。非アクティブ軸は表示のみ。
3. **アクティブ化**: ホバーで仮フレーム（プレビュー）、**クリックで固定**。
4. **フレーム**: スパイン枠線のみ（軸内に収め、プロット非干渉）。
5. **アクティブ軸スパインのゾーン**（優先順位 グリップ ＞ 枠線 ＞ 内/外、各ゾーンで**カーソル形状を変更**）:
   - **① グリップ（上端中央／下端中央）＝リサイズ**。判定は**グリップ要素上のみ**（帯にしない）。ただし**掴みやすさのため当たり判定はグリップ周囲に適切に拡張**（tolerance ハロー）。
   - **② 枠線（①以外のフレーム上）＝移動**（QDrag、他列へ/並べ替え）。
   - **③ 内側（プロット寄り・①②以外・高さ全体）＝ズーム**。
   - **④ 外側（反対側・①②以外・高さ全体）＝パン**。
6. **リサイズ＝モデルB**。制約は3つ:
   - **最小高さ 5%**
   - **隣接軸を押さない**（ドラッグした辺は隣接ギャップの範囲内でのみ動く）
   - **自身の逆端も押さない**（ドラッグした辺だけが動き、同じ軸の反対辺は固定。限界に達したら停止し反対辺へ波及しない）
   - 上下両端グリップにより拡大も可能（隣を縮めて隙間を作り、その隙間へ広げる）。
7. **ズーム＝範囲選択（ズームインのみ）**。内側ドラッグで選択した区間へレンジを縮める。
8. **ホイール操作・ダブルクリック操作は X/Y 軸とも不採用**。
9. **ズームアウト／リセット（Auto-Fit）はドラッグジェスチャでは行わない**。後日コンテキストメニューから実装予定（**本スコープ外**）。→ 本スコープでは**ドラッグによるズームはズームインのみ**となる（暫定仕様として明記）。
10. **X軸（時間・共有・パネル下端）は常時ズーム/パン可**（アクティブ概念の外）。内側=範囲選択ズーム、外側=パン。ホイール/ダブルクリックは無し。

## 4. 操作モデル詳細（アクティブ軸スパイン）

スパイン矩形（幅 `_Y_AXIS_FIXED_WIDTH`、高さ＝その軸のリージョン高さ）を次に区分する。プロットは右にあるため **内側＝右（プロット寄り）／外側＝左（窓端寄り）**。

```
        ┌──[グリップ:リサイズ]──┐  ← 上端中央の小バー（+tolerance）
        │ 外側(左) │ 内側(右)  │
        │  パン    │  ズーム   │  ← 枠線・グリップ以外の本体。高さ全体。
        │ (cursor↕)│ (cursor⤢) │
        └──[グリップ:リサイズ]──┘  ← 下端中央の小バー（+tolerance）
   枠線(上記以外の周縁)=移動(QDrag, cursor✥)
```

- **判定優先順位**: グリップ → 枠線 → 内/外本体。
- **カーソル**（提案、実装時に最終調整）: リサイズ=`SizeVerCursor`、移動=`SizeAllCursor`、ズーム=`CrossCursor`、パン=`OpenHandCursor`（ドラッグ中 `ClosedHandCursor`）。
- **非アクティブ軸**: いかなるドラッグ/ホイールも受け付けない。クリックでアクティブ化のみ。ホバーで仮フレーム表示。

## 5. リサイズのドメインロジック（モデルB）

新規 VM メソッド `resize_axis_edge(axis_index, edge, delta_ratio)` を追加。`edge ∈ {TOP, BOTTOM}`、`delta_ratio` は下方向正（ピクセル差 / パネル高）。対象軸を `i`、列内の縦順で直上を `prev`、直下を `next` とする（無ければ列上端 0.0 / 列下端 1.0）。

### 下端ドラッグ（`BOTTOM`）
- 望ましい新下端 `b' = t_i + h_i + delta`。
- クランプ:
  - 最小高さ: `h_i + delta ≥ 0.05`
  - 隣接を押さない: `b' ≤ (next.top_ratio もしくは 1.0)`
- 反映: `h_i += clamp(delta)`。`t_i` は不変（**逆端＝上辺は固定**）。他軸は一切変更しない。

### 上端ドラッグ（`TOP`）
- 下端 `t_i + h_i` を固定したまま上辺を動かす。望ましい新上端 `t' = t_i + delta`、新高さ `h' = h_i - delta`。
- クランプ:
  - 最小高さ: `h_i - delta ≥ 0.05`
  - 隣接を押さない: `t' ≥ (prev.bottom もしくは 0.0)`
- 反映: `t_i += clamp(delta)`、`h_i -= clamp(delta)`。下端 `t_i+h_i` は不変（**逆端＝下辺は固定**）。他軸は一切変更しない。

### 拡大フロー（密着時）
密着列では辺を広げる余地が無い。隣接軸を縮めて隙間を作り（例：上隣の下端グリップで上隣を縮小→`prev` と `i` の間に空白）、`i` の上端グリップでその空白へ拡大する。各操作は単一軸のみ変更し、非隣接軸は不動。

### 既存ロジックとの関係
- `GraphPanelVM.resize_axis`（連動・ゼロサム）は**削除**。
- レイアウト適用（`_sync_overlay_geometry` による絶対ストリップ配置）と高さ保持（`_layout_column_preserving`）は既存を流用。リサイズ後は通常の `refresh()` → 再配置で反映。

## 6. ズーム/パンのドメインロジック

- per-axis Y レンジは既存（`YAxisVM.y_range` / `set_range` / `calculate_virtual_range`）。**データ構造の変更は不要**。
- 現状 `GraphPanelVM.y_range` / `set_y_range` は **先頭軸 `_axes[0]` 固定**（property 委譲）。これを廃し、**アクティブ軸の `YAxisVM.set_range` を更新**する軸指定経路にする。
- **ズーム（内側・範囲選択）**: ドラッグ始点/終点の Y をアクティブ軸の ViewBox（`_view_boxes[i]`）でデータ値へ変換し、`ordered_pair(start, end)` をその軸の新レンジに設定（既存 `apply_zone_drag` の Y_INNER 相当を軸指定で再利用）。→ 区間へ縮める＝ズームインのみ。
- **パン（外側）**: `pan_range(lo, hi, start - end)` をアクティブ軸レンジへ。
- **X軸（常時）**: パネル単位の `x_range` を範囲選択ズーム/パン。共有のため全 ViewBox に XLink 済み。

## 7. アーキテクチャ・コンポーネント

### VM層（`GraphPanelVM` / `YAxisVM`）
- 追加 `resize_axis_edge(axis_index, edge, delta_ratio)`（§5）。
- 追加（または整理）: アクティブ軸指定の Y ズーム/パン経路（`YAxisVM.set_range` を対象軸に適用）。先頭軸固定の `set_y_range` を置換。
- 削除 `resize_axis`（連動）。
- `reset_x` / `reset_y` のロジックは**残す**（将来のコンテキストメニューから利用）。本スコープでは入口を設けない。

### View層（`GraphPanelView`）
- アクティブ軸状態 `_active_axis_index: int | None`、`_hover_axis_index: int | None`（**非永続** UI 状態。セッション/.vsproj に保存しない）。
- 軸移動後もアクティブ対象を維持し、他列でも認識しやすくする。
- **削除**: divider 生成ループ・`_position_dividers`・`self._dividers`。
- **Y軸のゾーン/ジェスチャ受付は AxisItem 側へ移設**（widget レベルの `mousePress/Move/Release` ゾーン処理・`wheelEvent`・`mouseDoubleClickEvent` は撤去または X 軸専用に縮退）。
- **X軸**は常時ズーム/パン（X-axis ストリップで範囲選択ズーム/パン、カーソル適用）。

### `_AlignedAxisItem`（中核＝操作面）
- `setAcceptHoverEvents(True)`。アイテムローカル座標で**ゾーン判定** `_zone_for_local_pos(pos)`（グリップ tolerance 含む）。
- `hoverMoveEvent`: アクティブ軸なら zone 別 `setCursor`。非アクティブは通常カーソル＋仮フレーム。
- マウス押下/ドラッグを zone で分岐:
  - **グリップ** → リサイズ直接ドラッグ（既存ディバイダーと同方式の `isStart/中間/isFinish`・`delta` → `resize_axis_edge`）。
  - **枠線** → 移動 QDrag（既存 `encode_axis_index` 経路）。
  - **内側** → 範囲選択ズーム（対象軸 `set_range`）。
  - **外側** → パン（対象軸 `set_range`）。
- 非アクティブ時はクリックでアクティブ化のみ。
- `paint`: アクティブ/ホバー時にフレーム枠線＋上下グリップを描画（案C）。

### 削除ファイル
- `src/valisync/gui/views/region_divider_item.py`（**承認済み**）。関連 import / 参照も除去。

## 8. データフロー

1. ホバー → `AxisItem.hoverMoveEvent` → 仮フレーム描画＋ゾーン別カーソル。
2. クリック → `_active_axis_index` 確定 → 再描画（フレーム＋グリップ）。
3. グリップドラッグ → `resize_axis_edge` → `top_ratio/height_ratio` 更新 → VM 通知 → `refresh()` → `_sync_overlay_geometry` で絶対ジオメトリ再配置。
4. 枠線ドラッグ → QDrag → drop → `move_axis_to_column`（既存）。
5. 内側/外側ドラッグ → 対象軸 ViewBox でデータ変換 → `YAxisVM.set_range` → `refresh()`。
6. X軸ドラッグ → `set_x_range`（既存）。

## 9. エラー処理・エッジケース

- リサイズ制約3つ（最小5%／隣接を押さない／逆端を押さない）を `resize_axis_edge` 内でクランプ。限界で停止し波及させない。
- **低い軸でグリップ重なり**: 上下グリップ（+tolerance）が重なる場合はグリップ優先＋最小高さ確保。重なって判別不能になる極小高さは最小5%が下限なので発生しにくいが、tolerance を高さに応じて縮める。
- **アクティブ軸が移動/削除された場合**: インデックス追従、または対象消失時はアクティブ解除。
- **単一軸/列に空白なし**: 広げる余地が無いときはリサイズ無反応（制約どおり）。
- **当たり判定 tolerance 値**: 実機（realgui）で掴みやすさを確認しつつ決定。

## 10. テスト戦略（GUIテストレイヤー）

`docs/gui-testing-layers.md` に準拠。計画時 `/gui-test-plan`、merge 前 `/gui-verify`。

- **Layer A（ユニット/VM）**
  - `resize_axis_edge`: モデルB挙動（対象のみ変化・他軸不動・ギャップ生成/消費）と制約3つ（最小5%／隣接を押さない／逆端を押さない）のクランプ。
  - ゾーン判定関数（ローカル座標→zone、グリップ tolerance、優先順位）。
  - per-axis ズーム/パンのレンジ更新（範囲選択＝ズームイン、パン）。
- **Layer B（ヘッドレス結合）**
  - AxisItem のゾーン分岐ロジック（直叩き）。
  - フレーム/グリップ描画がアクティブ時のみ出る。
  - divider 廃止の確認（生成されない／参照が無い）。
  - ※ **実イベント経路・カーソル変更・QDrag 実配送は Layer B では証明不可**（合成 sendEvent では D&D 実配送を再現できない）。
- **Layer C（realgui・必須）**
  - 実OS入力でグリップ→該当軸のみリサイズ（**描画ジオメトリの絶対確認**）。
  - 枠線→移動（QDrag 実配送は**別OSスレッド＋watchdog**で駆動しハングを回避）。
  - 内側→範囲選択ズーム／外側→パン。
  - **各ゾーンでカーソル形状が変化**すること（現状不具合の根治確認）。
  - **非アクティブ軸では一切受付しない**こと。
  - 受付エリアが**極狭でない**こと。
  - スクリーンショットは `QT_QPA_PLATFORM=windows`（offscreen は文字が□化）。

## 11. スコープ外（YAGNI / 別タスク）

- **ズームアウト／リセット（Auto-Fit）のコンテキストメニュー実装**（後日）。本スコープのドラッグズームはズームインのみ。
- 空白の自動詰め/均等化アクション。
- アクティブ状態の永続化。
- X軸のアクティブ化（X は常時操作）。

## 12. 実装時に確定する細部（open）

- グリップ可視寸法と tolerance 値（実機調整）。
- 各ゾーンの最終カーソル形状。
- X軸の受付を AxisItem 側に寄せるか widget レベルに残すか（根本修正の一貫性と実装簡潔性のトレードオフ。Y を AxisItem へ移すのに合わせ、X も X-AxisItem へ寄せるのを推奨）。
- `_data_value` 相当のピクセル→データ変換を AxisItem からどう呼ぶか（対象 ViewBox 経由）。

## 13. 既存仕様・成果物との関係

- 本設計は `valisync-gui-axes` のリサイズ操作を刷新するもの。`.kiro/specs/valisync-gui-axes/{design,tasks}.md` への反映要否は実装計画時に確認（要件がずれる場合は `design.md` 更新をユーザー承認）。
- 空白保持モデル（PR #14: 絶対比率保持＋空白）と整合（モデルBは空白を直下/直上に出し入れ）。
- 連動ディバイダーに依存した既存テスト（`test_region_divider_item.py`、`test_dragging_divider_resizes_adjacent_regions` 等）は廃止/置換する。

## 14. 実装メモ（実装時に確定した事項）

実装（subagent-driven）と realgui 実機検証で確定/判明した、将来の保守に効く要点。

- **`classify_zone` のYゾーンは保持（プラン逸脱・根拠あり）**: 計画では widget レベルの `classify_zone` を「X専用に縮退」とした。しかし `classify_zone` の `ZONE_Y_INNER/ZONE_Y_OUTER` は **`dropEvent` の R5 ドロップ判定**（信号をYストリップへ落とす＝該当軸へ追加/上書き、プロットへ落とす＝新規軸）でも消費される。X専用に縮退すると全ドロップが「新規軸作成」に落ち R5 上書き/Ctrl結合が壊れるため、**`classify_zone` はYゾーンを返したまま**とし、Yの**ズーム/パン/wheel/dblクリック/カーソル消費のみ**を撤去した。Y操作（リサイズ/ズーム/パン/移動）は `_AlignedAxisItem` 上のアクティブ軸ジェスチャへ移行済み。回帰ガード: ドロップ系テスト（`test_graph_panel_multi_axis`・`test_graph_panel_view`）が緑のまま。
- **ホバーカーソルは `_AlignedAxisItem` 自身に設定**（`hoverMoveEvent`→`setCursor`）。観測は `axis.cursor().shape()`（`view.cursor()` ではない）。
- **リサイズは絶対座標追従（`grip_resize_delta`、root-cause 修正）**: グリップ端はカーソルを **パネル全高に対する比率** で追従する。旧実装はピクセル差をスパイン高（`height_ratio*panel`）で割っており移動量が 1/height_ratio 倍に膨張→カーソルとエッジがずれ最小高へ暴走（上端ちらつき・下端ミスマッチ）。`grip_resize_delta(cursor_y, panel_top, panel_h, grab_offset, edge)` は軸高を引数に取らない（高さ非依存）設計でこれを封じる。回帰ガード: `test_axis_zone_classify` の `grip_delta_*`。
- **軸移動後の初回ジェスチャは rebuild を遅延（QDrag モーダル外へ）**: 軸移動の `QDrag.exec()`（Windows OLE モーダルループ）内で `dropEvent`→軸 rebuild すると、`GraphicsScene` が破棄済みアイテムへ press/drag/hover 参照を残し、移動後の初回リサイズが誤配送（no-op、さらに再帰 QDrag で**無限ハング**）。`dropEvent` の `move_axis_to_column` を `QTimer.singleShot(0, _apply_deferred_axis_move)` で次イベントループターンへ遅延し、rebuild 後に `reset_scene_drag_state(scene)` で `dragButtons/dragItem/clickEvents/lastDrag/lastHoverEvent` をクリア→次ジェスチャは `itemsNearEvent` で実アイテムを再発見。診断は `faulthandler.dump_traceback_later` ＋ zone 座標ログ。回帰ガード: realgui `test_move_then_resize`、headless `test_apply_deferred_axis_move_*`。詳細メモ: `gui_realgui_qdrag_rebuild_stale_scene`。
- **移動フレームは 8px ＋ 短軸は h/4 上限（掴みやすさ修正＝Symptom 2）**: `FRAME` 3→8px。3px ヘアラインは SizeAll カーソルが境界でちらつき掴み損ねが頻発したため拡幅（左右端＝幅固定の自然な掴み代）。上下バンドは `classify_axis_zone` で `v_frame=min(frame, h/4)` にキャップし、リサイズで縮んだ短軸でも中央にズーム/パン内部を残す（フレーム全潰れ防止）。回帰ガード: `test_axis_zone_classify` の FRAME=8 / h/4 ケース。
- **realgui 実機所見（Layer C 証拠ゲート）**:
  - Model B は「隣接軸を押さない」ため、連続レイアウト（隙間なし）では下端グリップを**下げて拡大は不可**（正しい no-op）。拡大は隣を縮めて隙間を作ってから。テストは下端グリップを**上げて縮小**で検証。
  - pyqtgraph のホバー配送は**漸進的な実移動**が必要（一発の `SetCursorPos` では `hoverMoveEvent` が出ない）。カーソル検証は小刻みスイープ＋配送リトライで駆動。
  - フレーム=移動の QDrag は、閾値超えの最初の移動を**垂直**にして lx を frame 帯（現 8px）内に保つ必要がある（`mouseDragEvent` の isStart は閾値超え後の `ev.pos()` でゾーン分類するため、水平移動だと frame を外れ pan 誤判定）。realgui の pan テストは逆に、拡幅した frame を避け掴み位置をスパイン幅の 0.25（内部）に置く。
  - グリップ矩形がスパイン上端を約3px はみ出す（左ガター列内で完結し非干渉＝案C維持・cosmetic、follow-up）。
