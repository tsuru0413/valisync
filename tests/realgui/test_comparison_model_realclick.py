# ruff: noqa: RUF002, RUF003
"""Layer C (realgui) — E-0＋E-2 比較データモデルの2ファイル実機ジャーニー (Task 4 Step 1)。

小型 CSV 2 ファイル (同名信号2＋非同名1) をテスト内生成し、実 MainWindow へ実 OS 入力
(_realgui_input の at/RDOWN/RUP/LDOWN/LUP) で駆動する。合成 qtbot.mouseClick /
action.trigger() は使わない (memory gui_realgui_synthetic_click_mislabeled_layer_c)。

検証する実機所見 (spec §6 Layer C・Task 4 brief Step 1 逐語):
  (a) ファイルブラウザの非基準ファイル行を実右クリック→「基準の同名信号を重ねる」を
      実クリック→同軸重なりの実描画 (a.csv の VehSpd/EngineSpeed と b.csv の同名信号が
      同じ Y 軸に重畳表示される)。
  (b) 色相ファミリーの実ピクセル (基準ファイル=青系 palette[0] / 対象ファイル=橙系
      palette[1]) — 実 grabWindow スクショの実ピクセルを、実際に割り当てられた
      pen_color (production の hue_variant 出力) と突き合わせて検証する。
  (c) 読み値ペイン (凡例モード) の「(csv_1)」/「(csv_2)」併記 — E-0 の衝突時ファイル
      キー併記規則 (spec §1.1 判断点4) が実描画パイプラインで機能することの実証。
  (d) 基準バッジ「◎基準」＋ファイル=色相チップ (DecorationRole) の実表示。

あわせて E-0 の残り2面 (spec §1.2) を同一ジャーニー内で実機確認する:
  - Y 軸メニューの曲線一覧 (build_axis_menu) に "::" 内部キーが露出しないこと。
  - エクスポートダイアログのツリー葉テキストに "::" が露出しないこと。

スクショは design_export/evidence_e2/ へ保存 (Task 4 report からの目視参照用)。
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
    to_phys,
)
from tests.realgui._realgui_input import key as key_input
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui

_EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "design_export" / "evidence_e2"
_EVIDENCE_DIR_TOGGLE = (
    Path(__file__).resolve().parents[2] / "design_export" / "evidence_comparison_toggle"
)

_N = 30
_DT = 0.1


# ─── shared harness (module-local copy of the established pattern —
# tests/realgui/test_axis_menu_offset.py / test_grid_realclick.py) ─────────────


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int, dt: float = 0.02) -> None:
    for _ in range(n):
        _pump(dt)


def _click(x: int, y: int) -> None:
    """Real left click at physical (x, y) — menu bar / QMenu item selection.

    Established pattern (test_theme_menu_realclick.py): raw OS input injects
    into the message queue; the caller's subsequent qtbot.waitUntil pumps
    events and drives the (non-blocking) QMenuBar/QMenu popup open/dismiss.
    """
    at(x, y, LDOWN)
    time.sleep(0.05)
    at(x, y, LUP)


def _phys_center(widget, rect):  # type: ignore[no-untyped-def]
    dpr = widget.devicePixelRatioF()
    gp = widget.mapToGlobal(rect.center())
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _menu_hang_watchdog(stop: threading.Event) -> None:
    """Force-close a stuck ``QMenu.exec()`` by sending a real Escape after 4s.

    See test_axis_menu_offset.py::_menu_hang_watchdog for the full rationale —
    module-local copy to avoid cross-test-module imports.
    """
    deadline = time.time() + 4.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.1)
    if not stop.is_set():
        key_input(VK_ESCAPE)


def _open_menu(dpr_widget, phys, shot_path: Path, item_text: str | None = None):  # type: ignore[no-untyped-def]
    """Real right-click at *phys*, screenshot the popup.

    If *item_text* is given, real-click that row (dismissing the menu via the
    action); otherwise just capture-and-close (no mutation). Returns
    {type, actions, clicked?}.
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    px, py = phys
    captured: dict[str, object] = {}
    loop = QEventLoop()

    def _do_right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def _capture_and_act() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        with contextlib.suppress(Exception):
            QApplication.primaryScreen().grabWindow(0).save(str(shot_path))
        if isinstance(popup, QMenu):
            captured["actions"] = [a.text() for a in popup.actions()]
            if item_text is not None:
                act = next((a for a in popup.actions() if a.text() == item_text), None)
                if act is not None:
                    r = popup.actionGeometry(act)
                    dpr = dpr_widget.devicePixelRatioF()
                    gp = popup.mapToGlobal(r.center())
                    hx, hy = round(gp.x() * dpr), round(gp.y() * dpr)
                    at(hx, hy, LDOWN)
                    at(hx, hy, LUP)
                    captured["clicked"] = True
            else:
                popup.close()
        loop.quit()

    stop = threading.Event()
    watchdog = threading.Thread(target=_menu_hang_watchdog, args=(stop,), daemon=True)
    watchdog.start()

    QTimer.singleShot(300, _do_right_click)
    QTimer.singleShot(900, _capture_and_act)
    QTimer.singleShot(5000, loop.quit)  # outer safety net
    loop.exec()

    stop.set()
    watchdog.join(timeout=2.0)
    return captured


# ─── fixture data ───────────────────────────────────────────────────────────


def _write_csv(path: Path, header: list[str], rows: list[list[float]]) -> None:
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(f"{v:.4f}" for v in row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """2 CSV: 同名信号2 (VehSpd/EngineSpeed) ＋ 非同名1 (Torque, b.csv のみ)。

    値域は意図的にファイル・信号ごとに分離した帯 (0-2.9 / 10-12.9 / 20-22.9 /
    30-32.9) — 同一 Y 軸に4本重ねても実ピクセル走査で個別に判別できるようにする。
    """
    a_csv = tmp_path / "a.csv"
    b_csv = tmp_path / "b.csv"
    a_rows = [[i * _DT, 0.0 + i * 0.1, 10.0 + i * 0.1] for i in range(_N)]
    b_rows = [
        [i * _DT, 20.0 + i * 0.1, 30.0 + i * 0.1, 40.0 + i * 0.1] for i in range(_N)
    ]
    _write_csv(a_csv, ["t", "VehSpd", "EngineSpeed"], a_rows)
    _write_csv(b_csv, ["t", "VehSpd", "EngineSpeed", "Torque"], b_rows)
    return a_csv, b_csv


def _bare_key(session, group_key: str, bare_name: str) -> str:  # type: ignore[no-untyped-def]
    return next(
        s.name
        for s in session.group_signals(group_key)
        if s.name.endswith(f"::{bare_name}")
    )


# ─── pixel helpers ──────────────────────────────────────────────────────────


def _rgb(hex_color: str) -> tuple[int, int, int]:
    from PySide6.QtGui import QColor

    c = QColor(hex_color)
    return c.red(), c.green(), c.blue()


def _is_blue_family(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return b > g + 15 and g > r + 15


def _is_orange_family(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return r > g + 15 and g > b + 15


def _find_pixel_near(
    image, col: int, row: int, expected_rgb: tuple[int, int, int], radius=8, tol=30
) -> bool:  # type: ignore[no-untyped-def]
    er, eg, eb = expected_rgb
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            c = image.pixelColor(col + dc, row + dr)
            if (
                abs(c.red() - er) <= tol
                and abs(c.green() - eg) <= tol
                and abs(c.blue() - eb) <= tol
            ):
                return True
    return False


# ─── the journey ────────────────────────────────────────────────────────────


def test_reference_overlay_hue_family_and_e0_display_names(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.export_csv_dialog import ExportCsvDialog
    from valisync.gui.views.main_window import MainWindow

    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    a_csv, b_csv = _build_fixture(tmp_path)

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)

    fmt_a = FormatDefinition(
        name="a_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    fmt_b = FormatDefinition(
        name="b_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=3,
        has_header=True,
    )
    session = window.app_vm.session
    outcome_a = session.load(a_csv, fmt_a)
    window._on_loaded(outcome_a)
    outcome_b = session.load(b_csv, fmt_b)
    window._on_loaded(outcome_b)
    key1, key2 = outcome_a.key, outcome_b.key  # csv_1 / csv_2 — spec §1.1 keying
    assert window.app_vm.reference_file_key == key1  # 既定=最初のロード (E-2a)
    # 比較モードのユーザー切り替え (2026-07-23 spec) で is_comparison_mode() は
    # 「明示フラグ AND 2+ファイル」に変わり、既定 OFF になった。本テストの意図は
    # 比較モード ON 時の重ね/家系色/バッジ/チップ挙動そのものの検証なので (M13
    # サイト別判断・機械的挿入ではなく意図確認済み)、ここで明示的に ON にする —
    # トグル UI 自体の実クリック経路は下の
    # test_comparison_mode_toggle_journey_realclick が別途担保する。
    window.app_vm.set_comparison_mode(True)

    vehspd1 = _bare_key(session, key1, "VehSpd")
    engspeed1 = _bare_key(session, key1, "EngineSpeed")
    vehspd2 = _bare_key(session, key2, "VehSpd")
    engspeed2 = _bare_key(session, key2, "EngineSpeed")

    # 基準ファイル (csv_1) の2信号を同一パネル・同一軸(0)へプロット — 重ねハンドラの
    # 「アクティブパネルの基準由来エントリを走査」対象になる (spec §3 手順1)。
    vm = window.graph_area_vm
    panel_vm = vm.panels(vm.active_tab_index)[vm.active_panel_index()]
    panel_vm.add_signal_to_axis(vehspd1, 0)
    panel_vm.add_signal_to_axis(engspeed1, 0)

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(
        screen.x() + 60,
        screen.y() + 60,
        min(1200, screen.width() - 120),
        min(820, screen.height() - 120),
    )
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    _pump_n(4)

    panel_view = next(w for _t, _p, w in window.graph_area_view._panel_views)
    qtbot.waitUntil(
        lambda: (
            bool(panel_view._view_boxes)
            and panel_view._view_boxes[0].sceneBoundingRect().height() > 100
        ),
        timeout=3000,
    )
    _pump_n(3)

    # ─── (a)(b)(c)(d): 実右クリック → 「基準の同名信号を重ねる」実クリック ───────
    fb = window.file_browser_view
    qtbot.waitUntil(
        lambda: fb.list_view.visualRect(fb.model.index(1, 0)).height() > 0,
        timeout=3000,
    )
    row1_rect = fb.list_view.visualRect(fb.model.index(1, 0))
    gp = fb.list_view.viewport().mapToGlobal(row1_rect.center())
    dpr = fb.devicePixelRatioF()
    px, py = round(gp.x() * dpr), round(gp.y() * dpr)

    shot_menu = _EVIDENCE_DIR / "overlay_menu.png"
    captured = _open_menu(fb, (px, py), shot_menu, item_text=S.ACTION_OVERLAY_REFERENCE)

    assert captured.get("type") == "QMenu", (
        "非基準ファイル行の実右クリックでメニューが開かない: "
        f"got {captured.get('type')!r}. screenshot: {shot_menu}"
    )
    assert captured.get("actions") == [
        S.ACTION_REMOVE_FILE,
        S.ACTION_SET_REFERENCE,
        S.ACTION_OVERLAY_REFERENCE,
    ], f"想定外のメニュー構成: {captured.get('actions')!r}"
    assert captured.get("clicked"), "「基準の同名信号を重ねる」の実クリックが不発"

    qtbot.waitUntil(lambda: len(panel_vm.plotted_entries()) == 4, timeout=3000)
    _pump_n(6)

    entries = {(sk, ax) for _eid, sk, ax in panel_vm.plotted_entries()}
    assert entries == {
        (vehspd1, 0),
        (engspeed1, 0),
        (vehspd2, 0),
        (engspeed2, 0),
    }, f"重ね後のエントリ集合が想定と不一致: {entries}"

    status = window.status_message()
    assert "2 件重ねました" in status, f"要約メッセージが想定外: {status!r}"
    assert "b.csv" in status

    # (c) 読み値ペイン(凡例モード)の「(csv_1)」「(csv_2)」併記 — 4エントリとも
    # 裸名衝突 (VehSpd x2 / EngineSpeed x2) なので全件 qualified になるはず。
    tsv = window.graph_area_view.readout_pane.table_tsv()
    for expected in (
        f"VehSpd ({key1})",
        f"VehSpd ({key2})",
        f"EngineSpeed ({key1})",
        f"EngineSpeed ({key2})",
    ):
        assert expected in tsv, f"readout に {expected!r} が無い。table_tsv=\n{tsv}"

    # (d) 基準バッジ「◎基準」＋ファイル=色相チップ (DecorationRole)。
    assert fb._vm.files[0].endswith(S.FILE_REFERENCE_BADGE_SUFFIX), fb._vm.files
    assert not fb._vm.files[1].endswith(S.FILE_REFERENCE_BADGE_SUFFIX), fb._vm.files
    chip0 = fb._vm.chip_color(0)
    chip1 = fb._vm.chip_color(1)
    assert chip0 == "#56b4e9", f"基準ファイルのチップ色が想定外: {chip0!r}"
    assert chip1 == "#e69f00", f"対象ファイルのチップ色が想定外: {chip1!r}"

    # 実描画スクショ (a)(c)(d) をまとめて1枚 — MainWindow は FileBrowser(バッジ/
    # チップ)・GraphArea(重畳曲線)・readout ペイン(併記名)が同一画面に同居する。
    _pump_n(4)
    time.sleep(0.15)  # DWM compositor flush 待ち (memory: FU-12 の教訓)
    _pump_n(2)
    shot_overlay = _EVIDENCE_DIR / "overlay_state.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_overlay))

    # (b) 色相ファミリー実ピクセル — 実際に割り当てられた pen_color (production の
    # hue_variant 出力そのもの) と、実 grabWindow スクショの実ピクセルを突き合わせる。
    by_key = {sk: eid for eid, sk, _ax in panel_vm.plotted_entries()}
    pen1_v = panel_view.pen_color(by_key[vehspd1])
    pen1_e = panel_view.pen_color(by_key[engspeed1])
    pen2_v = panel_view.pen_color(by_key[vehspd2])
    pen2_e = panel_view.pen_color(by_key[engspeed2])

    for pen in (pen1_v, pen1_e):
        assert _is_blue_family(_rgb(pen)), (
            f"csv_1 (基準) の pen_color が青系でない: {pen}"
        )
    for pen in (pen2_v, pen2_e):
        assert _is_orange_family(_rgb(pen)), (
            f"csv_2 (対象) の pen_color が橙系でない: {pen}"
        )

    vb0 = panel_view._view_boxes[0]
    image = pixmap = QApplication.primaryScreen().grabWindow(0)
    image = pixmap.toImage()
    samples = [
        (1.5, 1.5, pen1_v),  # VehSpd(csv_1)  band 0-2.9
        (1.5, 11.5, pen1_e),  # EngineSpeed(csv_1) band 10-12.9
        (1.5, 21.5, pen2_v),  # VehSpd(csv_2)  band 20-22.9
        (1.5, 31.5, pen2_e),  # EngineSpeed(csv_2) band 30-32.9
    ]
    for t, val, pen in samples:
        scene_pt = vb0.mapViewToScene(QPointF(t, val))
        col, row = to_phys(panel_view, scene_pt.x(), scene_pt.y())
        assert _find_pixel_near(image, col, row, _rgb(pen)), (
            f"実スクショに pen_color={pen} 相当のピクセルが (t={t}, v={val}) 付近に"
            f" 見つからない (col={col}, row={row}). screenshot: {shot_overlay}"
        )

    # ─── E-0 残り2面: Y軸メニューの曲線一覧・エクスポートツリー ────────────────
    spine0 = panel_view._y_axes[0].sceneBoundingRect()
    axis_px, axis_py = to_phys(panel_view, spine0.center().x(), spine0.center().y())
    shot_axis_menu = _EVIDENCE_DIR / "axis_menu_curve_list.png"
    axis_captured = _open_menu(panel_view, (axis_px, axis_py), shot_axis_menu)
    assert axis_captured.get("type") == "QMenu", (
        f"軸スパインの実右クリックでメニューが開かない: {axis_captured.get('type')!r}. "
        f"screenshot: {shot_axis_menu}"
    )
    axis_actions = list(axis_captured.get("actions") or [])
    assert axis_actions, "軸メニューにアクションが無い"
    assert not any("::" in a for a in axis_actions), (
        f"軸メニューに内部キー '::' が露出: {axis_actions}"
    )
    assert any(f"({key1})" in a for a in axis_actions) and any(
        f"({key2})" in a for a in axis_actions
    ), f"軸メニューの曲線一覧に併記名が無い: {axis_actions}"

    dlg = ExportCsvDialog(window.app_vm, initial_selected=set())
    dlg.show()
    _pump_n(3)
    shot_export = _EVIDENCE_DIR / "export_tree.png"
    dlg.grab().save(str(shot_export))
    leaf_texts: list[str] = []
    tree = dlg._tree
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        leaf_texts.append(top.text(0))
        for j in range(top.childCount()):
            leaf_texts.append(top.child(j).text(0))
    dlg.close()
    assert leaf_texts, "エクスポートツリーが空"
    assert not any("::" in t for t in leaf_texts), (
        f"エクスポートツリーに内部キー '::' が露出: {leaf_texts}. screenshot: {shot_export}"
    )

    window.close()


# ─── T-C1: 比較モードのユーザー切り替え実ジャーニー (Task 4 Step 1) ───────────


def test_comparison_mode_toggle_journey_realclick(qtbot: QtBot, tmp_path: Path) -> None:
    """実 OS で Analyze>比較モードをトグルし、家系色の出現/凍結・◎基準バッジの
    出現/消滅を実ピクセルで実証する (comparison-mode-toggle spec §7 T-C1)。

    4本 (VehSpd1/EngineSpeed1/VehSpd2/EngineSpeed2) を「重ねる」ボタンを使わず
    手動で直接プロットする — 比較モード OFF (既定) では affordance 自体が
    非表示 (spec §3 M7 対称化) なので使えないため。この直接プロットが同時に
    count-mod と家系色を実ピクセルで区別可能にする鍵になる:
    add 順の count-mod は「エントリ位置 mod パレット長」でファイル非依存に色を
    進めるため、csv_1 の2本目 (EngineSpeed1) は palette[1]=橙になる。一方、
    家系色は「ファイルごとに1色相・同ファイル内はバリアント」なので
    EngineSpeed1 は csv_1 の青ファミリーになる。この青/橙の反転が
    「トグル ON で家系色が実際に出現した」ことの動かぬ証拠になる。
    """
    skip_unless_real_display()
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.strings import strip_mnemonic
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    _EVIDENCE_DIR_TOGGLE.mkdir(parents=True, exist_ok=True)
    a_csv, b_csv = _build_fixture(tmp_path)

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)

    fmt_a = FormatDefinition(
        name="a_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    fmt_b = FormatDefinition(
        name="b_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=3,
        has_header=True,
    )
    session = window.app_vm.session
    outcome_a = session.load(a_csv, fmt_a)
    window._on_loaded(outcome_a)
    outcome_b = session.load(b_csv, fmt_b)
    window._on_loaded(outcome_b)
    key1, key2 = outcome_a.key, outcome_b.key

    assert window.app_vm.comparison_enabled is False, "既定はシングル (opt-in)"
    assert window.app_vm.is_comparison_mode() is False

    vehspd1 = _bare_key(session, key1, "VehSpd")
    engspeed1 = _bare_key(session, key1, "EngineSpeed")
    vehspd2 = _bare_key(session, key2, "VehSpd")
    engspeed2 = _bare_key(session, key2, "EngineSpeed")

    vm = window.graph_area_vm
    panel_vm = vm.panels(vm.active_tab_index)[vm.active_panel_index()]
    panel_vm.add_signal_to_axis(vehspd1, 0)
    panel_vm.add_signal_to_axis(engspeed1, 0)
    panel_vm.add_signal_to_axis(vehspd2, 0)
    panel_vm.add_signal_to_axis(engspeed2, 0)

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(
        screen.x() + 60,
        screen.y() + 60,
        min(1200, screen.width() - 120),
        min(820, screen.height() - 120),
    )
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    _pump_n(4)

    panel_view = next(w for _t, _p, w in window.graph_area_view._panel_views)
    qtbot.waitUntil(
        lambda: (
            bool(panel_view._view_boxes)
            and panel_view._view_boxes[0].sceneBoundingRect().height() > 100
        ),
        timeout=3000,
    )
    _pump_n(3)

    by_key = {sk: eid for eid, sk, _ax in panel_vm.plotted_entries()}

    def _pen(sk: str) -> str:
        return panel_view.pen_color(by_key[sk])

    vb0 = panel_view._view_boxes[0]

    def _pixel_matches(t: float, val: float, expected_hex: str) -> bool:
        scene_pt = vb0.mapViewToScene(QPointF(t, val))
        col, row = to_phys(panel_view, scene_pt.x(), scene_pt.y())
        image = QApplication.primaryScreen().grabWindow(0).toImage()
        return _find_pixel_near(image, col, row, _rgb(expected_hex))

    def _shot(name: str) -> Path:
        time.sleep(0.15)  # DWM compositor flush (memory: FU-12 の教訓)
        _pump_n(2)
        path = _EVIDENCE_DIR_TOGGLE / name
        with contextlib.suppress(Exception):
            QApplication.primaryScreen().grabWindow(0).save(str(path))
        return path

    fb = window.file_browser_view

    # ─── (1) トグル前 = count-mod・◎基準バッジなし ─────────────────────────
    pen_engspeed1_before = _pen(engspeed1)
    assert not _is_blue_family(_rgb(pen_engspeed1_before)), (
        "トグル前は count-mod のはずが engspeed1 が既に blue-family: "
        f"{pen_engspeed1_before}"
    )
    assert _is_orange_family(_rgb(pen_engspeed1_before)), (
        "count-mod で add 順2番目の engspeed1 は palette[1]=橙のはず: "
        f"{pen_engspeed1_before}"
    )
    assert not fb._vm.files[0].endswith(S.FILE_REFERENCE_BADGE_SUFFIX), (
        "トグル前は◎基準バッジが出ないはず"
    )

    shot_before = _shot("01_before_toggle_countmod.png")
    assert _pixel_matches(1.5, 11.5, pen_engspeed1_before), (
        f"トグル前スクショに count-mod 色 {pen_engspeed1_before} が見つからない。"
        f" screenshot: {shot_before}"
    )

    # ─── (2) 実 OS: メニューバー→Analyze→比較モード を実クリック (ON) ────────
    menubar = window.menuBar()
    analyze_action = next(
        a
        for a in menubar.actions()
        if strip_mnemonic(a.text()) == strip_mnemonic(S.MENU_ANALYZE)
    )
    _click(*_phys_center(menubar, menubar.actionGeometry(analyze_action)))
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None, timeout=3000)
    analyze_menu = QApplication.activePopupWidget()

    comparison_action = next(
        a for a in analyze_menu.actions() if a.text() == S.ACTION_COMPARISON_MODE
    )
    assert comparison_action.isEnabled(), "2ファイルロード済みなので有効のはず"
    assert not comparison_action.isChecked(), "トグル前は unchecked のはず"

    _click(*_phys_center(analyze_menu, analyze_menu.actionGeometry(comparison_action)))
    qtbot.waitUntil(lambda: window.app_vm.is_comparison_mode() is True, timeout=3000)
    _pump_n(4)

    assert window.app_vm.comparison_enabled is True
    assert comparison_action.isChecked()

    pen_engspeed1_on = _pen(engspeed1)
    assert _is_blue_family(_rgb(pen_engspeed1_on)), (
        f"ON 後は engspeed1 が家系色(青)のはずが: {pen_engspeed1_on}"
    )
    assert fb._vm.files[0].endswith(S.FILE_REFERENCE_BADGE_SUFFIX), (
        "ON 後は◎基準バッジが出るはず"
    )

    shot_on = _shot("02_after_toggle_on_families.png")
    assert _pixel_matches(1.5, 11.5, pen_engspeed1_on), (
        f"ON 後スクショに家系色 {pen_engspeed1_on} が見つからない。 screenshot: {shot_on}"
    )

    # ─── (3) 再度実クリックで OFF → 家系色は凍結 (count-mod へ戻らない) ─────
    _click(*_phys_center(menubar, menubar.actionGeometry(analyze_action)))
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None, timeout=3000)
    analyze_menu2 = QApplication.activePopupWidget()
    comparison_action2 = next(
        a for a in analyze_menu2.actions() if a.text() == S.ACTION_COMPARISON_MODE
    )
    assert comparison_action2.isChecked(), "再オープン時も checked が同期されるはず"

    _click(
        *_phys_center(analyze_menu2, analyze_menu2.actionGeometry(comparison_action2))
    )
    qtbot.waitUntil(lambda: window.app_vm.is_comparison_mode() is False, timeout=3000)
    _pump_n(4)

    assert window.app_vm.comparison_enabled is False
    assert not comparison_action2.isChecked()

    pen_engspeed1_off = _pen(engspeed1)
    assert pen_engspeed1_off == pen_engspeed1_on, (
        "OFF で色が変化した = 凍結でなく再着色/復帰してしまっている: "
        f"{pen_engspeed1_on!r} -> {pen_engspeed1_off!r}"
    )
    assert _is_blue_family(_rgb(pen_engspeed1_off)), (
        f"OFF 後も家系色(青)のまま凍結のはずが: {pen_engspeed1_off}"
    )
    assert not fb._vm.files[0].endswith(S.FILE_REFERENCE_BADGE_SUFFIX), (
        "OFF 後は◎基準バッジが消えるはず"
    )

    shot_off = _shot("03_after_toggle_off_frozen.png")
    assert _pixel_matches(1.5, 11.5, pen_engspeed1_off), (
        "OFF 後スクショに凍結された家系色 "
        f"{pen_engspeed1_off} が見つからない。 screenshot: {shot_off}"
    )

    window.close()
