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

## コマンド早見表

```bash
uv run pytest                          # Layer A+B（既定・CI と同じ。realgui は skip）
uv run pytest --realgui tests/realgui/ # Layer C（実ディスプレイ+Windows、マウス占有）
```

## 関連
- `docs/development.md` — 品質ゲート・offscreen テストの落とし穴
- `tests/gui/conftest.py`（offscreen 設定）/ `tests/conftest.py`（`--realgui` ゲート）/ `pyproject.toml`（`realgui` marker）
- 実例: `tests/gui/test_file_browser_view.py`（Layer A/B）, `tests/realgui/test_file_browser_realclick.py`（Layer C）
