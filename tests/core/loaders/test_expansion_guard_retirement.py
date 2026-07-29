"""1024 展開ガードの退役 (C-i) と LD-08 dedup インデックスの移動 (C-f) の test-lock.

E-3 の反転でローダーは物理チャンネル 1 本につき Signal 1 個を発行し、列は要求時に
鋳造される。列が Signal にならない以上「per-channel の展開列数上限」を設ける理由
(オブジェクト爆発とメモリ) が消えたので、1024 ガードと確認モーダルを退役させた。

退役は LD-08 の [idx] を動かす: ガードが生きている間はスキップされた広幅チャンネルが
インデックスを消費しないため、同名の生存チャンネルが W[0] を取っていた。退役後は
広幅も載るので生存側は W[1] へ動く。**意図的リネーム・移行パスなし** (spec C-f) —
プロット/軸/オフセットのセッション永続化は未実装 (F-1 defer 中) ゆえ実害はない。
本ファイルはその契約を凍結し、ガードの無言の復活を RED にする。

demo_data には依存しない (重複名が無く、そもそも CI で生成されない)。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np

from tests.mdf4_helpers import write_mdf4_duplicate_wide
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.core.session import Session


def test_wide_channel_loads_without_any_confirmation(tmp_path: Path) -> None:
    """ヘッドレスでも広幅チャンネルが載る (旧: コールバック不在 = 全スキップ + 警告)."""
    path = write_mdf4_duplicate_wide(tmp_path, cols=1025)
    result = MdfLoader().load(path)  # 確認コールバックという概念自体が無い

    sg = result.signal_group
    assert sg is not None
    # 物理チャンネル 3 本 (広幅 W / スカラー W / Clean) が全て生存する。
    assert {s.name for s in sg.signals} == {"W[0]", "W[1]", "Clean"}
    # fixture は完全に健全なデータなので、退役後は警告/エラー診断がゼロになる。
    # 退役前はここに「展開列数 1025 が上限 1024 を超えるためスキップ」が 1 件出る。
    assert not [d for d in result.diagnostics if d.level in ("error", "warning")], [
        d.message for d in result.diagnostics
    ]


def test_dedup_index_shifts_when_wide_channel_is_no_longer_skipped(
    tmp_path: Path,
) -> None:
    """C-f: 生存スカラーの永続キーが W[0] -> W[1] へ動く (意図的・移行なし)."""
    path = write_mdf4_duplicate_wide(tmp_path, cols=1025)
    session = Session()
    key = session.load(path).key

    # 先に載る広幅チャンネルが idx 0 を取る。列名は dedup の [0] と展開の [i] が
    # 同じ角括弧で連なる — この文法 (W[0][i]) も併せて凍結する。
    wide_cols = session.column_names_of(key, "W[0]")
    assert len(wide_cols) == 1025
    assert wide_cols[0] == "W[0][0]"
    assert wide_cols[-1] == "W[0][1024]"

    # 生存スカラーは idx 1 へ動いた (ガードが生きていた頃はこれが W[0] だった)。
    assert session.column_names_of(key, "W[1]") == ("W[1]",)
    scalar = session.resolve_signal(f"{key}{KEY_SEPARATOR}W[1]")
    assert scalar is not None
    np.testing.assert_array_equal(scalar.values, [7.0, 8.0, 9.0])

    # U2 の母数 (列数) にも退役が波及する: 1025 (広幅) + 1 (スカラー) + 1 (Clean)。
    assert session.total_column_count(key) == 1027


def test_column_of_duplicated_wide_channel_resolves_to_the_right_channel(
    tmp_path: Path,
) -> None:
    """重複生名 + 構造相違でも鋳造が正しい方のチャンネルを引く (退役で初到達).

    生名 "W" は 2 つの物理チャンネル (2D 1025 列 / スカラー) が共有しており、
    parse_leaf の docstring が言う「健全性の限界」そのものの配置になる。ガードが
    あった頃は広幅側がスキップされて到達不能だった経路。
    """
    path = write_mdf4_duplicate_wide(tmp_path, cols=1025)
    session = Session()
    key = session.load(path).key

    col = session.resolve_signal(f"{key}{KEY_SEPARATOR}W[0][5]")
    assert col is not None
    np.testing.assert_array_equal(col.values, [5, 5, 5])  # 列 j の値は j % 256


def test_load_signatures_no_longer_take_confirm_expansion() -> None:
    """退役の構造ロック: 引数だけ復活する部分的な巻き戻しを RED にする."""
    assert "confirm_expansion" not in inspect.signature(MdfLoader.load).parameters
    assert "confirm_expansion" not in inspect.signature(Session.load).parameters
