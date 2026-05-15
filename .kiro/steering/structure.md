# Project Structure

<!-- TODO: プロジェクト固有のディレクトリ構造に書き換える -->

```
project-root/
├── src/                    # メインパッケージ (または プロジェクト名/)
│   ├── models/             # データモデル
│   ├── services/           # ビジネスロジック
│   └── cli.py              # CLI エントリポイント
├── tests/                  # テスト
│   ├── conftest.py         # 共有 fixtures
│   ├── test_pbt_*.py       # プロパティベーステスト (Hypothesis)
│   └── test_*.py           # ユニットテスト
├── docs/                   # 運用ドキュメント
├── .kiro/
│   ├── steering/           # プロジェクトルール (Kiro 自動読込)
│   └── specs/              # 機能ごとの要件・設計・タスク
├── .github/workflows/      # CI
├── pyproject.toml          # プロジェクト設定 & 依存
└── uv.lock                 # ロックファイル
```

## Naming Conventions

- Test files: `test_<module>.py` for unit tests, `test_pbt_<topic>.py` for property-based tests
- Models: one file per domain concept
- <!-- TODO: プロジェクト固有の命名規則 -->

## Module Boundaries

<!-- TODO: モジュール間の依存ルールを定義 -->
<!-- 例:
- `models/` — pure data definitions, no I/O
- `services/` — pure computation, no I/O
- `cli.py` — thin entry point, I/O layer
-->
