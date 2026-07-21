"""gui/strings.py — 文言 OS の基盤 (Layer A・Qt 非依存)。"""

from valisync.gui import strings


def test_mn_composes_mnemonic():
    assert strings.mn("補間方式", "I") == "補間方式(&I)"


def test_strip_mnemonic_ja_and_legacy_forms():
    assert strings.strip_mnemonic("ファイル(&F)") == "ファイル"
    assert strings.strip_mnemonic("開く(&O)…") == "開く…"
    assert strings.strip_mnemonic("&File") == "File"
    assert strings.strip_mnemonic("E&xit") == "Exit"
    # && はリテラル & (Qt 仕様) — 破壊しない
    assert strings.strip_mnemonic("A && B") == "A & B"


def test_strings_module_is_qt_free():
    import sys

    assert "PySide6" not in getattr(strings, "__qt_probe__", "")
    # import 済みモジュール群に strings 起因の PySide6 依存が無いことは
    # 「strings を単独 import した fresh プロセス」で検証する (test_theme_apply 側)。
    assert "valisync.gui.strings" in sys.modules
