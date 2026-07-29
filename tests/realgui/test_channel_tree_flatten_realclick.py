"""Layer C: E-2 平坦化ツリーの ①ゲート (実ディスプレイ・実 OS 入力)。

E-2 はチャンネルブラウザを「1 行 = 1 物理チャンネル」へ平坦化し、列 (LD-14 の
``Name[i]`` / ``.field``) を **要求時に合成** するようにした。headless (Layer A/B)
は VM/モデルを直叩きできるため、
  * ツリーの展開が実際にユーザーの実クリックで届くか、
  * 実打鍵のフィルタが debounce を越えて行を絞るか、
  * 平坦化後も **列の個別選択**が右クリック → 追加 → 実描画まで通るか、
のいずれも証明できない。本テストはそれを実 MainWindow で end-to-end に踏む。

assert の honest-RED (何を殺せるか):
  1. トップ行 == ``["ACC.Speed", "ACC.Accel", "Mat", "Pos", "Scalar"]``
     — E-2 前の ``_base_of`` (orig の最初の ``[`` / ``.`` まで) が復活すると
     ``ACC.Speed`` / ``ACC.Accel`` が ``"ACC"`` 1 行へ畳まれて RED。
     逆に平坦化をやめて列ごとの行に戻せば 9 行になって RED。
     fixture が接頭辞共有 2 本を持つのはこの mutation を殺すため
     (1 本だと SignalTreeModel の単一リーフ畳み込みで旧実装でもトップ行が
     ``"ACC.Speed"`` に見え、オラクルが無力化する)。
  2. 展開前は子が **未合成** (``has_materialized_children`` False)・実クリックで
     ``Mat[0..2]`` が **画面に出る** (``visualRect().height() > 0``) — 事前保持へ
     戻せば前者が、要求時合成が壊れれば後者が RED。
  3. 実打鍵 ``x`` → ``["Pos"]`` へ絞られ、展開した子は ``["Pos.xa", "Pos.xb"]``
     だけ (``Pos.yc`` は出ない) — 件数と子行の述語が乖離すれば RED (C3)。
  4. **配列チャンネルの子行**を実クリック選択 → 実右クリック →
     「アクティブパネルへ追加」実クリックで ``Mat[0]`` が実描画される。
     対象がトップレベルのスカラーだと ``base_key == 実キー`` になり C1 の回帰
     (合成 base_key を葉キーに使う = 見えるのに永久に描かれない行) を素通しする
     ので、**必ず配列チャンネルの子行**を叩く。

実マウスドラッグは使わない (共有マシンでハング・memory
``gui_realgui_drag_qtimer_hang``)。実打鍵は英数字 + BackSpace のみ
(``ord('[') == 0x5B == VK_LWIN`` でスタートメニューが開き以後の実クリックが
別ウィンドウへ流れる — 記号入り列名マッチは Task 4 の Layer B が被覆済み)。
"""

from __future__ import annotations

import contextlib
import re
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, QPoint
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import write_mdf4_flatten_fixture
from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    VK_BACK,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
)
from tests.realgui._realgui_input import key as key_input
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui

_QUICK_MF4 = Path("D:/Programming/projects/valisync/demo_data/quick_demo.mf4")
_LOAD_TIMEOUT_MS = 180_000
# ChannelBrowserView._FILTER_DEBOUNCE_MS は 200ms — 打鍵後の反映待ちに余裕を持たせる。
_DEBOUNCE_WAIT_MS = 2_000
# E-2 前のグルーピング規則 (_base_of): orig の最初の '[' または '.' まで。
_OLD_BASE_RE = re.compile(r"[\[.]")


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


def _phys(w, local: QPoint) -> tuple[int, int]:  # type: ignore[no-untyped-def]
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
    """実ディスプレイ上の本物の MainWindow (画面内へ配置・前面化)。"""
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


def _top_names(model) -> list[str]:  # type: ignore[no-untyped-def]
    """トップレベル行の Name 列 (子は触らない = 合成を誘発しない)。"""
    return [model.data(model.index(r, 0)) for r in range(model.rowCount())]


def _child_names(model, parent: QModelIndex) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        model.data(model.index(r, 0, parent)) for r in range(model.rowCount(parent))
    ]


def _row_of(model, name: str) -> int:  # type: ignore[no-untyped-def]
    names = _top_names(model)
    assert name in names, f"トップ行に {name!r} が無い: {names}"
    return names.index(name)


def _click_index(tree, index: QModelIndex) -> None:  # type: ignore[no-untyped-def]
    """行を可視域へスクロールしてから、その行の実座標を実クリックする。"""
    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "対象行が可視域に無い (実クリックできない)"
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    _real_click(*_phys(vp, local))


def _click_expand_arrow(tree, index: QModelIndex) -> None:  # type: ignore[no-untyped-def]
    """展開アフォーダンス (ブランチインジケータ) を実クリックする。

    QTreeView は rootIsDecorated の矢印を item 矩形の **左** の
    ``indentation()`` 幅の帯に描く。``visualRect`` はテキスト側の矩形なので、
    その左端から半インデント戻った点がユーザーが実際に叩く三角形の中心。
    """
    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "展開対象行が可視域に無い"
    indent = tree.indentation()
    assert indent > 0, "indentation が 0 — 展開矢印が存在しない"
    arrow_x = rect.left() - indent // 2
    # 負値を黙って 2px へ丸めると、ジオメトリ計算の誤りが「どこか別の場所への
    # 誤クリック」として静かに揉み消される (assert がずれた症状で落ちる/落ちない
    # を運任せにする)。ここでは丸めず失敗させる。
    assert arrow_x > 0, (
        f"展開矢印の想定 x が負 (rect.left()={rect.left()}, indent={indent}, "
        f"x={arrow_x}) — インデント計算が壊れている"
    )
    local = QPoint(arrow_x, rect.center().y())
    _real_click(*_phys(tree.viewport(), local))


def _real_add_to_active_panel(tree, index: QModelIndex) -> None:  # type: ignore[no-untyped-def]
    """行を実クリック選択 → 実右クリック → 「アクティブパネルへ追加」を実クリック。

    ESC の watchdog を挟み、クリックを外した場合でも popup を閉じてから assert で
    落ちるようにする (共有マシンを開いたメニューで塞がない)。
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    _click_index(tree, index)  # 右クリックは選択を変えない → 先に左クリックで選択
    rect = tree.visualRect(index)
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    px, py = _phys(vp, local)

    loop = QEventLoop()
    seen: dict[str, object] = {}

    def right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def click_item() -> None:
        menu = QApplication.activePopupWidget()
        seen["popup"] = type(menu).__name__ if menu is not None else None
        if isinstance(menu, QMenu):
            seen["actions"] = [a.text() for a in menu.actions()]
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

    # タイマーは変数に保持し exec() 復帰後に明示 stop() する。stop し忘れると
    # click_item() (~1000ms) で loop.quit() した後も watchdog (1600ms) /
    # 最終フォールバック (5000ms) が生き残り、後続の qtbot.waitUntil の最中に
    # 発火 -- popup が別の理由でまだ開いていれば本物の VK_ESCAPE を送りかねない
    # (共有マシンでの非決定性要因)。
    t_click = QTimer()
    t_click.setSingleShot(True)
    t_click.timeout.connect(right_click)
    t_item = QTimer()
    t_item.setSingleShot(True)
    t_item.timeout.connect(click_item)
    t_watchdog = QTimer()
    t_watchdog.setSingleShot(True)
    t_watchdog.timeout.connect(watchdog)
    t_fallback = QTimer()
    t_fallback.setSingleShot(True)
    t_fallback.timeout.connect(loop.quit)

    t_click.start(300)
    t_item.start(1000)
    t_watchdog.start(1600)
    t_fallback.start(5000)
    loop.exec()
    for t in (t_click, t_item, t_watchdog, t_fallback):
        t.stop()

    assert seen.get("popup") == "QMenu", (
        f"実右クリックでコンテキストメニューが出ない: {seen}"
    )
    assert seen.get("action_found"), (
        f"メニューに {S.ACTION_ADD_TO_ACTIVE_PANEL!r} が無い "
        f"(actions={seen.get('actions')})"
    )


def _focus_filter(view) -> None:  # type: ignore[no-untyped-def]
    """検索ボックスを実クリックしてフォーカスを入れる。

    ツリー側を実クリックするとフォーカスは QTreeView へ移るので、打鍵の直前に
    毎回入れ直す (入れ忘れると打鍵がツリーへ流れ、フィルタが無反応になる)。
    """
    box = view.search_box
    _real_click(*_phys(box, box.rect().center()))
    assert box.hasFocus(), "検索ボックスに実クリックでフォーカスが入らない"


def _type_filter_char(view, ch: str) -> None:  # type: ignore[no-untyped-def]
    """検索ボックスへ英数字 1 文字を実打鍵する。

    ``key(ord(ch.upper()))`` は A-Z / 0-9 の VK が ASCII と一致することにのみ
    依存する (repo 唯一のタイピング前例・test_tab_ui_flow.py:142 等)。
    """
    _focus_filter(view)
    key_input(ord(ch.upper()))
    _pump_n(4)


def _backspace_filter(view) -> None:  # type: ignore[no-untyped-def]
    """検索ボックスへ実 BackSpace を 1 打鍵する (フィルタを消す実経路)。"""
    _focus_filter(view)
    key_input(VK_BACK)
    _pump_n(4)


def test_channel_tree_is_flattened_and_columns_stay_selectable(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """平坦化 / 要求時合成 / 実打鍵フィルタ / 列の個別選択 を実 OS 入力で通す。"""
    skip_unless_real_display()

    path = write_mdf4_flatten_fixture(tmp_path)
    window = _build_window(qtbot)
    window._load_file(path)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )

    view = window.channel_browser_view
    tree, model = view.tree, view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=_LOAD_TIMEOUT_MS)
    _pump_n(4)
    shot = _shot(tmp_path, "01_flat_tree")

    # ── (1) トップ行は物理チャンネル ───────────────────────────────────────
    top = _top_names(model)
    assert top == ["ACC.Speed", "ACC.Accel", "Mat", "Pos", "Scalar"], (
        f"トップ行が物理チャンネル 1 行になっていない: {top}。{shot}"
    )
    assert "ACC" not in top, (
        f"ドット分割グルーピング (_base_of) が復活している: {top}。{shot}"
    )
    # ヘッダーは列基準の件数 (5 チャンネル = 9 列)。
    assert view.header_label.text() == S.CHANNEL_HEADER_COUNT_TMPL.format(
        total=9, shown=9
    ), f"件数ヘッダーが列基準でない: {view.header_label.text()!r}"

    # ── (2) 配列チャンネルの子は「実クリックで展開するまで」合成されない ────
    mat_idx = model.index(_row_of(model, "Mat"), 0)
    assert not tree.isExpanded(mat_idx)
    assert not model.has_materialized_children(mat_idx), (
        "展開前に子が合成されている (葉の事前保持へ回帰)"
    )
    _click_expand_arrow(tree, mat_idx)
    assert tree.isExpanded(mat_idx), (
        f"展開アフォーダンスの実クリックで展開されない。{_shot(tmp_path, '02_expand_fail')}"
    )
    assert _child_names(model, mat_idx) == ["Mat[0]", "Mat[1]", "Mat[2]"], (
        f"展開しても列が現れない: {_child_names(model, mat_idx)}"
    )
    first_child = model.index(0, 0, mat_idx)
    assert tree.visualRect(first_child).height() > 0, (
        "子行がモデルにはあるが画面に出ていない (展開が view に届いていない)"
    )
    _shot(tmp_path, "03_expanded")

    # ── (3) 実打鍵フィルタ (英数字 1 文字) ─────────────────────────────────
    _type_filter_char(view, "x")
    qtbot.waitUntil(lambda: _top_names(model) == ["Pos"], timeout=_DEBOUNCE_WAIT_MS)
    _pump_n(3)
    pos_idx = model.index(0, 0)
    _click_expand_arrow(tree, pos_idx)
    assert tree.isExpanded(pos_idx)
    assert _child_names(model, pos_idx) == ["Pos.xa", "Pos.xb"], (
        f"フィルタ後の子行が一致列だけになっていない: {_child_names(model, pos_idx)}"
    )
    assert view.header_label.text() == S.CHANNEL_HEADER_COUNT_TMPL.format(
        total=9, shown=2
    ), f"フィルタ後の件数が一致列数でない: {view.header_label.text()!r}"
    _shot(tmp_path, "04_filtered")

    # フィルタを実 BackSpace で消して全行へ戻す。
    _backspace_filter(view)
    qtbot.waitUntil(lambda: len(_top_names(model)) == 5, timeout=_DEBOUNCE_WAIT_MS)
    assert view.search_box.text() == "", (
        f"BackSpace で検索ボックスが空にならない: {view.search_box.text()!r}"
    )
    _pump_n(3)

    # ── (4) 配列チャンネルの **子行** を実選択して実メニューから追加 ────────
    mat_idx = model.index(_row_of(model, "Mat"), 0)
    # BackSpace によるツリー再構築で展開状態が引き継がれていない前提を明示。
    # もし将来フィルタ再構築後も展開が保持されるよう変わっていたら、この
    # クリックは展開でなく畳み込みになり、直後の isExpanded assert が
    # 「展開できていない」という誤った理由で落ちる。
    assert not tree.isExpanded(mat_idx), (
        "前提が崩れている: BackSpace 再構築後に Mat が展開状態のまま"
    )
    _click_expand_arrow(tree, mat_idx)
    assert tree.isExpanded(mat_idx)
    child = model.index(0, 0, mat_idx)
    child_key = model.signal_key_at(child)
    assert child_key is not None and child_key.endswith("::Mat[0]"), (
        f"子行の葉キーが列の実キーでない (C1 回帰の疑い): {child_key!r}"
    )

    _real_add_to_active_panel(tree, child)

    panel_vm = window.graph_area_vm.panels(0)[0]
    qtbot.waitUntil(lambda: child_key in panel_vm.plotted_signal_keys(), timeout=5000)
    _pump_n(4)
    final = _shot(tmp_path, "05_column_plotted")

    panel = window.graph_area_view.tabs.widget(0).widget(0)
    assert child_key in panel.signal_keys_drawn(), (
        f"列を選んで追加したのに実描画されない: {child_key!r}。{final}"
    )
    xs, _ys = panel.curve_xy(panel.entry_id_for(child_key))
    assert xs is not None and len(xs) > 0, (
        f"描画カーブが空 (値が読まれていない): {child_key!r}。{final}"
    )


def _physical_channels(group_sigs) -> list[str]:  # type: ignore[no-untyped-def]
    """ローダー metadata から見た物理チャンネル (出現順・VM を経由しない独立オラクル)。"""
    out: list[str] = []
    seen: set[str] = set()
    for sig in group_sigs:
        orig = sig.name.split("::", 1)[1] if "::" in sig.name else sig.name
        phys = str((sig.metadata or {}).get("physical_channel") or orig)
        if phys not in seen:
            seen.add(phys)
            out.append(phys)
    return out


def _old_base_groups(group_sigs) -> set[str]:  # type: ignore[no-untyped-def]
    """E-2 前の _base_of グルーピングで出来ていたはずのトップ行集合。"""
    bases: set[str] = set()
    for sig in group_sigs:
        orig = sig.name.split("::", 1)[1] if "::" in sig.name else sig.name
        m = _OLD_BASE_RE.search(orig)
        bases.add(orig[: m.start()] if m else orig)
    return bases


def test_quick_demo_top_rows_are_physical_channels(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """補助オラクル: 本番相当 mf4 でもトップ行数 == 物理チャンネル数。

    ``demo_data/`` は .gitignore で非コミットなので不在はありうるが、**skip には
    しない** — ①ゲートの単一ファイル実行では skip が「pass」として報告されうる
    ため、不在は xfail (``x``) として可視に残す。
    """
    skip_unless_real_display()
    if not _QUICK_MF4.exists():
        pytest.xfail(f"補助オラクル用の mf4 が無い (skip ではなく xfail): {_QUICK_MF4}")

    window = _build_window(qtbot)
    # 配列展開の確認モーダルはワーカーからの呼び出し — 全スキップで非ブロック化。
    window._expansion_confirmer.confirm = lambda request: set()  # type: ignore[assignment]
    window._load_file(_QUICK_MF4)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )
    key = window.app_vm.loaded_file_keys[0]
    group_sigs = window.app_vm.session.group_signals(key)

    model = window.channel_browser_view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=_LOAD_TIMEOUT_MS)
    _pump_n(4)
    shot = _shot(tmp_path, "quick_demo_tree")

    phys = _physical_channels(group_sigs)
    old_bases = _old_base_groups(group_sigs)
    assert model.rowCount() == len(phys), (
        f"トップ行数 {model.rowCount()} != 物理チャンネル数 {len(phys)} "
        f"(列 {len(group_sigs)})。{shot}"
    )
    # E-3 反転で group_signals は物理チャンネルそのもの (len(phys) == len(group_sigs))
    # になったため、旧オラクル (列 Signal 数との差) は構造的に成立不能。独立オラクルを
    # ColumnSpec 由来の**列総数**へ照準変更する — 「畳まれている」の意味は変わらない。
    total_cols = window.app_vm.session.total_column_count(key)
    assert len(phys) < total_cols, (
        f"列が畳まれていない (物理 {len(phys)} == 列 {total_cols})。{shot}"
    )
    # 旧 _base_of なら別の (より少ない) 行数になるはず — 本番相当データでも
    # 「ドット分割の復活」が RED になることを担保する。
    assert len(old_bases) != len(phys), (
        f"物理チャンネル数 {len(phys)} が旧 _base_of グループ数 {len(old_bases)} と"
        f"一致 — このデータでは mutation を殺せない。{shot}"
    )
    assert _top_names(model) == phys, (
        f"トップ行が物理チャンネルの出現順と一致しない。{shot}"
    )
    print(
        f"[quick_demo] 列 {len(group_sigs)} / 物理チャンネル {len(phys)} / "
        f"旧 _base_of グループ {len(old_bases)}"
    )
