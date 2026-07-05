# core-loaders-hardening 第2弾（開く経路 LD-01/LD-02）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CSV を GUI から実際に開けるようにし（自動検出＋確認ダイアログ）、`.mdf`/`.dat`（MDF3 等）を受理する（拡張子拡張＋ローダーのリネーム置換）。

**Architecture:** LD-02 は `Mdf4Loader`→`MdfLoader`（ファイル `mdf_loader.py`）へリネームし `supports()` を `.mf4/.mdf/.dat` へ拡張、版判定は asammdf 委任。LD-01 は core の純粋 `CsvFormatDetector`（先頭行から `FormatDefinition` を推定）→ GUI の `CsvFormatDialog`（確認/微調整モーダル）→ `main_window._load_file` の CSV プリフライト配線（`format_resolver` 注入でテスト容易化）。

**Tech Stack:** Python 3.12/3.13・numpy・asammdf 8.8.x・PySide6・pytest / pytest-qt。

**設計 spec:** `docs/superpowers/specs/2026-07-05-core-loaders-hardening-r2-open-path-design.md`

## Global Constraints

- 品質ゲート（コミット前に全通過・終了コードで判定＝`| tail` で隠さない）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- worktree では最初に `uv sync --extra dev`（しないと pytest が親の旧コードにフォールバック）。
- コメントは WHY。全角括弧/記号（`（）` `＋` `⚠` `ℹ`）は docstring/コメントで RUF001/002/003 に触れるため半角化するか `# noqa: RUF00x`。
- GUI 機能は GUI テストレイヤー準拠（Layer A/B 必須・CI／Layer C=realgui はローカル）。実機ダイアログ操作の realgui 要否は `/gui-test-plan`。
- 非ゴール: File>Open メニュー（SH-01）／フォーマット定義の保存・再利用／内容スニッフィング／MDF3 固有変換の作り込み。

---

### Task 1: LD-02a — MdfLoader へのリネーム（置き換え）

`Mdf4Loader`→`MdfLoader`、ファイル `mdf4_loader.py`→`mdf_loader.py`、属性 `_mdf4_loader`→`_mdf_loader`、診断/ドキュメント文言「MDF4」→「MDF」。**挙動は不変**（既存テストが新名で緑になることが受け入れ条件）。

**Files:**
- Rename: `src/valisync/core/loaders/mdf4_loader.py` → `src/valisync/core/loaders/mdf_loader.py`
- Modify（識別子）: `src/valisync/core/session.py`・`src/valisync/core/loaders/__init__.py`・`src/valisync/gui/workers/expansion_confirmer.py`・`src/valisync/gui/views/expansion_dialog.py`・`tests/test_loaders.py`・`tests/test_pbt_mdf4.py`・`tests/gui/test_expansion_dialog.py`・`tests/gui/test_expansion_confirmer.py`（＋コメント: `tests/test_demo_mf4.py`・`scripts/generate_demo_mf4.py`・`tests/gui/test_channel_browser_vm.py`・`tests/gui/test_channel_browser_view.py`）

**Interfaces:**
- Produces: クラス `MdfLoader`（旧 `Mdf4Loader`・公開 API 不変: `supports`/`load`/`ConfirmExpansion`/`ExpansionRequest`/`OversizedChannel`/`EXPANSION_COLUMN_LIMIT`）、モジュール `valisync.core.loaders.mdf_loader`。

- [ ] **Step 1: worktree 準備**

```bash
uv sync --extra dev
```

- [ ] **Step 2: ファイルをリネーム**

```bash
git mv src/valisync/core/loaders/mdf4_loader.py src/valisync/core/loaders/mdf_loader.py
```

- [ ] **Step 3: 識別子を一括置換（docs は対象外）**

```bash
grep -rl --include='*.py' 'Mdf4Loader\|mdf4_loader' src tests scripts \
  | xargs sed -i 's/Mdf4Loader/MdfLoader/g; s/mdf4_loader/mdf_loader/g'
```

（`s/mdf4_loader/mdf_loader/g` は `self._mdf4_loader`→`self._mdf_loader`・`from ...loaders.mdf4_loader import`→`mdf_loader` も同時に更新。`mdf4_helpers`/`write_mdf4`/`.mf4` は別文字列なので不変。）

- [ ] **Step 4: 人間向け「MDF4」文言を「MDF」へ（sed の対象外分）**

`src/valisync/core/loaders/mdf_loader.py` 内の残存「MDF4」を Edit で修正:
- クラス docstring: 「MDF4 …」→「MDF (3.x / 4.x) …」（Task 2 でさらに追記）。
- 診断: `f"Failed to parse MDF4 '{file_path.name}': {exc}"` → `f"Failed to parse MDF '{file_path.name}': {exc}"`。

確認:
```bash
grep -rn "Mdf4Loader\|mdf4_loader" src tests scripts   # → 0 件
grep -rn "MDF4" src/valisync/core/loaders/mdf_loader.py # → 残っていれば文脈を見て MDF へ
```

- [ ] **Step 5: 全テストが新名で緑（挙動不変の確認）**

Run: `uv run pytest -q`
Expected: PASS（リネーム前と同数・import エラーなし）

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run ruff check ; uv run ruff format --check ; uv run mypy src/
git add -A
git commit -m "refactor(core): Mdf4Loader を MdfLoader へリネーム置換 (LD-02 準備・挙動不変)"
```

---

### Task 2: LD-02b — 拡張子拡張（.mf4/.mdf/.dat）＋MDF3/.dat テスト

`supports()` を 3 拡張子へ拡張。版判定は asammdf 委任。MDF3 実ファイル・`.dat` リネーム・非MDF `.dat` をテスト。

**Files:**
- Modify: `src/valisync/core/loaders/mdf_loader.py`（`supports`・docstring）
- Modify: `tests/mdf4_helpers.py`（`write_mdf3` 追加）
- Test: `tests/test_loaders.py`（LD-02 節を追加）

**Interfaces:**
- Consumes: `MdfLoader`（Task 1）。
- Produces: `MdfLoader.supports` が `{.mf4,.mdf,.dat}` を受理。`write_mdf3(tmp_path, version="3.30") -> Path`（テストヘルパ）。

- [ ] **Step 1: MDF3 ヘルパを追加**

`tests/mdf4_helpers.py` 末尾に追加（冒頭は既に `from asammdf import MDF, Signal as ASignal` 済み）:

```python
def write_mdf3(tmp_path: Path, version: str = "3.30") -> Path:
    """asammdf で MDF 3.x 実ファイルを書き出す (LD-02 の版横断読み取り検証用)."""
    t = np.arange(0.0, 5.0, 0.1, dtype=np.float64)
    sig = ASignal(
        samples=np.sin(t).astype(np.float64),
        timestamps=t,
        name="Sine3x",
    )
    mdf = MDF(version=version)
    mdf.append([sig])
    out = tmp_path / "signal_mdf3.mdf"
    mdf.save(out, overwrite=True)
    return out
```

- [ ] **Step 2: LD-02 の失敗テストを書く**

`tests/test_loaders.py` の MdfLoader 節末尾に追加（`write_mdf4` 等の既存ヘルパ import 行の並びに `write_mdf3` を足す）:

```python
def test_mdf_supports_mdf_and_dat_suffixes() -> None:
    """supports() は .mf4/.mdf/.dat を受理し .csv を拒否 (LD-02)."""
    loader = MdfLoader()
    assert loader.supports(Path("a.mf4")) is True
    assert loader.supports(Path("a.MDF")) is True   # 大小無視
    assert loader.supports(Path("a.dat")) is True
    assert loader.supports(Path("a.csv")) is False


def test_mdf3_file_loads_via_session(tmp_path: Path) -> None:
    """asammdf で書いた MDF3 実ファイルが既存 select() 経路で読める (LD-02)."""
    from tests.mdf4_helpers import write_mdf3

    path = write_mdf3(tmp_path)
    result = MdfLoader().load(path)
    assert result.signal_group is not None
    names = [s.name for s in result.signal_group.signals]
    assert any("Sine3x" in n for n in names)


def test_dat_renamed_mdf4_loads(tmp_path: Path) -> None:
    """MDF4 中身を .dat 拡張子にしても開ける (LD-02・拡張子で拒否しない)."""
    # write_mdf4(path, [channel dicts]) は tests/test_loaders.py 冒頭で
    # `.mdf4_helpers` から import 済み (CAN 定数も同様)。
    src = write_mdf4(
        tmp_path / "src.mf4",
        [{"name": "sig", "timestamps": [0.0, 1.0], "values": [1.0, 2.0], "bus_type": CAN}],
    )
    dat = tmp_path / "renamed.dat"
    dat.write_bytes(src.read_bytes())
    result = MdfLoader().load(dat)
    assert result.signal_group is not None


def test_non_mdf_dat_reports_diagnostic_not_crash(tmp_path: Path) -> None:
    """非MDF の .dat はクラッシュせず error 診断を返す (LD-02)."""
    dat = tmp_path / "garbage.dat"
    dat.write_bytes(b"this is not an MDF file\n" * 8)
    result = MdfLoader().load(dat)
    assert result.signal_group is None
    assert any(d.level == "error" for d in result.diagnostics)
```

（`write_mdf4(path, [channel dicts])` は `tests/test_loaders.py:20` の `from .mdf4_helpers import (...)` に既にあり、`CAN` 等の bus 定数も同ブロックで import 済み。`write_mdf3` を同 import ブロックへ追加する。）

- [ ] **Step 3: 失敗を確認**

Run: `uv run pytest tests/test_loaders.py -k "supports_mdf_and_dat or mdf3_file or dat_renamed or non_mdf_dat" -v`
Expected: FAIL（`supports` が `.mdf/.dat` を False 返す）

- [ ] **Step 4: supports を拡張**

`src/valisync/core/loaders/mdf_loader.py` の `supports` を変更し、クラス直下に定数を追加:

```python
class MdfLoader:
    """MDF (3.x / 4.x) file loader. asammdf でパースし Signal_Group を構築する。

    版 (MDF3/MDF4) は asammdf の内容自動判別に委任する。拡張子は .mf4/.mdf/.dat
    を受理し、非MDF/破損ファイルは load() の try/except で error 診断化する。
    """

    _SUPPORTED_SUFFIXES = frozenset({".mf4", ".mdf", ".dat"})

    # ... (既存の _READ_OPTIONS/_PROBE_OPTIONS 等はそのまま) ...

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self._SUPPORTED_SUFFIXES
```

- [ ] **Step 5: 通過＋無回帰を確認**

Run: `uv run pytest tests/test_loaders.py -q`
Expected: PASS（LD-02 新4テスト＋既存の MdfLoader テスト全緑）

> MDF3 読み取りが RED のまま（asammdf の版差で `select()` 経路が通らない）なら、spec §8「MDF3 固有差」に従い最小の版差ハンドリングを本タスクに追加する（想定外なら別途起票）。

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run ruff check ; uv run ruff format --check ; uv run mypy src/
git add src/valisync/core/loaders/mdf_loader.py tests/mdf4_helpers.py tests/test_loaders.py
git commit -m "feat(core): MDF ローダーを .mdf/.dat 受理へ拡張 (LD-02) — 版判定は asammdf 委任"
```

---

### Task 3: LD-01a — CsvFormatDetector（core・純粋）

CSV 先頭行から区切り/ヘッダ/単位行/時間列/信号列範囲を推定し `FormatDefinition`（不能なら None）と生プレビュー行を返す。Qt-free・単体テスト可能。

**Files:**
- Create: `src/valisync/core/loaders/csv_format_detector.py`
- Test: `tests/test_csv_format_detector.py`

**Interfaces:**
- Consumes: `FormatDefinition`/`Delimiter`（`core/models/format_def.py`）。
- Produces:
  - `split_line(line: str, delimiter: Delimiter) -> list[str]`
  - `DetectedFormat`（dataclass・下記フィールド）
  - `CsvFormatDetector().detect(file_path: Path, *, max_rows: int = 50) -> DetectedFormat`

- [ ] **Step 1: 失敗テストを書く**

`tests/test_csv_format_detector.py`:

```python
from __future__ import annotations

from pathlib import Path

from valisync.core.loaders.csv_format_detector import (
    CsvFormatDetector,
    split_line,
)
from valisync.core.models.format_def import Delimiter


def _w(tmp_path: Path, text: str, name: str = "d.csv") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_detect_comma_header_signals(tmp_path: Path) -> None:
    d = CsvFormatDetector().detect(_w(tmp_path, "t,speed,rpm\n0.0,1.0,10\n1.0,2.0,20\n"))
    assert d.format is not None
    assert d.delimiter is Delimiter.COMMA
    assert d.has_header is True
    assert d.timestamp_column == 0
    assert d.signal_start_column == 1 and d.signal_end_column == 2
    assert d.timestamp_unit == "sec"


def test_detect_semicolon_no_header(tmp_path: Path) -> None:
    d = CsvFormatDetector().detect(_w(tmp_path, "0.0;1.0\n1.0;2.0\n2.0;3.0\n"))
    assert d.delimiter is Delimiter.SEMICOLON
    assert d.has_header is False
    assert d.timestamp_column == 0


def test_detect_tab_delimiter(tmp_path: Path) -> None:
    d = CsvFormatDetector().detect(_w(tmp_path, "time\tv\n0\t1\n1\t2\n"))
    assert d.delimiter is Delimiter.TAB
    assert d.timestamp_column == 0  # 名前ヒント "time"


def test_detect_unit_row(tmp_path: Path) -> None:
    text = "time,speed\ns,km/h\n0.0,10\n1.0,20\n"
    d = CsvFormatDetector().detect(_w(tmp_path, text))
    assert d.has_header is True
    assert d.has_unit_row is True


def test_detect_timestamp_by_name_not_first_column(tmp_path: Path) -> None:
    text = "idx,time,v\n0,0.0,10\n1,1.0,20\n"
    d = CsvFormatDetector().detect(_w(tmp_path, text))
    assert d.timestamp_column == 1  # "time" 列を優先


def test_invalid_overlap_yields_format_none(tmp_path: Path) -> None:
    # 全列が単調増加数値 → ts=0, 信号列も 0 を含むと不変条件違反になり得るケースを、
    # 1 列だけの CSV で再現 (信号列が作れない)。
    d = CsvFormatDetector().detect(_w(tmp_path, "0.0\n1.0\n2.0\n"))
    # 1 列のみ: ts=0 で信号列範囲が作れず format=None、notes 付き。
    assert d.format is None
    assert d.notes


def test_undetectable_empty_file(tmp_path: Path) -> None:
    d = CsvFormatDetector().detect(_w(tmp_path, ""))
    assert d.format is None
    assert d.notes


def test_split_line_helper() -> None:
    assert split_line("a,b,c", Delimiter.COMMA) == ["a", "b", "c"]
    assert split_line("a\tb", Delimiter.TAB) == ["a", "b"]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_csv_format_detector.py -q`
Expected: FAIL（モジュール未作成）

- [ ] **Step 3: 検出器を実装**

`src/valisync/core/loaders/csv_format_detector.py`:

```python
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from valisync.core.models.format_def import Delimiter, FormatDefinition

# 時間列とみなすヘッダ名 (完全一致 or "time"/"timestamp" 前方一致)。
_TIME_NAME_HINTS = frozenset({"time", "timestamp", "t", "時刻", "sec", "msec", "ms"})
_DELIMITER_CANDIDATES = (
    Delimiter.COMMA,
    Delimiter.TAB,
    Delimiter.SEMICOLON,
    Delimiter.SPACE,
)


@dataclass(frozen=True)
class DetectedFormat:
    """CSV 検出結果。format は妥当なら FormatDefinition、不能なら None。

    プリフィル用フィールド (delimiter 以下) は format=None でも埋める。
    preview_lines は生の先頭行 (ダイアログで区切り変更時にライブ再分割するため)。
    """

    format: FormatDefinition | None
    name: str
    delimiter: Delimiter
    has_header: bool
    has_unit_row: bool
    timestamp_column: int
    timestamp_unit: str
    signal_start_column: int
    signal_end_column: int
    preview_lines: tuple[str, ...]
    notes: tuple[str, ...]


def split_line(line: str, delimiter: Delimiter) -> list[str]:
    """行を区切り文字で分割する (検出器とダイアログで共有)。"""
    return line.split(delimiter.value)


def _is_number(cell: str) -> bool:
    try:
        float(cell.strip())
    except ValueError:
        return False
    return True


def _row_all_nonnumeric(row: list[str]) -> bool:
    nonempty = [c for c in row if c.strip() != ""]
    return bool(nonempty) and all(not _is_number(c) for c in nonempty)


def _column_numeric(data_rows: list[list[str]], col: int) -> bool:
    vals = [r[col] for r in data_rows if col < len(r) and r[col].strip() != ""]
    if not vals:
        return False
    numeric = sum(1 for v in vals if _is_number(v))
    return numeric >= max(1, int(len(vals) * 0.8))


def _column_monotonic(data_rows: list[list[str]], col: int) -> bool:
    vals: list[float] = []
    for r in data_rows:
        if col >= len(r) or not _is_number(r[col]):
            return False
        vals.append(float(r[col]))
    return len(vals) >= 2 and all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))


class CsvFormatDetector:
    """CSV 先頭行から FormatDefinition を推定する (LD-01)。純粋・Qt-free。"""

    def detect(self, file_path: Path, *, max_rows: int = 50) -> DetectedFormat:
        lines = self._read_lines(file_path, max_rows)
        name = file_path.stem[:64] or "csv"
        if not lines:
            return self._undetectable(name, (), ("ファイルが空です",))  # noqa: RUF001

        delimiter = self._sniff_delimiter(lines)
        rows = [split_line(line, delimiter) for line in lines]
        n_cols = max((len(r) for r in rows), default=0)
        if n_cols < 1:
            return self._undetectable(
                name, tuple(lines[:10]), ("列を検出できません",)  # noqa: RUF001
            )

        has_header = _row_all_nonnumeric(rows[0])
        has_unit_row = has_header and len(rows) > 1 and _row_all_nonnumeric(rows[1])
        data_start = (2 if has_unit_row else 1) if has_header else 0
        data_rows = rows[data_start:]
        if not data_rows:
            return self._undetectable(
                name, tuple(lines[:10]), ("データ行がありません",)  # noqa: RUF001
            )

        header_names = rows[0] if has_header else []
        ts_col = self._detect_timestamp_column(header_names, data_rows, n_cols)

        notes: list[str] = []
        numeric_cols = [
            c for c in range(n_cols) if c != ts_col and _column_numeric(data_rows, c)
        ]
        if numeric_cols:
            sig_start, sig_end = min(numeric_cols), max(numeric_cols)
        else:
            sig_start = 0 if ts_col != 0 else 1
            sig_end = n_cols - 1
            notes.append("信号列を数値から特定できませんでした")  # noqa: RUF001

        notes.append("時間単位は sec と仮定しています。確認してください")  # noqa: RUF001
        fmt = self._try_build(
            name, delimiter, ts_col, "sec", sig_start, sig_end, has_header,
            has_unit_row, notes,
        )
        return DetectedFormat(
            format=fmt,
            name=name,
            delimiter=delimiter,
            has_header=has_header,
            has_unit_row=has_unit_row,
            timestamp_column=ts_col,
            timestamp_unit="sec",
            signal_start_column=sig_start,
            signal_end_column=sig_end,
            preview_lines=tuple(lines[:10]),
            notes=tuple(notes),
        )

    def _read_lines(self, file_path: Path, max_rows: int) -> list[str]:
        lines: list[str] = []
        with file_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            for i, line in enumerate(fh):
                if i >= max_rows:
                    break
                lines.append(line.rstrip("\r\n"))
        while lines and lines[-1].strip() == "":
            lines.pop()
        return lines

    def _sniff_delimiter(self, lines: list[str]) -> Delimiter:
        sample = "\n".join(lines[:20])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t ")
            for cand in _DELIMITER_CANDIDATES:
                if cand.value == dialect.delimiter:
                    return cand
        except csv.Error:
            pass
        best, best_score = Delimiter.COMMA, -1.0
        for cand in _DELIMITER_CANDIDATES:
            counts = [len(line.split(cand.value)) for line in lines if line.strip()]
            if not counts:
                continue
            maxc = max(counts)
            if maxc <= 1:
                continue
            consistency = sum(1 for c in counts if c == maxc) / len(counts)
            score = consistency * maxc
            if score > best_score:
                best, best_score = cand, score
        return best

    def _detect_timestamp_column(
        self, header_names: list[str], data_rows: list[list[str]], n_cols: int
    ) -> int:
        for c in range(n_cols):
            if c < len(header_names):
                nm = header_names[c].strip().lower()
                if nm in _TIME_NAME_HINTS or nm.startswith("time"):
                    return c
        for c in range(n_cols):
            if _column_monotonic(data_rows, c):
                return c
        return 0

    def _try_build(
        self,
        name: str,
        delimiter: Delimiter,
        ts_col: int,
        unit: str,
        sig_start: int,
        sig_end: int,
        has_header: bool,
        has_unit_row: bool,
        notes: list[str],
    ) -> FormatDefinition | None:
        try:
            return FormatDefinition(
                name=name,
                delimiter=delimiter,
                timestamp_column=ts_col,
                timestamp_unit=unit,
                signal_start_column=sig_start,
                signal_end_column=sig_end,
                has_header=has_header,
                has_unit_row=has_unit_row,
            )
        except ValueError as exc:
            notes.append(f"自動構築に失敗: {exc}")  # noqa: RUF001
            return None

    def _undetectable(
        self, name: str, preview: tuple[str, ...], notes: tuple[str, ...]
    ) -> DetectedFormat:
        return DetectedFormat(
            format=None,
            name=name,
            delimiter=Delimiter.COMMA,
            has_header=False,
            has_unit_row=False,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            preview_lines=preview,
            notes=notes,
        )
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/test_csv_format_detector.py -q`
Expected: PASS（8テスト緑）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/loaders/csv_format_detector.py tests/test_csv_format_detector.py
uv run ruff format src/valisync/core/loaders/csv_format_detector.py tests/test_csv_format_detector.py
uv run mypy src/
git add src/valisync/core/loaders/csv_format_detector.py tests/test_csv_format_detector.py
git commit -m "feat(core): CsvFormatDetector — CSV 先頭行から FormatDefinition を推定 (LD-01)"
```

---

### Task 4: LD-01b — CsvFormatDialog（GUI・確認モーダル）

検出値でプリフィルした確認/微調整ダイアログ。プレビューを区切りでライブ再分割し、不変条件違反で OK を無効化。

**Files:**
- Create: `src/valisync/gui/views/csv_format_dialog.py`
- Test: `tests/gui/test_csv_format_dialog.py`

**Interfaces:**
- Consumes: `DetectedFormat`/`split_line`（Task 3）・`FormatDefinition`/`Delimiter`。
- Produces: `CsvFormatDialog(detected, parent=None)`・インスタンス `_current_format() -> FormatDefinition | None`・クラスメソッド `ask(detected, parent=None) -> FormatDefinition | None`。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_csv_format_dialog.py`:

```python
from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.loaders.csv_format_detector import DetectedFormat
from valisync.core.models.format_def import Delimiter
from valisync.gui.views.csv_format_dialog import CsvFormatDialog


def _detected(**over: object) -> DetectedFormat:
    base = dict(
        format=None,
        name="d",
        delimiter=Delimiter.COMMA,
        has_header=True,
        has_unit_row=False,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        preview_lines=("t,speed,rpm", "0.0,1.0,10", "1.0,2.0,20"),
        notes=(),
    )
    base.update(over)
    return DetectedFormat(**base)  # type: ignore[arg-type]


def test_dialog_prefills_from_detected(qtbot: QtBot) -> None:
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    assert dlg._delim.currentData() is Delimiter.COMMA
    assert dlg._header.isChecked() is True
    assert dlg._ts_col.value() == 0
    assert dlg._sig_start.value() == 1 and dlg._sig_end.value() == 2


def test_dialog_builds_format_from_fields(qtbot: QtBot) -> None:
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    fmt = dlg._current_format()
    assert fmt is not None
    assert fmt.delimiter is Delimiter.COMMA
    assert fmt.timestamp_column == 0
    assert fmt.signal_start_column == 1 and fmt.signal_end_column == 2


def test_dialog_invalid_overlap_disables_ok(qtbot: QtBot) -> None:
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    dlg._ts_col.setValue(1)  # 時間列を信号列範囲 [1,2] に重ねる → 不変条件違反
    from PySide6.QtWidgets import QDialogButtonBox

    ok = dlg._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok.isEnabled() is False
    assert dlg._current_format() is None


def test_dialog_accept_sets_result_cancel_none(qtbot: QtBot) -> None:
    dlg = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg)
    dlg._on_accept()
    assert dlg._result is not None
    dlg2 = CsvFormatDialog(_detected())
    qtbot.addWidget(dlg2)
    dlg2.reject()
    assert dlg2._result is None
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_csv_format_dialog.py -q`
Expected: FAIL（モジュール未作成）

- [ ] **Step 3: ダイアログを実装**

`src/valisync/gui/views/csv_format_dialog.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from valisync.core.loaders.csv_format_detector import DetectedFormat, split_line
from valisync.core.models.format_def import Delimiter, FormatDefinition

_DELIM_LABEL = {
    Delimiter.COMMA: "カンマ (,)",
    Delimiter.TAB: "タブ",
    Delimiter.SEMICOLON: "セミコロン (;)",
    Delimiter.SPACE: "スペース",
}


class CsvFormatDialog(QDialog):
    """CSV 自動検出結果を確認/微調整するモーダル (LD-01)。"""

    def __init__(self, detected: DetectedFormat, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CSV フォーマットの確認")
        self._detected = detected
        self._result: FormatDefinition | None = None

        layout = QVBoxLayout(self)
        if detected.notes:
            banner = QLabel("注意: " + " / ".join(detected.notes))
            banner.setWordWrap(True)
            layout.addWidget(banner)

        self._preview = QTableWidget(self)
        self._preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._preview)

        form = QFormLayout()
        self._delim = QComboBox(self)
        for d in (Delimiter.COMMA, Delimiter.TAB, Delimiter.SEMICOLON, Delimiter.SPACE):
            self._delim.addItem(_DELIM_LABEL[d], d)
        self._delim.setCurrentIndex(self._delim.findData(detected.delimiter))
        form.addRow("区切り", self._delim)

        self._header = QCheckBox(self)
        self._header.setChecked(detected.has_header)
        form.addRow("ヘッダ行あり", self._header)

        self._unit_row = QCheckBox(self)
        self._unit_row.setChecked(detected.has_unit_row)
        form.addRow("単位行あり", self._unit_row)

        self._ts_col = QSpinBox(self)
        self._ts_col.setRange(0, 255)
        self._ts_col.setValue(detected.timestamp_column)
        form.addRow("時間列", self._ts_col)

        self._unit = QComboBox(self)
        self._unit.addItems(["sec", "msec"])
        self._unit.setCurrentText(detected.timestamp_unit)
        form.addRow("時間単位", self._unit)

        self._sig_start = QSpinBox(self)
        self._sig_start.setRange(0, 255)
        self._sig_start.setValue(detected.signal_start_column)
        form.addRow("信号列 開始", self._sig_start)

        self._sig_end = QSpinBox(self)
        self._sig_end.setRange(0, 255)
        self._sig_end.setValue(detected.signal_end_column)
        form.addRow("信号列 終了", self._sig_end)
        layout.addLayout(form)

        self._error = QLabel(self)
        self._error.setStyleSheet("color: #c0392b;")
        self._error.setWordWrap(True)
        layout.addWidget(self._error)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._delim.currentIndexChanged.connect(self._refresh)
        self._header.stateChanged.connect(self._validate)
        self._unit_row.stateChanged.connect(self._validate)
        self._ts_col.valueChanged.connect(self._validate)
        self._sig_start.valueChanged.connect(self._validate)
        self._sig_end.valueChanged.connect(self._validate)

        self._refresh()

    def _current_delim(self) -> Delimiter:
        data = self._delim.currentData()
        return data if isinstance(data, Delimiter) else Delimiter.COMMA

    def _refresh(self) -> None:
        """プレビューを現在の区切りで再分割し、列ハイライトと検証を更新。"""
        rows = [split_line(line, self._current_delim()) for line in self._detected.preview_lines]
        n_cols = max((len(r) for r in rows), default=0)
        self._preview.setRowCount(len(rows))
        self._preview.setColumnCount(n_cols)
        for ri, row in enumerate(rows):
            for ci in range(n_cols):
                text = row[ci] if ci < len(row) else ""
                self._preview.setItem(ri, ci, QTableWidgetItem(text))
        self._validate()

    def _current_format(self) -> FormatDefinition | None:
        try:
            fmt = FormatDefinition(
                name=self._detected.name,
                delimiter=self._current_delim(),
                timestamp_column=self._ts_col.value(),
                timestamp_unit=self._unit.currentText(),
                signal_start_column=self._sig_start.value(),
                signal_end_column=self._sig_end.value(),
                has_header=self._header.isChecked(),
                has_unit_row=self._unit_row.isChecked(),
            )
        except ValueError as exc:
            self._error.setText(str(exc))
            return None
        self._error.setText("")
        return fmt

    def _validate(self) -> None:
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setEnabled(self._current_format() is not None)

    def _on_accept(self) -> None:
        fmt = self._current_format()
        if fmt is not None:
            self._result = fmt
            self.accept()

    @classmethod
    def ask(
        cls, detected: DetectedFormat, parent: QWidget | None = None
    ) -> FormatDefinition | None:
        dlg = cls(detected, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._result
        return None
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_csv_format_dialog.py -q`
Expected: PASS（4テスト緑）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/csv_format_dialog.py tests/gui/test_csv_format_dialog.py
uv run ruff format src/valisync/gui/views/csv_format_dialog.py tests/gui/test_csv_format_dialog.py
uv run mypy src/
git add src/valisync/gui/views/csv_format_dialog.py tests/gui/test_csv_format_dialog.py
git commit -m "feat(gui): CsvFormatDialog — 検出値プリフィル＋区切りライブ再分割＋不変条件検証 (LD-01)"
```

---

### Task 5: LD-01c — Session.is_csv ＋ _load_file の CSV プリフライト配線

CSV 判定を Session に薄く公開し、`_load_file` に検出＋ダイアログのプリフライトを追加（`format_resolver` 差し替え可能）。

**Files:**
- Modify: `src/valisync/core/session.py`（`is_csv` 追加）
- Modify: `src/valisync/gui/views/main_window.py`（`_load_file`・`_csv_format_resolver`・`_default_csv_format_resolver`・import）
- Test: `tests/test_session.py`（is_csv）・`tests/gui/test_main_window.py`（配線）

**Interfaces:**
- Consumes: `CsvFormatDetector`/`CsvFormatDialog`（Task 3/4）。
- Produces: `Session.is_csv(path) -> bool`・`MainWindow._csv_format_resolver: Callable[[Path], FormatDefinition | None]`。

- [ ] **Step 1: is_csv の失敗テスト（core）**

`tests/test_session.py` に追加:

```python
def test_session_is_csv_true_for_csv_false_for_mdf() -> None:
    from valisync.core.session import Session

    s = Session()
    assert s.is_csv(Path("a.csv")) is True
    assert s.is_csv(Path("a.CSV")) is True
    assert s.is_csv(Path("a.mf4")) is False
```

- [ ] **Step 2: is_csv を実装**

`src/valisync/core/session.py` の `load` の直後に追加:

```python
    def is_csv(self, file_path: Path) -> bool:
        """*file_path* が CSV ローダー対象かを返す (GUI の開く経路分岐用・LD-01)。"""
        return self._csv_loader.supports(Path(file_path))
```

Run: `uv run pytest tests/test_session.py -k is_csv -q` → PASS

- [ ] **Step 3: 配線の失敗テスト（GUI）**

`tests/gui/test_main_window.py` に追加（既存 `_make_window`/`_csv_format`/`_write_csv` を流用）:

```python
def test_load_file_csv_uses_resolver_format(qtbot, monkeypatch, tmp_path):
    """CSV は _csv_format_resolver が返す FormatDefinition で session.load される (LD-01)."""
    import contextlib

    window = _make_window(qtbot)
    fmt = _csv_format()
    window._csv_format_resolver = lambda p: fmt  # ダイアログを差し替え

    captured: dict = {}
    monkeypatch.setattr(
        window._load_controller,
        "submit",
        lambda load_callable, **kw: captured.update(cb=load_callable, kw=kw),
    )
    window._load_file(_write_csv(tmp_path))

    seen: dict = {}

    def fake_load(path, f, cancel=None, confirm_expansion=None):
        seen["fmt"] = f
        raise RuntimeError("stop")

    monkeypatch.setattr(window.app_vm.session, "load", fake_load)
    with contextlib.suppress(RuntimeError):
        captured["cb"]()
    assert seen["fmt"] is fmt


def test_load_file_csv_cancel_aborts_without_submit(qtbot, monkeypatch, tmp_path):
    """resolver が None (ダイアログキャンセル) ならロードせず _on_load_cancelled (LD-01)."""
    window = _make_window(qtbot)
    window._csv_format_resolver = lambda p: None

    submits: list = []
    monkeypatch.setattr(
        window._load_controller, "submit", lambda *a, **k: submits.append(a)
    )
    cancelled: list = []
    monkeypatch.setattr(window, "_on_load_cancelled", lambda p: cancelled.append(p))
    window._load_file(_write_csv(tmp_path))

    assert submits == []
    assert len(cancelled) == 1


def test_load_file_mdf_skips_resolver(qtbot, monkeypatch, tmp_path):
    """MDF は resolver を通らず format_def=None で submit (LD-01 無回帰)."""
    window = _make_window(qtbot)
    called: list = []
    window._csv_format_resolver = lambda p: called.append(p)

    captured: dict = {}
    monkeypatch.setattr(
        window._load_controller,
        "submit",
        lambda load_callable, **kw: captured.update(cb=load_callable),
    )
    window._load_file(tmp_path / "x.mf4")
    assert called == []  # CSV 判定を通らない
    assert "cb" in captured  # submit された
```

- [ ] **Step 4: 失敗を確認**

Run: `uv run pytest tests/gui/test_main_window.py -k "csv_uses_resolver or csv_cancel or mdf_skips" -q`
Expected: FAIL（`_csv_format_resolver` 属性なし／CSV プリフライト未実装）

- [ ] **Step 5: _load_file にプリフライトを実装**

`src/valisync/gui/views/main_window.py`:

import 追加（ファイル冒頭の import 群へ）:
```python
from valisync.core.loaders.csv_format_detector import CsvFormatDetector
from valisync.core.models.format_def import FormatDefinition
from valisync.gui.views.csv_format_dialog import CsvFormatDialog
```

`__init__` 内（`_expansion_confirmer` 設定の近く）に resolver 属性を追加:
```python
        # LD-01: CSV フォーマット解決 (検出＋ダイアログ)。テストで差し替え可能。
        self._csv_format_resolver: Callable[[Path], FormatDefinition | None] = (
            self._default_csv_format_resolver
        )
```
（`Callable` は `from collections.abc import Callable`、`Path` は既存 import を確認。無ければ追加。）

`_load_file` を変更（先頭に CSV プリフライトを挿入、`fmt` を lambda へ）:
```python
    def _load_file(self, path: str | Path) -> None:
        """Load *path* off-thread. CSV は事前にフォーマットを解決する (LD-01)。"""
        session = self.app_vm.session
        target = Path(path)
        if session.is_csv(target):
            fmt = self._csv_format_resolver(target)
            if fmt is None:
                self._on_load_cancelled(target)  # ダイアログキャンセル=中止 (エラー無し)
                return
        else:
            fmt = None
        cancel_event = threading.Event()

        def _discard(outcome: LoadOutcome) -> None:
            session.remove_group(outcome.key, force=True)

        self._load_controller.submit(
            lambda: session.load(
                target,
                fmt,
                cancel=cancel_event.is_set,
                confirm_expansion=self._expansion_confirmer.confirm,
            ),
            busy=self.busy_overlay,
            cancel_event=cancel_event,
            label=target.name,
            on_success=self._on_loaded,
            on_error=lambda err: self._on_load_error(target, err),
            on_cancelled=lambda: self._on_load_cancelled(target),
            on_discard=_discard,
        )

    def _default_csv_format_resolver(
        self, path: Path
    ) -> FormatDefinition | None:
        """既定の CSV フォーマット解決: 検出 → 確認ダイアログ (LD-01)。"""
        detected = CsvFormatDetector().detect(path)
        return CsvFormatDialog.ask(detected, parent=self)
```

- [ ] **Step 6: 通過＋無回帰を確認**

Run: `uv run pytest tests/gui/test_main_window.py -q`
Expected: PASS（新3テスト＋既存 `test_load_file_wires_cancel_event_and_adapter`（.mf4）が緑）

- [ ] **Step 7: ゲート＋コミット**

```bash
uv run ruff check ; uv run ruff format --check ; uv run mypy src/
git add src/valisync/core/session.py src/valisync/gui/views/main_window.py tests/test_session.py tests/gui/test_main_window.py
git commit -m "feat(gui): _load_file に CSV プリフライト配線 (LD-01) — Session.is_csv＋format_resolver 注入"
```

---

### Task 6: ドキュメント更新（catalog / roadmap / CLAUDE.md / structure）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（LD-01/LD-02 → ✅解消）
- Modify: `docs/roadmap.md`（`core-loaders-hardening` 行を「第2弾完了＝全 LD 解消」へ）
- Modify: `CLAUDE.md`（改善サブスペック注記）
- Modify: `docs/structure.md`（`mdf4_loader.py`→`mdf_loader.py` の記述）

- [ ] **Step 1: catalog の LD-01/LD-02 を解消済みへ**

`docs/audit-findings-catalog.md`:
- LD-01: 「✅**解消（第2弾）** CSV を `CsvFormatDetector`（先頭行から区切り/ヘッダ/単位行/時間列/信号列を推定）＋`CsvFormatDialog`（確認/微調整・区切りライブ再分割・不変条件で OK 無効化）で開けるように。`_load_file` の CSV プリフライトから解決し `session.load(path, fmt)`。キャンセルは中止（エラー無し）」
- LD-02: 「✅**解消（第2弾）** `MdfLoader`（旧 Mdf4Loader をリネーム置換・`mdf_loader.py`）の `supports()` を `.mf4/.mdf/.dat` へ拡張、版判定は asammdf 委任。非MDF/破損は既存 try/except で診断化」

- [ ] **Step 2: roadmap の core-loaders 行を更新**

`docs/roadmap.md` の `core-loaders-hardening` 行を「第1弾＋第3弾＋LD-14＋**第2弾（開く経路 LD-01/02）で全 LD 解消**」に更新。件数列・代表課題を調整。

- [ ] **Step 3: CLAUDE.md の注記を更新**

`CLAUDE.md` の改善サブスペック段落で `core-loaders-hardening` を「第2弾（開く経路 LD-01/02＝CSV 自動検出＋確認ダイアログ・MDF .mdf/.dat 受理＋MdfLoader リネーム）実装済みで全 LD 完了」に更新（spec/plan ポインタ添付）。

- [ ] **Step 4: structure.md の記述を更新**

`docs/structure.md` の `mdf4_loader.py` 記述を `mdf_loader.py`（MdfLoader・MDF3/4）へ、`csv_format_detector.py`/`csv_format_dialog.py` を追記。

- [ ] **Step 5: 最終ゲート＋コミット**

```bash
uv run pytest
uv run ruff check ; uv run ruff format --check ; uv run mypy src/
git add docs/ CLAUDE.md
git commit -m "docs: core-loaders-hardening 第2弾（開く経路 LD-01/LD-02）を catalog/roadmap へ反映"
```

---

## Self-Review

- **Spec coverage**: §2 LD-02（supports 拡張＋リネーム）→ Task 1/2／§3.1 CsvFormatDetector → Task 3／§3.2 CsvFormatDialog → Task 4／§3.3 配線＋is_csv → Task 5／§6 テスト戦略 → 各タスクの Layer A(core 単体)/B(qtbot)／§9 docs → Task 6。全カバー。
- **型整合**: `DetectedFormat`（Task 3 定義）のフィールドを Task 4 ダイアログ・Task 5 は使わない（resolver 経由）。`split_line`（Task 3）を Task 4 が import。`Session.is_csv`（Task 5）・`_csv_format_resolver`（Task 5）一貫。`session.load(path, fmt, cancel=, confirm_expansion=)` は既存シグネチャ（`fake_load` の並びと一致）。
- **プレースホルダ**: なし（検出器・ダイアログ・配線とも実コード）。`write_mdf4` の正確なヘルパ名のみ実装時に既存 import を踏襲（Task 2 に明記）。
- **リネーム波及**: Task 1 で grep 0 件を保証（識別子 sed ＋文言 Edit）。docs/過去 spec は対象外（Task 6 で structure.md のみ更新）。
- **false-green 回避**: LD-02 は実 asammdf ラウンドトリップ（Session/loader 経由）で版横断読み取りを実証（memory `mdf_authoring_2d_and_value2text_traps`）。配線は resolver 注入＋submit/session.load スパイで決定的検証。
- **既存挙動の変更明示**: `_load_file` は CSV のとき resolver を通す（MDF は不変・`.mf4` の既存配線テストは resolver を通らず緑）。
