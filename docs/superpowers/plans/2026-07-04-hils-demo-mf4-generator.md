# HILS デモ mf4 ジェネレータ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本番（ADAS HILS・CANape 計測）相当の mf4 を再現可能に生成する CLI（`hils`≈2GB/`quick`≈180MB/`smoke`=CI 用）を作り、実機確認データを本番寄りにする。

**Architecture:** 単一スクリプト `scripts/generate_demo_mf4.py` に自己完結（シナリオ純関数群＋MDF 書き出し＋CLI）。テストは sys.path 経由で import（`src/` の構造変更なし）。値は「時刻の決定的関数＋seed 派生ノイズ」で生成し、チャンク分割に依存しない再現性を持つ。書き出しは asammdf の append→extend チャンク方式でピークメモリを抑制。

**Tech Stack:** Python 3.12/3.13・asammdf・numpy・argparse。製品コード（src/）は不変更。

**Spec:** [docs/superpowers/specs/2026-07-04-hils-demo-mf4-generator-design.md](../specs/2026-07-04-hils-demo-mf4-generator-design.md)

## Global Constraints

- 品質ゲート（コミット前・全体スコープ）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`（scripts/ は mypy 対象外だが ruff 対象 — pyproject の include を確認し、対象なら型注釈も整える）。
- **生成ファイルはコミットしない**: `demo_data/` を .gitignore に追加。テストは tmp_path に生成。
- **CI で hils/quick を生成しない**: テストは smoke プロファイル（10秒分・数MB・生成数秒）のみ。
- 再現性: 同一 `--seed`・同一プロファイル → バイト同一でなくてよいが**値は同一**（MDF 内部のタイムスタンプメタ等は除く）。シナリオ値は時刻の関数、ノイズは `default_rng(seed*1000 + group_id*100 + chunk_idx)`。
- コメントは WHY のみ・コメント内全角括弧 RUF002/003 注意（日本語文字列リテラル可）。
- 2GB ロードの実測（LD-10 データ取り）は**ユーザーの実機確認に委ねる** — 本プランでは実施しない（バックグラウンドで大量 RAM を消費しない）。

---

## File Structure

- Create `scripts/generate_demo_mf4.py` — 本体（シナリオ関数・グループ定義・書き出し・CLI）。
- Create `tests/test_demo_mf4.py` — シナリオ単体＋smoke 生成/読み戻し＋valisync 統合。
- Modify `.gitignore` — `demo_data/` 追加。
- Modify `docs/development.md` — 使い方1節。
- Modify `docs/audit-findings-catalog.md` — LD-12 追補1行。

---

## Task 1: シナリオ関数群＋プロファイル定義（スクリプト骨格）

**Files:**
- Create: `scripts/generate_demo_mf4.py`（本タスクではシナリオ・定数部まで）
- Create: `tests/test_demo_mf4.py`（シナリオ単体テスト）

**Interfaces:**
- Produces（後続タスクが使用）: `PROFILES: dict[str, Profile]`（`Profile(duration_s, chunk_s, xcp1ms_extra_ch)`）。`scenario_phase(t) -> str`（"cruise"/"lead_decel"/"cutin"/"cam_lost"/"recovery"・300s 周期）。各信号関数 `veh_spd(t)`・`ttc(t)`・`brk_press(t)`・`radar_obj(t, slot, attr)`・`cam_obj(t, slot, attr)`（cam_lost 区間は NaN）・`cluster_surr(t, slot, attr)` — いずれも `t: np.ndarray -> np.ndarray`（ベクトル化・決定的）。`add_noise(values, scale, rng)`。

- [ ] **Step 1: Write the failing tests**

`tests/test_demo_mf4.py`:

```python
"""HILS デモ mf4 ジェネレータのテスト（scripts/ を sys.path 経由で import）."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_demo_mf4 as gen  # noqa: E402


def test_scenario_phases_cover_300s_cycle():
    assert gen.scenario_phase(np.array([10.0]))[0] == "cruise"
    assert gen.scenario_phase(np.array([90.0]))[0] == "lead_decel"
    assert gen.scenario_phase(np.array([150.0]))[0] == "cutin"
    assert gen.scenario_phase(np.array([210.0]))[0] == "cam_lost"
    assert gen.scenario_phase(np.array([270.0]))[0] == "recovery"
    assert gen.scenario_phase(np.array([310.0]))[0] == "cruise"  # 周期反復


def test_veh_spd_cruise_is_near_80():
    t = np.arange(0.0, 50.0, 0.1)
    v = gen.veh_spd(t)
    assert np.all(np.abs(v - 80.0) < 3.0)


def test_ttc_decreases_during_lead_decel():
    t = np.arange(65.0, 115.0, 1.0)
    ttc = gen.ttc(t)
    assert np.all(np.diff(ttc) <= 0.0)
    assert ttc[-1] < ttc[0]


def test_cam_obj_nan_during_cam_lost():
    t = np.array([200.0])
    assert np.isnan(gen.cam_obj(t, slot=0, attr="dx"))[0]
    t2 = np.array([30.0])
    assert np.isfinite(gen.cam_obj(t2, slot=0, attr="dx"))[0]


def test_signals_deterministic_for_same_time():
    t = np.arange(0.0, 300.0, 0.5)
    assert np.array_equal(
        gen.veh_spd(t), gen.veh_spd(t.copy())
    )  # 時刻の関数＝チャンク分割非依存


def test_profiles_defined():
    assert set(gen.PROFILES) == {"hils", "quick", "smoke"}
    assert gen.PROFILES["hils"].duration_s == 3600.0
    assert gen.PROFILES["smoke"].duration_s <= 15.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_demo_mf4.py -v` → FAIL（モジュール未作成）。

- [ ] **Step 3: Implement — scripts/generate_demo_mf4.py（骨格＋シナリオ）**

```python
"""HILS デモ mf4 ジェネレータ — 本番（ADAS HILS・CANape 計測）相当の実機確認データ.

spec: docs/superpowers/specs/2026-07-04-hils-demo-mf4-generator-design.md
値は「時刻の決定的関数＋seed 派生ノイズ」— チャンク分割に依存せず再現可能。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CYCLE_S = 300.0  # ACC 追従シナリオの1サイクル（spec §4.3）


@dataclass(frozen=True)
class Profile:
    duration_s: float
    chunk_s: float  # extend 1回分（ピークメモリの上限を決める）


PROFILES: dict[str, Profile] = {
    "hils": Profile(duration_s=3600.0, chunk_s=300.0),
    "quick": Profile(duration_s=300.0, chunk_s=300.0),
    "smoke": Profile(duration_s=10.0, chunk_s=10.0),
}

_PHASES = (  # (開始秒, 名前) — 300s 周期
    (0.0, "cruise"),
    (60.0, "lead_decel"),
    (120.0, "cutin"),
    (180.0, "cam_lost"),
    (240.0, "recovery"),
)


def scenario_phase(t: np.ndarray) -> np.ndarray:
    """各時刻のシナリオフェーズ名（300s 周期・spec §4.3）."""
    tc = np.mod(t, CYCLE_S)
    out = np.empty(len(t), dtype=object)
    for start, name in _PHASES:
        out[tc >= start] = name
    return out


def _cycle_t(t: np.ndarray) -> np.ndarray:
    return np.mod(t, CYCLE_S)


def veh_spd(t: np.ndarray) -> np.ndarray:
    """自車速 km/h — 定常 80・減速で 55 まで・復帰で 80 へ（滑らかな折れ線）."""
    tc = _cycle_t(t)
    pts_t = [0.0, 60.0, 120.0, 180.0, 240.0, 300.0]
    pts_v = [80.0, 80.0, 55.0, 60.0, 60.0, 80.0]
    return np.interp(tc, pts_t, pts_v)


def lead_dist(t: np.ndarray) -> np.ndarray:
    """先行車距離 m — 減速で詰まり・カットインで一段近づく."""
    tc = _cycle_t(t)
    pts_t = [0.0, 60.0, 120.0, 125.0, 180.0, 240.0, 300.0]
    pts_v = [45.0, 45.0, 28.0, 20.0, 26.0, 30.0, 45.0]
    return np.interp(tc, pts_t, pts_v)


def ttc(t: np.ndarray) -> np.ndarray:
    """TTC 秒 — lead_decel 区間で単調減少（相対速度から粗く算出・下限 1.5s）."""
    tc = _cycle_t(t)
    base = lead_dist(t) / np.maximum((veh_spd(t) - lead_spd(t)) / 3.6, 0.5)
    return np.clip(np.where(tc < 60.0, 99.0, base), 1.5, 99.0)


def lead_spd(t: np.ndarray) -> np.ndarray:
    """先行車速 km/h."""
    tc = _cycle_t(t)
    pts_t = [0.0, 60.0, 120.0, 180.0, 240.0, 300.0]
    pts_v = [80.0, 80.0, 50.0, 58.0, 60.0, 80.0]
    return np.interp(tc, pts_t, pts_v)


def brk_press(t: np.ndarray) -> np.ndarray:
    """ブレーキ圧 bar — 減速区間で立ち上がる."""
    tc = _cycle_t(t)
    return np.where((tc >= 65.0) & (tc < 125.0), 18.0, 0.0) + np.where(
        (tc >= 120.0) & (tc < 130.0), 12.0, 0.0
    )


def aeb_warn_level(t: np.ndarray) -> np.ndarray:
    """AEB 警報レベル 0/1/2 — TTC 閾値で遷移（enum 生値・LD-07 現状）."""
    v = ttc(t)
    return np.where(v < 3.0, 2.0, np.where(v < 6.0, 1.0, 0.0))


def radar_obj(t: np.ndarray, slot: int, attr: str) -> np.ndarray:
    """レーダー物標 slot=0..7 の属性 — slot0=先行車・slot1=カットイン車・他は遠方固定."""
    tc = _cycle_t(t)
    if slot == 0:
        base = {
            "dx": lead_dist(t),
            "dy": np.zeros(len(t)),
            "vx": (lead_spd(t) - veh_spd(t)) / 3.6,
            "vy": np.zeros(len(t)),
            "ExistProb": np.full(len(t), 0.98),
        }[attr]
        return base
    if slot == 1:  # カットイン車: cutin 区間で隣車線から dy→0 へ
        in_scene = (tc >= 110.0) & (tc < 180.0)
        dy = np.where(tc < 125.0, np.interp(tc, [110.0, 125.0], [3.5, 0.0]), 0.0)
        vals = {
            "dx": np.interp(tc, [110.0, 125.0, 180.0], [35.0, 20.0, 26.0]),
            "dy": dy,
            "vx": np.full(len(t), -1.0),
            "vy": np.where(tc < 125.0, -0.8, 0.0),
            "ExistProb": np.full(len(t), 0.9),
        }[attr]
        return np.where(in_scene, vals, np.nan)  # 非存在スロットは NaN（本番表現）
    # slot 2..7: 遠方の静的物標（slot ごとに位置をずらす・常時存在）
    offs = float(slot) * 15.0
    return {
        "dx": np.full(len(t), 80.0 + offs),
        "dy": np.full(len(t), -3.5 + (slot % 3) * 3.5),
        "vx": np.zeros(len(t)),
        "vy": np.zeros(len(t)),
        "ExistProb": np.full(len(t), 0.6),
    }[attr]


def cam_obj(t: np.ndarray, slot: int, attr: str) -> np.ndarray:
    """カメラ物標 — レーダーと同物標だが cam_lost 区間（180-240s）は全 NaN."""
    tc = _cycle_t(t)
    attr_map = {"dx": "dx", "dy": "dy", "vx": "vx", "TypeClass": "ExistProb"}
    base = radar_obj(t, slot, attr_map[attr])
    if attr == "TypeClass":
        base = np.where(np.isfinite(base), float(2 if slot < 2 else 1), np.nan)
    return np.where((tc >= 180.0) & (tc < 240.0), np.nan, base)


def cluster_surr(t: np.ndarray, slot: int, attr: str) -> np.ndarray:
    """メーター表示の周辺車両 slot=0..5 — レーダー物標のうち近傍を表示（ETH）."""
    src = radar_obj(t, slot if slot < 2 else slot + 2, {"RelX": "dx", "RelY": "dy", "Type": "ExistProb"}[attr])
    if attr == "Type":
        return np.where(np.isfinite(src), 1.0, 0.0)
    return src


def add_noise(values: np.ndarray, scale: float, rng: np.random.Generator) -> np.ndarray:
    """NaN を保ったまま計測ノイズを付与（本番風の微振動）."""
    return values + np.where(np.isfinite(values), rng.normal(0.0, scale, len(values)), 0.0)
```

（本タスクではここまで。`main()`/書き出しは Task 2-3。`if __name__ == "__main__":` は Task 3 で追加。）

- [ ] **Step 4: Run tests / gates**

Run: `uv run pytest tests/test_demo_mf4.py -v` → PASS。
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/` → 全緑。

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_demo_mf4.py tests/test_demo_mf4.py
git commit -m "feat(scripts): HILS デモ mf4 のシナリオ関数群（ACC 追従 300s 周期・決定的）"
```

---

## Task 2: グループ定義＋MDF チャンク書き出しコア

**Files:**
- Modify: `scripts/generate_demo_mf4.py`
- Test: `tests/test_demo_mf4.py`（追加）

**Interfaces:**
- Produces: `GROUPS: list[GroupDef]`（`GroupDef(name, rate_s, jitter_pct, bus, signals: list[SigDef])`・`SigDef(name, fn, unit, dtype, conv, ndim)`）。`build_group_signals(g, t0, t1, seed, chunk_idx) -> tuple[np.ndarray, list[asammdf.Signal]]`（区間 [t0,t1) のタイムスタンプ＋Signal 群）。`write_mf4(out, profile, seed, dirty, progress) -> Path` — append→extend のチャンク書き出し。

**設計要点（実装時に必ず確認・プランの前提）:**
- `MDF.extend(index, signals)` のシグネチャ・「先頭要素=マスタ (timestamps, None)」要件を **asammdf 実ソースで確認**する。extend が使えない/挙動不一致の場合のフォールバック: チャンクごとに小 MDF を生成し `MDF.concatenate` で結合（メモリはチャンク分に留まる）— どちらを採ったか report に明記。
- CAN 信号の「整数 raw＋線形変換」は asammdf の `Signal(samples=int16_array, conversion=from_dict({"a": factor, "b": offset}))` で格納（読み側は物理値の float で受ける）。**物理値→raw の逆変換（`np.round((phys - b) / a)`）で int16 に収まるよう factor を選ぶ**。
- source メタ: `asammdf.Source`（`source_type`/`bus_type`）。valisync の `mdf4_loader._BUS_TYPE_MAP` を読み、CAN/Ethernet に正しくマップされる bus_type 値を使う（XCP グループは source 名 `XCP:HILS_ECU`・bus なし）。
- (b) 2D チャンネル: `Radar.ObjMatrix` = shape (N, 8) の float64（8物標の dx を行列化）を `XCP_10ms_Struct` に 2本。asammdf が配列チャンネルとして書けることを確認（不可なら CN template 方式を調査し、それでも不可なら report で相談）。

- [ ] **Step 1: Write the failing tests**

```python
def test_smoke_mf4_roundtrip(tmp_path):
    out = gen.write_mf4(
        out=tmp_path / "smoke.mf4", profile=gen.PROFILES["smoke"], seed=42,
        dirty=False, progress=False,
    )
    from asammdf import MDF

    with MDF(str(out)) as mdf:
        names = {ch.name for group in mdf.groups for ch in group.channels}
        assert "VehSpd" in names and "Radar.Obj[0].dx" in names
        assert "Cluster.SurrVeh[0].RelX" in names
        assert "Radar.ObjMatrix" in names  # (b) 2D チャンネル
        spd = mdf.get("VehSpd")
        assert spd.samples.dtype == np.float64 or np.issubdtype(spd.samples.dtype, np.floating)
        assert 70.0 < float(np.nanmean(spd.samples)) < 90.0  # 物理値変換が効いている
        assert str(spd.unit).strip() in ("km/h", "km/h ")


def test_smoke_reproducible_same_seed(tmp_path):
    a = gen.write_mf4(out=tmp_path / "a.mf4", profile=gen.PROFILES["smoke"], seed=7, dirty=False, progress=False)
    b = gen.write_mf4(out=tmp_path / "b.mf4", profile=gen.PROFILES["smoke"], seed=7, dirty=False, progress=False)
    from asammdf import MDF

    with MDF(str(a)) as ma, MDF(str(b)) as mb:
        assert np.array_equal(ma.get("VehSpd").samples, mb.get("VehSpd").samples)
```

- [ ] **Step 2: RED 確認** → `uv run pytest tests/test_demo_mf4.py -k smoke -v` FAIL（write_mf4 未定義）。

- [ ] **Step 3: Implement — グループ定義と書き出し**

`GroupDef`/`SigDef` を定義し、spec §4.2 の表どおりに `GROUPS` を構築:

- `XCP_1ms`（1ms・bus なし）: 主要 12ch（`ACC.TargetAccel [m/s^2]`・`ACC.SetSpeed [km/h]`・`ACC.TimeGap [s]`・`ACC.State`・`AEB.TTC [s]`=ttc・`AEB.State`・`AEB.WarnLevel`=aeb_warn_level・`LKA.SteerTrqCmd [Nm]`・`LKA.State`・`VehSpdInternal [km/h]`=veh_spd＋ノイズ・`LeadDist [m]`・`LeadSpd [km/h]`）＋ **`Ctrl.Internal[00..47]`（48ch・veh_spd/ttc 等の位相シフト合成＋ノイズで埋める）** = 計 60ch。
- `XCP_10ms`（10ms）: `Radar.Obj[0..7].{dx,dy,vx,vy,ExistProb}`（radar_obj・40ch）＋`Cam.Obj[0..7].{dx,dy,vx,TypeClass}`（cam_obj・32ch）＋`Cam.Lane.{C0,C1,Curvature,Quality}`（4ch・穏やかな正弦＋cam_lost 区間 NaN）。
- `XCP_10ms_Struct`（10ms）: `Radar.ObjMatrix`（N×8: 各 slot の dx）・`Cam.ObjMatrix`（N×8: 各 slot の dx）— 2D。
- `VehDyn_10ms`（10ms・jitter 5%・CAN1）: `VehSpd [km/h]`（raw int16, a=0.01）・`YawRate [deg/s]`（a=0.01）・`StrAngle [deg]`（a=0.1）・`WhlSpd_FL/FR/RL/RR [km/h]`（veh_spd±微差・a=0.01）。
- `PwrTrq_20ms`（20ms・jitter 5%・CAN1）: `EngTrq [Nm]`（a=0.5）・`MotTrq [Nm]`・`AccelPdl [%]`（a=0.4）・`BrkPress [bar]`（a=0.1）。
- `BodyInfo_100ms`（100ms・jitter 10%・CAN1）: `TurnSig`（enum: 0=OFF/1=LEFT/2=RIGHT — cutin 前に 1 を数秒・value2text conversion 埋込）・`GearPos`・`DoorState`。
- `Cluster_100ms`（100ms・ETH1）: `Cluster.SurrVeh[0..5].{RelX,RelY,Type}`（cluster_surr・18ch）＋`Cluster.ACCIcon`・`Cluster.LaneStat`・`Cluster.WarnMsg`（aeb_warn_level 連動）。

タイムスタンプ生成: 周期 `rate_s`、ジッタは `rng.uniform(-j, j) * rate_s` を**間隔に**加算し cumsum（常に単調）。チャンク境界は決定的（`t0 = chunk_idx * chunk_s`）で、間隔ノイズの rng は `default_rng(seed*1000 + group_id*100 + chunk_idx)`。

`write_mf4` の骨子:

```python
def write_mf4(out: Path, profile: Profile, seed: int, dirty: bool, progress: bool) -> Path:
    from asammdf import MDF

    out.parent.mkdir(parents=True, exist_ok=True)
    mdf = MDF(version="4.10")
    n_chunks = int(np.ceil(profile.duration_s / profile.chunk_s))
    for ci in range(n_chunks):
        t0 = ci * profile.chunk_s
        t1 = min(t0 + profile.chunk_s, profile.duration_s)
        for gi, g in enumerate(GROUPS):
            ts, sigs = build_group_signals(g, t0, t1, seed, ci)
            if dirty and g.name == "VehDyn_10ms":
                ts = _inject_dirty(ts, seed, ci)  # 重複数十点＋非単調数点（LD-03/04 デモ）
            if ci == 0:
                mdf.append(sigs, comment=g.name)  # グループ作成（index=gi を前提に順序固定）
            else:
                mdf.extend(gi, [(ts, None)] + [(s.samples, None) for s in sigs])
        if progress:
            print(f"chunk {ci + 1}/{n_chunks} ({t1:.0f}s)")  # noqa: T201
    mdf.save(str(out), overwrite=True)
    mdf.close()
    return out
```

（extend の実シグネチャ確認結果に合わせて調整。`_inject_dirty` は間隔配列の末尾側に 0 を数十点・負値を数点混ぜて cumsum。）

- [ ] **Step 4: Run tests / gates** → smoke roundtrip＋再現性 PASS・全体ゲート緑。

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_demo_mf4.py tests/test_demo_mf4.py
git commit -m "feat(scripts): CANape 風グループ定義とチャンク書き出し（raw+線形変換・2D 併録）"
```

---

## Task 3: CLI・dirty 注入・gitignore

**Files:**
- Modify: `scripts/generate_demo_mf4.py`（`main()`）
- Modify: `.gitignore`
- Test: `tests/test_demo_mf4.py`（追加）

- [ ] **Step 1: Write the failing tests**

```python
def test_cli_smoke_generates_file(tmp_path):
    out = tmp_path / "cli.mf4"
    rc = gen.main(["--out", str(out), "--profile", "smoke", "--seed", "1"])
    assert rc == 0 and out.exists() and out.stat().st_size > 100_000


def test_dirty_injects_non_monotonic(tmp_path):
    out = tmp_path / "d.mf4"
    gen.main(["--out", str(out), "--profile", "smoke", "--seed", "1", "--dirty"])
    from asammdf import MDF

    with MDF(str(out)) as mdf:
        spd = mdf.get("VehSpd")
        d = np.diff(spd.timestamps)
        assert np.any(d <= 0)  # 重複または非単調が実在
```

- [ ] **Step 2: RED 確認**（main 未定義）。

- [ ] **Step 3: Implement — main()**

```python
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="HILS デモ mf4 ジェネレータ")
    p.add_argument("--out", type=Path, default=Path("demo_data/hils_demo.mf4"))
    p.add_argument("--profile", choices=sorted(PROFILES), default="hils")
    p.add_argument("--duration", type=float, default=None, help="秒（プロファイル既定の上書き）")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--dirty", action="store_true", help="CAN に重複/非単調タイムスタンプを注入")
    a = p.parse_args(argv)
    prof = PROFILES[a.profile]
    if a.duration is not None:
        prof = Profile(duration_s=a.duration, chunk_s=min(prof.chunk_s, a.duration))
    out = write_mf4(out=a.out, profile=prof, seed=a.seed, dirty=a.dirty, progress=True)
    print(f"wrote {out} ({out.stat().st_size / 1e9:.2f} GB)")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`.gitignore` に `demo_data/` を追加。

- [ ] **Step 4: Run tests / gates** → PASS・全緑。

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_demo_mf4.py tests/test_demo_mf4.py .gitignore
git commit -m "feat(scripts): デモ mf4 の CLI（プロファイル/seed/dirty）と demo_data ignore"
```

---

## Task 4: valisync 統合テスト＋docs＋catalog LD-12 追補

**Files:**
- Test: `tests/test_demo_mf4.py`（追加）
- Modify: `docs/development.md`・`docs/audit-findings-catalog.md`

- [ ] **Step 1: 統合テスト（Layer A・smoke）**

```python
def test_valisync_loads_smoke_profile(tmp_path):
    out = tmp_path / "v.mf4"
    gen.main(["--out", str(out), "--profile", "smoke", "--seed", "1"])
    from valisync.core.session import Session

    session = Session()
    outcome = session.load(out)
    sigs = session.group_signals(outcome.key)
    names = {s.name.split("::", 1)[1] for s in sigs}
    assert "VehSpd" in names and "Radar.Obj[0].dx" in names
    # (b) 2D チャンネルは skip され警告が出る（spec §4.2/LD-12 の現状再現）
    assert any(
        "2D" in d.message or "skipped" in d.message for d in outcome.diagnostics
    )
    assert not any(d.level == "error" for d in outcome.diagnostics)


def test_valisync_dirty_shows_nonmonotonic_warning(tmp_path):
    out = tmp_path / "vd.mf4"
    gen.main(["--out", str(out), "--profile", "smoke", "--seed", "1", "--dirty"])
    from valisync.core.session import Session

    outcome = Session().load(out)
    assert any("非単調" in d.message or "重複" in d.message for d in outcome.diagnostics)
```

- [ ] **Step 2: docs/development.md に使い方節**

「デモデータ（本番相当 mf4）」節: 生成コマンド3種（hils/quick/smoke）・所要時間とサイズ目安・実機確認手順（quick で機能確認 → hils でロード時間/メモリ/**FB-04 キャンセルの実用性**を確認。**hils が重いのは LD-10 未対応の現行仕様であり、この実測が第3弾の優先度判断材料になる**旨を明記）・`--dirty` の説明。

- [ ] **Step 3: catalog に LD-12 追補**

`docs/audit-findings-catalog.md` の SS-LOADERS 表末尾に追加:

```markdown
| LD-12 | 🟠 | 多次元/構造化チャンネル（本番の物標配列 (b) パターン）が「2D samples, skipped」で表示不能。HILS デモ mf4（scripts/generate_demo_mf4.py）の `Radar.ObjMatrix` が再現データ | `core/loaders/mdf4_loader.py`（2D skip 分岐） | CANape 計測の物標リストが構造化格納だと丸ごと見えない（LD-07 と統合検討・第3弾） |
```

- [ ] **Step 4: Run tests / gates → Commit**

```bash
git add tests/test_demo_mf4.py docs/development.md docs/audit-findings-catalog.md
git commit -m "test+docs: デモ mf4 の valisync 統合テスト・使い方・catalog LD-12 追補"
```

---

## Task 5: hils キャリブレーション（ローカル実測・±20% 調整）

**目的:** hils プロファイルを1回実生成し、サイズを 2GB±20% に合わせ、生成時間を記録する。**2GB の valisync ロード実測はしない**（ユーザーの実機確認に委ねる — Global Constraints）。

- [ ] **Step 1:** `uv run python scripts/generate_demo_mf4.py --profile hils --out demo_data/hils_demo.mf4` を実行（分オーダー・進捗表示）。
- [ ] **Step 2:** 実測サイズが 1.6-2.4 GB を外れる場合は `Ctrl.Internal[NN]` の本数（XCP_1ms の ch 数）を調整して再生成（コード定数の変更＋テスト影響確認）。
- [ ] **Step 3:** 実測結果（サイズ・生成時間・ピークメモリ概算）を docs/development.md の使い方節に追記。quick も1回生成して同様に記録。
- [ ] **Step 4:** 全体ゲート→Commit（調整があった場合）。

```bash
git add scripts/generate_demo_mf4.py docs/development.md
git commit -m "chore(scripts): hils プロファイルのサイズ実測とキャリブレーション"
```

---

## Self-Review

**1. Spec coverage:** §2 成果物（script/demo_data ignore/docs節/LD-12 追補/CI smoke）→ T1-T5 ✓。§4.1 プロファイル→T1・§4.2 グループ→T2・§4.3 シナリオ→T1・§4.4 dirty→T2/T3・§4.5 チャンク/CLI→T2/T3 ✓。§5 検証（CI smoke・実機手順 docs）→T4 ✓。§6（extend index 固定・rng 独立ストリーム・時刻関数の決定性）→T1/T2 に反映 ✓。非ゴール（2GB ロード実測しない）→ Global Constraints＋T5 ✓。
**2. Placeholder scan:** T2 の GROUPS 詳細は表形式の完全仕様（信号名・生成関数・単位・変換係数）で列挙済み。asammdf API（extend/Source/2D）の3点は「実装時にソース確認＋フォールバック明記」の指示付き — 外部ライブラリ挙動のため実装時検証が正当。
**3. Type consistency:** `Profile(duration_s, chunk_s)`・`write_mf4(out, profile, seed, dirty, progress)`・`main(argv) -> int` は T1 定義＝T2-T5 使用で一貫。テストの関数名・シナリオ関数シグネチャ（`t: np.ndarray, slot, attr`）も全タスクで一致。
