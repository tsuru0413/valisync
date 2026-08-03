"""エクスポート確認ダイアログの本文と閾値判定 (pure・E-4b B2)。

QMessageBox の組み立ては ``MainWindow._default_confirm_export`` が行い、ここは
「何を見せるか」だけを持つ — file_browser_view の ``_default_confirm`` /
``_confirm_fn`` と同じ分離 (spec §5.5 [I15/ux-A])。pure なので Qt 無しでテストできる。
"""

from __future__ import annotations

from valisync.core.export.estimate import CONFIRM_THRESHOLD_S, ExportEstimate
from valisync.gui import strings as S
from valisync.gui.formatting import format_duration
from valisync.gui.viewmodels.file_browser_vm import _fmt_size


def needs_confirmation(est: ExportEstimate) -> bool:
    """確認を出すか。**推定時間ベース** (spec I10)。

    サイズ基準にすると「カーソル A-B x 全列」(出力 2 KB・読み 6.5 s) が素通りし、
    進捗もキャンセルも無いまま固まる。読み項と書き項を足すのは、どちらか一方でも
    支配しうるため (読み支配 = 範囲指定 x 全列 / 書き支配 = 全期間 x 全列)。
    """
    return (est.est_read_s + est.est_write_s) >= CONFIRM_THRESHOLD_S


def confirm_body(est: ExportEstimate) -> str:
    """B2 の 5 点。正確値と推定値を文言で区別する (「推定」の 2 文字が唯一の目印)。

    spec §5.5 の文言例からの **意図的逸脱が 2 点**ある (どちらも D-1 文言 OS 側が
    優先):
    1. 「約 66 %」— 例は「約 66%」だが R-06 (数値と単位の間に半角スペース) を採る。
    2. 「〜を書き出します。」— R-08 の確認形 (「〜しますか」+ 全角疑問符) でなく
       平叙形。動詞はボタン (`EXPORT_CONFIRM_YES` = 「書き出す」) が担う規約
       (`CONFIRM_CLOSE_YES` と同型) なので、本文を疑問形にすると本文とボタンで
       動詞が二重になる。
    """
    return S.EXPORT_CONFIRM_BODY_TMPL.format(
        columns=est.columns,
        rows=est.rows,
        size=_fmt_size(est.est_bytes),
        duration=format_duration(est.est_read_s + est.est_write_s),
        empty=round(est.empty_ratio * 100),
    )
