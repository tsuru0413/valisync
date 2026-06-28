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
   変更ファイル/機能名から `tests/realgui/test_*.py` を対応付ける。対応の手掛かり: ファイル名・テスト内の import・対象ウィジェット名。
   - 例: `file_browser*` の変更 → `tests/realgui/test_file_browser_realclick.py`
   - 例: `graph_panel*` / axis / D&D の変更 → `tests/realgui/test_multi_column_axis.py`
   対応する realgui が**無い**経路は「realgui カバレッジ無し。`reference/realgui-recipe.md` を参照して追加するか、`/verify` 観測のみで足る理由を明記せよ」と**フラグ**（黙って pass しない）。

3. **scoped 実行**
   worktree なら先に `uv sync --extra dev`。
   `uv run pytest --realgui tests/realgui/test_X.py -v`（**全 realgui ではなく該当のみ**＝低摩擦）。

4. **視覚項目の観測**
   アサートで尽くせない視覚結果（ハイライト・挿入線・dimmed source 等）は `/run`（起動・スクショ）・`/verify`（駆動・観測）で確認。スクショは `QT_QPA_PLATFORM=windows`（offscreen は□）。

5. **証拠集約**
   実行した realgui テスト名・pass/fail・ログ要約・スクショパスをまとめる。

6. **ゲート判定**
   - 全 pass ＋証拠あり → **充足**。
   - 失敗 / 証拠欠落 → **未充足**。done を宣言せず是正を促す。
   - **非 Windows・ディスプレイ無しで実行不可 → 未充足**（`skipped` を緑＝検証済みと誤認しない）。

## 出力フォーマット

- 実行した realgui テストと結果（pass/fail）
- 証拠（ログ要約＋スクショパス、または `/verify` 観測結果）
- **ゲート判定**: 充足 / 未充足（＋理由）
