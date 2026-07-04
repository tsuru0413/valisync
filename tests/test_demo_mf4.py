"""HILS デモ mf4 ジェネレータのテスト (scripts/ を sys.path 経由で import)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_demo_mf4 as gen


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
    # チャンク分割非依存の実質検証: 分割呼び出しと一括呼び出しが一致すること
    # (単純な同一引数の再呼び出しでは分割経路のバグを検出できない)。
    t = np.arange(0.0, 300.0, 0.5)
    assert np.array_equal(
        gen.veh_spd(t), np.concatenate([gen.veh_spd(t[:100]), gen.veh_spd(t[100:])])
    )


def test_profiles_defined():
    assert set(gen.PROFILES) == {"hils", "quick", "smoke"}
    assert gen.PROFILES["hils"].duration_s == 3600.0
    assert gen.PROFILES["smoke"].duration_s <= 15.0


def test_aeb_warn_level_escalates_through_1_and_2():
    t = np.arange(0.0, 300.0, 0.1)
    lv = gen.aeb_warn_level(t)
    assert set(np.unique(lv)) == {0.0, 1.0, 2.0}
    assert float(np.min(gen.ttc(t))) < 3.0
    # 遷移が減速〜カットイン窓 (60-130s) の中で起きる
    idx1 = int(np.argmax(lv >= 1.0))
    idx2 = int(np.argmax(lv >= 2.0))
    assert 60.0 <= t[idx1] <= 130.0
    assert t[idx1] <= t[idx2] <= 130.0


def test_object_slot_swap_at_cutin_completion():
    before = np.array([120.0])
    after = np.array([130.0])
    # 入替前: slot0=先行車 (遠め)・slot1=割込み車 (接近中) が別物標として共存
    assert gen.radar_obj(before, 0, "dx")[0] > gen.radar_obj(before, 1, "dx")[0]
    # 入替後: slot0=旧割込み車 (近)・slot1=旧先行車 (遠・+15m 付近)
    d0, d1 = gen.radar_obj(after, 0, "dx")[0], gen.radar_obj(after, 1, "dx")[0]
    assert np.isfinite(d0) and np.isfinite(d1) and d1 > d0 + 5.0


def test_add_noise_perturbs_finite_and_keeps_nan():
    values = np.array([10.0, np.nan, 20.0])
    rng = np.random.default_rng(1)
    noisy = gen.add_noise(values, scale=1.0, rng=rng)
    assert np.isnan(noisy[1])
    assert np.all(np.isfinite(noisy[[0, 2]]))
    assert not np.array_equal(noisy[[0, 2]], values[[0, 2]])  # 摂動が乗る


def test_add_noise_deterministic_for_same_seed():
    values = np.array([10.0, np.nan, 20.0])
    a = gen.add_noise(values, scale=1.0, rng=np.random.default_rng(5))
    b = gen.add_noise(values, scale=1.0, rng=np.random.default_rng(5))
    assert np.array_equal(a, b, equal_nan=True)
