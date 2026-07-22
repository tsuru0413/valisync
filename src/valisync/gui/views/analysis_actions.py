"""解析系 QAction の共有ファクトリ (計測 IA 刷新 spec §2.2)。

Analyze メニュー (MainWindow) と各パネルの空白右クリックメニュー
(GraphPanelView.build_context_menu) はチェック状態・文言が乖離しないよう、この
モジュールが生成する **同一の QAction インスタンス** を掲載する。生成箇所を1つに
閉じ込める。

配線規約 (レビュー blocker): 共有 checkable QAction の VM 変異は **triggered 配線
のみ**。``toggled`` は禁止 — aboutToShow / メニュー構築時の ``setChecked`` 同期は
``toggled`` を発火させるが ``triggered`` は発火させない (Qt の仕様) ため、
triggered だけに繋ぐことで「メニューを開いただけでカーソルが動く」事故を構造的に
防ぐ ([[gui_qactiongroup_exclusive_radio_menu]] の適用範囲を共有 checkable 全体へ
拡大)。

再ターゲット可能な dispatch (設計レビュー修正・spec §2.2 拘束): trigger 時に
「対象にするパネル」を解決する先は、共有 QAction インスタンス内部が持つ**書き換え
可能なターゲット**であって、生成時に固定した callable ではない。呼び出し側
(MainWindow の Analyze aboutToShow / GraphPanelView.build_context_menu) は
``sync_analysis_actions(actions, pvm)`` を呼ぶたびにターゲットを *pvm* へ再設定
する。メニューは常にモーダル (exec) で1つずつしか開かないため、trigger 時点で
「生きている」ターゲットは常に直前に同期した1つだけ — Analyze 経由はアクティブ
パネル、空白メニュー経由は右クリックされたパネル (=そのメニューを build した
self.vm) に正しく配送される。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QActionGroup

from valisync.core.interpolation import InterpolationMethod
from valisync.gui import strings as S
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

# Interp method → メニューラベル。GraphAreaView の readout ヘッダ表示も同じ辞書を
# 使う (単一の真実 — PC-09 由来の既存規約を踏襲)。
_INTERP_LABELS: dict[InterpolationMethod, str] = {
    InterpolationMethod.LINEAR: "線形",
    InterpolationMethod.ZERO_ORDER_HOLD: "前値保持",
    InterpolationMethod.NEAREST: "最近傍",
}


@dataclass(frozen=True)
class AnalysisActions:
    """Analyze メニューと空白メニューが共有する解析系 QAction 群。

    ``set_target`` は生成元の :func:`build_analysis_actions` クロージャが握る
    単一の書き換え可能な状態 (trigger 時のターゲット) を差し替える関数。
    ``sync_analysis_actions`` からのみ呼ぶ — 個別に呼ぶ場合は checked/enabled
    の同期を忘れないこと。
    """

    cursor_a: QAction
    cursor_b: QAction
    clear_cursors: QAction
    interp_actions: dict[InterpolationMethod, QAction]
    step_hint: QAction
    set_target: Callable[[GraphPanelVM | None], None]


def build_analysis_actions(parent: QObject) -> AnalysisActions:
    """解析系 QAction を1セット生成する (単一定義 — spec §2.2)。

    QAction の triggered スロットは、このクロージャが閉じ込める単一の書き換え
    可能なターゲット (初期値 None) だけを参照する — QWidget (self) を直接
    close over しないため、Qt 親子関係を介した参照循環も作らない。ターゲットの
    書き換えは ``sync_analysis_actions`` が担う。
    """
    target: GraphPanelVM | None = None

    def _get_target() -> GraphPanelVM | None:
        return target

    def _set_target(pvm: GraphPanelVM | None) -> None:
        nonlocal target
        target = pvm

    cursor_a = QAction(S.CURSOR_A, parent)
    cursor_a.setCheckable(True)
    cursor_a.setStatusTip("表示範囲の中央に設置 / 解除")

    def _toggle_a(checked: bool) -> None:
        pvm = _get_target()
        if pvm is not None:
            pvm.toggle_main_cursor(checked)

    cursor_a.triggered.connect(_toggle_a)

    cursor_b = QAction(S.CURSOR_B_DELTA, parent)
    cursor_b.setCheckable(True)
    cursor_b.setStatusTip("Shift+クリックで設置")

    def _toggle_b(checked: bool) -> None:
        pvm = _get_target()
        if pvm is not None:
            pvm.toggle_delta(checked)

    cursor_b.triggered.connect(_toggle_b)

    clear_cursors = QAction(S.CURSOR_CLEAR, parent)

    def _clear(_checked: bool = False) -> None:
        pvm = _get_target()
        if pvm is not None:
            pvm.toggle_main_cursor(False)  # A/B 全消去 (set_cursor(None) の不変条件)

    clear_cursors.triggered.connect(_clear)

    interp_group = QActionGroup(parent)
    interp_group.setExclusive(True)
    interp_actions: dict[InterpolationMethod, QAction] = {}
    for method, label in _INTERP_LABELS.items():
        act = QAction(label, parent)
        act.setCheckable(True)
        act.setActionGroup(interp_group)

        def _set_interp(
            _checked: bool = False, m: InterpolationMethod = method
        ) -> None:
            pvm = _get_target()
            if pvm is not None:
                pvm.set_interp_method(m)

        # _checked/m=method (キーワード既定値) はループ変数の late-binding を
        # 避ける既存規約 (旧 build_context_menu の補間 radio で使われていたパターン)。
        act.triggered.connect(_set_interp)
        interp_actions[method] = act

    # 情報行 (spec §2.2): 操作ではなく既存ジェスチャの説明のみ。無効化して選択不可に。
    step_hint = QAction("← / → サンプルステップ", parent)
    step_hint.setEnabled(False)

    return AnalysisActions(
        cursor_a=cursor_a,
        cursor_b=cursor_b,
        clear_cursors=clear_cursors,
        interp_actions=interp_actions,
        step_hint=step_hint,
        set_target=_set_target,
    )


def sync_analysis_actions(actions: AnalysisActions, pvm: GraphPanelVM | None) -> None:
    """*pvm* を trigger 時のターゲットとして再設定した上で checked/enabled を同期する。

    レビュー修正 (spec §2.2 拘束): 呼び出し元 (Analyze の aboutToShow /
    GraphPanelView.build_context_menu) はメニューを開く直前に必ずこれを呼ぶ。
    メニューはモーダル (exec) なので trigger 時点で「生きている」ターゲットは
    常に直前にここで設定した1つ — 複数パネル環境でも取り違えない。

    setChecked は toggled は発火させても triggered は発火させないため、ここで
    無条件に呼んでも共有 QAction の triggered ハンドラ (= 上のターゲット再設定を
    含む) は起動しない。
    """
    actions.set_target(pvm)
    has_a = pvm is not None and pvm.cursor_t is not None
    actions.cursor_a.setEnabled(pvm is not None)
    actions.cursor_a.setChecked(has_a)
    actions.cursor_b.setEnabled(has_a)
    actions.cursor_b.setChecked(pvm is not None and pvm.delta_enabled)
    actions.cursor_b.setToolTip("" if has_a else "カーソル A を有効化すると使えます")
    actions.clear_cursors.setEnabled(has_a)
    method = pvm.interp_method if pvm is not None else None
    for m, act in actions.interp_actions.items():
        act.setChecked(m is method)
