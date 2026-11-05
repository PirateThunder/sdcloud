from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .exceptions import ModelValidationError
from .ir import FUNCTION_SIGNATURES, constant_number
from .schemas import (
    BinaryExpression,
    BooleanExpression,
    CallExpression,
    CompareExpression,
    Expression,
    IfExpression,
    LiteralExpression,
    LookupExpression,
    ReferenceExpression,
    TimeExpression,
    UnaryExpression,
)

_TOKEN = re.compile(
    r"\s*(?:(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<quoted>'[^']*'|\"[^\"]*\")"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op>\*\*|<=|>=|==|!=|&&|\|\||<>|[-+*/%^<>()\[\],!=]))"
)
_TRANSLATION = str.maketrans(
    {"×": "*", "−": "-", "–": "-", "≤": "<=", "≥": ">=", "≠": "!=", "^": "^"}
)
_EXPRESSION_ADAPTER = TypeAdapter(Expression)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    position: int


def _tokens(source: str) -> list[Token]:
    text = source.translate(_TRANSLATION)
    result = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            if not text[position:].strip():
                break
            raise ModelValidationError(f"invalid expression syntax at position {position}")
        kind = match.lastgroup
        if kind is None:
            raise ModelValidationError(f"invalid expression syntax at position {position}")
        result.append(Token(kind, match.group(kind), match.start(kind)))
        position = match.end()
    result.append(Token("eof", "", len(text)))
    return result


class ExpressionParser:
    def __init__(self, source: str) -> None:
        if len(source) > 10_000:
            raise ModelValidationError("expression exceeds 10000 characters")
        self.tokens = _tokens(source)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def match(self, *values: str) -> str | None:
        if self.current.value in values:
            return self.advance().value
        return None

    def expect(self, value: str) -> None:
        if self.match(value) is None:
            raise ModelValidationError(
                f"expected {value!r} at position {self.current.position}, got {self.current.value!r}"
            )

    def parse(self) -> Expression:
        if self.current.kind == "eof":
            raise ModelValidationError("expression is empty")
        expression = self.parse_or()
        if self.current.kind != "eof":
            raise ModelValidationError(
                f"unexpected token {self.current.value!r} at position {self.current.position}"
            )
        return expression

    def parse_or(self) -> Expression:
        left = self.parse_and()
        while self.match("or", "||") is not None:
            left = BooleanExpression(op="or", args=[left, self.parse_and()])
        return left

    def parse_and(self) -> Expression:
        left = self.parse_comparison()
        while self.match("and", "&&") is not None:
            left = BooleanExpression(op="and", args=[left, self.parse_comparison()])
        return left

    def parse_comparison(self) -> Expression:
        left = self.parse_additive()
        operators = {"<": "lt", "<=": "le", ">": "gt", ">=": "ge", "==": "eq", "=": "eq", "!=": "ne", "<>": "ne"}
        operator = self.match(*operators)
        if operator is None:
            return left
        expression = CompareExpression(
            op=operators[operator], args=(left, self.parse_additive())
        )
        if self.current.value in operators:
            raise ModelValidationError("chained comparisons are not supported")
        return expression

    def parse_additive(self) -> Expression:
        left = self.parse_multiplicative()
        while self.current.value in {"+", "-"}:
            operator = self.advance().value
            left = BinaryExpression(
                op="add" if operator == "+" else "sub",
                args=(left, self.parse_multiplicative()),
            )
        return left

    def parse_multiplicative(self) -> Expression:
        left = self.parse_unary()
        while self.current.value in {"*", "/", "%"}:
            operator = self.advance().value
            operation = {"*": "mul", "/": "div", "%": "mod"}[operator]
            left = BinaryExpression(op=operation, args=(left, self.parse_unary()))
        return left

    def parse_unary(self) -> Expression:
        operator = self.match("+", "-", "!", "not")
        if operator is not None:
            operation = {"+": "pos", "-": "neg", "!": "not", "not": "not"}[operator]
            return UnaryExpression(op=operation, arg=self.parse_unary())
        return self.parse_power()

    def parse_power(self) -> Expression:
        left = self.parse_primary()
        if self.match("^", "**") is not None:
            return BinaryExpression(op="pow", args=(left, self.parse_unary()))
        return left

    def parse_list(self) -> list[Expression]:
        result = []
        if self.match("]") is None:
            while True:
                result.append(self.parse_or())
                if self.match("]") is not None:
                    break
                self.expect(",")
        return result

    def parse_primary(self) -> Expression:
        token = self.advance()
        if token.kind == "number":
            return LiteralExpression(op="lit", value=float(token.value))
        if token.value == "(":
            expression = self.parse_or()
            self.expect(")")
            return expression
        if token.kind == "quoted":
            content = token.value[1:-1]
            if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", content):
                return LiteralExpression(op="lit", value=float(content))
            return ReferenceExpression(op="ref", name=content)
        if token.kind != "name":
            raise ModelValidationError(
                f"expected a number, identifier or parenthesis at position {token.position}"
            )
        name = token.value.lower()
        if name == "if" and self.current.value.lower() == "then":
            self.advance()
            if self.current.value.lower() != "else":
                raise ModelValidationError("expected ELSE after IF THEN")
            self.advance()
            name = "if_then_else"
        elif name == "if" and self.current.value != "(":
            condition = self.parse_or()
            if self.current.value.lower() != "then":
                raise ModelValidationError("expected THEN after IF condition")
            self.advance()
            then = self.parse_or()
            if self.current.value.lower() != "else":
                raise ModelValidationError("expected ELSE after THEN expression")
            self.advance()
            otherwise = self.parse_or()
            return IfExpression(op="if", condition=condition, then=then, otherwise=otherwise)
        if self.match("(") is not None:
            args = []
            if self.match(")") is None:
                while True:
                    if self.match("[") is not None:
                        args.extend(self.parse_list())
                    else:
                        args.append(self.parse_or())
                    if self.match(")") is not None:
                        break
                    self.expect(",")
            return self._call(name, args)
        constants = {
            "true": LiteralExpression(op="lit", value=True),
            "false": LiteralExpression(op="lit", value=False),
            "pi": LiteralExpression(op="lit", value=math.pi),
            "e": LiteralExpression(op="lit", value=math.e),
        }
        if token.value in constants:
            return constants[token.value]
        if token.value.lower() == "time":
            return TimeExpression(op="time")
        return ReferenceExpression(op="ref", name=token.value)

    def _call(self, name: str, args: list[Expression]) -> Expression:
        if name == "ref" and len(args) == 1 and isinstance(args[0], ReferenceExpression):
            return args[0]
        if name == "lit" and len(args) == 1:
            if isinstance(args[0], LiteralExpression):
                return args[0]
            if isinstance(args[0], ReferenceExpression) and re.fullmatch(
                r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", args[0].name
            ):
                return LiteralExpression(op="lit", value=float(args[0].name))
            if (number := constant_number(args[0])) is not None:
                return LiteralExpression(op="lit", value=number)
        if name == "call" and len(args) >= 2 and isinstance(args[0], ReferenceExpression):
            return self._call(args[0].name, args[1:])
        if name == "time" and not args:
            return TimeExpression(op="time")
        if name in {"add", "mul"}:
            if len(args) < 2:
                raise ModelValidationError(f"{name} expects at least two arguments")
            expression = args[0]
            for arg in args[1:]:
                expression = BinaryExpression(op=name, args=(expression, arg))
            return expression
        binary_operations = {"sub": "sub", "div": "div", "divide": "div", "pow": "pow", "mod": "mod"}
        if name in binary_operations:
            if len(args) != 2:
                raise ModelValidationError(f"{name} expects two arguments")
            return BinaryExpression(op=binary_operations[name], args=(args[0], args[1]))
        compare_operations = {"lt", "le", "gt", "ge", "eq", "ne"}
        if name in compare_operations:
            if len(args) != 2:
                raise ModelValidationError(f"{name} expects two arguments")
            return CompareExpression(op=name, args=(args[0], args[1]))
        unary_operations = {"neg", "pos", "not"}
        if name in unary_operations:
            if len(args) != 1:
                raise ModelValidationError(f"{name} expects one argument")
            return UnaryExpression(op=name, arg=args[0])
        if name in {"and", "or"}:
            if len(args) < 2:
                raise ModelValidationError(f"{name} expects at least two arguments")
            return BooleanExpression(op=name, args=args)
        if name == "if":
            if len(args) != 3:
                raise ModelValidationError("if expects three arguments")
            return IfExpression(op="if", condition=args[0], then=args[1], otherwise=args[2])
        if name == "lookup":
            if len(args) != 2 or not isinstance(args[0], ReferenceExpression):
                raise ModelValidationError("lookup expects a table identifier and one expression")
            return LookupExpression(op="lookup", table=args[0].name, arg=args[1])
        if name in {"delay1", "delay3", "smooth", "smooth3"} and len(args) == 3:
            name = f"{name}i"
        signature = FUNCTION_SIGNATURES.get(name)
        if signature is None:
            raise ModelValidationError(f"function is not allowed: {name}")
        minimum, maximum = signature
        if not minimum <= len(args) <= maximum:
            raise ModelValidationError(
                f"function {name} expects between {minimum} and {maximum} arguments"
            )
        if name == "if_then_else":
            return IfExpression(
                op="if", condition=args[0], then=args[1], otherwise=args[2]
            )
        return CallExpression(op="call", name=name, args=args)


def parse_expression(source: str) -> Expression:
    return ExpressionParser(source).parse()


def _normalized_ast(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    op = result.get("op")
    if isinstance(op, str):
        op = op.lower()
        result["op"] = op
    if op == "ref" and isinstance(result.get("name"), str) and result["name"].lower() == "time":
        return {"op": "time"}
    if op == "divide":
        result["op"] = op = "div"
    if op in FUNCTION_SIGNATURES:
        args = result.get("args", [result["arg"]] if "arg" in result else [])
        if isinstance(args, dict | str | int | float):
            args = [args]
        result = {"op": "call", "name": op, "args": args}
        op = "call"
    if op == "call" and isinstance(result.get("name"), str):
        result["name"] = result["name"].lower()
        if result["name"] == "divide":
            result["op"] = "div"
            result.pop("name")
    if op == "lit" and isinstance(result.get("value"), str):
        literal = result["value"].strip()
        if literal.lower() in {"true", "false"}:
            result["value"] = literal.lower() == "true"
        elif re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", literal):
            result["value"] = float(literal)
    if "arg" in result and op in {"neg", "pos", "not", "lookup"}:
        result["arg"] = normalize_expression(result["arg"])
    if "args" in result and isinstance(result["args"], list):
        result["args"] = [normalize_expression(item) for item in result["args"]]
    if op == "if":
        for key in ("condition", "then", "otherwise"):
            if key in result:
                result[key] = normalize_expression(result[key])
    if op == "array" and isinstance(result.get("values"), list):
        result["values"] = [normalize_expression(item) for item in result["values"]]
    return result


def _numeric_value(value: dict[str, Any]) -> float | None:
    op = value.get("op")
    if op == "lit" and not isinstance(value.get("value"), bool):
        number = value.get("value")
        return float(number) if isinstance(number, int | float) and math.isfinite(number) else None
    if op in {"neg", "pos"}:
        number = _numeric_value(value.get("arg", {}))
        return None if number is None else -number if op == "neg" else number
    if op not in {"add", "sub", "mul", "div", "mod", "pow"}:
        return None
    args = value.get("args", [])
    if len(args) != 2:
        return None
    left, right = (_numeric_value(item) for item in args)
    if left is None or right is None:
        return None
    try:
        if op == "add":
            number = left + right
        elif op == "sub":
            number = left - right
        elif op == "mul":
            number = left * right
        elif op == "div":
            number = left / right
        elif op == "mod":
            number = left % right
        else:
            number = left**right
    except (ArithmeticError, TypeError, ValueError):
        return None
    return number if isinstance(number, int | float) and math.isfinite(number) else None


def _is_zero_literal(value: dict[str, Any]) -> bool:
    return (
        value.get("op") == "lit"
        and not isinstance(value.get("value"), bool)
        and value.get("value") == 0
    )


def _normalize_semantics(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    for key in ("arg", "condition", "then", "otherwise"):
        if isinstance(result.get(key), dict):
            result[key] = _normalize_semantics(result[key])
    for key in ("args", "values"):
        if isinstance(result.get(key), list):
            result[key] = [
                _normalize_semantics(item) if isinstance(item, dict) else item
                for item in result[key]
            ]
    number = _numeric_value(result)
    if result.get("op") != "lit" and number is not None:
        return {"op": "lit", "value": number}

    op = result.get("op")
    if op in {"add", "sub", "mod", "lt", "le", "gt", "ge", "eq", "ne"}:
        args = result.get("args", [])
        if len(args) == 2:
            if _is_zero_literal(args[0]) and not _is_zero_literal(args[1]):
                args[0] = {"op": "mul", "args": [{"op": "lit", "value": 0}, args[1]]}
            elif _is_zero_literal(args[1]) and not _is_zero_literal(args[0]):
                args[1] = {"op": "mul", "args": [{"op": "lit", "value": 0}, args[0]]}
    if op == "if":
        for key, other_key in (("then", "otherwise"), ("otherwise", "then")):
            if _is_zero_literal(result[key]) and not _is_zero_literal(result[other_key]):
                result[key] = {
                    "op": "mul",
                    "args": [{"op": "lit", "value": 0}, result[other_key]],
                }
    if op == "call" and result.get("name") in {"min", "max", "minimum", "maximum"}:
        args = result.get("args", [])
        nonzero = next((item for item in args if not _is_zero_literal(item)), None)
        if nonzero is not None:
            result["args"] = [
                {"op": "mul", "args": [{"op": "lit", "value": 0}, nonzero]}
                if _is_zero_literal(item)
                else item
                for item in args
            ]
    return result


def normalize_expression(value: Any) -> dict[str, Any]:
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            return normalize_expression(decoded)
    if isinstance(value, str):
        expression = parse_expression(value)
    elif isinstance(value, bool | int | float):
        expression = LiteralExpression(op="lit", value=value)
    elif isinstance(value, dict):
        try:
            expression = _EXPRESSION_ADAPTER.validate_python(_normalized_ast(value))
        except ValidationError as exc:
            raise ModelValidationError(f"invalid expression AST: {exc}") from exc
    else:
        raise ModelValidationError(f"expression must be a formula, number or AST object: {value!r}")
    if (
        isinstance(expression, CallExpression)
        and expression.name in {"delay1", "delay3", "smooth", "smooth3"}
        and len(expression.args) == 3
    ):
        expression = expression.model_copy(update={"name": f"{expression.name}i"})
    if isinstance(expression, CallExpression):
        signature = FUNCTION_SIGNATURES.get(expression.name)
        if signature is not None and not signature[0] <= len(expression.args) <= signature[1]:
            raise ModelValidationError(
                f"function {expression.name} expects between {signature[0]} and {signature[1]} arguments"
            )
    if isinstance(expression, CallExpression) and expression.name == "if_then_else":
        expression = IfExpression(
            op="if",
            condition=expression.args[0],
            then=expression.args[1],
            otherwise=expression.args[2],
        )
    return _normalize_semantics(expression.model_dump(mode="json"))
