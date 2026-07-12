# FU-12: 軸境界データの張り付き解消（レンダリング層のストリップ・インセット余白）設計 spec

## 背景と真因

新規パネルに `Radar.Obj0.dx` を追加すると、t=0-60 の定数区間 y=45 がプロット下端フレームに張り付いて視認できない（FU-12）。真因は **auto-fit 済みの軸で、値がレンジ境界（min/max）に一致するデータが、プロット枠の端ピクセル行に描かれてフレーム線と融合する**こと。

実コードで確定（`gui/viewmodels/y_axis_vm.py:39-59` `calculate_virtual_range`）:
- 各軸のデータレンジ `[y_lo, y_hi]` を「仮想 ViewBox レンジ」に写して、データ帯を軸のリージョン strip `[top_ratio, top_ratio+height_ratio]` に着地させる。
- **フレームに接する strip**（`top_ratio==0` または `top_ratio+height_ratio==1`）では `v_hi==y_max` / `v_lo==y_min` の**恒等写像**になり、境界データがビューポート端＝フレーム上に乗る。フルハイト軸（単一軸新パネル＝FU-12 の報告ケース）はその特殊例。**フルハイト限定でなく、積み重ね軸の最外周でも同様に起きる**（Fable5 敵対的パネルが実式で反証・当初「非フルハイトは安全」という読みは誤り）。

不変条件（敵対的検証で確立）: **「データ値 == レンジ境界」なら、そのデータは必ずフレーム線上に描かれる**（枠の端ピクセル ≡ 境界値、レンジ定義そのもの）。境界データをフレームから剥がす唯一の方法は、**ViewBox が写すレンジをデータより広げる**こと。純粋なピクセル余白（viewbox 幾何を縮めるだけ）ではフレームも一緒に寄るため効かない。

## 採用アプローチ: C（レンダリング層のストリップ・インセット）

軸スケール（`y_range`）は**実データ範囲のまま（正直）**保ち、レンダリング層で各軸 strip を上下 `m` だけ内側へ寄せる（＝どの軸も真のフルハイトにしない）。棄却した代替 A（`_padded_range` でデータレンジ自体を広げる）に対する C の優位（Fable5 パネル 3/4 が C、実コードで検証）:

- **手動ズームも救う**: A は auto-fit チョークポイント（`_fit_axis`→`_padded_range`）のみ。`set_y_range`/`set_axis_range`（`graph_panel_vm.py:618-629`）は RN-05 契約で正確値を保つため、A では手動ズーム境界のデータがフレーム上に残る。C のインセットは全レンジソースの下流ゆえ auto/manual を一律に救う（RN-05 の「値は正確」は保持＝余白はレンジ非依存の描画）。
- **軸スケールが正直**: A は `y_range` に非データ値（42.25/102.75）を格納し、範囲指定ダイアログ等に漏れる＋X/Y 非対称（`reset_x` は正確値）。C は `y_range == 実データ範囲`。
- **`_padded_range`/RN-05 不変**: 縮退（定数信号 ±50%）はデータ空間で先に処理され、インセットはその後の描画空間＝直交。`_padded_range` の恒等 test-lock を破壊しない。
- **ネイティブ機構は全て不可**（パネルが反証）: `setYRange(padding=m)` は仮想スパン（span/height_ratio）を pad するためリージョンごとに ~m/(1+2m) の非一様インセット・スパイン非連動でズレる／autorange は無効化済み・オーバーレイ写像を表現不能／`contentsMargins` はフレームごと寄る／z-order はビューボックスがクリップ。

**唯一割れた観点**（YAGNI レンズ→A・HIGH）は「手動境界一致は未報告・churn 最小」という価値判断。プロジェクトの根本解決優先＋A の手動穴＋pixel 盲目な VM ゆえ将来 thin-axis を直せない点で C を採用（記録として dissent を明示）。

### インセットの数式（must-fix: 乗算・strip 相対）

margin `m = 0.03`。各軸の**実効（インセット）比率**:

```
effective_top    = top_ratio + m * height_ratio
effective_height = height_ratio * (1 - 2*m)
```

**乗算 `height_ratio*(1-2m)` 必須。絶対値 `height_ratio - 2m` は禁止** — `MIN_H = 0.05 < 2m = 0.06` のため最小高さ軸で負になり、`calculate_virtual_range` の `max(h_ratio, 1e-9)` クランプ（`y_axis_vm.py:51`）を踏んで仮想スパンが爆発、曲線が平坦化する実バグ（パネルが発見）。

実効比率を `calculate_virtual_range` の式に入れると（フルハイト・y=(45,100)・m=3%）: `effective_top=0.03, effective_height=0.94` → 仮想レンジ ≈ `(43.245, 101.755)`。データ 45 は下端から 3% 上、100 は上端から 3% 下に着地。スパイン目盛りは 45-100 のまま（数値検証済み）。tick アライメントは代数的に厳密（ViewBox のピクセル分率が y_hi で `effective_top`、y_lo で `effective_top+effective_height` に一致＝インセット strip の端と同一・両写像とも線形）。これは「model 比率が (effective_top, effective_height) の軸」とビット等価で、既存の全 `height_ratio<1` 軸で既に正しくレンダリングされている構成。

### クリップ（承認済み・honest な余白）

ユーザー承認（選択肢 A）: **各曲線をその軸のデータ範囲 `[y_lo, y_hi]`（インセット strip）にクリップし、余白帯を空に保つ**。手動ズーム時に範囲外データが余白帯へ滲むのを防ぎ、見た目を正直にする。

- FU-12 の報告ケース（auto-fit）は `[y_lo,y_hi]` が実データ範囲ゆえ余白は元々空 → クリップ有無で同一。クリップが効くのは**手動ズーム／複数軸のバンド跨ぎ**。
- **既存挙動への影響**: 現行は "unclipped overlay"（データが strip を跨いで滲む設計）。クリップはこの跨ぎ滲みも止める＝**既存の複数軸レンダリング挙動の変更**。承認済みの honest-margin 決定の帰結として受容。
- 実装: 各 `PlotDataItem` をその軸のインセット strip の scene 矩形にクリップ（正確な pyqtgraph 機構は writing-plans で確定＝curve をインセット strip 矩形にクリップする per-axis クリップコンテナ／`QGraphicsItem` クリップ等を評価し、realgui スクショで「手動ズーム時に余白帯が空」を実証）。**インセット（境界剥がし）とクリップ（余白を空に）は分離可能なコンポーネント**として実装・検証し、クリップが過大な改変になる場合は follow-up 分離をユーザーに諮る。

## 変更設計（2箇所を変え、5+箇所は据え置く）

**インセットを適用する 2 プロダクションサイト**（同一の `m` を消費）:
1. `calculate_virtual_range`（`y_axis_vm.py:39-59`・呼び出し `graph_panel_view.py:957`）— 実効比率で仮想レンジを計算。
2. `_sync_overlay_geometry` のスパイン strip（`graph_panel_view.py:997-1003`）— スパイン geometry を実効 strip に。

**単一ソース（must-fix）**: 実効比率は**1つのヘルパ**（例 `YAxisVM.effective_region(m) -> (effective_top, effective_height)` または view 側純関数）から両サイトが消費。`m` の二重リテラルは禁止（片側忘れ＝tick ドリフトの唯一の誤描画経路）。**実効比率を `top_ratio`/`height_ratio` に書き戻さない**。

**VM を純粋に保つ（推奨）**: `m` は **view 側で注入**（`calculate_virtual_range(margin=...)` パラメータ等）。`YAxisVM` の恒等契約（`tests/gui/test_y_axis_vm.py`）を維持。既定 `margin=0` で既存挙動不変。

**インセットしてはならない 5+ の model 比率サイト**（負の契約・プランに明記）: `_axis_index_at`（`:1521-1526`）・`_axis_drop_target`（`:1537-1549`）・`_update_axis_move_feedback`（`:1612-1614`）・グリップ grab/resize 数学（`:548-576`）・ディバイダー境界・VM タイル不変（`_relayout_columns`/`_normalize_columns`）。これらをインセットすると当たり判定に**デッドゾーン**が生じる。ヒットテストの superset バンドは現状のまま正しい。

**スコープ**:
- **Y のみ**。`reset_x` / X 処理は不変（X は RN-01 の境界サンプル取込で対応・FU-12 は水平線が水平フレームに乗る問題）。
- `_padded_range` / RN-05 不変（縮退はデータ空間で先、インセットは描画空間で後）。
- `calculate_virtual_range` の `max(span, 1e-9)` クランプと `y_range is None` スキップ（`graph_panel_view.py:955`）を維持。
- `m` はフラクション（リサイズ不変）で維持。`setYRange` は `refresh()` でのみ再適用され `sigResized` では再適用されない（`_sync_overlay_geometry` のみ）ため、ピクセルベース floor は resize でスタックする。ピクセル floor は別スコープ（下記残存）。

## テスト戦略

- **数値根因（headless VM）**: `calculate_virtual_range(margin=m)` がフルハイト＋境界値でデータをインセット（`v_lo < y_lo` かつ `v_hi > y_hi`）することを決定的に証明（FU-12 の数値証明）。
- **クロスサイト・アライメント guard の厳格化（must-fix）**: 既存 `test_waveform_data_band_coincides_with_axis_spine_strip`（`tests/gui/test_graph_panel_render_geometry.py`）は現在 `abs=0.03 == m` で緩く、片側忘れが marginal に pass する。**`abs` を m より十分小さく（例 0.005）**、またはピクセル一致でアサート。加えて「描画データ y_lo のピクセル行 == スパイン下端エッジ」を1本の Layer B でロック（tick 正直さ＋drag-zoom 精度）。
- **既存の geometry 契約テストを意図的に更新**（deliberate divergence・memory [[gui_behavior_change_stale_parallel_realgui_test]] で tests/ 全域を旧 strip 式で grep）: `tests/gui/test_y_axis_vm.py`（恒等・m を view 注入なら不変）・`tests/realgui/test_move_then_resize.py:94,122`・`tests/realgui/test_click_activate_axis.py:97`・`tests/gui/test_graph_panel_render_geometry.py`（`abs=0.03` は m=3% でちょうど境界＝再センタリング）＋ memory [[gui_region_overlay_viewbox_fixed_axis_spine_height]] の更新。
- **RN-05 合成の回帰**: 定数信号が「±50% 拡幅 AND フレームからインセット」の両方になることをアサート。
- **realgui（`/gui-verify` ①ゲート）**: 現実サイズで Radar.Obj0.dx 型の定数（y=45 == 軸 min）が下フレームから可視に分離する honest-RED スクショ。手動ズームで余白帯が空（クリップ実証）。グリップ/ゾーン realgui スイートを**再実行**（grab 点は live geometry から再計算・(1-m) の視覚追従で ~3px 遅延・memory [[gui_realgui_grip_drag_small_steps]]）。
- **ViewBox レベル受け入れ**: auto-fit 後 AND 手動 `set_axis_range`（境界値信号）後に、描画された y_min のピクセルがフレーム下端から `>= m*strip_height` 上にあることをアサート。

## 視覚変化（ユーザー承認済み・A = C・クリップあり・m=3%）

- スパイン端がフレーム角から `m` 離れる（despine 風）。
- 積み重ね軸間に `2m*height` の隙間。
- クリップにより余白帯は空（手動ズーム時も範囲外データを描かない）。

実 pyqtgraph レンダリングのキャプチャ3枚（`scratchpad/fu12_fig{1,2,3}.png`）で承認取得済み。

## 残存リスク・follow-up

- **細軸の sub-pixel 余白**: `margin_px = m*height_ratio*plot_height` は `MIN_H=0.05` で ~0.45-1.2px、`height_ratio≈0.15` で ~1.35-3.6px（2.5px のアクティブ曲線ペンに対し不足）。**報告済み FU-12（新規パネル＝フルハイト）は解消**するが、細い積み重ね軸は残る。**pixel floor は別 follow-up**（view 側算出＋`sigResized` での `setYRange` 再適用が前提＝別スコープ）として catalog に登録。
- **恒久的な2慣習の geometry 面**（model 比率 vs 実効インセット比率）は将来編集の silent-drift ハザード。単一ソースヘルパと厳格化アライメントテストで緩和。プランに「どのサイトがどの慣習か」を明記。
- **グリップ resize の (1-m) 視覚追従遅延**（~3px/100px・非蓄積）＝realgui グリップスイートの潜在フレーク。実機再実行必須。
- **クリップの既存 unclipped-overlay 挙動変更**（跨ぎ滲みも止まる）＝承認済み honest-margin の帰結だが、複数軸ユーザーには挙動変化。realgui スクショで確認。

## ファイル構成（変更予定）

- 変更: `src/valisync/gui/viewmodels/y_axis_vm.py`（`calculate_virtual_range` に `margin` 注入 or `effective_region` ヘルパ）
- 変更: `src/valisync/gui/views/graph_panel_view.py`（`_sync_overlay_geometry` のスパイン strip インセット・呼び出しで同一 `m`・クリップ適用）
- 変更: 上記テスト群（意図的更新＋新規 alignment/ViewBox 受け入れ/realgui）
- 不変: `graph_panel_vm.py`（`_padded_range`/`_fit_axis`/`reset_x`）・model 比率ヒットテスト群
