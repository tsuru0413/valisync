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
  方式を差し替え）。上端配置は3ドックの `setAllowedAreas(Left|Right|Bottom)` で禁止。
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
