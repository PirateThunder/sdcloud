from __future__ import annotations

import ast

from .exceptions import ModelValidationError
from .ir import binary, call, lit, ref, time, unary
from .schemas import CompareExpression, Expression, IfExpression


def parse_legacy(source: str) -> Expression:
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ModelValidationError(f"invalid legacy expression: {exc.msg}") from exc
    return _convert(tree.body)


def _convert(node: ast.AST) -> Expression:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float | bool):
        return lit(node.value)
    if isinstance(node, ast.Name):
        return time() if node.id == "time" else ref(node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd | ast.Not):
        return unary(
            {ast.USub: "neg", ast.UAdd: "pos", ast.Not: "not"}[type(node.op)],
            _convert(node.operand),
        )
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, ast.Add | ast.Sub | ast.Mult | ast.Div | ast.Pow | ast.Mod
    ):
        op = {
            ast.Add: "add",
            ast.Sub: "sub",
            ast.Mult: "mul",
            ast.Div: "div",
            ast.Pow: "pow",
            ast.Mod: "mod",
        }[type(node.op)]
        return binary(op, _convert(node.left), _convert(node.right))
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        op = {
            ast.Lt: "lt",
            ast.LtE: "le",
            ast.Gt: "gt",
            ast.GtE: "ge",
            ast.Eq: "eq",
            ast.NotEq: "ne",
        }.get(type(node.ops[0]))
        if op is not None:
            return CompareExpression(
                op=op, args=(_convert(node.left), _convert(node.comparators[0]))
            )
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And | ast.Or):
        from .schemas import BooleanExpression

        return BooleanExpression(
            op="and" if isinstance(node.op, ast.And) else "or",
            args=[_convert(item) for item in node.values],
        )
    if isinstance(node, ast.IfExp):
        return IfExpression(
            op="if",
            condition=_convert(node.test),
            then=_convert(node.body),
            otherwise=_convert(node.orelse),
        )
    if isinstance(node, ast.Call) and not node.keywords:
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "np"
        ):
            name = node.func.attr
        else:
            name = ""
        aliases = {"ln": "log", "pow": "power"}
        name = aliases.get(name.lower(), name.lower())
        if name:
            return call(name, *[_convert(item) for item in node.args])
    raise ModelValidationError(f"legacy expression node is not allowed: {type(node).__name__}")


def flow_sign(expression: Expression, flow_id: str, sign: int = 1) -> int:
    from .schemas import BinaryExpression, ReferenceExpression, UnaryExpression

    if isinstance(expression, ReferenceExpression):
        return sign if expression.name == flow_id else 0
    if isinstance(expression, UnaryExpression):
        return flow_sign(expression.arg, flow_id, -sign if expression.op == "neg" else sign)
    if isinstance(expression, BinaryExpression):
        if expression.op in {"add", "sub"}:
            left = flow_sign(expression.args[0], flow_id, sign)
            right = flow_sign(
                expression.args[1], flow_id, sign if expression.op == "add" else -sign
            )
            if left and right and left != right:
                return 0
            return left or right
        if expression.op in {"mul", "div"}:
            left = flow_sign(expression.args[0], flow_id, sign)
            right = flow_sign(expression.args[1], flow_id, sign)
            return left or right
    return 0
