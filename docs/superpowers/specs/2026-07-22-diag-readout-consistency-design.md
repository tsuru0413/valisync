# 診断・読み値の整合性修正 設計 — 実バグ/不整合のみ（UX-06/07/31/44・UXG-12/17/27）

- **経緯**: 増分D-2（通知センター型診断）はユーザー決定で**不採用**（2026-07-22・モックアップ提示後「こんな豪華な診断ウィンドウは不要・現状のままで ok」）。本 spec はその代替として「**現状の見た目・構造・挙動契約を維持したまま、実バグと他機能との不整合だけを直す**」6 修正を定義する。デザイン刷新（詳細ペイン・件数内蔵チップ・自動展開・ステータスバー常設カウンタ）は**行わない**。
- **スコープ確定**: B1〜B4（コントローラ検証済みの不整合 4 件）＋ユーザー追加 2 件（B5 Clear 確認・B6 読み値スクロール）。
- **レビュー履歴**: 敵対的 spec レビュー（4 レンズ・22 エージェント・全指摘 Qt 実測検証つき）30 件を反映済み。B6 は初版の「グリッド親差し替えのみ」が実測で崩れた（座標系破綻・幅契約崩壊・透過機構誤り）ため本版で再設計。

## 1. 修正一覧と対象カタログ行

| # | カタログ | 問題（現物確認済み） | 修正 |
|---|---|---|---|
| B1 | UX-31 | フッターカウンタ「⛔ n / ⚠ n」に info が無く、ステータスバー誘導「ℹ 情報 n 件（「診断」ドックを参照）」と着地が矛盾 | カウンタを「⛔ n / ⚠ n / ℹ n」へ |
| B2 | UX-06 | フィルタ 3 ボタンが plain push で選択状態不可視。絞り込み 0 件と診断ゼロが同一文言で、警告のみ存在時に「エラー」絞り込み→「診断はありません」→ゼロと誤認する経路 | 3 ボタンを checkable 排他化＋0 件文言をフィルタ文脈付きに |
| B3 | UX-07 残余 / UXG-12 | メッセージ列 Stretch 済みだが切れた場合の全文閲覧手段がゼロ | メッセージセルに setToolTip(全文) |
| B4 | UX-44 | 展開側タイトルバーのシェブロンが全ドック「>」固定 — レール側は辺対応済み（PR #133）で、下端の診断は畳む方向（下）と矛盾 | シェブロンをドックの辺から解決（レールの逆写像・実行時移動にも追随） |
| B5 | UXG-27 | Clear が確認なし・非可逆で、診断（データ品質の証跡）が誤クリック 1 回で消える | 確認ダイアログ（アーカイブ化は不採用 — 「現状のまま」方針に沿う最小形） |
| B6 | UXG-17 | 読み値ペインに縦スクロールが無く、行数（曲線数に 1:1）がウィンドウ最小**高**を押し上げ、縮小時は診断ドックが先に圧潰される | 行部を QScrollArea 化 — **縦のみ有界化し、幅の契約（内容幅駆動）は sizeHint override で完全保存** |

**UX-53 への波及**: B1 でステータス誘導文とドックカウンタの照合が可能になり「着地で情報が消える」核は解消（部分解消として記録）。恒久残留自体は現状維持。

## 2. 設計

### 2.1 B1 — カウンタへ ℹ 追加

- `DiagnosticsViewModel.counts()` を `(errors, warnings)` → **`(errors, warnings, infos)` の 3-tuple へ拡張**（型変更で unpack が loud-fail）。
- `diagnostics_view._rebuild` のラベルを `f"⛔ {errors} / ⚠ {warnings} / ℹ {infos}"` へ（ASCII スラッシュ・既存 noqa 慣行）。
- **既存テスト追随（レビュー実測の全数）**: tests/gui/test_diagnostics_vm.py:27（`== (1, 2)`）・tests/gui/test_main_window.py:646（`== (0, 0)` — 診断系でないファイルに潜む実例）・tests/gui/test_diagnostics_view.py:75/84/87（「⛔ 0 / ⚠ 0」完全一致 3 assert）。インデックス参照（test_main_window.py:414/431/459 の `counts()[0]/[1]`）は生存。

### 2.2 B2 — フィルタの checkable 排他化＋0 件文言のフィルタ文脈

- すべて/エラー/警告 の 3 `QPushButton` を `setCheckable(True)`＋`QButtonGroup`（exclusive）。初期「すべて」checked。クリアは非 checkable・配置不変。checked の可視表現は Fusion 既定（新規スタイルなし）— 視認不足なら①ゲートで判定し chrome_highlight 枠の qss 断片を追加（トークン新設なし）。
- **checked と `_filter` の単一真実**: 公開 API `set_filter(level)` が**対応ボタンの `setChecked(True)` を同期**する（真実源は `_filter`。QButtonGroup 排他で他は自動 uncheck・`setChecked` は `clicked` を発火しないため再入なし）。既存テストが `set_filter` 直呼びでも checked が追随する。
- プレースホルダ文言:
  - フィルタなし 0 件: 「診断はありません」（現行維持）
  - フィルタあり 0 件: **「{フィルタ名}に該当する診断はありません（全 {n} 件）」**（n = 無フィルタ総数・strings.py へ `DIAG_EMPTY`/`DIAG_EMPTY_FILTERED_TMPL` 追加）
- **supersede 記録（出典訂正済み）**: 「絞り込み 0 件と診断ゼロの同一表示」の by-design は **[2026-07-02-gui-feedback-errors-design.md](2026-07-02-gui-feedback-errors-design.md) §7**（『空時はプレースホルダ』）を根拠に diagnostics_view.py のコードコメント（:137-139）と docstring（:9-11）が明文化している — 本修正で覆す（カタログ UX-06 が「誤認装置」と認定）。**実装タスクはコード側コメント/docstring 2 箇所の更新を含む**。docs/design.md 決定履歴へ記録。

### 2.3 B3 — メッセージ全文ツールチップ

- `_rebuild` のメッセージセル生成時に `item.setToolTip(e.message)`（メッセージ列のみ）。

### 2.4 B4 — シェブロンの辺解決

- `dock_collapse_rail.py` に**折りたたみ方向の写像**を追加: `collapse_chevron_for_area(area) -> str | None` — レールの展開方向写像の逆: Left→`chevron_left`・Right→`chevron_right`・Bottom→`chevron_down`・Top→`chevron_up`。**対応外 area（`NoDockWidgetArea` 等）は None を返し、呼び出し側は早期 return で直前アイコンを維持**。4 アイコンは vendored 済み（icons.py:27-30）— 追加なし。
- `CollapsibleDockTitleBar` は構築時に `main_window.dockWidgetArea(dock)` で初期解決（構築順は addDockWidget→バー構築で有効値 — main_window.py:156/173/187→233 実査済み）し、`dock.dockLocationChanged` へ接続。**発火挙動（実測）: フロート開始時に `NoDockWidgetArea` で発火・再ドッキング/`restoreState()` 時に実辺で発火** — None ガードで直前維持・復元経路は接続だけで追随。
- **テスト可能性のための introspection**: タイトルバーは解決済み意味名を保持し `chevron_icon_name() -> str` を公開する。`icons.icon()` はキャッシュ無しで毎回新規 QIcon（cacheKey 恒等比較は**不成立** — 実測）のため、**テストは (1) 写像関数（純関数）・(2) `chevron_icon_name()` の遷移・(3) cacheKey は「Bottom↔Left 遷移で変化/同辺で不変」の変化検出のみに使用**。
- ツールチップ「折りたたむ」不変。

### 2.5 B5 — Clear 確認ダイアログ

- `clear_diagnostics()` に確認を挿入: 明示 `QMessageBox`（G-14 と同型・file_browser_view.py:112-139 の `_confirm_fn` 属性 DI パターンを踏襲）。
  - 表題「診断のクリア」／本文 **「診断 {n} 件をクリアしますか？この操作は元に戻せません。」**（R-08 確認形・{n}=無フィルタ総数）／Yes→setText**「クリア」**・No→**「キャンセル」**。0 件時は確認なしで no-op。文言は strings.py へ。
- **既存テスト 4 サイトの同時更新が必須**（レビュー実測: DI なしだと offscreen で `QMessageBox.exec()` が**無期限ハング** — pytest-timeout 未導入で CI はジョブタイムアウトまで停止する最悪様態）: tests/gui/test_diagnostics_view.py:44/69/86（`clear_diagnostics()` 直呼び）・:143（`_btn_clear` 実クリック）— `_confirm_fn` stub 注入へ書換。
- **realgui 新設（実ダイアログ実クリック）はモーダル watchdog 必須**: test_readout_realclick.py の `_menu_hang_watchdog` と同型の Escape 送出 watchdog を併設（実クリックが外れた場合のハング保険）。

### 2.6 B6 — 読み値ペインの縦スクロール（再設計 — 縦のみ有界化・幅契約は保存）

**現物の構造（stale 理解の訂正）**: CursorReadout のヘッダ行は**時刻ラベルのみ**（モードトグルは GraphAreaView corner・✕ は計測 IA で撤去済み）。計測モードの**列見出し（A値/min/max/統計）は `_grid` の row 0** として生成される。

**構造変更**:
- `rows_host = QWidget()` を新設し、`_grid`（QGridLayout）・`_placeholder`・末尾 stretch を **rows_host 内へ移す**（placeholder の表示位置を現状の上詰めのまま保つ）。
- `QScrollArea`（`widgetResizable=True`・水平 `ScrollBarAlwaysOff`・垂直 `ScrollBarAsNeeded`・`NoFrame`）で rows_host を包み、outer VBox は「時刻ヘッダ（scroll 外・固定）＋ scroll」となる。
- **列見出し行は行と共にスクロールする（意図的簡易形）** — カタログ UXG-17 修正方向の「列見出し固定」からの逸脱として解消マークに注記する。固定化は 2 グリッド分割＋列幅同期＋差分更新機構（`_layout_sig`/`_full_rebuild`/`_update_in_place`）の再設計を要し「現状のまま」方針に反する。

**幅の契約保存（レビュー Critical/Important 群の根治・クローズ検証で式を確定）**: QScrollArea は sizeHint/minimumSizeHint の**幅も**内容非依存へ落とし（実測 418→120px 等）、(a) splitter でペインを内容幅未満に潰せるようになり水平 AlwaysOff で列が無言クリップ、(b) 凍結ベースライン 03_cursor/04_grid の divider 位置（readout ヒント駆動 — 実測 w=579）が変わる。これを防ぐため:
- **`CursorReadout.sizeHint()`/`minimumSizeHint()` を override**（QScrollArea 自身のヒントはキャッシュ汚染があるため使わない — rows_host/ヘッダのヒントを直接参照）:
  - **幅**: outer レイアウトのマージン込みで「時刻ヘッダと rows_host の内容ヒント幅の max」から合成し、**非オーバーフロー時は現行実装（レイアウト由来）のヒント幅と同値**になること（受け入れ条件: 凍結 03/04 の divider ピクセル一致が機械検証する）。**垂直スクロールバー予約幅（PM_ScrollBarExtent）は縦オーバーフロー時のみ加算**（無条件加算は全状態の divider を +extent 動かし凍結と矛盾・無予約はオーバーフロー時に右端列が extent 分クリップ — 実測で両立不能と確定した設計判断）。
  - **高さ**: `sizeHint` 高さは従来どおり内容ベース（rows_host＋ヘッダから合成）。**`minimumSizeHint` 高さのみ有界化 — 「outer マージン＋時刻ヘッダ高＋行 3 行分」の定数式**（ウィンドウ最小高へ伝搬する値 — UXG-17 の本体）。
- 帰結: 「ペインは内容幅未満に縮まない」現行契約・splitter 初期配分・**非オーバーフロー時（凍結カタログ全状態）の divider 位置を保存**し、縦だけが有界化。**縦オーバーフロー時のみペインが extent 分（約 14px）広がる**のは意図的な新挙動（凍結対象外の状態・§3/§7 の例外として明記）で、水平クリップは常に 0（UXG-18 の横スクロール導入はスコープ外を維持）。

**行クリックの座標整合（レビュー Critical の根治）**: `_row_at` は press 座標（self 空間）をラベル geometry（親空間）と比較する — rows_host 移設で座標系が割れ、**無スクロールでも 1 行ズレの誤行活性化**になる（実測）。`mousePressEvent` で **`pos = self._rows_host.mapFrom(self, pos)` へ写像してから `_row_at` に渡す**（mapFrom はスクロールオフセット込みで整合）。

**背景の透過（機構訂正）**: `QScrollArea.setWidget()` は渡したウィジェットの autoFillBackground を **True に強制する**（実測）。QSS 断片は無効（追加しない）。**`setWidget()` の後に** `scroll.viewport().setAutoFillBackground(False)` と `rows_host.setAutoFillBackground(False)` を明示（順序制約をコメントで固定）。**同値盲点対策**: 現行テーマは `chrome_window == surface_readout_panel` の同値でピクセル比較が盲目 — **`surface_readout_panel` を値分岐させたテーマでペイン面がトークンに追随するピクセルテスト**（既存の値分岐パターン）を必須とする。

**既存挙動の維持**: `updateGeometry` 呼び出し（ちらつき根治 — 増分B）は維持。行クリック・差分更新・凡例⇔計測切替は写像 1 行以外は不変。

## 3. 変更しないもの

- 診断の列構成・ドック構造・既定レイアウト・Clear の配置・フィルタボタンの並び・アイコングリフ（⛔⚠ℹ — D-3 領域）。
- 読み値ペインの列・書式・モード・**幅挙動**（内容幅駆動・内容幅未満に縮まない — §2.6 で明示保存。**例外: 縦オーバーフロー時のみスクロールバー分〔約 14px〕広がる意図的新挙動**）。UXG-18（幅キャップ＋横スクロール）はスコープ外のまま。
- D-2 で提案し不採用となった一切。

## 4. テスト戦略（/gui-test-plan 分析）

- **Layer A**:
  - B1: `counts()` 3-tuple＋ラベル文言（§2.1 の既存 5 assert 追随込み）。
  - B2: **三点結合**で検証 — 各ボタンのクリックで (1) `_filter` 値 (2) 表示行が当該レベルのみ（**error/warning/info を判別可能なシードで** — 1+1 シードは行数が同値で配線取り違えに盲目） (3) 当該ボタン checked。＋ programmatic `set_filter()`→checked 同期・「すべて」初期 checked・フィルタ 0 件文言（警告のみ＋エラーフィルタ→「エラーに該当する診断はありません（全 1 件）」）。排他性そのもの（Qt 保証）の単独 assert はしない。
  - B3: メッセージセル toolTip == 全文。
  - B5: `_confirm_fn` stub で 3 分岐（確認→実行/キャンセル→非実行/0 件→確認なし no-op）＋既存 4 サイトの stub 追随。
  - B6: **実イベント経路で正しい entry_id** — ラベルの `mapTo(readout)` 位置へ合成 QMouseEvent を届け、非スクロール時とスクロール後（`verticalScrollBar().setValue` 後）の両方で期待 entry_id が emit されること（**`activate_row()` 直呼びは B6 の検証として禁止** — emission-only は誤行を緑で通す）。minimumSizeHint 高さが行数非比例で有界（現行の行数比例 ≈16px/行を対照 — honest 実証済み）。**幅契約**: minimumSizeHint 幅が内容幅を保持し splitter で内容幅未満へ縮まない。**値分岐透過テスト**: surface_readout_panel 分岐テーマでペイン面ピクセルがトークン追随。
- **Layer B**:
  - B4: `collapse_chevron_for_area` 純関数の全域（4 辺＋None）・`chevron_icon_name()` の遷移（`addDockWidget(Left)` への実移動・`restoreState` 復元・フロート開始で直前維持）・cacheKey は変化検出のみ。
  - B2: 実クリックで checked 遷移（qtbot）。
- **Layer C（realgui・①ゲート）**:
  - B4: 下端診断のシェブロン「v」・右ドック「>」（現行同値＝無回帰）のスクショ目視。「<」は Layer B の Left 移動で検証（既定レイアウトに左ドックは無い）。
  - B5: 実クリック→実ダイアログ→「クリア」→空＋プレースホルダ（watchdog 併設）。
  - B6: 実表示でウィンドウ縦縮小 — 読み値 20 行超でも診断ドック非圧潰＋読み値側にスクロールバー（実表示必須）。**realgui 追随 3 本**: test_readout_pane_realclick.py（行の値セル実クリック — スクロール域内・座標写像後も正解 entry_id で pass すること）・test_readout_realclick.py:178/210（ペイン中心実右クリック — viewport 経由の contextMenuEvent 伝播を①ゲート前にローカル scoped 実行で確認）。**増分3 の DoD にローカル realgui scoped run を含める**（増分4 まで赤を持ち越さない）。
- **凍結検証**: 想定差分の全数列挙 — **診断ドック内**（カウンタ ℹ 追加・「すべて」ボタンの checked 枠 = 診断が写る全状態×両テーマ・下端タイトルバーのシェブロン > → v〔B4〕）のみ。**読み値ペイン・プロット viewport・divider 位置は §2.6 の幅契約保存によりピクセル一致**（既存の全体比較＋viewport crop で担保 — readout 専用 crop 拡張は不要）。一致しない差分が出た場合は原因を特定し、意図的なら目視承認→ベースライン昇格として記録。

## 5. リスクと対策

| リスク | 対策 |
|---|---|
| B6 の座標写像漏れ・退行 | §2.6 の mapFrom 明記＋Layer A は実イベント経路のみ（直呼び禁止）＋realgui 行クリックが最終防波堤（①ゲート） |
| B6 の幅契約の崩れ（splitter 圧縮・凍結 03/04 divider 移動・水平クリップ） | §2.6 の sizeHint/minimumSizeHint override（rows_host ヒント直接参照）＋Layer A 幅契約 assert＋凍結全体比較 |
| B6 の透過が同値テーマで無音破綻（トークン切断） | setWidget 後の明示 setAutoFillBackground(False)×2＋値分岐ピクセルテスト（凍結比較は同値で盲目のため） |
| B6 がちらつき根治（増分B）を退行 | stretch を rows_host 内へ・updateGeometry 維持・実機で分割ドラッグ目視 |
| B5 の既存テストがモーダルで無期限ハング | §2.5 の 4 サイト同時更新（stub 注入）を実装タスクに列挙・realgui は watchdog 必須 |
| B4 の NoDockWidgetArea | 写像は None 返し＋呼び出し側早期 return（§2.4） |
| B2 の checked と _filter の真実分裂 | set_filter が checked を同期（§2.2）＋同期テスト |
| counts() 3-tuple 化の呼出元漏れ | §2.1 の全数列挙（レビュー実測）＋型変更 loud-fail |
| realgui 掴み点 | 診断ボタン・chevron 掴みは属性参照で非依存（実査済み）。readout 3 本は §4 Layer C の追随対象として明記 |

## 6. 実装増分（writing-plans への入力）

単一ブランチ `feature/diag-readout-consistency`・PR 1 本・凍結/①ゲートは末尾 1 回（ただし増分3 は DoD にローカル realgui scoped run）。

1. **診断ビュー**: B1（VM counts 3-tuple＋既存 5 assert）＋B2（checkable 排他・set_filter 同期・0 件文言・supersede コメント更新）＋B3（tooltip）＋B5（Clear 確認・DI・既存 4 サイト stub 追随・**新設 realgui〔実ダイアログ実クリック＋watchdog〕の作成とローカル scoped 実行**）＋strings 追加。
2. **シェブロン辺解決**: B4（写像 None 契約・chevron_icon_name・dockLocationChanged 追随）＋Layer B。
3. **読み値スクロール**: B6（rows_host＋QScrollArea・sizeHint override〔条件付き予約・minimumSizeHint 高さ=ヘッダ＋3 行分〕・mapFrom 写像・透過 2 点セット・placeholder 同居）＋Layer A（実イベント/幅契約〔非オーバーフロー時ヒント同値含む〕/値分岐透過）＋realgui 3 本追随＋**新設 realgui〔ウィンドウ縦縮小で診断ドック非圧潰＋スクロールバー出現 — UXG-17 受け入れの本体〕**＋ローカル scoped realgui 実行。
4. **凍結・①ゲート・docs**: realgui フル・前後比較（§4 の想定差分照合）→昇格→DesignSync・design.md 決定履歴（D-2 不採用・feedback-errors spec §7 supersede・本 6 修正・UXG-17 列見出し逸脱）・カタログ解消マーク（UX-07/31/44・UXG-12/17 解消／**UX-06・UXG-27 は解消＋残項目の意図的不採用を注記**〔Clear 配置分離・Clear 後のステータス参照更新 — 「現状のまま」方針〕／UX-53 部分）。

## 7. 受け入れ基準

- 誘導文とカウンタの照合が可能（ℹ）・フィルタ状態が常時可視かつ checked と実フィルタが常に一致・絞り込み 0 件と診断ゼロが区別可能・メッセージ全文が hover で読める・シェブロンが畳む方向を指す・Clear は確認付き・読み値 20 行超でもウィンドウ縦縮小可能かつ診断ドック非圧潰・**読み値の行クリックがスクロール前後とも正しい曲線をハイライト**。
- ペイン幅挙動は非オーバーフロー時完全不変（凍結 03/04 divider 一致で機械検証）・縦オーバーフロー時の extent 分拡幅のみ意図的例外。
- 品質ゲート全通過＋realgui フル pass＋凍結（想定差分照合＋viewport crop 一致＋値分岐透過テスト green）＋DesignSync 再同期。
