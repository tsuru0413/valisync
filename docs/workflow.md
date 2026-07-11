# 開発ワークフロー — ブランチ運用と PR フロー

> 本ファイルは **常時適用ルール**。新規実装に着手するとき、まず本ファイルに従う。

## 0. 計画・実装フロー（superpowers 駆動）

本プロジェクトは superpowers スキルで計画→実装する（旧来の spec 駆動運用は廃止）。

1. **brainstorming** — 要件・設計を対話で詰め、設計 spec を `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` に書く。
2. **writing-plans** — 設計を bite-sized タスクの実装プラン `docs/superpowers/plans/YYYY-MM-DD-<topic>.md` に落とす。
3. **executing-plans / subagent-driven-development** — プランをタスク順に消化（各タスクで品質ゲート → commit）。
4. **finishing-a-development-branch** — テスト確認 → merge / PR。

- 完了済み Phase 1/2 の計画は `.kiro/specs/`（アーカイブ・歴史）。新規には使わない。
- GUI 入力経路の実装では `/gui-test-plan`・`/gui-verify` スキル（`.claude/skills/gui-{test-plan,verify}/`）のテストレイヤー方針に従い、計画時に `/gui-test-plan`、merge 前に `/gui-verify` を使う。

## 1. ブランチモデル

| ブランチ | 目的 |
|---|---|
| `main` | **本番ブランチ** (もしくはデフォルトブランチ) |
| `feature/<name>` | 新機能実装 (例: `feature/user-authentication`) |
| `bugfix/<name>` | バグ修正 |
| `docs/<name>` | ドキュメント・spec のみの更新 |
| `hotfix/<name>` | 緊急修正 (main 直 push 回避のため) |

### 命名規則

- ブランチ名は **小文字 + ハイフン区切り**
- 作業単位を表す簡潔な名前にする: `feature/<topic>`

## 2. 標準フロー

```
[main から分岐] git checkout -b feature/<name>
   ↓
[ローカル実装 + 動作確認]
   ↓
[品質ゲート通過]
   - uv run pytest / ruff check / ruff format --check / mypy
   ↓
[git push origin feature/<name>]
   ↓
[gh pr create] (or GitHub Web UI)
   ↓
[CI (GitHub Actions) が品質ゲートを再実行]
   ↓
[gh pr checks <num> --watch で CI 緑を確認 → gh pr merge <num> --squash]
   ↓
[merge 後の cleanup]
   - git checkout main
   - git pull --ff-only origin main
   - git fetch --prune origin (stale ref 掃除)
```

## 3. main 直接編集の禁止 (Self-Discipline 運用)

- main への直接 commit / push は **緊急 hotfix を除き禁止**
- 通常変更は必ず feature ブランチを経由
- 緊急 hotfix の場合も、可能なら `hotfix/<name>` ブランチで PR を経由

### 重要: GitHub Free + Private では branch protection が効かない

GitHub の方針変更により、**Free 個人アカウント + Private リポジトリでは Branch protection rules / Repository rulesets が enforced にならない** ("Your protected branch rules ... won't be enforced..." のメッセージが UI に表示される)。

そのため本テンプレートを使うプロジェクトは **self-discipline 運用** とする:

- 本ファイル (workflow.md) のルールを Claude Code / 開発者本人が遵守する
- 技術強制が必要になった場合は GitHub Organization + Team プラン ($4/user/月) への移行を検討
- CI (`.github/workflows/ci.yml`) は Free repo でも動作するため、push 後の品質検出は確実に機能する

### 着手時の振る舞い

- 新規作業は brainstorming → writing-plans の後、`git checkout -b feature/<topic>` する
- main で作業を始めてしまった場合は、変更を stash → 新ブランチに移す
- ユーザーが明示的に「main で作業」と指示しない限り、feature ブランチを使う
- `git push origin main` は実行しない (PR 経由でマージ)

### ローカル補助: pre-push hook (任意)

main への誤 push を防ぐローカル hook を入れることができる。`.git/hooks/pre-push` (実行権限要):

```sh
#!/bin/sh
# main への直接 push に確認プロンプトを出す
protected_branch='main'
current_branch=$(git symbolic-ref HEAD | sed -e 's,.*/\(.*\),\1,')
if [ "$current_branch" = "$protected_branch" ]; then
    read -p "main へ直接 push しようとしています。続行しますか? [y/N]: " confirm
    [ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || exit 1
fi
exit 0
```

```bash
chmod +x .git/hooks/pre-push
```

注意: `.git/hooks/` はリポジトリに含まれない (各環境で手動セットアップ)。複数環境を使う場合は `husky` や `pre-commit` 等で管理する選択肢もある。

## 4. PR 作成 / マージのフロー (GitHub CLI)

GitHub CLI (`gh`) を使うと、PR 作成からマージまでをコマンドで完結できる。Web UI を開く必要がない。

### 初回セットアップ

```powershell
# Windows
winget install --id GitHub.cli
gh auth login    # Web ブラウザで認証
```

```bash
# macOS
brew install gh
gh auth login

# Linux (apt)
sudo apt install gh
gh auth login
```

### PR 作成

```powershell
gh pr create --base main --head feature/<name> --title "<タイトル>" --body @'
## Summary
- ...

## Test plan
- [x] uv run pytest
- [x] (該当する手動確認手順)
'@
```

### Merge (CI 緑を確認して squash)

```powershell
gh pr checks <num> --watch --fail-fast    # CI 完了まで待機 (失敗は即中断)
gh pr merge <num> --squash --delete-branch
```

- `--squash`: squash merge で履歴を 1 commit に集約
- `--delete-branch`: マージ後に remote の feature ブランチを自動削除
- **`--auto` は使えない**: リポジトリ設定で auto-merge が無効のため `gh pr merge --auto` は `GraphQL: Auto merge is not allowed for this repository` で失敗する (2026-07-11・PR #80 で確認)。設定 (Settings > General > Allow auto-merge) を有効化した場合のみ `--auto` 併用に戻してよい

### マージ後の cleanup

```powershell
git checkout main
git pull --ff-only origin main
git fetch --prune origin    # stale な remote tracking ref を掃除
```

## 5. CI (GitHub Actions) の役割

`.github/workflows/ci.yml` で品質ゲートを自動実行:

- **push to main**: 品質ゲート再確認 (merge 後の最終確認)
- **PR (feature → main)**: 品質ゲート確認 (merge 前のゲート)

詳細: `docs/development.md`

## 6. spec / docs 更新の特例

ドキュメント・spec のみの更新でも、原則 `feature/<name>` または `docs/<name>` ブランチ + PR を経由する。

- 緊急性が低い → PR で履歴管理した方が後から経緯を追いやすい
- ただし、**実装直後に CLAUDE.md / docs 更新するケース** (タスク完了の整理として) は実装と同じブランチ・PR にまとめてよい

## 7. GUI 実装時のテストレイヤー（必須）

GUI（PySide6 / pyqtgraph）の機能・ユーザー操作を実装/変更するときは、**テストレイヤー方針に従うことを必須**とする。詳細・必須早見表（E2E スペクトル・レイヤー A/B/C 定義・①/②）: `/gui-test-plan`（`.claude/skills/gui-test-plan/reference/e2e-model.md`）・`/gui-verify`（`.claude/skills/gui-verify/reference/gate-and-pitfalls.md`）。

- **Layer A（ヘッドレス状態検証）**: 常に必須（CI）。
- **Layer B（ヘッドレス実イベント経路検証 / `sendEvent`）**: **入力イベント（右クリック・D&D・キー・ドロップ等）に関わる変更では必須**（CI）。シグナルを直接 `emit` して済ませない（経路破壊を見逃すため）。
- **Layer C（実 OS 入力 / `--realgui`）**: イベント経路を新規実装/変更したときはローカルで実機確認（`uv run pytest --realgui tests/realgui/`）。CI 除外。
- **realgui 証拠ゲート（①）**: GUI 入力経路の変更は、該当 realgui の実行証拠（視覚項目は `/verify` 観測）を **merge 前に要求**。非 Windows 等で実行不可なら「ゲート未充足」扱い（`skipped` を検証済みと誤認しない）。実行は `/gui-verify`。詳細: `.claude/skills/gui-verify/reference/gate-and-pitfalls.md`。
- **realgui 実質性（②）**: realgui のアサートは実経路でしか証明できない結果を検証する（VM 再チェック・スクショ保存だけは不可）。計画時の受け入れ要件設計は `/gui-test-plan`。

> 背景: PR #11 で「テストは緑だが実 GUI で右クリックメニューが出ない」false green が発生したため、入力系は実経路（Layer B）を必ず通す運用とした。

## 8. 関連ドキュメント

- `docs/development.md` — ローカル開発コマンド・品質ゲート詳細
- `/gui-test-plan`・`/gui-verify` スキル（`.claude/skills/gui-{test-plan,verify}/`）— GUI テストレイヤー（必須運用・自己完結。E2E スペクトル・レイヤー定義・①/②）
- `docs/policies.md` — プロジェクト方針・Architecture 原則・言語標準
- `CLAUDE.md` — エントリポイント（情報の探し方）
