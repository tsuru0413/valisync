"""B3 spike: MDF.select(record_offset/record_count) が読む量を実際に縮めるか。

**採否の条件** (spec §5.3):
- 仮想グループ (LD-14 展開の元になる 2-D チャンネル) で窓読みが成立するか
- copy_master=False との相互作用 (master も窓になるか・長さが samples と一致するか)
- 採る場合の必須条件 = **窓読みの結果を ChannelSampleCache に入れない**
  (キー空間に窓が無く、後続の全期間読みが切り詰められた配列を引く。_column_of の
  検証は長さ比較だけなので、同長の別窓は素通しする = サイレント誤データ)

既定は quick_demo (170 MB) に対して 4 形を測る: 全期間 select / 窓 select (先頭 10%) /
2-D チャンネルの窓 select / copy_master=False x 窓。判断は「読む量 (wall と
process I/O) が窓の比率どおり縮むか」で行い、縮まないなら不採用にして理由を
spec §9-4 へ追記する。

**使い捨て計測器** (``fu16_*_bench.py`` と同じ位置づけ)。production コードでは
ない — asammdf の生 API (``handle.mdf.select``) を直接叩き、``ChannelSampleCache``
や ``LazyMdfValues`` は経由しない (この spike が答えたいのは asammdf 自身が窓読みを
実際に縮めるかどうかであって、その上の層の挙動ではない)。

**M2 是正 (Task 11 レビュー)**: spec §9-4 の不採用判断は quick_demo の 2-D (8
leaves) だけでは判断材料として弱く、実際に判断の決め手になったのは
`Prod10Wide_0000` (1,100 leaves) での prod_demo 補足測定だった。当初この補足測定は
ファイルを直接編集しないと再現できなかった (`TARGET` が quick_demo 固定) —
``--target`` でファイルを差し替え可能にし、prod の証拠を再現可能にする。

Run:
    uv run --with psutil python scripts/e4b_record_range_spike.py
    uv run --with psutil python scripts/e4b_record_range_spike.py --target demo_data/prod_demo.mf4
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

_DEFAULT_TARGET = REPO / "demo_data" / "quick_demo.mf4"


def _resolve_target() -> Path:
    """既定は quick_demo・``--target <path>`` で任意ファイルへ差し替える (M2)。"""
    if "--target" in sys.argv:
        idx = sys.argv.index("--target")
        return Path(sys.argv[idx + 1])
    return _DEFAULT_TARGET


try:
    import psutil

    _PROC: Any = psutil.Process()
except ImportError:  # pragma: no cover - スクリプトは --with psutil で回す前提
    _PROC = None


def _io_read_bytes() -> int:
    """このプロセスの累積ディスク読み込みバイト数 (psutil 無しなら 0 = 未計測)。"""
    if _PROC is None:
        return 0
    return int(_PROC.io_counters().read_bytes)


@dataclass
class Probe:
    label: str
    wall_s: float
    read_bytes: int
    samples_len: int
    master_len: int
    master_matches_samples: bool


def _probe(
    label: str,
    mdf: Any,
    name: str,
    gi: int,
    ci: int,
    *,
    record_offset: int,
    record_count: int | None,
    copy_master: bool,
) -> Probe:
    io0 = _io_read_bytes()
    t0 = time.perf_counter()
    sig = mdf.select(
        [(name, gi, ci)],
        raw=False,
        ignore_value2text_conversions=True,
        copy_master=copy_master,
        record_offset=record_offset,
        record_count=record_count,
    )[0]
    wall = time.perf_counter() - t0
    read = _io_read_bytes() - io0
    samples_len = int(sig.samples.shape[0])
    master_len = len(sig.timestamps)
    return Probe(
        label=label,
        wall_s=wall,
        read_bytes=read,
        samples_len=samples_len,
        master_len=master_len,
        master_matches_samples=(master_len == samples_len),
    )


def _report(p: Probe, *, baseline: Probe | None, expect_ratio: float | None) -> None:
    io_note = f"read={p.read_bytes:,} B" if _PROC is not None else "read=(psutil 無し)"
    print(
        f"  {p.label:<32} wall={p.wall_s * 1000:8.2f} ms  {io_note:<20}  "
        f"samples={p.samples_len:,}  master_len={p.master_len:,}  "
        f"master==samples: {p.master_matches_samples}"
    )
    if baseline is not None and expect_ratio is not None:
        wall_ratio = p.wall_s / baseline.wall_s if baseline.wall_s > 0 else float("nan")
        print(
            f"    対 baseline: wall比={wall_ratio:.3f}  "
            f"(窓の比率どおりなら ~{expect_ratio:.3f})"
        )
        if _PROC is not None and baseline.read_bytes > 0:
            read_ratio = p.read_bytes / baseline.read_bytes
            print(f"    対 baseline: read比={read_ratio:.3f}")


def main() -> None:
    target = _resolve_target()
    if not target.exists():
        print(f"MISSING: {target} (run scripts/generate_demo_mf4.py --profile quick)")
        raise SystemExit(1)

    from valisync.core.loaders.column_names import leaf_count
    from valisync.core.session import Session

    print(f"loading {target.name} ...", flush=True)
    session = Session()
    outcome = session.load(target)
    key = outcome.key
    handle = session.group_signals(key)[0]._values_source._handle
    records = session._groups.column_records(key)
    mdf = handle.mdf

    # 最狭 (スカラー想定) と最広 (2-D 想定) の 2 チャンネルを選ぶ。
    widest_display, widest_n = "", 0
    narrowest_display, narrowest_n = "", 10**9
    for display, record in records.items():
        n = leaf_count(record.spec)
        if n > widest_n:
            widest_n, widest_display = n, display
        if n < narrowest_n:
            narrowest_n, narrowest_display = n, display
    assert widest_display and narrowest_display, "ロード済みグループに列レコードが無い"
    print(
        f"  narrowest={narrowest_display} (leaf_count={narrowest_n})  "
        f"widest={widest_display} (leaf_count={widest_n})",
        flush=True,
    )

    scalar_rec = records[narrowest_display]
    wide_rec = records[widest_display]
    is_2d = widest_n > 1

    print("\n=== (1)/(2) スカラー (想定) チャンネル: 全期間 vs 窓 (先頭 10%) ===")
    p1 = _probe(
        "(1) 全期間 select",
        mdf,
        scalar_rec.raw_base_name,
        scalar_rec.group_index,
        scalar_rec.channel_index,
        record_offset=0,
        record_count=None,
        copy_master=True,
    )
    _report(p1, baseline=None, expect_ratio=None)
    window = max(1, p1.master_len // 10)
    p2 = _probe(
        "(2) 窓 select (先頭10%)",
        mdf,
        scalar_rec.raw_base_name,
        scalar_rec.group_index,
        scalar_rec.channel_index,
        record_offset=0,
        record_count=window,
        copy_master=True,
    )
    _report(p2, baseline=p1, expect_ratio=window / p1.master_len)

    print(
        f"\n=== (3) 2-D (想定) チャンネル: 全期間 vs 窓 (先頭 10%) [is_2d={is_2d}] ==="
    )
    p3a = _probe(
        "(3a) 2-D 全期間 select",
        mdf,
        wide_rec.raw_base_name,
        wide_rec.group_index,
        wide_rec.channel_index,
        record_offset=0,
        record_count=None,
        copy_master=True,
    )
    _report(p3a, baseline=None, expect_ratio=None)
    window_2d = max(1, p3a.master_len // 10)
    p3b = _probe(
        "(3b) 2-D 窓 select (先頭10%)",
        mdf,
        wide_rec.raw_base_name,
        wide_rec.group_index,
        wide_rec.channel_index,
        record_offset=0,
        record_count=window_2d,
        copy_master=True,
    )
    _report(p3b, baseline=p3a, expect_ratio=window_2d / p3a.master_len)

    print("\n=== (4) copy_master=False x 窓 (スカラー) ===")
    p4 = _probe(
        "(4) copy_master=False x 窓",
        mdf,
        scalar_rec.raw_base_name,
        scalar_rec.group_index,
        scalar_rec.channel_index,
        record_offset=0,
        record_count=window,
        copy_master=False,
    )
    _report(p4, baseline=p1, expect_ratio=window / p1.master_len)
    print(
        f"    master 長 (copy_master=False) = {p4.master_len:,} "
        f"(全期間 master 長 {p1.master_len:,} と比較)"
    )

    print("\n=== 判定材料 ===")
    shrink_scalar = p2.wall_s < p1.wall_s * 0.7  # 窓 10% で wall が 30%+ 縮むか
    shrink_2d = p3b.wall_s < p3a.wall_s * 0.7
    print(f"  scalar: 窓読みで wall が縮む = {shrink_scalar}")
    print(f"  2-D   : 窓読みで wall が縮む = {shrink_2d}")
    print(f"  2-D   : master==samples (窓) = {p3b.master_matches_samples}")
    print(f"  copy_master=False: master 長が窓どおりか = {p4.master_len == window}")
    print(
        "  (縮む + 2-D で成立 -> spec §5.3/§10 を「採用」へ改訂。\n"
        "   縮まない/破綻 -> spec §9-4 へ理由つきで不採用を記録)",
        flush=True,
    )


if __name__ == "__main__":
    main()
