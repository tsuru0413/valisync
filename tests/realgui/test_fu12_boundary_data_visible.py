"""Layer C (realgui): FU-12 -- 境界値データが実ディスプレイでプロット枠から浮く。

純描画テスト(実 OS 入力なし)。単一フルハイト軸に信号を1本載せ、set_axis_range で
軸レンジの min をデータの最小値そのものに固定する(境界条件を確定させる -- A や
_padded_range の自動 pad に頼らない)。ViewBox の mapViewToScene で「データの最下点
がプロット下枠から AXIS_INSET_MARGIN の半分以上浮いている」ことを実描画済みの
scene 幾何でアサートし、実 OS の grabWindow で実ディスプレイのスクショを保存する
(クリック等の合成入力は一切行わない -- 純粋な描画結果の記録であり、
memory gui_realgui_synthetic_click_mislabeled_layer_c が警告する
「合成クリックを Layer C と誤表示する」問題は該当しない。証拠は QWidget.grab()
(オフスクリーンでも動く Qt 内部レンダーで実ディスプレイを証明しない)ではなく
QScreen.grabWindow() -- 実 OS の画面バッファを読む -- を使い、Layer C 契約ガード
tests/gui/test_realgui_layer_c_contract.py の要求(実入力 or grabWindow)も満たす)。

headless 側の同値契約は test_boundary_data_lifts_off_frame_autofit /
test_boundary_data_lifts_off_frame_manual_range (tests/gui/test_graph_panel_render_geometry.py)
で ViewBox 幾何として証明済み -- 本テストはそれを実ディスプレイの実レンダーパイプライン
(実ウィンドウ・実ペイント・実スクリーンショット)で裏取りする。

FU-12 final review 是正: 上記の mapViewToScene 幾何アサートだけでは offscreen でも
一字一句同じ結果になり(pyqtgraph の内部レンダーパイプラインを検証しているだけで、
実ディスプレイの描画結果は一度も見ていない)、headless 側の Layer B テストと同じ
契約の重複に過ぎず判別力がほぼゼロだった。実ディスプレイでの判別力を持たせるため、
grabWindow で撮った実スクショを QImage として実ピクセル走査し、「曲線色のピクセルが
実際にフレーム下端より上に描かれている」ことをピクセル座標で直接裏取りする
(backstop)。座標変換は tests/realgui/_realgui_input.to_phys が担う既存の scene->
物理スクリーンピクセル変換(DPR 込み)を再利用し、実 OS 入力ヘルパ群と同じ変換経路を
使うことで新規のズレ源を持ち込まない。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display, to_phys

pytestmark = pytest.mark.realgui


def _show_single_signal_panel(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_single_signal_panel

    view = make_single_signal_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # Fully on-screen (avoid off-screen clamp / partial paint on grab()).
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 80, screen.y() + 80, 800, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return view


def test_fu12_boundary_data_visible_on_real_display(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """境界値(軸レンジ min == データ最小値)が実ディスプレイでプロット下枠から浮く。

    合成入力は一切ない(mount -> auto-fit 確認 -> set_axis_range で境界固定 ->
    refresh -> geometry アサート -> 実 grabWindow スクショ保存、の純描画フロー)。
    """
    skip_unless_real_display()
    import time

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from valisync.gui.views.graph_panel_view import AXIS_INSET_MARGIN

    view = _show_single_signal_panel(qtbot)
    vm = view.vm

    assert vm.axes[0].y_range is not None
    y_lo, y_hi = vm.axes[0].y_range
    vm.set_axis_range(0, y_lo, y_hi)  # min == データ値(境界条件を確定、pad なし)
    view.refresh()
    for _ in range(3):
        QApplication.processEvents()
    # 実ピクセル走査は grabWindow の生スクショに依存するため、Qt 側の論理状態
    # (ViewBox の Y レンジ)が更新済みでも、OS コンポジタ(DWM)が実際の画面
    # フレームバッファへその再描画をまだ反映していない可能性がある。processEvents
    # だけ(壁時計 sleep なし)では compositor の flush を待たず、grabWindow が
    # 1フレーム前の stale な内容を拾って実ピクセル走査を偽陽性/偽陰性にする
    # (実測: sleep なしだと margin=0 sabotage 時にも旧フレームの浮きが写り込み
    # honest-RED が得られなかった)。壁時計 sleep を挟んで compositor に追いつかせる。
    time.sleep(0.15)
    for _ in range(3):
        QApplication.processEvents()

    vb = view._view_boxes[0]
    R = vb.sceneBoundingRect()
    frame_bot_scene = R.y() + R.height()
    data_bot_scene = vb.mapViewToScene(QPointF(0.0, y_lo)).y()
    lift_px = frame_bot_scene - data_bot_scene

    # 実 OS の画面バッファを読む(スクショ artifact は必ず残す -- 走査/アサートが
    # 何であれ、あとで目視できる証跡を suppress で握りつぶさない)。
    screenshot = tmp_path / "fu12_boundary_data_visible.png"
    pixmap = QApplication.primaryScreen().grabWindow(0)
    assert pixmap.save(str(screenshot)), (
        f"grabWindow スクショの保存に失敗: {screenshot}"
    )

    # 幾何アサート(scene 座標 -- offscreen でも同じ結果になる pyqtgraph 内部の
    # レンダーパイプライン検証。実ディスプレイの backstop はこの下のピクセル走査)。
    assert lift_px >= 0.5 * AXIS_INSET_MARGIN * R.height(), (
        f"境界データがフレームから浮いていない(lift={lift_px:.1f}px). "
        f"screenshot: {screenshot}"
    )

    # --- 実ピクセル走査(backstop): 実ディスプレイの実際の描画結果を見る ---
    # 曲線は make_single_signal_panel の v=t(単調増加)で、境界最小点は x=0 の
    # 1点のみ。x=0 から数サンプル右までの列帯(v=t の単調増加により、この帯の中で
    # 「フレーム下端から見て最初に見つかる(=最も row が大きい=最も低い)曲線色の
    # ピクセル」は必ず x=0 の境界点に属する -- 帯を広げても誤って別の低い点を
    # 拾うことはない)を、フレーム下端から上へスキャンする。
    #
    # 列範囲は x=0(ViewBox の左端そのもの)より左には絶対に出さない -- 最初の
    # 実装は左に 3px の余白を取ったところ、Y 軸の目盛ラベル("0.00" 等、ViewBox の
    # 外・左側のガター)の文字アンチエイリアス端(ClearType のサブピクセル
    # フリンジで純グレーの文字が青みがかった色になることがある)を誤検出し、
    # margin=0 の sabotage でも "曲線ピクセル" が見つかったことになる false-green
    # を招いた。右方向にのみ余白を取り、ガターへは踏み込まない。
    image = pixmap.toImage()
    dpr = view.devicePixelRatioF()

    scene_x_lo = vb.mapViewToScene(QPointF(0.0, y_lo)).x()
    scene_x_hi = vb.mapViewToScene(QPointF(0.06, y_lo)).x()
    col_lo, row_bot = to_phys(view, scene_x_lo + 1, frame_bot_scene)
    col_hi, _row_bot2 = to_phys(view, scene_x_hi, frame_bot_scene)
    search_top_scene = frame_bot_scene - 0.15 * R.height()
    _col, row_top = to_phys(view, scene_x_lo, search_top_scene)

    # 判定ヒューリスティクスの前提: palette[0] が青優勢 (b が r/g を 20 以上上回る)。
    # 再デザイン反復で palette[0] が青でなくなったら、ここが先に落ちて
    # ヒューリスティクスの更新を要求する (無言のスキャン失敗にしない)。
    from valisync.gui.theme.tokens import active

    pen0 = active().colors.signal_palette[0]
    assert pen0.b > pen0.g + 20 and pen0.b > pen0.r + 20, (
        f"palette[0]={pen0.hex} が青優勢でない — _is_curve_pixel をトークン値に合わせて更新せよ"
    )

    def _is_curve_pixel(color: QColor) -> bool:
        # 背景 plot_background=黒、曲線ペンは signal_palette[0] (青優勢)。
        # 青チャンネルが赤・緑を明確に上回る特徴は黒背景との混色でも保たれる。
        r, g, b, _a = color.getRgb()
        return b > g + 20 and b > r + 20

    found_row: int | None = None
    for row in range(row_bot, row_top - 1, -1):
        if any(
            _is_curve_pixel(image.pixelColor(col, row))
            for col in range(col_lo, col_hi + 1)
        ):
            found_row = row
            break

    assert found_row is not None, (
        "実ディスプレイの grabWindow 画像内で曲線色のピクセルが見つからなかった "
        f"(走査範囲: col={col_lo}..{col_hi}, row={row_top}..{row_bot}). "
        f"screenshot: {screenshot}"
    )

    lift_device_px = row_bot - found_row
    lift_logical_px = lift_device_px / dpr
    # 意図的にハードコード: AXIS_INSET_MARGIN を掛けて閾値を作ると、AXIS_INSET_MARGIN
    # 自体が margin=0 に退行したとき閾値も 0 へ一緒に縮み、このアサートが常に通って
    # しまう(sabotage 走査で実測・honest-RED を得るには production 定数から独立した
    # 閾値が必須)。0.012 == 0.4 * 現行設計値 0.03 を固定値として埋め込む。
    min_expected_logical_px = 0.012 * R.height()
    assert lift_logical_px >= min_expected_logical_px, (
        "実ディスプレイの実ピクセルで境界データがフレームから浮いていない "
        f"(lift={lift_logical_px:.1f}px logical, 期待>={min_expected_logical_px:.1f}px). "
        f"曲線ピクセル row={found_row}, フレーム下端 row={row_bot}. "
        f"screenshot: {screenshot}"
    )
