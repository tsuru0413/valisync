# Kiro/dual-agent → superpowers 移行 設計

> **種別**: brainstorming 設計ドキュメント（spec）。実装プランは承認後 `docs/superpowers/plans/2026-06-28-kiro-to-superpowers-migration.md` に writing-plans で生成する。
> **対象**: ドキュメント運用基盤（CLAUDE.md チェーン・`.kiro/`・`docs/`）の再構成。`src/` のコードは変更しない。

## 1. 背景（監査所見）

CLAUDE.md からのドキュメントチェーン監査（2026-06-28）で判明:

- **リンク健全性**: CLAUDE.md の外向きポインタ 20/20 が解決。ダングリング無し。
- **二重運用が既に進行**: 計画成果物が Kiro（`.kiro/specs/` 5 dir）と superpowers（`docs/superpowers/specs/` 4 ＋ `plans/` 8）の二系統。直近の実装（y軸 height-preserve / region-absolute-render / realgui ワークフロー）は全て superpowers。
- **CLAUDE.md の自己矛盾**: 「情報の探し方」優先順位表に `docs/superpowers/` が無く（実際の主力が未掲載）、ワークフロー節は純 Kiro 記述なのにリンク先成果物は superpowers。**記述＝旧、実体＝新**。
- **steering 内部の矛盾**: `product.md`（行39-43）は「ドキュメント・spec は日本語」と規定する一方、`spec-authoring.md`（行130）は「ドキュメント・spec・コミットは英語」と規定。実態は全て日本語。
- **overview-first パターンの死蔵**: `dual-agent-workflow.md` は `docs/<spec>-overview.md` を Kiro 入力として規定するが、直近は brainstorming 設計doc（`docs/superpowers/specs/`）に置換済み。
- **「6 sub-spec」記述のズレ**: `valisync-gui-file-browser` は実在 spec だが6分解リストに含まれず、`analysis/derived/views/script` は未着手。

## 2. 目標・原則

- dual-agent（Kiro + Claude Code）運用を廃止し、**superpowers 駆動（brainstorming → writing-plans → executing-plans / subagent-driven-development）に一本化**する。
- 完了済み Kiro spec は**アーカイブ保持**（歴史・トレーサビリティ）。価値ある steering 知識は `docs/` へ統合。死文の Kiro 専用 doc は廃止。
- Single Source of Truth を維持し、CLAUDE.md は薄いエントリポイントに保つ。
- `src/valisync/` のコード・テストは変更しない（ドキュメントのみ）。

## 3. 確定事項（brainstorming Q&A）

| 論点 | 決定 |
|---|---|
| `.kiro/` 終端状態 | `.kiro/specs/` は**アーカイブ保持**（read-only 歴史）。steering は docs/ へ移設、`dual-agent-workflow.md`・`spec-authoring.md` は廃止。新規 spec は superpowers のみ。 |
| steering 移設方法 | **重複解消しつつ統合**（tech→development、product 原則→policies、structure/workflow は独立移設）。 |
| 言語標準 | **日本語を明文化**（文章＝日本語、コード識別子・技術用語＝英語）を `policies.md` に。既存英語ルールは `spec-authoring.md` 廃止で消滅。 |

## 4. ファイル別 最終状態（移行マップ）

### 廃止（削除）
- `docs/dual-agent-workflow.md` → 新 `docs/development-workflow.md` に置換。
- `.kiro/steering/spec-authoring.md` → 廃止（Kiro spec 生成ルール）。内包する英語ルールは `product.md` の日本語ルールと矛盾しており、**日本語を正**とする。

### 統合（内容マージ）
- `.kiro/steering/tech.md` → `docs/development.md` へ（技術スタック・コマンド）。`product.md` の Coding Standards（Python 3.12 / 型ヒント / frozen dataclass / Protocol / pytest+Hypothesis / uv）も development.md に集約。
- `.kiro/steering/product.md` を分割:
  - **Architecture Principles** ＋ **Language Note** → `docs/policies.md`。
  - **概要 / Target Users / Key Capabilities** → slim な `docs/product.md`（CLAUDE.md「プロジェクト概要」がここを指す）。
  - **Implementation Phases** → CLAUDE.md Phase 表 / `docs/roadmap.md` に集約（重複削除）。

### 独立移設
- `.kiro/steering/structure.md` → `docs/structure.md`。dir tree を更新（`.kiro/` を「archive: specs のみ・steering 撤去済み」と表記、`docs/` の実構造を反映）。**Structural Change Policy**（memory `feedback_structural_change_approval` の根拠）も同梱。
- `.kiro/steering/workflow.md` → 新 `docs/development-workflow.md` に統合（ブランチモデル・命名・標準フロー・main 直編集禁止・PR フロー・CI・GUI テスト §7）。

### 新規
- `docs/development-workflow.md`: **superpowers 計画・実装フロー**（brainstorming → writing-plans → executing-plans / subagent-driven-development）＋ branch/PR フロー（旧 workflow.md 由来）＋ GUI テストレイヤー参照（`docs/gui-testing-layers.md`）＋ `/gui-test-plan`・`/gui-verify`。`dual-agent-workflow.md` の置換。
- `.kiro/ARCHIVE.md`: 「`.kiro/specs/` は完了済み Phase 1/2 の要件/設計/タスクのアーカイブ（歴史・トレーサビリティ）。新規計画は `docs/superpowers/specs|plans/`。steering は `docs/` へ移設済み。」と明記。

### アーカイブ保持（変更なし）
- `.kiro/specs/`（5 dir: valisync-core / valisync-gui / valisync-gui-mvp / valisync-gui-file-browser / valisync-gui-axes）。`docs/development.md` の PBT/MVVM 一次情報源ポインタが `design.md` の Correctness Properties を指すため保持必須。

### 撤去
- `.kiro/steering/`（4ファイル移設＋spec-authoring 廃止後、空ディレクトリを削除）。

## 5. CLAUDE.md 全面書換

| 節 | 変更 |
|---|---|
| 情報の探し方（優先順位表） | **superpowers-first** に再構成: ①`docs/superpowers/specs/` ＋ `plans/`（計画の一次情報・新規）②`docs/<topic>.md`（product/development/structure/policies/development-workflow/gui-testing-layers — 運用・知識）③`.kiro/specs/<spec>/`（**完了済み Phase 1/2 のアーカイブ・歴史**）④本ファイル（発見できない罠） |
| 開発ワークフロー | Kiro 記述を削除し superpowers フローへ。`docs/development-workflow.md` へポインタ。 |
| ブランチ運用 | 脱 Kiro。`feature/<topic>`（spec 単位の束縛を外す）、新規作業着手時は brainstorming から開始。 |
| Phase 状況 | 「一次情報源」列を 完了=`.kiro/specs/...`（archive）/ 新規=`docs/superpowers/...` に。`valisync-gui` 6 分解の注記を実態（file-browser 包含・analysis 等未着手）に修正。 |
| 実装の進め方 | 「必ず tasks.md に従う」→「writing-plans のプランに従い executing-plans / subagent-driven-development で消化」。 |
| ファイル更新ルール | `.kiro/specs/` の tasks.md 更新ルール → superpowers spec/plan の更新ルール（design doc は `docs/superpowers/specs/`、plan は `docs/superpowers/plans/`）。 |

CLAUDE.md は薄さを維持（実体は品質ゲートコマンド等の毎回参照分のみ、他はポインタ）。

## 6. ポインタ張替・既存不整合是正

- `docs/roadmap.md` / `docs/policies.md` / `docs/development.md` の `dual-agent-workflow.md`・`.kiro/steering/*` 参照を新パス（`docs/development-workflow.md`・`docs/structure.md` 等）へ張替。
- `docs/development.md` の PBT/MVVM 一次情報源（`.kiro/specs/.../design.md`）は archive 保持のためそのまま有効。
- **英語/日本語矛盾**の是正: `spec-authoring.md` 廃止＋ `policies.md` に日本語ルール明文化。
- **「6 sub-spec」記述**を実態に合わせて CLAUDE.md / roadmap で修正。

## 7. 検証

- **リンク整合監査の再実行**（本移行を生んだ監査手法）: 移行後の CLAUDE.md チェーン全ポインタの存在確認、かつ `grep` で旧パス（`dual-agent-workflow.md`・`.kiro/steering/`）への**dangling 参照ゼロ**を確認。
- **memory 整合**: `feedback_structural_change_approval`（structure.md 由来）が新パス（`docs/structure.md`）と整合するか、`gui_subspec_decomposition` 等が指す情報が生きているか確認。必要なら memory のポインタを更新（リポジトリ外・別途）。
- **CLAUDE.md 薄さ**: 肥大していないか（ポインタ中心か）目視。
- コード非変更の証拠: `git diff --name-only main...HEAD -- '*.py'` が空。

## 8. スコープ外（非ゴール）

- `src/valisync/` のコード・テスト変更。
- `.kiro/specs/` 内容の書換・移管（アーカイブとして凍結）。
- superpowers スキル自体の改変（既存の brainstorming/writing-plans 等をそのまま使う）。
- 新しい CI/フックの追加。

## 9. 関連

- 監査の発端: 本セッションのチェーン整合性監査。
- 置換対象: `docs/dual-agent-workflow.md`。
- superpowers フロー: `brainstorming` / `writing-plans` / `executing-plans` / `subagent-driven-development` スキル。
- GUI 補助: `/gui-test-plan`・`/gui-verify`（`docs/gui-testing-layers.md`）。
