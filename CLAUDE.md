# CLAUDE.md

このファイルは **エントリポイント** — 詳細情報は別ファイルに分散し、ここではポインタと最小限の不変情報のみ保持する。本ファイルが肥大化してきたら積極的に `docs/` に分離する。

## 情報の探し方 (優先順位)

| 順位 | 場所 | 内容 |
|---|---|---|
| 1 | `docs/superpowers/specs/` ＋ `docs/superpowers/plans/` | 計画の一次情報源（brainstorming 設計 spec / writing-plans 実装プラン）— **新規作業はここ** |
| 2 | `docs/<topic>.md`（`product` / `development` / `structure` / `policies` / `workflow` / `gui-testing-layers`） | プロダクト・技術/品質ゲート・構造・方針・開発フロー・GUI テスト |
| 3 | `.kiro/specs/<spec>/{requirements,design,tasks}.md` | **完了済み Phase 1/2 のアーカイブ**（歴史・トレーサビリティ。新規には使わない） |
| 4 | このファイル | 上記で発見できないハマりどころと方針概要 |

**ルール**: `docs/` または `.kiro/specs/`（アーカイブ）で確認可能な情報は本ファイルに重複させず、ポインタで繋ぐ。コードを読めば自明な事実 (ファイル名・関数シグネチャ等) も本ファイルには書かない。

## プロジェクト概要

ADAS ソフトウェア開発向けの時系列信号データ統合・同期・解析デスクトップ GUI アプリケーション。CAN・XCP・Ethernet・CSV フォーマットの信号を統一時間軸上で可視化・分析する。

詳細: `docs/product.md`

## リポジトリ

- **Remote**: `git@github.com:tsuru0413/valisync.git`
- **CI**: GitHub Actions (push to main / 全 PR で品質ゲート自動実行)

## 開発ワークフロー (superpowers 駆動)

詳細: `docs/workflow.md`

- **計画は superpowers** — `brainstorming`（設計 spec）→ `writing-plans`（実装プラン）→ `executing-plans` / `subagent-driven-development`（消化）→ `finishing-a-development-branch`。設計 spec は `docs/superpowers/specs/`、プランは `docs/superpowers/plans/`。
- CLAUDE.md はエントリポイント (薄く保つ)。詳細は `docs/` に分散、完了済み spec は `.kiro/specs/`（アーカイブ）。

## ブランチ運用 (常時適用)

詳細: `docs/workflow.md`

- **main は本番ブランチ** — 直接編集は禁止 (緊急 hotfix を除く)
- **新機能・修正は `feature/<topic>` ブランチで実装**
- **フロー**: feature ブランチで実装 → ローカル品質ゲート通過 → push → `gh pr create` → CI 通過 → `gh pr merge --auto` → `git fetch --prune`
- **着手時**: 新規作業は brainstorming から始め、feature ブランチを切って実装する

## Phase 状況

| Phase | スコープ | 状況 | 一次情報源（`.kiro/specs` はアーカイブ） |
|---|---|---|---|
| Phase 1 / valisync-core | Signal・Loader・Sync・Formula・補間・統計・Downsampler・Export・Session | 完了 (PR #2 merged) | `.kiro/specs/valisync-core/` |
| Phase 2 / valisync-gui-mvp | GUI 歩く骨格: シェル/ドッキング・データ取込/閲覧・タブ/パネル・Y-T 波形・X/Y ズーム/パン・動的 LOD・X 軸同期・D&D・コンテキストメニュー | 完了 (PR #2 merged) | `.kiro/specs/valisync-gui-mvp/` |
| Phase 2 / valisync-gui-file-browser | FileBrowser の分離: 読み込み済みファイルリストと選択ファイルごとの信号フラットリスト表示 | 完了 (PR #3 merged) — 詳細は [docs/file-browser-spec-revision-followup.md](docs/file-browser-spec-revision-followup.md) | `.kiro/specs/valisync-gui-file-browser/` |
| Phase 2 / valisync-gui-axes | 複数Y軸レイアウト: リージョンベースのオーバーレイ・Auto-Fit 縮尺・複数列グリッド配置 | R1–R6 完了（PR #4/#13/#14/#16/#17 merged）— 詳細は [docs/multi-axis-multicolumn-followup.md](docs/multi-axis-multicolumn-followup.md)・[docs/multi-axis-empty-region-followup.md](docs/multi-axis-empty-region-followup.md)、設計/プランは `docs/superpowers/specs/`・`docs/superpowers/plans/`。軸ごとリサイズ＋アクティブ軸統一操作モデル（グリップ=リサイズ/フレーム=移動/内側=ズーム/外側=パンをアクティブ軸のみ受付、連動ディバイダー廃止）を PR #19 で実装（realgui 9本、実装メモは設計 doc §14）— [docs/superpowers/specs/2026-06-28-y-axis-per-axis-resize-active-model-design.md](docs/superpowers/specs/2026-06-28-y-axis-per-axis-resize-active-model-design.md) | `.kiro/specs/valisync-gui-axes/`（archive）＋ `docs/superpowers/` |
| Phase 2 / valisync-gui-analysis | カーソル計測・範囲統計・時間オフセット（親 R14–R17）。R15 Global Cursor: プロット内クリックで全パネル同期カーソル設置・補間値読み取り・補間方式切替・線ドラッグ移動、補間値フロート表（`CursorReadout`）で既存凡例を置換 | **R14–R17 完了（全 PR merged・realgui ①ゲート充足）**。増分A=R15 Global Cursor（PR #21/#22、realgui 2/2＋軸操作 8/8 無回帰）／増分B=R16 Delta+R17 範囲統計（PR #23、realgui カーソル A/B 線ドラッグ pass）／増分C=R14 時間オフセット（PR #25）— realgui ①ゲートで実経路バグ2件（grabMouse 未使用で押下中 move 不達／`_finish_offset` の reset 順序）を検出し TDD 修正、headless 612・realgui 6/6（memory: `gui_realgui_move_not_reaching_parent_qwidget`） | 設計: [design](docs/superpowers/specs/2026-06-29-gui-analysis-cursor-offset-design.md)・プラン: [r15-plan](docs/superpowers/plans/2026-06-29-gui-analysis-r15-global-cursor.md)・[r14-plan](docs/superpowers/plans/2026-06-29-gui-analysis-r14-time-offset.md)・[r16-r17-plan](docs/superpowers/plans/2026-06-29-gui-analysis-r16-r17-delta-stats.md) |

| 横断 / realgui カバレッジ拡充 | headless が構造的に false-green を出す経路を実 OS 入力（Layer C）で検証。監査で realgui 必須 39・covered 16・missing 23 を特定し high クラスタから充足 | **Phase 1-7 実装完了（low クラスタ＋C3 昇格で全 missing 解消・merge 前 ①ゲートで実機実証）**。P1 共有ヘルパ `_realgui_input`/`drive_qdrag`（PR #27）／P2 コンテナメニュー3経路 H5-H7（ChannelBrowser/DataExplorer CustomContextMenu 化＋GraphPanel setMenuEnabled、PR #28）／P3 信号 D&D 実配送 H1-H4（クロスウィジェット QDrag、PR #29）／P4 click_to_activate_axis H8（純クリック活性化、PR #30）。付随: id() フレーク修正 #31（memory `gui_id_reuse_flake_object_recreation`）。P7 low: DataExplorer ドロップ・ドロップ青枠・非アクティブ軸 hover・grip 記録・C3 昇格（Plan 7 実装）。**残存（別計画）**: P5 クロスパネル軸移動（新機能）・C1 dock 復元（Layer A） | 監査 [docs/realgui-coverage-audit.md](docs/realgui-coverage-audit.md)・設計 [spec](docs/superpowers/specs/2026-06-30-realgui-coverage-expansion-design.md)・プラン `docs/superpowers/plans/2026-06-30-realgui-plan{1-4}-*.md` |

> Phase 2 `valisync-gui` は sub-spec に分解済み（mvp / file-browser / axes / **analysis（R14–R17 完了・realgui ①ゲート充足）** 完了、未着手: derived / views / script）。realgui カバレッジ拡充（横断）は Phase 1-7 実装完了（low クラスタ＋C3 昇格で全 missing 解消・merge 前 ①ゲートで実機実証）。詳細は `docs/roadmap.md`。
>
> **改善サブスペック（バケット② 実装済みだが不足）**: 実ユーザージャーニー監査（開く→表示→解析）で確定した 64 課題（補遺 LD-12/LD-13 で計 66 課題）を、`gui-feedback-errors` / `gui-shell-controls` / `gui-plot-analysis-controls` / `core-loaders-hardening` / `analysis-correctness` / `rendering-correctness-perf` の6サブスペックに割当。一次情報源は [docs/audit-findings-catalog.md](docs/audit-findings-catalog.md)（ID 付き・file:line・優先度）、俯瞰は `docs/roadmap.md`。着手起点の `gui-feedback-errors` は**完了 — 第1弾（FB-01/02/03/06・PR #37）＋第2弾（FB-04/05/07/08/09/10＝ハイブリッドキャンセル・ヘッダ/タイトル/プレースホルダ/ツールチップ・PR #38）で全10課題解消**。`gui-shell-controls` は**増分1（File I/O 導線）完結 — 1a（入口: SH-01/07・Open/Ctrl+O/Welcome 空状態 CTA/Recent MRU/ShellActions QAction レジストリ/QStackedWidget 化・PR #51）＋1b（出口: SH-03・`ExportCsvDialog`＝ファイル別信号ツリー/初期選択=プロット中/フルオプション・`CsvExportOptions` で csv_exporter 拡張・`ExportController` オフスレッド・File>Export/Ctrl+E/ツールバー・PR #52）。subagent-driven のレビューで実バグ2件を捕捉修正: worker 未保持で queued signal 消失→overlay ハング（memory [[gui_qrunnable_signals_lifetime_retention]]）・マルチレート MDF の shared-timeline 既定 unchecked で無言破損→統合TL 既定ON＋mismatch で ValueError**。**増分2（タブ/パネル・データソース管理）完結 — 2a（タブ: SH-02/04/13・コーナー「+」/Ctrl+T・closable・ダブルクリック改名・PR #53）＋2b（SH-06 パネル可視ボタン overlay・SH-08 削除確認ダイアログ＋閉じる導線・SH-10/15 DataExplorer ソース一覧 QListWidget/選択作用 Remove・PR #54）。subagent-driven のレビューで実バグ2件を捕捉修正: 2a=タブ改名の二重発火（hide() の同期 focusOut 再入で rename_tab が確定ごと2回→`_finish_rename` 先頭ガードで単発化）・2b=パネル chrome 行が plot を 27px 下げ hit-test 座標系を破壊（曲線グラブ/ゾーン/ホバーずれ・headless zone テストは viewport 空間 target で自己整合的に見逃す false-green を opus whole-branch review が計測実証→chrome overlay 化＋honest-RED、memory [[gui_panel_chrome_layout_row_shifts_hittest_origin]]）。**増分3（シェル chrome: SH-05 ショートカット/mnemonic・SH-12 ドックトグルのツールバー化・SH-11 Reset Layout・SH-14 アイコン/バージョン）完結で gui-shell-controls 全 SH 完結（PR #56）。opus whole-branch review で Exit ショートカット false-green（`StandardKey.Quit` は Windows で押せない `Key_Exit`・テストも tautology）を検出し `Ctrl+Q`＋honest テストへ是正。ユーザー指摘で realgui スケルトンが合成 `qtbot.mouseClick`＋`trigger()` の Layer C 偽装（実ディスプレイに何も映らない）だったと判明→`_realgui_input.at()` 実 OS 入力＋スクショ AI 判定へ書換・QSettings 隔離を `tests/realgui/conftest.py` へ横展開（memory [[gui_realgui_synthetic_click_mislabeled_layer_c]]）。再発防止に Layer C 契約ガード `tests/gui/test_realgui_layer_c_contract.py`（合成 realgui を CI で落とす）を追加。**さらに既存合成4つ open/export/tab_ui/panel_source_flow を実 OS 入力へ移行し allowlist を空にして完全厳格化**（Ctrl+O/E は実クリック前面化＋実キー・タブ改名は実ダブルクリック〔`GetDoubleClickTime` 窓内2連打＋event loop pump〕＋実タイピング・ソース選択/コーナー+ は実クリック。スクショ AI 判定 pass・memory [[gui_realgui_synthetic_click_mislabeled_layer_c]]）。設計 [spec](docs/superpowers/specs/2026-07-07-gui-shell-controls-design.md)・プラン `docs/superpowers/plans/2026-07-08-gui-shell-controls-r{1a,1b,2a,2b,3}-*.md`。`core-loaders-hardening` は**第1弾（TS 堅牢化＝記録どおり保持＋整列ビュー・LD-03/04/05/06/08/09・PR #39）＋第3弾（LD-07/10/12/13 解消・LD-11 仕様判断・PR #43）＋LD-14（ndim≥3 多段フラット展開 `Name[i][j]`＋per-channel 1024 列ガード＝超過は GUI ポップアップで展開/スキップ選択・ヘッドレスは全スキップ、[spec](docs/superpowers/specs/2026-07-05-ld14-ndim-flatten-design.md)/[plan](docs/superpowers/plans/2026-07-05-ld14-ndim-flatten.md)）実装済み＋第2弾（開く経路＝LD-01 CSV 自動検出 `CsvFormatDetector`＋確認ダイアログ `CsvFormatDialog`・LD-02 `.mdf/.dat` 受理＋`Mdf4Loader`→`MdfLoader` リネーム置換、[spec](docs/superpowers/specs/2026-07-05-core-loaders-hardening-r2-open-path-design.md)/[plan](docs/superpowers/plans/2026-07-05-core-loaders-r2-open-path.md)）で**全 LD-01〜14 解消（完了）**。`analysis-correctness` は**完了 — AN-01/02/03 を `Signal.finite_view()`（非有限値を除いた時系列ビュー）共通土台で解消**（AN-01 範囲統計を有限のみ集計・AN-02 補間で NaN 欠測除外・AN-03 単一サンプル ZOH 前方保持、[spec](docs/superpowers/specs/2026-07-05-analysis-correctness-design.md)/[plan](docs/superpowers/plans/2026-07-05-analysis-correctness.md)）。`rendering-correctness-perf` は**RN-01/RN-02（描画の正しさ）＋RN-06（カーソル移動 perf）解消済み**（RN-01 X 窓スライスに境界サンプル取込で疎信号のズーム消失を解消・RN-02 `_x_range_is_auto` で自動フィット中は追加信号で和集合拡張、[spec](docs/superpowers/specs/2026-07-05-rendering-correctness-design.md)/[plan](docs/superpowers/plans/2026-07-05-rendering-correctness.md)）、**RN-03/04/05 も解消し RN-01〜06 全解消＝サブスペック完結**（増分1: RN-03 リサイズ幅ガード＋RN-05 定数信号 Y 軸零幅パディング〔`_padded_range` 中心対称拡張・手動 set_y_range 非 pad〕・PR #72／増分2: RN-04 ダウンサンプラのベクトル化〔`_minmax_indices`＝`reduceat` で min/max first-hit・狭窓 ~53×・既存 test_downsampler/PBT で出力不変実証〕＋`set_x_range` 不変ガードで X-sync 扇状展開の冗長 render 除去・PR #73。RN-04 計測で根本原因がダウンサンプラのバケット毎 Python ループと判明し方針転換。±inf は描画不能〔pyqtgraph が非有限頂点破棄・Y auto-fit は finite のみ、[[pyqtgraph_drops_non_finite_vertices]]〕のため LOD 選択から意図的除外を設計判断〔旧 nanargmin/nanargmax からの deliberate divergence・test-lock〕、[r1-spec](docs/superpowers/specs/2026-07-10-rendering-perf-r1-resize-yaxis-design.md)・[r2-spec](docs/superpowers/specs/2026-07-10-rendering-perf-r2-downsampler-vectorize-design.md)）。加えて**ユーザー実機発見のカーソル UX クラスタを2増分で完了**。**増分①（PC-21/RN-06・PR #49 draft）**— PC-21=CursorReadout をプロット矩形へ追従再配置（ドラッグ位置尊重）・RN-06=範囲統計を平方分割 O(√n) 化（`RangeStatIndex`・並列分散マージで数値安定・191ms→<1ms、memory `range_stats_sqrt_decomp_parallel_variance`）＋readout 差分更新、[spec](docs/superpowers/specs/2026-07-05-cursor-readout-perf-design.md)/[plan](docs/superpowers/plans/2026-07-05-cursor-readout-perf.md)。**増分②（PC-22/PC-13/PC-14・PR #50 draft・①にスタック）**=軸ゾーン別ポインタ形状。カーソルレジストリ `gui/views/cursor_shapes.py`（`CursorKind` 純関数＋`cursor()` 遅延キャッシュ・カスタム QCursor(QPixmap) ズーム）で X inner=zoom（BitmapCursor）/outer=pan（SizeHor）区別・Y は縦カスタムで統一・非アクティブ軸は PointingHand・カーソル線と曲線ホバーに SizeHor（オフセット affordance）。アドバーサリアルレビューで挙動変更に追随しない stale な Layer C カーソル assert 2件を検出・修正（memory `gui_behavior_change_stale_parallel_realgui_test`）、[spec](docs/superpowers/specs/2026-07-05-cursor-axis-pointer-shapes-design.md)/[plan](docs/superpowers/plans/2026-07-05-cursor-axis-pointer-shapes.md)。`gui-plot-analysis-controls` は**増分1（アクティブパネル＋載せる入口・PC-07/02/04）完結（PR #59）** — 統一「アクティブ＋右クリック」操作モデルの土台。`GraphAreaVM.active_panel_index`（タブごと・作った=使う自動アクティブ＋remove clamp）／パネル左クリック・軸クリックで `activate_requested`→`VM.set_active_panel`（軸クリックは scene アイテムが accept して親に届かないため軸経路が唯一の活性化・両経路は VM no-op で冪等）／アクティブ枠 overlay（原点(0,0)維持で hit-test 非破壊＝[[gui_panel_chrome_layout_row_shifts_hittest_origin]] の教訓を踏襲）／Add・Export の `panels[0]` 固定をアクティブ配送へ根治／ChannelBrowser 追加ボタン＋ダブルクリック/Enter（Windows activated-on-Enter 二重発火ガード）。realgui 22/22（実 OS 入力＋スクショ目視）＋opus 最終ブランチレビュー Ready-to-merge（Critical/Important 0・Minor 3件は follow-up commit で取込）。**増分2a（entry_id 基盤＋曲線の直接操作・PC-01/PC-05）完結（PR #61）** — 曲線を entry_id（VM 採番の単調増分・VM 内一意）で識別し直接操作。View 内部辞書と公開アクセサを entry_id 全面移行（`curve_keys`/`curve_xy`/`pen_color`/`is_clipped`/`pen_width`＋signal_key 解決 `entry_id_for`/`signal_keys_drawn`・型変更が entry_id↔signal_key 混同を KeyError で loud-fail 化）／entry 単位 VM API（`toggle_entry_visibility`/`set_color`/`remove_entry`/`toggle_axis_visibility`）／曲線クリック活性化（太線化・軸連動・解除規則）＋DP16 ジェスチャ（press 候補＋grabMouse-at-press・閾値超え=オフセット/閾値内=活性化）／H キー（曲線→軸フォールバック・非解除）／右クリック曲線メニュー（非表示/色変更▸/削除・色ダイアログ DI・ルーティング骨格）／死蔵可視性コード削除（PC-05 吸収）。クロスパネル軸移動で entry_id を移動先 VM の採番へ再振り（VM 内一意保証・レビューで実バグ捕捉）。realgui 新規4＋既存移行16本（実 OS 入力・memory [[gui_pyside_qaction_submenu_shiboken_lifetime]]）＋opus 最終 whole-branch レビュー Ready-to-merge（Critical/Important 0・繰越 Minor は全て後回し可・follow-up 推奨は T4-c 軸クリック解除の Layer B テストのみ）。**増分2b（軸/曲線メニュー＋オフセット導線・PC-06/PC-03）完結（PR #63）** — Y軸右クリックメニュー `build_axis_menu`（オートフィット/範囲指定/削除/曲線一覧チェック式）＋`contextMenuEvent` 軸分岐（曲線→Y軸→空白・zone-gate で `_axis_index_at` の 0-fallback 回避）／VM 軸構造 API（`reset_axis_y`/`remove_axis`/`entries_on_axis`/`move_entry_to_new_axis`〔cache-key に axis_index 非包含のため `_invalidate_cache` 必須をサボタージュ検証〕）／曲線メニュー拡張（新しい軸へ移動・時間オフセット…数値ダイアログ・オフセットをリセット…・`オフセット: +Xs` 情報行〔固定小数 `:+.3f`〕）／`AppViewModel.reset_offset`（`apply_offset` 対称・既存 `'offsets'` ブロードキャスト相乗りで GraphPanelVM に reset 専用増設なし）／T4-c 軸クリック解除を `mouseClickEvent` 実駆動で Layer B カバー。全ダイアログ DI 注入。realgui 新規3＋無回帰7（実 Win32 OS 入力＋数値シフト assert・memory [[gui_realgui_offscreen_target_opens_os_system_menu]]）＋opus 最終 whole-branch レビュー Ready-to-merge（Critical/Important 0）。**増分3a（カーソル操作＋補間可視化・PC-08/PC-09）完結（PR #65）** — `GraphPanelVM.step_cursor`（表示〔オフセット適用〕軸の隣接サンプルへスナップ・端 clamp・基準 entry フォールバック・`searchsorted` side=fwd:right/bwd:left−1）／アクティブカーソル(A/B) クリック・ドラッグ活性化＋設置直後自動アクティブ＋アクティブ線太線化（再入 notify で誤って B へ活性が奪われない edge-detection・ドラッグ活性化は `set_cursor` の前に設定）／←/→ キーで `step_cursor` 配送（`_active_cursor or "A"`・基準 `_active_curve_id`・カーソル未設置は素通し）／カーソル線右クリック `build_cursor_menu`（時刻を指定…数値ダイアログ DI／消去 A=全消去・B=Δのみ）＋`contextMenuEvent` ルーティング先頭にカーソル分岐（カーソル→曲線→Y軸→空白・`_cursor_line_at` 切出で `_curve_at` ガードを DRY 化＝挙動厳密保存）／補間方式を `QActionGroup(exclusive)` 排他 radio 化＋現在値 checked＋readout ヘッダに現在方式を常時表示（memory [[gui_qactiongroup_exclusive_radio_menu]]）。realgui 新規2（実 `keybd_event` ←/→ でサンプル移動＋実右クリックメニュー「カーソルを消す」・honest-RED 実証・`VK_LEFT/VK_RIGHT` を共有 `_realgui_input` 追加）＋無回帰＋opus 最終 whole-branch レビュー Ready-to-merge（Critical/Important 0・繰越 Minor は全て 3b/後続へ defer、特に `CursorReadout._last_delta` の interp_label 欠落 [[followup_readout_last_delta_interp_label]]）。**増分3b（readout 刷新・PC-10/11/12/16/17/18）完結（PR #67）** — CursorReadout を刷新。VM `value_precision`（既定6・4/6/8）＋readings へ `sig.metadata` 単位注入／散在フォーマッタを精度パラメータ付き単一化（値・統計列のみ・count は整数・時刻ヘッダは固定 `.4g`）／名前脇 `[unit]` 淡色（DP8）／rows 4-tuple 化＋`_layout_sig` に unit 包含で unit 変化時の name ラベル stale 回避（memory [[gui_diff_update_layout_key_must_cover_unrewritten_fields]]）／`_last_delta` 5-tuple 化で **3a 繰越 followup（legacy stat-toggle 再描画で interp_label 欠落）を解消**／構造化 TSV `table_tsv()`（表示中の列/精度/単位反映）／常時 ✕（クリック=`toggle_main_cursor(False)` 全消去）＋移動アフォーダンス＋サブカーソル項目 disabled ツールチップ（`setToolTipsVisible(True)` 併設）／右クリック `build_readout_menu`（統計列 ▸＝既存 `build_column_menu` 再利用・精度 ▸＝`QActionGroup` 排他・表をコピー→clipboard・カーソルを消す）＋`contextMenuEvent` override。精度/クリア/統計列は View 経由 callback（CursorReadout は core 非依存）。realgui 新規2（実 ✕ クリック→消去・実右クリック→メニュー→「表をコピー」→clipboard・実ディスプレイ）＋既存カーソル realgui 無回帰＋opus 最終 whole-branch レビュー Ready-to-merge（Critical/Important 0・繰越 Minor は RichText 未エスケープ/メニュー蓄積/コメント表記/精度不変ガードテストで全て後続 defer）。**増分4（グリッド PC-15/チャンネルツールチップ PC-19/列ソート PC-20）完結（PR #69）で gui-plot-analysis-controls 全 PC 完結＝サブスペック完結** — PC-15 グリッド（`GraphPanelVM.grid_enabled` パネルごと transient・`_x_axis.setGrid` で X 方向縦線のみ〔Y 軸は非対象〕・空白部メニュー checkable「グリッド」・直接トグル/構造リビルド/fast-path の全経路で一貫）／PC-19 遅延リッチツールチップ（`ChannelBrowserVM.tooltip_for` を ToolTipRole hover 時に構築〔`signals` で事前計算しない〕・単位/サンプル数〔記録どおり `len(timestamps)`〕/由来/コメント/value_labels・欠損行省略・時間範囲なし・`SignalItem.tooltip` 撤去）／PC-20 列ソート（`QSortFilterProxyModel` ソート専用〔accept-all・`sortByColumn(-1)` パススルー既定〕・フィルタは VM 真実のまま・選択/D&D は `mapToSource` で源解決〔ソート後も見た目どおりの信号〕・ケース非依存 fold-in で混在ケース ADAS 名〔`EngineSpeed`/`vehSpd`〕を A–Z 連続化）。realgui はグリッド実描画スクショ目視＋実 D&D 無回帰、proxy 挿入で `tree.visualRect(源 index)` が空 QRect になる fallout を realgui 3ファイルで修正（memory [[gui_qsortfilterproxy_visualrect_source_index_empty_rect]]）。各タスク subagent-driven の2軸レビュー＋opus 最終 whole-branch レビュー Ready-to-merge（Critical/Important 0）。設計 [spec](docs/superpowers/specs/2026-07-09-gui-plot-analysis-controls-design.md)・プラン `docs/superpowers/plans/2026-07-09-plotctl-r{1,2a,2b,3a,3b,4}-*.md`。

新規実装は **writing-plans のプラン（`docs/superpowers/plans/`）に従い番号順 / 依存グラフ順** に進める。完了済み Phase 1/2 の `.kiro/specs/*/tasks.md` はアーカイブ（編集しない）。

## プロジェクト方針 (要約)

詳細: `docs/policies.md`

- **修正案は症状の隠蔽/緩和/根本解決を明示** — 根本解決を優先
- **リポジトリ構造はその都度最適化** — 責務分割のため新規ファイル/ディレクトリ作成を躊躇しない
- **CLAUDE.md はタスクごとに熟成** — 追記候補をユーザーに確認、肥大したら分離

## 主要コマンド (品質ゲート)

```bash
uv sync --extra dev          # 初回または依存変更後
uv run pytest                # 全テスト
uv run ruff check            # lint
uv run ruff format           # format
uv run mypy src/             # 型チェック
```

コミット前に上記全てを通すのが本プロジェクトの品質ゲート。詳細は `docs/development.md` を参照。

GUI 機能・操作を実装するときは **GUI テストレイヤー（Layer A/B 必須・CI / Layer C はローカル `--realgui`）** に従う。詳細: `docs/gui-testing-layers.md`（`docs/workflow.md` の計画・実装フローで必須化）。計画時は `/gui-test-plan`（②実質的な受け入れ要件の設計）、merge 前は `/gui-verify`（①realgui 証拠ゲート）を使う。

## 実機確認用デモデータ (本番相当 mf4)

本番（ADAS HILS・CANape 計測・XCP/CAN/Ethernet 統合）相当の mf4 を生成するツール: `scripts/generate_demo_mf4.py`（`uv run python scripts/generate_demo_mf4.py --profile {hils≈2GB / quick≈170MB / smoke=CI用}`）。プロファイル・シナリオ・実機確認手順・`--dirty`（LD-03 診断デモ）の詳細は `docs/development.md`「デモデータ」節。設計/プランは `docs/superpowers/specs|plans/2026-07-04-hils-demo-mf4-generator*`。生成物は `demo_data/`（gitignore・非コミット）。

## 開発環境の落とし穴

詳細: `docs/development.md` 末尾参照。

## ファイル更新ルール

- **コメント**: 何 (WHAT) ではなく なぜ (WHY) を書く。自明なコードに説明を付けない
- **計画ドキュメント**: 設計は `docs/superpowers/specs/`、実装プランは `docs/superpowers/plans/`。仕様変更時はプランのチェックボックス／設計 spec を更新し、要件がずれるなら設計 spec 更新をユーザーに確認する。旧 `.kiro/specs/` はアーカイブで編集しない
- **本ファイル (CLAUDE.md) の熟成**: タスク完了ごとに「CLAUDE.md / docs/ に追記すべき知見はあるか」をユーザーに確認する。本ファイル肥大化を検知したら積極的に `docs/` に分離 — トレーサビリティ (ポインタ・関連リンク) を必ず確保する
