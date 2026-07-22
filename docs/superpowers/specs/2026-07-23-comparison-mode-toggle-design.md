# 比較モードのユーザー切り替え（E-2 拡張）設計

> **出典**: E-0＋E-2 比較データモデル（[e2-comparison-model spec](2026-07-23-e2-comparison-model-design.md)）の追補。
> ユーザー決定（2026-07-23）で、比較モードの起動を「ファイル数 ≥ 2 の自動判定」から
> 「ユーザーが Analyze メニューで明示的に切り替えるフラグ」へ変更する。**同一ブランチ
> `feature/e2-comparison-model`（PR #145・未マージ）へ畳んで一つのまとまりとして出荷**する
> — 自動比較を出荷して直後に振る舞いを変えるカタログ churn を避けるため。

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

### 状態

- 新規フィールド `self._comparison_enabled: bool = False`（既定 OFF）。

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
    """The raw user flag (independent of file count) — for the menu checkstate
    and QSettings persistence. Distinct from is_comparison_mode(), which ANDs
    in the 2-file guard."""
    return self._comparison_enabled
```

- **`comparison_enabled`（生フラグ）と `is_comparison_mode()`（フラグ AND ≥2）を区別**する。
  メニューのチェック状態・永続化は生フラグ、色/バッジの発火は `is_comparison_mode()`。

### 永続化（QSettings）

- キー `comparisonMode`（bool）。テーマ/`dockCollapsed` と同じ UI プレファレンス層。
- 保存: `set_comparison_mode` を呼ぶ View 側で `QSettings` へ書く（AppViewModel は Qt 非依存を維持）。
- 復元: 起動時 `_restore_state()` の後・`_reset_layout()` は非対象（レイアウトではなくデータビュー設定）。
  復元は `app_vm.set_comparison_mode(saved)` を呼ぶだけ（0 ファイル起動では効果なし・2 ファイル目で発火）。
- **撮影ツールの QSettings 隔離必須**（memory [[gui_capture_qsettings_setdefaultformat_no_isolation]]）—
  撮影は `_ORG/_APP` 差し替え＋clear で実レジストリを遮断する既存機構を通るため、
  永続フラグはカタログへ漏れない。§8 で実測確認する。
- INI 直列化の bool 罠（[[followup_settings_iniformat]]）: `QSettings.value(key, False, type=bool)` で型明示読み。

## §2 UI: Analyze メニューの checkable 項目

Analyze メニュー（[main_window.py:361](../../../src/valisync/gui/views/main_window.py)）に checkable
「比較モード」QAction を追加する。既存の cursor/interp アクションと同じ `aboutToShow` 同期機構
（`_sync_analysis_actions`・[main_window.py:374](../../../src/valisync/gui/views/main_window.py)）へ相乗り。

- QAction は `AnalysisActions` レジストリ（またはそれに準ずる shared holder）に `comparison_mode`
  として追加し、cursor 群とはセパレータで区切る（計測アクションと別概念のため視覚的に分離）。
- `setCheckable(True)`。`triggered` を `app_vm.set_comparison_mode(checked)` ＋ QSettings 保存へ配線
  （`toggled` ではなく `triggered` — 排他 radio と同じく VM 変異は triggered、memory
  [[gui_qactiongroup_exclusive_radio_menu]] の思想）。
- `_sync_analysis_actions`（`aboutToShow`）で:
  - `setChecked(app_vm.comparison_enabled)`（生フラグを反映）
  - `setEnabled(len(loaded_file_keys) >= 2)`（2 ファイル未満は「比較対象なし」で無効・チェック状態は保持表示）
  - `setToolTip`: 無効時は「2 つ以上のファイルを読み込むと使えます」旨（`setToolTipsVisible(True)` は既設）
- 文言: `strings.py` に `ACTION_COMPARISON_MODE`（ニーモニクス付与はメニューバー面規約に従う — G-46 の
  メニューバー walk テスト集合へ含める）。

**スコープ**: Analyze メニューを必須配置とする。パネル空白右クリックへのミラーは本増分では行わない
（cursor/grid/syncX の右クリック面は計測 IA の資産・比較モードはデータビュー設定で別概念。必要なら
follow-up）。

## §3 フラグが制御するもの（＝比較モード ON のときだけ現れる E-2 の振る舞い）

すべて `is_comparison_mode()`（§1 の単一述語）を読むため、フラグ一つで一貫して従う。

1. **色相ファミリー着色** — `file_hue_resolver`（[app_viewmodel.py:276-292](../../../src/valisync/gui/viewmodels/app_viewmodel.py)）が
   `is_comparison_mode()` False で None を返す。ON のときのみ家系色。
2. **◎基準バッジ・ファイル色チップ** — `FileBrowserVM.is_comparison_mode()` は
   `AppViewModel.is_comparison_mode()` へ委譲済み（[file_browser_vm.py:91-98](../../../src/valisync/gui/viewmodels/file_browser_vm.py)）。
   `_refresh`（バッジ・[:170](../../../src/valisync/gui/viewmodels/file_browser_vm.py)）と `chip_color`
   （[:106](../../../src/valisync/gui/viewmodels/file_browser_vm.py)）は自動追従。
   - **追加配線**: `FileBrowserVM._on_app_change` の購読タグ集合
     （[:155](../../../src/valisync/gui/viewmodels/file_browser_vm.py) の
     `("loaded", "unloaded", "releasing", "reference")`）へ **`"comparison_mode"` を追加** —
     トグルでバッジ/チップが即再描画されるように。
3. **ファイルブラウザ右クリックの比較 affordance** — 「基準の同名信号を重ねる」は現行
   `not is_ref and self._vm.is_comparison_mode()` で enabled 判定
   （[file_browser_view.py:130](../../../src/valisync/gui/views/file_browser_view.py)）。述語が
   フラグ連動になるため、**シングルモードでは重ね項目が現れず、比較モード ON で現れる**（自動追従・変更不要）。
   - 「基準に設定」はシングルモードでも表示のままとする（基準マーカーの設定自体は無害・比較 ON 時に
     バッジで効いてくる）。現行どおり `key is not None`（loaded 行）で表示、reference 行のみ disabled。

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

OFF 後にシングルモードで**新規追加**した信号は、その時点の述語（False）で count-mod 色になる
（既存の家系色エントリと混在）。これは「凍結＝既存を触らない・新規は現モードに従う」の帰結として
**意図的挙動**とする（§9 で受け入れ）。

## §5 モードから独立に保つもの（E-0 の関心事）

読み値の「(csv_1)」ファイルキー併記は、`display_names()` の**実際の同名衝突**（表示集合内で
distinct group_key）で発火する表示曖昧性解消であり、E-0（表示名）の関心事。**比較モードのフラグとは
切り離す** — シングルモードで両ファイルの同名信号を手動プロットしても曖昧さは併記で解消される。
現行 readings 3 メソッドは `display_names()` 経由で衝突ベース（`is_comparison_mode()` 非依存）であることを
実測確認し、フラグ導入で誤って結合しないことを回帰で固定する（§7 T-A5）。

## §6 変更しないもの

- **同名信号の重ね先=基準と同一 Y 軸**（新規軸なし）。`overlay_reference_signals` が基準エントリの
  `axis_index` へ `add_signal_to_axis` する（[reference_overlay.py:119](../../../src/valisync/gui/reference_overlay.py)）—
  比較の目的そのもの。維持。
- **基準ファイル既定=最初のロード**（[app_viewmodel.py:253-254](../../../src/valisync/gui/viewmodels/app_viewmodel.py)）。
  シングルモードでは無害な内部マーカー（バッジ非表示）。維持。
- **キー体系・数式・オフセット・D&D mime・色パレット・hue_variant 係数**は不変。

## §7 テスト（gui-test-plan 準拠）

### 変更種別
VM 純ロジック（述語・フラグ）＋ウィジェット状態（メニュー checkable/enabled・バッジ/チップ再描画）＋
描画（家系色 ON/OFF の実ピクセル）。

### Layer A（headless・VM）
- **T-A1 述語**: `set_comparison_mode(True)`＋2 ファイル → `is_comparison_mode()` True。1 ファイルでは
  フラグ True でも False（`and len>=2`）。`comparison_enabled` は生フラグ（1 ファイルでも True）。
- **T-A2 no-op ガード**: 同値 set は notify なし（購読カウンタで実証）。
- **T-A3 resolver 連動**: フラグ OFF → resolver 全 None（count-mod）。ON＋2 ファイル → hue index。
- **T-A4 OFF 凍結**: 2 ファイル・ON で家系色 → `set_comparison_mode(False)` → reapply 呼出でも色不変
  （family 色のまま）。**sabotage**: reapply の `hue is None` の `continue` を「count-mod へ戻す」へ
  改変 → このテストが RED（凍結が壊れる）。
- **T-A5 E-0 独立**: 単一モードで両ファイルの同名を手動プロット → 読み値に「(csv_1)」併記が出る
  （`is_comparison_mode()` False でも）。**sabotage**: readings の display_names を `is_comparison_mode()`
  ゲートで包む → RED。
- **T-A6 sticky 展開**: 単一モードで同一ファイル 3 信号 add（count-mod）→ ON → 3 本が相異バリアント
  （潰れない・variant_step が add 時記録済みの帰結）。

### Layer B（実イベント・ウィジェット）
- **T-B1 メニュー同期**: 2 ファイルロード → Analyze `aboutToShow` → 比較モード項目 enabled・
  unchecked。トリガ → checked＋`app_vm.comparison_enabled` True＋バッジ出現。
- **T-B2 <2 ファイル無効**: 1 ファイル → 項目 disabled。
- **T-B3 バッジ/チップ再描画**: トグル → FileBrowser モデル reset 発火（`"comparison_mode"` 購読）→
  ◎基準サフィックス・チップ色の出現/消滅。
- **T-B4 重ね項目のモード連動**: シングルで右クリック → 「重ねる」不在。ON で右クリック → 出現。

### Layer C（realgui・①ゲート）
- **T-C1 実トグルジャーニー**（新設 or 既存 `test_comparison_model_realclick.py` 拡張）:
  2 ファイルロード → 実 OS で Analyze メニュー「比較モード」クリック → 家系色が**実ピクセルで出現**
  （ON 前は count-mod・ON 後は青系/橙系）→ 再クリックで OFF → **家系色が凍結（count-mod へ戻らない）**を
  実ピクセルで実証 → ◎基準バッジの出現/消滅。
- **T-C2 永続**: トグル ON → QSettings に `comparisonMode=true` 書込を確認（隔離下）。

### ①証拠ゲート
`uv run pytest tests/realgui/ --realgui -q` フル＋T-C1/T-C2 のスクショ目視を merge 前に必須化。

## §8 凍結カタログ / 検証契約

- **既定=シングル**なので、多ファイルを含むカタログ状態があれば count-mod 色（＝E-0 のみ適用・
  E-2 家系色なし）が既定表示になる。PR #145 で E-2 家系色に更新したベースラインのうち、
  **比較モードを ON にして撮った状態があれば count-mod へ戻る**。撮影 fixture が比較モードを
  ON にしているか（`--catalog` の各状態のロードファイル数・モード）を洗い出し、per-state で
  期待差分を確定する:
  - 1 ファイル状態（01/07/08 等）: フラグ導入前後で**完全一致**（`is_comparison_mode()` は 1 ファイルで
    常に False＝従来どおり）。
  - 2 ファイル状態（もしあれば）: 既定シングルなら count-mod へ。**比較を見せたい状態は撮影シナリオで
    明示的に `set_comparison_mode(True)` する**（撮影ツールに比較 ON の注入口を追加 — テーマ強制注入
    `apply_startup_theme(forced)` と同型）。
- QSettings 隔離を実測確認（永続フラグがカタログへ漏れない）。
- 昇格 → 再撮影 compare exit 0（両テーマ）＋決定性。

## §9 受け入れ基準

1. 既定でアプリ起動 → 2 ファイルロード → **count-mod 色のまま・◎基準バッジなし・「重ねる」項目なし**
   （＝先のユーザー確認と一致）。
2. Analyze メニュー「比較モード」ON → 家系色・◎基準バッジ・チップ・「重ねる」項目が一斉に出現。
3. OFF → **家系色は凍結**（count-mod へ戻らない）・バッジ/チップ/「重ねる」は消える。手動ピン色は不変。
4. 1 ファイル運用は完全従来互換（フラグ状態を問わず count-mod・バッジなし）。
5. 読み値の同名併記はモード非依存（衝突ベース）。
6. 同名重ねは同一 Y 軸（新規軸なし）を維持。
7. QSettings に設定が永続し、撮影カタログへ漏れない。
8. full suite green・realgui フル＋新設 T-C1/T-C2・凍結 per-state 契約充足・決定性 exit 0。

## §10 敵対的レビューが攻撃すべき点（closure anchors）

- **述語の二重定義**: `is_comparison_mode()`（フラグ AND ≥2）と `comparison_enabled`（生フラグ）の
  取り違え — メニュー checkstate/永続は生フラグ、色/バッジは AND 述語。誤読で「1 ファイル＋ON」に
  家系色が付く/カタログ破壊が起きないか。
- **OFF 凍結の実挙動**: reapply の `continue`-on-None が唯一の凍結機構。これが count-mod 復帰へ
  退行したとき検出する sabotage（T-A4）が実効か。realgui（T-C1）で実ピクセル凍結を撮っているか。
- **E-0/E-2 の結合**: 読み値併記がモードフラグへ誤って結合していないか（T-A5 sabotage）。
- **永続の隔離漏れ**: `comparisonMode` が実レジストリ経由でカタログや他テストへ漏れないか
  （撮影/conftest の隔離を実測）。
- **メニュー enabled の抜け**: <2 ファイルで有効化されると「押しても何も起きない」死にトグル。
- **通知の抜け**: `FileBrowserVM` が `"comparison_mode"` を購読していないとトグルでバッジが即更新されない
  false-green（メニューを閉じて開くまで気づかない）。
- **既存 E-2 テストの前提崩れ**: PR #145 の E-2 テスト群は「2 ファイル=比較モード」を暗黙前提に
  している可能性 — フラグ導入で明示 `set_comparison_mode(True)` が要る箇所を全数洗い出したか
  （機械置換でなくサイト単位で挙動整合を確認）。
