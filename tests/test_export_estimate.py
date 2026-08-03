# ruff: noqa: RUF003
"""事前見積 (E-4b T-UX・spec §5.5 / B2) の正確値・推定値・D5 検査。

**demo_data に依存しない**: 合成 mf4 (tests.mdf4_helpers) で「複数レート」「幅広
2-D チャンネル」「CSV グループ」の 3 形すべてを踏める。demo_data/ は gitignore 済みで
CI に生成ステップが無く、そこへ置くと丸ごと skip される (E-4a T0 と同じ判断)。

このファイルの中心的な主張は 3 つ:
1. 見積は **値を 1 バイトも読まない** (spec §6 全タスク共通制約)。読むと「見積のために
   10 GB 読む」形になり、B2 が減らそうとしている待ちを見積自身が作る。
2. 読み項は **物理チャンネル単位** で数える。列単位で数えると幅 1,100 の
   チャンネルで 1,100 倍に膨れ、prod 全列の推定が 29 時間 (実測外挿 18.4 分の ~95 倍)
   になる = 見積が桁で嘘をつく。
3. 「正確値」と名乗る行数・空セル率が**実出力と一致する**。見積と書き手は
   ``timeline.py`` を共有するので、共有部の誤りは両者が同じだけずれて相互比較では
   隠れる — だから ``test_exact_counts_match_a_real_export`` は
   **手計算値 (10 行 / 0.4) ↔ 見積 ↔ 実ファイルの走査**を三点で突き合わせる。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tests.mdf4_helpers import CAN, write_mdf4, write_mdf4_wide_2d
from valisync.core.export.csv_exporter import CsvExportOptions
from valisync.core.export.estimate import (
    CONFIRM_THRESHOLD_S,
    TEMP_AMPLIFICATION,
    ExportEstimate,
    disk_shortfall,
    estimate_export,
)
from valisync.core.session import Session


def _two_rate_session(tmp_path: Path) -> tuple[Session, list[str]]:
    """10 ms と 100 ms の 2 チャンネル (master 2 本・union は 10 行)。

    fast: t = 0.00, 0.01, ... 0.09 (10 点) / slow: t = 0.00, 0.05 (2 点だが
    どちらも fast と **同一 float** なので union は 10 行)。**値ではなく時刻の
    重なりだけ**で空セル率が決まることを、手計算できる小ささで固定する。
    """
    path = tmp_path / "two_rate.mf4"
    write_mdf4(
        path,
        [
            {
                "name": "Fast",
                "bus_type": CAN,
                "timestamps": [round(i * 0.01, 4) for i in range(10)],
                "values": [float(i) for i in range(10)],
            },
            {
                "name": "Slow",
                "bus_type": CAN,
                "timestamps": [0.0, 0.05],
                "values": [100.0, 200.0],
            },
        ],
    )
    session = Session()
    key = session.load(path).key
    return session, [f"{key}::Fast", f"{key}::Slow"]


def _dense_session(tmp_path: Path) -> tuple[Session, list[str]]:
    """10 行 x 2 列で **空セルゼロ** (2 チャンネルが同一の 10 時刻を持つ)。

    ``_two_rate_session`` と **セル総数が同じ** (10 x 2 = 20) で非空セル数だけが
    違う (20 対 12) — 書き項の 2 項モデル (基礎項 x 全セル + 増分項 x 値セル) を
    「1 項 x 全セル」から区別できる形の 1 つ (**旧「唯一の形」という記述は
    Task 11 レビュー I1 で supersede** — 本 fixture は非空セル数も一緒に動くので
    BASE 項だけを孤立させられない。BASE 単独の識別は
    ``_sparse_with_extra_empty_channel_session`` を使う)。
    """
    path = tmp_path / "dense.mf4"
    stamps = [round(i * 0.01, 4) for i in range(10)]
    write_mdf4(
        path,
        [
            {
                "name": "A",
                "bus_type": CAN,
                "timestamps": stamps,
                "values": [float(i) for i in range(10)],
            },
            {
                "name": "B",
                "bus_type": CAN,
                "timestamps": stamps,
                "values": [float(i) * 2 for i in range(10)],
            },
        ],
    )
    session = Session()
    key = session.load(path).key
    return session, [f"{key}::A", f"{key}::B"]


def _sparse_with_extra_empty_channel_session(
    tmp_path: Path,
) -> tuple[Session, list[str]]:
    """``_two_rate_session`` に「選択窓の外にしか値を持たない」3 本目を足す。

    Task 11 レビュー I1 是正: 2 項モデルの **BASE 項だけ**を孤立させる fixture。
    ``Ghost`` の唯一のサンプルは選択窓 (呼び出し側が渡す
    ``time_start=0.0, time_end=0.09``) の外にあるので、union には入るが
    ``row_range`` のスライスで消え、Ghost が寄与する非空セルは常に 0
    (nonempty_cells は Fast/Slow だけの場合と厳密に同じ 12 のまま)。一方で
    Ghost は「選択された列」なので columns が +1 され、その列の 10 行ぶんが
    まるごと空セルとして total_cells に乗る (20 -> 30)。VALUE 項の母数を
    動かさずに BASE 項の母数だけを動かせる、唯一 (かつ最小) の形。
    """
    path = tmp_path / "sparse_ghost.mf4"
    write_mdf4(
        path,
        [
            {
                "name": "Fast",
                "bus_type": CAN,
                "timestamps": [round(i * 0.01, 4) for i in range(10)],
                "values": [float(i) for i in range(10)],
            },
            {
                "name": "Slow",
                "bus_type": CAN,
                "timestamps": [0.0, 0.05],
                "values": [100.0, 200.0],
            },
            {
                "name": "Ghost",
                "bus_type": CAN,
                "timestamps": [100.0],  # 選択窓 (0.0-0.09) の外 -> 常に非空セル 0
                "values": [1.0],
            },
        ],
    )
    session = Session()
    key = session.load(path).key
    return session, [f"{key}::Fast", f"{key}::Slow", f"{key}::Ghost"]


def _eager_csv_session(tmp_path: Path) -> tuple[Session, list[str]]:
    """CSV グループ 1 列 (EagerValues・``ColumnRecord`` を持たない唯一の形)。

    MDF 系 fixture (``_two_rate_session`` / ``_wide_session``) が踏まない
    ``SignalGroupManager.channel_master`` の **record-less 分岐** (信号名の線形
    走査) はここでしか通らない。
    """
    from valisync.core.models import Delimiter, FormatDefinition

    csv = tmp_path / "eager.csv"
    csv.write_text("t,A\n0.0,1.0\n1.0,2.0\n", encoding="utf-8")
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    session = Session()
    key = session.load(csv, fmt).key
    return session, [f"{key}::A"]


def test_rows_and_columns_are_exact(tmp_path: Path) -> None:
    """列数 = keys 長・行数 = union 長 (どちらも B2 の「正確値」)。"""
    session, keys = _two_rate_session(tmp_path)
    est = estimate_export(session, keys, CsvExportOptions())
    assert est.columns == 2
    # union = fast の 10 点 ∪ {0.00, 0.05}。どちらも fast 側と **同一 float** なので
    # 畳まれる (完全一致セマンティクス・tolerance 無し) -> 10 行。
    assert est.rows == 10


def test_empty_ratio_is_exact_from_searchsorted_hits(tmp_path: Path) -> None:
    """空セル率は推定でなく **正確値** (master の union への引き当てヒット数)。

    fast は 10 行すべてにヒット・slow は 0.00 と 0.05 の 2 行だけ。
    非空セル = 10 + 2 = 12 / 全セル = 10 行 x 2 列 = 20 -> 空セル率 0.4。
    """
    session, keys = _two_rate_session(tmp_path)
    est = estimate_export(session, keys, CsvExportOptions())
    assert est.empty_ratio == pytest.approx(0.4)


def test_exact_counts_match_a_real_export(tmp_path: Path) -> None:
    """**独立オラクル**: 「正確値」を実際に書かれたファイルの走査と突き合わせる。

    見積と書き手は ``timeline.py`` (``_align`` / ``union_timeline`` / ``row_range``)
    を共有しているので、共有部が壊れると両者が**同じだけ**ずれて相互比較は緑のまま
    になる。ここで比較相手にするのは出力ファイルそのもの (行を数え・空セルを数える)
    で、さらに **手計算値 (10 行 / 0.4)** を第 3 の独立点として同時に固定する
    — 3 点が揃わない限り緑にならない。
    """
    session, keys = _two_rate_session(tmp_path)
    opts = CsvExportOptions(use_unified_timeline=True)
    est = estimate_export(session, keys, opts)

    out = tmp_path / "real.csv"
    session.export_csv(keys, out, opts)
    lines = out.read_text(encoding="utf-8-sig").splitlines()
    data_rows = lines[1:]  # 先頭はヘッダ (単位行は無効)
    empty_cells = sum(
        1 for row in data_rows for cell in row.split(",")[1:] if cell == ""
    )
    actual_ratio = empty_cells / (len(data_rows) * est.columns)

    assert len(data_rows) == est.rows
    assert actual_ratio == pytest.approx(est.empty_ratio)
    # 第 3 の独立点 (手計算)。これが無いと、共有部の誤りで見積と出力が**揃って**
    # 間違ったときに上の 2 本が両方緑になる。
    assert len(data_rows) == 10
    assert actual_ratio == pytest.approx(0.4)


def _wide_session(tmp_path: Path, cols: int = 16) -> tuple[Session, list[str]]:
    """幅 *cols* の 2-D チャンネル 1 本 (**列キー**が鋳造対象になる唯一の形)。

    鋳造の主張を検定できるのはこの形だけ: スカラーチャンネル (``_two_rate_session``)
    のキーは namespaced マップに実在するので ``resolve_signal`` を呼んでも
    ``mint_count`` は 1 も動かない = 鋳造 assert が **vacuous** になる。
    """
    path = write_mdf4_wide_2d(tmp_path, cols=cols)
    session = Session()
    key = session.load(path).key
    names = session.column_names_of(key, "Wide")
    assert len(names) == cols, "fixture 前提: 幅 cols の 2-D チャンネル"
    return session, [f"{key}::{n}" for n in names]


def test_estimate_reads_no_values_and_mints_no_columns(tmp_path: Path) -> None:
    """値を読まない・鋳造もしない (spec §6 共通制約 / MG-1 の帳簿汚染回避)。

    ``LazyMdfValues.array`` を「呼ばれたら即失敗」に差し替えるので、見積のどこかが
    値へ触れた瞬間に AssertionError で落ちる (返り値を偽装しないのは、偽装すると
    「読んだが正しい答えが出た」で緑になるため)。

    **fixture は幅広 2-D** (``_wide_session`` の docstring 参照): スカラー
    チャンネルでは鋳造が起こりようがなく、鋳造 assert が空振りする。
    """
    from valisync.core.models import sample_source as ss

    session, keys = _wide_session(tmp_path)
    group_key = keys[0].split("::", 1)[0]
    mgr = session._groups
    before_mint = mgr.mint_count
    # **transient は別勘定** (Task 6 の MG-1)。`mint_count` だけを見ていると、
    # 見積が `resolve_signal_transient` で全列鋳造しても全緑で通る。
    before_transient = mgr.transient_mint_count
    before_resolved = mgr.resolved_keys(group_key)

    def boom(self: object) -> np.ndarray:
        raise AssertionError("見積が値を読んだ (spec §6 の禁止事項)")

    original = ss.LazyMdfValues.array
    ss.LazyMdfValues.array = boom  # type: ignore[method-assign]
    try:
        est = estimate_export(session, keys, CsvExportOptions())
    finally:
        ss.LazyMdfValues.array = original  # type: ignore[method-assign]

    assert est.rows == 3
    assert est.columns == 16
    assert mgr.mint_count == before_mint, "見積が列を鋳造した (LRU の枠を食う)"
    assert mgr.transient_mint_count == before_transient, (
        "見積が resolve_signal_transient 経由で列を鋳造した "
        "(帳簿は汚れないが 330k 本の一過性 Signal を作る)"
    )
    assert mgr.resolved_keys(group_key) == before_resolved


@pytest.mark.parametrize("shape", ["two_rate", "wide", "eager_csv"])
def test_estimate_never_calls_sorted_view(tmp_path: Path, shape: str) -> None:
    """``sorted_view()`` も呼ばない — ``array()`` の boom とは**別の口**。

    ``LazyMdfValues.array`` だけを塞ぐと、EagerValues (CSV/Derived) 側の
    ``sorted_view`` 経由の実体化が素通りする。加えて ``sorted_view`` は FU-20 の
    float64 値キャッシュを信号ごとに焼き付けるので、「読んだ」以上に「常駐を
    増やした」という別種の退行になる (memory:
    signal_range_via_sorted_view_materializes_float64_cache)。

    3 形すべてを踏むのは master 取得の経路が 3 本あるため:
    two_rate = 物理索引 / wide = 列 -> チャンネル解決 / **eager_csv =
    ``channel_master`` の record-less 走査**。3 本目は MDF の 2 形では構造的に
    到達不能で、しかも走査は ``Signal`` オブジェクトを掴むため、そこで
    ``sorted_view()`` に触れると EagerValues の値キャッシュが焼き付く
    (``array()`` の boom は EagerValues を通らないので**この経路には盲目**)。
    """
    from valisync.core.models import Signal

    builders = {
        "two_rate": _two_rate_session,
        "wide": _wide_session,
        "eager_csv": _eager_csv_session,
    }
    expected_rows = {"two_rate": 10, "wide": 3, "eager_csv": 2}
    session, keys = builders[shape](tmp_path)
    calls: list[str] = []
    original = Signal.sorted_view

    def spy(self: Signal) -> tuple[np.ndarray, np.ndarray]:
        calls.append(self.name)
        raise AssertionError(f"見積が sorted_view を呼んだ: {self.name}")

    Signal.sorted_view = spy  # type: ignore[method-assign]
    try:
        est = estimate_export(session, keys, CsvExportOptions())
    finally:
        Signal.sorted_view = original  # type: ignore[method-assign]
    assert calls == []
    assert est.rows == expected_rows[shape]


def test_read_term_counts_physical_channels_not_columns(tmp_path: Path) -> None:
    """読み項は **チャンネル単位**。幅 k の 2-D を全列選んでも 1 チャンネル分。

    E-4a 以降の読みは 1 select + k スライスなので、列単位で数えると k 倍の嘘になる。
    """
    session, keys = _wide_session(tmp_path)
    est_all = estimate_export(session, keys, CsvExportOptions())
    est_one = estimate_export(session, keys[:1], CsvExportOptions())

    # 16 列でも 1 列でも「読むチャンネル」は 1 本 -> 読み項は同じ。
    assert est_all.est_read_s == pytest.approx(est_one.est_read_s)
    assert est_all.est_read_s > 0.0
    # 書き項は列数に比例する (読み項と書き項が別勘定であることの positive control)。
    assert est_all.est_write_s > est_one.est_write_s


def test_eager_csv_group_contributes_no_read_time(tmp_path: Path) -> None:
    """CSV グループは既に実体化済み (EagerValues) — cold read は 0。

    ここを 0 にしないと、CSV だけを選んだ小さなエクスポートでも確認ダイアログが
    出て「5 秒かかります」と嘘をつく。
    """
    session, keys = _eager_csv_session(tmp_path)
    est = estimate_export(session, keys, CsvExportOptions())
    assert est.est_read_s == 0.0
    # rows が 0 にならないことが要点: CSV グループは ColumnRecord を持たないので
    # `channel_key_of` が None を返す。そこで諦めると「0 列 0 行」を提示する。
    assert est.rows == 2


def test_write_term_charges_empty_and_value_cells_differently(tmp_path: Path) -> None:
    """書き項は **2 項** (全セル基礎 + 値セル増分)。空セルは値セルより安い。

    ``_write_block_temp`` の行ループは空セルなら ``""`` を置くだけで、
    ``vals[i]`` の索引も repr も払わない。1 つの単価を全セルに掛けると
    **空セルの多い出力ほど過大**に見積もる — prod (セルの 66% が空) は顕著な例。

    2 つの fixture は **セル総数が同一** (20) で非空セル数だけが違う (12 対 20)。
    **旧「唯一の識別点」という記述は Task 11 レビュー I1 で supersede**:
    ``sparse.est_write_s > 0.0`` は sparse 自体が非空セルを 12 個持つため
    BASE=0 (1 項モデルへ縮退) でも成立してしまう vacuous な assert だった
    (レビュアーが ``estimate.py`` から ``total_cells * BASE`` の項を丸ごと
    削除して実証・43 件 green のまま)。BASE 項単独の識別は
    ``test_base_term_is_load_bearing_for_empty_only_columns`` が担う。
    """
    sparse_session, sparse_keys = _two_rate_session(tmp_path)
    dense_session, dense_keys = _dense_session(tmp_path)
    sparse = estimate_export(sparse_session, sparse_keys, CsvExportOptions())
    dense = estimate_export(dense_session, dense_keys, CsvExportOptions())

    assert sparse.rows * sparse.columns == dense.rows * dense.columns == 20
    assert sparse.empty_ratio == pytest.approx(0.4)
    assert dense.empty_ratio == pytest.approx(0.0)
    assert dense.est_write_s > sparse.est_write_s


def test_base_term_is_load_bearing_for_empty_only_columns(tmp_path: Path) -> None:
    """BASE 項単独の識別点 (Task 11 レビュー I1 是正)。

    ``_sparse_with_extra_empty_channel_session`` は非空セル数 (VALUE 項の母数)
    を厳密に固定したまま、選択窓の外にしか値を持たない列を 1 本追加して
    空セルだけを増やす (total_cells 20 -> 30・nonempty_cells は 12 のまま)。
    差分は BASE 項だけに帰属するので、``sabotage`` (BASE を 0 にする/削除する)
    が確実に検出される — 実装の内部定数と突き合わせる直接形にすることで、
    値そのものの取り違え (符号違い・桁違い) も同時に捕まえる。
    """
    import valisync.core.export.estimate as est_mod

    opts = CsvExportOptions(time_start=0.0, time_end=0.09)
    base_session, base_keys = _two_rate_session(tmp_path)
    ghost_session, ghost_keys = _sparse_with_extra_empty_channel_session(tmp_path)
    without_ghost = estimate_export(base_session, base_keys, opts)
    with_ghost = estimate_export(ghost_session, ghost_keys, opts)

    assert without_ghost.rows == with_ghost.rows == 10
    assert without_ghost.columns == 2
    assert with_ghost.columns == 3

    def _nonempty(est: ExportEstimate) -> float:
        return est.rows * est.columns * (1.0 - est.empty_ratio)

    # 非空セル数 (VALUE 項の母数) は不変 — Ghost は選択窓の外にしか値を
    # 持たないので、追加された列は非空セルを 1 つも持ち込まない。
    assert _nonempty(without_ghost) == pytest.approx(_nonempty(with_ghost))
    assert _nonempty(without_ghost) == pytest.approx(12.0)

    delta_write_s = with_ghost.est_write_s - without_ghost.est_write_s
    # 追加された 10 個の空セルぶんだけ増える — VALUE 項の寄与はゼロなので、
    # この差分は BASE 単価そのもの (符号・桁の取り違えもここで割れる)。
    assert delta_write_s == pytest.approx(10 * est_mod._WRITE_S_PER_CELL_BASE)
    assert delta_write_s > 0.0, "BASE が 0 (または負) — 2 項モデルが縮退している"


def test_read_term_uses_channel_class_specific_unit_cost(tmp_path: Path) -> None:
    """読み単価は scalar/wide でクラス分けされている (Task 11 レビュー C1 是正)。

    1 チャンネル 1 リーフ (scalar) と 1 チャンネル 16 リーフ (wide) を同じ
    単価で数えると、実測 ~480 倍差 (spike §9-4) のある実コストのどちらかで
    必ず桁が外れる。fixture ごとの読み項が対応するクラス定数と厳密に
    一致することを直接検定し、単一単価への回帰・クラス取り違え (scalar/wide
    が逆) の回帰の両方を検出する。
    """
    import valisync.core.export.estimate as est_mod

    scalar_session, scalar_keys = _two_rate_session(tmp_path)  # Fast, Slow は scalar
    wide_session, wide_keys = _wide_session(tmp_path)  # 1 物理チャンネル (16 リーフ)

    scalar_est = estimate_export(scalar_session, scalar_keys, CsvExportOptions())
    wide_est = estimate_export(wide_session, wide_keys, CsvExportOptions())

    assert scalar_est.est_read_s == pytest.approx(
        2 * est_mod._READ_S_PER_COLD_SCALAR_CHANNEL
    )
    assert wide_est.est_read_s == pytest.approx(est_mod._READ_S_PER_COLD_WIDE_CHANNEL)
    # sabotage 耐性: 定数を入れ替えたら (scalar/wide を逆にしたら) 必ずどちらかが割れる。
    assert (
        est_mod._READ_S_PER_COLD_SCALAR_CHANNEL != est_mod._READ_S_PER_COLD_WIDE_CHANNEL
    )


def test_channel_columns_hint_gives_the_identical_estimate(tmp_path: Path) -> None:
    """呼び出し側の {チャンネル: 列数} 表は **速い経路であって別の答えではない**。

    GUI (``ExportCsvDialog``) はこの表を渡して列 -> チャンネル解決を丸ごと飛ばす
    (prod 330,004 列で 2.6 s = GUI スレッドのフリーズ)。速い経路が僅かでも違う
    数字を出すと、B2 が「正確値」と名乗る行数/空セル率が**表示経路でだけ**
    ずれる — 突き合わせるのは 6 フィールド全部。
    """
    session, keys = _wide_session(tmp_path)
    group_key = keys[0].split("::", 1)[0]
    hint = {f"{group_key}::Wide": len(keys)}

    slow = estimate_export(session, keys, CsvExportOptions())
    fast = estimate_export(session, keys, CsvExportOptions(), channel_columns=hint)
    assert fast == slow


def test_channel_columns_hint_is_ignored_when_it_disagrees_with_keys(
    tmp_path: Path,
) -> None:
    """列数の合計が合わない表は**無視して解決し直す** (安全網)。

    表は呼び出し側の内部状態から来るので、選択とキー列の同期が崩れれば黙って
    ずれる。空セル率と行数は「正確値」として提示されるので、速い経路が疑わしい
    ときは遅くても正しい方を採る。空 dict (``ask`` を差し替えたテスト経路) も
    同じ検査で自然にフォールバックへ落ちる。
    """
    session, keys = _wide_session(tmp_path)
    group_key = keys[0].split("::", 1)[0]
    expected = estimate_export(session, keys, CsvExportOptions())

    for bogus in ({}, {f"{group_key}::Wide": 1}, {"gone_1::Nope": len(keys) + 5}):
        got = estimate_export(session, keys, CsvExportOptions(), channel_columns=bogus)
        assert got == expected, bogus


def test_channel_columns_hint_with_matching_sum_but_wrong_keys_falls_back(
    tmp_path: Path,
) -> None:
    """関連性の破れの安全網 (T8 再レビュー Minor 1)。

    総和の一致検査は「量」しか見ない — **総和が合っていてキーが誤っている**表は
    素通りし、`channel_master` が解決できない列が黙って消えて rows=0 の嘘を
    「正確値」として提示していた (レビュー実測)。step 2 で解決列数を数え、
    不足したらヒントを捨てて自己解決へ落ちることを固定する。
    """
    session, keys = _wide_session(tmp_path)
    expected = estimate_export(session, keys, CsvExportOptions())

    # 総和 == 列数 だがキーが実在しない (量は正しく関連が誤り)
    wrong_key_hint = {"gone_1::Nope": len(keys)}
    got = estimate_export(
        session, keys, CsvExportOptions(), channel_columns=wrong_key_hint
    )
    assert got == expected
    assert got.rows > 0  # 反 vacuous: フォールバックが本当に解決した


def test_time_range_narrows_rows_on_a_closed_interval(tmp_path: Path) -> None:
    """範囲は閉区間 (lo=left / hi=right — M-3)。境界サンプルは残る。"""
    session, keys = _two_rate_session(tmp_path)
    opts = CsvExportOptions(time_start=0.02, time_end=0.05)
    est = estimate_export(session, keys, opts)
    # 0.02 / 0.03 / 0.04 / 0.05 の 4 行 (両端を含む)。
    assert est.rows == 4


def test_empty_selection_is_all_zero_without_dividing_by_zero(tmp_path: Path) -> None:
    """0 列 / 0 行でも例外を出さない (確認ダイアログの手前で落ちない)。"""
    session, _keys = _two_rate_session(tmp_path)
    est = estimate_export(session, [], CsvExportOptions())
    assert est == ExportEstimate(
        columns=0, rows=0, empty_ratio=0.0, est_bytes=0, est_read_s=0.0, est_write_s=0.0
    )


def test_unresolvable_keys_do_not_crash_or_report_a_negative_ratio(
    tmp_path: Path,
) -> None:
    """アンロード済み / 未知キーは master を持たない — 率は [0, 1] に留まる。

    確認ダイアログは見積の**手前で落ちてはならない** (落ちると「エクスポートを
    押しても何も起きない」になる)。列数には数えるが非空セルには寄与しないので、
    空セル率は安全側 (過大) へ倒れる。
    """
    session, keys = _two_rate_session(tmp_path)
    est = estimate_export(session, [*keys, "gone_1::Nope"], CsvExportOptions())
    assert est.columns == 3
    assert est.rows == 10
    assert 0.0 <= est.empty_ratio <= 1.0


def test_disk_shortfall_requires_the_temp_amplification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D5 は **2.3 x 推定出力** を要求する (多段マージの中間 temp を含む・spec §5.3)。

    1.0 x で判定すると、出力ちょうどの空きしかないボリュームで最終 replace の直前に
    ENOSPC になり、B6 の「何も残さない」が「途中まで書かれた temp が残る」に degrade する。
    """
    import valisync.core.export.estimate as est_mod

    free_bytes = 1_000
    # 差し替えるのは **module 属性 `est_mod.shutil`** であって `shutil.disk_usage`
    # ではない。後者は素の shutil module オブジェクトを書き換える = テスト中
    # 他のあらゆる import 元 (asammdf の一時ファイル操作等) が偽物を掴む。
    monkeypatch.setattr(
        est_mod,
        "shutil",
        SimpleNamespace(
            disk_usage=lambda _p: SimpleNamespace(
                total=free_bytes, used=0, free=free_bytes
            )
        ),
    )
    # 2.3 x 500 = 1150 > 1000 -> 150 不足
    assert disk_shortfall(tmp_path / "out.csv", 500) == 150
    # 2.3 x 400 = 920 <= 1000 -> 足りている
    assert disk_shortfall(tmp_path / "out.csv", 400) == 0
    assert TEMP_AMPLIFICATION == 2.3


def test_disk_shortfall_passes_when_the_volume_cannot_be_probed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """検査不能 (OSError) は 0 = 通す。誤拒否は「書けるのに書けないアプリ」になる。"""
    import valisync.core.export.estimate as est_mod

    def blow(_p: str) -> object:
        raise OSError("probe failed")

    # 上と同じ理由で module 属性ごと差し替える (グローバル shutil を汚さない)。
    monkeypatch.setattr(est_mod, "shutil", SimpleNamespace(disk_usage=blow))
    assert disk_shortfall(tmp_path / "out.csv", 10**12) == 0


def test_confirm_threshold_is_time_based_not_size_based() -> None:
    """閾値は推定時間 (spec I10)。サイズで判定すると読み支配ケースが素通りする。

    「カーソル A-B x 全列」は出力 2,057 B・読み 6.5 s (spec §1 実測) — サイズ基準の
    どんな閾値でも下回るので、確認もキャンセル導線も出ないまま 6.5 秒フリーズする。
    """
    from valisync.gui.views.export_confirm import needs_confirmation

    tiny_but_slow = ExportEstimate(
        columns=330_004,
        rows=1,
        empty_ratio=0.66,
        est_bytes=2_057,
        est_read_s=6.5,
        est_write_s=0.2,
    )
    big_but_fast = ExportEstimate(
        columns=2,
        rows=10,
        empty_ratio=0.0,
        est_bytes=10_000_000_000,
        est_read_s=0.1,
        est_write_s=0.1,
    )
    assert needs_confirmation(tiny_but_slow) is True
    assert needs_confirmation(big_but_fast) is False
    assert CONFIRM_THRESHOLD_S == 5.0


@pytest.mark.parametrize(
    ("total_s", "expected"),
    [(4.999, False), (5.0, True), (5.001, True)],
)
def test_confirm_threshold_includes_its_boundary(
    total_s: float, expected: bool
) -> None:
    """閾値ちょうどは **確認する** 側 (``>=``)。

    3 点で挟むのは、`>` / `>=` の取り違えが片側 1 点の assert では検出できない
    ため — 4.999 だけを見ると `>` でも緑、5.001 だけを見ると `<` 以外はすべて緑。
    読み項と書き項の和で判定するので、片方に寄せて合計を作る。
    """
    from valisync.gui.views.export_confirm import needs_confirmation

    est = ExportEstimate(
        columns=2,
        rows=10,
        empty_ratio=0.0,
        est_bytes=100,
        est_read_s=total_s,
        est_write_s=0.0,
    )
    assert needs_confirmation(est) is expected
