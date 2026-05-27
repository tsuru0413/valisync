# Project Structure

```
valisync/
├── src/
│   └── valisync/
│       ├── __init__.py
│       ├── core/                          # Phase 1: GUI-free data processing library
│       │   ├── __init__.py                # re-exports Session, Signal, etc.
│       │   ├── models/
│       │   │   ├── __init__.py
│       │   │   ├── signal.py              # Signal, Derived_Signal
│       │   │   ├── signal_group.py        # SignalGroup
│       │   │   ├── format_def.py          # FormatDefinition, Delimiter
│       │   │   └── load_result.py         # LoadResult, Diagnostic
│       │   ├── loaders/
│       │   │   ├── __init__.py
│       │   │   ├── base.py                # SignalLoader Protocol
│       │   │   ├── mdf4_loader.py         # MDF4 unified (CAN/XCP/Ethernet)
│       │   │   ├── csv_loader.py          # CSV (FormatDefinition-based)
│       │   │   └── format_def_manager.py  # FormatDefinition CRUD + JSON persistence
│       │   ├── sync/
│       │   │   ├── __init__.py
│       │   │   └── synchronizer.py        # TimeSynchronizer
│       │   ├── formula/
│       │   │   ├── __init__.py
│       │   │   ├── engine.py              # FormulaEngine (parser + evaluator)
│       │   │   └── library.py             # FormulaLibraryManager (Phase 3: CRUD + JSON)
│       │   ├── interpolation/
│       │   │   ├── __init__.py
│       │   │   └── interpolator.py        # Interpolator, InterpolationMethod
│       │   ├── statistics/
│       │   │   ├── __init__.py
│       │   │   └── range_stats.py         # RangeStatistics, StatisticsResult
│       │   ├── downsampler/
│       │   │   ├── __init__.py
│       │   │   └── downsampler.py         # Downsampler (min-max algorithm)
│       │   ├── export/
│       │   │   ├── __init__.py
│       │   │   └── csv_exporter.py        # CsvExporter (atomic write)
│       │   └── session.py                 # Session (orchestration layer)
│       └── gui/                           # Phase 2+: PyQt6 desktop app
│           ├── __init__.py
│           ├── views/                     # Qt widgets (View layer)
│           ├── viewmodels/                # MVVM ViewModel layer
│           ├── persistence/               # Phase 3: .vsproj save/restore
│           ├── theme/                     # Phase 3: light/dark mode
│           ├── i18n/                      # Phase 4: Qt translation
│           └── app.py                     # QApplication entry point
├── tests/
│   ├── conftest.py                        # shared fixtures & Hypothesis strategies
│   ├── test_pbt_signal.py                 # Signal モデル不変条件 (PBT)
│   ├── test_pbt_sync.py                   # 時刻同期 (PBT)
│   ├── test_pbt_formula.py                # Formula エンジン (PBT)
│   ├── test_pbt_csv.py                    # CSV/FormatDefinition ラウンドトリップ (PBT)
│   ├── test_pbt_mdf4.py                   # MDF4 Signal ラウンドトリップ (PBT)
│   ├── test_pbt_interpolation.py          # 補間計算 (PBT)
│   ├── test_pbt_statistics.py             # 範囲統計 (PBT)
│   ├── test_pbt_downsampler.py            # ダウンサンプリング (PBT)
│   ├── test_pbt_calcbar.py                # Calcbar 演算 (PBT)
│   ├── test_loaders.py                    # ローダー unit tests
│   ├── test_export.py                     # エクスポート unit tests
│   ├── test_session.py                    # Session unit tests
│   ├── test_format_def.py                 # FormatDefinition CRUD unit tests
│   ├── test_interpolation.py              # 補間 edge cases unit tests
│   ├── test_statistics.py                 # 統計 edge cases unit tests
│   ├── test_downsampler.py                # ダウンサンプラー unit tests
│   └── test_calcbar.py                    # Calcbar unit tests
├── data/
│   ├── formats/                           # FormatDefinition JSON files (runtime)
│   └── formulas/                          # FormulaDefinition JSON files (Phase 3)
├── docs/
├── .kiro/
│   ├── steering/                          # project-wide rules
│   └── specs/                             # per-feature requirements/design/tasks
├── .github/workflows/
├── pyproject.toml
└── uv.lock
```

## Naming Conventions

- Test files: `test_<module>.py` for unit tests, `test_pbt_<topic>.py` for property-based tests
- Models: one file per domain concept (`signal.py`, `signal_group.py`, `format_def.py`)
- Loaders: one file per format (`mdf4_loader.py`, `csv_loader.py`)
- Protocol interfaces: defined in `base.py` within each module directory

## Module Boundaries

| Module | Role | I/O |
|--------|------|-----|
| `core/models/` | Pure data definitions (frozen dataclass) | None |
| `core/loaders/` | File I/O — reads files, produces immutable models | Read |
| `core/sync/` | Pure computation — timestamp transformation | None |
| `core/formula/` | Pure computation — expression evaluation; `library.py` handles JSON I/O (Phase 3) | None / Write |
| `core/interpolation/` | Pure computation — value interpolation at arbitrary time | None |
| `core/statistics/` | Pure computation — range statistics | None |
| `core/downsampler/` | Pure computation — min-max downsampling | None |
| `core/export/` | File I/O — writes CSV, never modifies input files | Write |
| `core/session.py` | Orchestration — coordinates all core modules | Via modules |
| `gui/` | PyQt6 UI layer — imports from `core/` only, never the reverse | Qt |

## Dependency Rules

```
core/models/        ← depends on nothing (leaf)
core/loaders/       ← core/models/
core/sync/          ← core/models/
core/formula/       ← core/models/
core/interpolation/ ← core/models/
core/statistics/    ← core/models/
core/downsampler/   ← core/models/
core/export/        ← core/models/
core/session.py     ← all core modules above
gui/                ← core/session.py, core/models/ (MVVM: Session is the only gateway)
```

**Forbidden**: `core/` must never import from `gui/`.

## Structural Change Policy

パッケージ階層・モジュール境界・新規サブパッケージ追加など **`src/valisync/` 配下の構造変更は必ずユーザー承認を得てから実施する**。実装中に構造変更が必要と判断した場合は、変更理由と影響範囲を提示して承認を取ること。
