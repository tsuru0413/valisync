"""確認ダイアログの本文・閾値・D5 拒否の配線 (E-4b T-UX・B2/D5)。

本文は pure 関数 (``export_confirm.confirm_body``) が作り、QMessageBox は
``MainWindow._confirm_export_fn`` の既定実装が包むだけ — file_browser_view の
``_confirm_fn`` DI と同型 (spec §5.5 [I15/ux-A])。テストは DI 口を差し替えて
「訊いたか」「答えに従ったか」を効果で見る (モーダルは開かない)。

**D5 は必ず注入で固定する**: 実ディスクの空きを見る既定のままだと、`_EST`
(推定 10.1 GB -> 必要 23.2 GB) が通るかどうかが実行マシンの空き容量で変わり、
確認を見るはずのテストが D5 の早期 return を通って「訊かなかった」で落ちる。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.export.estimate import ExportEstimate
from valisync.gui.formatting import format_duration
from valisync.gui.views.export_confirm import confirm_body, needs_confirmation

_EST = ExportEstimate(
    columns=1234,
    rows=5678,
    empty_ratio=0.6612,
    est_bytes=10_100_000_000,
    est_read_s=600.0,
    est_write_s=504.0,
)


def test_body_labels_the_estimated_values_as_estimates() -> None:
    """B2: 正確値 (列/行/空セル率) と推定値 (サイズ/時間) を読者が区別できること。"""
    body = confirm_body(_EST)
    assert "推定サイズ" in body
    assert "推定時間" in body
    assert "1234" in body and "5678" in body


def test_body_uses_no_digit_grouping() -> None:
    """桁区切りは付けない (既存決定・strings.py のチャンネル件数と同規約)。"""
    body = confirm_body(_EST)
    assert "1,234" not in body
    assert "5,678" not in body


def test_body_explains_why_cells_are_empty() -> None:
    """空セル率だけ出しても読者は原因を推測できない (spec §5.5 の文言例)。"""
    body = confirm_body(_EST)
    assert "66" in body  # 0.6612 -> 66 %
    assert "記録周期" in body


def test_confirmation_is_skipped_below_the_threshold() -> None:
    fast = ExportEstimate(2, 10, 0.0, 100, 0.1, 0.1)
    assert needs_confirmation(fast) is False


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "0 秒"),
        (-1.0, "0 秒"),  # ETA の外挿は負になりうる (Task 9)
        (float("nan"), "0 秒"),
        (0.4, "0 秒"),
        (1.0, "1 秒"),
        (59.4, "59 秒"),
        (60.0, "1 分"),
        (1104.0, "18 分 24 秒"),
        (3600.0, "1 時間"),
        (7_500.0, "2 時間 5 分"),
    ],
)
def test_format_duration_drops_precision_as_the_wait_grows(
    seconds: float, expected: str
) -> None:
    """「1104 秒」では待てるか判断できない — 粒度を段階的に落とす。"""
    assert format_duration(seconds) == expected


def _window(qtbot: QtBot) -> Any:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    return window


def _request(tmp_path: Path) -> Any:
    from valisync.core.export.csv_exporter import CsvExportOptions, ExportRequest

    return ExportRequest(
        keys=("mf4_1::A",),
        output_path=tmp_path / "out.csv",
        options=CsvExportOptions(),
        header_resolver=list,
    )


def _no_shortfall(monkeypatch: pytest.MonkeyPatch) -> None:
    """D5 を「足りている」に固定する (実ディスク依存を排除)。"""
    import valisync.gui.views.main_window as mw

    monkeypatch.setattr(mw, "disk_shortfall", lambda _p, _b: 0)


def test_main_window_asks_and_aborts_when_refused(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """拒否したら submit しない (「訊いたが無視して書き出す」を閉じる)。"""
    _no_shortfall(monkeypatch)
    window = _window(qtbot)
    asked: list[ExportEstimate] = []
    submitted: list[object] = []
    window._confirm_export_fn = lambda est: (asked.append(est), False)[1]
    window._export_controller.submit = lambda *a, **k: submitted.append(a)

    window._run_export(_request(tmp_path), _EST)

    assert len(asked) == 1
    assert submitted == []


def test_main_window_submits_when_confirmed(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_shortfall(monkeypatch)
    window = _window(qtbot)
    submitted: list[object] = []
    window._confirm_export_fn = lambda est: True
    window._export_controller.submit = lambda *a, **k: submitted.append(a)

    window._run_export(_request(tmp_path), _EST)

    assert len(submitted) == 1


def test_main_window_skips_the_dialog_for_a_fast_export(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """閾値未満は**訊かずに**書き出す (I10 のスキップ — 進捗/中止は別途出る)。"""
    _no_shortfall(monkeypatch)
    window = _window(qtbot)
    asked: list[object] = []
    submitted: list[object] = []
    window._confirm_export_fn = lambda est: asked.append(est) or True
    window._export_controller.submit = lambda *a, **k: submitted.append(a)

    window._run_export(_request(tmp_path), ExportEstimate(2, 10, 0.0, 100, 0.1, 0.1))

    assert asked == []
    assert len(submitted) == 1


def test_disk_shortfall_refuses_before_asking_anything(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D5 は **唯一の拒否**。不足なら確認も submit もせずに理由を出す。"""
    import valisync.gui.views.main_window as mw

    window = _window(qtbot)
    asked: list[object] = []
    submitted: list[object] = []
    blocked: list[str] = []
    window._confirm_export_fn = lambda est: asked.append(est) or True
    window._export_controller.submit = lambda *a, **k: submitted.append(a)
    window._notify_blocked = blocked.append
    monkeypatch.setattr(mw, "disk_shortfall", lambda _p, _b: 4_096)

    window._run_export(_request(tmp_path), _EST)

    assert submitted == []
    assert asked == [], "ディスク不足なのに続行可否を訊いた (答えても書けない)"
    assert blocked and "空き容量" in blocked[0]
    # 不足量そのものが文言に載ること。「空き容量」だけを見ていると、
    # `_fmt_size(shortfall)` を落として「足りません」とだけ言う退行
    # (= どれだけ空ければよいか分からない) を素通しする。4,096 B -> "4.0 KB"。
    assert "4.0 KB" in blocked[0], blocked[0]


def test_disk_gate_upper_bounds_the_core_gate(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GUI 門番は core 門番を**上界包含**する (I-3・順序逆転の構造排除)。

    core (`csv_exporter._require_disk_space`) は粗い 12 B/セルで判定するので、
    GUI が実測校正済みの小さい推定だけを見ると「GUI を通過 -> 確認 Yes -> core で
    ValueError」という窓が開く。両者の大きい方を D5 へ渡していれば、GUI が問い合わせる
    バイト数は core の必要量以上になる。
    """
    import valisync.gui.views.main_window as mw
    from valisync.core.export.csv_exporter import estimate_output_bytes

    window = _window(qtbot)
    seen: list[int] = []
    monkeypatch.setattr(mw, "disk_shortfall", lambda _p, b: seen.append(b) or 0)
    window._confirm_export_fn = lambda est: True
    window._export_controller.submit = lambda *a, **k: None

    # est_bytes を故意に小さくした見積 (校正済み係数が core の 12 B/セルを下回る形)。
    small = ExportEstimate(
        columns=1234,
        rows=5678,
        empty_ratio=0.9,
        est_bytes=1_000,
        est_read_s=0.0,
        est_write_s=0.0,
    )
    window._run_export(_request(tmp_path), small)

    assert seen == [estimate_output_bytes(small.rows, small.columns)]
    assert seen[0] > small.est_bytes


# --- 見積を GUI スレッドで固まらせない配線 (I1) --------------------------------


def _wide_app_vm(tmp_path: Path) -> Any:
    """幅 16 の 2-D チャンネル + スカラー 1 本を積んだ実 AppViewModel。"""
    from tests.mdf4_helpers import write_mdf4_wide_2d
    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

    path = write_mdf4_wide_2d(tmp_path, cols=16)
    session = Session()
    key = session.load(path).key
    app_vm = AppViewModel(session)
    app_vm.register_loaded(key)
    return app_vm, key


def test_export_csv_hands_the_dialogs_channel_map_to_the_estimate(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ダイアログが持っている {チャンネル: 列数} が見積まで届く配線 (I1)。

    `estimate_export` は表が無ければ列キー 1 本ずつを `channel_key_of` で解決する
    — prod 330,004 列で **2.6 s** かかり、`export_csv` は GUI スレッドなので
    そのまま「押すと 3 秒固まる」になる。ダイアログは選択を物理チャンネル単位で
    持っている (spec §5.6) ので、確定時に書き戻してもらう。

    ここが見るのは **配線** (表が非空で・キーが物理チャンネル・合計が列数と一致)。
    速さそのものは prod 実データの demo-gated テストが見る (合成 16 列では
    フォールバックも速く、閾値を置いても意味がない)。
    """
    from PySide6.QtWidgets import QDialog

    import valisync.gui.views.main_window as mw_mod
    from valisync.core.export.estimate import ExportEstimate
    from valisync.gui.views.export_csv_dialog import ExportCsvDialog
    from valisync.gui.views.main_window import MainWindow

    app_vm, key = _wide_app_vm(tmp_path)
    window = MainWindow(app_vm)
    qtbot.addWidget(window)

    target = tmp_path / "out.csv"

    def _auto_accept(self: Any) -> QDialog.DialogCode:
        self._select_all()
        self._save_path_provider = lambda: str(target)
        self._on_accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExportCsvDialog, "exec", _auto_accept)

    captured: dict[str, Any] = {}

    def _fake_estimate(session: Any, keys: Any, options: Any, **kwargs: Any) -> Any:
        captured["keys"] = tuple(keys)
        captured.update(kwargs)
        return ExportEstimate(2, 10, 0.0, 100, 0.1, 0.1)

    monkeypatch.setattr(mw_mod, "estimate_export", _fake_estimate)
    monkeypatch.setattr(window, "_run_export", lambda req, est: None)

    window.export_csv()

    plan = captured["channel_columns"]
    # 幅 16 の "Wide" は **1 チャンネル 16 列**、"Clean" は 1 列。列ごとに 1 本の
    # エントリを作る表 (= 圧縮前の形) だと 17 エントリになるので、ここは
    # 「チャンネル単位で持っている」ことの assert でもある。
    assert plan == {f"{key}::Wide": 16, f"{key}::Clean": 1}, plan
    assert sum(plan.values()) == len(captured["keys"]) == 17


_PROD_DEMO = Path("demo_data/prod_demo.mf4")


@pytest.mark.skipif(not _PROD_DEMO.exists(), reason="prod demo mf4 not generated")
def test_prod_scale_estimate_stays_off_the_freeze_threshold(qtbot: QtBot) -> None:
    """prod 実データ (330,004 列) の見積が **GUI スレッドを固めない**。

    合成 fixture では捕まらない: フォールバック解決のコストは列数に比例するので、
    16 列でも 5,000 列でも「速い」に見える。実ファイルでしか 2.6 s は出ない。

    閾値 100 ms は「1 フレーム (16 ms) は超えるが人には引っかからない」帯で、
    実測 (下の print) はこれより 1 桁小さい。ダイアログが表を渡さなくなると
    フォールバックへ落ちて 2.6 s = **26 倍** になるので、閾値の置き場所に
    余裕がある。

    ついでに書き項も見る (I2): 2 項モデル化の前は同じ入力で 2,418 s (40 分) を
    提示していた — spec §1 の外挿 (~18.4 分 = 1,104 s) の 2.19 倍。帯を
    1,000-1,250 s (外挿の ±13%) と狭めに取るのは、**2 項をどう 1 項へ潰しても
    帯の外へ出る**ようにするため (VALUE だけを全セルへ = 1,375 s / BASE+VALUE を
    全セルへ = 2,010 s / 旧 6.1e-7 = 2,418 s)。**係数は Task 11 (T-M) が prod
    1 点で検定するまで暫定**なので、この帯は検定と一緒に見直すこと (帯そのものが
    受け入れ条件ではない — 桁が合っているかの見張り)。
    """
    import time

    from valisync.core.export.csv_exporter import CsvExportOptions
    from valisync.core.export.estimate import estimate_export
    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.export_csv_dialog import ExportCsvDialog

    session = Session()
    key = session.load(_PROD_DEMO).key
    try:
        app_vm = AppViewModel(session)
        app_vm.register_loaded(key)
        dlg = ExportCsvDialog(app_vm, initial_selected=set())
        qtbot.addWidget(dlg)
        dlg._select_all()
        plan = dlg.channel_columns()
        keys = dlg._checked_keys()
        assert len(keys) > 300_000, len(keys)

        started = time.perf_counter()
        est = estimate_export(session, keys, CsvExportOptions(), channel_columns=plan)
        elapsed = time.perf_counter() - started

        assert est.columns == len(keys)
        assert elapsed < 0.1, (
            f"見積が {elapsed * 1000:.0f} ms かかった (表が届いていない)"
        )
        assert 1000.0 < est.est_write_s < 1250.0, est.est_write_s
    finally:
        # 1.36 GB のハンドルを後続テストへ引き継がない。
        session.remove_group(key, force=True)
