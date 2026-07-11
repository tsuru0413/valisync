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

## 3. 規律（skill が強制する行動）

### 3.1 先回り E2E 規律（中核・省略不可）
GUI（`src/valisync/gui/`）またはユーザー可視フローに触れる変更で **done を宣言する前に**、`gui-verify` は以下を**構造的 REQUIRED** として要求する:

- 該当**ユーザージャーニー**（開く→ブラウズ→フィルタ→プロット→解析→閉じる のうち触れる区間）を**実アプリで先回り実行**する。
- perf/描画に触れるなら **prod スケール**（`prod_demo.mf4`）で実行する（小データでは FU-11/12/16 は顕在化しない）。
- 実 observable（スクショ/実測）を**観測して課題を報告**する。Claude がユーザーより先に見つける。

観測述語（いつ必須か）: 変更が `src/valisync/gui/` に触れる、またはユーザー可視の挙動/描画/perf を変える → 先回り E2E 必須。純 VM/ロジックのみで可視挙動不変なら Layer A のみ（従来どおり）。

### 3.2 真因は実測で確定してから直す（バグ修正時）
バグ修正では、**適切な E2E タイプで真因を実測/再現してから**修正を書き、**同じ計測で改善を実証**する。コード読解の仮説を"確定"扱いしない。

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
merge 前ゲートを**先回り E2E 込み**に再定義。**構造的 REQUIRED チェックリスト**:

- **(a) headless full**: `uv run pytest` が 0 errors（A/B・テスト間汚染検知）。
- **(b) 先回り E2E ジャーニー**（§3.1・**GUI 変更で必須**）: 該当ジャーニーを prod スケールで実行→スクショ/実測観測→課題報告。
- **(c) ①realgui 証拠**（入力経路変更時・scoped 実行＋証拠）。
- **(d) CI 緑**。

`writing-skills` の form-matching に従い、失敗タイプ＝**規律欠落**なので **REQUIRED 構造＋rationalization 表＋red flags** で書く:

- rationalization 表（例）: 「headless 緑だから done」→ headless 緑 ≠ ユーザー体験検証済み。実アプリを実スケールで見ていない／「realgui は CI skip だから省略可」→ skip は"未検証"であって"OK"ではない。①ゲートの主旨／「小データで動いた」→ FU-11/12/16 は prod スケールでのみ顕在化。
- red flags（STOP）: 「実アプリを一度も起動せず done と言おうとしている」「prod_demo で試さず perf/描画 done」「スクショを撮らず視覚結果を"多分 OK"」。
- **自己完結 reference/**: ①証拠ゲート手順・realgui-recipe（駆動プリミティブ・落とし穴・QSettings 隔離）・**実行関連 false-green 落とし穴**（`id()` フレーク・`qtbot.addWidget` teardown 連鎖・offscreen grab 豆腐）。

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

## 7. 作り方（writing-skills TDD）

**Iron Law: ベースライン失敗を観測せずに書かない**（編集にも適用）。

- **RED（ベースライン）**: 強化版**なし**の subagent に GUI 課題を実装させ、「headless 緑で done 宣言・実アプリを実スケールで操作せず・realgui skip を"検証済み"と誤認」する失敗と rationalization を**逐語採取**。可能なら FU 類似の注入課題（例: 画面外ドック / prod でしか出ない perf）で「見逃す」ことを実証。
- **GREEN**: 採取した rationalization を名指しで潰す強化版を書く（§4）。
- **REFACTOR**: 強化版で再実行し、新 rationalization を閉塞。文言は **micro-test**（no-guidance control＋5 reps・全ヒット目視）で束縛性を確認してから pressure シナリオ。
- **合格基準**: 強化版スキルを持つ fresh subagent が、GUI 課題で**先回りに実アプリを実スケールで E2E し、headless では見えない注入課題を自力で検出**する（ベースラインは done と誤宣言）。

## 8. 受け入れ（テスト戦略）

スキルは "process documentation" なので、テスト＝**subagent pressure シナリオ**（`writing-skills`）:

1. **discipline 検証**: 「時間がない/headless 全緑だから done でよいか」の圧力下で、強化版 gui-verify を持つ agent が先回り E2E を省略しないこと。
2. **application 検証**: gui-test-plan を持つ agent が、与えられた GUI 機能から正しいジャーニー＋E2E タイプ＋observable を設計できること。
3. **自己完結検証**: `gui-testing-layers.md` 不在でも両スキルが単体で必要情報を提供できること（外部参照ゼロ）。
4. **repoint 検証**: `grep gui-testing-layers` がアクティブ集合で 0 ヒット（archive を除く）。

## 9. 非目標（YAGNI）

- realgui を CI で回す仕組みは作らない（実ディスプレイ依存で構造的に CI 不可）。
- A/B/C レイヤーの**意味自体**は変えない（再配置・再フレームであって再定義でない）。
- archive（superpowers specs/plans・kiro）は編集しない。
- 巨大な自動 E2E スイート化はしない（先回り E2E は Claude がローカルで回す規律であって、網羅スイート構築ではない）。

## 10. 影響ファイル

- **書き換え**: `.claude/skills/gui-test-plan/SKILL.md` ＋ `reference/*`、`.claude/skills/gui-verify/SKILL.md` ＋ `reference/*`。
- **削除**: `docs/gui-testing-layers.md`。
- **repoint**: `docs/workflow.md`・`CLAUDE.md`・`docs/development.md`・`docs/realgui-coverage-audit.md`・`.claude/agents/gui-test-strategist.md`・アクティブテスト約13本。
- **新規（テスト資産）**: 先回り E2E ジャーニーの雛形/チェックリスト（reference 内）。
