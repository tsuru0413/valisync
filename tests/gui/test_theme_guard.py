"""色ハードコード再混入ガード (常設 Layer A・spec §7)。

src/valisync/gui/ (theme/ 除く) の AST を走査し、色直書き
(hex 文字列・rgba(/rgb(/hsl( 構文・QColor リテラル引数・Qt.GlobalColor)
を検出して fail する。コメント/docstring は対象外 (AST ベースの理由)。
正当な構造色 (デザイン色でないもの・spec §4.1) は _ALLOWLIST で管理。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_GUI = Path(__file__).resolve().parents[2] / "src" / "valisync" / "gui"

# (相対 path, 行内一致パターン, 理由) — 行パターン ratchet (spec §6):
# ファイル単位だと同一ファイル内の新規違反を隠すため、行内容で絞る。
# どこにも一致しなくなったエントリは陳腐化として fail する。
_ALLOWLIST: tuple[tuple[str, str, str], ...] = (
    (
        "views/cursor_shapes.py",
        "Qt.GlobalColor.transparent",
        "QPixmap 初期化の構造色 — デザイン色でない (spec §4.1)",
    ),
    (
        "views/cursor_shapes.py",
        "QColor(255, 255, 255)",
        "カーソル bitmap の白ハロー — OS カーソル慣行の構造色 (spec §4.1)",
    ),
    (
        "views/cursor_shapes.py",
        "QColor(0, 0, 0)",
        "カーソル bitmap の黒線 — 同上",
    ),
)

_COLOR_STR = re.compile(r"#[0-9a-fA-F]{6}\b|rgba?\(|hsla?\(")


def _iter_py_files() -> list[Path]:
    return [
        p
        for p in sorted(SRC_GUI.rglob("*.py"))
        if "theme" not in p.relative_to(SRC_GUI).parts
    ]


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _violations_in(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    doc_ids = _docstring_ids(tree)
    lines = source.splitlines()
    found: list[tuple[int, str]] = []

    def line_of(node: ast.AST) -> str:
        return lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in doc_ids
            and _COLOR_STR.search(node.value)
        ):
            found.append((node.lineno, line_of(node)))
        if isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
            if name == "QColor" and any(isinstance(a, ast.Constant) for a in node.args):
                found.append((node.lineno, line_of(node)))
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "GlobalColor"
        ):
            found.append((node.lineno, line_of(node)))
    return found


def test_no_hardcoded_colors_outside_theme():
    used_allow: set[int] = set()
    violations: list[str] = []
    for path in _iter_py_files():
        rel = path.relative_to(SRC_GUI).as_posix()
        for lineno, line in _violations_in(path.read_text(encoding="utf-8")):
            allowed = False
            for i, (a_path, a_pat, _reason) in enumerate(_ALLOWLIST):
                if rel == a_path and a_pat in line:
                    used_allow.add(i)
                    allowed = True
                    break
            if not allowed:
                violations.append(f"{rel}:{lineno}: {line}")
    assert not violations, (
        "色の直書きを検出 — gui/theme/tokens.py のトークン (tokens.active()) 経由に"
        "すること。QSS 断片は theme/qss.py に生成関数を追加する:\n"
        + "\n".join(violations)
    )
    stale = [_ALLOWLIST[i] for i in range(len(_ALLOWLIST)) if i not in used_allow]
    assert not stale, f"allowlist の陳腐化エントリ (どこにも一致しない): {stale}"
