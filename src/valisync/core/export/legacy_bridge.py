"""T-API の移行橋 (E-4b spec §5.2 [plan-4] — **Task 7 がこのファイルごと削除する**)。

境界 API を keys 化する Task 4 と、列ブロック x 行ストリームで実際に書く
Task 6/7 の間を埋める薄いアダプタ。keys を **全部** 解決してから旧一括実装
(``CsvExporter.export(signals, ...)``) へ渡すので、メモリ挙動は Task 4 の時点では
**現状のまま** (改善しない) — 改善は Task 6/7 の仕事で、Task 4 の仕事は
「境界が動いても出力バイトが 1 バイトも動かない」ことを橋で証明することにある。

独立ファイルにしてあるのは、撤去が **ファイルの削除** という構造的に検証可能な
操作になるから (``grep -rn legacy_bridge src/`` が 0 件になれば撤去完了)。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from valisync.core.export.csv_exporter import (
    EXPORT_EMPTY_REQUEST_ERROR,
    EXPORT_HEADER_LENGTH_ERROR_TMPL,
    EXPORT_UNRESOLVED_KEYS_ERROR_TMPL,
    CsvExporter,
    ExportRequest,
)
from valisync.core.models import Signal


def export_via_legacy_path(
    request: ExportRequest, resolve: Callable[[str], Signal | None]
) -> None:
    """*request* の keys を全解決し、旧一括実装で書き出す。

    ヘッダは ``request.header_resolver(request.keys)`` から、値は同じ keys から
    解決した Signal から作る — **同じ列から両方を導出する**のが保存すべき契約
    (spec §10)。extra_signals は末尾に連結し、ヘッダは Signal 自身の名前を使う
    (名前空間を持たないので resolver に渡す意味が無い)。
    """
    resolved: list[Signal] = []
    missing: list[str] = []
    for key in request.keys:
        sig = resolve(key)
        if sig is None:
            missing.append(key)
        else:
            resolved.append(sig)
    if missing:
        raise ValueError(
            EXPORT_UNRESOLVED_KEYS_ERROR_TMPL.format(n=len(missing), name=missing[0])
        )

    header = list(request.header_resolver(request.keys))
    if len(header) != len(request.keys):
        raise ValueError(
            EXPORT_HEADER_LENGTH_ERROR_TMPL.format(
                got=len(header), want=len(request.keys)
            )
        )

    signals = [*resolved, *request.extra_signals]
    if not signals:
        raise ValueError(EXPORT_EMPTY_REQUEST_ERROR)
    names = (*header, *(s.name for s in request.extra_signals))

    # header_names は Task 4 時点の旧 CsvExporter への **唯一の** ヘッダ搬送路。
    # Task 7 で `CsvExporter.export(request, resolve, ...)` へ移ると、この
    # replace ごと消える (フィールド自体の撤去可否は Task 7 が判断する)。
    opts = replace(request.options, header_names=names)
    CsvExporter().export(
        signals, request.output_path, request.options.use_unified_timeline, opts
    )
