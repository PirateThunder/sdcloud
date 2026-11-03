from __future__ import annotations

from collections.abc import Iterator

from .schemas import (
    ArrayExpression,
    BinaryExpression,
    BooleanExpression,
    CallExpression,
    CompareExpression,
    Expression,
    IfExpression,
    LiteralExpression,
    LookupExpression,
    ModelDocument,
    ReferenceExpression,
    TimeExpression,
    UnaryExpression,
)

FUNCTION_SIGNATURES: dict[str, tuple[int, int]] = {
    "min": (1, 20),
    "max": (1, 20),
    "minimum": (1, 20),
    "maximum": (1, 20),
    "sum": (1, 1),
    "prod": (1, 1),
    "vmin": (1, 1),
    "vmax": (1, 1),
    "abs": (1, 1),
    "exp": (1, 1),
    "log": (1, 1),
    "log10": (1, 1),
    "sqrt": (1, 1),
    "sin": (1, 1),
    "cos": (1, 1),
    "tan": (1, 1),
    "floor": (1, 1),
    "ceil": (1, 1),
    "round": (1, 1),
    "power": (2, 2),
    "xidz": (3, 3),
    "zidz": (2, 2),
    "if_then_else": (3, 3),
    "step": (2, 2),
    "pulse": (2, 5),
    "pulse_train": (4, 4),
    "ramp": (2, 3),
    "delay1": (2, 2),
    "delay3": (2, 2),
    "smooth": (2, 2),
    "smooth3": (2, 2),
    "initial": (1, 1),
}


def lit(value: float | bool) -> LiteralExpression:
    return LiteralExpression(op="lit", value=value)


def ref(name: str) -> ReferenceExpression:
    return ReferenceExpression(op="ref", name=name)


def time() -> TimeExpression:
    return TimeExpression(op="time")


def unary(op: str, arg: Expression) -> UnaryExpression:
    return UnaryExpression(op=op, arg=arg)  # type: ignore[arg-type]


def binary(op: str, left: Expression, right: Expression) -> BinaryExpression:
    return BinaryExpression(op=op, args=(left, right))  # type: ignore[arg-type]


def call(name: str, *args: Expression) -> CallExpression:
    return CallExpression(op="call", name=name, args=list(args))


def children(expression: Expression) -> list[Expression]:
    if isinstance(expression, UnaryExpression | LookupExpression):
        return [expression.arg]
    if isinstance(expression, BinaryExpression | CompareExpression):
        return list(expression.args)
    if isinstance(expression, BooleanExpression | CallExpression):
        return list(expression.args)
    if isinstance(expression, IfExpression):
        return [expression.condition, expression.then, expression.otherwise]
    if isinstance(expression, ArrayExpression):
        return list(expression.values)
    return []


def walk(expression: Expression) -> Iterator[Expression]:
    yield expression
    for child in children(expression):
        yield from walk(child)


def dependencies(expression: Expression) -> set[str]:
    return {node.name for node in walk(expression) if isinstance(node, ReferenceExpression)}


def is_boolean(expression: Expression) -> bool:
    return (
        isinstance(expression, CompareExpression | BooleanExpression)
        or (isinstance(expression, UnaryExpression) and expression.op == "not")
        or (isinstance(expression, LiteralExpression) and isinstance(expression.value, bool))
    )


def constant_number(expression: Expression) -> float | None:
    if isinstance(expression, LiteralExpression) and not isinstance(expression.value, bool):
        return float(expression.value)
    if isinstance(expression, UnaryExpression) and expression.op in {"neg", "pos"}:
        value = constant_number(expression.arg)
        if value is None:
            return None
        return -value if expression.op == "neg" else value
    return None


def expression_capabilities(expression: Expression) -> set[str]:
    capabilities: set[str] = set()
    for node in walk(expression):
        if isinstance(node, LookupExpression):
            capabilities.add("lookup")
        elif isinstance(node, IfExpression | CompareExpression | BooleanExpression) or (
            isinstance(node, UnaryExpression) and node.op == "not"
        ):
            capabilities.add("conditional")
        elif isinstance(node, CallExpression):
            if node.name in {"step", "pulse", "pulse_train", "ramp"}:
                capabilities.add("events")
            elif node.name in {"delay1", "delay3"}:
                capabilities.add("delay")
            elif node.name in {"smooth", "smooth3"}:
                capabilities.add("smooth")
            elif node.name == "initial":
                capabilities.add("initial")
            elif node.name in {"if_then_else", "xidz", "zidz"}:
                capabilities.add("conditional")
    return capabilities


def model_capabilities(document: ModelDocument) -> list[str]:
    capabilities = {"scalar_ode", "basic_math"}
    for variable in document.variables:
        if variable.subscripts:
            capabilities.add("subscripts")
        for expression in variable_expressions(variable):
            capabilities.update(expression_capabilities(expression))
    return sorted(capabilities)


def variable_expressions(variable) -> Iterator[Expression]:
    if hasattr(variable, "expression"):
        yield variable.expression
    if hasattr(variable, "initial"):
        yield variable.initial
    if getattr(variable, "derivative", None) is not None:
        yield variable.derivative


def derivative_for(document: ModelDocument, stock_id: str) -> Expression | None:
    stock = next(item for item in document.variables if item.id == stock_id)
    if stock.derivative is not None:
        return stock.derivative
    terms: list[Expression] = []
    for flow in document.variables:
        if flow.kind != "flow":
            continue
        if flow.target and flow.target.kind == "stock" and flow.target.id == stock_id:
            terms.append(ref(flow.id))
        if flow.source and flow.source.kind == "stock" and flow.source.id == stock_id:
            terms.append(unary("neg", ref(flow.id)))
    if not terms:
        return None
    result = terms[0]
    for term in terms[1:]:
        result = binary("add", result, term)
    return result


def with_derivatives(document: ModelDocument) -> ModelDocument:
    updates = {}
    for variable in document.variables:
        if variable.kind == "stock":
            updates[variable.id] = derivative_for(document, variable.id)
    variables = [
        item.model_copy(update={"derivative": updates[item.id]}) if item.kind == "stock" else item
        for item in document.variables
    ]
    return document.model_copy(update={"variables": variables})
