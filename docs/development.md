# Development Workflow

開発時のコマンド・品質ゲート・依存管理の運用ノート。

関連:
- `../CLAUDE.md` — エントリポイント
- `../.kiro/steering/tech.md` — 技術選定の一次情報源
- `dual-agent-workflow.md` — Kiro + Claude Code 併用開発ガイド
- `policies.md` — プロジェクト方針

---

## 品質ゲート

コミット前にこの順で全てを通す。1つでも失敗したら commit しない。

```bash
uv run pytest                # 1. 全テスト pass
uv run ruff check            # 2. lint 違反ゼロ
uv run ruff format --check   # 3. format 差分ゼロ
uv run mypy src/             # 4. 型エラーゼロ
```

## テスト

```bash
uv run pytest                          # 全テスト
uv run pytest -m property              # プロパティテストのみ
uv run pytest --cov                    # カバレッジ付き
uv run pytest -k "test_name"           # 名前一致で絞り込み
```

レイアウト:
- `tests/` — テストディレクトリ
- `--import-mode=importlib` (`pyproject.toml` 設定) により `__init__.py` 不要

新規モジュールを実装したら必ず対応する pytest テストを追加すること。

## Lint / Format (Ruff)

`pyproject.toml` の `[tool.ruff]` で集中管理。

```bash
uv run ruff check              # 違反検出のみ
uv run ruff check --fix        # 自動修正
uv run ruff format             # フォーマッタ適用
```

推奨ルールセット: `E, W, F, I, B, UP, SIM, RUF`

<!-- TODO: プロジェクト固有の ignore ルールを記載 -->

## 型チェック (Mypy)

```bash
uv run mypy src/               # 標準実行
```

推奨 strictness (`pyproject.toml` の `[tool.mypy]`):
- `disallow_incomplete_defs = true`
- `check_untyped_defs = true`
- `no_implicit_optional = true`
- `warn_unused_ignores = true`

## 依存管理

```bash
uv sync --extra dev            # dev 依存をインストール (初回 / 依存変更後)
uv add --dev <package>         # 新規 dev 依存追加
uv lock --upgrade              # ロックファイル更新
```

## CI (GitHub Actions)

`.github/workflows/ci.yml` — push to `main` と全 PR で品質ゲートを自動実行。

設定の要点:
- **ランナー**: `ubuntu-latest`
- **Python matrix**: requires-python の下限と最新の両端
- **uv キャッシュ**: `astral-sh/setup-uv@v3` の `enable-cache: true`
- **同時実行制御**: `concurrency` + `cancel-in-progress: true`

## 開発環境の落とし穴

<!-- TODO: 環境固有の問題を記載 -->
<!-- 例:
- Windows: `python` コマンドは Microsoft Store スタブ → `uv run python` を使う
- PowerShell: 出力が cp932 → PYTHONIOENCODING=utf-8 を設定
-->
