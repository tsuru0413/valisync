# GUI realgui テストワークフロー（2スキル＋ポリシー）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **スキル作成タスク（Task 4–6）の REQUIRED SUB-SKILL:** superpowers:writing-skills（frontmatter・description トリガー・自己完結・検証の作法）。

**Goal:** realgui テストの「高頻度スキップ（①）」と「検証の安直さ（②）」を、計画時スキル `/gui-test-plan`（②）と実行時スキル `/gui-verify`（①）＋ポリシー doc で開発ワークフローに組み込む。

**Architecture:** 知識を 2 種に分離配置する。**運用ノウハウ**（realgui 駆動レシピ・出力雛形）は各スキルの `reference/` が own し自己完結。**方針/標準**（どの変更にどのレイヤー・①証拠ルール・②実質性原則）は `docs/gui-testing-layers.md` が持ち、スキルはそれを enforce する（参照ではなく標準の適用）。設計→実行のハンドオフ: `/gui-test-plan` が受け入れ要件と証拠ゲート仕様を書き、`/gui-verify` が scoped に実行・証拠化する。

**Tech Stack:** Claude Code スキル（`.claude/skills/<name>/SKILL.md` ＋ `reference/`）・サブエージェント（`.claude/agents/<name>.md`）・Markdown ドキュメント。対象アプリは Python 3.12 / PySide6 / pyqtgraph（`uv run valisync`）。realgui は `pytest --realgui`（Windows + 実ディスプレイ）。

## Global Constraints

- **成果物は Markdown のみ**（Python コード変更なし）。ruff/mypy/pytest の品質ゲート対象外。ただし埋め込むコマンド例は正確であること。
- **ドキュメント言語は日本語**（既存 `docs/`・`.kiro/` に合わせる）。
- **スキルは自己完結**: 運用ノウハウは自分の `reference/` に持ち、外部 docs には enforce 対象の必読ポリシー（`docs/gui-testing-layers.md`）のみ参照する。独立した運用 doc（`docs/realgui-patterns.md` 等）は**作らない**。
- **realgui の一次情報源**: 駆動レシピは `.claude/skills/gui-verify/reference/realgui-recipe.md` に集約。散在していた memory・テスト注記はこれを指す。
- **設計の一次情報**: `docs/superpowers/specs/2026-06-28-gui-realgui-test-workflow-design.md`。
- **本プランは現 worktree（branch `worktree-feature+gui-realgui-test-workflow`）で実行**。各タスク末尾で commit。
- **コミットメッセージ末尾**に必ず付与:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Cq544M9LSEXJ285J1k46LF
  ```

---

## File Structure

| ファイル | 操作 | 責務 |
|---|---|---|
| `.gitignore` | 変更 | `.claude/worktrees/` を除外（skills/agents は追跡維持） |
| `docs/gui-testing-layers.md` | 変更 | ①証拠ゲートルール・②実質性原則・recipe ポインタを追記（POLICY 単一情報源） |
| `.kiro/steering/workflow.md` | 変更（§7） | ①②を必須 steering として参照 |
| `.claude/skills/gui-verify/reference/realgui-recipe.md` | 新規 | realgui 駆動レシピ（HOW・スキル所有） |
| `.claude/skills/gui-verify/SKILL.md` | 新規 | ①証拠ゲートの実行 orchestration |
| `.claude/skills/gui-test-plan/reference/output-template.md` | 新規 | 分析ブロック出力雛形 |
| `.claude/skills/gui-test-plan/SKILL.md` | 新規 | ②実質的受け入れ要件の設計 |
| `.claude/agents/gui-test-strategist.md` | 新規 | 既存テスト走査ワーカー（任意 dispatch） |
| `CLAUDE.md` | 変更 | GUI テスト行に 2 スキルへのポインタ追記 |
| memory（リポジトリ外） | 変更 | realgui 3 件を recipe ポインタへスリム化 |

---

## Task 1: リポジトリ hygiene（worktree を gitignore）

**Files:**
- Modify: `.gitignore`

**Interfaces:**
- Consumes: なし
- Produces: なし（以降のタスクが `.claude/skills/`・`.claude/agents/` を安全に commit できる前提を作る）

- [ ] **Step 1: 現状確認（worktrees が未 ignore であること）**

Run: `git check-ignore -v .claude/worktrees/x .claude/skills/x .claude/agents/x; echo "exit=$?"`
Expected: いずれも出力なし（未 ignore）、`exit=1`。

- [ ] **Step 2: `.gitignore` 末尾に追記**

`.gitignore` の末尾に追加:
```
# Claude Code worktree scratch（隔離チェックアウト。commit しない）。
# .claude/skills/ と .claude/agents/ は追跡する。
.claude/worktrees/
```

- [ ] **Step 3: ignore 判定の検証**

Run: `git check-ignore .claude/worktrees/foo; echo "worktree_exit=$?"; git check-ignore .claude/skills/gui-verify/SKILL.md; echo "skill_exit=$?"`
Expected: `.claude/worktrees/foo` は出力あり（ignore）→ `worktree_exit=0`。`.claude/skills/...` は出力なし → `skill_exit=1`（追跡対象）。

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore .claude/worktrees/ (keep skills/agents tracked)"
```

---

## Task 2: ポリシー doc に ①証拠ゲート・②実質性原則を追記

**Files:**
- Modify: `docs/gui-testing-layers.md`（`## 必須運用` セクションの後・`## コマンド早見表` の前に挿入）
- Modify: `.kiro/steering/workflow.md`（§7、Layer C の bullet の後に挿入）

**Interfaces:**
- Consumes: なし
- Produces: 両スキルが enforce する POLICY（節「realgui 実質性ルール（②）」「realgui 証拠ゲート（①）」と recipe ポインタ）。`/gui-verify` の recipe パス `.claude/skills/gui-verify/reference/realgui-recipe.md` をここで宣言。

- [ ] **Step 1: `docs/gui-testing-layers.md` に 2 節を挿入**

`## 必須運用（GUI 実装時のルール）` の表・箇条書きが終わった直後、`## コマンド早見表` の直前に以下を挿入:

```markdown
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

> 実際に Layer C を書くときの**駆動レシピ・落とし穴**は `.claude/skills/gui-verify/reference/realgui-recipe.md` 参照。
```

- [ ] **Step 2: `.kiro/steering/workflow.md` §7 に 2 bullet を追記**

`.kiro/steering/workflow.md:164`（Layer C の bullet）の直後、`> 背景:` 行の前に挿入:

```markdown
- **realgui 証拠ゲート（①）**: GUI 入力経路の変更は、該当 realgui の実行証拠（視覚項目は `/verify` 観測）を **merge 前に要求**。非 Windows 等で実行不可なら「ゲート未充足」扱い（`skipped` を検証済みと誤認しない）。実行は `/gui-verify`。詳細: `docs/gui-testing-layers.md`。
- **realgui 実質性（②）**: realgui のアサートは実経路でしか証明できない結果を検証する（VM 再チェック・スクショ保存だけは不可）。計画時の受け入れ要件設計は `/gui-test-plan`。
```

- [ ] **Step 3: 検証（節とポインタの存在）**

Run: `grep -c "実質性ルール（②）\|証拠ゲート（①）\|gui-verify/reference/realgui-recipe.md" docs/gui-testing-layers.md; grep -c "realgui 証拠ゲート（①）\|realgui 実質性（②）" .kiro/steering/workflow.md`
Expected: 1 行目 `3`、2 行目 `2`。

- [ ] **Step 4: Commit**

```bash
git add docs/gui-testing-layers.md .kiro/steering/workflow.md
git commit -m "docs(gui): realgui 証拠ゲート(①)と実質性原則(②)をポリシーに追加"
```

---

## Task 3: `/gui-verify` 駆動レシピ（スキル所有の運用知識）

**Files:**
- Create: `.claude/skills/gui-verify/reference/realgui-recipe.md`

**Interfaces:**
- Consumes: Task 2 のポリシー（WHEN）を前提に、本ファイルが HOW を担う
- Produces: realgui 駆動レシピ（`/gui-verify` SKILL と手書き勢が読む一次情報）

- [ ] **Step 1: レシピを作成**

`.claude/skills/gui-verify/reference/realgui-recipe.md`:

````markdown
# realgui 駆動レシピ（Layer C 実装の落とし穴と確立パターン）

> `/gui-verify` および手書きで `tests/realgui/` を書くときの**操作知識（HOW）**。方針（WHEN）は `docs/gui-testing-layers.md`。

## 実 D&D は別 OS スレッド＋watchdog で駆動する

`QDrag.exec()` は Windows で OLE `DoDragDrop` モーダルループに入り、Qt の single-shot タイマーを pump しない。LEFTDOWN 後の release を `QTimer.singleShot` で撒くと**一度も発火せず無限ハング**（実測: 約27分ブロック・スクショ0枚）。

確定パターン（PASS 実証）:
- マウス駆動を**別 OS スレッド**（`threading` ＋ `time.sleep` ＋ `ctypes` `user32.mouse_event`）で実時間注入する。
- メインスレッドは `QApplication.processEvents()` ループで GUI を pump（threshold move で `QDrag.exec` に入りブロック → ワーカーの実 OS 入力が OLE ループを駆動 → drop で復帰）。
- **watchdog**: N 秒で解決しなければワーカーが `keybd_event(VK_ESCAPE)` ＋ LEFTUP を強制注入して解放。
- drop 完了検知は `dropEvent` をフックして flag を立てる。
- 実例: `tests/realgui/test_multi_column_axis.py`。

## スクショは GUI スレッドで撮る

ワーカースレッドからの Qt `grabWindow` は不可。drag 中の絵は `dragMoveEvent` 内（＝GUI スレッド・drag 中）で撮る。

## offscreen の grab() は文字が□になる

`QT_QPA_PLATFORM=offscreen` の `QWidget.grab()` は全文字が豆腐（□＝フォント無し）。**読める画像は `QT_QPA_PLATFORM=windows` で撮る**。

## DPI 論理→物理変換

物理カーソル座標 = 論理座標 × `devicePixelRatioF()`。`mouse_event`/`SendInput` に渡す座標は物理。

## PySide6 の mapFromScene

`QGraphicsView.mapFromScene()` は PySide6 で `QPoint` を返す（`.toPoint()` を付けると AttributeError）。

## sendEvent では D&D 配送経路を再現できない

合成 `QApplication.sendEvent(QDropEvent)` は親 view / 子 plot_widget / viewport いずれに送っても `dropEvent` に届かない（このビューは「コンテナが DND 契約、子は `setAcceptDrops(False)`」設計で、実ドラッグは子→親バブリングで届くが合成イベントにはバブリング機構が無い）。

含意:
- ドロップ**ロジック**（ゾーン→VM メソッド）= ハンドラ直叩きで Layer A/B 検証可（`view.dropEvent(event)` を直接呼ぶ）。
- **実配送経路**（`QDrag.exec` ＋ヒットテスト＋子→親バブリング＋`setAcceptDrops` 配線）= **Layer C のみ**。
- context-menu（`QContextMenuEvent`）は viewport に届くので Layer B で再現可 — **D&D だけの特性**。
````

- [ ] **Step 2: 検証（主要見出しの存在）**

Run: `grep -c "^## " .claude/skills/gui-verify/reference/realgui-recipe.md`
Expected: `7`（7 つの落とし穴/パターン見出し）。

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/gui-verify/reference/realgui-recipe.md
git commit -m "feat(skill): gui-verify の realgui 駆動レシピを集約"
```

---

## Task 4: `/gui-verify` SKILL.md（①証拠ゲートの実行）

> **REQUIRED SUB-SKILL:** superpowers:writing-skills。

**Files:**
- Create: `.claude/skills/gui-verify/SKILL.md`

**Interfaces:**
- Consumes: `reference/realgui-recipe.md`（Task 3）、`docs/gui-testing-layers.md` 証拠ゲート（Task 2）
- Produces: `/gui-verify` スラッシュコマンド。出力＝実行した realgui・結果・証拠（ログ＋スクショパス）・ゲート判定（充足/未充足）

- [ ] **Step 1: SKILL.md を作成**

`.claude/skills/gui-verify/SKILL.md`:

````markdown
---
name: gui-verify
description: GUI 入力経路変更の realgui 証拠ゲートを実行する。git diff から変更 GUI ファイルを特定し、対応する tests/realgui を scoped に --realgui 実行、視覚項目は /run・/verify で観測、証拠（pass ログ＋スクショ）を集約して未充足なら done をブロックする。Use when finishing or verifying a PySide6/pyqtgraph GUI input-path change before merge.
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
````

- [ ] **Step 2: 構造検証**

Run: `grep -c "^name: gui-verify$" .claude/skills/gui-verify/SKILL.md; grep -c "git diff\|--realgui\|ゲート判定\|未充足\|非 Windows" .claude/skills/gui-verify/SKILL.md`
Expected: 1 行目 `1`、2 行目 `5` 以上（手順の核が揃っている）。

- [ ] **Step 3: dogfood（任意・環境が許せば）**

`/gui-verify` を起動し、本 worktree の diff（GUI 変更なし）に対して「GUI 入力経路の変更なし → ゲート対象外」と報告することを確認。Expected: 早期終了メッセージ（realgui を回さない）。
（注: 非 Windows / ディスプレイ無し環境ではここはスキップ可。Task 7 で改めて dogfood する。）

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/gui-verify/SKILL.md
git commit -m "feat(skill): gui-verify（realgui 証拠ゲートの scoped 実行）"
```

---

## Task 5: `/gui-test-plan` SKILL.md ＋ 出力雛形（②実質的受け入れ要件）

> **REQUIRED SUB-SKILL:** superpowers:writing-skills。

**Files:**
- Create: `.claude/skills/gui-test-plan/reference/output-template.md`
- Create: `.claude/skills/gui-test-plan/SKILL.md`

**Interfaces:**
- Consumes: `docs/gui-testing-layers.md`（必須運用表・②実質性・①証拠ゲート — Task 2）、`.claude/skills/gui-verify/reference/realgui-recipe.md`（誘導先 — Task 3）、`.claude/agents/gui-test-strategist`（任意 dispatch — Task 6）
- Produces: `/gui-test-plan` スラッシュコマンド。出力＝タスクごとの分析ブロック（writing-plans が織り込む）

- [ ] **Step 1: 出力雛形を作成**

`.claude/skills/gui-test-plan/reference/output-template.md`:

````markdown
# 分析ブロック出力テンプレート

各タスクにつき以下を出力する（writing-plans がプランへ織り込む）:

## Task <id>: <name>
- **変更種別**: <VM/純ロジック | ウィジェット構成・状態 | 入力イベント→ハンドラ>
- **必要レイヤー**: A=<必須> / B=<要/不要＋理由> / C=<要/不要＋理由>
- **入力経路の再現性**: <sendEvent 再現可 | Layer C 専用（理由）| 新規＝手法確立要 → recipe 誘導>
- **受け入れ要件**:
  - **Red**: <失敗するテスト（コードまたは明確な記述）>
  - **Green**: <最小実装の方針>
  - **Verify（/run・/verify 用チェックリスト）**:
    - 起動: `uv run valisync`
    - 手順: <操作手順>
    - 観測: <人間が見て合格と判断する項目>
- **②実質性チェック**: <観測項目→「自動アサート可（API 名）」/「視覚（スクショ＋/verify）」の割当。naive（スクショのみ・VM 再チェック）なら指摘>
- **①証拠ゲート**: `- [ ] uv run pytest --realgui tests/realgui/test_X.py + 証拠添付`（該当時のみ）
- **honest layering note**: <ある場合。例「ハンドラ直叩きは Layer B ではない」>

> 非 GUI タスクは「Layer A のみ・realgui 不要・標準 Red/Green」とだけ返す。
````

- [ ] **Step 2: SKILL.md を作成**

`.claude/skills/gui-test-plan/SKILL.md`:

````markdown
---
name: gui-test-plan
description: PySide6/pyqtgraph GUI タスクのテスト戦略と実質的な受け入れ要件を設計し、writing-plans に織り込む分析ブロックを返す。各タスクのレイヤー判定（A/B/C）・realgui 要否・Red/Green/Verify・②実質性ルーブリック・①証拠ゲート仕様を出力する。Use during writing-plans (or to audit a tasks.md) for GUI input-path features.
---

# gui-test-plan — GUI テスト戦略＆実質的受け入れ要件（課題②対策）

GUI タスクごとに「どのレイヤーをどう書くか」と「実経路でしか証明できない**実質的な**受け入れ要件」を設計し、writing-plans が織り込める**分析ブロック**を返す（非破壊。プランの所有は writing-plans）。

`docs/gui-testing-layers.md`（必須運用表・②実質性ルール・①証拠ゲート）を **enforce** する。出力形式は `reference/output-template.md`。

## 入力
spec 名 / `tasks.md` / writing-plans の下書きプラン / 自由記述のタスク。

## 手順（タスクごと）

1. **変更種別を分類**: VM/純ロジック | ウィジェット構成・状態 | 入力イベント→ハンドラ。
2. **必要レイヤー判定**（`docs/gui-testing-layers.md` の必須運用表）: A 必須 / B 要否 / C 要否＋根拠。
3. **入力経路の再現可否**: `sendEvent` で実経路再現可（`QContextMenuEvent` 等）か、**Layer C 専用**（`QDrag` D&D は合成イベントで配送不可）か。新規/不明な経路は「**手法を確立せよ**」とフラグし `.claude/skills/gui-verify/reference/realgui-recipe.md` へ誘導。
4. **②実質性ルーブリック適用**: 「人間が何を見て合格と判断するか」を列挙→各項目を「自動アサート可（`activePopupWidget()`・可視/ジオメトリ・要素数）」か「視覚（スクショ＋`/verify` 観測）」に割当。**スクショ保存だけ・VM 再チェックだけは naive としてフラグ**。
5. **受け入れ要件 Red/Green/Verify**: Verify 段は `/run`・`/verify` がそのまま食える観測チェックリスト（起動 `uv run valisync` ＋手順＋観測項目）。
6. **①証拠ゲート仕様**: 「該当 realgui を scoped 実行＋証拠添付」を**必須チェックボックス**としてプランに埋める仕様を出す（実行は `/gui-verify`）。
7. **honest layering note**: 経路を実検証しない近道（ハンドラ直叩きを Layer B と誤称する等）を明示。

## ノイジーな調査の委譲（任意）
似た既存入力経路テストの走査・再利用パターン抽出は `gui-test-strategist` サブエージェントに dispatch し、**結論だけ**受け取る（計画コンテキストを汚さない）。単純ケースはスキル内で完結。

## 出力
`reference/output-template.md` に従い、タスクごとの分析ブロックを返す。非 GUI タスクは「Layer A のみ・realgui 不要・標準 Red/Green」と返す。
````

- [ ] **Step 3: 構造検証**

Run: `grep -c "^name: gui-test-plan$" .claude/skills/gui-test-plan/SKILL.md; grep -c "実質性\|証拠ゲート\|realgui-recipe.md\|honest layering" .claude/skills/gui-test-plan/SKILL.md; test -f .claude/skills/gui-test-plan/reference/output-template.md && echo "template_ok"`
Expected: `1` / `4` 以上 / `template_ok`。

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/gui-test-plan/SKILL.md .claude/skills/gui-test-plan/reference/output-template.md
git commit -m "feat(skill): gui-test-plan（②実質的受け入れ要件の設計）"
```

---

## Task 6: `gui-test-strategist` サブエージェント（任意 dispatch ワーカー）

> **REQUIRED SUB-SKILL:** superpowers:writing-skills（agent frontmatter・tools 制限）。

**Files:**
- Create: `.claude/agents/gui-test-strategist.md`

**Interfaces:**
- Consumes: `tests/gui/`・`tests/realgui/`・`docs/gui-testing-layers.md`・`.claude/skills/gui-verify/reference/realgui-recipe.md`（Read/Grep/Glob のみ）
- Produces: `/gui-test-plan` から dispatch される走査結果（類似テスト・再現性判断・推奨アサート）

- [ ] **Step 1: エージェント定義を作成**

`.claude/agents/gui-test-strategist.md`:

````markdown
---
name: gui-test-strategist
description: GUI 入力経路の既存テスト走査・再利用パターン抽出を隔離コンテキストで行い、結論のみ返す。/gui-test-plan が必要時に dispatch する。
tools: Read, Grep, Glob
---

あなたは valisync の GUI テスト走査ワーカー。与えられた入力経路（右クリック / D&D / キー / ドロップ 等）について調べ、**結論のみ**を簡潔に返す（ファイルダンプ不要）。

## 手順
1. `tests/gui/` と `tests/realgui/` から類似の入力経路テストを Grep/Glob で探す。
2. 各々が Layer A/B/C のどれか、どんなアサートをしているか、再利用できるヘルパ（例 `_send_context_menu_event`、別 OS スレッド駆動）を特定する。
3. `docs/gui-testing-layers.md` と `.claude/skills/gui-verify/reference/realgui-recipe.md` を読み、当該経路が `sendEvent` 再現可（Layer B）か Layer C 専用かを判断する。

## 返す内容
- 類似テストのパス＋レイヤー＋再利用可能ヘルパ
- 当該経路の再現性判断（Layer B 可 / Layer C 専用＋理由）
- 推奨アサート（②実質性ルーブリックに沿うもの＝実経路でしか証明できない項目）
````

- [ ] **Step 2: 構造検証**

Run: `grep -c "^name: gui-test-strategist$" .claude/agents/gui-test-strategist.md; grep -c "^tools: Read, Grep, Glob$" .claude/agents/gui-test-strategist.md`
Expected: 両方 `1`。

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/gui-test-strategist.md
git commit -m "feat(agent): gui-test-strategist（GUI テスト走査ワーカー）"
```

---

## Task 7: dogfood — 既存 spec で 2 スキルを検証

**Files:**
- 変更なし（検証のみ。必要なら前タスクの skill/doc を微修正）

**Interfaces:**
- Consumes: `/gui-test-plan`（Task 5）、`/gui-verify`（Task 4）、`.kiro/specs/valisync-gui-axes/tasks.md`、`docs/superpowers/plans/2026-06-27-multi-column-y-axis.md`（Task 4.1 が②アンチパターン実例）
- Produces: スキルが①②を満たすことの確認記録

- [ ] **Step 1: `/gui-test-plan` を axes spec に対して dogfood**

`/gui-test-plan valisync-gui-axes` を実行。
Expected（観測項目）:
- D&D 系タスク（軸移動）に対し「入力イベント→ハンドラ」「Layer C 専用（QDrag は sendEvent 不可）」と分類し recipe へ誘導している。
- `2026-06-27-multi-column-y-axis.md` Task 4.1 相当（`vm.axes[i].column` だけ assert ＋スクショ保存）を **naive としてフラグ**し、実質的観測項目（軸が視覚的に目的列へ着地・挿入線・dimmed source）への置換を提案している。
- Verify 段が `uv run valisync` 起動＋手順＋観測の `/run`・`/verify` 用チェックリストになっている。
- ①証拠ゲートのチェックボックス（`--realgui tests/realgui/test_multi_column_axis.py + 証拠`）が含まれる。

- [ ] **Step 2: `/gui-verify` のマッピング判定を dogfood**

`/gui-verify` を実行（または手順 1–2 を手動トレース）。
Expected:
- 現 worktree の diff（GUI 変更なし）→「GUI 入力経路の変更なし → ゲート対象外」。
- 仮に `src/valisync/gui/views/graph_panel_view.py` を変更した想定 → 該当に `tests/realgui/test_multi_column_axis.py` を挙げる。
- 非 Windows / ディスプレイ無し環境では「実行不可＝ゲート未充足」と報告（緑にしない）。

- [ ] **Step 3: 不足があれば該当 skill/doc を修正**

dogfood で①②を満たさない点（naive 検出漏れ・誘導欠落・マッピング不全）があれば、Task 4/5 の該当ファイルを最小修正。

- [ ] **Step 4: Commit（修正した場合のみ）**

```bash
git add -A
git commit -m "fix(skill): dogfood で判明した gui-test-plan/gui-verify の不足を是正"
```

---

## Task 8: ポインタ整備（CLAUDE.md ＋ memory スリム化）

**Files:**
- Modify: `CLAUDE.md`（GUI テスト行）
- Modify（リポジトリ外）: memory `gui_realgui_drag_qtimer_hang.md` / `gui_drag_drop_not_sendevent_reproducible.md` / `gui_offscreen_grab_text_tofu.md`

**Interfaces:**
- Consumes: Task 2–6 の成果物（参照先が揃っていること）
- Produces: トレーサビリティ（CLAUDE.md → 2 スキル、memory → recipe 一次情報）

- [ ] **Step 1: CLAUDE.md に 2 スキルのポインタを追記**

`CLAUDE.md` の「GUI 機能・操作を実装するときは **GUI テストレイヤー…** に従う。詳細: `docs/gui-testing-layers.md`（…）。」の直後に 1 文追加:

```markdown
計画時は `/gui-test-plan`（②実質的な受け入れ要件の設計）、merge 前は `/gui-verify`（①realgui 証拠ゲート）を使う。
```

- [ ] **Step 2: 検証**

Run: `grep -c "/gui-test-plan\|/gui-verify" CLAUDE.md`
Expected: `2` 以上。

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): GUI テスト行に gui-test-plan/gui-verify ポインタ追記"
```

- [ ] **Step 4: memory スリム化（リポジトリ外・commit 不要）**

`C:\Users\trtrm\.claude\projects\D--Programming-projects-valisync\memory\` の 3 件の本文を、詳細列挙から `.claude/skills/gui-verify/reference/realgui-recipe.md` を一次情報源として指す短いポインタへ更新（事実は recipe が保持、memory は「どこを見るか」に寄せる）。`MEMORY.md` の各 hook 行も整合。
（これはユーザーグローバル memory のメンテで、リポジトリの git には乗らない。）

---

## Self-Review

**1. Spec coverage**（`docs/superpowers/specs/2026-06-28-gui-realgui-test-workflow-design.md` 各節 → タスク）:
- §3.1 知識所有原則（運用=skill / 方針=doc・独立 doc 不作成）→ Global Constraints・Task 2/3。✓
- §3.2 `/gui-test-plan`（②・分類/レイヤー判定/再現性/実質性/Verify チェックリスト/①ゲート仕様/honest note）→ Task 5。✓
- §3.3 `/gui-verify`（① diff→scoping→実行→/verify→証拠→ゲート判定）＋ recipe 所有 → Task 3/4。✓
- §3.4 `gui-test-strategist` → Task 6。✓
- §3.5 ②実質性ルーブリック（ポリシー化）→ Task 2 Step 1。✓
- §3.6 ①証拠ゲート（非 Windows=未充足含む）→ Task 2 Step 1/2、Task 4 Step 1 手順6。✓
- §4 ワークフロー統合（writing-plans / run・verify / verification-before-completion ハンドオフ）→ Task 4/5 本文。✓
- §5 エッジ処理（非 GUI／realgui 無し／非 Windows）→ Task 4 手順2/6、Task 5 出力、output-template 注記。✓
- §6 dogfooding → Task 7。✓
- §7 配置（skills/agents/docs/gitignore/memory）→ Task 1/2/3/4/5/6/8。✓
  - ギャップ: 設計 §7 は memory スリム化を「実装後」と記載 → Task 8 Step 4 で対応。CLAUDE.md ポインタは設計 §7 に未列挙だが、トレーサビリティ確保のため Task 8 で追加（軽量・ポリシー方針に合致）。

**2. Placeholder scan:** 「TBD/TODO/後で」なし。各 skill/doc/agent の**全文**を埋め込み済み。検証ステップは具体コマンド＋期待値。✓

**3. Type/名称整合:**
- recipe パス `.claude/skills/gui-verify/reference/realgui-recipe.md` は Task 2（ポインタ宣言）/3（作成）/5（誘導先）/6（参照）で一致。✓
- `tests/realgui/test_multi_column_axis.py`・`test_file_browser_realclick.py` の参照は実在ファイルと一致（Glob 確認済み）。✓
- スキル名 `gui-test-plan`・`gui-verify`、エージェント名 `gui-test-strategist` は frontmatter・参照箇所で一貫。✓
- `workflow.md` の挿入位置（:164 Layer C bullet 後）は実ファイル確認済み。✓

---

## 依存グラフ

```json
{
  "tasks": [
    {"id":"1","desc":"gitignore worktrees","deps":[]},
    {"id":"2","desc":"policy ①② + pointer","deps":[]},
    {"id":"3","desc":"realgui-recipe（運用知識）","deps":["2"]},
    {"id":"4","desc":"gui-verify SKILL","deps":["3","2"]},
    {"id":"5","desc":"gui-test-plan SKILL + template","deps":["2","3"]},
    {"id":"6","desc":"gui-test-strategist agent","deps":["3"]},
    {"id":"7","desc":"dogfood 検証","deps":["4","5","6"]},
    {"id":"8","desc":"CLAUDE.md + memory ポインタ","deps":["3","4","5"]}
  ]
}
```
