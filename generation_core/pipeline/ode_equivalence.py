from __future__ import annotations

import math
import re
from collections.abc import Mapping

from pydantic import TypeAdapter, ValidationError

from .exceptions import ModelValidationError
from .expression_parser import normalize_expression
from .ir import constant_number, derivative_for
from .schemas import (
    BinaryExpression,
    CallExpression,
    ComponentPlan,
    Expression,
    LiteralExpression,
    ModelDocument,
    OdeTerm,
    ReferenceExpression,
    SDVariable,
    TimeExpression,
    TimeSettings,
    UnaryExpression,
)

_EQUATION_START = re.compile(
    r"d(?:\((?P<braced>[A-Za-z_][A-Za-z0-9_]*)\)|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))"
    r"\s*/\s*dt\s*=\s*",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"\.\s+(?=[A-ZА-Я`])")
_EXPRESSION_ADAPTER = TypeAdapter(Expression)
_FUNCTIONS = {
    "abs": abs,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
    "power": math.pow,
    "min": min,
    "max": max,
    "minimum": min,
    "maximum": max,
}


class _UnsupportedExpression(ValueError):
    pass


def explicit_ode_expressions(description: str) -> dict[str, tuple[str, Expression]]:
    matches = list(_EQUATION_START.finditer(description))
    if not matches:
        return {}
    result = {}
    for index, match in enumerate(matches):
        stock = match.group("braced") or match.group("plain")
        if stock in result:
            return {}
        end = matches[index + 1].start() if index + 1 < len(matches) else len(description)
        raw = description[match.end() : end].strip()
        raw = re.sub(r"(?:\s+and|\s+и)$", "", raw, flags=re.IGNORECASE).strip()
        raw = _SENTENCE_END.split(raw, maxsplit=1)[0].strip().rstrip(",;")
        if not raw or len(raw) > 2000:
            continue
        try:
            expression = _EXPRESSION_ADAPTER.validate_python(normalize_expression(raw))
        except (ModelValidationError, ValidationError, TypeError, ValueError):
            continue
        result[stock] = (raw, expression)
    return result


def _evaluate(
    expression: Expression,
    environment: Mapping[str, float],
    definitions: Mapping[str, Expression],
    seen: frozenset[str] = frozenset(),
) -> float:
    if isinstance(expression, LiteralExpression):
        if isinstance(expression.value, bool):
            raise _UnsupportedExpression
        return float(expression.value)
    if isinstance(expression, ReferenceExpression):
        if expression.name in environment:
            return environment[expression.name]
        if expression.name in definitions and expression.name not in seen:
            return _evaluate(
                definitions[expression.name],
                environment,
                definitions,
                seen | {expression.name},
            )
        raise _UnsupportedExpression
    if isinstance(expression, TimeExpression):
        return environment["__time__"]
    if isinstance(expression, UnaryExpression):
        if expression.op not in {"neg", "pos"}:
            raise _UnsupportedExpression
        value = _evaluate(expression.arg, environment, definitions, seen)
        return -value if expression.op == "neg" else value
    if isinstance(expression, BinaryExpression):
        left = _evaluate(expression.args[0], environment, definitions, seen)
        right = _evaluate(expression.args[1], environment, definitions, seen)
        if expression.op == "add":
            return left + right
        if expression.op == "sub":
            return left - right
        if expression.op == "mul":
            return left * right
        if expression.op == "div":
            return left / right
        if expression.op == "pow":
            return left**right
        if expression.op == "mod":
            return left % right
    if isinstance(expression, CallExpression) and expression.name in _FUNCTIONS:
        function = _FUNCTIONS[expression.name]
        return float(
            function(
                *[
                    _evaluate(argument, environment, definitions, seen)
                    for argument in expression.args
                ]
            )
        )
    raise _UnsupportedExpression


def _equivalent(
    source: Expression,
    generated: Expression,
    variables: list[SDVariable],
) -> bool | None:
    constants = {}
    definitions = {}
    for variable in variables:
        expression = getattr(variable, "expression", None)
        if variable.kind in {"flow", "auxiliary"} and expression is not None:
            definitions[variable.id] = expression
        if variable.kind != "constant":
            continue
        if not isinstance(variable.expression, LiteralExpression) or isinstance(
            variable.expression.value, bool
        ):
            return None
        constants[variable.id] = float(variable.expression.value)
    stocks = [item.id for item in variables if item.kind == "stock"]
    for sample in range(4):
        environment = {
            **constants,
            **{
                stock: 0.63 + index * 0.77 + sample * 0.419
                for index, stock in enumerate(stocks)
            },
            "__time__": 0.37 + sample * 1.9,
        }
        try:
            expected = _evaluate(source, environment, definitions)
            actual = _evaluate(generated, environment, definitions)
        except (ArithmeticError, TypeError, ValueError):
            return None
        if not math.isfinite(expected) or not math.isfinite(actual):
            return None
        if not math.isclose(expected, actual, rel_tol=1e-7, abs_tol=1e-8):
            return False
    return True


def validate_explicit_odes(description: str, variables: list[SDVariable]) -> None:
    sources = explicit_ode_expressions(description)
    if not sources:
        return
    probe = ModelDocument(
        name="Explicit ODE validation",
        description="Numerical equivalence probe",
        time=TimeSettings(unit="time"),
        variables=variables,
    )
    stock_ids = {item.id for item in variables if item.kind == "stock"}
    for stock_id, (raw, source) in sources.items():
        if stock_id not in stock_ids:
            continue
        generated = derivative_for(probe, stock_id)
        if generated is None:
            continue
        equivalent = _equivalent(source, generated, variables)
        if equivalent is False:
            raise ModelValidationError(
                f"components.{stock_id} derivative is not numerically equivalent to the "
                f"explicit equation d{stock_id}/dt = {raw}. Preserve every original coefficient, "
                "including outer multipliers, inner products and divisions."
            )


def _split_terms(expression: Expression, sign: int = 1) -> list[tuple[int, Expression]]:
    if isinstance(expression, UnaryExpression) and expression.op in {"neg", "pos"}:
        return _split_terms(expression.arg, -sign if expression.op == "neg" else sign)
    if isinstance(expression, BinaryExpression) and expression.op in {"add", "sub"}:
        right_sign = sign if expression.op == "add" else -sign
        return [
            *_split_terms(expression.args[0], sign),
            *_split_terms(expression.args[1], right_sign),
        ]
    return [(sign, expression)]


def _product(expressions: list[Expression]) -> Expression:
    result = expressions[0]
    for expression in expressions[1:]:
        result = BinaryExpression(op="mul", args=(result, expression))
    return result


def _coefficient_and_expression(
    expression: Expression, parameter_ids: set[str]
) -> tuple[float | str, Expression]:
    literal = constant_number(expression)
    if literal is not None:
        return literal, LiteralExpression(op="lit", value=1)
    if isinstance(expression, ReferenceExpression) and expression.name in parameter_ids:
        return expression.name, LiteralExpression(op="lit", value=1)
    if isinstance(expression, BinaryExpression) and expression.op == "div":
        denominator = constant_number(expression.args[1])
        if denominator not in (None, 0):
            return 1 / denominator, expression.args[0]
    if isinstance(expression, BinaryExpression) and expression.op == "mul":
        factors = []

        def flatten(node: Expression) -> None:
            if isinstance(node, BinaryExpression) and node.op == "mul":
                flatten(node.args[0])
                flatten(node.args[1])
            else:
                factors.append(node)

        flatten(expression)
        for index, factor in enumerate(factors):
            coefficient: float | str | None = constant_number(factor)
            if (
                coefficient is None
                and isinstance(factor, ReferenceExpression)
                and factor.name in parameter_ids
            ):
                coefficient = factor.name
            if coefficient is not None:
                remaining = [*factors[:index], *factors[index + 1 :]]
                return coefficient, (
                    _product(remaining) if remaining else LiteralExpression(op="lit", value=1)
                )
    return 1, expression


def _dsl(expression: Expression) -> str | None:
    if isinstance(expression, LiteralExpression):
        return None if isinstance(expression.value, bool) else repr(expression.value)
    if isinstance(expression, ReferenceExpression):
        return expression.name
    if isinstance(expression, TimeExpression):
        return "TIME"
    if isinstance(expression, UnaryExpression) and expression.op in {"neg", "pos"}:
        argument = _dsl(expression.arg)
        if argument is None:
            return None
        return f"({'-' if expression.op == 'neg' else '+'}{argument})"
    if isinstance(expression, BinaryExpression):
        operator = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "^", "mod": "%"}.get(
            expression.op
        )
        if operator is None:
            return None
        left = _dsl(expression.args[0])
        right = _dsl(expression.args[1])
        if left is None or right is None:
            return None
        return f"({left} {operator} {right})"
    if isinstance(expression, CallExpression) and expression.name in _FUNCTIONS:
        arguments = [_dsl(argument) for argument in expression.args]
        if any(argument is None for argument in arguments):
            return None
        return f"{expression.name}({', '.join(arguments)})"
    return None


def _explicit_terms(expression: Expression, parameter_ids: set[str]) -> list[OdeTerm] | None:
    terms = []
    for sign, term_expression in _split_terms(expression):
        coefficient, remainder = _coefficient_and_expression(term_expression, parameter_ids)
        source = _dsl(remainder)
        if source is None:
            return None
        terms.append(
            OdeTerm(
                coefficient=coefficient,
                expression=source,
                sign=sign,
                name="explicit_equation_term",
            )
        )
    return terms


def _explicit_initial(description: str, stock: str) -> float | None:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(stock)}\s*=\s*"
        r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    )
    matches = list(pattern.finditer(description))
    if len(matches) != 1:
        return None
    try:
        return float(matches[0].group("value"))
    except ValueError:
        return None


def apply_explicit_odes(plan: ComponentPlan, description: str) -> ComponentPlan:
    from .ir import dependencies
    from .schemas import OdeStockSpec

    sources = explicit_ode_expressions(description)
    if not sources or not plan.components:
        return plan
    ode_components = [component for component in plan.components if component.kind == "polynomial_ode"]
    component_stocks = {component.stock for component in ode_components}
    missing = set(sources) - component_stocks
    parameter_ids = {
        parameter.id for component in ode_components for parameter in component.parameters
    } - set(sources)
    transformed_terms = {}
    for component in ode_components:
        if component.stock in sources:
            terms = _explicit_terms(sources[component.stock][1], parameter_ids)
            if terms is not None:
                transformed_terms[component.stock] = terms
    if missing and ode_components:
        units = {tuple(sorted(component.units.items())) for component in ode_components}
        time_units = {component.time_unit for component in ode_components}
        if len(units) == 1 and len(time_units) == 1:
            template = ode_components[0]
            for stock in sorted(missing):
                initial = _explicit_initial(description, stock)
                terms = _explicit_terms(sources[stock][1], parameter_ids)
                if initial is None or terms is None:
                    continue
                transformed_terms[stock] = terms
                ode_components.append(
                    OdeStockSpec(
                        kind="polynomial_ode",
                        stock=stock,
                        initial=initial,
                        units=template.units,
                        time_unit=template.time_unit,
                        terms=terms,
                        parameters=[],
                    )
                )
    missing = set(sources) - set(transformed_terms)
    if missing:
        raise ModelValidationError(
            f"missing explicit ODE stocks or unambiguous initial/shared units: {sorted(missing)}"
        )
    used_parameters = set()
    for terms in transformed_terms.values():
        used_parameters.update(
            term.coefficient for term in terms if isinstance(term.coefficient, str)
        )
        for term in terms:
            expression = _EXPRESSION_ADAPTER.validate_python(normalize_expression(term.expression))
            used_parameters.update(dependencies(expression))
    components = []
    for component in plan.components:
        if component.kind != "polynomial_ode" or component.stock not in sources:
            components.append(component)
            continue
        terms = transformed_terms[component.stock]
        components.append(
            component.model_copy(
                update={
                    "terms": terms,
                    "parameters": [
                        parameter
                        for parameter in component.parameters
                        if parameter.id in used_parameters and parameter.id not in sources
                    ],
                }
            )
        )
    components.extend(
        component for component in ode_components if component.stock not in component_stocks
    )
    return plan.model_copy(update={"components": components})
