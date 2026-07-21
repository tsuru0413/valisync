# 増分D-1 文言 OS — UI 文言インベントリ（付録）

> [2026-07-22-incd-strings-os-design.md](2026-07-22-incd-strings-os-design.md) の付録。
> 2026-07-22 時点の全ユーザー可視文言スナップショット（283 件・workflow 全域スイープ）。
> **行番号は撮影時点の値** — 実装時は文言そのもので grep して位置を再解決する。
> 「提案」は対訳表・表記規約適用後の文言案。設計判断（判断点 #1-13）の確定で変わる行は spec が優先。

| クラスタ | 件数 | 内訳 (ja/en/mixed) |
|---|---|---|
| shell | 68 | 37 / 28 / 3 |
| dialogs | 53 | 42 / 6 / 5 |
| graph | 92 | 67 / 20 / 5 |
| browsers | 38 | 13 / 23 / 2 |
| core | 32 | 13 / 14 / 5 |
| **計** | **283** | **172 / 91 / 20** |

## シェル（main_window / shell_actions / welcome / busy_overlay / recent_files）

| file:line | surface | lang | 現文言 | 提案 | note |
|---|---|---|---|---|---|
| busy_overlay.py:25 | label | ja | 読み込み中… | 読み込み中… | オーバーレイの既定文言。実運用では LoadController が set_message で「{ファイル名} を読み込み中…」等（別クラスタ workers/）に上書きするため、既定値が見えるのは上書き前の一瞬/テストのみ |
| busy_overlay.py:33 | button | ja | キャンセル | キャンセル | 既に日本語。ハイブリッドキャンセル（FB-04/05 系）の入口 |
| main_window.py:140 | title | en | File Browser | ファイルブラウザ | QDockWidget windowTitle。View メニュー/ツールバーの toggleViewAction 文言もここから派生。L227（折りたたみタイトルバー）・L853（レールタブ）の複製と要同期 — 単一定数化推奨 |
| main_window.py:157 | title | en | Channel Browser | チャンネルブラウザ | QDockWidget windowTitle。toggleViewAction 文言も派生。L228・L854 の複製と要同期 |
| main_window.py:227 | header | en | File Browser | ファイルブラウザ | CollapsibleDockTitleBar のタイトル。L140 の dock windowTitle と重複定義 — 訳語は必ず一致させる |
| main_window.py:228 | header | en | Channel Browser | チャンネルブラウザ | CollapsibleDockTitleBar のタイトル。L157 と重複定義 |
| main_window.py:229 | header | en | Diagnostics | 診断 | CollapsibleDockTitleBar のタイトル。DiagnosticsView 自身の windowTitle（diagnostics_view.py・別クラスタ）と要整合。L855 とも重複。L434/436 のステータス文言「Diagnostics を参照」もこの訳語に追随 |
| main_window.py:262 | menu | en | &File | ファイル | ニーモニクス提案: 「ファイル(&F)」 |
| main_window.py:265 | menu | en | Recent Files | 最近使ったファイル | ニーモニクス提案: 「最近使ったファイル(&R)」。Windows 標準表現に合わせた |
| main_window.py:268 | menu | en | E&xit | 終了 | ニーモニクス提案: 「終了(&X)」。Ctrl+Q ショートカット表示は Qt が自動併記 |
| main_window.py:275 | menu | en | &View | 表示 | ニーモニクス提案: 「表示(&V)」 |
| main_window.py:282 | menu | ja | テーマ | テーマ | 既に日本語。ニーモニクス提案: 「テーマ(&T)」 |
| main_window.py:287 | menu | ja | ライト | ライト | テーマ radio。L925 のステータス用 dict と同語 — 定数共有推奨 |
| main_window.py:288 | menu | ja | ダーク | ダーク | テーマ radio。L926 と同語 |
| main_window.py:289 | menu | ja | オート (OS に合わせる) | オート (OS に合わせる) | OS は技術トークンとして ja 判定。L927 のステータス用は補足なしの「オート」 |
| main_window.py:300 | menu | en | Reset Layout | レイアウトをリセット | ニーモニクス不要（サブ項目・衝突回避優先） |
| main_window.py:305 | menu | en | &Analyze | 解析 | ニーモニクス提案: 「解析(&A)」。配下の解析系 QAction（analysis_actions.py・別クラスタ）と語調統一要 |
| main_window.py:310 | menu | ja | 補間方式 | 補間方式 | 既に日本語。CursorReadout ヘッダの補間方式表示（別クラスタ）と用語一致要 |
| main_window.py:320 | menu | en | &Help | ヘルプ | ニーモニクス提案: 「ヘルプ(&H)」 |
| main_window.py:321 | menu | mixed | &About ValiSync | ValiSync について | ニーモニクス提案: 「ValiSync について(&A)」。ValiSync はブランド名で据え置き。L651 のダイアログタイトルと要一致 |
| main_window.py:325 | context_menu | en | Main | メイン | QToolBar タイトル。ツールバー/ドック領域を右クリックした際のトグルメニューに表示される（見落としやすい可視文言） |
| main_window.py:332 | button | en | Data Explorer | データエクスプローラ | ツールバー QAction テキスト。tooltip/statusTip（L335/336）は既に「データエクスプローラ」表記で用語は確定済み |
| main_window.py:335 | tooltip | ja | データエクスプローラを開く | データエクスプローラを開く | 既に日本語 |
| main_window.py:336 | status | ja | データエクスプローラを開く | データエクスプローラを開く | statusTip（hover 時に MainWindow.event 経由で右ステータスラベルへ流れる） |
| main_window.py:347 | status | ja | 準備完了 | 準備完了 | 起動直後の初期ステータス（FB-06）。既に日本語 |
| main_window.py:429 | status | ja | {source} を読み込みました | {source} を読み込みました | 動的 f-string テンプレート。{source}=Session.source_name（basename）。語調の基準例そのもの |
| main_window.py:434 | status | mixed |  ・ ⚠ {n_alert} 件の診断（Diagnostics を参照） |  ・ ⚠ {n_alert} 件の診断（診断パネルを参照） | L429 のテンプレートへ連結される。「Diagnostics」はドック名参照 — L229 の訳語決定に追随させる（「診断」×2 の重複が気になる場合は「{n} 件の警告/エラー」も候補）。⚠ 絵文字グリフの Lucide 置換は反復で個別判断（CLAUDE.md 記載の方針） |
| main_window.py:436 | status | mixed |  ・ ℹ {n_info} 件の情報（Diagnostics を参照） |  ・ ℹ {n_info} 件の情報（診断パネルを参照） | L434 と同様 — ドック名訳語に追随。ℹ グリフも同判断 |
| main_window.py:459 | status | ja | ⛔ 読み込み失敗: {source} | ⛔ 読み込み失敗: {source} | 動的テンプレート。⛔ グリフ置換は反復で個別判断 |
| main_window.py:462 | dialog | en | OK | OK | Qt 標準ボタン（QMessageBox.critical/about 共通・L462/616/651）。リテラルは存在せず Qt 供給 — QTranslator（qtbase_ja）導入で自動和訳される。日本語 UI でも「OK」据え置きが慣例のため proposed は同値。指示に従い 1 エントリとして計上 |
| main_window.py:464 | dialog | ja | 読み込みエラー | 読み込みエラー | QMessageBox.critical のタイトル。既に日本語 |
| main_window.py:465 | dialog | ja | {source} を読み込めませんでした。\n\n{messages} | {source} を読み込めませんでした。\n\n{messages} | 本文テンプレート。{messages}=例外由来（'; '.join）で英語になりうるが動的データのため文言 OS の対象外 |
| main_window.py:470 | status | ja | キャンセルしました: {path.name} | キャンセルしました: {path.name} | 動的テンプレート。ユーザー起点の正常系（モーダルなし・spec §6） |
| main_window.py:516 | title | en | ValiSync | ValiSync | ウィンドウタイトル（アクティブファイルなし時）。ブランド名で翻訳不要。L521 にも同一リテラル（KeyError フォールバック） |
| main_window.py:523 | title | en | {name} — ValiSync | {name} — ValiSync | 動的テンプレート（FB-07）。「ファイル名 — アプリ名」は日本語 Windows でも標準の並びのため据え置き提案 |
| main_window.py:571 | dialog | ja | 計測ファイル (*.mf4 *.mdf *.dat *.csv);;すべてのファイル (*) | 計測ファイル (*.mf4 *.mdf *.dat *.csv);;すべてのファイル (*) | QFileDialog のファイル種別フィルタ。既に日本語（拡張子は技術トークン） |
| main_window.py:580 | dialog | ja | 計測ファイルを開く | 計測ファイルを開く | QFileDialog.getOpenFileName のキャプション。既に日本語。Welcome の見出し（welcome_view.py L37）・ShellActions statusTip（L27）と同語で用語統一済み |
| main_window.py:608 | status | ja | エクスポートしました: {req.output_path.name} | エクスポートしました: {req.output_path.name} | 動的テンプレート。語調基準（〜しました）に既に一致 |
| main_window.py:615 | status | ja | ⛔ エクスポート失敗: {err} | ⛔ エクスポート失敗: {err} | 動的テンプレート。{err} は例外文字列（動的データ） |
| main_window.py:617 | dialog | ja | エクスポートエラー | エクスポートエラー | QMessageBox.critical のタイトル。既に日本語（同一行に本文もあり — 別エントリ） |
| main_window.py:617 | dialog | ja | CSV を書き出せませんでした。\n\n{err} | CSV を書き出せませんでした。\n\n{err} | 本文テンプレート。CSV は技術トークンとして ja 判定 |
| main_window.py:634 | menu | ja | （履歴なし） | （履歴なし） | Recent Files メニューの空状態（disabled 項目）。既に日本語・全角括弧（noqa: RUF001 済） |
| main_window.py:638 | menu | en | {path} | {path} | Recent Files の各項目=フルパスの純データ。i18n 対象外だが可視文言として計上。長パスの省略は Welcome 側（ElideMiddle）と非対称 — メニュー側は無省略 |
| main_window.py:647 | other | en | unknown | 不明 | バージョン取得失敗時のフォールバック。L648 の f"v{ver}" に埋め込まれ「vunknown」と表示される — 「不明」に変えるなら「v不明」を避ける表示形（例: バージョン不明）の再考が必要 |
| main_window.py:648 | dialog | ja | ValiSync v{ver} — ADAS 信号解析デスクトップ | ValiSync v{ver} — ADAS 信号解析デスクトップ | About 本文テンプレート。ブランド名/ADAS は据え置きで既に日本語一次 |
| main_window.py:651 | dialog | en | About ValiSync | ValiSync について | QMessageBox.about のタイトル。メニュー項目 L321 と要一致 |
| main_window.py:731 | status | en | A {a:.3f} s | A {a:.3f} s | ステータスバー左の計測即値（カーソル A・mono）。カーソル名/単位は国際表記のため翻訳不要 |
| main_window.py:732 | status | en | B {b:.3f} s | B {b:.3f} s | 計測即値（カーソル B）。翻訳不要 |
| main_window.py:734 | status | en | Δt {b - a:.3f} s | Δt {b - a:.3f} s | 計測即値（Δt）。Δt は解析系の確立表記のため翻訳不要 |
| main_window.py:853 | label | en | File Browser | ファイルブラウザ | 畳んだドックの辺レールタブ文言。L140/L227 と三重定義 — 単一定数化推奨 |
| main_window.py:854 | label | en | Channel Browser | チャンネルブラウザ | レールタブ文言。L157/L228 と三重定義 |
| main_window.py:855 | label | en | Diagnostics | 診断 | レールタブ文言。L229 と重複・DiagnosticsView（別クラスタ）と要整合 |
| main_window.py:925 | status | ja | ライト | ライト | L930 のステータステンプレートに埋め込まれるラベル。メニュー L287 と定数共有推奨 |
| main_window.py:926 | status | ja | ダーク | ダーク | 同上（L288 と共有推奨） |
| main_window.py:927 | status | ja | オート | オート | 同上。メニュー側 L289 は「オート (OS に合わせる)」と補足付きで意図的に非対称 |
| main_window.py:930 | status | ja | テーマを「{label}」に変更しました。再起動で反映されます | テーマを「{label}」に変更しました。再起動で反映されます | 動的テンプレート（timeout 8s）。{label}=L925-927 の dict 値。語調基準に一致 |
| shell_actions.py:24 | menu | ja | 開く… | 開く… | File メニュー＋ツールバー共有 QAction。ニーモニクス提案: 「開く(&O)…」 |
| shell_actions.py:27 | status | ja | 計測ファイルを開く | 計測ファイルを開く | statusTip 兼 tooltip 基底（tooltip は L57 で「{status} (Ctrl+O)」に合成）。既に日本語 |
| shell_actions.py:31 | menu | ja | フォルダを開く… | フォルダを開く… | ニーモニクス提案: 「フォルダを開く(&F)…」（File メニュー内スコープなので親メニューの &F と衝突しない） |
| shell_actions.py:34 | status | ja | データソースフォルダを登録する | データソースフォルダを登録する | statusTip 兼 tooltip 基底。既に日本語 |
| shell_actions.py:38 | menu | ja | エクスポート… | エクスポート… | ニーモニクス提案: 「エクスポート(&E)…」。データ読込まで disabled |
| shell_actions.py:41 | status | ja | 表示中の信号を CSV に書き出す | 表示中の信号を CSV に書き出す | statusTip 兼 tooltip 基底。CSV は技術トークンとして ja 判定 |
| shell_actions.py:57 | tooltip | ja | {status} ({shortcut}) | {status} ({shortcut}) | tooltip 合成テンプレート（言語中立の書式）。合成結果は日本語＋ショートカット表記のため据え置き |
| welcome_view.py:37 | label | ja | 計測ファイルを開く | 計測ファイルを開く | Welcome 空状態の見出し。既に日本語・QFileDialog キャプション（main_window.py L580）と同語 |
| welcome_view.py:39 | label | ja | mf4 / mdf / dat / csv をドラッグ&ドロップ、または下のボタンから | mf4 / mdf / dat / csv をドラッグ&ドロップ、または下のボタンから | 空状態の補助説明。拡張子は技術トークンとして ja 判定 |
| welcome_view.py:43 | button | ja | 計測ファイルを開く  (Ctrl+O) | 計測ファイルを開く  (Ctrl+O) | Welcome CTA ボタン。ショートカット併記を手書きしており ShellActions の Ctrl+O 定義（shell_actions.py L26）と重複 — ショートカット変更時に stale になる罠。二連スペースは原文どおり |
| welcome_view.py:77 | button | en | {path を ElideMiddle で省略した表示} | {path を ElideMiddle で省略した表示} | Recent 行ボタンのラベル=パスの純データ（FU-04 の 360px 省略）。i18n 対象外だが可視文言として計上 |
| welcome_view.py:79 | tooltip | en | {path} | {path} | Recent 行ボタンの tooltip=フルパスの純データ。i18n 対象外 |

## ダイアログ（export_csv / csv_format / expansion / signal_preview）

| file:line | surface | lang | 現文言 | 提案 | note |
|---|---|---|---|---|---|
| csv_format_dialog.py:22 | label | ja | カンマ (,) | カンマ (,) | _DELIM_LABEL — export_csv_dialog.py:42 の _DELIMS と重複定義。文言 OS 化の際は共通辞書へ集約候補 |
| csv_format_dialog.py:23 | label | ja | タブ | タブ |  |
| csv_format_dialog.py:24 | label | ja | セミコロン (;) | セミコロン (;) |  |
| csv_format_dialog.py:25 | label | ja | スペース | スペース |  |
| csv_format_dialog.py:34 | title | mixed | CSV フォーマットの確認 | CSV フォーマットの確認 | CSV は頭字語のため実質日本語一次・変更不要 |
| csv_format_dialog.py:40 | dialog | ja | 注意: {notes} | 注意: {notes} | 動的バナー（notes を「 / 」連結）。notes 実体はクラスタ外 valisync/core/loaders/csv_format_detector.py:117,119,216 — 117/119 は日本語済みだが 216 は f"自動構築に失敗: {exc}" で英語例外文が混入しうる |
| csv_format_dialog.py:53 | label | ja | 区切り | 区切り | export_csv_dialog.py:127 と同語 — 用語統一済み |
| csv_format_dialog.py:57 | label | ja | ヘッダ行あり | ヘッダ行あり |  |
| csv_format_dialog.py:61 | label | ja | 単位行あり | 単位行あり | export_csv_dialog.py:133 は「単位行を出力」— 入力/出力で文脈が違うため語形差は妥当 |
| csv_format_dialog.py:66 | label | ja | 時間列 | 時間列 |  |
| csv_format_dialog.py:69 | label | en | sec | sec | 重要: currentText() が FormatDefinition.timestamp_unit のデータ値としてそのまま使われる（line 130・format_def.py は 'sec'/'msec' のみ受理）。表示を「秒」に訳すなら addItem(表示, userData) 分離が必須 — 据え置きが安全 |
| csv_format_dialog.py:69 | label | en | msec | msec | 同上（データ値兼用のため据え置き推奨） |
| csv_format_dialog.py:71 | label | ja | 時間単位 | 時間単位 |  |
| csv_format_dialog.py:76 | label | ja | 信号列 開始 | 信号列 開始 |  |
| csv_format_dialog.py:81 | label | ja | 信号列 終了 | 信号列 終了 |  |
| csv_format_dialog.py:89 | button | en | OK / Cancel | OK / キャンセル | QDialogButtonBox 標準ボタン（無翻訳の Qt 英語）。qtbase_ja QTranslator 導入で一括日本語化可能 |
| csv_format_dialog.py:137 | diagnostic | en | {exc} | {exc} | FormatDefinition の ValueError をエラーラベルへ転写する動的文言。実体はクラスタ外 valisync/core/models/format_def.py:36-57 で完全英語（例 "timestamp_column must be 0-255, got 300"）— ユーザー可視の英語診断の代表例。日本語文言案（例「時間列は 0–255 の範囲で指定してください」「時間列は信号列の範囲と重ねられません」）を GUI 写像層か core 側で用意する判断要 |
| expansion_dialog.py:53 | title | ja | 大きな信号の展開確認 | 大きな信号の展開確認 |  |
| expansion_dialog.py:60 | dialog | ja | 以下の信号は展開すると列数が上限（{EXPANSION_COLUMN_LIMIT}）を超えます。
展開するものを選択してください（未選択はスキップ）。 | 以下の信号は展開すると列数が上限（{EXPANSION_COLUMN_LIMIT}）を超えます。
展開するものを選択してください（未選択はスキップ）。 | f-string テンプレート（定数埋め込み）。全角括弧に noqa: RUF001 既設 — 括弧幅方針を全体で決める際の参照点 |
| expansion_dialog.py:71 | label | ja | {name} — {column_count} 列 | {name} — {column_count} 列 | per-channel チェックボックスの動的テンプレート。{name} は信号名データ。em-dash 区切りは readout 系の「名前｜A値」等と別様式 — 統一判断は任意 |
| expansion_dialog.py:92 | button | ja | すべて展開 | すべて展開 | ニーモニクス案: 「すべて展開(&E)」 |
| expansion_dialog.py:93 | button | ja | すべてスキップ | すべてスキップ | ニーモニクス案: 「すべてスキップ(&S)」 |
| expansion_dialog.py:100 | button | en | OK / Cancel | OK / キャンセル | QDialogButtonBox 標準ボタン。qtbase_ja QTranslator 導入で一括日本語化可能 |
| expansion_dialog.py:124 | status | ja | 展開後の追加列数: {total} | 展開後の追加列数: {total} | チェック変更ごとに更新される動的合計ラベル |
| export_csv_dialog.py:42 | label | ja | カンマ (,) | カンマ (,) | _DELIMS の区切りコンボ項目。記号併記の半角括弧は定型として維持可（本文側は全角括弧で括弧幅が混在 — 方針統一の判断要） |
| export_csv_dialog.py:43 | label | ja | セミコロン (;) | セミコロン (;) |  |
| export_csv_dialog.py:44 | label | ja | タブ | タブ |  |
| export_csv_dialog.py:45 | label | ja | スペース | スペース |  |
| export_csv_dialog.py:47 | label | ja | ピリオド (.) | ピリオド (.) | _DECIMALS の小数点コンボ項目 |
| export_csv_dialog.py:47 | label | ja | カンマ (,) | カンマ (,) | _DECIMALS 側の同名項目（line 42 とは別エントリ） |
| export_csv_dialog.py:68 | title | mixed | CSV エクスポート | CSV エクスポート | CSV は定着した頭字語のため日本語一次として妥当・変更不要 |
| export_csv_dialog.py:78 | placeholder | ja | 信号名でフィルタ… | 信号名でフィルタ… |  |
| export_csv_dialog.py:107 | button | ja | すべて選択 | すべて選択 | ニーモニクス案: 「すべて選択(&A)」 |
| export_csv_dialog.py:109 | button | ja | 選択なし | すべて解除 | 「選択なし」は状態名で動作ボタンとして不自然 — 「すべて選択」との対で「すべて解除」を提案。ニーモニクス案: 「すべて解除(&N)」。ExpansionDialog の「すべて展開/すべてスキップ」と語調が揃う |
| export_csv_dialog.py:123 | label | ja | 統合タイムライン | 統合タイムライン | QFormLayout 行ラベル（チェックボックス） |
| export_csv_dialog.py:127 | label | ja | 区切り | 区切り | csv_format_dialog.py:53 と同語 — 用語統一済み。「区切り文字」への変更は両所同時に |
| export_csv_dialog.py:131 | label | ja | 小数点 | 小数点 |  |
| export_csv_dialog.py:133 | label | ja | 単位行を出力 | 単位行を出力 |  |
| export_csv_dialog.py:134 | label | ja | ラウンドトリップ(無指定) | ラウンドトリップ（桁数指定なし） | 「無指定」が何の無指定か不明瞭（precision=None の意）— 桁数指定なしを明示する案。半角括弧→全角括弧の統一も同時判断 |
| export_csv_dialog.py:136 | label | ja | 精度 | 精度 |  |
| export_csv_dialog.py:141 | label | ja | 小数桁 | 小数桁 |  |
| export_csv_dialog.py:153 | button | en | Cancel | キャンセル | QDialogButtonBox 標準ボタン。Ok 側は line 157 で「エクスポート…」に上書き済みのため英語残りは Cancel のみ。qtbase_ja の QTranslator 導入で全ダイアログ一括日本語化可能（個別 setText との方針選択要） |
| export_csv_dialog.py:157 | button | ja | エクスポート… | エクスポート… | 確定後に保存先ダイアログが続くため三点リーダは妥当。ニーモニクス案: 「エクスポート(&E)…」 |
| export_csv_dialog.py:213 | diagnostic | mixed | {exc} | {exc} | CsvExportOptions の ValueError をエラーラベルへ転写する動的文言。実体はクラスタ外 valisync/core/export/csv_exporter.py:32-37（例「delimiter と decimal は空文字にできません」= 識別子英語混じりの mixed）— GUI 表示用の日本語文言（例「区切り文字と小数点記号に同じ文字は使えません」）へ core 側修正か写像層かの判断要 |
| export_csv_dialog.py:220 | diagnostic | ja | 少なくとも1信号を選択してください | 少なくとも 1 つの信号を選択してください | 「1信号」の助数詞省略が硬い — 微修正案。現状維持も可 |
| export_csv_dialog.py:229 | title | mixed | CSV の保存先 | CSV の保存先 | QFileDialog.getSaveFileName のキャプション。CSV は頭字語のため実質日本語一次・変更不要 |
| export_csv_dialog.py:229 | other | mixed | CSV (*.csv);;すべてのファイル (*) | CSV (*.csv);;すべてのファイル (*) | ファイルダイアログのフィルタ文字列。glob 部は非翻訳対象・変更不要 |
| signal_preview_window.py:30 | title | ja | 信号プレビュー | 信号プレビュー |  |
| signal_preview_window.py:40 | status | ja | プレビューできません | この信号はプレビューできません | 空状態文言（QStackedWidget index 1）。主語を補い状況を明示する案 — 現状維持も可 |
| signal_preview_window.py:45 | label | ja | プレビュー | プレビュー | タブ見出し |
| signal_preview_window.py:50 | label | ja | 信号プロパティ | 信号プロパティ | タブ見出し |
| signal_preview_window.py:61 | title | ja | 信号プレビュー - {key} | 信号プレビュー - {key} | 動的テンプレート（{key} は信号キーデータ）。区切りは半角ハイフン — Windows タイトル慣例どおりで維持可 |
| signal_preview_window.py:82 | label | ja | {label}: {value} | {label}: {value} | プロパティタブの行は完全動的。ラベル実体はクラスタ外 valisync/gui/viewmodels/signal_preview_vm.py:49-82（名前/単位/サンプル数/時間範囲/最小値/最大値/由来/コメント/ラベル — 既に日本語）。時間範囲の "{min:.4g} - {max:.4g} s" 数値フォーマットも同所 — VM ファイル担当の棚卸しに含めること |

## グラフ系（graph_panel / graph_area / analysis_actions / cursor_readout / offscale_badge）

| file:line | surface | lang | 現文言 | 提案 | note |
|---|---|---|---|---|---|
| analysis_actions.py:40 | menu | ja | 線形 | 線形 | _INTERP_LABELS。Analyze メニュー/空白右クリックの補間 radio と readout ヘッダ表示の単一の真実（共有辞書） |
| analysis_actions.py:41 | menu | ja | 前値保持 | 前値保持 | _INTERP_LABELS（同上） |
| analysis_actions.py:42 | menu | ja | 最近傍 | 最近傍 | _INTERP_LABELS（同上） |
| analysis_actions.py:81 | menu | ja | カーソル A | カーソル A(&A) | Analyze メニューと空白右クリックで共有される同一 QAction。A はカーソル識別子で翻訳不要。ニーモニクス &A 提案 |
| analysis_actions.py:83 | status | ja | 表示範囲の中央に設置 / 解除 | 表示範囲の中央に設置 / 解除 | setStatusTip — ステータスバー未表示なら現状不可視の可能性（増分D ステータスバー導入で活きる） |
| analysis_actions.py:92 | menu | ja | カーソル B（Δ） | カーソル B（Δ）(&B) | 共有 QAction。ニーモニクス &B 提案 |
| analysis_actions.py:94 | status | ja | Shift+クリックで設置 | Shift+クリックで設置 | setStatusTip。Shift はキー名で翻訳不要 |
| analysis_actions.py:103 | menu | ja | カーソルを消す | カーソルを消す(&C) | 共有 QAction。cursor_readout.py:475 の同文言メニュー項目と用語一致を維持すること |
| analysis_actions.py:133 | menu | ja | ← / → サンプルステップ | ← / → サンプルステップ | disabled の情報行（操作ではなくジェスチャ説明・spec §2.2） |
| analysis_actions.py:164 | tooltip | ja | カーソル A を有効化すると使えます | カーソル A を有効化すると使えます | disabled 時のみ設定（有効時は空文字にリセット） |
| cursor_readout.py:35 | status | ja | 範囲外 | 範囲外 | テーブル値セルの欠測表示（TSV コピーにも出る） |
| cursor_readout.py:36 | status | ja | データなし | データなし | Δ統計 count==0 時の統計セル表示（TSV にも出る） |
| cursor_readout.py:37 | header | en | mean | 平均 | _STAT_COLS は列見出し・列選択メニュー（build_column_menu L436）・TSV 見出し・VM キー（visible_stat_cols）が同一文字列 — 日本語化は表示写像の導入が必要（キーは英語のまま維持） |
| cursor_readout.py:37 | header | en | max | 最大 | 同上（表示写像必須）。L239 の「max（全区間）」との用語整合も同時判断 |
| cursor_readout.py:37 | header | en | min | 最小 | 同上（表示写像必須） |
| cursor_readout.py:37 | header | en | std | 標準偏差 | 同上。列幅が伸びるため「σ」等の短縮表記も選択肢 — 要判断 |
| cursor_readout.py:37 | header | en | count | 点数 | 同上（表示写像必須）。「個数」「サンプル数」との用語選定要 |
| cursor_readout.py:236 | header | mixed | A {t:.3f} s（{interp_label}） | A {t:.3f} s（{interp_label}） | Global モード時刻ヘッダ（動的テンプレート・L241 に RichText 版の同型あり）。A/s は記号・単位で翻訳不要 |
| cursor_readout.py:239 | header | ja | A値 | A値 | Global モード列見出し |
| cursor_readout.py:239 | header | mixed | min（全区間） | 最小（全区間） | _STAT_COLS の min を日本語化するなら整合必須（英語維持なら現状どおり）— クラスタ内で統一判断 |
| cursor_readout.py:239 | header | mixed | max（全区間） | 最大（全区間） | 同上 |
| cursor_readout.py:286 | header | mixed | A {t_a:.3f} s ・ B {t_b:.3f} s（{interp_label}） | A {t_a:.3f} s ・ B {t_b:.3f} s（{interp_label}） | Delta モード時刻ヘッダ（動的テンプレート・L293 に RichText 版）。Δt は意図的に非表示（ステータスバー即値と重複回避・spec §2.5） |
| cursor_readout.py:290 | header | ja | A値 | A値 | Delta モード列見出し（L239 と同文言の別リテラル） |
| cursor_readout.py:290 | header | en | Δy | Δy | 記号のみ・翻訳不要 |
| cursor_readout.py:368 | other | ja | 値 | 値 | TSV コピー（表をコピー）の見出し — 列見出し空時の単一値列名 |
| cursor_readout.py:369 | other | ja | 信号 | 信号 | TSV コピーの先頭列見出し |
| cursor_readout.py:461 | context_menu | ja | 統計列 | 統計列 | readout 右クリックのサブメニュータイトル（項目は _STAT_COLS の英語 — L37 参照） |
| cursor_readout.py:464 | context_menu | ja | 精度 | 精度 | サブメニュー（項目は 4/6/8 の数値 radio・翻訳対象外）。「有効桁数」への明確化も検討可 |
| cursor_readout.py:474 | context_menu | ja | 表をコピー | 表をコピー |  |
| cursor_readout.py:475 | context_menu | ja | カーソルを消す | カーソルを消す | analysis_actions.py:103 / graph_panel_view.py:2467 と同文言 — 三面で用語一致を維持すること |
| graph_area_view.py:170 | button | en | + | + | 新規タブボタン。記号のみ・翻訳不要 |
| graph_area_view.py:171 | tooltip | ja | 新規タブ (Ctrl+T) | 新規タブ（Ctrl+T） | 括弧全角/半角の統一判断（ショートカット併記の書式はアプリ全体で統一を推奨） |
| graph_area_view.py:234 | button | ja | 読み値 | 読み値 | readout ペイン表示トグル（checkable QToolButton・タブ corner） |
| graph_area_view.py:235 | tooltip | ja | 読み値ペインの表示切替 | 読み値ペインの表示切替 |  |
| graph_panel_view.py:815 | label | en | Time | 時間 | X 軸ラベル（units="s" は別引数・pyqtgraph が "Time (s)" と合成表示）。プロット軸は英語維持の判断もあり — 要決定 |
| graph_panel_view.py:841 | button | en | + | + | 記号のみ・翻訳不要（パネル追加ボタン） |
| graph_panel_view.py:842 | tooltip | ja | パネルを追加 | パネルを追加 | build_context_menu の "Add Panel"(L2538) と同機能 — 文言統一の基準にする |
| graph_panel_view.py:850 | button | en | × | × | 記号のみ（U+00D7・noqa RUF001 付き）・翻訳不要 |
| graph_panel_view.py:851 | tooltip | ja | パネルを削除 | パネルを削除 | "Remove Panel"(L2541) と同機能 — 統一基準 |
| graph_panel_view.py:1884 | tooltip | en | Δt = {delta_t:+.3g} s | Δt = {delta_t:+.3g} s | オフセットドラッグ中の追従ツールチップ。記号+単位のみで翻訳不要（動的テンプレート） |
| graph_panel_view.py:1959 | title | ja | 時間オフセットの適用 | 時間オフセットの適用 |  |
| graph_panel_view.py:1962 | dialog | mixed | Δt = {delta_t:+.3g} s を適用します。対象を選択してください。 | Δt = {delta_t:+.3g} s を適用します。対象を選択してください。 | Δt は記号で維持（動的テンプレート） |
| graph_panel_view.py:1964 | dialog | ja | この信号のみ | この信号のみ | scope radio。L2389/L2444 と同文言の三重定義 — 共通化候補 |
| graph_panel_view.py:1965 | dialog | ja | 同じファイルグループ全体 | 同じファイルグループ全体 | scope radio（三重定義・同上） |
| graph_panel_view.py:1969 | dialog | en | OK / Cancel（QDialogButtonBox 標準ボタン） | OK / キャンセル | 根本解決は qtbase_ja の QTranslator 導入（全ダイアログ一括）— 個別 setText は対症。5 箇所ある button box の代表と同型 |
| graph_panel_view.py:2320 | context_menu | ja | 非表示 | 非表示 | 曲線メニュー。トグルだが checkable でない — 「非表示にする」の明確化も検討可 |
| graph_panel_view.py:2323 | context_menu | ja | 色変更 | 色変更 | サブメニュータイトル（docs では「色変更▸」表記） |
| graph_panel_view.py:2325 | context_menu | en | {c.hex} | {c.hex} | パレット項目のラベルは色コード（例 #1f77b4）+スウォッチアイコン。コード値表示が意図で翻訳不要 — 色名日本語化するかは判断 |
| graph_panel_view.py:2329 | context_menu | ja | その他… | その他… | カスタム色ダイアログを開く |
| graph_panel_view.py:2332 | context_menu | ja | 削除 | 削除 | 曲線の削除 |
| graph_panel_view.py:2335 | context_menu | ja | 新しい軸へ移動 | 新しい軸へ移動 |  |
| graph_panel_view.py:2339 | context_menu | ja | 時間オフセット… | 時間オフセット… |  |
| graph_panel_view.py:2346 | context_menu | ja | オフセットをリセット… | オフセットをリセット… | 非ゼロオフセット時のみ enabled |
| graph_panel_view.py:2350 | context_menu | ja | オフセット: {current_offset:+.3f}s | オフセット: {current_offset:+.3f} s | disabled 情報行。単位前スペース無しは他表示（" s"・L2385 等）と不統一 — スペース挿入を提案 |
| graph_panel_view.py:2383 | title | ja | 時間オフセット | 時間オフセット |  |
| graph_panel_view.py:2385 | dialog | ja | 現在のオフセット: {current:+.3f} s | 現在のオフセット: {current:+.3f} s | 動的テンプレート |
| graph_panel_view.py:2386 | dialog | ja | 追加する Δt (秒): | 追加する Δt（秒）: | 括弧の全角/半角がファイル内で混在（RUF001 回避で ASCII の箇所あり）— 全体方針の統一判断要 |
| graph_panel_view.py:2389 | dialog | ja | この信号のみ | この信号のみ | scope radio（L1964 と同文言・共通化候補） |
| graph_panel_view.py:2390 | dialog | ja | 同じファイルグループ全体 | 同じファイルグループ全体 | scope radio（同上） |
| graph_panel_view.py:2394 | dialog | en | OK / Cancel（QDialogButtonBox 標準ボタン） | OK / キャンセル | QTranslator で一括対応（L1969 と同件） |
| graph_panel_view.py:2441 | title | ja | 時間オフセットのリセット | 時間オフセットのリセット |  |
| graph_panel_view.py:2443 | dialog | ja | オフセットを 0 に戻します。対象を選択してください。 | オフセットを 0 に戻します。対象を選択してください。 |  |
| graph_panel_view.py:2444 | dialog | ja | この信号のみ | この信号のみ | scope radio（三重定義の 3 箇所目） |
| graph_panel_view.py:2445 | dialog | ja | 同じファイルグループ全体 | 同じファイルグループ全体 | scope radio（同上） |
| graph_panel_view.py:2449 | dialog | en | OK / Cancel（QDialogButtonBox 標準ボタン） | OK / キャンセル | QTranslator で一括対応（同件） |
| graph_panel_view.py:2464 | context_menu | ja | 時刻を指定… | 時刻を指定… | カーソル線メニュー |
| graph_panel_view.py:2467 | context_menu | ja | カーソルを消す | カーソルを消す | A 線用（A 消去=全消去）。analysis_actions.py:103 と同文言 — 用語一致を維持 |
| graph_panel_view.py:2467 | context_menu | ja | カーソル B（Δ）を消す | カーソル B（Δ）を消す | B 線用（Δ のみ解除）。同一行の条件式のもう片方 |
| graph_panel_view.py:2505 | title | ja | カーソル時刻を指定 | カーソル時刻を指定 |  |
| graph_panel_view.py:2507 | dialog | ja | {which} カーソルの時刻 (秒): | {which} カーソルの時刻（秒）: | {which}=A/B。括弧全角/半角の統一判断は L2386 と同件 |
| graph_panel_view.py:2511 | dialog | en | OK / Cancel（QDialogButtonBox 標準ボタン） | OK / キャンセル | QTranslator で一括対応（同件） |
| graph_panel_view.py:2538 | context_menu | en | Add Panel | パネルを追加 | 英語残存。+ボタン tooltip（L842）と同文言に統一 |
| graph_panel_view.py:2541 | context_menu | en | Remove Panel | パネルを削除 | 英語残存。×ボタン tooltip（L851）と同文言に統一 |
| graph_panel_view.py:2544 | context_menu | en | Reset All Axes | すべての軸をリセット | 英語残存。「この軸をオートフィット」「X軸をオートフィット」との用語整合（リセット vs オートフィット）を要判断 — 実動作は reset_x + reset_y |
| graph_panel_view.py:2547 | context_menu | ja | グリッド | グリッド | checkable |
| graph_panel_view.py:2560 | context_menu | ja | X軸同期（タブ内全パネル） | X軸同期（タブ内全パネル） | checkable・getter/setter 注入時のみ表示 |
| graph_panel_view.py:2579 | context_menu | ja | 補間方式 | 補間方式 | サブメニュータイトル（項目は _INTERP_LABELS の共有 QAction） |
| graph_panel_view.py:2587 | context_menu | ja | この軸をオートフィット | この軸をオートフィット | Y軸メニュー |
| graph_panel_view.py:2590 | context_menu | ja | 範囲を指定… | 範囲を指定… | Y軸メニュー（L2624 X軸メニューにも同文言） |
| graph_panel_view.py:2599 | context_menu | ja | ズームイン | ズームイン | Y軸メニュー（FU-09） |
| graph_panel_view.py:2602 | context_menu | ja | ズームアウト（引き） | ズームアウト（引き） | Y軸メニュー。「（引き）」補足の要否は要判断 |
| graph_panel_view.py:2605 | context_menu | ja | 軸を削除 | 軸を削除 |  |
| graph_panel_view.py:2621 | context_menu | ja | X軸をオートフィット | X軸をオートフィット | X軸メニュー |
| graph_panel_view.py:2624 | context_menu | ja | 範囲を指定… | 範囲を指定… | X軸メニュー（L2590 と同文言・意図的な統一） |
| graph_panel_view.py:2628 | context_menu | ja | ズームイン | ズームイン | X軸メニュー |
| graph_panel_view.py:2631 | context_menu | ja | ズームアウト（引き） | ズームアウト（引き） | X軸メニュー |
| graph_panel_view.py:2676 | title | ja | X軸の範囲を指定 | X軸の範囲を指定 | 同一行の条件式（axis_index==-1 が X 軸センチネル） |
| graph_panel_view.py:2676 | title | ja | Y軸の範囲を指定 | Y軸の範囲を指定 | 同一行の条件式のもう片方 |
| graph_panel_view.py:2680 | dialog | ja | 下限 | 下限 | QFormLayout 行ラベル |
| graph_panel_view.py:2681 | dialog | ja | 上限 | 上限 | QFormLayout 行ラベル |
| graph_panel_view.py:2682 | dialog | en | OK / Cancel（QDialogButtonBox 標準ボタン） | OK / キャンセル | QTranslator で一括対応（同件・本ファイル 5 箇所目） |
| offscale_badge.py:50 | tooltip | ja | レンジ外の曲線あり — クリックでフィット | レンジ外の曲線あり — クリックでフィット | ▲/▼ バッジ（描画は図形のみ・文字グリフなし） |

## ブラウザ・診断（channel_browser / file_browser / data_explorer / diagnostics / dock title bar / rail）

| file:line | surface | lang | 現文言 | 提案 | note |
|---|---|---|---|---|---|
| channel_browser_view.py:48 | placeholder | mixed | File Browser でファイルを選択すると
信号一覧を表示します | ファイルブラウザでファイルを選択すると
信号一覧を表示します | 「File Browser」は main_window.py:140 の QDockWidget タイトルの引用。ドック訳語（例:「ファイルブラウザ」）確定後に必ず一致させる（別クラスタと調整要） |
| channel_browser_view.py:49 | placeholder | ja | 「{query}」に一致する信号はありません | 「{query}」に一致する信号はありません | 動的テンプレート（.format(query=...)）。placeholder_label は PlainText 設定済でクエリの HTML 解釈なし — 既に適正 |
| channel_browser_view.py:50 | placeholder | mixed | このファイルに信号がありません
（Diagnostics に詳細） | このファイルに信号がありません
（詳細は診断ドックへ） | 「Diagnostics」は diagnostics_view.py:47 のドックタイトル引用。ドック訳語（「診断」案）と要整合 |
| channel_browser_view.py:68 | placeholder | en | Filter signals… | 信号をフィルタ… | QLineEdit.setPlaceholderText。末尾の三点リーダは維持 |
| channel_browser_view.py:288 | context_menu | en | Add to Active Panel | アクティブパネルへ追加 | ニーモニクス案「アクティブパネルへ追加(&A)」。選択なし時は disabled（文言に前提を書かなくてよい） |
| collapsible_dock_title_bar.py:47 | tooltip | ja | 折りたたむ | 折りたたむ | 既に適正。フロート中は disabled（tooltip は据え置き） |
| collapsible_dock_title_bar.py:57 | button | en | ❐ | ❐ | フロートボタンのグリフ（記号・言語非依存）。✕と同様、Lucide アイコン化は運用反復で個別判断（CLAUDE.md） |
| collapsible_dock_title_bar.py:58 | tooltip | ja | フロート | フロート | 実動作はトグル（フロート⇄再ドッキング）— 「フロート切替」への変更も検討価値あり |
| collapsible_dock_title_bar.py:69 | button | en | ✕ | ✕ | 閉じるボタンのグリフ。CLAUDE.md で✕置換は反復で個別判断と明記 — 増分Dでは据え置き可 |
| collapsible_dock_title_bar.py:70 | tooltip | ja | 閉じる | 閉じる | 既に適正 |
| data_explorer_view.py:70 | title | en | Data Explorer | データエクスプローラー | setWindowTitle。長音符方針（エクスプローラ/エクスプローラー）を design.md の表記規約で確定してから展開 |
| data_explorer_view.py:96 | other | en | Sources | データソース | addToolBar のタイトル — フロート時とツールバー表示切替コンテキストメニューでユーザー可視 |
| data_explorer_view.py:97 | button | en | Add Source | データソースを追加 | ツールバー QAction。「Source」単独でも訳は「データソース」に統一。ニーモニクス案「データソースを追加(&A)」 |
| data_explorer_view.py:99 | button | en | Remove Source | データソースを削除 | ツールバー QAction。line 231「Remove from Data Sources」と動詞「削除」で統一。ニーモニクス案「データソースを削除(&R)」 |
| data_explorer_view.py:115 | title | en | Select Data Source Folder | データソースフォルダを選択 | QFileDialog.getExistingDirectory のダイアログタイトル |
| data_explorer_view.py:127 | status | ja | 削除するデータソースをリストから選択してください | 削除するデータソースをリストから選択してください | statusBar().showMessage（4000ms）。既に適正 |
| data_explorer_view.py:228 | context_menu | en | Load File | ファイルを読み込む | 完了系文言「〜を読み込みました」と動詞「読み込む」で統一。ニーモニクス案「ファイルを読み込む(&L)」。ディレクトリ選択時は disabled |
| data_explorer_view.py:231 | context_menu | en | Remove from Data Sources | データソースから削除 | ニーモニクス案「データソースから削除(&D)」。未登録パスでは disabled |
| diagnostics_view.py:32 | other | en | ⛔ / ⚠ / ℹ（_LEVEL_ICON: error/warning/info） | ⛔ / ⚠ / ℹ | レベル列の絵文字グリフ（言語非依存）。CLAUDE.md のとおり Lucide 等アイコン化は運用反復で個別判断 — 増分Dでは据え置き可 |
| diagnostics_view.py:36 | header | ja | レベル | レベル | 既に適正 |
| diagnostics_view.py:36 | header | en | # | # | 受信順序番号（seq）列の簡潔ヘッダ。記号のままで可（spec §4.3/§4.4 の「時刻」を順序番号で充足する設計判断済） |
| diagnostics_view.py:36 | header | ja | ソース | ソース | ファイル由来を指す。DataExplorer の「データソース」（フォルダ）とは別概念 — 用語衝突に留意（必要なら「ファイル」へ） |
| diagnostics_view.py:36 | header | ja | メッセージ | メッセージ | 既に適正 |
| diagnostics_view.py:36 | header | ja | 対象 | 対象 | 既に適正（signal_name 表示専用列） |
| diagnostics_view.py:38 | placeholder | ja | 診断はありません | 診断はありません | フィルタ後ゼロ件でも同文言（spec §7）。既に適正 |
| diagnostics_view.py:47 | title | en | Diagnostics | 診断 | QDockWidget タイトル — main_window.py の CollapsibleDockTitleBar/畳みレールタブにも同文字列が流れる。channel_browser_view.py:50 の「Diagnostics に詳細」・View メニューのトグル文言（別クラスタ）と一括で要整合 |
| diagnostics_view.py:56 | button | en | All | すべて | フィルタボタン3兄弟（All/Errors/Warnings）は名詞で統一 |
| diagnostics_view.py:57 | button | en | Errors | エラー | counts チップ（line 144）を文字併記にする場合は同語「エラー」で統一 |
| diagnostics_view.py:58 | button | en | Warnings | 警告 |  |
| diagnostics_view.py:59 | button | en | Clear | クリア | 代替案「消去」— 既存メニュー「カーソルを消す」と動詞系統を合わせるかは design.md の用語表で判断 |
| diagnostics_view.py:127 | other | en | ? | ? | 未知レベル時のレベル列フォールバック記号。据え置き可 |
| diagnostics_view.py:131 | other | en | — | — | 対象（signal_name）なし時のセルプレースホルダ記号。据え置き可 |
| diagnostics_view.py:144 | label | en | ⛔ {errors} / ⚠ {warnings} | ⛔ {errors} / ⚠ {warnings} | counts チップの f-string テンプレート（記号+数値で言語非依存）。文字併記案「エラー {errors}／警告 {warnings}」は幅と要相談。絵文字グリフ置換は運用反復で個別判断 |
| file_browser_view.py:69 | placeholder | ja | ファイルが読み込まれていません

ウィンドウへファイルをドロップして追加 | ファイルが読み込まれていません

ウィンドウへファイルをドロップして追加 | 既に適正。Welcome 空状態 CTA（別クラスタ）と導線文言の整合のみ確認 |
| file_browser_view.py:106 | context_menu | en | Remove File | ファイルを閉じる | 用語衝突: 現状メニューは Remove、確認ダイアログ表題(line 114)は「閉じる」。unload 動作なので「閉じる」へ統一する案。ニーモニクス案「ファイルを閉じる(&C)」 |
| file_browser_view.py:114 | title | ja | ファイルを閉じる | ファイルを閉じる | QMessageBox.question のタイトル。既に適正 |
| file_browser_view.py:115 | dialog | ja | {filename} を閉じますか? プロット中の信号も消えます。 | {filename} を閉じますか？プロット中の信号も消えます。 | f-string テンプレート。半角「?」→全角「？」の表記統一判断（design.md の表記規約で確定を） |
| file_browser_view.py:116 | dialog | en | Yes / No（QMessageBox.StandardButton.Yes\|No） | はい / いいえ | Qt 標準ボタンの英語表示（1エントリとして報告）。qtbase 翻訳（QTranslator で qtbase_ja ロード）か button(...).setText の明示指定が必要 — 個別 setText よりアプリ全体で QTranslator 導入が根本解決 |

## core 診断（loaders / session — ユーザー可視の Diagnostic・例外文言）

| file:line | surface | lang | 現文言 | 提案 | note |
|---|---|---|---|---|---|
| core/loaders/csv_format_detector.py:82 | dialog | ja | ファイルが空です | ファイルが空です | 検出 notes — CsvFormatDialog のバナー（「注意: 」+ " / ".join(notes)）に表示。既に適正 |
| core/loaders/csv_format_detector.py:91 | dialog | ja | 列を検出できません | 列を検出できません | 検出 notes（バナー表示）。既に適正 |
| core/loaders/csv_format_detector.py:102 | dialog | ja | データ行がありません | データ行がありません | 検出 notes（バナー表示）。既に適正 |
| core/loaders/csv_format_detector.py:117 | dialog | ja | 信号列を数値から特定できませんでした | 信号列を数値から特定できませんでした | 検出 notes（バナー表示）。既に適正 |
| core/loaders/csv_format_detector.py:119 | dialog | ja | 時間単位は sec と仮定しています。確認してください | 時間単位は sec と仮定しています。確認してください | 検出 notes（バナー表示・常時付与）。「sec」はダイアログの単位コンボ実値（sec/msec）の литeral — 翻訳対象外。既に適正 |
| core/loaders/csv_format_detector.py:216 | dialog | mixed | 自動構築に失敗: {exc} | 自動構築に失敗: {exc} | テンプレート自体は ja だが {exc} は models/format_def.py の FormatDefinition ValueError（英語・別クラスタ）が入り runtime 混在。format_def.py の検証文言は CsvFormatDialog のエラーラベル（csv_format_dialog.py:137 setText(str(exc))）にも生表示されるため、models クラスタ側での日本語化要否を対訳表で要調整 |
| core/loaders/csv_loader.py:40 | diagnostic | en | File not found or not accessible: {file_path} | ファイルが見つからないか、アクセスできません: {path} | mdf_loader:252 と同一文言 — 同一訳で統一 |
| core/loaders/csv_loader.py:53 | diagnostic | en | Cannot read '{file_name}': {exc} | '{file}' を読み取れません: {exc} | {exc} は OSError の英語文字列（OS 由来・翻訳不能） |
| core/loaders/csv_loader.py:72 | diagnostic | en | Expected header row but file is empty | ヘッダ行が必要ですが、ファイルが空です | 「ヘッダ」表記は csv_loader:116（重複ヘッダ）・検出器 UI と統一（「ヘッダー」ではなく「ヘッダ」）— 用語表の確定が必要 |
| core/loaders/csv_loader.py:85 | diagnostic | en | Header has {n} columns, expected at least {min} | ヘッダの列数が {n} 列です（{min} 列以上が必要） | line_number 付き error 診断。line 157（データ行版）と文型統一 |
| core/loaders/csv_loader.py:116 | diagnostic | ja | 重複ヘッダ {names} を連番で改名（name[idx] 方式） | 重複ヘッダ {names} を連番で改名（name[idx] 方式） | 既に適正。「name[idx]」は実際の改名記法の литeral 表記（翻訳対象外） |
| core/loaders/csv_loader.py:157 | diagnostic | en | Row has {n} columns, expected at least {min} | 行の列数が {n} 列です（{min} 列以上が必要） | line_number 付き error 診断。line 85（ヘッダ版）と文型統一 |
| core/loaders/csv_loader.py:174 | diagnostic | en | Non-numeric timestamp {ts!r} | 非数値のタイムスタンプ {ts} | {ts!r} は repr 引用表示（'abc' 形式）— 日本語化後も引用表示を維持。line 189「非有限タイムスタンプ」と対の用語（非数値/非有限） |
| core/loaders/csv_loader.py:189 | diagnostic | ja | 非有限タイムスタンプ {ts!r}（時刻軸が破損） | 非有限タイムスタンプ {ts}（時刻軸が破損） | 既に適正。mdf_loader:440 の「時刻軸が破損」と用語一致済み |
| core/loaders/csv_loader.py:212 | diagnostic | en | Non-numeric value {val!r} in signal column | 信号列に非数値の値 {val} | line_number/column_number 付き error 診断。{val!r} は repr 引用表示を維持 |
| core/loaders/csv_loader.py:236 | diagnostic | ja | タイムスタンプ列: 非単調 {n} 箇所・重複 {m} 点（表示/演算は整列ビューで補正） | タイムスタンプ列: 非単調 {n} 箇所・重複 {m} 点（表示/演算は整列ビューで補正） | 既に適正（LD-04・ファイル単位1件）。mdf_loader:492 は「重複タイムスタンプ {m} 点」と語がやや異なる — 揃えるか要判断 |
| core/loaders/csv_loader.py:245 | diagnostic | ja | データ行が 0 行です | データ行が 0 行です | 既に適正（LD-09）。検出器の「データ行がありません」（detector:102）と文言が異なるが表示文脈が違う（成功+warning vs 検出不能）ため現状維持で可 |
| core/loaders/csv_loader.py:260 | diagnostic | ja | '{name}': 非有限値 {n} 個（'nan'/'inf' 文字列由来） | 信号 '{name}': 非有限値 {n} 個（'nan'/'inf' 文字列由来） | LD-06。プレフィックスが「'{name}':」のみで mdf_loader の「Signal '{name}':」系と不揃い — 「信号 '{name}':」への統一を提案（signal_name フィールドは別途保持済み） |
| core/loaders/mdf_loader.py:102 | diagnostic | ja | 構造化チャンネル | 構造化チャンネル | line 108 の展開診断メッセージの shape_desc フラグメント（単独表示はされない）。対訳表では line 108 テンプレートと一体で扱う |
| core/loaders/mdf_loader.py:104 | diagnostic | ja | {d1}x{d2}… 配列 | {d1}x{d2}… 配列 | line 108 の shape_desc フラグメント（"x".join(shape[1:]) + " 配列"）。次元数可変。line 108 テンプレートと一体で扱う |
| core/loaders/mdf_loader.py:108 | diagnostic | mixed | Signal '{base_name}': {shape_desc}を {n} 本に展開 | 信号 '{name}': {shape_desc}を {n} 本に展開 | LD-14 展開の info 診断。「Signal '{name}':」プレフィックスは mdf_loader 内 4 箇所（108/295/440/477/492）共通 — 「信号 '{name}':」への一括統一を提案。csv_loader:260 の「'{name}':」（信号なし）とも表記揺れあり |
| core/loaders/mdf_loader.py:252 | diagnostic | en | File not found or not accessible: {file_path} | ファイルが見つからないか、アクセスできません: {path} | csv_loader:40 と同一文言 — 同一訳で統一。error 診断（モーダル＋Diagnostics dock 表示） |
| core/loaders/mdf_loader.py:265 | diagnostic | en | Failed to parse MDF '{file_name}': {exc} | MDF '{file}' の解析に失敗しました: {exc} | {exc} は asammdf 例外の英語文字列がそのまま入る（翻訳不能・そのまま残す判断が必要） |
| core/loaders/mdf_loader.py:295 | diagnostic | mixed | Signal '{name}': 展開列数 {n} が上限 {limit} を超えるためスキップ | 信号 '{name}': 展開列数 {n} が上限 {limit} を超えるためスキップ | LD-14 warning 診断。プレフィックスのみ英語 → 「信号 '{name}':」へ統一 |
| core/loaders/mdf_loader.py:335 | diagnostic | en | Failed to read channels from '{file_name}': {exc} | '{file}' のチャンネル読み取りに失敗しました: {exc} | {exc} は英語例外文字列。「チャンネル」表記は既存 ja 診断（line 346）と一致 |
| core/loaders/mdf_loader.py:346 | diagnostic | ja | チャンネルが 0 本です（全チャンネルが読み取り不能） | チャンネルが 0 本です（全チャンネルが読み取り不能） | 既に適正（noqa: RUF001 付き全角括弧 — 日本語一次化後は既定表記とする） |
| core/loaders/mdf_loader.py:440 | diagnostic | mixed | Signal '{name}': 非有限タイムスタンプを含むため skip（時刻軸が破損） | 信号 '{name}': 非有限タイムスタンプを含むためスキップ（時刻軸が破損） | コード注記「文言は現行と同一（既存テスト互換）」あり — 変更時は文言依存テストの同時更新が必須。英語「skip」→「スキップ」で line 295 と統一 |
| core/loaders/mdf_loader.py:477 | diagnostic | en | Signal '{name}' has non-numeric values, skipped: dtype {dtype} | 信号 '{name}': 非数値型のためスキップ（dtype {dtype}） | FU-20 経路の warning。dtype はデバッグ情報として英語のまま残す。他のスキップ系（295/440）と文型統一 |
| core/loaders/mdf_loader.py:492 | diagnostic | mixed | Signal '{name}': 非単調 {n} 箇所・重複タイムスタンプ {m} 点（表示/演算は整列ビューで補正） | 信号 '{name}': 非単調 {n} 箇所・重複タイムスタンプ {m} 点（表示/演算は整列ビューで補正） | csv_loader:236 のファイル単位版（「タイムスタンプ列:」）と対の表現 — 用語（非単調/重複/整列ビュー）は既に統一済み。プレフィックスのみ「信号」へ |
| core/session.py:52 | dialog | en | failed to load {file_path}: {messages} | {path} の読み込みに失敗しました: {messages} | LoadError の str()。GUI 主経路は err.messages（診断文言リスト）を直接表示するが、LoadTask.fail(str(exc))・_on_load_error の getattr fallback で str(err) も露出しうる。{messages} は上記診断文言の '; ' 連結。ステータスバー既存文言「⛔ 読み込み失敗: {source}」（GUI クラスタ）との語調整合に注意 |
| core/session.py:153 | dialog | en | CSV files require a FormatDefinition | CSV の読み込みにはフォーマット定義が必要です | 防御的 ValueError だが load_many の failed 経路（str(exc)）と _on_load_error fallback でユーザー表示されうる。「フォーマット定義」の訳語は CsvFormatDialog（GUI クラスタ）の用語と統一が必要 |
| core/session.py:160 | dialog | en | no loader supports file: {file_path} | 対応していないファイル形式です: {path} | ValueError — D&D 等で未対応拡張子を渡すと load_many failed / _on_load_error 経由でモーダル表示されうる。逐語訳（「対応するローダーがありません」）より利用者視点の文言を提案 |

