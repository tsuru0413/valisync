# 増分 F-0「安全な取込・範囲付き出力・プレビューラベル」設計

> **出典**: UIUX 敵対的レビュー catalog 推奨6「入口と出口の再設計」の先行実施分（F-0）。
> [docs/uiux-adversarial-review-catalog.md](../../uiux-adversarial-review-catalog.md) の UX-05/UX-28/UX-43 を解く。
> F-1（.vsession セッション永続化）・F-2（Welcome 再開ハブ＋スナップショット共有）はユーザー決定で**今後検討へ defer**。
> ブランチ `feature/f0-safe-import-range-export`。

## Goal

「開く → 見る → 書き出す」ジャーニーの取込と出力を安全化する独立ダイアログ改修:
- **UX-05（🔴データ破損直結）**: CSV 取込ダイアログの列番号 off-by-one を構造解消（0 始まりヘッダ＋列ハイライト）。
- **UX-28**: エクスポートに出力範囲指定（全期間/表示範囲/カーソル A–B）＋選択数フッターを追加。
- **UX-43**: 信号プレビュー窓に軸ラベル（Time (s)・信号名[unit]）を付与。

3 パートは独立（別ダイアログ）だが、「入口と出口の安全化」として 1 増分にまとめる。

## ユーザー決定（確定）

1. **CSV 列番号 = 0 始まり「0: t」表記**（既存の 0 始まりスピン/検出器内部モデルと一致・core セマンティクス非侵入・最小変更で off-by-one 解消）。
2. **エクスポート既定範囲 = 全期間**（現行と同じ全データ出力・データ欠落の驚きなし）。
3. 見た目はモックアップ（2026-07-23・チャット提示）で承認済み。

## §1 安全な CSV 取込（UX-05）

### 現状（根本原因）
`CsvFormatDialog._refresh()`（[csv_format_dialog.py:109-122](../../../src/valisync/gui/views/csv_format_dialog.py)）はプレビュー
`QTableWidget` を `setColumnCount(n)` のみで埋め、**`setHorizontalHeaderLabels` を呼ばない** → Qt 既定の
**1 始まり**ヘッダを表示。一方、列指定スピン `_ts_col`/`_sig_start`/`_sig_end`（[:63-81](../../../src/valisync/gui/views/csv_format_dialog.py)）は
**0 始まり**（`DetectedFormat.*_column` は 0 始まり列インデックス・`row[col]` 添字用途）。表示（1..）と入力（0..）が 1 ずれる。

### 変更
1. **0 始まりヘッダ**: `_refresh()` で `setHorizontalHeaderLabels(["0: <名前>", "1: <名前>", …])` を設定。
   - `<名前>` はヘッダ行がある場合その列名（プレビュー先頭行から）・ない場合は番号のみ「0」「1」…。
   - 0 始まりでスピンと一致 → off-by-one を**構造解消**（番号の読み替え自体を不要にする）。
2. **列ハイライト（スピン連動・ライブ）**: プレビュー該当列セルの背景を面色ハイライト:
   - **時間列**（`_ts_col` の値）= `chrome_cursor_a` トークンの**半透明ティント**。
   - **信号列**（`_sig_start`..`_sig_end` の範囲）= `drop_highlight` トークンの半透明ティント。
   - 実装: `_refresh()` で `QTableWidgetItem.setBackground(QColor(...))`。トークン色から低 alpha（例 α≈55/255・test-lock）の `QColor` を導出（**新トークンなし**・既存 `chrome_cursor_a`/`drop_highlight` は両テーマで解決可）。ヘッダセルも同系色文字（`setForeground`）で対応列を示す。
   - **ライブ連動**: 3 スピンの `valueChanged` を `_refresh()`（または軽量な再着色関数）へ接続し、スピン変更で即時に色が追従。
3. core（`CsvFormatDetector`/`DetectedFormat`/`FormatDefinition`）は**非改変**（0 始まり内部モデルのまま）。

### 範囲外・エッジ
- `_sig_start > _sig_end` の逆転や範囲外は既存のバリデーション挙動を維持（着色は交差する有効列のみ）。
- ヘッダ行なし（`header_row` が該当しない）の CSV は列名なしで番号のみ表示。

## §2 範囲付きエクスポート（UX-28）

### 現状
`CsvExportOptions`（[csv_exporter.py:18-31](../../../src/valisync/core/export/csv_exporter.py)）は
`delimiter`/`decimal`/`unit_row`/`precision`/`header_names` のみ（**時間範囲フィールドなし**）。
`CsvExporter.export`（[:65-77](../../../src/valisync/core/export/csv_exporter.py)）・`_rows_unified_timeline`/`_rows_shared_timeline`
（[:92-133](../../../src/valisync/core/export/csv_exporter.py)）は**全行を書く**。ダイアログに範囲 UI も選択数フッターもなし。

### 変更（core）
`CsvExportOptions` に **`time_start: float | None`・`time_end: float | None`**（既定 None=無制限）を追加。
`_rows_unified_timeline`/`_rows_shared_timeline` の行ループで、行の時刻 `t` について
`(time_start is None or t >= time_start) and (time_end is None or t <= time_end)` を満たす行のみ出力。
- **統合タイムライン×範囲の順序**: 範囲フィルタは**タイムライン解決後**に適用（マルチレート MDF の shared-timeline
  mismatch は既存の loud-fail 仕様を維持 — 範囲は解決済み統一時間軸上で切る）。
- 端点は**閉区間** [start, end]（両端含む）。

### 変更（GUI: `ExportCsvDialog`）
- **出力範囲ラジオ**（`QRadioButton` 群・[export_csv_dialog.py:76-152](../../../src/valisync/gui/views/export_csv_dialog.py) の form へ追加）:
  - **[全期間]**（既定 checked）→ `time_start=time_end=None`。
  - **[現在の表示範囲]** → アクティブタブのアクティブパネルの現在 X 範囲（`GraphAreaVM.active_tab()` のアクティブ
    `GraphPanelVM` の x_range アクセサ）。X-sync によりタブ内で一意。
  - **[カーソル A–B]** → `GraphAreaVM.active_tab().cursor_state` の `min/max(cursor_t, cursor_t_b)`。
    ラベルに実範囲を併記（例「カーソル A–B（12.30 – 45.60 s）」）。**A/B 両設置でないとき disabled**
    （判定 `cursor_t is not None and cursor_t_b is not None`）。
- **選択数フッター**: 「N 信号を選択中」を `QLabel` で常時表示。ツリーのチェック変化で更新
  （既存 `_validate`（[:231-237](../../../src/valisync/gui/views/export_csv_dialog.py)）に更新を相乗り）。
- 範囲は `_current_options()` で `CsvExportOptions.time_start/time_end` へ注入。`ExportRequest`/`export_csv`
  呼び出し鎖は options 経由でそのまま通す。
- **依存注入**: 範囲取得のため `ExportCsvDialog.ask` の呼び出し側（`main_window.export_csv`）で
  現在の X 範囲・カーソル A–B をダイアログへ渡す（ダイアログは GraphAreaVM を直接握らない — View 分離）。

## §3 プレビューラベル（UX-43）

### 現状
`SignalPreviewWindow` の `preview_plot`（`pg.PlotWidget`・[signal_preview_window.py:37-46](../../../src/valisync/gui/views/signal_preview_window.py)）は
**軸ラベルなし**（曲線を描くのみ）。単位は VM `properties()`（[signal_preview_vm.py:76-115](../../../src/valisync/gui/viewmodels/signal_preview_vm.py)）に既存。

### 変更
`SignalPreviewWindow._render()` で:
- `preview_plot.setLabel("bottom", "Time (s)")`（時間単位は秒固定 — 統一時間軸の規約）。
- `preview_plot.setLabel("left", <信号名> [<unit>])`（unit があれば `名前 [unit]`・なければ `名前`）。
  信号名・unit は VM の `_signal()`/`properties()` から取得。
- ラベル色は既存プロット面のトークン（`text_secondary` 等）に従いテーマ両対応。

## §4 テスト（gui-test-plan 準拠）

### 変更種別
GUI ウィジェット状態（ダイアログ・ハイライト・ラベル）＋ core 純ロジック（範囲フィルタ）＋描画（realgui スクショ）。

### Layer A（headless）
- **T-A1 範囲フィルタ**: `CsvExporter` に `time_start`/`time_end` を与え、出力行が閉区間 [start,end] のみ・
  None は無制限、を検証。**prod スケール（330k 相当）で行数削減の正しさ**（端点含む・範囲外除外の境界）。
- **T-A2 タイムライン×範囲**: 統合タイムライン解決後に範囲が適用されること（shared-timeline mismatch の
  loud-fail は範囲指定でも維持）。
- **T-A3 検出器非改変**: `CsvFormatDetector`/`DetectedFormat` の 0 始まり列インデックスが不変（回帰ガード）。

### Layer B（実イベント・ウィジェット）
- **T-B1 0 始まりヘッダ**: プレビュー `QTableWidget` の水平ヘッダが「0: …」「1: …」でスピン値と一致。
- **T-B2 列ハイライト連動**: 時間列スピンを変更 → 該当列セルの背景色が `chrome_cursor_a` ティントへ移動・
  旧列は非着色に戻る。信号列 `_sig_start`..`_sig_end` が `drop_highlight` ティント。**sabotage**: 着色を
  スピン値でなく固定列にする → RED。
- **T-B3 範囲ラジオ→options**: [全期間]→None/None・[表示範囲]→x_range・[カーソル A–B]→cursor min/max が
  `CsvExportOptions` に注入。A/B 未設置で [カーソル A–B] が disabled。
- **T-B4 選択数フッター**: チェック変化で「N 信号を選択中」が更新。
- **T-B5 プレビューラベル**: `preview_plot` の bottom ラベル=「Time (s)」・left ラベルに信号名＋[unit]。

### Layer C（realgui・①ゲート）
- **T-C1 取込ダイアログ実描画**: 実 CSV を開く → フォーマットダイアログで時間列/信号列スピンを実操作 →
  **0 始まりヘッダ＋列ハイライト（時間列 amber・信号列 teal）を実ピクセルで確認**（スクショ目視）。
- **T-C2 範囲エクスポート実ジャーニー**: 2 カーソル設置 → エクスポートダイアログで [カーソル A–B] 選択 →
  実出力ファイルの**行の時間範囲が A–B に収まる**ことを検証（実ファイル読み直し）。全期間との行数差も確認。
- **T-C3 プレビューラベル実描画**: 信号プレビューを開き軸ラベルをスクショ目視。

### ①証拠ゲート
`uv run pytest tests/realgui/ --realgui -q` フル＋T-C1/T-C2/T-C3 のスクショ/ファイル検証を merge 前に必須化。

## §5 凍結カタログ

CSV フォーマットダイアログ・エクスポートダイアログ・プレビュー窓の見た目が変わる。撮影カタログの該当状態
（`d01_export_dialog` 等・`--catalog` が撮る状態）を洗い出し、**per-state 期待差分**を確定:
- エクスポートダイアログ状態: 範囲ラジオ行＋選択数フッターの追加分が差分（他は不変）。
- CSV フォーマットダイアログ状態（撮っていれば）: ヘッダ 0 始まり＋列ハイライトが差分。
- プレビュー窓状態（撮っていれば）: 軸ラベル追加が差分。
- プロット面（viewport crop）は不変を `--crop-meta` で実証。
想定差分に限定されることを確認 → ベースライン昇格 → 再撮影 compare exit 0（両テーマ）＋決定性。

## §6 受け入れ基準

1. CSV フォーマットダイアログのプレビューヘッダが 0 始まりでスピン値と一致（off-by-one 消滅）。
2. 選んだ時間列/信号列がプレビューで色ハイライトされ、スピン変更で即追従。
3. エクスポートに [全期間/現在の表示範囲/カーソル A–B] ラジオ（既定=全期間）・A–B は両設置時のみ有効。
4. 範囲指定で出力ファイルの時間範囲が閉区間に収まる（prod スケールで行数削減が正しい）。
5. 「N 信号を選択中」フッターが常時・チェック連動で更新。
6. プレビュー窓に Time (s)・信号名[unit] の軸ラベル。
7. core（検出器・キー体系）非改変。full suite green・realgui フル＋T-C1/2/3・凍結 per-state 契約・決定性 exit 0。

## §7 敵対的レビューが攻撃すべき点（closure anchors）

- **0 始まり統一の完全性**: ヘッダは 0 始まりだがスピンの min/表示・検出器の受け渡し・`FormatDefinition` 変換の
  どこかに 1 始まりが残っていないか（off-by-one が別経路で復活しないか）。
- **列ハイライトのライブ性**: `valueChanged` 接続漏れで初回のみ着色しスピン変更に追従しない false-green。
  sabotage（固定列着色）が捕捉するか。逆転（start>end）・範囲外時の着色の頑健性。
- **範囲フィルタの境界**: 閉区間端点の含有・浮動小数境界・空範囲（start==end や範囲外で 0 行）の扱い。
  統合タイムライン解決との順序（解決前に切ると誤る）。
- **カーソル A–B の取得元**: `active_tab().cursor_state` を読むのは正しいタブか（複数タブ）。両設置ガードの
  判定（`delta_t` vs `cursor_t/cursor_t_b` 直読）。ダイアログが GraphAreaVM を直接握らず DI 経由か（View 分離）。
- **選択数フッターの同期**: フィルタ適用時・全選択/解除時・ファイル折りたたみ時にカウントが正しいか。
- **prod スケール**: 範囲フィルタが 330k で正しく行数を削るか（小データでは境界バグが隠れる）。
- **凍結カタログ**: 差分が想定ダイアログ領域に限定され、プロット面 viewport は不変か。
- **テーマ両対応**: ハイライトティント・ラベル色が LIGHT/DARK 双方で可読か（chrome_cursor_a は LIGHT で濃色）。
