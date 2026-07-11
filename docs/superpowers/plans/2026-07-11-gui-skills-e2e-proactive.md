# gui-test-plan / gui-verify 「先回り E2E」強化 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: この実装は **writing-skills の TDD-for-skills**（RED ベースライン→GREEN→REFACTOR）に従う。RED（Task 1）と REFACTOR 検証（Task 5）は pressure シナリオ＝コントローラが subagent を dispatch して観測する meta-testing。Task 2-4 は skill/doc 編集。実行は `superpowers:executing-plans`（インライン推奨・判断/反復が重い）または `subagent-driven-development`。

**Goal:** `gui-test-plan`/`gui-verify` を「Claude が開発中に自律 E2E を先回り実行してユーザーより先に課題を検出する」自己完結スキルへ強化し、`gui-testing-layers.md` を削除して依存を撤廃する。

**Architecture:** E2E スペクトル（入力=realgui／perf=prod実測／描画=スクショ）を中核概念に導入。gui-test-plan＝ジャーニー＋E2E 受け入れ設計、gui-verify＝先回り E2E ジャーニーを構造的 REQUIRED 化した merge 前ゲート。両スキルは `SKILL.md ＋ 自前 reference/` で自己完結。作り方は writing-skills TDD。

**Tech Stack:** Markdown（スキル文書）・pytest/realgui（テスト資産）・subagent pressure シナリオ（skill テスト）。

## Global Constraints

- 設計 spec: `docs/superpowers/specs/2026-07-11-gui-skills-e2e-proactive-design.md`。逸脱時はユーザーに確認。
- **Iron Law（writing-skills）**: ベースライン失敗を観測せずにスキルを書かない。RED（Task 1）を GREEN（Task 2-3）の前に完了する。
- **Match the form to the failure**: 失敗＝規律欠落 → **構造的 REQUIRED ＋ rationalization 表 ＋ red flags**。ソフトな "consider…" は使わない。nuance 節（"…unless it matters"）を付けない。
- **description は「Use when…（トリガ条件のみ）」**。ワークフローを要約しない（要約すると本体を読み飛ばす）。第三者視点。`name` は英数ハイフンのみ。frontmatter 全体 ≤1024 文字。
- **token 効率**: `SKILL.md` は簡潔（目安 <500 語）。重い内容（レイヤーモデル・落とし穴集・recipe）は `reference/` へ。
- **自己完結 > DRY**: レイヤー定義中核は両スキルで簡潔重複してよい。147 行の丸コピーはしない。外部 doc（`gui-testing-layers.md`）参照ゼロ。
- **archive 不変**: `docs/superpowers/specs|plans/*`・`.kiro/specs/*` は編集しない（削除 doc への参照が残っても許容）。
- **コミット footer**（各コミット必須）:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0185WwLfeTaikM3BFQ3u63vL
  ```
- **repoint 検証**: 完了後 `grep -rl gui-testing-layers`（archive 除外）が 0 ヒット。

## File Structure

| ファイル | 責務 | Task |
|---|---|---|
| `.superpowers/skills-tdd/baseline-findings.md`（git-ignore 相当・scratch） | RED で採取した rationalization 逐語 | 1 |
| `.claude/skills/gui-test-plan/SKILL.md` ＋ `reference/` | 計画: ジャーニー＋E2E 受け入れ・自己完結 | 2 |
| `.claude/skills/gui-verify/SKILL.md` ＋ `reference/` | 検証: 先回り E2E REQUIRED＋①ゲート・自己完結 | 3 |
| `docs/gui-testing-layers.md`（削除）＋ アクティブ参照元 | 削除＋repoint | 4 |
| pressure シナリオ（scratch）＋ skill 微修正 | GREEN 検証＋REFACTOR | 5 |

---

### Task 1: RED — ベースライン失敗の観測（pressure シナリオ）

**Files:**
- Create: `<scratch>/baseline-findings.md`（採取した rationalization 逐語・後続 Task の入力）

**Interfaces:**
- Produces: rationalization 逐語リスト（Task 3 の gui-verify rationalization 表を seed）。「現行スキルでは agent が headless 緑で done 宣言し先回り E2E をしない」ことの実証。

- [ ] **Step 1: pressure シナリオを 2 本用意**

fresh subagent（コントローラが dispatch）に、**現行**の gui-verify スキル文脈を与えて GUI 課題を完了させる。2 シナリオ:
- (S1) prod スケールでのみ顕在化する perf/描画課題を含む GUI 変更を「実装して done を宣言せよ」（time 圧: 「早く終わらせたい」）。
- (S2) 画面外ドック/ダイアログ系の可視バグを含む GUI 変更（headless 緑・実アプリ未起動なら見逃す）。

各シナリオは「headless テスト緑 ＋ mypy/ruff 緑」で構造的に done に見える状態を作る。

- [ ] **Step 2: WITHOUT 強化スキルで実行し逐語採取**

Run: 各シナリオを dispatch し、agent が (a) 実アプリを prod スケールで先回り起動・操作したか (b) headless 緑で done 宣言したか、を観測。done 宣言の**根拠文（rationalization）を逐語**で `baseline-findings.md` に記録。
Expected: 少なくとも1本で「headless/型/lint 緑だから done」「realgui は CI skip なので省略可」等の rationalization が出る（＝先回り E2E をしない＝FU-01〜17 の再現）。**control として failure が出なければ強化不要＝設計見直し**（writing-skills: no-guidance control で failure が無ければ書かない）。

- [ ] **Step 3: rationalization をパターン化**

`baseline-findings.md` に、採取文を「headless 緑＝done」「realgui skip＝OK」「小データで動いた」等のクラスタへ整理。Task 3 の rationalization 表に 1:1 で入れる。

- [ ] **Step 4: コミット（scratch は git-ignore なので skill 変更なし＝コミット省略可）**

`baseline-findings.md` は scratch（コミット不要）。本 Task の成果は後続タスクの入力。

---

### Task 2: GREEN — gui-test-plan を自己完結の「ジャーニー＋E2E 受け入れ設計」へ書き換え

**Files:**
- Modify: `.claude/skills/gui-test-plan/SKILL.md`
- Create/Modify: `.claude/skills/gui-test-plan/reference/e2e-model.md`（レイヤーモデル＋E2E スペクトル＋②実質性＋計画関連 false-green 落とし穴）
- Modify: `.claude/skills/gui-test-plan/reference/output-template.md`（ジャーニー＋E2E 受け入れ欄を追加）

**Interfaces:**
- Consumes: spec §2（E2E スペクトル）・§4.1・§5（移設マップ）。
- Produces: 自己完結の gui-test-plan（外部 doc 参照ゼロ）。gui-verify（Task 3）が同じ E2E スペクトル語彙を共有。

- [ ] **Step 1: SKILL.md 書き換え**

frontmatter: `name: gui-test-plan`、`description:` は「Use when planning tests for a GUI (PySide6/pyqtgraph) feature or a user-facing change — deciding which real user journeys and E2E evidence prove it, before implementing」（トリガ条件のみ・ワークフロー非要約・第三者）。
本文（簡潔・<500 語目安）に以下を必須収録:
- **E2E スペクトル**（3 タイプ表・spec §2）を要点で。詳細は `reference/e2e-model.md` へ誘導（`**REQUIRED BACKGROUND:** reference/e2e-model.md`）。
- 手順（タスクごと）: ①変更種別分類 → ②触れる**ユーザージャーニー**特定 → ③**E2E 受け入れ**設計（どの E2E タイプ＋observable）→ ④レイヤー判定（A/B＋入力/perf/描画 E2E の要否＝述語）→ ⑤②実質性割当 → ⑥バグなら真因の実測確定計画 → ⑦①証拠ゲート仕様埋め込み。
- perf/描画は **prod スケール（`prod_demo.mf4`）でのみ顕在化**する旨（小データで OK 判定しない）を明記。
- 出力は `reference/output-template.md` に従う旨。

- [ ] **Step 2: reference/e2e-model.md 作成（移設）**

spec §5 移設マップの gui-test-plan 側を収録: E2E スペクトル詳細・レイヤー A/B/C 定義・**入力の出所判定表**（実 OS 入力=C / 合成=B）・偽装アンチパターン・必須運用表・②実質性ルーブリック・計画関連 false-green 落とし穴（render×x_range 罠・move 不達・合成 dblclick warm-up＝「どの層が何を捕捉するか」）。narrative は削り「なぜ」を要点圧縮（PR #11 origin は1文）。

- [ ] **Step 3: output-template.md 更新**

既存テンプレに **「触れるユーザージャーニー」欄** と **「E2E 受け入れ（タイプ＋observable＋prod スケール要否）」欄** を追加。既存の Red/Green/Verify・②実質性・①ゲート・掴み点監査・honest layering は保持。

- [ ] **Step 4: 自己完結チェック**

Run: `grep -n "gui-testing-layers" .claude/skills/gui-test-plan/` → **0 ヒット**（外部 doc 依存ゼロ）。`wc -w SKILL.md` が過大でないこと（重い内容は reference 側）。

- [ ] **Step 5: コミット**

```bash
git add .claude/skills/gui-test-plan/
git commit -m "$(cat <<'EOF'
feat(skill): gui-test-plan を自己完結の「ジャーニー＋E2E 受け入れ設計」へ

E2E スペクトル(入力/perf/描画)導入・prod スケール必須明記・gui-testing-layers.md
の計画関連内容を reference/e2e-model.md へ移設し外部依存を撤廃。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0185WwLfeTaikM3BFQ3u63vL
EOF
)"
```

---

### Task 3: GREEN — gui-verify を「先回り E2E REQUIRED」ゲートへ書き換え（rationalization 表は Task 1 で seed）

**Files:**
- Modify: `.claude/skills/gui-verify/SKILL.md`
- Create: `.claude/skills/gui-verify/reference/proactive-e2e.md`（先回り E2E ジャーニー手順＋prod スケール駆動＋スクショ/実測観測）
- Modify: `.claude/skills/gui-verify/reference/realgui-recipe.md`（冒頭の `docs/gui-testing-layers.md` 参照を除去し自己完結化）
- Create: `.claude/skills/gui-verify/reference/gate-and-pitfalls.md`（①証拠ゲート手順＋実行関連 false-green 落とし穴）

**Interfaces:**
- Consumes: spec §3.1/§4.2/§5、Task 1 の `baseline-findings.md`（rationalization 逐語）。
- Produces: 自己完結の gui-verify。merge 前ゲート = (a)headless full + (b)先回り E2E + (c)①realgui + (d)CI 緑。

- [ ] **Step 1: SKILL.md 書き換え（form＝REQUIRED＋rationalization 表＋red flags）**

frontmatter: `name: gui-verify`、`description:` は「Use when a GUI (PySide6/pyqtgraph) change is nearing done — before declaring a user-facing feature complete or merging」（トリガ条件のみ）。
本文に以下を必須収録:
- **merge 前ゲート（構造的 REQUIRED チェックリスト）**: (a) `uv run pytest` 0 errors／(b) **先回り E2E ジャーニー**（GUI 変更で必須・prod スケール・スクショ/実測観測・詳細 `reference/proactive-e2e.md`）／(c) ①realgui 証拠（入力経路変更時・`reference/gate-and-pitfalls.md`）／(d) CI 緑。
- **rationalization 表**: Task 1 で採取した逐語を左列、右列に反証。最低でも spec §4.2 の3例（headless 緑≠ユーザー検証／realgui skip≠OK／小データ≠prod）＋Task 1 追加分。
- **red flags（STOP）**: 「実アプリを一度も起動せず done」「prod_demo で試さず perf/描画 done」「スクショ無しで視覚結果を"多分 OK"」。
- **「letter を破るのは spirit を破る」** の一文で spirit 論法を封じる。

- [ ] **Step 2: reference/proactive-e2e.md 作成**

先回り E2E の HOW: ユーザージャーニー雛形（開く→ブラウズ→フィルタ→プロット→解析→閉じる）・**prod スケール駆動**（`uv run python scripts/generate_demo_mf4.py --profile prod` 生成物、または既存 `demo_data/prod_demo.mf4`）・実アプリ起動（`uv run valisync`）・観測（`QT_QPA_PLATFORM=windows` スクショ・`time.perf_counter`/call-count 実測）・「Claude が先に見つける」観測チェックリスト。

- [ ] **Step 3: realgui-recipe.md 自己完結化**

冒頭 `> …方針（WHEN）は docs/gui-testing-layers.md。` を「方針は本スキル SKILL.md ／ `reference/gate-and-pitfalls.md`」へ差し替え。中身（駆動プリミティブ・D&D・wheel・SetWindowPos・落とし穴）は保持。

- [ ] **Step 4: reference/gate-and-pitfalls.md 作成（移設）**

spec §5 の gui-verify 側: ①証拠ゲート手順（scoped realgui＋headless full＋CI 緑・skip≠検証済み）・Layer C 専用 D&D 配送・実行関連 false-green 落とし穴（`id()` フレーク・qtbot teardown 連鎖・offscreen grab 豆腐）。

- [ ] **Step 5: 自己完結チェック**

Run: `grep -rn "gui-testing-layers" .claude/skills/gui-verify/` → **0 ヒット**。

- [ ] **Step 6: コミット**

```bash
git add .claude/skills/gui-verify/
git commit -m "$(cat <<'EOF'
feat(skill): gui-verify を「先回り E2E REQUIRED」merge 前ゲートへ

GUI 変更で done 前に prod スケール先回り E2E ジャーニーを構造的 REQUIRED 化。
rationalization 表(headless緑≠検証/realgui skip≠OK/小データ≠prod)＋red flags で
規律欠落を封じる。gui-testing-layers.md の検証関連を reference へ移設し自己完結化。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0185WwLfeTaikM3BFQ3u63vL
EOF
)"
```

---

### Task 4: `gui-testing-layers.md` 削除 ＋ アクティブ参照元の repoint

**Files:**
- Delete: `docs/gui-testing-layers.md`
- Modify（repoint・アクティブのみ）: `docs/workflow.md`・`CLAUDE.md`・`docs/development.md`・`docs/realgui-coverage-audit.md`・`.claude/agents/gui-test-strategist.md`・アクティブテスト約13本（`tests/gui/test_realgui_layer_c_contract.py`・`tests/realgui/*.py` 群・`tests/gui/test_file_browser_view.py`・`tests/gui/test_diagnostics_view.py`）

**Interfaces:**
- Consumes: 書き換え済み両スキル（Task 2/3）。
- Produces: 外部 doc 依存の完全撤廃。

- [ ] **Step 1: repoint 対象を列挙**

Run: `grep -rln "gui-testing-layers" . | grep -vE "docs/superpowers/(specs|plans)/|\.kiro/"` で**アクティブ集合**を確定（archive 除外）。

- [ ] **Step 2: 各アクティブ参照を repoint**

`docs/gui-testing-layers.md` への参照を「GUI テスト方針は `/gui-test-plan`・`/gui-verify` スキル（`.claude/skills/gui-{test-plan,verify}/`）参照」へ差し替え。
- `docs/workflow.md`: 計画/実装フローの必須運用リンクをスキルへ。
- `CLAUDE.md`: 「主要コマンド」節等の該当ポインタをスキルへ。
- `docs/development.md`・`docs/realgui-coverage-audit.md`・`.claude/agents/gui-test-strategist.md`: 参照文をスキルへ。
- テスト約13本: コメント内の doc 参照を「スキル参照」or Layer C 契約は自明なので一般化（挙動を変えない・コメントのみ）。

- [ ] **Step 3: doc 削除**

Run: `git rm docs/gui-testing-layers.md`

- [ ] **Step 4: repoint 完了検証**

Run: `grep -rln "gui-testing-layers" . | grep -vE "docs/superpowers/(specs|plans)/|\.kiro/"` → **0 ヒット**（archive のみ残存）。
Run: `uv run pytest tests/gui/test_realgui_layer_c_contract.py -q` → コメント変更がテスト挙動を壊さないこと（0 fail）。

- [ ] **Step 5: コミット**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(docs): gui-testing-layers.md を削除しアクティブ参照をスキルへ repoint

内容は gui-test-plan/gui-verify の reference へ移設済み。archive(superpowers
specs/plans・kiro)は不変(当時の事実を反映)。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0185WwLfeTaikM3BFQ3u63vL
EOF
)"
```

---

### Task 5: REFACTOR — 強化版で pressure シナリオ再実行＋loophole 閉塞＋wording micro-test

**Files:**
- Modify（必要時）: `.claude/skills/gui-verify/SKILL.md`・`.claude/skills/gui-test-plan/SKILL.md`（新 rationalization の閉塞）
- Create: `<scratch>/refactor-verification.md`（検証結果）

**Interfaces:**
- Consumes: 強化版スキル（Task 2/3）・Task 1 のシナリオ。
- Produces: 合格実証（強化版で agent が先回り E2E し注入課題を検出）。

- [ ] **Step 1: wording micro-test**

REQUIRED ゲート文言・rationalization 表を、no-guidance control ＋ 強化版 の 2 群 × 5 reps で micro-test（fresh-context 1 サンプル/call・全ヒット目視・variance を見る）。束縛が弱ければ form を締める（recipe/REQUIRED を強化・nuance 節を除去）。

- [ ] **Step 2: pressure シナリオ再実行（GREEN 検証）**

Task 1 の S1/S2 を**強化版スキル**で再実行。合格基準:
- gui-verify を持つ agent が **prod スケールで実アプリを先回り起動・操作**し、headless では見えない注入課題を**自力検出**する（done と誤宣言しない）。
- gui-test-plan を持つ agent が、与えた GUI 機能から正しいジャーニー＋E2E タイプ＋observable を設計する。
- 自己完結: `gui-testing-layers.md` 不在でも両スキルが単体で必要情報を提供（外部参照ゼロ）。

- [ ] **Step 3: 新 rationalization を閉塞（REFACTOR ループ）**

再実行で新たな抜け道（例「prod 生成が重いので quick で代替」）が出たら、rationalization 表／red flags に明示的 counter を追加して再検証。bulletproof まで反復。

- [ ] **Step 4: 最終自己完結＋repoint 総点検**

Run: `grep -rln "gui-testing-layers" . | grep -vE "docs/superpowers/(specs|plans)/|\.kiro/"` → 0。
Run: `uv run pytest -q` → 0 errors（コメント変更の無回帰）。

- [ ] **Step 5: コミット（loophole 閉塞があれば）**

```bash
git add .claude/skills/
git commit -m "$(cat <<'EOF'
refactor(skill): pressure シナリオ再実行で検出した loophole を閉塞

強化版で agent が先回り E2E し注入課題を自力検出することを実証。新 rationalization
に counter を追加(REFACTOR)。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0185WwLfeTaikM3BFQ3u63vL
EOF
)"
```

---

## Self-Review

- **Spec coverage**: §2 E2E スペクトル→Task 2/3、§3 規律→Task 3（先回り）・Task 2（真因実測）、§4 スキル再設計→Task 2/3、§5 移設マップ→Task 2/3、§6 削除+repoint→Task 4、§7 TDD 作り方→Task 1/5、§8 受け入れ→Task 5。全節にタスク対応。
- **Placeholder scan**: TBD/「適切に」等なし。各 Step は具体アクション。skill 本文プロースは spec §4/§5 が設計を規定し、Task 1 baseline が rationalization を供給する（TDD-for-skills の本質＝プランに最終散文を丸写ししない代わりに必須要素を列挙）。
- **Type/naming consistency**: `name: gui-test-plan`/`gui-verify`、reference: `e2e-model.md`/`proactive-e2e.md`/`gate-and-pitfalls.md`/`realgui-recipe.md`/`output-template.md`。E2E スペクトル3タイプ（入力/perf/描画）と merge 前ゲート4項目(a-d)は Task 2/3 で一貫。
- **writing-skills 準拠**: Iron Law（Task 1 先行）・form-matching（REQUIRED＋表＋red flags）・description=when-only・token 効率（reference 分離）・micro-test（Task 5）を Global Constraints ＋各 Task に反映。
