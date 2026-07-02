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
- CLAUDE.md はエントリポイント (薄く保つ)。詳細は `docs/` に分散、完了済み spec は `.kiro/specs/`（アーカイブ）。

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
| Phase 2 / valisync-gui-axes | 複数Y軸レイアウト: リージョンベースのオーバーレイ・Auto-Fit 縮尺・複数列グリッド配置 | R1–R6 完了（PR #4/#13/#14/#16/#17 merged）— 詳細は [docs/multi-axis-multicolumn-followup.md](docs/multi-axis-multicolumn-followup.md)・[docs/multi-axis-empty-region-followup.md](docs/multi-axis-empty-region-followup.md)、設計/プランは `docs/superpowers/specs/`・`docs/superpowers/plans/`。軸ごとリサイズ＋アクティブ軸統一操作モデル（グリップ=リサイズ/フレーム=移動/内側=ズーム/外側=パンをアクティブ軸のみ受付、連動ディバイダー廃止）を PR #19 で実装（realgui 9本、実装メモは設計 doc §14）— [docs/superpowers/specs/2026-06-28-y-axis-per-axis-resize-active-model-design.md](docs/superpowers/specs/2026-06-28-y-axis-per-axis-resize-active-model-design.md) | `.kiro/specs/valisync-gui-axes/`（archive）＋ `docs/superpowers/` |
| Phase 2 / valisync-gui-analysis | カーソル計測・範囲統計・時間オフセット（親 R14–R17）。R15 Global Cursor: プロット内クリックで全パネル同期カーソル設置・補間値読み取り・補間方式切替・線ドラッグ移動、補間値フロート表（`CursorReadout`）で既存凡例を置換 | **R14–R17 完了（全 PR merged・realgui ①ゲート充足）**。増分A=R15 Global Cursor（PR #21/#22、realgui 2/2＋軸操作 8/8 無回帰）／増分B=R16 Delta+R17 範囲統計（PR #23、realgui カーソル A/B 線ドラッグ pass）／増分C=R14 時間オフセット（PR #25）— realgui ①ゲートで実経路バグ2件（grabMouse 未使用で押下中 move 不達／`_finish_offset` の reset 順序）を検出し TDD 修正、headless 612・realgui 6/6（memory: `gui_realgui_move_not_reaching_parent_qwidget`） | 設計: [design](docs/superpowers/specs/2026-06-29-gui-analysis-cursor-offset-design.md)・プラン: [r15-plan](docs/superpowers/plans/2026-06-29-gui-analysis-r15-global-cursor.md)・[r14-plan](docs/superpowers/plans/2026-06-29-gui-analysis-r14-time-offset.md)・[r16-r17-plan](docs/superpowers/plans/2026-06-29-gui-analysis-r16-r17-delta-stats.md) |

| 横断 / realgui カバレッジ拡充 | headless が構造的に false-green を出す経路を実 OS 入力（Layer C）で検証。監査で realgui 必須 39・covered 16・missing 23 を特定し high クラスタから充足 | **Phase 1-7 実装完了（low クラスタ＋C3 昇格で全 missing 解消・merge 前 ①ゲートで実機実証）**。P1 共有ヘルパ `_realgui_input`/`drive_qdrag`（PR #27）／P2 コンテナメニュー3経路 H5-H7（ChannelBrowser/DataExplorer CustomContextMenu 化＋GraphPanel setMenuEnabled、PR #28）／P3 信号 D&D 実配送 H1-H4（クロスウィジェット QDrag、PR #29）／P4 click_to_activate_axis H8（純クリック活性化、PR #30）。付随: id() フレーク修正 #31（memory `gui_id_reuse_flake_object_recreation`）。P7 low: DataExplorer ドロップ・ドロップ青枠・非アクティブ軸 hover・grip 記録・C3 昇格（Plan 7 実装）。**残存（別計画）**: P5 クロスパネル軸移動（新機能）・C1 dock 復元（Layer A） | 監査 [docs/realgui-coverage-audit.md](docs/realgui-coverage-audit.md)・設計 [spec](docs/superpowers/specs/2026-06-30-realgui-coverage-expansion-design.md)・プラン `docs/superpowers/plans/2026-06-30-realgui-plan{1-4}-*.md` |

> Phase 2 `valisync-gui` は sub-spec に分解済み（mvp / file-browser / axes / **analysis（R14–R17 完了・realgui ①ゲート充足）** 完了、未着手: derived / views / script）。realgui カバレッジ拡充（横断）は Phase 1-7 実装完了（low クラスタ＋C3 昇格で全 missing 解消・merge 前 ①ゲートで実機実証）。詳細は `docs/roadmap.md`。
>
> **改善サブスペック（バケット② 実装済みだが不足）**: 実ユーザージャーニー監査（開く→表示→解析）で確定した 64 課題を、`gui-feedback-errors` / `gui-shell-controls` / `gui-plot-analysis-controls` / `core-loaders-hardening` / `analysis-correctness` / `rendering-correctness-perf` の6サブスペックに割当。一次情報源は [docs/audit-findings-catalog.md](docs/audit-findings-catalog.md)（ID 付き・file:line・優先度）、俯瞰は `docs/roadmap.md`。着手起点の `gui-feedback-errors` は**第1弾（FB-01/02/03/06＝診断伝播＋Diagnostics ドック/モーダル/ステータスバー）を PR #37 で実装済み**（spec/プランは `docs/superpowers/`、残り FB-04/05/07-10 は第2弾）。

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
