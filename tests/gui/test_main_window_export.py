# tests/gui/test_main_window_export.py
from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.export.csv_exporter import CsvExportOptions
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views import main_window as mw_mod
from valisync.gui.views.export_csv_dialog import ExportRequest, csv_header_resolver
from valisync.gui.views.main_window import MainWindow


def test_export_action_disabled_until_data(qtbot: QtBot) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    assert mw.shell_actions.action("export").isEnabled() is False
    mw.app_vm.register_loaded("csv_1")  # loaded 通知で有効化
    assert mw.shell_actions.action("export").isEnabled() is True


def test_export_csv_runs_export_with_request(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    target = tmp_path / "out.csv"
    # E-4b Task 4 supersede: ExportRequest は **列キー + header_resolver** を運ぶ
    # (D1・spec §5.2 — Signal のリストは受けない)。Signal fixture が不要になった。
    req = ExportRequest(
        keys=("csv_1::a",),
        output_path=target,
        options=CsvExportOptions(delimiter=";"),
        header_resolver=csv_header_resolver,
    )
    # ダイアログを差し替え (要求を返す)
    monkeypatch.setattr(
        mw_mod.ExportCsvDialog, "ask", classmethod(lambda cls, *a, **k: req)
    )
    # export を捕捉 (実書出はここでは不要)
    calls: list[tuple] = []
    monkeypatch.setattr(
        mw.app_vm.session, "export_csv", lambda *a, **k: calls.append((a, k))
    )
    mw.export_csv()
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=3000)
    args, kwargs = calls[0]
    assert args[0] == ("csv_1::a",) and args[1] == target
    # 「要求の全フィールドが転送されること」という契約の意図は保存する
    # (E-4b Task 4 supersede: 旧 4 位置引数のうち use_unified_timeline は
    # options.use_unified_timeline へ移り、header_resolver/extra_signals が
    # キーワードで加わった — 転送漏れの回帰捕捉という役目は同じ)。
    assert args[2] is req.options
    assert kwargs["header_resolver"] is req.header_resolver
    assert kwargs["extra_signals"] is req.extra_signals


def test_export_csv_cancel_does_nothing(qtbot: QtBot, monkeypatch) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    monkeypatch.setattr(
        mw_mod.ExportCsvDialog, "ask", classmethod(lambda cls, *a, **k: None)
    )
    called: list[int] = []
    monkeypatch.setattr(
        mw.app_vm.session, "export_csv", lambda *a, **k: called.append(1)
    )
    mw.export_csv()
    assert called == []


# --- F-0/UX-28: 出力範囲 DI スナップショット (main_window.export_csv) --------


def _capture_ask_kwargs(monkeypatch, mw_module) -> dict[str, object]:
    captured: dict[str, object] = {}

    def _fake_ask(cls, app_vm, initial_selected, parent=None, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(mw_module.ExportCsvDialog, "ask", classmethod(_fake_ask))
    return captured


def test_export_csv_snapshots_active_tab_x_range_and_cursor(
    qtbot: QtBot, monkeypatch
) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    # タブ0のパネルへ紛らわしい別レンジ/カーソルを仕込み、アクティブタブ(1)側が
    # 使われることを検証する (マルチタブ回帰・spec §2.3)。
    panel0 = mw.graph_area_vm.panels(0)[0]
    panel0.set_x_range(100.0, 200.0)
    panel0.set_cursor(150.0)
    panel0.set_cursor_b(180.0)

    mw.graph_area_vm.add_tab()  # active_tab_index はタブ1へ移る
    panel1 = mw.graph_area_vm.active_panel()
    panel1.set_x_range(2.0, 9.0)
    panel1.set_cursor(3.0)
    panel1.set_cursor_b(6.0)

    captured = _capture_ask_kwargs(monkeypatch, mw_mod)
    mw.export_csv()

    assert captured["x_range"] == (2.0, 9.0)
    assert captured["cursor_a"] == 3.0
    assert captured["cursor_b"] == 6.0
    # I2 fix (task-3-review.md #1): main_window no longer precomputes a bool —
    # it hands the dialog a live resolver so the dialog can re-evaluate against
    # whichever signals end up checked in-dialog (spec §2.1 is selection-driven,
    # not an open-time snapshot like x_range/cursor above).
    offset_for = captured["offset_for"]
    assert callable(offset_for)
    assert offset_for("csv_1::anything") == 0.0  # no offsets applied in this test


def test_export_csv_offset_for_resolves_selected_signal_offset(
    qtbot: QtBot, monkeypatch
) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    panel = mw.graph_area_vm.active_panel()
    panel.add_signal("csv_1::speed")
    mw.app_vm.apply_offset("csv_1::speed", 1.0, "signal")

    captured = _capture_ask_kwargs(monkeypatch, mw_mod)
    mw.export_csv()

    offset_for = captured["offset_for"]
    assert callable(offset_for)
    assert offset_for("csv_1::speed") == 1.0
    # I2 fix (task-3-review.md #1): `offset_keys` が注入されて初めて prod は
    # 反転済み (Task 3) のガード経路を通る — 未注入だと legacy 経路へ黙って
    # 戻ってしまうのに、このファイルにはその配線を確認する assert が無かった。
    assert set(captured["offset_keys"]()) == {"csv_1::speed"}


def test_export_csv_offset_keys_carries_both_offset_sources(
    qtbot: QtBot, monkeypatch
) -> None:
    """`offset_keys` lambda は signal 辞書と file 辞書の**両方**を運ぶ。

    再レビュー是正 (2026-08-01): 上のテストは signal スコープしか張らないため
    lambda から `*file_offsets` を消しても緑のまま (実測 gui 1556 全緑)。
    その退行では `_selection_touches` のセパレータ無し分岐 (グループキー専用)
    が production で死に、ファイル単位の R14 オフセットが range-radio ガード
    (F-0/UX-28 契約) を黙って失う。group スコープ適用は実効オフセットを
    置き換えるため既存テストへは追記できず、専用テストで両源を束縛する。
    """
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    panel = mw.graph_area_vm.active_panel()
    panel.add_signal("csv_1::speed")
    # group 適用は同グループの signal オフセットを吸収して消す (R14 の
    # 「ファイル全体に適用」の意味論) ので、group -> signal の順で両辞書を残す。
    mw.app_vm.apply_offset("csv_1::speed", 2.0, "group")
    mw.app_vm.apply_offset("csv_1::speed", 1.0, "signal")

    captured = _capture_ask_kwargs(monkeypatch, mw_mod)
    mw.export_csv()

    keys = set(captured["offset_keys"]())
    # 片側だけの assert はもう片側の削除に盲目 — 両源を明示的に要求する。
    assert "csv_1" in keys, keys  # file 辞書由来 (グループキー)
    assert any("::" in k for k in keys), keys  # signal 辞書由来が空でないこと


def test_export_csv_offset_for_is_app_global_not_scoped_to_initial_selection(
    qtbot: QtBot, monkeypatch
) -> None:
    """I2 の穴の回帰テスト (task-3-review.md #1): 旧実装は `initial` (プロット中
    =初期選択) だけを走査した bool を1回だけ渡していたため、`initial` に含まれ
    ない (別ファイル/未プロットの) 信号のオフセットは main_window 層で握り
    つぶされていた。修正後は resolver 自体を渡すので、`initial` 外の信号の
    オフセットも (ダイアログ側で checked にされた瞬間) 解決できる。
    """
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    panel = mw.graph_area_vm.active_panel()
    panel.add_signal("csv_1::speed")  # 初期選択 (オフセット無し)
    mw.app_vm.apply_offset("csv_1::other", 1.0, "signal")  # 初期選択に含まれない信号

    captured = _capture_ask_kwargs(monkeypatch, mw_mod)
    mw.export_csv()

    offset_for = captured["offset_for"]
    assert offset_for("csv_1::speed") == 0.0  # 初期選択自体にはオフセット無し
    assert offset_for("csv_1::other") == 1.0  # 初期選択外でも resolver は解決できる
