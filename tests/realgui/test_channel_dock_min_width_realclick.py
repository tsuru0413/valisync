"""Layer C: real-display evidence for Task 5 (#14 拡張・spec §1.5) — shrinking
the channel_dock/file_dock column below the pre-fix ~258px pin.

`--realgui` opt-in・実ディスプレイ+Windows 必須。offscreen はフォント代替で
絶対 px が実機と大きく異なる (memory: gui_offscreen_grab_text_tofu 系) ため、
このテストは実ディスプレイ (real Windows フォント) で実際にウィンドウを表示・
撮影し、実測 px を報告する。

ドックのカラム幅変更そのものは ``resizeDocks()`` で駆動する — これは
QMainWindow の実ドックエリアレイアウトエンジン (``QDockAreaLayout``) を
インタラクティブなセパレータドラッグと**同一の経路**で駆動する正規の Qt API
であり (本タスクの実測で「既定構築幅とドラッグ到達幅は別物」であることを
確認する過程で何度も直接検証済み)、実際のマウスドラッグと同じ最終状態に
到達する。生のマウス press-move-release シーケンスによる検証も試みたが、
本機 (実際に他のアプリケーションが同時に開いている共有デスクトップ) 上で
原因不明のハング (要手動プロセス終了・マウスボタン安全解放2回) を引き起こし、
安全のため断念した — 詳細は Task 5 報告書を参照。"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui

# QSettings 隔離 (実 ValiSync 設定汚染/テスト間漏れ防止) は
# tests/realgui/conftest.py の autouse fixture が全 realgui テストへ適用する。

_LONG_NAME = "Radar.FrontLeft.Obj0.RelativeVelocityAlongVehicleAxis"


def _fmt() -> object:
    from valisync.core.models import Delimiter, FormatDefinition

    return FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )


def _shown_mw(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    path = tmp_path / "d.csv"
    path.write_text(
        f"t,{_LONG_NAME},VehSpd\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8"
    )
    app_vm = AppViewModel()
    key = app_vm.request_load(path, _fmt())
    app_vm.set_active_file(key)

    mw = MainWindow(app_vm)
    qtbot.addWidget(mw)
    mw._workbench_started = True
    mw._update_central()
    mw.showNormal()
    ag = QApplication.primaryScreen().availableGeometry()
    mw.setGeometry(
        ag.x() + 40,
        ag.y() + 40,
        min(1300, ag.width() - 80),
        min(800, ag.height() - 80),
    )
    qtbot.waitExposed(mw)
    for _ in range(6):
        QApplication.processEvents()
        time.sleep(0.02)
    return mw


def _grab(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    path = tmp_path / name
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(path))
    return path


def test_channel_dock_reaches_narrow_floor_on_real_display(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """実ディスプレイ (実フォント) で channel_dock の既定構築幅が修正前の
    258px 級より有意に細いこと、`resizeDocks` で詰めても同じ細い床に留まる
    こと (= 実ドラッグの最終状態と同一の Qt レイアウトエンジンで到達する床)、
    長い信号名が elide されること、`resizeDocks` で再拡大できることを実測・
    撮影で証明する (Task 5 Step 4)。"""
    skip_unless_real_display()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    mw = _shown_mw(qtbot, tmp_path)
    channel_dock = mw.channel_dock
    tree = mw.channel_browser_view.tree

    qtbot.waitUntil(
        lambda: tree.visualRect(tree.model().index(0, 0)).height() > 0, timeout=3000
    )

    default_width = channel_dock.width()
    shot_default = _grab(tmp_path, "default_width.png")
    print(
        f"[task5] real-display channel_dock.width() default={default_width} "
        f"screenshot={shot_default}"
    )

    # Pre-fix baseline (Task 4/5 measurement) was a deterministic ~258px
    # (Qt's hardcoded QAbstractScrollArea sizeHint fallback + 2px frame) --
    # font/DPI-independent, so this comparison is safe even though the
    # *floor* itself (below) is font-dependent across environments.
    assert default_width < 258, (
        f"既定構築幅が修正前の 258px 級から下がっていない (default={default_width})."
        f" screenshot: {shot_default}"
    )

    # Task 5 追調整 (ユーザー決定): 既定構築幅は最小まで詰めた床 (~181px) では
    # なく中間の ~200px を狙う (実測: _TREE_SIZEHINT_WIDTH=198 ->
    # channel_dock.width()==200 ぴったり)。フォント差でズレる可能性を見込み
    # レンジで許容する。
    assert 190 <= default_width <= 215, (
        "既定構築幅が目標の中間値 (~200px 近傍) から外れている "
        f"(default={default_width}). screenshot: {shot_default}"
    )

    # Drive the same QMainWindow dock-area layout engine an interactive
    # separator drag would (resizeDocks is the programmatic entry point to
    # QDockAreaLayout::resizeDocks, used identically by mouse-driven resize).
    mw.resizeDocks([channel_dock], [1], Qt.Orientation.Horizontal)
    for _ in range(8):
        QApplication.processEvents()
        time.sleep(0.02)
    floor_width = channel_dock.width()
    shot_floor = _grab(tmp_path, "shrunk_floor_width.png")
    print(
        f"[task5] real-display channel_dock.width() floor={floor_width} "
        f"screenshot={shot_floor}"
    )
    # <=, not <: resizeDocks は「それより細くはならない」ことだけを保証すれば
    # よい (floor が default と一致する環境があっても劣化ではない)。
    #
    # Task 5 追調整 (ユーザー決定) 前は、既定構築幅が title-bar 律速の floor
    # にぴったり一致していた (default==floor==~181px、当時のベストケース)。
    # 追調整後は既定構築幅を意図的に floor より広い中間値 (~200px) にした
    # ので、通常はここで floor_width < default_width になる (ドラッグで
    # さらに 181px まで詰められることを示す = 最小幅維持の実証)。
    assert floor_width <= default_width, (
        "resizeDocks で channel_dock が既定幅より広がってしまった (退行) "
        f"(default={default_width}, floor={floor_width}). screenshot: {shot_floor}"
    )
    assert floor_width < 230, (
        f"目標下限 (~181px 近傍・実測はフォント依存) に対して有意な改善が"
        f"見られない (floor={floor_width}). screenshot: {shot_floor}"
    )
    assert floor_width < default_width, (
        "既定幅とドラッグ最小床が一致してしまっている -- 中間幅への追調整"
        f"(ユーザー決定) が効いていない可能性 (default={default_width}, "
        f"floor={floor_width}). screenshot: {shot_floor}"
    )

    # Elide check on real rendering: the long name's full rendered width
    # must now exceed the narrowed Name column, so Qt's ElideRight kicks in.
    metrics = tree.fontMetrics()
    full_width = metrics.horizontalAdvance(_LONG_NAME)
    name_col_width = tree.columnWidth(0)
    assert name_col_width < full_width, (
        "Name 列が長い信号名のフル幅より広いままで elide の前提条件が満たされ"
        f"ない (name_col_width={name_col_width}, full_width={full_width})."
    )

    # Widen back: the same engine must grow the dock (and the Stretch-mode
    # Name column with it) again -- nothing gets permanently stuck narrow.
    mw.resizeDocks([channel_dock], [400], Qt.Orientation.Horizontal)
    for _ in range(8):
        QApplication.processEvents()
        time.sleep(0.02)
    widened_width = channel_dock.width()
    widened_name_col = tree.columnWidth(0)
    shot_widened = _grab(tmp_path, "widened_again.png")
    print(
        f"[task5] real-display channel_dock.width() widened={widened_width} "
        f"name_col={widened_name_col} screenshot={shot_widened}"
    )
    assert widened_width > floor_width + 20, (
        "再拡大で channel_dock が有意に広がらなかった "
        f"(floor={floor_width}, widened={widened_width}). screenshot: {shot_widened}"
    )
    assert widened_name_col > name_col_width, (
        "再拡大で Name 列 (Stretch モード) が広がらなかった "
        f"(narrow={name_col_width}, widened={widened_name_col})."
    )


def test_channel_dock_default_width_tracks_sizehint_widening(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 5 追調整 (ユーザー決定) の因果関係を実 display で直接実証する:
    _TREE_SIZEHINT_WIDTH/_FILE_LIST_SIZEHINT_WIDTH を追調整前のタイトな値
    (120・当時の既定=床=~181px) へ monkeypatch すると channel_dock の既定
    構築幅が有意に狭くなること。

    file_dock と channel_dock は同一カラムに縦積みのため、片方だけ patch
    しても列幅は変わらない (両者の sizeHint の max で列幅が決まる -- Task 5
    のクロスファイルブロッカーと同型。実際、channel 側だけ patch する初期
    実装ではこのテストが honest-RED にならず 200==200 で失敗し、この
    cross-file 依存を再発見した)。

    offscreen では書けない (実測: QT_QPA_PLATFORM=offscreen は "This plugin
    does not support propagateSizeHints()" のとおり sizeHint 変更が
    channel_dock.width() へ一切反映されない -- 120/198/400 いずれも同じ
    230px に張り付く。real display のみが sizeHint→レイアウトの伝播を
    正しく反映するため、この比較は realgui に置く。マウス操作は一切なし
    (MainWindow を2つ独立構築して比較するのみ)。"""
    skip_unless_real_display()

    import valisync.gui.views.channel_browser_view as cbv
    import valisync.gui.views.file_browser_view as fbv

    mw_wide = _shown_mw(qtbot, tmp_path)
    wide_default = mw_wide.channel_dock.width()
    print(
        f"[task5] real-display wide (_TREE_SIZEHINT_WIDTH=198) default={wide_default}"
    )

    monkeypatch.setattr(cbv, "_TREE_SIZEHINT_WIDTH", 120)
    monkeypatch.setattr(fbv, "_FILE_LIST_SIZEHINT_WIDTH", 120)
    mw_narrow = _shown_mw(qtbot, tmp_path)
    narrow_default = mw_narrow.channel_dock.width()
    print(
        f"[task5] real-display narrow (both sizeHint widths=120) "
        f"default={narrow_default}"
    )

    assert wide_default > narrow_default, (
        "既定構築幅が sizeHint 定数に連動していない (中間幅への"
        f"調整が効いていない可能性): wide={wide_default}, narrow={narrow_default}"
    )
