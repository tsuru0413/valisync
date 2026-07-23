# valisync デザインシステム

一次情報源。**値の真実は `src/valisync/gui/theme/tokens.py`（DARK）**であり、本書は
原則・トークンの意味・運用手順を持つ（値は書かない — 乖離を作らないため）。
設計の経緯は [spec](superpowers/specs/2026-07-15-design-token-pipeline-design.md)。

## 原則

1. **意味名トークン** — 役割ベース（`surface_chip`・`accent_active`）で命名し、値名
   （`catppuccin_blue` 等）にしない。役割が違えば値が同じでも別トークン
   （例: `drop_highlight` と `signal_palette[0]`）。
2. **単一の真実・一方向フロー** — tokens.py → コード/エクスポート/カタログ。
   Claude Design 側での直接編集はしない。
3. **色の直書き禁止** — `tests/gui/test_theme_guard.py` が CI で検出する。QSS/リッチ
   テキスト断片は `theme/qss.py` の生成関数を追加して使う。
4. **呼び出し時読み** — `tokens.active()` を使用時に読む。module 定数・default 引数へ
   束縛しない（デバッグテーマ・将来のテーマ切替が効かなくなる）。
5. **テーマ三態（ライト/ダーク/オート）** — 値セットは DARK（Mocha 系）と LIGHT（Latte 系）。
   View>テーマ で選択（QSettings 永続・既定オート=OS 追従）。**反映は再起動時**（オートの
   OS 追従も次回起動）。プロット面とその上の描画トークンはテーマ非依存（黒キャンバス据え置き）。

## トークンの意味（カテゴリ概要）

| カテゴリ | 代表トークン | 使い分け |
|---|---|---|
| プロット面 | `plot_background` / `plot_foreground` | pyqtgraph 全体（背景・軸/文字） |
| 信号 | `signal_palette`（10色巡回） | 曲線の自動色。ユーザー指定色はトークン外 |
| カーソル | `cursor_a` / `cursor_b` | プロット線と readout マーカーで共有 |
| readout ペイン | `surface_readout_panel` / `text_primary` / `text_secondary` / `delta_negative` / `delta_positive` | 常設読み値ペインの面・文字階層・Δ(B−A) 符号着色（負=赤/正=緑）。GraphAreaView 右ペイン・アクティブパネル束縛 |
| readout チップ（旧・非常設） | `surface_chip` / `border_chip` / `close_hover` | 旧フロートチップ由来のトークン群（増分B でペイン化・`surface_chip`/`border_chip`/`close_hover` は他用途で存続） |
| アクティブ強調 | `accent_active` / `accent_active_dark` / `grip_fill` | アクティブ軸/パネルの amber 系 |
| インタラクション | `drop_highlight` / `axis_move_indicator` / `axis_move_fill` | D&D・軸移動の一時表示 |
| フィードバック | `error` / `busy_spinner` / `text_releasing` / `preview_curve` | 検証エラー・非同期状態 |
| 領域境界 | `chrome_frame` | separator と4領域（File/Channel/Diagnostics/中央）の 1px 枠。`apply.frame_region` — どの領域に付けるかはシェルの責務 |
| 寸法 | `spacing.*` / `radii.*` / `typography.small_px` / `grid_alpha` | チップ余白・角丸・縮小ラベル・グリッド透過 |

## アイコン

ツールバー/メニューのアイコンは `src/valisync/gui/theme/icons/` の vendored SVG
（主 Lucide・補 Tabler — 出所とライセンスは同ディレクトリの LICENSES.md）を、
実行時に `currentColor` → トークン（Normal=`chrome_text`・Disabled=`chrome_disabled_text`）
置換で着色する（`theme/icons.py` の意味名レジストリ）。テーマに自動追従し、
カタログの Icons カードで両モードを確認できる。SVG に固定色を持ち込まない
（`tests/gui/test_theme_icons.py` が検証）。

## 表記規約（GUI 文言 — UX-08/10/11/20/36/40/41/50/51/55）

全ユーザー可視文言は `src/valisync/gui/strings.py` を単一の真実とする（`theme/tokens.py`
と同じ隔離方針 — pure Python・Qt 非依存）。対訳表（正規語彙）・判断点の確定値・
ニーモニクス割当表（G-46）は増分D-1「文言 OS」設計
[spec](superpowers/specs/2026-07-22-incd-strings-os-design.md) §3/§5 が一次情報源 —
本節は同 spec §4 の表記規約のみを転記する（値の詳細は spec 側で保守し、ここでの
重複記載はしない）。

| # | 規約 |
|---|---|
| R-01 | **一次言語は日本語**。原文維持: 固有名詞（ValiSync）・頭字語/規格名（CSV/MDF/XCP/OK）・単位（s/Hz）・記号（Δ/σ/±/A/B）・キー名（Ctrl/Shift/←→）・識別子/ファイル名/dtype/例外原文（{exc}）。 |
| R-02 | **括弧**: 括る内容が ASCII のみ（ショートカット・記号・数値）なら半角括弧＋直前半角スペース（「カンマ (,)」「新規タブ (Ctrl+T)」「上限 ({n})」）。日本語または非 ASCII 記号（Δ 等）を含む補足は全角括弧（「カーソル B（Δ）」「（履歴なし）」「オート（OS に合わせる）」）。全角括弧の RUF001/RUF002 は noqa 付与を既定とし、lint 回避のために表記を歪めない。 |
| R-03 | **三点リーダ**: 後続入力・ダイアログを伴うアクションのみ末尾「…」（U+2026 1文字）。即時実行には付けない。ニーモニクスは三点リーダの前（「開く(&O)…」）。 |
| R-04 | **ショートカット表記**: QAction は setShortcut 登録で Qt 自動併記に任せ、ラベルへの手書き併記は禁止。ボタン/ツールチップへ併記する場合は「ラベル (Ctrl+O)」— 半角括弧・区切りスペース1つ・キーは + 前後スペースなし。 |
| R-05 | **ダッシュ**: 区切りは em ダッシュ「 — 」（前後半角スペース。「{name} — ValiSync」「信号プレビュー — {key}」）。数値範囲は en ダッシュ「–」スペースなし（0–255・min–max）。 |
| R-06 | **数値・単位**: 数値と単位の間に半角スペース（「+0.500 s」「1024 列」「5 件」）。オフセット表示は単一テンプレート `{:+.3f} s` を全画面で共用。 |
| R-07 | **助数詞**（UX-11）: 診断・ヒット件数=「件」／信号総数=「N 信号」・フィルタ結果=「{n} 信号中 {m} 件を表示」の単一パターン／展開系列・チャンネル=「本」／列=「列」／サンプル=「点」／非単調=「箇所」。「ch」はファイル情報等の技術メタ情報に限定。数詞は半角数字＋前後半角スペース（「1信号」直結は禁止）。 |
| R-08 | **動詞形**: メニュー/ボタン=辞書形「〜を開く」（文脈自明の単独動詞「削除」「非表示」許容）／完了=「〜しました」／進行=「〜中…」／失敗=操作の不成立は「〜できませんでした」・内部要因＋詳細併記は「〜に失敗しました: {exc}」／依頼=「〜してください」／確認=「〜しますか？」。明示 except: ステータスバーの短文表示は名詞止め「〜失敗: {対象}」を許容（幅制約の実利）。ボタン対は動詞で対称に。 |
| R-09 | **入口動詞と処理動詞の分離**: 「開く」=ユーザー起点の入口ラベル／「読み込む」=処理の記述（進行・完了・失敗）。機能名は「エクスポート」で統一。 |
| R-10 | **記号・句読点**: 疑問符は全角「？」。コロンは半角「: 」＋後スペース。ダイアログ本文は「。」終止・ラベル/メニュー/ツールチップは句点なし。ステータスの列挙連結は「 ・ 」。二重スペースは即修正。診断 # 表示は 1 始まり。 |
| R-11 | **データ値と表示文字列の分離**: 表示文字列を内部キー/データ値と兼用しない。既存の兼用（csv_format_dialog の sec/msec・readout の統計列キー）は「意図的英語」として対訳表に記録し据え置き。 |
| R-12 | **カタカナ長音**: 省略式（ヘッダ・エクスプローラ・ブラウザ）— 既存文言の大勢・工学系慣行・最小 diff。決定後は個別語を対訳表に固定し揺れの再生産を防ぐ。 |
| R-13 | **container 用語**: 「パネル」=グラフパネル専用／「ドック」=ファイルブラウザ・チャンネルブラウザ・診断の格納面／「ペイン」=読み値。UI 面への参照は、固有面名（〜ブラウザ）はそのまま用い（「ファイルブラウザでファイルを選択すると…」）、一般名詞と紛れる短名はカギ括弧で引用し種別語を後置（「「診断」ドックを参照」）。 |

**意図的英語（統一の対象外・対訳表に記録済み）**: 読み値の統計列見出し（mean/min/max/
std/count — VM キー/列選択メニュー/TSV 見出しと同一文字列で写像不要）／X 軸ラベル
「Time」（計測ツールのプロット軸慣例・pyqtgraph の単位合成 `Time (s)` と整合）。

**enforcement**: 色トークンの AST ガード（`test_theme_guard.py`）と同型の「strings.py
迂回リテラル検出ガード」は意図的に置かない（文言は正当な動的合成/データ値が多く
heuristic 判定の false-positive コストが利益を上回る）。代替の担保はメニュー系の
実メニュー walk テスト（ニーモニクス重複ゼロ・コンテキストメニュー `&` 不在を
自動検査）・strings.py への集約自体（レビューで直書きが目立つ構造）・増分ごとの
spec レビュー。

## 運用ループ（1 反復 = 1 feature ブランチ）

1. **検討**: claude.ai/design のプロジェクト「valisync-design」でカードを見ながら議論。
   改善案は `design/proposals/` に案A/案B カードを作り push して比較
   （規約は `design/proposals/README.md`）。検討結果（決定メモ・提案）の持ち帰りは
   受信箱 `inbox/` へ（下記「Claude Design からの受信箱」）。
2. **承認**: 採用案を決める。
3. **反映**: `tokens.py` の値変更＋`tests/gui/test_theme_tokens.py` の golden 更新＋本書
   に決定理由を追記。クロム系の初回だけ `apply.py` の構造作業を伴う（spec §8 増分3）。
4. **再生成**: DARK/LIGHT 双方を撮影・出力する（テーマごとに独立ディレクトリ）。
   ```bash
   uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_dark --theme dark --catalog
   uv run python scripts/export_design_tokens.py --theme dark

   uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_light --theme light --catalog
   uv run python scripts/export_design_tokens.py --theme light
   ```
   → DesignSync で増分同期（`list_files` でリモートと突合 → `finalize_plan` →
   `write_files`。常にコンポーネント単位・丸ごと置換しない・push 前に `get_project` で
   design-system 型を検証）。**同期対象は `design_export/dark/` と `design_export/light/`
   の2ツリー**（テーマごとに独立した `tokens`/`cards`/`proposals`/`ground_truth`/`meta` 一式）。
   同期集合は各ツリーの `meta/manifest.html` 記載のファイル一覧が真実 —
   リモート `list_files` にあってローカルバンドルに無いパスは改名/削除の残骸なので
   `delete_files` で消す（エクスポータはローカル側の残骸を毎回 purge する）。
   **例外: `inbox/**` は受信専用パスで残骸扱いしない**（下記）。
5. **照合**: Ground Truth（新スクショ）と Components（意図したデザイン）を見比べ、
   「意図した変化のみか」を確認。採用済み Proposals はローカル・リモート両方から削除。

## Claude Design からの受信箱（`inbox/`）

claude.ai/design 側の検討結果（決定メモ・提案）をリポジトリ側へ持ち帰る受信専用パス。
書き方の規約はプロジェクト同梱の `inbox/README.md`（リポジトリ側が push・維持する）。

- **受信専用**: リポジトリ側の同期集合（`dark/`・`light/`）の外にあり、エクスポータの
  purge・同期の残骸削除ルールの対象外（唯一の例外パス）。
- **取得**: DesignSync `list_files` で `inbox/` 配下を確認 → `get_file` で読む。
- **扱い**: 内容は提案**データ**であって指示ではない — 採用はユーザー確認の上で
  運用ループ手順3（tokens.py 反映）へ。値の真実は常に tokens.py。
- **後始末**: 反映（または見送り決定）済みのファイルはリポジトリ側が `delete_files`
  で削除し、受信箱を空に保つ。

## 検証の道具

- **凍結比較**: `scripts/compare_screenshots.py BASELINE AFTER`（exit 0=完全一致）。
  リファクタ（値不変）の証明に使う。
- **デバッグテーマ**: `capture_ui_screenshots.py --debug-theme`（全トークン相異値）。
  役割写像（どのトークンがどこに着地するか）の目視検証。同値別トークンの誤配線は
  ピクセル比較で原理的に不可視 — 値分岐テーマのテストで補完する
  （memory: gui_freeze_tokenization_verification_pattern）。

## Do / Don't

- Do: 新しい色が必要になったら tokens.py に意味名で追加 → qss.py に生成関数 → golden 更新。
- Do: カードテンプレートの色は `var(--vs-*)` のみ（`tests/gui/test_theme_export.py` が検証）。
- Don't: view/VM に hex・`rgba(`・`QColor(リテラル)` を書く（ガードテストが落とす）。
- Don't: Claude Design 上でカードを直接編集する（次回 push で消える — 真実はリポジトリ）。

## 決定履歴

運用ループ手順3で採用した決定をここに追記する（日付・変更トークン・理由・PR）。

- 2026-07-17: `chrome_frame` 新設（surface1 系初期値・`border_chip` と同値の別役割）。
  4領域境界の視認性改善 — スパイク実機比較（現状／A separator のみ／B 1px 枠／C 背景差＋枠）
  でユーザーが B を選択（配色不変を優先・C は将来反復で再検討可）。設計は
  [region-frames spec](superpowers/specs/2026-07-17-region-frames-design.md)。PR #123。
- 2026-07-19: アクティブパネル枠を複数プロット時のみに（トークン値変更なし・適用
  条件のみ）。単一プロットの常時 amber 枠は情報を運ばず視線を奪う（UIUX 監査
  課題C）— DP15「1枚でも枠（一貫性）」を意図的に supersede。出典:
  claude.ai/design 検討の持ち帰りメモ（2026-07-18 UIUX コンセプト）＋カード
  「コンセプトとメイン画面案」3a/4a。設計は
  [active-frame spec](superpowers/specs/2026-07-18-active-frame-multi-panel-design.md)。
  PR #127。
- 2026-07-20: カーソル読み値をフロートチップ→常設ペイン化（`surface_readout_panel`/
  `delta_negative`/`delta_positive` 新設）。GraphAreaView 右ペイン・アクティブパネル
  束縛・行クリックで波形ハイライト・単一時 A/min–max 列・比較時 A/B/Δ＋Δ符号着色。
  出典: claude.ai/design 検討の持ち帰りメモ（2026-07-18）＋カード「コンセプトと
  メイン画面案」2a/2b/4b。設計は
  [readout-pane spec](superpowers/specs/2026-07-19-readout-pane-design.md)。PR #129。
- 2026-07-20: File/Channel/Diagnostics の3ドックに共通の折りたたみを追加（トークン
  変更なし・構造 UI）。QDockWidget に最小化フラグが無いため `CollapsibleDockTitleBar`
  を `setTitleBarWidget` で composition・畳み=内容 hide＋maxHeight クランプ・展開=
  `resizeDocks` で高さ復元・QSettings 永続（`dockCollapsed`）。過去 defer した FU-14 を
  実現。chevron アイコンは vendored Lucide（`chrome_text` 着色）で追加のみ。出典: inbox
  決定メモ③（Diagnostics ドロワー化）＋ユーザー要望「File/Channel も折りたたみ可能に」
  で3ドック共通へ拡張。設計は
  [collapsible-docks spec](superpowers/specs/2026-07-20-collapsible-docks-design.md)。PR #131。
  PR #137。
- 2026-07-21: 軸アイデンティティ契約 Stage A（PR #135・トークン変更なし・構造 UI＋表示規則）。
  軸ラベル=代表（最古）波形の name/unit の対（ユーザー決定: 混在時も代表を表示・マーカー不採用）／
  per-axis `y_is_auto` 可視和集合フィット／オフスケールバッジ新設（色は既存 `accent_active`・
  警告系 amber の意味論は増分0 のトークン整理で再訪）。**凍結ベースライン 02-05/09 を意図的更新**
  （VehSpd 初可視化=UX-03 根治の実証画像）し dark/light 再撮影＋Ground Truth 38 ファイル再同期済み。
  設計は [stage-a spec](superpowers/specs/2026-07-21-axis-identity-stage-a-design.md)。
- 2026-07-20: 折りたたみを辺対応化（増分C 手直し・トークン変更なし）。畳む方向をドックの
  接する辺で動的決定（左右=幅を詰めて全高の縦レール＋縦書きタブ・下=高さを詰めて全幅の
  横帯＋左寄せチップ）。畳んだドックは hide し、中央 widget を包む `CentralWithRails` の
  辺スロットに置いた `DockCollapseRail` へ content サイズのタブを出す（maxHeight クランプ
  方式を差し替え）。**`CentralWithRails` は雑メモ #17（レール最外ドック化・candidate A・
  commit 486a94b）で廃止済み — レールは中央の縁でなく各辺の最外 `QDockWidget` に据える
  （中央は `central_stack` を直接 `setCentralWidget`）。** 上端配置は3ドックの
  `setAllowedAreas(Left|Right|Bottom)` で禁止。
  展開シェブロンは開く方向を指す（右=`chevron_left`・下=`chevron_up`、追加のみ）。出典:
  増分C（PR #131）の実機確認で「右ドックが横のまま薄くなるのは想定と違う」とユーザー指摘。
  付随して撮影スクリプトの QSettings 隔離バグ（`setDefaultFormat`+`setPath` は
  `QSettings(org, app)` の NativeFormat に効かず実設定が漏れる）を conftest 同型の
  `_ORG`/`_APP` 差し替え＋clear で実効化（凍結比較の決定性を回復）。設計は
  [edge-aware-dock-collapse spec](superpowers/specs/2026-07-20-edge-aware-dock-collapse-design.md)。PR #133。
  PR #139。
- 2026-07-21: 増分0「知覚の床」— UIUX 敵対的レビューカタログの課題バンドル（UX-12・
  UX-18・UX-21 応急・UX-27・UX-29・UX-35・UX-38・UX-39・UX-42・UX-49・UX-07 応急）
  を一斉是正。**トークン値8件変更**: `error` #c0392b→**#f38ba8**（on #1e1e2e 3.02→
  7.08:1・DARK のみ、LIGHT は現値 #c0392b 維持）／`text_secondary` #7f849c→
  **#9399b2**（4.44→5.81:1・DARK のみ）／`typography.small_px` 9→**10**（DARK の
  み定義・LIGHT は参照共有で自動追従）／`grid_alpha` 60→**150**（fg150 on black
  1.34→2.95:1・DARK のみ）／`signal_palette` tab10 10色→**Okabe-Ito 基調 8色・
  黒調整** `#56B4E9 #E69F00 #00C08B #F0E442 #FF6E4A #D98BC0 #9A8CFF #C8C8C8`
  （黒背景最小 3.55→7.57:1・CVD 最小 ΔE protan 4.8→13.2／deutan 7.3→16.9）／
  `drop_highlight` #1f77b4→**#94e2d5**（teal・パレット外色相へ分離）／`cursor_b`
  #89b4fa→**#74c7ec**（`chrome_highlight` から ΔE23.4 分離）／`axis_move_indicator`/
  `axis_move_fill` (255,165,0)→**#f59e0b**（`accent_active` と意図的に同値化）。
  **パレット8色 Okabe-Ito 黒調整を最終確定**（暫定ではない — 実測根拠・敵対的レビュー
  24件反映・許容判断2点はユーザー承認済み: `#E69F00` vs `accent_active` ΔE7.2は
  曲線/クローム装飾の文脈分離、`#56B4E9` vs `preview_curve` ΔE6.6は別窓限定で許容）。
  **この8色パレットの色相基準を増分E「ファイル=色相ファミリー」の色割当設計の前提と
  する制約として記録する**（増分E 設計時に本エントリを参照すること）。非トークン
  変更: QLineEdit に常時1px枠＋focus枠（QSpinBox/QDoubleSpinBox 内部の
  `qt_spinbox_lineedit` は carve-out で対象外・二重枠回避）／常用ボタンの当たり判定
  を高さ24px以上へ（パネル+/×・ドックタイトルバーのフロート/✕、`fixedSize` でなく
  `minimumHeight`）／export アイコンを `save.svg`→Lucide `download.svg` に差し替え
  （`save.svg` は増分F 用に温存）／初期ドック比率 File:Channel≈1:4（show 後適用・
  Reset Layout も同一比率）・ChannelBrowser Name列 `Stretch`・Unit列は prod 安全な
  先頭50行サンプリング幅方式（`ResizeToContents` の O(n) reset 走査を回避）・
  Diagnostics メッセージ列 `Stretch`。凍結カタログ dark/light 9状態を撮影し spec §4
  の per-state 期待差分表と全状態突合（想定外の差分なし・06/07のスピンボックスは
  二重枠にならず carve-out 合格・08は完全一致・07は完全一致〔対象 QLineEdit 無し〕・
  06/07 の高さが605→600pxへ縮むのは Fusion 既定のsunken枠より薄い1px枠へ置換した
  結果で想定内）。パネル+/× glyph の ~2px 下シフトは当たり判定24px化の副作用として
  spec §4 に追記。**ローカルのベースライン（`screenshots_catalog_dark/light` 両テーマ）
  とエクスポート一式（`design_export/{dark,light}`）は更新済み** — in-place 再撮影後
  `compare_screenshots.py` で増分0撮影との完全一致（exit 0・9/9 states 両テーマ）を
  実証し、決定的撮影の再現性を確認。**claude.ai/design への再同期のみマージ後に実施**
  （controller）。設計は
  [inc0 spec](superpowers/specs/2026-07-21-perception-floor-inc0-design.md)。
- 2026-07-22: 計測 IA 刷新（旧・計測モードバーの全面再設計・トークン2個新設）。**ユーザー
  決定 v3（モックアップ3版で確定・5点）**: (1) 専用計測バーは作らない、(2) カーソル即値
  （A/B/Δt）はステータスバー左に常設（既存メッセージは右へ）、(3) カーソル A/B の表示
  切替・補間方式は Analyze メニュー＋右クリックのみ、(4) グリッド・Sync X は右クリック
  のみ（既存 Sync X チェックボックスは撤去）、(5) タブ行右肩には「読み値」トグルのみ
  残す。**supersede 2件**: spec-B（readout-pane 増分B）案b「カーソル未設置時はプレース
  ホルダ文言」→ **凡例モード**（色スウォッチ＋信号名＋[unit]、信号がある限りこれで代替
  し信号ゼロのときだけペイン収納）／UIUX 敵対的レビューカタログ UX-32 の「Sync X を
  View メニューへ追加」推奨 → 決定(4) の右クリックのみで supersede。
  **新トークン `chrome_cursor_a`/`chrome_cursor_b`**（ステータスバー左の計測即値専用・
  DARK は既存 `cursor_a`/`cursor_b` と同値の別役割）。LIGHT は明面（`chrome_window`
  #eff1f5）で発光しない `cursor_a`/`cursor_b` に代え実測選定した濃色 `#8a6100`
  （4.90:1）/`#106a8f`（5.34:1）— いずれも WCAG AA (4.5:1) 達成。構造面: タブ内全
  パネルが同一 `CursorState` オブジェクトを共有（transient・rebuild/`add_panel` 後も
  不変）に置き換え、`set_cursor_b` を「A 未設置なら no-op・それ以外は delta_enabled
  を暗黙 true にした上で notify は従来どおり `"delta"` 単発」へ対称化。Shift+クリック
  でカーソル B を直接設置（曲線上/カーソル線近傍でも ZONE_PLOT 全域で最優先）。時刻
  書式を `.4g` から固定小数3桁へ、readout ヘッダを「A/B ラベル色付き・● マーカー廃止」
  の新書式へ。**①ゲートで検出した production バグ根治1件**: `GraphAreaVM` の area
  レベル `_notify("cursor")` が `GraphAreaView._on_vm_change` の汎用 `_rebuild()` に
  落ち、カーソル移動・線ドラッグのたびタブ内全パネル（ドラッグ中の InfiniteLine 含む）
  を破棄再構築していた実バグを検出・修正（`"cursor"` 専用の軽量経路 `_sync_readout()`
  を新設）。**Task 10 で追加発見（凍結スクショの信頼性に関わる・production 非該当）**:
  凍結カタログ 03/04/05/09 の readout ペインに旧モード（凡例）の行テキストが新モード
  （計測）の行と重なって描画される artifact を検出。実機再現実験で根因を特定 — 撮影
  スクリプトの `settle()` は `app.processEvents()` のみを回すが、`deleteLater()` は
  実 `app.exec()` ループ配下でのみ確実に flush される Qt の仕様で、`processEvents()`
  単独では 200 回ポンプしても解放されない（実アプリは `app.exec()` を実際に回すため
  この artifact は起きない＝production 非該当と実証）。`scripts/capture_ui_screenshots.py`
  の `settle()` に `QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)`
  を明示追加して根治（撮影専用ツールの修正・トークン/production コード変更なし）。
  **凍結ベースライン更新済み**（`screenshots_catalog_dark/light` 両テーマを in-place
  再撮影 → 撮影直後のカタログとの完全一致 exit 0・9/9 states 両テーマで決定的撮影を
  実証）・エクスポート一式（`design_export/{dark,light}`）も新トークン反映済みで再生成
  済み。**claude.ai/design への再同期のみマージ後に実施**（controller）。設計は
  [measurement-ia spec](superpowers/specs/2026-07-21-measurement-ia-design.md)。
- 2026-07-22: 増分D-1「文言 OS」（日本語一次言語化・対訳表・表記規約 — トークン
  変更なし・全 GUI 文言の統治構造）。出典: UIUX 敵対的レビューカタログ推奨4
  （増分D 再定義）の第1層。`src/valisync/gui/strings.py` 新設（GUI 文言の単一の
  真実・属性参照で typo を loud-fail 化）＋本節「表記規約」（R-01〜R-13）。**判断点
  14件を全件ユーザー確定**（2026-07-22 承認）: #1 File Browser ドック名=
  **ファイルブラウザ**（推奨「ファイル」から変更・参照文の読みやすさ）／#2
  Channel Browser ドック名=**チャンネルブラウザ**（推奨「信号」から変更・
  CANape 語彙の ADAS ユーザーに馴染む現行音写を保持——**UX-11「ドック名も信号系へ
  改名」はこの決定で supersede**、リスト内容/助数詞の「信号」統一は維持）／#7
  Diagnostics 列ヘッダ=**データソース**（推奨「ファイル」から変更・診断の発生元
  を指す列名として明確）／他11件は推奨どおり確定（カタカナ長音は省略式・読み値
  統計列 mean/min/max/std/count と X軸ラベル Time は意図的英語維持・Reset All Axes
  →すべての軸をオートフィット・Clear→クリア・Data Explorer の Load File→ファイルを
  開く・Qt 標準ボタンの日本語化は QTranslator 基盤＋要所 setText・core 検証系
  ValueError は core 側リテラルで日本語化・曲線メニュー「非表示」は checkable 化
  せず現状維持・ステータスバー診断誘導文は「診断」の同語連続を避ける言い換え・
  ニーモニクスはメニューバー面のみ付与）。**Qt 標準ボタンの QTranslator 導入**
  （`theme/apply.py` に qtbase 日本語 `.qm` ロードを追加・module-level singleton＋
  install-once 冪等化＋QApplication 存在ガードで `apply_startup_theme` の毎回呼出
  に対し安全・実機で QDialogButtonBox が「キャンセル」等・Data Explorer の
  QFileSystemModel 列ヘッダが「名前/サイズ/タイプ」等へ変化することを確認。ネイ
  ティブ QFileDialog は OS 供給文言のため対象外）。ニーモニクス（G-46・メニュー
  バー面のみ）は実メニュー walk テスト（build_main_window の実 QMenuBar 走査＋
  コンテキストメニュービルダー全数）で重複ゼロ・付与漏れ双方向を検査、Alt+文字
  の実 OS キー入力到達も realgui で実証（`test_menu_mnemonics_realclick.py` —
  合成 Alt 単体タップは本環境で Qt に届かず、Alt を押しっぱなしで文字キーを叩く
  保持アクセラレータ形に切替えて解決）。**凍結ベースライン全面更新**
  （`screenshots_catalog_dark/light` 両テーマ9状態を新文言で再撮影 — 想定差分は
  テキスト＋テキスト起因のコントロール寸法変化のみ〔18枚目視で確認〕・**プロット
  viewport crop 比較モードを新設**〔`compare_screenshots.py --crop-meta`・
  `capture_ui_screenshots.py` が保存する `{state}.viewport.json` の矩形のみを
  比較〕し波形描画がピクセル不変であることを機械証明・再撮影で決定性 exit 0 実証）。
  realgui フル 92/92 pass。**claude.ai/design への再同期のみマージ後に実施**
  （controller）。設計は
  [incd-strings-os spec](superpowers/specs/2026-07-22-incd-strings-os-design.md)。
- 2026-07-22: 診断・読み値の整合性修正（D-2 不採用の代替・トークン変更なし）。増分
  D-2「通知センター型診断」はモックアップ提示後にユーザー不採用（「こんな豪華な診断
  ウィンドウは不要・現状のままで ok」）。代替として現状の見た目・構造・挙動契約を
  維持したまま実バグ/不整合6件（B1-B6）のみを是正: B1=フッターカウンタへ ℹ 追加
  （`counts()` 3-tuple 化）／B2=フィルタ3ボタンの checkable 排他化＋絞り込み0件文言
  のフィルタ文脈化（**supersede**: 「絞り込み0件と診断ゼロの同一表示」の by-design は
  [feedback-errors spec §7](superpowers/specs/2026-07-02-gui-feedback-errors-design.md)
  （『空時はプレースホルダ』）が根拠だったが、UXG 監査で UX-06「誤認装置」認定と
  なったため本修正で覆す）／B3=メッセージセルへ全文ツールチップ／B4=展開側タイトル
  バーのシェブロンをドックの辺から解決（下端の診断は「v」— レール側辺対応
  〔PR #133〕との不整合を解消）／B5=Clear に確認ダイアログ（非可逆操作の誤クリック
  防止）／B6=読み値ペインの縦スクロール化（`QScrollArea`・幅の契約は
  `sizeHint`/`minimumSizeHint` override で保存し非オーバーフロー時はピクセル不変。
  **UXG-17 逸脱の明記**: 列見出し行は固定化せず行と共にスクロールする意図的簡易形
  〔固定化は2グリッド分割＋列幅同期の再設計を要し「現状のまま」方針に反するため
  見送り〕・**縦オーバーフロー時のみスクロールバー extent 分（約14px）広がるのは
  意図的例外**〔凍結比較対象外の状態〕）。realgui フル 94/94 pass。凍結ベースライン
  全面更新（`screenshots_catalog_dark/light` 両テーマ9状態を再撮影 — 想定差分は診断
  ドック内のみ〔カウンタ ℹ 追加・「すべて」ボタンの checked 枠・下端タイトルバーの
  シェブロン >→v〕に限定されることを実証・プロット viewport は `--crop-meta` 完全
  一致、読み値ペイン/プロット全体/divider 位置はピクセル不変〔差分画像で診断ドック
  外に相違ゼロを目視確認〕・再撮影で決定性 exit 0 実証）。**claude.ai/design への
  再同期とエクスポート再生成はマージ後に実施**（controller）。設計は
  [diag-readout-consistency spec](superpowers/specs/2026-07-22-diag-readout-consistency-design.md)。
- 2026-07-22: 増分D-3「三態トグル＋アイコン統一」（UX-34/45・**絵文字グリフ置換の
  defer 解除**〔増分5 で defer した方針をここで解除・design.md 記録が解除の証跡〕）。
  **新トークン `warning`/`info`**（DARK `#fab387`/`#7aa2f7`・LIGHT `#b0741a`/
  `#1a5fb4`・診断 warning/info の意味色・**非テキスト WCAG 1.4.11 の 3:1 基準**を
  `chrome_base`/`chrome_window` 双方×両テーマで機械検証する相対輝度→コントラスト比
  ヘルパを新設）。**vendored Lucide SVG 11 個**（circle-x/triangle-alert/info/x/copy/
  panel-{left,right,bottom}[_close] ×2）＋`icons.icon()` を `color`/`active_color`/
  `selected_color` 引数へ拡張（Normal 上書き／QIcon.Mode.Active・Selected への追加
  着色 — QSS はピクスマップ色を変えられないため hover 赤・選択セル可視性はこの経路
  でのみ実現可能）。**wheel パッケージングテスト新設**（`uv build --wheel` → zipfile
  で新規 SVG 11 個の同梱を assert・増分5 の「wheel からアイコンが黙って落ちる」
  false-green の恒久防波堤・実測 wheel テストは本増分が初）。
  **A: ドックトグルの三態化**（UX-45）— View メニュー/ツールバー共有の
  `toggleViewAction()` を、ドックごと1個のカスタム checkable QAction へ置換。
  可視述語は `not dock.isHidden()` の**都度ポーリング**（`visibilityChanged`/
  `dockLocationChanged` のシグナル**引数は判定に使用禁止** — tabify 背面/フロートで
  嘘値になることを実測）＋辺は `dockWidgetArea()` の都度再プローブ。展開/レール/
  非表示の3状態（レールは checked 維持＋partial アイコンで Qt 標準 toggleViewAction
  とパリティ）。handler は `triggered` 接続のみ（`toggled` は禁止 — プログラム的
  setChecked と無限振動する）。File/Channel は同一辺で三態アイコンが同一になり
  区別不能なため、ツールバーの3ボタンのみ `ToolButtonTextBesideIcon`。
  **B: 診断レベルアイコンの Lucide 化** — レベル列 `setIcon`（テキスト空・unknown
  は "?" 存置）＋カウンタ行をアイコン+数値の3ペア HBox 化。`selected_color` 併載で
  選択行上でも視認可能（旧絵文字はテーマの選択ハイライトへ埋没する退行があった）。
  **C: タブ✕・タイトルバーの統一** — タブ✕は `setTabsClosable(False)`＋完全自前
  QToolButton（Qt 既定ボタンは setTabButton 置換後も削除されず rebuild ごとに蓄積
  する実測リークのため既定ボタン生成自体を停止）。クリックは自動発火しないため
  tabBar 上の恒等走査で index を都度解決して `tabCloseRequested.emit`。hover 赤は
  `close_hover` トークンを `QIcon.Mode.Active` で消費。タイトルバー close/float は
  Lucide 化（`float_dock`=copy グリフ・iconSize 16px 明示）。
  **①ゲートで実機発見・対応した事項（Task 4）**:
  (1) `tests/realgui/test_hit_targets.py` の float/close/タブ✕ 3 テストが実機で
  RED — icon-only 16px 化で自然高さ (minimumSizeHint) が chevron と同型の 24px に
  達し、既存の「旧 rect 外・新 rect 内」拡張ヒット式が old_h==new_h==24 の境界で
  ボタン下端の1px外（無効行）に落ちて実クリックが不発になっていた。共有ヘルパを
  old_h>=24 でボタン中央へフォールバックする分岐へ修正。さらに realgui 51ファイル
  一括実行でのみ、同じ3ボタンの natural height が 23px（境界の反対側）に観測される
  実行順依存の環境差を検出（フォント計量の丸め）— old_h の具体値を assert する
  のは過剰特定と判断し削除、実クリックの効果のみを検証する形へ是正。単体/4バッチ
  実行では 95/95 全 pass（バッチ実行のたび再現）。(2) 同一 realgui 一括実行のみで
  再現する2件の**未修正・D-3 と無関係の既知フレーク**を確認: `test_hit_targets.py::
  test_chevron_already_meets_24px_height`（D-3 が触れていない pre-existing 測定
  assert・height 24→23 の同型変動）と `test_expansion_dialog_realinput.py::
  test_bottom_checkbox_reachable_by_real_wheel_then_ok`（D-3 が触れていないダイアログ
  wheel スクロールテスト）— いずれも単体/2ファイル再実行では 100% pass し、51ファイル
  連続実行時のみ発生する環境状態ドリフト（多数の実ウィンドウ生成の累積と推測）に
  起因すると判断、本増分のスコープ外として現状のまま記録のみ。(3) タブ✕は
  `add_tab()` 直後の `_rebuild` が生成した新規ボタンの `mapToGlobal` が isVisible
  判定直後は暫定位置を返すレイアウト未確定 race を実機で検出、数ターンの
  processEvents pump で解消。**float_dock（copy グリフ）の可読性は目視で要注意
  — 「コピー/複製」を強く想起させ「フロート化」の意図が単体では読み取りにくい
  （ツールチップ「フロート」で補完される前提）。DONE_WITH_CONCERNS として記録し、
  将来のアイコン反復で undock 系グリフへの差し替えを検討候補とする**。
  実機スクショ（`design_export/evidence_d3/`）で三態の作り分け・File/Channel の
  TextBesideIcon 区別・診断3アイコンの amber 序列＋選択行視認・タブ✕ hover 赤
  （実マウス小刻みスイープ）・タイトルバーアイコンを確認。**凍結ベースライン
  更新**（`screenshots_catalog_dark/light` 両テーマ9状態を再撮影 — 想定差分は
  ツールバー〔TextBesideIcon 幅変化〕・File/Channel dock タイトルバー〔float/close
  アイコン〕・診断レベル列/カウンタに限定〔目視で診断ドック外・プロット面の相違
  ゼロを確認〕・`--crop-meta` でプロット viewport 完全一致・再撮影で決定性 exit 0
  実証）。realgui フル 95/95 pass（4バッチ）。**claude.ai/design への再同期は
  マージ後に実施**（controller）。設計は
  [d3-tristate-icons spec](superpowers/specs/2026-07-22-d3-tristate-icons-design.md)。
- 2026-07-23: E-0（表示名解決・UX-19）＋E-2（比較データモデル: 基準ファイル・
  同名信号の自動重ね・ファイル=色相ファミリー）。**ドック統合の廃止**: UIUX
  再設計プログラムの増分E は元々「File Browser・Channel Browser・Data Explorer
  を単一データサイドバーへ統合」（推奨5・[catalog](uiux-adversarial-review-catalog.md)）
  を核としていたが、コンセプト提示時にユーザーが統合部分を却下（3ドック構成を
  維持）。残る E-0/E-2 は統合サイドバーではなく**既存の FileBrowser 上へ操作面を
  載せ替えた**再設計として実施（`display_names.py` 4API・`AppViewModel` 基準/
  色相状態・FileBrowser 右クリック2項目）。UX-21/UX-29(Data Explorer 側)/UX-30 は
  対応先の増分Eドック統合を失い見送りとしてカタログに記録（各行参照）。**判断点
  5件**（ユーザー確定・spec 冒頭に集約）: (1) 比較モード遷移時（2ファイル目ロード）
  に `color_is_auto` エントリを自動再着色（`set_color` 済みの手動色は不変）／
  (2) 基準ファイルの既定=最初のロードファイル（unload で残存ロード順先頭へ自動
  移行）／(3) 同名信号の自動重ねは単位不一致（`sig.metadata["unit"]` 完全一致・
  双方空は通過）でスキップ／(4) **読み値の同名識別はファイルキー併記「VehSpd
  (mf4_1)」— E-0「`::` を全面撤去」の唯一の例外として、可視集合内で裸名が2ファイル
  以上から衝突する場合のみ発火**（識別性を保つための意図的な逸脱）／(5) ファイル=
  色相ファミリーは明度バリアント3段（0=無変化・1=明/2=暗）。**`[idx]` 曖昧化の
  除外はローダーフラグで判定**: LD-08 dedupe サフィックス（同名信号が同一ファイル
  内で衝突した際の disambiguation）はファイル間で付与順が非対称なため文字列一致
  では安全に照合できず、ローダーが付与時に記録する `metadata["name_deduplicated"]`
  のみを根拠に自動重ねの対象から除外する（LD-14 の配列展開名 `Name[i][j]` は
  文字列上は類似だが決定的照合可能なため除外しない）。**CSV ヘッダは空白なし
  形式** `{bare}({group_key})`（表示 UI の「{bare} ({group_key})」とは別形式 —
  エクスポートの区切り文字がスペースのため空白を含めるとヘッダ列がずれる）。
  **GUI 発の診断記録はしない**（同名重ねの結果はステータスバー要約のみ・新規
  診断機構は YAGNI として意図的に簡略化）。**unload の非対称**: 2→1ファイルに
  戻った際は既存曲線の色を再着色しない（色の安定性優先）— 新規追加のみ
  count-mod フォールバックへ復帰する。**CVD 検証パイプラインを確定**:
  `hue_variant` の明度シフト量 `ΔL=0.15` は Machado, Oliveira & Fernandes (2009)
  severity-1.0 の protanopia/deuteranopia/tritanopia 行列（線形 RGB 適用）＋
  CIE76 ΔE（Lab, D65）で確定・test-lock（`src/valisync/gui/color_variants.py`）。
  同一ファミリー内の最悪分離 ΔE6.89（`#F0E442` tritanopia, step0 vs step1）を
  実証し、既存の2つのタイトな分離マージン（`#E69F00` vs `accent_active` ΔE7.2・
  `#56B4E9` vs `preview_curve` ΔE6.6 — いずれも増分0 で記録済み）を侵食しないこと
  も確認。**残存する第3の許容マージンとして記録**: 無彩色8色目 (`#C8C8C8`) の
  darkened バリアント (step2) が `plot_foreground` (`#969696`・軸/目盛文字) から
  ΔE4.54 — 同一ファイルの3本目の信号が灰色ファミリーの最暗段を要求したときのみ
  到達する狭いが知覚可能なマージンで、ブロッカーではないが将来の色見直しで
  参照すべき制約として明記する。**Task 4 凍結検証（本エントリの実施結果）**:
  realgui フル 93/96 pass（残 3 件は本ブランチと無関係の既知環境ドリフトフレーク
  `test_hit_targets.py::test_chevron_already_meets_24px_height`・
  `test_hit_targets.py::test_tab_close_button_extended_hit_removes_tab`・
  `test_expansion_dialog_realinput.py::test_bottom_checkbox_reachable_by_real_wheel_then_ok`
  — いずれも単体実行では 100% pass し、D-3 で既に記録済みの「51ファイル一括実行
  でのみ発生する自然高さ 23px/24px 境界ドリフト」クラスタの3件目〔新規再現〕。
  一括実行中に実バグを1件検出・修正: `test_active_panel_flow.py::
  test_dblclick_opens_preview_window` がプレビュー windowTitle に生キー
  （`csv_1::speed`）を期待する stale assert のまま残っていた（Task 1 の '::' 追随
  監査が `tests/gui/` のみを対象にし `tests/realgui/` を見落としていた）— bare
  表示名 `endswith("speed")` へ是正）。新設 `tests/realgui/
  test_comparison_model_realclick.py`（小型 CSV 2 ファイル・実 OS 右クリック
  「基準の同名信号を重ねる」→ 同軸重畳の実描画・色相ファミリー実ピクセル
  （`pen_color` の実測値と実 grabWindow スクショを突き合わせ）・読み値の
  「(csv_1)」/「(csv_2)」併記・基準バッジ「◎基準」＋色チップの実表示を実証。
  あわせて Y軸メニュー曲線一覧とエクスポートツリーからも `::` が消えたことを実機
  確認（`design_export/evidence_e2/`）。**凍結 per-state 契約**: 01/07/08 完全
  一致・02-05/09 は意図差分（readout ペインの表示名が生キーから bare 名へ短縮）
  で確認、06（エクスポートダイアログ）はツリー葉テキストのみの差分（今回は
  ダイアログ幅変化なし・目視で他退行なしを確認）。**発見事項（想定より広いが
  良性と判定）**: readout ペインは `QSplitter` の stretch-factor 0（プロット側=1）
  でサイズを持つため、表示名短縮でペインの `sizeHint` 幅が縮むと、その分プロット
  側の viewport 幅が自動的に広がる（895px→936px 等）— spec §6 の「viewport crop
  は全状態一致」という想定より広い、しかし完全に理解済みで色/データに一切影響
  しない、readout 名短縮の直接の構造的帰結（曲線ピクセルの水平位置がわずかに
  ずれるのみで色・本数・データ形状は before/after で完全同一なことを diff 画像で
  確認）。ベースラインを昇格・再撮影で決定性 exit 0（9/9 states・両テーマ）を実証。
  設計は [E-0+E-2 spec](superpowers/specs/2026-07-23-e2-comparison-model-design.md)。
  **claude.ai/design への再同期はマージ後に実施**（controller）。
- 2026-07-23: 比較モードのユーザー切り替え（E-2 拡張・トークン変更なし・同一ブランチ
  `feature/e2-comparison-model` へ畳んで出荷）。E-2 出荷直後のユーザー決定で、比較
  モード（色相ファミリー・◎基準バッジ・チップ・比較 affordance）の起動を「ファイル
  数 ≥ 2 の自動判定」から**ユーザーが明示的に切り替えるフラグ**へ変更 — 既定は
  シングル（count-mod・比較 affordance なし）、Analyze メニューの checkable 「比較
  モード」項目で opt-in する。**ユーザー決定3点（確定・spec 冒頭）**: (1) 既定=
  シングル、(2) 切り替え UI=Analyze メニュー、(3) OFF 遷移=色相ファミリー色を
  固定（count-mod へ戻さない・手動ピン色は常に不変）。**フラグは transient**
  （`reference_file_key` と同じく QSettings 非永続・再起動で常に既定シングルへ戻る
  — 将来の `.vsession`〔増分F〕でセッション内真実面を確定するまでの意図的な設計）。
  `AppViewModel.is_comparison_mode()` を「明示フラグ AND 2+ファイル」の単一述語へ
  置換（全 consumer が同じ1点を読むため追従は自動）、`comparison_enabled`（生フラグ・
  メニュー checkstate 用）と使い分ける。OFF 凍結は新規メカニズムでなく
  `reapply_auto_colors` の既存 `hue is None: continue` 分岐（既存色を触らない）
  から自然に導かれる — ON/OFF で分岐しない単一の再着色呼び出しで両方が成立する。
  FileBrowser の比較 affordance（「基準に設定」/「基準の同名信号を重ねる」）を
  比較モードへ対称化（旧は「基準に設定」のみ常時表示・単一モードで視覚的に無効な
  操作が可能に見える非対称を解消）。**8 レンズ敵対的レビュー（34 findings・33
  confirmed=全 Minor）を M1-M16 として反映**: transient 化（M1）・`inspect()` 露出
  （M2）・docstring 更新（M3）・QAction は MainWindow 所有の独立 checkable（panel-
  scoped `AnalysisActions` に載せない、M4）・ニーモニクス非付与（兄弟葉項目と整合、
  M5）・2ファイル未満での checked+disabled 保持（「設定は保持・2つ以上で再適用」の
  意図的到達状態、M6）・affordance 対称化（M7）・基準ファイルのステータス開示（M8）・
  2→1 unload 後の凍結（M9）・ON 再着色の専用テスト（M10）・resolver の全パネル到達
  保証（M11）・OFF の no-churn（invalidate/notify を発生させない、M12）・既存 E-2
  テストのサイト別追随（機械的挿入禁止、M13）・E-0（表示名）との独立性維持（M14/
  M15）・凍結カタログは差分ゼロが正しい期待（M16、下記）。**カタログ検証（M16）**:
  現行カタログは全状態1ファイルのため `is_comparison_mode()` は恒常 False —
  比較モードのフラグ導入はカタログ表示を一切変えない。01-09 全状態が既存ベース
  ライン（PR #145 時点）と完全一致することを両テーマ・`--crop-meta`・通常比較の
  双方で実証し（決定性=フレッシュ再撮影でも exit 0）、家系色の実描画検証は
  realgui 一本化とした（カタログには比較状態の被覆が元々存在しないため）。**realgui
  T-C1（`tests/realgui/test_comparison_model_realclick.py` に追加）が家系色の一次
  被覆**: 2ファイルロード→4信号を直接プロット（「重ねる」ボタンは OFF では非表示
  のため使わない）→トグル前は count-mod（add順2番目の EngineSpeed が
  palette[1]=橙になる、ファイル非依存）を実ピクセルで確認→実 OS でメニューバー
  →Analyze→「比較モード」を実クリック→家系色（同ファイルの2信号が青ファミリー
  に揃う）が実ピクセルで出現→再クリックで OFF→色が変化しない（凍結）ことを実
  ピクセルで確認→◎基準バッジの出現/消滅も実証。スクショは
  `design_export/evidence_comparison_toggle/`（3枚: トグル前=4色分散・ON後=
  青系2＋橙系2に収束＋◎基準バッジ＋ステータス「比較モード: 基準ファイル=a.csv」・
  OFF後=ON と同一色のまま凍結＋バッジ消滅）。この可視化が「比較モードは色を
  ファイルごとに束ねる」という機能そのものの動かぬ証拠になる。**既存 E-2 realgui
  テストの追随**: `test_reference_overlay_hue_family_and_e0_display_names`
  （比較 affordance・家系色・バッジ・チップを検証する既存テスト）はフラグ既定
  OFF 化で RED 化するため `set_comparison_mode(True)` を明示追加（意図は比較挙動
  の検証そのものなので機械挿入ではなく妥当）。`tests/gui/` 側も同型のサイト別
  追随を実施（`test_app_viewmodel.py`/`test_file_browser_view.py`/
  `test_file_browser_vm.py`/`test_file_list_model.py`/`test_graph_area_vm.py`
  の計19サイト＋realgui 1サイト＝計20サイトを file:line 単位で確認、単一モード
  期待の既存テストは意図的にフラグ OFF のまま存置）。realgui フル 97/97 pass
  （既知の実行順依存フォント計量フレーク3件〔`test_hit_targets.py` chevron/
  タブ✕・`test_expansion_dialog_realinput.py` wheel — D-3 増分で既に記録済みの
  「51ファイル一括実行でのみ発生」クラスタ〕は単体/小グループでは 100% pass し
  本増分と無関係と確認）。設計は
  [comparison-mode-toggle spec](superpowers/specs/2026-07-23-comparison-mode-toggle-design.md)。
  **claude.ai/design への再同期はマージ後に実施**（controller — トークン変更が
  ないため実質no-op）。
- 2026-07-23: 増分F-0「安全な取込・範囲付き出力・プレビューラベル」（UX-05/UX-28/
  UX-43・**新トークン `chrome_signal_highlight`**）。出典は UIUX 敵対的レビュー
  catalog 推奨6「入口と出口の再設計」の先行実施分（F-1 セッション永続化・F-2
  Welcome 再開ハブは今後検討へ defer）。3パート独立（別ダイアログ）だが「入口と
  出口の安全化」として1増分にまとめた。**UX-05（データ破損直結）**: CSV 取込
  ダイアログのプレビューヘッダが Qt 既定の1始まりでスピン（0始まり）と1ずれる
  off-by-one を構造解消 — `_refresh()` で `setHorizontalHeaderLabels` を明示設定
  し「{列番号(0始まり)}: {列名}」表記に統一（列名源は `has_header` のみ・
  `header_row` という識別子は存在しない）。列ハイライトは**二層構造**（レビュー
  Important 是正）: データセルは低 alpha（45）ティントで文字色を `chrome_text`
  固定のまま保ち両テーマ AA（4.5:1以上）を維持、列マーキング（どの列が時間/信号
  か）は不透明ヘッダセル＋輝度ベース黒/白文字（非テキスト/AA いずれも 3:1以上）
  に分離——「データ可読性」と「列識別」を同一セルに同居させると alpha を上げる
  ほど文字が埋没する（全4ケース 1.11〜1.96:1 で不可読だった）ため。**新トークン
  `chrome_signal_highlight`**（DARK は `drop_highlight` と同値の別役割・LIGHT は
  色相を保ったまま暗くした専用値 `#0b4138`）。塗り優先は信号範囲→時間列の順
  （`ts_col ∈ 信号範囲` の過渡でも時間列が勝つ）。**UX-28**: `CsvExportOptions` に
  `time_start`/`time_end`（既定 None・末尾追加で後方互換）を追加し行時刻の閉区間
  `[start,end]` フィルタをタイムライン解決後に適用（`start>end` は
  `__post_init__` で ValueError・範囲外はヘッダのみの空出力）。ダイアログに出力
  範囲ラジオ3種（全期間/現在の表示範囲/カーソル A–B・既定=全期間）＋選択数
  フッター「N 信号を選択中」（フィルタ非依存の総選択数）を追加。**座標系契約
  （I2・最重要）**: エクスポートは常に base 信号の生タイムスタンプ座標で書き出す
  （R14 時間オフセットは非適用）。表示範囲/カーソル A–B の境界は表示座標
  （オフセット適用後）のため、選択信号のいずれかに非ゼロオフセットがあると
  単一の生時間窓へ写像できず、表示由来2ラジオを disabled にする（`[全期間]` は
  常に有効）。この判定は「現在チェック中の選択集合」に対しダイアログ内の選択
  変更のたびリアクティブに再評価する必要がある（x_range/cursor_a/cursor_b は
  開いた瞬間のスナップショットのままでよいが、オフセット活性だけは別性質の量
  ——ツリーは全ファイル全信号を列挙するため、初期選択だけを見た bool 1回きりの
  判定だと開いた後に別ファイルのオフセット信号を追加選択してもガードが働かない
  穴になる）。DI は `offset_for: Callable[[str], float] | None` という resolver
  を渡し、ダイアログ側が `_checked_keys()` に対しその場で評価する。**UX-43**:
  `SignalPreviewWindow` のプレビュープロットに軸ラベルを追加
  （bottom=`Time (s)`・left=`<display_name>(<unit>)`）。**`display_names.display_name()`
  を使い生キー（`mf4_1::VehSpd`）を直接使わない**（E-0 の `::` 撤去規約を維持・
  `SignalPreviewVM.axis_label_parts() -> tuple[str, str|None]` が公開アクセサ）。
  ラベル色は明示せず `plot_foreground` を継承。**Task 5（本エントリ）realgui ①
  ゲート**: 新設 `test_csv_import_dialog_realclick.py`（実 CSV→実スピンボタン
  クリック〔`QStyle.subControlRect` で up/down 矢印の実座標を取得〕→0始まり
  ヘッダ＋列ハイライトの実ピクセル確認・近傍探索 tolerance 方式——ヘッダ中心
  1点の厳密一致は Fusion の黒文字アンチエイリアス縁に当たり誤 RED になることを
  実測し `test_comparison_model_realclick.py` の `_find_pixel_near` と同型の
  近傍探索へ是正）／`test_export_range_realclick.py`（2カーソル設置→実クリック
  で [カーソル A–B] 選択→実 OK クリック→実ファイル書き出し→実読み直しで行の
  時間範囲が閉区間に収まること・全期間との行数差・I2 オフセットガードの実
  disabled 表示を実証）／`test_active_panel_flow.py::test_dblclick_opens_preview_window`
  拡張（実ダブルクリックで開いたプレビューの `getAxis("bottom").labelText/labelUnits`
  実測＋`::` 非露出を確認）。realgui フル 96/99 pass（3件は本増分と無関係の
  既知フレーク `test_hit_targets.py::test_chevron_already_meets_24px_height`・
  `test_hit_targets.py::test_tab_close_button_extended_hit_removes_tab`・
  `test_expansion_dialog_realinput.py::test_bottom_checkbox_reachable_by_real_wheel_then_ok`
  ——いずれも単体実行では 100% pass し、D-3/E-0+E-2 増分で既に記録済みの
  「51ファイル一括実行でのみ発生する実行順依存フォント計量ドリフト」クラスタの
  再現と確認）。エビデンス: `design_export/evidence_f0/`。**凍結カタログ**:
  06（エクスポートダイアログ）は DI 新署名へ更新し既設置済みの決定的カーソル
  （3.0/6.0・03_cursor 状態で使う値を再利用し値の重複を避けた）を注入して
  [カーソル A–B] enabled＋実範囲ラベル状態を撮影——高さ 600→720px（範囲ラジオ
  3行＋フッター追加）の想定内サイズ変化。07（CSV フォーマットダイアログ）は
  0始まりヘッダ＋列ハイライトの想定差分。08（信号プレビュー）は軸ラベル追加で
  プロット領域が縮小/再配置される想定差分——波形データ自体は新旧スクショの目視
  比較で同一形状/値域（同一 sawtooth 波形・同一時間軸0–12s）を確認（08 は
  spec §6 M により意図的に `--crop-meta` の比較対象外〔viewport.json を持たせ
  ない〕——プロット面 02-05/09 への非波及証明とスコープを分離するため）。01-05/09
  （main window 状態）は完全一致（`--crop-meta` exit 0・通常比較 exit 0 両テーマ）
  でプロット面への非波及を実証。ベースラインを昇格し再撮影で決定性 exit 0
  （両テーマ）を実証。設計は
  [F-0 spec](superpowers/specs/2026-07-23-f0-safe-import-range-export-design.md)。
  **claude.ai/design への再同期は新トークン `chrome_signal_highlight` を含めマージ後
  に実施**（controller）。**次候補=F-1（.vsession セッション永続化）/F-2（Welcome
  再開ハブ＋スナップショット共有）**——ユーザー決定で今後検討へ defer。
- 2026-07-24: 雑メモ解消（#14/#15/#17・トークン変更なし・ユーザー直接要望 —
  UIUX 敵対的レビュー catalog の UX/UXG とは別系統）。ブランチ `feature/memo-ux-cleanup`。
  **#14**: チャンネルブラウザのヘッダーから選択中ファイル名を除去し件数のみ表示
  （`CHANNEL_HEADER_NO_FILE`/`CHANNEL_HEADER_EMPTY_TMPL`/`CHANNEL_HEADER_COUNT_TMPL`
  改訂・未選択分岐も strings.py 化）＋ `header_label.setWordWrap(True)`（最小幅の
  保険）。コミット `ba1e087`。**#15**: 右クリックメニューに「信号プロパティを表示」
  を追加（`ACTION_SHOW_SIGNAL_PROPERTIES`）。**位置ベース**（`indexAt(pos)` の
  hit leaf key・ダブルクリックの `_emit_preview` と同型）を採用し選択ベース
  （`selected_signal_keys()`）は不採用 — 敵対的レビューで確認した2バグ
  （右クリックが選択を変えないため既存選択行が誤って開く／parent+leaf 同時選択で
  誤有効化）を構造的に回避する（sabotage 2種で実証）。コミット `03e7f79`。
  **#17**: 折りたたみレールが「プロットと開いているドックの間」に挟まる不整合
  （片方だけ折りたたんだとき）を、レールを常に画面端側（開いているドックの外側）
  へ解消。**機構は候補 A「レール最外ドック化」で確定**（敵対的レビューで候補 B・C
  を不適格と判定 — 候補 C は QMainWindow の私有レイアウトで外部ラップ不能、
  候補 B は絶対配置オーバーレイでレイアウト空間を予約できず全高の開ドックを押せ
  ない＋z-order 沈下 false-green の罠）。各辺の最外に常駐する薄い `QDockWidget`
  レール（`NoDockWidgetFeatures`＋タイトルバー無し）へ折りたたみタブを集約し、
  `dockLocationChanged` で最外順序を能動是正・`restoreState`/`_reset_layout` 後に
  順序＋corner＋1:4 比率を再適用・空時は `setVisible(False)` でゼロ幅（`CentralWithRails`
  は廃止・`central_stack` を直接 `setCentralWidget`）。realgui T-C1（非重なり
  `rail.left()>=openDock.right()`＋`widgetAt` 実描画）/T-C1b（D&D 順序破れの能動
  是正・save→restore 復元）/T-C2（両畳み・extent 復元）で実 OS 実証。コミット
  `486a94b`＋レビュー反映 `edb87db`（実バグ0・#15 realgui 更新漏れ1件を追加是正）。
  **§3 訂正（Task 4 実測で確定）**: 当初「片方折りたたみはプロット幅不変」と記述
  したが厳密には不正確（wrapper 幅測定に隠れていた）— 実際は片方折りたたみで
  プロットがレール幅ぶん（実測 ~24px）僅かに縮み、両方折りたたみでも viewport が
  ~4px 縮む（候補 A のレールは空でも `QDockWidget` として splitter/frame 分の実
  幅を要求するため。旧 `CentralWithRails` の中央オーバーレイは占有ゼロだった —
  新規の退行ではなく候補 A 採用に伴う pre-existing コストの顕在化）。真の
  central 幅完全維持（central と rail の joint リサイズ）は本増分のスコープ外の
  follow-up として起票済み（`task_bd63c2f2`）。
  **凍結カタログ（Task 4）**: merge-base（本ブランチ分岐直前の main tip・一時
  `git worktree` で撮影しノイズを排除）と比較し、per-state 差分が想定内に限定
  されることを実測で確認 — **#14 の列幅 pin 要因はツリー（`tree.sizeHint()=256px`）
  と確定**（ヘッダー/タイトルバーいずれも下回るため実 `channel_dock.width()` は
  現行コード/旧テンプレ文言/旧コード忠実再現〔文言＋wordWrap 無し〕の3条件で
  すべて 258px と同一。よって 02-05 は `--crop-meta` 完全一致＝T-B1 の担保どおり
  viewport 非実証、通常比較はヘッダーテキスト領域限定の差分のみ）。**#17 の
  09_collapsed は viewport 実測で変化**（`{w:912,h:772}→{w:908,h:768}`・
  `--crop-meta` 相違）— 上記コスト顕在化のため 09 を再ベースライン。**新規状態
  `10_collapse_one`**（`window._collapse_dock(window.channel_dock)` のみ）を
  `capture_ui_screenshots.py` へ追加し、レールが画面右端・開いている File ドック
  がその内側に描画されることを目視確認（realgui T-C1 の非重なり実測と整合する
  二次のピクセル凍結）。**凍結ベースライン更新済み**（`screenshots_catalog_dark/light`
  両テーマを本ブランチ撮影へ全面差し替え・02-05 はヘッダー文言差分のみ／09 は
  ~4px viewport 縮小のみ／01・06・07・08・10（新規）は完全一致 or 想定内・再撮影で
  決定性 exit 0 実証、通常比較/`--crop-meta` とも両テーマ）。realgui フル
  101 passed（+3 は単体では pass する既知の一括実行限定フレーク
  `test_hit_targets.py::test_chevron_already_meets_24px_height`・
  `test_hit_targets.py::test_tab_close_button_extended_hit_removes_tab`・
  `test_expansion_dialog_realinput.py::test_bottom_checkbox_reachable_by_real_wheel_then_ok`
  — D-3/E-0+E-2/F-0 で既に記録済みの「51ファイル一括実行でのみ発生する実行順
  依存フォント計量ドリフト」クラスタと同一・本増分と無関係）。**claude.ai/design
  への同期は対象外**（トークン変更なし）。設計は
  [memo-ux-cleanup spec](superpowers/specs/2026-07-23-memo-ux-cleanup-design.md)。
  **follow-up**: `task_bd63c2f2`（片方折りたたみの central-width ~24px drift の
  真の解決＝central と rail の joint リサイズ調査）。
