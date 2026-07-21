# 増分0「知覚の床」— トークン・寸法の一斉是正 設計

- 日付: 2026-07-21（ユーザー承認済み: パレット案B・許容判断 2 点〔#E69F00×accent ΔE7.2=文脈分離・#56B4E9×preview_curve ΔE6.6=別窓限定〕。
  敵対的設計レビュー 24 指摘反映済み — important 18 を全て取込）
- 出典: [UIUX 敵対的レビューカタログ](../../uiux-adversarial-review-catalog.md) デザイン推奨1「知覚の床」バンドル。
  解く課題: UX-12・UX-18・UX-21（応急部分）・UX-27・UX-29・UX-35・UX-38・UX-39・UX-42・UX-49＋UX-07 応急部分。
- 位置づけ: 実施順の先頭（1〜2 PR）。**パレットは「暫定」でなく最終確定** — 増分E の
  「ファイル=色相ファミリー」は本パレットの色相基準で設計する制約を docs/design.md に記録する。
- 実測根拠は全て計算・実機スパイクで確認済み（ユーザーが before/after 画像で承認）。

## 1. 変更一覧（全て実測根拠付き）

### 1.1 トークン値（`tokens.py` DARK — プロット面系・Typography・grid は LIGHT へ参照共有で自動伝搬）

| # | トークン | 現値 → 新値 | 実測根拠・注記 |
|---|---|---|---|
| 1 | `error` | #c0392b → **#f38ba8** | on #1e1e2e: 3.02:1 → **7.08:1**。**LIGHT は現値 #c0392b 維持**。**新値は `close_hover`・`delta_negative` と同値の三つ組になる**（§3 で値分岐テスト必須） |
| 2 | `text_secondary` | #7f849c → **#9399b2** | on #1e1e2e: 4.44 → **5.81:1**（DARK のみ — LIGHT の text_secondary は対象外） |
| 3 | `typography.small_px` | 9 → **10** | **DARK のみ更新** — LIGHT は `typography=DARK.typography` の参照共有（`tokens.py:246`・identity lock `test_theme_tokens.py:200`）で自動追従。独立定義してはならない（レビュー捕捉: 事実誤認訂正） |
| 4 | `grid_alpha` | 60 → **150** | fg150 on black 実効: 1.34 → **2.95:1**。90=1.69・120=2.22 では不達を実測。LIGHT は参照共有（:247） |
| 5 | `signal_palette` | tab10 10色 → **8色 Okabe-Ito 基調・黒調整** `#56B4E9 #E69F00 #00C08B #F0E442 #FF6E4A #D98BC0 #9A8CFF #C8C8C8` | 黒背景最小 3.55→**7.57:1**・CVD 最小 ΔE: protan **4.8→13.2**／deutan **7.3→16.9**・通常視最小 35.1。LIGHT は参照共有（:207） |
| 6 | `drop_highlight` | #1f77b4 → **#94e2d5**（teal） | パレット外色相へ分離（UX-35）。Δ+ #a6e3a1 と ΔE27.9 |
| 7 | `cursor_b` | #89b4fa → **#74c7ec** | `chrome_highlight` から ΔE**23.4** 分離（UX-35）。sky 曲線とは ΔE11.4＋形状差で弁別 |
| 8 | `axis_move_indicator` / `axis_move_fill` | (255,165,0) → **#f59e0b**（fill 同色 α60） | amber 意味論統一（UX-35）。`accent_active` と同値化（§3） |

- 8色化で色再利用閾値は 10→8 に下がるが、**色割当アルゴリズム（UXG-15/16）はスコープ外**（増分E）。
- 許容判断（ユーザー承認済み・記録）: `#E69F00` vs `accent_active` ΔE7.2（曲線 vs クローム装飾の文脈分離）／
  `#56B4E9` vs `preview_curve` ΔE6.6（別窓単曲線限定）。

### 1.2 QSS（app レベル — `apply.py` の app sheet へルール連結）

| # | 変更 | 課題 |
|---|---|---|
| 9 | `QLineEdit` に常時 `1px solid chrome_frame` 枠＋`QLineEdit:focus` で `chrome_highlight` 枠。**carve-out 必須**: `QLineEdit#qt_spinbox_lineedit { border: none; }` を併記（型セレクタは QSpinBox/QDoubleSpinBox 内部の QLineEdit にも一致し、CsvFormatDialog の QSpinBox×3・ExportCsvDialog の QSpinBox×1 が二重枠になる — レビュー捕捉）。`apply_theme` の app sheet は既存 `main_window_separator` ルールとの**連結**になる（構成注記） | UX-49 |

### 1.3 寸法・当たり判定

| # | 変更 | 対象と方式 | 課題 |
|---|---|---|---|
| 10 | クリック当たり判定の**高さ**を 24px 以上へ保証（`setMinimumHeight`/余白 — **fixedSize(24,24) は使わない**: text ボタンの幅 44→24 縮小で「視覚不変」と矛盾しヒット幅がむしろ縮む — レビュー捕捉） | `CollapsibleDockTitleBar` の**フロート/✕（text ボタン 44×19 実測）**＋GraphPanel の**パネル +/×** — 縦方向のみ不足。**chevron は現状 24×23 で既充足（検証のみ・変更なし）**。**`DockCollapseRail` は対象外**（chevron は QLabel でタブ全面が既にヒット領域＝UX-38 充足済みと記録 — QToolButton は存在しない） | UX-38 |

- **スコープ調整（記録）**: タブ✕（Qt native close button）は `setTabButton` カスタム化と一体の増分D へ移管
  （UX-34 の常時赤✕排除と同時・二度作り替え回避）。

### 1.4 アイコン（vendored 追加のみ）

| # | 変更 | 課題 |
|---|---|---|
| 11 | export アイコンを `save.svg` → **Lucide `download.svg`**（unpkg lucide-static@1.24.0 pinned・無改変・`LICENSES.md` 追記・`icons.py` の `export` キー差し替え・pyproject package-data 収載確認）。`save.svg` は増分F 用に温存 | UX-42 |

### 1.5 初期レイアウト・列幅既定

| # | 変更 | 課題 |
|---|---|---|
| 12 | 初期ドック比率 File:Channel ≈ **1:4**（縦）。**適用規定（レビュー捕捉）**: (a) `_restore_state()` を「保存 windowState を適用したか」の bool 返しへ変更（`restoreState()` の bool を伝搬 — 現状 :598-611 は破棄）、(b) 適用は **初回 show 後**（`showEvent` 後の `singleShot(0)` — pre-show は dock extent 未確定で no-op になる既知の罠 `main_window.py:656-660`）、(c) **`_reset_layout()` も restore 後に同じ 1:4 を再適用**（`_default_state` は 1:4 適用前の捕捉のため、放置すると初回起動と Reset Layout で比率が食い違う） | UX-21 応急 |
| 13 | ChannelBrowser: Name 列 `Stretch`。**Unit 列は `ResizeToContents` を使わない** — prod 264k〜330k 行で `sizeHintForColumn` の O(n) 走査が reset ごとに走り FU-22 級フリーズを再導入しうる（レビュー捕捉）。**方式: `Interactive`＋モデル reset 時に先頭 N=50 行サンプリングの内容幅で `setColumnWidth`**（上限付き）。①ゲートに prod 相当ロードの同期ブロック時間無回帰を含める | UX-29 |
| 14 | Diagnostics: メッセージ列 `Stretch`・他列 `ResizeToContents`（行数は診断件数有界で perf 問題なし） | UX-07 応急 |

## 2. 波及の全数追随（レビューで補完済み — 実装タスクの必須チェックリスト）

1. **値 golden**: `test_theme_tokens.py` — パレット :69-78・drop_highlight :90・axis_move :91-92（**RGB 形式 `Color(255, 165, 0)`**）・error :93（DARK のみ・LIGHT :213 不変）・text_secondary :85・cursor_b・small_px・grid_alpha。
2. **本数/構造 golden（レビュー捕捉の漏れ分）**: `test_theme_tokens.py:54` `len(v) == 10` → 8。
   `test_theme_export.py` — :33-34 `for i in range(10)`・:40 `--vs-font-small: 9px`・:41 `--vs-grid-alpha: 60`・
   :53 `len == 10`・:54 palette[0] hex・:57 `small_px == 9`・:58 `grid_alpha == 60`。
3. **パレット循環テストの意図的 supersede**: `test_graph_panel_vm.py:810-824`
   `test_palette_cycles_beyond_ten_signals`（`colors[10] == colors[0]`）→「9 本目（index 8）が palette[0] へ
   循環」へテスト名・データ構築・docstring ごと再設計（10 色前提の supersede として記録）。
4. **同値別役割の値分岐テスト（§3）**: 新規 3 関係。
5. **realgui バッジテストの色衝突（事前特定済み）**: 新 palette[1] `#E69F00`(230,159,0) は amber
   `#f59e0b`(245,158,11) と全チャンネル ±20 以内 → `tests/realgui/test_offscale_badge.py` の走査が誤検出。
   **テスト側で曲線色を `set_color` で非衝突色（#56B4E9/#00C08B）へ明示指定**し :266 の色距離コメントを新値で書き直す。
6. **FU-12 ピクセル走査**: palette[0] #1f77b4→#56B4E9（B=233 で青ドミナンス維持見込み）を `--realgui` 実行で実証。
7. **`test_cursor_readout.py` の "#1f77b4" 多数**: CursorReading fixture の任意 hex — **追随不要**（変更しない）。
8. **旧色 grep（最終確認・パターン拡張済み — レビュー捕捉）**:
   `#1f77b4|#ff7f0e|#2ca02c|#d62728|#9467bd|#8c564b|#e377c2|#7f7f7f|#bcbd22|#17becf|c0392b|89b4fa|255,\s*165,\s*0`
   を src/ tests/ 全域 grep。**期待残存リスト**: LIGHT `error` #c0392b（意図維持）・`chrome_highlight` #89b4fa
   （cursor_b 分離後も選択色として正当）・`test_cursor_readout.py` fixture 群・`graph_panel_view.py:1433`
   docstring 例示。これ以外の残存は取りこぼし。

## 3. 同値別役割の値分岐テーマテスト（新規 3 関係 — memory `gui_freeze_tokenization_verification_pattern`）

| 関係 | 同値 | テスト（既存 `test_theme_qss.py:138-151`・`test_cursor_readout.py:565` の型） |
|---|---|---|
| `error` == `delta_negative` | #f38ba8 | 値分岐テーマで error_label/rename_error_border → error・readout Δ負値 → delta_negative を双方向実証 |
| `error` == `close_hover` | #f38ba8 | 同上 — readout ✕ hover → close_hover・エラー文言/枠 → error（**三つ組の 2 本目** — レビュー捕捉の列挙漏れ） |
| `axis_move_indicator` == `accent_active` | #f59e0b | 軸移動フィードバック → axis_move_*・アクティブ枠/バッジ → accent_active |

既存の値分岐テスト（`chrome_frame`==`border_chip`・`delta_negative`==`close_hover` 等）は不変。
`drop_highlight` の palette[0] 同値は解消されるが既存値分岐テストは削除しない（役割写像の実証を残す）。

## 4. 凍結スクショへの影響（per-state 期待差分表 — レビュー捕捉で全変更ベースへ拡張）

**監査基準は「§1 の全変更（トークン＋QSS＋寸法＋アイコン＋レイアウト）の着地箇所のみ」**。撮影は QSettings
隔離＝保存レイアウト無しのため #12 の 1:4 も必ず着地する。

| 状態 | 期待差分 |
|---|---|
| 01_welcome | ツールバー export アイコン・フィルタ/入力欄の 1px 枠・ドック比率 1:4・Name 列幅・診断列幅 |
| 02_plotted | ＋パレット 2 色（#56B4E9/#E69F00）・text_secondary/small_px（readout 無表示なら軸のみ） |
| 03_cursor | ＋cursor_b 色・readout ヘッダ/単位の明色化と 10px 化・Δ负 #f38ba8 |
| 04_grid | ＋grid 明化（α150） |
| 05_affordances | ＋drop_highlight teal 化（アクティブ枠 amber は不変） |
| 06/07 ダイアログ | error 文言 #f38ba8・QLineEdit 枠。**スピンボックスは二重枠にならないこと（carve-out の合格条件）** |
| 08_signal_preview | ほぼ不変（preview_curve #4FC3F7 据え置き）— 微差のみ許容 |
| 09_collapsed | 01 と同系＋レール表示（タブ寸法不変） |
| 02-05 系（共通） | UX-38 由来: パネル +/× glyph ~2px 下シフト（当たり判定 24px 化に伴うボタン高さ変更の副作用） |

手順: dark/light 撮影 → 上表と突合（表外の差分＝回帰調査）→ ベースライン更新＋Ground Truth 再同期
（DesignSync・docs/design.md 手順4-5）＋決定履歴へ記録（値一覧・パレット確定の増分E 制約）。

## 5. E2E 受け入れ（/gui-test-plan 分析）

### Task A: トークン値変更（§1.1）＋値分岐 3 関係（§3）＋golden/構造 assert 追随（§2-1〜3）
- 変更種別: トークン値＋描画の正しさ／レイヤー: A=必須（golden・本数構造・値分岐 3 組・循環テスト再設計）／
  描画 E2E=§4 の per-state 目視。prod スケール不要（色はデータ規模非依存）。
- Red/Green: golden が新値で RED → tokens.py 更新で GREEN。値分岐はサボタージュ（写像先取り違え）で RED 実証。

### Task B: QLineEdit 枠＋carve-out（§1.2）
- レイヤー: A/B=app sheet に両ルールが入り focus 分岐が効く assert／描画 E2E=01 の入力欄枠＋**06/07 の
  スピンボックス無変化を明示の合格条件**（レビュー捕捉）。realgui 不要（静的スタイル）。

### Task C: 当たり判定（§1.3）
- レイヤー: A=対象ボタンの `minimumHeight >= 24`／入力経路 E2E(C)=**必須** — honest RED は固定オフセットでなく
  **実行時 geometry から「旧 rect 外 ∧ 新 rect 内」の点を導出**して実 OS クリック（拡張前=不発・拡張後=発火。
  chevron は既充足のため検証のみ。DPI/フォント差でのフレークを避ける — レビュー捕捉）。
- 掴み点監査: 隣接ボタン誤爆なし＋**chrome overlay 拡大後も plot 側 press（曲線グラブ/ゾーン）が overlay
  直下以外で無回帰**（scoped realgui: collapse 系・panel 系・curve 系）。

### Task D: アイコン差し替え（§1.4）
- レイヤー: A=SVG 色規約（currentColor のみ）＋レジストリ解決＋package-data／描画 E2E=01 ツールバー目視。

### Task E: 初期レイアウト・列幅（§1.5）
- レイヤー: A/B=「1:4 適用が呼ばれた」の呼出記録＋ResizeMode/setColumnWidth 値 assert（**offscreen の
  dock 実寸 assert は構造的 false-green — 効きの証明はカタログ 01 実ディスプレイのみ** — レビュー捕捉）／
  描画 E2E=01 目視（File 薄・Channel 広・Name フル表示・診断メッセージ列拡張）。
- **perf E2E=必須（レビュー捕捉）**: quick/hils 相当の実ロードで ChannelBrowser 表示までの同期ブロック時間が
  現行と同等（Unit 列サンプリング幅方式の実証）。Reset Layout 後も 1:4 になることを Layer B で assert。

### 共通ゲート
- full pytest／ruff×2／mypy。①ゲート: `- [ ] uv run pytest --realgui tests/realgui/`（フル）＋§2-5/6 の
  実行確認＋Task C 実クリック証拠＋Task E perf 実測。§2-8 の旧色 grep（期待残存リスト照合）。

## 6. スコープ外（明示）

色割当アルゴリズム（UXG-15/16 — 増分E）／タブ✕（増分D）／Diagnostics 既定折りたたみ・自動展開（増分D）／
LIGHT の `text_secondary`・`chrome_highlight_text`（LIGHT 洗練反復）／警告系 amber の意味論整理（増分D）／
`preview_curve` の palette[0] 参照化（任意の後続）。
