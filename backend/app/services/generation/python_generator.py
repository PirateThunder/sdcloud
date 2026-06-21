"""Deterministic Python code generator from structured equations."""

from __future__ import annotations

import ast


def _build_call_transformer(variable_names: set[str]) -> ast.NodeTransformer:
    """Return a transformer that turns bare variable refs into function calls."""

    # Normalize Vensim-style uppercase function names to Python builtins.
    function_aliases = {"MAX": "max", "MIN": "min", "ABS": "abs"}

    class CallTransformer(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
            if node.id in variable_names and isinstance(node.ctx, ast.Load):
                return ast.Call(
                    func=ast.Name(id=node.id, ctx=ast.Load()),
                    args=[ast.Name(id="time", ctx=ast.Load())],
                    keywords=[],
                )
            if node.id in function_aliases and isinstance(node.ctx, ast.Load):
                return ast.Name(id=function_aliases[node.id], ctx=ast.Load())
            return node

    return CallTransformer()


def generate_python_code(
    variables: list[dict],
    equations: list[dict],
) -> str:
    """
    Generate PySD-compatible Python code from structured variables/equations.

    This is deterministic and avoids LLM hallucinations such as undefined
    variables or incorrect imports. All model variables are turned into
    functions of ``time``; bare references inside expressions are rewritten
    as function calls.
    """
    if not equations:
        return ""

    variable_names = {v["name"] for v in variables}
    variable_types = {v["name"]: v.get("type", "") for v in variables}

    transformer = _build_call_transformer(variable_names)

    function_lines: list[str] = []

    for eq in equations:
        lhs = eq.get("lhs", "")
        rhs = str(eq.get("rhs", "")).strip()
        vtype = eq.get("variable_type", "").lower()
        if not lhs or not rhs:
            continue

        try:
            rhs_tree = ast.parse(rhs, mode="eval")
            rhs_tree = transformer.visit(rhs_tree)
            ast.fix_missing_locations(rhs_tree)
            transformed_rhs = ast.unparse(rhs_tree.body)
        except SyntaxError:
            # Fall back to the raw RHS if parsing fails.
            transformed_rhs = rhs

        if vtype == "stock":
            # Stocks already use integ(..., initial_value) in the RHS.
            function_lines.append(f"\ndef {lhs}(time):")
            function_lines.append(f"    return {transformed_rhs}")
        else:
            function_lines.append(f"\ndef {lhs}(time):")
            function_lines.append(f"    return {transformed_rhs}")

    if not function_lines:
        return ""

    code_lines = [
        "import numpy as np",
        "from pysd.py_backend.functions import integ",
    ]
    code_lines.extend(function_lines)
    return "\n".join(code_lines).strip()
