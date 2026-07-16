# デザイントークン・パイプライン 設計 spec

- **日付**: 2026-07-15
- **ステータス**: 設計承認済み（brainstorming セクション承認＋アドバーサリアルレビュー反映 2026-07-15）。**2026-07-16 改訂**: ユーザー要件によりテーマ方向性を「ダーク単一」→「ライト/ダーク/オート（OS 追従）三態を実装予定」へ変更（§3/§4.3/§8/§9）。増分3 冒頭の QStyle スパイク完了 — Fusion＋QPalette 採用（§4.3）
- **スコープ**: デザイントークン基盤（`gui/theme/`）＋ Claude Design 連携パイプライン（抽出・カタログ・同期・反映ループ）

## 1. 背景と課題

valisync GUI の現在のビジュアルデザインは、コード上に単一の真実を持たない。

- **集中管理されたテーマ機構が存在しない** — テーマモジュール・色定数・QSS ファイル・QPalette 設定はゼロ。スタイルは各ビューにインライン QSS とハードコード色で散在（純リテラル約 44 箇所・コメント内 hex 等を含めると約 58 箇所・10 ファイル。「何を 1 箇所と数えるか」の基準は増分1 実装プランの全数調査で確定する）。
- **2つの暗黙パレットが混在** — 信号カーブは matplotlib tab10（`viewmodels/graph_panel_vm.py:31-43` の `_PALETTE`）、カーソル readout は Catppuccin Mocha 系ダーク配色（`views/cursor_readout.py:76-80`）。「青」だけで `#1f77b4` / `#89b4fa` / `#4FC3F7` の 3 種が併存。
- **クロムとプロットの分裂** — アプリクロム（メニュー・ドック・ダイアログ）は OS 既定のライト、プロット面は pyqtgraph 既定のダークで、混在状態が固定。ダーク/ライト切替なし。**重要**: この既定外観はコード上に値が存在しない（`pg.setConfigOption` / `QPalette` / アプリレベル QSS は src 全体で 0 件）。つまり凍結トークン化が集約できるのはコード上のリテラルのみで、暗黙のフレームワーク既定はトークンに乗らない（→ §8 増分3 の前提）。
- **フォント指定ゼロ**（OS 既定依存・唯一の例外は `cursor_readout.py:420` の `font-size:9px`）、**カスタムアイコンアセットゼロ**（Qt 標準アイコン＋絵文字＋実行時描画）。
- スペーシングも各所リテラル（module 定数化は `_Y_AXIS_FIXED_WIDTH = 72` 等ごく一部）。
- なお動的色計算（lighten/blend 等）は src/ に存在せず全色が静的リテラル — 「値をそのまま凍結」戦略の前提は成立している（調査済み）。

このため「統一感のある洗練されたデザイン」を実装・維持する土台がなく、機能追加のたびにハードコードが増える構造になっている。

## 2. ゴールと成功基準

**ゴール（brainstorm 決定: 案A）**: 継続的なデザイン運用パイプラインを作る。現在の UI を Claude Design（claude.ai/design）上にカタログ化し、「デザイン検討 → 承認 → コード反映 → 再生成 → 照合」のループを回せる状態にする。デザイントークン（`gui/theme/tokens.py`）＋デザインコンセプト文書（`docs/design.md`）が単一の真実になる。

成功基準:

1. コード上に存在する色・余白・radii・タイポ指定の値がリポジトリ内の 1 箇所（`tokens.py`）に集約され、GUI コードはトークン名で参照する（タイポは現状 `font-size:9px` の 1 箇所のみなのでほぼ空カテゴリとして始まる）。
2. Claude Design プロジェクト上に Ground Truth（実機スクショ）/ Tokens / Components / Proposals のカード群が成立し、スクリプト再実行＋DesignSync で増分更新できる。
3. デザイン変更が原則「トークン値の diff」として表現され、再生成→同期→照合の手順が文書化されている（例外は §8 増分3 の初回クロム反復 — 構造作業を伴う）。
4. 新規コードへの色ハードコード混入を CI のガードテストが捕捉する。

## 3. 決定事項（brainstorming Q&A）

| 論点 | 決定 | 理由 |
|---|---|---|
| ゴール | **A: 継続運用の仕組み**（一回きりの刷新ではない） | 未着手 GUI サブスペック（derived / views / script）が控えており、テーマ機構を先に作ると以降の実装が全て乗る |
| Claude Design 上の表現 | **C: ハイブリッド**（スクショ = Ground Truth ＋ HTML = Tokens/Components） | スクショだけでは反復手段がなく、HTML だけでは現状との乖離を検証できない。スクショは「実装がデザインに追従できたか」の照合点 |
| テーマ方向性 | 当初 **C: ダーク単一で実装、両対応可能な構造**。**改訂（2026-07-16・ユーザー要件）: ライト/ダーク/オート（OS 追従）の三態を実装予定** — オートは OS カラースキームが**トークンセットの選択のみ**を行い、値の真実は tokens.py のまま（単一の真実は不変）。増分3=ダーククロムのトークン化（三態の土台）、増分4=LIGHT 値セット＋テーマ選択 UI（View メニュー radio＋QSettings 永続）＋オート（`QStyleHints.colorScheme`/`colorSchemeChanged`）。切替の反映方式（ライブ再適用 vs 再起動反映）は増分4 の設計で確定 | ADAS HILS 計測環境はダークが実用的だが、明環境・レビュー用途にライトの需要あり。増分1 で `active()`/`set_active()`（呼び出し時読み）を敷いた構造がそのまま三態の切替機構になる |
| 適用順序 | **A: 凍結→トークン化→再デザインの 2 段階** — まず現状色をそのままトークン値として凍結（見た目不変の純リファクタ）、刷新はその後の反復で適用。**2 回目以降の反復はトークン値変更のみで回る。ただし初回のクロム反復（増分3）はトークン追加＋`apply.py` 実装という構造作業を伴う**（§8） | 「見た目不変」はスクショ前後比較で機械的に検証でき、リファクタ不具合とデザイン変更の差分が混ざらない |
| 単一の真実の形式 | **案1: Python ネイティブトークン**（`tokens.py`）＋エクスポータで CSS/JSON へ導出 | 最大の消費者（Qt コード）と同じ言語で mypy/ruff の品質ゲートに乗り、タイポが型エラーで落ちる。JSON 真実（案2）は文字列キーのパース層が入り loud-fail 文化と相性が悪く、現時点で言語中立性の需要がない |

## 4. 全体アーキテクチャ

```
src/valisync/gui/theme/          ← 新パッケージ（単一の真実）※src/ 構造変更としてユーザー承認済み
  tokens.py     意味名トークン定義（Qt/pyqtgraph 非依存の pure Python 必須）
  qss.py        トークン→QSS 断片フォーマッタ（view ソースから色構文文字列を排除する）
  apply.py      起動時適用フック（Qt 依存はここに隔離）
design/cards/                    ← コンポーネントカードの HTML テンプレート（手書き・コミット対象）
design/proposals/                ← 検討中の改善案カード（手書き・コミット対象）
scripts/export_design_tokens.py  ← エクスポータ（tokens → design_export/）
scripts/capture_ui_screenshots.py ← 実機スクショ撮影（→ design_export/screenshots/）
design_export/                   ← ビルド成果物（gitignore）。DesignSync 同期バンドル
docs/design.md                   ← 人間向けデザインコンセプト文書（値は持たずトークン名で参照）
```

### 4.1 tokens.py — トークン定義

- **構造制約**: 全階層 frozen dataclass＋属性アクセス（dict 禁止）。これにより「タイポが mypy の型エラーで落ちる」という案1 選定理由が実際に成立する。値セットは `DARK = ThemeTokens(...)` の 1 インスタンスのみ。
- **純粋性制約**: `tokens.py` は Qt/pyqtgraph を import しない（pure Python）。`viewmodels/graph_panel_vm.py` 等は docstring で「No PySide6/Qt/pyqtgraph imports」を宣言する pure-Python VM であり、theme からの import でこれを壊さないため。`theme/__init__.py` は tokens のみ re-export し、`apply` / `qss` は明示 import とする。増分1 で純粋性ガードテスト（tokens import 後の `sys.modules` 検査）を Layer A に常設する。
- **色値の型**: 生文字列ではなく正規化表現（frozen `Color` dataclass、RGBA 各 0–255 int）で持ち、消費側フォーマッタを設ける — Qt QSS（`rgba(r,g,b,a)` の a は 0–255）/ `QColor` / pyqtgraph / CSS（`rgba()` の a は 0–1、hex の alpha 位置も Qt `#AARRGGBB` と CSS `#RRGGBBAA` で逆）はフォーマットが非互換であり、素通しするとエクスポート先の tokens.css が壊れるため。
- **命名は意味名**（役割ベース）: `surface_chip` / `text_primary` / `cursor_a` / `cursor_b` / `accent_active` / `error` / `drop_highlight` / `signal_palette`（tab10 の 10 色 tuple）等。値名（`catppuccin_blue` 等）にしない。
- 具体的なフィールド一覧は増分1 の実装プランで全数調査に基づいて確定する。同値の色でも**役割が違えば別トークン**にする（後の再デザインで独立に動かせるように。例: `#1f77b4` はパレット 1 番とドロップ強調枠で役割が異なる）。
- spacing / radii / typography は現在使われている値（chip padding `(6,5,6,5)`、`border-radius:5px`、`font-size:9px` 等）を凍結して収録。`_Y_AXIS_FIXED_WIDTH = 72` のような**レイアウト機構の定数はトークン化しない**。
- **デザイン色 vs 構造色の線引き**: 視覚デザインの一部として選ばれた色はトークン化する。描画機構上の必然で決まる色（カーソル bitmap のマスク用白黒 `cursor_shapes.py:98-99`、`Qt.GlobalColor.transparent` 等）は構造色としてトークン化せず、ガードスキャンの allowlist に理由付きで登録する。

### 4.2 qss.py — QSS フォーマッタ

インライン QSS 文字列を view 側で f-string 組み立てすると、view ソースに `rgba(...)` 等の色構文テキストが残り**ガードスキャン（§7）と正面衝突する**。これを避けるため、QSS 断片の生成関数を theme 側（`qss.py`）に置き、view は `qss.chip_style(tokens)` のような関数呼び出しだけを持つ。view ソースから色構文文字列そのものが消えるので、ガードスキャンは単純なままで済む。

### 4.3 apply.py — 適用フック

- **呼び出し位置**: `build_main_window()`（またはそれが使う共有経路）から**冪等に**呼ぶ。多重呼び出し安全。`main()` だけに置くと、`build_main_window` を直接使う pytest-qt / realgui テストが apply を通らず、apply が実処理を持つ増分3 以降でテスト描画と実アプリ描画が乖離する（false-green/false-red 化）ため。撮影スクリプトも同じ経路（`build_main_window` 経由）で起動し、描画経路を実アプリと一致させる。
- **増分1 では原則 no-op**（注入点の配線のみ）。例外として pyqtgraph の既定と同値の明示固定（`background='k'` / `foreground='d'` 等）のみ行ってよい。**QPalette・アプリレベル QSS の「現行既定の明示固定」は増分1 ではやらない** — 非空 QSS は native スタイルの描画パスを変える既知の Qt 罠があり、凍結保証（見た目不変）自体を毀損しうるため。
- **クロム統一の QStyle 選択 — スパイクで確定（2026-07-16）**: 3方式（A=既定 `windows11` style・B=Fusion＋QPalette・C=全面 QSS）を実機同一状態で比較し **B を採用**。根拠: (1) QPalette の約12 role をクロムトークンに写像するだけで全コントロールが一貫し、combo/spin/checkbox 等がネイティブ品質、(2) ライト/ダークが**パレット値の差し替えだけ**で表現でき三態要件と整合、(3) 既存の widget 単位 QSS（チップ・エラーラベル・overlay 枠）と共存することを実証。C（全面 QSS）は全ウィジェット種×全状態の網羅保守が重く不採用 — 個別コンポーネントの上書きが必要になったら `qss.py` 関数で随時。A は OS 追従でクロム色がトークン制御外（実機は Qt6 `windows11` style が OS ダークに追従して既にダークだった — §1 の「ライトクロム」はコード監査由来で OS 設定依存が実態）のため不採用。ただし「オート」は OS スキーム検出→トークンセット選択の形で実現する（描画は常に Fusion＋トークン由来 QPalette）。

### 4.4 既存コードの変化

- 散在するハードコード色・QSS リテラルを `theme.tokens`（QSS は `theme.qss` 経由）参照へ置換（値は現状のまま凍結＝見た目不変）。
- `graph_panel_vm.py` の `_PALETTE`（信号色）は `tokens.py` の `signal_palette` へ移動し、VM は theme から import する（`views/graph_panel_view.py:68` による private 定数 `_PALETTE` の越境参照も解消される）。
- **色値を assert する既存テストの移行**（約 24 箇所・凍結時点で実施）: palette 値・カーソル色等に直結するもの（`tests/gui/test_graph_panel_vm.py:151,183`・`tests/gui/test_cursor_readout_diff.py:55` 等）は**期待値をトークンから導出**する形に書き換える（ただし「コード==コード」の同義反復にならないもののみ）。特に `tests/realgui/test_fu12_boundary_data_visible.py:146-151` のピクセル述語は palette[0]==青・背景==黒を前提としており、トークン導出に書き換えないと増分3 の最初の値変更で即崩壊する。`#123456` 等のカスタム色プラミングテストはトークン非依存で無変更のまま正しい。

## 5. データフローと運用ループ

**一方向のデータフロー**(真実は常にリポジトリ側。Claude Design 側で直接編集しない):

```
tokens.py（単一の真実）
  ├─ import ──────────→ Qt ビュー/VM（実アプリの描画）
  ├─ apply.py ────────→ QPalette / pyqtgraph 全体設定
  └─ エクスポータ ────→ design_export/tokens.css + tokens.json + 見本カード
                            ↑ design/cards/・design/proposals/ テンプレート（var(--vs-*) 参照）
実アプリ ─ 撮影スクリプト ─→ design_export/screenshots/（Ground Truth カード）
design_export/ ─ DesignSync ─→ claude.ai/design プロジェクト「valisync-design」
```

### Claude Design プロジェクトのカードグループ構成

| グループ | 中身 | 由来 |
|---|---|---|
| Ground Truth | 実機スクショ（メインウィンドウ・波形パネル・readout・各ダイアログ） | 撮影スクリプト。PNG は `<img>` 埋め込みのラッパ HTML カードとして生成（DesignSync のカード索引は HTML 先頭の `@dsCard` マーカーで構築されるため PNG 単体はカードにならない） |
| Tokens | 色見本・spacing スケール・タイポ見本 | エクスポータ自動生成 |
| Components | readout チップ・軸ガター・アクティブ枠・ドロップ強調・ダイアログ等の HTML 再現 | `design/cards/` テンプレート |
| Proposals | 検討中の改善案カード（採用されたらトークン値に反映して削除） | `design/proposals/` テンプレート（**ローカル作成→push**。リモート限定にすると未採用案がセッション間で消え、一方向規約とも矛盾するため、Proposals もコミット対象とする） |
| Meta | 同期マニフェストカード（push 時の git SHA・tokens ハッシュ・カード一覧） | エクスポータ自動生成 |

各カード HTML の先頭に `<!-- @dsCard group="…" -->` マーカーを付与し、Claude Design 側のグループ分けを自動化する。

### 同期状態の管理

`design_export/` は gitignore のため「前回何を push したか」がリポジトリに残らない。リネーム・廃止カードの削除（`delete_files`）を決めるため、**同期は毎回 `list_files` でリモートの実状態と突合**し、ローカルバンドルに無いパスを削除候補として提示する。Meta グループの同期マニフェストカードが「リモートがどの git SHA 由来か」の照合点になる。

### 運用ループ（1 反復 = 1 feature ブランチ）

1. **検討**: claude.ai/design 上でカードを見ながら議論。改善案は `design/proposals/` に案A/案B カードとして作成して push し、Proposals グループで比較。
2. **承認**: 採用案を決定。
3. **反映**: `tokens.py` の値変更（意味名は不変なのでコード側 diff は原則トークン値のみ。初回クロム反復のみ §4.3 の構造作業を伴う）＋ `docs/design.md` に決定理由を追記。
4. **再生成**: エクスポータ＋撮影スクリプトを再実行 → DesignSync で増分同期（`finalize_plan` → `write_files`。常にコンポーネント単位、丸ごと置換はしない）。
5. **照合**: Ground Truth（新スクショ）と Components（意図したデザイン）を見比べ、**「意図した変化のみが起きたか」**を確認（増分1 の凍結検証＝厳密一致とは別物 — §7）。採用済み Proposals はカード削除＋ `design/proposals/` からも削除。

この手順は `docs/design.md` に文書化し、以降のセッションで再現可能にする。

## 6. エラー処理・堅牢性

- **エクスポータの決定的出力**: 同じ `tokens.py` → バイト同一の出力。成立条件を実装で固定する — `open(..., newline="\n")`（Windows 既定の `\r\n` 混入防止）・JSON は `sort_keys=True, indent 固定, ensure_ascii 固定`・出力順は dataclass フィールド定義順。トークン名→CSS 変数名の変換で衝突が生じたら loud-fail。
- **撮影スクリプト**:
  - 実ディスプレイ必須（offscreen の `QWidget.grab()` は全文字が□になる既知の罠 — `QT_QPA_PLATFORM=windows` を強制）。
  - **QSettings 隔離必須**: `MainWindow._restore_state` がユーザーの実ドック配置/ジオメトリを復元してしまうため、`tests/realgui/conftest.py` と同じ隔離機構を組み込む。
  - デモデータ不在なら「`scripts/generate_demo_mf4.py --profile quick` を先に実行」と明示してエラー終了。状態ごとにタイムアウトを設けハングを防ぐ。
  - モーダルダイアログは `exec()` がブロックするため show()＋非モーダル駆動等の段取りが要る（詳細は実装プラン）。
- **同期**: DesignSync の `finalize_plan` が書込パスを事前確定するため誤爆的な全置換は構造的に不可能。push 前に `get_project` でプロジェクトが design-system 型であることを検証する。`get_file` は 256 KiB cap があるため、大きな PNG は読み戻しでなくローカル成果物で照合する。
- **ガードテストの例外管理**: allowlist は**行パターン単位の ratchet**（ファイルパス＋一致パターン＋理由を必須）。ファイル単位だと同一ファイル内の新規違反を隠し、カウント式は行移動で偽陽性化するため。

## 7. テスト戦略

詳細は各増分の実装プラン作成時に `/gui-test-plan` スキルで確定する。骨子:

| レイヤー | 内容 |
|---|---|
| Layer A（ロジック） | トークン構造の妥当性（全フィールド型付き・Color 値域検証）、純粋性ガード（tokens import 後の `sys.modules` に Qt 不在）、エクスポータ round-trip（`tokens.py` ↔ `tokens.json` 一致）、golden 出力テスト、Color→各フォーマット変換の正しさ（Qt QSS / CSS の alpha・hex 順序） |
| Layer B（Qt 直叩き） | `apply.py` が期待どおり pyqtgraph 設定を注入すること・冪等であること、置換後のビューがトークン色で描画されること（スポットチェック） |
| **凍結検証**（増分1 の要） | 下記「凍結検証の成立条件」参照 |
| Layer C（realgui） | 各増分の merge 前に `/gui-verify` の①ゲート（実 OS 入力＋スクショ AI 判定） |
| ガードスキャン（常設） | **AST ベース**（文字列リテラルのみ走査 — コメント/docstring 内 hex の偽陽性を回避）＋ `QColor(数値リテラル引数)` 呼び出し検出。対象パターン: hex・`rgba(`・`rgb(`・`hsl(`・`QColor("名前色")`・`Qt.GlobalColor.*`（transparent 等の構造色は allowlist）。対象: `src/valisync/gui/`（`theme/` 除く）。例外は §6 の ratchet allowlist |

### 凍結検証の成立条件（増分1）

ピクセル厳密一致を成立させるため、以下を増分1 の設計条件として固定する:

1. **撮影単位は `QWidget.grab()`**（コンポジタ非経由・OS カーソル非含有・タイトルバー〔ファイルパス等の環境文字列を含む〕を構造的に除外）。全画面 `grabWindow(0)` はタスクバー時計や背後ウィンドウが写るため凍結比較には使わない（Ground Truth カード用の見栄え撮影とは用途を分ける）。
2. **静止状態の定義**: スピナー（QTimer 回転アーク）・不確定プログレスバー・テキストカレット点滅・hover 効果を排した状態のみ撮影対象にする。物理マウスはウィンドウ外へ退避。
3. **環境固定の運用規定**: ベースライン→再撮影の間、同一マシン・同一 DPI・OS テーマ/ClearType 不変・**uv.lock 変更禁止**（Qt/pyqtgraph 更新は描画を変えうる）。デモデータは**同一ファイルを再利用**（再生成しない）。
4. **比較機構は増分1 の新規成果物**: リポジトリに画像比較の仕組みは現存しないため、diff ピクセル数＋diff 画像を出力する比較スクリプトを作る。
5. **手順**: 撮影スクリプト（最小版）をブランチ先頭で実装 → リファクタ**前**に撮影しベースラインを scratchpad 等の作業領域に保存 → 置換 → 再撮影 → 比較。証拠（一致レポート）は PR に添付。
6. **役割写像の検証**（ピクセル比較の盲点対策）: 同値別トークンの誤配線はピクセル比較では原理的に検出できない（値が同じなので画は一致する）。補完として (a) 「58 箇所→トークン」のマッピング表を実装プランのレビュー成果物とする、(b) **全トークンを相異なる値にしたデバッグテーマ**を一時適用して撮影し、各トークンの着地点を目視検証する追加パスを行う（トークン化したからこそ可能になる検証で、パイプラインの自己実証を兼ねる）。
7. **二層の照合の区別**: 増分1 の凍結検証＝厳密一致。§5 運用ループ手順5 の照合＝「意図した変化のみか」の許容付き判定。長期では OS/Qt 更新で Ground Truth が漂移するため、両者を混同しない。

## 8. 増分分割（1 増分 = 1 feature ブランチ = 1 実装プラン）

1. **増分1: 凍結トークン化** — theme パッケージ新設（`tokens.py`/`qss.py`/`apply.py`＝原則 no-op 注入点を `build_main_window` に配線）、ハードコード色を現状値のままトークン参照へ置換、色 assert 既存テストのトークン導出化（§4.4）、ガードテスト常設、凍結検証（§7 の成立条件＋比較スクリプト＋デバッグテーマ検証）。**撮影スクリプトは凍結検証に必要な最小版（主要状態のみ）をここで先行実装する**。ここまでで「単一の真実」が成立。
2. **増分2: パイプライン構築** — エクスポータ・`design/cards/` テンプレート・撮影スクリプトのカタログ用拡張（全サーフェス＋ダイアログ網羅）・同期マニフェスト・`docs/design.md`・初回同期で Claude Design 上にカタログ成立。ここまでで運用ループが回せる状態。
3. **増分3: クロムのトークン化（ダーク・三態の土台）** — クロム系トークン（QPalette の約12 role に対応する `chrome_*` 群）を新規追加し、`apply.py` で **Fusion＋トークン由来 QPalette** を適用（スパイクで確定・§4.3）。初期値はスパイクの Catppuccin 系ダーク（確定配色は以降の Claude Design 反復でトークン値変更のみ）。ベースライン更新・カタログ再撮影・再同期を含む。**注意**: Fusion 切替は全コントロールの描画メトリクス（行高・タブ高等）を変えうるため realgui **全数**無回帰を merge 前ゲートに含める。
4. **増分4: テーマ三態（ライト/ダーク/オート）** — 詳細設計は §11（2026-07-16 brainstorming 確定）。要点: LIGHT 値セット（Catppuccin Latte 初期値で出荷→Claude Design で洗練）＋View メニューのテーマ radio（ライト/ダーク/オート・QSettings 永続・既定=オート）＋**全面「再起動反映」で一貫**（オートの OS 追従も次回起動・`colorSchemeChanged` は購読しない）。`resolve_theme(mode, os_prefers_dark)` 純関数（tokens.py）＋`apply_startup_theme`（apply.py・起動時に mode/OS を解決して `set_active`→`apply_theme`）。プロット面のライト化は非スコープ（黒据え置き・曲線色の再設計を避ける）。
5. **増分5: アイコン刷新（予定・2026-07-16 追加）** — Qt 標準アイコン（`QStyle.StandardPixmap` — Open/Save/フォルダ等）をカスタム SVG アセットへ置換し、トークン連動の着色（ライト/ダークで自動追従）にする。ツールバー/メニュー/ドックのアイコンが Claude Design の検討範囲に入る。詳細設計（アセット管理・描画方式・テーマ連動の選択肢比較）は着手時の設計スパイクで確定。§9 の「カスタムアイコン非導入」はこの増分で解除。
6. **増分6 以降: 運用（再デザイン反復）** — トークン値変更のみで回る「軽い反復」。デザイン反復ごとに小さなブランチ。

## 9. 非スコープ（YAGNI）

- ~~ライトテーマの値セット・テーマ切替 UI~~（**2026-07-16 改訂で増分4 のスコープへ昇格** — §3/§8）
- JSON/YAML を単一の真実にする案（案2 — 外部デザインツール連携が本格化したら再検討）
- ~~カスタムアイコンアセットの導入~~（**2026-07-16 改訂で増分5 のスコープへ昇格** — §8/§12）
- Claude Design 側での直接編集・双方向同期
- `_Y_AXIS_FIXED_WIDTH` 等レイアウト機構定数のトークン化
- 増分1 での QPalette / アプリ QSS の「現行既定の明示固定」（§4.3 — 凍結保証を毀損しうるため増分3 で扱う）

## 10. リスクと対策

| リスク | 対策 |
|---|---|
| 凍結置換の見落とし・誤置換 | スクショ前後ピクセル比較（§7 成立条件）＋ガードスキャンが残存ハードコードを列挙 |
| 同値別トークンの誤配線（ピクセル比較で不可視） | マッピング表レビュー＋デバッグテーマ撮影パス（§7-6） |
| HTML 再現と Qt 実描画の乖離 | Components はあくまで検討用の近似と位置づけ、最終照合は Ground Truth スクショで行う（§5 手順5） |
| 撮影スクリプトの不安定さ（実ディスプレイ・タイミング） | realgui 基盤の既知の知見（実ディスプレイ強制・QSettings 隔離・タイムアウト・画面内配置）を再利用。撮影は CI に入れずローカル運用 |
| design_export/ と Claude Design の乖離 | 真実は常にリポジトリ側という一方向規約＋毎回 `list_files` 突合＋同期マニフェスト（§5） |
| 増分3 の QStyle 切替が想定外に大工事化 | ~~増分3 冒頭に設計スパイク~~ **スパイク完了（2026-07-16）— Fusion＋QPalette 採用で解消**（§4.3）。残リスクは Fusion 化による描画メトリクス変化 → realgui 全数を merge 前ゲートに |
| ライブテーマ切替（増分4）の再適用パスが大工事化 | **解消（2026-07-16 brainstorming）— 全面「再起動反映」を採用**（§11）。ライブ再適用の 33 箇所配線を回避し、`apply_startup_theme` を起動時1回で完結 |

## 11. 増分4 詳細設計（テーマ三態・2026-07-16 brainstorming 確定）

### 11.1 決定事項（Q&A）

| 論点 | 決定 | 理由 |
|---|---|---|
| 切替の反映方式 | **全面「再起動反映」** — メニュー選択は QSettings 保存のみ、次回起動から適用 | ADAS 計測でテーマは長時間固定の設定。ライブは構築時焼き込み（QSS/pen）の 33 箇所再適用配線＋realgui 検証コストに見合わない |
| オートの OS 追従タイミング | **起動時に一度だけ検出**（`colorSchemeChanged` 非購読）— 起動中の OS 変化は次回起動で追従 | 再起動反映と一貫。OS 切替は稀で「次回起動追従」で実用上十分 |
| LIGHT 初期配色 | **Catppuccin Latte**（Mocha の公式ライト対応版）を出荷値に→Claude Design で洗練 | 実装→Ground Truth→検討のパイプライン思想。Mocha と役割対応が取れた既製パレット |
| 新規インストール既定 | **オート（OS 追従）** | 三態で最も無難な既定。当環境は OS ダークで現状と連続 |

### 11.2 コンポーネント

- **`tokens.py`**（pure Python 維持）: `LIGHT: ThemeTokens`（Latte 値・DARK と同一フィールド構成 — frozen dataclass の必須キーワード引数によりフィールド漏れは import 時 `TypeError` で loud-fail）／`ThemeMode(Enum)`（`LIGHT`/`DARK`/`AUTO`・値は QSettings 保存形の文字列）／`resolve_theme(mode: ThemeMode, os_prefers_dark: bool) -> ThemeTokens`（純関数: AUTO→os で DARK/LIGHT・LIGHT/DARK は os 無視）。
- **`apply.py`**（Qt 隔離層）:
  - `os_prefers_dark() -> bool`（`QApplication.styleHints().colorScheme()`）。**判定不能は一律 dark**（`Unknown`／QApplication 不在／非対応 Qt はすべて `True`＝現行 DARK 単一運用との連続性を優先し非対称を排除。C1 レビュー反映）。CI（Linux+xvfb）で `Unknown` が返っても dark に落ちるため Layer A/B は安定。
  - `load_theme_mode()/save_theme_mode()`（QSettings・未知値は AUTO フォールバック）。**org/app 定数は `theme/settings.py`（新設・薄い共有モジュール）に集約し、`main_window.py`/`recent_files.py` も将来これを参照**（今は既存 `_ORG`/`_APP` 値と同一文字列を settings.py に定義し apply.py が使用）。キー名 `"theme_mode"`（geometry/windowState と衝突しない）。`main_window → apply` の呼び出し方向のみ（apply は main_window を import しない＝循環回避）。
  - `apply_startup_theme(forced: ThemeMode | None = None)`（`forced` 指定時は QSettings/OS を読まず `resolve_theme(forced, os_prefers_dark())` 相当で確定→`set_active`→`apply_theme`。**通常起動は `forced=None` で QSettings/OS 解決**）。この `forced` 経路が撮影スクリプトのテーマ強制注入口（C1 反映）。
- **`app.py`**: `build_main_window(app_vm=None, *, theme=None)` にテーマ override 引数を追加し、内部で `apply_startup_theme(forced=theme)` を呼ぶ（`apply_theme()` 直呼びを差し替え）。`--debug-theme`/`--theme` の両撮影経路はこの override を通す（`set_active` 事前注入をやめ、上書き衝突を構造的に解消）。
- **`main_window.py`**: View>テーマ サブメニューに radio 3つ（`QActionGroup` 排他）。**既存の確立パターンを踏襲**（`setChecked` を `triggered` 配線の**前**に行う・`toggled` でなく `triggered` に配線＝起動時 checked 同期が `save_theme_mode` を誘発しない。過去のタブ改名/Enter 二重発火の教訓）。選択で `save_theme_mode`＋「再起動で反映されます」ステータス。**active/apply_theme は呼ばない**（再起動反映）。

### 11.3 データフロー

```
通常起動: main() → build_main_window(theme=None) → apply_startup_theme(forced=None)
             ├ load_theme_mode() [QSettings・未保存→AUTO]
             ├ os_prefers_dark() [AUTO のときのみ意味]
             ├ resolve_theme(mode, os) → DARK|LIGHT
             ├ set_active(resolved)
             └ apply_theme() [Fusion+build_palette(active)]
          → 各ウィジェット __init__ が active を焼き込み
撮影強制: build_main_window(theme=DARK|LIGHT) → apply_startup_theme(forced=...)
             [QSettings/OS を読まず forced を set_active — --debug-theme/--theme 共通経路]
メニュー選択: save_theme_mode(mode) のみ ＋ ステータス表示（現画面は不変）
```

### 11.4 LIGHT 値の方針

- クロム: Latte 対応色（`chrome_window`=Base `#eff1f5`・`chrome_text`=Text `#4c4f69`・`chrome_button`=Surface0 `#ccd0da`・`chrome_highlight`=Blue `#1e66f5`・`chrome_disabled_text`=Overlay0 `#9ca0b0` 等・全数は実装プランで Latte 対応表として確定）。
- readout チップ: 半透明ライト面＋Latte Text 文字。
- **プロット面据え置きトークン（テーマ非依存・両テーマ共通値）**（C3 レビュー反映）: `plot_background`（黒）・`plot_foreground`・`signal_palette`（tab10）に加え、**プロットキャンバス上またはその直上に `QPainter`/`pg.mkPen` で直接描画されるトークンも据え置く** — `cursor_a`/`cursor_b`（カーソル線＝黒背景で視認必須）・`accent_active`/`accent_active_dark`/`grip_fill`（アクティブ軸/枠）・`drop_highlight`（ドロップ強調枠）・`axis_move_indicator`/`axis_move_fill`（軸移動）・`preview_curve`（プレビュー線）。これらは §4.1 の「役割が違えば別トークン」原則により、クロムの Latte 化から独立して黒背景前提の値を保つ。
  - **兼用トークンの分割判断**: `cursor_a`/`cursor_b` は現状「プロット線」と「readout マーカー」兼用（`tokens.py` コメント）。プロット線は据え置き必須だが readout マーカーは Latte 面上に載る。**増分4 では分割せず据え置き優先**（黄/青のマーカーは半透明ライト面でも視認可・分割は増分肥大）。将来 readout の Latte 最適化が必要なら別トークンへ分割（Claude Design 反復）。
- **`plot_background` の白化は非スコープ**（曲線色の再設計を要し増分肥大 → Claude Design 反復で判断）。

### 11.5 二テーマのカタログ/エクスポート

- **出力レイアウト**（I3/I4 反映）: `export_design_tokens.py --theme {dark,light}`（既定 dark）はテーマ別サブツリー `design_export/{theme}/...`（例 `design_export/light/tokens.css`・`.../cards/...`・`.../ground_truth/...`）へ出力。**purge は自テーマのサブツリーのみ対象**（他テーマ・screenshots を消さない）。`capture_ui_screenshots.py --theme {dark,light}` は `build_main_window(theme=...)` 経由で強制起動して撮影。
- **Claude Design 上の区別**: カードのグループ名にテーマを含める（例 `Tokens / Light`・`Ground Truth / Light`）。`_card()` のラッパー配色は当該テーマ由来にする（LIGHT カードはライトなページ chrome）。Meta マニフェストは両テーマ分のパスを記録。
- `--debug-theme` は base theme 引数を取り LIGHT でも役割写像検証可能にする（I5 反映）。
- **docs/design.md 更新**（M2 反映）: 「ダーク単一」→「三態」・運用ループのコマンド例に `--theme` を反映するのを増分4 のタスクに含める。

### 11.6 テスト

- **QSettings 隔離**（C2 反映）: `tests/gui/conftest.py`・`tests/realgui/conftest.py` の隔離フィクスチャに `theme.settings`（新設共有モジュール）の org/app monkeypatch を追加する（既存 `mw`/`rf` に加える3つ目の書込元 — 追加しないと realgui のテーマ radio クリックが実レジストリを汚す）。
- Layer A: `resolve_theme` 全分岐（AUTO×dark→DARK／AUTO×light→LIGHT／LIGHT→LIGHT・os 無視／DARK→DARK・os 無視）／**LIGHT 全域スナップショット test-lock**（DARK と同形式・Latte 値ロック）／`load_theme_mode` 未知値→AUTO フォールバック／`build_main_window(theme=...)` の forced 経路が QSettings を無視すること。
- Layer B: `apply_startup_theme`（light 設定で build_main_window→LIGHT active＋Latte パレット＝再起動反映のインプロセス実証／`forced=LIGHT` が QSettings=dark を上書きすること）／`os_prefers_dark` の colorScheme→bool 写像・判定不能→dark／メニュー（`QActionGroup` 排他・現 mode checked・**選択後 active() 不変**・**メニュー構築〔checked 同期〕が `save_theme_mode` を呼ばない＝呼出回数0**）。
- 描画 E2E: `capture --theme light` でライト起動スクショ（LIGHT Ground Truth・クロム/チップ/文字が Latte 一貫・**プロット面据え置きトークンが黒背景で視認可**）。`--debug-theme --theme light` で LIGHT の役割写像目視。
- realgui: テーマ radio 実クリック→ステータス「再起動で反映」＋QSettings 保存＋**画面即変化なし**。ライト実適用の視覚確認は light 設定での実アプリ起動スクショ。

### 11.7 非スコープ（増分4）

プロット面のライト化・プロット据え置きトークンの分割（cursor_a/b 兼用のまま）・ライブ切替・`colorSchemeChanged` 購読・LIGHT 確定配色（Latte 初期値で出荷）。

## 12. 増分5 詳細設計（アイコン刷新・2026-07-16 brainstorming＋スパイク確定）

### 12.1 決定事項（Q&A＋実機スパイク）

| 論点 | 決定 | 理由 |
|---|---|---|
| アセットの出所 | **既製 OSS をアイコン単位で vendored・主 Lucide（ISC）＋補 Tabler（MIT）** — 実機スパイク（両セット×4アイコンをトークン着色で実ツールバー/48px シート・dark/light 撮影）でユーザー選定 | 両セットとも 24×24/stroke 2px/丸キャップの線画で混在可。主従ルールで統一感を担保。アイコン単位 vendoring なので技術コストゼロ |
| 絵文字グリフ（診断 ⛔⚠ℹ・✕ 等） | **増分5 対象外** — 基盤確立後のデザイン反復で個別判断 | 文字列埋め込みの置換はリスト装飾ロール化等でスコープ倍増。現状でも機能しており YAGNI |
| 機構 | **レジストリ＋実行時 SVG 着色**（案1）。qrc コンパイル（案2）は4ファイルに過剰・QIconEngine（案3）はライブ切替が無い現状では複雑さのみ（将来のライブ切替時の選択肢として記録） | 既存アーキテクチャ（pure レジストリ＋呼び出し時読み＋Qt 層描画）と同型 |

### 12.2 コンポーネント

- **`src/valisync/gui/theme/icons/`**（新設・パッケージ内アセット）: vendored SVG（初期4個・下表）＋`LICENSES.md`（Lucide=ISC・Tabler=MIT の全文＋アイコンごとの出所一覧）。**SVG 規約: 色は `currentColor` のみ**（固定 fill/stroke 色を持ち込まない — テーマ追従の前提）。Layer A テストで全ファイル検証 — 既存 AST ガード（`test_theme_guard.py`）は `*.py` のみ走査で `theme/` を除外するため **`.svg` の色規約はこの新規テストが唯一の防波堤**（レビュー M1）。
- **アセット解決と配布**（レビュー C1 — wheel ビルド実証で SVG 欠落を確認）: 実行時解決は `Path(__file__).resolve().parent / "icons"`。**`pyproject.toml` に `[tool.setuptools.package-data] "valisync.gui.theme" = ["icons/**/*.svg", "icons/LICENSES.md"]` を追加**（setuptools 既定は `.py` 以外を静かに落とす。dev/CI は editable install のため無症状だが、wheel 配布時にアイコン参照全てが FileNotFoundError になる false-green の構造的盲点 — 追加理由をコメントで残す）。
- **`theme/icons.py`**（新設・Qt 依存層）: 意味名レジストリ `ICONS: dict[str, str]`（意味名→アセット相対パス）＋ `icon(name: str, size: int = 20) -> QIcon`。呼び出し時に `tokens.active()` を読み、`currentColor` を **Normal=`chrome_text`・Disabled=`chrome_disabled_text`** に置換して QSvgRenderer で描画し QIcon の両モードに登録。**HiDPI 対応（レビュー I3）**: `devicePixelRatioF()` を乗じた物理ピクセルで QPixmap を確保し `setDevicePixelRatio(dpr)` して登録（置換前の `QStyle.standardIcon` はネイティブ HiDPI 対応のため、怠ると高 DPI で置換前より滲む退行になる）。未知の name は KeyError（loud-fail）。
- **消費側**: `shell_actions.py` の3箇所（open/open_folder/export）＋ `main_window.py` の Data Explorer 1箇所を `icons.icon(...)` へ置換（`QStyle.standardIcon` は src から消滅）。
- **エクスポータ**: **Icons カード**（group=`Icons / {テーマ}`）を追加。**Components 方式＝Qt 非依存（レビュー I2）**: `export.py` は SVG 生テキストを `<svg>` としてそのまま埋め込み、Normal/Disabled 各ラッパーに `style="color: var(--vs-color-chrome-text)"` / `var(--vs-color-chrome-disabled-text)` を与えて `currentColor` の解決をブラウザの CSS 継承へ委譲する（pure 制約維持・QSvgRenderer 不要・出所名付き）。

### 12.3 初期レジストリ（主 Lucide 原則）

| 意味名 | アセット | 出所 |
|---|---|---|
| `open` | `lucide/folder-open.svg` | Lucide |
| `open_folder` | `lucide/folder.svg` | Lucide |
| `export` | `lucide/save.svg` | Lucide |
| `data_explorer` | `lucide/folder-tree.svg` | Lucide |

（Tabler は「Lucide に無い/意味が合わない」場合の補完として `tabler/` サブディレクトリに追加。混在時もレジストリと LICENSES.md が出所を明示する。）

### 12.4 テーマ連動と検証

- アイコンは構築時生成 → **再起動反映（§11）と自然に一貫**。撮影 `--theme {dark,light}` で両テーマのアイコンがそのまま Ground Truth に写る。
- テスト: Layer A（レジストリ全登録の SVG 実在・`currentColor` のみ規約・着色置換の文字列検証・未知 name の KeyError）／Layer B（4アクションのアイコン非空・pixmap のピクセルが chrome_text 系・Disabled pixmap が chrome_disabled_text 系）／描画 E2E（dark/light 撮影で**ツールバーのみ意図変化**・他領域は前ベースラインと一致）／realgui（journey 系無回帰 — 入力経路不変のため scoped で可）。
- ベースライン更新（意図した変化）＋両テーマカタログ再撮影＋再同期を増分内に含む。

### 12.5 非スコープ（増分5）

絵文字/文字グリフの置換・qrc 化・QIconEngine（ライブ切替対応）・ドックタイトルバーの float/close ボタン（QDockWidget 内部・QStyle 由来）・4個以外のアイコン追加。（§8 の「ドックのアイコン」はレジストリに含まれる data_explorer **起動アイコン**を指し、QDockWidget 自体の float/close chrome とは別物 — 後者は本項で明示的に非スコープ。レビュー I1 の曖昧さ解消。）

## 13. 関連

- 現状調査: 本 spec §1（2026-07-15 実施の GUI スタイリング実態調査に基づく）
- アドバーサリアルレビュー: 2026-07-15 実施（Critical 1・Important 8・Minor 6 を本 spec に反映済み）
- 実装プラン: [r1-freeze](../plans/2026-07-15-design-tokens-r1-freeze.md)（増分1）・[r2-pipeline](../plans/2026-07-15-design-tokens-r2-pipeline.md)（増分2）・[r3-chrome](../plans/2026-07-16-design-tokens-r3-chrome.md)（増分3）
- 運用文書: `docs/design.md`（増分2 で作成）
