"""境界 API の keys 化と移行橋(E-4b Task 4・spec §5.2)。

橋は「keys を全解決して旧一括実装へ渡す」薄いアダプタで、Task 7 が撤去する。
本ファイルが固定するのは **境界の契約** であって橋の実装ではないので、
Task 7 で橋が消えてもそのまま生き残る設計にしてある(本ファイルの test 関数は
1 本も ``export_via_legacy_path`` / ``legacy_bridge`` を参照しない — すべて
``Session.export_csv`` 経由。橋の削除で import エラーになるテストは存在しない)。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.export.csv_exporter import (
    CsvExportOptions,
    ExportRequest,
    passthrough_header_names,
)
from valisync.core.models import Signal
from valisync.core.session import Session


def _derived(name: str, ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig").splitlines()


# ─── keys 経路(passthrough 既定) ────────────────────────────────────────────


def test_export_csv_writes_columns_in_key_order(tmp_path: Path) -> None:
    """出力列順 = keys の順(spec §10)。**逆順を渡すと逆順で出る**。

    「ヘッダと値は同じ keys から導出」の by-construction 性の直接検証でもあり、
    同時に「resolver 未指定の既定は passthrough」の**結合検証**でもある
    (`passthrough_header_names` 単体テストは関数を見るだけで、`export_csv` が
    実際にそれを既定に据えているかは語らない)。

    旧 API は signals と header_names を別々に運んでいて、header_names 指定時
    (GUI 経路)の対応崩しが無検出だった(C1/M7 — header_names=None の既存
    テスト 6 本は `signals.reverse()` を捕まえるが、header_names 指定時は
    無検出だった)。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "rev.csv"

    session.export_csv([f"{key}::Mat[2]", f"{key}::Mat[0]"], out)

    assert _read(out)[0] == f"timestamp,{key}::Mat[2],{key}::Mat[0]"


def test_passthrough_header_resolver_is_the_default(tmp_path: Path) -> None:
    """既定 resolver は list(keys) — 直呼びの現行ヘッダバイトを保存する。"""
    assert passthrough_header_names(["a::b", "c::d"]) == ["a::b", "c::d"]


def test_injected_header_resolver_drives_the_header_row(tmp_path: Path) -> None:
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "h.csv"

    session.export_csv(
        [f"{key}::Mat[0]"],
        out,
        header_resolver=lambda ks: [k.split("::", 1)[1] for k in ks],
    )

    assert _read(out)[0] == "timestamp,Mat[0]"


def test_header_resolver_length_mismatch_fails_loudly(tmp_path: Path) -> None:
    """resolver が keys と違う本数を返したら書かずに落ちる。

    ここを通すと「ヘッダと値がずれた CSV」が黙って出る — E-4b が構造的に
    根治しようとしている失敗そのものなので、橋の段でも検査する。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "bad.csv"

    with pytest.raises(ValueError, match="ヘッダ"):
        session.export_csv(
            [f"{key}::Mat[0]", f"{key}::Mat[1]"], out, header_resolver=lambda ks: ["x"]
        )
    assert not out.exists()


def test_unresolvable_key_fails_loudly_without_writing(tmp_path: Path) -> None:
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "missing.csv"

    with pytest.raises(ValueError, match="解決"):
        session.export_csv([f"{key}::NoSuchColumn"], out)
    assert not out.exists()


def test_empty_request_fails_loudly(tmp_path: Path) -> None:
    """keys も extra_signals も空なら書かずに落ちる(素の IndexError にしない)。"""
    out = tmp_path / "empty.csv"
    with pytest.raises(ValueError, match="1 つも"):
        Session().export_csv([], out)
    assert not out.exists()


# ─── Derived escape hatch(spec §5.2 [I-3]) ─────────────────────────────────


def test_extra_signals_carry_derived_signals_that_no_key_can_resolve(
    tmp_path: Path,
) -> None:
    """Derived は SignalGroupManager に登録されず keys で解決できない。

    ヘッダは Signal 自身の名前(keys 側の resolver は通さない)— 名前空間を
    持たないので resolver に渡す意味が無い。
    """
    out = tmp_path / "derived.csv"

    Session().export_csv([], out, extra_signals=[_derived("Plain", [0.0], [1.5])])

    assert _read(out)[0] == "timestamp,Plain"
    assert _read(out)[1] == "0.0,1.5"


def test_extra_signals_come_after_keys_in_column_order(tmp_path: Path) -> None:
    """列順は keys -> extra_signals(混ぜない)。

    GUI のツリーは `loaded_file_keys` しか列挙しないので Derived は今日
    選択に入らない。順序契約を先に固定しておかないと、後で Derived を
    載せた瞬間に列順が実装依存で決まる。

    extra の時間軸を Mat と**同一**にしてあるのは、既定 (共有タイムライン) の
    整合検査が先に ValueError を投げると、列順の主張がそもそも到達しないから
    (時間軸を揃えないと本テストは「順序が正しいか」ではなく「共有 TL 検査が
    生きているか」を測ってしまう)。

    **ヘッダ行だけを見てはならない** (S3 サボタージュの実測で判明): ヘッダ名は
    extra_signals の *名前* から作られるので、extra を**値の側から落とす**変異では
    ヘッダは正しいまま データ行だけが 1 列短くなる = ヘッダ行しか見ないテストは
    構造的に盲目になる (ヘッダと値がずれた CSV — E-4b が根治しようとしている
    失敗そのもの)。データ行も突き合わせて列数と対応の両方を縛る。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "mixed.csv"

    session.export_csv(
        [f"{key}::Mat[0]"],
        out,
        extra_signals=[
            _derived("Extra", [0.0, 0.1, 0.2, 0.3], [9.0, 9.5, 9.75, 9.875])
        ],
    )

    lines = _read(out)
    assert lines[0] == f"timestamp,{key}::Mat[0],Extra"
    # Mat[0] の列値は [0, 10, 20, 30] (mdf4_helpers の規則)、Extra は 9.0 始まり。
    assert lines[1] == "0.0,0.0,9.0"
    assert lines[2] == "0.1,10.0,9.5"


def test_extra_signals_are_still_container_checked(tmp_path: Path) -> None:
    """escape hatch はコンテナ拒否の抜け道にはならない。

    名前空間つき Signal を extra_signals へ入れて guard を迂回できると、
    「GUI を通らない直呼びを守る唯一の層」(E-3 C-d)が穴になる。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    parent = next(s for s in session.group_signals(key) if s.name == f"{key}::Mat")

    with pytest.raises(ValueError, match=r"Mat\[0\]"):
        session.export_csv([], tmp_path / "out.csv", extra_signals=[parent])


# ─── options.use_unified_timeline(M-1) ─────────────────────────────────────


def test_use_unified_timeline_travels_through_options(tmp_path: Path) -> None:
    """統合タイムラインは options 経由(共有インターフェース契約 M-1)。"""
    a = _derived("a", [0.0, 2.0], [10.0, 12.0])
    b = _derived("b", [1.0, 2.0], [21.0, 22.0])
    out = tmp_path / "u.csv"

    Session().export_csv(
        [],
        out,
        options=CsvExportOptions(use_unified_timeline=True),
        extra_signals=[a, b],
    )

    assert _read(out) == ["timestamp,a,b", "0.0,10.0,", "1.0,,21.0", "2.0,12.0,22.0"]


def test_positional_bool_as_options_is_refused(tmp_path: Path) -> None:
    """移行し損ねた呼び出し(第 3 引数に bool)を黙って options 扱いしない。

    `export_csv(keys, path, True)` は旧署名の use_unified_timeline のつもりで、
    新署名では options。dataclass でない bool が素通しされると
    `opts.delimiter` で AttributeError が出るだけで原因が分からない。
    """
    with pytest.raises(TypeError, match="use_unified_timeline"):
        Session().export_csv([], tmp_path / "x.csv", True)  # type: ignore[arg-type]


# ─── ExportRequest 自体 ──────────────────────────────────────────────────────


def test_export_request_is_frozen_and_defaults_extra_signals_empty() -> None:
    req = ExportRequest(
        keys=("a::b",),
        output_path=Path("x.csv"),
        options=CsvExportOptions(),
        header_resolver=passthrough_header_names,
    )
    assert req.extra_signals == ()
    # frozen dataclass への代入は FrozenInstanceError (AttributeError の派生)。
    # 裸の Exception で受けると「別の理由で落ちても緑」になる。
    with pytest.raises(FrozenInstanceError):
        req.keys = ()  # type: ignore[misc]
