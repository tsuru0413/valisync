"""`ExportController.submit` の後方互換 pin(E-4b Task 4)。

spec §5.2 は「submit の署名は後方互換に拡張」と書くが、**T-API では拡張が
要らない**(境界の変更は callable の中身にしか現れない)。進捗/キャンセルを
足すのは T-UX (Task 8/9) なので、ここでは「足すときに壊してはいけない形」を
固定するだけにする — 既存 5 本と合わせてこれが Task 8/9 の受け入れ条件になる。
"""

from __future__ import annotations

import inspect
import threading

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.workers.export_worker import ExportController


def test_submit_takes_a_zero_arg_callable_positionally() -> None:
    """第 1 引数は位置で渡せる zero-arg callable のまま(既存 5 本の前提)。"""
    sig = inspect.signature(ExportController.submit)
    params = list(sig.parameters.values())
    assert params[1].name == "export_callable"
    assert params[1].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    # busy/on_success/on_error/label はすべて既定つきキーワード専用
    for name in ("busy", "on_success", "on_error", "label"):
        p = sig.parameters[name]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY
        assert p.default is None


def test_worker_is_retained_until_the_callback_fires(qtbot: QtBot) -> None:
    """QRunnable + 別 signals QObject の寿命保持(memory: queued signal 消失)。

    Task 8/9 が submit へ progress/cancel を足すときに最も落としやすい不変条件。
    `_active` を直接見るのは、これが「参照を保持している」ことの唯一の観測点だから。
    """
    ctl = ExportController()
    release = threading.Event()
    done: list[int] = []
    ctl.submit(lambda: release.wait(5.0), on_success=lambda: done.append(1))
    assert len(ctl._active) == 1
    release.set()
    qtbot.waitUntil(lambda: done == [1], timeout=5000)
    assert ctl._active == set()
