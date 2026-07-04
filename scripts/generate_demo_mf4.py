"""HILS デモ mf4 ジェネレータ — 本番 (ADAS HILS・CANape 計測) 相当の実機確認データ.

spec: docs/superpowers/specs/2026-07-04-hils-demo-mf4-generator-design.md
値は「時刻の決定的関数 + seed 派生ノイズ」— チャンク分割に依存せず再現可能。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from asammdf import MDF, Signal, Source

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


# --- 追加シナリオ信号 (ACC/AEB/LKA/パワトレ/ボディ/メーター・spec §4.2 表埋め) ---
# CANape 実ログに近づけるための単純な決定的関数群 — 物理的厳密さより
# 「グループ表を全チャンネル埋める・値が読める範囲に収まる」ことを優先する。


def acc_target_accel(t: np.ndarray) -> np.ndarray:
    """ACC 目標加速度 m/s^2 — 先行車との速度差に比例 (簡易 P 制御相当)."""
    return np.clip((lead_spd(t) - veh_spd(t)) / 3.6 / 2.0, -3.5, 2.0)


def acc_set_speed(t: np.ndarray) -> np.ndarray:
    """ACC 設定車速 km/h — ドライバー設定値 (シナリオ通して固定)."""
    return np.full(len(t), 80.0)


def acc_time_gap(t: np.ndarray) -> np.ndarray:
    """ACC 車間タイムギャップ設定 s — 固定値."""
    return np.full(len(t), 1.8)


def acc_state(t: np.ndarray) -> np.ndarray:
    """ACC 状態 (0=OFF/1=巡航/2=追従) — 先行車近接時に追従へ遷移."""
    return np.where(lead_dist(t) < 60.0, 2.0, 1.0)


def aeb_state(t: np.ndarray) -> np.ndarray:
    """AEB 状態 (0=待機/1=作動) — WarnLevel エスカレーションに連動."""
    return np.where(aeb_warn_level(t) > 0.0, 1.0, 0.0)


def lka_steer_trq_cmd(t: np.ndarray) -> np.ndarray:
    """LKA 操舵トルク指令 Nm — 車線内微修正を模した緩やかな振動."""
    return 2.0 * np.sin(2.0 * np.pi * t / 9.0)


def lka_state(t: np.ndarray) -> np.ndarray:
    """LKA 状態 (1=作動) — シナリオ通して有効."""
    return np.ones(len(t))


def cam_lane_c0(t: np.ndarray) -> np.ndarray:
    """カメラ車線オフセット m (C0) — 穏やかな正弦、cam_lost 区間は NaN."""
    tc = _cycle_t(t)
    v = 0.15 * np.sin(2.0 * np.pi * t / 23.0)
    return np.where((tc >= 180.0) & (tc < 240.0), np.nan, v)


def cam_lane_c1(t: np.ndarray) -> np.ndarray:
    """カメラ車線角度 rad (C1) — 穏やかな正弦、cam_lost 区間は NaN."""
    tc = _cycle_t(t)
    v = 0.01 * np.sin(2.0 * np.pi * t / 31.0)
    return np.where((tc >= 180.0) & (tc < 240.0), np.nan, v)


def cam_lane_curvature(t: np.ndarray) -> np.ndarray:
    """カメラ車線曲率 1/m — 穏やかな正弦、cam_lost 区間は NaN."""
    tc = _cycle_t(t)
    v = 0.0005 * np.sin(2.0 * np.pi * t / 47.0)
    return np.where((tc >= 180.0) & (tc < 240.0), np.nan, v)


def cam_lane_quality(t: np.ndarray) -> np.ndarray:
    """カメラ車線検出信頼度 (0-1) — cam_lost 区間は NaN (未検出)."""
    tc = _cycle_t(t)
    v = np.full(len(t), 0.95)
    return np.where((tc >= 180.0) & (tc < 240.0), np.nan, v)


def eng_trq(t: np.ndarray) -> np.ndarray:
    """エンジントルク Nm — ACC 目標加速度に応じて増減."""
    return np.clip(80.0 + 40.0 * acc_target_accel(t), 0.0, 260.0)


def mot_trq(t: np.ndarray) -> np.ndarray:
    """モータトルク Nm — 減速時は回生 (負値) 側に振れる."""
    return np.clip(20.0 * acc_target_accel(t), -50.0, 50.0)


def accel_pdl(t: np.ndarray) -> np.ndarray:
    """アクセル開度 % — ACC 目標加速度に応じて増減."""
    return np.clip(20.0 + 15.0 * acc_target_accel(t), 0.0, 100.0)


def yaw_rate(t: np.ndarray) -> np.ndarray:
    """ヨーレート deg/s — カットイン前後の隣接車線幾何を簡易反映."""
    tc = _cycle_t(t)
    return np.where(
        (tc >= 108.0) & (tc < 126.0),
        3.0 * np.sin(2.0 * np.pi * (tc - 108.0) / 18.0),
        0.0,
    )


def str_angle(t: np.ndarray) -> np.ndarray:
    """操舵角 deg — ヨーレートと同じ窓で緩やかに動く."""
    tc = _cycle_t(t)
    return np.where(
        (tc >= 108.0) & (tc < 126.0),
        12.0 * np.sin(2.0 * np.pi * (tc - 108.0) / 18.0),
        0.0,
    )


def whl_spd(t: np.ndarray, corner: str) -> np.ndarray:
    """車輪速 km/h — 自車速 ± わずかな左右前後差 (VehSpd と同一ソースだが独立 CAN 信号)."""
    offs = {"FL": 0.05, "FR": -0.05, "RL": 0.03, "RR": -0.03}[corner]
    return veh_spd(t) + offs


def turn_sig(t: np.ndarray) -> np.ndarray:
    """ウインカー (0=OFF/1=LEFT/2=RIGHT) — カットイン直前に LEFT を数秒点灯."""
    tc = _cycle_t(t)
    return np.where((tc >= 113.0) & (tc < 120.0), 1.0, 0.0)


def gear_pos(t: np.ndarray) -> np.ndarray:
    """ギアポジション — D レンジ固定 (走行シナリオ想定)."""
    return np.full(len(t), 3.0)


def door_state(t: np.ndarray) -> np.ndarray:
    """ドア状態 (0=全閉) — 走行中は常に閉."""
    return np.zeros(len(t))


def cluster_acc_icon(t: np.ndarray) -> np.ndarray:
    """メーター ACC アイコン状態 — ACC.State に連動."""
    return acc_state(t)


def cluster_lane_stat(t: np.ndarray) -> np.ndarray:
    """メーター車線認識状態 (0=OK/1=ロスト) — cam_lost 区間に連動."""
    tc = _cycle_t(t)
    return np.where((tc >= 180.0) & (tc < 240.0), 1.0, 0.0)


def ctrl_internal(t: np.ndarray, idx: int) -> np.ndarray:
    """Ctrl.Internal[NN] — ECU 内部変数のダミー埋め (veh_spd/ttc の位相シフト合成).

    実データの「用途不明な内部変数群」を模すためだけの穴埋めチャンネルで、
    物理的な意味は持たない — 位相と重みを idx ごとにずらし重複を避ける。
    """
    phase = float(idx) * 2.5
    w = (idx % 4) / 4.0
    return w * veh_spd(t - phase) + (1.0 - w) * (5.0 * ttc(t - phase))


def _radar_obj_matrix(t: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Radar.ObjMatrix 用 (N, 8) 行列 — 各スロットの dx を列に持つ."""
    del rng  # 決定的信号 (ノイズ無し) — インターフェース統一のためだけの引数
    return np.stack([radar_obj(t, slot, "dx") for slot in range(8)], axis=1)


def _cam_obj_matrix(t: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Cam.ObjMatrix 用 (N, 8) 行列 — 各スロットの dx を列に持つ."""
    del rng
    return np.stack([cam_obj(t, slot, "dx") for slot in range(8)], axis=1)


# --- グループ/チャンネル定義 (spec §4.2) ---


@dataclass(frozen=True)
class SigDef:
    name: str
    fn: Callable[[np.ndarray, np.random.Generator], np.ndarray]
    unit: str = ""
    dtype: type = np.float64
    conv: dict[str, object] | None = None
    ndim: int = 1  # >1 の場合 fn は (N, ndim) の 2D 配列を返す (配列チャンネル)
    comment: str = ""  # value2text の代替となるラベル注記等 (Finding 3)


@dataclass(frozen=True)
class GroupDef:
    name: str
    rate_s: float
    jitter_pct: float
    bus: str | None  # None=XCP (バスなし)・"CAN1"/"ETH1" 等
    signals: list[SigDef]
    group_id: int  # rng seed 系列の分離用 (GROUPS 内での位置)


_RADAR_ATTR_UNITS: dict[str, str] = {
    "dx": "m",
    "dy": "m",
    "vx": "m/s",
    "vy": "m/s",
    "ExistProb": "",
}
_CAM_ATTR_UNITS: dict[str, str] = {"dx": "m", "dy": "m", "vx": "m/s", "TypeClass": ""}
_CLUSTER_ATTR_UNITS: dict[str, str] = {"RelX": "m", "RelY": "m", "Type": ""}


def _radar_signals() -> list[SigDef]:
    sigs: list[SigDef] = []
    for slot in range(8):
        for attr, unit in _RADAR_ATTR_UNITS.items():
            sigs.append(
                SigDef(
                    name=f"Radar.Obj[{slot}].{attr}",
                    fn=lambda t, rng, slot=slot, attr=attr: radar_obj(t, slot, attr),
                    unit=unit,
                )
            )
    return sigs


def _cam_signals() -> list[SigDef]:
    sigs: list[SigDef] = []
    for slot in range(8):
        for attr, unit in _CAM_ATTR_UNITS.items():
            sigs.append(
                SigDef(
                    name=f"Cam.Obj[{slot}].{attr}",
                    fn=lambda t, rng, slot=slot, attr=attr: cam_obj(t, slot, attr),
                    unit=unit,
                )
            )
    return sigs


def _cluster_signals() -> list[SigDef]:
    sigs: list[SigDef] = []
    for slot in range(6):
        for attr, unit in _CLUSTER_ATTR_UNITS.items():
            sigs.append(
                SigDef(
                    name=f"Cluster.SurrVeh[{slot}].{attr}",
                    fn=lambda t, rng, slot=slot, attr=attr: cluster_surr(t, slot, attr),
                    unit=unit,
                )
            )
    return sigs


def _ctrl_internal_signals() -> list[SigDef]:
    sigs: list[SigDef] = []
    for idx in range(48):
        sigs.append(
            SigDef(
                name=f"Ctrl.Internal[{idx:02d}]",
                fn=lambda t, rng, idx=idx: add_noise(ctrl_internal(t, idx), 0.5, rng),
            )
        )
    return sigs


def _build_groups() -> list[GroupDef]:
    xcp_1ms_main = [
        SigDef("ACC.TargetAccel", lambda t, rng: acc_target_accel(t), "m/s^2"),
        SigDef("ACC.SetSpeed", lambda t, rng: acc_set_speed(t), "km/h"),
        SigDef("ACC.TimeGap", lambda t, rng: acc_time_gap(t), "s"),
        SigDef("ACC.State", lambda t, rng: acc_state(t)),
        SigDef("AEB.TTC", lambda t, rng: ttc(t), "s"),
        SigDef("AEB.State", lambda t, rng: aeb_state(t)),
        SigDef("AEB.WarnLevel", lambda t, rng: aeb_warn_level(t)),
        SigDef("LKA.SteerTrqCmd", lambda t, rng: lka_steer_trq_cmd(t), "Nm"),
        SigDef("LKA.State", lambda t, rng: lka_state(t)),
        SigDef(
            "VehSpdInternal", lambda t, rng: add_noise(veh_spd(t), 0.2, rng), "km/h"
        ),
        SigDef("LeadDist", lambda t, rng: lead_dist(t), "m"),
        SigDef("LeadSpd", lambda t, rng: lead_spd(t), "km/h"),
    ]

    xcp_10ms = [
        *_radar_signals(),
        *_cam_signals(),
        SigDef("Cam.Lane.C0", lambda t, rng: cam_lane_c0(t)),
        SigDef("Cam.Lane.C1", lambda t, rng: cam_lane_c1(t)),
        SigDef("Cam.Lane.Curvature", lambda t, rng: cam_lane_curvature(t), "1/m"),
        SigDef("Cam.Lane.Quality", lambda t, rng: cam_lane_quality(t)),
    ]

    xcp_10ms_struct = [
        # dtype は uint8 (格納時の実表現・_pack_array_channel で量子化).
        SigDef("Radar.ObjMatrix", _radar_obj_matrix, "m", np.uint8, None, 8),
        SigDef("Cam.ObjMatrix", _cam_obj_matrix, "m", np.uint8, None, 8),
    ]

    veh_dyn = [
        SigDef(
            "VehSpd",
            lambda t, rng: add_noise(veh_spd(t), 0.15, rng),
            "km/h",
            np.int16,
            {"a": 0.01, "b": 0.0},
        ),
        SigDef(
            "YawRate",
            lambda t, rng: add_noise(yaw_rate(t), 0.1, rng),
            "deg/s",
            np.int16,
            {"a": 0.01, "b": 0.0},
        ),
        SigDef(
            "StrAngle",
            lambda t, rng: add_noise(str_angle(t), 0.2, rng),
            "deg",
            np.int16,
            {"a": 0.1, "b": 0.0},
        ),
        *[
            SigDef(
                f"WhlSpd_{corner}",
                lambda t, rng, corner=corner: add_noise(whl_spd(t, corner), 0.1, rng),
                "km/h",
                np.int16,
                {"a": 0.01, "b": 0.0},
            )
            for corner in ("FL", "FR", "RL", "RR")
        ],
    ]

    pwr_trq = [
        SigDef(
            "EngTrq",
            lambda t, rng: np.clip(add_noise(eng_trq(t), 2.0, rng), 0.0, 300.0),
            "Nm",
            np.int16,
            {"a": 0.5, "b": 0.0},
        ),
        SigDef(
            "MotTrq",
            lambda t, rng: np.clip(add_noise(mot_trq(t), 1.0, rng), -80.0, 80.0),
            "Nm",
            np.int16,
            {"a": 0.5, "b": 0.0},
        ),
        SigDef(
            "AccelPdl",
            lambda t, rng: np.clip(add_noise(accel_pdl(t), 0.5, rng), 0.0, 100.0),
            "%",
            np.int16,
            {"a": 0.4, "b": 0.0},
        ),
        SigDef(
            "BrkPress",
            lambda t, rng: np.clip(add_noise(brk_press(t), 0.3, rng), 0.0, 50.0),
            "bar",
            np.int16,
            {"a": 0.1, "b": 0.0},
        ),
    ]

    body_info = [
        SigDef(
            "TurnSig",
            lambda t, rng: turn_sig(t),
            "",
            np.uint8,
            # value2text (TABX) 埋込復活 (第3弾 LD-13/LD-07 で解消): 第2弾
            # Finding 3 で見送った Mdf4Loader の dead オプション問題
            # (ignore_value2text_conversions が MDF() に無効でテキスト化され
            # 「non-numeric, skipped」で消滅) は select() ベースの刷新で
            # 解消済み — 生値のまま生存し、metadata['value_labels'] にこの
            # 変換表が構造化保持される。Signal(conversion=dict) は asammdf
            # 側で from_dict() 相当の変換を内部的に行う (val_N/text_N の
            # ペア羅列が TABX 変換として解釈される)。
            {
                "val_0": 0,
                "text_0": "OFF",
                "val_1": 1,
                "text_1": "LEFT",
                "val_2": 2,
                "text_2": "RIGHT",
            },
            1,
            "0=OFF, 1=LEFT, 2=RIGHT",  # ラベルは comment にも維持 (人間可読の冗長化)
        ),
        SigDef("GearPos", lambda t, rng: gear_pos(t)),
        SigDef("DoorState", lambda t, rng: door_state(t)),
    ]

    cluster = [
        *_cluster_signals(),
        SigDef("Cluster.ACCIcon", lambda t, rng: cluster_acc_icon(t)),
        SigDef("Cluster.LaneStat", lambda t, rng: cluster_lane_stat(t)),
        SigDef("Cluster.WarnMsg", lambda t, rng: aeb_warn_level(t)),
    ]

    return [
        GroupDef(
            "XCP_1ms", 0.001, 0.0, None, [*xcp_1ms_main, *_ctrl_internal_signals()], 0
        ),
        GroupDef("XCP_10ms", 0.01, 0.0, None, xcp_10ms, 1),
        GroupDef("XCP_10ms_Struct", 0.01, 0.0, None, xcp_10ms_struct, 2),
        GroupDef("VehDyn_10ms", 0.01, 0.05, "CAN1", veh_dyn, 3),
        GroupDef("PwrTrq_20ms", 0.02, 0.05, "CAN1", pwr_trq, 4),
        GroupDef("BodyInfo_100ms", 0.1, 0.1, "CAN1", body_info, 5),
        GroupDef("Cluster_100ms", 0.1, 0.0, "ETH1", cluster, 6),
    ]


GROUPS: list[GroupDef] = _build_groups()


def _group_timestamps(
    t0: float, t1: float, rate_s: float, jitter_pct: float, rng: np.random.Generator
) -> np.ndarray:
    """区間 [t0, t1) のタイムスタンプ — 公称グリッド+tick 毎の有界ジッタ.

    間隔 cumsum でジッタを累積させると、累積ドリフト (~rate*j*sqrt(n)) が
    次チャンクの決定的開始時刻 t0' を追い越して seam で逆行する (実機確認で
    hils の CAN/ETH 系に非単調警告が混入した根因)。tick 毎の独立オフセットなら
    |δ| <= j*rate < rate/2 より連続差分 >= rate*(1-2j) > 0 で、チャンク内・
    チャンク境界とも厳密単調が保証される (バス到着ジッタとしても自然)。

    前提: jitter_pct < 0.5、かつ chunk 長 (t1-t0) は rate_s の整数倍
    (端数だと前チャンク末尾+ジッタが次チャンク先頭 t0' を追い越し得る —
    現行の全プロファイル/レート組は整数倍で安全)。
    """
    assert 0.0 <= jitter_pct < 0.5, "jitter_pct must be < 0.5 to guarantee monotonicity"
    n = max(int(np.ceil((t1 - t0) / rate_s)), 1)
    ts = t0 + np.arange(n, dtype=np.float64) * rate_s
    if jitter_pct:
        # 先頭は t0 ちょうど (チャンク境界を決定的に保つ)
        ts[1:] += rng.uniform(-jitter_pct, jitter_pct, n - 1) * rate_s
    return ts


def _group_source(g: GroupDef) -> Source:
    """グループの acq_source — CAN/Ethernet は mdf4_loader._BUS_TYPE_MAP に整合させる."""
    if g.bus is None:
        return Source(
            name="XCP:HILS_ECU",
            path="XCP:HILS_ECU",
            comment="",
            source_type=Source.SOURCE_ECU,
            bus_type=Source.BUS_TYPE_NONE,
        )
    bus_type = (
        Source.BUS_TYPE_CAN if g.bus.startswith("CAN") else Source.BUS_TYPE_ETHERNET
    )
    return Source(
        name=g.bus,
        path=g.bus,
        comment="",
        source_type=Source.SOURCE_BUS,
        bus_type=bus_type,
    )


def _pack_array_channel(values: np.ndarray) -> np.ndarray:
    """(N, k) の物理値 (m) → uint8 の byte-array 2D 配列 (0-255 にクリップ量子化).

    Finding 2 (review): 構造化 dtype (単一フィールドの subarray) でパッキング
    すると、asammdf 8.8.11 の iter_channels がこの配列を ndim==1 の
    structured array として返し、Mdf4Loader の 2D skip 判定を素通りしてしまう
    — さらに読み戻し時に (i) 親チャンネルが列0だけの偽データとして化け、
    (ii) 存在しない兄弟チャンネル ObjMatrix[0..7] が8本湧く (実機確認済み)。
    これは spec の設計目的 (本番 (b) パターンの「2D samples, skipped」再現)
    の真逆になる。

    itemsize==1 (uint8) の非構造化 byte-array 表現のみ shape (N, k) のまま
    正しく書け・読み戻ることを実機確認した (itemsize>1 の float64/int16 等は
    レコードバイトサイズを要素1個分しか確保しない既知の asammdf バグで
    後続サンプルがずれる — tests/mdf4_helpers.py の
    write_mdf4_all_channels_bad が LD 第1弾で使ったのと同じ手法)。この結果
    iter_channels は ndim==2 のまま返し、Mdf4Loader が 2D として認識できる
    (第2弾時点は skip 診断・core-loaders-hardening 第3弾以降は Name[i] へ
    要素展開＋info 診断)。本チャンネルは 2D 経路の検証専用データであり
    物理精度は不要なため、0-255m にクリップ量子化する
    (非存在スロットの NaN は 0 に丸める)。
    """
    finite = np.where(np.isfinite(values), values, 0.0)
    return np.clip(finite, 0.0, 255.0).astype(np.uint8)


def build_group_signals(
    g: GroupDef, t0: float, t1: float, seed: int, chunk_idx: int
) -> tuple[np.ndarray, list[Signal]]:
    """区間 [t0, t1) のタイムスタンプ + グループ内 Signal 群を生成."""
    rng = np.random.default_rng(seed * 1000 + g.group_id * 100 + chunk_idx)
    ts = _group_timestamps(t0, t1, g.rate_s, g.jitter_pct, rng)

    sigs: list[Signal] = []
    for sd in g.signals:
        values = sd.fn(ts, rng)
        if sd.ndim > 1:
            samples = _pack_array_channel(values)
        elif sd.conv is not None and "a" in sd.conv:
            a = float(sd.conv["a"])  # type: ignore[arg-type]
            b = float(sd.conv.get("b", 0.0))  # type: ignore[union-attr]
            raw = np.round((values - b) / a)
            info = np.iinfo(sd.dtype)
            if raw.min() < info.min or raw.max() > info.max:
                raise ValueError(
                    f"{sd.name}: raw value out of {sd.dtype} range "
                    f"(min={raw.min()}, max={raw.max()}, a={a})"
                )
            samples = raw.astype(sd.dtype)
        else:
            samples = values.astype(sd.dtype)

        sigs.append(
            Signal(
                samples=samples,
                timestamps=ts,
                name=sd.name,
                unit=sd.unit,
                conversion=sd.conv,
                comment=sd.comment,
            )
        )
    return ts, sigs


def _inject_dirty(ts: np.ndarray, seed: int, chunk_idx: int) -> np.ndarray:
    """LD-03/04 実機確認デモ用 — 末尾側に重複数十点 + 非単調数点を混入.

    実 CAN ログにありがちなタイムスタンプ品質劣化 (バス再送による重複・
    巻き戻り) を模す。間隔配列を再構成してから壊すことで、他の区間は
    正常な単調増加のまま保つ。
    """
    if len(ts) < 60:
        return ts
    rng = np.random.default_rng(seed * 1000 + 99900 + chunk_idx)
    intervals = np.diff(ts, prepend=ts[0])
    n = len(intervals)
    tail_start = n - 40
    tail = np.arange(tail_start, n)
    dup_idx = rng.choice(tail, size=min(20, len(tail)), replace=False)
    intervals[dup_idx] = 0.0  # 重複タイムスタンプ (連続点が同時刻)
    remaining = np.setdiff1d(tail, dup_idx)
    neg_idx = rng.choice(remaining, size=min(5, len(remaining)), replace=False)
    intervals[neg_idx] = -np.abs(intervals[neg_idx]) - 0.001  # 非単調 (時刻巻き戻り)
    return ts[0] + np.cumsum(intervals)


def write_mf4(
    out: Path, profile: Profile, seed: int, dirty: bool, progress: bool
) -> Path:
    """プロファイル分のチャンクを append→extend で書き出す (spec §4.2/§4.4)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    mdf = MDF(version="4.10")
    n_chunks = int(np.ceil(profile.duration_s / profile.chunk_s))
    for ci in range(n_chunks):
        t0 = ci * profile.chunk_s
        t1 = min(t0 + profile.chunk_s, profile.duration_s)
        for gi, g in enumerate(GROUPS):
            ts, sigs = build_group_signals(g, t0, t1, seed, ci)
            if dirty and g.name == "VehDyn_10ms":
                ts = _inject_dirty(ts, seed, ci)
                # Finding 1 (review): ts の再束縛だけでは sigs 内の各 Signal
                # (クリーンな master をコピー保持) に伝播しない — ci==0 の
                # append はそちらを見るため、伝播しないと --dirty が
                # 単一チャンク経路 (smoke 等) で no-op になる。
                for s in sigs:
                    s.timestamps = ts
            if ci == 0:
                mdf.append(
                    sigs,
                    comment=g.name,
                    acq_source=_group_source(g),
                    common_timebase=True,
                )
            else:
                mdf.extend(gi, [(ts, None)] + [(s.samples, None) for s in sigs])
        if progress:
            print(f"chunk {ci + 1}/{n_chunks} ({t1:.0f}s)")
    mdf.save(str(out), overwrite=True)
    mdf.close()
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント — プロファイル・seed・dirty フラグでジェネレーション."""
    p = argparse.ArgumentParser(description="HILS デモ mf4 ジェネレータ")
    p.add_argument("--out", type=Path, default=Path("demo_data/hils_demo.mf4"))
    p.add_argument("--profile", choices=sorted(PROFILES), default="hils")
    p.add_argument(
        "--duration", type=float, default=None, help="秒(プロファイル既定の上書き)"
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--dirty", action="store_true", help="CAN に重複/非単調タイムスタンプを注入"
    )
    a = p.parse_args(argv)

    # validate --duration is positive (prevent ZeroDivisionError in write_mf4 / silent corrupt file on -5)
    if a.duration is not None and a.duration <= 0:
        p.error("--duration must be positive")

    prof = PROFILES[a.profile]
    if a.duration is not None:
        # chunk_s > duration を Profile に作らないための整合性維持 —
        # 境界計算は write_mf4 側でもクランプされる (n_chunks = ceil(...))
        prof = Profile(duration_s=a.duration, chunk_s=min(prof.chunk_s, a.duration))
    out = write_mf4(out=a.out, profile=prof, seed=a.seed, dirty=a.dirty, progress=True)
    print(f"wrote {out} ({out.stat().st_size / 1e9:.2f} GB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
