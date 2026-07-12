# FU-20 native dtype 保持で float64 膨張を解消 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MDF ローダが全チャンネル値を float64 に強制キャストしている（native uint8 を 8× 膨張＝prod 330k で ~10.8GB）のをやめ、native dtype で保持し、float64 化は計算境界 `Signal.sorted_view()` の一点で行うことで、値 RAM を ~1.36GB へ 8× 削減する。

**Architecture:** `Signal.values` を native dtype で保持し、`sorted_view()` が返す値配列だけを float64 に upcast する。全計算・描画・export・formula・downsample・統計・補間は `sorted_view()`／`finite_view()`（後者は前者に委譲）を経由するため、この単一境界で下流の float64 契約を維持できる。プロット/解析した信号だけが float64 コストを払う。

**Tech Stack:** numpy（`ndarray.astype`・dtype.kind）・asammdf 8.8.22・pytest / hypothesis（PBT）・`tests/mdf4_helpers.py`（合成 MDF4 生成）。

## Global Constraints

- **VM・GUI・downsampler/interpolator/statistics/csv_exporter/formula のロジックは変更しない**（`sorted_view()` の返り値が native→float64 に変わるだけで、これらは既に float64 を期待している）。core は Qt 非依存を維持。
- **timestamps は float64 のまま**（精度必須・グループ共有）。**CSV loader は不変**（`csv_loader.py` の float64 はスコープ外）。
- **MDF のみ**が対象。遅延ロード（Approach A）は不採用（YAGNI）。
- **下流の float64 契約を維持**: `sorted_view()`／`finite_view()` は float64 を返す。native dtype が見えるのは loader（構築）と `sorted_view()`（即 upcast）と非計算の直接消費者（length・nbytes・pass-through 構築）のみ。
- **精度**: native→float64 は uint8/int8/16/32・float32 で厳密。int64/uint64 で |値|>2^53 のみ丸めるが現行と同一挙動（`astype(float64)` は現状もロード時に実行済み）＝新規精度損失なし。int64>2^53 の特別扱いはしない。
- **`is_monotonic` 不変**: `sorted_view()[0] is self.timestamps` は timestamps 同一性判定で、値の upcast の影響を受けない。
- **タスク順序厳守**: Task 1（sorted_view upcast）を先に入れる。値が現状 float64 の間は upcast は no-op で全スイート green のまま。Task 2（loader native 化）を後に入れて初めて native uint8 が流れ、Task 1 の upcast がそれを float64 化する。逆順だと Task 2 単独で native uint8 が下流に漏れスイートが壊れる。
- コミットメッセージ末尾に必須フッタ2行（`Co-Authored-By:` と `Claude-Session:`）。

---

### Task 1: `Signal.sorted_view()` が値を float64 に upcast する

**Files:**
- Modify: `src/valisync/core/models/signal.py`（`sorted_view()`・:50-86／docstring）
- Test: `tests/test_signal_sorted_view.py`（dtype/monotonic/interp-wrap を追加）・`tests/test_pbt_signal.py`（厳密性 PBT を追加）

**Interfaces:**
- Consumes: `Signal(name, timestamps, values, file_format, bus_type, source_file, metadata=...)`（既存・values は任意の数値 dtype を受理）。
- Produces: `Signal.sorted_view() -> (ts: float64, vs: float64)`（値は常に float64）。`finite_view()`/`range_stat_index()` は sorted_view に委譲するため自動的に float64 を受け取る（コード変更不要）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_signal_sorted_view.py` の末尾に追加。native dtype の値を持つ Signal を直接構築し、`sorted_view()`/`finite_view()` が float64 を返すこと・値が等価・`is_monotonic` 不変・線形補間が uint8 減算 wrap を起こさないことを検証する。

```python
import numpy as np

from valisync.core.interpolation.interpolator import (
    InterpolationMethod,
    Interpolator,
)
from valisync.core.models import Signal


def _sig(values, timestamps=None):
    ts = np.asarray(
        timestamps if timestamps is not None else np.arange(len(values)),
        dtype=np.float64,
    )
    return Signal(
        name="s",
        timestamps=ts,
        values=np.asarray(values),
        file_format="MDF4",
        bus_type="",
        source_file="",
    )


def test_sorted_view_upcasts_native_uint8_to_float64():
    sig = _sig(np.array([10, 20, 30], dtype=np.uint8))
    ts, vs = sig.sorted_view()
    assert vs.dtype == np.float64
    assert np.array_equal(vs, [10.0, 20.0, 30.0])


def test_finite_view_is_float64_for_native_uint8():
    sig = _sig(np.array([10, 20, 30], dtype=np.uint8))
    _, vs = sig.finite_view()
    assert vs.dtype == np.float64


def test_is_monotonic_unchanged_for_native_uint8_monotonic_signal():
    sig = _sig(np.array([1, 2, 3], dtype=np.uint8))
    # 単調 ts なので fast path: sorted_view()[0] は timestamps 同一オブジェクト。
    assert sig.is_monotonic is True
    assert sig.sorted_view()[0] is sig.timestamps


def test_linear_interp_no_uint8_wraparound():
    # vs=[200,10] uint8。float64 なら中点=105.0。uint8 減算 (10-200) は 66 に wrap し
    # 233.0 になる (sorted_view が upcast しないと FAIL する discriminating テスト)。
    sig = _sig(np.array([200, 10], dtype=np.uint8), timestamps=[0.0, 1.0])
    v = Interpolator().interpolate(sig, 0.5, InterpolationMethod.LINEAR)
    assert v == 105.0
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_signal_sorted_view.py::test_sorted_view_upcasts_native_uint8_to_float64 tests/test_signal_sorted_view.py::test_linear_interp_no_uint8_wraparound -v`
Expected: FAIL（現行 `sorted_view` は native dtype をそのまま返すため vs.dtype==uint8／補間は 233.0）。

- [ ] **Step 3: 最小の実装を書く**

`src/valisync/core/models/signal.py` の `sorted_view()` を次に置換する（値を float64 化・timestamps は不変）。

```python
    def sorted_view(self) -> tuple[np.ndarray, np.ndarray]:
        """Strictly-monotonic float64 view for computation and rendering (spec §4.1).

        Stable-sorts by timestamp and keeps the last-recorded value for equal
        timestamps (CAN "last received wins"). Values are upcast to float64
        here (the single computation boundary), so ``Signal.values`` can be
        stored in its native dtype (FU-20: avoids the 8x float64 inflation of
        wide uint8 array channels) while every consumer still receives float64.
        Timestamps are already float64 and are returned untouched, so
        ``is_monotonic`` (a timestamp-identity check) is unaffected. Cached
        after the first call; the computation is idempotent, so racing
        initialisations are harmless.
        """
        cache = getattr(self, "_sorted_view_cache", None)
        if cache is not None:
            return cache
        delegate = getattr(self, "_sorted_view_delegate", None)
        if delegate is not None:
            cache = delegate.sorted_view()
            object.__setattr__(self, "_sorted_view_cache", cache)
            return cache
        ts, vs = self.timestamps, self.values
        if len(ts) < 2 or bool(np.all(np.diff(ts) > 0)):
            # 値を float64 へ (既に float64 なら copy=False で無コピー)。
            vs64 = vs.astype(np.float64, copy=False)
            vs64.flags.writeable = False
            cache = (ts, vs64)
        else:
            order = np.argsort(ts, kind="stable")
            ts_s = ts[order]
            vs_s = vs[order]
            # keep-last: 安定ソートで同値 ts は記録順のまま並ぶので、各ランの
            # 末尾(次の ts が大きくなる位置)だけ残せば「最後の記録」が勝つ
            keep = np.concatenate((np.diff(ts_s) > 0, [True]))
            ts_s = ts_s[keep]
            vs_s = vs_s[keep].astype(np.float64, copy=False)
            ts_s.flags.writeable = False
            vs_s.flags.writeable = False
            cache = (ts_s, vs_s)
        object.__setattr__(self, "_sorted_view_cache", cache)
        return cache
```

`values` の docstring（`:20` 付近のクラス docstring）も更新する。

```python
    values: np.ndarray  # native 数値 dtype, shape=(n,); float64 は sorted_view()/finite_view() で
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/test_signal_sorted_view.py -v`
Expected: PASS（新規4件＋既存 sorted_view テスト無回帰）。

- [ ] **Step 5: PBT で native→float64 厳密性を lock**

`tests/test_pbt_signal.py` の末尾に追加。

整数 dtype（uint8/int16/int32・いずれも値が 2^53 未満で float64 に厳密表現可）で厳密性を検証する。float32 は float64 の部分集合で自明なため PBT 対象外（mixed elements 戦略の dtype 不整合も回避）。

```python
import hypothesis.extra.numpy as hnp
import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.models import Signal


@given(
    hnp.arrays(
        dtype=st.sampled_from([np.uint8, np.int16, np.int32]),
        shape=st.integers(min_value=1, max_value=64),
    )
)
def test_sorted_view_float64_upcast_is_exact_for_integers(vals):
    ts = np.arange(len(vals), dtype=np.float64)  # 単調 → fast path
    sig = Signal(
        name="s", timestamps=ts, values=vals,
        file_format="MDF4", bus_type="", source_file="",
    )
    _, vs = sig.sorted_view()
    assert vs.dtype == np.float64
    # uint8/int16/int32 は |値|<2^53 で float64 に厳密表現できるので値は不変。
    assert np.array_equal(vs, vals.astype(np.float64))
```

- [ ] **Step 6: PBT を実行して成功を確認**

Run: `uv run pytest tests/test_pbt_signal.py::test_sorted_view_float64_upcast_is_exact_for_integers -v`
Expected: PASS。

- [ ] **Step 7: 品質ゲート＋全スイート無回帰**

Run: `uv run ruff check src/valisync/core/models/signal.py tests/test_signal_sorted_view.py tests/test_pbt_signal.py && uv run ruff format --check src/valisync/core/models/signal.py tests/test_signal_sorted_view.py tests/test_pbt_signal.py && uv run mypy src/valisync/core/models/signal.py && uv run pytest -q`
Expected: 全 pass（sorted_view の値が現状 float64 の間は upcast が no-op ＝既存全スイート green）。

- [ ] **Step 8: コミット**

```bash
git add src/valisync/core/models/signal.py tests/test_signal_sorted_view.py tests/test_pbt_signal.py
git commit -m "feat(core): Signal.sorted_view() で値を float64 upcast (FU-20 単一境界)

..."  # フッタ2行必須
```

---

### Task 2: `MdfLoader` が native dtype を保持する（float64 astype を撤去）

**Files:**
- Modify: `src/valisync/core/loaders/mdf_loader.py`（`_load_group` の `:468-482`）
- Test: `tests/test_loaders.py`（native dtype 保持・非数値スキップを追加）

**Interfaces:**
- Consumes: `Signal.sorted_view()`（Task 1・native 値を float64 化する）。`_flatten` の返す各 leaf は native dtype の contiguous 配列。
- Produces: `Signal.values` を **native 数値 dtype**（uint8/int16/float32/... 記録どおり）で構築。非数値（dtype.kind not in "iufb"）は warning 診断でスキップ。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_loaders.py` の末尾に追加。2D uint8 チャンネルをロードして展開後の値が uint8 のまま（float64 に膨張しない）ことを検証する。

```python
import numpy as np

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.loaders.mdf_loader import MdfLoader


def test_loader_preserves_native_uint8_dtype(tmp_path):
    # write_mdf4_2d: 4x3 uint8 の "Mat" (3 列に展開) + float64 の "Clean"。
    path = write_mdf4_2d(tmp_path)
    result = MdfLoader().load(path)
    sigs = {s.name: s for s in result.signal_group.signals}
    mat_cols = [s for name, s in sigs.items() if name.startswith("Mat")]
    assert len(mat_cols) == 3
    # native uint8 を保持 — 現行の astype(float64) なら float64 になり FAIL。
    assert all(s.values.dtype == np.uint8 for s in mat_cols)
    # float64 元データ (Clean) は float64 のまま。
    assert sigs["Clean"].values.dtype == np.float64
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_loaders.py::test_loader_preserves_native_uint8_dtype -v`
Expected: FAIL（現行 `col.astype(np.float64)` で Mat 列が float64 になる）。

- [ ] **Step 3: 最小の実装を書く**

`src/valisync/core/loaders/mdf_loader.py` の `_load_group` 内、`for out_name, col in pairs:` の値変換ブロック（`:468-482`）を次に置換する。

```python
            for out_name, col in pairs:
                # FU-20: native dtype を保持し float64 膨張 (wide uint8 の 8x) を避ける。
                # 数値 (int/uint/float/bool) 以外は Signal が扱えないため従来どおり skip。
                # float64 化は計算境界 Signal.sorted_view() で行う。
                if col.dtype.kind not in "iufb":
                    diagnostics.append(
                        Diagnostic(
                            level="warning",
                            message=(
                                f"Signal '{out_name}' has non-numeric values,"
                                f" skipped: dtype {col.dtype}"
                            ),
                        )
                    )
                    continue
                values = col
                values.flags.writeable = False
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/test_loaders.py::test_loader_preserves_native_uint8_dtype -v`
Expected: PASS。

- [ ] **Step 5: 非数値スキップの無回帰を確認**

`tests/test_loaders.py` に非数値スキップの明示テストを追加（既存の all-bad テストがあれば重複回避し、無ければ新設）。

```python
from tests.mdf4_helpers import write_mdf4_all_channels_bad


def test_loader_skips_non_numeric_channel_with_warning(tmp_path):
    # byte-string (S4) チャンネルのみ = 全滅。dtype.kind 'S' はスキップ対象。
    path = write_mdf4_all_channels_bad(tmp_path)
    result = MdfLoader().load(path)
    assert result.signal_group.signals == ()
    assert any(
        d.level == "warning" and "non-numeric" in d.message
        for d in result.diagnostics
    )
```

Run: `uv run pytest tests/test_loaders.py::test_loader_skips_non_numeric_channel_with_warning -v`
Expected: PASS。

- [ ] **Step 6: 品質ゲート＋全スイート無回帰**

Run: `uv run ruff check src/valisync/core/loaders/mdf_loader.py tests/test_loaders.py && uv run ruff format --check src/valisync/core/loaders/mdf_loader.py tests/test_loaders.py && uv run mypy src/valisync/core/loaders/mdf_loader.py && uv run pytest -q`
Expected: 全 pass（Task 1 の upcast で native uint8 は下流に float64 で届く。既存 loader テストの値等価は dtype 非依存で通る。もし `values.dtype == np.float64` を仮定する既存テストがあれば native/float64 の期待へ更新し理由を報告）。

- [ ] **Step 7: コミット**

```bash
git add src/valisync/core/loaders/mdf_loader.py tests/test_loaders.py
git commit -m "feat(core): MdfLoader が native dtype を保持 (FU-20 float64 膨張撤去)

..."  # フッタ2行必須
```

---

### Task 3: E2E メモリ実測（合成 wide-uint8 の nbytes 比例＋ローカル prod_demo RSS）

**Files:**
- Create: `tests/test_native_dtype_memory.py`
- （ローカル手動検証手順を本タスク Step 4 に記載）

**Interfaces:**
- Consumes: `MdfLoader().load(path)`（Task 2・native dtype 保持）・`tests/mdf4_helpers.write_mdf4_wide_2d`。
- Produces: なし（テスト＋ローカル検証手順）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_native_dtype_memory.py` を新規作成。展開上限 1024 未満の wide uint8 チャンネルを実ロード経路でロードし、値配列の総 nbytes が native（1 バイト/要素）であり float64（8 バイト）に膨張していないことを実測する。

```python
"""FU-20 E2E: wide uint8 チャンネルの実ロードで値 RAM が native 比例 (float64 の 1/8)。

prod 330k の ~10.8GB→~1.36GB (8x 削減) の CI 可能なプロキシ。展開上限 1024 を
超えると headless では全スキップされるため cols=1000 (<1024) を使う。
"""

from __future__ import annotations

import numpy as np

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.loaders.mdf_loader import MdfLoader


def test_wide_uint8_channel_keeps_native_footprint(tmp_path):
    cols = 1000  # < EXPANSION_COLUMN_LIMIT(1024): 全列がロードされる
    path = write_mdf4_wide_2d(tmp_path, cols=cols)
    result = MdfLoader().load(path)
    wide = [s for s in result.signal_group.signals if s.name.startswith("Wide")]
    assert len(wide) == cols  # 展開された uint8 列

    # 各列は 3 サンプル (write_mdf4_wide_2d の ts は 3 点) の uint8。
    assert all(s.values.dtype == np.uint8 for s in wide)
    native_bytes = sum(s.values.nbytes for s in wide)
    # native: cols * 3 * 1。float64 に膨張していれば *8 になり FAIL。
    assert native_bytes == cols * 3 * 1
```

- [ ] **Step 2: テストを実行して失敗するか確認（サボタージュ判定）**

Task 1/2 適用後は PASS するはず。discriminating 性を確認するため、`mdf_loader.py` の `values = col` を一時的に `values = col.astype(np.float64)` に戻して実行し FAIL することを確認 → 戻す。

Run: `uv run pytest tests/test_native_dtype_memory.py -v`
Expected: サボタージュ時 FAIL（`native_bytes == cols*3*8` になり `== cols*3*1` が成立しない）／復帰後 PASS。

- [ ] **Step 3: 品質ゲート**

Run: `uv run ruff check tests/test_native_dtype_memory.py && uv run ruff format --check tests/test_native_dtype_memory.py && uv run pytest tests/test_native_dtype_memory.py -v`
Expected: PASS。

- [ ] **Step 4: ローカル実 prod_demo RSS 検証（手動・証拠添付）**

CI では重すぎるため**ローカル手動ゲート**（realgui 同様）。`demo_data/prod_demo.mf4` が有る環境で下記スクリプトを実行し、値 RAM が現行 ~10.8GB 相当から ~1.36GB 相当へ低下したことを RSS で確認し、report に数値を添付する。スクリプトはスクラッチに置きコミットしない。

```python
# scratch: prod_demo をロードし値配列総 nbytes を実測 (RSS 相当)。
from pathlib import Path
from valisync.core.loaders.mdf_loader import MdfLoader

res = MdfLoader().load(Path("demo_data/prod_demo.mf4"))
sigs = res.signal_group.signals
total = sum(s.values.nbytes for s in sigs)
print(f"signals={len(sigs)}  values RAM = {total/1e9:.2f} GB")
# 期待: ~1.36 GB (float64 なら ~10.8 GB)。
```

Run: `uv run python <scratch>.py`
Expected: `values RAM = ~1.36 GB`（本 spec の 8x 削減の実機再現）。数値を report に記録。

- [ ] **Step 5: コミット**

```bash
git add tests/test_native_dtype_memory.py
git commit -m "test(core): FU-20 wide uint8 実ロードで値 RAM が native 比例を実測

..."  # フッタ2行必須
```

---

## Self-Review

- **Spec coverage**: 変更点①loader native 化＝Task 2／②sorted_view upcast＝Task 1／③契約 docstring＝Task 1 Step 3。テスト: native 保持＝Task 2／view float64＝Task 1／PBT 厳密性＝Task 1 Step 5／オーバーフロー(補間 wrap)＝Task 1／非数値スキップ＝Task 2／E2E メモリ＝Task 3。spec の全項目に対応タスクあり。
- **Placeholder scan**: コミット本文の `...` はフッタ必須指示付きの意図的プレースホルダ。コード/テストは全て完全記述。
- **Type consistency**: `Signal.sorted_view() -> (float64, float64)`（Task 1）を Task 2/3 が前提。`write_mdf4_2d`/`write_mdf4_wide_2d`/`write_mdf4_all_channels_bad` は `tests/mdf4_helpers.py` の実シグネチャと一致。`col.dtype.kind`・`values.flags.writeable` は numpy 実 API。`EXPANSION_COLUMN_LIMIT=1024` は `mdf_loader.py` 実定数（cols=1000<1024 で全列ロード）。
- **順序整合**: Task 1（no-op while float64）→ Task 2（native 化で win 発火）→ Task 3（実測）。各タスク独立に green。
