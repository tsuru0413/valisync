# ①証拠ゲートと実行関連 false-green 落とし穴

> gui-verify が自己完結で参照する権威リファレンス（外部 doc 非依存）。①realgui 証拠ゲートの手順・E2E スペクトルと入力の出所・実行時に「壊れているのに緑」を出す落とし穴集。

## E2E スペクトル（実 observable の種類）

**E2E テスト = ユーザーの実入力→実出力の経路を通し、実 observable を判定すること。** 検証対象で3タイプ。Layer A/B はその下位（構造は証明するが end-to-end observable は証明しない）。

| E2E タイプ | 実経路 | 判定 observable | 環境 |
|---|---|---|---|
| **入力経路 E2E**（realgui = Layer C） | 実 OS 入力→実 Qt 経路→実描画 | スクショ目視 ＋ `activePopupWidget`/可視/ジオメトリ | 実ディスプレイ＋Windows |
| **perf E2E** | 実コード経路を **prod スケール**（330k ch）で実行 | 実測 wall-clock / call-count vs 目標 | ヘッドレス可 |
| **描画 E2E** | 実データで実プロット描画 | スクショ目視 | 実ディスプレイ |

### 嘘プロキシ（実 observable を代替してはいけない）

- `QDockWidget.isVisible()` は**画面外/タブ裏でも True**（FU-04 の偽陰性計器）。画面内判定は `visibleRegion` ＋画面内グローバル矩形（memory `gui_isvisible_true_for_offscreen_hidden_dock`）。
- フィルタ検証の `setText()` 1回 ≠ 実打鍵（per-keystroke の debounce/キャッシュ/backspace/大小切替は出ない）。
- 小データ perf ≠ prod スケール（FU-11 は 330k でのみ 17s フリーズ）。

## ①証拠ゲート手順（scoped realgui ＋ headless full ＋ CI）

realgui は `--realgui` オプトイン＋CI 自動スキップで高頻度にスキップされ「skipped＝検証済み」と誤認される。変更に対応する分だけ scoped に実行・証拠化して誤認を断つ。

1. **変更経路を特定**: `git diff --name-only main...HEAD -- src/valisync/gui/`（未コミットは `git status --short` 併用）。
2. **該当 realgui をマッピング**: `tests/realgui/test_*.py` を全列挙し、各本文が変更ファイルのモジュール/ウィジェット/関数名を参照するかで対応付け（`grep -l <識別子>`・固定表に頼らない・1変更が複数に対応し得る）。対応 realgui が無い経路はフラグ（黙って pass しない・`realgui-recipe.md` で追加するか観測のみで足る理由を明記）。**クロスカット変更**（`QApplication`/共有祖先への `installEventFilter`・グローバルショートカット等）は名前マッピング不成立（全ウィジェットの入力に介入）→ 介入コンテナ内の入力経路 realgui クラスタ**全実行**＋**介入＋祖先チェーン実在の組立てハーネスで既存ジェスチャ完遂の証拠を最低1本**。「bare ハーネスは非曝露＝除外」は逆（検出不能なだけで安全ではない・FU-15）。
3. **scoped 実行 ＋ headless full**: worktree なら先に `uv sync --extra dev`。realgui は該当のみ `uv run pytest --realgui tests/realgui/test_X.py -v`。headless 全体 `uv run pytest`（**0 errors**）を必ず回す（realgui scoped はテスト間汚染を検知しない・memory `gui_qtbot_addwidget_vs_manual_delete_cascade`）。
4. **CI 緑**（push 済みなら確認）。
5. **skip≠検証済み**: 非 Windows・ディスプレイ無しで realgui を実行できないなら未充足（`skipped` を緑と数えない）。

### Layer C か B かは「入力の出所」で決まる

`tests/realgui/` に置き `@pytest.mark.realgui` を付け `--realgui` で pass しても、それだけでは Layer C ではない。判定は**入力の出所**:

| 入力手段 | 層 |
|---|---|
| 実 OS 入力: `_realgui_input.at()`（`SetCursorPos`+`mouse_event`）/`key()`/`wheel()`/`set_window_pos()`/`drive_qdrag()` | **Layer C** |
| 合成: `qtbot.mouseClick`/`keyClick`/`mouseDClick`/`QTest`/`QApplication.sendEvent`/`action.trigger()` | **Layer B** |

合成を `tests/realgui/` に置くと実ディスプレイに何も映らず OS→Qt を検証しないのに Layer C を騙る false-green（memory `gui_realgui_synthetic_click_mislabeled_layer_c`）。機械ガード `tests/gui/test_realgui_layer_c_contract.py` が合成 realgui を CI で落とす。

## 実行関連 false-green 落とし穴

### app レベル event filter は祖先バブルで誤発火・合成 notify/部分組立ては見逃す（FU-15 退行）
実クリック1回で `MouseButtonPress` は複数配送（QWindow→target→未 accept なら**親バブルで介入コンテナの祖先へも**）。`QApplication` フィルタは全配送を観測し「subtree 外なら解除」型条件は**祖先配送で誤発火**（FU-15: 軸上 press が自らアクティブ軸を解除→ジェスチャ全滅・純クリックだけ release 後勝ちで生存）。合成 `notify(target, ev)` は1配送のみ・bare ハーネスはフィルタ未設置・介入コンテナ top-level 化は祖先消失でバブル停止＝いずれも構造的 false-green。非発火側の検証は実 `MainWindow` 組立て＋実 OS 入力のみ。

### D&D の実配送は合成 sendEvent で再現不可（Layer C 専用）
context-menu は `sendEvent` で viewport に届き Layer B 再現可。だが **D&D の実配送（QDrag＋ヒットテスト＋子→親バブリング）は合成イベントで再現不可**。ドロップ**ロジック**（ゾーン→VM）はハンドラ直叩き Layer A/B、**実配送経路**は Layer C のみ（memory `gui_drag_drop_not_sendevent_reproducible`）。駆動は `realgui-recipe.md`。

### `id()` によるオブジェクト再生成検証は非決定フレーク
再生成を検証するのに `id()` を使うと CPython のアドレス再利用で非決定に緑/赤が揺れる（main CI 赤の根因・PR #31）。**参照を保持し `is not` で比較**する（memory `gui_id_reuse_flake_object_recreation`）。

### qtbot.addWidget した widget の手動 deleteLater は teardown 二重削除
`addWidget` した widget を手動 `deleteLater` すると teardown で二重削除→**次テストへ連鎖エラー**（別テストに出るので診断ミスリード）。破棄検証テストは `addWidget` しない（memory `gui_qtbot_addwidget_vs_manual_delete_cascade`）。scoped realgui では見えず headless full でのみ顕在化するため full を必ず回す。

### offscreen の grab() は文字が□（豆腐）
`QT_QPA_PLATFORM=offscreen` の `QWidget.grab()`/スクショは全文字が豆腐（フォント無し）。読める画像は `QT_QPA_PLATFORM=windows` で撮る（memory `gui_offscreen_grab_text_tofu`）。描画 E2E の合否をスクショで判定するときは必ず windows プラットフォームで。
