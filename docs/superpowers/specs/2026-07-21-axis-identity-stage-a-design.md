# 軸アイデンティティ契約 Stage A — critical 3 件（UX-01/02/03）根治 設計

- 日付: 2026-07-21（敵対的設計レビュー 29 指摘反映済み — blocker 2・important 17 を全て取込。
  ユーザー決定 2026-07-21: 複数波形の軸は**最初に登録された波形の情報を表示**〔混在マーカー不採用〕）
- 出典: [UIUX 敵対的レビュー課題カタログ](../../uiux-adversarial-review-catalog.md)（PR #134）の
  critical 3 件＋デザイン推奨2「軸アイデンティティ契約」の Stage A。
- 位置づけ: 独立バグ修正サブスペック。**増分E（比較データモデル・同名信号の自動重ね）の前提修正**
  — E は join を主動線化するため、Y 再フィット無しでは UX-03 を踏む。
- スコープ外: Stage B（軸ヘッダチップ・リージョン区切り・`[unit]` 表記統一）・Stage C（空状態の
  偽目盛廃止）・「単位混在の重ねを許すか」自体の判断（増分E と併せて確定）。

## 1. 課題（根因確認済み・2026-07-21 main@f6792d0）

| ID | 症状 | 根因 |
|---|---|---|
| UX-01 | 軸ラベルが「最初の信号名＋最後に追加した信号の単位」の捏造ペア（`VehSpdInternal (Nm)`）。削除後も残存名（UXG-19） | `graph_panel_vm.py:261-271` — `axis.name` は first-wins・`axis.unit` は無条件上書き（last-wins）の非対称。増分更新のみで再計算なし。unit last-wins を lock するテストは存在しない（意図しない実装の傍証。`overwrite_axis:285-297` は name/unit を対でクリア＝作者意図は「代表信号のペア」） |
| UX-02 | 曲線右クリック「新しい軸へ移動」で曲線が 0–1 デフォルトレンジ・無ラベルの新軸に落ちて画面から消える | `move_entry_to_new_axis:718-740` — 新 `YAxisVM` を `y_range=None`/`name=""`/`unit=""` で生成し `_auto_fit_ranges` 非呼出・ラベル非伝搬。view は `y_range None` の軸に `setYRange` せず（`graph_panel_view.py:973-978`）、全 ViewBox `disableAutoRange()` のため pyqtgraph 既定 0..1 に留まる。spec DP17「D&D 新軸と同一 VM 経路」と実装が矛盾する見落としバグ |
| UX-03 | 同一Y軸へ後から追加した信号がレンジ再計算されず、スケールが違うと可視チェックONのまま 1px も描かれない。レンジ外の手掛かりゼロ | `_auto_fit_ranges:1332-1351` の `if axis.y_range is None:` ゲート — `_fit_axis` が初回 add で具体値を格納した後は恒久的に再フィット不能。RN-02 の auto フラグ（`_x_range_is_auto`）は X のみで Y 版が無い。`add_signal` docstring（:241-242「y_range も union にフィット」）と実装が乖離 |

## 2. 契約（このスペックが導入する不変条件）

**軸に表示される名前・単位・範囲は常に現状の真実である。**

1. **name** = 軸に現存する最古（追加順）エントリ＝**代表波形**の信号表示名。代表が削除・
   アンロードされたら次の現存エントリへ交代する（残存名の放置を許さない — **VM 値だけでなく
   画面のラベルも**）。
2. **unit** = **代表波形の単位**（name と常に同一信号のペア — 捏造ペアの根絶）。単位が混在して
   いても代表の単位を表示する（**ユーザー決定 2026-07-21**: 「一つの軸に複数波形が存在する時は
   1番最初に登録された波形の情報を表示する」— 混在マーカーは不採用。混在の可視化が必要に
   なったら Stage B の軸ヘッダチップで再訪）。代表の単位が空なら単位表示なし。
3. **y_range** = 軸ごとの auto フラグが立っている間、**可視**エントリの整列ビュー値域の
   和集合に常時追従する（X の RN-02 と対称）。手動設定後は尊重し、代わりに
   **現 X 窓内で 1px も描かれない可視曲線があることをオフスケールバッジで通知**する
   （「無言の不可視」の根絶）。
4. 上記はエントリ集合・軸割当・可視性を変異させる**全経路**で成立する（§3.7 の全数表 —
   経路ごとの挙動差を残さない）。

## 3. 設計

### 3.1 YAxisVM — `y_is_auto` フラグ

```python
class YAxisVM(Observable):
    def __init__(self, ..., y_is_auto: bool = True): ...
```

- `y_is_auto`: 既定 True。`_x_range_is_auto`（`graph_panel_vm.py:167/625/759`）の per-axis 対称。
- **注意（レビュー捕捉）**: auto=False への遷移を `YAxisVM.set_range` や `_fit_axis` に置いては
  ならない — auto フィット自身が同じ funnel を通るため、初回フィットでフラグが折れて
  「恒久 manual」＝UX-03 の None ゲートと同型が再発する。遷移は GraphPanelVM の
  **手動系メソッド側**（§3.3）にのみ置く。

### 3.2 ラベル再計算 `_recalc_axis_labels()`（増分更新の廃止）

first-wins/last-wins の増分更新（`add_signal_to_axis:261-271`）と `overwrite_axis` の手動クリアを
**削除**し、単一の再計算に置換する:

```
for 各 axis:
    entries = 軸上の現存エントリ（_plotted の追加順）
    rep = entries[0] if entries else None   # 代表波形（ユーザー決定 2026-07-21）
    axis.name = rep の表示名（signal_key.split("::")[-1]）if rep else ""
    axis.unit = rep の unit（sig.metadata.get("unit", "")）if rep else ""
```

name と unit は**常に代表波形の対**として一括更新する（別信号からの合成 = UX-01 の根因を
構造的に不可能にする）。

- 呼出点は §3.7 の全数表に従う（**各変異メソッドの末尾＝`_notify` 直前で全軸一括再計算** —
  O(plotted)・エントリ数十本規模で無視できる。`_compact_axes` 内へのフックは
  toggle 系〔compact 非経由〕を取りこぼすため採らない）。
- **view（レビュー捕捉: setLabel は 2 サイト）**: `graph_panel_view.py` の
  fast path（`:1068-1075` — 構造署名不変時。**Ctrl+join・同一軸内削除という UX-01 の主経路は
  こちらを通る**）と rebuild（`:1195-1196`）の両方を、共有ヘルパ
  `_apply_axis_label(axis_item, axis_vm)` に抽出して置換する:
  - 通常 → `setLabel(text=name, units=unit or None)`（代表波形の対）
  - name/unit とも空 → **明示クリア**（`setLabel(text="", units=None)` または
    `showLabel(False)`）。現行の `if axis_vm.name or axis_vm.unit:` ガードは「空への遷移」で
    setLabel を呼ばず、全エントリ削除→placeholder 化（配置署名不変→fast path）で
    **画面に死んだ信号のラベルが残存**する — 契約 §2.1 の view 層違反（blocker）。

### 3.3 Y 和集合フィット（UX-03）

`_auto_fit_ranges` の Y 部ゲートを `if axis.y_range is None:` → `if axis.y_is_auto:` に変更。

- **フィット対象は「可視エントリ・整列ビュー（sorted_view）・有限値のみ」**で
  `reset_axis_y:673-707` と完全に同一規則にし、共有ヘルパへ抽出する（現行 `_auto_fit_ranges` は
  可視性を見ておらず `reset_axis_y` と矛盾している — 統一自体が挙動変更、§4）。
  `add_signal` docstring（:241-242）の「union of all plotted signals」も visible-only へ追随させる。
- auto フラグ遷移:
  - **False にする**: `set_axis_range`（`graph_panel_vm.py:635` — 軸メニュー範囲指定
    `view:2477`・アクティブ軸ズーム drag `view:595`・パン drag `view:600`・`zoom_axis:642-652`
    〔軸メニュー「ズームイン/ズームアウト」FU-09〕の**全手動経路がこの 1 メソッドに集約**。
    レビューで y_range を書く経路の全数が `set_axis_range` / `set_y_range:629` /
    レガシー `y_range` プロパティ setter `:209-212` / `_fit_axis` のみと確認済み）・
    `set_y_range`・レガシー `y_range` setter。
  - **True に戻す＋即フィット**: `reset_axis_y` / `reset_y`（「この軸をオートフィット」）。
  - `set_range(None, None)` の「None=クリア」挙動は維持（既存 test-lock:
    `test_graph_panel_vm.py:849-860`・`test_context_menus.py:207-215`）。auto なら直後の
    `_auto_fit_ranges` が再取得する。
- 再フィットのトリガ: §3.7 の全数表（可視性トグルは **entry 版と axis 版の両方** — H キーの
  軸フォールバック `toggle_axis_visibility:600-613`／`view:1956` を含む。含めないと
  「H×2 往復で UX-03 が再発」する — レビュー捕捉）。
- **perf（レビュー捕捉: オフセット枝で「エントリ有界」根拠が崩れる）**: `_signal_map` は
  オフセット適用中、全チャンネル overlay 再構築＋`apply_offset` の Signal 再生成
  （sorted_view キャッシュ喪失）を毎回行う。実装指針:
  (a) ラベル再計算は unit のみ必要でオフセット非依存 → `session.signal_map()` の fast path を
  直接使う。(b) Y フィットは values のみでオフセット不変 → **base 信号（オフセット非適用）で
  計算**する（X フィットのみオフセットが要る）。これによりフィット/再計算コストは
  プロット済みエントリ有界・チャンネル総数（prod 330k）非依存を維持する。
  perf E2E は不要のままとするが、①ゲートの realgui 手順に「quick/hils 実データで
  追加・可視性トグル連打（オフセット適用中含む）の体感確認」を 1 行含める。

### 3.4 move_entry_to_new_axis の同経路化（UX-02）

`:718-740` の末尾（`_compact_axes` / `_relayout_columns` 後）に §3.2 の再計算＋
`_auto_fit_ranges` を追加。新軸は `y_is_auto=True` で生まれるため即フィットされ、
移動元軸も auto なら残存エントリへ再フィット・ラベル再計算される。既存 assert
（axis_index 再割当・compact・cache-bust — `test_graph_panel_multi_axis.py:1349-1390`）は不変。

### 3.5 内容総入替時のレンジリセット（挙動変更・2 経路で対）

「内容が丸ごと入れ替わった軸の手動レンジは旧内容に紐づく情報であり無意味」を 2 経路に適用:

1. **`overwrite_axis`**（plain ドロップ）: `y_range=None`・`y_is_auto=True` にリセットしてから
   再追加（現行は y_range 温存で「唯一の新信号すら不可視」になりうる — UX-03 検証所見。
   温存を assert する既存テストは無い）。
2. **`_compact_axes` の placeholder 化**（全エントリ削除で `axes[0]` オブジェクトを温存する分岐
   `:424-429`）: 同様に `y_range=None`・`y_is_auto=True`・name/unit クリア。
   これが無いと「手動ズーム→全削除→新規追加」で空パネルの 1 本目が旧手動レンジ上に載って
   不可視になり、§3.5-1 と非対称の穴が残る（レビュー捕捉・important）。

### 3.6 オフスケールバッジ（view・UX-03 の手動レンジ側）

- **表示条件**: 軸が手動（`y_is_auto=False`）かつ、可視エントリのうち
  **render と同一の X 窓スライス（RN-01 の境界サンプル取込を含む）内の有限値域**が現
  `y_range` と交差しない（=現画面に 1px も描かれない）ものが存在するとき。上外れ=▲・
  下外れ=▼（両方あれば両方）。判定域を全信号値域にすると「窓内だけ範囲外」を見逃し
  「窓内は可視なのに大域で外」を誤点灯する（レビュー捕捉）。
  - X 窓内にサンプルが無いエントリ・有限値を 1 つも持たないエントリ（全 NaN — どのレンジ
    でも描画不能 [[pyqtgraph_drops_non_finite_vertices]]）は**判定対象外**（バッジは
    「フィットすれば見える」ときだけ真実）。
  - 部分クリップは対象外（レンジ内に手掛かりが残るため・ノイズ抑制）。
- **配置（列非依存 — レビュー捕捉）**: 「スパイン右縁のプロット側」は外側列（column 0）では
  隣列のガター帯（別軸の掴み点）に重なり成立しない。**当該軸リージオン内・プロット矩形
  （全列ガターの右）の左縁の上端/下端**に置く。高さが閾値未満の短小リージョンは▲▼を
  片側（外れ方向優先）に集約。scene item（クリック可能）・Z 値は曲線より上に明示。
- **クリック** = `reset_axis_y(axis_index)`（既存 API・auto 復帰＋フィット）。バッジが press を
  **accept してプロット内クリックの既存意味論（R15 カーソル設置・曲線活性化・DP16 press
  候補）に食われない/誤発火させない**ことを仕様とする。ホバーで
  ツールチップ「レンジ外の曲線あり — クリックでフィット」（誤クリック＝手動レンジ破棄の
  リスクを affordance で緩和。Undo は UXG-22 で別途）。
- **色**: `accent_active`（既存トークン・新設なし）。警告系 amber の意味論は増分0
  「知覚の床」のトークン整理で再訪する（本 spec では既存語彙に留める）。
- **更新タイミング**: signals / axes / range（X レンジ変更＝ズーム/パン/X-sync 含む）の
  変異イベント後の再描画パスで再評価。cursor / offsets のドラッグ中イベントでは再評価しない
  （新規タイマー等は導入しない）。

### 3.7 変異トリガ全数表（契約 §2.4 の「全経路」の定義）

「`_plotted` の集合・`axis_index` 割当・`visible` を変異させる全メソッド」の末尾
（`_notify` 直前）で、ラベル再計算（§3.2）＋auto 軸再フィット（§3.3）を行う:

| メソッド | 変異 | 備考 |
|---|---|---|
| `add_signal_to_axis`（`add_signal`/`overwrite_axis` 経由含む） | 追加 | |
| `overwrite_axis` | 総入替 | §3.5-1 のリセット後に add へ委譲（二重再計算は冪等・可） |
| `move_entry_to_new_axis` | 軸割当 | §3.4 |
| `remove_entry` / `remove_axis` | 削除 | `_compact_axes` の placeholder 化は §3.5-2 |
| `remove_signal`（legacy・src 内呼出なし） | 削除 | **同処置**（dead-path 扱いにせず一貫させる — テスト経由の利用があるため） |
| `prune_missing_signals:494-514` | 削除（**ファイルアンロード** — `graph_area_vm.py:67` から全パネル配送） | 漏らすと UXG-19（残存名）がアンロード経路で再発（レビュー捕捉・blocker 構成要素） |
| `extract_axis` / `insert_axis`（クロスパネル軸移動 — `graph_area_vm.py:256/260`） | 軸移送 | YAxisVM はオブジェクトごと移送（`y_is_auto` も運ばれる）。挿入先で再計算＋auto なら即フィット。抽出元は既存の compact 経路 |
| `toggle_entry_visibility` | 可視性（曲線単位） | auto 軸のみ再フィット |
| `toggle_axis_visibility:600-613` | 可視性（軸一括 — H キー軸フォールバック `view:1956`） | 同上（漏らすと H×2 往復で UX-03 再発） |
| `toggle_visibility:557-564`（legacy・src 内呼出なし） | 可視性 | **同処置** |

## 4. 挙動変更の一覧と test-lock 影響（走査済み）

| 変更 | 影響 | 対応 |
|---|---|---|
| unit last-wins → **代表波形（最古エントリ）の対表示**（ユーザー決定 2026-07-21） | **RED になる既存テストなし**（last-wins は untested）。`test_graph_panel_multi_axis.py:450-471` は同一 unit のため green のまま | 異単位 join でも代表 unit 維持・代表交代（削除/アンロード後）で name/unit が**対で**交代・全削除で両方空、の新規 Layer A/B lock を追加 |
| auto 和集合フィットの可視性除外（`reset_axis_y` と統一） | 現行 `_auto_fit_ranges` は不可視エントリも含めてフィット → 統一で初回フィット値が変わるケースあり | 新規則を test-lock（旧規則の lock は無い） |
| 可視性トグル（entry/axis 両方）が auto 軸をフィットし直す | 新挙動（トグルでレンジが動く）。全エントリ非表示 → フィット対象空 → `set_range(None, None)` でクリア（auto のまま・再表示で再フィット） | 意図を spec 明記＋test-lock。手動軸は不変 |
| `overwrite_axis`・placeholder 化のレンジ/フラグリセット | 温存 assert 無し（`test_graph_panel_multi_axis.py:664-670`・realgui H2 は signal keys のみ） | 新挙動を test-lock（§3.5 の 2 経路とも） |
| reset 系の None クリア | 維持（既存 lock: `test_graph_panel_vm.py:849-860` 等） | 変更しない |
| 並行記述の追随 | `tests/realgui/test_axis_menu_offset.py:210-218` docstring が「None の間のみフィット」前提（assert は union でも green） | docstring 更新（memory `gui_behavior_change_stale_parallel_realgui_test`） |
| `add_signal` docstring :241-242 | visible-only union と一致するよう文言更新 | 乖離解消＋新規則へ追随 |

## 5. E2E 受け入れ（/gui-test-plan 分析ブロック）

### Task 1: UX-01 ラベル契約（name/unit 再計算）
- **変更種別**: VM/純ロジック＋ウィジェット状態（ラベル文字列）
- **触れるユーザージャーニー**: プロット→解析（多信号を軸に載せ単位を読む・削除して読み直す・ファイルを閉じる）
- **E2E 受け入れ**:
  - 異単位 join でも軸ラベルが代表波形の対のまま: E2E タイプ=入力経路(realgui) / 実 observable=
    実 OS 操作（Ctrl+ドロップ join）後の `labelText`=代表名・`labelUnits`=**代表（1本目）の
    unit** assert（現行 last-wins は 2 本目の unit を表示 → honest Red）＋スクショ目視 /
    **prod スケール不要**（ラベル文字列はデータ規模非依存） /
    実経路=既存 D&D realgui（H3 join）へ assert 追加。**前提: fixture の 2 信号へ相異なる非空
    unit を session ロード後に注入**（`test_graph_panel_multi_axis.py:458-461` の
    `sig.metadata["unit"]` 注入パターン — 現行 fixture は unit 無し CSV のため注入なしでは
    first-wins/last-wins を弁別できない・レビュー捕捉）
  - 代表削除/アンロードで名前が交代・全削除で画面ラベルも消える: Layer A/B
- **必要レイヤー**: A=必須（再計算規則: 同単位/異単位でも代表の対/代表 unit 空/代表交代で
  対交代/アンロード（prune）で交代/全削除で両方空）/ B=**必須＋経路指定**（`labelText`/`labelUnits` を
  **構造不変経路（構築済み view への join → fast path :1068-1075）と構造変更経路（新軸作成 →
  rebuild :1195-1196）の両方**で assert。fresh 構築のみの assert は fast path を exercise せず
  false-green — memory `gui_diff_update_layout_key_must_cover_unrewritten_fields` 同型。
  「全エントリ削除後 labelText 空」も Layer B 必須）/
  C=要（join 実配送は D&D＝合成再現不可のため既存 realgui へ assert 追加）/ perf=不要 /
  描画=不要（ラベルは `labelText` が実 observable）
- **受け入れ要件**: Red=「unit V + unit A を join → labelUnits == "V"（現行は "A"=last-wins で
  fail）」「代表削除→ name/unit が次エントリの対へ」「全削除→画面ラベル空」が現行実装で
  fail することを確認 / Green=§3.2 /
  Verify=quick_demo で VehSpd(km/h)+EngTrq(Nm) を同軸に載せ、軸ラベルが
  「VehSpdInternal (km/h)」のまま（Nm に化けない）こと・VehSpd 削除で「EngTrq (Nm)」へ対で
  交代すること・ファイルを閉じてラベルが残らないことを目視
- **②実質性**: labelText/labelUnits=自動アサート可。スクショは補助目視
- **①証拠ゲート**: `- [ ] uv run pytest --realgui tests/realgui/test_signal_dnd_realclick.py`（join 系 scoped）＋証拠添付

### Task 2: UX-02 新軸移動の fit＋ラベル
- **変更種別**: VM＋描画の正しさ（移動した曲線が見える）
- **触れるユーザージャーニー**: 解析（多軸分配）
- **E2E 受け入れ**:
  - 移動直後に曲線が新軸リージョンに見える: E2E タイプ=入力経路(realgui)＋描画 /
    実 observable=既存 `tests/realgui/test_axis_menu_offset.py:410-443`
    `test_real_curve_menu_move_to_new_axis`（実右クリック→実項目クリック）へ
    「新軸 `y_range` が移動信号の値域へフィット」「`labelText`=移動信号名」assert 追加＋
    FU-12 型 `grabWindow` ピクセル走査。**前提: fixture（`_two_curve_one_axis_panel` —
    現行 a=0→1・b=1→0）の片方を 0..1 に収まらない値域（例 -5..5）へ変更**する — 現行値域は
    pyqtgraph 既定レンジ 0..1 と一致し、バグのままでもピクセルが出て Red にならない
    （レビュー捕捉。変更しない場合ピクセル assert は装飾にすぎない） /
    **prod スケール不要**（レンジ計算はエントリ有界・描画確認は値域の代表ケースで成立） /
    実経路=既存実 OS メニュー駆動をそのまま再利用
- **必要レイヤー**: A=必須（fit・ラベル・移動元再計算）/ B=要（メニュー trigger→VM 経路は既存
  `test_graph_panel_view.py` 型）/ C=要（上記既存テスト拡張）/ perf=不要 /
  描画 E2E=要（「見かけ上のデータ消失」が主訴のため、ピクセル存在が実 observable）
- **受け入れ要件**: Red=移動後 `new_axis.y_range is None`（現行）＋fixture 値域変更後の
  ピクセル 0 件を新 assert が fail で捕捉 / Green=§3.4 / Verify=quick_demo で 0..1 に収まらない
  信号（YawRate 等）を「新しい軸へ移動」→曲線が消えずラベル付き新リージョンに現れることを目視
- **②実質性**: y_range 数値・labelText=自動アサート。曲線可視=ピクセル走査（FU-12 前例）
- **①証拠ゲート**: `- [ ] uv run pytest --realgui tests/realgui/test_axis_menu_offset.py`＋証拠添付

### Task 3: UX-03 auto 和集合フィット＋オフスケールバッジ
- **変更種別**: VM＋ウィジェット構成（バッジ新設）＋入力イベント（バッジクリック）＋描画
- **触れるユーザージャーニー**: ブラウズ→プロット（2本目以降の追加）→解析（手動ズーム後の追加・H トグル・ファイル閉じ）
- **E2E 受け入れ**:
  - auto 軸への追加で両曲線が見える: E2E タイプ=描画 / 実 observable=FU-12 型ピクセル走査
    （スケール乖離 2 信号を同軸 add → 両方の色ピクセルが存在。現行 main では 2 本目が 0 件＝
    Red が実バグを再現） / **prod スケール不要**（§3.3 のとおりエントリ有界。ただし①ゲートで
    quick/hils 実データの体感確認を実施 — オフセット適用中の連打含む） /
    実経路=「Add to Active Panel」実クリック（既存 realgui パターン）
  - 手動レンジ×レンジ外曲線でバッジが出る・クリックで復帰: E2E タイプ=入力経路(realgui) /
    実 observable=実 OS クリックでバッジ命中 → `axes[i].y_range` が和集合値へ（before/after
    数値 assert — `test_axis_menu_offset.py:462-503` の雛形）＋バッジ出現/非出現のピクセル走査
    （overlay/scene item の `isVisible` は嘘プロキシ — memory
    `gui_overlay_sibling_zorder_sinks_behind_later_children` 同型） /
    prod スケール不要 / 実経路=実ズーム（手動化）→実追加→実バッジクリック
- **必要レイヤー**: A=必須（フラグ遷移全表〔§3.7 の全メソッド — H 軸トグル・prune・
  extract/insert 含む〕・和集合規則・§3.5 の 2 リセット・バッジ表示条件の純関数
  〔X 窓判定・全 NaN 除外・窓内サンプル無し除外〕）/
  B=要（バッジ item クリック→`reset_axis_y` を scene 直駆動）/
  C=**必須**（バッジの実クリック到達＝hit-test/z-order は Layer C 専用）/ perf=不要（根拠 §3.3・
  ①ゲート体感確認で補完）/ 描画 E2E=要（不可視バグの根治証明はピクセルのみが honest）
- **受け入れ要件**: Red=(1) スケール乖離 add 後 2 本目のピクセル 0 件（現行）(2) 手動化後の
  レンジ外 add でバッジ item 不在 / Green=§3.3+§3.5+§3.6 / Verify=quick_demo で EngineSpeed 系＋
  小振幅信号を同軸に足し両方見える・ズーム後に足すとバッジが出てクリックで全体が見える・
  H×2 往復後も全曲線が見える
- **②実質性**: y_range 数値・フラグ=自動アサート（Layer A）。可視/バッジ出現=ピクセル走査。
  realgui は「実クリック→レンジ復帰」の before/after を assert（VM 再チェックのみは naive）
- **①証拠ゲート**: `- [ ] uv run pytest --realgui tests/realgui/test_offscale_badge.py`（新設）＋証拠添付
- **realgui 掴み点監査**（クリック可能ゾーン新設のため必須 — **対象はプロット内クリック意味論**。
  レビュー捕捉: 既存ガター掴み点〔スパイン中心/FRAME 帯/grip 帯/zoom・pan ゾーン〕は axis
  item-local 座標でプロット側バッジと構造的に交差しない）: バッジ矩形と R15 プロット内
  クリック＝カーソル設置・曲線ヒット（CURVE_HIT_TOL_PX）・カーソル線（CURSOR_LINE_HIT_PX）・
  DP16 press 候補の非干渉（バッジが accept して勝つ仕様の実証）を確認し、
  `tests/realgui/test_global_cursor.py`・`test_curve_direct_ops.py`・
  `test_axis_menu_offset.py` を scoped 無回帰実行
- **honest layering note**: バッジ `isVisible()` は画面到達の証拠にならない（scene item の
  z-order 沈没・領域外配置を見逃す）。出現/非出現の証明はピクセル走査で行う

### 凍結スクショへの影響（レビュー捕捉で反転 — 「不変」ではなく「意図的差分が確定」）

撮影 fixture（`capture_ui_screenshots.py:26-31/139-143`）は EngineSpeed（800..2275）と
VehSpd（0..118.8）を**同一軸0へ join**しており、現行ベースラインの 02-05 は「軸 800–2275・
VehSpd 不可視」＝**UX-03 の症状そのものを写している**。和集合フィット化で軸は約 [0,2275] へ
変わり、`02_plotted`/`03_cursor`/`04_grid`/`05_affordances`（＋カタログ `09_collapsed`・light
系統・Ground Truth カード）は**必ず意図的差分になる**（VehSpd の初可視化＝UX-03 根治の実証画像）。

- merge 前手順: (a) 前後スクショ目視で差分が「軸レンジ変化＋VehSpd 出現（＋それに伴う目盛/
  曲線形状）」のみであることを確認 → (b) dark/light 両テーマのベースライン更新 →
  (c) Ground Truth カード再生成と claude.ai/design 再同期（docs/design.md 運用ループ手順4-5）。
- **不変を実証する対象は `01_welcome`・`06`/`07`/`08`（ダイアログ/プレビュー）のみ**。

## 6. 実装順序（writing-plans への引き継ぎ）

1. YAxisVM フラグ＋`_recalc_axis_labels`＋和集合フィット＋§3.7 全経路接続＋§3.5 リセット
   （VM 一式・Layer A 群）
2. view ラベル共有ヘルパ（2 サイト＋空クリア）＋ Layer B（fast path 経路必須）
3. 既存 realgui 拡張（Task 1 unit 注入・Task 2 fixture 値域変更＋assert）
4. オフスケールバッジ（view item＋クリック）＋新設 realgui（Task 3 の C）＋プロット内
   クリック意味論の非干渉監査
5. 凍結ベースライン更新（dark/light・Ground Truth 再同期）・docstring 追随・full ゲート・
   ①ゲート体感確認（オフセット適用中の連打含む）

**第1弾 PR への同梱物**（ユーザー指示）: CLAUDE.md「Phase 状況」への UIUX 敵対的レビュー行の
追加＋docs/roadmap.md へのカタログポインタ追記。
