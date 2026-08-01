"""ゴールデン CSV を生成する (E-4b Task 2)。**再生成は禁止**。

    uv run python scripts/generate_golden_csv.py

**既存のゴールデンを 1 つでも見つけたら何も書かずに終了する** (exit 1)。
ゴールデンは出力バイトの凍結そのものなので、「壊してから再生成して差分を見る」
運用にすると凍結が凍結でなくなる — 実装を壊した本人が再生成すれば常に緑になる
(spec G1)。

意図的な変更は **supersede**: 対象ファイルを ``git rm`` で明示的に落とし、
理由を docs/design.md 決定履歴へ記録してから本スクリプトを走らせる。
``--force`` は**意図的に用意しない** (用意した瞬間に上の抑止が効かなくなる)。
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    # `python scripts/x.py` では sys.path[0] が scripts/ になり tests/ が見えない。
    sys.path.insert(0, str(_REPO_ROOT))

from tests.golden_csv_cases import (  # noqa: E402  (sys.path 調整の後でしか import できない)
    GOLDEN_CASES,
    GOLDEN_DIR,
    GoldenCase,
    export_case,
)


def main(
    golden_dir: Path = GOLDEN_DIR,
    cases: Sequence[GoldenCase] = GOLDEN_CASES,
) -> int:
    golden_dir.mkdir(parents=True, exist_ok=True)
    existing = [c.case_id for c in cases if (golden_dir / f"{c.case_id}.csv").exists()]
    if existing:
        print("既存のゴールデンがあるため**何も書かずに**中止しました (spec G1):")
        for case_id in existing:
            print(f"  {golden_dir / (case_id + '.csv')}")
        print(
            "意図的に更新する場合は、対象を `git rm` して理由を "
            "docs/design.md 決定履歴へ記録してから再実行してください。"
        )
        return 1
    # **全ケースを組み立ててから書く** (二相)。途中のケースが例外を投げたときに
    # 部分的なゴールデンが残ると、次の実行は「既存あり」で拒否され、直すには
    # 半端なファイルを git rm する必要が出る = 拒否の仕組み自体が罠になる。
    produced: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for case in cases:
            produced[case.case_id] = export_case(case, work)
    for case_id, data in produced.items():
        (golden_dir / f"{case_id}.csv").write_bytes(data)
        n_lines = data.count(b"\n")
        print(f"wrote {case_id}.csv  ({len(data)} bytes, {n_lines} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
