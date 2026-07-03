from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

import numpy as np

from valisync.core.models import Signal

# ─── Supported functions ────────────────────────────────────────────────────────

_FUNCTIONS: dict[str, tuple[Any, int]] = {
    "sin": (np.sin, 1),
    "cos": (np.cos, 1),
    "tan": (np.tan, 1),
    "asin": (np.arcsin, 1),
    "acos": (np.arccos, 1),
    "atan": (np.arctan, 1),
    "log": (np.log, 1),
    "log10": (np.log10, 1),
    "abs": (np.abs, 1),
    "sqrt": (np.sqrt, 1),
    "pow": (np.power, 2),
}

# ─── Public result type ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: tuple[str, ...] = ()


# ─── Token types ───────────────────────────────────────────────────────────────


class _TK(Enum):
    NUMBER = auto()
    IDENT = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    CARET = auto()
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    EOF = auto()


@dataclass(frozen=True)
class _Token:
    kind: _TK
    value: float | str | None = None
    pos: int = 0


# ─── AST nodes ─────────────────────────────────────────────────────────────────


@dataclass
class _NumberNode:
    value: float


@dataclass
class _BinOpNode:
    op: str
    left: Any
    right: Any


@dataclass
class _UnaryMinusNode:
    expr: Any


@dataclass
class _FuncCallNode:
    name: str
    args: list[Any]
    pos: int = 0


@dataclass
class _SignalRefNode:
    name: str


# ─── Lexer ──────────────────────────────────────────────────────────────────────

_SIMPLE_OPS: dict[str, _TK] = {
    "+": _TK.PLUS,
    "-": _TK.MINUS,
    "*": _TK.STAR,
    "/": _TK.SLASH,
    "^": _TK.CARET,
    "(": _TK.LPAREN,
    ")": _TK.RPAREN,
    ",": _TK.COMMA,
}


class _Lexer:
    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0

    def tokenize(self) -> list[_Token]:
        tokens: list[_Token] = []
        while True:
            while self._pos < len(self._text) and self._text[self._pos].isspace():
                self._pos += 1
            if self._pos >= len(self._text):
                tokens.append(_Token(_TK.EOF, pos=self._pos))
                break

            start = self._pos
            ch = self._text[self._pos]

            # Number (integer / decimal / scientific)
            if ch.isdigit() or (
                ch == "."
                and self._pos + 1 < len(self._text)
                and self._text[self._pos + 1].isdigit()
            ):
                while self._pos < len(self._text) and (
                    self._text[self._pos].isdigit() or self._text[self._pos] == "."
                ):
                    self._pos += 1
                if self._pos < len(self._text) and self._text[self._pos] in ("e", "E"):
                    self._pos += 1
                    if self._pos < len(self._text) and self._text[self._pos] in (
                        "+",
                        "-",
                    ):
                        self._pos += 1
                    while (
                        self._pos < len(self._text) and self._text[self._pos].isdigit()
                    ):
                        self._pos += 1
                tokens.append(
                    _Token(_TK.NUMBER, float(self._text[start : self._pos]), start)
                )
                continue

            # Identifier — supports "::" namespace separator (e.g. mf4_1::speed)
            if ch.isalpha() or ch == "_":
                while self._pos < len(self._text) and (
                    self._text[self._pos].isalnum() or self._text[self._pos] == "_"
                ):
                    self._pos += 1
                while (
                    self._pos + 1 < len(self._text)
                    and self._text[self._pos] == ":"
                    and self._text[self._pos + 1] == ":"
                ):
                    self._pos += 2
                    while self._pos < len(self._text) and (
                        self._text[self._pos].isalnum() or self._text[self._pos] == "_"
                    ):
                        self._pos += 1
                tokens.append(_Token(_TK.IDENT, self._text[start : self._pos], start))
                continue

            if ch in _SIMPLE_OPS:
                tokens.append(_Token(_SIMPLE_OPS[ch], ch, start))
                self._pos += 1
                continue

            raise SyntaxError(f"unexpected character {ch!r} at position {start}")

        return tokens


# ─── Parser (recursive descent) ─────────────────────────────────────────────────


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    @property
    def _cur(self) -> _Token:
        return self._tokens[self._pos]

    def _eat(self, kind: _TK) -> _Token:
        tok = self._cur
        if tok.kind != kind:
            raise SyntaxError(
                f"expected {kind.name}, got {tok.kind.name!r} at position {tok.pos}"
            )
        self._pos += 1
        return tok

    def _match(self, *kinds: _TK) -> bool:
        return self._cur.kind in kinds

    def parse(self) -> Any:
        node = self._expr()
        self._eat(_TK.EOF)
        return node

    # expr → term (('+' | '-') term)*
    def _expr(self) -> Any:
        node = self._term()
        while self._match(_TK.PLUS, _TK.MINUS):
            op = str(self._cur.value)
            self._pos += 1
            node = _BinOpNode(op, node, self._term())
        return node

    # term → pow_ (('*' | '/') pow_)*
    def _term(self) -> Any:
        node = self._pow()
        while self._match(_TK.STAR, _TK.SLASH):
            op = str(self._cur.value)
            self._pos += 1
            node = _BinOpNode(op, node, self._pow())
        return node

    # pow_ → unary ('^' pow_)?   — right-associative
    def _pow(self) -> Any:
        base = self._unary()
        if self._match(_TK.CARET):
            self._pos += 1
            return _BinOpNode("^", base, self._pow())
        return base

    # unary → '-' unary | primary
    def _unary(self) -> Any:
        if self._match(_TK.MINUS):
            self._pos += 1
            return _UnaryMinusNode(self._unary())
        return self._primary()

    # primary → NUMBER | '(' expr ')' | IDENT ['(' args ')']
    def _primary(self) -> Any:
        tok = self._cur

        if tok.kind == _TK.NUMBER:
            self._pos += 1
            return _NumberNode(float(tok.value))  # type: ignore[arg-type]

        if tok.kind == _TK.LPAREN:
            self._pos += 1
            node = self._expr()
            self._eat(_TK.RPAREN)
            return node

        if tok.kind == _TK.IDENT:
            name = str(tok.value)
            pos = tok.pos
            self._pos += 1
            if self._match(_TK.LPAREN):
                self._pos += 1
                args: list[Any] = []
                if not self._match(_TK.RPAREN):
                    args.append(self._expr())
                    while self._match(_TK.COMMA):
                        self._pos += 1
                        args.append(self._expr())
                self._eat(_TK.RPAREN)
                return _FuncCallNode(name, args, pos)
            return _SignalRefNode(name)

        raise SyntaxError(f"unexpected token {tok.kind.name!r} at position {tok.pos}")


# ─── AST helpers ────────────────────────────────────────────────────────────────


def _collect_signal_refs(node: Any) -> set[str]:
    if isinstance(node, _SignalRefNode):
        return {node.name}
    if isinstance(node, _NumberNode):
        return set()
    if isinstance(node, _UnaryMinusNode):
        return _collect_signal_refs(node.expr)
    if isinstance(node, _BinOpNode):
        return _collect_signal_refs(node.left) | _collect_signal_refs(node.right)
    if isinstance(node, _FuncCallNode):
        result: set[str] = set()
        for arg in node.args:
            result |= _collect_signal_refs(arg)
        return result
    return set()


def _check_functions(node: Any, errors: list[str]) -> None:
    if isinstance(node, _FuncCallNode):
        if node.name not in _FUNCTIONS:
            errors.append(f"unknown function {node.name!r} at position {node.pos}")
        for arg in node.args:
            _check_functions(arg, errors)
    elif isinstance(node, _BinOpNode):
        _check_functions(node.left, errors)
        _check_functions(node.right, errors)
    elif isinstance(node, _UnaryMinusNode):
        _check_functions(node.expr, errors)


# ─── Result timestamp computation ───────────────────────────────────────────────


def _compute_result_timestamps(
    refs: set[str], signals: dict[str, Signal]
) -> np.ndarray:
    """Union of all referenced signals' timestamps within the common time range.

    Returns an empty array when any referenced signal has no samples (no common
    interval) or when signals' time ranges do not overlap.
    """
    if not refs:
        return np.array([], dtype=np.float64)
    if any(len(signals[n].timestamps) == 0 for n in refs):
        return np.array([], dtype=np.float64)

    t_start = max(signals[n].sorted_view()[0][0] for n in refs)
    t_end = min(signals[n].sorted_view()[0][-1] for n in refs)
    if t_start > t_end:
        return np.array([], dtype=np.float64)

    parts: list[np.ndarray] = []
    for n in refs:
        ts = signals[n].sorted_view()[0]
        parts.append(ts[(ts >= t_start) & (ts <= t_end)])

    return np.unique(np.concatenate(parts))


# ─── Evaluator ──────────────────────────────────────────────────────────────────


def _count_non_finite(v: Any) -> int:
    if np.isscalar(v):
        return 0 if np.isfinite(float(v)) else 1  # type: ignore[arg-type]
    return int(np.sum(~np.isfinite(np.asarray(v))))


class _Evaluator:
    def __init__(self, signals: dict[str, Signal], result_ts: np.ndarray) -> None:
        self._signals = signals
        self._result_ts = result_ts
        self.warnings: list[str] = []

    def _interp(self, name: str) -> np.ndarray:
        sig = self._signals[name]
        if len(sig.timestamps) == 0 or len(self._result_ts) == 0:
            return np.zeros(len(self._result_ts), dtype=np.float64)
        ts, vs = sig.sorted_view()  # np.interp は単調な xp が前提
        return np.interp(self._result_ts, ts, vs)

    def eval(self, node: Any) -> Any:
        if isinstance(node, _NumberNode):
            return node.value

        if isinstance(node, _SignalRefNode):
            return self._interp(node.name)

        if isinstance(node, _UnaryMinusNode):
            return -self.eval(node.expr)

        if isinstance(node, _BinOpNode):
            left = self.eval(node.left)
            right = self.eval(node.right)
            if node.op == "+":
                return left + right
            if node.op == "-":
                return left - right
            if node.op == "*":
                return left * right
            if node.op == "/":
                with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
                    result = np.true_divide(left, right)
                n = _count_non_finite(result)
                if n:
                    self.warnings.append(
                        f"division: {n} sample(s) set to NaN (divide by zero)"
                    )
                return result
            if node.op == "^":
                with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
                    return np.power(left, right)

        if isinstance(node, _FuncCallNode):
            func, arity = _FUNCTIONS[node.name]
            if len(node.args) != arity:
                raise ValueError(
                    f"{node.name!r} expects {arity} argument(s), got {len(node.args)}"
                )
            args = [self.eval(a) for a in node.args]
            with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
                result = func(*args)
            n = _count_non_finite(result)
            if n:
                self.warnings.append(
                    f"{node.name}(): {n} sample(s) set to NaN (domain error)"
                )
            return result

        raise ValueError(f"unknown AST node: {type(node).__name__}")


# ─── Public API ─────────────────────────────────────────────────────────────────


class FormulaEngine:
    """Parses and evaluates math expressions over Signal inputs.

    Supported operators: + - * / ^ (right-associative)
    Supported functions: sin cos tan asin acos atan log log10 abs sqrt pow
    Signal names may include the key namespace separator (e.g. mf4_1::speed).

    Multi-signal evaluation: result timestamps = sorted union of all referenced
    signals' timestamps within the common time range. Signals are linearly
    interpolated (np.interp) to the result grid; original values are used
    exactly at each signal's own sample times.
    """

    def validate(self, expression: str) -> ValidationResult:
        """Check syntax and function names without evaluating against signals."""
        errors: list[str] = []
        try:
            ast = _Parser(_Lexer(expression).tokenize()).parse()
            _check_functions(ast, errors)
        except SyntaxError as exc:
            errors.append(str(exc))
        return ValidationResult(is_valid=not errors, errors=tuple(errors))

    def evaluate(
        self,
        expression: str,
        signals: dict[str, Signal],
        max_depth: int = 100,
    ) -> Signal:
        """Evaluate *expression* over *signals* and return a Derived Signal.

        Raises ValueError on syntax errors, unknown function/signal names, or
        when max_depth ≤ 0 (nesting depth exceeded, Req 10.10). Operation errors
        (zero division, domain errors) produce NaN samples and are recorded in
        the returned Signal's metadata["formula_warnings"].
        """
        if max_depth <= 0:
            raise ValueError("formula nesting depth limit exceeded (max 100 levels)")

        try:
            ast = _Parser(_Lexer(expression).tokenize()).parse()
        except SyntaxError as exc:
            raise ValueError(f"formula syntax error: {exc}") from exc

        func_errors: list[str] = []
        _check_functions(ast, func_errors)
        if func_errors:
            raise ValueError("; ".join(func_errors))

        refs = _collect_signal_refs(ast)
        missing = refs - signals.keys()
        if missing:
            raise ValueError(f"unknown signal name(s): {sorted(missing)}")

        result_ts = _compute_result_timestamps(refs, signals)
        evaluator = _Evaluator(signals, result_ts)
        raw = evaluator.eval(ast)

        if np.isscalar(raw):
            values = np.full(len(result_ts), float(raw), dtype=np.float64)  # type: ignore[arg-type]
        else:
            values = np.asarray(raw, dtype=np.float64)

        # Inf → NaN (Req 10.7)
        values = np.where(np.isinf(values), np.nan, values)

        meta: dict[str, Any] = {}
        if evaluator.warnings:
            meta["formula_warnings"] = list(evaluator.warnings)

        return Signal(
            name=f"({expression})",
            timestamps=result_ts,
            values=values,
            file_format="Derived",
            bus_type="",
            source_file="",
            metadata=meta,
        )
