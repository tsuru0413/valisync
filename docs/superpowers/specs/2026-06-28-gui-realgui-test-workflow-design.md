# GUI realgui テストワークフロー設計（2スキル＋ポリシー）

> **種別**: brainstorming 設計ドキュメント（spec）。実装プランは承認後 `docs/superpowers/plans/2026-06-28-gui-realgui-test-workflow.md` に writing-plans で生成する。
> **対象**: PySide6/pyqtgraph GUI（`src/valisync/gui/`）の入力経路テスト運用。

## 1. 背景・課題

GUI テストは `docs/gui-testing-layers.md` の 3 レイヤー（A=ヘッドレス状態 / B=`sendEvent` 実イベント経路 / C=`--realgui` 実 OS 入力）で運用している。このうち **Layer C（realgui）** に 2 つの実運用課題がある。

- **課題① realgui テストが高頻度でスキップされる**
  `@pytest.mark.realgui` がオプトイン（`--realgui`）で、CI（Linux・非 Windows）でも自動スキップ。結果、日常の `uv run pytest` でも CI でもまず実行されない。**「skipped」が「検証済み」と誤認**され、回帰が素通りし、テストが腐敗する。

- **課題② 作成された realgui テストの検証項目が安直で不足**
  realgui のアサーションは書きにくく、安直な実装は「VM 状態を再チェック＋スクショ保存」止まりになりがち（例: 既存プラン `2026-06-27-multi-column-y-axis.md` Task 4.1「`vm.axes[i].column` が変わった＋スクショ保存」）。これは **実経路でしか証明できない結果**（軸が視覚的に目的列へ着地・挿入線描画・source dimmed）を検証しておらず、Layer A と重複するだけで**浅い**。

## 2. ゴール / 非ゴール

**ゴール**: 上記①②への対策を、開発ワークフロー（brainstorming → writing-plans → 実装 → verify → merge）に**組み込む**。

**非ゴール（今回やらない）**:
- フックによるハード強制（pre-push/pre-merge ブロック）。強制度は**規律ゲート**を採用（ユーザー決定）。フック/定期ローカル実行は将来オプションとして残すが本スコープ外。
- 既存 `tests/realgui/` 全本の自動リファクタ。①②での一度の監査は**任意フォローアップ**として記すに留める。
- 非 GUI タスクへの適用（素直に「Layer A のみ・realgui 不要」と返すのみ）。

## 3. 解決アーキテクチャ概要

**2 つの薄い・自己完結スキル**を、ライフサイクルの継ぎ目（**設計時 vs 実行時**）で分割する。共有するのは**ポリシー**だけで、**運用ノウハウは各スキルが own** する。

| | スキル | 働く時点 | 主担当課題 | 隣接する既存資産 |
|---|---|---|---|---|
| **A** | `/gui-test-plan` | 計画時（受け入れ要件を設計） | **②** 検証の実質性 | `writing-plans` |
| **B** | `/gui-verify` | 実装後/verify/merge 前（実行・証拠化） | **①** 高頻度スキップ | `/run`・`/verify`・`verification-before-completion` |

**設計→実行のハンドオフ**: `/gui-test-plan` が「実質的な受け入れ要件」と「証拠ゲートの仕様」を**書く** → `/gui-verify` がそれを**実行し証拠化**する。これは既存の `/run`・`/verify`（実行）が計画と分離しているのと同じ構図。

### 3.1 知識の所有原則（本設計の中核判断）

スキルは**自己完結**であるべき。スキルの**実体（運用ノウハウ）が外部 docs に在る**のは smell。一方で**方針/標準**は元々 human/workflow の文書であり、スキルはそれを「参照」ではなく **enforce** する（lint がスタイル設定を enforce するのと同じ）。よって知識を 2 種に分けて配置する。

| 知識の種類 | 例 | 置き場所 | 所有者 |
|---|---|---|---|
| **運用ノウハウ** | realgui 駆動レシピ、出力ブロック雛形 | スキルの `reference/` | 各スキル |
| **方針/標準** | どの変更にどのレイヤー、①証拠ルール、②実質性原則 | `docs/gui-testing-layers.md`（`workflow.md §7` 必読） | human/workflow |

この分類により「2 スキルが同じ運用知識を共有する」状況がほぼ消える（後述 3.4）。したがって運用レシピ用の独立 doc（`docs/realgui-patterns.md` 等）は**作らない**。スキルが触れる唯一の "doc" は enforce 対象の必読ポリシーのみ。

### 3.2 Skill A: `/gui-test-plan`（計画時・②中心）

- **役割**: GUI タスクのテスト戦略と**実質的な受け入れ要件**を設計し、writing-plans が織り込める**分析ブロック**を返す（非破壊）。
- **入力**: spec 名 / `tasks.md` / writing-plans の下書きプラン / 自由記述のタスク。
- **タスクごとの出力（分析ブロック）**:
  1. **変更種別の分類**: VM/純ロジック | ウィジェット構成・状態 | 入力イベント→ハンドラ。
  2. **必要レイヤー判定**（A 必須 / B 要否 / C 要否）＋根拠。`gui-testing-layers.md` の必須運用表を **enforce**。
  3. **入力経路の再現可否**: `sendEvent` で実経路再現可（例 `QContextMenuEvent`）か、**Layer C 専用**（例 `QDrag` D&D は合成イベントで配送不可）か。新規/不明な経路は「**手法を確立せよ**」とフラグし `/gui-verify` のレシピへ誘導。
  4. **受け入れ要件 Red/Green/Verify**。Verify 段は **`/run`・`/verify` がそのまま食える観測チェックリスト**形式（起動 `uv run valisync` ＋手順＋観測項目）。
  5. **②実質性ルーブリックの適用**（後述 3.5）: 人間が見て合格と判断する観測項目を列挙し、各項目を「自動アサート可」か「スクショ＋`/verify` 観測」に割り当て。**「スクショ保存だけ」「VM 再チェックだけ」を naive としてフラグ**。
  6. **①証拠ゲートの仕様**: 「該当 realgui を scoped 実行し証拠添付」を**プランの必須チェックボックス**として埋め込む（仕様のみ。実行は `/gui-verify`）。
  7. **honest layering note**: 例「ハンドラ直叩きは Layer B ではない（scene の mouse-dispatch/hit-test を迂回する）」。
- **所有物**: 出力ブロック雛形（`reference/output-template.md`）。**enforce 対象**は `docs/gui-testing-layers.md`。
- **任意の内部委譲**: 似た既存入力経路テストの走査（再利用パターン抽出）など**ノイジーな調査**は `gui-test-strategist` サブエージェントに dispatch し、結論だけ受け取る（計画コンテキストを汚さない）。単純ケースはスキル内で完結。

### 3.3 Skill B: `/gui-verify`（実行時・①中心）

- **役割**: 証拠ゲートを**実行**する。①の根因である「摩擦」を消す。
- **手順**:
  1. `git diff` → 変更された GUI ファイル（`src/valisync/gui/...`）を特定。
  2. 対応する `tests/realgui/test_*.py` をマッピング（**全 realgui ではなく該当のみ**＝低摩擦）。
  3. `uv run pytest --realgui tests/realgui/test_X.py` を実行。
  4. 視覚項目は `/run`（起動・スクショ）・`/verify`（駆動・観測）を駆動。
  5. **証拠（pass ログ＋スクショ）を集約**。揃わなければ／失敗していれば **"done" をブロック**（`verification-before-completion` の具体例）。
- **所有物（自己完結）**: `reference/realgui-recipe.md` に**駆動レシピ**を own:
  - 実 D&D の move/release は **別 OS スレッド＋watchdog** で駆動（`QDrag.exec` の OLE モーダルループが Qt single-shot タイマーを starve するため `QTimer` 駆動は無限ハング）。
  - DPI 論理→物理変換（`* devicePixelRatioF()`）。
  - **スクショは GUI スレッドで撮る**（ワーカースレッドからの Qt `grabWindow` 不可）。
  - **offscreen の `grab()` は全文字□（フォント無し）→ 読める画像は `QT_QPA_PLATFORM=windows` で撮る**。
  - `QGraphicsView.mapFromScene()` は PySide6 で `QPoint` を返す（`.toPoint()` で AttributeError）。
  - **`sendEvent` では D&D の実配送経路を再現できない**（バブリング設計のため）→ D&D は Layer C 専用。
- **自己完結性**: 読むのは自分の `reference/` ＋ enforce 対象の必読ポリシーのみ。

### 3.4 サブエージェント: `gui-test-strategist`（任意）

`/gui-test-plan` が必要時に dispatch する**走査/分析ワーカー**。隔離コンテキストで `tests/` を走査し、当該入力経路に似た既存テスト・再利用パターンを特定して**結論のみ**返す。計画コンテキストを汚さないための内部最適化であり、必須ではない。

### 3.5 ②実質性ルーブリック（ポリシーとして `gui-testing-layers.md` へ）

realgui のアサーションは次を満たすこと（手書き勢も従う標準）:

1. **Layer A/B で再チェック不能なものを対象にする**（OS→Qt 配送・ヒットテスト・**描画結果**）。VM 状態の再チェックだけ＝Layer A と重複＝**naive**。
2. **「人間なら何を見て合格と判断するか」を列挙**し、各観測項目を割り当てる:
   - **自動アサート可**（`QApplication.activePopupWidget()` でメニュー出現、ウィジェット可視/ジオメトリ、要素数）→ realgui テスト内で直接 assert。
   - **視覚/描画**（ハイライト色、挿入線位置、dimmed source、波形 unclip）→ スクショ＋**`/verify` でエージェント観測**（安定なら pixel サンプル）。
3. **「スクショ保存だけ・アサート無し」を禁止**。

### 3.6 ①証拠ゲートルール（ポリシーとして `gui-testing-layers.md` / `workflow.md §7` へ）

- GUI 入力経路の変更は、**該当 realgui の実行証拠（または視覚項目は `/verify` 観測）を merge 前に要求**する。
- **環境制約で realgui を実行できない場合（非 Windows/ディスプレイ無し）は「ゲート未充足（赤/ブロック）」として扱う**。skipped を緑（検証済み）と誤認させない — ①の根因への直接対策。

## 4. ワークフロー統合（データフロー）

```
brainstorming
   └─> writing-plans（私がプラン起草）
          └─> /gui-test-plan <spec|tasks|draft-plan>
                 ├─(必要時)─> gui-test-strategist サブ（走査）→ 結論
                 └─> 分析ブロック返却（②実質性 + ①ゲート仕様 + Verify チェックリスト）
          └─> 私がプランへ織り込む
   └─> 実装（TDD: Layer A/B）
   └─> /gui-verify（① ゲート実行）
          ├─> 該当 tests/realgui を scoped 実行（--realgui）
          ├─> 視覚項目は /run・/verify を駆動
          └─> 証拠集約 / 未充足なら done をブロック
   └─> merge（証拠が揃って初めて）
```

- **writing-plans 連携**: `/gui-test-plan` は分析ブロックを返すだけ（プランの所有は writing-plans）。
- **`/run`・`/verify` 連携**: `/gui-verify` が視覚項目の検証で両者を駆動（Verify 段の実行アーム）。計画時はコードが無いので `/gui-test-plan` は両者を**呼ばず**、契約（観測チェックリスト）を**書く**だけ。
- **`verification-before-completion` 連携**: `/gui-verify` は「証拠なしに done と言わない」の具体実装。

## 5. エラー / エッジ処理

- **非 GUI タスク**を `/gui-test-plan` に渡した場合 → 「Layer A のみ・realgui 不要・標準 Red/Green」と素直に返す。
- **変更経路に対応する realgui テストが無い**場合 → `/gui-verify` は「この経路に realgui カバレッジ無し。レシピ参照で追加するか、`/verify` 観測のみで足る理由を明記せよ」と**フラグ**（黙って pass しない）。
- **非 Windows/ディスプレイ無し**で `/gui-verify` 実行 → 「ここでは Layer C を実行不可＝ゲート未充足」と報告（黙ってスキップ→緑にしない）。

## 6. スキル自体の検証（dogfooding）

スキルはコードでなく指示文書なので、検証は dogfooding で行う:
- `/gui-test-plan` を既存 spec（例 `valisync-gui-axes`）に対して走らせ、分析ブロックが①②を満たすか（naive アサート検出・Verify チェックリストの観測可能性・ゲート仕様の有無）を確認。
- `/gui-verify` を既知の GUI 変更に対して走らせ、(a) 該当 `tests/realgui` を正しく scoping するか、(b) 証拠（pass ログ＋スクショ）を集約するか、(c) 実行不可環境で「未充足」を返すかを確認。

## 7. 成果物一覧と配置

**スキル（プロジェクト共有・commit、`.claude/skills/`）**
- `.claude/skills/gui-test-plan/SKILL.md` ＋ `reference/output-template.md`
- `.claude/skills/gui-verify/SKILL.md` ＋ `reference/realgui-recipe.md`

**サブエージェント（commit、`.claude/agents/`）**
- `.claude/agents/gui-test-strategist.md`（任意）

**ポリシー doc（commit、編集）**
- `docs/gui-testing-layers.md` — ①証拠ゲートルール・②実質性原則・`/gui-verify` レシピへのポインタを追記。
- `.kiro/steering/workflow.md`（§7）— ①②を必須 steering として参照。

**hygiene（commit）**
- `.gitignore` — `.claude/worktrees/` を追加（skills/agents は追跡したまま worktree だけ除外）。

**brainstorm/plan（commit、`docs/superpowers/`）**
- `docs/superpowers/specs/2026-06-28-gui-realgui-test-workflow-design.md`（本書）
- `docs/superpowers/plans/2026-06-28-gui-realgui-test-workflow.md`（承認後 writing-plans で生成）

**memory（リポジトリ外・ユーザーグローバル、実装後クリーンアップ）**
- realgui 3 件（QTimer ハング・`sendEvent` 不可・offscreen grab □）を `/gui-verify` レシピ（または policy のポインタ）の一次情報へスリム化。

## 8. 関連

- `docs/gui-testing-layers.md` — 3 レイヤー方針（本設計が拡張する POLICY）
- `.kiro/steering/workflow.md §7` — GUI テスト必須運用
- `docs/superpowers/plans/2026-06-27-multi-column-y-axis.md` — Task 4.1 が②の naive アンチパターン実例
- 既存 realgui 実例: `tests/realgui/test_file_browser_realclick.py`（活きた `activePopupWidget` アサート）, `tests/realgui/test_multi_column_axis.py`（OS スレッド駆動の D&D）
