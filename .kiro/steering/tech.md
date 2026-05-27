# Tech Stack

## Language & Runtime

- Python 3.12+ (requires-python >= 3.12)
- 最小限の外部依存（コアロジックは標準ライブラリ + numpy のみ）
- GUI 層は PyQt6/PySide6 + PyQtGraph（別 spec で管理）

## Build & Package Management

- **uv** — dependency manager (pyproject.toml + uv.lock)
- **setuptools** — build backend
- Package is installable via `pip install -e .`

## Core Dependencies

- **numpy** — 高速な時系列データ操作（Signal のタイムスタンプ・値配列）

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

- Signal データは frozen dataclass + numpy array で表現
- 全ての変換処理は新しいオブジェクトを返す（元データ不変）
- Protocol でインターフェースを定義し、具象クラスで実装
- Format_Definition の永続化は JSON ファイル（`data/` ディレクトリ）
- GUI entry point: `src/valisync/gui/app.py`（Phase 2 で実装）
