# 計測 IA 刷新（旧・計測モードバー）設計

- 日付: 2026-07-21（敵対的設計レビュー 33 指摘反映済み — blocker 3・important 19 を全て取込）
- 出典: [UIUX 敵対的レビューカタログ](../../uiux-adversarial-review-catalog.md) デザイン推奨3
  ＋**ユーザー決定 v3（2026-07-21・モックアップ 3 版で確定）**:
  1. **専用計測バーは作らない**（推奨3 の「常設計測バー」を supersede）
  2. カーソル即値（A/B/Δt）は**ステータスバー左**に常設（既存メッセージは右へ）
  3. カーソル A/B の表示切替・補間方式は **Analyze メニュー＋右クリックのみ**
  4. **グリッド・Sync X は右クリックのみ**（既存 Sync X チェックボックスは撤去。
     カタログ UX-32 の「View メニューへ追加」推奨はこの決定で supersede）
  5. タブ行右肩には「読み値」トグルのみ残す
- 解く課題: UX-04・UX-13・UX-14・UX-15・UX-16・UX-22（凡例回復部分）・UX-24（解析系部分）・
  UX-25・UX-26・UX-32・UX-33・UX-37・UX-46・UX-48。
- **記録済み決定の supersede（本 spec で実行・design.md 決定履歴へ記録）**:
  spec-B（readout-pane 増分B）案b「カーソル未設置時はプレースホルダ文言」→ **凡例モード**へ。

## 1. 現状の構造（調査・レビューで確定済み — main@f323460 相当）

- カーソル状態は **GraphPanelVM ごと**に所有（`graph_panel_vm.py:177-182` で `__init__` が
  4 フィールドを直接代入）。タブ同期は `propagate_cursor:286-293` が **A 時刻のみ** push。
  `GraphAreaVM._on_panel_change` は `"cursor"` のみルーティングし **`"delta"` は素通し**
  （`graph_area_vm.py:102-116`）。`add_panel`（:184）は種付けなし。
- **カーソルは render cache key に非包含**（`_make_cache_key:1383-1392` — x_range/width/
  visible_keys のみ）で、カーソル線は cache 外の InfiniteLine オーバーレイ。view は
  `"cursor"`/`"delta"` notify を線同期のみの軽量経路で処理し（`graph_panel_view.py:906-913`）、
  他タグは fallback `refresh()` でフル再レンダー。カーソル系 setter はキャッシュを触らない。
- `set_cursor_b` は delta を立てない half-set（UX-13/46）。notify 契約は `"delta"` 単発
  （`test_graph_panel_vm.py:1122-1133` が lock）。
- プレーン空白クリックは**カーソルを設置しない**（曲線非活性化＋軸解除のみ —
  `graph_panel_view.py:2004-2006`）。A の設置経路はメニュー toggle（表示範囲中央
  `_default_cursor_x:1087-1096` — **パネルの x_range 依存**）・線ドラッグ・時刻ダイアログ。
- **statusTip 機構**: `shell_actions.py:59`（全アクション）・`main_window.py:295` が statusTip を
  設定済みで、Qt はメニュー/ツールバー hover 時に QStatusTipEvent → **内部で
  `QStatusBar.showMessage`** を駆動する（src の showMessage を全廃しても発生）。
- `showMessage` 呼出は main_window 7 箇所＋`data_explorer_view.py:126` — 後者は
  **DataExplorerView（独立 QMainWindow・parent なし）自身の内蔵バー**であり本体バーとは別物。
  timeout 付きは 2 箇所（テーマ変更 8000ms `:780`・data_explorer 4000ms）。
- corner widget は「+」ボタン 1 個（`cornerWidget().objectName()=="new_tab_button"` を
  `test_graph_area_tab_ui.py:30-32` が lock・realgui `test_tab_ui_flow.py:104-107` は
  cornerWidget 中心を実クリック）。
- readout ヘッダは ● マーカー richtext（`test_header_markers_and_pane_use_tokens` が
  cursor_a/b.hex 包含を lock）・`cursor_a`/`cursor_b` トークンは**プロット面据え置き**
  （LIGHT も DARK 値 — 淡色でクローム明面上は不可視）。

## 2. 設計

### 2.1 共有 CursorState（タブ所有・オブジェクト共有 — UX-13/15/16 の構造根治）

```python
@dataclass
class CursorState:
    """タブ内全パネルが共有する計測カーソル状態（transient — 永続化しない）。
    既定値は本 dataclass が唯一持つ（レビュー blocker: __init__ 側の既定値代入は
    注入済み共有状態を巻き戻すため禁止）。"""
    cursor_t: float | None = None
    cursor_t_b: float | None = None
    delta_enabled: bool = False
    interp_method: InterpolationMethod = InterpolationMethod.LINEAR
```

- `GraphAreaVM._Tab` が `cursor_state: CursorState` を所有。タブ内全 GraphPanelVM は
  **同一オブジェクトを参照**（生成時注入・`add_panel` でも注入）。
- **GraphPanelVM 側の規定（レビュー blocker 反映）**:
  - `__init__` は 4 フィールドへ**書き込まない** — `self._cursor_state = injected or CursorState()`
    のみ（単独生成時は自前の state）。既存の直接代入 4 行（:177-182）は撤去。
  - 既存 4 フィールドは **property 化**して `_cursor_state` へ委譲（読み書き API・イベント名は
    不変 — R15-17 テスト資産の書換え最小化）。
  - `set_cursor_b(t)` は **`cursor_t is None` のとき no-op**（`toggle_delta` と同一ガード —
    「B requires A」不変条件の維持）。それ以外は `delta_enabled=True` を暗黙設定した上で
    **notify は従来どおり `"delta"` 単発**（既存 lock `:1122-1133` 維持）。
- **扇状配布は notify のみ・render cache 不変（確定事実: cursor は cache key 非包含 —
  `_invalidate_cache` は呼んではならない**。呼ぶとカーソル移動のたびタブ全 LOD キャッシュが
  無意味に全滅する perf 退行 — レビュー捕捉）。配布 notify は**発生源タグを保存**
  （`"cursor"`/`"delta"` — 他タグは view の fallback `refresh()` に落ちフル再レンダーになる）。
  `GraphAreaVM._on_panel_change` に **`"delta"` ルーティング分岐を新設**し、`"cursor"`/`"delta"`
  とも「タブ内他パネルへ同タグ notify を配布＋**area レベル `_notify("cursor")` を発火**」
  （§2.4 の即値更新に使う）。`propagate_cursor` の状態 push は不要になる（状態は共有済み）。

### 2.2 Analyze メニュー実装＋右クリック統一＋Shift+クリック（UX-04/24/37・v3 決定 3）

- **AnalysisActions ファクトリ（単一定義・DI — レビュー捕捉）**: 解析系 QAction 群
  （カーソル A・カーソル B（Δ）・カーソルを消す・補間方式 radio 群）の**生成関数を 1 箇所**に置き、
  - MainWindow はこれで生成した 1 セットを **Analyze メニュー**に掲載、
  - `GraphAreaView` 構築時に同セットを panel_factory 経由で `GraphPanelView` へ注入し
    **空白右クリックメニューは同一 QAction を共有**（checked/文言の乖離を構造防止）、
  - **未注入時（bare テストハーネス・単独構成）は同一ファクトリからローカル生成**
    （既存 headless/realgui のメニュー列挙 assert 群を壊さない）。
- **配線規定（レビュー blocker/important 反映）**:
  - 共有 checkable QAction の VM 変異は**全て `triggered` 配線**（programmatic `setChecked` では
    発火しない）。`toggled` 配線は**禁止** — aboutToShow / メニュー build 時の `setChecked` 同期が
    VM を変異させる（メニューを開くだけでカーソルが動く）ため。
    [[gui_qactiongroup_exclusive_radio_menu]] の適用範囲を全共有 checkable へ拡大。
  - 同期点: メニュー `aboutToShow`（Analyze）とコンテキストメニュー build 時に
    **アクティブパネルの状態から** checked/enabled を `setChecked` する。
  - **trigger 配送先**: Analyze メニュー経由=**アクティブタブのアクティブパネル**
    （既存 `_active_pvm_call` パターン — `toggle_main_cursor` の中央設置がパネル x_range 依存の
    ため「タブへ配送」では未確定）・コンテキストメニュー経由=**右クリックされたパネル**。
- **文言（レビュー捕捉: 虚偽 status tip の排除）**:
  - 「カーソル A」status tip=「表示範囲の中央に設置 / 解除」（クリック設置は存在しない —
    嘘のヒントを新設しない）
  - 「カーソル B（Δ）」status tip=「Shift+クリックで設置」・enabled=A あり
  - 「カーソルを消す」＝A/B 全消去。情報行「← / → サンプルステップ」（disabled 表示）。
  - 既存の「メインカーソル」「サブカーソル（Δ）」「サブカーソルを消す」等を
    **「カーソル A」「カーソル B（Δ）」語彙へ全面統一**（UX-37）。
- **Shift+クリック B 設置（新ジェスチャ — 優先規則をレビュー反映で確定）**:
  - **Shift 押下の左 press は ZONE_PLOT 全域で計測ジェスチャとして最優先** — 曲線ヒット
    （DP16 press 候補）・カーソル線 10px ヒット帯より先に分岐（B を A 線近傍や曲線上に置く典型
    操作が不発にならないため）。X/Y 軸ゾーンは対象外。
  - A 設置済み → `set_cursor_b(その時刻)`（暗黙 delta 込み）。**A 未設置 → A をその時刻に設置
    （B は置かない）**。非 Shift の既存意味論（活性化・解除・ドラッグ）は不変。

### 2.3 グリッド・Sync X = 右クリックのみ（v3 決定 4）

- 空白右クリックメニューに **「X軸同期（タブ内全パネル）」** checkable を新設（triggered 配線）。
  スコープはタブ — sync 状態の所有は現行どおり area 側とし、パネル view へは注入 callback
  （getter/setter）経由（GraphPanelView の area 非依存を維持・未注入時は項目非表示）。
- **タブ行の `sync_checkbox` を撤去**（`graph_area_view.py:120-121`）。グリッドは既存どおり。
- **corner widget コンテナ化**: 「+」と読み値トグルを横並びコンテナで `setCornerWidget`。
  **test-lock 追随（レビュー捕捉）**: `test_graph_area_tab_ui.py:30-32` の
  `cornerWidget().objectName()` assert → `findChild` による子ボタン検索へ・realgui
  `test_tab_ui_flow.py:104-107` は **`new_tab_button` 自体の矩形中心**を掴む形へ（コンテナ中心は
  ボタン境界に落ち実挙動を破壊する）。

### 2.4 ステータスバー刷新（v3 決定 2・増分D と整合）

- **左**: 即値ラベル群（`addWidget` — `A 100.035 s`／`B 149.865 s`／`Δt 49.830 s`・mono）。
  未設置分は空文字。
- **右**: メッセージラベル（`addPermanentWidget`）＋
  `MainWindow.set_status_message(text, timeout_ms=0)` ヘルパ（**timeout>0 で単発 QTimer
  自動クリア・再呼び出しで前タイマー破棄** — テーマ変更 :780 の 8000ms を引数で維持）。
- **`showMessage` の廃止スコープは MainWindow のバーに限定**（レビュー捕捉）:
  main_window.py の 7 箇所を `set_status_message` へ置換。
  **`data_explorer_view.py:126` は対象外**（DataExplorerView は独立 QMainWindow の自前バーで
  左即値と非干渉・現状維持 — grep ガードの allowlist に明記。
  `test_data_explorer_source_list.py:63` も無変更）。
- **statusTip 対策（レビュー blocker）**: Qt はメニュー/ツールバー hover の QStatusTipEvent を
  QMainWindow 既定処理で**内部的に showMessage へ流す**ため、src の全廃だけでは左即値が
  hover のたび隠れる。**`MainWindow.event()` で `QEvent.Type.StatusTip` を横取りして
  `set_status_message(tip)` へルーティングし、既定処理（一時メッセージ機構）へ通さない**。
  Layer B ガード: QStatusTipEvent を sendEvent → 左即値ラベルが隠れない＋右ラベルに tip が出る。
- **即値の更新経路（レビュー捕捉: CursorState は素の dataclass で購読不能）**:
  §2.1 の area レベル `_notify("cursor")` を MainWindow（または即値ウィジェット）が
  `graph_area_vm` 購読 1 本で受け、`"cursor"`/`"active"`/`"tabs"`/`"panels"` で
  **アクティブタブの CursorState を pull** して setText（既存 readout_changed fan-in と同型の
  pull 型・パネル個別購読の張り替え問題を回避）。Layer A: タブ切替で即値がそのタブの状態に
  入れ替わる。
- **配色（レビュー捕捉: LIGHT でプロット用 cursor トークンはクローム上不可視）**:
  新トークン **`chrome_cursor_a` / `chrome_cursor_b`** を新設 — DARK は既存 `cursor_a`/`cursor_b`
  と**同値の別役割**（値分岐テーマテスト必須 — 既存規約）・LIGHT は明面で AA を満たす濃色
  （実装時に実測選定・candidates: Latte yellow #df8e1d 系 / sapphire #209fb5 系）。Δt は
  `chrome_text`。トークン追加に伴う golden/エクスポート/カード再同期の波及は §3 に含める。

### 2.5 時刻書式の固定小数化（UX-14/48）

- カーソル時刻・Δt を `.4g` → **固定小数 3 桁** `f"{t:.3f} s"` へ。適用面: ステータス即値・
  readout ヘッダ・カーソル時刻ダイアログ初期値（:2481 `.6g`）。
  **意図的制限として記録**: サブ ms の Δt（線を 0.5ms 未満に近接配置）は `Δt 0.000 s` に丸まる
  （スナップ運用外のエッジ・許容）。`signal_preview_vm.py:56` 等の時間範囲表示は**対象外**（別途）。
- readout ヘッダは「`A 100.035 s ・ B 149.865 s（線形）`」へ（UX-48 — ● マーカー・─ 連結廃止。
  **A/B ラベル部分は cursor_a/cursor_b 色の richtext 着色を維持**〔readout ペインは暗面で可視〕—
  `test_header_markers_and_pane_use_tokens` は新書式へ追随・色 assert は維持）。

### 2.6 読み値ペイン 2 モード化（UX-22 部分/25/26/33・spec-B 案b supersede）

- **凡例モード**（カーソル未設置・信号あり）: 色スウォッチ＋信号名＋`[unit]` のみ。
  行クリック→曲線ハイライトは両モード共通。
- **計測モード**: `min–max` 融合 1 列 → **`min`/`max` 右揃え独立 2 列**＋列ヘッダ「（全区間）」
  （UX-25/33）。TSV コピーも列分離に追随。
- **信号ゼロ**: ペイン自動収納。**観測 API を定義**（レビュー捕捉）: `readout_stowed: bool`
  （収納中）を導入し、「トグル ON かつ収納中」の第 3 状態を `readout_visible()`（トグル状態）と
  分離。`show_placeholder("表示中の信号がありません")` の 3 呼出経路は収納へ置換
  （既存 assert の追随は §3）。「プロットをクリックしてカーソルを設置」プレースホルダは撤去
  （spec-B 案b supersede）。

### 2.7 凍結スクショへの波及（per-state — レビューで実測ベースに全面訂正）

canned スクリプトは 03 で set_cursor(3.0)+set_cursor_b(6.0) を設定後クリアしない（04/05/09 へ
残存）。01 は WelcomeView 表示で graph_area のバー行は写らない。

| 状態 | 期待差分 |
|---|---|
| 01_welcome | **ステータスバー構造のみ**（メッセージ右寄せ化） |
| 02_plotted | バー行消滅（Sync X 撤去）＋読み値トグル corner 化＋**readout 凡例モード**＋ステータスバー構造 |
| 03_cursor | 02 同（凡例除く）＋**Δ 表示化（B 線・A/B/Δ 列・統計列）**＋ヘッダ新書式＋**左即値 A/B/Δt 非空** |
| 04_grid / 05_affordances / 09_collapsed | **03 と同系**（カーソル残存のため Δ 表示＋即値非空を含む）＋各状態固有差分 |
| 06/07/08 | 不変 |

手順: dark/light 撮影 → 突合 → ベースライン昇格＋Ground Truth 再同期＋design.md 決定履歴
（supersede 2 件〔spec-B 案b・UX-32 View 案〕＋新トークン 2 個を含む）。

## 3. 挙動変更の一覧と test-lock 影響（レビューで全数補完済み）

| 変更 | 追随 |
|---|---|
| `__init__` の 4 フィールド代入撤去＋property 化 | 既存 R15-17 テストは API 互換で green 維持が要件。**新規必須: 値設定済みタブへ add_panel → 4 値不変**（レビュー blocker: この不変条件が無いと共有巻き戻しバグが全 green で通過する） |
| `set_cursor_b`: A 未設置 no-op＋暗黙 delta | half-set を lock する既存テストは無し（census 済み）。notify `"delta"` 単発契約（`test_graph_panel_vm.py:1122-1133`）維持 |
| `_on_panel_change` の `"delta"` ルーティング新設＋area `_notify("cursor")` | 新規 Layer A（B/Δ/補間変更のタブ内配布・area 通知） |
| 文言統一（メインカーソル/サブカーソル → カーソル A/B（Δ）） | grep `メインカーソル\|サブカーソル` 全数追随（headless＋**realgui `test_grid_realclick` / `test_graph_panel_menu_realclick` のメニュー項目列挙 assert**） |
| showMessage → set_status_message（**main_window 限定**） | `currentMessage\|showMessage` grep 追随（**allowlist: data_explorer_view.py:126 と test_data_explorer_source_list.py:63 は現状維持**）。同一文言 assert・タイムアウト 8000ms は引数で維持 |
| statusTip 横取り（`MainWindow.event()`） | 新規 Layer B（QStatusTipEvent sendEvent → 左即値不隠蔽＋右ラベル反映） |
| `sync_checkbox` 撤去 → 右クリック | `sync_checkbox` 依存テスト書換え（headless `test_x_sync.py` 系）。**X-sync realgui は存在しない（新設確定）** |
| corner コンテナ化 | `test_graph_area_tab_ui.py:30-32`（objectName → findChild）・realgui `test_tab_ui_flow.py:104-107`（new_tab_button 矩形中心へ） |
| readout ヘッダ新書式 | `test_header_markers_and_pane_use_tokens` の ● 前提を新書式へ（A/B ラベル着色 assert は維持） |
| プレースホルダ → 凡例モード＋信号ゼロ収納 | `show_placeholder` 3 経路・`readout_visible()`/`isVisible` assert（realgui `test_global_cursor.py:290` 含む）を `readout_stowed` 分離で追随・spec-B 案b 反転を supersede 記録 |
| `.4g` → `.3f`／min–max 2 列化 | 時刻書式・列数・TSV assert 追随 |
| 新トークン `chrome_cursor_a/b` | golden・値分岐（DARK 同値別役割 2 組）・エクスポート構造 assert・カード再同期 |
| 空白メニュー項目構成変更 | メニュー列挙 assert（headless＋realgui 上記 2 ファイル）追随 |

## 4. E2E 受け入れ（/gui-test-plan 分析）

### Task A: CursorState 共有化＋対称化（§2.1）
- A=必須: 同一オブジェクト共有・タブ独立・rebuild 後同一・**値設定→add_panel→4 値不変**・
  A 未設置 set_cursor_b no-op・暗黙 delta・`"delta"` 配布・area 通知／B=既存 R15-17 無回帰
  （property 互換証明）／C=既存カーソル realgui scoped 無回帰: `test_global_cursor.py`・
  `test_axis_menu_offset.py`（カーソル系）・`test_curve_direct_ops.py`。perf E2E 不要
  （fan-out は notify のみ・cache 不変を §2.1 で確定済み）。

### Task B: メニュー＋Shift+クリック（§2.2）
- A=ファクトリ単一定義・triggered 配線・配送先規定／B=**aboutToShow の setChecked 同期のみでは
  toggle_main_cursor/toggle_delta が呼ばれない**（レビュー捕捉の誤発火ガード）・共有 QAction の
  checked 同期・**曲線上/カーソル線 10px 内の Shift+クリックでも B 設置**（優先規則）／
- C=**必須 3 本のうち 2 本**: (i) 実 OS で Analyze メニュー→「カーソル A」実クリック→線消滅
  （UX-04 根治の実証）、(ii) Shift+実クリック B 設置 — honest RED=同座標の Shift なしクリックで
  B 非設置（対照）＋実装前 sabotage で不発実証。曲線上座標でも 1 ケース。
- 掴み点監査: 非 Shift 経路の既存 realgui scoped 無回帰（上記＋`test_grid_realclick.py`・
  `test_graph_panel_menu_realclick.py`）。

### Task C: Sync X/グリッド右クリック＋トグル整理（§2.3）
- A/B=メニュー項目・注入 callback・チェック状態／C=**必須 3 本目**: 実右クリック「X軸同期」ON →
  2 パネル実ズーム→追随の実測（**新設** — 既存 X-sync realgui は無い）。corner 化後の
  `test_tab_ui_flow` 追随＋読み値トグル実クリック無回帰。

### Task D: ステータスバー刷新（§2.4）
- A/B=set_status_message（timeout 意味論含む）・即値書式/空文字・**QStatusTipEvent 横取り**
  （sendEvent で左不隠蔽）・タブ切替で即値入替・新トークン golden/値分岐／
  描画 E2E=凍結 per-state（§2.7）。realgui 不要。

### Task E: 時刻書式＋readout 2 モード化（§2.5/2.6）
- A=書式・モード遷移（未設置=凡例/設置=計測/信号ゼロ=収納・`readout_stowed` API）・min/max
  2 列・TSV／B=構築済み view のモード切替／描画 E2E=凍結 03-05/09 の Δ 表示化を含む突合。

### 共通
- full pytest／ruff×2／mypy。①ゲート: フル realgui＋**新設 3 本**＋凍結 per-state（dark/light）→
  ベースライン昇格＋Ground Truth 再同期。

## 5. スコープ外

診断/通知センター・文言 OS（増分D）／読み値ペイン幅キャップ・スクロール（UXG-03/17/18）／
カーソル線ドラッグ・←/→ ステップ等の既存操作変更（維持）／`signal_preview` の時刻書式／
`.vsession`（増分F）。
