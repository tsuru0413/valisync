# 増分 F-0「安全な取込・範囲付き出力・プレビューラベル」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CSV 取込の列番号 off-by-one を構造解消（0 始まりヘッダ＋列ハイライト）、エクスポートに出力範囲指定＋選択数フッターを追加、プレビュー窓に軸ラベルを付与する。UX-05/UX-28/UX-43。

**Architecture:** [spec](../specs/2026-07-23-f0-safe-import-range-export-design.md) §1-§8 に逐語で従う。3 パートは独立ダイアログ改修。範囲フィルタは core（`CsvExportOptions`）で生座標・閉区間、GUI は表示座標の境界を DI で渡す（オフセット有効信号があるとき表示由来ラジオを disable）。列ハイライト・軸ラベルは既存トークン/表示名規約を守る。

**Tech Stack:** PySide6・pyqtgraph・pytest(-qt)・realgui。

**Spec:** [docs/superpowers/specs/2026-07-23-f0-safe-import-range-export-design.md](../specs/2026-07-23-f0-safe-import-range-export-design.md) — **8 レンズ敵対的レビュー 29 confirmed（I1-I3 Important＋Minor 18）反映済み**。

## Global Constraints

- **CSV 列番号 = 0 始まり**。core（`CsvFormatDetector`/`DetectedFormat`/`FormatDefinition`）は非改変。
- **エクスポート既定範囲 = 全期間**。
- **座標系（I2）**: エクスポートは base 信号の生タイムスタンプ座標・R14 オフセット非適用。範囲フィルタも生座標。表示由来ラジオ（現在の表示範囲・カーソル A–B）は**選択信号にオフセットがあるとき disabled**（全期間は常に有効）。
- **ガード**: x_range None で [現在の表示範囲] disabled（I3）・A/B 両設置でないとき [カーソル A–B] disabled。
- **列ティント可読性（I1）**: 時間列=`chrome_cursor_a`・信号列ティントは**両テーマで非テキスト最低 3:1**（値ベース機械検証・warning/info トークンと同型）。LIGHT で不足なら色相保持の暗色を用意し test-lock。
- **軸ラベルは display_name**（`display_names.display_name(sig.name)`）で生キー `::` を露出しない（E-0/UX-19 維持）。
- **DI は既定 None キーワード引数**（`ExportCsvDialog.__init__`/`.ask` 末尾）で後方互換（撮影・既存テスト直接構築が TypeError にならない）。
- **範囲は閉区間 [start,end]**。`start > end` は `CsvExportOptions.__post_init__` で **ValueError**。範囲外 0 行は header-only 出力。
- **新規文言は strings.py に Final 定数**（D-1 表記規約 R-01..13）。`Time`（軸ラベル）は意図的英語で据え置き。
- 品質ゲート各タスク末: `uv run pytest -q`・`uv run ruff check`・`uv run ruff format`・`uv run mypy src/`（同期実行）。
- コミット末尾: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## Task 1: 安全な CSV 取込（UX-05・0 始まりヘッダ＋列ハイライト）

**Files:**
- Modify: `src/valisync/gui/views/csv_format_dialog.py`（`_refresh` にヘッダラベル＋列ハイライト・`_header`/スピン接続）
- Modify（必要時）: `src/valisync/gui/theme/tokens.py`（LIGHT 信号ハイライト値・3:1 不足時のみ）
- Test: `tests/gui/test_csv_format_dialog*.py`・可読性は `tests/gui/test_theme_*` 系の値ベース

**Interfaces:**
- Consumes: 既存 `_ts_col`/`_sig_start`/`_sig_end`/`_header` ウィジェット・`chrome_cursor_a`/`drop_highlight` トークン。

- [x] **Step 1（0 始まりヘッダ TDD）**: プレビュー水平ヘッダが `"0: <名前>"`/`"1: <名前>"`（has_header 時）・`"0"`/`"1"`（無ヘッダ）で、スピン値と一致するテスト。ragged 行（`rows[0]` が短い）で IndexError しないこと。
- [x] **Step 2（RED）**: `uv run pytest tests/gui/test_csv_format_dialog.py -q` → FAIL（現状ヘッダラベル未設定）。
- [x] **Step 3（実装）**: `_refresh()` に:

```python
n_cols = max((len(r) for r in rows), default=0)
has_header = self._header.isChecked()
labels = []
for ci in range(n_cols):
    name = rows[0][ci] if (has_header and rows and ci < len(rows[0])) else None
    labels.append(f"{ci}: {name}" if name else str(ci))
self._preview.setHorizontalHeaderLabels(labels)
```

- [x] **Step 4（GREEN）**: Step 1 PASS。
- [x] **Step 5（列ハイライト TDD）**: 時間列スピン変更 → 該当列セル背景が `chrome_cursor_a` ティントへ移動・旧列非着色。信号列 `_sig_start`..`_sig_end` が信号ティント。`ts_col ∈ 信号範囲` の過渡で ts_col 勝ち。**sabotage**: 固定列着色 → RED。
- [x] **Step 6（実装）**: `_refresh()` 本体で `QTableWidgetItem.setBackground(QColor(...))`。信号範囲を先に塗り→時間列を後で塗る。トークン色から低 α の `QColor` 導出。**`_ts_col`/`_sig_start`/`_sig_end` の `valueChanged` と `_header.stateChanged` を全て `_refresh` へ接続**（現状 `_validate` のみの `_header`/スピンを追加接続）。
- [x] **Step 7（可読性 TDD — I1）**: 時間列/信号列ティント値が**両テーマで非テキスト最低 3:1**（値ベース機械検証・既存 warning/info テストと同型）。LIGHT で `drop_highlight` 低 α が不足するなら `tokens.py` に色相保持の LIGHT 専用信号ハイライト値を追加し 3:1 を満たす値を test-lock。**sabotage**: 3:1 未満の値へ差し替え → RED。
- [x] **Step 8（GREEN＋回帰）**: Step 5/7 PASS。`CsvFormatDetector`/`DetectedFormat` の 0 始まり列インデックス不変を Layer A で回帰ガード（T-A4）。ヘッダ ON/OFF トグルで名前部が追従（stale なし）。
- [x] **Step 9（ゲート＋commit）**: 全ゲート green → `feat(gui): CSV 取込ダイアログ 0 始まりヘッダ＋列ハイライト (UX-05)`
  - 注: トークンを追加した場合、`uv run python scripts/export_design_tokens.py` で design 差分が出る（Task 5 で DesignSync 反映）。

---

## Task 2: 範囲付きエクスポート core（UX-28・`CsvExportOptions` 拡張）

**Files:**
- Modify: `src/valisync/core/export/csv_exporter.py`（`CsvExportOptions` に `time_start`/`time_end`＋`__post_init__` 検証・`_rows_*` フィルタ）
- Test: `tests/**/test_csv_exporter*.py`

**Interfaces:**
- Produces: `CsvExportOptions.time_start: float | None`・`time_end: float | None`（既定 None）。`_rows_unified_timeline`/`_rows_shared_timeline` が閉区間フィルタ。

- [x] **Step 1（範囲フィルタ TDD）**: `time_start`/`time_end` を与え、出力行が**閉区間 [start,end]** のみ・None は無制限・浮動小数境界（t==start/end 含有）を検証。**prod スケール（330k 相当）で行数削減の正しさ**。
- [x] **Step 2（RED）**: FAIL（フィールド未定義）。
- [x] **Step 3（実装）**: `CsvExportOptions` 末尾に既定付きフィールド追加＋`__post_init__` で `start>end` 検証:

```python
time_start: float | None = None
time_end: float | None = None

def __post_init__(self) -> None:
    if self.time_start is not None and self.time_end is not None and self.time_start > self.time_end:
        raise ValueError("time_start must be <= time_end")
```

`_rows_unified_timeline`/`_rows_shared_timeline` の行ループで行時刻 `t` に対し
`(time_start is None or t >= time_start) and (time_end is None or t <= time_end)` を満たす行のみ yield（**タイムライン解決後**に適用）。ヘッダ/単位行は無条件出力（範囲外 0 行なら header-only）。

- [x] **Step 4（GREEN）**: Step 1 PASS。
- [x] **Step 5（境界/タイムライン TDD）**: `start>end`→ValueError・範囲外→header-only・`start==end` 境界。統合タイムライン解決後に範囲適用（shared-timeline mismatch loud-fail 維持）。既存 `test_csv_exporter` が新フィールド既定 None で後方互換（無回帰）。
- [x] **Step 6（ゲート＋commit）**: green → `feat(core): CSV エクスポートに時間範囲フィルタ (CsvExportOptions.time_start/time_end) (UX-28)`

---

## Task 3: 範囲付きエクスポート GUI（UX-28・ダイアログ範囲ラジオ＋フッター）

**Files:**
- Modify: `src/valisync/gui/views/export_csv_dialog.py`（範囲ラジオ・フッター・DI・ガード・`_current_options` 注入）
- Modify: `src/valisync/gui/views/main_window.py`（`export_csv` で x_range・A/B・オフセットをスナップショット注入）
- Modify: `src/valisync/gui/strings.py`（範囲ラベル・ラジオ3種・フッター・tooltip 文言）
- Test: `tests/gui/test_export_csv_dialog*.py`

**Interfaces:**
- Consumes: Task 2 の `CsvExportOptions.time_start/time_end`・`GraphAreaVM.active_tab()`・`GraphPanelVM.x_range`（属性）・`cursor_state`・`AppViewModel` オフセット。

- [x] **Step 1（範囲ラジオ→options TDD）**: [全期間]→None/None・[現在の表示範囲]→x_range・[カーソル A–B]→cursor min/max が `CsvExportOptions` に注入されるテスト。**ガード**: x_range None で [表示範囲] disabled・A/B 未設置で [A–B] disabled・**選択信号オフセット時に表示由来2ラジオ disabled**。マルチタブでアクティブタブ参照。
- [x] **Step 2（RED）**: FAIL（範囲 UI 未実装）。
- [x] **Step 3（実装）**: `ExportCsvDialog.__init__`/`.ask` 末尾に**既定 None のキーワード引数**（`x_range`・`cursor_a`・`cursor_b`・`offset_active`）を追加。range `QRadioButton` 群（[全期間]既定 checked）＋各ガードで `setEnabled`。`_current_options()` で range→`time_start/time_end` 注入。`main_window.export_csv` で `active_tab()`/`active_panel().x_range`/`cursor_state`/オフセットをスナップショットして渡す（View 分離）。文言は `strings.py` の `Final` 定数（範囲ラベル・ラジオ3種・カーソル範囲併記テンプレ・tooltip）。
- [x] **Step 4（GREEN）**: Step 1 PASS。
- [x] **Step 5（選択数フッター TDD）**: 「N 信号を選択中」= 総選択数 `len(_checked_keys())`（フィルタ非依存）。選択済みをフィルタで隠してもフッター不変・フッター数==出力集合数。すべて選択/解除は `blockSignals` バッチ化。**sabotage**: フッターをフィルタ後の可視数にする → RED。
- [x] **Step 6（実装）**: `_validate` 相乗りで `QLabel` 更新＋`_select_all`/`_select_none` バッチ化。
- [x] **Step 7（GREEN＋後方互換）**: Step 5 PASS。既存 export ダイアログテスト（直接構築）が既定 None 引数で無回帰。
- [x] **Step 8（ゲート＋commit）**: green → `feat(gui): エクスポートダイアログに出力範囲ラジオ＋選択数フッター (UX-28)`

---

## Task 4: プレビューラベル（UX-43）

**Files:**
- Modify: `src/valisync/gui/views/signal_preview_window.py`（`_render` に `setLabel`）
- Modify: `src/valisync/gui/viewmodels/signal_preview_vm.py`（`axis_label_parts()` 公開アクセサ）
- Test: `tests/gui/test_signal_preview*.py`

**Interfaces:**
- Produces: `SignalPreviewVM.axis_label_parts() -> tuple[str, str | None]`（display_name, unit）。

- [x] **Step 1（ラベル TDD）**: `preview_plot` の bottom ラベル=「Time」(units="s")・left ラベルに **display_name（`::` なし）＋unit**。`axis_label_parts()` が `display_names.display_name(sig.name)` と unit を返す。**sabotage**: 生キー `_signal().name` を使う → `::` が出て RED。
- [x] **Step 2（RED）**: FAIL（ラベル/アクセサ未実装）。
- [x] **Step 3（実装）**: `SignalPreviewVM.axis_label_parts()` 追加。`_render()` で
  `preview_plot.setLabel("bottom", "Time", units="s")`／`preview_plot.setLabel("left", name, units=unit)`
  （name/unit は `axis_label_parts()`・色は明示せず `plot_foreground` 継承）。
- [x] **Step 4（GREEN）**: Step 1 PASS。
- [x] **Step 5（ゲート＋commit）**: green → `feat(gui): 信号プレビュー窓に軸ラベル (Time/信号名 unit・display_name) (UX-43)`

---

## Task 5: realgui ①ゲート＋凍結カタログ＋撮影 DI 更新＋docs＋最終ゲート

**Files:**
- Modify: `tests/realgui/`（T-C1/T-C2/T-C3 新設 or 拡張）
- Modify: `scripts/capture_ui_screenshots.py`（ExportCsvDialog 新 DI 署名・決定的カーソル注入・プレビュー crop）
- Modify: `docs/design.md`・`docs/uiux-adversarial-review-catalog.md`・`CLAUDE.md`
- Verify: `design_export/screenshots_catalog_{dark,light}`

- [x] **Step 1（realgui T-C1/2/3）**:
  - T-C1: 実 CSV → フォーマットダイアログでスピン実操作 → 0 始まりヘッダ＋列ハイライトを実ピクセル確認（スクショ目視）。
  - T-C2: 2 カーソル設置 → [カーソル A–B] 選択 → **実出力ファイルの行時間範囲が A–B に収まる**ことを実ファイル読み直しで検証。全期間との行数差。
  - T-C3: プレビューを開き軸ラベルをスクショ目視。
  - エビデンスを `design_export/evidence_f0/` へ保存し Read で目視・所見を report へ。
- [x] **Step 2（realgui フル）**: `uv run pytest tests/realgui/ --realgui -q`（timeout 600000・バッチ可）。既知フレークは単体で切り分け。
- [x] **Step 3（撮影 DI 更新＋凍結）**: `capture_ui_screenshots.py` の ExportCsvDialog 直接構築（:216 付近）を**新 DI 署名へ更新**し決定的カーソル（例 3.0/6.0）を注入して [カーソル A–B] enabled＋実範囲ラベルを撮る。プレビュー窓に viewport crop 相当を用意。撮影 → `compare_screenshots.py`（両テーマ・`--crop-meta`）。**per-state 期待差分**（エクスポート=範囲ラジオ3行＋フッター／CSV ダイアログ=0始まりヘッダ+ハイライト／プレビュー 08=軸ラベル＋波形再配置〔データ不変〕）に限定を実証。main window プロット面 viewport は不変。想定外差分は原因特定。
- [x] **Step 4（昇格＋決定性）**: 想定差分に限定なら昇格 → 再撮影 compare exit 0（両テーマ）＋決定性。
- [x] **Step 5（docs）**:
  - docs/design.md 決定履歴に 1 エントリ（F-0・0 始まり列/ハイライト・範囲エクスポート＋オフセット座標系契約・プレビューラベル・敵対的レビュー I1-I3 の要点）。トークン追加時は design.md のトークン節反映。
  - docs/uiux-adversarial-review-catalog.md: UX-05 → ✅解消・UX-28 → ✅解消・UX-43 → ✅解消の注記。
  - CLAUDE.md の 横断/UIUX 敵対的レビュー行へ F-0 完了サマリ（F-1/F-2 は defer・次候補）。
- [x] **Step 6（プランのチェックボックス更新）**: 消化済みへ。
- [x] **Step 7（最終ゲート＋commit）**: `uv run pytest -q`・ruff・mypy green → `feat(gui): F-0 realgui ①ゲート＋凍結検証＋docs`

## Self-Review 済み確認事項

- spec §1-§8 の全要素がタスクに 1:1（0始まりヘッダ/ragged・列ハイライト/ライブ配線・LIGHT 3:1・range core フィルタ/検証・GUI ラジオ/ガード/フッター/DI・プレビュー display_name ラベル・realgui/カタログ/docs）。
- I1-I3 反映: I1 可読性 3:1（Task 1 Step7）・I2 座標系 offset disable（Global＋Task 3 Step1/3）・I3 x_range None ガード（Task 3 Step1）。
- Minor 反映: header 追従（T1 S6）・ragged（T1 S3）・phantom header_row 除去（spec 済）・塗り優先（T1 S5/6）・ライブ配線一本化（T1 S6）・窓外非包含/空範囲（T2 S5）・API 名訂正（T3 S3）・フッター意味論/バッチ（T3 S5/6）・:: 撤去（T4 S1）・公開アクセサ（T4 S3）・units 規約/色（T4 S3）・crop スコープ/プレビュー08（T5 S3）・DI 既定 None（T3 S3）・文言集約（T3 S3）。
- 型整合: `time_start/time_end: float|None`・`axis_label_parts()->tuple[str,str|None]`・DI 既定 None キーワード引数を Interfaces に明記。
