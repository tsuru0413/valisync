# gui-test-plan / gui-verify 「先回り E2E」強化 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: この実装は **writing-skills の TDD-for-skills**（RED→GREEN→micro-test）に従う。失敗タイプは**規律欠落でなく「E2E 検証が不十分（真面目にやっても diff スコープ止まり）」＝不完全出力**なので、form は **positive な contract/recipe**（禁止形は使わない）、テストは pressure でなく **application/カバレッジ**。RED（Task 1・coverage ベースライン）と検証（Task 5・application/micro-test）はコントローラが subagent を dispatch して観測する meta-testing。Task 2-4 は skill/doc 編集。実行は `superpowers:executing-plans`（インライン推奨）。

**Goal:** `gui-test-plan`/`gui-verify` を「Claude が開発中に自律 E2E を先回り実行してユーザーより先に課題を検出する」自己完結スキルへ強化し、`gui-testing-layers.md` を削除して依存を撤廃する。

**Architecture:** E2E スペクトル（入力=realgui／perf=prod実測／描画=スクショ）を中核概念に導入。gui-test-plan＝ジャーニー＋E2E 受け入れ設計、gui-verify＝先回り E2E ジャーニーを構造的 REQUIRED 化した merge 前ゲート。両スキルは `SKILL.md ＋ 自前 reference/` で自己完結。作り方は writing-skills TDD。

**Tech Stack:** Markdown（スキル文書）・pytest/realgui（テスト資産）・subagent application/coverage テスト（skill テスト）。

## Global Constraints

- 設計 spec: `docs/superpowers/specs/2026-07-11-gui-skills-e2e-proactive-design.md`。逸脱時はユーザーに確認。
- **Iron Law（writing-skills）**: ベースライン失敗を観測せずにスキルを書かない。RED（Task 1）を GREEN（Task 2-3）の前に完了する。
- **Match the form to the failure**: 失敗＝**不完全出力**（真面目にやっても E2E が不十分）→ **positive な contract/recipe**（"十分な E2E 検証とは何か＝必須構成要素" を規定）。**禁止形（rationalization 表 / red flags / "…せず done するな"）は使わない**（writing-skills: 不完全出力に禁止形は逆効果）。ソフトな "consider…" も不可。nuance 節（"…unless it matters"）を付けない。
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
| `<scratch>/baseline-findings.md` | coverage baseline: 現行 E2E の不十分性＋contract 必須構成要素 | 1 |
| `.claude/skills/gui-test-plan/SKILL.md` ＋ `reference/` | 計画: ジャーニー＋E2E 受け入れ・自己完結 | 2 |
| `.claude/skills/gui-verify/SKILL.md` ＋ `reference/` | 検証: 先回り E2E REQUIRED＋①ゲート・自己完結 | 3 |
| `docs/gui-testing-layers.md`（削除）＋ アクティブ参照元 | 削除＋repoint | 4 |
| application/coverage テスト（scratch）＋ skill 締め | GREEN 検証＋穴埋め | 5 |

---

### Task 1: RED — coverage ベースライン（現行 E2E 検証の不十分性を実証・**実行済み**）

**Files:**
- Create: `<scratch>/baseline-findings.md`（現行 method の不十分性の実証・後続 Task の入力）

**Interfaces:**
- Produces: 「現行（diff スコープ）の E2E 検証は不十分」の実証と、**contract に必要な構成要素**（何が欠けると不十分か）の抽出。※discipline 失敗（rationalization）ではなく**不完全カバレッジ**の実証。

- [x] **Step 1-3: coverage シナリオ 2 本を実行・観測（完了）**

現行 gui-verify スキル文脈を与えた fresh subagent（sonnet・full repo access）2 本に、全ゲート緑（headless/型/lint/CI）の GUI 変更の充足判定をさせた。結果（`baseline-findings.md`）:
- **規律失敗は無い**（両者 NO-GO・締切圧下でも署名拒否）。→ 禁止形/rationalization 表は不要（form 見直しの根拠）。
- **現行 method は不十分**を両者が実証: S1=「報告 realgui は変更経路と別コード＝カバレッジ実質ゼロ（フィルタの realgui 不在）」／S2=「headless の `isVisible()` は FU-04 偽陰性計器・回帰テスト未実行」。
- 抽出した**contract 必須構成要素**（欠けると不十分）: ①変更挙動を実経路で exercise する realgui（同名別コードは不可）／②嘘プロキシ（`isVisible`）でなく実 observable／③prod スケール（perf/描画）／④ジャーニー単位のカバレッジ。
- **副次リスク**: 両者の"不足検出"は現行 `gui-testing-layers.md`＋memory 依存。削除時は権威を skill へ移設・強化必須。

- [ ] **Step 4: findings を contract 設計へ反映**

`baseline-findings.md` の「contract 必須構成要素」を Task 2/3 の contract 定義（spec §3.1）へ 1:1 で反映。scratch はコミット不要（後続の入力）。

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

### Task 3: GREEN — gui-verify を「E2E 十分性 contract の点検」ゲートへ書き換え（positive contract 形）

**Files:**
- Modify: `.claude/skills/gui-verify/SKILL.md`
- Create: `.claude/skills/gui-verify/reference/proactive-e2e.md`（先回り E2E ジャーニー手順＋prod スケール駆動＋スクショ/実測観測）
- Modify: `.claude/skills/gui-verify/reference/realgui-recipe.md`（冒頭の `docs/gui-testing-layers.md` 参照を除去し自己完結化）
- Create: `.claude/skills/gui-verify/reference/gate-and-pitfalls.md`（①証拠ゲート手順＋実行関連 false-green 落とし穴）

**Interfaces:**
- Consumes: spec §3.0/§3.1/§4.2/§5、Task 1 の `baseline-findings.md`（contract 必須構成要素）。
- Produces: 自己完結の gui-verify。merge 前ゲート = (a)headless full + (b)E2E 十分性 contract 充足 + (c)①realgui + (d)CI 緑。

- [ ] **Step 1: SKILL.md 書き換え（form＝positive contract・禁止形は使わない）**

frontmatter: `name: gui-verify`、`description:` は「Use when a GUI (PySide6/pyqtgraph) change is nearing done — before declaring a user-facing feature complete or merging」（トリガ条件のみ・ワークフロー非要約）。
本文に以下を必須収録:
- **merge 前ゲート = 以下をすべて満たす**: (a) `uv run pytest` 0 errors／(b) **E2E 十分性 contract（spec §3.1）を満たす**＝変更が触れるジャーニーの各ユーザー可視効果に正しい E2E タイプの実 observable（realgui スクショ/prod スケール実測/描画スクショ）が対応し、変更挙動を実経路で exercise し、嘘プロキシで代替していない／(c) ①realgui 証拠（入力経路変更時・`reference/gate-and-pitfalls.md`）／(d) CI 緑。
- **判定の形（positive contract）**: 「E2E 証拠が contract の**必須構成要素**（ジャーニー/observable/prod スケール/実経路 exercise/非プロキシ）に一致するか」で充足/未充足を出す。**未充足時は欠けている構成要素を具体的に名指し**し、埋める観測手順（`reference/proactive-e2e.md`）へ誘導する。**禁止リスト（"…せず done するな"）/rationalization 表/red flags は書かない**（writing-skills: 不完全出力に禁止形は逆効果）。
- **不十分な E2E 証拠の具体例**（充足と誤認しやすいもの・contract のどの要素が欠けるか）: 同名だが別コードを触る realgui（実経路 exercise 欠）／`isVisible()` 等の嘘プロキシ（実 observable 欠・FU-04）／小データ perf（prod スケール欠・FU-11）／スクショ無しの視覚判定（描画 observable 欠・FU-12）。

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
feat(skill): gui-verify を「E2E 十分性 contract 点検」merge 前ゲートへ

merge 前ゲートを positive contract（ジャーニー/observable/prod スケール/実経路
exercise/非プロキシ）の充足点検として再定義。不十分な E2E 証拠(同名別コード
realgui/isVisible プロキシ/小データ perf/スクショ無し)を未充足と判定し欠けた
構成要素を名指し。gui-testing-layers.md の検証関連を reference へ移設し自己完結化。
禁止形/rationalization 表は使わない(不完全出力に逆効果)。

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

### Task 5: 検証 — application/coverage テスト＋contract 文言の束縛性 micro-test＋不足の穴埋め

**Files:**
- Modify（必要時）: `.claude/skills/gui-verify/SKILL.md`・`.claude/skills/gui-test-plan/SKILL.md`（contract の抜け穴を締める）
- Create: `<scratch>/verification.md`（検証結果）

**Interfaces:**
- Consumes: 強化版スキル（Task 2/3）。
- Produces: 合格実証（contract を持つ agent が**十分な E2E**を設計/点検する）。

- [ ] **Step 1: contract 文言の束縛性 micro-test**

contract 文言を、**no-guidance control（現行 diff スコープ）＋ contract 版** の 2 群 × 5 reps で micro-test（fresh-context 1 サンプル/call・全ヒット目視・variance を見る）。判定: contract 版の agent が**ジャーニー/observable/prod スケール/実経路 exercise/非プロキシ**の必須要素を揃えるか（control は diff スコープ止まり）。variance が高い＝束縛が弱ければ recipe を締める（必須要素を構造化・nuance 節を除去）。

- [ ] **Step 2: application 検証（GREEN・2 方向）**

強化版スキルを持つ fresh subagent で:
- **gui-test-plan**: 与えた GUI 機能（例 FU-11/12/04 類似）から**十分な E2E 設計**（正しいジャーニー＋E2E タイプ別 observable＋prod スケール要否＋実経路 exercise）を産むこと。control は不足に留まること。
- **gui-verify**: 不十分な E2E 証拠（同名別コード realgui／`isVisible` プロキシ／小データ perf／スクショ無し）を渡すと、**未充足と判定し欠けた構成要素を名指し**すること。

- [ ] **Step 3: 不足の穴埋め（締めループ）**

検証で contract が要素を取りこぼす/曖昧（例「prod 生成が重いので quick で代替」を十分と誤認）なら、その要素を contract に明示追加して再検証。bulletproof まで反復（禁止形でなく**必須要素の追加**で締める）。

- [ ] **Step 4: 最終自己完結＋repoint 総点検**

Run: `grep -rln "gui-testing-layers" . | grep -vE "docs/superpowers/(specs|plans)/|\.kiro/"` → 0。
Run: `uv run pytest -q` → 0 errors（コメント変更の無回帰）。

- [ ] **Step 5: コミット（穴埋めがあれば）**

```bash
git add .claude/skills/
git commit -m "$(cat <<'EOF'
refactor(skill): application 検証で判明した contract の取りこぼし要素を追加

contract 版で agent が十分な E2E を設計/点検することを実証。不十分な E2E 証拠を
未充足と名指しできることを確認。取りこぼした必須要素を contract へ追加。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0185WwLfeTaikM3BFQ3u63vL
EOF
)"
```

---

## Self-Review

- **Spec coverage**: §2 E2E スペクトル→Task 2/3、§3 十分性 contract→Task 3（gui-verify 点検）・Task 2（gui-test-plan 設計）・§3.2 真因実測→Task 2、§4 スキル再設計→Task 2/3、§5 移設マップ→Task 2/3、§6 削除+repoint→Task 4、§7 作り方→Task 1/5、§8 受け入れ→Task 5。全節にタスク対応。
- **Placeholder scan**: TBD/「適切に」等なし。各 Step は具体アクション。skill 本文プロースは spec §3.1/§4/§5 が contract 構成要素を規定し、Task 1 coverage baseline が「欠けると不十分な要素」を供給する（プランに最終散文を丸写ししない代わりに必須要素を列挙）。
- **Type/naming consistency**: `name: gui-test-plan`/`gui-verify`、reference: `e2e-model.md`/`proactive-e2e.md`/`gate-and-pitfalls.md`/`realgui-recipe.md`/`output-template.md`。E2E スペクトル3タイプ（入力/perf/描画）と merge 前ゲート4項目(a-d)・contract 必須構成要素（ジャーニー/observable/prod スケール/実経路 exercise/非プロキシ）は Task 2/3 で一貫。
- **writing-skills 準拠**: Iron Law（Task 1 coverage baseline 先行・実行済み）・**form-matching＝positive contract/recipe（禁止形不使用）**・description=when-only（ワークフロー非要約）・token 効率（reference 分離）・contract 文言 micro-test（Task 5）を Global Constraints ＋各 Task に反映。
