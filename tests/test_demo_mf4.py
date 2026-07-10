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


def test_smoke_mf4_roundtrip(tmp_path):
    out = gen.write_mf4(
        out=tmp_path / "smoke.mf4",
        profile=gen.PROFILES["smoke"],
        seed=42,
        dirty=False,
        progress=False,
    )
    from asammdf import MDF

    with MDF(str(out)) as mdf:
        names = {ch.name for group in mdf.groups for ch in group.channels}
        assert "VehSpd" in names and "Radar.Obj[0].dx" in names
        assert "Cluster.SurrVeh[0].RelX" in names
        assert "Radar.ObjMatrix" in names  # (b) 2D チャンネル
        spd = mdf.get("VehSpd")
        assert spd.samples.dtype == np.float64 or np.issubdtype(
            spd.samples.dtype, np.floating
        )
        assert 70.0 < float(np.nanmean(spd.samples)) < 90.0  # 物理値変換が効いている
        assert str(spd.unit).strip() in ("km/h", "km/h ")


def test_smoke_reproducible_same_seed(tmp_path):
    a = gen.write_mf4(
        out=tmp_path / "a.mf4",
        profile=gen.PROFILES["smoke"],
        seed=7,
        dirty=False,
        progress=False,
    )
    b = gen.write_mf4(
        out=tmp_path / "b.mf4",
        profile=gen.PROFILES["smoke"],
        seed=7,
        dirty=False,
        progress=False,
    )
    from asammdf import MDF

    with MDF(str(a)) as ma, MDF(str(b)) as mb:
        assert np.array_equal(ma.get("VehSpd").samples, mb.get("VehSpd").samples)


def test_multi_chunk_extend_preserves_continuity(tmp_path):
    # smoke プロファイル (chunk_s == duration_s) は append のみで extend を
    # 通らない — チャンク境界をまたぐ経路 (append→extend) を別途小尺で検証する。
    profile = gen.Profile(duration_s=4.0, chunk_s=1.0)
    out = gen.write_mf4(
        out=tmp_path / "chunks.mf4",
        profile=profile,
        seed=3,
        dirty=False,
        progress=False,
    )
    from asammdf import MDF

    with MDF(str(out)) as mdf:
        spd = mdf.get("VehSpd")
        assert (
            len(spd.timestamps) > 350
        )  # 10ms レート x 4s 分がチャンク分割で欠落しない
        assert np.all(np.diff(spd.timestamps) > 0.0)  # dirty=False は常に単調
        mat = mdf.get("Radar.ObjMatrix")
        assert mat.samples.shape[0] == len(mdf.get("Radar.Obj[0].dx").timestamps)


def test_dirty_injects_nonmonotonic_only_in_vehdyn(tmp_path):
    profile = gen.Profile(duration_s=4.0, chunk_s=1.0)
    out = gen.write_mf4(
        out=tmp_path / "dirty.mf4", profile=profile, seed=11, dirty=True, progress=False
    )
    from asammdf import MDF

    with MDF(str(out)) as mdf:
        veh_spd_ts = mdf.get("VehSpd").timestamps
        diffs = np.diff(veh_spd_ts)
        assert np.any(diffs <= 0.0)  # LD-03/04 デモ: 重複/非単調が混入
        other_ts = mdf.get("EngTrq").timestamps  # dirty 対象外グループは無傷
        assert np.all(np.diff(other_ts) > 0.0)


def test_dirty_injects_nonmonotonic_in_single_chunk_profile(tmp_path):
    # Finding 1 回帰: smoke は chunk_s == duration_s のため ci==0 の append 分岐
    # しか通らない。_inject_dirty がローカル名 ts のみ書き換えて Signal.timestamps
    # (sigs 内) に伝播しないと、この経路では dirty=True が no-op になっていた。
    out = gen.write_mf4(
        out=tmp_path / "dirty_smoke.mf4",
        profile=gen.PROFILES["smoke"],
        seed=5,
        dirty=True,
        progress=False,
    )
    from asammdf import MDF

    with MDF(str(out)) as mdf:
        veh_spd_ts = mdf.get("VehSpd").timestamps
        assert np.any(np.diff(veh_spd_ts) <= 0.0)


def test_2d_channels_explode_in_valisync(tmp_path):
    # LD-12 (第3弾): 物標行列 (b) パターンは列展開されて Radar/Cam.ObjMatrix[0..7]
    # として valisync から見えるようになった — 旧仕様 (2D は丸ごと「skipped」)
    # は本タスクで置換 (spec §4.2 歴史注記参照)。旧テストが守っていた「親チャン
    # ネルが偽データとして化けない」不変条件は展開後も変わらず成立する
    # (親名 "Radar.ObjMatrix"/"Cam.ObjMatrix" 単体は信号として現れない)。
    out = gen.write_mf4(
        out=tmp_path / "s.mf4",
        profile=gen.PROFILES["smoke"],
        seed=1,
        dirty=False,
        progress=False,
    )
    from valisync.core.session import Session

    session = Session()
    outcome = session.load(out)

    names = {sig.name.split("::", 1)[1] for sig in session.group_signals(outcome.key)}
    for i in range(8):
        assert f"Radar.ObjMatrix[{i}]" in names
        assert f"Cam.ObjMatrix[{i}]" in names
    assert "Radar.ObjMatrix" not in names
    assert "Cam.ObjMatrix" not in names

    infos = [
        d for d in outcome.diagnostics if d.level == "info" and "ObjMatrix" in d.message
    ]
    assert len(infos) == 2  # Radar/Cam の ObjMatrix 2本とも展開 info

    skips = [
        d
        for d in outcome.diagnostics
        if "skipped" in d.message and "ObjMatrix" in d.message
    ]
    assert len(skips) == 0  # 展開されるので skip 警告は 0 件


def test_turn_sig_survives_load_with_raw_enum_values(tmp_path):
    # Finding 3 回帰: value2text (TABX) conversion を埋め込むと、
    # MdfLoader の ignore_value2text_conversions が MDF() コンストラクタには
    # 効かない dead オプションのため iter_channels がテキストを返し、
    # 「non-numeric, skipped」でチャンネルごと消滅していた。
    out = gen.write_mf4(
        out=tmp_path / "turnsig.mf4",
        profile=gen.PROFILES["smoke"],
        seed=2,
        dirty=False,
        progress=False,
    )
    from valisync.core.session import Session

    session = Session()
    outcome = session.load(out)
    names = {
        sig.name.split("::", 1)[1]: sig for sig in session.group_signals(outcome.key)
    }
    assert "TurnSig" in names
    values = set(np.unique(names["TurnSig"].values).tolist())
    assert values <= {0.0, 1.0, 2.0}
    turn_sig = names["TurnSig"]
    # LD-07: 復活させた value2text がラベルとして構造化保持される
    assert turn_sig.metadata.get("value_labels") == {
        0.0: "OFF",
        1.0: "LEFT",
        2.0: "RIGHT",
    }


def test_valisync_loads_smoke_profile(tmp_path):
    # brief 相当の smoke プロファイル統合確認: 代表信号名の存在 (VehSpd/Radar.Obj[0].dx)
    # に加え、(b) 2D チャンネルは LD-12 展開により Radar.ObjMatrix[0] として見える
    # こと、error レベル診断はゼロであること (詳細な展開契約の中身は
    # test_2d_channels_explode_in_valisync が既に担保している)。
    out = tmp_path / "v.mf4"
    gen.main(["--out", str(out), "--profile", "smoke", "--seed", "1"])
    from valisync.core.session import Session

    session = Session()
    outcome = session.load(out)
    sigs = session.group_signals(outcome.key)
    names = {s.name.split("::", 1)[1] for s in sigs}
    assert "VehSpd" in names and "Radar.Obj[0].dx" in names
    assert "Radar.ObjMatrix[0]" in names  # (b) 2D チャンネルは展開されて見える (LD-12)
    assert not any(d.level == "error" for d in outcome.diagnostics)


def test_valisync_dirty_shows_nonmonotonic_warning(tmp_path):
    # brief 相当: 既存の dirty テストは asammdf/CLI レベルの生タイムスタンプ検証のみ
    # (test_dirty_injects_non_monotonic 等) — ここでは Session.load を経由し、LD-03
    # (core/loaders/mdf_loader.py) が非単調/重複を warning 診断として実際に表面化
    # させることを確認する。
    out = tmp_path / "vd.mf4"
    gen.main(["--out", str(out), "--profile", "smoke", "--seed", "1", "--dirty"])
    from valisync.core.session import Session

    outcome = Session().load(out)
    assert any(
        "非単調" in d.message or "重複" in d.message for d in outcome.diagnostics
    )


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


def test_cli_rejects_nonpositive_duration(tmp_path):
    import pytest

    # duration=0 は SystemExit を送出するべき
    with pytest.raises(SystemExit):
        gen.main(
            ["--out", str(tmp_path / "x.mf4"), "--profile", "smoke", "--duration", "0"]
        )
    assert not (tmp_path / "x.mf4").exists()

    # duration=-5 も SystemExit を送出するべき
    with pytest.raises(SystemExit):
        gen.main(
            ["--out", str(tmp_path / "y.mf4"), "--profile", "smoke", "--duration", "-5"]
        )
    assert not (tmp_path / "y.mf4").exists()


def test_clean_multichunk_timestamps_strictly_monotonic(tmp_path):
    """チャンク境界のジッタ累積ドリフトで seam 逆行が起きない(実機確認で発見した生成バグ).

    AEB.TTC は無ジッタグループ(XCP_1ms)の健全性コントロール — バグの対象は
    ジッタあり群(VehSpd/EngTrq/TurnSig)のみ。
    """
    prof = gen.Profile(
        duration_s=120.0, chunk_s=10.0
    )  # 11 seam・seed 42 で旧実装は VehSpd が逆行
    out = gen.write_mf4(
        out=tmp_path / "m.mf4", profile=prof, seed=42, dirty=False, progress=False
    )
    from asammdf import MDF

    with MDF(str(out)) as mdf:
        for name in ("VehSpd", "EngTrq", "TurnSig", "AEB.TTC"):
            ts = mdf.get(name).timestamps
            d = np.diff(ts)
            assert np.all(d > 0), f"{name}: {int(np.sum(d <= 0))} non-monotonic points"


def test_clean_multichunk_load_yields_only_2d_info(tmp_path):
    """クリーン生成(--dirty なし) は valisync ロードで警告を一切出さない
    (ObjMatrix は LD-12 展開により info 診断のみ・第3弾で契約変更 — 旧仕様は
    skip 警告2件だった)."""
    prof = gen.Profile(duration_s=40.0, chunk_s=10.0)
    out = gen.write_mf4(
        out=tmp_path / "c.mf4", profile=prof, seed=42, dirty=False, progress=False
    )
    from valisync.core.session import Session

    outcome = Session().load(out)
    warns = [d for d in outcome.diagnostics if d.level == "warning"]
    assert warns == [], [d.message for d in warns]

    infos = [
        d for d in outcome.diagnostics if d.level == "info" and "ObjMatrix" in d.message
    ]
    assert len(infos) == 2


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
    est_bytes, est_channels = estimate_profile_size(
        [g], 10.0
    )  # 10s / 10ms = 1000 sample
    # 展開後: scalar 1 + array 100 = 101
    assert est_channels == 101
    # bytes: n=1000. 時刻 1000*8=8000 + scalar 1000*1*8=8000 + array 1000*100*1=100000
    assert est_bytes == 8000 + 8000 + 100000
