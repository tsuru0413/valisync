"""Layer C: E-4a チャンネル単位サンプルキャッシュの ①ゲート (実ディスプレイ・実 OS 入力)。

E-4a の主張は「同じ物理チャンネルの列を何本読んでも **デコードは 1 回**」である。
headless (Layer A/B) では ``ChannelSampleCache`` を直叩きできてしまうため、
その主張がユーザーの実操作 (行の実選択 -> 実右クリック -> メニューの実クリック) を
貫通することは証明できない。ここでは実 MainWindow に実 mf4 をロードし、実 OS 入力で

  1. 5 列を **まとめて** 追加 -> チャンネルのデコードは 1 回 (miss 1 / select 1)、
     かつ読み経路が ``_flatten`` を 1 度も呼ばない (位置パスへ移行済み)、
  2. 1 列ずつ **探索的に** 追加 -> 2 本目以降はキャッシュヒット (miss は増えない)、
  3. **予算を注入して小さくすると** 古いチャンネルが落ちる (evict され、再訪は冷える)、

を実測する。3 は spec D6: 実データでは 256 MB に広幅 (uint8 12000x1100 = 13.2 MB) が
~19 本入るため evict をほぼ発火させられないので、予算そのものを注入して小さくする
(``TeardownService(byte_budget=...)`` と同型の注入)。

**回数の assert は上界で書く** (T0 レビューの契約・``ChannelSampleCache.get`` の
docstring): 正しい関係は ``misses >= select`` であって等式ではない。兄弟列は別々の
``LazyMdfValues`` インスタンスなので per-instance の fast path では畳まれず、
畳んでいるのは共有キャッシュだけ — 同一チャンネルの別列を **同時に** 読み始めると
miss と select の関係が直列時と変わる。等式で書くと「主張より良い結果」でも落ちる
テストになるので、E-4a の主張そのもの (「高々 1 回しかデコードしない」) を上界で
固定し、「実際にデコードが起きたこと」が要るところ (脚 3 の evict 後の再訪) だけ
下界で書く。**等式で書いてよいのはバイト会計** (``bytes_held``) — こちらは
「2-D 配列そのものが載っている」ことの唯一の防波堤で、緩めると列だけ/upcast を
見逃す。

**恒真化させないための設計** (E-3 の ①ゲートは、反転で「未展開」が自明に真になり、
しかも会計が鋳造列を列挙外にしていたという二重の穴を踏んだ):

  * 観測は 2 系統を **独立** に持つ。``cache.misses`` は実装自身が書く数値なので、
    それとは別に asammdf の ``MDF.select`` へラッパを載せて **実際に何回デコードしたか**
    を数える。両者が食い違えば counters が嘘をついている。
  * ``_flatten`` の呼び出しも数える。0 であることが空虚に通らないよう、
    差し替えが「呼び出し時 import」から見えることを positive control で確かめ、
    ``sample_source`` がモジュール直下に別名を持たないことも assert する
    (別名を持たれるとカウンタが盲目になる)。
  * **対照 assert**: 「まとめ追加が実は 1 列も追加していなかった」「クリックが no-op
    だった」のどちらでも RED になるよう、選択キー集合・プロット済みキー集合・
    実描画カーブ (RenderCurve 非空) を各段で固定する。
  * 値そのものを fixture の規則と突き合わせる。位置パスが隣の列や別チャンネルを
    返す誤りは「読めている」だけでは検出できない (長さも dtype も一致するので
    ``LazyMdfValues`` の長さ検証も素通りする)。

実マウスドラッグは使わない (共有マシンでハング・memory
``gui_realgui_drag_qtimer_hang``)。複数選択は実クリック + 実 Shift+クリックで行う。
demo_data には依存しない (gitignore・CI に生成ステップが無い) — 合成 fixture で
幅 64 の 2-D uint8 チャンネルを 2 本作る。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QModelIndex, QPoint
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import write_mdf4_two_wide_channels
from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    VK_ESCAPE,
    VK_SHIFT,
    at,
    click_with_modifier,
    skip_unless_real_display,
)
from tests.realgui._realgui_input import key as key_input
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.session import Session
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui

_LOAD_TIMEOUT_MS = 30_000
_PLOT_TIMEOUT_MS = 10_000
_ROWS = 1000
_COLS = 64
# uint8 (ROWS, COLS) = デコード済み 2-D チャンネル 1 本の実体サイズ。
_ENTRY_BYTES = _ROWS * _COLS
# D6: 1 本は載り 2 本は載らない予算。1.5 倍にしておけば、pin 由来の set_reserved が
# 多少食っても「2 本同時滞在」は構造的に成立しない (2 本 = 2.0 倍 > 1.5 倍)。
# 実数: エントリ 64,000 B / 予算 96,000 B。
#
# **pin 1 列 = 9,000 B** (実測: 脚 3 の reserved は 1 列 9,000 / 3 列 27,000)。
# 値配列 1,000 B だけではない — ``pinned_column_bytes`` は teardown と同じ
# ``retained_bytes`` で数えるので、プロット中の列が抱える ``sorted_view()`` の
# float64 実体 8,000 B が乗る (uint8 なので 8 倍側の方が大きい)。3 列 pin 後の
# LRU 容量は max(96,000 - 27,000, 最新エントリ 64,000) = 69,000 B。
# 1 本 (64,000) は載り 2 本 (128,000) は載らない、が本テストで使う全ての状態で成立する
# — さらに ``_capacity_for`` の最低容量 (spec §5.5) が「最新 1 エントリ」を無条件に
# 確保するので、pin がこれ以上増えても 1 本は必ず載る。
_SMALL_BUDGET = _ENTRY_BYTES + _ENTRY_BYTES // 2


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


def _phys(w: Any, local: QPoint) -> tuple[int, int]:
    gp = w.mapToGlobal(local)
    dpr = w.devicePixelRatioF()
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _shot(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    p = tmp_path / f"{name}.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(p))
    return p


def _build_window(qtbot: QtBot, session: Session | None = None) -> Any:
    """実ディスプレイ上の本物の MainWindow (画面内へ配置・前面化)。

    オフスクリーン配置だと右クリックが OS のシステムメニューを開く
    (memory: gui_realgui_offscreen_target_opens_os_system_menu)。

    *session* は D6 の予算注入用 (脚 3 のみ)。``AppViewModel(None)`` は自前で
    ``Session()`` を作るので、既定の 2 本は今までどおり production 既定の予算で走る。
    **ロード後に session.channel_cache を差し替える形は使えない** — MdfLoader が
    __init__ 時点のインスタンスを捕捉するので、差し替えても読み経路は旧インスタンスを
    見続ける (counters が全て 0 のまま脚 3 が構造的に成立しない)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel(session))
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


def _load_and_settle(qtbot: QtBot, window: Any, path: Path) -> str:
    """実ロード経路 (off-thread LoadController + BusyOverlay) を通し group key を返す。

    オーバーレイが引くまで待つ — 引いていないと以後の実クリックが全てオーバーレイに
    当たり、テストは「クリックしたつもり」で無音に流れる。
    """
    window._load_file(path)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=_LOAD_TIMEOUT_MS)
    _pump_n(6)
    return str(window.app_vm.loaded_file_keys[0])


def _panel_widget(window: Any, tab: int, panel: int) -> Any:
    return window.graph_area_view.tabs.widget(tab).widget(panel)


def _top_names(model: Any) -> list[str]:
    """トップレベル行の Name 列 (子は触らない = 合成も鋳造も誘発しない)。"""
    return [model.data(model.index(r, 0)) for r in range(model.rowCount())]


def _child_names(model: Any, parent: QModelIndex) -> list[str]:
    return [
        model.data(model.index(r, 0, parent)) for r in range(model.rowCount(parent))
    ]


def _row_of(model: Any, name: str) -> int:
    names = _top_names(model)
    assert name in names, f"トップ行に {name!r} が無い: {names}"
    return names.index(name)


def _row_point(tree: Any, index: QModelIndex) -> tuple[int, int]:
    """行を可視域へスクロールし、その行の掴み点 (物理ピクセル) を返す。"""
    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "対象行が可視域に無い (実クリックできない)"
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    return _phys(vp, local)


def _click_index(tree: Any, index: QModelIndex) -> None:
    _real_click(*_row_point(tree, index))


def _click_expand_arrow(tree: Any, index: QModelIndex) -> None:
    """展開アフォーダンス (ブランチインジケータ) を実クリックする。

    QTreeView は rootIsDecorated の矢印を item 矩形の **左** の ``indentation()``
    幅の帯に描く。``visualRect`` はテキスト側の矩形なので、その左端から半インデント
    戻った点がユーザーが実際に叩く三角形の中心。
    """
    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "展開対象行が可視域に無い"
    indent = tree.indentation()
    assert indent > 0, "indentation が 0 — 展開矢印が存在しない"
    arrow_x = rect.left() - indent // 2
    # 負値を黙って丸めると、ジオメトリ計算の誤りが「どこか別の場所への誤クリック」
    # として静かに揉み消される。丸めず失敗させる。
    assert arrow_x > 0, (
        f"展開矢印の想定 x が負 (rect.left()={rect.left()}, indent={indent}, "
        f"x={arrow_x}) — インデント計算が壊れている"
    )
    _real_click(*_phys(tree.viewport(), QPoint(arrow_x, rect.center().y())))


def _real_right_click_add(view: Any, px: int, py: int) -> dict[str, Any]:
    """物理点 (px, py) を実右クリックし「アクティブパネルに追加」を実クリックする。

    **左クリックはしない** — 複数行を選んだ状態でメニューを開くのが「まとめ追加」の
    実経路で、ここで選択し直すと選択が 1 行へ潰れ、テストがまとめ追加を検証できなく
    なる (ChannelBrowserView._show_context_menu は意図的に選択を変えない)。
    メニューが開いている瞬間の選択キーも記録する — 右クリックが選択を壊していない
    ことの対照であり、これが無いと「1 列しか追加されなかった」原因を帰属できない。

    ESC の watchdog を挟み、クリックを外した場合でも popup を閉じてから assert で
    落ちるようにする (共有マシンを開いたメニューで塞がない)。タイマは exec() 復帰後に
    明示 stop する — 生き残ると後続の waitUntil 中に本物の ESC を送りかねない。
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    loop = QEventLoop()
    seen: dict[str, Any] = {}

    def right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def click_item() -> None:
        menu = QApplication.activePopupWidget()
        seen["popup"] = type(menu).__name__ if menu is not None else None
        if isinstance(menu, QMenu):
            seen["selection"] = view.selected_signal_keys()
            seen["actions"] = [a.text() for a in menu.actions()]
            act = next(
                (a for a in menu.actions() if a.text() == S.ACTION_ADD_TO_ACTIVE_PANEL),
                None,
            )
            seen["action_found"] = act is not None
            seen["action_enabled"] = act is not None and act.isEnabled()
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

    timers = []
    for delay, slot in (
        (300, right_click),
        (1000, click_item),
        (1600, watchdog),
        (5000, loop.quit),
    ):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(slot)
        timer.start(delay)
        timers.append(timer)
    loop.exec()
    for timer in timers:
        timer.stop()
    _pump_n(4)

    assert seen.get("popup") == "QMenu", (
        f"実右クリックでコンテキストメニューが出ない: {seen}"
    )
    assert seen.get("action_found"), (
        f"メニューに {S.ACTION_ADD_TO_ACTIVE_PANEL!r} が無い: {seen}"
    )
    assert seen.get("action_enabled"), (
        f"「追加」が disabled = 選択が空 (以後の assert が空虚に通る): {seen}"
    )
    return seen


def _add_single_row(view: Any, index: QModelIndex) -> dict[str, Any]:
    """1 行だけを実クリック選択し、実右クリックメニューから追加する。"""
    _click_index(view.tree, index)
    return _real_right_click_add(view, *_row_point(view.tree, index))


def _cache(session: Any) -> ChannelSampleCache:
    cache = session.channel_cache
    assert isinstance(cache, ChannelSampleCache), (
        f"Session が共有チャンネルキャッシュを公開していない: {cache!r}"
    )
    return cache


def _count_selects(handle: Any, request: pytest.FixtureRequest) -> list[Any]:
    """``handle.mdf.select`` の実呼び出しを数える (counters とは独立のオラクル)。

    ``LazyMdfValues`` は ``self._handle.mdf.select(...)`` を呼ぶので、MDF インスタンスへ
    ラッパを載せれば **実際に何回デコードしたか** を production 経路で数えられる。
    ``cache.misses`` だけを見ると「counters は動くが select も毎回走る」実装を見逃す —
    counters は実装自身が書く数値、select は asammdf 側の事実である。
    **ロード完了後に載せる** (ローダー自身の probe/select を数えないため)。

    **必ず復元する** (T5 の ``_ReadCounters`` と対称)。元の状態は「インスタンス属性が
    無い」なので、復元は ``setattr`` ではなく ``__dict__`` からの削除 — bound method を
    焼き付けると、閉じた MDF への参照がクラス実装を隠したまま残り、同じハンドルを別の
    計測が掴んだときにラッパが二重に積み重なる。assert が途中で落ちても finalizer なら
    必ず走る。
    """
    assert "select" not in vars(handle.mdf), (
        "handle.mdf に select のインスタンス属性が既にある (前の計測が復元されていない)"
    )
    calls: list[Any] = []
    original = handle.mdf.select

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(args[0] if args else None)
        return original(*args, **kwargs)

    handle.mdf.select = counting
    request.addfinalizer(lambda: vars(handle.mdf).pop("select", None))
    return calls


def _records(session: Any, key: str) -> Any:
    """{表示名: ColumnRecord} — fixture の (gi, ci) を setup precondition に使う。"""
    return session._groups.column_records(key)


def _count_flatten(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """``mdf_loader._flatten`` の実呼び出しを数える (読み経路から消えたことの観測点)。

    ``sample_source`` は ``array()`` の中で **呼び出し時 import** するので、モジュール
    属性を差し替えれば読み経路からの呼び出しは必ずここを通る。逆にモジュール直下へ
    別名を持たれるとこのカウンタは盲目になる (0 が空虚に通る) ので、その形で無いことも
    確かめてから数える。
    """
    import valisync.core.loaders.mdf_loader as mdf_loader
    import valisync.core.models.sample_source as sample_source

    assert not hasattr(sample_source, "_flatten"), (
        "sample_source がモジュール直下に _flatten の別名を持っている — "
        "mdf_loader 側の差し替えが読み経路に届かず、このカウンタは盲目になる"
    )
    calls: list[str] = []
    original = mdf_loader._flatten

    def counting(name: str, arr: Any) -> Any:
        calls.append(name)
        return original(name, arr)

    monkeypatch.setattr(mdf_loader, "_flatten", counting)
    from valisync.core.loaders.mdf_loader import _flatten as resolved

    assert resolved is counting, (
        "呼び出し時 import から差し替えが見えない (カウンタが盲目)"
    )
    return calls


def _expected_column(channel: str, j: int) -> np.ndarray:
    """fixture の列 j の期待値 (write_mdf4_two_wide_channels と同じ規則)。"""
    base = 0 if channel == "WideA" else 128
    return ((np.arange(_ROWS, dtype=np.int64) + 7 * j + base) % 251).astype(np.uint8)


def _expand_channel(qtbot: QtBot, window: Any, name: str) -> QModelIndex:
    """物理チャンネル *name* の行を実クリックで展開し、その親 index を返す。"""
    view = window.channel_browser_view
    tree, model = view.tree, view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=_LOAD_TIMEOUT_MS)
    _pump_n(4)
    parent = model.index(_row_of(model, name), 0)
    assert not model.has_materialized_children(parent), (
        f"{name} の子が展開前に合成されている (葉の事前保持へ回帰)"
    )
    _click_expand_arrow(tree, parent)
    assert tree.isExpanded(parent), f"{name} が実クリックで展開されない"
    return parent


def test_bulk_add_of_five_columns_decodes_the_channel_once(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """5 列まとめて実追加 -> デコード 1 回・``_flatten`` 0 回 (spec §9 の出口 2 行)。"""
    skip_unless_real_display()

    path = write_mdf4_two_wide_channels(tmp_path, rows=_ROWS, cols=_COLS)
    window = _build_window(qtbot)
    loaded_key = _load_and_settle(qtbot, window, path)
    session = window.app_vm.session
    cache = _cache(session)
    # C-e: Session には出さない introspection (realgui は直接触る先例あり)。
    handle = session._groups.group(loaded_key).handle
    assert handle is not None and handle.is_closed is False

    view = window.channel_browser_view
    tree, model = view.tree, view.model
    # 既定キャッシュは **プロセス単位でありうる** (別テストの残留が乗る) ので、
    # 絶対値ではなく差分で見る。予算注入をするのは 3 本目のテストだけ。
    selects = _count_selects(handle, request)
    flattens = _count_flatten(monkeypatch)
    hits_before, misses_before = cache.hits, cache.misses

    parent = _expand_channel(qtbot, window, "WideA")
    children = _child_names(model, parent)
    assert children[:5] == [f"WideA[{j}]" for j in range(5)], (
        f"子行が列になっていない: {children[:8]}"
    )
    # 展開はデコードしない (E-3 の契約・無回帰)。
    assert selects == [] and cache.misses == misses_before, (
        f"ツリーの展開がチャンネルをデコードしている: selects={selects} "
        f"misses+{cache.misses - misses_before}"
    )
    _shot(tmp_path, "01_expanded")

    # ── 5 列を実選択 (先頭を実クリック -> 5 行目を実 Shift+クリック) ──────────
    _click_index(tree, model.index(0, 0, parent))
    click_with_modifier(*_row_point(tree, model.index(4, 0, parent)), VK_SHIFT)
    _pump_n(6)
    expected = [f"{loaded_key}::WideA[{j}]" for j in range(5)]
    selected = view.selected_signal_keys()
    assert sorted(selected) == sorted(expected), (
        f"実 Shift+クリックで 5 列が選択されていない (まとめ追加を検証できない): "
        f"{selected}。{_shot(tmp_path, '02_selection')}"
    )

    # ── 選択内の 3 行目を実右クリック -> 「追加」を実クリック ────────────────
    seen = _real_right_click_add(view, *_row_point(tree, model.index(2, 0, parent)))
    assert sorted(seen.get("selection") or []) == sorted(expected), (
        f"メニューを開いた時点で選択が壊れている (まとめ追加になっていない): {seen}"
    )

    panel_vm = window.graph_area_vm.panels(0)[0]
    qtbot.waitUntil(
        lambda: len(panel_vm.plotted_signal_keys()) == 5, timeout=_PLOT_TIMEOUT_MS
    )
    _pump_n(6)
    shot = _shot(tmp_path, "03_five_plotted")

    # ── 対照: 5 列が実際に載り、実際に描かれた (no-op クリックを排除) ────────
    panel = _panel_widget(window, 0, 0)
    assert sorted(panel_vm.plotted_signal_keys()) == sorted(expected), (
        f"5 列がまとめて追加されていない: {panel_vm.plotted_signal_keys()}。{shot}"
    )
    for key in expected:
        assert key in panel.signal_keys_drawn(), (
            f"追加した列が実描画されない: {key!r}。{shot}"
        )
        xs, _ys = panel.curve_xy(panel.entry_id_for(key))
        assert xs is not None and len(xs) > 0, (
            f"描画カーブが空 (値が読まれていない): {key!r}。{shot}"
        )

    # ── 本題: 5 列 = デコード 1 回 ───────────────────────────────────────────
    # **上界で書く** (T0 の契約: misses >= select・等式ではない)。E-4a が主張して
    # いるのは「高々 1 回」であって「ちょうど 1 回」ではない — 等式にすると、より
    # 良い結果 (既に温まっていて 0 回) でも落ちるテストになる。空虚に通らないことは
    # 下の hits (>= 4 = 2 本目以降が実際に共有キャッシュを引いた) と、上の実描画・
    # 下の値照合が担保する。
    assert cache.misses - misses_before <= 1, (
        f"5 列の追加でチャンネルを {cache.misses - misses_before} 回デコードしている "
        f"(キャッシュ未命中の上界 1)。{shot}"
    )
    # **この 1 行は上の misses の言い換えではない** (sabotage 実測): ``get`` の先頭で
    # ``return None`` する形に壊すと ``_misses += 1`` に到達しないので上の
    # ``misses <= 1`` は 0 で**通り**、実際に 5 回デコードしていることを捕まえるのは
    # この select オラクルだけになる (実測 selects=5・全て [('WideA', 0, 1)])。
    # counters は実装自身が書く数値なので、counters だけを見る ①gate は
    # 「counters を書かない壊れ方」に構造的に盲目である。
    assert len(selects) <= 1, (
        f"asammdf select の実呼び出しが {len(selects)} 回 (上界 1) — "
        f"counters と実デコード回数が乖離している: {selects}。{shot}"
    )
    assert cache.hits - hits_before >= 4, (
        f"2 列目以降がキャッシュヒットになっていない (hits+"
        f"{cache.hits - hits_before})。{shot}"
    )
    assert flattens == [], (
        f"読み経路がまだ _flatten を呼んでいる (位置パスへ移っていない): "
        f"{flattens[:5]} (計 {len(flattens)})。{shot}"
    )

    # ── 値の照合: 位置パスが「その列」を返している ───────────────────────────
    misses_at_check = cache.misses
    for j, key in enumerate(expected):
        sig = session.resolve_signal(key)
        assert sig is not None, f"プロット済みの列が解決できない: {key!r}"
        got = np.asarray(sig.values)
        assert np.array_equal(got, _expected_column("WideA", j)), (
            f"列 {j} の値が違う (位置パスが別の列を返している疑い): 先頭 {got[:4]}"
        )
        # spec §5.4 (C1): 命中パスが view を返すと evict しても RSS が下がらず、
        # nbytes_if_materialized も実体の 1/1000 を返してバイト軸が黙って死ぬ。
        # **ただしこの assert は幅 64 の 2-D 列では構造的に恒真**である (実測:
        # apply_path の copy ガードを外しても、幅 3 以上の 2-D スライスは非連続なので
        # ascontiguousarray が必ず実コピーする)。C1 の**一次ゲートは T1/T2** —
        # 連続 view になる 2 形状 (write_mdf4_single_column_shapes の Mono[0] / P.x)
        # を使う test_column_paths.py と test_channel_cache_read_path.py が持つ。
        # ここは「実 GUI 経路でも所有権が崩れていない」ことの**回帰ガード**であって、
        # 所有権違反を検出する歯ではない (歯だと誤解して T1/T2 側を削らないこと)。
        held = sig._values_source.array_if_materialized()
        assert held is not None and held.base is None, (
            f"鋳造列の値が共有 2-D 配列の view になっている (所有権不変条件の違反): "
            f"{key!r}"
        )
    assert cache.misses <= misses_at_check, (
        "値の照合が新しいデコードを誘発した (観測が対象を変えている)"
    )


def test_exploring_columns_one_by_one_hits_the_channel_cache(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """1 列ずつ探索的に実追加 -> 2 本目以降はキャッシュヒット (U1 のもう半分)。"""
    skip_unless_real_display()

    path = write_mdf4_two_wide_channels(tmp_path, rows=_ROWS, cols=_COLS)
    window = _build_window(qtbot)
    loaded_key = _load_and_settle(qtbot, window, path)
    session = window.app_vm.session
    cache = _cache(session)
    handle = session._groups.group(loaded_key).handle
    assert handle is not None

    view = window.channel_browser_view
    model = view.model
    selects = _count_selects(handle, request)
    flattens = _count_flatten(monkeypatch)
    hits_before, misses_before = cache.hits, cache.misses

    parent = _expand_channel(qtbot, window, "WideB")
    panel_vm = window.graph_area_vm.panels(0)[0]
    panel = _panel_widget(window, 0, 0)

    for step, j in enumerate((0, 1, 2)):
        _add_single_row(view, model.index(j, 0, parent))
        key = f"{loaded_key}::WideB[{j}]"
        qtbot.waitUntil(
            lambda k=key: k in panel_vm.plotted_signal_keys(), timeout=_PLOT_TIMEOUT_MS
        )
        _pump_n(4)
        shot = _shot(tmp_path, f"1{step}_added_{j}")

        # 対照: この 1 回で 1 本だけ増え、実際に描かれた。
        assert len(panel_vm.plotted_signal_keys()) == step + 1, (
            f"{step + 1} 回目の追加でプロット数が {len(panel_vm.plotted_signal_keys())} "
            f"— クリックが no-op / 二重発火。{shot}"
        )
        assert key in panel.signal_keys_drawn(), f"実描画されない: {key!r}。{shot}"
        xs, _ys = panel.curve_xy(panel.entry_id_for(key))
        assert xs is not None and len(xs) > 0, f"描画カーブが空: {key!r}。{shot}"

        # 本題: 何本目でもデコードは高々 1 回 (上界・T0 の misses >= select 契約)。
        assert cache.misses - misses_before <= 1, (
            f"{step + 1} 本目でチャンネルを再デコードしている "
            f"(misses+{cache.misses - misses_before})。{shot}"
        )
        assert len(selects) <= 1, (
            f"{step + 1} 本目で asammdf select が再度走った: {len(selects)} 回。{shot}"
        )
        if step > 0:
            assert cache.hits - hits_before >= step, (
                f"{step + 1} 本目がキャッシュヒットになっていない "
                f"(hits+{cache.hits - hits_before})。{shot}"
            )

    assert flattens == [], (
        f"読み経路がまだ _flatten を呼んでいる: {flattens[:5]} (計 {len(flattens)})"
    )

    # 3 本が **それぞれ別の列** を返している (同じ列を配り回していない)。
    misses_at_check = cache.misses
    for j in (0, 1, 2):
        sig = session.resolve_signal(f"{loaded_key}::WideB[{j}]")
        assert sig is not None
        got = np.asarray(sig.values)
        assert np.array_equal(got, _expected_column("WideB", j)), (
            f"WideB[{j}] の値が違う (キャッシュが別の列を返している疑い): 先頭 {got[:4]}"
        )
    assert cache.misses <= misses_at_check, (
        "値の照合が新しいデコードを誘発した (観測が対象を変えている)"
    )


def test_injected_small_budget_evicts_the_older_channel(
    qtbot: QtBot, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """予算を注入して小さくすると古いチャンネルが落ちる (D6・spec §5.1 の LRU)。"""
    skip_unless_real_display()

    path = write_mdf4_two_wide_channels(tmp_path, rows=_ROWS, cols=_COLS)
    # D6: 予算は **Session のコンストラクタ**で注入する。実データでは 256 MB に
    # 広幅 (13.2 MB/本) が ~19 本入るので evict を起こせず、予算そのものを小さく
    # するのが唯一の実験手段。
    # **後から session.channel_cache へ代入する形は使えない** (property に setter が
    # 無いだけでなく、あっても効かない): Session.__init__ が MdfLoader へ渡した
    # 時点で MdfLoader._cache が旧オブジェクトを捕捉し、MdfHandle はロード時に
    # それを提げる。LazyMdfValues.array() が見るのは self._handle.cache なので、
    # 注入した新キャッシュは**誰も書かない** = misses も bytes_held も 0 のまま
    # 以下の全 assert が RED になる (脚 3 が構造的に成立しない)。
    session = Session(cache_budget_bytes=_SMALL_BUDGET)
    window = _build_window(qtbot, session=session)
    cache = _cache(session)

    loaded_key = _load_and_settle(qtbot, window, path)
    # open はチャンネルをデコードしない (E-3 の契約) — ここが 0 でないと以下の
    # 絶対値の会計が読めなくなるので、先に固定する。
    assert (cache.misses, cache.bytes_held) == (0, 0), (
        f"open がチャンネルをデコードしている: misses={cache.misses} "
        f"bytes_held={cache.bytes_held}"
    )
    handle = session._groups.group(loaded_key).handle
    assert handle is not None
    selects = _count_selects(handle, request)

    # 変異の到達範囲を fixture の実測で固定する (T2 の 3 軸 sabotage と同型)。
    # 実測: WideA=(gi=0, ci=1) / WideB=(gi=1, ci=1) — **ci は同じで gi が違う**
    # (ci=0 は各グループの時間マスターチャンネル)。したがって本テストが殺せるのは
    # **gi 軸**であって ci 軸ではない: ci を定数 0 にしても (h,0,0) と (h,1,0) は
    # 別キーのままで衝突せず RED にならない。ci 軸の被覆は core 側
    # (test_channel_cache_read_path.py::test_cache_key_separates_two_channels_in_one_group)
    # が持つ。この 3 本の assert が無いと「どの軸に盲目か」を自己証明できない。
    recs = _records(session, loaded_key)
    positions = {
        n: (recs[n].group_index, recs[n].channel_index) for n in ("WideA", "WideB")
    }
    assert positions["WideA"] != positions["WideB"], positions
    assert recs["WideA"].channel_index == recs["WideB"].channel_index, (
        f"fixture の ci が違う — 本テストは gi 軸ではなく ci 軸を殺している: {positions}"
    )
    assert recs["WideA"].group_index != recs["WideB"].group_index, positions

    view = window.channel_browser_view
    model = view.model
    panel_vm = window.graph_area_vm.panels(0)[0]
    panel = _panel_widget(window, 0, 0)

    # ── (a) WideA[0] を実追加 -> A の 2-D 配列が載る ─────────────────────────
    parent_a = _expand_channel(qtbot, window, "WideA")
    _add_single_row(view, model.index(0, 0, parent_a))
    key_a0 = f"{loaded_key}::WideA[0]"
    qtbot.waitUntil(
        lambda: key_a0 in panel_vm.plotted_signal_keys(), timeout=_PLOT_TIMEOUT_MS
    )
    _pump_n(4)
    shot_a = _shot(tmp_path, "20_a0")
    assert key_a0 in panel.signal_keys_drawn(), f"実描画されない: {key_a0!r}。{shot_a}"
    # 「読んだ」の下界は bytes_held (下) が持つので、ここは上界だけで足りる。
    assert cache.misses <= 1 and len(selects) <= 1, (
        f"1 本目のデコード回数が上界 1 を超えた: misses={cache.misses} "
        f"selects={len(selects)}。{shot_a}"
    )
    assert cache.bytes_held == _ENTRY_BYTES, (
        f"デコード済み 2-D チャンネル配列そのものが載っていない "
        f"(列だけ/upcast の疑い): bytes_held={cache.bytes_held} "
        f"期待 {_ENTRY_BYTES}。{shot_a}"
    )
    assert cache.evictions == 0, f"1 本目で evict が起きている。{shot_a}"
    assert cache.skipped_oversize == 0, (
        f"1 エントリ ({_ENTRY_BYTES} B) が予算超 (D7) と判定された — 注入した予算 "
        f"{_SMALL_BUDGET} B との比較が壊れている。**oversize 判定は reserved を見ない**"
        f" (put は size > budget だけで決める) ので、ここは pin の影響を受けない。"
        f"{shot_a}"
    )
    # pin (T3 の set_reserved) が LRU の最低容量 (1 物理チャンネル分・spec §5.5) を
    # 割り込んでいないことの観測点は **bytes_held**: 割り込んでいれば 1 本目が
    # 載った直後に自分自身を落として 0 になる。上の bytes_held == _ENTRY_BYTES が
    # その assert であり、skipped_oversize ではこの機構を殺せない。

    # ── (b) WideB[0] を実追加 -> 予算超で A が落ちる ─────────────────────────
    parent_b = _expand_channel(qtbot, window, "WideB")
    _add_single_row(view, model.index(0, 0, parent_b))
    key_b0 = f"{loaded_key}::WideB[0]"
    qtbot.waitUntil(
        lambda: key_b0 in panel_vm.plotted_signal_keys(), timeout=_PLOT_TIMEOUT_MS
    )
    _pump_n(4)
    shot_b = _shot(tmp_path, "21_b0")
    assert key_b0 in panel.signal_keys_drawn(), f"実描画されない: {key_b0!r}。{shot_b}"
    # ここだけは **下界** が主張の本体: 別チャンネルの読みが「実際にデコードになった」
    # (= キー空間が gi を含む) ことを言う。上界は暴走 (毎回デコード) の検出用。
    assert len(selects) >= 2, (
        f"別チャンネルの読みがデコードになっていない: selects={len(selects)} "
        f"misses={cache.misses} — キー空間が group_index を含んでいない疑い。{shot_b}"
    )
    assert cache.misses <= 2 and len(selects) <= 2, (
        f"デコード回数が上界 2 を超えた: misses={cache.misses} "
        f"selects={len(selects)}。{shot_b}"
    )
    # **これはシステム全体の assert であって ``put`` の単体ゲートではない** (sabotage
    # 実測): 実 GUI 経路では予算の執行点が **2 つ**ある — ``put`` の evict ループと、
    # プロット変更のたびに ``Session.set_pinned_columns`` から呼ばれる ``set_reserved``
    # の evict ループ。実測で ``put`` 側だけを外しても、直後の pin 更新で
    # ``set_reserved`` が同じエントリを落とすため、この 3 本 (evictions / bytes_held /
    # 冷えた再訪) は**全て緑のまま通る**。ここが固定しているのは「ユーザーの実操作の
    # 結果として予算が執行される」ことであり、両方の執行点を外すと RED になる
    # (実測 evictions=0)。個々のメソッドの歯は Layer A が持つ
    # (tests/core/loaders/test_channel_cache.py — ``put`` 側の除去で 4 本 RED)。
    # ここを「put のテスト」と読んで core 側を削らないこと。
    assert cache.evictions >= 1, (
        f"予算超なのに evict が起きていない (evictions={cache.evictions}) — "
        f"注入した予算 {_SMALL_BUDGET} が効いていない。{shot_b}"
    )
    assert cache.bytes_held == _ENTRY_BYTES, (
        f"2 本が同時に載っている (bytes_held={cache.bytes_held}) — "
        f"バイト予算が執行されていない。{shot_b}"
    )

    # ── (c) 落ちた WideA へ戻る -> 冷えているので再デコード ─────────────────
    _add_single_row(view, model.index(1, 0, parent_a))
    key_a1 = f"{loaded_key}::WideA[1]"
    qtbot.waitUntil(
        lambda: key_a1 in panel_vm.plotted_signal_keys(), timeout=_PLOT_TIMEOUT_MS
    )
    _pump_n(4)
    shot_c = _shot(tmp_path, "22_a1")
    assert key_a1 in panel.signal_keys_drawn(), f"実描画されない: {key_a1!r}。{shot_c}"
    # 下界が主張の本体 (evict 済みチャンネルの再訪は冷えている = 再デコードされる)。
    assert len(selects) >= 3, (
        f"evict 済みチャンネルの再訪がヒット扱いになっている "
        f"(selects={len(selects)} misses={cache.misses}) — 落ちていないか、"
        f"落ちたのに会計が追随していない。{shot_c}"
    )
    assert cache.misses <= 3 and len(selects) <= 3, (
        f"デコード回数が上界 3 を超えた: misses={cache.misses} "
        f"selects={len(selects)}。{shot_c}"
    )
    assert cache.evictions >= 2, (
        f"再ロードで B が落ちていない (evictions={cache.evictions})。{shot_c}"
    )
    assert cache.bytes_held == _ENTRY_BYTES, (
        f"bytes_held={cache.bytes_held} (期待 {_ENTRY_BYTES})。{shot_c}"
    )

    # evict を挟んでも値は正しい (キャッシュの再構築が別の列にならない)。
    for key, channel, j in (
        (key_a0, "WideA", 0),
        (key_b0, "WideB", 0),
        (key_a1, "WideA", 1),
    ):
        sig = session.resolve_signal(key)
        assert sig is not None
        got = np.asarray(sig.values)
        assert np.array_equal(got, _expected_column(channel, j)), (
            f"{key} の値が違う (evict 後の再デコードが別の列/別チャンネル): "
            f"先頭 {got[:4]}。{shot_c}"
        )
