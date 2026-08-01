"""出力バイトのゴールデン照合 (E-4b Task 2 / spec §7.1・G1)。

``read_bytes()`` の全文一致。ゴールデンは **BOM・行末 LF・クォート・区切り・
列順・ヘッダ導出形・repr・空セル** を一度に縛る唯一のオラクルで、Task 4-7 の
書き経路の全面再構築 (keys 化 -> 列ブロック -> 多段マージ) がバイトを 1 個も
変えていないことの受け入れ条件になる。

**再生成で黙らせない (spec G1)**: ``scripts/generate_golden_csv.py`` は既存
ファイルがあると何も書かずに終了する。意図的な変更はゴールデン **11 本すべて**
を ``git rm`` して再生成する (生成は決定的なので、意図した 1 本だけが diff に
出る) — 理由を docs/design.md 決定履歴へ記録してからの手動 supersede のみ (M2)。

**ゴールデンだけでは足りない部分**: ゴールデンは「今こう出ている」を固める
だけで、**オラクル自身が入力の何に反応するか**は語らない。列順を反転しても
バイトが変わらない実装 (spec §1 の M7 = 現状「全緑」) を捕まえるには、
入力を変えてバイトが**変わる**ことを直接見る必要がある — それが本ファイル
後半の感度オラクル群。
"""

from __future__ import annotations

import difflib
import inspect
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    # ``tests.*`` は pytest が解決できるが ``scripts`` はどのテストパッケージにも
    # 属さないため sys.path に現れない (実測: ModuleNotFoundError)。生成器の
    # 上書き拒否は**実物の main を呼んで**確かめたいので、ここでルートを通す。
    sys.path.insert(0, str(_REPO_ROOT))

from tests.golden_csv_cases import (  # noqa: E402  (sys.path 調整の後でしか import できない)
    BLOCK_COLS_VARIANTS,
    GOLDEN_CASES,
    GOLDEN_DIR,
    ULP_EXPECTED_ROWS,
    GoldenCase,
    GoldenInput,
    _sig,
    build_options,
    export_case,
)
from valisync.core.export import csv_exporter  # noqa: E402
from valisync.core.export.csv_exporter import (  # noqa: E402
    CsvExporter,
    CsvExportOptions,
)

_CASES_BY_ID = {c.case_id: c for c in GOLDEN_CASES}


def _golden_path(case_id: str) -> Path:
    return GOLDEN_DIR / f"{case_id}.csv"


def _diff_message(case: GoldenCase, expected: bytes, actual: bytes) -> str:
    """バイト差分を人が読める形に落とす。

    BOM/CRLF/末尾改行の差は decode 後の diff に**現れない**ので、先頭バイトと
    行末の種類を別途明記する (「diff が空なのに落ちる」を防ぐ)。
    """
    head = [
        f"case={case.case_id} ({case.why})",
        f"expected {len(expected)} bytes / actual {len(actual)} bytes",
        f"expected BOM={expected[:3]!r} / actual BOM={actual[:3]!r}",
        f"expected CRLF={expected.count(b'\r\n')} / actual CRLF={actual.count(b'\r\n')}",
    ]
    diff = difflib.unified_diff(
        # errors="replace": ここは診断の組み立て自体であり、エンコーディング退行
        # (例: BOM 崩れで有効な UTF-8 でなくなる) が起きたときこそ差分を読みたい。
        # 素の decode だと診断器自身が UnicodeDecodeError で落ち、本来のバイト差分
        # (先頭バイト/CRLF 個数は head で既に出している) が一切見えなくなる。
        expected.decode("utf-8-sig", errors="replace").splitlines(keepends=True),
        actual.decode("utf-8-sig", errors="replace").splitlines(keepends=True),
        fromfile="golden",
        tofile="actual",
        n=2,
    )
    return "\n".join([*head, "", *list(diff)[:60]])


# ─── 本体: バイト一致 ────────────────────────────────────────────────────────


# E-4b Task 7 supersede: ``BLOCK_COLS_VARIANTS`` を ``(None, 1, 2)`` へ広げた
# (spec G1「ゴールデンは複数ブロック・境界跨ぎで駆動」)。**期待バイトは 1 バイトも
# 変えていない** — 全変種が同じ golden ファイルと突き合わされる。駆動側だけが
# parametrize される形であることが要点で、期待側を block_cols で分岐させたら
# 「どう分割しても同じバイト」という主張そのものが消える。
@pytest.mark.parametrize("block_cols", BLOCK_COLS_VARIANTS, ids=lambda b: f"bc{b}")
@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.case_id)
def test_golden_bytes_match(
    case: GoldenCase, block_cols: int | None, tmp_path: Path
) -> None:
    expected = _golden_path(case.case_id).read_bytes()
    actual = export_case(case, tmp_path, block_cols=block_cols)
    assert actual == expected, _diff_message(case, expected, actual)


def test_every_case_has_exactly_one_golden_file() -> None:
    """孤児と欠落の双方向検出。

    片方向 (ケース -> ファイル) だけだと、ケースを消したときに古いゴールデンが
    残り続け、次に同じ case_id を足した人が**別の意図のバイト**と照合される。
    """
    on_disk = {p.stem for p in GOLDEN_DIR.glob("*.csv")}
    declared = {c.case_id for c in GOLDEN_CASES}
    assert on_disk == declared, (
        f"孤児={sorted(on_disk - declared)} / 欠落={sorted(declared - on_disk)}"
    )


def test_all_goldens_start_with_a_bom_and_use_lf_line_endings() -> None:
    """凍結した 3 つの大域性質を、ケースを跨いで 1 本で言い切る。

    個々のバイト比較でも捕まるが、失敗メッセージが「56 行のどこかが違う」に
    なって読めない。ここが先に落ちれば原因が 1 行で分かる。
    """
    for case in GOLDEN_CASES:
        raw = _golden_path(case.case_id).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), case.case_id
        assert raw.count(b"\xef\xbb\xbf") == 1, case.case_id
        # 行末 LF (据え置き決定)。ここが CR で落ちるときの原因はほぼ **git の
        # 改行変換** で、エクスポータは無実 — `core.autocrlf=true` の Windows が
        # checkout で LF -> CRLF に化けさせる (実測で再現済み)。生成器は上書きを
        # 拒否するので「作り直して直す」は効かない。`.gitattributes` の
        # `tests/golden_csv/** -text` が生きているかをまず見ること。
        assert b"\r" not in raw, (
            f"{case.case_id}: CR を検出。.gitattributes の -text が効いていない "
            "可能性が高い (git の改行変換であってエクスポータの退行ではない)"
        )
        assert raw.endswith(b"\n"), case.case_id  # 末尾改行あり (据え置き決定)


def test_goldens_are_pinned_against_git_eol_conversion() -> None:
    """`.gitattributes` の `-text` が外れたことを検出できる唯一の場所 (I3)。

    CI (ubuntu) は ``core.autocrlf`` が既定で無効なので、この破壊は構造的に
    観測できない — 落ちるのは Windows 環境 (本開発機・Windows CI があれば) だけ。
    それでも `.gitattributes` の記述ミス (typo・パターン漏れ) はここでしか
    捕まらないので、`git check-attr` で実際の適用結果を直接見る。
    保護されているときの出力は ``: text: unset``、外れると ``: text: unspecified``
    になる (どちらも実測で確認済み)。
    """
    out = subprocess.run(
        ["git", "check-attr", "text", "--", str(_golden_path("g01_shared_basic"))],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.rstrip().endswith(": text: unset"), out


def test_ulp_split_row_count_is_frozen() -> None:
    """分裂の**行数まで**凍結する (spec §7.1)。

    バイト比較でも当然捕まるが、行数を独立に言うことで「union の畳み方を
    tolerance 化した (spec C-1 が禁止)」という**意味**の退行が一目で分かる。
    反 vacuous: 分裂していなければ 51 行 (fast の点数) のはずで、56 > 51 が
    「実際に分裂している」ことの証拠。
    """
    raw = _golden_path("g07_unified_ulp_split").read_bytes()
    data_rows = raw.decode("utf-8-sig").splitlines()[1:]
    assert len(data_rows) == ULP_EXPECTED_ROWS
    assert ULP_EXPECTED_ROWS > 51, "分裂していない fixture では軸を守れない"


# ─── 感度オラクル: 入力を変えたらバイトが変わること ──────────────────────────


def _export_with(
    mutate: Callable[[GoldenInput], GoldenInput], case_id: str, tmp_path: Path
) -> bytes:
    """ケースの入力を変異させて export する (src は一切触らない)。"""
    case = _CASES_BY_ID[case_id]
    inp = case.build(tmp_path)
    try:
        mutated = mutate(inp)
        out = tmp_path / "mutated.csv"
        CsvExporter().export(
            mutated.signals,
            out,
            mutated.use_unified_timeline,
            build_options(mutated),
        )
        return out.read_bytes()
    finally:
        inp.close()


def test_reversed_column_order_changes_the_bytes(tmp_path: Path) -> None:
    """列順はゴールデンが縛る対象そのもの (spec §10)。"""
    actual = _export_with(
        lambda inp: replace(
            inp, signals=list(reversed(inp.signals)), keys=tuple(reversed(inp.keys))
        ),
        "g01_shared_basic",
        tmp_path,
    )
    golden = _golden_path("g01_shared_basic").read_bytes()
    assert actual != golden
    header = actual.decode("utf-8-sig").splitlines()[0]
    assert header == "timestamp,Brake,EngSpeed,VehSpd"


def test_signals_reversed_without_headers_changes_the_bytes(tmp_path: Path) -> None:
    """spec §1 の M7 (``signals.reverse()`` で全緑) を閉じる。

    keys はそのまま = ヘッダ不変で**値の列だけ**入れ替わる形。ヘッダと値を
    別々に運ぶ実装が黙って対応を崩したときの唯一の検出点。
    """
    actual = _export_with(
        lambda inp: replace(inp, signals=list(reversed(inp.signals))),
        "g01_shared_basic",
        tmp_path,
    )
    golden = _golden_path("g01_shared_basic").read_bytes()
    assert actual != golden
    lines = actual.decode("utf-8-sig").splitlines()
    assert lines[0] == "timestamp,VehSpd,EngSpeed,Brake"  # ヘッダは不変
    assert lines[1] != golden.decode("utf-8-sig").splitlines()[1]  # 値は入れ替わる


def test_dropping_columns_changes_the_bytes(tmp_path: Path) -> None:
    """列の部分集合がゴールデンと一致しないこと (= ゴールデンは列集合に敏感)。"""
    actual = _export_with(
        lambda inp: replace(inp, signals=inp.signals[:1], keys=inp.keys[:1]),
        "g01_shared_basic",
        tmp_path,
    )
    assert actual != _golden_path("g01_shared_basic").read_bytes()
    assert actual.decode("utf-8-sig").splitlines()[0] == "timestamp,VehSpd"


def test_changing_the_delimiter_changes_the_bytes(tmp_path: Path) -> None:
    actual = _export_with(
        lambda inp: replace(inp, options=replace(inp.options, delimiter=";")),
        "g01_shared_basic",
        tmp_path,
    )
    assert actual != _golden_path("g01_shared_basic").read_bytes()


def test_changing_the_precision_changes_the_bytes(tmp_path: Path) -> None:
    actual = _export_with(
        lambda inp: replace(inp, options=replace(inp.options, precision=6)),
        "g01_shared_basic",
        tmp_path,
    )
    assert actual != _golden_path("g01_shared_basic").read_bytes()


@pytest.mark.parametrize(
    ("start", "end"),
    [(0.0, 1.5), (0.5, 2.0)],
    ids=["start_minus_one_sample", "end_plus_one_sample"],
)
def test_range_boundary_off_by_one_sample_changes_the_bytes(
    start: float, end: float, tmp_path: Path
) -> None:
    """境界を 1 サンプル動かすと必ずバイトが変わること。

    ``row_range の side='left'/'right'`` の ``>=`` / ``<=`` を片側だけ壊す変異は、ゴールデンの中身が
    境界サンプルを含んでいなければ素通りする — g04 の両端がサンプル上に
    乗っていることがこのテストの前提。
    """
    actual = _export_with(
        lambda inp: replace(
            inp, options=replace(inp.options, time_start=start, time_end=end)
        ),
        "g04_unified_range_closed",
        tmp_path,
    )
    assert actual != _golden_path("g04_unified_range_closed").read_bytes()


def test_empty_selection_fails_loudly_and_writes_no_file(tmp_path: Path) -> None:
    """空選択の**現行**契約を凍結する: 例外・ファイル無し。

    T-G 時点は ``_rows_shared_timeline`` の ``views[0]`` で IndexError、
    ``_rows_unified_timeline`` の ``np.concatenate([])`` で ValueError だった。
    **E-4b Task 7 supersede**: 両実装は消え、``_export_request`` 冒頭の
    ``EXPORT_EMPTY_REQUEST_ERROR`` (ValueError) が唯一の loud-fail になった —
    期待は ``(IndexError, ValueError)`` のまま 1 文字も変えていない (契約は
    「例外・ファイル無し」であって例外クラスではない)。
    GUI は ``_on_accept`` の ``if not keys: return`` で到達させないが、
    ``Session.export_csv`` 直呼びは到達する。**沈黙して空ファイルを書く**
    (ヘッダだけの CSV を「成功」として渡す) 形へ degrade させないことが要点。
    """
    out = tmp_path / "empty.csv"
    for unified in (False, True):
        with pytest.raises((IndexError, ValueError)):
            CsvExporter().export([], out, unified)
        assert not out.exists()


# ─── I1 (レビュー指摘): データ行クォート抜けの検出 ───────────────────────────


@pytest.mark.parametrize("unified", [False, True], ids=["shared", "unified"])
def test_data_cells_are_quoted_when_the_delimiter_can_appear_in_a_number(
    unified: bool,
    tmp_path: Path,
) -> None:
    """データ行の _join を落とすと RED になる唯一のオラクル (T-G sabotage M4b)。

    ゴールデン 11 本と既存 65 本は、既定 delimiter では数値セルに区切り文字が
    構造的に現れないため、データ行の _join を素の delimiter.join へ落としても
    全緑になる (実測)。float の repr は負値/指数で '-' と '+' を出すので、
    合法な delimiter='-' がこの穴を塞ぐ最小の入力。

    **両タイムラインで駆動する** (再レビュー是正 2026-08-01): T-G 時点では _join の
    サイトが _rows_unified_timeline と _rows_shared_timeline の 2 箇所にあり、
    片方だけ落とす変異は他方を駆動するテストでは捕まらなかった (実測: unified 側
    だけ落とすと 27 passed / RED ゼロ)。**E-4b Task 7 supersede**: 両実装が消え
    データ行の _join は `_write_block_temp` / `_write_time_temp` の 2 箇所
    (値側と時刻側) になった — サイトが片翼ずつ独立に盲目になりうる構造は
    変わらないので、両モード駆動は維持する (union==元 ts なので出力は同一)。
    さらに Task 7 のマージ器は断片を**素の delimiter で繋ぐ** (二重クォート禁止)
    ので、このテストは「ブロック内でクォート済み・マージで再クォートしない」の
    合成結果も同時に縛っている。
    """
    out = tmp_path / "d.csv"
    sig = _sig("mf4_1::v", [0.0, 1.0], [-1.5, 1e300])
    CsvExporter().export([sig], out, unified, CsvExportOptions(delimiter="-"))
    # header_names 未指定なので header セルは raw name ("mf4_1::v")。
    # -1.5 の repr は '-1.5' -> delimiter '-' を含むのでクォート必須。
    # 1e300 の repr は '1e+300' -> '-' を含まないので non-quoted のまま (正しい)。
    assert out.read_bytes() == (
        b'\xef\xbb\xbftimestamp-mf4_1::v\n0.0-"-1.5"\n1.0-1e+300\n'
    )


# ─── Task 7 への申し送りガード ───────────────────────────────────────────────


def test_block_cols_handoff_is_not_forgotten() -> None:
    """spec G1「ゴールデンは複数ブロック (境界跨ぎ) で駆動」の**片翼**を強制する (I2)。

    このアサーション単体が強制できるのは「``__init__`` に ``block_cols`` が現れた
    ら ``BLOCK_COLS_VARIANTS`` を複数値へ広げること」という**名指し**だけ —
    広げた後に driver (``export_case``) が実際にその値を ``CsvExporter`` へ渡して
    境界跨ぎで export し直すかは、ここだけでは見ていない。その追随を強制するのは
    ``test_golden_bytes_match`` に足した
    ``@pytest.mark.parametrize("block_cols", BLOCK_COLS_VARIANTS, ...)`` の側で、
    ``export_case`` が ``block_cols`` を ``CsvExporter`` へ渡さない限り、variants を
    広げた瞬間に **コンストラクタの ``TypeError``** でゴールデン全本が RED になる。
    両方が揃って初めて G1 (複数ブロックでの実駆動) を強制する。

    T-G 時点で ``block_cols`` は存在しない。Task 7 が列ブロック化したとき、
    ゴールデンを 1 ブロックのまま走らせても**バイトは一致する** — つまり
    「境界跨ぎで駆動する」という受け入れ条件は、忘れても誰も落ちない。
    ``block_cols`` が現れた瞬間にここが RED になり、``BLOCK_COLS_VARIANTS`` の
    拡張が名指しで強制される。

    **見るのは ``__init__``**: Task 6/7 は ``block_cols`` を **コンストラクタの
    注入口** に置く (``export()`` の署名は共有インターフェース契約で凍結されて
    いるため)。``export`` の署名を見ると block_cols は永久に現れず、この
    ガードは恒久的に空虚になる (G1「複数ブロック駆動」の強制が消える)。

    **E-4b Task 7 で発火済み** (両辺 True で緑)。Task 6 の実測どおり、
    ``__init__`` の ``block_cols`` と ``BLOCK_COLS_VARIANTS`` の拡張は片方だけでは
    通らない (param だけ足すとここが RED・variants だけ広げると
    ``export_case`` の ``CsvExporter(block_cols=...)`` が TypeError) ので、
    **1 コミットで同時に landing させた**。以後は「片方を戻す」退行の門番として
    残る — 恒真ではなく、両辺が同時に倒れる形の双方向 assert であることが要点。
    """
    params = inspect.signature(CsvExporter.__init__).parameters
    has_block_cols = "block_cols" in params
    assert has_block_cols == (len(BLOCK_COLS_VARIANTS) > 1), (
        "block_cols の導入とゴールデンの複数ブロック駆動は同時に行うこと "
        f"(signature={list(params)}, variants={BLOCK_COLS_VARIANTS})"
    )


def test_multi_column_goldens_really_cross_a_block_boundary(tmp_path: Path) -> None:
    """``block_cols=1`` の駆動が**実際に 2 ブロック以上**を作っていること (G1)。

    ``BLOCK_COLS_VARIANTS`` を広げるだけでは G1 は空虚になりうる — 実装が
    ``block_cols`` を無視 (あるいは下限で握り潰) しても、出力バイトは同じなので
    ``test_golden_bytes_match`` は全数緑のままになる。**Task 6 のレビューで
    一度この空虚な緑が返ってきた**ので、「境界を跨いだ」ことを出力ではなく
    **ブロック計画そのもの**で観測する。

    観測点を ``plan_blocks`` にするのは、ここが「列 -> ブロック」の唯一の決定点
    だから (block-temp を数える案は temp が finally で消えるため観測窓が要る)。
    """
    seen: list[tuple[tuple[int, int], ...]] = []
    original = csv_exporter.plan_blocks

    def spy(runs, block_cols):  # type: ignore[no-untyped-def]
        blocks = original(runs, block_cols)
        seen.append(blocks)
        return blocks

    # g05 は 5 列 (要クォート名・単位行)。列数が最も多い部類のケースで、
    # block_cols=1 なら 5 ブロックになるはず。
    case = _CASES_BY_ID["g05_quoting_japanese_units"]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(csv_exporter, "plan_blocks", spy)
        actual = export_case(case, tmp_path, block_cols=1)

    assert actual == _golden_path(case.case_id).read_bytes()
    assert len(seen) == 1, seen
    assert len(seen[0]) > 1, (
        f"block_cols=1 でもブロックが 1 個しか作られていない: {seen[0]} — "
        "ゴールデンの複数ブロック駆動 (G1) が空虚"
    )
    # 反 vacuous の裏側: 既定 (自動決定) では 1 ブロックであることも見る。
    # 両方が同じ数なら「block_cols が効いていない」ことの直接証拠になる。
    seen.clear()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(csv_exporter, "plan_blocks", spy)
        export_case(case, tmp_path, block_cols=None)
    assert len(seen[0]) == 1, seen


# ─── 生成器の上書き拒否 (spec G1) ────────────────────────────────────────────


def test_generator_refuses_to_overwrite_existing_goldens(tmp_path: Path) -> None:
    """2 回目の生成は**何も書かずに** exit 1 を返す。

    ここが緩むと「壊してから再生成」でゴールデンを黙らせられるようになる。
    1 ケースだけで駆動するのは、11 本を毎回作り直すコストを避けるため
    (拒否の判定はケース数に依存しない)。

    さらに 1 回目の生成物がコミット済みバイトと一致することも見る — 生成器と
    照合テストが同じ export_case を通っていることの独立確認 (別経路で作られた
    ゴールデンをうっかりコミットする事故の検出)。
    """
    from scripts.generate_golden_csv import main

    case = _CASES_BY_ID["g01_shared_basic"]
    assert main(golden_dir=tmp_path, cases=[case]) == 0
    produced = (tmp_path / f"{case.case_id}.csv").read_bytes()
    assert produced == _golden_path(case.case_id).read_bytes()

    before = produced
    assert main(golden_dir=tmp_path, cases=[case]) == 1
    assert (tmp_path / f"{case.case_id}.csv").read_bytes() == before


def test_generator_has_no_force_switch() -> None:
    """``--force`` 相当を持たないことを構造で縛る (spec G1)。

    「拒否する」実装は簡単に「拒否をスキップできる」実装へ育つ。main の
    キーワードに force/overwrite の類が現れたら RED。
    """
    from scripts.generate_golden_csv import main

    params = set(inspect.signature(main).parameters)
    assert params == {"golden_dir", "cases"}, params
