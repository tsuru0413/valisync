"""BusyOverlay の所有権 (参照カウント) と determinate 進捗 / ETA (E-4b・spec §5.5)。

今日の 3 衝突のうち 2 つ (所有権・不確定バー) をここで閉じる。3 つ目 (cancel の
恒久配線) は test_export_cancel_routing.py。

ETA は注入した時計で駆動する — wall-clock に依存させると「遅いマシンで落ちる」
テストになり、値を緩めた瞬間に何も検証しなくなる。
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import LoadOutcome
from valisync.gui.views.busy_overlay import BusyOverlay


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _blocking_load(release: threading.Event) -> Callable[[], LoadOutcome]:
    """release が立つまで戻らないロード callable (実 LoadController を走らせる)。"""

    def _run() -> LoadOutcome:
        release.wait(5.0)
        return LoadOutcome("late")

    return _run


def test_overlay_stays_up_until_every_owner_releases(qtbot: QtBot) -> None:
    """衝突 2: 1 インスタンス共有でも、片方の完了が他方の overlay を消さない。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    load, export = object(), object()

    overlay.acquire(load, message="a.mf4 を読み込み中…")
    overlay.acquire(export, message="out.csv をエクスポート中…")
    assert overlay.owner_count() == 2
    assert not overlay.isHidden()

    overlay.release(export)
    assert not overlay.isHidden(), "export の完了が load の overlay を消した"
    assert overlay.message() == "a.mf4 を読み込み中…", "残った所有者の文言へ戻らない"

    overlay.release(load)
    assert overlay.isHidden()
    assert overlay.owner_count() == 0


def test_release_of_a_non_owner_is_a_no_op(qtbot: QtBot) -> None:
    """遅れて届いた解放が、無関係な所有者の overlay を落とさない。

    LoadController は cancel 済みワーカーの完了で _refresh_busy を呼ばないが、
    非 cancel の別ワーカーが後から 0 件で refresh する経路がある (load_worker._pop)。
    """
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="x")
    overlay.release(object())
    assert not overlay.isHidden()
    assert overlay.owner_count() == 1


def test_progress_makes_the_bar_determinate_and_release_restores_it(
    qtbot: QtBot,
) -> None:
    """衝突 3: ブロック進捗を出す。解放したら不確定へ戻す (次のロードが壊れない)。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    owner = object()
    assert overlay.is_indeterminate()  # 構築直後は従来どおり不確定

    overlay.acquire(owner, message="エクスポート中…")
    overlay.set_progress(owner, 3, 12)

    assert not overlay.is_indeterminate()
    assert overlay.progress_bar.maximum() == 12
    assert overlay.progress_bar.value() == 3

    overlay.release(owner)
    assert overlay.is_indeterminate(), "解放後も determinate のままだと次のロードで固着"


def test_releasing_the_progress_owner_restores_the_bar_for_the_others(
    qtbot: QtBot,
) -> None:
    """進捗の持ち主だけが抜けても、**残る所有者のために**不確定へ戻す。

    「最後の 1 人が抜けたときの全体リセット」とは別の経路 — こちらが無いと、
    エクスポート完了後もロードの overlay が「12 分の 3」で固まったまま残る。
    """
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    load, export = object(), object()
    overlay.acquire(load, message="a.mf4 を読み込み中…")
    overlay.acquire(export, message="out.csv をエクスポート中…")
    overlay.set_progress(export, 3, 12)
    assert not overlay.is_indeterminate()

    overlay.release(export)

    assert overlay.owner_count() == 1, "positive control: load はまだ持っている"
    assert not overlay.isHidden()
    assert overlay.is_indeterminate(), "エクスポートの進捗がロードの表示に残った"


def test_eta_says_measuring_until_the_first_unit_completes(qtbot: QtBot) -> None:
    """done=0 は 0 除算そのもの。外挿できないことを人に見せる (spec §5.5)。"""
    clock = _Clock()
    overlay = BusyOverlay(clock=clock)
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="エクスポート中…")

    clock.now = 4.0
    overlay.set_progress(owner, 0, 10)

    assert "計測中" in overlay.eta_text()


def test_eta_extrapolates_from_elapsed_over_completed(qtbot: QtBot) -> None:
    """経過 x 残り/完了。2/10 を 4 秒で終えたなら残り 8 単位 = 16 秒。"""
    clock = _Clock()
    overlay = BusyOverlay(clock=clock)
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="エクスポート中…")
    overlay.set_progress(owner, 0, 10)  # 起点を記録

    clock.now = 4.0
    overlay.set_progress(owner, 2, 10)

    assert "16 秒" in overlay.eta_text(), overlay.eta_text()


def test_eta_stops_promising_a_number_once_only_the_merge_stages_remain(
    qtbot: QtBot,
) -> None:
    """末尾のマージ段では**数字を出さない** (単位が等重でない・csv_exporter の
    `n_units` コメント)。

    prod 形は「時刻 1 + ブロック 8,253 + マージ 2 = 8,256 単位」で、マージ 2 単位は
    単位数では 0.024% しかないのに実時間では ~10 GB の全列を 2 回フル読み書きする。
    線形 ETA をそのまま出すと、バーが 8,254/8,256 に達した瞬間から数分間ずっと
    「残り時間: 約 0 秒」と嘘をつく。
    """
    clock = _Clock()
    overlay = BusyOverlay(clock=clock)
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="エクスポート中…")
    overlay.set_progress(owner, 0, 8256)  # 起点

    clock.now = 600.0
    overlay.set_progress(owner, 8000, 8256)  # まだブロック中 = 外挿できる
    assert "秒" in overlay.eta_text(), overlay.eta_text()

    overlay.set_progress(owner, 8254, 8256)  # 全ブロック完了・残りはマージ段のみ

    assert "仕上げ処理中" in overlay.eta_text(), overlay.eta_text()
    assert "秒" not in overlay.eta_text(), (
        "線形 ETA のまま = 「残り時間: 約 0 秒」と言いながら数分回る"
    )


def test_zero_total_does_not_divide_by_zero(qtbot: QtBot) -> None:
    """総単位 0 (空選択の縁) でも例外を出さない。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="x")
    overlay.set_progress(owner, 0, 0)
    assert overlay.is_indeterminate()


def test_progress_from_a_released_owner_is_ignored(qtbot: QtBot) -> None:
    """queued 配送で遅れて届いた進捗が、解放済みの overlay を再表示しない。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="x")
    overlay.release(owner)
    overlay.set_progress(owner, 5, 10)
    assert overlay.isHidden()
    assert overlay.is_indeterminate()


def test_a_finished_load_does_not_take_the_overlay_from_a_running_export(
    qtbot: QtBot,
) -> None:
    """所有権を **実 controller 2 本が同時に走っている状態**で見る (衝突 2 の実経路)。

    object() を owner にした上のテストは overlay 側の算術しか見ていないので、
    LoadController / ExportController が hide() を直呼びしたままでも緑になる。
    2 本を **逐次でなく同時に** 走らせないと、この衝突は再現しない。
    """
    from valisync.gui.workers.export_worker import ExportController
    from valisync.gui.workers.load_worker import LoadController

    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    load_ctl = LoadController()
    export_ctl = ExportController()
    load_release = threading.Event()
    export_release = threading.Event()

    export_ctl.submit(lambda: export_release.wait(5.0), busy=overlay, label="out.csv")
    load_ctl.submit(_blocking_load(load_release), busy=overlay, label="a.mf4")
    assert overlay.owner_count() == 2, "2 本同時が成立していない (前提の確認)"

    load_release.set()
    qtbot.waitUntil(lambda: overlay.owner_count() == 1, timeout=5000)

    assert not overlay.isHidden(), "ロードの完了がエクスポートの overlay を消した"
    assert "out.csv" in overlay.message(), "残ったエクスポートの文言へ戻らない"

    export_release.set()
    qtbot.waitUntil(lambda: overlay.isHidden(), timeout=5000)
    assert overlay.owner_count() == 0
