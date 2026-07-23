# E-0＋E-2「比較データモデル」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** E-0（mf4_1:: 内部キーの表示撤去・UX-19）＋E-2（基準ファイル・同名信号の同軸自動重ね・ファイル=色相ファミリー）。1 ファイル運用は完全従来互換。

**Architecture:** spec §1-§4 の確定設計に逐語で従う — 表示名は `gui/display_names.py` の 4 API（split_key/qualified_name/display_names/csv_header_names）へ一元化・キー体系は不変。基準/色相状態は AppViewModel 所有（resolver クロージャ・<2 ファイルで None）。色は color_is_auto＋sticky variant_step（全 add で確定）。

**Tech Stack:** PySide6・pytest(-qt)・realgui・colorsys（明度バリアント純関数）。

**Spec:** [docs/superpowers/specs/2026-07-23-e2-comparison-model-design.md](../specs/2026-07-23-e2-comparison-model-design.md) — **敵対的レビュー 30＋クローズ検証 9 指摘を全て実測検証つきで反映済み。§1-§4 の設計要素は一つも省けない**。

## Global Constraints

- **キー体系・数式・オフセット・D&D mime は不変** — 変えるのは表示のみ（E-0）。
- 表示名の唯一の出典は `display_names.py` の 4 API（spec §1.1 の契約逐語 — split_key はセパレータ無しで `("", 入力)`・衝突=distinct group_key・CSV は csv_header_names〔空白なし形式・"timestamp" 母集合注入〕）。
- resolver 契約: AppViewModel クロージャ・**ロード中ファイル < 2 なら None**・チップ/バッジも同一述語。注入は**パネル生成の単一ファクトリへ集約**（3 構築点 graph_area_vm.py:55/168/227 の漏れを構造的に防ぐ）。
- `variant_step` は**モードに関わらず全 add で確定**（sticky・color_is_auto 問わず数えて最小空き段・全段使用中は使用中総数 mod 3）。reapply は**専用変異経路**（e.color 直接更新＋`_invalidate_cache()`＋notify・set_color 禁止・hue のみ再解決）。
- 同名照合は裸名一致・`metadata["name_deduplicated"]` フラグ付きは「曖昧」除外（LD-14 配列名は除外しない）。
- 1 ファイル時の count-mod・凍結カタログ（01/07/08 完全一致・02-05/09 読み値名のみ・06 別契約）を壊さない。
- 品質ゲート各タスク末: uv run pytest -q・ruff check・ruff format・mypy src/（同期実行）。realgui は作成分 scoped＋Task 4 フル。
- コミット末尾: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## Task 1: E-0 — 表示名リゾルバ＋6 面置換

**Files:**
- Create: `src/valisync/gui/display_names.py`
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（readings 3 メソッド）・`graph_panel_view.py`（軸メニュー :2610 表示解決）・`export_csv_dialog.py`（葉/フィルタ/header_names 計算）・`src/valisync/core/export/csv_exporter.py`＋`CsvExportOptions`（header_names 受け渡し）・`signal_preview_vm.py`/`signal_preview_window.py`（名前行/タイトル）・`channel_browser_vm.py`（_SEP 統一）
- Test: 新規 `tests/gui/test_display_names.py`＋表示 assert 追随（spec §6 の実測サイト: test_graph_panel_vm.py:153・test_graph_panel_view.py:1260・test_export_csv_dialog.py:101・test_signal_preview_vm.py:38・test_signal_preview_window.py:56・readout 束縛系・test_graph_panel_multi_axis.py:1327-1335）

**Interfaces:**
- Produces: `split_key`/`qualified_name`/`display_names`/`csv_header_names`（spec §1.1 契約逐語）・`CsvExportOptions.header_names: tuple[str, ...] | None`。

- [x] **Step 1（リゾルバ TDD）**: 4 API の純関数テスト（契約全域 — セパレータ無し `("", x)`・distinct group_key 衝突・同一キー重複は衝突に数えない・timestamp 母集合・空白なし CSV 形式）→ 実装。
- [x] **Step 2（6 面置換）**: spec §1.2 の表逐語 — readings 3 メソッド（可視集合スコープ）・軸メニュー view 解決（VM 返り値は signal_key のまま）・エクスポート（葉/フィルタ裸名・UserRole 不変・header_names を dialog 側で計算し CsvExportOptions 経由 — **Signal 非改変**）・プレビュー名前行/タイトル（全ロード信号スコープ）・channel_browser の _SEP 統一。
- [x] **Step 3（追随）**: '::' 表示 assert のサイト単位追随（機械置換禁止・上記実測サイト＋`rg '::'` 再実測で漏れ確認）。
- [x] **Step 4**: ゲート → commit `feat(gui): E-0 表示名解決 — mf4_1:: を全表示面から撤去 (display_names 4 API・CSV header_names) (UX-19)`

---

## Task 2: E-2a/b — 基準ファイル＋同名重ね

**Files:**
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py`（reference 状態）・`file_browser_vm.py`（"reference" 購読・装飾 API）・`file_browser_view.py`（メニュー 2 項目・ガード）・`qt_signal_models.py`（バッジは表示テキスト — VM 側）・`graph_panel_vm.py`（`plotted_entries()` 公開）・`main_window.py`（重ねハンドラ）・`src/valisync/core/loaders/mdf_loader.py`/`csv_loader.py`（dedupe metadata フラグ）・`strings.py`
- Test: `tests/gui/test_app_viewmodel*.py`・`test_file_browser_*.py`・重ねロジック新設

**Interfaces:**
- Produces: `AppViewModel.reference_file_key`/`set_reference_file`（notify "reference"・unload 移行は _notify("unloaded") 前）・`GraphPanelVM.plotted_entries() -> list[tuple[int, str, int]]`・`metadata["name_deduplicated"]`・strings（基準に設定/基準の同名信号を重ねる/◎基準/要約 4 計数＋全済み＋母数 0 文言）。

- [x] **Step 1（基準状態 TDD）**: 既定=最初ロード・unload 移行（notify 順序）・"reference" notify → 実装。FileBrowserVM の "reference" 購読＋バッジ（**比較モード時のみ** — resolver 述語は Task 3 で完成のため本タスクでは `loaded_file_keys >= 2` の同一定義をローカル使用し Task 3 で述語共有へ寄せる）。
- [x] **Step 2（loader フラグ）**: dedupe サフィックス付与サイト（mdf_loader.py:416-419・csv_loader.py:102-117）で `metadata["name_deduplicated"]=True` → Layer A（フラグ有無・LD-14 配列名にフラグが付かないこと）。
- [x] **Step 3（重ねハンドラ TDD）**: spec §3 の 5 手順逐語（plotted_entries 走査・裸名照合・同軸 add・スキップ 4 種＋曖昧除外・要約 4 計数/全済み/母数 0）→ MainWindow ハンドラ＋メニュー 2 項目（releasing/範囲外ガード・基準行分岐）。
- [x] **Step 4（Layer B）**: メニュー enabled 状態・「基準に設定」→モデル reset 発火＋表示テキスト変化・重ね実行→エントリ/軸/ステータス統合。
- [x] **Step 5**: ゲート → commit `feat(gui): 基準ファイル＋同名信号の同軸自動重ね (E-2a/b)`

---

## Task 3: E-2c — ファイル=色相ファミリー

**Files:**
- Modify: `app_viewmodel.py`（file_hue_index・resolver クロージャ）・`graph_area_vm.py`（**パネル生成ファクトリ集約＋resolver 注入**・"loaded" で reapply）・`graph_panel_vm.py`（color_is_auto/variant_step・割当規則・reapply_auto_colors 専用経路）・`file_browser_vm.py`/`qt_signal_models.py`（DecorationRole チップ）・新規 `gui/color_variants.py`（hue_variant 純関数）
- Test: 色系新設＋既存破壊面追随（test_graph_panel_vm.py:177-201/510-519〔1 ファイル仕様として存置〕・:811-833 存置・view :800-811 スウォッチ）

**Interfaces:**
- Consumes: Task 2 の比較モード述語。Produces: `hue_variant(hex, step) -> hex`（CVD 検証済み係数を test-lock）・`GraphPanelVM.reapply_auto_colors()`（引数なし・注入済み resolver 使用）。

- [x] **Step 1（hue_variant）**: colorsys 純関数＋CVD シミュレーション（deuteranopia/protanopia/tritanopia）でファミリー間/バリアント間分離を検証し係数確定・test-lock（増分0 手順・design.md の ΔE マージン非侵食）。
- [x] **Step 2（割当エンジン TDD — spec §4.1 逐語）**: variant_step 全 add 確定（sticky・color_is_auto 問わず・最小空き段・mod 3 巡回）・resolver None=count-mod 完全一致・int=hue_variant。resolver は AppViewModel クロージャ（<2 で None）・**ファクトリ集約で 3 構築点へ注入**。
- [x] **Step 3（reapply — spec §4.2 逐語）**: 専用変異経路（_invalidate_cache 必須・set_color 禁止・hue のみ・冪等）・"loaded" 配線・チップ DecorationRole。
- [x] **Step 4（Layer A/B — spec §6 逐語）**: 遷移分離（1 ファイル 3 本→2 ファイル目→相異 variant）・歯抜け再利用・移送後不変・2→1 復帰・render_data 新色・手動ピン留め尊重・hue assert は**初期パネル＋add_tab パネルの 2 経路（GraphAreaVM(app_vm) 経由構築）**。
- [x] **Step 5**: ゲート → commit `feat(gui): ファイル=色相ファミリー (sticky variant_step・reapply 専用経路・CVD 検証) (E-2c)`

---

## Task 4: 凍結・①ゲート・docs

- [x] **Step 1**: realgui フル＋新設 2 ファイルジャーニー（小型 CSV 2 ファイルをテスト内生成 — 既存 realgui fixture 流儀）: 実 OS 右クリック「基準の同名信号を重ねる」→同軸重なり実描画・色相ファミリー実ピクセル（青系/橙系）・読み値「(csv_1)」併記・バッジ/チップ実表示・E-0 の表示面スクショ。
- [x] **Step 2**: 凍結 per-state 契約（spec §6 逐語）: 完全一致=01/07/08・意図差分=02-05/09（読み値名のみ）・06=exit 2 許容は「NG が 06 のみの場合」＋リサイズ前後の目視記録。viewport crop 全一致 → 昇格 → 決定性。
- [x] **Step 3**: docs — design.md 決定履歴（ドック統合廃止・判断点 5 件＋読み値ファイルキー併記・[idx] 曖昧除外・CSV 空白なし形式・診断記録なし簡略化・unload 非対称）／カタログ（UX-19 解消・UX-18 CVD 制約充足・推奨5 の統合部分却下注記・UX-21/29/30 見送り注記）／CLAUDE.md（次=増分F）。
- [x] **Step 4**: 最終ゲート → commit → PR（DesignSync はマージ後コントローラ）。

## Self-Review 済み確認事項

- spec §1-§4 の全設計要素がステップに 1:1（4 API・6 面・reference notify 順序・loader フラグ・plotted_entries・sticky step・resolver 契約・ファクトリ集約・専用 reapply・per-state 凍結契約）。
- 破壊面はレビュー実測の行番号で列挙済み。型整合: 4 API・header_names・plotted_entries・hue_variant・reapply_auto_colors() を Interfaces に明記。
