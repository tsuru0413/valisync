# 増分 F-0「安全な取込・範囲付き出力・プレビューラベル」設計

> **出典**: UIUX 敵対的レビュー catalog 推奨6「入口と出口の再設計」の先行実施分（F-0）。
> [docs/uiux-adversarial-review-catalog.md](../../uiux-adversarial-review-catalog.md) の UX-05/UX-28/UX-43 を解く。
> F-1（.vsession セッション永続化）・F-2（Welcome 再開ハブ＋スナップショット共有）はユーザー決定で**今後検討へ defer**。
> ブランチ `feature/f0-safe-import-range-export`。
>
> **改訂履歴**: 初版を 8 レンズ敵対的レビュー（34 findings・29 confirmed）で検証し I1-I3（Important）＋Minor 18 を反映
> （座標系オフセット契約・x_range None ガード・LIGHT 可読性契約・:: 撤去維持・API 名訂正・DI 既定 None・文言集約）。

## Goal

「開く → 見る → 書き出す」ジャーニーの取込と出力を安全化する独立ダイアログ改修:
- **UX-05（🔴データ破損直結）**: CSV 取込ダイアログの列番号 off-by-one を構造解消（0 始まりヘッダ＋列ハイライト）。
- **UX-28**: エクスポートに出力範囲指定（全期間/表示範囲/カーソル A–B）＋選択数フッターを追加。
- **UX-43**: 信号プレビュー窓に軸ラベル（Time (s)・信号名 unit）を付与。

3 パートは独立（別ダイアログ）だが、「入口と出口の安全化」として 1 増分にまとめる。

## ユーザー決定（確定）

1. **CSV 列番号 = 0 始まり「0: t」表記**（既存の 0 始まりスピン/検出器内部モデルと一致・core 非侵入）。
2. **エクスポート既定範囲 = 全期間**（現行と同じ全データ出力）。
3. 見た目はモックアップ（2026-07-23・チャット提示）で承認済み。

## §1 安全な CSV 取込（UX-05）

### 現状（根本原因）
`CsvFormatDialog._refresh()`（[csv_format_dialog.py:109-122](../../../src/valisync/gui/views/csv_format_dialog.py)）はプレビュー
`QTableWidget` を `setColumnCount(n)` のみで埋め、**`setHorizontalHeaderLabels` を呼ばない** → Qt 既定の
**1 始まり**ヘッダを表示。列指定スピン `_ts_col`/`_sig_start`/`_sig_end`（[:63-81](../../../src/valisync/gui/views/csv_format_dialog.py)）は
**0 始まり**（`DetectedFormat.*_column` は 0 始まり列インデックス）。表示（1..）と入力（0..）が 1 ずれる。

### 変更1: 0 始まりヘッダ
`_refresh()` で `setHorizontalHeaderLabels` を設定。ラベルは列番号（0 始まり）＋任意の列名:
- 列名源は **`has_header`（`_header` チェックボックス）が True のときプレビュー先頭行 `rows[0]`**、False のとき列名なし。
  spec 中に `header_row` という識別子は使わない（実在しない — 制御は `has_header` ブールのみ・M）。
- **ragged 行ガード**（M）: `n_cols = max(len(r) for r in rows)` に対し `rows[0]` が短い場合があるので、
  `name = rows[0][ci] if (has_header and ci < len(rows[0])) else None`／
  `label = f"{ci}: {name}" if name else str(ci)`。列数が区切り再分割で動くときもラベルは列数に追従。
- 0 始まりでスピンと一致 → off-by-one を**構造解消**。core（`CsvFormatDetector`/`DetectedFormat`/`FormatDefinition`）は非改変。

### 変更2: 列ハイライト（面色・ライブ連動）
プレビュー該当列セルの背景を面色ハイライト:
- **時間列**（`_ts_col`）= `chrome_cursor_a` トークンの半透明ティント。
- **信号列**（`_sig_start`..`_sig_end`）= 信号ハイライトトークンの半透明ティント（§1.2 可読性契約）。
- **塗り優先（M）**: `FormatDefinition` は `ts_col ∈ [sig_start,sig_end]` を禁止する（[format_def.py:56-61](../../../src/valisync/core/loaders/format_def.py)）が、
  **スピン調整の過渡でこの重なりは必ず発生**する。信号範囲を先に塗り→時間列を後で塗る（`ts_col` 勝ち）と固定し、
  T-B2 で `ts_col ∈ 信号範囲` の過渡の期待色を pin。
- **ライブ配線（M）**: 着色は `_refresh()` 本体に含める。**3 スピン（`_ts_col`/`_sig_start`/`_sig_end`）の `valueChanged`
  に加え、`_header`（必要なら `_unit_row`）の `stateChanged` も `_refresh` へ接続**（現状は `_validate` のみ接続・
  [csv_format_dialog.py:96-98](../../../src/valisync/gui/views/csv_format_dialog.py)）。軽量再着色関数に分けると区切り変更→`_refresh` 全再構築で
  色が消える穴が残るため、経路を `_refresh` 一本に統一。接続を外すと RED になる sabotage Layer B で固定。

### §1.2 列ハイライトの可読性契約（I1）
`drop_highlight`（`#94e2d5` teal）は DARK/LIGHT で同一値を共有（[tokens.py:224](../../../src/valisync/gui/theme/tokens.py)）。LIGHT 明面
`chrome_base #e6e9ef` に α≈55 で合成するとほぼ判別不能・ヘッダ生ティール文字は明面で ≈1.22:1 で不可読。
- **契約**: 列ティントは**両テーマで非テキスト最低 3:1**（既存 `warning`/`info` トークンと同型の機械検証）。
  DARK は `drop_highlight` の低 α で満たす。**LIGHT で不足する場合は色相保持で暗くした LIGHT 専用の信号
  ハイライト値**を用意（`chrome_cursor_a` が LIGHT で `#8a6100` と濃色化されているのと同じ方針）。
- ヘッダ `setForeground` は AA/3:1 を担保できる色に限定するか、**背景ティントのみ**（文字色は既定）にする。
- 低 α 値・LIGHT 専用値は test-lock（両テーマ 3:1 の値ベース assert）。

## §2 範囲付きエクスポート（UX-28）

### 現状
`CsvExportOptions`（[csv_exporter.py:18-31](../../../src/valisync/core/export/csv_exporter.py)）は
`delimiter`/`decimal`/`unit_row`/`precision`/`header_names` のみ。`_rows_unified_timeline`/`_rows_shared_timeline`
（[:92-133](../../../src/valisync/core/export/csv_exporter.py)）は全行を書く。ダイアログに範囲 UI も選択数フッターもなし。

### §2.1 座標系契約（I2 — 最重要）
エクスポートは **base 信号の生タイムスタンプ座標**で書き出す（R14 時間オフセットは既存どおり**非適用**）。
範囲フィルタも**生座標**で行う。一方 `[現在の表示範囲]`/`[カーソル A–B]` の境界は**表示座標**（オフセット適用後）。
- **オフセットなし（既定・共通ケース）**: 表示座標=生座標なので境界をそのまま生座標として使える。
- **選択信号のいずれかに非ゼロオフセットがあるとき**: 単一の生時間窓へ写像できない（信号ごとにオフセットが
  異なりうる）ため、**表示由来の範囲ラジオ（現在の表示範囲・カーソル A–B）を disabled** にする
  （tooltip「オフセットをリセットすると範囲指定が使えます」）。`[全期間]` は常に有効。
  オフセット併用の範囲エクスポート（出力時刻もオフセット適用して表示座標で統一）は **follow-up** とする。
- 判定: 選択信号キー集合に対し `AppViewModel` の signal/file offset が非ゼロのものが1つでもあるか。

### §2.2 core（`CsvExportOptions` 拡張）
`time_start: float | None`・`time_end: float | None`（既定 None=無制限）を**dataclass 末尾に既定付きで追加**
（既存構築テスト後方互換）。`_rows_*` の行ループで行時刻 `t` について
`(time_start is None or t >= time_start) and (time_end is None or t <= time_end)`（**閉区間 [start,end]**）を満たす行のみ出力。
- **統合タイムライン×範囲の順序**: 範囲フィルタは**タイムライン解決後**に適用（shared-timeline mismatch の loud-fail は維持）。
- **窓外アンカー非包含（M）**: 描画は RN-01 で窓外1点ずつ含めて線分を引く（[graph_panel_vm.py:1045-1048](../../../src/valisync/gui/viewmodels/graph_panel_vm.py)）が、
  エクスポート閉区間は**窓内サンプルのみ**（時刻帰属で厳密に切る・RN-01 の窓外線形成サンプルは含めない）。
- **空範囲（M）**: `start > end` は `CsvExportOptions.__post_init__` で **ValueError**（loud-fail・core 堅牢化方針と同型）。
  範囲外で 0 行に一致する場合は**ヘッダ/単位行のみのファイル**（header-only）を by-design で出力（ヘッダは行ループ前に
  無条件生成・[csv_exporter.py:100/128](../../../src/valisync/core/export/csv_exporter.py)）。`start == end` は閉区間ゆえ境界サンプルを含みうる（必ずしも 0 行でない）。
- ヘッダ行・単位行は範囲フィルタの影響を受けず常に出力。

### §2.3 GUI（`ExportCsvDialog`）
- **出力範囲ラジオ**（`QRadioButton` 群・[export_csv_dialog.py:76-152](../../../src/valisync/gui/views/export_csv_dialog.py) の form へ追加）:
  - **[全期間]**（既定 checked）→ `time_start=time_end=None`。
  - **[現在の表示範囲]** → **アクティブパネルの `x_range` 属性**（`GraphAreaVM.active_tab().panels[active_panel_index]`
    の `GraphPanelVM.x_range`・[graph_panel_vm.py:204](../../../src/valisync/gui/viewmodels/graph_panel_vm.py)。API 名訂正: `active_tab()` は `_Tab` を返す・`x_range`
    は**メソッドでなく属性**）。**x_range が None のとき（初期・未プロット・reset_x 後）このラジオを disabled**
    （A–B と同型ガード・I3）。意味論: auto-fit の x_range は**アクティブパネルの可視プロット信号の和集合窓**であり、
    プロット外の選択信号は寄与しない窓へクリップされる（§6 に注記）。X-sync 有効時タブ内一様・**無効時はパネル固有**。
  - **[カーソル A–B]** → `active_tab().cursor_state` の `min/max(cursor_t, cursor_t_b)`。ラベルに実範囲併記
    （例「カーソル A–B（12.30 – 45.60 s）」）。**A/B 両設置でないとき disabled**（判定 `cursor_t is not None and
    cursor_t_b is not None`・`cursor_state` を唯一ソースとし B の None 化に依拠・マルチタブはアクティブタブ参照）。
  - §2.1 のオフセット条件でも表示由来2ラジオを disabled。
- **選択数フッター**: 「N 信号を選択中」を `QLabel` で常時表示。**N = 総選択数 `len(_checked_keys())`（フィルタ非依存・
  実エクスポート集合と一致）**。チェック変化・すべて選択/解除・フィルタ再構築で更新（`_validate`（[:231-237](../../../src/valisync/gui/views/export_csv_dialog.py)）相乗り）。
  - **すべて選択/解除のバッチ化（M）**: `_select_all`/`_select_none` は `blockSignals` でバッチ化し完了後に一度だけ
    再計算（per-child itemChanged→`_validate` O(n) カスケードを回避）。
- **DI（既定 None・後方互換）**: 範囲取得は `ExportCsvDialog.__init__`/`.ask` の**末尾に既定 None のキーワード引数**
  （x_range・cursor A/B・オフセット判定に必要な選択信号オフセット情報）として追加。注入なしでも `[全期間]` 既定で
  従来動作（撮影 [capture:216] と既存テスト約9箇所の直接構築が TypeError にならない）。ダイアログは `GraphAreaVM` を
  直接握らず、呼び出し側 `main_window.export_csv`（[main_window.py:713-739](../../../src/valisync/gui/views/main_window.py)）が現在の x_range・A/B・オフセットを
  スナップショットして渡す（View 分離・ダイアログ表示中は不変スナップショット）。範囲は `_current_options()` で
  `CsvExportOptions.time_start/time_end` へ注入し `ExportRequest`/`export_csv`/`ExportController` の鎖を options 経由で通す。

## §3 プレビューラベル（UX-43）

### 現状
`SignalPreviewWindow` の `preview_plot`（`pg.PlotWidget`・[signal_preview_window.py:37-46](../../../src/valisync/gui/views/signal_preview_window.py)）は軸ラベルなし。

### 変更
`SignalPreviewWindow._render()` で `preview_plot.setLabel(...)` を追加:
- bottom: `setLabel("bottom", "Time", units="s")`（**pyqtgraph 規約 `units=`**・本体プロットと統一・角括弧でなく丸括弧 SI 表示）。
  「Time」は D-1 判断点の意図的英語で据え置き。
- left: `setLabel("left", <display_name>, units=<unit or None>)`。
  - **名前は `display_names.display_name(sig.name)`（`::` を撤去した表示名・E-0/UX-19 維持）を使い、生キー
    `_signal().name`（`mf4_1::VehSpd`）を直接使わない**（M・windowTitle/properties「名前」行と同一規約）。
  - unit があれば `units=unit`・なければ省略（unit なし表示）。
- **公開アクセサ（M）**: `SignalPreviewVM` に `axis_label_parts() -> tuple[str, str | None]`（display_name, unit）を追加し
  window はそれを呼ぶ（`properties()` のローカライズ文言「単位」への文字列一致結合＝private `_signal()` 依存を避ける）。
- **ラベル色（M）**: `setLabel` に色を明示せず**本体プロットと同じ `plot_foreground`（#969696）を継承**
  （`text_secondary` はクローム/チップ専用でプロット面未使用のため指定しない）。

## §4 横断: 文言（strings.py 集約・M）
新規 UI 文言は `strings.py` に `Final` 定数として追加し D-1 表記規約（R-01..13）に従う（既存 `EXPORT_*` は集約済み）:
- 出力範囲ラベル・ラジオ3種（全期間/現在の表示範囲/カーソル A–B）・カーソル範囲併記テンプレ・フッター
  「{n} 信号を選択中」・オフセット時 disabled tooltip。
- `Time`（軸ラベル）は D-1 判断点の意図的英語で据え置き（整合）。
- docs/design.md 対訳表への追記要否を実装タスクで判断。

## §5 テスト（gui-test-plan 準拠）

### Layer A（headless）
- **T-A1 範囲フィルタ**: `time_start`/`time_end` で出力行が閉区間のみ・None 無制限。**prod スケール（330k 相当）で
  行数削減の正しさ**（端点含む・範囲外除外の境界・浮動小数境界）。
- **T-A2 タイムライン×範囲**: 統合タイムライン解決後に範囲適用（shared-timeline mismatch loud-fail 維持）。
- **T-A3 空範囲/検証**: `start > end` → `__post_init__` ValueError。範囲外 → header-only 出力。`start == end` の境界。
- **T-A4 検出器非改変**: `DetectedFormat` の 0 始まり列インデックス不変（回帰ガード）。
- **T-A5 座標系**: 選択信号にオフセットがあるときの範囲取り扱い（GUI disable は Layer B・core は生座標フィルタのみ）。

### Layer B（実イベント・ウィジェット）
- **T-B1 0 始まりヘッダ**: 水平ヘッダが「0: …」「1: …」でスピン値一致。ヘッダ ON/OFF トグルで名前部が追従（stale なし）。ragged 行。
- **T-B2 列ハイライト連動**: 時間列スピン変更 → 該当列 `chrome_cursor_a` ティント移動・旧列非着色。信号列 range ティント。
  `ts_col ∈ 信号範囲` の過渡で ts_col 勝ち。**sabotage**: 固定列着色 → RED。
- **T-B3 範囲ラジオ→options＋ガード**: [全期間]→None/None・[表示範囲]→x_range・[A–B]→cursor min/max 注入。
  **x_range None で [表示範囲] disabled・A/B 未設置で [A–B] disabled・選択信号オフセット時に表示由来2ラジオ disabled**。マルチタブ回帰。
- **T-B4 選択数フッター**: N=総選択数（フィルタ非依存）。選択済みをフィルタで隠してもフッター不変・フッター数==出力集合数。
- **T-B5 プレビューラベル**: bottom=「Time (s)」・left=display_name（`::` なし）＋unit・色は plot_foreground 継承。
- **T-B6 可読性（I1）**: 列ティント値が両テーマで非テキスト 3:1（値ベース機械検証・warning/info と同型）。

### Layer C（realgui・①ゲート）
- **T-C1 取込ダイアログ実描画**: 実 CSV → スピン実操作 → 0 始まりヘッダ＋列ハイライト（時間列 amber・信号列）を実ピクセル確認。
- **T-C2 範囲エクスポート実ジャーニー**: 2 カーソル設置 → [カーソル A–B] 選択 → **実出力ファイルの行の時間範囲が A–B に収まる**
  ことを実ファイル読み直しで検証。全期間との行数差も確認。
- **T-C3 プレビューラベル実描画**: プレビューを開き軸ラベルをスクショ目視。

### ①証拠ゲート
`uv run pytest tests/realgui/ --realgui -q` フル＋T-C1/T-C2/T-C3 の証拠を merge 前に必須化。

## §6 凍結カタログ

CSV フォーマットダイアログ・エクスポートダイアログ・プレビュー窓の見た目が変わる。
- **crop-meta のスコープ（M）**: `--crop-meta` は viewport.json を持つ main window 状態（02-05/09）のみ比較し F-0 変更状態
  （ダイアログ・プレビュー）は SKIP → 「main window プロット面への非波及証明」。ダイアログ/プレビュー差分は**フル画像比較**でカバー。
- **エクスポートダイアログ状態**: 範囲ラジオ3行＋選択数フッターが差分。撮影は **DI 新署名へ更新**し決定的カーソル
  （例 3.0/6.0）を注入して [カーソル A–B] enabled 状態＋実範囲ラベルを撮る（capture:216 の直接構築を更新）。
- **CSV フォーマットダイアログ状態**（撮っていれば）: ヘッダ 0 始まり＋列ハイライトが差分。
- **プレビュー窓状態 08**（撮っていれば）: 軸ラベル追加で**プロット領域が縮小し波形が窓全域で再配置**（データ不変・幾何のみ変化）。
  08 は viewport.json を持たないため、**preview_plot 用 viewport crop 相当**を用意して波形コンテンツ領域不変/データ同一性を機械検証。
- 想定差分に限定を確認 → ベースライン昇格 → 再撮影 compare exit 0（両テーマ）＋決定性。

## §7 受け入れ基準

1. CSV プレビューヘッダが 0 始まりでスピン値一致（off-by-one 消滅・ヘッダ ON/OFF・ragged で stale/crash なし）。
2. 選んだ時間列/信号列が色ハイライトされスピン変更で即追従（両テーマ 3:1）。
3. エクスポートに [全期間/現在の表示範囲/カーソル A–B] ラジオ（既定=全期間）。x_range None・A/B 未設置・**選択信号オフセット時**は該当ラジオ disabled。
4. 範囲指定で出力ファイルの時間範囲が閉区間に収まる（prod スケールで行数削減が正しい・生座標）。`start>end` は ValueError。
5. 「N 信号を選択中」が総選択数（フィルタ非依存）で常時更新。
6. プレビュー窓に Time (s)・display_name（`::` なし）＋unit の軸ラベル（色は plot_foreground 継承）。
7. core（検出器・キー体系・オフセット非適用のエクスポート既定）非改変。新規文言は strings.py 集約。
   full suite green・realgui フル＋T-C1/2/3・凍結 per-state 契約・決定性 exit 0。

## §8 敵対的レビューが攻撃すべき点（closure anchors）

- **0 始まり統一の完全性**: スピン min/表示・検出器受け渡し・`FormatDefinition` 変換・ヘッダ ON/OFF 追従のどこかに
  1 始まり/stale が残らないか。ragged 行の IndexError。
- **列ハイライトのライブ性/可読性**: `valueChanged`＋`stateChanged` 接続漏れの false-green（sabotage で捕捉）。
  LIGHT 明面での信号ティント/文字の 3:1（drop_highlight 側の埋没を値ベースで実証）。ts_col∈信号範囲の塗り優先。
- **座標系（I2）**: オフセット有効信号を含む範囲エクスポートが生座標で誤行抽出しないか。GUI disable が実効か。
- **範囲フィルタの境界**: 閉区間端点・浮動小数境界・空範囲（start>end→ValueError・範囲外→header-only）・タイムライン解決順。
- **x_range None（I3）**: [表示範囲] が None で crash/無言 fallback しないか（disabled ガード）。auto-fit 窓の意味論。
- **カーソル A–B**: 正しいアクティブタブか・両設置ガード・DI View 分離・スナップショット性。
- **選択数フッター**: フィルタ非表示の選択済みを含む総選択数か・出力集合と一致・すべて選択のバッチ化。
- **:: 撤去維持（§3）**: 軸ラベルが display_name で生キーを露出しないか（E-0 回帰）。
- **DI 後方互換**: 既定 None キーワード引数で撮影/既存テストが TypeError にならないか。
- **凍結カタログ**: crop-meta スコープ・プレビュー 08 の幾何変化とデータ不変・ダイアログ差分の想定限定。
