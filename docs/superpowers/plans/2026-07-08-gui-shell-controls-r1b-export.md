# gui-shell-controls 増分1b（出口: CSV Export 導線）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 読み込んだ信号を一級市民の Export CSV ダイアログ（File>Export…・Ctrl+E・ツールバー）からフルオプション（区切り/小数/単位行/精度）でオフスレッド書き出しできるようにし、SH-03 を解消する。

**Architecture:** コア `CsvExporter` を `CsvExportOptions` で拡張（round-trip 既定を保ちつつ）。`ExportCsvDialog`（`CsvFormatDialog.ask` 前例踏襲）でファイル別信号ツリー・初期選択＝プロット中・CSV 形式・保存先を集め `ExportRequest` を返す。`ExportController`（`LoadController` 前例踏襲）で `BusyOverlay` 付きオフスレッド書出。MainWindow が `export` アクション（1a で予約済み・無効）を配線しデータ有無で有効化する。

**Tech Stack:** Python 3.12+ / PySide6 (Qt6) / pyqtgraph / pytest + pytest-qt。MVVM（View=Qt / ViewModel=純 Python / Core=Qt 非依存）。

## Global Constraints

- **設計 spec**: `docs/superpowers/specs/2026-07-07-gui-shell-controls-design.md`（§4.3 ExportCsvDialog・§4.4 CsvExporter 拡張・§5.2 組み立て/テスト・§6.4 SH-03）。
- **1a は PR #51 で merged**（`main`=6457cb8）。本増分は `gui-shell-controls-r1b`（origin/main 由来）。作業前に `uv sync --extra dev`。
- **品質ゲート**（コミット前に全通過）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。ruff の実 exit は `echo "exit: ${PIPESTATUS[0]}"` で確認。
- **全角文字禁止（コード内）**: `（）＋−` 等は RUF001/002/003。日本語 UI 文字列・`# noqa: RUF001` 付き行は既存慣習に従う。
- **コア変更は spec §4.4 で承認済み**: `csv_exporter.py`／`session.py` の拡張はユーザー承認済み設計（本増分着手もユーザー承認済み）。round-trip 既定（`precision=None` → `repr(float)`）を壊さないこと。
- **MVVM 不変**: `core/` は Qt 非依存・ViewModel は Qt 非依存・View がスレッドを跨いで VM を変更しない。
- **エクスポート源**: ユーザーがダイアログでチェックした部分集合（初期選択＝アクティブパネルのプロット中信号）。増分1b では時間オフセットは既定 0（オフセット連動は後続・§5.2）。
- **区切り/小数の衝突**: `delimiter == decimal` は CSV を曖昧化するため、コア（`CsvExportOptions.__post_init__`）で拒否＋ダイアログ側でも相互排他バリデーション（Ok 無効化＋エラー表示）。
- **既存資産の再利用**: オフスレッドは `LoadController`/`BusyOverlay` パターン、ダイアログは `CsvFormatDialog.ask` パターンを踏襲（新規発明しない）。単位は `signal.metadata.get("unit","")`。

---

## File Structure

| ファイル | 責務 | 種別 |
|---|---|---|
| `src/valisync/core/export/csv_exporter.py` | `CsvExportOptions` 追加＋`export`/`_fmt`/`_rows_*`/ヘッダ結合をオプション経由に（区切り/小数/単位行/精度） | 変更 |
| `src/valisync/core/session.py` | `export_csv` に `options` を passthrough | 変更 |
| `src/valisync/gui/viewmodels/graph_panel_vm.py` | `plotted_signal_keys()` アクセサ追加（順序保持 dedup） | 変更 |
| `src/valisync/gui/views/export_csv_dialog.py` | `ExportRequest`＋`ExportCsvDialog`（信号ツリー・初期選択・フィルタ・全/なし・統合切替・形式・保存先・衝突検証・`ask()`） | 新規 |
| `src/valisync/gui/workers/export_worker.py` | `ExportWorker`(QRunnable)＋`ExportController`（BusyOverlay 付きオフスレッド export） | 新規 |
| `src/valisync/gui/views/main_window.py` | `export_csv` スロット＋`export` アクション配線＋データ有無で有効化 | 変更 |
| `tests/...`（各） | Layer A/B テスト | 新規 |
| `tests/realgui/test_export_flow.py` | Ctrl+E honest gate＋ダイアログ操作スケルトン | 新規 |

**依存順**: Task 1（core）→ Task 2（vm）は独立。Task 3（dialog）・Task 4（controller）は Task 1 に依存。Task 5（integration）は Task 1-4 全てに依存。Task 6（realgui）・Task 7（docs）は最後。

---

## Task 1: CsvExportOptions ＋ CsvExporter/Session 拡張（コア）

**Files:**
- Modify: `src/valisync/core/export/csv_exporter.py`
- Modify: `src/valisync/core/session.py`
- Test: `tests/test_csv_export_options.py`

**Interfaces:**
- Produces:
  - `CsvExportOptions(delimiter: str=",", decimal: str=".", unit_row: bool=False, precision: int|None=None)` — frozen dataclass。`__post_init__` は `delimiter==decimal` と `precision<0` を `ValueError`。
  - `CsvExporter.export(signals, output_path, use_unified_timeline=False, options: CsvExportOptions|None=None)` — `options=None` は既定 `CsvExportOptions()`。
  - `Session.export_csv(signals, output_path, use_unified_timeline=False, options: CsvExportOptions|None=None)` — passthrough。
  - 既定（`CsvExportOptions()`）の出力は**現行と完全一致**（round-trip・カンマ・単位行なし）。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_csv_export_options.py
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import CsvExportOptions, CsvExporter
from valisync.core.models import Signal


def _sig(name: str, ts: list[float], vs: list[float], unit: str = "") -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        metadata={"unit": unit} if unit else {},
    )


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").splitlines()


def test_default_options_match_current_behavior(tmp_path: Path) -> None:
    s = _sig("speed", [0.0, 1.0], [1.5, 2.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)  # options 省略 = 既定
    assert _read(out) == ["timestamp,speed", "0.0,1.5", "1.0,2.5"]


def test_semicolon_delimiter(tmp_path: Path) -> None:
    s = _sig("speed", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(delimiter=";"))
    assert _read(out) == ["timestamp;speed", "0.0;1.5"]


def test_comma_decimal_with_semicolon_delimiter(tmp_path: Path) -> None:
    s = _sig("speed", [0.5], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [s], out, options=CsvExportOptions(delimiter=";", decimal=",")
    )
    assert _read(out) == ["timestamp;speed", "0,5;1,5"]


def test_precision_fixed_decimals(tmp_path: Path) -> None:
    s = _sig("speed", [0.0], [1.23456])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(precision=2))
    assert _read(out) == ["timestamp,speed", "0.00,1.23"]


def test_unit_row_below_header(tmp_path: Path) -> None:
    s = _sig("speed", [0.0], [1.5], unit="km/h")
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(unit_row=True))
    assert _read(out) == ["timestamp,speed", "s,km/h", "0.0,1.5"]


def test_delimiter_decimal_collision_rejected() -> None:
    with pytest.raises(ValueError):
        CsvExportOptions(delimiter=",", decimal=",")


def test_negative_precision_rejected() -> None:
    with pytest.raises(ValueError):
        CsvExportOptions(precision=-1)


def test_session_passthrough(tmp_path: Path) -> None:
    # Session.export_csv が options を CsvExporter へ渡すこと
    from valisync.core.session import Session

    out = tmp_path / "d.csv"
    Session().export_csv(
        [_sig("v", [0.0], [1.5])], out, options=CsvExportOptions(delimiter=";")
    )
    assert _read(out)[0] == "timestamp;v"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_csv_export_options.py -q`
Expected: FAIL（`ImportError: CsvExportOptions` / `export()` に `options` なし）

- [ ] **Step 3: 実装 — csv_exporter.py**

`csv_exporter.py` を次のように変更（`_fmt` をオプション経由に・`CsvExportOptions` 追加・`_rows_*` にオプション・単位行）:

```python
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from valisync.core.models import Signal

#: Header name for the leading timestamp column (Req 7.3).
_TIMESTAMP_HEADER = "timestamp"
#: 単位行を出力するときのタイムスタンプ列の単位（コアは秒に正規化済み）。
_TIMESTAMP_UNIT = "s"


@dataclass(frozen=True)
class CsvExportOptions:
    """CSV 書式オプション。既定は現行挙動（round-trip・カンマ・単位行なし）。"""

    delimiter: str = ","
    decimal: str = "."
    unit_row: bool = False
    precision: int | None = None

    def __post_init__(self) -> None:
        # 区切りと小数点が同一だと CSV が曖昧になる（ダイアログでも防ぐが核でも拒否）。
        if self.delimiter == self.decimal:
            raise ValueError("delimiter と decimal に同じ文字は使えません")
        if self.precision is not None and self.precision < 0:
            raise ValueError("precision は 0 以上または None")


def _fmt(value: float, options: CsvExportOptions) -> str:
    """値を書式化。precision=None は round-trip（repr）、指定時は固定小数桁。"""
    if options.precision is None:
        s = repr(float(value))  # 再パースで float64 を厳密復元
    else:
        s = f"{float(value):.{options.precision}f}"
    if options.decimal != ".":
        s = s.replace(".", options.decimal)
    return s


class CsvExporter:
    """CSV exporter. Writes Signal data as a single CSV file.

    Columns are the timestamp (first) followed by one column per Signal value
    (Req 7.2, 7.3). Writing is atomic (Req 7.7). Formatting is governed by
    :class:`CsvExportOptions`; the default reproduces the original behavior.
    """

    def export(
        self,
        signals: list[Signal],
        output_path: Path,
        use_unified_timeline: bool = False,
        options: CsvExportOptions | None = None,
    ) -> None:
        opts = options if options is not None else CsvExportOptions()
        if use_unified_timeline:
            rows = self._rows_unified_timeline(signals, opts)
        else:
            rows = self._rows_shared_timeline(signals, opts)
        self._atomic_write(Path(output_path), rows)

    def _header_rows(self, signals: list[Signal], opts: CsvExportOptions) -> list[str]:
        """ヘッダ行（＋ unit_row 指定時は単位行）を返す。"""
        names = [s.name for s in signals]
        lines = [opts.delimiter.join([_TIMESTAMP_HEADER, *names])]
        if opts.unit_row:
            units = [s.metadata.get("unit", "") for s in signals]
            lines.append(opts.delimiter.join([_TIMESTAMP_UNIT, *units]))
        return lines

    def _rows_unified_timeline(
        self, signals: list[Signal], opts: CsvExportOptions
    ) -> list[str]:
        """Align all signals onto the sorted union of their timestamps (Req 7.4)."""
        views = [s.sorted_view() for s in signals]
        unified = np.unique(np.concatenate([ts for ts, _vs in views]))
        lookups = [dict(zip(ts.tolist(), vs.tolist(), strict=True)) for ts, vs in views]

        lines = self._header_rows(signals, opts)
        for ts in unified.tolist():
            cells = [_fmt(ts, opts)]
            cells.extend(_fmt(lk[ts], opts) if ts in lk else "" for lk in lookups)
            lines.append(opts.delimiter.join(cells))
        return lines

    def _rows_shared_timeline(
        self, signals: list[Signal], opts: CsvExportOptions
    ) -> list[str]:
        """Build CSV lines assuming all signals share one timestamp axis."""
        timestamps = signals[0].sorted_view()[0]
        sorted_values = [s.sorted_view()[1] for s in signals]
        lines = self._header_rows(signals, opts)
        for i in range(len(timestamps)):
            cells = [_fmt(timestamps[i], opts)]
            cells.extend(_fmt(vs[i], opts) for vs in sorted_values)
            lines.append(opts.delimiter.join(cells))
        return lines

    def _atomic_write(self, output_path: Path, lines: list[str]) -> None:
        """Write lines to a temp file in the target dir, then atomically rename."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(output_path.parent), prefix=".tmp_", suffix=".csv"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write("\n".join(lines))
                f.write("\n")
            os.replace(tmp_name, output_path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
```

（注: 既存の `_rows_*` にあった共有軸コメントは簡潔化のため要点のみ残す。挙動は不変。）

- [ ] **Step 4: 実装 — session.py の passthrough**

`session.py` の `export_csv` を変更:

```python
    def export_csv(
        self,
        signals: list[Signal],
        output_path: Path,
        use_unified_timeline: bool = False,
        options: "CsvExportOptions | None" = None,
    ) -> None:
        self._exporter.export(signals, output_path, use_unified_timeline, options)
```

`session.py` 冒頭の import に追加（`CsvExporter` を import している行の近く）:
```python
from valisync.core.export.csv_exporter import CsvExportOptions, CsvExporter
```
（既存が `from valisync.core.export.csv_exporter import CsvExporter` ならこの1行に統合。`CsvExportOptions` は型注釈の前方参照を実体化するため実 import する。）

- [ ] **Step 5: パス確認**

Run: `uv run pytest tests/test_csv_export_options.py -q`
Expected: PASS（8 passed）

- [ ] **Step 6: 既存 exporter テスト無回帰＋ゲート＋コミット**

```bash
uv run pytest tests/ -k "export or csv_export" -q 2>&1 | tail -5   # 既存 exporter/session テスト無回帰
uv run ruff check src/valisync/core/export/csv_exporter.py src/valisync/core/session.py tests/test_csv_export_options.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/core/export/csv_exporter.py src/valisync/core/session.py tests/test_csv_export_options.py
uv run mypy src/valisync/core/export/csv_exporter.py src/valisync/core/session.py
git add src/valisync/core/export/csv_exporter.py src/valisync/core/session.py tests/test_csv_export_options.py
git commit -m "feat(core): CsvExportOptions で CSV 書式拡張（区切り/小数/単位行/精度・既定は現行一致・SH-03）"
```

---

## Task 2: GraphPanelVM.plotted_signal_keys()

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- Test: `tests/gui/test_graph_panel_plotted_keys.py`

**Interfaces:**
- Produces: `GraphPanelVM.plotted_signal_keys() -> list[str]` — プロット中の信号キーを**追加順・重複除去**で返す（同一信号が複数軸にあっても1回）。Export ダイアログの初期選択に使う。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_graph_panel_plotted_keys.py
from __future__ import annotations

from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


def test_plotted_signal_keys_order_preserving_dedup() -> None:
    vm = GraphPanelVM(Session())
    vm.add_signal("csv_1::a")
    vm.add_signal("csv_1::b")
    vm.add_signal_to_axis("csv_1::a", 0)  # 同一キーを別操作で再追加（重複）
    assert vm.plotted_signal_keys() == ["csv_1::a", "csv_1::b"]


def test_plotted_signal_keys_empty() -> None:
    assert GraphPanelVM(Session()).plotted_signal_keys() == []
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_plotted_keys.py -q`
Expected: FAIL（`AttributeError: plotted_signal_keys`）

- [ ] **Step 3: 実装**

`graph_panel_vm.py` の「Signal list management」節（`add_signal` の近く）に追加:

```python
    def plotted_signal_keys(self) -> list[str]:
        """プロット中の信号キーを追加順・重複除去で返す（Export 初期選択用）。"""
        return list(dict.fromkeys(e.signal_key for e in self._plotted))
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_graph_panel_plotted_keys.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_plotted_keys.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_plotted_keys.py
uv run mypy src/valisync/gui/viewmodels/graph_panel_vm.py
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_plotted_keys.py
git commit -m "feat(gui): GraphPanelVM.plotted_signal_keys()（Export 初期選択・SH-03）"
```

---

## Task 3: ExportRequest ＋ ExportCsvDialog

**Files:**
- Create: `src/valisync/gui/views/export_csv_dialog.py`
- Test: `tests/gui/test_export_csv_dialog.py`

**Interfaces:**
- Consumes: `AppViewModel`（`loaded_file_keys`・`session.source_name(key)`・`session.group_signals(key)`）・`CsvExportOptions`（Task 1）・`Signal`。
- Produces:
  - `ExportRequest`（frozen dataclass）: `signals: list[Signal]`・`output_path: Path`・`use_unified_timeline: bool`・`options: CsvExportOptions`。
  - `ExportCsvDialog(app_vm, initial_selected: set[str], parent=None)` — QDialog。
  - `ExportCsvDialog.ask(cls, app_vm, initial_selected: set[str], parent=None) -> ExportRequest | None`（`CsvFormatDialog.ask` 前例）。
  - 初期チェック＝`initial_selected`（信号 `name` 集合）。フィルタ・すべて/なし・統合切替・区切り/小数/単位行/精度。`delimiter==decimal` は Ok 無効化＋エラー表示。0 選択も Ok 無効。
  - テスト容易化のため、保存先取得は差し替え可能なフック `_save_path_provider: Callable[[], str]`（既定 `QFileDialog.getSaveFileName` ラッパ）。ツリー/Ok に objectName（`"export_tree"`/`"export_ok"`）。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_export_csv_dialog.py
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Signal
from valisync.gui.views.export_csv_dialog import ExportCsvDialog, ExportRequest


class _FakeSession:
    def __init__(self, groups: dict[str, list[Signal]], names: dict[str, str]) -> None:
        self._groups = groups
        self._names = names

    def source_name(self, key: str) -> str:
        return self._names[key]

    def group_signals(self, key: str) -> list[Signal]:
        return self._groups[key]


class _FakeAppVM:
    def __init__(self, session: _FakeSession, keys: list[str]) -> None:
        self.session = session
        self.loaded_file_keys = keys


def _sig(name: str) -> Signal:
    return Signal(name=name, timestamps=np.array([0.0]), values=np.array([1.0]))


def _app_vm() -> _FakeAppVM:
    sess = _FakeSession(
        groups={"csv_1": [_sig("csv_1::a"), _sig("csv_1::b")]},
        names={"csv_1": "run.csv"},
    )
    return _FakeAppVM(sess, ["csv_1"])


def _ok(dlg: ExportCsvDialog) -> bool:
    return dlg._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_initial_selection_is_plotted(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"})
    qtbot.addWidget(dlg)
    checked = dlg._checked_keys()
    assert checked == ["csv_1::a"]  # プロット中のみ初期チェック
    assert _ok(dlg) is True  # 1 件チェックで Ok 有効


def test_select_all_and_none(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected=set())
    qtbot.addWidget(dlg)
    assert _ok(dlg) is False  # 0 選択で Ok 無効
    dlg._select_all()
    assert set(dlg._checked_keys()) == {"csv_1::a", "csv_1::b"}
    assert _ok(dlg) is True
    dlg._select_none()
    assert dlg._checked_keys() == []
    assert _ok(dlg) is False


def test_delimiter_decimal_collision_disables_ok(qtbot: QtBot) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a"})
    qtbot.addWidget(dlg)
    dlg._set_delimiter(",")
    dlg._set_decimal(",")  # 衝突
    assert _ok(dlg) is False
    assert dlg._error.text() != ""


def test_ask_builds_request_from_widgets(qtbot: QtBot, tmp_path: Path) -> None:
    dlg = ExportCsvDialog(_app_vm(), initial_selected={"csv_1::a", "csv_1::b"})
    qtbot.addWidget(dlg)
    dlg._set_delimiter(";")
    dlg._unit_row.setChecked(True)
    target = tmp_path / "out.csv"
    dlg._save_path_provider = lambda: str(target)  # 保存ダイアログを差し替え
    dlg._on_accept()
    req = dlg._result
    assert isinstance(req, ExportRequest)
    assert {s.name for s in req.signals} == {"csv_1::a", "csv_1::b"}
    assert req.output_path == target
    assert req.options.delimiter == ";"
    assert req.options.unit_row is True
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_export_csv_dialog.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

```python
# src/valisync/gui/views/export_csv_dialog.py
"""ExportCsvDialog — 選択信号を CSV へ書き出すモーダル (SH-03)。

CsvFormatDialog.ask を前例に、ファイル別の信号ツリー（初期チェック=プロット中）・
フィルタ・すべて/なし・統合タイムライン切替・CSV 形式（区切り/小数/単位行/精度）・
保存先を集め、ExportRequest を返す。実 export は呼び出し側がオフスレッドで行う。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from valisync.core.export.csv_exporter import CsvExportOptions
from valisync.core.models import Signal

if TYPE_CHECKING:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

# ラベル -> 実文字。タブ/スペースは表示名と実文字が異なる。
_DELIMS: tuple[tuple[str, str], ...] = (
    ("カンマ (,)", ","),
    ("セミコロン (;)", ";"),
    ("タブ", "\t"),
    ("スペース", " "),
)
_DECIMALS: tuple[tuple[str, str], ...] = (("ピリオド (.)", "."), ("カンマ (,)", ","))


@dataclass(frozen=True)
class ExportRequest:
    """ExportCsvDialog が返す確定要求。"""

    signals: list[Signal]
    output_path: Path
    use_unified_timeline: bool
    options: CsvExportOptions


class ExportCsvDialog(QDialog):
    def __init__(
        self,
        app_vm: AppViewModel,
        initial_selected: set[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CSV エクスポート")
        self._app_vm = app_vm
        self._result: ExportRequest | None = None
        # 保存先取得フック（テストで差し替え可能）。空文字はキャンセル。
        self._save_path_provider: Callable[[], str] = self._default_save_path

        layout = QVBoxLayout(self)

        # フィルタ
        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText("信号名でフィルタ…")
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        # 信号ツリー（ファイル別・チェックボックス）
        self._tree = QTreeWidget(self)
        self._tree.setObjectName("export_tree")
        self._tree.setHeaderHidden(True)
        self._sig_by_key: dict[str, Signal] = {}
        for key in app_vm.loaded_file_keys:
            top = QTreeWidgetItem(self._tree, [app_vm.session.source_name(key)])
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            for sig in app_vm.session.group_signals(key):
                child = QTreeWidgetItem(top, [sig.name])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                state = (
                    Qt.CheckState.Checked
                    if sig.name in initial_selected
                    else Qt.CheckState.Unchecked
                )
                child.setCheckState(0, state)
                child.setData(0, Qt.ItemDataRole.UserRole, sig.name)
                self._sig_by_key[sig.name] = sig
        self._tree.expandAll()
        self._tree.itemChanged.connect(lambda *_: self._validate())
        layout.addWidget(self._tree)

        # すべて/なし
        btn_row = QHBoxLayout()
        all_btn = QPushButton("すべて選択")
        all_btn.clicked.connect(self._select_all)
        none_btn = QPushButton("選択なし")
        none_btn.clicked.connect(self._select_none)
        btn_row.addWidget(all_btn)
        btn_row.addWidget(none_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # 形式オプション
        form = QFormLayout()
        self._unified = QCheckBox(self)
        form.addRow("統合タイムライン", self._unified)
        self._delim = QComboBox(self)
        for label, ch in _DELIMS:
            self._delim.addItem(label, ch)
        form.addRow("区切り", self._delim)
        self._decimal = QComboBox(self)
        for label, ch in _DECIMALS:
            self._decimal.addItem(label, ch)
        form.addRow("小数点", self._decimal)
        self._unit_row = QCheckBox(self)
        form.addRow("単位行を出力", self._unit_row)
        self._round_trip = QCheckBox("ラウンドトリップ（無指定）", self)
        self._round_trip.setChecked(True)
        form.addRow("精度", self._round_trip)
        self._precision = QSpinBox(self)
        self._precision.setRange(0, 15)
        self._precision.setValue(6)
        self._precision.setEnabled(False)
        form.addRow("小数桁", self._precision)
        layout.addLayout(form)

        self._round_trip.toggled.connect(
            lambda on: self._precision.setEnabled(not on)
        )
        self._delim.currentIndexChanged.connect(self._validate)
        self._decimal.currentIndexChanged.connect(self._validate)

        self._error = QLabel(self)
        self._error.setStyleSheet("color: #c0392b;")
        self._error.setWordWrap(True)
        layout.addWidget(self._error)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("エクスポート…")
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._validate()

    # ─── 選択 ─────────────────────────────────────────────────────────────
    def _iter_children(self):  # type: ignore[no-untyped-def]
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def _checked_keys(self) -> list[str]:
        return [
            c.data(0, Qt.ItemDataRole.UserRole)
            for c in self._iter_children()
            if c.checkState(0) == Qt.CheckState.Checked
        ]

    def _select_all(self) -> None:
        for c in self._iter_children():
            c.setCheckState(0, Qt.CheckState.Checked)

    def _select_none(self) -> None:
        for c in self._iter_children():
            c.setCheckState(0, Qt.CheckState.Unchecked)

    def _apply_filter(self, text: str) -> None:
        t = text.strip().lower()
        for c in self._iter_children():
            key = c.data(0, Qt.ItemDataRole.UserRole)
            c.setHidden(bool(t) and t not in key.lower())

    # ─── 形式 ─────────────────────────────────────────────────────────────
    def _set_delimiter(self, ch: str) -> None:
        self._delim.setCurrentIndex(self._delim.findData(ch))

    def _set_decimal(self, ch: str) -> None:
        self._decimal.setCurrentIndex(self._decimal.findData(ch))

    def _current_options(self) -> CsvExportOptions | None:
        precision = None if self._round_trip.isChecked() else self._precision.value()
        try:
            return CsvExportOptions(
                delimiter=self._delim.currentData(),
                decimal=self._decimal.currentData(),
                unit_row=self._unit_row.isChecked(),
                precision=precision,
            )
        except ValueError as exc:
            self._error.setText(str(exc))
            return None

    def _validate(self) -> None:
        opts = self._current_options()
        has_sel = bool(self._checked_keys())
        if opts is not None:
            self._error.setText("" if has_sel else "少なくとも1信号を選択してください")
        ok = opts is not None and has_sel
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    # ─── 確定 ─────────────────────────────────────────────────────────────
    def _default_save_path(self) -> str:
        from PySide6.QtWidgets import QFileDialog

        path, _sel = QFileDialog.getSaveFileName(
            self, "CSV の保存先", "", "CSV (*.csv);;すべてのファイル (*)"
        )
        return path

    def _on_accept(self) -> None:
        opts = self._current_options()
        keys = self._checked_keys()
        if opts is None or not keys:
            return
        path = self._save_path_provider()
        if not path:
            return  # 保存ダイアログをキャンセル
        self._result = ExportRequest(
            signals=[self._sig_by_key[k] for k in keys],
            output_path=Path(path),
            use_unified_timeline=self._unified.isChecked(),
            options=opts,
        )
        self.accept()

    @classmethod
    def ask(
        cls,
        app_vm: AppViewModel,
        initial_selected: set[str],
        parent: QWidget | None = None,
    ) -> ExportRequest | None:
        dlg = cls(app_vm, initial_selected, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._result
        return None
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_export_csv_dialog.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/export_csv_dialog.py tests/gui/test_export_csv_dialog.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/export_csv_dialog.py tests/gui/test_export_csv_dialog.py
uv run mypy src/valisync/gui/views/export_csv_dialog.py
git add src/valisync/gui/views/export_csv_dialog.py tests/gui/test_export_csv_dialog.py
git commit -m "feat(gui): ExportCsvDialog（信号ツリー・初期選択=プロット中・形式/衝突検証・ask・SH-03）"
```

---

## Task 4: ExportController ＋ ExportWorker（オフスレッド）

**Files:**
- Create: `src/valisync/gui/workers/export_worker.py`
- Test: `tests/gui/test_export_worker.py`

**Interfaces:**
- Consumes: `BusyOverlay`（`show`/`hide`/`set_message`）。
- Produces:
  - `ExportWorker(export_callable: Callable[[], None])` (QRunnable) — `run` で呼び、成功で `signals.finished`、例外で `signals.failed(exc)`。
  - `ExportController(thread_pool=None, parent=None)` — `submit(export_callable, *, busy=None, on_success=None, on_error=None, label=None)`。BusyOverlay を表示→完了/失敗で非表示、GUI スレッドで on_success/on_error を呼ぶ。v1 は mid-write キャンセル無し（大容量の全行メモリ構築＋atomic write のため・後続で検討）。

**注**: `LoadController` を前例とするが、Export は返り値 None・cancel/discard/task 無しで簡素。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_export_worker.py
from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.workers.export_worker import ExportController


def test_success_invokes_on_success(qtbot: QtBot) -> None:
    ctl = ExportController()
    done: list[int] = []
    ran: list[int] = []
    ctl.submit(lambda: ran.append(1), on_success=lambda: done.append(1))
    qtbot.waitUntil(lambda: done == [1], timeout=3000)
    assert ran == [1]


def test_failure_invokes_on_error(qtbot: QtBot) -> None:
    ctl = ExportController()
    errs: list[Exception] = []

    def _boom() -> None:
        raise OSError("disk full")

    ctl.submit(_boom, on_error=errs.append)
    qtbot.waitUntil(lambda: len(errs) == 1, timeout=3000)
    assert isinstance(errs[0], OSError)


def test_busy_shown_then_hidden(qtbot: QtBot) -> None:
    class _Busy:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def set_message(self, m: str) -> None:
            self.calls.append("msg")

        def show(self) -> None:
            self.calls.append("show")

        def hide(self) -> None:
            self.calls.append("hide")

    ctl = ExportController()
    busy = _Busy()
    done: list[int] = []
    ctl.submit(lambda: None, busy=busy, on_success=lambda: done.append(1))
    qtbot.waitUntil(lambda: done == [1], timeout=3000)
    assert "show" in busy.calls and busy.calls[-1] == "hide"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_export_worker.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

```python
# src/valisync/gui/workers/export_worker.py
"""Off-thread CSV export (SH-03).

ExportWorker runs an injected zero-arg export callable on a QThreadPool thread
and reports completion via queued signals. ExportController shows a BusyOverlay
while the export runs and drives success/error callbacks back on the GUI thread,
so the View stays responsive during large writes (the exporter builds all rows
in memory then does one atomic write — the direct reason off-thread is needed).

Simpler than LoadController: export returns None and has no cancel/discard/task.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

if TYPE_CHECKING:
    from valisync.gui.views.busy_overlay import BusyOverlay


class ExportWorkerSignals(QObject):
    finished = Signal()
    failed = Signal(object)  # the raised Exception


class ExportWorker(QRunnable):
    def __init__(self, export_callable: Callable[[], None]) -> None:
        super().__init__()
        self._export_callable = export_callable
        self.signals = ExportWorkerSignals()

    def run(self) -> None:
        try:
            self._export_callable()
        except Exception as exc:  # report, never crash the pool thread
            self.signals.failed.emit(exc)
        else:
            self.signals.finished.emit()


class ExportController(QObject):
    def __init__(
        self,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pool = thread_pool or QThreadPool.globalInstance()

    def submit(
        self,
        export_callable: Callable[[], None],
        *,
        busy: BusyOverlay | None = None,
        on_success: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        label: str | None = None,
    ) -> None:
        if busy is not None:
            busy.set_message(f"エクスポート中: {label or 'CSV'}")
            busy.show()
        worker = ExportWorker(export_callable)
        worker.signals.finished.connect(
            lambda: self._finish(busy, on_success)
        )
        worker.signals.failed.connect(
            lambda exc: self._fail(busy, exc, on_error)
        )
        self._pool.start(worker)

    def _finish(
        self, busy: BusyOverlay | None, on_success: Callable[[], None] | None
    ) -> None:
        if busy is not None:
            busy.hide()
        if on_success is not None:
            on_success()

    def _fail(
        self,
        busy: BusyOverlay | None,
        exc: Exception,
        on_error: Callable[[Exception], None] | None,
    ) -> None:
        if busy is not None:
            busy.hide()
        if on_error is not None:
            on_error(exc)
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_export_worker.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/workers/export_worker.py tests/gui/test_export_worker.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/workers/export_worker.py tests/gui/test_export_worker.py
uv run mypy src/valisync/gui/workers/export_worker.py
git add src/valisync/gui/workers/export_worker.py tests/gui/test_export_worker.py
git commit -m "feat(gui): ExportController/ExportWorker（BusyOverlay 付きオフスレッド export・SH-03）"
```

---

## Task 5: MainWindow — export_csv スロット＋アクション配線＋有効化

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_main_window_export.py`

**Interfaces:**
- Consumes: `ExportCsvDialog.ask`（Task 3）・`ExportController`（Task 4）・`GraphPanelVM.plotted_signal_keys`（Task 2）・`Session.export_csv`（Task 1）・`shell_actions.action("export")`（1a）。
- Produces:
  - `MainWindow.export_csv(*_) -> None` — アクティブパネルの `plotted_signal_keys()` を初期選択に `ExportCsvDialog.ask` → 要求があれば `ExportController.submit` でオフスレッド `session.export_csv(...)`。成功→ステータス、失敗→ステータス＋モーダル。
  - `export` アクションはデータ有無で有効/無効（`_on_app_change` の loaded/unloaded）。初期は無効（1a の ShellActions 既定）。
  - `MainWindow._export_controller: ExportController`。
  - テスト差し替え点: `MainWindow._export_dialog = ExportCsvDialog.ask`（クラス属性でなくインスタンスフックにしてもよいが、ここでは module 関数を直接呼び monkeypatch 可能にする）。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_main_window_export.py
from __future__ import annotations

from pathlib import Path

import numpy as np
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.export.csv_exporter import CsvExportOptions
from valisync.core.models import Signal
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views import main_window as mw_mod
from valisync.gui.views.export_csv_dialog import ExportRequest
from valisync.gui.views.main_window import MainWindow


def test_export_action_disabled_until_data(qtbot: QtBot) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    assert mw.shell_actions.action("export").isEnabled() is False
    mw.app_vm.register_loaded("csv_1")  # loaded 通知で有効化
    assert mw.shell_actions.action("export").isEnabled() is True


def test_export_csv_runs_export_with_request(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    target = tmp_path / "out.csv"
    sig = Signal(name="csv_1::a", timestamps=np.array([0.0]), values=np.array([1.0]))
    req = ExportRequest(
        signals=[sig],
        output_path=target,
        use_unified_timeline=False,
        options=CsvExportOptions(delimiter=";"),
    )
    # ダイアログを差し替え（要求を返す）
    monkeypatch.setattr(mw_mod.ExportCsvDialog, "ask", classmethod(lambda cls, *a, **k: req))
    # export を捕捉（実書出はここでは不要）
    calls: list[tuple] = []
    monkeypatch.setattr(
        mw.app_vm.session, "export_csv", lambda *a, **k: calls.append((a, k))
    )
    mw.export_csv()
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=3000)
    args, kwargs = calls[0]
    assert args[0] == [sig] and args[1] == target


def test_export_csv_cancel_does_nothing(qtbot: QtBot, monkeypatch) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    monkeypatch.setattr(mw_mod.ExportCsvDialog, "ask", classmethod(lambda cls, *a, **k: None))
    called: list[int] = []
    monkeypatch.setattr(mw.app_vm.session, "export_csv", lambda *a, **k: called.append(1))
    mw.export_csv()
    assert called == []
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_main_window_export.py -q`
Expected: FAIL（`export_csv` なし / export 無効化されない）

- [ ] **Step 3: 実装**

`main_window.py` の import に追加:
```python
from valisync.gui.views.export_csv_dialog import ExportCsvDialog
from valisync.gui.workers.export_worker import ExportController
```

`__init__` の `self._load_controller = LoadController(parent=self)` の近くに:
```python
        self._export_controller = ExportController(parent=self)
```

`export` の triggered を接続（1a のコメント「export の triggered は増分1b で接続」の行を置換）:
```python
        self.shell_actions.action("export").triggered.connect(self.export_csv)
```

`_on_app_change` にデータ有無での有効化を追加:
```python
    def _on_app_change(self, change: str) -> None:
        if change == "loaded":
            self.channel_browser_vm.refresh()
            self._workbench_started = True
            self._update_central()
        if change in ("active_file", "loaded", "unloaded"):
            self._update_window_title()
        if change in ("loaded", "unloaded"):
            # SH-03: データがあるときだけ Export を許可（spec §6.4）
            self.shell_actions.action("export").setEnabled(
                bool(self.app_vm.loaded_file_keys)
            )
```

`export_csv` スロットを Actions 節（`open_file` の近く）に追加:
```python
    def export_csv(self, *_: object) -> None:
        """File>Export / Ctrl+E / ツールバーの集約先（SH-03）。

        アクティブパネルのプロット中信号を初期選択に ExportCsvDialog を開き、
        確定したら既存の BusyOverlay パターンでオフスレッド書き出しする。
        """
        panels = self.graph_area_vm.panels(self.graph_area_vm.active_tab_index)
        initial = set(panels[0].plotted_signal_keys()) if panels else set()
        req = ExportCsvDialog.ask(self.app_vm, initial, self)
        if req is None:
            return
        session = self.app_vm.session
        self._export_controller.submit(
            lambda: session.export_csv(
                req.signals, req.output_path, req.use_unified_timeline, req.options
            ),
            busy=self.busy_overlay,
            label=req.output_path.name,
            on_success=lambda: self.statusBar().showMessage(
                f"エクスポートしました: {req.output_path.name}"
            ),
            on_error=self._on_export_error,
        )

    def _on_export_error(self, err: Exception) -> None:
        # FB-01 同様: 失敗を握りつぶさない（ステータス＋モーダル）。
        self.statusBar().showMessage(f"⛔ エクスポート失敗: {err}")
        QMessageBox.critical(
            self, "エクスポートエラー", f"CSV を書き出せませんでした。\n\n{err}"
        )
```

- [ ] **Step 4: パス確認＋全体無回帰**

```bash
uv run pytest tests/gui/test_main_window_export.py -q
uv run pytest -q 2>&1 | tail -3
```
Expected: 新テスト PASS＋全体無回帰。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/main_window.py tests/gui/test_main_window_export.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/main_window.py tests/gui/test_main_window_export.py
uv run mypy src/valisync/gui/views/main_window.py
git add src/valisync/gui/views/main_window.py tests/gui/test_main_window_export.py
git commit -m "feat(gui): Export CSV スロット＋アクション配線＋データ有無で有効化（File>Export/Ctrl+E・SH-03）"
```

---

## Task 6: Layer C realgui スケルトン（Ctrl+E honest gate ＋ ダイアログ操作）

**Files:**
- Create: `tests/realgui/test_export_flow.py`

**Interfaces:**
- Consumes: `MainWindow`・`ShellActions`（export／Ctrl+E）・`ExportCsvDialog`。
- 目的: (1) Ctrl+E が `MainWindow.export_csv` へ到達するか（実 OS キー入力）を honest gate 化。**構築前にクラス `MainWindow.export_csv` を patch**（`__init__` が QAction を connect した後にインスタンス patch しても差し替わらず実ダイアログでハングする — memory `gui_realgui_qaction_slot_patch_before_construction`）。(2) ダイアログ実操作のスケルトン（skip 前提）。

- [ ] **Step 1: スケルトンを書く**

```python
# tests/realgui/test_export_flow.py
"""Layer C: Ctrl+E が export_csv へ到達するか（実 OS キー入力）。

honest RED: File メニュー/ツールバーに export を載せ忘れる、shortcut を外す、
またはデータ無しで無効のままだと Ctrl+E が届かず fired が空になる。
"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_ctrl_e_triggers_export(qtbot: QtBot, monkeypatch) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    fired: list[int] = []
    # 構築前にクラスを patch（connect が捕捉する bound method を stub 化）。
    monkeypatch.setattr(MainWindow, "export_csv", lambda self, *a: fired.append(1))
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    # export はデータ有りで有効。ロード成功を模擬して有効化する。
    mw.app_vm.register_loaded("csv_1")
    mw.show()
    qtbot.waitExposed(mw)
    QApplication.processEvents()

    qtbot.keyClick(mw, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()

    assert fired == [1], "Ctrl+E が export_csv に届かない（export の shortcut/有効化/配線を確認）"
```

- [ ] **Step 2: 収集確認**

Run: `uv run pytest tests/realgui/test_export_flow.py --collect-only -q`
Expected: 1 test collected（`--realgui` 無しでは skip）

- [ ] **Step 3: ゲート＋コミット**

```bash
uv run ruff check tests/realgui/test_export_flow.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format tests/realgui/test_export_flow.py
git add tests/realgui/test_export_flow.py
git commit -m "test(realgui): Ctrl+E→export_csv 到達の honest gate スケルトン（SH-03）"
```

---

## Task 7: docs 反映（catalog / roadmap）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（SH-03 解消）
- Modify: `docs/roadmap.md`（gui-shell-controls 行に増分1b・increment 1 完結）

- [ ] **Step 1: catalog の SH-03 行に解消注記**

SH-03 行頭の優先度を `✅解消（増分1b）` にし、本文先頭へ:
`**✅解消（2026-07-08・増分1b）: Export CSV ダイアログ（File>Export…・Ctrl+E・ツールバー）＝ファイル別信号ツリー・初期選択=プロット中・統合タイムライン・フルオプション（区切り/小数/単位行/精度）・オフスレッド書出（BusyOverlay・失敗時モーダル）。CsvExporter を CsvExportOptions で拡張（既定は現行一致）。** 〔元課題〕...`

- [ ] **Step 2: roadmap の gui-shell-controls 行を更新**

「増分1b（出口: SH-03・Export ダイアログ＋csv_exporter 拡張＋オフスレッド）実装済み＝**増分1（File I/O 導線）完結**」を追記。

- [ ] **Step 3: コミット**

```bash
git add docs/audit-findings-catalog.md docs/roadmap.md
git commit -m "docs: gui-shell-controls 増分1b（Export・SH-03）解消を catalog/roadmap に反映"
```

---

## Self-Review（プラン→spec 突合）

**1. Spec カバレッジ**（spec §4.3/4.4/5.2/6.4）:
- CsvExporter フルオプション（区切り/小数/単位行/精度）＋既定一致 → Task 1。✓
- Session passthrough → Task 1。✓
- ExportCsvDialog（信号ツリー・初期選択=プロット中・フィルタ・全/なし・統合・形式・保存先・`ExportRequest`・`ask`） → Task 3。✓
- 初期選択の源（plotted） → Task 2（accessor）＋Task 5（配線）。✓
- オフスレッド（LoadController パターン・BusyOverlay・失敗時フィードバック） → Task 4＋Task 5。✓
- 到達（File>Export/Ctrl+E/ツールバー）＋データ無し無効 → Task 5（配線・有効化）。アクション定義は 1a 済み。✓
- delimiter/decimal 衝突の相互排他 → Task 1（核 `ValueError`）＋Task 3（Ok 無効化＋エラー）。✓
- Ctrl+E 衝突監査 → Task 6（honest gate で実到達を検証）。pyqtgraph 束縛は現状 Escape のみ（spec §5.1）で衝突なし。✓
- Layer A/B 必須＋Layer C（新入力経路 Ctrl+E/ダイアログ操作） → 各 Task のテスト＋Task 6。✓

**2. プレースホルダ走査**: TBD/TODO なし。全コードは実挙動。

**3. 型整合**: `CsvExportOptions(delimiter/decimal/unit_row/precision)`・`CsvExporter.export(...,options)`・`Session.export_csv(...,options)`・`GraphPanelVM.plotted_signal_keys()->list[str]`・`ExportRequest(signals/output_path/use_unified_timeline/options)`・`ExportCsvDialog.ask(app_vm,initial_selected,parent)->ExportRequest|None`・`ExportController.submit(callable,*,busy,on_success,on_error,label)`・`MainWindow.export_csv`/`_export_controller`/`_on_export_error` — Produces と後続 Consumes が一致。

**留意（実装時）**: (a) `AppViewModel` の実型（`loaded_file_keys`・`session.group_signals`・`session.source_name`）は Task 3 のフェイク VM と一致することを実行時に確認。(b) `_on_app_change` の既存分岐を壊さず追記（1a の title/central 更新を保持）。(c) 核変更（csv_exporter/session）はコミット前に既存 export テストの無回帰を必ず確認。
