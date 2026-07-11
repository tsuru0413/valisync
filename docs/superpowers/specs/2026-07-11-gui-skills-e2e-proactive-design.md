# gui-test-plan / gui-verify を「先回り E2E」スキルへ強化 — 設計 spec

- **日付**: 2026-07-11
- **対象ブランチ**: `worktree-gui-skills-e2e`
- **種別**: スキル強化（`writing-skills` の TDD-for-skills で実施）

## 1. 問題と狙い

### 1.1 問題
FU-01〜17 の課題は、いずれも**実装済みアプリをユーザーが実データで操作して初めて発覚**した（例: FU-01 ダイアログ画面外・FU-04 ドック画面外・FU-11 フィルタ 17s フリーズ・FU-12 y=45 不可視・FU-16 クローズ遅延）。共通構造は「**headless テストは緑だが、実アプリを実スケールで操作していないので見えなかった**」。ユーザーが後から発見する＝**修正の手戻り**が発生し、開発効率と正確性を損なう。

### 1.2 狙い
`gui-test-plan` / `gui-verify` を、**Claude が開発中に自律的に E2E を先回り実行してユーザーより先に課題を検出する**スキルへ再方向づける。あわせて2つの構造要件:

1. **自己完結**: スキルは外部プロジェクト doc（`docs/gui-testing-layers.md`）に依存せず、`SKILL.md ＋ 自前 reference/` で完結する（`writing-skills` の自己完結原則）。→ `gui-testing-layers.md` を**削除**し内容をスキルへ移設、参照元を repoint。
2. **作り方は TDD-for-skills**: `writing-skills` の RED→GREEN→REFACTOR。強化版なしのベースライン失敗を観測してから書く。

## 2. 中核概念: E2E スペクトル

「E2E テスト」＝**ユーザーがする実入力→実出力の経路を通し、実 observable を判定する**こと。検証対象で3タイプに分かれる。Layer A/B はその下位（構造は証明するが end-to-end observable は証明しない）。

| E2E タイプ | 実経路 | 判定 observable | 対象例 | 環境 |
|---|---|---|---|---|
| **入力経路 E2E**（realgui = 従来 Layer C） | 実 OS 入力→実 Qt 経路→実描画 | スクショ目視 ＋ `activePopupWidget`/可視/ジオメトリ assert | メニュー・D&D・キー・クリック（FU-01/04） | 実ディスプレイ＋Windows |
| **perf E2E** | 実コード経路を **prod スケール**（`prod_demo.mf4`・330k ch）で実行 | **実測 wall-clock / call-count** vs 目標 | perf（FU-08/11/16） | ヘッドレス可（プロファイル）＝GUI クリック不要でも"実スケール実経路"で E2E |
| **描画 E2E** | 実データで実プロットを描画 | **スクショ目視** | 描画の正しさ（FU-12） | 実ディスプレイ |

> **要点**: 「真因確定」も「修正検証」も、対象に応じた E2E タイプで**実測/実描画で締める**のが確定。コード読解だけの仮説は"有力"止まりで確定ではない（FU-11/12/16 の教訓）。

## 3. 十分な E2E 検証の contract（skill が規定する構成要素）

### 3.0 問題の形と skill の形（writing-skills form-matching）
RED ベースライン（§7）で判明: 真面目な agent は検証をサボらない（規律失敗は無い）。真の失敗は **「E2E 検証そのものが不十分」＝真面目に回しても diff スコープ止まりで、ジャーニー/prod スケール/実 observable を保証しないため実ユーザー課題を捕まえられない**（wrong-shaped/incomplete output）。

`writing-skills` の form-matching に従い、これは **禁止形（rationalization 表/red flags）ではなく positive な contract/recipe** で対処する。skill は「**十分な E2E 検証とは何か＝その必須構成要素**」を規定し、真面目な agent が回せば**十分なカバレッジを産む**ようにする（禁止形は不完全出力に逆効果、と writing-skills が明言）。

### 3.1 十分な E2E 検証の contract（必須構成要素・順序）
GUI（`src/valisync/gui/`）またはユーザー可視フローに触れる変更の E2E 検証は、以下を**すべて満たして初めて十分**:

1. **ジャーニー同定**: 変更が参加する**実ユーザージャーニー**（開く→ブラウズ→フィルタ→プロット→解析→閉じる のうち触れる区間）を diff でなく**ユーザー視点**で特定する。
2. **効果ごとに E2E タイプ＋実 observable を割当**: ユーザー可視の各効果に対し §2 の E2E タイプと**実 observable**を明記—入力=realgui＋スクショ/`activePopupWidget`、perf=**prod スケール実測**、描画=**スクショ視覚判定**。
3. **prod スケール必須**: perf/描画がスケールしうるなら `prod_demo.mf4`（330k）で締める（小データは FU-11/12/16 を隠す）。
4. **observable は"ユーザーが実際に見る/体験する終状態"**: 嘘をつく headless プロキシで代替しない（`isVisible()` の偽陰性＝FU-04・`setText()` 1回 vs 実打鍵・**隣接コードの同名 realgui**）。
5. **カバレッジ完全性**: E2E 証拠が**変更したユーザー可視挙動を実経路で実際に exercise している**こと（S1 の教訓: 同名だが別コードを触る realgui は"カバレッジ"でない）。

これを満たさない E2E 証拠は**不十分**＝未充足。gui-test-plan が contract を**設計**し（どのジャーニー/observable）、gui-verify が contract 充足を**実行/点検**する。

### 3.2 真因は実測で確定してから直す（バグ修正時）
バグ修正では、**適切な E2E タイプで真因を実測/再現してから**修正を書き、**同じ計測で改善を実証**する。コード読解の仮説を"確定"扱いしない（これも E2E 十分性の一部＝症状の実 observable で確定する）。

## 4. スキル再設計

### 4.1 gui-test-plan（自己完結・計画時）
- **入力**: GUI 機能/変更、またはバグ。
- **出力（分析ブロック）**:
  1. 触れる**ユーザージャーニー**と、その **E2E 受け入れ**（どの E2E タイプが証明するか＋具体 observable）。
  2. レイヤー計画（A/B は従来判定・入力経路/perf/描画 E2E は §3.1 述語で必須判定）。
  3. **②実質性**（人間が何を見て合格と判断するか→自動 assert 可 / 視覚・実測 に割当。naive フラグ）。
  4. バグなら **真因の実測確定計画**（§3.2）。
- **自己完結 reference/**: E2E スペクトル・レイヤーモデル（A/B/C 定義・入力の出所判定・偽装アンチパターン）・②実質性ルーブリック・**計画関連 false-green 落とし穴**（render 経由 x_range 罠・move 不達・合成 dblclick warm-up＝「どの層が何を捕捉するか」の判断材料）・output-template。

### 4.2 gui-verify（自己完結・merge 前ゲート）
merge 前ゲートを **E2E 十分性 contract の点検**として再定義（positive contract 形＝§3.0）。ゲート充足 = 以下を**すべて満たす**:

- **(a) headless full**: `uv run pytest` が 0 errors（A/B・テスト間汚染検知）。
- **(b) E2E 十分性 contract（§3.1）を満たす**: 変更が触れるジャーニーの各ユーザー可視効果に、正しい E2E タイプの**実 observable**（realgui スクショ/prod スケール実測/描画スクショ）が対応し、**変更挙動を実経路で exercise**し、**嘘プロキシで代替していない**こと。不足があれば**どの効果の観測が欠けているか**を名指しで未充足報告。
- **(c) ①realgui 証拠**（入力経路変更時・scoped 実行＋証拠。skip≠検証済み）。
- **(d) CI 緑**。

**判定の形（positive contract）**: 「E2E 証拠が contract の必須構成要素（ジャーニー/observable/prod スケール/実経路 exercise/非プロキシ）に一致するか」で充足/未充足を出す。禁止リスト（"…せず done するな"）や rationalization 表は使わない（writing-skills: 不完全出力に禁止形は逆効果）。未充足時は**欠けている構成要素を具体的に列挙**し、それを埋める観測手順（`reference/proactive-e2e.md`）へ誘導する。

- **自己完結 reference/**: E2E 十分性 contract 点検手順・①証拠ゲート・realgui-recipe（駆動プリミティブ・落とし穴・QSettings 隔離）・先回り E2E ジャーニーの駆動手順（prod スケール起動・スクショ/実測観測）・**実行関連 false-green 落とし穴**（`isVisible` 偽陰性・`id()` フレーク・`qtbot.addWidget` teardown 連鎖・offscreen grab 豆腐）。

### 4.3 記述形式（writing-skills 準拠）
- `description` は「Use when…（トリガ条件のみ）」でワークフローを要約しない（要約すると skill 本体を読み飛ばす）。
- token 効率: `SKILL.md` は簡潔に、重い内容（レイヤーモデル・落とし穴集・recipe）は `reference/` へ。
- 小さいフローチャートは判断が非自明な箇所のみ。

## 5. `gui-testing-layers.md` 内容の移設マップ

| 現 `gui-testing-layers.md` の中身 | 移設先 |
|---|---|
| Layer A/B/C 定義・入力の出所判定・偽装アンチパターン・必須運用表 | **gui-test-plan** reference（計画が"どの層"を所有）＋ gui-verify reference に C 実行の要点を簡潔再掲 |
| ②実質性ルール | gui-test-plan reference |
| ①証拠ゲート | gui-verify reference |
| false-green: render×x_range 罠・move 不達・合成 dblclick warm-up | gui-test-plan reference（"どの層が捕捉するか"の計画判断） |
| false-green: `id()` フレーク・qtbot teardown 連鎖 | gui-verify reference（実行/回帰の安定化） |
| Layer C 専用 D&D 配送 | gui-verify reference（realgui-recipe と同居） |
| コマンド早見表 | 両 reference に該当分 |
| 背景（PR #11 origin story） | 要点のみ各 reference の "なぜ" に凝縮（narrative は削る＝writing-skills 反ナラティブ） |

> 自己完結 > DRY: レイヤー定義の**中核**は両スキルで簡潔に重複してよい（各々が単体で成立するため）。147 行の丸コピーはせず、各スキルの仕事に必要な粒度で持つ。

## 6. 削除と repoint

- **削除**: `docs/gui-testing-layers.md`。
- **repoint（アクティブのみ）**: `docs/workflow.md`・`CLAUDE.md`・`docs/development.md`・`docs/realgui-coverage-audit.md`・`.claude/agents/gui-test-strategist.md`・アクティブなテストファイルのコメント参照（約13本: `tests/gui/test_realgui_layer_c_contract.py`・`tests/realgui/*` 群・`tests/gui/test_file_browser_view.py`・`tests/gui/test_diagnostics_view.py`）→ 参照先を「`/gui-test-plan`・`/gui-verify` スキル」へ。
- **触らない（archive）**: `docs/superpowers/specs|plans/*`・`.kiro/specs/*` は日付きスナップショット（当時の事実を反映・編集しない）。削除 doc への参照が残るが許容。

## 7. 作り方（writing-skills TDD・form=positive recipe）

**Iron Law: ベースライン失敗を観測せずに書かない**（編集にも適用）。失敗タイプは**規律欠落でなく不完全出力**なので、テストは pressure でなく **application/カバレッジ**、form は **positive recipe**（writing-skills form-matching）。

- **RED（coverage ベースライン・観測済み）**: 現行（diff スコープ）gui-verify を適用した agent の E2E 検証が**不十分**であることを示す。**実測済み**: 2 subagent（capable・full repo access）とも「現行の E2E 証拠は diff スコープで不足（S1: フィルタの realgui 不在・S2: `isVisible` 偽計器で回帰未実行）」と判定＝現行 method の不十分性を実証（`baseline-findings.md`）。※両者は現行 `gui-testing-layers.md`＋memory に依存して不足を"検出"できていた＝削除時は権威を skill へ移設・強化しないと後退する。
- **GREEN**: E2E 十分性 contract（§3.1）を positive recipe で書く（§4）。「十分な E2E とは何か＝必須構成要素」を規定。
- **micro-test（文言の束縛性）**: contract 文言を、no-guidance control＋contract 版の 2 群 × 5 reps で micro-test（fresh-context・全ヒット目視・variance を見る）。**判定**: contract 版の agent が**ジャーニー/observable/prod スケール/実経路 exercise/非プロキシ**の必須要素を揃えた E2E を設計するか（control は diff スコープ止まり）。variance が高ければ recipe を締める。
- **合格基準**: contract を持つ fresh subagent が、GUI 課題から**十分な E2E 検証**（正しいジャーニー＋E2E タイプ別 observable＋prod スケール＋実経路 exercise＋嘘プロキシ非使用）を設計/実行し、FU-11/12/16/04 類似の"実スケール/視覚でしか見えない"課題を**捕捉できる観測を含む**こと。

## 8. 受け入れ（テスト戦略）

失敗＝**不完全出力**なので、テストは **application/カバレッジ**（discipline pressure ではない）:

1. **application（gui-test-plan）**: contract を持つ agent が、与えた GUI 機能から**十分な E2E 設計**（ジャーニー＋E2E タイプ別 observable＋prod スケール要否＋実経路 exercise）を産むこと。control（現行 diff スコープ）は不足に留まること。
2. **application（gui-verify）**: contract を持つ agent が、不十分な E2E 証拠（例: 同名だが別コードの realgui・`isVisible` プロキシ・小データ perf）を**未充足と判定し欠けている構成要素を名指し**できること。
3. **retrieval/自己完結**: `gui-testing-layers.md` 不在でも両スキルが単体で必要情報を提供（外部参照ゼロ）。RED が示したとおり agent が現に頼る権威（ゲート定義・②/①・偽陰性計器の知識）を skill が**保持・強化**していること。
4. **repoint 検証**: `grep gui-testing-layers` がアクティブ集合で 0 ヒット（archive を除く）。

## 9. 非目標（YAGNI）

- realgui を CI で回す仕組みは作らない（実ディスプレイ依存で構造的に CI 不可）。
- A/B/C レイヤーの**意味自体**は変えない（再配置・再フレームであって再定義でない）。
- archive（superpowers specs/plans・kiro）は編集しない。
- 巨大な自動 E2E スイート化はしない（先回り E2E は Claude がローカルで回す実践であって、網羅スイート構築ではない）。

## 10. 影響ファイル

- **書き換え**: `.claude/skills/gui-test-plan/SKILL.md` ＋ `reference/*`、`.claude/skills/gui-verify/SKILL.md` ＋ `reference/*`。
- **削除**: `docs/gui-testing-layers.md`。
- **repoint**: `docs/workflow.md`・`CLAUDE.md`・`docs/development.md`・`docs/realgui-coverage-audit.md`・`.claude/agents/gui-test-strategist.md`・アクティブテスト約13本。
- **新規（テスト資産）**: 先回り E2E ジャーニーの雛形/チェックリスト（reference 内）。
