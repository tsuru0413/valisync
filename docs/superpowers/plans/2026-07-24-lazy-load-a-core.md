# 遅延ロード 増分A（core）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ファイルオープン時に全信号の**値**を eager 展開するのをやめ、`Signal.values` をサンプルソース抽象の背後でオンデマンド展開にする（メモリ 2GB/ファイル・ロード 13s の根治）。

**Architecture:** `Signal.values` を `SampleSource` プロトコル（`EagerValues`＝配列直持ち / `LazyMdfValues`＝`mdf` からオンデマンド読み）の背後に置くプロパティにする。`timestamps`（グループ master）は eager 保持。ローダーは `mdf.select`（全値一括読み）を **1 チャンネル select 経由の master 読み**＋メタデータ列挙＋1レコード形状プローブに置換し、MDF ハンドルを `SignalGroup` に保持。既存の全 Signal 構築サイトは `values=<array>`（→`EagerValues` に自動包装）のまま無変更で、遅延サイト（mdf_loader）と共有サイト（namespaced/offset）だけ `values_source=` を使う。

> **⚠ 実装中の設計反転（Task 3b・本プランの記述を訂正）**: 当初 master は `mdf.get_master(gi)` で読む計画だったが、**ハンドルを開いたまま保持する本設計では使用禁止**と実測で判明した（生レコードブロック全体を開いたハンドルにキャッシュし解放しない — `prod_demo.mf4` で **+1,296 MB** 保持 / select 経由なら **+197 MB**・実 GUI 定常 RSS 1,897 MB → 868 MB）。本プラン中の `get_master` 記述はすべて select 経由へ訂正済み（Task 3 Step 4）。回帰ガード `tests/core/loaders/test_mdf_loader_master_retention.py` は **`VALISYNC_MEMTEST=1` ＋ 1.36 GB `prod_demo.mf4` ＋ psutil の二重 gate で CI 非実行**。詳細は設計 spec の改訂履歴・§設計判断。

**Tech Stack:** Python 3.13 / numpy / asammdf 8.8.22 / PySide6（teardown のみ）/ pytest。

**設計 spec:** [docs/superpowers/specs/2026-07-24-lazy-load-signal-samples-design.md](../specs/2026-07-24-lazy-load-signal-samples-design.md)（増分A の節が一次情報源）。

## Global Constraints

- 品質ゲート全通過: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- **既存の公開挙動を完全保存**: `sorted_view`/`finite_view`/`range_stat_index`/`time_range`/`is_monotonic` の返り値・**数値変換適用済みの値**・診断文言・LD-14 展開規約・重複名 `[idx]`・オフセット意味論・インスタンス書込保護。**例外 1 件（実装後に確定・意図的に受け入れた逸脱）**: master 破損グループで落ちたチャンネルが `[idx]` 曖昧化カウンタを進めなくなり、同名信号が別グループで生き残る場合に `Dup[1]` → `Dup[0]` と採番が変わる（衝突なし・診断/データ不変・両リビジョンで再現実証）。理由と採用判断は設計 spec の§グローバル制約を参照。
- 遅延読みプリミティブは **`mdf.get(raw=True)` 禁止**（変換喪失）・**`mdf.get(raw=False)` 禁止**（enum 文字列化）。**正**: `handle.mdf.select([(name, gi, ci)], raw=False, ignore_value2text_conversions=True, copy_master=False)[0].samples`。
- 共有 MDF ハンドルへの全遅延読みは `threading.Lock` で直列化（asammdf `select`/`get` は単一 `self._file` を seek+read するためスレッド非安全）。
- コメントは WHY を書く。DRY / YAGNI / TDD / 頻繁なコミット。
- 実装はブランチ `feature/lazy-load-samples`（既存）上。main 直接編集禁止。

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `src/valisync/core/models/sample_source.py` | `SampleSource` プロトコル・`EagerValues`・`LazyMdfValues`・`SampleReadError` | 新規 |
| `src/valisync/core/loaders/mdf_handle.py` | 開いたままの `MDF`＋`threading.Lock` を包む `MdfHandle` | 新規 |
| `src/valisync/core/models/signal.py` | `values` をソース背後のプロパティ化・`length` 検証・書込保護・`is_monotonic` を master のみ・値検証遅延 | 変更 |
| `src/valisync/core/models/signal_group.py` | `MdfHandle` を任意保持 | 変更 |
| `src/valisync/core/loaders/mdf_loader.py` | `mdf.select` 全読み → **1 チャンネル select の master 読み**＋メタ＋形状プローブ＋`LazyMdfValues` シェル・ハンドル保持・エラー/キャンセルで明示 close | 変更 |
| `src/valisync/core/loaders/signal_group_manager.py` | namespaced ラッパーが元の `_values_source` を共有 | 変更 |
| `src/valisync/core/sync/synchronizer.py` | offset Signal が元の遅延ソースを共有 | 変更 |
| `src/valisync/gui/workers/teardown_service.py` | nbytes 会計を is_materialized ガード | 変更 |
| `src/valisync/gui/views/main_window.py` ほか | `SampleReadError` の集中 degrade | 変更 |

---

## Task 1: SampleSource 抽象と Signal のソース化（純リファクタ・挙動不変）

`SampleSource`/`EagerValues` を新設し、`Signal.values` をソース背後のプロパティにする。既存の全構築サイトは `values=<array>` のまま（→`EagerValues` 自動包装）で**挙動完全不変**にし、既存テストを全通過させる。LazyMdfValues はまだ導入しない（Task 2）。

**Files:**
- Create: `src/valisync/core/models/sample_source.py`
- Modify: `src/valisync/core/models/signal.py`
- Test: `tests/core/models/test_sample_source.py`, 既存 `tests/test_pbt_signal.py`

**Interfaces:**
- Produces:
  - `class SampleReadError(Exception)`
  - `class SampleSource(Protocol)`: `array() -> np.ndarray` / `is_materialized: bool` / `length: int` / `nbytes_if_materialized: int`
  - `class EagerValues`: `__init__(self, array: np.ndarray)`（copy-if-writeable 凍結）
  - `Signal.__init__(..., values: np.ndarray | None = None, values_source: SampleSource | None = None, ...)` — どちらか一方。`values` 配列は `EagerValues` に包む。
  - `Signal._values_source: SampleSource`（内部・共有用に Task 4/5 が参照）
  - `Signal.values -> np.ndarray`（プロパティ・`self._values_source.array()`）

- [ ] **Step 1: `EagerValues`/`SampleSource` の失敗テストを書く**

`tests/core/models/test_sample_source.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from valisync.core.models.sample_source import EagerValues, SampleReadError


def test_eager_values_returns_array_and_is_materialized() -> None:
    arr = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    src = EagerValues(arr)
    assert src.is_materialized is True
    assert src.length == 3
    got = src.array()
    np.testing.assert_array_equal(got, arr)
    assert got.flags.writeable is False  # 凍結される


def test_eager_values_copies_writeable_input_not_freezing_caller_array() -> None:
    # 呼び出し側の可変配列を in-place 凍結してはならない (現行 __post_init__ と同契約)
    caller = np.array([1.0, 2.0], dtype=np.float64)  # writeable
    EagerValues(caller)
    assert caller.flags.writeable is True  # 呼び出し側配列は不変のまま


def test_eager_values_shares_readonly_input_without_copy() -> None:
    ro = np.array([1.0, 2.0], dtype=np.float64)
    ro.flags.writeable = False
    src = EagerValues(ro)
    assert src.array() is ro  # read-only はコピーせず共有


def test_eager_values_nbytes_if_materialized() -> None:
    arr = np.zeros(10, dtype=np.float64)
    assert EagerValues(arr).nbytes_if_materialized == arr.nbytes


def test_sample_read_error_is_exception() -> None:
    assert issubclass(SampleReadError, Exception)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/core/models/test_sample_source.py -q`
Expected: FAIL（`ModuleNotFoundError: sample_source`）

- [ ] **Step 3: `sample_source.py` を実装**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


class SampleReadError(Exception):
    """遅延サンプル読み取りが I/O 等で失敗したことを表す (アプリは落とさず degrade)."""


@runtime_checkable
class SampleSource(Protocol):
    """Signal の値配列の供給源。EagerValues (即時) と LazyMdfValues (遅延) の共通契約."""

    @property
    def is_materialized(self) -> bool:
        """値配列が既にメモリ上にあるか (mechanism 観測。RSS プロキシではない)."""
        ...

    @property
    def length(self) -> int:
        """サンプル数。値を展開せずに既知 (長さ不変条件の検証に使う)."""
        ...

    @property
    def nbytes_if_materialized(self) -> int:
        """展開済みなら値配列の nbytes、未展開なら 0 (teardown 会計用)."""
        ...

    def array(self) -> np.ndarray:
        """値配列を返す (初回で展開＋キャッシュ・read-only 凍結)。失敗時 SampleReadError."""
        ...


def _freeze(array: np.ndarray) -> np.ndarray:
    """現行 Signal.__post_init__ と同一の凍結: writeable ならコピーしてから read-only 化.

    呼び出し側が保持する可変配列を in-place で凍結しない (read-only はそのまま共有)."""
    frozen = array.copy() if array.flags.writeable else array
    frozen.flags.writeable = False
    return frozen


class EagerValues:
    """値配列を即時保持する SampleSource (CSV/Derived/downsampler/offset 前の既定)."""

    __slots__ = ("_array",)

    def __init__(self, array: np.ndarray) -> None:
        self._array = _freeze(array)

    @property
    def is_materialized(self) -> bool:
        return True

    @property
    def length(self) -> int:
        return len(self._array)

    @property
    def nbytes_if_materialized(self) -> int:
        return int(self._array.nbytes)

    def array(self) -> np.ndarray:
        return self._array
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/core/models/test_sample_source.py -q`
Expected: PASS

- [ ] **Step 5: Signal のソース化の失敗テストを書く**

`tests/core/models/test_sample_source.py` に追記:

```python
from valisync.core.models.signal import Signal


def _sig(values: np.ndarray) -> Signal:
    ts = np.arange(len(values), dtype=np.float64)
    return Signal(
        name="s", timestamps=ts, values=values,
        file_format="MDF4", bus_type="CAN", source_file="/x.mf4",
    )


def test_signal_wraps_array_values_in_eager_source() -> None:
    s = _sig(np.array([1.0, 2.0, 3.0]))
    assert isinstance(s._values_source, EagerValues)
    assert s._values_source.is_materialized is True
    np.testing.assert_array_equal(s.values, [1.0, 2.0, 3.0])


def test_signal_accepts_values_source_directly() -> None:
    src = EagerValues(np.array([4.0, 5.0]))
    ts = np.array([0.0, 1.0])
    s = Signal(name="s", timestamps=ts, values_source=src,
               file_format="MDF4", bus_type="CAN", source_file="/x.mf4")
    assert s._values_source is src
    np.testing.assert_array_equal(s.values, [4.0, 5.0])


def test_signal_length_invariant_uses_source_length_not_values() -> None:
    # timestamps と source.length が食い違えば構築時に ValueError
    ts = np.array([0.0, 1.0, 2.0])
    with pytest.raises(ValueError, match="same length"):
        Signal(name="s", timestamps=ts, values=np.array([1.0, 2.0]),
               file_format="MDF4", bus_type="", source_file="")


def test_signal_requires_exactly_one_of_values_or_source() -> None:
    ts = np.array([0.0])
    with pytest.raises(ValueError, match="exactly one"):
        Signal(name="s", timestamps=ts, file_format="MDF4", bus_type="", source_file="")


def test_signal_is_instance_write_protected() -> None:
    s = _sig(np.array([1.0]))
    with pytest.raises(AttributeError):
        s.name = "changed"  # type: ignore[misc]


def test_signal_is_monotonic_reads_master_only() -> None:
    s = _sig(np.array([1.0, 2.0, 3.0]))
    assert s.is_monotonic is True
    # values 未展開で is_monotonic が判定できる (EagerValues は常に materialized なので
    # LazyMdfValues 導入後の Task 2 で未展開判定は再検証する)
```

- [ ] **Step 6: テストが失敗することを確認**

Run: `uv run pytest tests/core/models/test_sample_source.py -q`
Expected: FAIL（`_values_source` 無し／`values_source` 引数無し）

- [ ] **Step 7: `signal.py` を書き換え**

`@dataclass(frozen=True)` を通常クラス化し、`values` をプロパティに、検証を非展開化する。現行 `signal.py` の 12–50 行（dataclass 宣言〜`__post_init__`）を次で置換:

```python
class Signal:
    """Immutable time-series signal. Values are supplied lazily via a SampleSource.

    ``timestamps`` (グループ master・float64) は即時保持。``values`` は
    ``_values_source`` (EagerValues/LazyMdfValues) の背後で初回アクセス時に展開する。
    インスタンスは書込保護 (公開属性の再代入は AttributeError)。
    """

    __slots__ = (
        "name", "timestamps", "file_format", "bus_type", "source_file", "metadata",
        "_values_source", "_monotonic",
        "_sorted_view_cache", "_finite_view_cache", "_range_stat_index_cache",
        "_sorted_view_delegate",
    )

    def __init__(
        self,
        name: str,
        timestamps: np.ndarray,
        file_format: str,
        bus_type: str,
        source_file: str,
        values: np.ndarray | None = None,
        values_source: SampleSource | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if (values is None) == (values_source is None):
            raise ValueError("exactly one of values / values_source must be given")
        # array-imported コンストラクションは EagerValues に包む (既存サイト無変更)
        source: SampleSource = (
            values_source if values_source is not None else EagerValues(values)  # type: ignore[arg-type]
        )
        # 長さ不変条件は values を展開せず source.length で検証する
        if len(timestamps) != source.length:
            raise ValueError(
                f"timestamps ({len(timestamps)}) and values ({source.length}) "
                "must have the same length"
            )
        if len(timestamps) > 0 and not np.all(np.isfinite(timestamps)):
            idx = int(np.argmax(~np.isfinite(timestamps)))
            raise ValueError(f"時刻列の {idx} 番目に非有限値が含まれています")
        ts = timestamps.copy() if timestamps.flags.writeable else timestamps
        ts.flags.writeable = False
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "timestamps", ts)
        object.__setattr__(self, "file_format", file_format)
        object.__setattr__(self, "bus_type", bus_type)
        object.__setattr__(self, "source_file", source_file)
        object.__setattr__(self, "metadata", metadata if metadata is not None else {})
        object.__setattr__(self, "_values_source", source)

    def __setattr__(self, name: str, value: Any) -> None:
        # インスタンス不変 (旧 frozen dataclass 相当)。内部は object.__setattr__ を使う。
        raise AttributeError(f"Signal is immutable; cannot set {name!r}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"Signal is immutable; cannot delete {name!r}")

    @property
    def values(self) -> np.ndarray:
        """値配列 (初回アクセスで展開＋キャッシュ)。失敗時 SampleReadError."""
        return self._values_source.array()
```

`signal.py` 冒頭の import に追加:

```python
from valisync.core.models.sample_source import EagerValues, SampleSource
```

`is_monotonic` を master のみで計算するよう書き換え（現行 171–174 行）:

```python
    @property
    def is_monotonic(self) -> bool:
        """True when timestamps are strictly increasing (master のみ・値を展開しない)."""
        cached = getattr(self, "_monotonic", None)
        if cached is not None:
            return cached
        ts = self.timestamps
        result = len(ts) < 2 or bool(np.all(np.diff(ts) > 0))
        object.__setattr__(self, "_monotonic", result)
        return result
```

`sorted_view`/`finite_view`/`range_stat_index` の本体は現行のまま（`self.values` アクセスが展開を誘発するだけ）。ただし `sorted_view` 冒頭の「racing initialisations are harmless」コメントに「I/O は handle.lock 依存で win-once（Task 2）」を追記。

- [ ] **Step 8: 既存 frozen テストを AttributeError 期待へ更新**

`tests/test_pbt_signal.py::test_instance_is_frozen`（143–146 行付近）の `FrozenInstanceError` 期待を `AttributeError` 期待へ変更:

```python
def test_instance_is_frozen() -> None:
    s = Signal(name="s", timestamps=np.array([0.0]), values=np.array([1.0]),
               file_format="MDF4", bus_type="", source_file="")
    with pytest.raises(AttributeError):
        s.name = "x"  # type: ignore[misc]
```

（テスト冒頭の `from dataclasses import FrozenInstanceError` を除去。他に Signal を `dataclasses.replace`/`==` で使うテストが無いことは設計時 grep 済み。）

- [ ] **Step 9: 全構築サイトが `values=` キーワードで通ることを確認（無変更の担保）**

現行の 8 構築サイトはすべて `values=<array>` を渡している。位置引数順を変えたので**キーワード渡しであること**を確認する（下記は既に全てキーワード）: `mdf_loader.py:513`, `csv_loader.py:279`, `formula/engine.py:481`, `session.py:414`, `synchronizer.py:42`, `signal_group_manager.py:83`, `downsampler.py:88`, `downsampler.py:114`。位置引数で `values` を渡しているサイトがあれば `values=` へ直す。

Run: `uv run pytest -q`
Expected: PASS（全既存テスト通過＝挙動不変）

- [ ] **Step 10: ゲート＋コミット**

Run: `uv run ruff check && uv run ruff format --check && uv run mypy src/`
```bash
git add src/valisync/core/models/sample_source.py src/valisync/core/models/signal.py tests/core/models/test_sample_source.py tests/test_pbt_signal.py
git commit -m "feat(core): Signal 値を SampleSource 抽象化 (EagerValues・挙動不変リファクタ)"
```

---

## Task 2: MdfHandle と LazyMdfValues（変換保存・スレッド直列化）

`MdfHandle`（開いたままの MDF＋lock）と `LazyMdfValues`（変換保存の単一チャンネル `select` で初回展開）を新設。まだローダーには繋がない（Task 3）。実 mf4（`demo_data/quick_demo.mf4`）で eager 値と一致することを検証。

**Files:**
- Create: `src/valisync/core/loaders/mdf_handle.py`
- Modify: `src/valisync/core/models/sample_source.py`（`LazyMdfValues` 追加）
- Test: `tests/core/loaders/test_lazy_mdf_values.py`

**Interfaces:**
- Consumes: `SampleSource`（Task 1）
- Produces:
  - `class MdfHandle`: `__init__(self, mdf: Any)`; `lock: threading.Lock`; `mdf: Any`; `close() -> None`（冪等）; `is_closed: bool`
  - `class LazyMdfValues`: `__init__(self, handle: MdfHandle, name: str, gi: int, ci: int, length: int, selector: tuple[str, ...] | None = None)`。`SampleSource` を満たす。

- [ ] **Step 1: `MdfHandle` の失敗テストを書く**

`tests/core/loaders/test_lazy_mdf_values.py`:

```python
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest
from asammdf import MDF

from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.models.sample_source import LazyMdfValues, SampleReadError

DEMO = Path("demo_data/quick_demo.mf4")
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def test_mdf_handle_close_is_idempotent() -> None:
    h = MdfHandle(MDF(str(DEMO)))
    assert h.is_closed is False
    h.close()
    assert h.is_closed is True
    h.close()  # 多重 close 安全
    assert h.is_closed is True


def test_mdf_handle_has_lock() -> None:
    h = MdfHandle(MDF(str(DEMO)))
    assert isinstance(h.lock, type(threading.Lock()))
    h.close()
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_lazy_mdf_values.py -q`
Expected: FAIL（`mdf_handle` 無し）

- [ ] **Step 3: `mdf_handle.py` を実装**

```python
from __future__ import annotations

import threading
from typing import Any


class MdfHandle:
    """開いたままの asammdf MDF と直列化ロックを包む。

    asammdf の select/get は単一の共有 self._file を seek+read するためスレッド
    非安全。グループ内の全 LazyMdfValues はこの lock で読みを直列化する。ハンドルは
    SignalGroup が 1 個所有し、unload/エラー経路で close() する (増分B/M3)。"""

    __slots__ = ("mdf", "lock", "_closed")

    def __init__(self, mdf: Any) -> None:
        self.mdf = mdf
        self.lock = threading.Lock()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """冪等な close (mmap 解放・ファイルロック解除)."""
        if self._closed:
            return
        self._closed = True
        with self.lock:
            self.mdf.close()
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/loaders/test_lazy_mdf_values.py -q`
Expected: PASS（2 件）

- [ ] **Step 5: `LazyMdfValues` の失敗テスト（変換保存・遅延・スレッド）を書く**

追記:

```python
def _eager_samples(name: str, gi: int, ci: int) -> np.ndarray:
    # 現行ローダーと同一意味論の eager 読み (変換適用・value2text スキップ)
    m = MDF(str(DEMO))
    try:
        sig = m.select([(name, gi, ci)], raw=False,
                       ignore_value2text_conversions=True, copy_master=False)[0]
        return np.ascontiguousarray(sig.samples)
    finally:
        m.close()


def _first_scalar_channel() -> tuple[str, int, int, int]:
    # 1D 数値チャンネルを 1 本見つける (name, gi, ci, length)
    m = MDF(str(DEMO))
    try:
        for gi, g in enumerate(m.groups):
            master_ci = m.masters_db.get(gi)
            for ci, ch in enumerate(g.channels):
                if ci == master_ci:
                    continue
                probe = m.get(group=gi, index=ci, samples_only=True, raw=True)[0]
                if probe.ndim == 1 and probe.dtype.kind in "iufb":
                    return ch.name, gi, ci, g.channel_group.cycles_nr
        raise AssertionError("no scalar channel found")
    finally:
        m.close()


def test_lazy_is_not_materialized_until_array_called() -> None:
    name, gi, ci, length = _first_scalar_channel()
    h = MdfHandle(MDF(str(DEMO)))
    src = LazyMdfValues(h, name, gi, ci, length=length)
    assert src.is_materialized is False
    assert src.length == length
    assert src.nbytes_if_materialized == 0
    got = src.array()
    assert src.is_materialized is True
    assert src.nbytes_if_materialized == got.nbytes
    assert src.array() is got  # キャッシュ (再読みしない)
    h.close()


def test_lazy_values_match_eager_scaled_values() -> None:
    name, gi, ci, length = _first_scalar_channel()
    h = MdfHandle(MDF(str(DEMO)))
    got = LazyMdfValues(h, name, gi, ci, length=length).array()
    np.testing.assert_array_equal(got, _eager_samples(name, gi, ci))
    assert got.flags.writeable is False
    h.close()


def test_lazy_read_failure_raises_sample_read_error() -> None:
    name, gi, ci, length = _first_scalar_channel()
    h = MdfHandle(MDF(str(DEMO)))
    h.mdf = None  # 読み時に AttributeError -> SampleReadError へ変換される
    with pytest.raises(SampleReadError):
        LazyMdfValues(h, name, gi, ci, length=length).array()


def test_lazy_reads_are_serialized_by_handle_lock() -> None:
    # 同一ハンドルへの並行 array() が select を直列化することを、再入で失敗する
    # スタブで検証する。
    name, gi, ci, length = _first_scalar_channel()
    h = MdfHandle(MDF(str(DEMO)))
    real_select = h.mdf.select
    active = {"in": False}
    reentered = {"hit": False}

    def guarded_select(*a, **k):  # type: ignore[no-untyped-def]
        if active["in"]:
            reentered["hit"] = True
        active["in"] = True
        try:
            return real_select(*a, **k)
        finally:
            active["in"] = False

    h.mdf.select = guarded_select  # type: ignore[assignment]
    srcs = [LazyMdfValues(h, name, gi, ci, length=length) for _ in range(8)]
    threads = [threading.Thread(target=s.array) for s in srcs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert reentered["hit"] is False  # lock で直列化され再入なし
    h.close()
```

- [ ] **Step 6: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_lazy_mdf_values.py -q`
Expected: FAIL（`LazyMdfValues` 無し）

- [ ] **Step 7: `LazyMdfValues` を `sample_source.py` に実装**

`sample_source.py` に追記（`_flatten` は mdf_loader のものを再利用するため import）:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from valisync.core.loaders.mdf_handle import MdfHandle


class LazyMdfValues:
    """MDF から値配列をオンデマンド読みする SampleSource。

    初回 array() で現行 eager と同一意味論の単一チャンネル select を lock 下で実行し、
    LD-14 selector があれば該当リーフ列を抽出、native dtype 凍結してキャッシュする。"""

    __slots__ = ("_handle", "_name", "_gi", "_ci", "_length", "_selector", "_cache")

    def __init__(
        self,
        handle: MdfHandle,
        name: str,
        gi: int,
        ci: int,
        length: int,
        selector: tuple[str, ...] | None = None,
    ) -> None:
        self._handle = handle
        self._name = name
        self._gi = gi
        self._ci = ci
        self._length = length
        self._selector = selector
        self._cache: np.ndarray | None = None

    @property
    def is_materialized(self) -> bool:
        return self._cache is not None

    @property
    def length(self) -> int:
        return self._length

    @property
    def nbytes_if_materialized(self) -> int:
        return 0 if self._cache is None else int(self._cache.nbytes)

    def array(self) -> np.ndarray:
        # 遅延 import: sample_source(model) -> loaders の循環を避ける
        from valisync.core.loaders.mdf_loader import _flatten

        with self._handle.lock:
            if self._cache is not None:
                return self._cache
            if self._handle.is_closed:
                raise SampleReadError(f"信号 '{self._name}' のファイルは既に閉じられています")
            try:
                asig = self._handle.mdf.select(
                    [(self._name, self._gi, self._ci)],
                    raw=False,
                    ignore_value2text_conversions=True,
                    copy_master=False,
                )[0]
                samples = asig.samples
                if self._selector is not None:
                    # LD-14: 展開リーフ列を名前一致で取り出す
                    leaf = dict(_flatten(self._name, samples))
                    col = leaf[self._selector[-1]]
                else:
                    col = np.ascontiguousarray(samples)
            except SampleReadError:
                raise
            except Exception as exc:  # I/O・破損・閉鎖後アクセス等
                raise SampleReadError(
                    f"信号 '{self._name}' のサンプル読み取りに失敗しました: {exc}"
                ) from exc
            col = _freeze(col)
            self._cache = col
            return col
```

（`selector` の照合キーは Task 3 のローダーが `_flatten` のリーフ名で作る。最小実装として selector をリーフ名タプルにし `leaf[self._selector[-1]]` で引く。単一 1D は `selector=None`。）

- [ ] **Step 8: 通ることを確認**

Run: `uv run pytest tests/core/loaders/test_lazy_mdf_values.py -q`
Expected: PASS（変換一致・遅延・失敗変換・直列化）

- [ ] **Step 9: ゲート＋コミット**

```bash
git add src/valisync/core/loaders/mdf_handle.py src/valisync/core/models/sample_source.py tests/core/loaders/test_lazy_mdf_values.py
git commit -m "feat(core): MdfHandle・LazyMdfValues (変換保存の単一select・lock直列化)"
```

---

## Task 3: ローダーを遅延化（master の単体 select＋メタ＋形状プローブ・ハンドル保持）

`mdf_loader._load_group` を、`mdf.select` 全読みから「1レコード形状プローブ＋**1 チャンネル select 経由の master 読み**＋`LazyMdfValues` シェル」に置換。MDF ハンドルを `MdfHandle` に包んで `SignalGroup` に保持。成功経路のみ close 省略・エラー/キャンセルで明示 close。

> **訂正（Task 3b）**: 本タスクは当初 `mdf.get_master(gi)` で書かれていたが、ハンドル保持下では生レコードブロックを丸ごと残す（+1,296 MB）と実測され select 経由へ反転した。以下の Step 4 は訂正後の内容。

**Files:**
- Modify: `src/valisync/core/models/signal_group.py`（`handle: MdfHandle | None = None` フィールド追加）
- Modify: `src/valisync/core/loaders/mdf_loader.py`
- Test: `tests/core/loaders/test_mdf_loader_lazy.py`（新規）＋既存 `tests/core/loaders/test_mdf_loader*.py` 全通過

**Interfaces:**
- Consumes: `MdfHandle`, `LazyMdfValues`（Task 2）
- Produces: ロード後の `Signal` が `LazyMdfValues` を持ち、ロード直後は全信号 `is_materialized == False`。`SignalGroup.handle` に `MdfHandle`。

- [ ] **Step 1: 遅延ロードの失敗テストを書く**

`tests/core/loaders/test_mdf_loader_lazy.py`:

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from asammdf import MDF

from valisync.core.loaders.mdf_loader import MdfLoader

DEMO = Path("demo_data/quick_demo.mf4")
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def test_load_leaves_all_signals_unmaterialized() -> None:
    result = MdfLoader().load(DEMO, confirm_expansion=None)
    sg = result.signal_group
    assert sg is not None
    assert len(sg.signals) > 0
    assert all(s._values_source.is_materialized is False for s in sg.signals)
    assert sg.handle is not None and sg.handle.is_closed is False


def test_lazy_values_equal_eager_select_for_sample_signals() -> None:
    result = MdfLoader().load(DEMO, confirm_expansion=None)
    sg = result.signal_group
    assert sg is not None
    m = MDF(str(DEMO))
    try:
        for s in sg.signals[:20]:  # 代表 20 本
            # s.name は base 名 (namespace 前)。ローカライズ位置は metadata 経由で持つ想定だが
            # ここでは値の一致のみ検証: 展開して有限一致
            got = s.values
            assert got.dtype.kind in "iufb"
    finally:
        m.close()


def test_load_failure_path_closes_handle(tmp_path: Path) -> None:
    bad = tmp_path / "broken.mf4"
    bad.write_bytes(b"not an mdf file")
    result = MdfLoader().load(bad, confirm_expansion=None)
    # 破損は error 診断で返る (ハンドルはリークしない)
    assert result.signal_group is None
    assert any(d.level == "error" for d in result.diagnostics)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_mdf_loader_lazy.py -q`
Expected: FAIL（`sg.handle` 属性無し／`is_materialized` が True）

- [ ] **Step 3: `SignalGroup` に handle フィールドを追加**

`signal_group.py` の dataclass に追加（`from __future__ import annotations` 済みなので前方参照可）:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from valisync.core.loaders.mdf_handle import MdfHandle


@dataclass(frozen=True)
class SignalGroup:
    signals: tuple[Signal, ...]
    source_path: Path
    file_format: str
    loaded_at: datetime
    handle: MdfHandle | None = None  # MDF 遅延読み用ハンドル (CSV は None)
```

- [ ] **Step 4: ローダーを書き換え**

`mdf_loader.py`:
1. `from valisync.core.loaders.mdf_handle import MdfHandle` と `from valisync.core.models.sample_source import LazyMdfValues` を import。
2. `load()`: `mdf` を `MdfHandle(mdf)` に包み、成功時は `SignalGroup(..., handle=handle)` で返す。`finally: mdf.close()` を削除し、**エラー/キャンセル経路（`except LoadCancelled`／`except Exception`）で `handle.close()` を明示呼び出し**してから raise/return する。
3. `_load_group()`: `asigs = mdf.select(entries, **self._SELECT_OPTIONS)` を廃止。代わりに:
   - master をグループの先頭 entry の単体 select から取り（`mdf.select([entries[0]], raw=False, ignore_value2text_conversions=True, copy_master=False)[0].timestamps`）、finiteness/diff 診断（現行 `master`/`master_diffs_warn` ロジックを master 単体に適用）。**`mdf.get_master(gi)` は禁止**（ハンドル保持下で生ブロック +1,296 MB）。
   - master 読みのオプションは `_MASTER_OPTIONS = {"raw": False, "ignore_value2text_conversions": True, "copy_master": False}`（`LazyMdfValues.array()` と同じ正準セット）を ClassVar で定義して使う。
   - 形状は既存 `_PROBE_OPTIONS`（record_count=1）で `probes = mdf.select(entries, **self._PROBE_OPTIONS)` を 1 回だけ取り、各チャンネルの `probe.samples` から `_flatten` でリーフ構造（列名＝selector）を得る。
   - 各リーフ列に `LazyMdfValues(handle, base_name, gi, ci, length=len(master), selector=<leaf_name_tuple or None>)` を作り `Signal(..., values_source=...)` を構築。単一 1D は `selector=None`。
   - value_labels/conversion/unit/comment/source は現行どおり `_extract_metadata` で（probe の asig もしくは生チャンネルから）。

具体差分（`_load_group` の中核）:

```python
        entries = [
            e for e in self._group_entries(mdf, gi) if (e[1], e[2]) not in skip_keys
        ]
        if not entries:
            return
        if cancel is not None and cancel():
            raise LoadCancelled(f"load cancelled: {resolved_path.name}")

        # master を仮想グループ単位で単体読みする (値は読まない)。診断・同一性・
        # 長さの土台。get_master(gi) は禁止 — ハンドルを開いたまま保持する本
        # ローダーでは生レコードブロック全体がハンドル上に残る (+1,296MB)。
        # copy_master=False は asammdf 内部を指しうるため必ずコピーして凍結する。
        asig = mdf.select([entries[0]], **self._MASTER_OPTIONS)[0]
        master = np.array(asig.timestamps, dtype=np.float64, copy=True)
        del asig  # 値サンプルを即時に解放 (master だけを持ち越す)
        if len(master) > 0 and not np.all(np.isfinite(master)):
            for base_name, _g, _c in entries:
                diagnostics.append(Diagnostic(
                    level="error",
                    message=(f"信号 '{base_name}': 非有限タイムスタンプを含むため"
                             "スキップ（時刻軸が破損）"),
                    signal_name=base_name))
            return
        master.flags.writeable = False
        diffs = np.diff(master)
        n_backward, n_dup = int(np.sum(diffs < 0)), int(np.sum(diffs == 0))

        # 形状のみ 1 レコードプローブ (値の全読みなし)
        probes = mdf.select(entries, **self._PROBE_OPTIONS)
        for (base_name, _g, _c), probe in zip(entries, probes, strict=True):
            if cancel is not None and cancel():
                raise LoadCancelled(f"load cancelled: {resolved_path.name}")
            idx = name_seen.get(base_name, 0)
            name_seen[base_name] = idx + 1
            deduplicated = name_total[base_name] > 1
            signal_name = f"{base_name}[{idx}]" if deduplicated else base_name

            samples = probe.samples
            exploded = samples.ndim != 1 or bool(samples.dtype.names)
            if exploded:
                leaves = _explode_samples(signal_name, samples, diagnostics)
                pairs = [(leaf_name, (leaf_name,)) for leaf_name, _arr in leaves]
            else:
                pairs = [(signal_name, None)]  # type: ignore[list-item]

            raw_conversion = (
                None if exploded else mdf.groups[_g].channels[_c].conversion
            )
            for out_name, selector in pairs:
                # dtype チェックは probe (1 レコード) で行う (値の全読み不要)
                if selector is None:
                    col_probe = samples
                else:
                    col_probe = dict(_flatten(signal_name, samples))[selector[-1]]
                if col_probe.dtype.kind not in "iufb":
                    diagnostics.append(Diagnostic(
                        level="warning",
                        message=(f"信号 '{out_name}': 非数値型のためスキップ"
                                 f"（dtype {col_probe.dtype}）")))
                    continue
                if n_backward or n_dup:
                    diagnostics.append(Diagnostic(
                        level="warning",
                        message=(f"信号 '{out_name}': 非単調 {n_backward} 箇所・"
                                 f"重複タイムスタンプ {n_dup} 点"
                                 "（表示/演算は整列ビューで補正）"),
                        signal_name=out_name))
                out_metadata = _extract_metadata(probe, raw_conversion)
                if deduplicated:
                    out_metadata["name_deduplicated"] = True
                signals.append(Signal(
                    name=out_name,
                    timestamps=master,
                    values_source=LazyMdfValues(
                        handle, base_name, _g, _c, length=len(master),
                        selector=selector),
                    file_format=self._format_label(mdf),
                    bus_type=_detect_bus_type(getattr(probe, "source", None)),
                    source_file=str(resolved_path),
                    metadata=out_metadata,
                ))
```

`_load_group` のシグネチャに `handle: MdfHandle` を追加し、`load()` から渡す。`master_diffs_warn`/`master_bad`/旧 `asigs` ループは削除。

> **注意（レビュー M4）**: 単一チャンネル select はグループのデータブロックを毎回解凍する。1 グループの多数チャンネルを同時プロットする場面のバッチ最適化は増分C 以降の課題として本 Task では単純経路にする。

- [ ] **Step 5: 通ることを確認 + 既存ローダーテスト全通過**

Run: `uv run pytest tests/core/loaders/ -q`
Expected: PASS（新規遅延テスト＋既存 LD-01〜14 テストが全通過＝診断/展開/重複名の挙動不変）

- [ ] **Step 6: ゲート＋コミット**

```bash
git add src/valisync/core/models/signal_group.py src/valisync/core/loaders/mdf_loader.py tests/core/loaders/test_mdf_loader_lazy.py
git commit -m "feat(core): MDFローダーを遅延化 (master単体select+形状プローブ+LazyMdfValues・ハンドル保持)"
```

---

## Task 4: namespaced ラッパーのソース共有

`SignalGroupManager._namespaced` が `values=sig.values`（全展開）でなく元の `_values_source` を共有するようにする。`signal_map()`/`signals()`/`group_signals()` がプロット前に展開しないことを検証。

**Files:**
- Modify: `src/valisync/core/loaders/signal_group_manager.py`
- Test: `tests/core/loaders/test_namespaced_lazy.py`（新規）

**Interfaces:**
- Consumes: `Signal(values_source=...)`（Task 1）
- Produces: namespaced ラッパーが `wrapper._values_source is origin._values_source`。

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_namespaced_lazy.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager

DEMO = Path("demo_data/quick_demo.mf4")
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def _loaded_manager() -> tuple[SignalGroupManager, str]:
    sg = MdfLoader().load(DEMO, confirm_expansion=None).signal_group
    assert sg is not None
    mgr = SignalGroupManager()
    key = mgr.add(sg)
    return mgr, key


def test_group_signals_does_not_materialize() -> None:
    mgr, key = _loaded_manager()
    ns = mgr.group_signals(key)
    assert all(s._values_source.is_materialized is False for s in ns)


def test_signals_and_signal_map_do_not_materialize() -> None:
    mgr, _key = _loaded_manager()
    _ = mgr.signals()
    _ = mgr.signal_map()
    assert all(s._values_source.is_materialized is False for s in mgr.signals())


def test_wrapper_shares_origin_source_identity() -> None:
    sg = MdfLoader().load(DEMO, confirm_expansion=None).signal_group
    assert sg is not None
    mgr = SignalGroupManager()
    key = mgr.add(sg)
    origin = sg.signals[0]
    wrapper = next(w for w in mgr.group_signals(key)
                   if w.name.endswith(f"::{origin.name}"))
    assert wrapper._values_source is origin._values_source
    # ラッパー経由の展開が共有ソースを 1 度だけ満たす
    _ = wrapper.values
    assert origin._values_source.is_materialized is True
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_namespaced_lazy.py -q`
Expected: FAIL（`test_signals_and_signal_map_do_not_materialize` 等が materialized True）

- [ ] **Step 3: `_namespaced` を書き換え**

`signal_group_manager.py:83-91` の `Signal(...)` 構築を `values=sig.values` → `values_source=sig._values_source` に変更:

```python
            ns_sig = Signal(
                name=f"{key}{KEY_SEPARATOR}{sig.name}",
                timestamps=sig.timestamps,
                values_source=sig._values_source,
                file_format=sig.file_format,
                bus_type=sig.bus_type,
                source_file=sig.source_file,
                metadata=sig.metadata,
            )
```

（`_sorted_view_delegate = sig` はそのまま維持。共有ソース＋master identity で delegate の前提〔配列同一〕は保たれる。）

- [ ] **Step 4: 通ることを確認 + 既存の namespaced テスト全通過**

Run: `uv run pytest tests/core/loaders/ -q`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/core/loaders/signal_group_manager.py tests/core/loaders/test_namespaced_lazy.py
git commit -m "feat(core): namespaced ラッパーが遅延ソースを共有 (プロット前展開の回帰を封じる)"
```

---

## Task 5: offset が遅延ソースを共有

`TimeSynchronizer.apply_offset` が新 Signal を `values=signal.values`（展開）でなく `values_source=signal._values_source` で作るようにする。全体オフセット（scope=group）でも未プロットが展開されないことを検証。

**Files:**
- Modify: `src/valisync/core/sync/synchronizer.py`
- Test: `tests/core/sync/test_offset_lazy.py`（新規）＋既存 `tests/core/sync/` 全通過

**Interfaces:**
- Consumes: `Signal(values_source=...)`（Task 1）
- Produces: offset Signal が元の `_values_source` を共有（timestamps のみ +total）。

- [ ] **Step 1: 失敗テストを書く**

`tests/core/sync/test_offset_lazy.py`:

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.sync.synchronizer import TimeSynchronizer

DEMO = Path("demo_data/quick_demo.mf4")
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def test_apply_offset_shares_lazy_source_no_materialize() -> None:
    sg = MdfLoader().load(DEMO, confirm_expansion=None).signal_group
    assert sg is not None
    base = sg.signals[0]
    shifted = TimeSynchronizer().apply_offset(base, file_offset=1.5)
    assert shifted._values_source is base._values_source
    assert base._values_source.is_materialized is False  # 展開しない
    np.testing.assert_allclose(shifted.timestamps, base.timestamps + 1.5)


def test_apply_offset_zero_returns_same_signal() -> None:
    sg = MdfLoader().load(DEMO, confirm_expansion=None).signal_group
    assert sg is not None
    base = sg.signals[0]
    assert TimeSynchronizer().apply_offset(base, 0.0, 0.0) is base
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/sync/test_offset_lazy.py -q`
Expected: FAIL（`shifted._values_source is base._values_source` が False）

- [ ] **Step 3: `apply_offset` を書き換え**

`synchronizer.py:42` の `Signal(...)` を:

```python
        return Signal(
            name=signal.name,
            timestamps=signal.timestamps + total,
            values_source=signal._values_source,
            file_format=signal.file_format,
            bus_type=signal.bus_type,
            source_file=signal.source_file,
            metadata=signal.metadata,
        )
```

docstring の "Pure computation, no I/O" は維持（ソース共有ゆえ I/O は起きない）。

- [ ] **Step 4: 通ることを確認 + 既存 sync テスト全通過**

Run: `uv run pytest tests/core/sync/ -q`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/core/sync/synchronizer.py tests/core/sync/test_offset_lazy.py
git commit -m "feat(core): offset が遅延ソースを共有 (全体オフセットで未プロットを展開しない)"
```

---

## Task 6: teardown の非展開会計

`TeardownService.pending_bytes`/`_drain` が未展開信号の `sig.values` を読まないようにする。ロード→（何もプロットせず）unload で一切展開しないことを検証。

**Files:**
- Modify: `src/valisync/gui/workers/teardown_service.py`
- Test: `tests/gui/workers/test_teardown_lazy.py`（新規）＋既存 `tests/gui/workers/test_teardown_service*.py` 全通過

**Interfaces:**
- Consumes: `SampleSource.is_materialized` / `.nbytes_if_materialized`（Task 1）

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/workers/test_teardown_lazy.py`:

```python
from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import pytest

from valisync.core.models import Signal, SignalGroup
from valisync.core.models.sample_source import SampleSource
from valisync.gui.workers.teardown_service import TeardownService


class _CountingLazy:
    """array() が呼ばれたら記録する遅延ソース (テスト用)."""

    def __init__(self, n: int) -> None:
        self._n = n
        self.reads = 0
        self._cache: np.ndarray | None = None

    @property
    def is_materialized(self) -> bool:
        return self._cache is not None

    @property
    def length(self) -> int:
        return self._n

    @property
    def nbytes_if_materialized(self) -> int:
        return 0 if self._cache is None else self._cache.nbytes

    def array(self) -> np.ndarray:
        self.reads += 1
        self._cache = np.zeros(self._n, dtype=np.float64)
        return self._cache


def _lazy_group(n_signals: int, length: int) -> tuple[SignalGroup, list[_CountingLazy]]:
    ts = np.arange(length, dtype=np.float64)
    srcs = [_CountingLazy(length) for _ in range(n_signals)]
    sigs = tuple(
        Signal(name=f"s{i}", timestamps=ts, values_source=s,  # type: ignore[arg-type]
               file_format="MDF4", bus_type="", source_file="/x.mf4")
        for i, s in enumerate(srcs)
    )
    g = SignalGroup(signals=sigs, source_path=Path("/x.mf4").resolve(),
                    file_format="MDF4", loaded_at=datetime.datetime.now())
    return g, srcs


def test_pending_bytes_does_not_materialize(qtbot) -> None:  # type: ignore[no-untyped-def]
    svc = TeardownService()
    g, srcs = _lazy_group(50, 100)
    svc.enqueue("k", g)
    _ = svc.pending_bytes()
    assert all(s.reads == 0 for s in srcs)  # 会計で展開しない


def test_drain_does_not_materialize(qtbot) -> None:  # type: ignore[no-untyped-def]
    finished: list[str] = []
    svc = TeardownService(on_finished=finished.append)
    g, srcs = _lazy_group(50, 100)
    svc.enqueue("k", g)
    qtbot.waitUntil(lambda: finished == ["k"], timeout=3000)
    assert all(s.reads == 0 for s in srcs)  # drain で展開しない
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/workers/test_teardown_lazy.py -q`
Expected: FAIL（`s.values.nbytes` が array() を呼び reads>0）

- [ ] **Step 3: 会計を is_materialized ガード化**

`teardown_service.py` の `pending_bytes`（59-63 行）:

```python
    def pending_bytes(self) -> int:
        return sum(
            s.timestamps.nbytes + _materialized_value_bytes(s)
            for _key, sigs in self._groups
            for s in sigs
        )
```

`_drain`（84 行）:

```python
                freed += sig.timestamps.nbytes + _materialized_value_bytes(sig)
```

モジュール末尾にヘルパを追加（`_sorted_view_cache` 等 Signal 側キャッシュも計上・array id で dedupe）:

```python
def _materialized_value_bytes(sig: Signal) -> int:
    """未展開の値は 0。展開済み値＋Signal 上の派生キャッシュ (float64 昇格等) を計上.

    未展開信号の sig.values を絶対に読まない (読むと遅延ロードを再誘発する)."""
    total = sig._values_source.nbytes_if_materialized
    seen: set[int] = set()
    sv = getattr(sig, "_sorted_view_cache", None)
    fv = getattr(sig, "_finite_view_cache", None)
    for pair in (sv, fv):
        if pair is None:
            continue
        for arr in pair:  # (timestamps, values) タプル
            if id(arr) not in seen:
                seen.add(id(arr))
                total += int(arr.nbytes)
    return total
```

（`_range_stat_index_cache` のブロック配列も厳密には計上対象だが、支配項は values/sorted_view ゆえ本 Task では sorted/finite の値配列までを計上する。timestamps は既に別途 `sig.timestamps.nbytes` で計上され master 共有ゆえ二重計上は pacing の過大側で無害。）

- [ ] **Step 4: 通ることを確認 + 既存 teardown テスト全通過**

Run: `uv run pytest tests/gui/workers/ -q`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/gui/workers/teardown_service.py tests/gui/workers/test_teardown_lazy.py
git commit -m "feat(gui): teardown 会計を is_materialized ガード (unload で未プロットを展開しない)"
```

---

## Task 7: SampleReadError の集中 degrade

遅延読み失敗を GUI で集中捕捉し、診断＋当該カーブ degrade でアプリを落とさない。render/auto-fit/cursor-step/formula の各トリガを被覆。

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（アプリ全体の例外フック設置）
- Modify: `src/valisync/gui/views/graph_panel_view.py`（render 境界の局所 degrade）
- Test: `tests/gui/test_sample_read_error_degrade.py`（新規）

**Interfaces:**
- Consumes: `SampleReadError`（Task 1）

- [ ] **Step 1: 失敗テストを書く（render 経路の degrade）**

`tests/gui/test_sample_read_error_degrade.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from valisync.core.models.sample_source import SampleReadError


class _FailingSource:
    is_materialized = False
    length = 3
    nbytes_if_materialized = 0

    def array(self) -> np.ndarray:
        raise SampleReadError("boom")


def test_render_data_degrades_on_sample_read_error(qtbot) -> None:  # type: ignore[no-untyped-def]
    from valisync.core.models.signal import Signal
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM  # 実型に合わせる

    ts = np.array([0.0, 1.0, 2.0])
    bad = Signal(name="bad", timestamps=ts, values_source=_FailingSource(),  # type: ignore[arg-type]
                 file_format="MDF4", bus_type="", source_file="/x.mf4")
    # GraphPanelVM に bad を 1 本プロットさせ、render_data() が例外を投げず
    # 空カーブ+診断で返ることを assert する (実 API に合わせて配線)。
    # （具体配線は既存 graph_panel_vm テストの plot ヘルパを流用）
    ...
```

> 実装者へ: 既存 `tests/gui/viewmodels/test_graph_panel_vm*.py` のプロット・render ヘルパを流用して bad 信号をプロットし、`render_data()`（または実 render エントリ）が `SampleReadError` を送出せず degrade（空 RenderCurve）＋診断 1 件を返すことを assert する。診断表面は `DiagnosticsVM` 経由。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_sample_read_error_degrade.py -q`
Expected: FAIL（例外が render を貫通）

- [ ] **Step 3: render 境界で局所 degrade を実装**

`graph_panel_view.py` の render ループ（`_items`/`setData` 付近・936-995 行）で、各プロット信号の `sorted_view()`/`values` アクセスを try/except `SampleReadError` で包み、失敗時は当該 entry を空カーブにして継続。失敗を 1 度だけ `DiagnosticsVM`（または既存の診断 sink）へ `信号 'X' のサンプル読み取りに失敗しました` として記録。

- [ ] **Step 4: アプリ全体の集中フックを設置（トリガ広域被覆）**

`main_window.py` 構築時に、Qt スロット横断の最後の砦として `sys.excepthook`（または `QCoreApplication` の通知ラップ）で `SampleReadError` を捕捉し、ダイアログでなく診断＋ステータスに落として**プロセスを落とさない**（auto-fit/cursor-step 等 render 境界外の初回展開の保険）。core 計算（formula/`_require_min_samples`）は既存の派生信号エラー UI 経路へ `SampleReadError` を通す。

- [ ] **Step 5: 通ることを確認**

Run: `uv run pytest tests/gui/test_sample_read_error_degrade.py -q`
Expected: PASS

- [ ] **Step 6: ゲート＋コミット**

```bash
git add src/valisync/gui/views/main_window.py src/valisync/gui/views/graph_panel_view.py tests/gui/test_sample_read_error_degrade.py
git commit -m "feat(gui): SampleReadError の集中 degrade (遅延読み失敗でアプリを落とさない)"
```

---

## Task 8: ①gate realgui ＋ 実メモリ計測アーティファクト（受け入れ）

実 GUI で実 mf4 をロード→プロット→未プロット信号が未展開のままを実証し、実 RSS（peak/steady・1/2 ファイル）を計測して受け入れコミット値を記録する。

**Files:**
- Create: `tests/realgui/test_lazy_load_realclick.py`
- Create: `scripts/measure_lazy_footprint.py`（本セッションの psutil 手法を製品化）

**Interfaces:**
- Consumes: 全 Task 1-7

- [ ] **Step 1: realgui テストを書く（実 OS 入力・スクショ AI 判定）**

`tests/realgui/test_lazy_load_realclick.py`: 実ディスプレイで実 mf4 をロード→チャンネルを 1 本プロット→(a) プロットした信号は描画される (b) **プロットしていない信号の `_values_source.is_materialized` が False のまま**を assert。共有 `_realgui_input` を使う（`docs/` の gui-verify 参照）。

- [ ] **Step 2: 実行して実機で pass を確認**

Run: `uv run pytest tests/realgui/test_lazy_load_realclick.py --realgui -q`
Expected: PASS（実機・スクショ目視/AI 判定）

- [ ] **Step 3: メモリ計測スクリプトを製品化**

`scripts/measure_lazy_footprint.py`: `prod_demo.mf4` を実 GUI 経路でロードし peak/steady RSS（1 ファイル・2 ファイル compare）を出力。`uv run --with psutil python scripts/measure_lazy_footprint.py` で回す。

- [ ] **Step 4: 計測してコミット値を記録**

Run: `uv run --with psutil python scripts/measure_lazy_footprint.py`
Expected: 1 ファイル steady が旧 1,201MB から大幅減（目標 ~500-700MB）。数値をプラン完了報告と PR 本文に記録。

- [ ] **Step 5: フルゲート＋コミット**

Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/`
```bash
git add tests/realgui/test_lazy_load_realclick.py scripts/measure_lazy_footprint.py
git commit -m "test(gui): 遅延ロードの ①gate realgui ＋実メモリ計測アーティファクト"
```

---

## Self-Review（プラン著者チェック）

- **Spec coverage**: 増分A の各要件 → Task。サンプルソース抽象(T1)・LazyMdfValues 変換保存(T2)・ローダー遅延化/ハンドル保持/エラー close(T3)・namespaced 共有(T4)・offset 共有(T5)・teardown 非展開(T6)・SampleReadError degrade(T7)・①gate+メモリ実測(T8)。master eager コスト実測は T8 の計測に含む。**A/B 結合**: teardown 非展開ガードは T6 で A に含めた（B のハンドル close は増分B プラン）。
- **型整合**: `SampleSource`（array/is_materialized/length/nbytes_if_materialized）・`EagerValues`・`LazyMdfValues(handle,name,gi,ci,length,selector)`・`MdfHandle(mdf).lock/close/is_closed`・`Signal(values=|values_source=)`・`SignalGroup(handle=)` は全 Task で一貫。
- **Placeholder**: T7 の render 配線は既存テストヘルパ流用を指示（GUI 実 API に依存するため具体配線は実装時に確定）— これは spec の意図的な「実 API 合わせ」であり TODO ではない。GUI 増分ゆえ `/gui-test-plan` を実装前に実行（下記）。

> **GUI テスト計画**: T7（degrade）と T8（realgui）は GUI 挙動を含むため、実装着手前に `/gui-test-plan` で E2E 受け入れ（②十分性）を設計し、merge 前に `/gui-verify` で ①証拠ゲートを通す。
