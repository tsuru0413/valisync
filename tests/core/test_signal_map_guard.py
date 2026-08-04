"""``signal_map()`` 全列列挙ガード (常設 Layer A・E-4c spec §4)。

``SignalGroupManager.signal_map()`` は **非対称 Mapping** (E-1 の意図的逸脱):
``[]``/``get``/``in`` は列キーを解決器経由で鋳造しうるが、``__iter__``/``__len__``
は既存 (物理) キーしか返さない。全論理キーの列挙は prod の 330,004 列を鋳造して
~390 MB を再導入するので提供しない — つまり ``dict(session.signal_map())`` は
**例外も警告も出さずに「全列の顔をした物理チャンネルだけの map」**を返す。
E-4c 以前、この契約への防御は挙動テストだけで、``src/`` に 1 行書けば
コンパイルも CI も通ってしまった。

**二層防御の上段**がこのファイル: ``src/`` に書いた瞬間に落ちる。下段は
``tests/core/loaders/test_resolver.py:269-353`` と ``tests/core/test_session_signal_map.py``
の挙動テストで、そちらは「仕様そのものが壊れたら落ちる」。上段は false positive を
allowlist で吸収し、下段が false negative を実測で拾う — **2 つは独立オラクルなので
片方を他方に合わせて弱めてはならない**。

形は ``tests/gui/test_theme_guard.py`` と同型 (行内容 ratchet allowlist + 陳腐化
assert)。コメント/docstring は AST 上 ``Constant`` にしか現れず、ここでは
``Call``/``For``/``comprehension`` しか見ないので自然に対象外になる
(``signal_group_manager.py:393`` や ``session.py:276`` の禁止事項を書いた docstring が
自分自身を違反にしない理由)。
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "valisync"

# 列挙を強制する組み込み (spec §4.2-1)。
_ENUMERATORS = frozenset({"dict", "list", "set", "sorted", "tuple", "iter"})
# ビュー形 (spec §4.2-3)。
_VIEW_METHODS = frozenset({"keys", "items", "values"})
# ``x.signal_map()`` を名乗る呼び出し。``_signal_map`` を含めるのは spec §4.2-1 の
# 素直な広げ方であって緩めではない: ``GraphPanelVM._signal_map()`` は同じ非対称
# map (または列挙が TypeError になる ``_OffsetOverlay``) を返す実質同一の口で、
# ここを外すと prod で最も列挙されそうな 8 サイトが丸ごと盲点になる。
_SIGNAL_MAP_CALLS = frozenset({"signal_map", "_signal_map"})

_MESSAGE = (
    "signal_map() の全列列挙は禁止（列挙は物理キーのみ返る — E-1 の非対称 Mapping。"
    "全論理キーを列挙すると prod 330,004 列を鋳造して ~390 MB を再導入する）。"
    "列数は total_column_count() ／列名は column_names_of() ／存在確認は "
    "has_column() を使う"
)

# (相対 path, 行内一致パターン, 理由) — 行パターン ratchet (theme_guard と同型):
# ファイル単位だと同一ファイル内の新規違反を隠すため、行内容で絞る。
# どこにも一致しなくなったエントリは陳腐化として fail する。
# **空が目標**。2026-08-04 実測で src/ の違反は 0 件。
_ALLOWLIST: tuple[tuple[str, str, str], ...] = ()


def _iter_py_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _is_signal_map_call(node: ast.AST) -> bool:
    """``<x>.signal_map()`` / ``signal_map()`` そのものか (spec §4.2-1)。"""
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr in _SIGNAL_MAP_CALLS
    return isinstance(fn, ast.Name) and fn.id in _SIGNAL_MAP_CALLS


def _is_signal_map_name(node: ast.AST) -> bool:
    """``signal_map`` を名前に含む変数 (spec §4.2-4 の**浅い**追跡)。

    データフロー解析はしない。false positive は allowlist で吸収し、false
    negative は下段の挙動テストが実測で拾う — それが二層である理由そのもの。
    """
    return isinstance(node, ast.Name) and "signal_map" in node.id


def _is_map_expr(node: ast.AST) -> bool:
    return _is_signal_map_call(node) or _is_signal_map_name(node)


def _violations_in(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    lines = source.splitlines()
    found: set[tuple[int, str]] = set()

    def record(node: ast.AST) -> None:
        lineno = getattr(node, "lineno", 0)
        line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
        found.add((lineno, line))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            # 1. 直結形: dict(m) / list(m) / set(m) / sorted(m) / tuple(m) / iter(m)
            if (
                isinstance(fn, ast.Name)
                and fn.id in _ENUMERATORS
                and any(_is_map_expr(a) for a in node.args)
            ):
                record(node)
            # 3. ビュー形: m.keys() / m.items() / m.values()
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr in _VIEW_METHODS
                and _is_map_expr(fn.value)
            ):
                record(node)
        # 2. イテレーション形: for ... in m / 内包表記の iter
        if isinstance(node, (ast.For, ast.AsyncFor)) and _is_map_expr(node.iter):
            record(node)
        if isinstance(node, ast.comprehension) and _is_map_expr(node.iter):
            record(node.iter)  # comprehension 自体は lineno を持たない
    return sorted(found)


def _scan(
    allowlist: tuple[tuple[str, str, str], ...],
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """(違反, 陳腐化 allowlist エントリ) を返す — 2 本のテストが共有する唯一の実装。

    陳腐化テストが**同じ照合ロジック**を通ることが要点: allowlist を空のまま
    置くと本体側の陳腐化 assert は構造的に空回りするので、機構そのものは
    合成 allowlist で別途実証する。
    """
    used: set[int] = set()
    violations: list[str] = []
    for path in _iter_py_files():
        rel = path.relative_to(SRC).as_posix()
        for lineno, line in _violations_in(path.read_text(encoding="utf-8")):
            allowed = False
            for i, (a_path, a_pat, _reason) in enumerate(allowlist):
                if rel == a_path and a_pat in line:
                    used.add(i)
                    allowed = True
                    break
            if not allowed:
                violations.append(f"{rel}:{lineno}: {line}")
    stale = [allowlist[i] for i in range(len(allowlist)) if i not in used]
    return violations, stale


def test_no_signal_map_enumeration_in_src() -> None:
    violations, stale = _scan(_ALLOWLIST)
    assert not violations, _MESSAGE + ":\n" + "\n".join(violations)
    assert not stale, f"allowlist の陳腐化エントリ (どこにも一致しない): {stale}"


def test_stale_allowlist_entry_is_reported() -> None:
    """陳腐化検出の機構そのものを固定する (``_ALLOWLIST`` が空でも空回りしない)。"""
    fake = (("core/session.py", "この行は src に存在しない", "陳腐化検出の実証用"),)
    violations, stale = _scan(fake)
    assert violations == [], violations  # 合成 allowlist は違反を増やさない
    assert stale == list(fake)
