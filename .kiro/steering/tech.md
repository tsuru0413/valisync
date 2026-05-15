# Tech Stack

## Language & Runtime

- Python 3.12+ (requires-python >= 3.12)
- <!-- TODO: runtime 依存の方針 (例: 標準ライブラリのみ / 最小限の外部依存) -->

## Build & Package Management

- **uv** — dependency manager (pyproject.toml + uv.lock)
- **setuptools** — build backend
- Package is installable via `pip install -e .`

## Testing

- **pytest** >= 8.0 — test runner
- **Hypothesis** >= 6.100 — property-based testing
- **pytest-cov** >= 5.0 — coverage reporting

## Lint & Format

- **ruff** — linter + formatter (replaces flake8, isort, black)
- **mypy** — static type checker

## Common Commands

```bash
# 依存インストール
uv sync --extra dev

# テスト
uv run pytest
uv run pytest --cov
uv run pytest -m property

# Lint & Format
uv run ruff check
uv run ruff check --fix
uv run ruff format

# 型チェック
uv run mypy src/

# 全品質ゲート (コミット前に必ず実行)
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
```

## Configuration

- pytest config in `pyproject.toml` under `[tool.pytest.ini_options]`
- ruff config in `pyproject.toml` under `[tool.ruff]`
- mypy config in `pyproject.toml` under `[tool.mypy]`
- Coverage target: 80% minimum (`fail_under = 80`)

## Key Conventions

- <!-- TODO: プロジェクト固有の慣習 -->
- CLI entry point: <!-- TODO: エントリポイント -->
- Data files stored in `data/` directory as JSON
