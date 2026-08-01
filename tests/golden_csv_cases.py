"""ゴールデン CSV の入力ケース定義と駆動 (E-4b Task 2 / spec §7.1)。

**唯一の駆動点**: 生成スクリプト (``scripts/generate_golden_csv.py``) と照合
テスト (``tests/test_golden_csv.py``) の両方が ``export_case()`` を呼ぶ。
片方だけが知っている経路を作らないことで「生成したときと違う条件で比較する」
事故を構造的に消す。

**共有ヘルパに依存しない**: mf4 fixture は ``tests/mdf4_helpers.py`` を使わず
本モジュール内で完結させる。共有ヘルパは他タスクが自由に書き換える対象で、
そこに依存するとゴールデンが**無関係な編集で赤くなる** = 凍結の意味が消える。

**セル値は f(j, i) の単射** (spec §7.1 [I11])。列定数 f(j) だと searchsorted の
オフバイワンや行シフトでバイトが変わらず、オラクルが構造的に盲目になる。

**asammdf 依存の明示**: g08/g11 は実ローダーを通す。asammdf のラウンドトリップ
挙動 (2-D uint8 の列展開・TABX の生値保持) が変わればこの 2 本が RED になる。
それは誤検知ではなく**実挙動の変化**なので、RED になったらまずファイルを
読み戻して値を直接確認してから判断すること (ゴールデンの再生成で黙らせない)。

**ヘッダの駆動形 (MG-7)**: 主系 10 本は GUI と同じ導出形
(``csv_header_names`` → ``options.header_names``・
``gui/views/export_csv_dialog.py:792-793`` と同一) で凍結する。ユーザーが実際に
見る形とゴールデンを一致させるため。g02 だけが passthrough (raw namespaced 名)
で、``Session.export_csv`` 直呼びの既定バイトを凍結する — Task 4 の
``header_resolver`` 既定 (passthrough) がこれを再現しなければならない。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from valisync.core.export.csv_exporter import CsvExporter, CsvExportOptions
from valisync.core.models import Signal
from valisync.core.session import Session
from valisync.gui.display_names import csv_header_names

#: コミット済みゴールデンの置き場 (このファイルからの相対で解決する)。
GOLDEN_DIR = Path(__file__).resolve().parent / "golden_csv"

#: Task 7 が block_cols を導入したら「複数ブロックでも同じバイト」を駆動する
#: ための変種。T-G 時点では 1 ブロック相当の (None,) のみ。
#: test_block_cols_handoff_is_not_forgotten がこの定数と __init__ の signature の
#: 同期を強制する (spec G1)。
BLOCK_COLS_VARIANTS: tuple[int | None, ...] = (None,)


# ─── 値の生成規則 ─────────────────────────────────────────────────────────────


def cell(j: int, i: int) -> float:
    """列 j (出力の値列 0 始まり)・行 i で**一意**な値。

    ``(j+1)*1000 + i`` は j < 100・i < 1000 の範囲で単射。列を入れ替えても行を
    ずらしても必ずバイトが変わる (列定数だとどちらにも盲目)。
    """
    return (j + 1) * 1000.0 + i


def cell_frac(j: int, i: int) -> float:
    """``cell`` の 1/3 ずらし版 — shortest round-trip repr (17 桁) を凍結する。

    ``1000.3333333333333`` のような repr が固まるので、``repr`` を ``str`` や
    numpy のベクトル化書式へ替える変更 (spec C-4 が禁じている) が必ず露見する。
    """
    return (j + 1) * 1000.0 + i / 3.0


def _cumulative(start: float, step: float, n: int) -> np.ndarray:
    """``start`` から ``step`` を**逐次加算**した float64 時刻列。

    ULP 分裂 (spec §5.4) は逐次加算でしか出ない: ``5.0 + 3*0.1`` は 5.3 だが
    ``((5.0+0.1)+0.1)+0.1`` は 5.300000000000001 になる。実 CANape の 10ms/100ms
    ラスタが分裂するのはこの機序なので、fixture も逐次加算で作る。
    """
    out = [start]
    for _ in range(n - 1):
        out.append(out[-1] + step)
    return np.array(out, dtype=np.float64)


def _sig(
    key: str,
    ts: Sequence[float] | np.ndarray,
    vs: Sequence[float] | np.ndarray,
    unit: str | None = "",
    *,
    unit_present: bool = True,
) -> Signal:
    """名前空間つきキーを ``name`` に持つ Signal (production と同じ形)。

    ``unit_present=False`` は metadata にキー自体を置かない (欠落) ケース。
    ``unit=None`` は「キーはあるが値が None」= spec §9-6 のケース。
    """
    metadata: dict[str, object] = {}
    if unit_present:
        metadata["unit"] = unit
    return Signal(
        name=key,
        timestamps=np.asarray(ts, dtype=np.float64),
        values=np.asarray(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata=metadata,
    )


def _noop() -> None:
    return None


# ─── ケースの型 ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GoldenInput:
    """1 ケースの export 入力一式。"""

    signals: list[Signal]
    #: 出力列順 = この順。``signal.name`` と 1:1 で一致すること (ヘッダと値を
    #: 同じキーから導出する契約・spec §10)。
    keys: tuple[str, ...]
    use_unified_timeline: bool
    options: CsvExportOptions
    #: True = GUI と同じ csv_header_names 導出形 / False = passthrough (raw keys)。
    derive_headers: bool = True
    #: mf4 ハンドルを閉じるなど、export 後に必ず走らせる後始末。
    close: Callable[[], None] = field(default=_noop)


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    build: Callable[[Path], GoldenInput]
    #: このケースが**単独で**守っている軸 (照合失敗時に読む人が最初に見る行)。
    why: str


def build_options(inp: GoldenInput) -> CsvExportOptions:
    """GUI (export_csv_dialog.py:792-793) と**同一手順**で header_names を埋める。"""
    if not inp.derive_headers:
        return inp.options
    header_map = csv_header_names(inp.keys)
    return replace(inp.options, header_names=tuple(header_map[k] for k in inp.keys))


def export_case(
    case: GoldenCase, work_dir: Path, block_cols: int | None = None
) -> bytes:
    """1 ケースを現行 API で駆動して出力バイトを返す。

    生成器とテストが**この関数だけ**を共有する。ここに入力を組む処理と export
    呼び出しを閉じ込めることで、「生成時は unified・照合時は shared」のような
    ずれが起こりえなくなる。

    ``block_cols`` (I2): T-G 時点では ``None`` のみが渡る (生成器も既定呼び出しも
    未指定)。Task 7 が ``BLOCK_COLS_VARIANTS`` を複数値へ広げた瞬間、ここで
    ``CsvExporter(block_cols=block_cols)`` を呼ぶ経路が生きて **TypeError** で
    落ちる (今日の ``CsvExporter.__init__`` は ``block_cols`` を受け付けない) —
    driver 側の追随を強制する仕掛けそのもの (``test_block_cols_handoff_is_not_forgotten``
    と対になる)。
    """
    inp = case.build(work_dir)
    try:
        out = work_dir / f"{case.case_id}.csv"
        exporter = (
            CsvExporter() if block_cols is None else CsvExporter(block_cols=block_cols)
        )
        exporter.export(inp.signals, out, inp.use_unified_timeline, build_options(inp))
        return out.read_bytes()
    finally:
        inp.close()


# ─── ケース定義 ───────────────────────────────────────────────────────────────


_BASIC_KEYS = ("mf4_1::VehSpd", "mf4_1::EngSpeed", "mf4_1::Brake")
_BASIC_TS = [0.0, 0.5, 1.0, 1.5, 2.0]


def _basic_signals() -> list[Signal]:
    return [
        _sig(k, _BASIC_TS, [cell_frac(j, i) for i in range(len(_BASIC_TS))])
        for j, k in enumerate(_BASIC_KEYS)
    ]


def _build_shared_basic(_work: Path) -> GoldenInput:
    return GoldenInput(
        signals=_basic_signals(),
        keys=_BASIC_KEYS,
        use_unified_timeline=False,
        options=CsvExportOptions(),
    )


def _build_shared_passthrough_headers(_work: Path) -> GoldenInput:
    return GoldenInput(
        signals=_basic_signals(),
        keys=_BASIC_KEYS,
        use_unified_timeline=False,
        options=CsvExportOptions(),
        derive_headers=False,
    )


_GAP_KEYS = ("mf4_1::A", "mf4_1::B", "mf4_1::C")


def _gap_signals() -> list[Signal]:
    # 3 本のラスタをずらして union に穴を作り、そこへ NaN/±inf を重ねる。
    # t=1.0 の行は「A=正常値・B=NaN・C=-inf」= 欠測と非有限が同一バイトになる
    # ことをファイル上で示す唯一の行。
    return [
        _sig(_GAP_KEYS[0], [0.0, 1.0, 2.0], [cell(0, 0), cell(0, 1), cell(0, 2)]),
        _sig(_GAP_KEYS[1], [0.5, 1.0, 1.5], [cell(1, 0), float("nan"), float("inf")]),
        _sig(_GAP_KEYS[2], [1.0, 2.0], [float("-inf"), cell(2, 1)]),
    ]


def _build_unified_gaps_nonfinite(_work: Path) -> GoldenInput:
    return GoldenInput(
        signals=_gap_signals(),
        keys=_GAP_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(),
    )


def _build_unified_range_closed(_work: Path) -> GoldenInput:
    # g03 と同じ信号を [0.5, 1.5] で閉区間フィルタ。両端がちょうどサンプル上に
    # 乗るので、`>=`->`>` / `<=`->`<` の変異と ±1 サンプルのずれが必ず出る。
    return GoldenInput(
        signals=_gap_signals(),
        keys=_GAP_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(time_start=0.5, time_end=1.5),
    )


_QUOTE_KEYS = (
    "mf4_1::a,b",
    'mf4_1::say "hi"',
    "mf4_1::line\nbreak",
    "mf4_1::車速",
    "mf4_1::plain",
)


def _build_quoting_japanese_units(_work: Path) -> GoldenInput:
    ts = [0.0, 1.0]
    units: list[tuple[str | None, bool]] = [
        ("m,s", True),  # 単位に区切り文字 (単位行のクォート)
        ('in"ch', True),  # 単位に二重引用符
        (None, True),  # spec §9-6: キーはあるが None
        ("km/h", True),
        (None, False),  # キー欠落 (従来の既定 "")
    ]
    signals = [
        _sig(
            key,
            ts,
            [cell(j, i) for i in range(len(ts))],
            unit=u,
            unit_present=present,
        )
        for j, (key, (u, present)) in enumerate(zip(_QUOTE_KEYS, units, strict=True))
    ]
    return GoldenInput(
        signals=signals,
        keys=_QUOTE_KEYS,
        use_unified_timeline=False,
        options=CsvExportOptions(unit_row=True),
    )


_OPT_KEYS = ("mf4_1::spd", "mf4_1::rpm")


def _build_semicolon_precision_units(_work: Path) -> GoldenInput:
    ts = [0.0, 1.0]
    signals = [
        _sig(_OPT_KEYS[0], ts, [cell_frac(0, 0), float("nan")], unit="km/h"),
        _sig(_OPT_KEYS[1], ts, [cell_frac(1, 0), cell_frac(1, 1)], unit="1/min"),
    ]
    # decimal="," のセル (1000,333) が **クォートされない** ことと、precision 分岐の
    # NaN が空セルになることを 1 本で凍結する。
    return GoldenInput(
        signals=signals,
        keys=_OPT_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(
            delimiter=";", decimal=",", precision=3, unit_row=True
        ),
    )


_ULP_KEYS = ("mf4_1::fast", "mf4_1::slow")


def _build_unified_ulp_split(_work: Path) -> GoldenInput:
    # 10ms x 51 点 と 100ms x 6 点。数学的には slow ⊂ fast だが、逐次加算の
    # 丸めで一致するのは t=5.0 だけ → union は 51 + 5 = 56 行に分裂する
    # (spec §5.4 の「今日すでに分裂している」の最小再現)。
    fast_ts = _cumulative(5.0, 0.01, 51)
    slow_ts = _cumulative(5.0, 0.1, 6)
    signals = [
        _sig(_ULP_KEYS[0], fast_ts, [cell(0, i) for i in range(len(fast_ts))]),
        _sig(_ULP_KEYS[1], slow_ts, [cell(1, i) for i in range(len(slow_ts))]),
    ]
    return GoldenInput(
        signals=signals,
        keys=_ULP_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(),
    )


#: g07 の union 行数 (= データ行数)。実測値 (Step 3 で生成時に確認)。
#: 「分裂の行数まで凍結する」(spec §7.1) を、バイト差分を読まずに一目で
#: 分かる形にしておくための独立オラクル。
ULP_EXPECTED_ROWS = 56


def _write_golden_mdf4_dedup_enum(path: Path) -> Path:
    """同名 2-D uint8 x2 (dedup) + enum + 通常 の mf4。

    ローダー実測 (asammdf 8.8.22):
      mf4_1::W[0][0] = [0,2,4,6] / mf4_1::W[0][1] = [1,3,5,7]
      mf4_1::W[1][0] = [100,102,104,106] / mf4_1::W[1][1] = [101,103,105,107]
      mf4_1::Enum = [0.0,1.0,2.0,3.0] / mf4_1::Clean = [1.5,2.5,3.5,4.5]

    2-D は **uint8 でなければ往復しない** (float64 の 2-D は (N,w) -> (N,) へ
    潰れる — mdf4_helpers.py の同旨の注記)。値が 0-255 に制限されるので
    ``cell()`` は使えず、``base + 2*i + j`` の単射規則を使う。
    enum の samples を [0,1,2,3] にしてあるのは、[0,1,2,1] だと列内に重複が
    出て行シフトに鈍感になるため。
    """
    from asammdf import MDF
    from asammdf import Signal as ASignal
    from asammdf.blocks.conversion_utils import from_dict

    ts = np.array([0.0, 0.1, 0.2, 0.3], dtype=np.float64)
    mdf = MDF()
    try:
        for base in (0, 100):
            samples = np.array(
                [[base + 2 * i + j for j in range(2)] for i in range(4)],
                dtype=np.uint8,
            )
            mdf.append([ASignal(samples=samples, timestamps=ts, name="W", unit="m")])
        conv = from_dict(
            {
                "val_0": 0,
                "text_0": "S0",
                "val_1": 1,
                "text_1": "S1",
                "val_2": 2,
                "text_2": "S2",
                "val_3": 3,
                "text_3": "S3",
            }
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([0, 1, 2, 3], dtype=np.int16),
                    timestamps=ts,
                    name="Enum",
                    conversion=conv,
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.5, 2.5, 3.5, 4.5]),
                    timestamps=ts,
                    name="Clean",
                    unit="km/h",
                )
            ]
        )
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


_DEDUP_LEAVES = ("W[0][0]", "W[0][1]", "W[1][0]", "W[1][1]", "Enum", "Clean")


def _build_mdf_dedup_enum_columns(work: Path) -> GoldenInput:
    path = _write_golden_mdf4_dedup_enum(work / "golden_dedup_enum.mf4")
    session = Session()
    group_key = session.load(path).key
    assert group_key == "mf4_1", f"グループキーが想定外: {group_key}"
    keys = tuple(f"{group_key}::{leaf}" for leaf in _DEDUP_LEAVES)
    signals: list[Signal] = []
    for k in keys:
        sig = session.resolve_signal(k)
        assert sig is not None, f"列キーが解決できない: {k}"
        signals.append(sig)
    return GoldenInput(
        signals=signals,
        keys=keys,
        use_unified_timeline=False,
        options=CsvExportOptions(unit_row=True),
        # 遅延読み (LazyMdfValues) なので export が終わるまでハンドルを開けておく。
        # force=True は「Derived の依存が無いか」の判定を飛ばすため (この Session
        # は本ケース専用で Derived を持たない)。閉じないと tmp_path の後始末が
        # Windows で失敗する。
        close=lambda: session.remove_group(group_key, force=True),
    )


_EDGE_KEYS = ("mf4_1::empty", "mf4_1::messy", "mf4_1::clean")


def _build_unified_len0_nonmonotonic(_work: Path) -> GoldenInput:
    signals = [
        # LD-09 のヘッダのみ CSV 相当。素朴な searchsorted 実装は IndexError に
        # なる (spec §5.4 [M-4]) ので、現行の出力を先に凍結しておく。
        _sig(_EDGE_KEYS[0], [], []),
        # 非単調 + 重複。sorted_view は同時刻で **最後に記録された値** を残す
        # (CAN の last received wins) — t=1.0 の値が cell(1,3) になる。
        _sig(
            _EDGE_KEYS[1],
            [0.0, 2.0, 1.0, 1.0],
            [cell(1, 0), cell(1, 1), cell(1, 2), cell(1, 3)],
        ),
        _sig(_EDGE_KEYS[2], [0.0, 1.0, 2.0], [cell(2, i) for i in range(3)]),
    ]
    return GoldenInput(
        signals=signals,
        keys=_EDGE_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(),
    )


_SOLO_KEYS = ("mf4_1::solo",)


def _build_shared_single_column_range(_work: Path) -> GoldenInput:
    ts = [0.0, 1.0, 2.0, 3.0]
    return GoldenInput(
        signals=[_sig(_SOLO_KEYS[0], ts, [cell(0, i) for i in range(len(ts))])],
        keys=_SOLO_KEYS,
        use_unified_timeline=False,
        options=CsvExportOptions(time_start=1.0, time_end=2.0),
    )


def _write_golden_mdf4_plain(
    path: Path, channels: list[tuple[str, list[float], list[float], str]]
) -> Path:
    """1 チャンネル 1 グループの素の mf4 (g11 用・float64 のみ)。"""
    from asammdf import MDF
    from asammdf import Signal as ASignal

    mdf = MDF()
    try:
        for name, ts, vs, unit in channels:
            mdf.append(
                [
                    ASignal(
                        samples=np.asarray(vs, dtype=np.float64),
                        timestamps=np.asarray(ts, dtype=np.float64),
                        name=name,
                        unit=unit,
                    )
                ]
            )
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def _build_unified_cross_file_collision(work: Path) -> GoldenInput:
    """2 ファイルに同名 ``Spd`` + 片方に文字どおり ``timestamp`` という名の信号。

    ``csv_header_names`` の 2 つの分岐を同時に踏む唯一のケース:
      - 別グループが同じ bare 名を持つ -> ``Spd(mf4_1)`` / ``Spd(mf4_2)``
      - 母集合に常設注入された "timestamp" と衝突 -> ``timestamp(mf4_1)``
    ファイルキー併記のヘッダは BOM を入れた動機そのもの (spec §5.1-2)。
    """
    ta = [0.0, 1.0, 2.0]
    tb = [0.5, 1.0, 1.5]
    p1 = _write_golden_mdf4_plain(
        work / "golden_cross_a.mf4",
        [
            ("Spd", ta, [cell(0, i) for i in range(3)], "km/h"),
            ("timestamp", ta, [cell(1, i) for i in range(3)], "s"),
        ],
    )
    p2 = _write_golden_mdf4_plain(
        work / "golden_cross_b.mf4",
        [("Spd", tb, [cell(2, i) for i in range(3)], "km/h")],
    )
    session = Session()
    k1 = session.load(p1).key
    k2 = session.load(p2).key
    assert (k1, k2) == ("mf4_1", "mf4_2"), f"グループキーが想定外: {k1}/{k2}"
    keys = (f"{k1}::Spd", f"{k1}::timestamp", f"{k2}::Spd")
    signals: list[Signal] = []
    for k in keys:
        sig = session.resolve_signal(k)
        assert sig is not None, f"列キーが解決できない: {k}"
        signals.append(sig)

    def _close() -> None:
        session.remove_group(k1, force=True)
        session.remove_group(k2, force=True)

    return GoldenInput(
        signals=signals,
        keys=keys,
        use_unified_timeline=True,
        options=CsvExportOptions(unit_row=True),
        close=_close,
    )


# ─── 被覆 (spec §7.1 の軸 x ケース。全組み合わせではなく被覆集合) ─────────────
#
# 全直積は 2(TL) x 2(範囲) x 13(その他の軸) = 実用的でない。各軸を最低 1 本、
# 相互作用が疑われる組 (範囲 x TL 種別・非有限 x precision・クォート x 単位行)
# だけを重ねて 11 本に畳んである。
#
# | 軸                                   | 被覆ケース                          |
# |--------------------------------------|-------------------------------------|
# | 単一 (shared) タイムライン            | g01 g02 g05 g08 g10                 |
# | 統合 (unified) タイムライン           | g03 g04 g06 g07 g09 g11             |
# | 範囲なし                              | g01 g02 g03 g05 g06 g07 g08 g09 g11 |
# | 範囲あり (閉区間・両端がサンプル上)    | g04 (統合) / g10 (単一)             |
# | 欠測 (union の穴)                     | g03 g04 g07 g09 g11                 |
# | NaN                                   | g03 g04 g06                         |
# | ±inf                                  | g03 g04                             |
# | 要クォート名 (区切り/引用符/改行)      | g05                                 |
# | 日本語ヘッダ                          | g05                                 |
# | 重複名 dedup (W[0] 形)                | g08                                 |
# | enum                                  | g08                                 |
# | unit=None / キー欠落                  | g05                                 |
# | 単位行                                | g05 g06 g08 g11                     |
# | len 0 信号                            | g09                                 |
# | 非単調/重複 ts (last-wins)            | g09                                 |
# | ULP 分裂 (行数まで凍結)               | g07                                 |
# | shortest round-trip repr (17 桁)      | g01 g02 g07                         |
# | ヘッダ passthrough (raw namespaced)   | g02                                 |
# | ヘッダ GUI 形・衝突なし (bare)         | g01 g03-g10                         |
# | ヘッダ GUI 形・衝突あり (bare(group))  | g11                                 |
# | ヘッダ GUI 形・"timestamp" 母集合注入  | g11                                 |
# | 非既定 delimiter/decimal/precision     | g06                                 |
# | 1 列のみ                              | g10                                 |
# | 実ローダー経路 (遅延値・LazyMdfValues) | g08 g11                             |
#
# 単一 x 非既定オプションは g05 (単位行つき) が担う — g06 は統合側。
#
# **軸を持たない意図的な穴**:
# - 空選択: 現行は例外 (共有=IndexError / 統合=ValueError) なのでゴールデンに
#   できない。test_empty_selection_fails_loudly_and_writes_no_file が凍結する。
# - 複数ブロック (境界跨ぎ): T-G に block_cols が存在しない。
#   test_block_cols_handoff_is_not_forgotten が Task 7 へ強制する (spec G1)。
# - prod 規模 (330,004 列): ゴールデンの目的はバイト表現の凍結であって規模の
#   検証ではない。規模は G3/G4 (Task 11 の T-M) が担う。
#
# **T-G の sabotage で判明した穴 (意図ではなく発見・I1 レビューで是正)**:
# - **データ行のクォート適用サイトを守るゴールデンが T-G 時点では 1 本も無かった**。
#   ただし穴の広さは「実装者の主張 (現実的なオプションではクォートを要する
#   データセルが構造的に発生しない)」より**狭い** — I1 レビューで反証された:
#   ``delimiter='-'`` は ``__post_init__`` の合法な入力で、float の repr は
#   負値/指数表記で ``'-'``/``'+'`` を出すため、クォートを要するデータセルは
#   構成可能。**ドロップ方向 (クォートすべきセルを非クォートで出す) は既定
#   delimiter (数字の書式に現れない文字) の下でのみブラインド** — この方向は
#   ``tests/test_golden_csv.py::test_data_cells_are_quoted_when_the_delimiter_can_appear_in_a_number``
#   が唯一のオラクルとして塞ぐ。**過剰クォート方向 (クォート不要なセルまで
#   クォートする) は g06 が守る** (``_quote`` を常時クォートへハードコードする
#   変異=reviewer M11 で g06 が RED になることを実測済み)。
#   実測 (既定 delimiter 下): ``_rows_*_timeline`` の 2 サイトだけ ``_join`` を
#   素の ``delimiter.join`` へ落としても、ゴールデン 11 本 + 既存エクスポート系
#   65 本が**全緑**のまま (ヘッダ/単位行側だけを落とすと g05 が RED になるのと
#   対照的)。書き経路を再構築する Task 6/7 がデータ行のクォートを落としても、
#   既定 delimiter のケースだけでは誰も落ちない — 非既定 delimiter の単体テストと
#   g06 の両方を保つことがレビューでの担保点になる。
#   **サイトは 2 つあり片方ずつ独立にブラインドになりうる** (再レビュー実測:
#   unified 側の ``_join`` だけを落とすと当時の単体テストは shared 駆動のため
#   27 passed / RED ゼロ)。よって単体テストは shared/unified を parametrize で
#   両駆動する — 片翼だけのテストに戻す変更はこの穴の再導入。
GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        "g01_shared_basic",
        _build_shared_basic,
        "単一タイムライン・範囲なし・GUI 形ヘッダ・3 列。列順/ヘッダ対応/LF/BOM/"
        "最小クォート非適用/shortest repr の基準線",
    ),
    GoldenCase(
        "g02_shared_passthrough_headers",
        _build_shared_passthrough_headers,
        "header_names=None (passthrough) の raw namespaced ヘッダ。Task 4 の "
        "header_resolver 既定が再現すべきバイト (MG-7)",
    ),
    GoldenCase(
        "g03_unified_gaps_nonfinite",
        _build_unified_gaps_nonfinite,
        "統合タイムライン・欠測・NaN・±inf。欠測と非有限が同一バイトになる契約",
    ),
    GoldenCase(
        "g04_unified_range_closed",
        _build_unified_range_closed,
        "統合タイムライン + 閉区間 [0.5, 1.5]。両端がサンプル上に乗る境界",
    ),
    GoldenCase(
        "g05_quoting_japanese_units",
        _build_quoting_japanese_units,
        "要クォート名 3 種 (区切り/引用符/改行)・日本語・単位行・unit=None/欠落",
    ),
    GoldenCase(
        "g06_semicolon_precision_units",
        _build_semicolon_precision_units,
        "delimiter=';' + decimal=',' + precision=3 + 単位行 + precision 分岐の NaN",
    ),
    GoldenCase(
        "g07_unified_ulp_split",
        _build_unified_ulp_split,
        "ULP 分裂 (10ms x 51 と 100ms x 6 が 56 行へ分裂) — 行数まで凍結",
    ),
    GoldenCase(
        "g08_mdf_dedup_enum_columns",
        _build_mdf_dedup_enum_columns,
        "実 mf4 ロード経路: 重複名 dedup (W[0]/W[1]) + 2-D 列展開 + enum + 単位行",
    ),
    GoldenCase(
        "g09_unified_len0_nonmonotonic",
        _build_unified_len0_nonmonotonic,
        "len 0 信号 (M-4 の IndexError 予防) + 非単調/重複 ts の last-wins",
    ),
    GoldenCase(
        "g10_shared_single_column_range",
        _build_shared_single_column_range,
        "1 列のみ + 単一タイムライン + 範囲 [1.0, 2.0]。末尾余分区切りの検出",
    ),
    GoldenCase(
        "g11_unified_cross_file_collision",
        _build_unified_cross_file_collision,
        "2 ファイル同名 Spd と信号名 'timestamp' -> csv_header_names の衝突 2 分岐",
    ),
)
