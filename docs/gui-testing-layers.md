# GUI テストレイヤー（必須運用）

> **常時適用ルール**: GUI（PySide6 / pyqtgraph）側の機能・ユーザー操作を実装/変更するときは、本ドキュメントのレイヤー方針に従ってテストを書くこと。`docs/workflow.md` から参照される必須運用。

## 背景：なぜレイヤー分けするのか

PR #11 で、FileBrowser の「Remove File」右クリックメニューが**実 GUI で表示されない**不具合が発覚した。根本原因は `contextMenuEvent` をコンテナ（`FileBrowserView`）で override し、子 `QListView` からのイベント伝播に依存していたこと（アイテムビューは伝播しないため発火しない）。

問題は、当時のヘッドレステストが `contextMenuEvent` を**直接呼ぶ**／シグナルを**直接 emit する**ものだったため、**実イベント経路を迂回して「壊れているのにグリーン」**になっていた（false green）こと。

**教訓**: 「テストが見る経路」と「実ユーザー操作の経路」が一致していないと、テストは不具合を見逃す。これを防ぐため、GUI 操作の検証を 3 レイヤーに分け、入力に関わる箇所では実経路を必ず通す。（memory: `feedback_gui_verify_real_input`）

## 3 レイヤー

### Layer A — ヘッドレス・ユニット/状態検証（必須・CI）
- **何を**: VM/モデルのロジック、ウィジェットの構成・ポリシー・状態を直接 assert。例: `setContextMenuPolicy` が `CustomContextMenu` であること、`build_context_menu(row)` が正しいアクションを返すこと。
- **環境**: `QT_QPA_PLATFORM=offscreen`（`tests/gui/conftest.py`）。`uv run pytest` / CI で常時実行。
- **限界**: 「実際の入力イベントがその経路を起動するか」は検証しない。

### Layer B — ヘッドレス・実イベント経路検証（必須・CI）★今回の本命
- **何を**: 実際の Qt イベント（例 `QContextMenuEvent`）を `QApplication.sendEvent()` で**実ターゲット（viewport 等）へ送り**、ポリシー → シグナル → ハンドラの**実経路**が起動することを assert。シグナルを直接 emit しない。
- **なぜ**: 直接 emit はポリシー/配線が壊れていても通る（false green）。`sendEvent` 経由なら、ポリシー欠落などの経路破壊で**テストが落ちる**。実際、`setContextMenuPolicy` を外すと Layer B テストは赤、直接 emit のテストは緑のまま（＝検出漏れ）になることを確認済み。
- **環境**: offscreen で動く（イベント配送はレンダリング非依存）。`uv run pytest` / CI で常時実行。
- **実例**: `tests/gui/test_file_browser_view.py::test_right_click_on_row_opens_remove_menu_and_unloads`（ヘルパ `_send_context_menu_event`）。
- **限界**: OS が `QContextMenuEvent` を生成し正しいウィジェットへ届ける部分（OS→Qt 変換・ヒットテスト）は検証しない。

### Layer C — 実 OS 入力検証（オプトイン・ローカルのみ・CI 除外）
- **何を**: 物理カーソルを移動し**本物の OS 右クリック**（Win32 `mouse_event` / `SendInput`）を発行 → `QApplication.activePopupWidget()` でメニュー出現を assert（＋失敗時スクショを保存）。OS→Qt の最終経路まで含めて検証する。
- **環境**: **実ディスプレイ + Windows 必須**。`@pytest.mark.realgui` で**既定除外**、`--realgui` でオプトイン。配置は `tests/realgui/`（`tests/gui/` 配下の offscreen 強制を継承しないため、その外に置く）。
- **実行**: `uv run pytest --realgui tests/realgui/`（実行中、約1秒マウスカーソルを占有する）。
- **CI 不可の理由**: 実ディスプレイ・カーソル制御が必要で flaky、かつ Win32 依存。CI（Linux + xvfb）では `--realgui` 未指定 かつ 非 Windows のため**二重に自動スキップ**される。
- **注意点**: DPI 変換（論理→物理 = `* devicePixelRatioF()`）、ウィンドウ最前面化、マウス占有。回帰検出というより**経路の最終確認**用。
- **実例**: `tests/realgui/test_file_browser_realclick.py`。

### Layer C か Layer B かは「入力の出所」で決まる（偽装アンチパターン）

**`tests/realgui/` に置き `@pytest.mark.realgui` を付け `--realgui` で pass しても、それだけでは Layer C ではない。** `skip_unless_real_display()` は**プラットフォーム（offscreen か否か）しか見ない**ため、「skip されず pass」は「実プラットフォームで動いた」ことしか意味しない。判定境界は**入力の出所**:

| 入力手段 | 層 |
|---|---|
| 実 OS 入力: `_realgui_input.at()`（`SetCursorPos`+`mouse_event`）/`key()`/`drive_qdrag()` | **Layer C** |
| 合成: `qtbot.mouseClick`/`keyClick`/`mouseDClick`/`QTest`/`QApplication.sendEvent`/`action.trigger()` | **Layer B** |

`qtbot.mouseClick` は場所やマーカに関係なく合成（Layer B）。これを `tests/realgui/` に置くと**実ディスプレイに何も映らず**、OS→Qt のヒットテスト/配送を検証しないのに Layer C を騙る false-green になる（実際に踏んだ。memory: `gui_realgui_synthetic_click_mislabeled_layer_c`）。「場所＋マーカ＋--realgui で pass」を Layer C の代理基準にせず、**テスト本体が実入力プリミティブを使うかで判定**する。

**判定様式**: realgui は Claude/人が OS 入力を直接制御し、操作後の**スクリーンショットを目視して PASS/FAIL を確定**する（`grabWindow(0).save(...)`）。自動 assert は backstop で、合成では証明できない実結果はスクショ判定が本体（②）。

**機械的ガード**: `tests/gui/test_realgui_layer_c_contract.py` が全 `tests/realgui/test_*.py` を走査し、実入力プリミティブ（`at`/`key`/`drive_qdrag`）or `grabWindow` を使わない合成テストを **CI で落とす**（散文警告は現に見落とされたため機械化）。2026-07-08 に既知合成4つ（`test_open_flow`/`test_export_flow`/`test_tab_ui_flow`/`test_panel_source_flow`）を実 OS 入力へ移行し **allowlist を空にした（完全厳格化）**。以後 `tests/realgui/` に合成テストを置くと CI で落ちる。実キーは前面ウィンドウへ届くため実クリックで前面化してから発行し、実ダブルクリックは同一点2連打を `GetDoubleClickTime` 窓内に発行しつつ各イベント間で event loop を pump する（間隔ゼロの連打は OS が dblclick と認識しない・`test_diagnostics_dock_realinput.py::_double_click` の確立パターン）。

**MainWindow 系 realgui の QSettings 隔離**: MainWindow を構築する realgui は `save_state`/`_restore_state`/`recent_files` 経由で実 ValiSync 設定（ウィンドウ/ドック/Recent）を汚染しうる。`tests/gui/conftest.py` の隔離は `tests/realgui/` に効かないため、`tests/realgui/conftest.py` の autouse fixture が per-test 固有キーへ隔離する（`QT_QPA_PLATFORM=offscreen` は設定しない）。

### Layer C 専用ケース: D&D の実配送経路は合成イベントで再現できない

コンテキストメニュー（`QContextMenuEvent`）は `sendEvent` で viewport に届き Layer B で実経路を再現できる。しかし **D&D の実配送経路は合成 `QApplication.sendEvent` では再現できない**（実測済み）。

**背景**: `GraphPanelView` は「コンテナ (`GraphPanelView`) が DND 契約を持ち、子 `GraphicsLayoutWidget` は `setAcceptDrops(False)`」という設計になっている。実ドラッグでは Qt の DND マネージャが子→親へバブリングして親の `dropEvent` に届く。しかし合成 `sendEvent`（親 / 子 / viewport いずれに送っても）は `QApplication::notify` の D&D 特別処理により座標下の子（ドロップ無効）へ配送され、親に届かない。子の無いプレーン `QWidget` では `sendEvent(QDropEvent)` が `dropEvent` に到達し、`setAcceptDrops` 無しでは到達しないことも確認済み。

**テスト戦略の分割**:
- **ドロップ*ロジック*（ゾーン→VM メソッド: 上書き / Ctrl 追加 / 新規 / `_axis_drop_target` 等）**: `view.dropEvent(event)` を直接呼ぶハンドラ直叩きで **Layer A/B** 検証（`_zone_at` / `_axis_index_at` をスタブ、MIME はローカル保持）。
- **実ドロップ配送経路**（QDrag 起動＋ヒットテスト＋子→親バブリング＋`setAcceptDrops` 配線）: **Layer C（`--realgui`）でのみ検証**。

## 必須運用（GUI 実装時のルール）

| 変更の種類 | Layer A | Layer B | Layer C |
|---|---|---|---|
| VM / モデル / 純ロジック | **必須** | — | — |
| ウィジェット構成・状態 | **必須** | 該当すれば | — |
| **入力イベント→ハンドラ**（右クリック / D&D / キー / ドロップ 等） | **必須** | **必須** | 推奨（経路を新規実装/変更したとき） |

- 入力イベントに関わる修正では **Layer B を必ず追加**する（emit 直叩きで済ませない）。
- イベント経路（ポリシー・伝播・ヒットテスト）を新規実装/変更したら、リリース前や挙動が疑わしいときに **Layer C をローカル実行**して実機確認する。
- TDD: いずれのレイヤーも RED→GREEN で書く。特に Layer B は「壊れたコードで一度落ちる」ことを確認してから通す（systematic-debugging の検証手順）。

## realgui（Layer C）の実質性ルール（②）

realgui のアサーションは「**実経路でしか証明できない結果**」を検証すること。次を満たさないものは不可:

1. **Layer A/B で再チェック不能なものを対象にする** — OS→Qt 配送・ヒットテスト・**描画結果**。VM 状態の再チェックだけは Layer A と重複（naive）。
2. **「人間が何を見て合格と判断するか」を列挙**し、各観測項目を割り当てる:
   - **自動アサート可**（`QApplication.activePopupWidget()` でメニュー出現、ウィジェット可視/ジオメトリ、要素数）→ テスト内で直接 assert。
   - **視覚/描画**（ハイライト色・挿入線位置・dimmed source・波形 unclip）→ スクショ＋ `/verify` 観測（安定なら pixel サンプル）。
3. **「スクショ保存だけ・アサート無し」は禁止**。

> アンチパターン: 実ドラッグ後に `vm.axes[i].column` だけ assert ＋スクショ保存（VM 再チェック＝Layer A と重複、視覚結果は未検証）。

## realgui 証拠ゲート（①）

realgui は `--realgui` オプトイン＋CI 自動スキップで高頻度にスキップされ、「skipped」が「検証済み」と誤認される。これを断つため、GUI 入力経路（`src/valisync/gui/`）の変更は **merge 前に realgui 実行証拠を要求**する:

- 変更経路に対応する `tests/realgui/test_*.py` を `uv run pytest --realgui tests/realgui/test_X.py`（**該当のみ**）で実行し、pass ログ＋スクショを残す。視覚項目は `/verify` 観測で代替可。
- **環境制約（非 Windows・ディスプレイ無し）で実行できない場合は「ゲート未充足」**として扱う（`skipped` を緑＝検証済みと誤認しない）。
- 実行は `/gui-verify` スキルが scoped に自動化する。
- **重要 — realgui 証拠だけでは merge 可ではない**: 本ゲートは Layer C スライスのみを保証する。merge 前ゲート全体は **(a) full `uv run pytest` が 0 errors（headless A/B）＋ (b) 本 realgui 証拠 ＋ (c) CI 緑**。realgui scoped 実行はテスト間汚染（ある headless テストが次テストの isolation を壊す連鎖エラー）を構造的に検知できず、realgui 全 pass で「充足」でも CI が赤になり得る（実例: PR #19、`qtbot.addWidget` した widget の手動 `deleteLater` による teardown 二重削除 → 別テストへ連鎖。memory `gui_qtbot_addwidget_vs_manual_delete_cascade`）。

> 実際に Layer C を書くときの**駆動レシピ・落とし穴**は `.claude/skills/gui-verify/reference/realgui-recipe.md` 参照。

## false-green 落とし穴: render 経由で「データ移動」を検証する Layer A/B テスト

信号を時間方向にシフト/オフセットした結果を `render_data()` / `curve_xy()`（レンダ経路）で検証するテストの**二重トラップ**（R14 時間オフセットで3回踏んだ。memory: `gui_offset_render_test_xrange_pitfall`）:

- **症状**: fixture は `add_signal_to_axis` で `x_range` を元データ窓（例 0–0.29s）に auto-fit する。オフセット（例 +0.5s）でデータが窓外に出ると render は窓でクリップし**空配列**を返す→アサート失敗。
- **やりがちな誤修正（禁止）**: production の `set_offsets`/ブロードキャストで `x_range = None`（auto-range）を足してテストを通す。これは二重に悪い:
  1. **誤 UX**: オフセット適用は全パネルにブロードキャストされるため、適用のたびに全パネルのズーム/パンが飛ぶ。
  2. **false-green**: cache key に `x_range` が入るため、`x_range` 変化で**キャッシュキーが変わり**キャッシュが落ちる＝`_invalidate_cache()` を消しても/ブロードキャストが壊れていてもテストが通る。
- **正しい対処**: production はビューポート（`x_range`）を**触らない**。**テスト側で shifted データを含む広い `x_range` を明示固定**（例 `vm.x_range = (0.0, 1.5)`）してから検証する。これでシフトが可視化され、かつ `x_range` 不変＝無効化機構/ブロードキャストが唯一のバスト要因＝真のガードになる。
- **honest 検証**: 「無効化機構を一時的に壊すとテストが落ちる」（`_invalidate_cache` 除去でキャッシュテストが落ちる／ブロードキャストをタブ0限定にすると他タブが未シフトで落ちる）まで確認すると false-green を炙り出せる。

## false-green 落とし穴: move 駆動ジェスチャーは sendEvent で証明できない

押下中の **move イベントでデルタを積算するジェスチャー**（線/曲線ドラッグ移動・ラバーバンド等）を、`GraphPanelView`（プレーン QWidget）が子 `GraphicsLayoutWidget`（QGraphicsView）を内包する構成で実装したときの落とし穴（R14 オフセットドラッグで踏んだ。memory: `gui_realgui_move_not_reaching_parent_qwidget`）:

- **症状**: 実 OS ドラッグでは **press と release は親 GraphPanelView に伝播するが、押下中の move は子 QGraphicsView に消費され親に届かない**（実機スパイで move=0回／press・release=各1回を確認）。move 駆動の積算デルタが 0 のまま commit され、**実アプリで機能ゼロ**になる。X ズーム/パンが無傷なのは release 位置だけで完結し move 不要だから。
- **なぜ Layer B が見逃すか**: Layer B は `QApplication.sendEvent(view, MouseMove(...))` を**親へ直接**送るため move が必ず届く＝実プロパゲーション（子による消費）を迂回する。よって「move 不達」は**構造的に Layer C(realgui) でしか捕捉できない**。headless 全 pass でも実機機能ゼロになり得る。
- **正しい対処**: ジェスチャー開始で親が `grabMouse()`、終了/取消/Escape/対象除去の**全終了パス**で `releaseMouse()`（grab リーク＝アプリ凍結を防ぐため全パスで解放必須。modal を開く前に解放しないと dialog がマウス入力を取れない）。
- **テスト戦略の分割**: ①挙動（move が届きデルタが積算され適用される）＝ **Layer C(realgui) が真のゲート**。②回帰ガードは安価な Layer B で「grab/release のペアリング（リーク防止）」に留める（挙動は realgui に委ねる）。
- D&D の sendEvent 非再現（§「Layer C 専用ケース」）とは**別現象** — あちらは QDrag/drop の配送、これは押下中 move の親への伝播。

## false-green 落とし穴: 合成 mouseDClick は fresh な itemview で不発（warm-up click 必須）

itemview（QTableWidget 等）のダブルクリック経路を Layer B で検証するときの罠（gui-feedback-errors 第1弾・PR #37 の Diagnostics ドックで確立。memory: `gui_qtest_dblclick_warmup_click`）:

- **症状**: 表示直後の itemview へ単発 `qtbot.mouseDClick(table.viewport(), LeftButton, pos=visualItemRect(item).center())` を送っても `cellDoubleClicked` が安定発火しない（Qt 内部の `pressedIndex` が合成 release で消える QTest replay アーティファクト。production バグではない）。
- **対処**: 同一点への warm-up `qtbot.mouseClick` を前置する。**warm-up が対象シグナルを自力で発火させないことを sabotage 検証で確認**（対象 connect を一時的に外すとテストが落ちる＝warm-up 起因の false-green でない証明）してから通す。
- **Layer C（実 OS）は warm-up 不要**: 同一点2連打（間隔 < `user32.GetDoubleClickTime()`・MOVE 無し）で OS が WM_LBUTTONDBLCLK に変換する。実例: `tests/realgui/test_diagnostics_dock_realinput.py`。
- **事前条件（両レイヤー共通）**: `show()` 後に `qtbot.waitUntil(lambda: table.visualItemRect(item).height() > 0)` でレイアウト確定を待ってから座標算出。

## flake 落とし穴: オブジェクト再生成の検証に `id()` を使うと非決定フレーク

破棄→再生成（例 `ci.clear()` での ViewBox 作り直し）を「別オブジェクトになった」で検証するテストで `vb_before = id(obj)` を保存し `assert id(new) != vb_before` とすると**非決定的にフレーク**する（memory: `gui_id_reuse_flake_object_recreation`）:

- **症状**: ローカル/CI で運良く通過したり誤失敗したりする。実例 `test_graph_panel_cursor.py::test_delta_line_survives_axis_rebuild` が PR #27-29 で通過・PR #30 マージ後の main CI（Linux/3.13）で誤失敗し main を赤にした（production 無関係）。
- **なぜ**: `id()` はメモリアドレス。`id(int)` だけ保持すると旧オブジェクトへの参照が無く GC され、CPython が解放スロットを同サイズの新オブジェクトに再利用して `id(new) == id(old)` になる。`id()` の一意性は「同時生存オブジェクト間」のみ保証。
- **正しい対処**: オブジェクト**参照**を保持（`vb_before = obj`）してメモリを固定し、`assert new is not vb_before` で真の同一性比較にする（`is`/`is not` は id 再利用に頑健）。
- **honest 検証との関係**: このアサート自体が「実リビルドが起きた（ファストパス早期 return でない）」ことの false-green ガードなので、フレークで誤失敗すると別の本物の回帰を覆い隠す。決定的にすること。

## コマンド早見表

```bash
uv run pytest                          # Layer A+B（既定・CI と同じ。realgui は skip）
uv run pytest --realgui tests/realgui/ # Layer C（実ディスプレイ+Windows、マウス占有）
```

## 関連
- `docs/development.md` — 品質ゲート・offscreen テストの落とし穴
- `tests/gui/conftest.py`（offscreen 設定）/ `tests/conftest.py`（`--realgui` ゲート）/ `pyproject.toml`（`realgui` marker）
- 実例: `tests/gui/test_file_browser_view.py`（Layer A/B）, `tests/realgui/test_file_browser_realclick.py`（Layer C）
