"""Post-process LLM-generated model artifacts to fix common defaults."""

from __future__ import annotations

import ast
import logging
import re

logger = logging.getLogger(__name__)


def _safe_float(value: object) -> float | None:
    """Convert a value to float if possible."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _infer_constant_default(var: dict) -> str:
    """Pick a sensible non-zero default for a constant based on name/units."""
    name = str(var.get("name", "")).lower()
    units = str(var.get("units", "")).lower()
    iv = _safe_float(var.get("initial_value"))

    # Prefer the user-provided initial value if it is non-zero
    if iv is not None and iv != 0.0:
        return repr(iv)

    # Name-based heuristics
    if any(k in name for k in ("rate", "fraction", "probability", "share", "coefficient", "elasticity")):
        return "0.05"
    if any(k in name for k in ("growth", "birth", "death", "decay", "interest")):
        return "0.02"
    if any(k in name for k in ("capacity", "limit", "max", "initial", "start")):
        return "1000.0"
    if any(k in units for k in ("year", "month", "day")) and "rate" in name:
        return "0.1"

    # Generic small non-zero default
    return "0.1"


def _patch_constant_equation(eq: dict, variables: list[dict]) -> dict:
    """Ensure constants have a meaningful, non-zero RHS."""
    lhs = eq.get("lhs", "")
    rhs = str(eq.get("rhs", "")).strip()

    if rhs in ("", "0", "0.0"):
        matching = [v for v in variables if v.get("name") == lhs and v.get("type") == "constant"]
        default = _infer_constant_default(matching[0]) if matching else "0.1"
        logger.warning(f"Constant '{lhs}' had zero/empty RHS; patching to {default}")
        eq["rhs"] = default
        eq["_patched"] = True

    return eq


def _patch_stock_equation(eq: dict, variables: list[dict]) -> dict:
    """Ensure stock integ() initial values are non-zero and taken from variables."""
    lhs = eq.get("lhs", "")
    rhs = str(eq.get("rhs", "")).strip()

    match = re.search(r"integ\(([^,]+),\s*([^)]+)\)", rhs)
    if not match:
        return eq

    init_str = match.group(2).strip()
    init_val = _safe_float(_try_eval(init_str))

    if init_val is None or init_val == 0.0:
        matching = [v for v in variables if v.get("name") == lhs and v.get("type") == "stock"]
        if matching:
            replacement = _safe_float(matching[0].get("initial_value"))
            if replacement is None or replacement == 0.0:
                replacement = 100.0
        else:
            replacement = 100.0

        new_rhs = re.sub(
            r"(integ\([^,]+,\s*)[^)]+(\))",
            rf"\g<1>{replacement}\g<2>",
            rhs,
            count=1,
        )
        logger.warning(f"Stock '{lhs}' had zero initial value; patching to {replacement}")
        eq["rhs"] = new_rhs
        eq["_patched"] = True

    return eq


def _try_eval(expr: str) -> object:
    """Safely evaluate a simple numeric literal."""
    try:
        return ast.literal_eval(expr)
    except (SyntaxError, ValueError):
        return expr


def post_process_equations(variables: list[dict], equations: list[dict]) -> list[dict]:
    """
    Patch common LLM mistakes in generated equations.

    - Constants with 0.0/empty RHS get a realistic non-zero default.
    - Stocks with integ(..., 0.0) get initial value from variables or 100.0.
    """
    if not equations:
        return equations

    patched: list[dict] = []
    for eq in equations:
        eq = dict(eq)
        vtype = eq.get("variable_type", "").lower()
        if vtype == "constant":
            eq = _patch_constant_equation(eq, variables)
        elif vtype == "stock":
            eq = _patch_stock_equation(eq, variables)
        patched.append(eq)

    return patched
