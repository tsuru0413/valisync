# gui-plot-analysis-controls 設計 spec — 統一「アクティブ＋右クリック」操作モデルによるプロット/解析コントロールの完成

- **日付**: 2026-07-09
- **状態**: 設計（brainstorming 完了・ユーザー承認済み）→ writing-plans へ
- **一次情報源**: [docs/audit-findings-catalog.md](../../audit-findings-catalog.md) の SS-PLOTCTL（PC-01..22。PC-13/14/21/22 は解消済み）、[docs/roadmap.md](../../roadmap.md)
- **設計探索の来歴**: 7 並列 Understand エージェント（機能グループ別: 信号ブラウザ導線／曲線管理／Y軸・表示／パネル管理／カーソル計測／readout／ツールチップ）で残 18 課題の現状コード・欠落・共有面を実測調査（file:line は調査時点の実測値）。ビジュアルコンパニオン（モックアップ 3 画面）でユーザーと UI 形状を確定。

---

## 1. 背景と目的

実ユーザージャーニー監査で確定した SS-PLOTCTL クラスタ（プロット・曲線・Y軸・カーソル・読み取り表の操作コントロールと発見可能性）のうち、未解消の **18 課題（🔴3・🟠10・🟡5）** を解消する。

調査で判明した本質: **VM 側の能力は大半が既存で、欠けているのは「発見可能な操作面」**。

- PC-02/04: `add_to_panel_requested` → `_add_to_active_panel` の emit→sink 経路は完成済み。可視 UI（ボタン/ダブルクリック）だけ不足
- PC-01: `GraphPanelVM.remove_signal`(graph_panel_vm.py:427)・`toggle_visibility`(:486) は実装済み・未配線。新規は色変更のみ
- PC-06: `set_axis_range`(:510)・`reset_y`(:538)・`create_new_axis`(:250) 等ほぼ揃い、トリガー面だけ不足
- PC-08: `set_cursor(t)`(:738) 既存
- PC-11: 単位は `Signal.metadata['unit']` に捕捉済み（ChannelBrowser の Unit 列と Y軸ラベルが消費実績）。readout だけが落としている
- PC-12: `build_column_menu`(cursor_readout.py:215) は完成済み・呼び出し元ゼロ

したがって本サブスペックは「新機能開発」ではなく **「既存 VM 能力への統一的な操作面の接続」** である。

### 横断構造（増分の切り方を決めた 4 つの共有面）

1. **パネル右クリックメニュー**（`build_context_menu` graph_panel_view.py:1866）— PC-01/03/06/08/09 の 5 課題が共有。メニュー構造は本 spec で一括設計（バラバラ実装だと 3 回作り直し）
2. **CursorReadout** — PC-09/10/11/12/16/17/18 の 7 課題が同一ウィジェット。コピー内容は単位/精度に依存 → 単位/精度が先
3. **アクティブパネル**（PC-07）— PC-02/04 の配送先 `_add_to_active_panel`(main_window.py:375-381) が `panels[0]` ハードコード（バグ）。入口系の前提
4. **可視性の二重概念** — ChannelBrowserVM に配線先ゼロの死蔵 `_hidden`(channel_browser_vm.py:62,168-190) が存在。実体は GraphPanelVM.entry.visible。PC-05 は PC-01 に吸収し死蔵を削除

---

## 2. 統一操作モデル（本設計の核）

個別課題の寄せ集めではなく、1 つの操作言語に統一する:

> **「クリック＝アクティブ化、アクティブ＋キー＝操作、右クリック＝対象別メニュー」**

| 対象 | クリック | アクティブ時のキー | 右クリック |
|---|---|---|---|
| パネル | 活性化（枠表示） | — | パネルメニュー（既存＋「グリッド」checkable） |
| 曲線 | 活性化（太線化） | **H** = 表示切替 | 非表示／色変更 ▸／削除／新しい軸へ移動／時間オフセット…／オフセットをリセット… |
| Y軸 | 活性化（既存 amber 枠） | **H** = 軸内曲線の一括表示切替 | この軸をオートフィット／範囲を指定…／軸を削除／曲線一覧（チェック式） |
| カーソル線 | 活性化（太線化） | **←/→** = サンプル点へ移動 | 時刻を指定…／カーソルを消す |
| readout | （右上 ✕ のみ常時） | — | 統計列 ▸／精度 ▸／表をコピー／カーソルを消す |

- 素クリックは活性化専用。**クリックでのカーソル設置/移動はしない**（カーソル移動は線ドラッグ＋矢印キー＋数値ダイアログのみ）
- 既存の「アクティブ軸」操作モデル（クリック活性化・amber 枠）を全対象に一般化した形
- **アクティブ曲線の解除規則**: 別対象のクリック（軸・空白・他曲線）で解除され、H の対象は軸/なしへ戻る。**H による非表示化は解除トリガーではない**（非表示曲線はクリック不可のため、直後の H 再表示を保証する）。曲線のアクティブ化は**属する軸も同時にアクティブ化**する（枠と太線が常に同一軸を指す）

---

## 3. 承認済み設計判断

| # | 判断 | 決定 | 根拠 |
|---|---|---|---|
| DP1 | 対数軸・軸反転（PC-15 の一部） | **不採用**（follow-up にもしない） | ユーザー決定: 不要。region-overlay 仮想レンジ写像（y_axis_vm.py:39）貫通の回帰リスクが価値に見合わない |
| DP2 | 階層グルーピング＋折りたたみ（PC-20 の一部） | **follow-up へ後送り** | table→tree モデル転換の重量級。列ソートのみ今回実装 |
| DP3 | PC-05 の可視性の意味 | **PC-01 に吸収** | ChannelBrowser に可視性 UI を置かず曲線管理に一本化。死蔵 `_hidden` 系は削除 |
| DP4 | 曲線管理の器（PC-01） | **常時凡例は作らない。曲線右クリック＋アクティブ化+H** | ユーザー決定（モック A/B/C 提示の上で独自案）。chrome 最小・直接操作 |
| DP5 | 非表示曲線の再表示導線 | **Y軸右クリックの曲線一覧（チェック式）＋軸アクティブ時 H** | 軸は曲線が非表示でも残る（可視の入口）。PC-06 の軸メニューと器を共有 |
| DP6 | 素クリックの割当 | **活性化専用**（曲線/パネル）。カーソルのクリック設置なし | ユーザー決定。誤発火排除・ジェスチャ最小 |
| DP7 | カーソル精密操作 | **矢印キー=アクティブカーソル移動（サンプル点スナップ）＋カーソル線右クリックで数値ダイアログ** | ユーザー決定 |
| DP8 | readout 単位表示（PC-11） | **信号名の脇に 1 回 `[km/h]`（淡色）** | モック 3 案比較で B 採用。1 行内の全列は同一単位で情報欠落なし |
| DP9 | readout 精度（PC-16） | **可変精度 UI**（VM 状態・メニューで 4/6/8 桁・既定 6） | ユーザー決定（可変）。既定 6 桁への引き上げも承認済み |
| DP10 | readout コントロール配置 | **✕ のみ常時＋残りは右クリックメニュー** | モック 3 案比較で C 採用。「片付ける」だけは常時、他は流儀どおりメニュー |
| DP11 | 増分分解 | **4 増分**（§5） | 案 A/B/C 比較で A 採用。凝集度と PR サイズのバランス |
| DP12 | コピー（PC-10）のスコープ | **表示どおり（表示中の列・現在精度・単位込み）の TSV をクリップボードへ**。ファイル保存なし | 承認済み。予測可能性優先 |
| DP13 | グリッド（PC-15） | **X 方向（垂直線）のみ・パネルごと** | 承認済み。複数Y軸は各軸独立レンジで「Y グリッド」が多義的 |
| DP14 | ツールチップ（PC-19） | **lazy 方式・時間範囲は含めない** | 承認済み。O(n) 回避・FileBrowser 側で見られる（YAGNI） |
| DP15 | パネル枠・自動アクティブ | パネル 1 枚でも枠表示／新規パネルは自動アクティブ／起動時はパネル 0 アクティブ | 承認済み。一貫性・「作った＝使う」・クリック前でも Add が機能 |
| DP16 | オフセットドラッグのタイミング | **press は候補保持 → `startDragDistance` 閾値超えで開始／閾値内 release は曲線アクティブ化**（grabMouse は press 時点で取得・§7） | 承認済み。クリック=活性化との共存（既存ジェスチャの挙動変更） |
| DP17 | Y軸「追加」のトリガー面（PC-06 の 4 要素目） | **曲線メニューに「新しい軸へ移動」を追加** | spec 自己レビューで検出した欠落（軸追加だけ可視コントロール未設計＝PC-06 が catalog どおり解消しない）への対処。既存 D&D（プロットドロップ=新軸）と同一 VM 経路・空軸を作らないモデルと整合。※ユーザーレビューで要確認 |

---

## 4. アーキテクチャ（共通基盤）

### 4.1 アクティブ化状態の所在（MVVM 配置）

| 状態 | 置き場所 | 理由 |
|---|---|---|
| アクティブパネル `active_panel_index` | `GraphAreaVM._Tab`（graph_area_vm.py:21-27）にタブごとの VM 状態として追加 | MainWindow の配送（Add/Export）と GraphAreaView の枠描画の両方が読むクロスビュー状態。`x_sync_enabled` と同格 |
| アクティブ軸 `_active_axis_index` | GraphPanelView（既存 :669・変更なし） | 既存モデル維持 |
| アクティブ曲線 | GraphPanelView（View transient・軸と同格） | 操作は entry_id 指名で VM へ委譲。パネル再構築で自然リセット |
| アクティブカーソル（A/B） | GraphPanelView（View transient） | 矢印キーの配送先選択のみに使用 |

### 4.2 曲線の同一性 — entry_id 指名（PC-01 の前提修正）

現状 `_plotted: list[_PlottedEntry]`（dataclass graph_panel_vm.py:106-113・宣言 :128）は同一 signal_key を複数持て、`toggle_visibility`(:486) は先頭 1 件だけ反転する（曖昧）。**曲線操作を entry 単位の安定 ID に統一**する:

- `_PlottedEntry` に `entry_id`（単調増分 int）を追加。`RenderCurve` にも載せ View→VM の逆引きを ID で行う
- **View 側の再キー化もスコープに含む**: `refresh()` の `desired = {c.name: c}` マップ(graph_panel_view.py:794)・`_items: dict[str, PlotDataItem]`(:636)・`_item_vb`・`_curve_at` の返り値(:1457)・オフセットドラッグのキーは全て signal_key キーで同名 RenderCurve を collapse するため、**これらを entry_id キーへ移行**する（重複 signal_key の entry が独立の PlotDataItem として描画・ヒットテストされる）。テスト表面 `curve_keys()`/`curve_xy()`/`pen_color()`(:1141-1155) と既存テストへの波及に注意
- 新 API: `toggle_entry_visibility(entry_id)`／`set_color(entry_id, color)`／`remove_entry(entry_id)`。既存 `remove_signal(signal_key)` は production 呼び出しが現状ゼロ（D&D 置換は `overwrite_axis` 経由 :1827）— 既存テスト互換のため残置し、本 spec では配線しない
- **色変更・可視切替は cache invalidate＋`_notify('signals')` 必須**（色は `_make_cache_key`(:991) に含まれず、invalidate しないと古い色の RenderCurve が返る。既存 `toggle_visibility` が良い先例）

### 4.3 右クリックのルーティング一元化

`GraphPanelView.contextMenuEvent`(:1903) を pos ベースのヒットテスト分岐に拡張。QGraphicsItem 側にハンドラを散らさず、`classify_zone`＋`_axis_index_at`＋`_curve_at` で 1 箇所に集約する。

**優先順: カーソル線 → 曲線 → Y軸 → 空白（=パネルメニュー）**

| ビルダ | 項目 |
|---|---|
| `build_cursor_menu(which)` | 時刻を指定…／カーソルを消す — **消去スコープ**: A 線=全消去（B は「B は A 依存」の既存 VM 不変条件どおり道連れ）・B 線=Δ のみ無効化（`toggle_delta(False)`） |
| `build_curve_menu(entry_id)` | 非表示／色変更 ▸（`_PALETTE` 10 色スウォッチ＋「その他…」）／削除／**新しい軸へ移動**（この entry を新規 Y軸へ付け替え＝PC-06「軸の追加」の可視トリガー面。既存 D&D の `create_new_axis` 経路 :1833 と同じ VM 挙動）／──／時間オフセット…／オフセットをリセット…（適用中のみ enabled・**スコープ選択ダイアログ〔`_default_apply_dialog` と同型・DI 注入〕経由**で `reset_offset` を呼ぶ）／`オフセット: +0.250s`（disabled 情報行・非ゼロ時のみ） |
| `build_axis_menu(axis_index)` | この軸をオートフィット／範囲を指定…／軸を削除／──／曲線一覧（チェック式・非表示含む・`entries_on_axis` から構築） |
| `build_context_menu()`（既存拡張） | 既存項目＋「グリッド」checkable |

- ダイアログ（軸範囲・カーソル時刻・オフセット数値・QColorDialog）は全て **DI 注入**（既存 `apply_dialog_fn`(:631) パターン）でテスト時スタブ可能に。realgui でネイティブモーダルを駆動しない既存作法を踏襲
- disabled 項目にツールチップを付ける箇所（§8 のサブカーソル等）は **`menu.setToolTipsVisible(True)` を併設**（QMenu は既定で QAction ツールチップを表示しない — 文字列 assert だけの Layer B は false-green になる）

### 4.4 キーイベント

`GraphPanelView.keyPressEvent`(:1718-1723、現状 Esc のみ) に追加。focus は既存 ClickFocus(:777):

- **H**: アクティブ曲線があればその表示切替 → なければアクティブ軸の全曲線を一括切替（1 本でも可視なら全非表示／全非表示なら全表示）
- **←/→**: アクティブカーソルを移動。`GraphPanelVM.step_cursor(which, direction, reference_entry_id=None)` 新設 — View がアクティブ曲線の entry_id を渡し、None（または非表示）なら先頭可視 entry にフォールバック（可視ゼロは no-op）。基準曲線の隣接サンプル時刻へスナップ（**オフセット適用後の表示時刻**基準）。端で clamp。アクティブ曲線は View transient のため VM は引数で受ける（§4.1 と整合）
- 既存 Esc（オフセットキャンセル）は不変

---

## 5. 増分分解（4 増分・実装順 1→2→3→4）

| 増分 | 内容 | 解消課題 |
|---|---|---|
| **1. アクティブパネル＋載せる入口** | `active_panel_index`＋配送修正＋パネル枠、ChannelBrowser の Add ボタン＋ダブルクリック/Enter | PC-07🟠・PC-02🔴・PC-04🟠 |
| **2. 曲線・軸の直接操作** | 曲線アクティブ化＋H、曲線/Y軸右クリックメニュー、VM 追加 API、オフセット導線＋リセット、死蔵削除 | PC-01🔴・PC-03🔴・PC-05🟠・PC-06🟠 |
| **3. カーソル・readout 計測 UX** | アクティブカーソル＋矢印キー、数値ダイアログ、補間 checkable＋表示、readout 刷新（単位/精度/列/コピー/✕/移動カーソル） | PC-08🟠・PC-09🟠・PC-10🟠・PC-11🟠・PC-12🟠・PC-16🟡・PC-17🟡・PC-18🟡 |
| **4. 仕上げ** | グリッド X、チャンネルツールチップ、列ソート | PC-15🟠(縮小)・PC-19🟡・PC-20🟡(縮小) |

- 1 が 2 の「アクティブ」基盤と入口を先に固める。4 は独立でいつでも可
- 各増分は gui-shell-controls と同規模の 1 PR。🔴3 件は増分 1・2 で早期解消
- writing-plans 時に増分 2・3 を 2a/2b 等へ分割する余地を残す
- **§4 共通基盤の増分帰属**: `active_panel_index`＝増分 1／entry_id・右クリックルーティング骨格（曲線/軸/空白分岐）・H キー＝増分 2／カーソル線分岐・←/→＝増分 3（増分 2 のルーティングはカーソル線分岐を後から差し込める形にする）

---

## 6. 増分 1 詳細: アクティブパネル＋載せる入口

### GraphAreaVM（Layer A 主戦場）
- `_Tab` に `active_panel_index: int = 0` を追加（タブごと）
- `set_active_panel(tab_index, idx)`＋アクセサ＋`_notify("active_panel")`
- 不変条件: 起動時パネル 0 アクティブ／`add_panel`(:171) で新規パネル自動アクティブ／`remove_panel`(:189) で clamp（アクティブより前を消したら -1 追従・自身なら同 index を len-1 に clamp。`active_tab_index` の clamp :146-149 が手本）
- 配送修正: `_add_to_active_panel`(main_window.py:375-381) と Export 初期選択(:405-406) を `panels[0]` → アクティブパネルへ

### View（枠表示・活性化）
- パネル内の任意クリック（プロット `mousePressEvent`:1653 と `_AlignedAxisItem` クリック :443-448 の両経路）→ `activate_requested(panel_index)` → GraphAreaView（`_wire_panel`:188-211）が VM へ配線。軸クリックはパネルも活性化
- アクティブ枠はアクティブ軸 amber 枠(:377-395)と同系の控えめな枠。**overlay/scene 描画で plot 原点 (0,0) を動かさない**（memory [[gui_panel_chrome_layout_row_shifts_hittest_origin]]。QWidget border stylesheet は content margin を足し plot をシフトさせるため不可。検証は `plot_widget.pos()==(0,0)`）
- `active_panel` 通知は `_rebuild` を起こさず枠の再描画のみ（`_sync_current`:213-218 と同じ軽量経路）。`_rebuild` 後は VM から枠を再適用
- パネル 1 枚でも枠表示（DP15）

### ChannelBrowser（入口）
- ヘッダ行に「**アクティブパネルへ追加**」ボタン（FileBrowser Open ボタンのパターン file_browser_view.py:72-83 踏襲・objectName 付き・選択 0 件で disabled、selectionChanged で同期）
- `tree.activated`（ダブルクリック）＋ `keyPressEvent` の Return/Enter 明示処理 → 同じ `add_to_panel_requested.emit(selected_signal_keys())`。対象は現在の複数選択全部（右クリックメニュー :152-160 と同一挙動）
- **二重発火ガード必須**: Windows では `activated` が Return/Enter でも発火するため、素直に両配線すると Enter 1 回で 2 回 emit される。**Return/Enter は keyPressEvent で処理し accept で消費（activated へ到達させない）、activated 経路はダブルクリック専用**とし、Enter で 1 回だけ emit されることを Layer B で検証する（タブ改名の hide() 再入二重発火＝PR #53 と同型の罠。DataExplorerView :79 は activated 単独配線のためガードの先例にならない）

---

## 7. 増分 2 詳細: 曲線・軸の直接操作

### GraphPanelVM 追加 API（全て cache invalidate＋notify）
- `set_color(entry_id, color)`／`toggle_entry_visibility(entry_id)`／`remove_entry(entry_id)`（→既存 `_compact_axes`:360。空軸の blank band 挙動は既存パリティ維持）
- `move_entry_to_new_axis(entry_id)` — 「新しい軸へ移動」用: entry を現在軸から外し新規軸へ付け替え（既存 `create_new_axis`:250／`_compact_axes` の不変条件と整合。空軸は作らない）
- `reset_axis_y(axis_index)`（`reset_y`:538 の単一軸版。invisible 除外は既存踏襲）／`remove_axis(axis_index)`（軸上全 entry 削除＋compact）
- `entries_on_axis(axis_index)` → `[(entry_id, 表示名, color, visible)]`（軸メニューの曲線一覧用）
- `offset_for(signal_key) -> float` — signal＋file 合算の現在有効オフセット（private `_signal_offsets`/`_file_offsets`:158-159 の公開 getter。曲線メニューの enabled 判定と情報行用）

### AppViewModel 追加 API と配線
- `reset_offset(...)` — `apply_offset`(app_viewmodel.py:58-81) と対称（スコープ: この信号のみ／ファイルグループ全体を 0 へ）。既存 `'offsets'` 通知 → GraphAreaVM(:67-78) → 各 `GraphPanelVM.set_offsets`(:467-484) の配信経路にそのまま乗る
- **上流配線**: 既存 `offset_apply_requested` と同型の新 signal `offset_reset_requested` → GraphAreaView `_wire_panel` → GraphAreaVM 転送 → `AppViewModel.reset_offset`。UI フローは曲線メニュー「オフセットをリセット…」→ スコープ選択ダイアログ（`_default_apply_dialog` と同型・DI 注入）→ emit

### 曲線アクティブ化とオフセットドラッグの共存（DP16・挙動変更）
- 現状: 曲線上 press で即 `_begin_offset_drag`(:1511)
- 新: press は候補保持 → `QApplication.startDragDistance()` 閾値超えの move で `_begin_offset_drag` へ昇格／閾値内 release で曲線アクティブ化
- **grabMouse は press（候補保持開始）時点で取る**（閾値超え後ではない）: 押下中の move は子 QGraphicsView viewport に消費され親 GraphPanelView に届かない（memory [[gui_realgui_move_not_reaching_parent_qwidget]]・:1526-1531 のコメントが根拠。viewport の eventFilter :1680-1686 は button-held move を転送しない）。閾値判定自体に move が要るため press で grab し、**閾値内 release（活性化）・Escape・全終了パスで releaseMouse**（既存 `_reset_offset_state`:1604 のパターン踏襲）。Layer B の sendEvent は move を親へ直送するためこの欠陥を検出できない — 実 OS ドラッグの Layer C が真のゲート
- アクティブ曲線の可視フィードバック: **線幅太線化**（通常 1 → アクティブ 2.5・色不変）。`refresh`(:828) の setPen で反映
- 非表示曲線はクリック不可（描画されない）→ 再表示は軸メニュー／軸 H（DP5）

### PC-03「誰も気づけない」の解消根拠（3 欠落の分担）
カーソルヒント/アフォーダンスは **PC-14 解消（PR #50）の曲線近傍ホバー DRAG_H**(:1641-1651) で既提供。本 spec は残り 2 欠落 — **起動導線**（曲線メニュー「時間オフセット…」＋数値ダイアログ）と**状態可視化**（「オフセット: +0.250s」情報行・リセット導線）— を追加し、3 要素の組で解消する。

### 死蔵コード削除（PC-05 吸収）
- `ChannelBrowserVM._hidden`(:62)／`toggle_visibility`(:168-174)／`is_visible`(:176)／`visible_signal_keys`(:180-190)、`SignalItem.visible` フィールド(:27・算出 :97)とその参照箇所、View の `toggle_visibility_for_selection`(channel_browser_view.py:145-148)、対応テストを削除

### オフセット数値ダイアログ
- 「時間オフセット…」→ 既存ドラッグ確定ダイアログ `_default_apply_dialog`(:1606-1637・この信号のみ/ファイルグループ全体) に Δt 数値入力を加えた拡張。DI 注入

---

## 8. 増分 3 詳細: カーソル・readout 計測 UX

### カーソル操作（PC-08）
- **設置経路は不変**: パネルメニューのメインカーソル/サブカーソル checkable・初期位置 50%/75% はそのまま。固定初期位置の不便は「設置直後の自動アクティブ → 矢印キー（サンプルスナップ）／線右クリック→時刻を指定…」で任意時刻へ即移動できることで解消する
- アクティブカーソル（A/B）: カーソル線のクリック/ドラッグで活性化、設置直後は自動アクティブ。アクティブ線は太線化（曲線と同じフィードバック言語）
- `GraphPanelVM.step_cursor(which, direction, reference_entry_id=None)` 新設（§4.4）。ロジックは VM（Layer A で網羅）、キー配送と基準 entry_id の解決だけ View
- カーソル線右クリック → `build_cursor_menu`: 時刻を指定…（数値ダイアログ・DI）／カーソルを消す（消去スコープは §4.3: A=全消去・B=Δ のみ）

### 補間方式の可視化（PC-09）
- サブメニュー(:1892-1900) を checkable＋QActionGroup 排他にし現在値（`vm.interp_method`:144）を checked（`build_column_menu`:215-229 の既存パターン踏襲）
- readout ヘッダ右端に現在方式を常時表示（例: `●A 12.400s ●B 15.200s Δt 2.800s ─ 線形`）。`_sync_cursor_from_vm`(:1207 付近) からラベルを渡す引数拡張

### readout 刷新（PC-10/11/12/16/17/18）
- **単位**: `CursorReading`(graph_panel_vm.py:65-73)/`DeltaReading`(:76-86) に `unit: str = ''` 追加。`cursor_readings`(:773-781)/`delta_readings`(:868-878) で `sig.metadata.get('unit','')` 注入（axis.unit :216-218 と同パターン）。表示は DP8（名前脇 `[km/h]` 淡色）
- **精度**: 散在フォーマッタ（`_fmt`:23/`_fmt_dy`:33/`_fmt_time`:39/inline stat_map:172-178）を精度パラメータ付き単一フォーマッタへ集約。精度は `visible_stat_cols` と同じく VM が source of truth（既定 6・4/6/8 切替）。**適用範囲は値・統計列のみ** — count は整数のまま、時刻表示（●A/Δt ヘッダ）は既存 `_fmt_time` の固定精度を維持。TSV コピーも同規則
- **右クリックメニュー**（DP10）: 統計列 ▸（既存 `build_column_menu` 配線=PC-12）／精度 ▸／表をコピー／カーソルを消す（**✕ と同一＝全消去**）
- **コピー**（DP12）: 表示中の列・現在精度・単位込み TSV を `QApplication.clipboard()` へ。`row_texts()`(:197-203) は表示整形済みで再利用不可のため構造化行データ API を追加（`header_text`/`column_headers`:185-195 は置換対象外）
- **✕ 常時**（PC-17）: readout 右上。クリック=カーソル全消去（既存 `toggle_main_cursor(False)` 経由・`_sync_cursor_from_vm` :1210-1216 が非表示＋`reset_user_moved` まで処理済み）。灰色サブカーソル項目(:1889) に `setToolTip("メインカーソルを有効化すると使えます")`
- **移動アフォーダンス**（PC-18）: `setCursor(cursor(CursorKind.MOVE))` 1 行（cursor_shapes.py の既存レジストリ再利用）。readout 行からの曲線操作入口は作らない（曲線右クリックに一本化・二重実装回避）

---

## 9. 増分 4 詳細: 仕上げ

- **グリッド**（PC-15 縮小・DP13）: パネル右クリックメニューに「グリッド」checkable。X 方向（垂直線）のみ。状態は `GraphPanelVM.grid_enabled`（パネルごと・transient）。描画は共有 `_x_axis`(graph_panel_view.py:686) ベース（overlay 値写像は不変更）
- **チャンネルツールチップ**（PC-19・DP14）: lazy 方式 — `ChannelBrowserVM.tooltip_for(key)` を `SignalTableModel` の ToolTipRole(qt_signal_models.py:137-138) からホバー時のみ呼ぶ（FileListModel の遅延 `tooltip_text` :89-90／file_browser_vm.py:81-97 が先例）。内容: 単位／サンプル数（生記録数 `len(timestamps)`）／由来（bus_type・channel_group_name/source_name。CSV 等の欠損行は省略）／comment／**value_labels（LD-07 退行なし・一節として内包。既存テスト test_channel_browser_vm.py:92-147・test_qt_signal_models.py:84-128 の期待値更新）**。時間範囲は含めない
- **列ソート**（PC-20 縮小・DP2）: `QSortFilterProxyModel` を挟み `setSortingEnabled(True)`（ヘッダクリックで名前/単位ソート）。フィルタは現行どおり VM 真実（proxy はソート専用）。`selected_signal_keys`(:130-137) と D&D の index は `mapToSource` 経由に修正

---

## 10. エッジケース・エラー処理

| ケース | 挙動 |
|---|---|
| アクティブパネル削除 | clamp（§6）。`_rebuild` 後は VM から枠を再適用 |
| アクティブタブに信号未選択で Add | 選択 0 件はボタン disabled（§6）。防御的 no-op ガードは維持（「パネル 0 枚のタブ」は VM 不変条件〔各タブ常時 ≥1 パネル・graph_area_vm.py:35,126-127,196〕により通常到達不能） |
| H で非表示にした曲線 | **アクティブのまま維持** — もう一度 H で再表示可能（クリック不可でも H が効く）。解除は曲線削除・パネル再構築・**別対象のクリック（軸・空白・他曲線）**（§2 の解除規則） |
| 軸 H の一括切替 | 1 本でも可視 → 全非表示／全非表示 → 全表示 |
| 最後の 1 軸を「軸を削除」 | 許容 — 全曲線削除時の既存挙動と同じ空パネルへ戻る（既存パリティ） |
| カーソル消去の各入口 | A 線メニュー=全消去（B 道連れ・既存不変条件）／B 線メニュー=Δ のみ／readout ✕・readout メニュー=全消去（§4.3・§8） |
| オフセット未適用の曲線 | 「オフセットをリセット」disabled・現在量表示行は非表示 |
| 数値ダイアログの不正入力 | lo≥hi・非有限値は OK 無効化（CsvFormatDialog の既存作法） |
| ←/→ が端に到達 | 最初/最後のサンプルで clamp。可視曲線ゼロなら no-op |
| カーソル未設置 | readout 自体が非表示 → コピー/✕ は露出しない |
| 表示状態の永続化 | しない（グリッド・色・精度・アクティブ状態は transient。永続化は Phase 3 valisync-persistence） |

---

## 11. テスト戦略（Layer A/B/C）

計画時 `/gui-test-plan`・merge 前 `/gui-verify` ①ゲート。詳細レイヤー定義は [docs/gui-testing-layers.md](../../gui-testing-layers.md)。

### Layer A（純 VM ロジック・CI）— 主戦場
- `active_panel_index` set/clamp/自動アクティブ/タブごと独立、配送先の実 VM 検証（どの GraphPanelVM が `add_signal` を受けたか）
- entry_id 指名 API・`reset_axis_y`・`remove_axis`・`entries_on_axis`
- `reset_offset` の加減算・`'offsets'` 通知、`step_cursor` のスナップ/clamp
- 精度付きフォーマッタ・unit 注入・TSV シリアライズ・`tooltip_for` 組立（value_labels 内包＝LD-07 退行防止）

### Layer B（sendEvent 合成・CI）
- Add ボタン enable 同期＋click→emit、Enter 追加（**Enter 1 回で 1 回だけ emit＝二重発火防止**）、ダブルクリック→activated（warm-up click 前置＋sabotage 検証・memory [[gui_qtest_dblclick_warmup_click]]）
- **contextMenuEvent ルーティング**: QContextMenuEvent を sendEvent し、pos に応じ cursor/curve/axis/panel の正しいメニューが優先順どおり構築されること（ビルダー直呼びだけで済ませない — ルーティング破壊の false-green 防止）
- **keyPressEvent**: qtbot.keyClick 合成で H（曲線切替→軸フォールバック）・←/→（step_cursor 配送・ClickFocus 前提込み）が起動すること
- **クリック活性化**: 合成 press で `activate_requested`→VM 反映（パネル）／曲線・軸のアクティブ状態反映
- 各メニュー構築（項目・enabled・checkable 排他・現在値反映）— ダイアログは DI スタブ
- readout: 単位/精度の row_texts 反映・✕→カーソル消去・コピー→clipboard 検証・補間ラベル
- proxy ソート順・`mapToSource` 選択

### Layer C（realgui・実 OS 入力＋スクショ AI 判定）— headless が構造的に false-green を出す経路のみ
- **増分 1**: 実クリックでパネル 2 活性化→枠スクショ→Add 実クリックでパネル 2 着地（H8 click_to_activate_axis が雛形）／実ダブルクリック追加（GetDoubleClickTime 窓内 2 連打・memory [[gui_qtest_dblclick_warmup_click]]）
- **増分 2**: 曲線実クリック活性化（太線化スクショ）→実 H キーで非表示⇄再表示／曲線・軸の実右クリックメニュー実行／**既存 `tests/realgui/test_offset_drag.py` の見直し必須** — DP16 の閾値変更で「閾値内クリック=活性化」「閾値超え=実ドラッグ開始→オフセット適用が実際に動く」の両方を実 OS 入力で検証（grabMouse タイミングの誤りは Layer B では検出不能・memory [[gui_realgui_move_not_reaching_parent_qwidget]]。挙動変更時は同値を assert する並行 realgui を tests/ 全体 grep — memory [[gui_behavior_change_stale_parallel_realgui_test]]）
- **増分 3**: 実 ←/→ でカーソル移動／readout ✕ 実クリック／readout 実右クリックメニュー
- **増分 4**: グリッドの実描画スクショ判定（描画ピクセルの正しさは realgui のみ誠実・memory [[gui_offscreen_grab_text_tofu]]）。**proxy 挿入で D&D のドラッグ元 index 経路が変わるため、既存 ChannelBrowser 発の realgui D&D（H1-H4 系クロスウィジェット QDrag）を①ゲートで再実行し無回帰を証拠化**（D&D は合成再現不可・memory [[gui_drag_drop_not_sendevent_reproducible]]）。ツールチップは Qt 標準 ToolTipRole 自動表示のため A/B で十分と文書化（実ホバー 1 本は任意。やる場合は memory [[gui_realgui_hover_needs_incremental_move]] の小刻みスイープ）
- 新規 realgui は全て `_realgui_input` 実 OS 入力ヘルパ使用（Layer C 契約ガード `tests/gui/test_realgui_layer_c_contract.py` が CI で合成を検出）

### 品質ゲート
各増分 PR ごとに `uv run pytest`／`ruff check`＋`ruff format --check`／`mypy src/` 全通過＋subagent-driven レビュー（既存運用踏襲）。

---

## 12. スコープ外・Follow-up

| 項目 | 扱い |
|---|---|
| 対数軸・軸反転 | **不採用**（DP1・ユーザー決定「不要」。follow-up にもしない） |
| 階層グルーピング＋折りたたみ（PC-20） | follow-up（table→tree 転換。着手時は Signal.metadata のグループ化キー整備状況を先に確認） |
| 表示状態（グリッド/色/精度/レンジ）の永続化 | Phase 3 `valisync-persistence` へ |
| 計測スナップショットのファイル保存 | 不採用（クリップボード TSV のみ・DP12） |
| 非表示曲線バッジ（`1 hidden ▾` overlay） | 不採用（再表示は軸メニュー＋H で足りる・DP5） |
| コマンド一覧へのショートカット統合（H・←/→ のメニュー表記） | 増分実装時に ShellActions レジストリとの整合を確認（パネルローカルキーは QAction 化せず View 直処理で可） |
