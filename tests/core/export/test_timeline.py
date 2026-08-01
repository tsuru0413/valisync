"""union 合成と列引き当ての純関数 (E-4b Task 5・spec §5.4)。

**demo_data に依存しない**: 判定はすべて合成 ndarray と手組み Signal で踏める。
本モジュールの時点で production 配線は 0 件 (Task 6/7 が配線する) なので、
ここが唯一の執行点であり、緑であることが「実装が効いている」の唯一の根拠になる。
"""

from __future__ import annotations

import numpy as np
import pytest

from valisync.core.export.csv_exporter import CsvExportOptions, _in_range
from valisync.core.export.timeline import (
    canonical_master,
    column_on_union,
    hit_mask,
    row_range,
    union_timeline,
)
from valisync.core.models import Signal


def _sig(name: str, ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="test",
        bus_type="",
        source_file="",
    )


def _spy_concat_sizes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """``np.concatenate`` の**入力要素数**を記録する (dedup の下界オラクル)。

    結果配列だけを見ると dedup の有無で同じ union になるため、値ベースの assert は
    dedup を消しても緑のまま通る。畳んだことを観測できる唯一の場所が入力側。
    """
    sizes: list[int] = []
    real = np.concatenate

    def spy(arrays, *args, **kwargs):  # type: ignore[no-untyped-def]
        sizes.append(sum(len(a) for a in arrays))
        return real(arrays, *args, **kwargs)

    monkeypatch.setattr(np, "concatenate", spy)
    return sizes


# ─── union: identity dedup (spec §5.4) ────────────────────────────────────────


def test_union_dedups_the_same_master_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """prod 形: 1 つの master オブジェクトを全列が共有する (loader が同一物を渡す)。

    **下界オラクル** [I11]: 結果だけを見ると dedup 有無で同じ配列になるので、
    dedup を消しても値ベースの assert は緑のまま通る。concat の**入力要素数**を
    直接観測して「畳んだこと」を性能側で pin する。
    """
    master = np.arange(1000, dtype=np.float64)
    concat_sizes = _spy_concat_sizes(monkeypatch)

    out = union_timeline([master] * 64)

    assert concat_sizes == [1000], "dedup が効いていない (64 本ぶん concat した)"
    assert np.array_equal(out, master)


def test_union_of_distinct_objects_with_equal_values_is_correct_but_not_deduped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """安全側の逸脱: identity dedup は「別オブジェクト・同値」を畳まない。

    畳まれないのは**コストだけ**で、結果は正しい。ここを値比較 (array_equal) に
    「改善」すると ULP 差の行が黙って畳まれ、時刻がずれる (C3)。
    """
    a = np.arange(1000, dtype=np.float64)
    b = np.arange(1000, dtype=np.float64)  # 同値・別オブジェクト
    assert a is not b
    concat_sizes = _spy_concat_sizes(monkeypatch)

    out = union_timeline([a, b])

    assert concat_sizes == [2000]  # 畳まれない (identity が違う)
    assert np.array_equal(out, a)  # 正しさは保たれる


def test_union_is_sorted_unique_across_multi_rate_masters() -> None:
    slow = np.array([0.0, 2.0, 4.0])
    fast = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    out = union_timeline([slow, fast])
    assert out.tolist() == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_union_of_no_masters_is_empty_not_valueerror() -> None:
    """空選択 (列 0 本)。np.concatenate([]) は ValueError なので先に返す。"""
    out = union_timeline([])
    assert out.shape == (0,)
    assert out.dtype == np.float64


def test_union_result_is_read_only() -> None:
    out = union_timeline([np.arange(3, dtype=np.float64)])
    assert out.flags.writeable is False


def test_union_does_not_freeze_the_caller_master() -> None:
    """凍結するのは union の結果だけ (入力 master を巻き添えにしない)。

    単一 master の経路で ``np.unique`` が入力をそのまま返す実装に変わると、
    呼び出し側の配列が黙って read-only 化し、無関係な書き込みが ValueError で
    落ちる (loader/GUI 側の master は共有物なので影響範囲が広い)。
    """
    # 昇順・一意 = 短絡最適化が「そのまま返す」形。非単調 fixture だと
    # 短絡が絶対に取らない形なので、guarded aliasing 実装 (concat 後に
    # array_equal で入力へ差し替える) が 27 passed 全盲になる (レビュー実測)。
    master = np.arange(5.0)
    union_timeline([master])
    assert master.flags.writeable is True


def test_union_from_raw_masters_equals_union_from_sorted_views() -> None:
    """**Task 7 の等価性の要**: union を生 master から作ってよい根拠。

    旧実装は ``sorted_view()`` の時刻軸から union を作っていた (= 全列の値を
    実体化してから union を出す)。生 master から作れないと、見積 (T-UX) の
    「値を読まない」契約も、ブロック開始前の union 確定も成り立たない。
    非単調・重複 ts を含む形で**同値であること**をここで pin する。
    """
    a = _sig("a", [0.0, 2.0, 1.0], [10.0, 30.0, 20.0])  # 非単調
    b = _sig("b", [1.0, 1.0, 3.0], [1.0, 2.0, 3.0])  # 重複 ts
    from_raw = union_timeline([a.timestamps, b.timestamps])
    from_views = np.unique(np.concatenate([a.sorted_view()[0], b.sorted_view()[0]]))
    assert np.array_equal(from_raw, from_views)


# ─── canonical_master ─────────────────────────────────────────────────────────


def test_canonical_master_returns_the_same_object_when_monotonic() -> None:
    """同一オブジェクトを返すこと自体が契約 (identity dedup の前提条件)。"""
    m = np.arange(5, dtype=np.float64)
    assert canonical_master(m) is m


def test_canonical_master_matches_sorted_view_ts_for_non_monotonic_and_dups() -> None:
    s = _sig("x", [0.0, 2.0, 1.0, 1.0], [10.0, 30.0, 20.0, 21.0])
    assert np.array_equal(canonical_master(s.timestamps), s.sorted_view()[0])


def test_canonical_master_preserves_identity_dedup_in_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**合成の pin**: canonical 化した後でも union の identity dedup が効く。

    prod の呼び出し順は「各列の master を canonical 化 -> union」なので、
    ``canonical_master`` が単調入力に対して新配列を返すようになった瞬間、
    dedup は 1 件も効かなくなる (330,004 列ぶんの concat が復活する)。
    2 つの単体テストがどちらも緑のまま dedup が死ぬので、合成でだけ検出できる。
    """
    master = np.arange(1000, dtype=np.float64)
    concat_sizes = _spy_concat_sizes(monkeypatch)

    union_timeline([canonical_master(master) for _ in range(64)])

    assert concat_sizes == [1000], "canonical_master が identity を壊している"


# ─── column_on_union: 完全一致セマンティクス ──────────────────────────────────


def test_column_on_union_matches_only_exact_timestamps() -> None:
    """既存 test-lock ``"1.0,,21.0"`` (test_csv_export_options.py:284) と同じ形。"""
    union = np.array([0.0, 1.0, 2.0, 3.0])
    a_ts, a_vs = np.array([0.0, 2.0]), np.array([10.0, 12.0])
    b_ts, b_vs = np.array([1.0, 3.0]), np.array([21.0, 23.0])

    a_vals, a_present = column_on_union(a_ts, a_vs, union)
    b_vals, b_present = column_on_union(b_ts, b_vs, union)

    assert a_present.tolist() == [True, False, True, False]
    assert b_present.tolist() == [False, True, False, True]
    assert a_vals[0] == 10.0 and a_vals[2] == 12.0
    assert b_vals[1] == 21.0 and b_vals[3] == 23.0


def test_column_on_union_tail_overrun_is_absent_not_indexerror() -> None:
    """union の末尾が信号の末尾より後 (既存 test-lock "2.0,3.0," の形)。

    素朴な ``sig_ts[idx]`` は ``idx == len(sig_ts)`` で IndexError。
    """
    union = np.array([0.0, 1.0, 2.0])
    vals, present = column_on_union(np.array([0.0, 1.0]), np.array([4.0, 5.0]), union)
    assert present.tolist() == [True, True, False]
    assert vals[0] == 4.0 and vals[1] == 5.0


def test_column_on_union_head_underrun_is_absent() -> None:
    """union の先頭が信号の先頭より前 (clip の下側・idx == 0 の腕)。"""
    union = np.array([0.0, 5.0])
    _vals, present = column_on_union(np.array([5.0]), np.array([1.0]), union)
    assert present.tolist() == [False, True]


def test_column_on_union_of_zero_length_signal_is_all_absent() -> None:
    """LD-09 (ヘッダのみ CSV = データ行 0)。素朴実装は IndexError [M-4]。"""
    union = np.array([0.0, 1.0, 2.0])
    vals, present = column_on_union(
        np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64), union
    )
    assert present.tolist() == [False, False, False]
    assert len(vals) == 3  # 行数は union に揃う (下流の索引が壊れない)


def test_column_on_union_of_empty_union_is_empty() -> None:
    vals, present = column_on_union(np.array([0.0]), np.array([1.0]), np.empty(0))
    assert len(vals) == 0 and len(present) == 0


def test_column_on_union_outputs_are_read_only() -> None:
    vals, present = column_on_union(
        np.array([0.0]), np.array([1.0]), np.array([0.0, 1.0])
    )
    assert vals.flags.writeable is False
    assert present.flags.writeable is False


def test_column_on_union_ulp_split_rows() -> None:
    """ULP 分裂 (spec §1・C-1 で既知の不完全性として受容)。

    100 ms 刻みと 10 ms 刻みは「同じ 0.3 秒」を別のビット列で作る:
    ``3*0.1 == 0.30000000000000004`` / ``30*0.01 == 0.3``。tolerance を入れない
    限り union は分裂する。**分裂の行数まで凍結する** — 「union が 120 行に
    なった」ら誰かが tolerance を入れたということ。
    """
    slow_ts = np.array([i * 0.1 for i in range(12)], dtype=np.float64)
    fast_ts = np.array([i * 0.01 for i in range(120)], dtype=np.float64)
    union = union_timeline([slow_ts, fast_ts])

    assert len(union) == 122  # 120 ではない (2 点が ULP で分裂している)

    _sv, slow_present = column_on_union(slow_ts, slow_ts.copy(), union)
    _fv, fast_present = column_on_union(fast_ts, fast_ts.copy(), union)
    assert int(slow_present.sum()) == 12
    assert int(fast_present.sum()) == 120
    assert int((slow_present & fast_present).sum()) == 10  # 一致するのは 10 点だけ
    assert int((~slow_present & ~fast_present).sum()) == 0  # 全空の行は無い
    split = [
        t for t, p in zip(union.tolist(), fast_present.tolist(), strict=True) if not p
    ]
    assert split == [0.30000000000000004, 0.6000000000000001]


# ─── hit_mask: 見積と出力が同じ存在判定を共有する ─────────────────────────────


def test_hit_mask_agrees_with_column_on_union_presence() -> None:
    """**T-UX (見積) と書き手が同じ答えを出す**ことの pin。

    ずれると B2 が提示する空セル率が「正確値」でなくなる (見積は 2 割空だと
    言い、出力は 6 割空、という形の嘘)。存在判定の実装が 2 つに割れたときの
    唯一の検出点なので、境界 (先頭 underrun・末尾 overrun・len 0) を全部通す。

    **恒真化の回避**: 現在の実装では両者が private ``_align`` を共有するので、
    「hit_mask == present」だけを見る assert は実装が何を返しても通る。第三の
    **独立オラクル** (searchsorted を通さない素朴なメンバシップ判定と、旧実装
    ``dict(zip(ts.tolist(), vs.tolist()))`` 相当の値引き当て) を置いて、共有された
    その 1 本が**正しい**ことまで固定する。
    """
    union = np.array([0.0, 1.0, 2.0, 3.0])
    for sig_ts in (
        np.array([0.0, 2.0]),
        np.array([1.0, 3.0]),
        np.array([5.0]),  # 全部範囲外
        np.empty(0, dtype=np.float64),  # len 0 (LD-09)
    ):
        vals = np.arange(len(sig_ts), dtype=np.float64) + 10.0
        oracle = dict(zip(sig_ts.tolist(), vals.tolist(), strict=True))
        expected = [t in oracle for t in union.tolist()]

        out_vals, present = column_on_union(sig_ts, vals, union)

        assert present.tolist() == expected, sig_ts
        assert hit_mask(sig_ts, union).tolist() == expected, sig_ts
        for row, t in enumerate(union.tolist()):
            if t in oracle:
                assert out_vals[row] == oracle[t], (sig_ts, t)


def test_hit_mask_is_read_only_and_matches_union_length() -> None:
    mask = hit_mask(np.array([0.0]), np.array([0.0, 1.0, 2.0]))
    assert mask.tolist() == [True, False, False]
    assert mask.flags.writeable is False


# ─── row_range: 閉区間の保存 (M-3) ────────────────────────────────────────────


def test_row_range_includes_both_endpoints() -> None:
    union = np.array([0.0, 1.0, 2.0, 3.0])
    assert row_range(union, 1.0, 2.0) == (1, 3)


def test_row_range_unbounded_sides() -> None:
    union = np.array([0.0, 1.0, 2.0])
    assert row_range(union, None, None) == (0, 3)
    assert row_range(union, 1.0, None) == (1, 3)
    assert row_range(union, None, 1.0) == (0, 2)


def test_row_range_outside_the_data_is_empty() -> None:
    union = np.array([0.0, 1.0])
    lo, hi = row_range(union, 5.0, 6.0)
    assert lo == hi  # 行 0 本 (ヘッダのみのファイルになる)


def test_row_range_agrees_with_in_range_row_by_row() -> None:
    """``_in_range`` (行ごとの比較) と**同じ行集合**であることの独立オラクル。

    sides を取り違えると両端が 1 行ずつ欠ける — 値ベースの assert では
    「境界にサンプルが無い」fixture で緑のまま通るので、境界に必ずサンプルが
    在る格子で全パターンを突き合わせる。
    """
    union = np.arange(0.0, 10.0, 1.0)
    for start in (None, 0.0, 2.0, 9.0, 9.5):
        for end in (None, 0.0, 2.0, 9.0, 9.5):
            if start is not None and end is not None and start > end:
                continue
            opts = CsvExportOptions(time_start=start, time_end=end)
            expected = [i for i, t in enumerate(union.tolist()) if _in_range(t, opts)]
            lo, hi = row_range(union, start, end)
            assert list(range(lo, hi)) == expected, (start, end)
