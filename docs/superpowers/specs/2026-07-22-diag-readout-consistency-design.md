# 診断・読み値の整合性修正 設計 — 実バグ/不整合のみ（UX-06/07/31/44・UXG-12/17/27）

- **経緯**: 増分D-2（通知センター型診断）はユーザー決定で**不採用**（2026-07-22・モックアップ提示後「こんな豪華な診断ウィンドウは不要・現状のままで ok」）。本 spec はその代替として「**現状の見た目・構造を維持したまま、実バグと他機能との不整合だけを直す**」6 修正を定義する。デザイン刷新（詳細ペイン・件数内蔵チップ・自動展開・ステータスバー常設カウンタ）は**行わない**。
- **スコープ確定**: B1〜B4（コントローラ検証済みの不整合 4 件）＋ユーザー追加 2 件（B5 Clear 確認・B6 読み値スクロール）。

## 1. 修正一覧と対象カタログ行

| # | カタログ | 問題（現物確認済み） | 修正 |
|---|---|---|---|
| B1 | UX-31 | フッターカウンタ「⛔ n / ⚠ n」に info が無く、ステータスバー誘導「ℹ 情報 n 件（「診断」ドックを参照）」と着地が矛盾 | カウンタを「⛔ n / ⚠ n / ℹ n」へ |
| B2 | UX-06 | フィルタ 3 ボタンが plain push で選択状態不可視。絞り込み 0 件と診断ゼロが同一文言で、警告のみ存在時に「エラー」絞り込み→「診断はありません」→ゼロと誤認する経路 | 3 ボタンを checkable 排他化＋0 件文言をフィルタ文脈付きに |
| B3 | UX-07 残余 / UXG-12 | メッセージ列 Stretch 済みだが切れた場合の全文閲覧手段がゼロ | メッセージセルに setToolTip(全文) |
| B4 | UX-44 | 展開側タイトルバーのシェブロンが全ドック「>」固定 — レール側は辺対応済み（PR #133）で、下端の診断は畳む方向（下）と矛盾 | シェブロンをドックの辺から解決（レールの逆写像・実行時移動にも追随） |
| B5 | UXG-27 | Clear が確認なし・非可逆で、診断（データ品質の証跡）が誤クリック 1 回で消える | 確認ダイアログ（アーカイブ化は不採用 — 「現状のまま」方針に沿う最小形） |
| B6 | UXG-17 | 読み値ペインに縦スクロールが無く、行数（曲線数に 1:1）がウィンドウ最小高を押し上げ、縮小時は診断ドックが先に圧潰される | 読み値の行グリッドを QScrollArea 化（ヘッダ行は固定・行部のみスクロール） |

**UX-53 への波及**: B1 でステータス誘導文とドックカウンタの照合が可能になり「着地で情報が消える」核は解消（部分解消として記録）。恒久残留自体は現状維持。

## 2. 設計

### 2.1 B1 — カウンタへ ℹ 追加

- `DiagnosticsViewModel.counts()` を `(errors, warnings)` → **`(errors, warnings, infos)` の 3-tuple へ拡張**（呼出元は view と既存テストのみ — 型変更で loud-fail）。
- `diagnostics_view._rebuild` のラベルを `f"⛔ {errors} / ⚠ {warnings} / ℹ {infos}"` へ（既存と同じ ASCII スラッシュ・RUF001 は既存 noqa 慣行）。

### 2.2 B2 — フィルタの checkable 排他化＋0 件文言のフィルタ文脈

- すべて/エラー/警告 の 3 `QPushButton` を `setCheckable(True)` にし **`QButtonGroup`（exclusive）** へ登録。初期状態は「すべて」checked。クリアは非 checkable のまま（見た目・配置は不変）。checked の可視化は Fusion palette の既定表現（新規スタイル追加なし — 「現状のまま」方針）。
- プレースホルダ文言を状態依存に:
  - フィルタなしで 0 件: 「診断はありません」（現行維持）
  - フィルタありで 0 件: **「{フィルタ名}に該当する診断はありません（全 {n} 件）」**（n = 無フィルタ総数）
- 文言は `strings.py` へ追加（`DIAG_EMPTY`・`DIAG_EMPTY_FILTERED_TMPL`）。フィルタ名は表示ラベルと同語（「エラー」「警告」）。
- **supersede 記録**: 旧 valisync-gui spec §7「絞り込み 0 件と診断ゼロの同一表示は by-design」を本修正で覆す（カタログ UX-06 自身が「誤認装置になっており再考の根拠がある」と認定）。docs/design.md 決定履歴へ記録。

### 2.3 B3 — メッセージ全文ツールチップ

- `_rebuild` のメッセージセル生成時に `item.setToolTip(e.message)`（メッセージ列のみ — 他列は内容幅で全表示されるため不要）。

### 2.4 B4 — シェブロンの辺解決

- `dock_collapse_rail.py` に**折りたたみ方向の写像**を追加: `collapse_chevron_for_area(area) -> str` — レールの展開方向写像（Left→chevron_right 等）の**逆**: Left→`chevron_left`・Right→`chevron_right`・Bottom→`chevron_down`（Top は現状未使用だが `chevron_up` を定義）。4 アイコンは vendored Lucide に既存（icons.py 27-30 行）— **アイコン追加なし**。
- `CollapsibleDockTitleBar` は構築時に `main_window.dockWidgetArea(dock)` で初期解決し、**`dock.dockLocationChanged` へ接続して実行時のドック移動にも追随**（レールと同じ辺基準）。フロート中は直前の辺を維持（dockLocationChanged はフロート復帰時に発火）。
- ツールチップ「折りたたむ」は不変。

### 2.5 B5 — Clear 確認ダイアログ

- `clear_diagnostics()` に確認を挿入: 明示 `QMessageBox`（G-14 と同型 — `.question()` 便宜形はボタンハンドル無しのため使わない）。
  - 表題: 「診断のクリア」／本文: **「診断 {n} 件をクリアしますか？この操作は元に戻せません。」**（R-08 確認形・R-10 全角？・{n} = 無フィルタ総数）
  - ボタン: Yes→setText **「クリア」**・No→setText **「キャンセル」**（G-14 の setText 方式・本文動詞と一致）
  - **0 件時は確認なしで no-op**（空リストに確認を出すのはノイズ）。
- ダイアログは DI 注入可能に（既存の色ダイアログ/削除確認と同じテスト容易性パターン — コンストラクタ/属性でファクトリ差し替え）。
- 文言は `strings.py` へ追加。

### 2.6 B6 — 読み値ペインの縦スクロール

- `CursorReadout` の構造変更: `_grid`（QGridLayout・現在 outer VBox 直下）を **`rows_host = QWidget()` へ移し、`QScrollArea`（`widgetResizable=True`・水平 `ScrollBarAlwaysOff`・垂直 `ScrollBarAsNeeded`・`setFrameShape(NoFrame)`）で包む**。ヘッダ行（モードトグル・✕ 等）は scroll 外に残し常時可視。
- outer 末尾の `addStretch(1)` は rows_host 内へ移動（行が少ないとき行を上詰めに保つ — 現行の見た目維持）。
- **サイズ挙動**: QScrollArea の minimumSizeHint は内容非依存の小値 — 行数がウィンドウ最小高を押し上げる連鎖（UXG-17 の本体）が構造的に消える。既存の `updateGeometry` 呼び出し（ちらつき根治 — 増分B）は無害なので維持。
- **背景の透過**: `QScrollArea { background: transparent; }`＋viewport 透過（`rows_host` は autoFillBackground=False）で `surface_readout_panel` トークンの見えを不変に保つ（qss.py へ断片追加・値は既存トークンのみ）。**非オーバーフロー時のピクセル不変**が凍結検証の対象。
- 行クリック（波形ハイライト連動）・差分更新（`_layout_sig`/`_update_in_place`）・凡例⇔計測モード切替は rows_host 内で従来どおり動作（グリッドの親が変わるだけで生成・更新ロジックは不変）。

## 3. 変更しないもの

- 診断の列構成・ドック構造・既定レイアウト・Clear の配置・フィルタボタンの並び・アイコングリフ（⛔⚠ℹ — D-3 領域）。
- 読み値ペインの列・書式・モード（計測 IA 確定仕様）。
- D-2 で提案し不採用となった一切（詳細ペイン・自動展開・常設カウンタ・件数内蔵チップ）。

## 4. テスト戦略（/gui-test-plan 分析）

- **Layer A**:
  - B1: `counts()` 3-tuple＋ラベル文言（info 込み）。
  - B2: 排他性（エラー checked→すべて unchecked）・フィルタ 0 件文言のフィルタ文脈（警告のみ存在＋エラーフィルタ→「エラーに該当する診断はありません（全 1 件）」）・「すべて」初期 checked。
  - B3: メッセージセルの toolTip == 全文。
  - B5: DI ダイアログ stub で「確認→クリア実行/キャンセル→非実行/0 件→ダイアログ非表示で no-op」の 3 分岐。
  - B6: 多行時に `minimumSizeHint().height()` が行数非比例で有界（honest: 修正前は行数比例で増える値を sabotage 的に対照）・行クリック→`row_activated` 発火が scroll 内でも不変。
- **Layer B**:
  - B4: `dockLocationChanged` 駆動でアイコンが辺に追随（アイコン恒等は `icons.icon()` の QIcon 比較でなく**写像関数の戻り値**＋ボタンへ設定されたアイコンの cacheKey で検証）。
  - B2: 実クリックで checked 遷移（qtbot）。
- **Layer C（realgui・①ゲート）**:
  - B4: 実表示で下端診断のシェブロンが「v」であることのスクショ目視（＋左ドックは「<」）。
  - B5: 実クリックで確認ダイアログ→「クリア」→表が空＋プレースホルダ（実 OS 入力）。
  - B6: **実ディスプレイでウィンドウを縦に縮め、読み値 20 行超でも診断ドックが圧潰されず読み値側にスクロールバーが出る**ことを実測（UXG-17 の再現→解消の対照。[[gui_dock_toggle_width_change_needs_real_display_and_layout]] — オフスクリーンではレイアウト圧力が再現しないため実表示必須）。
- **凍結検証**: 影響は診断ドック（カウンタ文言・ボタン checked 枠）と読み値ペイン（非オーバーフロー時は不変のはず）。前後比較で**差分が診断ドック内のカウンタ/ボタン領域に限られ、読み値ペイン・プロット viewport はピクセル一致**（crop 比較モード再利用）→ ベースライン昇格 → DesignSync 再同期。

## 5. リスクと対策

| リスク | 対策 |
|---|---|
| B6 の QScrollArea 化が増分B のちらつき根治（addStretch＋updateGeometry）を退行させる | stretch を rows_host 内へ移し既存 updateGeometry 維持。凍結比較＋実機で分割ドラッグ時の見た目確認 |
| B6 の透過設定漏れで readout 背景が Fusion 既定色に化ける | qss 断片＋値分岐は不要（既存トークンのみ消費）— 凍結ピクセル比較が検出 |
| B2 の checked 表現が Fusion で視認不足 | まず既定表現で実機確認し、不足なら chrome_highlight 枠の qss 断片を追加（トークン新設はしない）。①ゲートで判定 |
| B4 の dockLocationChanged がフロート中に発火し辺不定 | area が DockWidgetArea 外（NoDockWidgetArea）の間は直前アイコンを維持 |
| counts() 3-tuple 化の呼出元漏れ | 型変更で unpack が loud-fail・全呼出元 grep をプランに含める |
| realgui 掴み点（診断ボタン・readout）への波及 | ボタン文言不変・配置不変のため掴み点変化なし。readout の realgui はスクロール外のヘッダ操作のみ — 全数 grep で確認 |

## 6. 実装増分（writing-plans への入力）

単一ブランチ `feature/diag-readout-consistency`・PR 1 本・凍結/①ゲートは末尾 1 回。

1. **診断ビュー**: B1（VM counts 3-tuple）＋B2（checkable 排他＋0 件文言）＋B3（tooltip）＋B5（Clear 確認・DI）＋strings 追加＋Layer A/B。
2. **シェブロン辺解決**: B4（写像追加・タイトルバー接続・dockLocationChanged 追随）＋Layer B。
3. **読み値スクロール**: B6（QScrollArea 化・透過・stretch 移動）＋Layer A honest テスト。
4. **凍結・①ゲート・docs**: realgui 追随/実機確認・前後比較→昇格→DesignSync・design.md 決定履歴（D-2 不採用の記録＋spec §7 supersede＋本 6 修正）・カタログ解消マーク（UX-06/07/31/44・UXG-12/17/27・UX-53 部分）。

## 7. 受け入れ基準

- 誘導文とカウンタの照合が可能（ℹ 表示）・フィルタ状態が常時可視・絞り込み 0 件と診断ゼロが区別可能・メッセージ全文が hover で読める・シェブロンが畳む方向を指す・Clear は確認付き・読み値 20 行超でもウィンドウ縮小可能かつ診断ドック非圧潰。
- 品質ゲート全通過＋realgui フル pass＋凍結（差分限定＋viewport/readout crop 一致）＋DesignSync 再同期。
