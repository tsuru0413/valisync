"""多段マージと export() の最終形 (E-4b Task 7・spec §5.3)。

**FD 天井は本環境実測 8,189 本** (CPython 3.13.7 / Win11)。prod 3 ファイル比較の
全列エクスポートは block 数 ~8,253 で、単段の横マージは**確実に**天井を超える
(MG-2) — だから多段。
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import (
    _FLUSH_ROWS,
    _MERGE_FAN_IN,
    CsvExporter,
    CsvExportOptions,
    ExportCancelled,
    ExportRequest,
    merge_stage_count,
)
from valisync.core.models import Signal


def _sig(name: str, ts: list[float], vs: list[float], unit: str = "") -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="test",
        bus_type="",
        source_file="",
        metadata={"unit": unit} if unit else {},
    )


def _request(signals: list[Signal], out: Path, **opts: object) -> ExportRequest:
    return ExportRequest(
        keys=tuple(s.name for s in signals),
        output_path=out,
        options=CsvExportOptions(**opts),  # type: ignore[arg-type]
        header_resolver=list,
    )


def _resolve(signals: list[Signal]):  # type: ignore[no-untyped-def]
    table = {s.name: s for s in signals}
    return lambda key: table.get(key)


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8-sig").splitlines()


# ─── 段数の算術 ───────────────────────────────────────────────────────────────


def test_merge_stage_count_matches_the_prod_shape() -> None:
    """prod 3 ファイル全列 = block ~8,253 + 時刻 1 -> F=512 で 2 段 (MG-2)。

    先頭の assert は ``512`` を**直書き**する — ここが縛っているのは「prod 形が
    2 段で畳めること」であって「``_MERGE_FAN_IN`` が今いくつか」ではない。旧版は
    ``_MERGE_FAN_IN`` を象徴的に使いながら ``== 2`` という F=512 前提の具体値を
    混ぜていたため、定数を正当な理由で変える (例: FD 天井の再測定で 256 へ下げる)
    だけでここが意味不明に RED になっていた。残りの assert は fan-in に依存しない
    一般則なので symbolic のまま。
    """
    assert merge_stage_count(8254, 512) == 2
    assert merge_stage_count(_MERGE_FAN_IN, _MERGE_FAN_IN) == 1
    assert merge_stage_count(_MERGE_FAN_IN + 1, _MERGE_FAN_IN) == 2
    assert merge_stage_count(2, _MERGE_FAN_IN) == 1
    assert _MERGE_FAN_IN == 512, (
        "FD 天井 8,189 の実測が前提 (MG-2) — 再チューニングなら spec を読み直せ"
    )


def test_merge_stage_count_is_at_least_one() -> None:
    """入力 1 本でも 1 段走る (ヘッダ/単位行を書くのが最終段の役目)。"""
    assert merge_stage_count(1, _MERGE_FAN_IN) == 1


def test_merge_stage_count_refuses_a_fan_in_below_two() -> None:
    """``fan_in == 1`` は ``remaining`` が減らず**無限ループ**になる。

    ``plan_blocks`` の ``block_cols < 1`` ガードと同型で、``merge_fan_in`` が
    Task 7 で公開注入口になったからこそ到達しうる (`CsvExporter(merge_fan_in=1)`)。
    """
    for bad in (1, 0, -1):
        with pytest.raises(ValueError, match="fan-in"):
            merge_stage_count(4, bad)
    with pytest.raises(ValueError, match="merge_fan_in"):
        CsvExporter(merge_fan_in=1)


def test_block_cols_below_one_is_refused_at_construction() -> None:
    """``plan_blocks`` の無限ループガードと同じ理由を注入の瞬間に前倒しする。"""
    with pytest.raises(ValueError, match="block_cols"):
        CsvExporter(block_cols=0)


def test_merge_never_opens_more_than_fan_in_plus_one(tmp_path: Path) -> None:
    """同時 open の上界 = F + 1 (実測天井 8,189 に対し 1 桁の余裕)。"""
    n = 40
    signals = [_sig(f"s{i}", [0.0, 1.0], [float(i), float(i) + 0.5]) for i in range(n)]
    out = tmp_path / "o.csv"
    opened: list[int] = []
    live = 0

    import builtins

    original = builtins.open

    def counting_open(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal live
        handle = original(*args, **kwargs)
        live += 1
        opened.append(live)
        close = handle.close

        def wrapped_close() -> None:
            nonlocal live
            live -= 1
            close()

        handle.close = wrapped_close  # type: ignore[method-assign]
        return handle

    builtins.open = counting_open  # type: ignore[assignment]
    try:
        CsvExporter(block_cols=1, merge_fan_in=4).export(
            _request(signals, out), _resolve(signals)
        )
    finally:
        builtins.open = original  # type: ignore[assignment]
    # 反 vacuous: 実際に F+1 まで開いている (上界だけだと「1 本も開かない実装」で緑)。
    assert max(opened) == 4 + 1, opened
    assert len(_read(out)) == 3  # header + 2 rows


# ─── 行数一致 assert (MG-6) ───────────────────────────────────────────────────


def test_merge_loud_fails_when_an_input_has_fewer_rows(tmp_path: Path) -> None:
    """ブロック writer のバグ (行数のずれ) を黙って横に繋がない。

    ずれたまま繋ぐと、ある列から先が **1 行ずれた別の時刻の値**になる —
    例外も長さ検証も出ないサイレント誤データ。
    """
    exporter = CsvExporter()
    a = tmp_path / "a.tmp"
    b = tmp_path / "b.tmp"
    a.write_text("1\n2\n3\n", encoding="utf-8")
    b.write_text("4\n5\n", encoding="utf-8")  # 1 行少ない
    with pytest.raises(ValueError, match="行数が一致しません"):
        exporter._merge_one_stage(
            [a, b],
            merged_path=tmp_path / "merged.tmp",
            stage=0,
            prefix_lines=(),
            opts=CsvExportOptions(),
            cancel=None,
        )


def test_merge_loud_fails_when_an_input_has_more_rows(tmp_path: Path) -> None:
    exporter = CsvExporter()
    a = tmp_path / "a.tmp"
    b = tmp_path / "b.tmp"
    a.write_text("1\n2\n", encoding="utf-8")
    b.write_text("4\n5\n6\n", encoding="utf-8")
    with pytest.raises(ValueError, match="行数が一致しません"):
        exporter._merge_one_stage(
            [a, b],
            merged_path=tmp_path / "merged.tmp",
            stage=0,
            prefix_lines=(),
            opts=CsvExportOptions(),
            cancel=None,
        )


def test_merge_row_mismatch_is_detected_past_the_flush_chunk(tmp_path: Path) -> None:
    """行数のずれを **バッファ 1 チャンクより先** でも検出する。

    ゴールデンは最大 57 行で、``_FLUSH_ROWS`` (1,024) を 1 度も跨がない。
    ずれの検出をチャンク単位の長さ比較で実装すると、短い fixture では緑のまま
    prod (12,012 行) だけで壊れる — 実データ規模でしか出ない類の穴なので、
    ここだけは >1 チャンクの入力で駆動する。
    """
    n = _FLUSH_ROWS * 2 + 7
    a = tmp_path / "a.tmp"
    b = tmp_path / "b.tmp"
    a.write_text("".join(f"{i}\n" for i in range(n)), encoding="utf-8")
    b.write_text("".join(f"{i}\n" for i in range(n - 1)), encoding="utf-8")
    with pytest.raises(ValueError, match="行数が一致しません"):
        CsvExporter()._merge_one_stage(
            [a, b],
            merged_path=tmp_path / "merged.tmp",
            stage=0,
            prefix_lines=(),
            opts=CsvExportOptions(),
            cancel=None,
        )


def test_merge_writes_every_row_across_flush_chunks(tmp_path: Path) -> None:
    """反対側 (健全な経路): チャンク境界で行を落とさない・重複させない。

    ``_FLUSH_ROWS`` の倍数ちょうどでない行数を選ぶ (末尾の端数 buf を書き忘れる
    実装がここで RED になる)。
    """
    n = _FLUSH_ROWS * 2 + 7
    signals = [
        _sig("a", list(map(float, range(n))), [float(i) for i in range(n)]),
        _sig("b", list(map(float, range(n))), [float(i) * 2 for i in range(n)]),
    ]
    out = tmp_path / "big.csv"
    CsvExporter(block_cols=1, merge_fan_in=2).export(
        _request(signals, out), _resolve(signals)
    )
    lines = _read(out)
    assert len(lines) == n + 1  # header + n rows
    # 全行の内容そのものを assert する (4 点スポットチェックだと、正味の行数が
    # 変わらない「1 行落として別の 1 行を複製する」変異に盲目になる)。
    assert lines == ["timestamp,a,b"] + [
        f"{float(i)},{float(i)},{float(i * 2)}" for i in range(n)
    ]


# ─── 出力の形 ─────────────────────────────────────────────────────────────────


def test_multi_stage_merge_produces_the_same_file_as_single_stage(
    tmp_path: Path,
) -> None:
    signals = [
        _sig(f"s{i}", [0.0, 1.0, 2.0], [float(i), float(i), float(i)]) for i in range(9)
    ]
    wide = tmp_path / "wide.csv"
    deep = tmp_path / "deep.csv"
    CsvExporter(block_cols=9, merge_fan_in=512).export(
        _request(signals, wide), _resolve(signals)
    )
    CsvExporter(block_cols=1, merge_fan_in=2).export(
        _request(signals, deep), _resolve(signals)
    )
    assert wide.read_bytes() == deep.read_bytes()
    # 反 vacuous: deep 側は実際に多段 (9 列 + 時刻 = 10 本 -> F=2 で 4 段)。
    assert merge_stage_count(10, 2) == 4


def test_unit_row_comes_from_the_sideband_not_a_second_resolve(
    tmp_path: Path,
) -> None:
    """マージ段での再 resolve は禁止 (330k 再解決 = ~390 MB の一撃・MG-4)。"""
    a = _sig("a", [0.0], [1.0], unit="km/h")
    b = _sig("b", [0.0], [2.0], unit="rpm")
    out = tmp_path / "o.csv"
    calls: list[str] = []
    table = {"a": a, "b": b}

    def resolve(key: str) -> Signal | None:
        calls.append(key)
        return table.get(key)

    CsvExporter(block_cols=1).export(_request([a, b], out, unit_row=True), resolve)
    assert _read(out) == ["timestamp,a,b", "s,km/h,rpm", "0.0,1.0,2.0"]
    # 前走査 (scan_masters) 1 回 + ブロック 1 回 = 列あたり 2 回。マージ段で
    # 3 回目が出たら再 resolve が入っている。
    assert calls.count("a") == 2 and calls.count("b") == 2


def test_shared_timeline_accepts_identically_non_monotonic_masters(
    tmp_path: Path,
) -> None:
    """共有 TL の前提検証は ``canonical_master`` 同士で比べる (生 master ではない)。

    旧実装は ``sorted_view()[0]`` 同士を比べていた。値を読まない検証へ移すときに
    **生 master のまま**比べると、「非単調だが整列すれば同一」の 2 本 (CAN の
    再送で順序が入れ替わった実データの形) を誤って拒否する。既存の非単調テストは
    **単一信号**なので比較が 0 回になり、この退行に構造的に盲目 —
    2 本必要なのはそのため。
    """
    a = _sig("a", [0.0, 2.0, 1.0], [10.0, 30.0, 20.0])
    b = _sig("b", [1.0, 0.0, 2.0], [11.0, 31.0, 21.0])
    out = tmp_path / "o.csv"
    CsvExporter().export(_request([a, b], out), _resolve([a, b]))
    assert _read(out) == [
        "timestamp,a,b",
        "0.0,10.0,31.0",
        "1.0,20.0,11.0",
        "2.0,30.0,21.0",
    ]


def test_header_is_resolved_before_any_temp_is_written(tmp_path: Path) -> None:
    """ヘッダ解決と長さ検査は **temp を 1 バイトも書く前** (C-5 の位置契約)。

    S13 サボタージュ (解決を全ブロックの後ろへ移す) の実測 RED は **0 件**
    だった — ``test_header_resolver_length_mismatch_fails_loudly`` の
    ``assert not out.exists()`` は、後ろへ下げても finally が temp を消すので
    緑のままになる。位置は**出力の契約ではなく perf/B6 の契約** (prod では
    全ブロックを書き切ってから落ちる = ~18 分の無駄 + temp 生成) なので、
    出力ではなく「解決が呼ばれた時点で temp が 0 本」を直接見る。
    """
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    b = _sig("b", [0.0, 1.0], [3.0, 4.0])
    out = tmp_path / "o.csv"
    temps_at_resolve: list[int] = []

    def header_resolver(keys):  # type: ignore[no-untyped-def]
        temps_at_resolve.append(
            len([p for p in tmp_path.iterdir() if p.name.startswith(".tmp_export_")])
        )
        return list(keys)

    CsvExporter(block_cols=1, merge_fan_in=2).export(
        ExportRequest(
            keys=("a", "b"),
            output_path=out,
            options=CsvExportOptions(),
            header_resolver=header_resolver,
        ),
        _resolve([a, b]),
    )
    assert temps_at_resolve == [0], temps_at_resolve
    # 反 vacuous: 健全な経路では temp が実際に作られる (0 本のまま終わる実装なら
    # 上の assert は何も言っていない)。ここは「作られたが解決より後」を示す。
    assert _read(out) == ["timestamp,a,b", "0.0,1.0,3.0", "1.0,2.0,4.0"]


def test_export_leaves_no_temp_files_on_success(tmp_path: Path) -> None:
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    out = tmp_path / "o.csv"
    CsvExporter(block_cols=1, merge_fan_in=2).export(_request([a], out), _resolve([a]))
    assert [p.name for p in tmp_path.iterdir()] == ["o.csv"]


def test_cancel_removes_every_temp_and_leaves_no_output(tmp_path: Path) -> None:
    """G6: 「temp が一度は存在した」ことを観測してから消滅を assert する。"""
    signals = [
        _sig(f"s{i}", np.arange(50.0).tolist(), np.arange(50.0).tolist())
        for i in range(8)
    ]
    out = tmp_path / "o.csv"
    cancel = threading.Event()
    saw_temp: list[int] = []

    def progress(done: int, total: int) -> None:
        del total
        saw_temp.append(len([p for p in tmp_path.iterdir() if p.name != "o.csv"]))
        if done >= 2:
            cancel.set()

    with pytest.raises(ExportCancelled):
        CsvExporter(block_cols=1).export(
            _request(signals, out), _resolve(signals), progress=progress, cancel=cancel
        )
    assert max(saw_temp) > 0, "temp が一度も存在していない (上界 0 の空虚形)"
    assert list(tmp_path.iterdir()) == []


def test_cancel_during_the_merge_stage_also_leaves_nothing(tmp_path: Path) -> None:
    """マージ段で中断しても同じ (掃除役は export() の finally 1 か所だけ)。

    ブロック段だけを見ると、マージ器が自分の出力 temp を temps へ登録し忘れる
    退行 (中間 temp だけが残る形) に盲目になる。
    """
    signals = [_sig(f"s{i}", [0.0, 1.0], [1.0, 2.0]) for i in range(4)]
    out = tmp_path / "o.csv"
    cancel = threading.Event()
    saw_temp: list[int] = []

    def progress(done: int, total: int) -> None:
        saw_temp.append(len([p for p in tmp_path.iterdir() if p.name != "o.csv"]))
        # 時刻 1 + ブロック 4 = 5 単位を過ぎた後 = 最初のマージ段の直後。
        if done > 5:
            cancel.set()
        del total

    with pytest.raises(ExportCancelled):
        CsvExporter(block_cols=1, merge_fan_in=2).export(
            _request(signals, out), _resolve(signals), progress=progress, cancel=cancel
        )
    assert max(saw_temp) > 0
    assert list(tmp_path.iterdir()) == []


def test_disk_space_shortage_is_rejected_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D5: 2.3 x 推定出力を満たさないなら開始しない。"""
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    out = tmp_path / "o.csv"
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(0, 0, 0)
    )
    with pytest.raises(ValueError, match="空き容量"):
        CsvExporter().export(_request([a], out), _resolve([a]))
    assert list(tmp_path.iterdir()) == []


# ─── 段数算術の防御 (S15) ───────────────────────────────────────────────────────


def test_stage_arithmetic_mismatch_is_loud_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``merge_stage_count`` の算術と実マージループがずれたら、列を落とした
    ファイルを黙って出さない (:667-671 の ``len(current) != 1`` ガード)。

    ``merge_stage_count`` を過小な段数へ差し替えると、マージのステージ数
    ループが ``current`` を 1 本まで畳み切れずに終わる。ガードが無いと
    ``current[0]`` (=一部の temp しか畳んでいない・列を落としたファイル) が
    そのまま ``os.replace`` で最終ファイルへ化ける — 例外も長さ検証も出ない
    サイレント列欠損。到達させる入力を作れない (算術は正しいので) ため
    ``merge_stage_count`` そのものを monkeypatch で嘘つきにする。
    """
    from valisync.core.export import csv_exporter

    signals = [_sig(f"s{i}", [0.0, 1.0], [1.0, 2.0]) for i in range(4)]
    out = tmp_path / "o.csv"
    monkeypatch.setattr(csv_exporter, "merge_stage_count", lambda _n, _f: 1)  # 過小
    with pytest.raises(ValueError, match="マージ段数の算術"):
        CsvExporter(block_cols=1, merge_fan_in=2).export(
            _request(signals, out), _resolve(signals)
        )
    assert list(tmp_path.iterdir()) == []


# ─── progress ─────────────────────────────────────────────────────────────────


def test_progress_units_are_blocks_plus_merge_stages(tmp_path: Path) -> None:
    signals = [_sig(f"s{i}", [0.0, 1.0], [1.0, 2.0]) for i in range(4)]
    out = tmp_path / "o.csv"
    seen: list[tuple[int, int]] = []
    CsvExporter(block_cols=1, merge_fan_in=2).export(
        _request(signals, out),
        _resolve(signals),
        # `progress=seen.append` は書けない — 契約は 2 引数 `(done, total)` で、
        # `list.append` は 1 引数しか取らない (TypeError)。
        progress=lambda done, total: seen.append((done, total)),
    )
    total = seen[0][1]
    # 時刻 temp 1 + ブロック 4 = 5 本 -> F=2 なら 3 段
    assert total == 1 + 4 + 3
    assert [d for d, _t in seen] == list(range(1, total + 1))


def test_progress_total_is_stable_across_the_whole_run(tmp_path: Path) -> None:
    """分母が途中で動くと GUI のバーが巻き戻る (T-UX の前提)。"""
    signals = [_sig(f"s{i}", [0.0, 1.0], [1.0, 2.0]) for i in range(5)]
    out = tmp_path / "o.csv"
    seen: list[tuple[int, int]] = []
    CsvExporter(block_cols=2, merge_fan_in=3).export(
        _request(signals, out),
        _resolve(signals),
        progress=lambda done, total: seen.append((done, total)),
    )
    assert len({t for _d, t in seen}) == 1, seen


# ─── オフスレッド性 (G7 の core 側の半分) ─────────────────────────────────────


def test_export_runs_entirely_on_the_calling_thread(tmp_path: Path) -> None:
    """core は自分でスレッドを起こさない (worker 側の責務・部分並列化の検出)。"""
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    out = tmp_path / "o.csv"
    threads: set[int] = set()

    def resolve(key: str) -> Signal | None:
        threads.add(threading.get_ident())
        return a if key == "a" else None

    CsvExporter().export(_request([a], out), resolve)
    assert threads == {threading.get_ident()}


# ─── 橋の撤去 (legacy 形が同じパイプラインへ落ちること) ───────────────────────


def test_legacy_form_goes_through_the_same_block_pipeline(tmp_path: Path) -> None:
    """legacy 形 (`export(signals, path, ...)`) も列ブロックを通る。

    旧一括実装を legacy にだけ残すと ``dict(zip(...tolist()))`` (実測
    97 B/サンプル) がそこに生き残り、既存 40 サイトが全部緑のままそこを通り
    続ける。**橋の撤去はテストで検出しにくい** (出力バイトは同じ) ので、
    「ブロック計画が実際に呼ばれた」ことを直接観測する。
    """
    from valisync.core.export import csv_exporter

    seen: list[tuple[tuple[int, int], ...]] = []
    original = csv_exporter.plan_blocks

    def spy(runs, block_cols):  # type: ignore[no-untyped-def]
        blocks = original(runs, block_cols)
        seen.append(blocks)
        return blocks

    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    b = _sig("b", [0.0, 1.0], [3.0, 4.0])
    out = tmp_path / "legacy.csv"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(csv_exporter, "plan_blocks", spy)
        CsvExporter(block_cols=1).export([a, b], out)

    assert seen == [((0, 1), (1, 2))], seen
    assert _read(out) == ["timestamp,a,b", "0.0,1.0,3.0", "1.0,2.0,4.0"]


def test_legacy_form_keeps_duplicate_signal_names_as_separate_columns(
    tmp_path: Path,
) -> None:
    """同名 Signal 2 本が dict で潰れない (キーは名前でなく**位置**)。

    legacy 形は Signal のリストなので同名が来うる (Derived を 2 本作れば到達)。
    キーを ``sig.name`` にすると片方が消え、ヘッダは 2 列・データは 1 列という
    ずれた CSV になる — E-4b が根治しようとしている失敗そのもの。
    """
    a = _sig("dup", [0.0, 1.0], [1.0, 2.0])
    b = _sig("dup", [0.0, 1.0], [3.0, 4.0])
    out = tmp_path / "dup.csv"
    CsvExporter(block_cols=1).export([a, b], out)
    assert _read(out) == ["timestamp,dup,dup", "0.0,1.0,3.0", "1.0,2.0,4.0"]


def test_legacy_header_names_length_mismatch_fails_loudly(tmp_path: Path) -> None:
    """legacy 形の ``header_names`` にも C-5 のヘッダ長検査がかかる。

    旧 ``_header_rows`` は長さを検査せず、``header_names`` が短ければヘッダだけ
    列数が足りない CSV を黙って書いていた。legacy 形を同じパイプラインへ落とした
    副産物としてこの穴が閉じる (**強化であって退行ではない** — 既存 19 本は
    すべて長さ一致で呼んでおり無回帰)。
    """
    a = _sig("a", [0.0], [1.0])
    b = _sig("b", [0.0], [2.0])
    out = tmp_path / "bad.csv"
    with pytest.raises(ValueError, match="ヘッダ"):
        CsvExporter().export(
            [a, b], out, options=CsvExportOptions(header_names=("only-one",))
        )
    assert not out.exists()


def test_export_request_form_refuses_a_path_as_resolve(tmp_path: Path) -> None:
    """2 形 dispatch の取り違え (request 形に出力パスを渡す) を黙って進めない。"""
    a = _sig("a", [0.0], [1.0])
    with pytest.raises(TypeError, match="resolve"):
        CsvExporter().export(_request([a], tmp_path / "o.csv"), tmp_path / "o.csv")  # type: ignore[arg-type]


def test_legacy_form_refuses_a_resolver_as_output_path(tmp_path: Path) -> None:
    a = _sig("a", [0.0], [1.0])
    with pytest.raises(TypeError, match="出力パス"):
        CsvExporter().export([a], _resolve([a]))  # type: ignore[arg-type]
