"""ロック順 probe: handle.lock 保持中に resolve() を呼ばない (E-4b・spec §10)。

列ブロックの **最も自然な書き方**

    with handle.lock:
        for k in block:
            resolve(k)

がこの契約を破る。破っても単一スレッドでは何も起きない (``threading.Lock`` は非再帰
だが acquire しに行かないので self-deadlock すら起きず、ただ他スレッドの読みを
~18 分止めるだけ) ため、**テストでしか捕まえられない**。E-4a の ``_LockProbeArray``
(tests/core/loaders/test_channel_cache.py) と同じ「その瞬間にロック状態を非ブロッキング
で問い合わせる」手法を転用する。

非ブロッキング acquire が False を返す原因は「自スレッドが保持」と「他スレッドが保持」
の 2 つあるので、**このテストは単一スレッドで走らせる** (他に握る者が居ない状態を作る)。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest


def assert_no_resolve_under_handle_lock(handle: Any, resolve: Any) -> Any:
    """*resolve* を包み、呼び出し時に *handle.lock* が保持されていたら即座に落とす。

    ブロック処理へこのラッパを差し込んで使う (常設 probe)。差し込む口は
    ``scan_masters`` / ``CsvExporter.export`` の ``resolve`` 引数そのもの —
    「ブロックを列挙する公開関数」は存在しない (``plan_blocks`` は runs と幅しか
    受け取らない純関数)。
    """

    def probed(key: str):  # type: ignore[no-untyped-def]
        acquired = handle.lock.acquire(blocking=False)
        if not acquired:
            raise AssertionError(
                "handle.lock を保持したまま resolve() が呼ばれた (spec §10 違反)"
            )
        handle.lock.release()
        return resolve(key)

    return probed


def test_probe_detects_a_violation() -> None:
    """probe 自身が効くことの positive control (probe が壊れていたら全部緑になる)。"""

    class _H:
        lock = threading.Lock()

    handle = _H()
    probed = assert_no_resolve_under_handle_lock(handle, lambda k: k)
    assert probed("ok") == "ok"
    with handle.lock:
        try:
            probed("bad")
        except AssertionError:
            return
    raise AssertionError("probe が違反を見逃した")


def test_block_pipeline_never_resolves_under_the_handle_lock(tmp_path: Path) -> None:
    """**実在 API のブロック経路**を probe 越しに走らせ、違反ゼロを固定する。

    前走査 (``scan_masters``・値を読まない) とブロック書き
    (``CsvExporter.export`` -> ``_write_block_temp``) の **両方** を probe 越しに
    通す。片方だけだと、もう片方が handle.lock 下で resolve していても緑になる。

    ``block_cols=2`` は「ブロックを複数作る」ための注入 — 1 ブロックに収まると
    「ブロック 2 本目の解決」という最も破りやすい窓 (前ブロックの読みが lock を
    握ったまま次を解決する形) が観測窓ごと消える。
    """
    from tests.mdf4_helpers import CAN, write_mdf4
    from valisync.core.export.csv_exporter import (
        CsvExporter,
        CsvExportOptions,
        ExportRequest,
        scan_masters,
    )
    from valisync.core.export.timeline import union_timeline
    from valisync.core.session import Session

    path = tmp_path / "probe.mf4"
    write_mdf4(
        path,
        [
            {
                "name": f"C{i}",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [float(i), float(i + 1)],
            }
            for i in range(6)
        ],
    )
    session = Session()
    key = session.load(path).key
    handle = session._groups.group(key).handle
    assert handle is not None
    keys = [f"{key}::C{i}" for i in range(6)]
    columns = [(k, None) for k in keys]
    probed = assert_no_resolve_under_handle_lock(handle, session.export_resolver())

    scan = scan_masters(columns, probed)
    union = union_timeline(scan.masters)
    out = tmp_path / "probe_out.csv"
    CsvExporter(block_cols=2).export(
        ExportRequest(
            keys=tuple(keys),
            output_path=out,
            options=CsvExportOptions(),
            header_resolver=list,
        ),
        probed,
    )
    assert len(union) == 2  # 反 vacuous: 実際に列を走査している
    # 反 vacuous その 2: 実際に**読み**まで到達している。resolve が 1 度も
    # 呼ばれない (前走査だけで落ちる) 構成では probe は何も見ていない。
    assert out.exists() and len(out.read_text(encoding="utf-8-sig").splitlines()) == 3


def test_a_pipeline_shaped_violation_is_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Minor 4 (Task 10b レビュー是正): probe が「本物の壊れた実装」を検出する
    ことの permanent positive control。

    `test_probe_detects_a_violation` は probe 自身のロジックを固定し、
    `test_block_pipeline_never_resolves_under_the_handle_lock` は**今日の**
    実パイプラインが契約を守っていることを固定する ― だが両方あわせても
    「実パイプラインが**破った形**を probe が検出できる」ことまでは実証しない
    (probe ロジックだけ壊れて実パイプラインだけ緑、という取り違えを別々には
    捕まえられない)。ここでその隙間を埋める: モジュール docstring が言う
    「ブロックの最も自然な誤書き方」―

        with handle.lock:
            for k in block:
                resolve(k)

    ―を `_write_block_temp` (実 API) の呼び出しへ monkeypatch でそのまま
    再現する。

    最初に試した src サボタージュ (``LazyMdfValues.array()`` の末尾で lock を
    握りっぱなしにする) は 1 度取った lock を誰も解放しないため、次の
    ``array()``/``close()`` が同じ非再帰 Lock へ**再入**して自スレッド
    deadlock を起こし、pytest ごと 300 秒ハングした (S12 misfire ―
    task-10b-report.md §3 参照。ハングは RED でも GREEN でもなく「サボタージュが
    効いたか不明」になるだけ)。ここでは逆に「`_write_block_temp` **1 回分**を
    lock で包む」形にする ― probe の `acquire(blocking=False)` はブロッキングで
    待たずその場で False を返すので、`with handle.lock:` を抜けるより前に
    `AssertionError` で即 unwind し、lock は `with` の後始末で確実に解放される
    (握りっぱなしの窓が存在しないので S12 のハング要因が構造的に無い)。
    src には 1 バイトも触れない (monkeypatch はテストプロセス内限定)。
    """
    from tests.mdf4_helpers import CAN, write_mdf4
    from valisync.core.export.csv_exporter import (
        CsvExporter,
        CsvExportOptions,
        ExportRequest,
    )
    from valisync.core.session import Session

    path = tmp_path / "pipeline_violation.mf4"
    write_mdf4(
        path,
        [
            {
                "name": f"C{i}",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [float(i), float(i + 1)],
            }
            for i in range(6)
        ],
    )
    session = Session()
    key = session.load(path).key
    handle = session._groups.group(key).handle
    assert handle is not None
    keys = [f"{key}::C{i}" for i in range(6)]
    probed = assert_no_resolve_under_handle_lock(handle, session.export_resolver())

    original_write_block_temp = CsvExporter._write_block_temp

    def pipeline_shaped_violation(
        self: CsvExporter, columns: Any, **kwargs: Any
    ) -> list[str]:
        # spec §10 が禁じる「最も自然な書き方」そのもの: ブロック全体を
        # handle.lock で包んでから列を解決する。
        with handle.lock:
            return original_write_block_temp(self, columns, **kwargs)

    monkeypatch.setattr(CsvExporter, "_write_block_temp", pipeline_shaped_violation)

    with pytest.raises(
        AssertionError, match=r"handle\.lock を保持したまま resolve\(\) が呼ばれた"
    ):
        CsvExporter(block_cols=2).export(
            ExportRequest(
                keys=tuple(keys),
                output_path=tmp_path / "pipeline_violation_out.csv",
                options=CsvExportOptions(),
                header_resolver=list,
            ),
            probed,
        )
