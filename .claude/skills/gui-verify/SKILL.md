---
name: gui-verify
description: Use when PySide6/pyqtgraph の GUI 入力経路（右クリック・drag-and-drop・キー・drop ハンドラ）を変更し、merge 前に検証/完了しようとするとき。realgui（Layer C）が --realgui オプトインや CI 自動スキップで「skipped＝検証済み」と誤認されるのを防ぐ証拠ゲートが要る場面。
---

# gui-verify — realgui 証拠ゲート（課題①対策）

realgui テストは `--realgui` オプトイン＋CI 自動スキップで高頻度にスキップされ、「skipped」が「検証済み」と誤認される。本スキルは変更に対応する分だけを scoped に実行・証拠化して、その誤認を断つ。

- 方針（WHEN）: `docs/gui-testing-layers.md`「realgui 証拠ゲート（①）」を enforce。
- 駆動レシピ（HOW）: `reference/realgui-recipe.md`。

## 手順

1. **変更経路を特定**
   `git diff --name-only main...HEAD -- src/valisync/gui/`（未コミットも見るなら `git status --short -- src/valisync/gui/` も併用）で変更 GUI ファイルを列挙。空なら「GUI 入力経路の変更なし → ゲート対象外」と報告して終了。

2. **該当 realgui をマッピング**
   `tests/realgui/test_*.py` を**全列挙**し、各テスト本文が変更ファイルの**モジュール名/ウィジェット名/関数名**を参照しているかで対応付ける（例: `grep -l <変更識別子> tests/realgui/test_*.py`）。固定の対応表に頼らない（realgui テストが増えると漏れる）。**1つの変更が複数の realgui に対応し得る**ので網羅する。
   - 例: `file_browser*` → `test_file_browser_realclick.py`・`test_remove_file_preserves_proportions.py`
   - 例: `graph_panel*` / axis / D&D → `test_multi_column_axis.py`・`test_remove_file_preserves_proportions.py`
   対応する realgui が**無い**経路は「realgui カバレッジ無し。`reference/realgui-recipe.md` を参照して追加するか、`/verify` 観測のみで足る理由を明記せよ」と**フラグ**（黙って pass しない）。

3. **scoped realgui 実行 ＋ headless full**
   worktree なら先に `uv sync --extra dev`。
   - realgui（該当のみ）: `uv run pytest --realgui tests/realgui/test_X.py -v`（**全 realgui ではなく該当のみ**＝低摩擦）。
   - headless 全体: `uv run pytest`（**0 errors** を確認）。realgui scoped はテスト間汚染を検知できないので full を必ず回す（memory `gui_qtbot_addwidget_vs_manual_delete_cascade`）。

4. **視覚項目の観測**
   アサートで尽くせない視覚結果（ハイライト・挿入線・dimmed source 等）は `/run`（起動・スクショ）・`/verify`（駆動・観測）で確認。スクショは `QT_QPA_PLATFORM=windows`（offscreen は□）。

5. **証拠集約**
   実行した realgui テスト名・pass/fail・ログ要約・スクショパスをまとめる。

6. **ゲート判定**（realgui 証拠は merge 前ゲートの一部にすぎない）
   - **(a) headless full**: `uv run pytest` が **0 errors**。realgui 全 pass でも headless のテスト間汚染で CI は赤になる（memory `gui_qtbot_addwidget_vs_manual_delete_cascade`）。
   - **(b) realgui 証拠**: 該当 realgui が全 pass ＋証拠あり。
   - **(c) CI 緑**（push 済みなら確認）。
   - (a)〜(c) すべて満たす → **充足**。いずれか欠ける／証拠欠落 → **未充足**（done を宣言せず是正を促す）。
   - **非 Windows・ディスプレイ無しで (b) 実行不可 → 未充足**（`skipped` を緑＝検証済みと誤認しない）。

## 出力フォーマット

- **headless full**: `uv run pytest` の結果（passed / errors 数）
- 実行した realgui テストと結果（pass/fail）
- 証拠（ログ要約＋スクショパス、または `/verify` 観測結果）
- **ゲート判定**: 充足 / 未充足（＋理由。(a)headless 0 errors / (b)realgui 証拠 / (c)CI 緑 の充足状況）
