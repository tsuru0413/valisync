"""unload x export の競合は **クラッシュでなく decay** (E-4b・spec §5.7 [I7c])。

今日の防波堤は GUI の busy 述語 1 枚 (`AppViewModel.unload_file`)。E-4b 後もそれは
維持しつつ、core 側の振る舞いを定義する: worker が列を解決できない / 読めなくなったら
B6 経路 (全 temp 削除・ファイル無し・診断 1 件) へ落ちる。

`ExportSourceLost` が `ExportCancelled` を継承するのは、temp 削除と「失敗ならファイルが
存在しない」契約の経路を **1 本に保つ** ため — 別系統の例外にすると `_export_request` の
`finally` の網から漏れ、GUI 側でも `ExportController._fail` の
`isinstance(exc, ExportCancelled)` から外れてエラーモーダルへ流れる。

**decay の入口は 2 つある** (片方だけ塞ぐと production の実レースが素通りする):

1. `Session.export_resolver()` — 解決が `None` を返す (グループが `_groups` から
   消えている)。
2. `CsvExporter._export_request` の `except SampleReadError` — 解決は成功したが
   **読む瞬間** に閉じられた。`Session.remove_group` は `_groups.remove` ->
   `handle.close()` の順なので、`_write_block_temp` の「解決 -> `sorted_view()`」の
   隙間に入るのがこちら。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.export.csv_exporter import (
    CsvExportOptions,
    ExportCancelled,
    ExportSourceLost,
)
from valisync.core.models import Signal
from valisync.core.models.sample_source import SampleReadError
from valisync.core.session import Session


def _load(tmp_path: Path, n: int = 4) -> tuple[Session, str, list[str]]:
    path = tmp_path / "decay.mf4"
    write_mdf4(
        path,
        [
            {
                "name": f"C{i}",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [float(i), float(i + 1)],
            }
            for i in range(n)
        ],
    )
    session = Session()
    key = session.load(path).key
    return session, key, [f"{key}::C{i}" for i in range(n)]


def _leftover_temps(directory: Path) -> list[Path]:
    return sorted(directory.glob(".tmp_export_*"))


# ── 型の契約 ───────────────────────────────────────────────────────────────────


def test_export_source_lost_is_an_export_cancelled() -> None:
    """継承が temp 削除経路の共有そのもの (別系統にすると finally から漏れる)。"""
    assert issubclass(ExportSourceLost, ExportCancelled)


# ── 入口 1: 解決器 (Session.export_resolver) ───────────────────────────────────


class _StubSession:
    """`resolve_signal_transient` だけを持つ最小スタブ (Session を丸ごと作らない)。"""

    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour

    def resolve_signal(self, key: str):  # type: ignore[no-untyped-def]
        # MG-1 の門番をここにも置く: export の解決が LRU 帳簿経路へ退行したら
        # 「decay のテストが緑のまま帳簿を汚す」ことになる。
        raise AssertionError("MG-1: export_resolver は transient 口だけを読むこと")

    def resolve_signal_transient(self, key: str):  # type: ignore[no-untyped-def]
        if self.behaviour == "none":
            return None
        raise SampleReadError(
            "ファイルは既に閉じられています", signal_key=key, source_file="x.mf4"
        )


def _resolver(behaviour: str):  # type: ignore[no-untyped-def]
    return Session.export_resolver(_StubSession(behaviour))  # type: ignore[arg-type]


def test_unloaded_group_decays_to_export_source_lost() -> None:
    with pytest.raises(ExportSourceLost) as excinfo:
        _resolver("none")("mf4_1::A")
    # 文言にキーが載ること: 診断だけを見た人が「どの列で失われたか」を辿れる。
    assert "mf4_1::A" in str(excinfo.value)


def test_sample_read_error_from_the_resolver_decays_too() -> None:
    with pytest.raises(ExportSourceLost) as excinfo:
        _resolver("raise")("mf4_1::A")
    # 元の理由を差し替えない (SampleReadError は I/O 失敗でも上がる)。
    assert "閉じられています" in str(excinfo.value)
    assert excinfo.value.source_file == "x.mf4"


def test_the_decay_carries_the_key_for_the_diagnostic() -> None:
    """GUI は `exc.key` を診断の signal_name に載せる — 空だと宛先が消える。"""
    with pytest.raises(ExportSourceLost) as excinfo:
        _resolver("none")("mf4_1::A")
    assert excinfo.value.key == "mf4_1::A"


def test_the_resolver_returns_the_signal_when_nothing_is_lost(tmp_path: Path) -> None:
    """反 vacuous: 解決器は正常時に **Signal を返す** (常に投げる器ではない)。"""
    session, _key, keys = _load(tmp_path, n=1)
    resolved = session.export_resolver()(keys[0])
    assert resolved.name == keys[0]


# ── production 配線 (差し替えたことの実証) ────────────────────────────────────


def test_exporting_an_unloaded_key_decays_instead_of_value_error(
    tmp_path: Path,
) -> None:
    """`export_csv_request` が `export_resolver()` を通ることの**唯一の**実証。

    `resolve_signal_transient` を直接渡していた頃、欠落キーは `scan_masters` の
    `ValueError` になっていた (= decay ではない ⇒ GUI はエラーモーダルを出すだけで
    診断が 1 件も残らない)。差し替えを戻すとここが `ValueError` で RED になる。
    """
    session, key, keys = _load(tmp_path)
    out = tmp_path / "gone.csv"
    session.remove_group(key)  # エクスポートの直前にアンロード

    with pytest.raises(ExportSourceLost):
        session.export_csv(keys, out)

    assert not out.exists(), "失敗したのに出力ファイルが残っている (B6)"
    assert _leftover_temps(tmp_path) == [], "temp が残っている (B6)"


def test_a_healthy_export_still_writes_the_file(tmp_path: Path) -> None:
    """positive control — 上の RED が「fixture が壊れている」由来でないこと。"""
    session, _key, keys = _load(tmp_path)
    out = tmp_path / "ok.csv"

    session.export_csv(keys, out)

    assert out.exists() and out.stat().st_size > 0
    assert _leftover_temps(tmp_path) == []


# ── 入口 2: 読みの最中に閉じられた (production の実レース) ────────────────────


def test_unload_between_the_scan_and_the_block_write_leaves_nothing(
    tmp_path: Path,
) -> None:
    """前走査は通ったがブロック書きで解決できなくなる窓 (temp が既に在る状態)。

    ここが 1 番厳しい形: 時刻 temp を書き終えた後に落ちるので、`finally` の掃除が
    効いていなければ `.tmp_export_*` が実際に残る。
    """
    session, key, keys = _load(tmp_path)
    out = tmp_path / "midway.csv"
    original = session.resolve_signal_transient
    seen: list[str] = []

    def unload_after_the_scan(k: str):  # type: ignore[no-untyped-def]
        seen.append(k)
        if len(seen) == len(keys):  # 前走査の最後の列を返した直後に閉じる
            result = original(k)
            session.remove_group(key)
            return result
        return original(k)

    session.resolve_signal_transient = unload_after_the_scan  # type: ignore[method-assign]

    with pytest.raises(ExportSourceLost):
        session.export_csv(keys, out)

    assert len(seen) > len(keys), "ブロック書きの解決まで到達していない (窓が違う)"
    assert not out.exists()
    assert _leftover_temps(tmp_path) == [], "decay 時に temp が残った (B6)"


def test_reading_a_closed_handle_mid_export_decays(tmp_path: Path) -> None:
    """解決は成功し **読みで** 落ちる経路 (`Session.remove_group` の実際の順序)。

    `_mint_column` / namespaced ラッパはどちらも I/O を伴わないので、ハンドルを
    閉じても解決は成功し `LazyMdfValues` を提げた Signal が返る。落ちるのは
    `_write_block_temp` の `sorted_view()`。`except SampleReadError` を外すと
    `SampleReadError` がそのまま出て `ExportCancelled` 系から外れる。
    """
    session, key, keys = _load(tmp_path)
    out = tmp_path / "closed.csv"
    handle = session._groups.group(key).handle
    assert handle is not None
    sig = session.resolve_signal_transient(keys[0])
    assert sig is not None
    assert sig._values_source.is_materialized is False, (
        "値が既に実体化しているので閉じても読みが失敗しない (遅延経路を踏めていない)"
    )
    del sig
    handle.close()  # グループは残したまま閉じる = 解決は通り、読みだけが落ちる

    with pytest.raises(ExportSourceLost) as excinfo:
        session.export_csv(keys, out, CsvExportOptions())

    # 型は decay へ寄せるが、理由は元の文言のまま運ぶ。
    assert "閉じられています" in str(excinfo.value)
    assert excinfo.value.key == "C0", f"チャンネル名が載っていない: {excinfo.value.key}"
    assert not out.exists()
    assert _leftover_temps(tmp_path) == []


class _FailingSource:
    """読みだけが失敗する SampleSource (I/O 障害の形 — 「閉じられた」ではない)。

    `LazyMdfValues` は `__slots__` なので `array` を差し替えられない。実ハンドルを
    壊す代わりに、同じ契約を満たす最小のソースを渡す。
    """

    def __init__(self, length: int) -> None:
        self._length = length

    @property
    def is_materialized(self) -> bool:
        return False

    @property
    def length(self) -> int:
        return self._length

    @property
    def nbytes_if_materialized(self) -> int:
        return 0

    def array_if_materialized(self):  # type: ignore[no-untyped-def]
        return None

    def array(self):  # type: ignore[no-untyped-def]
        raise SampleReadError("ディスクが読めません", signal_key="C0")


def test_a_read_failure_is_not_relabelled_as_a_close(tmp_path: Path) -> None:
    """SampleReadError は「閉じられた」以外でも上がる — 文言を上書きしないこと。

    上書きすると、ディスク I/O 障害が「元ファイルが閉じられました」という**嘘の**
    診断として残る (型 = 扱いだけを decay へ寄せ、理由は伝聞のまま渡す契約)。
    """
    session, _key, keys = _load(tmp_path, n=1)
    out = tmp_path / "ioerr.csv"
    healthy = session.resolve_signal_transient(keys[0])
    assert healthy is not None
    broken = Signal(
        name=keys[0],
        timestamps=healthy.timestamps,
        values_source=_FailingSource(len(healthy.timestamps)),
        file_format=healthy.file_format,
        bus_type=healthy.bus_type,
        source_file=healthy.source_file,
    )
    session.resolve_signal_transient = lambda _k: broken  # type: ignore[assignment, method-assign]

    with pytest.raises(ExportSourceLost) as excinfo:
        session.export_csv(keys, out, CsvExportOptions())

    assert "ディスクが読めません" in str(excinfo.value)
    assert "閉じられ" not in str(excinfo.value)
    assert not out.exists()
    assert _leftover_temps(tmp_path) == []
