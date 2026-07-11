# E2E モデルとレイヤー（GUI テストの権威リファレンス）

> gui-test-plan / gui-verify が共有する**十分な E2E 検証の定義**とレイヤーモデル。自己完結（外部 doc 非依存）。

## なぜレイヤー分けするのか（背景・要点）

PR #11 で、FileBrowser の「Remove File」右クリックメニューが**実 GUI で表示されない**不具合が発覚した。真因は `contextMenuEvent` をコンテナで override し子 `QListView` からの伝播に依存していたこと（アイテムビューは伝播しない）。当時のヘッドレステストは `contextMenuEvent` を**直接呼ぶ**／シグナルを**直接 emit** していたため、**実イベント経路を迂回して「壊れているのにグリーン」**になっていた（false green）。

**教訓**: 「テストが見る経路」と「実ユーザー操作の経路」が一致しないとテストは不具合を見逃す。だから入力に関わる箇所は実経路を必ず通す。（memory: `feedback_gui_verify_real_input`）

## E2E スペクトル（何が「十分な E2E」か）

**E2E テスト = ユーザーがする実入力→実出力の経路を通し、実 observable を判定すること。** 検証対象で3タイプに分かれる。Layer A/B はその下位（構造は証明するが end-to-end observable は証明しない）。

| E2E タイプ | 実経路 | 判定 observable | 対象例 | 環境 |
|---|---|---|---|---|
| **入力経路 E2E**（realgui = Layer C） | 実 OS 入力→実 Qt 経路→実描画 | スクショ目視 ＋ `activePopupWidget`/可視/ジオメトリ assert | メニュー・D&D・キー・クリック（FU-01/04） | 実ディスプレイ＋Windows |
| **perf E2E** | 実コード経路を **prod スケール**（`prod_demo.mf4`・330k ch）で実行 | **実測 wall-clock / call-count** vs 目標 | perf（FU-08/11/16） | ヘッドレス可（プロファイル）＝GUI クリック不要でも"実スケール実経路"で E2E |
| **描画 E2E** | 実データで実プロットを描画 | **スクショ目視** | 描画の正しさ（FU-12） | 実ディスプレイ |

### 十分な E2E 検証の必須構成要素（この5つが揃って初めて十分）
1. **ジャーニー同定**: 変更が参加する実ユーザージャーニー（開く→ブラウズ→フィルタ→プロット→解析→閉じる）を diff でなくユーザー視点で特定。
2. **効果ごとに E2E タイプ＋実 observable を割当**（上表）。
3. **prod スケール必須**（perf/描画がスケールしうるなら `prod_demo.mf4`。小データは FU-11/12/16 を隠す）。
4. **observable はユーザーが実際に見る/体験する終状態**（嘘プロキシで代替しない）。
5. **カバレッジ完全性**: E2E 証拠が**変更したユーザー可視挙動を実経路で exercise** している（同名だが別コードを触るテストはカバレッジでない）。

### 「嘘プロキシ」（実 observable を代替してはいけない例）
- `QDockWidget.isVisible()` は**画面外/タブ裏でも True**（FU-04 の偽陰性計器）。画面内判定は `visibleRegion` ＋ 画面内グローバル矩形で行う（memory: `gui_isvisible_true_for_offscreen_hidden_dock`）。
- フィルタ検証の `setText()` 1回 ≠ 実打鍵（per-keystroke の debounce/キャッシュ/backspace/大小切替は setText では出ない）。
- 小データの perf 計測 ≠ prod スケール（FU-11 は 330k でのみ 17s フリーズが顕在化）。

## レイヤー A/B/C（E2E の下位ティア）

### Layer A — ヘッドレス・ユニット/状態検証（必須・CI）
VM/モデルのロジック、ウィジェットの構成・ポリシー・状態を直接 assert。環境 `QT_QPA_PLATFORM=offscreen`。**限界**: 実入力がその経路を起動するかは検証しない。

### Layer B — ヘッドレス・実イベント経路検証（必須・CI）
実 Qt イベント（例 `QContextMenuEvent`）を `QApplication.sendEvent()` で**実ターゲット（viewport 等）へ送り**、ポリシー→シグナル→ハンドラの**実経路**が起動することを assert。シグナルを直接 emit しない（直接 emit はポリシー破壊でも通る false green）。offscreen で動く。**限界**: OS→Qt 変換・ヒットテストは検証しない。

### Layer C — 実 OS 入力検証（= 入力経路 E2E・オプトイン・CI 除外）
物理カーソル移動＋**本物の OS 入力**（Win32 `mouse_event`/`SendInput`）→ `activePopupWidget()` 等で assert ＋**スクショ目視**。OS→Qt の最終経路まで検証。実ディスプレイ＋Windows 必須、`@pytest.mark.realgui` で既定除外、`--realgui` でオプトイン。配置は `tests/realgui/`。CI（Linux+xvfb）では二重に自動スキップ。

### Layer C か B かは「入力の出所」で決まる（偽装アンチパターン）
`tests/realgui/` に置き `@pytest.mark.realgui` を付け `--realgui` で pass しても、それだけでは Layer C ではない。判定境界は**入力の出所**:

| 入力手段 | 層 |
|---|---|
| 実 OS 入力: `_realgui_input.at()`（`SetCursorPos`+`mouse_event`）/`key()`/`wheel()`/`set_window_pos()`/`drive_qdrag()` | **Layer C** |
| 合成: `qtbot.mouseClick`/`keyClick`/`mouseDClick`/`QTest`/`QApplication.sendEvent`/`action.trigger()` | **Layer B** |

`qtbot.mouseClick` は場所やマーカに関係なく合成（Layer B）。`tests/realgui/` に置くと実ディスプレイに何も映らず OS→Qt を検証しないのに Layer C を騙る false-green になる（memory: `gui_realgui_synthetic_click_mislabeled_layer_c`）。**テスト本体が実入力プリミティブを使うかで判定**する。機械ガード: `tests/gui/test_realgui_layer_c_contract.py` が合成 realgui を CI で落とす。

## 必須運用表（GUI 実装時のレイヤー選定）

| 変更の種類 | Layer A | Layer B | 入力経路 E2E(C) | perf E2E | 描画 E2E |
|---|---|---|---|---|---|
| VM / 純ロジック（可視挙動不変） | **必須** | — | — | — | — |
| ウィジェット構成・状態 | **必須** | 該当すれば | — | — | — |
| **入力イベント→ハンドラ**（右クリック/D&D/キー/ドロップ） | **必須** | **必須** | **必須**（経路を新規/変更したとき） | — | — |
| **perf に影響**（描画/走査/キャッシュ） | 必須 | — | — | **必須**（prod スケール実測） | 該当すれば |
| **描画の正しさ**（レンジ/クリップ/色/線） | 必須 | — | — | — | **必須**（スクショ） |

## ②実質性ルール（realgui のアサーションは実経路でしか証明できない結果を検証）

1. **Layer A/B で再チェック不能なものを対象に** — OS→Qt 配送・ヒットテスト・**描画結果**。VM 状態の再チェックだけは Layer A と重複（naive）。
2. **「人間が何を見て合格と判断するか」を列挙**し各観測を割当:
   - **自動アサート可**（`activePopupWidget()`・可視/ジオメトリ・要素数）→ テスト内 assert。
   - **視覚/描画/実測**（ハイライト色・挿入線・dimmed source・波形 unclip・レイテンシ）→ スクショ/実測。
3. **「スクショ保存だけ・アサート無し」「VM 再チェックだけ」は禁止**（naive）。

## 計画関連 false-green 落とし穴（どの層が何を捕捉するか）

### render 経由で「データ移動」を検証する Layer A/B（x_range 罠）
シフト/オフセット結果を `render_data()`/`curve_xy()` で検証するとき: fixture は元データ窓に auto-fit するため、オフセットで窓外に出ると render が空配列を返し失敗。**誤修正禁止**＝production で `x_range=None`（ズーム飛び＋cache キー変化で false-green）。**正**＝テスト側で shifted を含む広い `x_range` を明示固定・production はビューポート不変（memory: `gui_offset_render_test_xrange_pitfall`）。

### 押下中 move 駆動ジェスチャーは sendEvent で証明できない
線/曲線ドラッグ移動等、押下中 move でデルタ積算するジェスチャーは、`GraphPanelView`（QWidget）が子 `GraphicsLayoutWidget`（QGraphicsView）を内包する構成で、**実 OS ドラッグの move が子に消費され親に届かない**（press/release は届く）。Layer B の `sendEvent(view, MouseMove)` は親へ直送するため必ず届き**実プロパゲーションを迂回＝false-green**。→ 挙動は **Layer C が真のゲート**、Layer B は grab/release ペアリング回帰に留める（memory: `gui_realgui_move_not_reaching_parent_qwidget`）。

### 合成 mouseDClick は fresh な itemview で不発
表示直後の itemview へ単発 `mouseDClick` は `cellDoubleClicked` が安定発火しない（QTest replay アーティファクト）。warm-up click 前置＋sabotage 検証。Layer C（実 OS）は同一点2連打（間隔 < `GetDoubleClickTime`）で不要（memory: `gui_qtest_dblclick_warmup_click`）。

### D&D の実配送は合成 sendEvent で再現不可
context-menu は `sendEvent` で viewport に届き Layer B 再現可。だが **D&D の実配送（QDrag＋ヒットテスト＋子→親バブリング）は合成イベントで再現不可**。ドロップ**ロジック**（ゾーン→VM）はハンドラ直叩き Layer A/B、**実配送経路**は Layer C のみ（memory: `gui_drag_drop_not_sendevent_reproducible`）。
