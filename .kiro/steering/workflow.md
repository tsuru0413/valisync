# 開発ワークフロー — ブランチ運用と PR フロー

> 本ファイルは **常時適用ルール**。Claude Code / Kiro が新規実装に着手するとき、まず本ファイルに従ってブランチを切ること。

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
- spec 単位で実装する場合は spec 名と一致させる: `feature/<spec-name>`

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
[gh pr merge --auto] (CI 通過後に自動 squash merge)
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

- 本ファイル (workflow.md) のルールを Claude Code / Kiro / 開発者本人が遵守する
- 技術強制が必要になった場合は GitHub Organization + Team プラン ($4/user/月) への移行を検討
- CI (`.github/workflows/ci.yml`) は Free repo でも動作するため、push 後の品質検出は確実に機能する

### Claude Code / Kiro の振る舞い

- 新規 spec の実装に着手する際、最初に `git checkout -b feature/<spec-name>` する
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

### Auto-merge (推奨)

```powershell
gh pr merge <num> --squash --delete-branch --auto
```

- `--squash`: squash merge で履歴を 1 commit に集約
- `--delete-branch`: マージ後に remote の feature ブランチを自動削除
- `--auto`: CI 通過まで待ってから自動マージ (CI 失敗時は手動介入が必要)

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
- ただし、**実装直後に CLAUDE.md / steering 更新するケース** (タスク完了の整理として) は実装と同じブランチ・PR にまとめてよい

## 7. GUI 実装時のテストレイヤー（必須）

GUI（PySide6 / pyqtgraph）の機能・ユーザー操作を実装/変更するときは、**テストレイヤー方針に従うことを必須**とする。詳細・必須早見表: `docs/gui-testing-layers.md`。

- **Layer A（ヘッドレス状態検証）**: 常に必須（CI）。
- **Layer B（ヘッドレス実イベント経路検証 / `sendEvent`）**: **入力イベント（右クリック・D&D・キー・ドロップ等）に関わる変更では必須**（CI）。シグナルを直接 `emit` して済ませない（経路破壊を見逃すため）。
- **Layer C（実 OS 入力 / `--realgui`）**: イベント経路を新規実装/変更したときはローカルで実機確認（`uv run pytest --realgui tests/realgui/`）。CI 除外。

> 背景: PR #11 で「テストは緑だが実 GUI で右クリックメニューが出ない」false green が発生したため、入力系は実経路（Layer B）を必ず通す運用とした。

## 8. 関連ドキュメント

- `docs/development.md` — ローカル開発コマンド・品質ゲート詳細
- `docs/gui-testing-layers.md` — GUI テストレイヤー（必須運用）
- `docs/dual-agent-workflow.md` — Kiro + Claude Code 併用フロー
- `.kiro/steering/spec-authoring.md` — spec 生成ルール (Wave 設計 / follow-up memo 運用)
