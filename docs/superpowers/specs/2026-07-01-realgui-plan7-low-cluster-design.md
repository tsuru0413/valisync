# realgui カバレッジ拡充 Plan 7（最終・low クラスタ＋C3 ② 昇格）設計

> 設計 spec。一次根拠: [docs/realgui-coverage-audit.md](../../realgui-coverage-audit.md)（優先度 low = 63-67 行 / C3 caveat = 75 行）。
> 前提: high（H1-H8）・medium（M1-M13、M6→クロスパネル軸移動 P5・M8/M9→H5 統合）・dock C1 は完了・マージ済（PR #27-30 / #33 / #34）。本 Plan で realgui 拡充を完了させる。

## 目的

監査の未消化＝優先度 **low クラスタ**（ドロップ青枠ハイライト・非アクティブ軸 hover 仮フレーム・grip 掴み・DataExplorer OS ファイルドロップ）と **C3 caveat**（既存 realgui の load-bearing assert が VM 状態止まり）を消化し、realgui カバレッジ拡充を完了する。**production 変更なし**（realgui 新規1本＋既存 realgui の assert 強化のみ）。

## 方針（honest layering）

- 全 realgui は Layer C（`--realgui`・honest-RED 付き）。各追加/強化は「配線破壊で RED になる」ことをコントローラ実機 win32 ①ゲートで実証する。
- 「相乗り」と分類された視覚項目は**現状 assert されていない＝想定にすぎない**。本 Plan で **assert 可能な状態（描画を駆動する bool / index）まで踏み込んで honest 化**する（ユーザー判断: 完全 assert 化）。純粋な見た目のみスクショ＋`/verify` 観測。
- 既存の realgui 掴み点・ウィンドウ配置は memory `gui_realgui_zone_widgetspace_and_offscreen_clamp` に従う（classify_zone と同じ widget 空間で座標算出・`availableGeometry` 内配置）。

## コンポーネント（4項目）

### 1. DataExplorer OS ファイルドロップ realgui（新規1本）

**対象経路**: `src/valisync/gui/views/data_explorer_view.py`
- `setAcceptDrops(True)`（R12.1・80 行）→ `dragEnterEvent(hasUrls)`（154）→ `dropEvent`（166）が各 URL を `url.toLocalFile()` → `self._load_handler(local)`（172-174）で読み込む。`_load_handler` はダブルクリック（150）／「Load File」メニュー（185）と同一ハンドラ。

**テスト**（新規 `tests/realgui/test_data_explorer_file_drop.py`、`pytestmark = pytest.mark.realgui`）:
- M5（`test_file_drop_realclick.py`）と同型。実 Explorer は cross-process OLE で自動化不可のため、**アプリ内 QDrag with URL mime**（`QMimeData.setUrls([QUrl.fromLocalFile(...)])`）を `_UrlSource(QWidget)` から起動し、`drive_qdrag`（bg スレッド＋watchdog・非 QTimer）で DataExplorer へ steer。
- `_load_handler` を spy（差し替え or wrap）し、**ドロップしたローカルパスで呼ばれたこと**を assert（`Path.resolve()` 正規化・呼出1回）。
- **honest-RED**: `dragEnterEvent` の `hasUrls` 受理を `event.ignore()` 化 → ドロップ不達 → `_load_handler` 未呼出 → RED。
- docstring に「実 Explorer 非自動化ゆえアプリ内 QDrag URL mime substitute＝同一 IDropTarget 経路」を明記。

### 2. low 視覚項目の完全 assert 化（既存 realgui 強化）

現状 assert されていない2つを mid-gesture で honest 化する。

**(2a) ドロップ青枠ハイライト**（`graph_panel_view.py`: `is_drop_highlighted()`=1646・`_drop_active`=644・`_set_drop_highlight`=1650、border stylesheet）:
- `tests/realgui/test_signal_dnd_realclick.py` の信号 D&D 経路で、ドラッグ中に `panel.is_drop_highlighted() is True`（＋`panel.styleSheet()` に border を含む）を **mid-drag 捕捉**、ドロップ後 `is_drop_highlighted() is False` を assert。捕捉は `drive_qdrag` の waypoint コールバック（`done`/中間）か `_CapturingView` 拡張で（M7 の mid-drag 捕捉パターン踏襲）。
- **honest-RED**: `_set_drop_highlight` を no-op 化 → mid-drag で False → RED。

**(2b) 非アクティブ軸 hover 仮フレーム**（`graph_panel_view.py`: `_AlignedAxisItem.paint` が `_is_active_or_hover()`=328 で仮フレーム描画・`set_hover_axis`=1071・`_hover_axis_index`=660）:
- 2軸パネルで**非アクティブ軸**を hover（実 OS の小刻み MOVE スイープ・memory `gui_realgui_hover_needs_incremental_move`）→ `view._hover_axis_index == 非アクティブ軸 index` を **mid-hover assert**（＝仮フレーム paint を駆動する状態）＋スクショ。
- 仮フレームは即時モード paint（別 QGraphicsItem でない）ため `isVisible()` は持たない。**描画を駆動する `_hover_axis_index` が最も honest な assert 代理**。純粋な見た目はスクショ＋`/verify`。
- **honest-RED**: `set_hover_axis` を no-op 化 → `_hover_axis_index` 更新されず → RED。
- 新規小テスト `tests/realgui/test_axis_hover_frame.py` に置くか既存 hover テストに追記（実装プランで確定）。

### 3. C3 ② 昇格（既存テスト強化）

**対象**: `tests/realgui/test_move_then_resize.py::test_first_resize_after_axis_move_works`
- 現状 load-bearing assert は VM `view.vm.axes[0].height_ratio`（90/114 行）のみ＝②的 borderline（描画結果を保証しない）。
- **描画ジオメトリ assert を追加**: resize 前後で対象軸の viewbox 実描画高（`view._view_boxes[0].sceneBoundingRect().height()`、または対象軸に対応する viewbox の高さ）が縮小したことを assert。VM 状態でなく**実際に描画されたジオメトリ**が変化したことを保証。既存の VM assert は残す（二重保証）。
- honest-RED（記録）: 既存の stale-scene バグ再現（scene drag 状態リセットを外す）で RED（既存テストの主眼と同じ）。描画 assert 追加により「VM は変わったが描画は no-op」型 false-green も塞ぐ。

### 4. grip_hit_area_grabbability（記録のみ）

- 既存の resize/zoom/move realgui（`test_active_axis_resize.py`・`test_multi_column_axis.py` 等）が具体点掴みで実質カバー済み。**新規テスト不要**。監査に「covered（既存 grip ドラッグ realgui が具体点掴みで実証）」と記録更新のみ。

## テスト戦略 / ゲート

| 項目 | レイヤー | 新規/強化 | honest-RED |
|---|---|---|---|
| 1 DataExplorer ドロップ | C | 新規1本 | dragEnter ignore 化 |
| 2a ドロップ青枠 | C | 既存強化 | _set_drop_highlight no-op |
| 2b 軸 hover 仮フレーム | C | 新規/追記 | set_hover_axis no-op |
| 3 C3 描画ジオメトリ | C | 既存強化 | scene リセット除去（既存主眼） |
| 4 grip | — | 記録のみ | — |

- merge 前に `/gui-verify` ①証拠ゲート: 新規/強化分の GREEN＋各 honest-RED 実証＋全 realgui 無回帰。コントローラが実機 win32 実行（席を外す確認必須）。
- 品質ゲート: `uv run pytest`（0 errors・realgui は headless skip）／ruff check／ruff format --check／mypy src/。
- MVVM 維持（本 Plan は production 変更なし・テストのみ）。

## 完了条件

- realgui テスト本数が現 16 ファイル / 34 テストから、上記 1・2b（＋2a は既存強化）分増加。
- 監査 `docs/realgui-coverage-audit.md` の low クラスタ・C3 を「covered / 昇格済」に更新。
- realgui カバレッジ拡充（横断）を完了とし、`docs/roadmap.md`・CLAUDE.md の Phase 状況を更新。

## スコープ外（YAGNI）

- production 挙動変更（本 Plan は検証のみ）。
- low 相乗りのうち純粋な見た目（フレーム描画の色/角丸の外観）を pixel 単位で assert すること（スクショ＋`/verify` に委ねる）。
- 監査 high/medium の再検証（PR #27-34 で完了・実機ゲート充足済）。
