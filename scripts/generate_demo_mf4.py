"""HILS デモ mf4 ジェネレータ — 本番 (ADAS HILS・CANape 計測) 相当の実機確認データ.

spec: docs/superpowers/specs/2026-07-04-hils-demo-mf4-generator-design.md
値は「時刻の決定的関数 + seed 派生ノイズ」— チャンク分割に依存せず再現可能。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CYCLE_S = 300.0  # ACC 追従シナリオの1サイクル (spec §4.3)


@dataclass(frozen=True)
class Profile:
    duration_s: float
    chunk_s: float  # extend 1回分 (ピークメモリの上限を決める)


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
    """各時刻のシナリオフェーズ名 (300s 周期・spec §4.3)."""
    tc = np.mod(t, CYCLE_S)
    out = np.empty(len(t), dtype=object)
    for start, name in _PHASES:
        out[tc >= start] = name
    return out


def _cycle_t(t: np.ndarray) -> np.ndarray:
    return np.mod(t, CYCLE_S)


def veh_spd(t: np.ndarray) -> np.ndarray:
    """自車速 km/h — 定常 80・減速で 58 まで (先行車より応答遅れ)・復帰で 80 へ."""
    tc = _cycle_t(t)
    pts_t = [0.0, 60.0, 115.0, 125.0, 180.0, 240.0, 300.0]
    pts_v = [80.0, 80.0, 62.0, 58.0, 60.0, 60.0, 80.0]
    return np.interp(tc, pts_t, pts_v)


def lead_dist(t: np.ndarray) -> np.ndarray:
    """先行車距離 m — 減速で急接近 (AEB 発火域) してから復帰・カットインへ.

    120s 到達前 (tc=115) に最接近させ、以降は急速に開ける — カットイン車
    (dx 最大35m) より先行車が遠い状態を tc=120 まで保つため (物標スロット
    入替テストとの整合・spec §4.3-3)。
    """
    tc = _cycle_t(t)
    pts_t = [0.0, 60.0, 100.0, 115.0, 120.0, 125.0, 180.0, 300.0]
    pts_v = [45.0, 45.0, 25.0, 8.0, 32.0, 34.0, 26.0, 45.0]
    return np.interp(tc, pts_t, pts_v)


def ttc(t: np.ndarray) -> np.ndarray:
    """TTC 秒 — lead_decel 区間で単調減少・AEB 発火域まで下げる (下限 1.5s)."""
    tc = _cycle_t(t)
    base = lead_dist(t) / np.maximum((veh_spd(t) - lead_spd(t)) / 3.6, 0.5)
    return np.clip(np.where(tc < 60.0, 99.0, base), 1.5, 99.0)


def lead_spd(t: np.ndarray) -> np.ndarray:
    """先行車速 km/h."""
    tc = _cycle_t(t)
    pts_t = [0.0, 60.0, 110.0, 120.0, 180.0, 240.0, 300.0]
    pts_v = [80.0, 80.0, 45.0, 55.0, 60.0, 60.0, 80.0]
    return np.interp(tc, pts_t, pts_v)


def brk_press(t: np.ndarray) -> np.ndarray:
    """ブレーキ圧 bar — 減速区間で立ち上がる."""
    tc = _cycle_t(t)
    return np.where((tc >= 65.0) & (tc < 125.0), 18.0, 0.0) + np.where(
        (tc >= 120.0) & (tc < 130.0), 12.0, 0.0
    )


def aeb_warn_level(t: np.ndarray) -> np.ndarray:
    """AEB 警報レベル 0/1/2 — TTC 閾値で遷移 (enum 生値・LD-07 現状)."""
    v = ttc(t)
    return np.where(v < 3.0, 2.0, np.where(v < 6.0, 1.0, 0.0))


def _lead_track(t: np.ndarray, attr: str) -> np.ndarray:
    """先行車の軌跡 (従来 slot0) — カットイン完了後は slot1 に降格する追跡対象."""
    return {
        "dx": lead_dist(t),
        "dy": np.zeros(len(t)),
        "vx": (lead_spd(t) - veh_spd(t)) / 3.6,
        "vy": np.zeros(len(t)),
        "ExistProb": np.full(len(t), 0.98),
    }[attr]


def _cutin_track(t: np.ndarray, attr: str) -> np.ndarray:
    """カットイン車の軌跡 (従来 slot1) — cutin 区間で隣車線から dy→0 へ."""
    tc = _cycle_t(t)
    in_scene = (tc >= 110.0) & (tc < 180.0)
    dy = np.where(tc < 125.0, np.interp(tc, [110.0, 125.0], [3.5, 0.0]), 0.0)
    vals = {
        "dx": np.interp(tc, [110.0, 125.0, 180.0], [35.0, 20.0, 26.0]),
        "dy": dy,
        "vx": np.full(len(t), -1.0),
        "vy": np.where(tc < 125.0, -0.8, 0.0),
        "ExistProb": np.full(len(t), 0.9),
    }[attr]
    return np.where(in_scene, vals, np.nan)  # 非存在スロットは NaN (本番表現)


def radar_obj(t: np.ndarray, slot: int, attr: str) -> np.ndarray:
    """レーダー物標 slot=0..7 の属性.

    カットイン完了 (tc=125) でトラック→スロットの割当を入替える (spec §4.3-3):
    割込み車が先行車スロット (0) を乗っ取り、旧先行車は slot1 に降格する。
    """
    tc = _cycle_t(t)
    if slot == 0:
        return np.where(tc < 125.0, _lead_track(t, attr), _cutin_track(t, attr))
    if slot == 1:
        old_lead = _lead_track(t, attr) + (15.0 if attr == "dx" else 0.0)
        return np.where(
            (tc >= 110.0) & (tc < 125.0),
            _cutin_track(t, attr),
            np.where((tc >= 125.0) & (tc < 180.0), old_lead, np.nan),
        )
    # slot 2..7: 遠方の静的物標 (slot ごとに位置をずらす・常時存在)
    offs = float(slot) * 15.0
    return {
        "dx": np.full(len(t), 80.0 + offs),
        "dy": np.full(len(t), -3.5 + (slot % 3) * 3.5),
        "vx": np.zeros(len(t)),
        "vy": np.zeros(len(t)),
        "ExistProb": np.full(len(t), 0.6),
    }[attr]


def cam_obj(t: np.ndarray, slot: int, attr: str) -> np.ndarray:
    """カメラ物標 — レーダーと同物標だが cam_lost 区間 (180-240s) は全 NaN."""
    tc = _cycle_t(t)
    attr_map = {"dx": "dx", "dy": "dy", "vx": "vx", "TypeClass": "ExistProb"}
    base = radar_obj(t, slot, attr_map[attr])
    if attr == "TypeClass":
        base = np.where(np.isfinite(base), float(2 if slot < 2 else 1), np.nan)
    return np.where((tc >= 180.0) & (tc < 240.0), np.nan, base)


def cluster_surr(t: np.ndarray, slot: int, attr: str) -> np.ndarray:
    """メーター表示の周辺車両 slot=0..5 — レーダー物標のうち近傍を表示 (ETH)."""
    src = radar_obj(
        t,
        slot if slot < 2 else slot + 2,
        {"RelX": "dx", "RelY": "dy", "Type": "ExistProb"}[attr],
    )
    if attr == "Type":
        return np.where(np.isfinite(src), 1.0, 0.0)
    return src


def add_noise(values: np.ndarray, scale: float, rng: np.random.Generator) -> np.ndarray:
    """NaN を保ったまま計測ノイズを付与 (本番風の微振動)."""
    return values + np.where(
        np.isfinite(values), rng.normal(0.0, scale, len(values)), 0.0
    )
