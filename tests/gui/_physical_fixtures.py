"""反転後の production 形 (1 Signal = 1 物理チャンネル + 列名表) を注入する。

反転前は ``session.group_signals`` に **列 Signal** を並べれば済んだが、反転後の
production はそこに物理チャンネルしか置かず、列名は ColumnRecord 由来の
``Session.column_names_of`` から来る。偽物 session がその 2 面を揃えないと、
「今日の production では起きない形」を検証し続けることになる。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from valisync.core.models import Signal

# (物理チャンネル表示名, unit, 列名タプル)
Channel = tuple[str, str, tuple[str, ...]]


def physical_signal(key: str, display_name: str, unit: str, n_columns: int) -> Signal:
    """ローダーが反転後に発行する形の Signal 1 本。

    複数列のチャンネルは values も 2-D にする — 「親 Signal をそのままプロット/
    エクスポートへ流す」壊れ方が値の形として現れるようにするため (1-D の偽物に
    すると誤配線がテストを素通りする)。
    """
    values = np.zeros((1, n_columns)) if n_columns > 1 else np.zeros(1)
    return Signal(
        name=f"{key}::{display_name}",
        timestamps=np.array([0.0]),
        values=values,
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={"unit": unit, "physical_channel": display_name},
    )


def inject_physical_channels(
    app_vm: Any, key: str, channels: Sequence[Channel]
) -> list[Signal]:
    """*app_vm* の session を「反転後のローダー出力」で差し替える。

    group_signals は物理チャンネルのみ、column_names_of / total_column_count は
    ColumnRecord 由来の列名表 (Task 1 の Session API) を返す。
    """
    sigs = [
        physical_signal(key, name, unit, len(cols)) for name, unit, cols in channels
    ]
    columns = {name: cols for name, _unit, cols in channels}
    total = sum(len(cols) for cols in columns.values())
    app_vm.session.group_signals = lambda _k: list(sigs)  # type: ignore[method-assign]
    app_vm.session.column_names_of = lambda _k, display: columns[display]  # type: ignore[method-assign]
    app_vm.session.total_column_count = lambda _k: total  # type: ignore[method-assign]
    return sigs
