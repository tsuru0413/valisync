# GUI テストレイヤー（必須運用）

> **常時適用ルール**: GUI（PySide6 / pyqtgraph）側の機能・ユーザー操作を実装/変更するときは、本ドキュメントのレイヤー方針に従ってテストを書くこと。`.kiro/steering/workflow.md` から参照される必須運用。

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

## 必須運用（GUI 実装時のルール）

| 変更の種類 | Layer A | Layer B | Layer C |
|---|---|---|---|
| VM / モデル / 純ロジック | **必須** | — | — |
| ウィジェット構成・状態 | **必須** | 該当すれば | — |
| **入力イベント→ハンドラ**（右クリック / D&D / キー / ドロップ 等） | **必須** | **必須** | 推奨（経路を新規実装/変更したとき） |

- 入力イベントに関わる修正では **Layer B を必ず追加**する（emit 直叩きで済ませない）。
- イベント経路（ポリシー・伝播・ヒットテスト）を新規実装/変更したら、リリース前や挙動が疑わしいときに **Layer C をローカル実行**して実機確認する。
- TDD: いずれのレイヤーも RED→GREEN で書く。特に Layer B は「壊れたコードで一度落ちる」ことを確認してから通す（systematic-debugging の検証手順）。

## コマンド早見表

```bash
uv run pytest                          # Layer A+B（既定・CI と同じ。realgui は skip）
uv run pytest --realgui tests/realgui/ # Layer C（実ディスプレイ+Windows、マウス占有）
```

## 関連
- `docs/development.md` — 品質ゲート・offscreen テストの落とし穴
- `tests/gui/conftest.py`（offscreen 設定）/ `tests/conftest.py`（`--realgui` ゲート）/ `pyproject.toml`（`realgui` marker）
- 実例: `tests/gui/test_file_browser_view.py`（Layer A/B）, `tests/realgui/test_file_browser_realclick.py`（Layer C）
