"""Layer C: 遅延ロードの勝利を実 GUI で end-to-end 実証 (Task 8・①ゲート)。

honest layering (gui-e2e-acceptance §Task 8): ``_values_source.is_materialized``
は「lazy か eager か」の *メカニズム* 証明 — RSS の代理ではない。ここでは実
ディスプレイの本物の MainWindow で実 mf4 (prod_demo.mf4・1.36GB・264k 信号) を
実ロード経路でロードし、実 OS 入力で 1 本だけプロットして、

  (a) プロットした信号は実際に描画される (RenderCurve が非空)、
  (b) *開いた直後* は全信号が未展開 (is_materialized == False) = open はメタ+master のみ、
  (c) 1 本プロット後も *未プロット* 信号は全数未展開のまま、

を assert する。headless の直叩きは namespaced ラッパー/オフセット/描画の実経路を
迂回しうるため、遅延がユーザーの実操作を貫通することはここでしか証明できない
(RSS の実測は scripts/measure_lazy_footprint.py が担う — 両方必要)。

実マウスドラッグは使わない (共有マシンでハング・memory gui_realgui_drag_qtimer_hang)。
プロットは実クリックで行を選択 → 実右クリックメニュー「アクティブパネルに追加」を
実クリック、である (double-click は FU-13 でプレビューに変更・Enter 追加は無いため、
右クリックメニューが唯一の実プロット経路)。

E-3 (列展開の遅延化) 以後、「未展開」オラクルだけでは**恒真**になる: 列 Signal は
ロード時に存在せず、鋳造された列は ``SignalGroup.signals`` の外 (副テーブル
``SignalGroupManager._resolved_by_key``) に居るため ``session.group_signals()`` の
走査に**現れない**。そこで本ファイルは非鋳造 introspection (``mint_count`` /
``resolved_keys()``) を併用し、「親を展開しても鋳造 0・列を 1 本プロットして初めて
**その列だけ**が鋳造される」を実 OS 入力で assert する
(``test_expanding_parent_and_plotting_one_column_mints_only_that_column``)。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import write_mdf4_flatten_fixture
from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
)
from tests.realgui._realgui_input import key as key_input
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui

_PROD_MF4 = Path("D:/Programming/projects/valisync/demo_data/prod_demo.mf4")
_LOAD_TIMEOUT_MS = 180_000  # prod_demo は 1.36GB — 遅延ロードでも数秒〜十数秒


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int) -> None:
    for _ in range(n):
        _pump(0.02)


def _real_click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    _pump_n(4)


def _phys_center(w, local) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    gp = w.mapToGlobal(local)
    dpr = w.devicePixelRatioF()
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _shot(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    p = tmp_path / f"{name}.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(p))
    return p


def _build_window(qtbot: QtBot):  # type: ignore[no-untyped-def]
    """実ディスプレイ上の本物の MainWindow (画面内へ配置・前面化)。

    1024 ガード (LD-14 の展開確認モーダル) は E-3 で退役したので
    ``_expansion_confirmer`` の差し替えは行わない — 全チャンネルが無条件に
    ロードされる (そもそも列は展開されない)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    w = min(1200, screen.width() - 120)
    h = min(800, screen.height() - 120)
    window.setGeometry(screen.x() + 60, screen.y() + 60, w, h)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    _pump_n(3)
    return window


def _panel_widget(window, tab: int, panel: int):  # type: ignore[no-untyped-def]
    return window.graph_area_view.tabs.widget(tab).widget(panel)


def _top_names(model) -> list[str]:  # type: ignore[no-untyped-def]
    """トップレベル行の Name 列 (子は触らない = 合成も鋳造も誘発しない)。"""
    return [model.data(model.index(r, 0)) for r in range(model.rowCount())]


def _child_names(model, parent) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        model.data(model.index(r, 0, parent)) for r in range(model.rowCount(parent))
    ]


def _row_of(model, name: str) -> int:  # type: ignore[no-untyped-def]
    names = _top_names(model)
    assert name in names, f"トップ行に {name!r} が無い: {names}"
    return names.index(name)


def _click_expand_arrow(tree, index) -> None:  # type: ignore[no-untyped-def]
    """展開アフォーダンス (ブランチインジケータ) を実クリックする。

    QTreeView は rootIsDecorated の矢印を item 矩形の **左** の
    ``indentation()`` 幅の帯に描く。``visualRect`` はテキスト側の矩形なので、
    その左端から半インデント戻った点がユーザーが実際に叩く三角形の中心。
    """
    from PySide6.QtCore import QPoint

    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "展開対象行が可視域に無い"
    indent = tree.indentation()
    assert indent > 0, "indentation が 0 — 展開矢印が存在しない"
    arrow_x = rect.left() - indent // 2
    # 負値を黙って 2px へ丸めると、ジオメトリ計算の誤りが「どこか別の場所への
    # 誤クリック」として静かに揉み消される。丸めず失敗させる。
    assert arrow_x > 0, (
        f"展開矢印の想定 x が負 (rect.left()={rect.left()}, indent={indent}, "
        f"x={arrow_x}) — インデント計算が壊れている"
    )
    local = QPoint(arrow_x, rect.center().y())
    _real_click(*_phys_center(tree.viewport(), local))


def _first_scalar_leaf_row(model) -> int:  # type: ignore[no-untyped-def]
    """First top-level row that is a scalar leaf (signal_key_at not None).

    Array bases (LD-14) collapse under parent rows whose ``signal_key_at`` is
    None; scalars stay top-level leaves. Scanning only top-level indexes is
    lazy-safe — it never materializes a group's children (FU-22 B).
    """
    for row in range(model.rowCount()):
        if model.signal_key_at(model.index(row, 0)) is not None:
            return row
    raise AssertionError("チャンネルツリーにスカラー葉が無い")


def _count_materialized(session, key: str) -> list[str]:  # type: ignore[no-untyped-def]
    """値が展開済みの Signal 名 (**物理チャンネル + 鋳造列**)。

    反転後、鋳造した列 Signal は ``SignalGroup.signals`` の外 —
    ``SignalGroupManager._resolved_by_key`` の副テーブル — に居るので、
    ``group_signals()`` だけを走査すると鋳造列の展開が丸ごと会計から落ちる
    (「何列鋳造して読んでも leak ゼロ」が通る恒真テストになる)。

    副テーブルの列挙は ``resolved_keys()`` (鋳造を誘発しない introspection) で行い、
    実体は ``resolve()`` で取る — 既に鋳造済みのキーなのでキャッシュヒットであり、
    観測が新たな鋳造を作らない (観測が対象を変えない)。
    """
    mgr = session._groups
    names = [
        s.name for s in session.group_signals(key) if s._values_source.is_materialized
    ]
    for col_key in sorted(mgr.resolved_keys(key)):
        col = mgr.resolve(col_key)
        if col is not None and col._values_source.is_materialized:
            names.append(col.name)
    return names


def _real_select_and_menu_add(window, index) -> None:  # type: ignore[no-untyped-def]
    """Scroll *index* into view, real-click to select, then real right-click and
    real-click the "アクティブパネルに追加" menu item (nested QMenu.exec).

    An ESC watchdog closes a stuck popup so a missed click fails on an
    assertion rather than hanging the shared machine.
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    tree = window.channel_browser_view.tree
    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "対象行が可視域に無い (実クリックできない)"
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    px, py = _phys_center(vp, local)
    _real_click(px, py)  # select the row → "アクティブパネルに追加" enabled

    loop = QEventLoop()
    seen: dict[str, object] = {}

    def right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def click_item() -> None:
        menu = QApplication.activePopupWidget()
        seen["popup"] = type(menu).__name__ if menu is not None else None
        if isinstance(menu, QMenu):
            act = next(
                (a for a in menu.actions() if a.text() == S.ACTION_ADD_TO_ACTIVE_PANEL),
                None,
            )
            seen["action_found"] = act is not None
            if act is not None:
                gc = menu.mapToGlobal(menu.actionGeometry(act).center())
                dpr = menu.devicePixelRatioF()
                mx, my = round(gc.x() * dpr), round(gc.y() * dpr)
                at(mx, my, LDOWN)
                at(mx, my, LUP)
        loop.quit()

    def watchdog() -> None:
        if isinstance(QApplication.activePopupWidget(), QMenu):
            key_input(VK_ESCAPE)
        loop.quit()

    QTimer.singleShot(300, right_click)
    QTimer.singleShot(1000, click_item)
    QTimer.singleShot(1600, watchdog)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()

    assert seen.get("popup") == "QMenu", (
        f"実右クリックでコンテキストメニューが出ない: {seen}"
    )
    assert seen.get("action_found"), (
        f"メニューに {S.ACTION_ADD_TO_ACTIVE_PANEL!r} が無い: {seen}"
    )


def test_lazy_load_keeps_unplotted_unmaterialized(qtbot: QtBot, tmp_path: Path) -> None:
    """実 mf4 ロード → 1 本実プロット → 未プロットは全数未展開 (実 OS 入力・prod スケール)。"""
    skip_unless_real_display()
    if not _PROD_MF4.exists():
        pytest.skip(f"prod スケール mf4 が無い: {_PROD_MF4}")

    window = _build_window(qtbot)

    # ── 実ロード経路 (LoadController off-thread + busy overlay) を駆動 ──
    window._load_file(_PROD_MF4)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )
    loaded_key = window.app_vm.loaded_file_keys[0]
    session = window.app_vm.session
    mgr = session._groups  # C-e: Session には出さない introspection
    group_sigs = session.group_signals(loaded_key)
    n_physical = len(group_sigs)
    n_columns = session.total_column_count(loaded_key)
    # 反転後 group_signals() は **物理チャンネル** — 規模の主張は列数側でも張る
    # (物理 4,324 だけを見て「prod スケール」と言うと桁を 60 倍取り違える)。
    assert n_physical > 1000 and n_columns > 100_000, (
        f"prod スケールで無い (物理 {n_physical:,} / 列 {n_columns:,})"
    )
    _shot(tmp_path, "01_loaded")

    # (b) open = メタ+master のみ: プロット前は全信号が未展開。
    materialized_before = _count_materialized(session, loaded_key)
    assert materialized_before == [], (
        f"開いた直後に値が展開されている (open が eager の疑い): "
        f"{materialized_before[:5]} ... 計 {len(materialized_before)}"
    )
    assert mgr.mint_count == 0, (
        f"開いた直後に列が鋳造されている (open が列を触っている): {mgr.mint_count}"
    )

    # ── チャンネルツリーが reset を終えるのを待つ ──
    model = window.channel_browser_view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=_LOAD_TIMEOUT_MS)
    _pump_n(6)
    leaf_row = _first_scalar_leaf_row(model)
    plotted_key = model.signal_key_at(model.index(leaf_row, 0))
    assert plotted_key is not None

    # ── 実クリックで行選択 → 実右クリックメニュー「追加」を実クリック ──
    vm = window.graph_area_vm
    _real_select_and_menu_add(window, model.index(leaf_row, 0))

    panel = _panel_widget(window, 0, 0)  # 既定 1 パネル (active) へ着地
    panel_vm = vm.panels(0)[0]
    qtbot.waitUntil(lambda: plotted_key in panel_vm.plotted_signal_keys(), timeout=5000)
    _pump_n(4)
    shot = _shot(tmp_path, "02_one_plotted")

    # (a) プロットした信号が実際に描画される (RenderCurve が非空)。
    assert plotted_key in panel.signal_keys_drawn(), (
        f"プロットした信号がパネルに実描画されない: {plotted_key!r}。{shot}"
    )
    entry_id = panel.entry_id_for(plotted_key)
    xs, _ys = panel.curve_xy(entry_id)
    assert xs is not None and len(xs) > 0, (
        f"描画カーブが空 (値が読まれていない疑い): {plotted_key!r}。{shot}"
    )

    # (c) プロット後も未プロットは全数未展開 — 展開されたのはプロットした 1 本のみ。
    materialized_after = _count_materialized(session, loaded_key)
    leaked = [name for name in materialized_after if name != plotted_key]
    assert leaked == [], (
        f"未プロット信号が展開された (遅延が実 GUI を貫通していない): "
        f"{leaked[:5]} ... 計 {len(leaked)} 展開 (plotted={plotted_key!r})。{shot}"
    )
    # プロットした信号は展開済み = レンダが実際に値を読んだ (no-op pass を排除)。
    assert plotted_key in materialized_after, (
        f"プロットした信号が展開されていない (レンダが値を読んでいない疑い): "
        f"{plotted_key!r}。{shot}"
    )
    # スカラー葉は物理チャンネルそのもの = 鋳造経路を **通らない**。この経路が
    # 鋳造していたら、それは解決器が物理キーを副テーブルへ横流ししている印。
    assert mgr.mint_count == 0, (
        f"スカラー葉のプロットで列が鋳造された: {mgr.mint_count} "
        f"(keys={sorted(mgr.resolved_keys(loaded_key))[:5]})"
    )


def test_expanding_parent_and_plotting_one_column_mints_only_that_column(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """親を実展開 → 列を実プロット → **その列だけ**が鋳造される (E-3 ①ゲート)。

    E-3 反転後、「未展開」オラクル (上のテスト) は列 Signal が存在しないため
    自明に真になりうる。鋳造は非鋳造 introspection でしか観測できない
    (``mint_count`` / ``resolved_keys()`` — どちらも列を作らない)。ここで固定するのは:

      1. open は列を 1 本も鋳造しない、
      2. **ツリーの展開も鋳造しない** (展開が鋳造するなら prod 4,324 行の一括展開が
         264k 鋳造の一撃になる — C-b が塞いだ footgun そのもの)、
      3. 列を 1 本プロットすると **その列だけ** が鋳造され実描画される、
      4. 2-D 親 Signal の値は読まれない (親を実体化すると sorted_view() の
         astype(float64) が 8 倍膨張した恒久キャッシュになる)。

    demo_data には依存しない (gitignore・非コミット) — 合成 fixture で 3 列の
    配列チャンネル ``Mat`` と構造化チャンネル ``Pos`` を作る。
    """
    skip_unless_real_display()

    path = write_mdf4_flatten_fixture(tmp_path)
    window = _build_window(qtbot)
    window._load_file(path)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )
    loaded_key = window.app_vm.loaded_file_keys[0]
    session = window.app_vm.session
    mgr = session._groups  # C-e: Session には公開しない (realgui は直接触る先例あり)

    view = window.channel_browser_view
    tree, model = view.tree, view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=_LOAD_TIMEOUT_MS)
    _pump_n(4)
    _shot(tmp_path, "10_loaded_flat")

    # (1) open は鋳造しない。
    assert mgr.mint_count == 0, f"ロードだけで列が鋳造された: {mgr.mint_count}"
    assert mgr.resolved_keys(loaded_key) == frozenset(), (
        f"ロード直後に副テーブルが空でない: {sorted(mgr.resolved_keys(loaded_key))}"
    )

    # (2) 親 (Mat = 3 列) を実クリックで展開 — 列名だけで賄われ鋳造しない。
    mat_idx = model.index(_row_of(model, "Mat"), 0)
    assert not model.has_materialized_children(mat_idx), (
        "展開前に子が合成されている (葉の事前保持へ回帰)"
    )
    _click_expand_arrow(tree, mat_idx)
    assert tree.isExpanded(mat_idx), (
        f"展開アフォーダンスの実クリックで展開されない。"
        f"{_shot(tmp_path, '11_expand_fail')}"
    )
    assert _child_names(model, mat_idx) == ["Mat[0]", "Mat[1]", "Mat[2]"], (
        f"展開しても列が現れない: {_child_names(model, mat_idx)}"
    )
    first_child = model.index(0, 0, mat_idx)
    assert tree.visualRect(first_child).height() > 0, (
        "子行がモデルにはあるが画面に出ていない (展開が view に届いていない)"
    )
    assert mgr.mint_count == 0, (
        f"ツリーの展開が列 Signal を鋳造している (C-b 違反): "
        f"mint_count={mgr.mint_count} keys={sorted(mgr.resolved_keys(loaded_key))}"
    )
    _shot(tmp_path, "12_expanded")

    # (3) 2 番目の列を実選択 → 実右クリック → 「アクティブパネルに追加」を実クリック。
    #     先頭 (Mat[0]) を避けるのは、LD-08 dedup の `Mat[0]` 衝突規則と紛れないため。
    child = model.index(1, 0, mat_idx)
    child_key = model.signal_key_at(child)
    assert child_key is not None and child_key.endswith("::Mat[1]"), (
        f"子行の葉キーが列の実キーでない: {child_key!r}"
    )
    _real_select_and_menu_add(window, child)

    panel_vm = window.graph_area_vm.panels(0)[0]
    qtbot.waitUntil(lambda: child_key in panel_vm.plotted_signal_keys(), timeout=5000)
    _pump_n(4)
    shot = _shot(tmp_path, "13_column_plotted")

    panel = _panel_widget(window, 0, 0)
    assert child_key in panel.signal_keys_drawn(), (
        f"列を選んで追加したのに実描画されない: {child_key!r}。{shot}"
    )
    xs, _ys = panel.curve_xy(panel.entry_id_for(child_key))
    assert xs is not None and len(xs) > 0, (
        f"描画カーブが空 (鋳造列の値が読まれていない): {child_key!r}。{shot}"
    )

    # その列 **だけ** が鋳造された。
    assert mgr.resolved_keys(loaded_key) == frozenset({child_key}), (
        f"プロットした列以外も鋳造された: "
        f"{sorted(mgr.resolved_keys(loaded_key))} (plotted={child_key!r})。{shot}"
    )
    assert mgr.mint_count == 1, (
        f"鋳造回数が 1 でない (同一キーの再鋳造 = 副テーブルのキャッシュが効いて"
        f"いない疑い): {mgr.mint_count}。{shot}"
    )

    # 恒真化対策: 展開済み走査が **鋳造列を含む** こと自体を固定する。
    # group_signals() だけを歩くと鋳造列は列挙外なので、いくら鋳造しても
    # 「leak ゼロ」が通ってしまう (このファイルの ①ゲートが無力化する)。
    assert _count_materialized(session, loaded_key) == [child_key], (
        f"展開済み走査が鋳造列を見ていない / 余計な信号が展開された: "
        f"{_count_materialized(session, loaded_key)}。{shot}"
    )

    # (4) 2-D 親の値は読まれていない (読むと float64 8 倍膨張の恒久キャッシュ)。
    parent = session.resolve_signal(f"{loaded_key}::Mat")
    assert parent is not None, "物理チャンネル Mat が解決できない"
    assert not parent._values_source.is_materialized, (
        f"2-D 親 Signal の値が展開された (列の読みが親経由になっている疑い)。{shot}"
    )
