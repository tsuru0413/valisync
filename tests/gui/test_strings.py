"""gui/strings.py — 文言 OS の基盤 (Layer A・Qt 非依存)。"""

import subprocess
import sys

from valisync.gui import strings


def test_mn_composes_mnemonic():
    assert strings.mn("補間方式", "I") == "補間方式(&I)"


def test_busy_templates_format_with_expected_placeholders():
    """G-41: BusyOverlay 実文言テンプレートが期待プレースホルダで format 可能 (spec §6)。"""
    assert strings.BUSY_LOADING_TMPL.format(label="a.mf4") == "a.mf4 を読み込み中…"
    assert strings.BUSY_LOADING_MULTI_TMPL.format(n=2) == "2 ファイルを読み込み中…"
    assert (
        strings.BUSY_EXPORTING_TMPL.format(label="out.csv")
        == "out.csv をエクスポート中…"
    )


def test_status_diag_templates_embed_ref_diagnostics():
    """判断点#13: 診断誘導メッセージが REF_DIAGNOSTICS を単一定数から合成する。"""
    alert = strings.STATUS_DIAG_ALERT_TMPL.format(n=1)
    info = strings.STATUS_DIAG_INFO_TMPL.format(n=2)
    assert alert == " ・ ⚠ 警告/エラー 1 件（「診断」ドックを参照）"
    assert info == " ・ ℹ 情報 2 件（「診断」ドックを参照）"
    assert strings.REF_DIAGNOSTICS in alert
    assert strings.REF_DIAGNOSTICS in info


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
