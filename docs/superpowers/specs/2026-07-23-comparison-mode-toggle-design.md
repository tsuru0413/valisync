# 比較モードのユーザー切り替え（E-2 拡張）設計

> **出典**: E-0＋E-2 比較データモデル（[e2-comparison-model spec](2026-07-23-e2-comparison-model-design.md)）の追補。
> ユーザー決定（2026-07-23）で、比較モードの起動を「ファイル数 ≥ 2 の自動判定」から
> 「ユーザーが Analyze メニューで明示的に切り替えるフラグ」へ変更する。**同一ブランチ
> `feature/e2-comparison-model`（PR #145・未マージ）へ畳んで一つのまとまりとして出荷**する
> — 自動比較を出荷して直後に振る舞いを変えるカタログ churn を避けるため。
>
> **改訂履歴**: 初版を 8 レンズ敵対的レビュー（34 findings・33 confirmed=全 Minor）で検証し、
> M1-M16 を反映（永続化→transient 化・QAction 配置是正・§8 カタログ前提の誤り訂正・テスト計画精緻化）。

## Goal

シングルモード（従来 count-mod 色・比較 affordance なし）と比較モード（ファイル=色相ファミリー・
◎基準バッジ・同名重ね）を、**ユーザーが明示的に切り替えられる**ようにする。既定はシングル。
1 ファイル運用は完全従来互換のまま。

## ユーザー決定（確定・覆さない）

1. **既定モード=シングル**（比較は明示オプトイン）。2 ファイルをロードしても、ユーザーが
   比較モードを ON にするまで count-mod 色のまま。
2. **切り替え UI=Analyze メニュー**（checkable 項目）。
3. **OFF 遷移=色相ファミリー色のまま固定**（count-mod へ戻さない）。手動ピン色は常に不変。

## §1 モードフラグ（AppViewModel）

現行 `is_comparison_mode()`（[app_viewmodel.py:261-269](../../../src/valisync/gui/viewmodels/app_viewmodel.py)）は
`len(self._loaded_keys) >= 2` の自動判定。これを**明示フラグ＋「比較対象が 2 つ以上ある」ガードの積**へ置換する。

### 状態（transient）

- 新規フィールド `self._comparison_enabled: bool = False`（既定 OFF）。
- **transient（非永続）** — `reference_file_key` と同じくセッション内の一時状態とし、QSettings へ
  永続しない（M1）。理由: (a) reference は将来 `.vsession`（増分F）へ入る transient であり、比較フラグを
  グローバル永続すると**スコープ不整合**、(b) 永続すると「別データセットで次に 2 ファイル目をロードした
  瞬間に家系色/バッジが無言で自動発火」するクロスセッション帰結、(c) セッション復元が未実装の現状で
  永続の実利益はほぼゼロ。アプリ再起動で常に既定シングルへ戻る（＝明示オプトインをセッションごとに行う）。
  比較状態の真実面（inspect/`.vsession`）の確定は増分F で行う。

### 述語（唯一の真実 — 全 consumer が読む単一点）

```python
def is_comparison_mode(self) -> bool:
    """True when the user has enabled comparison mode AND 2+ files are loaded.

    The `>= 2` guard preserves the invariant that a single loaded file always
    looks single (frozen 1-file catalogue is mode-independent); the flag makes
    comparison an explicit opt-in (spec §1, user decision 1). A 2nd file
    arriving while the flag is already ON auto-applies families via the
    "loaded" reapply wiring (§4).
    """
    return self._comparison_enabled and len(self._loaded_keys) >= 2
```

**根拠**: フラグ単独だと「1 ファイル＋比較 ON」で単一ファイルへ家系色（palette[0] のバリアント）が
付き、1 ファイル凍結カタログを壊す。`and len >= 2` で「1 ファイルは常にシングル」を保証しつつ、
フラグをユーザー制御点にする。`file_hue_resolver`/バッジ/チップ/FileBrowserVM は全て
`is_comparison_mode()` を読むため、この 1 箇所の変更で全 consumer が追従する（重複判定なし）。

### 変異 API＋通知

```python
def set_comparison_mode(self, enabled: bool) -> None:
    """Enable/disable comparison mode; notify 'comparison_mode' on change.

    No-op (no notify) when already in the requested state — mirrors
    set_reference_file's same-value guard.
    """
    if enabled == self._comparison_enabled:
        return
    self._comparison_enabled = enabled
    self._notify("comparison_mode")

@property
def comparison_enabled(self) -> bool:
    """The raw user flag (independent of file count) — for the menu checkstate.
    Distinct from is_comparison_mode(), which ANDs in the 2-file guard."""
    return self._comparison_enabled
```

- **`comparison_enabled`（生フラグ）と `is_comparison_mode()`（フラグ AND ≥2）を区別**する。
  メニューのチェック状態は生フラグ、色/バッジの発火は `is_comparison_mode()`。この使い分けの
  取り違え（メニューへ AND 述語を使う／色へ生フラグを使う）を sabotage で固定する（§7 T-B1）。

### introspection（M2）

- `inspect()`/状態スナップショット（[app_viewmodel.py:322付近](../../../src/valisync/gui/viewmodels/app_viewmodel.py)）へ
  `'comparison_enabled': self._comparison_enabled` を `reference_file` と同層で追加する。フラグ化後は
  `loaded_keys` から再構成不能なため、headless/AI introspection で可視化しないと真に不可視になる。

### register_loaded の docstring 更新（M3）

- `register_loaded`（[app_viewmodel.py:245-259](../../../src/valisync/gui/viewmodels/app_viewmodel.py)）の docstring
  中の「2nd file's load flips is_comparison_mode() true」は既定 OFF で **stale** 化する。実装タスクで
  「比較モードの発火は 2 ファイル目ロードではなく、トグル/フラグ ON（かつ ≥2 ファイル）時に起きる」旨へ
  更新する（実装者が名前/色配線を誤ってフラグゲート述語へ結合させないため）。

## §2 UI: Analyze メニューの checkable 項目

Analyze メニュー（[main_window.py:361](../../../src/valisync/gui/views/main_window.py)）に checkable
「比較モード」QAction を追加する。

### 配置（M4 — 是正）

- **`comparison_mode` は panel-scoped な `AnalysisActions`／`_sync_analysis_actions(pvm)` に載せない。**
  それらは各パネル（GraphPanelVM）に束縛され、bare パネルごとに QAction を量産し、app_vm 由来の
  triggered/checked/enabled を同期できず factory 汚染を招く。
- **MainWindow 所有の独立した checkable QAction** とする:
  - `setCheckable(True)`。`analyze_menu.addAction(...)` で追加（cursor 群とはセパレータで区切る）。
  - `triggered` → `app_vm.set_comparison_mode(checked)`（`toggled` ではなく `triggered` で VM 変異 —
    memory [[gui_qactiongroup_exclusive_radio_menu]] の思想）。
  - `checked`/`enabled` の同期は既存の `_sync_analysis_actions`（`aboutToShow`・
    [main_window.py:374](../../../src/valisync/gui/views/main_window.py)）内で **app_vm を直読**して行う
    （panel VM 経由でなく）:
    - `setChecked(app_vm.comparison_enabled)`（生フラグ）
    - `setEnabled(len(app_vm.loaded_file_keys) >= 2)`（2 ファイル未満は「比較対象なし」で無効）
    - 無効時 `setToolTip`「設定は保持されます・2 つ以上のファイルを読み込むと再適用されます」
      （`setToolTipsVisible(True)` は既設）

### ニーモニクス（M5）

- 兄弟の葉項目（カーソル A/B・カーソルを消す）はニーモニクス非付与であり、G-46 解析割当も
  `{補間方式: i}` のみ。整合のため **`comparison_mode` にはニーモニクスを付与しない** —
  `test_menu_mnemonics` の G-46 dict・docs/design.md 対訳表とも**変更不要**。
- 文言: `strings.py` に `ACTION_COMPARISON_MODE`（& なし）を追加。D-1 文言 OS の表記規約に従う（新規追加のみ・
  対訳表 G 番号の追加は不要 — メニューバー面の非ニーモニクス項目）。

### メニュー状態の既知トレードオフ（M6）

- 2 ファイル・比較 ON → 1 ファイルへ unload すると、項目は `setEnabled(False)`（<2）かつ
  `setChecked(True)`（生フラグ保持）＝**「✓グレーアウト」**になる。一方 `is_comparison_mode()`=False で
  家系色/バッジ/チップは出ない。これは「設定は保持・2 つ以上で再適用」の意図的状態とする
  （unchecked へ反転する再設計は生フラグ/実効述語の分離思想と衝突するため不可）。§10 の closure anchor
  と §7 T-B2 の assert でロックする。

**スコープ**: Analyze メニューを必須配置とする。パネル空白右クリックへのミラーは本増分では行わない。

## §3 フラグが制御するもの（＝比較モード ON のときだけ現れる E-2 の振る舞い）

すべて `is_comparison_mode()`（§1 の単一述語）を読むため、フラグ一つで一貫して従う。

1. **色相ファミリー着色** — `file_hue_resolver`（[app_viewmodel.py:276-292](../../../src/valisync/gui/viewmodels/app_viewmodel.py)）が
   `is_comparison_mode()` False で None を返す。ON のときのみ家系色。
2. **◎基準バッジ・ファイル色チップ** — `FileBrowserVM.is_comparison_mode()` は
   `AppViewModel.is_comparison_mode()` へ委譲済み（[file_browser_vm.py:91-98](../../../src/valisync/gui/viewmodels/file_browser_vm.py)）。
   `_refresh`（バッジ・[:170](../../../src/valisync/gui/viewmodels/file_browser_vm.py)）と `chip_color`
   （[:106](../../../src/valisync/gui/viewmodels/file_browser_vm.py)）は自動追従。
   - **追加配線（必須）**: `FileBrowserVM._on_app_change` の購読タグ集合
     （[:155](../../../src/valisync/gui/viewmodels/file_browser_vm.py) の
     `("loaded", "unloaded", "releasing", "reference")`）へ **`"comparison_mode"` を追加** —
     これを忘れるとトグルでバッジ/チップが即再描画されず、メニューを閉じて開くまで気づかない
     false-green（§7 T-B3 で捕捉）。
3. **ファイルブラウザ右クリックの比較 affordance（M7 — 対称化）** — 現行「基準の同名信号を重ねる」は
   `not is_ref and is_comparison_mode()` で enabled 判定
   （[file_browser_view.py:130](../../../src/valisync/gui/views/file_browser_view.py)）。
   **「基準に設定」も同様に比較モード時のみ表示する**よう対称化する（単一モードでの set-reference は
   ◎バッジ抑制・チップ None・ステータス無変化で視覚効果ゼロなのに、相方「重ねる」は非表示という
   非対称＝「壊れて見える」を解消）。すなわち:
   - **単一モード**: 右クリックは「削除」のみ（比較 affordance なし＝E-2 以前と同じ素のプロット）。
   - **比較モード ON**: 「基準に設定」（reference 行は disabled）＋「基準の同名信号を重ねる」（非 reference 行）が現れる。
4. **基準既定の開示（M8）** — 比較モード ON にした初回、`reference_file_key` は
   `register_loaded` で最初のロードへ無条件設定済み（[app_viewmodel.py:253-254](../../../src/valisync/gui/viewmodels/app_viewmodel.py)）
   だが単一モードでは不可視。ON 時に「いつの間にか基準が決まっている」唐突さを避けるため、
   トグル ON のハンドラで **ステータス通知**「比較モード: 基準ファイル=〈表示名〉（右クリックで変更）」を出す。

## §4 遷移の対称性（ON=再着色 / OFF=凍結）

`GraphAreaVM._on_app_change`（[graph_area_vm.py:86-103](../../../src/valisync/gui/viewmodels/graph_area_vm.py)）へ
`"comparison_mode"` の分岐を追加する。

```python
elif change == "comparison_mode":
    # ON: recolor autos into hue families. OFF: reapply is a structural no-op
    # (resolver returns None for every group → reapply_auto_colors' `continue`
    # on `hue is None` leaves existing colors untouched), so the SAME call
    # gives freeze-on-OFF for free (user decision 3). No ON/OFF branching needed.
    self._for_each_panel(lambda p: p.reapply_auto_colors())
```

**設計の要**: `reapply_auto_colors` は resolver が None を返すと
`continue`（既存色保持）する（[graph_panel_vm.py:746-747](../../../src/valisync/gui/viewmodels/graph_panel_vm.py)）—
**count-mod へ戻さない**。したがって:

- **ON（単一→比較）**: 述語 True → 各 auto エントリが家系色へ。sticky `variant_step` は全 add で
  記録済み（[:326](../../../src/valisync/gui/viewmodels/graph_panel_vm.py)）なので、同一ファイルの
  複数信号は潰れず明度バリアントへ展開。
- **OFF（比較→単一）**: 述語 False → resolver 全 None → reapply は完全 no-op（色を触らない）＝**家系色のまま凍結**。
- **手動ピン色**: `color_is_auto=False` で reapply の対象外（常に不変）。

`_for_each_panel` は全タブ/全パネルへ効く（アクティブのみではない）ことを前提とする（§7 T-B で確認）。

OFF 後にシングルモードで**新規追加**した信号は、その時点の述語（False）で count-mod 色になる
（既存の家系色エントリと混在）。これは「凍結＝既存を触らない・新規は現モードに従う」の帰結として
**意図的挙動**とする（§9 で受け入れ）。

## §5 モードから独立に保つもの（E-0 の関心事）

読み値の「(csv_1)」ファイルキー併記は、`display_names()` の**実際の同名衝突**（表示集合内で
distinct group_key）で発火する表示曖昧性解消であり、E-0（表示名）の関心事。**比較モードのフラグとは
切り離す**。

- **スコープの正確化（M14）**: 衝突検出は `_visible_display_names`（同一パネルの可視エントリ内で
  distinct group_key ≥ 2）で発火する。したがって併記が出るのは「**同一パネルに両ファイルの同名信号を
  ともに可視でプロットしたとき**」に限る。VehSpd(csv_1)=パネルA／VehSpd(csv_2)=パネルB の別パネル
  レイアウトでは併記は出ない（読み値ペインはアクティブパネル束縛ゆえ同時併存の曖昧性がそもそも無い）—
  機構（衝突ベース・モード非依存）の正しさは保持する。
- 現行 readings 3 メソッドは `display_names()` 経由で衝突ベース（`is_comparison_mode()` 非依存）であることを
  実測確認し、フラグ導入で誤って結合しないことを回帰で固定する（§7 T-A5）。

## §6 変更しないもの

- **同名信号の重ね先=基準と同一 Y 軸**（新規軸なし）。`overlay_reference_signals` が基準エントリの
  `axis_index` へ `add_signal_to_axis` する（[reference_overlay.py:119](../../../src/valisync/gui/reference_overlay.py)）—
  比較の目的そのもの。維持。
- **基準ファイル既定=最初のロード**。シングルモードでは無害な内部マーカー（バッジ非表示）。維持。
- **キー体系・数式・オフセット・D&D mime・色パレット・hue_variant 係数**は不変。

## §7 テスト（gui-test-plan 準拠）

### 変更種別
VM 純ロジック（述語・フラグ）＋ウィジェット状態（メニュー checkable/enabled・バッジ/チップ再描画）＋
描画（家系色 ON/OFF の実ピクセル）。

### Layer A（headless・VM）
- **T-A1 述語（両分岐 rewrite）**: `set_comparison_mode(True)`＋2 ファイル → `is_comparison_mode()` True。
  2 ファイル・OFF → False。1 ファイル・ON → `is_comparison_mode()` False かつ `comparison_enabled` True。
  `is_comparison_mode()` と `comparison_enabled` を**別々に固定**（AND ガードと生フラグの分離）。
- **T-A2 no-op ガード**: 同値 set は notify なし（購読カウンタで実証）。
- **T-A3 resolver 連動**: フラグ OFF → resolver 全 None（count-mod）。ON＋2 ファイル → hue index。
- **T-A4 OFF 凍結＋no-churn（M12）**: 2 ファイル・ON で家系色 → `set_comparison_mode(False)` → reapply 呼出でも
  (a) 色不変（family 色のまま）＋(b) **`notify` 回数=0・`_cache` 同一性**（色同一なのに invalidate/notify する
  churn がない）を assert。**sabotage 2 種**: (1) reapply の `hue is None` の `continue` を「count-mod へ戻す」へ
  改変 → 色不変 assert が RED。(2) reapply の invalidate/notify を `if changed` の外へ移す → no-churn assert が RED。
- **T-A5 E-0 独立（setup 明示・M15）**: (1) 2 つの distinct group_key で同一裸名の信号を用意 →
  (2) **同一アクティブパネル**へ `add_signal_to_axis` で両プロット → (3) 両 visible の状態で →
  (4) `cursor_readings`（可能なら legend/delta も）の name に「bare (group_key)」併記が出る。
  `is_comparison_mode()` False（単一モード）でも出ることを assert。**sabotage**: readings の
  `_visible_display_names` を `is_comparison_mode()` ゲートで包む → RED。
- **T-A6 sticky 展開**: 単一モードで同一ファイル 3 信号 add（count-mod）→ ON → 3 本が相異バリアント
  （潰れない・variant_step が add 時記録済みの帰結）。
- **T-A7 2→1 unload 凍結（M9）**: 2 ファイル・ON で家系色 → 1 ファイルへ unload → 生存曲線は
  **家系色のまま凍結**（count-mod へ戻らない）・`comparison_enabled` は True 保持を assert。

### Layer B（実イベント・ウィジェット）
- **T-B1 メニュー同期＋生フラグ厳守（M6/M4）**: 2 ファイルロード → Analyze `aboutToShow` → 項目 enabled・
  unchecked。トリガ → checked＋`app_vm.comparison_enabled` True＋バッジ出現。**sabotage**: checkstate を
  `is_comparison_mode()` へ差し替える → 「1 ファイル＋ON」で RED（生フラグでなく AND 述語を使う退行を捕捉）。
- **T-B2 <2 ファイル無効＋checked 保持（M6）**: 1 ファイル → 項目 disabled。2 ファイル・ON → 1 ファイルへ
  unload → 項目 disabled かつ **checkstate=checked 保持**（意図的決定をロック）。
- **T-B3 バッジ/チップ再描画（M3 配線）**: トグル → FileBrowser モデル reset 発火（`"comparison_mode"` 購読）→
  ◎基準サフィックス・チップ色の出現/消滅。
- **T-B4 比較 affordance のモード連動（M7）**: シングルで右クリック → 「基準に設定」「重ねる」ともに不在。
  ON で右クリック → 両方出現（reference 行は set-ref disabled）。
- **T-B5 ON 再着色配線（M10）**: **2 ファイルをロード済み（count-mod 表示中）→ `set_comparison_mode(True)` →
  `comparison_mode` 分岐発火 → 各パネル reapply → 家系色**、を決定的に検査する専用テスト
  （ユーザー主経路＝「2 ファイル表示中にメニュー ON」）。既存 hue テスト（loaded 経路・
  test_graph_panel_vm.py:806-893 相当）は**存置**し、この経路と統一しない（両経路とも必要）。
- **T-B6 resolver 全パネル到達（M11）**: 2 ファイル・比較 ON で**任意のパネル**（初期＋add_tab）が
  hue 由来色を持つことを assert（resolver 注入が全 construction site に届く不変条件 — OFF 凍結テストと対）。

### Layer C（realgui・①ゲート）
- **T-C1 実トグルジャーニー**（既存 `test_comparison_model_realclick.py` 拡張）:
  2 ファイルロード → 実 OS で Analyze メニュー「比較モード」クリック → 家系色が**実ピクセルで出現**
  （ON 前は count-mod・ON 後は青系/橙系）→ 再クリックで OFF → **家系色が凍結（count-mod へ戻らない）**を
  実ピクセルで実証 → ◎基準バッジの出現/消滅。**E-2 家系色ビジュアルの凍結被覆は本 realgui が一次**
  （§8 のとおりカタログには家系色状態が無いため）。

### 既存 E-2 テスト追随（M13 — プランへ）
フラグ導入で「2 ファイル=比較自動 ON」前提の既存 E-2 テストが RED 化する。**機械的 `set_comparison_mode(True)`
挿入は禁止**（T-A1 の境界カバレッジや §3 の set-ref 意図を消す）。プランに**サイト別チェックリスト**を置く:
- Layer A VM の色/バッジ/チップテスト → 明示 `set_comparison_mode(True)` を要否判断つきで追加。
- set-reference テスト → フラグ OFF で存置し、「単一で set-ref/overlay 不在／ON で両方」を T-B4 で assert。
- `reference_overlay` ハンドラ系 → 非依存で存置（重ね項目の到達性は既存 emit テスト＋T-C1 で担保・両者フラグ追随）。
- `_FakeHueResolver` 系の isolation テスト → 注入せず存置。**フラグ回帰の実検出網は GraphAreaVM 経由
  （806-893）＋Layer B/C のみ**（_Fake 系は当てにしない）を §7/§10 で明記。

### ①証拠ゲート
`uv run pytest tests/realgui/ --realgui -q` フル＋T-C1 のスクショ目視を merge 前に必須化。

## §8 凍結カタログ / 検証契約（M16 — 是正）

**現行カタログは全状態 1 ファイル**（`capture_ui_screenshots.py` は各状態で load を 1 回のみ）。
したがって `is_comparison_mode()` は全状態で恒常 False であり、**家系色/◎バッジ/チップを撮った状態は
1 つも存在しない**（PR #145 が更新した 02-05/09 の差分は E-0 の読み値名短縮に由来し、E-2 家系色ではない）。

- **帰結**: 比較モードのフラグ導入はカタログ表示を一切変えない。**01-09 全状態が PR #145 ベースラインと
  完全一致**（差分ゼロ・compare exit 0・両テーマ）。注入口の追加も再撮影も不要。
- **家系色の実描画検証は §7 T-C1（realgui）に一本化**する（カタログには被覆が無いため）。
- **（任意・follow-up）** 比較ビジュアルを凍結被覆したい場合は、2 個目 fixture ロード → 両ファイルから
  プロット → `set_comparison_mode(True)`（→ 任意で同名重ね）の**新規状態**（例 `10_comparison_families`）を
  明示手順で追加し、その状態のみ E-2 差分を許容する形で per-state 契約を分離する。本増分では realgui T-C1 を
  一次被覆とし、この新規カタログ状態は増分スコープ外とする。
- 昇格 → 再撮影 compare exit 0（両テーマ）＋決定性で「トグル追加が既存 01-09 を壊さない」ことを実証する。

## §9 受け入れ基準

1. 既定でアプリ起動 → 2 ファイルロード → **count-mod 色のまま・◎基準バッジなし・比較 affordance なし**
   （＝先のユーザー確認と一致）。
2. Analyze メニュー「比較モード」ON → 家系色・◎基準バッジ・チップ・比較 affordance が一斉に出現＋
   基準ファイルのステータス開示。
3. OFF → **家系色は凍結**（count-mod へ戻らない）・バッジ/チップ/比較 affordance は消える。手動ピン色は不変。
4. **フレッシュ 1 ファイル起動**はフラグ状態を問わず count-mod・バッジなし（従来互換）。**2→1 unload 後**は
   §4.2 の家系色凍結（count-mod へ戻さない）— §4.2 とのクロス参照で「1 ファイル」の 2 系（フレッシュ起動 vs
   unload 後）を区別する。
5. 読み値の同名併記はモード非依存（同一パネル可視・衝突ベース）。
6. 同名重ねは同一 Y 軸（新規軸なし）を維持。
7. 比較モードは transient（セッションごとに既定シングルへ戻る・reference_file と同じ）。`inspect()` に
   `comparison_enabled` を露出。
8. OFF/アンロード後は色↔ファイル対応が読み値ペインの名前でのみ辿れる（on-plot 凡例は ON でも非存在）—
   既知トレードオフとして受け入れる。
9. full suite green・realgui フル＋T-C1・凍結 01-09 完全一致（差分ゼロ）・決定性 exit 0。

## §10 敵対的レビューが攻撃すべき点（closure anchors）

- **述語の二重定義**: `is_comparison_mode()`（フラグ AND ≥2）と `comparison_enabled`（生フラグ）の
  取り違え — メニュー checkstate は生フラグ、色/バッジは AND 述語。誤読で「1 ファイル＋ON」に
  家系色が付く/カタログ破壊が起きないか（T-B1 sabotage）。
- **OFF 凍結の実挙動**: reapply の `continue`-on-None が唯一の凍結機構。count-mod 復帰へ退行したとき／
  color 不変でも churn（invalidate/notify）するとき、を検出する sabotage 2 種（T-A4）が実効か。
  realgui（T-C1）で実ピクセル凍結を撮っているか。
- **checked+disabled 到達状態（M6）**: 2 ファイル ON→1 ファイル unload で「✓グレーアウト」かつキャンバスは
  非比較、というメニュー/挙動の乖離が意図的決定としてロックされているか（T-B2）。
- **resolver 全パネル到達（M11）**: 将来 construction site 追加で resolver 注入を忘れると、OFF は
  「家系色未着ゆえ自明に凍結」で緑・ON だけが無言 no-op（家系色皆無）になる。全 construction site で
  resolver が届き ON で任意パネルが hue 由来色を持つ（T-B6）を OFF 凍結テストと対で assert しているか。
- **E-0/E-2 の結合**: 読み値併記がモードフラグへ誤って結合していないか（T-A5 sabotage）。
- **配線の抜け**: `FileBrowserVM` が `"comparison_mode"` を購読していないとトグルでバッジが即更新されない
  false-green（T-B3）。`GraphAreaVM._on_app_change` の `comparison_mode` 分岐欠落を「トグル ON→ロード」順の
  既存テストが隠す順序依存 false-green（T-B5 が主経路を決定的に検査）。
- **既存 E-2 テストの前提崩れ**: 「2 ファイル=比較モード」を暗黙前提にした既存テストを、機械置換でなく
  サイト単位で挙動整合を確認して追随したか（§7 の 14 サイト・チェックリスト）。
