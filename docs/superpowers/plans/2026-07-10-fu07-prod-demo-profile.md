# FU-07 本番想定デモ mf4（`prod` プロファイル）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scripts/generate_demo_mf4.py` に大規模 `prod` プロファイル（計測120秒・展開後~32万ch・~1.5GB）を追加し、FU-01（1024列超ダイアログのスクロール不能）・FU-03（多チャンネルのドック切替フリーズ）を実機再現できるデモデータを生成する。

**Architecture:** アレイ主体構成（生 append は数千本、loader が LD-14 で展開して~32万ch へ）。プロファイルごとに group 群を切替える `Profile.groups_builder` を追加し、`prod` 用の大規模 group ビルダーを新設。純関数のサイズ/本数試算でプロファイル定義が目標±20%内であることをユニットテストで担保（実 1.5GB は CI 非生成）。製品コードは不変更（`scripts/`・テスト・docs のみ）。

**Tech Stack:** Python 3.13 / asammdf 8.8.11 / numpy。テストは pytest（`tests/test_demo_mf4.py`）。

## Global Constraints

- **目標3数値（±20% 実測調整）**: 計測長 **120秒** / 展開後チャンネル数 **~32万** / ファイルサイズ **~1.5GB**。
- **アレイは uint8 のみ**: `_pack_array_channel` は uint8 byte-array のみ asammdf 8.8.11 で正しく round-trip する（int16/float の 2D は itemsize>1 バグでサンプルがずれる）。バルク/広幅アレイは全て uint8。バルクスカラーは float64（1D スカラーは正常）。
- **10ms 比率 ~30%**（残り 100〜500ms）。10ms がサイズ主因。
- **広幅アレイ（>1024列）を数十本**含め、GUI で LD-14 展開ダイアログ（`ExpansionDialog`）が多数チェックボックスで発火する状況を作る（FU-01 再現データ）。列数は 1024 超（例 1100）。
- **製品コード（`src/valisync/`）不変更**。変更は `scripts/generate_demo_mf4.py`・`tests/test_demo_mf4.py`・`docs/development.md` のみ。
- **既存 `hils`/`quick`/`smoke` プロファイル据え置き**（回帰させない）。
- 生成物は `demo_data/`（gitignore 済み・非コミット）。
- **品質ゲート**（コミット前）: `uv run pytest tests/test_demo_mf4.py` / `uv run ruff check scripts/ tests/test_demo_mf4.py` / `uv run ruff format --check scripts/ tests/test_demo_mf4.py` / `uv run mypy` は scripts/ を型対象外なら省略可（既存方針に合わせる）。
- **コミット trailer（必須・末尾2行）**:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4
  ```

---

## File Structure

- **`scripts/generate_demo_mf4.py`**（Modify）: (1) `estimate_profile_size` 純関数、(2) `_bulk_array`/`_bulk_array_signals`/`_bulk_scalar_signals` 生成ヘルパ、(3) `Profile.groups_builder` フィールド＋`_build_prod_groups`＋`PROFILES["prod"]` 登録、(4) `write_mf4` の group 解決を profile 経由に、(5) `main` の `--duration` 上書きで `groups_builder` を保持。
- **`tests/test_demo_mf4.py`**（Modify）: 各タスクのユニット/構造テストを追記。既存テストは不変（`test_profiles_defined` のみ prod 追加で更新）。
- **`docs/development.md`**（Modify）: デモデータ節に `prod` を追記。

---

## Task 1: プロファイルのサイズ/本数試算（純関数）

**Files:**
- Modify: `scripts/generate_demo_mf4.py`（`estimate_profile_size` を `GroupDef`/`SigDef` 定義の後・`_build_groups` 付近に追加）
- Test: `tests/test_demo_mf4.py`

**Interfaces:**
- Consumes: 既存 `GroupDef`（`.rate_s`・`.signals`）・`SigDef`（`.ndim`・`.dtype`）。
- Produces: `estimate_profile_size(groups: list[GroupDef], duration_s: float) -> tuple[int, int]` — `(推定バイト数, 展開後チャンネル数)`。

### 背景

`prod` の group 定義が目標（1.5GB/32万ch/120秒）に収まるかを、**実生成せずに**検証するための純関数。サイズは「レコード = 時刻(float64 8B) + Σ 各信号のバイト（アレイ=列数×1B uint8／スカラー=dtype.itemsize）」× サンプル数、展開後チャンネル数は「アレイは列数ぶん・スカラーは1」で数える（LD-14 の (N,k)→k スカラー展開に対応）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_demo_mf4.py` 末尾に追記:

```python
def test_estimate_profile_size_arithmetic():
    from generate_demo_mf4 import GroupDef, SigDef, estimate_profile_size

    g = GroupDef(
        name="G",
        rate_s=0.01,  # 10ms
        jitter_pct=0.0,
        bus=None,
        signals=[
            SigDef("s1", lambda t, rng: t, dtype=np.float64),  # scalar float64
            SigDef(
                "arr", lambda t, rng: np.zeros((len(t), 100)), dtype=np.uint8, ndim=100
            ),  # array 100 列
        ],
        group_id=0,
    )
    est_bytes, est_channels = estimate_profile_size([g], 10.0)  # 10s / 10ms = 1000 sample
    # 展開後: scalar 1 + array 100 = 101
    assert est_channels == 101
    # bytes: n=1000. 時刻 1000*8=8000 + scalar 1000*1*8=8000 + array 1000*100*1=100000
    assert est_bytes == 8000 + 8000 + 100000
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_demo_mf4.py::test_estimate_profile_size_arithmetic -v`
Expected: FAIL — `ImportError: cannot import name 'estimate_profile_size'`。

- [ ] **Step 3: 実装**

`scripts/generate_demo_mf4.py` の `GroupDef`/`SigDef` 定義より後（例 `_build_groups` の直前）に追加:

```python
def estimate_profile_size(groups: list[GroupDef], duration_s: float) -> tuple[int, int]:
    """(推定バイト数, 展開後チャンネル数) を実生成せず算出する純関数.

    - bytes ≈ Σ_group[ n × (8[float64 時刻] + Σ_sig 列数×dtype_bytes) ]
      n = ceil(duration_s / rate_s)、アレイ(ndim>1)は _pack_array_channel で
      uint8(1B)格納・スカラーは dtype.itemsize。
    - 展開後 ch ≈ Σ_sig (ndim if ndim>1 else 1)  # LD-14 の (N,k)→k 展開に対応。
    """
    total_bytes = 0
    total_channels = 0
    for g in groups:
        n = max(int(np.ceil(duration_s / g.rate_s)), 1)
        group_bytes = n * 8  # float64 時刻チャンネル
        for sd in g.signals:
            cols = sd.ndim if sd.ndim > 1 else 1
            dtype_bytes = 1 if sd.ndim > 1 else np.dtype(sd.dtype).itemsize
            group_bytes += n * cols * dtype_bytes
            total_channels += cols
        total_bytes += group_bytes
    return total_bytes, total_channels
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/test_demo_mf4.py::test_estimate_profile_size_arithmetic -v`
Expected: PASS。

- [ ] **Step 5: コミット**

```bash
git add scripts/generate_demo_mf4.py tests/test_demo_mf4.py
git commit -m "feat(demo): プロファイルのサイズ/本数試算 純関数 estimate_profile_size

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4"
```

---

## Task 2: バルクアレイ/スカラー生成ヘルパ

**Files:**
- Modify: `scripts/generate_demo_mf4.py`（`_ctrl_internal_signals` 付近に追加）
- Test: `tests/test_demo_mf4.py`

**Interfaces:**
- Consumes: 既存 `veh_spd`/`ttc`/`ctrl_internal`/`add_noise`・`SigDef`。
- Produces:
  - `_bulk_array(t: np.ndarray, cols: int, arr_idx: int) -> np.ndarray` — `(len(t), cols)` の決定的 2D 配列。
  - `_bulk_array_signals(prefix: str, n_arrays: int, cols: int, start_idx: int) -> list[SigDef]` — uint8・ndim=cols のアレイ SigDef を n_arrays 本。
  - `_bulk_scalar_signals(n: int, start_idx: int) -> list[SigDef]` — float64 スカラー SigDef を n 本。

### 背景

`prod` の 32万ch を「少数の生アレイ SigDef（各 cols 列）＋スカラー」で構成するための生成ヘルパ。値は `_pack_array_channel` で uint8 量子化されるため物理精度不要。**列ループを避けベクトル化**（cols が大きい）。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_bulk_array_shape_and_determinism():
    from generate_demo_mf4 import _bulk_array

    t = np.arange(0.0, 1.0, 0.01)  # 100 sample
    a = _bulk_array(t, cols=50, arr_idx=3)
    assert a.shape == (100, 50)
    b = _bulk_array(t, cols=50, arr_idx=3)
    assert np.array_equal(a, b)  # 決定的
    c = _bulk_array(t, cols=50, arr_idx=4)
    assert not np.array_equal(a, c)  # arr_idx でずれる


def test_bulk_array_signals_are_uint8_arrays():
    from generate_demo_mf4 import _bulk_array_signals

    sigs = _bulk_array_signals("Prod10", n_arrays=5, cols=1000, start_idx=0)
    assert len(sigs) == 5
    assert all(sd.ndim == 1000 and sd.dtype == np.uint8 for sd in sigs)
    assert sigs[0].name == "Prod10_0000" and sigs[4].name == "Prod10_0004"


def test_bulk_scalar_signals_count_and_names():
    from generate_demo_mf4 import _bulk_scalar_signals

    sigs = _bulk_scalar_signals(n=7, start_idx=0)
    assert len(sigs) == 7
    assert all(sd.ndim == 1 for sd in sigs)
    assert sigs[0].name == "Prod_Scalar_00000"
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_demo_mf4.py -k "bulk_array or bulk_scalar" -v`
Expected: FAIL — import エラー（関数未定義）。

- [ ] **Step 3: 実装**

`_ctrl_internal_signals`（現行 L422）の直後に追加:

```python
def _bulk_array(t: np.ndarray, cols: int, arr_idx: int) -> np.ndarray:
    """(len(t), cols) の決定的バルク配列 — 物理的意味なし・arr_idx で位相をずらす.

    下流 _pack_array_channel で 0-255 uint8 に量子化されるため物理精度は不要。
    列ループを避けベクトル化する (cols が大きいため)。
    """
    base = veh_spd(t - arr_idx * 0.7) + 5.0 * ttc(t - arr_idx * 1.3)  # (N,)
    col_scale = 1.0 + 0.017 * np.arange(cols)  # (cols,)
    return base[:, None] * col_scale[None, :]  # (N, cols)


def _bulk_array_signals(
    prefix: str, n_arrays: int, cols: int, start_idx: int
) -> list[SigDef]:
    """n_arrays 本の (N, cols) uint8 アレイ SigDef を生成 (loader が要素展開)."""
    sigs: list[SigDef] = []
    for i in range(n_arrays):
        idx = start_idx + i
        sigs.append(
            SigDef(
                name=f"{prefix}_{i:04d}",
                fn=lambda t, rng, c=cols, ai=idx: _bulk_array(t, c, ai),
                dtype=np.uint8,
                ndim=cols,
            )
        )
    return sigs


def _bulk_scalar_signals(n: int, start_idx: int) -> list[SigDef]:
    """n 本の平坦スカラー SigDef (XCP 内部変数風・ctrl_internal 流用・float64)."""
    sigs: list[SigDef] = []
    for i in range(n):
        idx = start_idx + i
        sigs.append(
            SigDef(
                name=f"Prod_Scalar_{i:05d}",
                fn=lambda t, rng, ai=idx: add_noise(ctrl_internal(t, ai), 0.5, rng),
            )
        )
    return sigs
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/test_demo_mf4.py -k "bulk_array or bulk_scalar" -v`
Expected: PASS（3件）。

- [ ] **Step 5: コミット**

```bash
git add scripts/generate_demo_mf4.py tests/test_demo_mf4.py
git commit -m "feat(demo): バルクアレイ/スカラー生成ヘルパ（uint8 アレイ・ベクトル化）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4"
```

---

## Task 3: `prod` group ビルダー＋プロファイル登録＋`write_mf4` 配線

**Files:**
- Modify: `scripts/generate_demo_mf4.py`（`Profile` フィールド追加・`_build_prod_groups`・`PROFILES["prod"]`・`write_mf4`・`main` の `--duration` 分岐）
- Test: `tests/test_demo_mf4.py`

**Interfaces:**
- Consumes: Task 1 `estimate_profile_size`・Task 2 `_bulk_array_signals`/`_bulk_scalar_signals`・既存 `veh_spd`/`ttc`/`lead_dist`/`radar_obj`/`add_noise`・`GroupDef`・`GROUPS`。
- Produces: `Profile.groups_builder`・`_build_prod_groups(...) -> list[GroupDef]`・`PROFILES["prod"]`。

### 背景と要点

- `Profile` は現状 `(duration_s, chunk_s)`。プロファイルごとに group 群を切替えるため `groups_builder: Callable[[], list[GroupDef]] | None = None` を追加（`None` は既存 `GROUPS`＝hils/quick/smoke）。**Callable はハッシュ可能なので frozen dataclass のまま**。
- `PROFILES`（現行 L26）は `_build_prod_groups` 定義前にあるため、**prod は `_build_prod_groups` 定義後に `PROFILES["prod"] = ...` で追記**（前方参照回避）。`main` の `choices=sorted(PROFILES)` は import 完了後に評価されるので prod が自動的に選択肢に入る。
- **`main` の `--duration` 上書きは新 `Profile` を作るため `groups_builder` を明示継承**しないと prod で hils group に化ける（バグ）。

### `_build_prod_groups` の目標数値

デフォルト定数は展開後 ~33万ch・~1.36GB（いずれも目標±20%内）:

| group | rate | 内容 | 展開後 |
|---|---|---|---|
| Prod_Scenario_10ms | 10ms | 実信号4本（プロット確認） | 4 |
| Prod_Bulk10ms | 10ms | 通常30本×1000列 ＋ 広幅60本×1100列（>1024=FU-01） | 96,000 |
| Prod_Bulk100ms | 100ms | 150本×1000列 | 150,000 |
| Prod_Bulk500ms | 500ms | 80本×1000列 | 80,000 |
| Prod_Scalars_500ms | 500ms | スカラー4000本 | 4,000 |

10ms 合計 96,004 / 総計 ~330,004（10ms=~29%）。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_prod_profile_registered_and_within_targets():
    from generate_demo_mf4 import PROFILES, _build_prod_groups, estimate_profile_size

    assert "prod" in PROFILES
    prof = PROFILES["prod"]
    assert prof.duration_s == 120.0
    assert prof.groups_builder is not None

    groups = _build_prod_groups()
    est_bytes, est_channels = estimate_profile_size(groups, prof.duration_s)
    # 1.5GB ±20% / 32万ch ±20%
    assert 1.2e9 <= est_bytes <= 1.8e9, f"{est_bytes / 1e9:.2f}GB out of range"
    assert 256_000 <= est_channels <= 384_000, f"{est_channels} ch out of range"

    # FU-01 用: >1024 列アレイが数十本ある
    wide = [sd for g in groups for sd in g.signals if sd.ndim > 1024]
    assert len(wide) >= 30

    # 複数レートの group（10ms/100ms/500ms）
    rates = {g.rate_s for g in groups}
    assert {0.01, 0.1, 0.5} <= rates


def test_prod_profile_does_not_disturb_existing():
    from generate_demo_mf4 import PROFILES

    assert PROFILES["hils"].duration_s == 3600.0
    assert PROFILES["hils"].groups_builder is None  # 既存は GROUPS 経由のまま
```

Also update the existing `test_profiles_defined`（現行）:

```python
def test_profiles_defined():
    assert set(gen.PROFILES) == {"hils", "quick", "smoke", "prod"}
    assert gen.PROFILES["hils"].duration_s == 3600.0
    assert gen.PROFILES["smoke"].duration_s <= 15.0
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_demo_mf4.py -k "prod_profile or profiles_defined" -v`
Expected: FAIL（`prod` 未登録・`_build_prod_groups` 未定義）。

- [ ] **Step 3: 実装**

**(a)** `Profile` に field 追加（`from collections.abc import Callable` は既に import 済み）:

```python
@dataclass(frozen=True)
class Profile:
    duration_s: float
    chunk_s: float  # extend 1回分 (ピークメモリの上限を決める)
    groups_builder: Callable[[], list[GroupDef]] | None = None
```

**(b)** `_build_groups`/`GROUPS`（L581）の後に `_build_prod_groups` と prod 登録を追加:

```python
def _build_prod_groups(
    n_10ms_arrays: int = 30,
    n_wide_arrays: int = 60,
    n_100ms_arrays: int = 150,
    n_500ms_arrays: int = 80,
    cols: int = 1000,
    wide_cols: int = 1100,  # >1024 で LD-14 ダイアログを発火 (FU-01)
    n_scalars: int = 4000,
) -> list[GroupDef]:
    """prod プロファイルの大規模 group 群 — アレイ主体で展開後 ~33万ch/~1.36GB/120s.

    引数は縮小版 (CI 構造テスト) 用にパラメータ化。デフォルトは目標±20%内。
    """
    scenario = [
        SigDef("VehSpd", lambda t, rng: add_noise(veh_spd(t), 0.2, rng), "km/h"),
        SigDef("AEB.TTC", lambda t, rng: ttc(t), "s"),
        SigDef("LeadDist", lambda t, rng: lead_dist(t), "m"),
        SigDef("Radar.Obj0.dx", lambda t, rng: radar_obj(t, 0, "dx"), "m"),
    ]
    g10 = _bulk_array_signals("Prod10", n_10ms_arrays, cols, 0)
    g10_wide = _bulk_array_signals("Prod10Wide", n_wide_arrays, wide_cols, 100_000)
    g100 = _bulk_array_signals("Prod100", n_100ms_arrays, cols, 200_000)
    g500 = _bulk_array_signals("Prod500", n_500ms_arrays, cols, 300_000)
    scalars = _bulk_scalar_signals(n_scalars, 400_000)
    return [
        GroupDef("Prod_Scenario_10ms", 0.01, 0.0, None, scenario, 0),
        GroupDef("Prod_Bulk10ms", 0.01, 0.0, None, [*g10, *g10_wide], 1),
        GroupDef("Prod_Bulk100ms", 0.1, 0.0, None, g100, 2),
        GroupDef("Prod_Bulk500ms", 0.5, 0.0, None, g500, 3),
        GroupDef("Prod_Scalars_500ms", 0.5, 0.0, None, scalars, 4),
    ]


PROFILES["prod"] = Profile(
    duration_s=120.0, chunk_s=5.0, groups_builder=_build_prod_groups
)
```

**(c)** `write_mf4`（L727）の group 解決を profile 経由に変更:

```python
    n_chunks = int(np.ceil(profile.duration_s / profile.chunk_s))
    groups = profile.groups_builder() if profile.groups_builder is not None else GROUPS
    for ci in range(n_chunks):
        t0 = ci * profile.chunk_s
        t1 = min(t0 + profile.chunk_s, profile.duration_s)
        for gi, g in enumerate(groups):
```

（以降 `GROUPS` を直接参照している箇所は無い＝この関数内の `enumerate(GROUPS)` のみ。`enumerate(groups)` に置換。）

**(d)** `main`（L775）の `--duration` 上書きで `groups_builder` を継承:

```python
    if a.duration is not None:
        prof = Profile(
            duration_s=a.duration,
            chunk_s=min(prof.chunk_s, a.duration),
            groups_builder=prof.groups_builder,
        )
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/test_demo_mf4.py -k "prod_profile or profiles_defined" -v`
Expected: PASS（3件）。

- [ ] **Step 5: 既存デモテストの回帰確認**

Run: `uv run pytest tests/test_demo_mf4.py -v`
Expected: 全 PASS（既存 smoke/hils/dirty/2D 展開テストが `write_mf4` の group 解決変更で壊れない＝`groups_builder is None` で従来どおり `GROUPS`）。

- [ ] **Step 6: コミット**

```bash
git add scripts/generate_demo_mf4.py tests/test_demo_mf4.py
git commit -m "feat(demo): prod プロファイル（大規模アレイ主体・~33万ch/~1.36GB/120s）

Profile.groups_builder でプロファイル別 group 切替・_build_prod_groups 追加・
write_mf4 を profile 経由の group 解決へ・--duration 上書きで groups_builder 継承。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4"
```

---

## Task 4: CI 極小版の構造検証（生成＋`Session.load`）

**Files:**
- Test: `tests/test_demo_mf4.py`

**Interfaces:**
- Consumes: Task 3 `_build_prod_groups`（縮小パラメータ）・`Profile`・`write_mf4`・`valisync.core.session.Session`。

### 背景

実 1.5GB は CI で作らない。`_build_prod_groups` を**縮小パラメータ**で呼び、prod と**同じコード経路**の極小 mf4 を生成して構造を検証する。広幅アレイ（>1024列）はヘッドレスでは LD-14 が全スキップするため、**≤1024 アレイは展開・広幅アレイは非展開**を弁別的に確認する（＝FU-01 用データが正しく「展開ダイアログ対象」になる証拠）。

> **API 注記（既存テストで検証済み）**: `session.group_signals(outcome.key)` は `Signal` のリスト（`.name` は `"<group>::<signal>"` 形式なので `split("::", 1)[1]` で信号名・`.values` で値）。`outcome.diagnostics` は `.level`（`"error"`/`"warning"`/`"info"`）と `.message` を持つ。2D `(N,k)` uint8 アレイは LD-14 で `Name[i]` へ展開（`test_2d_channels_explode_in_valisync` が `Radar.ObjMatrix[0..7]` で確認済み）。`veh_spd([0,50)) ≈ 80`（`test_veh_spd_cruise_is_near_80`）なので極小尺でも値健全性を assert できる。

- [ ] **Step 1: 弁別的な構造テスト2本を書く**

Task 3 実装済みコードに対する検証テスト。展開名（`Name[i]`）は検証済みだが、万一実測とずれたら Step 2 で実観測して文字列を合わせる（false-green 回避の唯一の未知点）。

```python
def test_prod_tiny_structure_loads(tmp_path):
    # prod と同じコード経路の極小版 (広幅は 1100 列で >1024 を維持).
    builder = lambda: gen._build_prod_groups(  # noqa: E731
        n_10ms_arrays=2,
        n_wide_arrays=1,
        n_100ms_arrays=2,
        n_500ms_arrays=2,
        cols=6,
        wide_cols=1100,  # >1024 を維持 (FU-01 対象)
        n_scalars=3,
    )
    prof = gen.Profile(duration_s=0.5, chunk_s=0.5, groups_builder=builder)
    out = gen.write_mf4(
        out=tmp_path / "prod_tiny.mf4", profile=prof, seed=1, dirty=False, progress=False
    )

    from valisync.core.session import Session

    session = Session()
    outcome = session.load(out)
    by_name = {s.name.split("::", 1)[1]: s for s in session.group_signals(outcome.key)}
    names = set(by_name)

    # シナリオ実信号が見える + 値が物理レンジ (cruise ≈ 80km/h・既存 smoke と同流儀)
    assert "VehSpd" in names
    assert 70.0 < float(np.nanmean(by_name["VehSpd"].values)) < 90.0
    # ≤1024 列アレイは要素展開される (cols=6 → [0..5])
    assert "Prod10_0000[0]" in names and "Prod10_0000[5]" in names
    # >1024 列の広幅アレイはヘッドレスでは展開されない (LD-14 全スキップ=FU-01 対象)
    assert not any(n.startswith("Prod10Wide_0000[") for n in names)
    # error 診断はゼロ
    assert not any(d.level == "error" for d in outcome.diagnostics)


def test_prod_tiny_has_multiple_rate_groups(tmp_path):
    builder = lambda: gen._build_prod_groups(  # noqa: E731
        n_10ms_arrays=1,
        n_wide_arrays=1,
        n_100ms_arrays=1,
        n_500ms_arrays=1,
        cols=4,
        wide_cols=1100,
        n_scalars=2,
    )
    prof = gen.Profile(duration_s=1.0, chunk_s=1.0, groups_builder=builder)
    out = gen.write_mf4(
        out=tmp_path / "prod_rates.mf4", profile=prof, seed=1, dirty=False, progress=False
    )
    from asammdf import MDF

    with MDF(str(out)) as mdf:
        # Prod10_0000 (10ms) と Prod500_0000 (500ms) のサンプル数比が rate 比 (~50x) を反映
        n_10 = len(mdf.get("Prod10_0000").timestamps)
        n_500 = len(mdf.get("Prod500_0000").timestamps)
        assert n_10 > n_500 * 10  # 10ms は 500ms の 50 倍レート
```

- [ ] **Step 2: テストを実行して結果を確認（未知点＝展開名の実測突合）**

Run: `uv run pytest tests/test_demo_mf4.py -k "prod_tiny" -v`
Expected: PASS（2件・Task 3 が正しければ）。もし `Prod10_0000[0]` の assert が FAIL したら、`print(sorted(n for n in names if n.startswith("Prod10_0000")))` で実際の展開名を観測し、確定文字列を実測へ合わせる（LD-14 の `Name[i]` を既存テストで確認済みなので通常は不要）。

- [ ] **Step 3: コミット**

```bash
git add tests/test_demo_mf4.py
git commit -m "test(demo): prod 極小版の構造検証（≤1024展開・>1024非展開・複数レート）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4"
```

---

## Task 5: `docs/development.md` に `prod` を追記

**Files:**
- Modify: `docs/development.md`（「デモデータ」節）

### 背景

`prod` の目的（FU-01/FU-03 再現）・生成コマンド・目標数値・実機確認手順を追記。実測値（生成時間・ロード時間・実サイズ・展開後 ch 数）は初回実生成後に埋める欄を用意。

- [ ] **Step 1: デモデータ節を特定**

Run: `grep -n "デモデータ\|--profile\|hils\|generate_demo_mf4" docs/development.md`
Expected: 既存のデモデータ節（hils/quick/smoke の説明）が見つかる。

- [ ] **Step 2: `prod` 説明を追記**

既存プロファイル表/説明の後に以下を追記（該当節の文体に合わせて整形）:

```markdown
### `prod` プロファイル（本番想定・大規模チャンネル / FU-07）

FU-01（1024列超の展開ダイアログがスクロール不能）・FU-03（多チャンネルのドック切替フリーズ）を実機再現するための大規模データ。

- 生成: `uv run python scripts/generate_demo_mf4.py --profile prod`
- 目標: 計測 **120秒** / 展開後 **~32万チャンネル** / **~1.5GB**（アレイ主体・広幅アレイ >1024列を数十本含む）。
- 実機確認: `uv run valisync` でロード → (i) 広幅アレイの LD-14 展開ダイアログがチェックボックス多数でスクロール不能（FU-01）・(ii) ロード後にドック表示切替がフリーズ気味（FU-03）を `/run`・`/verify` で観測。
- 実測値（初回生成後に記入）: 生成時間 ____ / ロード時間 ____ / 実サイズ ____ GB / 展開後 ch 数 ____。
- 注: FU-08（Y軸オートフィットの重さ）は高サンプル数が要るため `hils`（1ms×3600s）が適役（`prod` は 120秒×10ms 上限で対象外）。
```

- [ ] **Step 3: コミット**

```bash
git add docs/development.md
git commit -m "docs: development.md に prod プロファイル（FU-07・FU-01/03 再現）を追記

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4"
```

---

## 完了時の全体ゲート

- [ ] `uv run pytest tests/test_demo_mf4.py`（全 PASS・既存回帰なし）
- [ ] `uv run ruff check scripts/ tests/test_demo_mf4.py` / `uv run ruff format --check scripts/ tests/test_demo_mf4.py`
- [ ] （任意・時間があれば）`uv run python scripts/generate_demo_mf4.py --profile prod` を実走し、実サイズ・生成時間を docs の欄に記入（重いので必須ではない・CI 非対象）。

## Self-Review（プラン作成者チェック済み）

- **Spec coverage**: プロファイル定義→Task3／32万内訳（アレイ主体）→Task2/3／制約解決A(10ms30%)→Task3 定数／生成実現性(アレイで生本数抑制)→Task2/3／テスト戦略(試算純関数・CI極小版・実機手順)→Task1/4/5／FU-08 限界の明記→Task5 docs＋spec。全 spec 要素にタスク対応。
- **Placeholder scan**: コード steps は全て完全コード。docs（Task5）の「実測値 ____」のみ意図的な空欄＝初回実生成後に埋める実測値プレースホルダ（用途明記）。Task4 の唯一の未知点（LD-14 展開名）は検証済み（`test_2d_channels_explode_in_valisync`）＋Step2 に実測突合フォールバックを明記。他に TBD/TODO なし。
- **Type consistency**: `estimate_profile_size(groups, duration_s)->(int,int)`・`_build_prod_groups(...)->list[GroupDef]`・`_bulk_array_signals(prefix,n_arrays,cols,start_idx)`・`_bulk_scalar_signals(n,start_idx)`・`Profile.groups_builder` を全タスクで一貫使用。uint8 アレイ／float64 スカラーの dtype 方針を Global Constraints で固定。
