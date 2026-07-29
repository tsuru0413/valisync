"""unload でファイルロックが決定的に解放されることを固定する (増分B)。

今日でも最終的には解放されるが、それは asammdf の MDF.__del__ 経由で
「そのグループの最後の Signal 参照が死んだ時」= TeardownService のドレイン後
であり非決定的。明示 close で決定化する。

**CI 可視の主オラクルは `MdfHandle.is_closed` と mdf.close() の呼出回数**
(test_handle_is_closed_after_remove / test_remove_group_calls_close_exactly_once)。
os.replace を使う 2 本は Windows 限定 gate を付けてある — POSIX の rename(2) は
open 中のファイルでも成功するので、ubuntu CI では「確定 RED」か「恒真 PASS」に
しかならない (Global Constraints)。実 OS のロック解放の一次証拠は Task 8 の realgui。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.session import Session

windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="open-file rename lock は Windows のファイル共有セマンティクス "
    "(POSIX の rename(2) は open 中でも成功する)",
)


def _load_one(tmp_path: Path) -> tuple[Session, str, Path]:
    path = tmp_path / "lock.mf4"
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
    outcome = session.load(path)
    return session, outcome.key, path


@windows_only
def test_file_is_locked_while_loaded(tmp_path: Path) -> None:
    session, _key, path = _load_one(tmp_path)
    victim = tmp_path / "moved.mf4"
    with pytest.raises(OSError):
        os.replace(path, victim)  # 開いている間は移動できない
    del session  # 明示: ここまで session を生存させる (早期解放でロックが落ちない)


@windows_only
def test_remove_group_releases_the_lock_without_gc(tmp_path: Path) -> None:
    # gc.collect() を呼ばずに解放されることが「決定的」の意味
    session, key, path = _load_one(tmp_path)
    session.remove_group(key)
    victim = tmp_path / "moved.mf4"
    os.replace(path, victim)  # 例外が出なければ成功
    assert victim.exists()


def test_handle_is_closed_after_remove(tmp_path: Path) -> None:
    """CI 可視の主オラクル (platform 非依存)。"""
    session, key, _path = _load_one(tmp_path)
    handle = session._groups.group(key).handle  # remove 前に掴んでおく
    assert handle is not None and handle.is_closed is False
    session.remove_group(key)
    assert handle.is_closed is True


def test_remove_group_calls_close_exactly_once(tmp_path: Path) -> None:
    """close 回数の platform 非依存オラクル (冪等 close なので 0 回も 2 回も不可)。"""

    class _CloseSpy:
        """handle.mdf を包んで close 回数を数える。

        MdfHandle.__slots__ に "mdf" があるのでインスタンス差し替えができる。
        """

        def __init__(self, real: object) -> None:
            self.real = real
            self.calls = 0

        def close(self) -> None:
            self.calls += 1
            self.real.close()

    session, key, _path = _load_one(tmp_path)
    handle = session._groups.group(key).handle
    assert handle is not None
    spy = _CloseSpy(handle.mdf)
    handle.mdf = spy
    session.remove_group(key)
    assert spy.calls == 1, f"mdf.close() が {spy.calls} 回 (冪等 close なので 1 回が正)"


def test_refused_removal_leaves_the_handle_open(tmp_path: Path) -> None:
    """拒否経路 (removed=False) は handle を閉じない。

    close は ``self._groups.remove(key)`` の後 = 依存 Derived_Signal による early
    return より下にあるので構造的に到達しないが、既存の拒否テスト
    (test_session.py) は CSV グループ (handle=None) しか使っておらず「閉じない」
    ことを実証していない。close 呼び出しが early return より上へ移動する回帰を
    ここで捕まえる。force=True の後続 assert が「そもそも依存が効いていない」
    との区別 (positive control) になっている。
    """
    session, key, _path = _load_one(tmp_path)
    handle = session._groups.group(key).handle
    assert handle is not None
    src = session.signals()[0]
    session.evaluate_formula(f"{src.name} * 2", {src.name: src})

    refused = session.remove_group(key)

    assert refused.removed is False
    assert handle.is_closed is False, "拒否されたのに handle が閉じられた"

    assert session.remove_group(key, force=True).removed is True
    assert handle.is_closed is True  # positive control: force なら閉じる


def test_csv_group_removal_does_not_touch_a_handle(tmp_path: Path) -> None:
    """CSV は handle=None。close 経路が None で落ちないこと。

    (旧名 test_remove_group_is_idempotent_for_csv_groups — 本文は冪等性を一切
    exercise していなかったのでリネームした。冪等性の実挙動は
    test_remove_group_twice_raises が pin する。)
    """
    from valisync.core.models import Delimiter, FormatDefinition

    csv = tmp_path / "d.csv"
    csv.write_text("t,v\n0,1\n1,2\n", encoding="utf-8")
    session = Session()
    fmt = FormatDefinition(
        name="t1",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    key = session.load(csv, fmt).key
    result = session.remove_group(key)
    assert result.removed is True


def test_remove_group_twice_raises(tmp_path: Path) -> None:
    """spec の「多重 unload 冪等」は今日のコードに対して偽 — 実挙動を pin する。

    2 回目は SignalGroupManager.remove が KeyError (signal_group_manager.py:57-60)。
    GUI からは 1 回目でキーがリストから消えるため到達不能なので、冪等化ではなく
    spec 文言の訂正を選んだ (改訂履歴の判断 2)。
    """
    session, key, _path = _load_one(tmp_path)
    session.remove_group(key)
    with pytest.raises(KeyError):
        session.remove_group(key)


def test_registration_failure_closes_the_handle(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """add() が raise しても handle はリークしない (CI 可視の主オラクル)。

    GUI では _on_load_error がモーダルを出す間トレースバックが handle を pin する
    ため、閉じないとダイアログ表示中ずっとファイルがロックされる。
    """
    path = tmp_path / "reg_fail.mf4"
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
    captured: list[object] = []

    # 本物の add と同じシグネチャに揃える (E-3 T1 で column_records が追加された)。
    # オラクルは handle.is_closed のまま — 二重 (double) の受け口だけを広げる。
    def _boom(group, column_records=None):  # type: ignore[no-untyped-def]
        captured.append(group)  # 強参照を保持 -> GC ではなく close だけを測る
        raise ValueError("unsupported file_format: 'MDF3'")

    monkeypatch.setattr(session._groups, "add", _boom)
    with pytest.raises(ValueError):
        session.load(path)

    handle = captured[0].handle
    assert handle is not None and handle.is_closed is True


@windows_only
def test_registration_failure_does_not_leave_the_file_locked(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """実 OS のロック解放版 (Windows のみ — POSIX の rename は open 中でも成功する)。"""
    path = tmp_path / "reg_fail2.mf4"
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

    def _boom(_group, column_records=None):  # type: ignore[no-untyped-def]
        raise ValueError("unsupported file_format: 'MDF3'")

    monkeypatch.setattr(session._groups, "add", _boom)
    with pytest.raises(ValueError):
        session.load(path)

    victim = tmp_path / "moved2.mf4"
    os.replace(path, victim)  # 例外が出なければリークしていない
    assert victim.exists()
