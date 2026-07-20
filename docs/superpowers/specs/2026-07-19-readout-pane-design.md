# カーソル読み値の常設ペイン化（readout-pane）設計

日付: 2026-07-19 ／ ステータス: 承認済み（brainstorming）
出自: UIUX 再設計プログラム**増分B** — claude.ai/design 検討の inbox 決定メモ
（2026-07-18-uiux-concept-and-main-layout）＋カード「コンセプトとメイン画面案」
2a/2b（読み値テーブル）・4b（比較状態）。プログラム全体 A〜F のうち2番目。

## 1. 背景・問題

現在のカーソル読み値（`CursorReadout`）は各 `GraphPanelView` の**子オーバーレイ**で、
プロットの上に浮かびそのパネルの信号だけを表示し、カーソル設置時に現れドラッグで
動かせる。パネルが複数あれば読み値も複数浮く。フロートチップは (a) 波形本体に被る、
(b) パネルごとに散在する、(c) 「見比べる」ための一覧性が弱い。コンセプトは
「カーソル読み値はオーバーレイ廃止 → 常設テーブルへ」。

## 2. 要件（確定した設計判断）

- **コンテナ**: グラフエリアの一部（GraphAreaView 内ペイン）。MainWindow の
  QDockWidget にはしない（ユーザー確定: 案2）
- **表示/非表示トグル**: あり。位置は右固定・左右切替は作らない（要望なし・YAGNI）
- **集約範囲**: **アクティブパネルの信号のみ**（増分Aのアクティブ概念と一貫・
  タブ内全集約はしない）
- **カーソル未設置時**: プレースホルダのみ（値表示は完全にカーソル連動・案b）。
  信号ゼロ時は別プレースホルダ
- **実装方針**: 既存 `CursorReadout` を進化（新規ゼロ作りはしない・案1）

## 3. アーキテクチャ（§1）

所有を GraphPanelView（子オーバーレイ）→ GraphAreaView（タブレベル単一ペイン）へ移す。

```
GraphAreaView
└─ QSplitter(Horizontal)
    ├─ QTabWidget（プロットスタック群・既存）    ← 左
    └─ ReadoutPane（進化した CursorReadout ×1） ← 右（トグルで開閉）
```

CursorReadout インスタンスはアプリ全体で1つ（現在の「パネルごと」から激減）。
タブ切替してもペインは1つのまま「アクティブタブのアクティブパネル」を映す。

**ウィジェットの進化（CursorReadout）**:
- **残す**: 表描画・列・統計列・精度切替・value_labels 併記・デルタモード・
  `table_tsv` CSV コピー・右クリックメニュー（`build_readout_menu`）
- **外す**: ドラッグ移動・`_reposition_readout`/`_readout_placed`/`was_user_moved` の
  フロート追従・カーソル連動の自動可視・チップ枠スタイル（WA_StyledBackground・角丸）・
  チップの常時✕（=全消去）
- **足す**: プレースホルダ状態2種・行クリックで該当波形ハイライト・
  ペイン面の `surface_readout_panel` 背景・Δ の符号着色

## 4. データフロー（§2）

読み値の算出は VM 据え置き（`GraphPanelVM.cursor_readings()`/`delta_readings()`/
`value_precision`/`visible_stat_cols`/`interp_method`）。カーソルはグローバル時刻
ブロードキャストなので、どのパネルがアクティブでも既存ロジックで読み値が出る。
変えるのは「どこへ流すか」だけ。

**`_sync_readout()` の起動条件（4つ）**:
1. タブ切替（`QTabWidget.currentChanged`）
2. アクティブパネル変更（増分Aで使った `"active_panel"` 通知経路）
3. アクティブパネルのカーソル/信号変化（GraphPanelView が読み値関連の状態変化時に
   pull シグナルを emit → GraphAreaView が受けてアクティブ判定）
4. パネル rebuild（`"panels"`）

**`_sync_readout()` の中身**: アクティブパネル VM を引く →
`cursor_t is None` or 信号ゼロ → プレースホルダ ／ `delta_enabled` かつ B あり →
`set_delta` ／ それ以外 → `set_global`。プロット上のカーソル縦線の表示は従来どおり
GraphPanelView が管理（移動しない）。

**行クリックハイライト（新規）**: 現状 `CursorReading`/`DeltaReading` は `name`/`color`
のみで曲線への安定識別子を持たない（同名 signal_key の複数エントリを区別できない）。
そこで両 dataclass に **`entry_id`（`_PlottedEntry.entry_id` の単調安定 id）を追加**し、
読み値行がプロット曲線への逆引きを持つようにする。ReadoutPane が「行クリック →
`entry_id`」のシグナルを出し、GraphAreaView がアクティブパネルへ転送して該当曲線を
強調（既存の曲線ハイライト機構＝entry_id ベースを再利用）。VM の readings 生成側で
entry_id を詰めるのが唯一の VM データモデル変更。

**再配線**: 既存 callback（`_on_clear`/`_on_precision`/`_on_stat_toggled`）は
GraphAreaView 経由でアクティブパネル VM へ配線し直す。

## 5. 単一ファイル列と比較（§スコープ）

- **単一ファイル（B の主眼）**: カーソル A 設置時、列 = 「信号名 ｜ A値 ｜ min–max」。
  A は主カーソル位置の補間値、min–max はその信号の値域（VM 既存の min/max stat から
  `lo–hi` 整形）。統計列・精度・value_labels は移植
- **デルタ（移植）**: `delta_enabled` かつ B カーソルありで A/B/Δ＋統計列。**Δ(B−A) を
  符号で赤緑着色**（`delta_negative`/`delta_positive`）— これは readout の新挙動
- **比較は骨格まで**: run 横断の「vs 基準」列・比較データモデル（同名信号の重ね・
  基準指定・ファイル=色）は**増分E**。B では A/B/Δ の列構造まで

## 6. トークン（§3・3個・同乗導入）

消費者を持つ3トークンを追加（消費者なし先行導入は避ける）。

| トークン | DARK | LIGHT | 役割・消費点 | 同値別役割 |
|---|---|---|---|---|
| `surface_readout_panel` | `#1e1e2e` | `#eff1f5` | 読み値ペイン面（qss 背景・常時消費） | =`chrome_alternate_base`（DARK では `chrome_window` とも同値）→ 値分岐テスト必須 |
| `delta_negative` | `#f38ba8` | `#d20f39` | Δ(B−A) 負値・基準比マイナス文字色（デルタモードで消費） | =`close_hover` 同値 → 値分岐テスト必須 |
| `delta_positive` | `#a6e3a1` | `#40a02b` | Δ(B−A) 正値・基準比プラス文字色（Catppuccin green・デルタモードで消費） | 新規値（同値ペアなし） |

golden スナップショット（DARK/LIGHT）を更新。LIGHT は Catppuccin Latte 系。

## 7. 検証（§4）

**Layer B（CI）**:
- ペインのアクティブパネル束縛（アクティブ切替で内容が入れ替わる）・タブ切替追従
- プレースホルダ2種（信号ゼロ／カーソル未設置）
- 単一列レンダ（名前｜A｜min–max）
- デルタ Δ の符号着色（`delta_negative`/`positive` 参照を値分岐で実証）
- 行クリック → ハイライト転送
- トークン配線（qss 生成関数）＋**同値別役割トークンの値分岐テスト**
  （`surface_readout_panel` vs chrome 群・`delta_negative` vs `close_hover`）
- フロート挙動を検証していた既存テストは honest に更新（削除でなく新挙動へ・
  memory gui_behavior_change_stale_parallel_realgui_test）

**Layer C（realgui・/gui-verify ①ゲート）**:
- ペインでの行クリックハイライト・CSV コピー・アクティブ切替でのペイン内容切替を
  実機実証＋既存カーソル系無回帰

## 8. 成果物（大きな意図差分）

- 読み値がオーバーレイ→右ペインへ移動しプロットが狭まる → **カタログ 03_cursor/
  05_affordances が大きく変わる**（意図差分）。前後差分の空間分布で「読み値の
  再配置＋プロット幅縮小のみ」を確認 → ベースライン差し替え・両テーマ再撮影・
  エクスポート再生成・valisync-design 再同期
- `design/cards/readout_chip.html` を「readout パネル」カードへ更新（チップ→ペイン）
- docs/design.md: トークン表に3個追記＋決定履歴（運用反復3・出典 inbox メモ＋
  カード 2a/2b/4b）。CLAUDE.md 更新は merge 後 docs PR

## 9. 進め方

`feature/readout-pane` ブランチ・subagent-driven development・ゲート4種
（pytest / ruff check / ruff format --check / mypy src/）。タスク5〜7個の中反復。
