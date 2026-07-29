from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from valisync.core.models.signal_group import SignalGroup

if TYPE_CHECKING:
    # 実行時 import は循環する: core.models -> core.loaders.column_names は
    # パッケージ core.loaders の __init__ (csv_loader/mdf_loader) を起動し、
    # そこから core.models へ戻る。注釈は from __future__ で文字列化済み。
    from valisync.core.loaders.column_names import ColumnRecord


@dataclass(frozen=True)
class Diagnostic:
    """Single diagnostic message from a load operation."""

    level: str  # "error" | "warning" | "info"
    message: str
    line_number: int | None = None
    column_number: int | None = None
    signal_name: str | None = None
    sample_index: int | None = None

    def __post_init__(self) -> None:
        if self.level not in ("error", "warning", "info"):
            raise ValueError(
                f"level must be 'error', 'warning' or 'info', got {self.level!r}"
            )


@dataclass(frozen=True)
class LoadResult:
    """Result of a file load operation."""

    signal_group: SignalGroup | None
    diagnostics: tuple[Diagnostic, ...] = ()
    # E-3: 列鋳造の材料 {LD-08 dedup 済み表示名: ColumnRecord}。ローダーが 1 レコード
    # プローブから作り、Session が SignalGroupManager へ引き渡す。列構造を持たない
    # CSV は空のまま (1 信号 1 列として扱われる)。
    column_records: Mapping[str, ColumnRecord] = field(default_factory=dict)


class LoadCancelled(Exception):
    """Raised when a load is cancelled via the cooperative ``cancel`` callback.

    User-initiated: callers must NOT surface this as an error (no modal, no
    diagnostics entry) — see spec §4.1/§6.

    Defined here (not in session.py) to avoid a circular import: loaders need
    to raise it but must not import from session, which imports the loaders.
    """
