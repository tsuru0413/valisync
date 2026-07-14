# FU-06 + FU-13: 信号プレビューウィンドウ＋追加導線の整理 設計

## 背景 / 課題

- **FU-13**（UX 要望）: ChannelBrowser の信号ダブルクリックを、現状の「アクティブパネルへ追加」（PC-04）から**波形プレビュー/信号プロパティ表示**へ変更したい。
- **FU-06**（UX リファイン）: Channel Browser の「アクティブパネルへ追加」ボタン（PC-02）を廃止したい。
- **追加のユーザー指示（2026-07-14）**: **Enter での追加も廃止**。プレビューは**「プレビュー」タブと「信号プロパティ」タブを持つウィンドウ**にする。**Enter は何もしない**（プレビューにも割り当てない）。

現状の追加導線（`channel_browser_view.py`）: (1) ボタン `add_button`「アクティブパネルへ追加」（PC-02）・(2) `tree.activated`→`_emit_add_selected`（PC-04＝ダブルクリック）・(3) Enter を `eventFilter` が消費して単発 add・(4) 右クリック `build_context_menu` "Add to Active Panel"・(5) D&D（`mime_data_for_selection`）。プロパティは PC-19 の hover リッチツールチップ（`ChannelBrowserVM.tooltip_for`）で一部提供済み。プレビュー基盤は無し。

## ゴール

1. 信号ダブルクリックで、**2タブ（プレビュー波形／信号プロパティ）を持つ非モーダル・単一インスタンスのウィンドウ**を開く。
2. 追加導線を整理: **ボタン・ダブルクリック追加・Enter 追加を廃止**し、**右クリック "Add to Active Panel" ＋ D&D のみ**に絞る。Enter は何もしない。

## 追加導線の最終セット（相互作用の解決）

| 導線 | 変更前 | 変更後 |
|---|---|---|
| 追加ボタン（PC-02） | あり | **廃止（FU-06）** |
| ダブルクリック | 追加（PC-04） | **プレビューを開く（FU-13）** |
| Enter | 追加（eventFilter 単発） | **何もしない**（配線除去） |
| 右クリック "Add to Active Panel" | あり | **残す**（可視の click-add を維持） |
| D&D | あり | **残す** |

**発見性**: 右クリックメニュー "Add to Active Panel" が可視の click-add を保つため、3導線廃止でもマウス/キーボード双方の追加手段が失われない（右クリック2クリック＋D&D）。

## アーキテクチャ

### 新規 `SignalPreviewVM`（`gui/viewmodels/signal_preview_vm.py`）
- 現在の対象 `signal_key` を保持。`set_signal(key)` で更新し `_notify("signal")`。
- `properties() -> list[tuple[str, str]]`: 信号プロパティを (ラベル, 値) の順序付きリストで返す。`tooltip_for` のデータ（単位・サンプル数・由来・コメント・value_labels）を**構造化して再利用**し、tooltip が除外している**時間範囲**（`Signal.time_range()` ＝生 min/max・FU-18 のガードレール）と **min/max 値**を追加。信号が解決できない/空なら空リスト。
- `plot_data() -> tuple[np.ndarray, np.ndarray] | None`: プレビュー波形用の**ダウンサンプル済** (x, y)。core の Downsampler（`core/downsampler/downsampler.py`）を全時間範囲・プレビュー幅（固定 px 想定・例 480）で適用。空/非解決なら None。
- session からの信号解決は `ChannelBrowserVM._signal_by_key` と同じ経路（session 参照を DI）。core は Qt 非依存を維持（VM は gui/viewmodels）。

### 新規 `SignalPreviewWindow`（`gui/views/signal_preview_window.py`）
- 非モーダルのトップレベル `QWidget`（`Qt.WindowType.Window`）。`QTabWidget` で2タブ：
  - **「プレビュー」**: `pyqtgraph` の read-only プロット（マウス操作無効＝`setMouseEnabled(False, False)`・メニュー無効）。`plot_data()` の波形を1本描画。データ無しは「プレビューできません」ラベル。
  - **「信号プロパティ」**: `QFormLayout`（または行ラベル）で `properties()` を列挙。空は「プロパティなし」。
- `show_signal(key)`: VM を `set_signal(key)` → 両タブを再描画 → ウィンドウを `show()` ＋ `raise_()` ＋ `activateWindow()`（既出なら内容差し替え＝**単一インスタンス**）。
- ウィンドウタイトルに信号名を表示。閉じるは通常のウィンドウクローズ（破棄せず hide＝再利用）。

### `ChannelBrowserView` の変更
- `tree.doubleClicked.connect(...)` → 新シグナル `preview_requested = Signal(str)` を選択中の signal_key で emit（`activated`→add の配線を置換。`doubleClicked` はダブルクリック専用ゆえ Enter で発火しない）。
- `add_button`（PC-02）と関連配線（`_emit_add_selected` の clicked 接続・`_refresh` の `setEnabled`）を**削除**。
- Enter 用 `eventFilter` の add emit を**削除**（Enter は何もしない）。`eventFilter` 自体が他用途を持たなければ除去。
- **残す**: `build_context_menu` "Add to Active Panel"（`add_to_panel_requested`）・D&D。`_emit_add_selected` はメニューが使うため残す（clicked からは切り離す）。

### 配線（`MainWindow`）
- `SignalPreviewWindow` を単一インスタンスで所有。`channel_browser_view.preview_requested` → `preview_window.show_signal(key)`。
- プレビュー VM に session を注入（`app_vm.session`）。

## データフロー

ダブルクリック → View が `preview_requested(key)` emit → MainWindow が `preview_window.show_signal(key)` → VM が session から Signal 解決 → プロパティ構造化＋波形ダウンサンプル → 2タブ描画 → ウィンドウ表示（既出なら差し替え）。

## エラーハンドリング

- 信号が session に無い/空 timestamps: プレビュータブ＝「プレビューできません」ラベル・プロパティタブ＝取得可能分のみ（空なら「プロパティなし」）。例外は投げない。
- 親（配列）ノードのダブルクリック: `signal_key` が None（親）→ preview_requested を emit しない（親はプレビュー対象外）。

## テスト設計（gui-test-plan）

- **Layer A（`SignalPreviewVM`）**: `properties()` が時間範囲・min/max を含み tooltip データを構造化（単位/サンプル数/由来/コメント/value_labels）・`plot_data()` がダウンサンプル済で全範囲・空/非解決で None/空・`set_signal` で内容更新。`Signal.time_range()` 経由で FU-20 float64 キャッシュを materialize しない（[[signal_range_via_sorted_view_materializes_float64_cache]]）ことを sabotage で確認。
- **Layer B（`ChannelBrowserView`）**: `doubleClicked` が `preview_requested`（signal_key）を emit し `add_to_panel_requested` は emit しない・`add_button` が存在しない（属性/レイアウト非在）・Enter が add を emit しない（eventFilter add 除去）・右クリック "Add to Active Panel" と D&D は従来どおり `add_to_panel_requested` を emit（無回帰）・親ノードのダブルクリックは preview_requested を emit しない。
- **Layer B（`SignalPreviewWindow`）**: 2タブが正しいタイトルで存在・`show_signal` 後にプレビュータブにプロット item が1本・プロパティタブが populated・別 key で `show_signal` 再呼びで内容差し替え（単一インスタンス）。
- **可視効果は real display スクショ**（[[gui_dock_toggle_width_change_needs_real_display_and_layout]] と同様、ウィンドウ描画は real display で確認）: ダブルクリック→2タブウィンドウが開き、プレビュータブに波形が描画される。
- **gui-verify ①ゲート**（入力経路変更＝ダブルクリック挙動）: realgui で「実ダブルクリック→プレビューウィンドウが開く」＋「右クリック "Add to Active Panel"／D&D で追加は無回帰」＋ journey smoke。

## YAGNI（除外）

- プレビュープロットの操作（ズーム/パン/カーソル/LOD 再計算）＝静的ダウンサンプル描画のみ。
- 複数プレビューウィンドウ（単一インスタンス）・複数信号オーバーレイ・データ変化のライブ追従。
- プロパティタブの編集/コピー等の高度操作（表示のみ）。

## Global 制約

- core（Signal/Downsampler/session の非 Qt 部）は Qt 非依存維持。`SignalPreviewVM` は gui/viewmodels、`SignalPreviewWindow` は gui/views。
- 品質ゲート: pytest / ruff check / ruff format --check / mypy 全通過。
- Python コメント/文字列に全角約物 `()：+=` 禁止（RUF001/002/003）。ASCII を使う（`->`/`→`/`・` は可）。
- 入力経路（ダブルクリック）変更ゆえ merge 前に gui-verify ①realgui 証拠ゲート。
