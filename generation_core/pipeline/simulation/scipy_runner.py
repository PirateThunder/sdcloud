from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

from ..exceptions import SimulationError
from ..ir import derivative_for
from ..schemas import (
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


@dataclass
class EngineOutput:
    time: list[float]
    variables: dict[str, list[float]]
    metadata: dict[str, int | float | str | bool]


class ScipyCompiler:
    def __init__(
        self, document: ModelDocument, parameters: dict[str, float], input_series=None
    ) -> None:
        self.document = document
        self.parameters = parameters
        self.input_series = input_series or {}
        self.indices = {item.id: index for index, item in enumerate(document.variables)}
        self.stocks = [item for item in document.variables if item.kind == "stock"]
        self.stock_indices = {item.id: index for index, item in enumerate(self.stocks)}
        self.functions: dict[str, str] = {}

    def emit(self, expression: Expression) -> str:
        if isinstance(expression, LiteralExpression):
            return repr(expression.value)
        if isinstance(expression, ReferenceExpression):
            return self.functions[expression.name]
        if isinstance(expression, TimeExpression):
            return "t"
        if isinstance(expression, UnaryExpression):
            value = self.emit(expression.arg)
            return (
                f"(not {value})"
                if expression.op == "not"
                else f"({'-' if expression.op == 'neg' else '+'}({value}))"
            )
        if isinstance(expression, BinaryExpression):
            operators = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "**", "mod": "%"}
            left, right = (self.emit(item) for item in expression.args)
            return f"({left} {operators[expression.op]} {right})"
        if isinstance(expression, CompareExpression):
            operators = {"lt": "<", "le": "<=", "gt": ">", "ge": ">=", "eq": "==", "ne": "!="}
            left, right = (self.emit(item) for item in expression.args)
            return f"({left} {operators[expression.op]} {right})"
        if isinstance(expression, BooleanExpression):
            operator = " and " if expression.op == "and" else " or "
            return "(" + operator.join(self.emit(item) for item in expression.args) + ")"
        if isinstance(expression, LookupExpression):
            return f"_lookup({expression.table!r}, {self.emit(expression.arg)})"
        if isinstance(expression, IfExpression):
            condition = self.emit(expression.condition)
            then = self.emit(expression.then)
            otherwise = self.emit(expression.otherwise)
            return f"({then} if {condition} else {otherwise})"
        if isinstance(expression, CallExpression):
            args = expression.args
            if expression.name == "if_then_else":
                return f"({self.emit(args[1])} if {self.emit(args[0])} else {self.emit(args[2])})"
            if expression.name == "xidz":
                return f"({self.emit(args[2])} if abs({self.emit(args[1])}) < 1e-6 else {self.emit(args[0])} / {self.emit(args[1])})"
            if expression.name == "zidz":
                return f"(0 if abs({self.emit(args[1])}) < 1e-6 else {self.emit(args[0])} / {self.emit(args[1])})"
            function = "power" if expression.name == "power" else expression.name
            return f"{function}({', '.join(self.emit(item) for item in args)})"
        raise SimulationError(f"unsupported SciPy expression: {type(expression).__name__}")

    def compile(self):
        for index, variable in enumerate(self.document.variables):
            self.functions[variable.id] = f"_v{index}(t, state)"
        lines = [
            "import math",
            "min = min",
            "max = max",
            "abs = abs",
            "power = pow",
            "floor = math.floor",
            "ceil = math.ceil",
            "round = round",
            "exp = math.exp",
            "log = math.log",
            "log10 = math.log10",
            "sqrt = math.sqrt",
            "sin = math.sin",
            "cos = math.cos",
            "tan = math.tan",
            "",
            "def _lookup(table_id, value):",
            "    xs, ys, mode = _TABLES[table_id]",
            "    if value <= xs[0]:",
            "        if mode == 'error' and value < xs[0]: raise ValueError('lookup input below table')",
            "        return ys[0] if mode == 'clamp' else ys[0] + (value-xs[0])*(ys[1]-ys[0])/(xs[1]-xs[0])",
            "    if value >= xs[-1]:",
            "        if mode == 'error' and value > xs[-1]: raise ValueError('lookup input above table')",
            "        return ys[-1] if mode == 'clamp' else ys[-1] + (value-xs[-1])*(ys[-1]-ys[-2])/(xs[-1]-xs[-2])",
            "    for index in range(1, len(xs)):",
            "        if value <= xs[index]:",
            "            return ys[index-1] + (value-xs[index-1])*(ys[index]-ys[index-1])/(xs[index]-xs[index-1])",
            "    return ys[-1]",
            "",
        ]
        for index, variable in enumerate(self.document.variables):
            lines.append(f"def _v{index}(t, state):")
            if variable.kind == "stock":
                lines.append(f"    return state[{self.stock_indices[variable.id]}]")
            elif variable.kind == "constant" and variable.id in self.input_series:
                lines.append(f"    return _lookup({f'external_{variable.id}'!r}, t)")
            elif variable.kind == "constant":
                lines.append(
                    f"    return _PARAMS.get({variable.id!r}, {self.emit(variable.expression)})"
                )
            else:
                lines.append(f"    return {self.emit(variable.expression)}")
            lines.append("")
        derivative_names = []
        initial_names = []
        for index, stock in enumerate(self.stocks):
            derivative = derivative_for(self.document, stock.id)
            derivative_source = "0.0" if derivative is None else self.emit(derivative)
            lines.extend([f"def _d{index}(t, state):", f"    return {derivative_source}", ""])
            lines.extend(
                [f"def _i{index}(t, state):", f"    return {self.emit(stock.initial)}", ""]
            )
            derivative_names.append(f"_d{index}")
            initial_names.append(f"_i{index}")
        lines.extend(
            [
                "def _derivatives(t, state):",
                f"    return [{', '.join(f'{name}(t, state)' for name in derivative_names)}]",
                "",
                "def _initial(t, state):",
                f"    return [{', '.join(f'{name}(t, state)' for name in initial_names)}]",
            ]
        )
        namespace = {
            "_PARAMS": self.parameters,
            "_TABLES": {
                table.id: (
                    [point[0] for point in table.points],
                    [point[1] for point in table.points],
                    table.extrapolation,
                )
                for table in self.document.tables
            },
        }
        namespace["_TABLES"].update(
            {
                f"external_{name}": (
                    [point[0] for point in series.points],
                    [point[1] for point in series.points],
                    series.extrapolation,
                )
                for name, series in self.input_series.items()
            }
        )
        exec("\n".join(lines), namespace)  # noqa: S102
        return namespace


def run_simulation(
    document: ModelDocument,
    parameters: dict[str, float],
    stock_initial: dict[str, float],
    *,
    initial_time: float,
    final_time: float,
    time_step: float,
    output_times: list[float],
    integration_method: str,
    rtol: float,
    atol: float,
    input_series=None,
) -> EngineOutput:
    try:
        namespace = ScipyCompiler(document, parameters, input_series).compile()
        state = np.array(
            namespace["_initial"](initial_time, np.zeros(len(document.variables))), dtype=float
        )
        for index, stock in enumerate(item for item in document.variables if item.kind == "stock"):
            if stock.id in stock_initial:
                state[index] = stock_initial[stock.id]
        derivatives = namespace["_derivatives"]
        if integration_method in {"euler", "rk4"}:
            steps = round((final_time - initial_time) / time_step)
            wanted = set(output_times)
            states = {}
            current = initial_time
            for step in range(steps + 1):
                if any(math.isclose(current, value, rel_tol=0, abs_tol=1e-9) for value in wanted):
                    states[round(step * time_step + initial_time, 12)] = state.copy()
                if step == steps:
                    break
                k1 = np.asarray(derivatives(current, state), dtype=float)
                if integration_method == "euler":
                    state = state + time_step * k1
                else:
                    k2 = np.asarray(
                        derivatives(current + time_step / 2, state + time_step * k1 / 2),
                        dtype=float,
                    )
                    k3 = np.asarray(
                        derivatives(current + time_step / 2, state + time_step * k2 / 2),
                        dtype=float,
                    )
                    k4 = np.asarray(
                        derivatives(current + time_step, state + time_step * k3), dtype=float
                    )
                    state = state + time_step * (k1 + 2 * k2 + 2 * k3 + k4) / 6
                current = initial_time + (step + 1) * time_step
            metadata = {"solver_steps": steps}
        else:
            methods = {"rk45": "RK45", "dop853": "DOP853", "lsoda": "LSODA", "bdf": "BDF"}
            solution = solve_ivp(
                derivatives,
                (initial_time, final_time),
                state,
                method=methods[integration_method],
                t_eval=output_times,
                max_step=time_step,
                rtol=rtol,
                atol=atol,
            )
            if not solution.success:
                raise SimulationError(f"SciPy integration did not converge: {solution.message}")
            metadata = {
                "solver_steps": len(solution.t) - 1,
                "solver_evaluations": int(solution.nfev),
            }
        variables = {item.id: [] for item in document.variables}
        for time in output_times:
            if integration_method in {"euler", "rk4"}:
                point = states[round(time, 12)]
            else:
                index = output_times.index(time)
                point = solution.y[:, index]
            for variable in document.variables:
                variables[variable.id].append(
                    float(namespace[f"_v{document.variables.index(variable)}"](time, point))
                )
        return EngineOutput(time=output_times, variables=variables, metadata=metadata)
    except SimulationError:
        raise
    except Exception as exc:
        raise SimulationError(f"SciPy simulation failed: {type(exc).__name__}: {exc}") from exc
