# Implementation Plan: valisync-gui-mvp

## Overview

ValiSync GUI の「歩く骨格（walking skeleton）」を実装する。PySide6 + PyQtGraph を用い、Qt 標準 QDockWidget ドッキング上で「ファイル読込 → 信号ツリー閲覧 → パネルへ D&D → Y-T 波形描画 → X/Y ズーム/パン → 動的 LOD」を end-to-end に成立させる。

設計の核心（design.md 準拠）:
- **純 Python ViewModel（Qt 非依存・観測可能）+ 薄い Qt アダプタ View**。ロジックは VM に集約し、ヘッドレスでテスト・駆動できる（AI エージェント実機テスト容易性）
- **Session が唯一のコア窓口**（valisync-core は main にマージ済み）。GUI は `valisync.core.session.Session` と `valisync.core.models` のみ参照し、他コアモジュールを直接 import しない
- **動的 LOD を最初から**: viewport 連動・min-max・`searchsorted` スライス・debounce・キャッシュで 16ms 予算/60fps を満たす

依存順は **VM 層（headless でテスト可能）→ Qt View 層 → 統合** とする。VM を先に固めることで、View はロジックを持たない薄いアダプタに保てる。

実装は全タスク **TDD（RED→GREEN→REFACTOR）** で進める。VM はユニット/プロパティテスト、View 層は `pytest-qt`（`QT_QPA_PLATFORM=offscreen`）で検証する。

## 着手前提

- Phase 1 `valisync-core` 完了・main マージ済み（Session が load / signals / downsample / apply_offset / 各種 pass-through を公開）
- `feature/valisync-gui-mvp` ブランチで作業（main + 本 spec の上に実装）

## Tasks

- [x] 0. プロジェクト基盤・依存追加
  - [x] 0.1 GUI 依存の追加
    - `pyproject.toml` の dependencies に `PySide6>=6.7`, `pyqtgraph>=0.13` を追加
    - dev に `pytest-qt>=4.4` を追加。`uv sync --extra dev` で反映、`uv.lock` 更新
    - `[project.scripts]` に `valisync = "valisync.gui.app:main"` を有効化
    - _Requirements: 13.4_
  - [x] 0.2 pytest の Qt 設定
    - `pyproject.toml` の `[tool.pytest.ini_options]` に Qt offscreen 用設定（`env = ["QT_QPA_PLATFORM=offscreen"]` 相当、または conftest で `os.environ` 設定）を追加
    - `tests/gui/` ディレクトリと `tests/gui/conftest.py`（`qapp` / `qtbot` の前提、offscreen 設定）を作成
    - _Requirements: 13.1, 13.6_

- [x] 1. ViewModel 基盤とオブザーバ
  - [x] 1.1 Observable 基盤の実装
    - `src/valisync/gui/__init__.py`（既存・空）はそのまま、`src/valisync/gui/viewmodels/__init__.py` を作成
    - `src/valisync/gui/viewmodels/observable.py` に `Observable`（`subscribe(cb)->unsubscribe`, `_notify(change: str)`）を実装。Qt 非依存
    - `tests/gui/test_observable.py`: 購読・通知・解除のユニットテスト
    - _Requirements: 13.1_
  - [x] 1.2 AppViewModel の実装
    - `src/valisync/gui/viewmodels/app_viewmodel.py` に `AppViewModel(Observable)` を実装。`Session` を保持し、読込済みファイル一覧・アクティブ Graph_Area タブ・登録データソース一覧の状態を公開
    - `request_load(path, format_def?)`（後段で LoadTask 経由）、`inspect()->dict`（検査用状態）
    - `tests/gui/test_app_viewmodel.py`: 状態公開・通知のテスト（Session はテンポラリ CSV で実体使用、モック不使用）
    - _Requirements: 13.1, 13.2, 13.6_

- [x] 2. データ取込・閲覧 VM と永続化
  - [x] 2.1 データソース永続化の実装
    - `src/valisync/gui/persistence/__init__.py` と `src/valisync/gui/persistence/data_sources.py` を作成
    - 登録データソース（フォルダパス一覧）を JSON で保存/読込（`save(paths, file)`, `load(file)->list[Path]`）。検査容易性のため平易な JSON
    - `tests/gui/test_data_sources.py`: 保存→読込ラウンドトリップ、不存在ファイル時は空リスト
    - _Requirements: 3.5_
  - [x] 2.2 ChannelBrowserVM の実装
    - `src/valisync/gui/viewmodels/channel_browser_vm.py` に `ChannelBrowserVM(Observable)` を実装
    - Session の信号から「ソースファイル > 信号名」階層・メタ（型・サンプル数・時間範囲）を構成。`set_filter(text)` でインクリメンタル絞り込み、複数選択状態、表示/非表示トグル状態を保持
    - `tree()->構造化データ`, `visible_signal_keys()`, `inspect()`
    - `tests/gui/test_channel_browser_vm.py`: ツリー構成・検索絞り込み・選択・トグルのテスト
    - _Requirements: 4.1, 4.2, 4.4, 4.5, 4.6, 13.6_

- [x] 3. グラフ ViewModel（パネル・エリア・LOD）
  - [x] 3.1 GraphPanelVM と動的 LOD の実装
    - `src/valisync/gui/viewmodels/graph_panel_vm.py` に `GraphPanelVM(Observable)` を実装
    - 状態: 表示信号（signal_key, 色, 表示/非表示）、`x_range`, `y_range`, `panel_width_px`, `lod_active`, `last_rendered_points`
    - 操作: `add_signal/remove_signal/toggle_visibility`, `set_x_range/set_y_range/reset_x/reset_y`, `set_panel_width`
    - `render_data()->list[RenderCurve]`: 各信号につき `np.searchsorted` で可視範囲スライス → `n = 2*panel_width_px` → `Session.downsample(slice, n)`（R11.5 Session 経由）→ `lod_active`/`last_rendered_points` 更新。直近 `(x_lo,x_hi,n)` 結果をキャッシュ
    - 色は固定パレット巡回割当。`inspect()` で表示信号・範囲・色・lod_active・点数を構造化公開
    - `tests/gui/test_graph_panel_vm.py`: 信号追加→render の点数有界性、可視範囲スライス、lod_active 判定、リセット、キャッシュ
    - _Requirements: 8.1, 8.2, 8.3, 8.5, 9.x（範囲計算）, 10.x（範囲計算）, 11.1, 11.3, 11.4, 11.5, 11.6, 13.2, 13.6_
  - [x] 3.2 GraphAreaVM の実装
    - `src/valisync/gui/viewmodels/graph_area_vm.py` に `GraphAreaVM(Observable)` を実装
    - タブ群（各タブが GraphPanelVM のリスト）、アクティブタブ、`x_sync_enabled` を保持
    - `add_tab/remove_tab(最後の1つは拒否)/rename_tab(1-32文字)`, `add_panel(最大8)/remove_panel(最後の1つ拒否)`, `set_x_sync(bool)`, `propagate_x_range(range)`（同期時に全パネルへ）
    - `tests/gui/test_graph_area_vm.py`: タブ追加/削除/最後の1つ拒否/リネーム検証、パネル追加/最大8/削除再分配、X同期伝播
    - _Requirements: 5.2, 5.3, 5.4, 5.6, 6.2, 6.3, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4_

- [x] 4. ワーカー読込（VM 側状態）
  - [x] 4.1 LoadTask の実装
    - `src/valisync/gui/viewmodels/load_task.py` に `LoadTask(Observable)` を実装。状態: `idle/loading/done/error`、結果 key またはエラーメッセージ
    - 実行関数は注入可能（テストでは同期関数を渡す）。AppViewModel.request_load から呼ばれ、完了/失敗を通知
    - `tests/gui/test_load_task.py`: 成功遷移（idle→loading→done）、失敗遷移（→error）。実 Session.load を使用
    - _Requirements: 2.4, 2.5, 13.5_

- [x] 5. チェックポイント — ViewModel 層（ヘッドレス）
  - 全 VM テストが Qt/ディスプレイ無しで green。`uv run pytest tests/gui -q`（View 未実装分を除く）・ruff・mypy 通過

- [x] 6. シェル・ドッキング・エントリポイント
  - [x] 6.1 MainWindow の実装
    - `src/valisync/gui/views/__init__.py` と `src/valisync/gui/views/main_window.py` を作成
    - `QMainWindow`: Channel_Browser と Graph_Area を独立 QDockWidget として配置（左/右）、central はプレースホルダ。メニュー/ツールバー（Data_Explorer 起動、閉じたドック再表示 = `toggleViewAction`）
    - 起動時に QSettings からウィンドウ位置・サイズ復元、終了時保存
    - `tests/gui/test_main_window.py`（pytest-qt）: ドック存在・フロート可能・閉→再表示、QSettings 復元
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.3_
  - [x] 6.2 app.py エントリポイントの実装
    - `src/valisync/gui/app.py` に `main()`: QApplication 生成 → Session 生成 → AppViewModel → MainWindow 表示
    - `tests/gui/test_app.py`（pytest-qt）: `main()` 相当の組み立てでウィンドウが 3 秒以内に表示可能な状態になる（起動スモーク）
    - _Requirements: 2.1, 2.2_

- [x] 7. データ閲覧 View
  - [x] 7.1 純VM→QAbstractItemModel アダプタの実装
    - `src/valisync/gui/adapters/__init__.py` と `src/valisync/gui/adapters/qt_signal_models.py` を作成
    - `ChannelBrowserVM` のツリー状態を `QAbstractItemModel` に橋渡し（信号メタを列に提供）
    - `tests/gui/test_qt_signal_models.py`（pytest-qt）: モデルの行/列/データが VM ツリーと一致
    - _Requirements: 4.1, 4.2_
  - [x] 7.2 Channel_Browser View の実装
    - `src/valisync/gui/views/channel_browser_view.py`: QDockWidget 内に QTreeView + アダプタ + 検索ボックス。検索→`set_filter`、選択→VM、トグル UI、信号 D&D の MimeData 生成（signal_key 群）
    - `tests/gui/test_channel_browser_view.py`（pytest-qt）: 検索絞り込み反映、複数選択、ドラッグ MimeData 生成
    - _Requirements: 4.3, 4.4, 4.5, 4.6, 12.2, 12.3_
  - [x] 7.3 Data_Explorer View の実装
    - `src/valisync/gui/views/data_explorer_view.py`: ツールバーから開く独立 `QMainWindow`。`QFileSystemModel` ベースのツリー、拡張子アイコン簡易判定、ダブルクリック/Enter/コンテキストメニューで `AppViewModel.request_load`、ソース追加/削除（persistence 連携）、OS からのファイル D&D 受理
    - `tests/gui/test_data_explorer_view.py`（pytest-qt）: ソース登録→ツリー表示、ダブルクリックで request_load 呼出、永続化往復
    - _Requirements: 1.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 12.1_

- [x] 8. グラフ View（タブ・分割・波形・ズーム/パン・LOD 描画）
  - [x] 8.1 Graph_Area View（タブ + パネル分割）の実装
    - `src/valisync/gui/views/graph_area_view.py`: QDockWidget 内に `QTabWidget`、各タブは `QSplitter`（垂直）で GraphPanelView を配置。タブ追加/削除/リネーム、パネル追加/削除、高さ比率ドラッグ
    - `tests/gui/test_graph_area_view.py`（pytest-qt）: タブ操作・パネル分割・最後の1つ拒否が VM と連動
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 6.1, 6.2, 6.3, 6.4, 6.6_
  - [x] 8.2 Graph_Panel View（PyQtGraph 波形 + 凡例 + LOD 描画）の実装
    - `src/valisync/gui/views/graph_panel_view.py`: `pyqtgraph.PlotWidget` ラッパ。GraphPanelVM の `render_data()` 結果を `PlotDataItem.setData` で描画、凡例（信号名↔色）、空信号は空グラフ+凡例。パネル幅変更→`set_panel_width`→再 render。信号ドロップ受理→`add_signal`
    - `tests/gui/test_graph_panel_view.py`（pytest-qt）: 信号追加で曲線描画、凡例表示、空信号、`QWidget.grab()` スクショ取得が成功
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 11.2, 12.4_
  - [x] 8.3 X/Y ズーム・パン（内側/外側ゾーン）と LOD 連動の実装
    - `graph_panel_view.py` にマウスハンドリング追加: X/Y 軸領域を内側/外側ゾーン分割、内側ドラッグ=範囲選択ズーム、外側ドラッグ=パン、ホイール=カーソル中心ズーム、ダブルクリック=リセット、ゾーン境界でカーソル形状変更。範囲確定→`set_x_range/set_y_range`→debounce 後 `render_data()` 再実行
    - debounce タイマ（~16-30ms）・キャッシュで 16ms 予算
    - `tests/gui/test_graph_panel_zoom.py`（pytest-qt）: 内側/外側ドラッグの範囲反映、ホイールズーム、ダブルクリックリセットが VM 範囲に反映
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.4_
  - [x] 8.4 X 軸同期の実装
    - `graph_area_view.py`: `x_sync_enabled` 時に同一エリア内全 GraphPanelView の ViewBox を `setXLink` 連結、無効時 `setXLink(None)`。同期トグル UI
    - `tests/gui/test_x_sync.py`（pytest-qt）: 同期 ON で 1 パネルのズームが全パネルへ伝播、OFF で独立
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 9. D&D・ビジー表示・コンテキストメニュー
  - [x] 9.1 BusyOverlay と読込ワーカーの実装
    - `src/valisync/gui/views/busy_overlay.py`: 不確定（インディターミネート）ビジー表示
    - `src/valisync/gui/workers/__init__.py` と `src/valisync/gui/workers/load_worker.py`: `QRunnable` で `Session.load` をオフスレッド実行し queued signal で完了通知。AppViewModel/LoadTask と接続、読込中 BusyOverlay 表示
    - `tests/gui/test_load_worker.py`（pytest-qt）: ワーカー実行→完了通知でツリー更新、読込中ビジー表示
    - _Requirements: 2.4, 2.5, 12.1_
  - [x] 9.2 ファイル/信号 D&D ワークフローの実装
    - OS ファイルマネージャ → Data_Explorer / Graph_Area への D&D 読込、Channel_Browser 信号 → Graph_Panel D&D（複数選択一括）、ドロップ領域ハイライト
    - `tests/gui/test_dnd_workflow.py`（pytest-qt）: 信号ドロップで波形追加、ファイルドロップで読込
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_
  - [x] 9.3 最小コンテキストメニューの実装
    - Channel_Browser 信号右クリック「アクティブ Graph_Panel に追加」、Data_Explorer ファイル右クリック「ファイル読み込み/データソースから除外」、Graph_Panel 空白右クリック「パネル追加/削除/全軸リセット」。状態に応じグレーアウト
    - `tests/gui/test_context_menus.py`（pytest-qt）: 各メニュー項目の表示・有効/無効・動作
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

- [x] 10. チェックポイント — 統合
  - 全 GUI テスト（VM + pytest-qt offscreen）green。`uv run pytest`・ruff・ruff format・mypy 通過。`valisync` エントリポイントで起動し、CSV/MDF4 読込→D&D→波形→ズーム/パン→LOD が動作

- [x] 11. 性能検証
  - [x] 11.1 LOD 描画性能ベンチ
    - 100 万点合成 Signal で `GraphPanelVM.render_data()` の所要時間とフレーム時間を計測するテスト/ベンチ。描画点数が `~2*panel_width_px` に有界であることを確認
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1", "0.2"] },
    { "id": 1, "tasks": ["1.1", "1.2"] },
    { "id": 2, "tasks": ["2.1", "2.2", "3.1", "3.2", "4.1"] },
    { "id": 3, "tasks": ["5"] },
    { "id": 4, "tasks": ["6.1", "6.2"] },
    { "id": 5, "tasks": ["7.1", "7.2", "7.3", "8.1"] },
    { "id": 6, "tasks": ["8.2", "8.3", "8.4"] },
    { "id": 7, "tasks": ["9.1", "9.2", "9.3"] },
    { "id": 8, "tasks": ["10", "11.1"] }
  ]
}
```

依存の要点:
- VM 層（1〜4）は Qt 非依存で先行実装し、チェックポイント 5 でヘッドレス検証
- View 層（6〜9）は対応する VM に依存。Graph_Panel 描画（8.2）→ ズーム/パン（8.3）→ X同期（8.4）の順
- adapters/qt_signal_models（7.1）は Channel_Browser View（7.2）の前提

## Notes

- **MVVM 境界の厳守**: `views/`・`adapters/`・`workers/` のみ Qt/PyQtGraph を import。`viewmodels/` は Qt 非依存。`gui/` 全体は `valisync.core.session.Session` と `valisync.core.models` のみ参照し、他コアモジュール（loaders/sync/formula/export/downsampler）を直接 import しない（R13.4）
- **テスト方針**: VM はヘッドレス unit/PBT。View は `pytest-qt`（`QT_QPA_PLATFORM=offscreen`）+ 必要に応じ `QWidget.grab()` スクショ。VM の `inspect()` を使い表示状態をピクセルなしで assert（AI エージェント実機テスト容易性, R13.6）
- **動的 LOD**: 描画ダウンサンプリングは必ず `Session.downsample` 経由（R11.5）。可視範囲スライスは `Session.signals()` が返す不変 Signal の timestamps に `np.searchsorted`。debounce/キャッシュで 16ms 予算
- **後続 sub-spec への申し送り**: 複数 Y 軸・X-Y プロット（`valisync-gui-axes`）導入時に GraphPanelVM の「単一共通 Y 軸」前提を Y 軸コレクションへ拡張する。信号→軸の関連を将来差し替え可能な形に保つ
- **構造変更ポリシー**: `gui/` 配下のサブパッケージ（viewmodels/views/adapters/workers/persistence）は design.md で承認済みの構成。新規追加が必要になればユーザー承認を取る
- 完了タスクは本ファイルのチェックボックスを `[x]` に更新する

### UI 配線の申し送り（コードレビュー 2026-06-02 抽出 → Task 10 で大半解消）

- ~~**MainWindow → Data_Explorer 起動**~~ → **Task 10 で解消**: `open_data_explorer()` が `DataExplorerView`（`load_handler=_load_file` 注入）を生成・表示（R1.5）
- ~~**Data_Explorer の Add Source ボタン**~~ → **Task 10 で解消**: `action_add_source` を `QFileDialog.getExistingDirectory`（`dir_chooser` 注入でテスト可）→ `add_source()` に接続（R3.4）。Remove Source ボタンも接続（現在のルートが登録済みソースなら除外）
- ~~**Data_Explorer の Remove/除外**~~ → **9.3 で実装済み**: ファイル右クリック「Remove from Data Sources」（R8.2）
- ~~**クロスビューシグナルの統合接続**~~ → **Task 10 で解消**: MainWindow が `add_to_panel_requested`→アクティブ Graph_Panel の `add_signal`（R14.1）、`file_dropped`→`LoadController` 非同期読込（R12.1）を接続。読込完了は `register_loaded`→"loaded" 通知→`channel_browser_vm.refresh` + `_refresh_panels`
- **残：OS ファイル D&D の実機到達**: `file_dropped`/`dropEvent` はユニット・offscreen 統合では検証済みだが、実機で子ウィジェットがドロップを先取りする可能性は実 GUI での手動確認が必要（offscreen スクショでは波形描画まで確認済み）
- **残：CSV 読込のフォーマット選択 UI**: 統合の読込経路は `session.load(path, None)` で **MDF4 のみ**対応。CSV は FormatDefinition が要るためフォーマット選択ダイアログが必要（後続 sub-spec / 別タスク）
- **残：「アクティブ Graph_Panel」はアクティブタブの先頭パネル**（MVP 簡易）。最後に操作したパネルを追跡する真の active-panel は後続で

### コードレビュー残課題（堅牢性・効率、2026-06-02）

- ~~**render キャッシュの Session 非追従**（`graph_panel_vm.py`）~~ → **Task 10 で解消**: `GraphPanelVM.refresh()`（cache invalidate + 通知）を追加し、MainWindow が読込完了の "loaded" 通知で全パネルに `refresh()` を呼ぶ（`_refresh_panels`）。初回 render 時未ロードだった信号も、ロード後に再描画される
- ~~**reset_x/reset_y の旧レンジ温存**（`graph_panel_vm.py`）~~ → **修正済み(2026-06-02)**: 対象なし時は range=None にクリアし、後続 add_signal の auto-fit を妨げない
- ~~**`tree()` の `split("::",1)` 無防備**（`channel_browser_vm.py`）~~ → **修正済み(2026-06-02)**: 区切り無しの名前は全名をグループキーにフォールバック（ブラウザ全体クラッシュを防止）
- **ズーム/パンのライブプレビュー + debounce 未実装**（`graph_panel_view.py`, Task 8.3）: 現状はジェスチャ確定時（ドラッグ release / ホイール 1 ノッチ）に 1 回だけ range を適用する方式。16ms 予算は VM の render キャッシュ + 点数有界で満たすが、ドラッグ中の連続プレビュー（debounce タイマ ~16-30ms）は未実装。R9.5/R10.5 の体感向上のための refinement として後続で対応可
- **ズーム/パンのピクセル→データ写像は best-effort**（`graph_panel_view.py` `_data_value`/`_plot_rect_in_widget`）: ジェスチャ→範囲の純ロジックは決定論的にテスト済み。Qt イベント→データ座標のグルーは offscreen 幾何依存のため smoke テストのみ。実機での精度は手動 verify（Task 10）で確認
- **X 軸同期は setXLink ではなく VM 伝播で実装（Task 8.4, 設計判断）**: tasks.md の実装ヒントは pyqtgraph `setXLink` だが、8.2/8.3 で確立した「VM が表示範囲の唯一の真実、View は refresh で viewbox に反映」という構造と setXLink（viewbox 直結）は衝突する（同期表示が VM と乖離し次の refresh で破れる）。代わりに `GraphAreaVM` が各パネルの "range" 通知を購読し、同期 ON のタブ内で `propagate_x_range` により兄弟パネル VM へ伝播（`_propagating` ガードで再帰防止）。headless テスト可能で構造的に一貫。R7.1-7.4 充足
- **GraphAreaView の全再構築**（`graph_area_view.py`）: notify 毎に全パネルを破棄→再生成（リーク自体は修正済み）。本物の GraphPanelView 投入後は差分更新が望ましい。**Task 8.2** で再検討
