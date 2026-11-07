from __future__ import annotations

import itertools
import re
import tempfile
from pathlib import Path

from .schemas import (
    ArrayExpression,
    BinaryExpression,
    BooleanExpression,
    CallExpression,
    CompareExpression,
    Expression,
    IfExpression,
    IndexedExpression,
    LiteralExpression,
    LookupExpression,
    ModelDocument,
    ReferenceExpression,
    TimeExpression,
    UnaryExpression,
)
from .units import format_units


def _name(value: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) and not value.startswith("time"):
        return value
    return f'"{value}"'


def runtime_name(value: str) -> str:
    return _name(value)


def runtime_variable_name(variable) -> str:
    name = runtime_name(variable.label or variable.id)
    if variable.subscripts:
        name += f"[{','.join(variable.subscripts)}]"
    return name


def series_names(document: ModelDocument) -> list[str]:
    names = []
    dimensions = {item.id: item.elements for item in document.dimensions}
    for variable in document.variables:
        if not variable.subscripts:
            names.append(variable.id)
            continue
        for elements in itertools.product(*(dimensions[name] for name in variable.subscripts)):
            names.append(f"{variable.id}[{','.join(elements)}]")
    return names


def expression_to_vensim(
    expression: Expression,
    names: dict[str, str],
    tables: dict[str, str],
    subscripts: dict[str, list[str]] | None = None,
) -> str:
    subscripts = subscripts or {}
    if isinstance(expression, LiteralExpression):
        if isinstance(expression.value, bool):
            return "1" if expression.value else "0"
        return repr(expression.value)
    if isinstance(expression, ReferenceExpression):
        if expression.name not in names and any(
            expression.name in dimensions for dimensions in subscripts.values()
        ):
            return expression.name
        result = _name(names[expression.name])
        if expression.name in subscripts:
            result += f"[{','.join(subscripts[expression.name])}]"
        return result
    if isinstance(expression, IndexedExpression):
        indices = expression.indices
        ordered = subscripts.get(expression.name, list(indices))
        values = [
            f"{dimension}!" if indices[dimension] == "*" else indices[dimension]
            for dimension in ordered
        ]
        return f"{_name(names[expression.name])}[{','.join(values)}]"
    if isinstance(expression, ArrayExpression):
        values = [
            expression_to_vensim(item, names, tables, subscripts) for item in expression.values
        ]
        if expression.shape and len(expression.shape) > 1:
            width = expression.shape[-1]
            return (
                "; ".join(
                    ",".join(values[index : index + width])
                    for index in range(0, len(values), width)
                )
                + ";"
            )
        return ",".join(values)
    if isinstance(expression, TimeExpression):
        return "Time"
    if isinstance(expression, UnaryExpression):
        value = expression_to_vensim(expression.arg, names, tables, subscripts)
        return (
            f"NOT ({value})"
            if expression.op == "not"
            else f"{'-' if expression.op == 'neg' else '+'}({value})"
        )
    if isinstance(expression, BinaryExpression):
        operators = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "^", "mod": "MODULO"}
        left, right = (
            expression_to_vensim(item, names, tables, subscripts) for item in expression.args
        )
        if expression.op == "mod":
            return f"MODULO({left}, {right})"
        if expression.op == "pow":
            if isinstance(expression.args[0], UnaryExpression):
                left = f"({left})"
            if isinstance(expression.args[1], UnaryExpression):
                right = f"({right})"
        return f"({left} {operators[expression.op]} {right})"
    if isinstance(expression, CompareExpression):
        operators = {"lt": "<", "le": "<=", "gt": ">", "ge": ">=", "eq": "=", "ne": "<>"}
        left, right = (
            expression_to_vensim(item, names, tables, subscripts) for item in expression.args
        )
        return f"({left} {operators[expression.op]} {right})"
    if isinstance(expression, BooleanExpression):
        function = "MIN" if expression.op == "and" else "MAX"
        args = ", ".join(
            expression_to_vensim(item, names, tables, subscripts) for item in expression.args
        )
        return f"{function}({args})"
    if isinstance(expression, LookupExpression):
        return f"{_name(tables[expression.table])}({expression_to_vensim(expression.arg, names, tables, subscripts)})"
    if isinstance(expression, IfExpression):
        condition = expression_to_vensim(expression.condition, names, tables, subscripts)
        then = expression_to_vensim(expression.then, names, tables, subscripts)
        otherwise = expression_to_vensim(expression.otherwise, names, tables, subscripts)
        return f"IF THEN ELSE({condition}, {then}, {otherwise})"
    if isinstance(expression, CallExpression):
        names_map = {"log": "LN", "power": "POWER", "if_then_else": "IF THEN ELSE"}
        function_name = expression.name
        if function_name in {"delay1", "delay3", "smooth", "smooth3"} and len(expression.args) == 3:
            function_name = f"{function_name}i"
        function = names_map.get(function_name, function_name).upper()
        arguments = list(expression.args)
        if expression.name in {"sum", "prod", "vmin", "vmax"} and isinstance(
            arguments[0], ReferenceExpression
        ):
            reference = arguments[0]
            if reference.name in subscripts:
                arguments[0] = IndexedExpression(
                    op="index",
                    name=reference.name,
                    indices={name: "*" for name in subscripts[reference.name]},
                )
        args = ", ".join(
            expression_to_vensim(item, names, tables, subscripts) for item in arguments
        )
        return f"{function}({args})"
    raise TypeError(f"unsupported expression: {type(expression).__name__}")


def _array_assignment_lines(
    variable,
    document: ModelDocument,
    names: dict[str, str],
    tables: dict[str, str],
    subscripts: dict[str, list[str]],
) -> list[str]:
    expression = variable.expression
    dimensions = {item.id: item.elements for item in document.dimensions}
    elements = list(itertools.product(*(dimensions[name] for name in variable.subscripts)))
    if len(elements) != len(expression.values):
        raise ValueError(f"array shape mismatch for {variable.id}")
    lines = []
    for index, values in enumerate(elements):
        name = f"{runtime_name(variable.label or variable.id)}[{','.join(values)}]"
        rhs = expression_to_vensim(
            _element_expression(expression.values[index], variable.subscripts, values),
            names,
            tables,
            subscripts,
        )
        lines.extend(
            [
                f"{name} = {rhs}",
                f"\t~ {format_units(variable.units, variable.units_raw)}",
                f"\t~ {variable.description or ''} |",
                "",
            ]
        )
    return lines


def _element_expression(
    expression: Expression, subscripts: list[str], elements: tuple[str, ...], aggregate: bool = False
) -> Expression:
    if isinstance(expression, IndexedExpression):
        if aggregate or not any(element == "*" for element in expression.indices.values()):
            return expression
        indices = {}
        for position, (name, index) in enumerate(expression.indices.items()):
            if index != "*":
                indices[name] = index
            elif name in subscripts:
                indices[name] = elements[subscripts.index(name)]
            elif len(expression.indices) == len(subscripts):
                indices[name] = elements[position]
            else:
                raise ValueError("cannot resolve a partially indexed array expression")
        return expression.model_copy(update={"indices": indices})
    if isinstance(expression, UnaryExpression):
        return expression.model_copy(
            update={"arg": _element_expression(expression.arg, subscripts, elements, aggregate)}
        )
    if isinstance(expression, BinaryExpression | CompareExpression):
        return expression.model_copy(
            update={
                "args": tuple(
                    _element_expression(argument, subscripts, elements, aggregate)
                    for argument in expression.args
                )
            }
        )
    if isinstance(expression, BooleanExpression | CallExpression):
        nested_aggregate = aggregate or (
            isinstance(expression, CallExpression) and expression.name in {"sum", "prod", "vmin", "vmax"}
        )
        return expression.model_copy(
            update={
                "args": [
                    _element_expression(argument, subscripts, elements, nested_aggregate)
                    for argument in expression.args
                ]
            }
        )
    if isinstance(expression, IfExpression):
        return expression.model_copy(
            update={
                "condition": _element_expression(expression.condition, subscripts, elements, aggregate),
                "then": _element_expression(expression.then, subscripts, elements, aggregate),
                "otherwise": _element_expression(expression.otherwise, subscripts, elements, aggregate),
            }
        )
    if isinstance(expression, LookupExpression):
        return expression.model_copy(
            update={"arg": _element_expression(expression.arg, subscripts, elements, aggregate)}
        )
    if isinstance(expression, ArrayExpression):
        return expression.model_copy(
            update={
                "values": [
                    _element_expression(value, subscripts, elements, aggregate)
                    for value in expression.values
                ]
            }
        )
    return expression


def _array_stock_lines(
    variable,
    document: ModelDocument,
    names: dict[str, str],
    tables: dict[str, str],
    subscripts: dict[str, list[str]],
    initial_helpers: dict[str, str],
) -> list[str]:
    derivative = variable.derivative
    dimensions = {item.id: item.elements for item in document.dimensions}
    elements = list(itertools.product(*(dimensions[name] for name in variable.subscripts)))
    if len(elements) != len(derivative.values):
        raise ValueError(f"derivative array shape mismatch for {variable.id}")
    lines = []
    for index, values in enumerate(elements):
        name = f"{runtime_name(variable.label or variable.id)}[{','.join(values)}]"
        initial_expression = (
            variable.initial.values[index]
            if isinstance(variable.initial, ArrayExpression)
            else variable.initial
        )
        derivative_expression = derivative.values[index]
        initial = expression_to_vensim(
            _element_expression(initial_expression, variable.subscripts, values), names, tables, subscripts
        )
        rhs = expression_to_vensim(
            _element_expression(derivative_expression, variable.subscripts, values),
            names,
            tables,
            subscripts,
        )
        lines.extend(
            [
                f"{name} = INTEG({rhs}, {initial})",
                f"\t~ {format_units(variable.units, variable.units_raw)}",
                f"\t~ {variable.description or ''} |",
                "",
            ]
        )
    return lines


def _array_initial_lines(
    variable,
    helper: str,
    document: ModelDocument,
    names: dict[str, str],
    tables: dict[str, str],
    subscripts: dict[str, list[str]],
) -> list[str]:
    expression = variable.initial
    dimensions = {item.id: item.elements for item in document.dimensions}
    elements = list(itertools.product(*(dimensions[name] for name in variable.subscripts)))
    if len(elements) != len(expression.values):
        raise ValueError(f"initial array shape mismatch for {variable.id}")
    lines = []
    for index, values in enumerate(elements):
        name = f"{helper}[{','.join(values)}]"
        rhs = expression_to_vensim(
            _element_expression(expression.values[index], variable.subscripts, values), names, tables, subscripts
        )
        lines.extend(
            [
                f"{name} = {rhs}",
                f"\t~ {format_units(variable.units, variable.units_raw)}",
                "\t~ |",
                "",
            ]
        )
    return lines


def export_vensim(document: ModelDocument) -> str:
    names = {item.id: item.label or item.id for item in document.variables}
    tables = {item.id: item.label or item.id for item in document.tables}
    subscripts = {item.id: item.subscripts for item in document.variables if item.subscripts}
    lines = ["{UTF-8}"]
    for dimension in document.dimensions:
        lines.extend([f"{dimension.id}:", ", ".join(dimension.elements), "\t~", "\t~ |", ""])
    for table in document.tables:
        xs = [point[0] for point in table.points]
        ys = [point[1] for point in table.points]
        points = ",".join(f"({x},{y})" for x, y in table.points)
        definition = f"[({min(xs)},{min(ys)})-({max(xs)},{max(ys)})],{points}"
        lines.extend([f"{_name(table.label or table.id)}({definition})", "\t~", "\t~ |", ""])
    initial_helpers = {}
    for variable in document.variables:
        if (
            variable.kind != "stock"
            or not isinstance(variable.initial, ArrayExpression)
            or isinstance(variable.derivative, ArrayExpression)
        ):
            continue
        helper = f"initial_{variable.id}"
        suffix = 2
        while helper in names:
            helper = f"initial_{variable.id}_{suffix}"
            suffix += 1
        initial_helpers[variable.id] = helper
        names[helper] = helper
        subscripts[helper] = variable.subscripts
        lines.extend(_array_initial_lines(variable, helper, document, names, tables, subscripts))
    for variable in document.variables:
        if variable.kind == "stock" and isinstance(variable.derivative, ArrayExpression) and variable.subscripts:
            lines.extend(_array_stock_lines(variable, document, names, tables, subscripts, initial_helpers))
            continue
        if variable.kind != "stock" and isinstance(variable.expression, ArrayExpression) and variable.subscripts:
            lines.extend(_array_assignment_lines(variable, document, names, tables, subscripts))
            continue
        name = runtime_variable_name(variable)
        if variable.kind == "stock":
            rhs = (
                expression_to_vensim(variable.derivative, names, tables, subscripts)
                if variable.derivative
                else "0"
            )
            initial_expression = (
                ReferenceExpression(op="ref", name=initial_helpers[variable.id])
                if variable.id in initial_helpers
                else variable.initial
            )
            initial = expression_to_vensim(initial_expression, names, tables, subscripts)
            rhs = f"INTEG({rhs}, {initial})"
        else:
            rhs = expression_to_vensim(variable.expression, names, tables, subscripts)
        lines.extend(
            [
                f"{name} = {rhs}",
                f"\t~ {format_units(variable.units, variable.units_raw)}",
                f"\t~ {variable.description or ''} |",
                "",
            ]
        )
    for name, value in (
        ("INITIAL TIME", document.time.initial_time),
        ("FINAL TIME", document.time.final_time),
        ("TIME STEP", document.time.time_step),
        ("SAVEPER", "TIME STEP"),
    ):
        lines.extend([f"{name} = {value}", f"\t~ {document.time.unit}", "\t~ |", ""])
    return "\n".join(lines)


def load_pysd_model(document: ModelDocument, directory: Path):
    import pysd

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "model.mdl"
    path.write_text(export_vensim(document), encoding="utf-8")
    return pysd.read_vensim(str(path))


def generate_python_code(document: ModelDocument) -> str:
    with tempfile.TemporaryDirectory(prefix="sdcloud_codegen_") as temporary:
        model = load_pysd_model(document, Path(temporary))
        return Path(model.py_model_file).read_text(encoding="utf-8")
