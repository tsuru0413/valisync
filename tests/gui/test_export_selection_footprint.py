"""`_selected` の圧縮 (E-4b spec §5.6) を構造とバイトの両方で固定する。

構造テスト (エントリ数 = **行数**) は scale-free な本命で、バイト比テストは
「畳み込みを外す」形の退行 (ALL を PARTIAL(range(count)) で持つ) を捕まえる。
どちらか片方だけでは不十分: 構造だけだと PARTIAL 退行が緑、バイトだけだと
Python のバージョン差でしきい値が揺れる。

prod (4,324 行 / 330,004 列 / 実測 54-57 MB) はここでは再現しない — 合成でも
比は線形に効くので、CI では 100 行 / 50,000 列で十分に決定的。prod 1 点の実測は
別途 (demo_data がある環境でのみ) 行う (spec §9-1)。
"""

from __future__ import annotations

import sys

import numpy as np
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Signal
from valisync.gui.views.export_csv_dialog import _ALL, ExportCsvDialog

_ROWS = 100
_COLS_PER_ROW = 500  # 100 x 500 = 50,000 列


def _deep_size(obj: object, seen: set[int] | None = None) -> int:
    """dict/tuple/frozenset/set/str/int を再帰した実バイト (共有は 1 度だけ数える)。

    共有を id で畳むのが要点: ALL の共有インスタンスや、`_rows` と `_selected` が
    共有する選択キー文字列を二重計上すると、圧縮の効果が見かけ上消える。
    """
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return 0
    seen.add(id(obj))
    size = sys.getsizeof(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            size += _deep_size(k, seen) + _deep_size(v, seen)
    elif isinstance(obj, (tuple, list, set, frozenset)):
        for item in obj:
            size += _deep_size(item, seen)
    elif hasattr(obj, "__slots__"):
        for name in obj.__slots__:  # type: ignore[attr-defined]
            size += _deep_size(getattr(obj, name), seen)
    return size


class _WideSession:
    def __init__(self) -> None:
        self._phys = [f"Ch{i:04d}" for i in range(_ROWS)]
        self._names = {
            p: tuple(f"{p}[{j}]" for j in range(_COLS_PER_ROW)) for p in self._phys
        }

    def source_name(self, key: str) -> str:
        return "wide.mf4"

    def group_signals(self, key: str) -> list[Signal]:
        return [
            Signal(
                name=f"mf4_1::{p}",
                timestamps=np.array([0.0]),
                values=np.array([1.0]),
                file_format="MDF4",
                bus_type="",
                source_file="",
                metadata={"physical_channel": p},
            )
            for p in self._phys
        ]

    def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]:
        return self._names.get(display_name, (display_name,))

    def has_column(self, key: str, display_name: str) -> bool:
        return display_name not in self._names

    def resolve_signal(self, key: str) -> Signal | None:
        return None


class _WideAppVM:
    def __init__(self) -> None:
        self.session = _WideSession()
        self.loaded_file_keys = ["mf4_1"]


def test_select_all_keeps_one_entry_per_channel_row_not_per_column(
    qtbot: QtBot,
) -> None:
    """本命 (scale-free): 「すべて選択」のエントリ数は **行数**。

    旧形は列数ぶん (50,000) 持っていた。列数に比例する実装はこの 1 本で落ちる。
    """
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)

    dlg._select_all()

    assert len(dlg._selected) == _ROWS
    assert dlg.selected_count() == _ROWS * _COLS_PER_ROW
    assert len(dlg._checked_keys()) == _ROWS * _COLS_PER_ROW


def test_select_all_footprint_is_orders_below_the_per_column_dict(
    qtbot: QtBot,
) -> None:
    """バイト比: 旧形 (列ごとの `dict[str, tuple[int, int]]`) と実測で比べる。

    旧形を実際に組んで比べるのは、「比が桁で効く」ことを主張でなく実測で示す
    ため (推定値で書くと Python のバージョン差で意味が変わる)。
    """
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)
    dlg._select_all()

    new_bytes = _deep_size(dlg._selected)
    legacy = {
        key: (r, c) for r in range(_ROWS) for c, key in enumerate(dlg._column_keys(r))
    }
    legacy_bytes = _deep_size(legacy)

    print(f"[footprint] legacy={legacy_bytes:,} B  compressed={new_bytes:,} B")
    assert legacy_bytes // max(new_bytes, 1) >= 50, (
        f"圧縮比が想定を下回る: legacy={legacy_bytes} compressed={new_bytes}"
    )
    assert new_bytes < 1_000_000, f"50,000 列で {new_bytes} B は圧縮が効いていない"


def test_all_rows_share_one_selection_object(qtbot: QtBot) -> None:
    """ALL は行ごとに作らず共有する (`_ALL` シングルトン)。

    行ごとに `ColumnSelection(is_all=True)` を作る実装は上のバイト比を通って
    しまう (オブジェクトは小さい) ので、同一性で直接 pin する。
    """
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)
    dlg._select_all()

    values = list(dlg._selected.values())
    assert len({id(v) for v in values}) == 1


def test_unchecking_one_column_does_not_inflate_the_other_rows(
    qtbot: QtBot,
) -> None:
    """1 列外しても PARTIAL になるのは **その行だけ** (全行 PARTIAL 化の退行検出)。"""
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)
    dlg._select_all()

    dlg._drop_selection(0, 3, dlg._column_keys(0)[3])

    partial = [k for k, v in dlg._selected.items() if not v.is_all]
    assert len(partial) == 1
    assert dlg.selected_count() == _ROWS * _COLS_PER_ROW - 1
    # Minor 5 (task-3-review.md): 上の `selected_count()` は `_total` という
    # 並走カウンタで、PARTIAL 状態でも実際の展開 (`_checked_keys()`) と一致する
    # ことまでは確認していなかった (カウンタ側だけがずれる退行を見逃す穴)。
    assert len(dlg._checked_keys()) == _ROWS * _COLS_PER_ROW - 1


def test_checking_every_column_individually_folds_back_to_all(qtbot: QtBot) -> None:
    """個別チェックで全列そろったら ALL へ畳む (S2 で予測外だった穴を塞ぐ)。

    `_select_all` / ファイル行は `_select_row_all` が直に `_ALL` を置くので、
    `_add_selection` の畳み込みを **一切通らない**。畳み込みを外した実装
    (常に `ColumnSelection(False, merged)`) は上の 4 本すべてを緑で通過し、
    「列を 1 本ずつ全部チェックしたユーザー」だけが旧形と同じ列数ぶんの int を
    抱える — つまり圧縮が一括経路にしか効かない退行が無検出になる。
    ここは `_add_selection` を **列ごとに** 通す唯一の経路。
    """
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())  # type: ignore[arg-type]
    qtbot.addWidget(dlg)

    keys = dlg._column_keys(0)
    for col_index, key in enumerate(keys):
        dlg._add_selection(0, col_index, key)

    sel = dlg._selected[dlg._rows[0].sel_key]
    assert sel is _ALL  # 共有シングルトンへ畳む (行ごとの新規生成でもない)
    assert sel.indices == frozenset()  # 畳んだ ALL は index を 1 個も抱えない
    assert dlg.selected_count() == _COLS_PER_ROW
