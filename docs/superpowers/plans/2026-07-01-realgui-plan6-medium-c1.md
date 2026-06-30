# realgui medium (M1-M5,M7,M10-M13) ＋ dock C1 Implementation Plan (Phase 6+7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 監査 doc の medium realgui（M1-M5, M7, M10-M13。M6 は Phase 5 で実装済み）を既存 realgui の拡張中心に追加し、唯一の実 production バグ C1（dock 復元 false-green）を Layer A で根本修正する。各 realgui は honest 検証（配線破壊で RED）を経る。

**Architecture:** 既存 realgui ファイル（test_offset_drag/test_global_cursor/test_multi_column_axis/test_active_axis_zoom_pan）へ実 OS 入力テストを追記、新規に X軸（test_x_axis_zoom_pan）とファイルドロップ（test_file_drop_realclick）を追加。C1 は `main_window.py` に `setObjectName` を付与し Layer A ラウンドトリップで保証。production 変更は C1（dock）と、M13（X軸 hover が親に届かない場合のみ viewport eventFilter）に限定。

**Tech Stack:** PySide6 / pyqtgraph / pytest / pytest-qt / ctypes(Win32)。共有 realgui 入力ヘルパ `tests/realgui/_realgui_input.py`（`drive_qdrag`/`at`/`LDOWN`/`MOVE`/`LUP`/`key`/`VK_ESCAPE`/`to_phys`/`skip_unless_real_display`）。

## Global Constraints

- 設計 spec: `docs/superpowers/specs/2026-06-30-realgui-coverage-expansion-design.md`（medium=87-93・low=95-97・C1=99-104）。一次根拠: `docs/realgui-coverage-audit.md`（M1-M13・C1）。
- **MVVM**: viewmodels に Qt/pyqtgraph を import しない。
- **honest 検証（①②の核）**: 各 realgui は配線破壊で RED になることを1度実証してから GREEN。RED→GREEN は実 win32 のみ証明可＝**コントローラ ①ゲート**（実装サブエージェントは headless 収集＋フルゲートまで・`--realgui` を実行しない）。
- **QDrag 駆動は `drive_qdrag`（背景 OS スレッド＋watchdog）**。`QTimer` 駆動禁止。
- realgui は `tests/realgui/`・module-level `pytestmark = pytest.mark.realgui`。Layer A（C1）は `tests/gui/`。
- **M5 honest 制約**: 実 Windows Explorer ドラッグは Win32 mouse_event で自動化不可（クロスプロセス OLE DoDragDrop）。**アプリ内 QDrag with URL mime**（同一 Qt OLE IDropTarget 経路を通る正当な substitute）で検証する。このトレードオフをテスト docstring に明記。
- **M13 honest 制約**: hover move が親 GraphPanelView に届くか不明（R14 型 move 到達リスク）。**RED-first**: テストを先に書き、hover が届かなければ即 RED＝production fix（viewport eventFilter）が必要、届けば fix 不要。判定はコントローラ①ゲート。
- コミットメッセージ末尾に必須トレーラ（`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k`）。
- コミット前ゲート: `uv run pytest`（headless 0 errors）/ `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。worktree なら先に `uv sync --extra dev`。

## File Structure

- Modify: `src/valisync/gui/views/main_window.py` — C1: file_dock/channel_dock に `setObjectName`。
- (contingent) Modify: `src/valisync/gui/views/graph_panel_view.py` — M13: hover が親に届かない場合のみ viewport eventFilter。
- Modify (test): `tests/gui/test_main_window.py`（C1 Layer A）、`tests/realgui/test_offset_drag.py`（M1/M2）、`tests/realgui/test_global_cursor.py`（M3）、`tests/realgui/test_multi_column_axis.py`（M4/M7）、`tests/realgui/test_active_axis_zoom_pan.py`（M11）。
- Create (test): `tests/realgui/test_x_axis_zoom_pan.py`（M10/M12/M13）、`tests/realgui/test_file_drop_realclick.py`（M5）。

**検証済みアンカー（map より）**: 各項目の production_path / honest_red / reuse は本プラン各タスクに転記。参照テンプレ: test_multi_column_axis.py（軸 QDrag・_CapturingView・drive_qdrag）、test_active_axis_zoom_pan.py（zoom/pan/hover sweep）、test_offset_drag.py（offset drag・_two_panel_area）、test_global_cursor.py（cursor 線ドラッグ）。

---

### Task 1: C1 dock 復元 false-green を Layer A で根本修正（production バグ）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_main_window.py`

**背景**: `main_window.py` が `saveState/restoreState` を使うのに file_dock/channel_dock に `setObjectName` が無く、`restoreState` がドック配置を黙って no-op にする（実機でドック復元不発）。現 `TestStatePersistence` は no-crash/title 一致しか見ず false-green。

- [ ] **Step 1: Layer A ラウンドトリップ RED テスト**（`tests/gui/test_main_window.py`、TestStatePersistence に追加）。dock 配置変更→`saveState`→新 MainWindow インスタンス→`restoreState`→`dockWidgetArea(file_dock)`/`isFloating` が一致を assert。setObjectName 無しでは restoreState が no-op で RED:

```python
def test_dock_layout_roundtrips_across_instances(self, qtbot) -> None:
    from PySide6.QtCore import Qt
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, w1.file_dock)  # move
    assert w1.dockWidgetArea(w1.file_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    state = w1.saveState()

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.restoreState(state)
    assert w2.dockWidgetArea(w2.file_dock) == Qt.DockWidgetArea.LeftDockWidgetArea, (
        "dock layout not restored — restoreState no-op (setObjectName missing?)"
    )
```

（実 dock 属性名・area enum は main_window.py を読んで確定。`file_dock`/`channel_dock` が実在することを確認。）

- [ ] **Step 2: RED 確認** → 当該テストが fail（dock が既定 area に戻る）。

- [ ] **Step 3: production 修正**（`main_window.py`）。各 dock 生成直後に一意 `setObjectName` を付与（map: file_dock は line 70 付近、channel_dock は line 80 付近・実コードで確認）:

```python
self.file_dock.setObjectName("file_dock")
# ... channel_dock など全 QDockWidget に一意名
self.channel_dock.setObjectName("channel_dock")
```

全 `QDockWidget`（および saveState 対象の toolbar 等があれば）に一意名を付ける。

- [ ] **Step 4: GREEN＋フルゲート**。当該テスト pass・既存 TestStatePersistence 無回帰／`uv run pytest`／ruff/format/mypy。

- [ ] **Step 5: Commit** — `fix(gui): dock に setObjectName を付与し restoreState 復元を有効化（C1 false-green 根治）`。

---

### Task 2: M4 同一列リオーダー＋M7 mid-drag フィードバック（test_multi_column_axis 拡張）

**Files:** Modify: `tests/realgui/test_multi_column_axis.py`

- **M4**: 2軸とも内側列 col=1 の状態から、`_y_axes[0]` の FRAME ゾーン（左端・上半分中央 y）を press、同 col=1 帯の下半分 y（`y > height*0.75`）へ `drive_qdrag`、`done=lambda: view.drop_seen`。drop 後: 軸順が入れ替わり（旧 top 軸が `top_ratio > 0.4`）、`_strip()` で描画反映を assert。**source/target x は col=1 帯**（`x ∈ [_Y_AXIS_FIXED_WIDTH, 2*_Y_AXIS_FIXED_WIDTH)`）に保つ。`set_active_axis(0)` 必須。honest RED（ゲート）: `_apply_deferred_axis_move`（graph_panel_view.py:1661）を `position=None` 固定にすると常に末尾追加で RED。
- **M7**: 既存 `_CapturingView.dragMoveEvent`（test_multi_column_axis.py:132）に mid-drag 状態捕捉を追加: `view.mid_line_visible = view._axis_move_line.isVisible()`、`view.mid_source_opacity = view._y_axes[0].opacity()`。drive_qdrag 後: `mid_line_visible or mid_highlight_visible` が True（オレンジ挿入線/空列ハイライト描画）、`mid_source_opacity == pytest.approx(0.35, abs=0.01)`（source dimmed）を assert。honest RED: `_update_axis_move_feedback`（graph_panel_view.py:1641）をコメントアウト。

- [ ] **Step 1: M4/M7 テスト追記**（実 API・属性名 `_axis_move_line`/`opacity()`/`_strip` を実コードで確認・調整）。
- [ ] **Step 2: ヘッドレス収集＋フルゲート**（realgui skip・既存 multi_column 無回帰）／ruff/format/mypy。
- [ ] **Step 3: Commit** — `test(realgui): M4 同一列リオーダー＋M7 mid-drag フィードバック`。

---

### Task 3: M3 R17 統計ライブ再計算＋判読スクショ（test_global_cursor 拡張）

**Files:** Modify: `tests/realgui/test_global_cursor.py`

- **M3**: `vm.toggle_main_cursor(True)`＋`vm.toggle_delta(True)` で A/B 両線表示。B 線（rect 75%）を `at` LDOWN/MOVE steps/LUP で右へドラッグ、mid-drag で `processEvents`＋`view._readout.row_texts()` が数値統計を含む（`範囲外`/`データなし` でない）を assert。最後に `QApplication.primaryScreen().grabWindow(0)` を `tmp_path/'stats_live.png'` に保存（/verify 判読確認）。honest RED: `sigPositionChanged`→`_on_cursor_line_b_dragged` の connect（graph_panel_view.py:1122）を切ると stale stats で RED。

- [ ] **Step 1: M3 テスト追記**（`_readout.row_texts` 等の実 API 確認）。
- [ ] **Step 2: 収集＋フルゲート**／ruff/format/mypy。
- [ ] **Step 3: Commit** — `test(realgui): M3 R17 範囲統計ライブ再計算＋判読スクショ`。

---

### Task 4: M1 Escape キャンセル＋M2 カーソル線×曲線オーバーラップ routing（test_offset_drag 拡張）

**Files:** Modify: `tests/realgui/test_offset_drag.py`

- **M1**: `_two_panel_area()` 流用。曲線を `at(gx,gy,LDOWN)`＋MOVE steps、LUP 前に `key(VK_ESCAPE)`。assert: 状態クリア（`_offset_drag_key is None`・pen 復元・tooltip 非表示・grab 解放）かつ **apply ダイアログが開かない**。honest RED: keyPressEvent の Escape 処理（graph_panel_view.py:1608-1610）除去 or grabMouse（1457）除去。
- **M2**: カーソル A 線を既知 data_x（`vm.set_cursor(t_line)`）に置き、その x を通る曲線を用意。重なり点を `to_phys` で press。assert: `_curve_at` が None を返し（線ガード成功）offset drag が始まらない（`_offset_drag_key` は None・pen 非ハイライト）。honest RED: カーソル線ガード（graph_panel_view.py:1407-1408）除去で曲線が先に当たり offset drag が始まる。

- [ ] **Step 1: M1/M2 テスト追記**（重なり座標・apply ダイアログ抑止の確認。M2 は absence assert なので honest RED でガード除去時に確実に GREEN→RED 反転することをゲートで確認）。
- [ ] **Step 2: 収集＋フルゲート**／ruff/format/mypy。
- [ ] **Step 3: Commit** — `test(realgui): M1 Escape キャンセル＋M2 カーソル線×曲線 routing`。

---

### Task 5: M10 X軸ズーム/パン＋M12 X軸クロスパネル同期（新規 test_x_axis_zoom_pan）

**Files:** Create: `tests/realgui/test_x_axis_zoom_pan.py`

- **M10**: `make_two_axis_panel()`（set_active_axis 不要・X zoom/pan は常時）。X strip = `view._x_axis.sceneBoundingRect()`。ZONE_X_INNER（上半分 y=strip_top+0.25h）水平ドラッグ→`(x_range 幅) < 0.9*元`（zoom）。ZONE_X_OUTER（y=strip_top+0.75h）→幅不変＋center シフト（pan）。`at` LDOWN/MOVE/LUP。honest RED: mousePressEvent の ZONE_X 分岐（graph_panel_view.py:1573-1575）コメントアウトで `_drag_zone` 未設定→release で apply されず x_range 不変。
- **M12**: `_two_panel_area()`（test_offset_drag.py:56-114）2パネル。panel0 の X strip を同様にドラッグ→`panels[0].vm.x_range == panels[1].vm.x_range`（同期）かつ元と異なる（実 zoom）を assert。honest RED: `area_vm.set_x_sync(0, False)` で propagate されず RED。

- [ ] **Step 1: M10/M12 テスト作成**（X strip 座標・ZONE_X 判定・x_sync API を実コードで確認。X AxisItem が左 press を消費しないことを実機で確認＝notes）。module-level `pytestmark = pytest.mark.realgui`。
- [ ] **Step 2: 収集＋フルゲート**／ruff/format/mypy。
- [ ] **Step 3: Commit** — `test(realgui): M10 X軸ズーム/パン＋M12 X軸クロスパネル同期`。

---

### Task 6: M13 X軸/プロットゾーン hover カーソル（RED-first・production fix は条件付き）

**Files:** Modify: `tests/realgui/test_x_axis_zoom_pan.py`（＋条件付き `src/valisync/gui/views/graph_panel_view.py`）

- **M13**: hover sweep（test_active_axis_zoom_pan.py:145-162 の incremental MOVE＋6回リトライ）を X strip 上で実行→`view.cursor().shape() == Qt.CursorShape.SizeHorCursor`（親ウィジェットの cursor）。ZONE_PLOT は ArrowCursor。**RED-first**: まず production 変更なしで書く。hover move が親に届かなければ即 RED＝**production fix**（`plot_widget.viewport().installEventFilter(self)`＋`eventFilter` で押下なし MouseMove を `self.mouseMoveEvent` へ転送、graph_panel_view.py ~687 付近）を追加して GREEN。届けば fix 不要で、honest RED は `setCursor` 呼び（~1588）コメントアウト。**どちらになるかはコントローラ①ゲートで判定**。

- [ ] **Step 1: M13 hover テスト追記**（production 変更はまだしない＝RED-first。実 cursor API・hover sweep を確認）。
- [ ] **Step 2: 収集＋フルゲート**（headless では realgui skip）／ruff/format/mypy。
- [ ] **Step 3: Commit** — `test(realgui): M13 X軸/プロットゾーン hover カーソル（RED-first）`。
- [ ] **(ゲートで hover 不達が判明した場合) production fix を別 commit** — `fix(gui): plot viewport の hover move を親へ転送（M13 SizeHor カーソル）`＋必要なら Layer B eventFilter テスト。

---

### Task 7: M11 動的 LOD 描画（test_active_axis_zoom_pan 拡張）

**Files:** Modify: `tests/realgui/test_active_axis_zoom_pan.py`

- **M11**: 5000点信号のパネルを狭幅（`setGeometry(300,300,200,600)`）で表示→`vm.lod_active is True` かつ `len(panel._items[key].getData()[0]) <= 2*vm.panel_width_px + 10`（View が LOD 縮約配列を適用）。スクショ保存。広幅（1600）へ resize→`len(item.getData()[0])` が増加（LOD 緩和）。スクショ保存（密度変化の視覚証拠）。ドラッグ不要（resizeEvent 駆動）。honest RED: `item.setData(curve.timestamps, curve.values)`（graph_panel_view.py:785）を生配列に変えると点数が `2*width` 超で RED。

- [ ] **Step 1: M11 テスト追記**（`panel._items`/`getData`/`vm.lod_active`/`vm.panel_width_px` の実 API 確認。large signal fixture）。
- [ ] **Step 2: 収集＋フルゲート**／ruff/format/mypy。
- [ ] **Step 3: Commit** — `test(realgui): M11 動的 LOD 描画（getData 点数＋resize 密度変化）`。

---

### Task 8: M5 シェルファイルドロップ（新規 test_file_drop_realclick・アプリ内 QDrag URL mime）

**Files:** Create: `tests/realgui/test_file_drop_realclick.py`

- **M5**: 実 Explorer ドラッグは自動化不可ゆえ**アプリ内 QDrag with `QUrl(local_file)` mime** で代替（同一 Qt OLE IDropTarget 経路）。ヘルパ QWidget が mouseMoveEvent で `QDrag`＋URL mime を起動。`at(src,LDOWN)`＋`at(tgt,MOVE)`＋`at(tgt,LUP)` で GraphAreaView へドロップ。`file_dropped` シグナルを list に接続し `== [str(local_file)]` を assert。honest RED: `GraphPanelView.dragEnterEvent` の else 分岐（graph_panel_view.py:1632）`event.ignore()`→`accept()`（子が URL drag を食う）or GraphArea の `setAcceptDrops(True)`（graph_area_view.py:62）除去で親 dropEvent 不達→RED。docstring に「実 Explorer ドラッグ非自動化・アプリ内 QDrag は同一 OLE 経路の正当 substitute」を明記。

- [ ] **Step 1: M5 テスト作成**（アプリ内 QDrag ヘルパ・URL mime・file_dropped シグナル・GraphAreaView 構築を実コードで確認）。module-level `pytestmark = pytest.mark.realgui`。
- [ ] **Step 2: 収集＋フルゲート**／ruff/format/mypy。
- [ ] **Step 3: Commit** — `test(realgui): M5 シェルファイルドロップ（アプリ内 QDrag URL mime substitute）`。

---

## コントローラ ①ゲート（実 win32・honest RED→GREEN）＋ finishing

実装完了後、コントローラが `/gui-verify` を実 win32 実行（**ユーザーに席を外す確認**・各段外部 watchdog）。C1 は Layer A ゆえ headless full に含まれカーソル不要。

1. **GREEN**: 新設/拡張 realgui を実 win32 で全 pass・ハング無し。証拠ログ＋スクショ（M3/M7/M11 等の視覚は /verify 観測）。
2. **honest RED（各項目1度）**: 各 honest_red（M1 Escape 除去／M2 線ガード除去／M3 connect 切／M4 position=None／M7 feedback 除去／M10 ZONE_X 分岐除去／M12 set_x_sync False／M11 LOD bypass／M5 dragEnter accept）で当該 realgui が RED→復元。**M13 は hover 不達なら production fix を入れて GREEN・入れて honest RED**（fix の有無をゲートで決定）。
3. **全 realgui 無回帰**: `uv run pytest --realgui tests/realgui/ -v` → Phase 1-5 の 23 件＋本 Phase の新規/拡張＝全 pass・ハング無し。
4. ゲート判定: (a) headless full 0 errors（C1 含む） (b) realgui 証拠（GREEN＋RED） (c) CI 緑。3点充足で finishing（push + PR）。

---

## Self-Review

**1. Spec coverage（medium M1-M13 ＋ C1）**: M1/M2=Task4・M3=Task3・M4/M7=Task2・M5=Task8・M10/M12=Task5・M11=Task7・M13=Task6・C1=Task1。M6 は Phase 5 済み。low は high リスクテスト内の mid-drag/mid-hover スクショ＋/verify 相乗り（M7/M3/M13 に内包）。✔

**2. Placeholder scan**: 各タスクに target file・gesture・assertion・honest_red・production_change を map から転記。realgui は proven テンプレ（test_multi_column_axis/test_active_axis_zoom_pan/test_offset_drag/test_global_cursor）の delta として実装＝実装者がテンプレを読んで具体化。C1 production は exact code。✔

**3. リスク/特記**: (a) **C1 が唯一の実バグ**＝最優先・Layer A・カーソル不要。(b) **M13 は production fix 条件付き**（hover 不達なら eventFilter・RED-first でゲート判定）。(c) **M5 は実 Explorer 非自動化**＝アプリ内 QDrag URL mime の正当 substitute（docstring 明記）。(d) M2 は absence assert ゆえ honest RED（ガード除去で GREEN→RED）をゲートで必ず確認。(e) 全 D&D realgui は drive_qdrag、その他は手動 at()＝QDrag でないジェスチャ（zoom/pan/hover/resize）。(f) realgui の実 win32 GREEN/RED はコントローラ①ゲート。
