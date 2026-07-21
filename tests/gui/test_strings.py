"""gui/strings.py — 文言 OS の基盤 (Layer A・Qt 非依存)。"""

import subprocess
import sys

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
    """strings.py の Qt 非依存 (spec §2.1) の恒久ガード。

    fresh subprocess で valisync.gui.strings のみを import し、PySide6 が
    sys.modules に現れないことを検証する。既存プロセス内での検査は他テストが
    先に PySide6 を import 済みで常に真になり恒真化する (レビュー Important
    指摘) ため、隔離された fresh interpreter でしか意味を持たない
    (test_theme_apply.py の subprocess パターンと同型)。
    """
    code = (
        "import sys; "
        "import valisync.gui.strings; "
        "sys.exit(1 if 'PySide6' in sys.modules else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
