# Kiro/dual-agent → superpowers 移行 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dual-agent（Kiro + Claude Code）運用を廃止し、CLAUDE.md・docs・`.kiro/` を superpowers 駆動へ再構成する（`.kiro/specs` はアーカイブ保持、steering は docs/ へ統合、Kiro 専用 doc は廃止）。

**Architecture:** ドキュメントのみの再構成（`src/` は不変）。先に新しい知識の置き場所（docs/ 統合・新 `docs/workflow.md`）を作り、次に CLAUDE.md を superpowers-first に書換、最後にポインタ張替・旧ファイル廃止・リンク整合検証を行う。

**Tech Stack:** Markdown ドキュメント。検証は `git`・`grep`・`test -f`（コードは変更しない）。設計 spec: `docs/superpowers/specs/2026-06-28-kiro-to-superpowers-migration-design.md`。

## Global Constraints

- **Markdown のみ**。`src/valisync/` のコード・テストは変更しない（最終検証で `git diff --name-only main...HEAD -- '*.py'` が空であること）。
- **言語**: 文章（docs・コミット・PR）は日本語、コード識別子・技術用語は英語。
- **`.kiro/specs/` は凍結**（read-only アーカイブ。内容を書換えない）。
- **新プロセス doc は `docs/workflow.md`**（設計 spec の暫定名 `development-workflow.md` を、既存 `docs/development.md`「Development Workflow」との衝突回避のためリファイン）。`docs/workflow.md` は `.kiro/steering/workflow.md` と `docs/dual-agent-workflow.md` の両方を置換する。
- 各タスク末尾で commit。コミットメッセージ末尾に必ず:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Cq544M9LSEXJ285J1k46LF
  ```

---

## File Structure

| ファイル | 操作 | 責務 |
|---|---|---|
| `docs/development.md` | 変更 | tech.md（技術スタック）＋ product Coding Standards を統合。tech.md/dual-agent ポインタ更新 |
| `docs/policies.md` | 変更 | product Architecture Principles ＋ 言語標準を追記。ポインタ更新 |
| `docs/product.md` | 新規 | product.md の概要/Users/Capabilities（slim な製品/ドメイン doc） |
| `docs/structure.md` | 新規 | structure.md を移設（dir tree 更新・Structural Change Policy 同梱） |
| `docs/workflow.md` | 新規 | workflow.md（branch/PR/CI/§7）＋ superpowers 計画フロー。dual-agent-workflow.md の置換 |
| `CLAUDE.md` | 変更 | superpowers-first へ全面書換 |
| `docs/roadmap.md` | 変更 | ポインタ更新＋6-subspec 注記是正 |
| `docs/dual-agent-workflow.md` | 削除 | `docs/workflow.md` に置換 |
| `.kiro/steering/*` | 削除 | 全5ファイル移設/廃止後にディレクトリ撤去 |
| `.kiro/ARCHIVE.md` | 新規 | `.kiro/specs` はアーカイブと明記 |

依存: W1（docs 整備）→ W2（CLAUDE.md 書換）→ W3（ポインタ張替・旧廃止）→ W4（検証）。

---

## Wave 1: steering 知識を docs/ へ統合（新しい置き場所を作る）

### Task 1: `docs/development.md` に技術スタックを統合

**Files:** Modify `docs/development.md`

**Interfaces:**
- Consumes: なし（`.kiro/steering/tech.md` の内容を取り込む）
- Produces: 技術スタックの単一情報源としての development.md（後続の CLAUDE.md 優先順位表が指す）

- [ ] **Step 1: 関連ポインタを更新**
  `docs/development.md:5-9` の「関連」リストを次に置換:
  ```markdown
  関連:
  - `../CLAUDE.md` — エントリポイント
  - `policies.md` — プロジェクト方針
  - `workflow.md` — ブランチ/PR フロー・superpowers 計画フロー
  ```
  （`../.kiro/steering/tech.md` 行と `dual-agent-workflow.md` 行を削除。前者は本ファイルへ統合、後者は廃止。）

- [ ] **Step 2: 「技術スタック」節を追加**
  `docs/development.md` の「## 品質ゲート」(現 line 13) の直前に、以下の節を挿入:
  ```markdown
  ## 技術スタック

  - **言語/ランタイム**: Python 3.12+（`requires-python >= 3.12`）。コアは標準ライブラリ + numpy のみ、GUI は PySide6（LGPL）+ PyQtGraph。
  - **パッケージ管理**: uv（`pyproject.toml` + `uv.lock`）。build backend は setuptools（`pip install -e .` 可）。
  - **コア依存**: numpy（Signal のタイムスタンプ・値配列）。
  - **テスト**: pytest >= 8.0 / Hypothesis >= 6.100 / pytest-cov >= 5.0。カバレッジ下限 80%（`fail_under = 80`）。
  - **Lint/Format/型**: ruff（flake8/isort/black 代替）/ mypy。設定は `pyproject.toml`（`[tool.pytest.ini_options]` / `[tool.ruff]` / `[tool.mypy]`）。
  - **Coding Standards**: 型ヒントを全関数に付与 / immutable データは frozen dataclass + numpy array / インターフェースは Protocol で定義し具象で実装 / 変換処理は新オブジェクトを返す（元データ不変）/ FormatDefinition の永続化は JSON（`data/`）。
  - **GUI entry point**: `src/valisync/gui/app.py`。

  ```

- [ ] **Step 3: 検証**
  Run: `grep -c "技術スタック\|frozen dataclass\|requires-python\|fail_under" docs/development.md; grep -c "steering/tech.md\|dual-agent-workflow.md" docs/development.md`
  Expected: 1 行目 ≥4、2 行目 `0`（旧ポインタ消滅）。

- [ ] **Step 4: Commit**
  ```bash
  git add docs/development.md
  git commit -m "docs: tech.md と Coding Standards を development.md に統合"
  ```

### Task 2: `docs/policies.md` に原則と言語標準を追記

**Files:** Modify `docs/policies.md`

**Interfaces:**
- Consumes: `.kiro/steering/product.md` の Architecture Principles + Language Note
- Produces: 方針・原則・言語標準の単一情報源

- [ ] **Step 1: 関連ポインタを更新**
  `docs/policies.md:5-9` の「関連」を次に置換:
  ```markdown
  関連:
  - `../CLAUDE.md` — エントリポイント (本ファイルへのポインタを持つ)
  - `workflow.md` — 開発フロー（superpowers 計画・branch/PR）
  - `product.md` — プロダクト概要・ドメイン
  - `../.kiro/specs/<spec>/design.md` — 完了済み spec の設計判断（アーカイブ）
  ```

- [ ] **Step 2: 「Architecture 原則」節を追加**
  `docs/policies.md` の「## ドキュメントの育て方」節の直後（`<!-- TODO` ブロックの直前）に挿入:
  ```markdown
  ## Architecture 原則（常時適用）

  - Signal データは immutable（読み込み後の変更禁止）。入力ファイルへの書き込みは厳禁（データ改ざん防止）。
  - 同期・Formula 等の変換処理は元データを変更せず新しいオブジェクトを生成する。
  - Protocol（`typing.Protocol`）でモジュール間インターフェースを定義し疎結合を維持。
  - Strategy パターンでフォーマット別パーサーを差し替え可能にする。
  - コアロジック（データ処理）と GUI 層を分離し、コアは GUI に依存しない。
  - 将来の AD（完全自動運転）スコープ拡張を見据えた拡張性。

  ## 言語標準

  - **文章（docs・設計 spec・コミットメッセージ・PR）**: 日本語。
  - **コード識別子（変数・関数・クラス名）・技術用語**: 英語。
  - **コードコメント**: 日本語可（WHY を書く）。
  - 旧 `.kiro/steering/spec-authoring.md` の「英語で書く」ルールは廃止（実態と逆だった）。
  ```

- [ ] **Step 3: 検証**
  Run: `grep -c "Architecture 原則\|言語標準\|immutable\|コード識別子" docs/policies.md; grep -c "dual-agent-workflow.md\|steering/product.md" docs/policies.md`
  Expected: 1 行目 ≥4、2 行目 `0`。

- [ ] **Step 4: Commit**
  ```bash
  git add docs/policies.md
  git commit -m "docs: Architecture 原則と言語標準を policies.md に追記"
  ```

### Task 3: `docs/product.md`（新規・slim な製品/ドメイン doc）

**Files:** Create `docs/product.md`

**Interfaces:**
- Consumes: `.kiro/steering/product.md` の概要/Users/Capabilities
- Produces: CLAUDE.md「プロジェクト概要」が指す製品 doc

- [ ] **Step 1: 作成**
  `docs/product.md`:
  ```markdown
  # Product — ValiSync

  ## 概要

  ADAS ソフトウェア開発向けの時系列信号データ統合・同期・解析デスクトップ GUI アプリケーション。CAN・XCP・Ethernet・CSV フォーマットの信号を統一時間軸上で可視化・分析する。

  ## 対象ユーザー

  - テストエンジニア: 信号データの読み込み・同期・波形分析
  - テスト設計者: フォーマット定義の管理、Formula の設定、時間オフセットの調整
  - 制御エンジニア: ECU 内部変数（XCP）の時系列データ解析

  ## 主要機能

  - マルチフォーマット信号読み込み（CAN / XCP / Ethernet / CSV）
  - ユーザー定義可能な CSV フォーマット設定
  - ファイル単位の Signal 管理（Signal_Group）
  - マルチフォーマット時刻同期（Unified_Timeline）
  - ファイル単位・信号単位の時間オフセット設定
  - Formula による派生信号生成（入れ子対応）
  - CSV エクスポート
  - 高速波形可視化（GUI）

  > Architecture 原則・Coding Standards は `policies.md` / `development.md`、Phase 進捗は `CLAUDE.md` / `roadmap.md` 参照。
  ```

- [ ] **Step 2: 検証**
  Run: `test -f docs/product.md && grep -c "ValiSync\|対象ユーザー\|主要機能" docs/product.md`
  Expected: `3`。

- [ ] **Step 3: Commit**
  ```bash
  git add docs/product.md
  git commit -m "docs: product.md（製品/ドメイン概要）を新設"
  ```

### Task 4: `docs/structure.md`（structure.md を移設）

**Files:** Create `docs/structure.md`（内容元: `.kiro/steering/structure.md`）

**Interfaces:**
- Consumes: `.kiro/steering/structure.md`
- Produces: ディレクトリ構造・モジュール境界・Structural Change Policy の単一情報源（memory `feedback_structural_change_approval` の根拠）

- [ ] **Step 1: 内容を移設**
  `.kiro/steering/structure.md` の全内容を `docs/structure.md` にコピーする。その上で、ファイルツリー内の `.kiro/` 記述（元 line 73-75）を次に置換し、`docs/` を反映:
  ```
  ├── docs/                                   # 運用知識・superpowers spec/plan
  │   └── superpowers/{specs,plans}/          # 計画の一次情報（新規）
  ├── .kiro/
  │   └── specs/                              # 完了済み Phase1/2 のアーカイブ（要件/設計/タスク）
  ```
  （`steering/  # project-wide rules` 行は削除＝steering は docs/ へ移設済み。）

- [ ] **Step 2: 検証**
  Run: `test -f docs/structure.md && grep -c "Structural Change Policy\|Module Boundaries\|Dependency Rules" docs/structure.md; grep -c "steering/  *# project-wide" docs/structure.md`
  Expected: 1 行目 `3`、2 行目 `0`（steering 行が消えている）。

- [ ] **Step 3: Commit**
  ```bash
  git add docs/structure.md
  git commit -m "docs: structure.md を steering から docs へ移設（dir tree 更新）"
  ```

### Task 5: `docs/workflow.md`（新規・branch/PR ＋ superpowers 計画フロー）

**Files:** Create `docs/workflow.md`（内容元: `.kiro/steering/workflow.md` を脱 Kiro 化 + 新 superpowers 節）

**Interfaces:**
- Consumes: `.kiro/steering/workflow.md`（branch/PR/CI/§7）
- Produces: `docs/dual-agent-workflow.md` と `.kiro/steering/workflow.md` の置換（CLAUDE.md ワークフロー/ブランチ節が指す）

- [ ] **Step 1: workflow.md を移設し脱 Kiro 化**
  `.kiro/steering/workflow.md` の全内容を `docs/workflow.md` にコピーし、以下の脱 Kiro 編集を適用:
  - 冒頭の `> 本ファイルは常時適用ルール。Claude Code / Kiro が…` → `> 本ファイルは常時適用ルール。新規実装に着手するとき、まず本ファイルに従う。`
  - 「### 命名規則」の `spec 単位で実装する場合は spec 名と一致させる: feature/<spec-name>` → `作業単位を表す簡潔な名前にする: feature/<topic>`
  - 「### Claude Code / Kiro の振る舞い」見出し → 「### 着手時の振る舞い」。本文の `新規 spec の実装に着手する際、最初に git checkout -b feature/<spec-name>` → `新規作業は brainstorming → writing-plans の後、feature/<topic> ブランチを切って実装する`。`Kiro` の語を削除。
  - 「## 6. spec / docs 更新の特例」内の `実装直後に CLAUDE.md / steering 更新するケース` → `実装直後に CLAUDE.md / docs 更新するケース`。

- [ ] **Step 2: superpowers 計画フロー節を追加**
  `docs/workflow.md` の「## 1. ブランチモデル」の直前に、以下の節を挿入:
  ```markdown
  ## 0. 計画・実装フロー（superpowers 駆動）

  本プロジェクトは superpowers スキルで計画→実装する（旧 Kiro spec 駆動は廃止）。

  1. **brainstorming** — 要件・設計を対話で詰め、設計 spec を `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` に書く。
  2. **writing-plans** — 設計を bite-sized タスクの実装プラン `docs/superpowers/plans/YYYY-MM-DD-<topic>.md` に落とす。
  3. **executing-plans / subagent-driven-development** — プランをタスク順に消化（各タスクで品質ゲート → commit）。
  4. **finishing-a-development-branch** — テスト確認 → merge / PR。

  - 完了済み Phase 1/2 の計画は `.kiro/specs/`（アーカイブ・歴史）。新規には使わない。
  - GUI 入力経路の実装では `docs/gui-testing-layers.md` のテストレイヤーに従い、計画時に `/gui-test-plan`、merge 前に `/gui-verify` を使う。

  ```

- [ ] **Step 3: 検証**
  Run: `test -f docs/workflow.md && grep -c "superpowers 駆動\|brainstorming\|writing-plans\|gh pr merge" docs/workflow.md; grep -ci "kiro" docs/workflow.md`
  Expected: 1 行目 ≥4、2 行目 `0`（Kiro 語の残存ゼロ）。

- [ ] **Step 4: Commit**
  ```bash
  git add docs/workflow.md
  git commit -m "docs: workflow.md を新設（branch/PR + superpowers 計画フロー、脱 Kiro）"
  ```

---

## Wave 2: CLAUDE.md を superpowers-first へ全面書換

### Task 6: CLAUDE.md 書換

**Files:** Modify `CLAUDE.md`（全面置換）

**Interfaces:**
- Consumes: W1 で作成した docs/（product/development/structure/policies/workflow）
- Produces: superpowers-first のエントリポイント

- [ ] **Step 1: CLAUDE.md を以下で全面置換**
  ````markdown
  # CLAUDE.md

  このファイルは **エントリポイント** — 詳細情報は別ファイルに分散し、ここではポインタと最小限の不変情報のみ保持する。本ファイルが肥大化してきたら積極的に `docs/` に分離する。

  ## 情報の探し方 (優先順位)

  | 順位 | 場所 | 内容 |
  |---|---|---|
  | 1 | `docs/superpowers/specs/` ＋ `docs/superpowers/plans/` | 計画の一次情報源（brainstorming 設計 spec / writing-plans 実装プラン）— **新規作業はここ** |
  | 2 | `docs/<topic>.md`（`product` / `development` / `structure` / `policies` / `workflow` / `gui-testing-layers`） | プロダクト・技術/品質ゲート・構造・方針・開発フロー・GUI テスト |
  | 3 | `.kiro/specs/<spec>/{requirements,design,tasks}.md` | **完了済み Phase 1/2 のアーカイブ**（歴史・トレーサビリティ。新規には使わない） |
  | 4 | このファイル | 上記で発見できないハマりどころと方針概要 |

  **ルール**: `docs/` または `.kiro/specs/`（アーカイブ）で確認可能な情報は本ファイルに重複させず、ポインタで繋ぐ。コードを読めば自明な事実 (ファイル名・関数シグネチャ等) も本ファイルには書かない。

  ## プロジェクト概要

  ADAS ソフトウェア開発向けの時系列信号データ統合・同期・解析デスクトップ GUI アプリケーション。CAN・XCP・Ethernet・CSV フォーマットの信号を統一時間軸上で可視化・分析する。

  詳細: `docs/product.md`

  ## リポジトリ

  - **Remote**: `git@github.com:tsuru0413/valisync.git`
  - **CI**: GitHub Actions (push to main / 全 PR で品質ゲート自動実行)

  ## 開発ワークフロー (superpowers 駆動)

  詳細: `docs/workflow.md`

  - **計画は superpowers** — `brainstorming`（設計 spec）→ `writing-plans`（実装プラン）→ `executing-plans` / `subagent-driven-development`（消化）→ `finishing-a-development-branch`。設計 spec は `docs/superpowers/specs/`、プランは `docs/superpowers/plans/`。
  - CLAUDE.md はエントリポイント (薄く保つ)。詳細は `docs/` に分散、完了済み Kiro spec は `.kiro/specs/`（アーカイブ）。

  ## ブランチ運用 (常時適用)

  詳細: `docs/workflow.md`

  - **main は本番ブランチ** — 直接編集は禁止 (緊急 hotfix を除く)
  - **新機能・修正は `feature/<topic>` ブランチで実装**
  - **フロー**: feature ブランチで実装 → ローカル品質ゲート通過 → push → `gh pr create` → CI 通過 → `gh pr merge --auto` → `git fetch --prune`
  - **着手時**: 新規作業は brainstorming から始め、feature ブランチを切って実装する

  ## Phase 状況

  | Phase | スコープ | 状況 | 一次情報源（`.kiro/specs` はアーカイブ） |
  |---|---|---|---|
  | Phase 1 / valisync-core | Signal・Loader・Sync・Formula・補間・統計・Downsampler・Export・Session | 完了 (PR #2 merged) | `.kiro/specs/valisync-core/` |
  | Phase 2 / valisync-gui-mvp | GUI 歩く骨格: シェル/ドッキング・データ取込/閲覧・タブ/パネル・Y-T 波形・X/Y ズーム/パン・動的 LOD・X 軸同期・D&D・コンテキストメニュー | 完了 (PR #2 merged) | `.kiro/specs/valisync-gui-mvp/` |
  | Phase 2 / valisync-gui-file-browser | FileBrowser の分離: 読み込み済みファイルリストと選択ファイルごとの信号フラットリスト表示 | 完了 (PR #3 merged) — 詳細は [docs/file-browser-spec-revision-followup.md](docs/file-browser-spec-revision-followup.md) | `.kiro/specs/valisync-gui-file-browser/` |
  | Phase 2 / valisync-gui-axes | 複数Y軸レイアウト: リージョンベースのオーバーレイ・Auto-Fit 縮尺・複数列グリッド配置 | R1–R6 完了（PR #4/#13/#14/#16/#17 merged）— 詳細は [docs/multi-axis-multicolumn-followup.md](docs/multi-axis-multicolumn-followup.md)・[docs/multi-axis-empty-region-followup.md](docs/multi-axis-empty-region-followup.md)、設計/プランは `docs/superpowers/specs/`・`docs/superpowers/plans/` | `.kiro/specs/valisync-gui-axes/`（archive）＋ `docs/superpowers/` |

  > Phase 2 `valisync-gui` は sub-spec に分解済み（mvp / file-browser / axes、未着手: analysis / derived / views / script）。詳細は `docs/roadmap.md`。

  新規実装は **writing-plans のプラン（`docs/superpowers/plans/`）に従い番号順 / 依存グラフ順** に進める。完了済み Phase 1/2 の `.kiro/specs/*/tasks.md` はアーカイブ（編集しない）。

  ## プロジェクト方針 (要約)

  詳細: `docs/policies.md`

  - **修正案は症状の隠蔽/緩和/根本解決を明示** — 根本解決を優先
  - **リポジトリ構造はその都度最適化** — 責務分割のため新規ファイル/ディレクトリ作成を躊躇しない
  - **CLAUDE.md はタスクごとに熟成** — 追記候補をユーザーに確認、肥大したら分離

  ## 主要コマンド (品質ゲート)

  ```bash
  uv sync --extra dev          # 初回または依存変更後
  uv run pytest                # 全テスト
  uv run ruff check            # lint
  uv run ruff format           # format
  uv run mypy src/             # 型チェック
  ```

  コミット前に上記全てを通すのが本プロジェクトの品質ゲート。詳細は `docs/development.md` を参照。

  GUI 機能・操作を実装するときは **GUI テストレイヤー（Layer A/B 必須・CI / Layer C はローカル `--realgui`）** に従う。詳細: `docs/gui-testing-layers.md`（`docs/workflow.md` の計画・実装フローで必須化）。計画時は `/gui-test-plan`（②実質的な受け入れ要件の設計）、merge 前は `/gui-verify`（①realgui 証拠ゲート）を使う。

  ## 開発環境の落とし穴

  詳細: `docs/development.md` 末尾参照。

  ## ファイル更新ルール

  - **コメント**: 何 (WHAT) ではなく なぜ (WHY) を書く。自明なコードに説明を付けない
  - **計画ドキュメント**: 設計は `docs/superpowers/specs/`、実装プランは `docs/superpowers/plans/`。仕様変更時はプランのチェックボックス／設計 spec を更新し、要件がずれるなら設計 spec 更新をユーザーに確認する。旧 `.kiro/specs/` はアーカイブで編集しない
  - **本ファイル (CLAUDE.md) の熟成**: タスク完了ごとに「CLAUDE.md / docs/ に追記すべき知見はあるか」をユーザーに確認する。本ファイル肥大化を検知したら積極的に `docs/` に分離 — トレーサビリティ (ポインタ・関連リンク) を必ず確保する
  ````

- [ ] **Step 2: 検証（superpowers-first 化と Kiro 残存）**
  Run: `grep -c "docs/superpowers/specs/\|superpowers 駆動\|docs/workflow.md\|アーカイブ" CLAUDE.md; grep -c "Kiro + Claude Code\|dual-agent\|steering" CLAUDE.md`
  Expected: 1 行目 ≥4、2 行目 `0`（旧ワークフロー語の残存ゼロ）。

- [ ] **Step 3: Commit**
  ```bash
  git add CLAUDE.md
  git commit -m "docs(claude): CLAUDE.md を superpowers-first に全面書換（脱 Kiro）"
  ```

---

## Wave 3: ポインタ張替・旧ファイル廃止

### Task 7: `docs/roadmap.md` のポインタ更新と注記是正

**Files:** Modify `docs/roadmap.md`

**Interfaces:**
- Consumes: なし
- Produces: 旧パス参照の解消、sub-spec 注記の実態整合

- [ ] **Step 1: 関連ポインタを更新**
  `docs/roadmap.md:5-8` を次に置換:
  ```markdown
  関連:
  - `.kiro/specs/` — 完了済み Phase 1/2 spec のアーカイブ（requirements / design / tasks）
  - `docs/superpowers/{specs,plans}/` — 新規計画の一次情報源
  - `CLAUDE.md` — Phase 状況テーブル（進捗管理）
  - `docs/product.md` — プロダクト概要・原則
  ```

- [ ] **Step 2: sub-spec 注記を実態へ是正**
  `docs/roadmap.md:71`（`…6 つの sub-spec に分解する…`）の文に、file-browser が分解後に追加された旨を補記。当該文末に追記:
  ```markdown
  （その後 `valisync-gui-file-browser` を mvp から分離して追加。`analysis`/`derived`/`views`/`script` は未着手。各 sub-spec 表の「状態」列は着手当時のもので、最新の完了状況は CLAUDE.md Phase 表を一次とする。）
  ```

- [ ] **Step 3: 検証**
  Run: `grep -c "docs/superpowers\|file-browser を mvp から分離\|CLAUDE.md Phase 表を一次" docs/roadmap.md; grep -c "steering/product.md" docs/roadmap.md`
  Expected: 1 行目 ≥2、2 行目 `0`。

- [ ] **Step 4: Commit**
  ```bash
  git add docs/roadmap.md
  git commit -m "docs: roadmap のポインタ更新と sub-spec 注記是正"
  ```

### Task 8: 旧ファイル廃止・steering 撤去・アーカイブ明記

**Files:** Delete `docs/dual-agent-workflow.md`, `.kiro/steering/`（5ファイル）; Create `.kiro/ARCHIVE.md`

**Interfaces:**
- Consumes: W1/W2 で全参照が新パスへ張替済みであること
- Produces: Kiro 専用 doc の消滅、`.kiro/` のアーカイブ化

- [ ] **Step 1: 残存参照がないことを確認（削除前ガード）**
  Run: `grep -rln "dual-agent-workflow" docs/ CLAUDE.md .kiro/ 2>/dev/null; echo "---"; grep -rln "\.kiro/steering" docs/ CLAUDE.md 2>/dev/null`
  Expected: 両方とも出力なし（参照ゼロ）。**出力があれば該当ファイルを先に張替えてから次へ進む。**

- [ ] **Step 2: 旧ファイルを削除**
  ```bash
  git rm docs/dual-agent-workflow.md
  git rm .kiro/steering/product.md .kiro/steering/tech.md .kiro/steering/structure.md .kiro/steering/spec-authoring.md .kiro/steering/workflow.md
  ```

- [ ] **Step 3: `.kiro/ARCHIVE.md` を作成**
  ```markdown
  # .kiro/ — アーカイブ

  `.kiro/specs/` は **完了済み Phase 1/2** の要件・設計・タスク（requirements / design / tasks）の**アーカイブ**。歴史・トレーサビリティ（特に `docs/development.md` の PBT/MVVM 一次情報源が `design.md` の Correctness Properties を指す）のため凍結保持する。

  - **新規の計画は `docs/superpowers/specs/`（設計）・`docs/superpowers/plans/`（実装プラン）** で行う（superpowers 駆動）。
  - 旧 `.kiro/steering/` のルールは `docs/`（product / development / structure / policies / workflow）へ移設済み。
  - 本ディレクトリの内容は編集しない（アーカイブ）。
  ```

- [ ] **Step 4: 検証**
  Run: `test ! -e docs/dual-agent-workflow.md && test ! -e .kiro/steering && test -f .kiro/ARCHIVE.md && echo OK; ls .kiro/`
  Expected: `OK`、`ls .kiro/` は `ARCHIVE.md` と `specs` のみ。

- [ ] **Step 5: Commit**
  ```bash
  git add -A .kiro/ docs/
  git commit -m "docs: dual-agent-workflow.md と .kiro/steering を撤去、.kiro をアーカイブ化"
  ```

---

## Wave 4: 検証

### Task 9: リンク整合監査・dangling 参照ゼロ・コード非変更

**Files:** 変更なし（検証のみ）

- [ ] **Step 1: CLAUDE.md チェーンの全ポインタ存在確認**
  Run:
  ```bash
  for p in docs/product.md docs/development.md docs/structure.md docs/policies.md docs/workflow.md docs/gui-testing-layers.md docs/roadmap.md .kiro/specs/valisync-core .kiro/specs/valisync-gui-mvp .kiro/specs/valisync-gui-file-browser .kiro/specs/valisync-gui-axes .kiro/ARCHIVE.md docs/superpowers/specs docs/superpowers/plans; do test -e "$p" && echo "OK $p" || echo "MISSING $p"; done
  ```
  Expected: 全て `OK`。

- [ ] **Step 2: 旧パスへの dangling 参照ゼロ**
  Run: `grep -rln "dual-agent-workflow\|\.kiro/steering\|steering/" docs/ CLAUDE.md 2>/dev/null; echo "exit gate"`
  Expected: 出力なし（`exit gate` のみ）。

- [ ] **Step 3: 旧 Kiro 駆動表現が CLAUDE.md/docs に残っていない**
  Run: `grep -rln "tasks.md に従って\|tasks.md を消化\|Kiro Spec で" CLAUDE.md docs/*.md 2>/dev/null; echo "exit gate"`
  Expected: 出力なし（`exit gate` のみ）。

- [ ] **Step 4: コード非変更の証拠**
  Run: `git diff --name-only main...HEAD -- '*.py'; echo "exit gate"`
  Expected: 出力なし（`exit gate` のみ）。

- [ ] **Step 5: memory 整合の確認（参考・リポジトリ外）**
  `feedback_structural_change_approval`（structure.md 由来）が指す情報は `docs/structure.md`「Structural Change Policy」に存在。`gui_subspec_decomposition` が指す分解情報は `docs/roadmap.md` に存在。必要なら memory のポインタを更新（別作業・リポジトリ外）。

- [ ] **Step 6: 監査結果を1コミットにまとめる（任意）**
  検証で軽微な是正が出た場合のみ:
  ```bash
  git add -A && git commit -m "docs: 移行後リンク整合の最終是正"
  ```

---

## Self-Review

**1. Spec coverage**（設計 spec 各節 → タスク）:
- §4 廃止（dual-agent-workflow.md / spec-authoring.md）→ Task 8。✓
- §4 統合（tech→development / product 原則→policies / Coding Standards→development）→ Task 1, 2。✓
- §4 独立移設（structure→docs/structure / workflow→docs/workflow）→ Task 4, 5。✓
- §4 新規（docs/workflow.md superpowers 節 / .kiro/ARCHIVE.md）→ Task 5, 8。✓
- §4 product 分割（概要→product.md / 原則・言語→policies / Phases→roadmap・CLAUDE）→ Task 3, 2, 6/7。✓
- §4 アーカイブ保持（.kiro/specs）/ 撤去（.kiro/steering）→ Task 8（specs 不変・steering 削除）。✓
- §5 CLAUDE.md 全面書換（優先順位表/ワークフロー/ブランチ/Phase 表/tasks.md→plans/更新ルール）→ Task 6。✓
- §6 ポインタ張替（roadmap/policies/development）→ Task 1, 2, 7。✓
- §6 既存不整合是正（英語日本語＝Task 2＋8 / 6-subspec＝Task 6, 7）。✓
- §7 検証（リンク整合・dangling ゼロ・コード非変更・memory）→ Task 9。✓

**2. Placeholder scan:** 「TBD/TODO/後で」なし。新規 doc の全文と各編集の具体内容・検証コマンド・期待値を記載。移設タスク（structure/workflow）は「全内容コピー＋具体編集」で内容を再転記しない（転記ミス回避）。✓

**3. 名称整合:**
- 新プロセス doc は全タスクで `docs/workflow.md` に統一（Global Constraints で設計の `development-workflow.md` からのリファインを明記）。✓
- CLAUDE.md 優先順位表②の docs リスト（product/development/structure/policies/workflow/gui-testing-layers）は Task 1–5 の成果物と一致。✓
- 削除対象（dual-agent-workflow.md, steering 5ファイル）は Task 8 の `git rm` 対象と一致。Task 8 Step 1 の削除前ガードで参照ゼロを保証。✓

---

## 依存グラフ

```json
{
  "tasks": [
    {"id":"1","desc":"development.md に tech 統合","deps":[]},
    {"id":"2","desc":"policies.md に原則・言語","deps":[]},
    {"id":"3","desc":"product.md 新設","deps":[]},
    {"id":"4","desc":"structure.md 移設","deps":[]},
    {"id":"5","desc":"workflow.md 新設","deps":[]},
    {"id":"6","desc":"CLAUDE.md 全面書換","deps":["1","2","3","4","5"]},
    {"id":"7","desc":"roadmap ポインタ・注記","deps":[]},
    {"id":"8","desc":"旧廃止・steering 撤去・ARCHIVE","deps":["1","2","4","5","6","7"]},
    {"id":"9","desc":"リンク整合検証","deps":["6","7","8"]}
  ]
}
```
