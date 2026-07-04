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
    t = np.arange(0.0, 300.0, 0.5)
    assert np.array_equal(
        gen.veh_spd(t), gen.veh_spd(t.copy())
    )  # 時刻の関数 = チャンク分割非依存


def test_profiles_defined():
    assert set(gen.PROFILES) == {"hils", "quick", "smoke"}
    assert gen.PROFILES["hils"].duration_s == 3600.0
    assert gen.PROFILES["smoke"].duration_s <= 15.0
