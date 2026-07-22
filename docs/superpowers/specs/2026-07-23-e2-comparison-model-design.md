# E-0＋E-2「比較データモデル」設計 — 表示名解決・基準ファイル・同名重ね・ファイル=色相ファミリー

- **経緯**: 増分E の「データ/信号ドック統合」（単一データサイドバー・Data Explorer 廃止）は**ユーザー決定で廃止**（2026-07-23）。本 spec は残る E-0（mf4_1:: 内部キーの表示撤去・UX-19）と E-2（比較データモデル）を、**操作面を既存ファイルブラウザへ載せ替えた**再設計として定義する。設計案・完成イメージは 2026-07-23 にユーザー提示済み・判断点 5 件全て確定。
- **確定済み判断点**: (1) 比較モード遷移時に自動割当色を再着色（手動変更は尊重）／(2) 基準の既定=最初のロードファイル／(3) 同名×単位不一致はスキップ／(4) **読み値の同名識別はファイルキー併記「VehSpd (mf4_1)」（ユーザー決定 — E-0 の例外として同名衝突時のみ）**／(5) 明度バリアント 3 段。
- **現状構造**: 本 spec の file:line は 2026-07-23 スカウト（3 領域・38 findings）による実査値。

## 1. E-0 — 表示名解決（UX-19）

**キー体系は不変**。信号キーは `{mf4|csv}_{n}::{orig}`（SignalGroupManager.add が発番・単一ファイルでも必ず付く — signal_group_manager.py:30-42/75-101）で、オフセット辞書・数式エンジンの依存記録・View 逆引き・D&D mime が全てこのキーに依存する（変更すると全滅 — スカウト実証）。**変えるのは表示だけ**。

### 1.1 表示名リゾルバの新設

`src/valisync/gui/display_names.py`（pure Python・Qt 非依存）:
- `split_key(signal_key) -> tuple[str, str]` — `(group_key, bare_name)`（`KEY_SEPARATOR` は signal_group_manager から import。**channel_browser_vm.py:19 のローカル `_SEP` 重複定義もこれへ統一**）。**セパレータ無し入力の契約: `(入力, "")` を返す**（冪等・契約外呼出の ValueError を作らない）。
- `qualified_name(signal_key) -> str` — `"{bare} ({group_key})"` 形式（例 `VehSpd (mf4_1)`）。**ファイルキー採用の根拠**: 同一 basename の重複ロード（UXG-09 — キーは `csv_3` 等で常に一意・basename は同一文字列）でも一意に識別できる。`Session.source_name`（basename）は識別子に使わない。
- **`display_names(keys) -> dict[signal_key, str]`（第 3 の API — 集合スコープの衝突ヘルパ）**: 衝突の定義は「**同一裸名が 2 つ以上の異なる group_key に由来する**」— 該当裸名の全キーを qualified、他は裸名。**同一 signal_key の重複（同じ信号の 2 回プロット — 現行 UI で到達可能・graph_panel_vm.py:290-296 の dedupe docstring が実在証跡）は衝突に数えない**（単一ファイル運用で併記が誤発火しない・判断点 4 の「識別」目的に整合）。
- **CSV ヘッダ専用形式 `csv_header_name`**: `"{bare}({group_key})"`（**空白なし** — エクスポートは区切り文字「スペース」を正式提供し exporter は無クォート join のため、空白含み形式はヘッダ列構造を破壊する〔レビュー実測: pandas が無言列ずれ〕。表示 UI の「{bare} ({group_key})」とは別形式であることを設計判断として記録）。衝突判定の母集合には**固定列ヘッダ `"timestamp"` を常に含める**（裸名 timestamp の信号は qualified へ）。
- 用語注意: `metadata['source_name']`（MDF の ECU ソース名 — mdf_loader.py:162-169）とは**別概念** — リゾルバ API 名に source を使わず display/bare/qualified 系で命名。

### 1.2 露出 6 面の置換（スカウト 5 面＋レビュー実測で 1 面追補 — 実行時全域走査で他に残存なし）

| 面 | 現状 | 変更 |
|---|---|---|
| 読み値ペイン 3 モード＋TSV | readings 3 メソッドが `name=entry.signal_key` を直格納（graph_panel_vm.py:1103-1146/1148-1175/1308-1361）→ cursor_readout が無加工描画・table_tsv へも | **readings 生成時に表示名化**（表示・TSV へ自動波及）。**可視エントリ集合内で裸名が衝突するものだけ** `qualified_name`、他は裸名（判断点 4）。共有ヘルパ 1 つを 3 メソッドから呼ぶ。差分更新は `_layout_sig` が name を含むため正しく full_rebuild（cursor_readout.py:541-543） |
| Y軸メニューの曲線一覧 | `entries_on_axis` が signal_key を表示ラベル兼用（graph_panel_vm.py:1377-1387・view :2610） | **VM の返り値は signal_key のまま・view :2610 で表示名解決**（VM 側で置換すると tuple の str がキーでなくなり既存の鍵消費・E-2b 走査が静かに壊れる）。衝突判定は**同軸エントリ内**。既存テスト test_graph_panel_multi_axis.py:1327-1335・test_graph_panel_view.py:1260 を追随リストへ |
| エクスポートダイアログ | 葉テキスト・フィルタ・**CSV 出力ヘッダ行**が namespaced 名（export_csv_dialog.py:88-101/197-201・csv_exporter.py:73-78） | 葉テキストとフィルタは裸名（**UserRole の選択キーは不変** — :100-101）。CSV ヘッダは裸名・選択集合（＋"timestamp"）内の衝突時のみ **`csv_header_name` 形式**。**実装機構: `CsvExportOptions` へ `header_names: tuple[str, ...] | None`（signals と同順）を追加し、GUI 側（ExportCsvDialog）が display_names で計算して渡す** — core は与えられた名前を書くだけ（core→gui import の層違反を作らない）。**Signal オブジェクトは非改変**（改名コピーは `_sorted_view_delegate` を失い FU-20 の float64 キャッシュ再実体化を再導入する — signal_group_manager.py:92-99） |
| 信号プレビュー「名前」行 | namespaced（signal_preview_vm.py:49） | 裸名 |
| **信号プレビューの windowTitle（6 面目 — レビュー実測で発見）** | `PREVIEW_TITLE_TMPL` へ生キー（signal_preview_window.py:62・strings.py:102）。**撮影は client 領域のみでタイトルバーは凍結比較に写らない — 検出網ゼロの silent 面** | 衝突時 qualified・非衝突時 裸名（`display_names` — 衝突スコープ=全ロード信号）。**既存テスト test_signal_preview_window.py:56 の `endswith("g::B")` lock を同時追随** |
| FileBrowser fallback | **変更なし** — fallback が表示するのは group_key（`"mf4_1"` — `::` 非含有・file_browser_vm.py:117-118）で既に E-0 の目標形（初版の「split_key 適用」指示はスカウト誤読として撤回） | — |

- **変更しない面**: チャンネルブラウザ（剥がし済み — channel_browser_vm.py:113）・診断・軸ラベル（Stage A 代表ペア — 裸名済み）・D&D mime（非可視）・ステータス/タイトル（basename 済み）。
- **既知の残穴（スコープ外・記録）**: 診断ジャンプの basename first-match（main_window.py:550-553 — 同一 basename 複数ロードで最初のファイルへ着地）は既存の穴のまま。

## 2. E-2a — 基準ファイル

- `AppViewModel` に `reference_file_key: str | None` を新設（`_active_file_key` と同型 — app_viewmodel.py:110-127 の先例・pure Python・**非永続** — R14 オフセットの transient 先例。F-1 で .vsession 対象化）。
- **既定=最初のロードファイル**（判断点 2）: `register_loaded` で未設定なら設定。`unload_file` で基準を失ったら**残存のロード順先頭へ自動移行**（全 unload で None）。notify タグ `"reference"`。
- UI: ファイルブラウザ行に**基準バッジ**（表示テキスト接尾「 ◎基準」— strings.py へ）・右クリック「基準に設定」（基準行では disabled）。行↔キーは既存の位置対応（file_browser_vm.py:52-58 と同型で VM に装飾 API を追加）。
- **バッジの表示条件は比較モード（2 ファイル以上）のみ**（チップと同一述語 — 1 ファイル時は基準概念が無意味で、凍結カタログ〔02-05 に FileBrowser 行が実写〕の完全一致も守られる）。
- **notify 配線（レビュー捕捉 — 記述だけでは誰も購読しない）**: `FileBrowserVM._on_app_change` の refresh 条件（現行 loaded/unloaded/releasing — file_browser_vm.py:100-103）へ **"reference" を追加**（バッジ即時更新）。`unload_file` 内の基準自動移行は **`_notify("unloaded")` より前**に完了させる（バッジが unloaded refresh に相乗りできる順序）。
- **新メニュー 2 項目は releasing 行・範囲外行でガード**（既存 select_file/unload の index ガードと同型 — customContextMenuRequested は flags 無効でも発火する）。

## 3. E-2b — 同名信号の自動重ね

- 導線: ファイルブラウザの**非基準ファイル行**右クリック「基準の同名信号を重ねる」（2 ファイル以上で表示・基準行では出さない）。
- 挙動（MainWindow ハンドラ — `_add_to_active_panel` と同じ配送先解決）:
  1. **アクティブパネル**の plotted エントリのうち**基準ファイル由来**のものを走査 — **公開 API `plotted_entries() -> list[tuple[entry_id, signal_key, axis_index]]` を GraphPanelVM に新設**（既存 plotted_signal_keys は axis 無し dedupe 済みで不足・private `_plotted` 直叩きを禁じる）
  2. 各エントリの裸名と同名の信号を対象ファイルの `group_signals` から検索（裸名はファイル内一意 — ローダーが `[idx]` サフィックスで保証・実付与サイトは mdf_loader.py:416-419／CSV は csv_loader.py:102-117 の LD-08 同方式）
  3. 見つかった同名を**同じ axis_index へ** `add_signal_to_axis(key, axis_index)`（既存 API — graph_panel_vm.py:270-288）
  4. スキップ条件: 同名なし／**単位不一致**（`sig.metadata` の unit 比較 — **双方空を含む文字列完全一致で通過・片方のみ空はスキップ**〔実データで unit 欠落は普通〕・判断点 3）／既に同一 (key, axis) のエントリが存在（重複追加防止 — 「済み」として別計上）
  5. **[idx] 曖昧化の既知の限界（レビュー実測）**: `[idx]` 付き裸名は基準/対象で付与の非対称・走査順対応になり得るため**自動照合から除外し「曖昧」として別計上**（誤ペア重ねは全ゲートで検出不能な静かな事故 — 安全側。design.md へ設計判断として記録）
- 結果要約: `set_status_message(...)` — `{表示名}` は source_name・**重複 basename 時はキー併記（判断点 4 と同規則）**。計数は**母数=基準エントリ**で「n 件を重ねました（同名なし m・単位不一致 k・済み j・曖昧 i — 0 の項は省略）」・全件済みは専用文言「すべて重ね済みです」（strings.py 定義）。timeout_ms=8000（既存 API — main_window.py:754-769）。**診断への記録はしない**（GUI 発診断の新機構は YAGNI — 初版モックからの意図的簡略化として記録）。
- 基準切替・後続ロードでの**自動再配置はしない**（明示操作のみ）。

## 4. E-2c — ファイル=色相ファミリー

### 4.1 割当エンジン（現状: count-mod の単一ファネル）

現状は `add_signal_to_axis` の `palette[len(_plotted) % 8]`（graph_panel_vm.py:272-273）が唯一の割当点・スロット管理なし・手動フラグなし。変更:

- **`_PlottedEntry.color_is_auto: bool = True`＋`variant_step: int = 0` を新設**（y_is_auto と同型）。`set_color`（:637-648）で color_is_auto=False（手動ピン留め — 以後の自動再着色から除外）。
- **ファイル→色相の割当は AppViewModel が所有**: `file_hue_index: dict[str, int]`（group_key→palette index・`register_loaded` で単調カウンタ mod 8 割当・unload でも**再利用しない** — 色の安定性優先）。
- **resolver 契約（レビュー捕捉 — 判定の一元化）**: AppViewModel が保持するクロージャで、**ロード中ファイルが 2 未満なら常に None を返す**（比較モード判定は AppViewModel の責務 — VM 側でファイル数を数えない・None の意味は「file-hue 不適用=count-mod fallback」に単義化）。チップ/バッジの表示条件も**同一述語**を参照（二重実装を作らない）。
- **注入は GraphPanelVM の全 3 構築点**（graph_area_vm.py:55 初期パネル・:168 add_tab・:227 add_panel — 初版の :227 単独引用は誤り。**パネル生成を単一ファクトリヘルパへ集約して注入を構造的に 1 箇所化**することを推奨）。既定 None=従来動作でテスト互換。`reapply_auto_colors` は**注入済み resolver を読む（引数なし）** — §4.2 との配管を統一。
- **割当規則**:
  - **resolver が None（1 ファイル・未注入）: 従来の count-mod を完全維持**（フォールバック — 凍結挙動・既存テストの大半を保存）
  - **resolver が int（比較モード）**: `base = palette[hue]`・**`variant_step` は add 時に一度だけ確定する sticky 値** — 同一パネル内の同一ファイル由来 auto エントリが**現在使用中の段を避けて最小の空き段（0/1/2）**を選ぶ（削除の歯抜けを再利用し家族内重複を回避）・全段使用中は巡回。**reapply は hue のみ再解決し step は保持** — 後続ロードで無操作の曲線が変色しない（「色の安定性優先」と整合・レビュー Critical の根治）。クロスパネル移送（extract/insert_axis）は entry ごと color/step を保持（既存挙動）。
- **明度バリアント生成**: pure 純関数 `hue_variant(hex, step) -> hex` を新設（colorsys — Color 型/Qt に色操作 API は現存しない・スカウト確認済み）。**具体係数は実装時に CVD シミュレーション（deuteranopia/protanopia/tritanopia）でファミリー間/バリアント間の分離を検証して確定し test-lock**（増分0 の手順）。design.md 記録済みの分離マージン（drop_highlight teal・ΔE 許容 2 件）を食い潰さないことも検証対象。

### 4.2 モード遷移の再着色（判断点 1）

- **2 ファイル目のロード（"loaded" notify）で、`color_is_auto=True` のエントリを file-hue 割当へ再着色**（GraphAreaVM の "loaded" ハンドラ — graph_area_vm.py:70-80 の既存 refresh 経路に相乗り — から各パネルの `reapply_auto_colors()` を呼ぶ）。手動変更（color_is_auto=False）は不変。
- **reapply は専用変異経路（レビュー捕捉）**: `e.color` 直接更新＋**`_invalidate_cache()` 必須**（color はキャッシュキー非包含 — set_color docstring :637-648 が明記する既存制約）＋notify。**`set_color` は使わない**（使うと新仕様の color_is_auto=False 化で全 auto エントリが初回 reapply で恒久手動化される）。冪等（再実行で無変化）を test-lock。
- **1 ファイルへ戻ったとき（unload）は再着色しない**（既存曲線の色安定を優先・新規追加のみ従来割当へ戻る — 意図的非対称として記録）。
- 曲線メニューの色スウォッチ（8 基本色 — graph_panel_view.py:2325-2328）は**現状維持**（手動ピック=手動ピン留めの導線として意味が変わるだけ・構造不変）。

### 4.3 ファイル色チップ

- `FileListModel` に **DecorationRole** を追加（QColor 返却で QListView が自動描画 — 現状 DecorationRole 未実装・qt_signal_models.py:70-110）。VM が row→hue 色を公開（比較モード時のみ・1 ファイル時はチップなし）。

## 5. 変更しないもの

- キー体系・数式エンジン・オフセット機構・D&D mime・チャンネルブラウザ・Data Explorer・軸操作モデル・凍結カタログの構成（**カタログは単一ファイルのため比較モードは発火せず、色・レイアウトはピクセル不変** — E-0 の表示名変化のみが意図差分）。
- 基準/色相/重ねの永続化（F-1 の .vsession で扱う）。

## 6. テスト戦略（/gui-test-plan 分析)

- **Layer A**:
  - リゾルバ純関数（split/qualified・重複 basename の一意性）・衝突判定ヘルパ（可視集合/同軸/エクスポート選択の各スコープ）
  - 色: hue 割当の安定性（unload 後も不変・再利用なし）・`hue_variant` の CVD 分離 test-lock・**1 ファイル時の count-mod 完全一致**（フォールバック不変 — 既存 modulo 巡回ロックテスト test_graph_panel_vm.py:811-833 は**比較モード外の仕様として存置**）・color_is_auto の遷移（set_color→False・再着色除外）
  - 同名重ね VM ロジック（同軸配置・スキップ 3 条件・要約カウント）
  - 基準状態（既定・unload 移行・notify）
- **Layer A 追加（レビュー反映）**: 同一キー重複プロット時は裸名のまま（衝突誤発火なし）・reapply の冪等性＋「削除歯抜け後の add が空き段再利用」＋「移送後のロードで step 不変」・「2→1 ファイル遷移後の新規追加が count-mod へ戻る」・reapply 後の `render_data()` が新色を返す（VM 状態でなく curve を assert — cache 無効化の検証）
- **Layer B**: ファイルブラウザメニュー（enabled 状態・基準行分岐・releasing ガード）・チップ/バッジの Role 出力＋**「基準に設定」直後にモデル reset が発火し表示テキストが変わる**（data() 直読の false-green を避ける）・重ね実行→エントリ/軸/ステータスの統合・再着色（手動ピン留め尊重）・**hue 色 assert は GraphAreaVM(app_vm) 経由で構築した「初期パネル」と「add_tab パネル」の 2 経路**（resolver 直接注入 VM では配線漏れに盲目）
- **Layer C（realgui・①ゲート）**: 2 ファイル実ロード→実 OS 右クリック「基準の同名信号を重ねる」→同軸重なりの実描画スクショ・色相ファミリー（青系/橙系の実ピクセル）・読み値の「(mf4_1)」併記・基準バッジ/チップの実表示
- **凍結検証（per-state 契約 — レビューが実ベースライン読取で確定）**: **完全一致 = 01/07/08**（08 のプレビュー撮影は「プレビュー」タブで名前行は写らない — 初版記述を訂正）／**意図差分 = 02-05/09**（読み値ペイン領域の名前のみ）／**06 = ツリー葉テキスト＋ダイアログ幅のサイズ変化許容**（テキスト長依存で PNG サイズ不一致 = compare exit 2 になり得る既知現象 — compare_screenshots.py:73-75）。プロット viewport crop は全状態一致・色不変。バッジ/チップは比較モード限定のためカタログ不変（§2）。
- **既存テスト破壊面（スカウト実測 — プランへ引き渡し）**: 表示名系 — readout/軸メニュー/エクスポートの表示 assert（'::' 出現 361 箇所/51 ファイル〔プラン時に再実測〕のうち**表示文字列を assert するもののみ — 実測で約 8 ファイル十数サイト**〔test_graph_panel_vm.py:153・test_graph_panel_view.py:1260・test_export_csv_dialog.py:101・test_signal_preview_vm.py:38・test_signal_preview_window.py:56・readout 束縛系・multi_axis:1327-1335〕 — キー不変のため大半は無傷・サイト単位判定）。色系 — test_graph_panel_vm.py:177-188/191-201/510-519（1 ファイル時仕様として存置可）・view スウォッチ index 参照 :800-811・realgui ピクセル前提（test_fu12_boundary_data_visible.py:146-157・test_offscale_badge.py:228-297・test_axis_menu_offset.py:506-513 — **明度バリアントが ±40/ch マッチに入る false-positive リスクは 2 ファイル時のみで既存テストは単一ファイル — 非破壊見込み・要確認**）。

## 7. リスクと対策

| リスク | 対策 |
|---|---|
| E-0 の表示変更がキー参照を壊す | キー体系不変の原則（§1）・表示化は readings 生成/ツリーテキストのみ・UserRole/mime/辞書は非接触 |
| 色エンジン変更が 1 ファイル運用を退行させる | フォールバック完全維持＋count-mod 一致テスト・凍結ピクセル不変（単一ファイルカタログ） |
| 明度バリアントが CVD/既存分離マージンを崩す | 係数を CVD シミュレーション＋ΔE 検証で確定し test-lock（増分0 手順・design.md 制約参照） |
| resolver 注入の配線漏れ（比較モードでも従来色） | 注入は CursorState と同じ構築点・Layer B で 2 ファイル時の hue 色を assert |
| 再着色が手動色を潰す | color_is_auto フラグ＋Layer B ピン留めテスト |
| readout 併記の layout 崩れ | name 変化は _layout_sig 経由で full_rebuild（既存機構）・Layer B で衝突出現/解消の遷移確認 |
| 同名重ねの誤配置（axis_index ずれ） | 既存 add_signal_to_axis の axis 指定・Layer B で軸一致 assert・①ゲート実機 |

## 8. 実装増分（writing-plans への入力）

単一ブランチ `feature/e2-comparison-model`・PR 1 本・凍結/①ゲートは末尾 1 回。

1. **E-0**: display_names.py（リゾルバ・_SEP 統一）＋5 面置換＋表示 assert 追随（サイト単位）。
2. **基準＋同名重ね**: AppViewModel 基準状態・ファイルブラウザメニュー 2 項目＋バッジ・重ねハンドラ＋要約・Layer A/B。
3. **色相ファミリー**: color_is_auto・hue 割当（AppViewModel）＋resolver 注入・hue_variant（CVD 確定）・再着色・チップ（DecorationRole）・破壊面追随。
4. **凍結・①ゲート・docs**: realgui フル＋2 ファイル実機ジャーニー・前後比較（E-0 意図差分のみ）→昇格→DesignSync・design.md 決定履歴（ドック統合廃止・判断点 5 件・診断記録の簡略化・色の非対称遷移）・カタログ（UX-19 解消・推奨5 の統合部分却下を注記・UX-18 の CVD 制約充足）・CLAUDE.md。

## 9. 受け入れ基準

- 表示面から `mf4_1::` が消える（読み値/軸メニュー/エクスポート/プレビュー — 同名衝突時の読み値・CSV ヘッダの「(mf4_1)」併記は意図的例外）。
- 基準バッジ・色チップ・右クリック 2 項目が機能し、同名重ねが同軸配置＋要約表示（実機）。
- 2 ファイル時にファイル=色相ファミリー（実描画）・手動色は再着色で不変・1 ファイル時は完全従来どおり（count-mod 一致＋凍結ピクセル不変）。
- 品質ゲート＋realgui フル＋凍結（E-0 意図差分照合・viewport crop 一致・決定性）＋DesignSync 再同期。
