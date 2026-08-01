"""Task 2 のゴールデンを **新しい境界 API 経由** でも byte 一致させる (spec G1/MG-7)。

期待バイトはこのファイルに書き写さない — Task 2 が凍結した ``.csv`` を
``read_bytes()`` で読む (二重の真実を作らない・ゴールデンの再生成は禁止)。
橋を通しても 1 バイトも動かないことが「MG-7 のヘッダ導出形の凍結」の実証。

Task 2 の成果物 (``tests/golden_csv_cases.py``) を import して再利用し、**ケースの
定義をここへ複製しない**。旧経路 (``export_case``) との違いは 2 点だけ:

1. 列を **キー** で渡す (``Session.export_csv(keys, ...)``)
2. ヘッダを **resolver** で導出する (``build_options`` の header_names 事前計算を
   使わない)

出力バイトがそれでも 1 個も動かないことが、Task 4 の境界変更が「呼び出し形の
付け替え」であって「出力仕様の変更」ではないことの証明になる。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests.golden_csv_cases import GOLDEN_CASES, GOLDEN_DIR, GoldenCase
from tests.test_golden_csv import _diff_message  # 診断の二重実装を避ける
from valisync.core.models import Signal
from valisync.core.session import Session
from valisync.gui.display_names import csv_header_resolver


class _KeyedSession(Session):
    """golden ケースの Signal を **列キーで引ける** ようにした Session。

    ゴールデン 11 本のうち 9 本は素の Derived Signal を組み立てるだけで
    ``SignalGroupManager`` に登録されていない (g08/g11 だけがローダーを通る)。
    ``Session.export_csv`` の解決口を差すのが「境界を通す」最小の介入になる。

    **E-4b Task 7 supersede**: 差す口が ``resolve_signal`` から
    ``resolve_signal_transient`` へ移った (spec §5.2 MG-1 が Task 6 で名指しした
    まさにその 1 点を、Task 7 が `Session.export_csv` へ配線した)。**両方を
    override する** — 片方だけにすると「production が読む口」と「テストが差す口」が
    ずれても誰も落ちず、`export_csv` が transient 経路をやめて LRU 帳簿へ戻る
    退行 (MG-1 の破棄) がこのファイルからは見えなくなる。

    **解決そのものは本ファイルの検証対象ではない** (それは
    ``test_export_request_bridge`` と、実ローダーの Signal を流す g08/g11 が持つ)。
    ここが測るのは「keys で運んで resolver でヘッダを作ってもバイトが動かない」だけ。
    """

    def __init__(self, by_key: dict[str, Signal]) -> None:
        super().__init__()
        self._by_key = by_key

    def resolve_signal(self, key: str) -> Signal | None:
        return self._by_key.get(key)

    def resolve_signal_transient(self, key: str) -> Signal | None:
        return self._by_key.get(key)


def _export_via_keys_boundary(case: GoldenCase, work_dir: Path) -> bytes:
    inp = case.build(work_dir)
    try:
        # keys と signal.name の 1:1 を**独立に**確かめる。ずれたまま dict を
        # 組むと、列キーと値が別チャンネルから来る CSV が黙って出る
        # (E-4b が構造的に根治しようとしている失敗そのもの)。
        assert [s.name for s in inp.signals] == list(inp.keys), (
            f"{case.case_id}: keys と signal.name が 1:1 でない"
        )
        session = _KeyedSession(dict(zip(inp.keys, inp.signals, strict=True)))
        out = work_dir / f"{case.case_id}.csv"
        # M-1: 統合タイムラインは options 経由 (旧 export_case は独立引数で渡す)。
        opts = replace(inp.options, use_unified_timeline=inp.use_unified_timeline)
        if inp.derive_headers:
            session.export_csv(inp.keys, out, opts, header_resolver=csv_header_resolver)
        else:
            # 既定 (passthrough) の**結合**検証。resolver 引数を渡さないことに
            # 意味があるので、None を明示的に渡す形へ畳んではならない。
            session.export_csv(inp.keys, out, opts)
        return out.read_bytes()
    finally:
        inp.close()


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.case_id)
def test_golden_bytes_survive_the_keys_boundary(
    case: GoldenCase, tmp_path: Path
) -> None:
    """全ゴールデンを keys 境界経由で再現する (GUI 形は resolver 注入・g02 は既定)。"""
    expected = (GOLDEN_DIR / f"{case.case_id}.csv").read_bytes()
    actual = _export_via_keys_boundary(case, tmp_path)
    assert actual == expected, _diff_message(case, expected, actual)


def test_passthrough_golden_bytes_survive_the_keys_boundary() -> None:
    """凍結集合が **両方のヘッダ形** を含むことを、ファイルのバイトから確かめる。

    上のパラメトライズは各ケース自身の形で駆動する。だから「passthrough 形の
    ゴールデンが 1 本も無い」状態になると、既定 resolver が壊れていても
    **誰も落ちない** (parametrize は空集合を黙って許すのと同じ穴)。

    判定材料をケース定義 (``derive_headers``) ではなく**凍結ファイルのヘッダ行**に
    置くのは、こちらが独立オラクルだから — 生の名前空間つきキー (``::`` を含む)
    が出ているファイルが passthrough 形、bare 名だけのものが GUI 形。
    ケース側のフラグを読むと、フラグの綴りが変わった瞬間に一緒に盲目になる。
    """
    heads = {
        p.stem: p.read_bytes().split(b"\n", 1)[0] for p in GOLDEN_DIR.glob("*.csv")
    }
    assert heads, "ゴールデンが 1 本も無い"
    passthrough = sorted(k for k, h in heads.items() if b"::" in h)
    gui_form = sorted(set(heads) - set(passthrough))
    assert passthrough, (
        "raw namespaced ヘッダのゴールデンが消えた — Session.export_csv 直呼びの"
        "既定 (passthrough) ヘッダバイトを縛るものが無くなる"
    )
    assert gui_form, "GUI 形 (bare 名) ヘッダのゴールデンが消えた"
