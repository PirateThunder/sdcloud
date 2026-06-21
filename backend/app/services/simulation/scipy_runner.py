"""SciPy-based simulation runner for generated system-dynamics Python code.

This runner parses LLM-generated Python models (which use the PySD 2.x style
``integ(flow, init)`` convention) and integrates them with
``scipy.integrate.solve_ivp``. It is used as a fallback when PySD cannot load
the generated code directly.
"""

import ast
import logging
import re
import traceback
from typing import Any

import numpy as np
from scipy.integrate import solve_ivp

from app.core.exceptions import SimulationError

logger = logging.getLogger(__name__)


def _is_stock_function(node: ast.FunctionDef) -> tuple[bool, ast.expr | None, ast.expr | None]:
    """Check if a function definition represents a stock (returns integ(...))."""
    if not node.body:
        return False, None, None

    last_stmt = node.body[-1]
    if not isinstance(last_stmt, ast.Return):
        return False, None, None

    value = last_stmt.value
    if not isinstance(value, ast.Call):
        return False, None, None

    func = value.func
    if isinstance(func, ast.Name) and func.id == "integ":
        args = value.args
        if len(args) >= 2:
            return True, args[0], args[1]
        if len(args) == 1:
            # No initial value provided - default to 0
            return True, args[0], ast.Constant(value=0.0)

    return False, None, None


def _sanitize_code_for_parsing(code: str) -> str:
    """Clean up common LLM-generated code issues before AST parsing."""
    code = code.strip()
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]
    code = code.strip()
    # Vensim/PySD sometimes emit uppercase builtins; Python uses lowercase.
    for upper, lower in {"MAX": "max", "MIN": "min", "ABS": "abs"}.items():
        # Use word boundaries to avoid replacing substrings inside identifiers.
        code = re.sub(rf"\b{upper}\b", lower, code)
    return code


def _build_simulation_module(code: str) -> tuple[dict[str, Any], list[str], list[float]]:
    """
    Transform generated Python model code into an executable simulation module.

    The strategy:
    - Stock functions (``def x(time): return integ(flow, init)``) are replaced
      with lookups into a shared global state dictionary.
    - All other (algebraic) functions are kept as-is and call stock functions
      normally; their calls now read from the shared state.
    - A ``derivatives(t, state)`` function updates the shared state and returns
      the net flows for each stock.
    - An ``initial_state()`` function returns the list of initial values.
    """
    code = _sanitize_code_for_parsing(code)

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SimulationError(detail=f"Generated Python code has syntax error: {exc}") from exc

    stock_info: dict[str, tuple[ast.expr, ast.expr]] = {}
    non_stock_nodes: list[ast.AST] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            is_stock, flow_expr, init_expr = _is_stock_function(node)
            if is_stock and flow_expr is not None and init_expr is not None:
                stock_info[node.name] = (flow_expr, init_expr)
                continue
        non_stock_nodes.append(node)

    if not stock_info:
        raise SimulationError(
            detail="No stock variables found in generated model. Cannot run simulation."
        )

    stock_names = list(stock_info.keys())

    # Collect names of all model functions (stocks + algebraic) so we can
    # rewrite bare references into function calls. Generated models often
    # omit parentheses when using variables, e.g.:
    #     def prey_births(time): return prey * prey_growth_rate
    # We rewrite that to:
    #     def prey_births(time): return prey(time) * prey_growth_rate(time)
    all_model_functions: set[str] = set(stock_names)
    algebraic_names: set[str] = set()
    for node in non_stock_nodes:
        if isinstance(node, ast.FunctionDef):
            algebraic_names.add(node.name)
            all_model_functions.add(node.name)

    # Filter out PySD integ imports (they fail in PySD 3.x) and provide a
    # harmless stub so any residual references don't crash parsing.
    cleaned_non_stock_nodes: list[ast.AST] = []
    for node in non_stock_nodes:
        if isinstance(node, ast.ImportFrom):
            if node.module in {"pysd.py_backend.functions", "pysd"}:
                # Only drop the import if it is importing ``integ``.
                if any(alias.name == "integ" for alias in node.names):
                    continue
        cleaned_non_stock_nodes.append(node)

    # Stub for integ so the name is defined in the module namespace.
    integ_stub = ast.FunctionDef(
        name="integ",
        args=ast.arguments(
            posonlyargs=[],
            args=[
                ast.arg(arg="flow", annotation=None),
                ast.arg(arg="initial", annotation=None),
            ],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=[ast.Return(value=ast.Constant(value=None))],
        decorator_list=[],
    )

    class _FunctionCallTransformer(ast.NodeTransformer):
        """Rewrite bare references to model functions as function calls."""

        def __init__(self, func_names: set[str], time_name: str = "time") -> None:
            self.func_names = func_names
            self.time_name = time_name

        def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
            if (
                node.id in self.func_names
                and isinstance(node.ctx, ast.Load)
                and node.id != self.time_name
            ):
                return ast.Call(
                    func=ast.Name(id=node.id, ctx=ast.Load()),
                    args=[ast.Name(id=self.time_name, ctx=ast.Load())],
                    keywords=[],
                )
            return node

        def visit_Call(self, node: ast.Call) -> ast.AST:  # noqa: N802
            # If the call already targets a model function, do not wrap the
            # function name again; only transform its arguments.
            if isinstance(node.func, ast.Name) and node.func.id in self.func_names:
                node.args = [self.visit(arg) for arg in node.args]
                node.keywords = [self.visit(kw) for kw in node.keywords]
                return node
            return self.generic_visit(node)

    # Build stock accessor functions:
    #   def prey_population(time, *args, **kwargs):
    #       return _STATE["prey_population"]
    # Accept *args, **kwargs because generated code may call stocks with
    # extra keyword arguments (e.g. ``prey_population(time, **kwargs)``).
    stock_accessor_nodes: list[ast.AST] = []
    for name in stock_names:
        stock_accessor_nodes.append(
            ast.FunctionDef(
                name=name,
                args=ast.arguments(
                    posonlyargs=[],
                    args=[ast.arg(arg="time", annotation=None)],
                    vararg=ast.arg(arg="args", annotation=None),
                    kwonlyargs=[],
                    kw_defaults=[],
                    kwarg=ast.arg(arg="kwargs", annotation=None),
                    defaults=[],
                ),
                body=[
                    ast.Return(
                        value=ast.Subscript(
                            value=ast.Name(id="_STATE", ctx=ast.Load()),
                            slice=ast.Constant(value=name),
                            ctx=ast.Load(),
                        )
                    )
                ],
                decorator_list=[],
            )
        )

    # Build derivative assignments:
    #   _STATE["prey_population"] = state[0]
    #   prey_population_net = <flow expression>
    #   ...
    #   return [prey_population_net, ...]
    derivative_body: list[ast.stmt] = [
        # Generated functions reference the independent variable as `time`.
        ast.Assign(
            targets=[ast.Name(id="time", ctx=ast.Store())],
            value=ast.Name(id="t", ctx=ast.Load()),
        ),
        # Some generated code spreads ``**kwargs`` in calls; provide an empty
        # dict so those calls remain valid inside the derivative function.
        ast.Assign(
            targets=[ast.Name(id="kwargs", ctx=ast.Store())],
            value=ast.Dict(keys=[], values=[]),
        ),
    ]
    net_names: list[str] = []

    # First, load all stock values into _STATE so algebraic functions can
    # read any stock without depending on assignment order.
    for idx, name in enumerate(stock_names):
        derivative_body.append(
            ast.Assign(
                targets=[
                    ast.Subscript(
                        value=ast.Name(id="_STATE", ctx=ast.Load()),
                        slice=ast.Constant(value=name),
                        ctx=ast.Store(),
                    )
                ],
                value=ast.Subscript(
                    value=ast.Name(id="state", ctx=ast.Load()),
                    slice=ast.Constant(value=idx),
                    ctx=ast.Load(),
                ),
            )
        )

    # Rewrite algebraic function bodies so every model-function reference
    # is invoked with `time`. This makes generated code robust to the LLM
    # omitting parentheses (e.g. ``prey * prey_growth_rate``).
    call_transformer = _FunctionCallTransformer(all_model_functions, time_name="time")
    transformed_non_stock_nodes: list[ast.AST] = []
    for node in cleaned_non_stock_nodes:
        if isinstance(node, ast.FunctionDef):
            node = call_transformer.visit(node)
            ast.fix_missing_locations(node)
        transformed_non_stock_nodes.append(node)

    # Then compute net flows for each stock.
    for name in stock_names:
        flow_expr, _ = stock_info[name]
        # Inside the flow expression, model functions must also be called.
        flow_expr = call_transformer.visit(flow_expr)
        ast.fix_missing_locations(flow_expr)
        net_name = f"_net_{name}"
        net_names.append(net_name)
        derivative_body.append(
            ast.Assign(
                targets=[ast.Name(id=net_name, ctx=ast.Store())],
                value=flow_expr,
            )
        )

    derivative_body.append(
        ast.Return(value=ast.List(elts=[ast.Name(id=n, ctx=ast.Load()) for n in net_names], ctx=ast.Load()))
    )

    # Build initial_state function
    init_body: list[ast.stmt] = []
    for name in stock_names:
        _, init_expr = stock_info[name]
        init_body.append(
            ast.Assign(
                targets=[ast.Name(id=f"_init_{name}", ctx=ast.Store())],
                value=init_expr,
            )
        )
    init_body.append(
        ast.Return(
            value=ast.List(
                elts=[ast.Name(id=f"_init_{name}", ctx=ast.Load()) for name in stock_names],
                ctx=ast.Load(),
            )
        )
    )

    # Assemble module
    module_body: list[ast.AST] = [
        ast.Import(names=[ast.alias(name="numpy", asname="np")]),
        ast.Assign(
            targets=[ast.Name(id="_STATE", ctx=ast.Store())],
            value=ast.Dict(keys=[], values=[]),
        ),
        integ_stub,
        *transformed_non_stock_nodes,
        *stock_accessor_nodes,
        ast.FunctionDef(
            name="derivatives",
            args=ast.arguments(
                posonlyargs=[],
                args=[
                    ast.arg(arg="t", annotation=None),
                    ast.arg(arg="state", annotation=None),
                ],
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=derivative_body,
            decorator_list=[],
        ),
        ast.FunctionDef(
            name="initial_state",
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=init_body,
            decorator_list=[],
        ),
    ]

    new_module = ast.Module(body=module_body, type_ignores=[])
    ast.fix_missing_locations(new_module)

    namespace: dict[str, Any] = {"__builtins__": __builtins__}
    try:
        compiled = compile(new_module, "<generated_model>", "exec")
        exec(compiled, namespace)  # noqa: S102
    except Exception as exc:
        logger.error(
            "Failed to compile generated model for SciPy.\nOriginal code:\n%s\nTransformed module dump:\n%s",
            code,
            ast.dump(new_module, indent=2),
        )
        raise SimulationError(
            detail=f"Failed to compile generated model for SciPy: {exc}\n{traceback.format_exc()}"
        ) from exc

    initial_values = namespace["initial_state"]()
    return namespace, stock_names, initial_values


def run_simulation(
    python_code: str,
    params: dict[str, float] | None = None,
    time_start: float = 0.0,
    time_end: float = 100.0,
    time_step: float = 0.25,
    integration_method: str = "rk45",
) -> dict[str, list[float]]:
    """
    Run a system-dynamics simulation from generated Python code using SciPy.

    Args:
        python_code: Python model code using ``integ(flow, init)`` stocks.
        params: Parameter overrides.
        time_start: Simulation start time.
        time_end: Simulation end time.
        time_step: Output time step.
        integration_method: SciPy solver method (rk45, rkf45, dop853, lsoda, etc.).

    Returns:
        Dict with ``time`` and variable names mapped to lists of values.
    """
    namespace, stock_names, initial_values = _build_simulation_module(python_code)

    params = params or {}

    # Apply parameter overrides. Stock initial values are handled separately
    # from constant/flow/auxiliary overrides so the shared-state machinery
    # keeps working.
    stock_initial_overrides: dict[str, float] = {}
    for param_name, param_value in params.items():
        if not isinstance(param_value, (int, float)):
            continue
        if param_name in stock_names:
            stock_initial_overrides[param_name] = float(param_value)
        elif param_name in namespace:
            namespace[param_name] = lambda t, v=float(param_value): v  # type: ignore[misc]

    if stock_initial_overrides:
        original_initial_state = namespace["initial_state"]

        def _overridden_initial_state() -> list[float]:
            base = original_initial_state()
            return [
                stock_initial_overrides.get(name, val)
                for name, val in zip(stock_names, base, strict=True)
            ]

        namespace["initial_state"] = _overridden_initial_state

    derivatives_fn = namespace["derivatives"]
    initial_state = np.array(namespace["initial_state"](), dtype=float)

    n_steps = int((time_end - time_start) / time_step) + 1
    t_eval = np.linspace(time_start, time_end, n_steps)

    method_map = {
        "euler": "RK45",
        "rk4": "RK45",
        "rk45": "RK45",
        "rkf45": "RK45",
        "dop853": "DOP853",
        "lsoda": "LSODA",
        "bdf": "BDF",
    }
    scipy_method = method_map.get(integration_method.lower(), "RK45")

    try:
        sol = solve_ivp(
            derivatives_fn,
            [time_start, time_end],
            initial_state,
            method=scipy_method,
            t_eval=t_eval,
        )
    except Exception as exc:
        logger.error(
            "SciPy integration failed.\nOriginal code:\n%s\nInitial state: %s",
            python_code,
            initial_state,
        )
        raise SimulationError(
            detail=f"SciPy integration failed: {exc}\n{traceback.format_exc()}"
        ) from exc

    if not sol.success:
        raise SimulationError(detail=f"SciPy integration did not converge: {sol.message}")

    output: dict[str, list[float]] = {"time": sol.t.tolist()}
    for i, name in enumerate(stock_names):
        output[name] = sol.y[i].tolist()

    return output
