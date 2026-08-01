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
