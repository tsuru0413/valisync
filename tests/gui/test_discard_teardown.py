"""_discard (手遅れ完走のロールバック) の遅延解放を固定する (増分B)。

330,004 シェルの同期解放は GUI スレッドで実測 649ms。Task 1 で close は
remove_group が担うようになったが、遅延解放の配線は別途要る。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.models import Signal, SignalGroup
from valisync.core.session import LoadOutcome, Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel


def _loaded_but_discarded_setup(
    qtbot: QtBot, tmp_path: Path
) -> tuple[Any, LoadOutcome, int, Callable[[LoadOutcome], None]]:
    """実 `_load_file` から `_discard` クロージャを捕まえ、ロードを完走させる。

    `_discard` は `_load_file` 内のクロージャなので外から掴めないが、**プロダクション
    にテスト専用の入口は足さない** — `LoadController.submit` を差し替えて kwargs の
    `on_discard` を取り出し、同じく渡された load_callable を同期実行することで
    「キャンセルが手遅れでロードが完走した」状態そのものを作る
    (`tests/gui/test_main_window.py::test_load_file_wires_cancel_event_and_adapter`
    と同型の捕捉)。`on_success` は呼ばないので `register_loaded` を通らず、この
    グループは `loaded_keys` に載らない = 実 `_discard` の前提と同じ。
    """
    from valisync.gui.views.main_window import MainWindow

    path = tmp_path / "discard.mf4"
    write_mdf4(
        path,
        [
            {
                "name": f"Sig{i}",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [float(i), float(i) + 1.0],
            }
            for i in range(5)
        ],
    )
    app_vm = AppViewModel(session=Session())
    win = MainWindow(app_vm)
    qtbot.addWidget(win)

    captured: dict[str, Any] = {}

    def fake_submit(load_callable: Callable[[], LoadOutcome], **kwargs: Any) -> None:
        captured["on_discard"] = kwargs["on_discard"]
        captured["load"] = load_callable

    win._load_controller.submit = fake_submit  # type: ignore[method-assign]
    win._load_file(path)
    outcome = captured["load"]()  # 手遅れ = ワーカーは既に完走している
    n_signals = len(app_vm.session._groups.group(outcome.key).signals)
    assert n_signals > 0, "fixture が空グループでは手渡しを観測できない"
    assert outcome.key not in app_vm.loaded_file_keys, (
        "_discard の前提が崩れている (register_loaded を通ってしまった)"
    )
    return win, outcome, n_signals, captured["on_discard"]


def _loaded(tmp_path: Path) -> tuple[AppViewModel, str, MdfHandle]:
    """tests/gui/test_unload_export_guard.py と同型の最小ロード。"""
    path = tmp_path / "guard.mf4"
    write_mdf4(
        path,
        [
            {
                "name": "Spd",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            }
        ],
    )
    session = Session()
    key = session.load(path, confirm_expansion=None).key
    app_vm = AppViewModel(session=session)
    app_vm.register_loaded(key)
    handle = session._groups.group(key).handle
    assert handle is not None
    return app_vm, key, handle


def _minted_column(name: str) -> Signal:
    """tests/test_session.py の `_derived(...)` と同型 (鋳造列の代役)。"""
    return Signal(
        name=name,
        timestamps=np.array([0.0], dtype=np.float64),
        values=np.array([1.0], dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )


class _DummyTeardown:
    """duck-typed teardown — enqueue(key, group, columns=...) の実引数をそのまま記録する。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, SignalGroup, tuple[Signal, ...]]] = []

    def enqueue(
        self, key: str, group: SignalGroup, columns: tuple[Signal, ...] = ()
    ) -> None:
        self.calls.append((key, group, columns))


def test_discard_hands_the_group_to_the_teardown_service(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """本命: 遅延解放が実際に起きたことを pending_signals で観測する。"""
    win, outcome, n_signals, discard = _loaded_but_discarded_setup(qtbot, tmp_path)
    win.teardown_service._timer.stop()  # ドレインを止めて手渡しだけを見る

    discard(outcome)

    assert win.teardown_service.pending_signals() == n_signals


def test_discard_closes_the_handle(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """spec の Layer A 項目「_discard 経路でも close される」(Task 1 の close 規約が
    _discard も構造的にカバーしていることのガード)。"""
    win, outcome, _n, discard = _loaded_but_discarded_setup(qtbot, tmp_path)
    handle = win.app_vm.session._groups.group(outcome.key).handle
    assert handle is not None and handle.is_closed is False

    discard(outcome)

    assert handle.is_closed is True


def test_discard_never_shows_a_releasing_row(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """UI churn が無いこと (幽霊行懸念の正直形)。

    `len(vm.files) == 1` は現行コードでも通る恒真 assert なので使わない。
    "releasing" 通知が 1 度も飛ばないことを見る — mark_released の既定値 pop が
    将来外れた場合に RED になる。
    """
    win, outcome, _n, discard = _loaded_but_discarded_setup(qtbot, tmp_path)
    tags: list[str] = []
    win.app_vm.subscribe(tags.append)

    discard(outcome)
    qtbot.waitUntil(lambda: win.teardown_service.pending_signals() == 0, timeout=5000)

    assert "releasing" not in tags


def test_minted_columns_are_handed_to_the_teardown_service(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """E-3 本命: 鋳造列も同じ enqueue で TeardownService へ渡る。

    渡さないと result のスコープアウトで GUI スレッドの同期解放になる (プロット済み列は
    実体化済み = バイトが重い → FU-16 のフリーズが戻る)。E-1 では loud-fail の tripwire で
    代用していたが、本タスクで実配線に置き換える。
    """
    # _loaded は tests/gui/test_unload_export_guard.py と同型
    app_vm, key, _handle = _loaded(tmp_path)
    dummy = _DummyTeardown()
    app_vm.set_teardown(dummy)
    column = _minted_column(f"{key}::Spd[7]")
    app_vm.session._groups._resolved_by_key.setdefault(key, {})[column.name] = column

    app_vm.unload_file(key)

    assert len(dummy.calls) == 1  # 同一 key を 2 エントリに割らない
    got_key, got_group, got_columns = dummy.calls[0]
    assert got_key == key
    assert got_group is not None  # グループ本体は従来どおり渡る
    assert got_columns == (column,)  # 鋳造列が同じ呼び出しに乗る


def test_discard_also_hands_the_minted_columns(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """2 サイト目 (_discard) も列を渡す。

    session.load はグループ登録 (session.py:170) の**後**にキャンセルが確定するので、その窓で
    resolve された列は実在しうる。_discard は AppViewModel を経由しないため、unload_file 側の
    配線では 1 バイトもカバーされない。
    """
    win, outcome, n_signals, discard = _loaded_but_discarded_setup(qtbot, tmp_path)
    # 注意: enqueue はタイマーを再始動する (teardown_service.py の start)。ここが
    # 決定的なのは stop() ではなく「assert までイベントループを回さない」ことによる。
    win.teardown_service._timer.stop()
    column = _minted_column(f"{outcome.key}::Sig0[1]")
    resolved = win.app_vm.session._groups._resolved_by_key
    resolved.setdefault(outcome.key, {})[column.name] = column

    discard(outcome)

    assert win.teardown_service.pending_signals() == n_signals + 1
    # 件数だけでは「その列が渡ったか」も「1 キー 1 エントリか」も pin できない。
    # _discard は tripwire を持たない唯一の経路なので、実体で押さえる。
    entries = win.teardown_service._groups
    assert len(entries) == 1, f"1 キー = 1 エントリのはず ({len(entries)} エントリ)"
    assert column in entries[-1][1]
