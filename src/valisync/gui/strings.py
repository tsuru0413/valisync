# ruff: noqa: RUF002
"""GUI 文言の単一の真実 (増分D-1 文言 OS)。

- pure Python・Qt 非依存 (theme/tokens.py と同じ隔離方針)。
- 定数は日本語一次 (spec 2026-07-22-incd-strings-os-design.md §3 対訳表が出典)。
- ニーモニクスはメニューバー面のみ (G-46)。2面共有文言は素形定数＋mn() 合成。
"""

from __future__ import annotations

import re

_MNEMONIC_RE = re.compile(r"\(&[^)]\)")


def mn(text: str, key: str) -> str:
    """メニューバー掲載面のニーモニクス付与形を合成する (G-46 が割当の唯一の出典)。"""
    return f"{text}(&{key})"


def strip_mnemonic(text: str) -> str:
    """表示文言からニーモニクスを除いた素形 (テストの掴み点比較用)。"""
    text = _MNEMONIC_RE.sub("", text)
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")
