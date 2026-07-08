# Audit Findings Catalog — 実装済み機能の不足（改善サブスペックの一次情報源）

実ユーザージャーニー（**ファイルを開く → 波形表示 → データ解析**）を対象に実施した2つの監査の全確定所見を、重複統合し ID を付与して管理する台帳。各所見は「**実装済みだが不足**」バケット②の改善サブスペックへ割り当てられており、ロードマップ（[roadmap.md](roadmap.md)）の該当サブスペックから本カタログの ID を参照する。

- **作成**: 2026-07-02
- **監査方法**: 6次元×2ラウンド（①機能ジャーニー ②UI/UX コントロール）を並列コード精読し、各所見を独立エージェントが実コードで敵対的検証（`CONFIRMED`/`PLAUSIBLE`/`REFUTED`）。計 100+ サブエージェント。raw 87 確定所見 → 重複統合後 **64 正準課題**。加えて本監査後、HILS デモ mf4 ジェネレータ開発（2026-07-04）で LD-12（spec 起票時から想定の 2D skip 再現データ）・LD-13（開発中に発見した実バグ）の2件を補遺として追加し、**66 件**。さらに 2026-07-05、ユーザーが実機 GUI 操作で発見した5課題を実コードで解析し、3件を新規（PC-21 CursorReadout のレイアウトずれ・PC-22 カーソル線ホバーのポインタ形状・RN-06 カーソル移動時の統計計算の重さ）として追加、2件を既存 PC-13/PC-14 の具体要件（軸ゾーン別カーソル形状）として反映し、現在は **69 件**。
- **凡例**: 重要度 🔴high / 🟠medium / 🟡low。`kind` = BUG(誤動作) / SILENT(サイレント失敗・誤計算) / MISSING_CONTROL / DISCOVERABILITY(発見困難) / FEEDBACK(状態可視化欠如) / PERF / ROBUSTNESS。
- **注意**: 記載の行番号は監査時点（2026-07-01〜02, main@82c14b9）のもの。着手時に再確認すること。

> **2バケットの定義**
> - **① 今後実装予定**（未着手の新機能）= ロードマップ既存の `gui-derived` / `gui-views` / `gui-script` ＋ Phase3/4。本カタログの対象外（roadmap 参照）。
> - **② 実装済みだが不足**（既存機能の欠陥・改善）= 本カタログ。下記6サブスペックへ割当。

---

## サブスペック別サマリ（バケット②）

| サブスペック | 主眼 | 件数 | 最優先 |
|---|---|---|---|
| [`gui-feedback-errors`](#ss-feedback--gui-feedback-errors) | エラー/診断/状態フィードバックの可視化 | 10 | 🔴 |
| [`gui-shell-controls`](#ss-shell--gui-shell-controls) | シェル操作（File メニュー・タブ/パネル/レイアウト管理・エクスポート導線） | 15 | 🔴 |
| [`gui-plot-analysis-controls`](#ss-plotctl--gui-plot-analysis-controls) | プロット/曲線/軸/カーソルの操作コントロール | 22 | 🟠 |
| [`core-loaders-hardening`](#ss-loaders--core-loaders-hardening) | ローダー堅牢性・対応形式拡張 | 13 | 🔴 |
| [`analysis-correctness`](#ss-analysis--analysis-correctness) | 統計・補間の計算の正しさ | 3 | 🔴 |
| [`rendering-correctness-perf`](#ss-render--rendering-correctness-perf) | 描画の正しさ・LOD/同期の性能 | 6 | 🟠 |

**横断テーマ（最重要）**: 「**サイレント失敗の連鎖**」。`_on_load_error=pass`（FB-01）＋ `Session.load` が成功時の診断を破棄（FB-02）することで、CSV 非対応・拡張子制限・チャンネル skip・空ファイル等の多くの欠陥が一箇所で無言化される。FB-01/FB-02 の解消が LD-01〜05・SH-03 の可視化を一気に前進させるため、**着手順の起点**とする。

---

## SS-FEEDBACK — `gui-feedback-errors`

エラー・診断・状態のユーザー可視化。**最優先**（他サブスペックの欠陥を「気づける」ようにする土台）。

| ID | 重要度 | 課題 | 場所 | ユーザー影響 |
|---|---|---|---|---|
| FB-01 | 🔴 | ✅**解消（PR #37）** `_on_load_error` が `pass`。全ロード失敗（破損/非対応/権限/Data Explorer 経由）が無言。ダイアログもステータス面も無い → 診断記録＋モーダル＋ステータスバー＋ドック自動 raise | `gui/views/main_window.py`（旧 :134）, `data_explorer_view.py:150`（load_handler 経由で合流） | 開けたか失敗したか判別不能。実ファイルの破損/版差で頻発 |
| FB-02 | 🔴 | ✅**解消（PR #37）** `Session.load` が成功時に `result.diagnostics` を破棄。チャンネル skip/空グループ/0ch の警告が構造的に UI へ到達不能 → `LoadOutcome(key, diagnostics)` 化＋Diagnostics ドック表示（LD-03/05 の診断発行は core-loaders-hardening 側で本器に載る） | `core/session.py`（旧 :92） | 一部信号が無言で欠落しても警告が出ない（サイレントなデータ欠損の増幅器） |
| FB-03 | 🟠 | ✅**解消（PR #37）** ロード直後にアクティブファイルが未設定で Channel Browser が空のまま → `_on_loaded` で `set_active_file` | `gui/viewmodels/app_viewmodel.py`（旧 :152） | 開いた直後に「壊れて見える」 |
| FB-04 | 🟠 | ✅**解消（PR #38）** BusyOverlay がラベル/進捗/キャンセルなしの全画面ブロック → ラベル＋キャンセルボタン＋ハイブリッドキャンセル（`Session.load(cancel=...)` 協調的中断＋世代管理・進捗%は非ゴール） | `gui/views/busy_overlay.py`（旧 :15,22） | 重い MDF4 ロード中に何が起きているか不明・中断不可 |
| FB-05 | 🟠 | ✅**解消（PR #38）** 検索0件/未選択ファイルでリストが無言に空・件数表示なし → ヘッダ「file — M ch 中 N 件表示」＋空状態3分類プレースホルダ | `gui/views/channel_browser_view.py`（旧 :41） | 「信号が無い」のか「条件で消えた」のか分からない |
| FB-06 | 🟡 | ✅**解消（PR #37）** ステータスバー未使用（進捗/件数/準備完了/エラーの常設面が無い） → 常設化（準備完了／ロード結果＋警告件数要約） | `gui/views/main_window.py`（旧 :106） | 状態の常設表示先が無い |
| FB-07 | 🟡 | ✅**解消（PR #38）** ウィンドウタイトルが固定「ValiSync」で状態/アクティブファイルを反映しない → 「<basename> — ValiSync」追従 | `gui/views/main_window.py`（旧 :53） | 何を見ているか分からない |
| FB-08 | 🟡 | ✅**解消（PR #38）** 空状態ガイド皆無（File/Channel Browser にプレースホルダなし） → 両 Browser にプレースホルダ（グラフエリアは views 系の表示オブジェクト切替構想へ委譲・spec 境界注記） | `channel_browser_view.py`・`file_browser_view.py`（旧 :41/:42） | 初回ユーザーが取り残される |
| FB-09 | 🟡 | ✅**解消（PR #38）** 表示中ファイルがビューに示されない（コンテキスト不可視） → ChannelBrowser ヘッダにアクティブファイル名（FB-05 と統合） | `gui/viewmodels/channel_browser_vm.py`（旧 :53） | どのファイルの信号か分からない |
| FB-10 | 🟡 | ✅**解消（PR #38）** File Browser が basename のみ → ホバーツールチップ（パス/サイズ/時間範囲/ch数/形式）＋`Session.source_info` 新設 | `gui/viewmodels/file_browser_vm.py`（旧 :70） | ファイルの素性が確認できない |

---

## SS-SHELL — `gui-shell-controls`

グローバルシェルの操作コントロール（メニュー・ツールバー・ショートカット・タブ/パネル/レイアウト管理・エクスポート導線）。**GUI に押せるボタンがほぼ無い**構造の是正。

| ID | 重要度 | 課題 | 場所 | ユーザー影響 |
|---|---|---|---|---|
| SH-01 | ✅解消 | **✅解消（2026-07-08・増分1a）: File>Open＋Ctrl+O＋Welcome 空状態 CTA＋File Browser ボタン＋Recent Files（QSettings MRU・再開可能な絶対パス保存・存在剪定）を既存 _load_file へ集約配線。ShellActions QAction レジストリ新設。CSV Export 導線（SH-03）は増分1b で実装予定。** 〔元課題〕File>Open / Ctrl+O / 最近使ったファイルが皆無（読み込みは D&D か「Data Explorer」ボタンのみ） | `gui/views/main_window.py:97` | 初回ユーザーがデータの開き方に気づけない |
| SH-02 | ✅解消 | **✅解消（2026-07-08・増分2a）: QTabWidget コーナー "+" ボタン＋Ctrl+T で GraphAreaVM.add_tab に配線。** 新規タブを作成する UI が無い（多タブ機能に到達不能） | `gui/views/graph_area_view.py:68` | 実装済みの多タブが使えない |
| SH-03 | ✅解消 | **✅解消（2026-07-08・増分1b）: Export CSV ダイアログ（File>Export…・Ctrl+E・ツールバー）＝ファイル別信号ツリー・初期選択=プロット中・統合タイムライン・フルオプション（区切り/小数/単位行/精度）・オフスレッド書出（BusyOverlay・失敗時モーダル）。CsvExporter を CsvExportOptions で拡張（既定は現行一致）。** 〔元課題〕CSV エクスポート/成果書き出しの導線が GUI に無い（`Session.export_csv` 到達不能） | `gui/views/main_window.py:96` | 解析結果を持ち出せない（ジャーニーの出口欠如） |
| SH-04 | ✅解消 | **✅解消（2026-07-08・増分2a）: setTabsClosable＋tabCloseRequested→remove_tab。最後の1枚は close ボタン抑制。** タブを閉じる UI が無い（`remove_tab` 到達不能） | `gui/views/graph_area_view.py:179` | 増えたタブを整理できない |
| SH-05 | 🟠 | キーボードショートカット/アクセラレータが皆無 | `gui/views/main_window.py:104` | 反復操作が遅い |
| SH-06 | ✅解消 | **✅解消（2026-07-08・増分2b）: パネル chrome 行に「+」/「×」QToolButton を追加し add_panel_requested/remove_panel_requested に配線。set_removable が「×」を連動 disable。右クリックメニュー併存。** 〔元課題〕パネルの追加/削除が右クリック限定・可視ボタンなし | `gui/views/graph_panel_view.py:1776` | パネル分割の発見が困難 |
| SH-07 | ✅解消 | **✅解消（2026-07-08・増分1a）: File Browser ヘッダの開くボタン（ヘッダの開くボタン→open_requested→open_file で File>Open と同じファイル選択ダイアログを開き、空リストの手詰まりを解消）を実装。** 〔元課題〕File Browser にファイルを開く/追加する操作が無い（空リストから前進不能） | `gui/views/file_browser_view.py:34` | File Browser 単体で作業を始められない |
| SH-08 | ✅解消 | **✅解消（2026-07-08・増分2b）: 削除前に QMessageBox.question 確認（注入フック _confirm_fn）＋ヘッダに「閉じる」ボタン。メニュー「Remove File」も確認経由。** 〔元課題〕読み込み済みファイル削除が右クリック限定・確認/取り消しなし | `gui/views/file_browser_view.py:60,63` | 誤操作で即消える |
| SH-09 | 🟠 | データソース永続化が実アプリで無効（毎回消える。`sources_file` 未指定） | `gui/views/data_explorer_view.py:128`（Phase3 persistence と重複領域） | 毎回フォルダ再登録 |
| SH-10 | ✅解消 | **✅解消（2026-07-08・増分2b）: DataExplorer に登録ソース QListWidget（splitter で tree と並置）。選択で tree root 切替。** 〔元課題〕登録データソース一覧が UI に無く複数ソース切替不可 | `gui/views/data_explorer_view.py:137` | 複数フォルダを扱えない |
| SH-11 | 🟡 | レイアウトを既定に戻す「Reset Layout」が無い（乱れたドック配置から復帰不能） | `gui/views/main_window.py:164`（既知の永続化 footgun と関連） | 崩れた配置を戻せない |
| SH-12 | 🟡 | ドック表示トグルが View メニュー限定（ツールバー/タイトルバー導線なし） | `gui/views/main_window.py:96` | ★ユーザー指摘：ドック表示切り替えボタンが無い |
| SH-13 | ✅解消 | **✅解消（2026-07-08・増分2a）: tabBarDoubleClicked→インライン QLineEdit エディタ→rename_tab（1-32字・範囲外は編集継続）。** タブ名リネーム UI が無い（`rename_tab` 到達不能・Tab N 固定） | `gui/views/graph_area_view.py:183` | タブを識別できない |
| SH-14 | 🟡 | ツールバーにアイコン/ツールチップなし・Help/About/バージョンなし | `gui/views/main_window.py:104` | 機能の意味が伝わらない |
| SH-15 | ✅解消 | **✅解消（2026-07-08・増分2b）: Remove Source が不可視ルートでなく選択リスト項目に作用。未選択は statusBar フィードバック。** 〔元課題〕Remove Source が不可視の「現在ルート」に作用し、右クリック削除と操作モデルが不一致・no-op フィードバックなし | `gui/views/data_explorer_view.py:105` | 何が消えるか予測できない |

---

## SS-PLOTCTL — `gui-plot-analysis-controls`

プロット・曲線・Y軸・カーソル・読み取り表の操作コントロールと発見可能性。

| ID | 重要度 | 課題 | 場所 | ユーザー影響 |
|---|---|---|---|---|
| PC-01 | 🔴 | 曲線ごとの 表示ON/OFF・削除・色変更 コントロールが GUI に皆無 | `gui/views/graph_panel_view.py:1776` | 一度載せた曲線を管理できない |
| PC-02 | 🔴 | 信号を波形へ「追加」する可視ボタンが無い（右クリック/正確な D&D のみ） | `gui/views/channel_browser_view.py:57` | 波形表示の最初の一歩が分からない |
| PC-03 | 🔴 | 時間オフセット操作が完全に隠れている（起動導線・アフォーダンス・カーソルヒントなし） | `gui/views/graph_panel_view.py:1582` | 主要解析機能に誰も気づけない |
| PC-04 | 🟠 | 行ダブルクリック/Enter での追加が未接続（最短追加操作が無い） | `gui/views/channel_browser_view.py:64` | 追加に手数がかかる |
| PC-05 | 🟠 | 信号の表示/非表示トグルが UI から到達不能・可視状態フィードバックなし | `gui/views/channel_browser_view.py:102` | 表示中の信号を切り替えられない |
| PC-06 | 🟠 | Y軸の追加/削除/軸ごとオートフィット/数値レンジ設定が無い | `gui/views/graph_panel_view.py:1772` | 複数Y軸を制御しきれない |
| PC-07 | 🟠 | アクティブパネルの可視表示なし・追加が常に `panels[0]` 固定 | `gui/views/main_window.py:143`（対: 挙動バグ） | 複数パネルで意図したパネルに入らない |
| PC-08 | 🟠 | カーソル設置が右クリックのチェックのみ・固定50%・クリック設置/精密指定/キーボード不可 | `graph_panel_view.py:1791,1637` | 任意時刻の計測が多手数・不正確 |
| PC-09 | 🟠 | 補間方式サブメニューが現在選択を示さず（非checkable）読み取り表にも反映されない | `gui/views/graph_panel_view.py:1802` | 現在の補間方式が分からない |
| PC-10 | 🟠 | 読み取り値のコピー/エクスポート手段なし | `gui/views/cursor_readout.py:264` | 計測値を持ち出せない |
| PC-11 | 🟠 | 読み取り表に単位が一切なし（Signal/readout モデルに単位フィールドなし） | `gui/views/cursor_readout.py:131` | km/h か m/s か °C か区別不能 |
| PC-12 | 🟠 | 統計列選択メニュー（列▾）が孤立・どこからも呼ばれない（`build_column_menu`） | `gui/views/cursor_readout.py:182` | 実装済みの列切替が使えない |
| PC-13 | ✅解消 | **✅解消（2026-07-05・増分②・PR #50）: `hoverMoveEvent` の非アクティブ軸を `unsetCursor`→`PointingHandCursor`（「クリックで活性化」）に緩和、アクティブ軸は `cursor_for_local` のゾーン別形状。`cursor_for_local` を `CursorKind` 化し X と流儀統一（ZOOM_V 垂直カスタム/PAN_V=SizeVer/RESIZE_V/MOVE）。** 〔元課題〕Y軸ジェスチャは事前クリック活性化が必須だがヒント/フィードバックなし。**（ユーザー実機要望 2026-07-05）** Y軸ゾーン別カーソルは既に差別化済み（`cursor_for_local:303-326`＝GRIP:SizeVer/FRAME:SizeAll/ZOOM:Cross/PAN:OpenHand）だが `hoverMoveEvent:351-357` の**アクティブ軸ゲートで非アクティブ軸は `unsetCursor`** → 常時効かせるにはゲート緩和が必要。X（PC-14）と流儀統一も検討 | `gui/views/graph_panel_view.py:476`・`_AlignedAxisItem.cursor_for_local:303-326`・`hoverMoveEvent:351-357` | 軸操作の前提が伝わらない |
| PC-14 | ✅解消 | **✅解消（2026-07-05・増分②・PR #50）: `cursor_for_zone` を `CursorKind` 化し X inner=zoom→カスタム水平ズーム [\|→←\|]（BitmapCursor）／outer=pan→`SizeHorCursor` で区別。オフセット誤発火はプロット領域で曲線近傍ホバー時に `SizeHorCursor`（ドラッグ可アフォーダンス）を提示し予測可能化（発火条件は不変）。カスタム QCursor はレジストリ `gui/views/cursor_shapes.py` で生成。** 〔元課題〕X軸 内側=ズーム/外側=パンの境界が不可視・両ゾーン同一カーソル・プロット領域に X パン/ズームなしで左ドラッグがオフセット誤発火。**（ユーザー実機要望 2026-07-05）** 根因: `cursor_for_zone:244-245` が ZONE_X_INNER(zoom)/ZONE_X_OUTER(pan) 双方に `SizeHorCursor` を返し区別不能。要望=パン[←→]（≒`SizeHorCursor`）／ズーム[\|→←\|]。**Qt 標準に「水平拡縮」形状は無い** → `SplitHCursor` 近似か `QCursor(QPixmap)` カスタム。Y（PC-13）と一括で「軸ゾーン別カーソル形状」として設計 | `graph_panel_view.py:244-246,1581,1609,1618` | ズーム/パン操作が予測不能・誤操作 |
| PC-15 | 🟠 | グリッド/対数軸/軸反転などの表示オプションなし | `gui/views/graph_panel_view.py:1005` | 解析に必要な軸表現ができない |
| PC-16 | 🟡 | 読み取り値が固定4桁 `:.4g` で精密読み取り不可 | `gui/views/cursor_readout.py:24` | 微小差を読めない |
| PC-17 | 🟡 | 計測オーバーレイのクリア/閉じる導線が弱く無効化理由の提示もなし | `gui/views/graph_panel_view.py:1799` | 計測を片付けにくい |
| PC-18 | 🟡 | CursorReadout の移動アフォーダンス/曲線操作の入口がなし | `gui/views/cursor_readout.py:264` | 移動できると気づけない |
| PC-19 | 🟡 | チャンネルのツールチップ（単位/ソース/サンプル数）が皆無 | `gui/adapters/qt_signal_models.py:131` | 信号の素性を確認できない |
| PC-20 | 🟡 | 並べ替え/グルーピング/折りたたみなし（多数信号を部分一致フィルタのみで捌く） | `gui/views/channel_browser_view.py:48` | 大量信号を捌けない |
| PC-21 | ✅解消 | **✅解消（2026-07-05・増分①・PR #49）: `_reposition_readout()` を新設し、初回配置と幾何変化（軸/カラム追加・リサイズ via `_sync_overlay_geometry`）で readout をプロット矩形左上へ追従。`CursorReadout.was_user_moved()` 中は抑止しユーザードラッグ位置を尊重、カーソル消去でリセット。** 〔元課題〕**（ユーザー実機発見 2026-07-05・BUG）** CursorReadout（読み取り表）が他操作後にレイアウト崩れ・プロットからずれて表示。根因: readout は plot_widget と兄弟の**レイアウト非管理オーバーレイ**で、初回表示時に一度だけ `move(8,8)`（`_readout_placed` ガード）→ 以後プロット矩形に追従しない。軸/カラム追加で `_reconcile_axes` が `_Y_AXIS_FIXED_WIDTH=72px` ガターを確保しプロット原点が右へずれても readout は widget (8,8) 固定でガター上に残る。パネル縮小リサイズ後も未再配置 | `gui/views/graph_panel_view.py:719,1166-1171`・`_reconcile_axes:885,970-991` | 計測値表示が崩れ、読み取りへの信頼を損なう |
| PC-22 | ✅解消 | **✅解消（2026-07-05・増分②・PR #50）: `_make_cursor_line` 生成直後に `line.setCursor(SizeHorCursor)`（レジストリ `CursorKind.DRAG_H`）で A/B 両線にドラッグ可アフォーダンスを付与。** 〔元課題〕**（ユーザー実機要望 2026-07-05・DISCOVERABILITY）** カーソル縦線ホバー時に色ハイライト（pyqtgraph 既定 hoverPen）は出るが**マウスポインタ形状が変わらない**（矢印のまま）。ドラッグ可能を示す形状（`SizeHorCursor` 等）を足したい。差し込み: `_make_cursor_line:1116-1128` で生成直後に `line.setCursor(...)`（色変化と厳密同期させるなら InfiniteLine subclass で `hoverEvent` オーバーライド） | `gui/views/graph_panel_view.py:1116-1128,712,715` | カーソルを動かせると気づけない |

---

## SS-LOADERS — `core-loaders-hardening`

ローダーの堅牢性と対応形式の拡張。実車ログ特有の異常データで壊れない/黙って落とさないこと。**サイレントなデータ欠損の根治**（可視化側は SS-FEEDBACK）。

| ID | 重要度 | 課題 | 場所 | ユーザー影響 |
|---|---|---|---|---|
| LD-01 | 🔴 | ✅**解消（第2弾）** CSV を `CsvFormatDetector`（先頭行から区切り/ヘッダ/単位行/時間列/信号列を推定・時間単位は既定 sec＋確認）＋`CsvFormatDialog`（確認/微調整・区切りライブ再分割・不変条件で OK 無効化）で開けるように。`main_window._load_file` の CSV プリフライトから `format_resolver`（注入可能）で解決し `session.load(path, fmt)`。キャンセルは中止（エラー無し） | `core/loaders/csv_format_detector.py`・`gui/views/csv_format_dialog.py`・`main_window._load_file`・`session.is_csv` | 主要フォーマット CSV が完全な行き止まり |
| LD-02 | 🔴 | ✅**解消（第2弾）** `MdfLoader`（旧 `Mdf4Loader` をリネーム置換・`mdf_loader.py`）の `supports()` を `.mf4/.mdf/.dat` へ拡張、版判定は asammdf の内容自動判別に委任。MDF3 実ファイルは既存 `select()` 経路でそのまま読め、`file_format` は版に応じ MDF3/MDF4 へ正確化。非MDF/破損は既存 try/except で診断化（クラッシュなし） | `core/loaders/mdf_loader.py` `supports`/`_format_label` | 実務で多い測定ファイルが開けない |
| LD-03 | 🔴 | ✅**解消（PR #39）** MDF4 の非単調/重複タイムスタンプ ch が厳密検証で丸ごと skip → 記録どおり受け入れ＋「非単調 N 箇所・重複 M 点」warning（演算/描画は `Signal.sorted_view()` 整列ビュー・重複は keep-last） | `core/loaders/mdf4_loader.py`（旧 :156） | CAN/イベント駆動ログの信号が無言で欠落 |
| LD-04 | 🔴 | ✅**解消（PR #39）** CSV は1列の非単調/重複でファイル全体が読み込み失敗 → MDF4 と対称化（受け入れ＋ファイル単位 warning） | `core/loaders/csv_loader.py`（旧 :176） | 1列の乱れで全体が開けない |
| LD-05 | 🟠 | ✅**解消（PR #39）** チャンネル0本の MDF4 も無言で「成功」 → 「チャンネルが 0 本」warning（R2 の no_channels プレースホルダと接続） | `core/loaders/mdf4_loader.py`（旧 :164） | 開いたのに解析へ進めない |
| LD-06 | 🟠 | ✅**解消（PR #39）** CSV の `'nan'/'inf'` 文字列が無言採用 → 受け入れ＋列ごとの件数 warning（統計側の防御は AN-01） | `core/loaders/csv_loader.py`（旧 :151） | 下流の統計/補間を Inf が誤誘導 |
| LD-07 | 🟠 | ✅**解消（第3弾・PR #43）** MDF4 の enum/状態信号が生値で生存し `Signal.metadata['value_labels']` に変換表を保持（カーソル readout・ChannelBrowser tooltip に併記）。文字列(VLSD)チャンネルは対象外＝従来どおり non-numeric skip（第3弾 spec §5 で明示的にスコープ外・必要になれば別途起票） | `core/loaders/mdf4_loader.py`（旧 :54） | 状態信号の意味が失われる/消える |
| LD-08 | 🟠 | ✅**解消（PR #39）** CSV 同名ヘッダ列で重複 `Signal.name` を生成 → MDF4 と同一の `name[idx]` 方式で曖昧化＋warning | `core/loaders/csv_loader.py`（旧 :83） | 信号の取り違え |
| LD-09 | 🟡 | ✅**解消（PR #39）** ヘッダのみ CSV が長さ0の空信号を無言生成 → 成功＋「データ行が 0 行」warning | `core/loaders/csv_loader.py`（旧 :166） | 何も描画されない理由が不明 |
| LD-10 | 🟡 | ✅**解消（第3弾・PR #43）** `select()` ベース刷新＋共有マスタ／ゼロコピー化で大容量 MDF4 の配列多重コピーを解消。**実測 before（2026-07-04・hils 2.01GB/171ch・Win11）: ロード 7.8 秒・ピーク +7.3GB → after（2026-07-05・同ファイル・同環境）: ロード 3.05 秒・ピーク +2.53GB**（quick 0.17GB: before 0.9 秒/+0.66GB → after 0.79 秒/+0.445GB）。受け入れ基準（ピーク増分 ≤+3.0GB・時間 ≤7.8 秒）を充足 | `core/loaders/mdf4_loader.py`（旧 :134） | 大きいログでメモリ不足（2GB 級ログで RAM 8GB 占有を確認 — 本番相当ファイルで実害域） |
| LD-11 | 🟡 | ✅**仕様と判断（2026-07-05 ユーザー決定）** 同一ファイル二重読み込みで別グループ増殖する現状挙動は仕様として許容する（同一パス再読込は別グループとして扱う）。ファイル更新に追従する再読込操作が必要になれば別途起票する | `core/loaders/signal_group_manager.py:24` | 重複エントリで混乱（仕様として許容） |
| LD-12 | 🟠 | ✅**解消（第3弾・PR #43）** 多次元/構造化チャンネルを列/フィールド単位（`Name[i]`/`Name.field`）へ展開して表示可能化（展開時に `info` 診断を emit）。**LD-14 で改訂**: 「列数上限なし」を per-channel 1024 列ガードへ変更（1024 以下は自動展開のまま・超過はユーザー確認で展開/スキップ） | `core/loaders/mdf4_loader.py`（旧 :140-150） | CANape 計測の物標リストが構造化格納だと丸ごと見えない（LD-07 と統合実装） |
| LD-13 | 🟠 | ✅**解消（第3弾・PR #43）** 読み取りパスを `select(ignore_value2text_conversions=True, copy_master=False)` ベースへ刷新し、value2text conversion 付きチャンネルも生値で生存するように修正 | `core/loaders/mdf4_loader.py`（旧 :56/:79/:97） | enum 信号が診断1行を残して不可視。修正経路は `select()` 直接使用または `iter_groups()` 系への切替（LD-07 と同時対応）。発見経緯: HILS デモ mf4 の value2text 埋込テスト（詳細 `.superpowers/sdd/task-2-report.md`） |
| LD-14 | 🟠 | ✅**解消（LD-14）** `_explode_samples` を任意 ndim の多段フラット展開（`Name[i][j]…`）へ再帰化し、3D 以上の物標行列も展開可能に。併せて per-channel の展開列数が 1024 を超えるチャンネルは、本読み前の 1 レコードプローブで検出し GUI ポップアップ（チェックボックス一覧）で展開/スキップを選択（ヘッドレスは全スキップ＋警告）。承認されない超過は本読み entries からも除外（メモリ/時間も節約） | `core/loaders/mdf4_loader.py` `_flatten`/`_scan_oversized`・`gui/views/expansion_dialog.py`・`gui/workers/expansion_confirmer.py` | ndim≥3 の物標行列が消失／深い展開の列爆発が無制御（LD-12 の後続・「iter_channels は ndim≥3 に対応できているか」の検討で確定） |

---

## SS-ANALYSIS — `analysis-correctness`

統計・補間の計算の正しさ。**サイレントな誤計算の根治**。

| ID | 重要度 | 課題 | 場所 | ユーザー影響 |
|---|---|---|---|---|
| AN-01 | 🔴 | ✅**解消** 範囲統計を `Signal.finite_view()`（値が非有限のサンプルを除いた時系列ビュー）で算出。有限値のみで mean/max/min/std を計算し `count` は範囲内の有限サンプル数。NaN/Inf を一律 `np.isfinite` で除外。範囲内が全て非有限なら count=0・全 NaN | `core/statistics/range_stats.py:44`・`core/models/signal.py` `finite_view` | 9999/10000 が有効でも統計が全て `nan`。R17 範囲統計が誤誘導 |
| AN-02 | 🟡 | ✅**解消** 補間を `finite_view()` へ切替 — NaN/Inf サンプルを欠測として除外し、前後の有限サンプル間で補間（LINEAR/ZOH/NEAREST いずれも有限基準）。散在 NaN でもカーソル値が読める | `core/interpolation/interpolator.py:33`・`signal.py` `finite_view` | 無効サンプル散在で読み取りが広範囲で `nan` |
| AN-03 | 🟡 | ✅**解消** 単一有限サンプルは ZOH 前方保持（`t≥ts0` で値・`t<ts0` は None）。方式に依らず保持 | `core/interpolation/interpolator.py:41` | 単一サンプル信号の値が読めない |

---

## SS-RENDER — `rendering-correctness-perf`

描画の正しさと LOD/同期の性能。

| ID | 重要度 | 課題 | 場所 | ユーザー影響 |
|---|---|---|---|---|
| RN-01 | 🔴 | ✅**解消** X 窓スライスを窓外の隣接サンプル1点ずつ（`lo_idx-1`/`hi_idx+1`・両端クランプ）まで拡張し、窓を横切る線分の端点を保持。窓内にサンプルが無くても線が描かれ、疎信号のズーム時消失を解消（窓が信号域外なら境界1点は可視域外でクリップ＝外挿の捏造なし） | `gui/viewmodels/graph_panel_vm.py` `render_data` | 低頻度信号がズームで消失（サイレント失敗） |
| RN-02 | 🟠 | ✅**解消** `_x_range_is_auto` フラグを導入し、自動フィット中は追加信号のたび x_range を全信号の時間和集合へ拡張（`None` チェックだけだと初回オートフィット後の非 None を手動と誤認していた）。手動ズーム後（`set_x_range`）は尊重し `reset_x` が受け皿。X 同期は `set_x_range` 経由で手動追従 | `gui/viewmodels/graph_panel_vm.py` `_auto_fit_ranges`/`set_x_range`/`reset_x` | 別録画/2本目の信号が見えない |
| RN-03 | 🟡 | リサイズ毎に全曲線 LOD 再計算（キャッシュ全破棄） | `gui/views/graph_panel_view.py:1760` | 高さ変更だけで無駄に再計算 |
| RN-04 | 🟡 | X 同期が全パネルへ扇状展開・UI スレッドで同期的に全 LOD 再計算 | `gui/viewmodels/graph_area_vm.py:247` | 多パネルで同期操作が重い |
| RN-05 | 🟡 | 定数信号が零幅 `y_range=(v,v)` で Y 軸目盛り退化 | `gui/viewmodels/y_axis_vm.py:49` | 定数信号の軸が情報を持たない |
| RN-06 | ✅解消 | **✅解消（2026-07-05・増分①・PR #49）: 計測で「Global=interpolate は実質タダ／Delta の範囲統計だけが計算量ボトルネック（20信号×1M=191ms）」と判明。範囲統計を平方分割 O(√n) 化（`RangeStatIndex`・並列分散マージ Chan/Welford で数値安定・命題1-6＋property-based で数学的正当性を実証）し `compute_statistics` へ透過委譲、`cursor_readout` を全 QLabel 破棄再生成から `setText` 差分更新へ。スレッド/間引き不採用で遅延ゼロの真リアルタイムを維持（20信号×1M で 191ms→<1ms）。** 〔元課題〕**（ユーザー実機発見 2026-07-05・PERF）** カーソルドラッグ移動が重くスムーズに更新されない（更新自体は維持したい）。根因: `InfiniteLine.sigPositionChanged` がドラッグ中の移動ごとに発火 → `set_cursor` → **A カーソルは全兄弟パネルへブロードキャスト**（`propagate_cursor:252`）→ 各パネルで**可視全信号を毎フレーム `interpolate`**（Global）／さらに **`compute_statistics` を範囲全区間で毎フレーム**（Delta）→ `cursor_readout._rebuild` で**全 QLabel 破棄再生成**。throttle/debounce/差分更新は皆無 | `graph_panel_view.py:1127,1175-1183,1138`・`graph_panel_vm.py:747-774,822-871`・`cursor_readout.py:236-274`・`graph_area_vm.py:252` | カーソル計測のスムーズさが損なわれ主要操作が重い |

---

## 検証で除外した所見（透明性のため）

| 所見 | 判定 | 理由 |
|---|---|---|
| Data Explorer 標準ロードが GUI スレッドで同期実行 | REFUTED | 実際は off-thread（LoadController 経由） |
| 値に含まれる ±Inf がそのまま描画され Y オートフィットが壊れる | REFUTED | `isfinite` で除外済み |
| 「Add to Active Panel」以外にパネル/軸の指定が無い（どこに入るか事前選択不可） | REFUTED | 別経路の代替提供あり（PC-07 として挙動側のみ採用） |

---

## 推奨着手順（コスパ順）

1. **SS-FEEDBACK（FB-01/FB-02）** — サイレント失敗連鎖の起点を断つ。最小コストで LD-01〜05・SH-03 の可視性が改善。
2. **SS-ANALYSIS（AN-01）＋ SS-RENDER（RN-01）** — 解析の正しさに直結する2つの誤り（統計 NaN 汚染・ズーム時の疎信号消失）。
3. **SS-LOADERS（LD-01/LD-02）** — CSV ピッカー＋MDF 拡張子拡張で「開く」経路の穴埋め。
4. **SS-SHELL（SH-01/SH-03）** — File メニュー/Open と CSV エクスポート配線でジャーニーの入口と出口。
5. **SS-PLOTCTL** — 可視コントロール（曲線管理・追加ボタン・オフセット導線）で操作性を底上げ。

各サブスペックは着手時に `brainstorming`（設計 spec）→ `writing-plans`（実装プラン）から始め、本カタログの ID を要件トレーサビリティの参照点として使う。
