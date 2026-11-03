from __future__ import annotations

import ast

from .exceptions import ModelValidationError
from .legacy import flow_sign, parse_legacy
from .naming import identifier
from .units import parse_units


def migrate_v1(value: dict) -> dict:
    raw_variables = value.get("variables") or []
    equations = {item.get("lhs"): item.get("rhs") for item in value.get("equations") or []}
    used: set[str] = set()
    names: dict[str, str] = {}
    for variable in raw_variables:
        original = variable.get("name", "variable")
        names[original] = identifier(original, used)
        used.add(names[original])
    variables = []
    flows: list[dict] = []
    for raw in raw_variables:
        original = raw["name"]
        name = names[original]
        kind = raw.get("type", "auxiliary")
        common = {
            "id": name,
            "label": original,
            "description": raw.get("description"),
            "units": parse_units(raw.get("units")),
            "units_raw": raw.get("units"),
        }
        rhs = equations.get(original)
        if rhs is None:
            raise ModelValidationError(f"legacy variable has no equation: {original}")
        if kind == "stock":
            initial, derivative = _stock_parts(rhs, float(raw.get("initial_value") or 0))
            variables.append(
                {
                    **common,
                    "kind": "stock",
                    "initial": initial.model_dump(mode="json"),
                    "derivative": derivative.model_dump(mode="json"),
                }
            )
        else:
            expression = parse_legacy(rhs)
            item = {
                **common,
                "kind": kind,
                "expression": expression.model_dump(mode="json"),
            }
            if kind == "flow":
                item["topology_status"] = "missing"
                flows.append(item)
            variables.append(item)
    _restore_topology(variables, flows)
    return {
        "schema_version": "2.0",
        "id": "model",
        "name": "Migrated system dynamics model",
        "description": value.get("description") or "Migrated model",
        "time": {
            "unit": next(
                (
                    name
                    for raw in raw_variables
                    if raw.get("type") == "flow"
                    for name, power in (parse_units(raw.get("units")) or {}).items()
                    if power == -1 and name in {"day", "week", "month", "year", "hour", "minute"}
                ),
                "time",
            ),
            "initial_time": 0,
            "final_time": 100,
            "time_step": 0.25,
            "saveper": 0.25,
        },
        "variables": variables,
        "assumptions": [],
        "provenance": {"kind": "migration"},
        **({"created_at": value["created_at"]} if value.get("created_at") else {}),
    }


def _stock_parts(rhs: str, fallback: float):
    try:
        tree = ast.parse(rhs, mode="eval")
    except SyntaxError as exc:
        raise ModelValidationError(f"invalid legacy stock: {exc.msg}") from exc
    if not isinstance(tree.body, ast.Call) or not isinstance(tree.body.func, ast.Name):
        raise ModelValidationError("legacy stock must use integ(flow, initial)")
    if tree.body.func.id.lower() != "integ" or len(tree.body.args) != 2:
        raise ModelValidationError("legacy stock must use integ(flow, initial)")
    from .ir import lit

    return parse_legacy(ast.unparse(tree.body.args[1])) if tree.body.args[1] else lit(
        fallback
    ), parse_legacy(ast.unparse(tree.body.args[0]))


def _restore_topology(variables: list[dict], flows: list[dict]) -> None:
    for flow in flows:
        positive = []
        negative = []
        for stock in variables:
            if stock["kind"] != "stock":
                continue
            derivative = stock["derivative"]
            sign = flow_sign(_expression(derivative), flow["id"])
            if sign > 0:
                positive.append(stock["id"])
            elif sign < 0:
                negative.append(stock["id"])
        if len(positive) == 1 and len(negative) == 1:
            flow["source"] = {"kind": "stock", "id": negative[0]}
            flow["target"] = {"kind": "stock", "id": positive[0]}
        elif len(positive) == 1 and not negative:
            flow["source"] = {"kind": "cloud", "id": f"source_{flow['id']}"}
            flow["target"] = {"kind": "stock", "id": positive[0]}
        elif len(negative) == 1 and not positive:
            flow["source"] = {"kind": "stock", "id": negative[0]}
            flow["target"] = {"kind": "cloud", "id": f"sink_{flow['id']}"}
        else:
            continue
        flow["topology_status"] = "inferred"


def _expression(value: dict):
    from pydantic import TypeAdapter

    from .schemas import Expression

    return TypeAdapter(Expression).validate_python(value)
