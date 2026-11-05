from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .codegen import export_vensim, generate_python_code
from .components import build_components, normalize_component_payload, normalize_inferred_time
from .exceptions import LLMResponseError, ModelValidationError
from .expression_parser import normalize_expression
from .formats import export_xmile
from .io import write_json_atomic, write_stage
from .ir import dependencies, ref, walk
from .llm import LLMClient
from .ode_equivalence import apply_explicit_odes, validate_explicit_odes
from .pattern_library import pattern_prompt, select_pattern
from .prompts import (
    BRIEF_REPAIR_PROMPT,
    COMPONENT_BRIEF_GUIDANCE,
    COMPONENT_PLAN_PROMPT,
    EQUATION_GENERATION_PROMPT,
    MODEL_BRIEF_PROMPT,
    REPAIR_PROMPT,
    STAGE_REPAIR_PROMPT,
    VARIABLE_EXTRACTION_PROMPT,
)
from .rag import component_rag_context
from .schemas import (
    Assumption,
    ComponentPlan,
    Expression,
    FlowEndpoint,
    FlowVariable,
    GenerationRequest,
    LookupTable,
    ModelBrief,
    ModelDocument,
    SDVariable,
    SimulationParameters,
    TimeSettings,
    ValidationIssue,
)
from .semantics import with_semantic_validation
from .simulation import simulate_model
from .units import combine
from .validation import finalize_model


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_EXPRESSION_INPUT_SCHEMA = {
    "anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]
}
_UNITS_SCHEMA = {"type": "object", "additionalProperties": {"type": "integer"}}
_ENDPOINT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["stock", "cloud"]},
        "id": {"type": "string"},
    },
    "required": ["kind", "id"],
    "additionalProperties": False,
}
_BASE_VARIABLE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": ["stock", "flow", "auxiliary", "constant"]},
        "label": _nullable({"type": "string"}),
        "description": _nullable({"type": "string"}),
        "units": _nullable(_UNITS_SCHEMA),
        "units_raw": _nullable({"type": "string"}),
        "bounds": _nullable(
            {
                "type": "object",
                "properties": {
                    "min": _nullable({"type": "number"}),
                    "max": _nullable({"type": "number"}),
                    "on_violation": {"type": "string", "enum": ["error", "warn"]},
                },
                "required": ["min", "max", "on_violation"],
                "additionalProperties": False,
            }
        ),
        "subscripts": {"type": "array", "items": {"type": "string"}},
        "initial": _nullable(_EXPRESSION_INPUT_SCHEMA),
        "derivative": _nullable(_EXPRESSION_INPUT_SCHEMA),
        "allow_isolated": {"type": "boolean"},
        "expression": _nullable(_EXPRESSION_INPUT_SCHEMA),
        "source": _nullable(_ENDPOINT_SCHEMA),
        "target": _nullable(_ENDPOINT_SCHEMA),
        "topology_status": {
            "type": "string",
            "enum": ["declared", "inferred", "missing"],
        },
        "exogenous": {"type": "boolean"},
    },
    "additionalProperties": False,
}


def _typed_variable_schema(kind: str) -> dict:
    properties = dict(_BASE_VARIABLE_ITEM_SCHEMA["properties"])
    properties["kind"] = {"type": "string", "enum": [kind]}
    if kind in {"stock", "constant"}:
        properties["initial"] = _EXPRESSION_INPUT_SCHEMA
    return {**_BASE_VARIABLE_ITEM_SCHEMA, "properties": properties}


_VARIABLE_ITEM_SCHEMA = {
    "anyOf": [
        _typed_variable_schema(kind) for kind in ("stock", "flow", "auxiliary", "constant")
    ]
}
_TABLE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "label": _nullable({"type": "string"}),
        "points": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "number"}},
        },
        "x_units": _nullable(_UNITS_SCHEMA),
        "y_units": _nullable(_UNITS_SCHEMA),
        "interpolation": {"type": "string", "enum": ["linear"]},
        "extrapolation": {"type": "string", "enum": ["clamp", "linear", "error"]},
    },
    "additionalProperties": False,
}
_ASSUMPTION_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "value": {"type": "string"},
        "source": {
            "type": "string",
            "enum": ["user", "archetype", "llm_inferred", "imported", "migration"],
        },
        "rationale": {"type": "string"},
        "requires_confirmation": {"type": "boolean"},
    },
    "required": ["path", "value", "source", "rationale", "requires_confirmation"],
    "additionalProperties": False,
}
_TIME_SCHEMA = {
    "type": "object",
    "properties": {
        "unit": {"type": "string"},
        "initial_time": {"type": "number"},
        "final_time": {"type": "number"},
        "time_step": {"type": "number", "exclusiveMinimum": 0},
        "saveper": {"type": "number", "exclusiveMinimum": 0},
    },
    "required": ["unit", "initial_time", "final_time", "time_step", "saveper"],
    "additionalProperties": False,
}
_VARIABLES_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "time": _TIME_SCHEMA,
        "variables": {
            "type": "array",
            "items": _VARIABLE_ITEM_SCHEMA,
            "minItems": 1,
            "maxItems": 200,
        },
        "tables": {"type": "array", "items": _TABLE_ITEM_SCHEMA},
        "assumptions": {"type": "array", "items": _ASSUMPTION_ITEM_SCHEMA},
    },
    "required": ["name", "time", "variables", "tables", "assumptions"],
    "additionalProperties": False,
}
_EQUATIONS_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "expressions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "expression": _EXPRESSION_INPUT_SCHEMA,
                },
                "required": ["id", "expression"],
                "additionalProperties": False,
            },
            "minItems": 1,
        }
    },
    "required": ["expressions"],
    "additionalProperties": False,
}


def _save_stage(workdir: Path | None, stage: str, value: Any = None) -> None:
    if workdir is None:
        return
    write_stage(workdir, stage)
    if value is not None:
        write_json_atomic(workdir / f"{stage}.json", value)


@dataclass
class _RepairBudget:
    maximum: int
    attempts: int = 0

    def take(self) -> bool:
        if self.attempts >= self.maximum:
            return False
        self.attempts += 1
        return True


def _json_excerpt(value: Any, limit: int = 12_000) -> str:
    if isinstance(value, str):
        return value[:limit]
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)[:limit]
    except (TypeError, ValueError):
        return repr(value)[:limit]


async def _call_stage[T](
    llm: LLMClient,
    *,
    stage: str,
    prompt: str,
    system: str,
    temperature: float,
    response_schema: dict | None,
    parser: Callable[[Any], T],
    budget: _RepairBudget,
    workdir: Path | None,
) -> T:
    current_stage = stage
    current_prompt = prompt
    previous_response = ""
    while True:
        try:
            response = await llm.chat_json(
                current_prompt,
                stage=current_stage,
                system=system,
                temperature=temperature,
                response_schema=response_schema,
            )
            previous_response = _json_excerpt(response)
            _save_stage(workdir, f"{current_stage}_response", response)
            return parser(response)
        except (LLMResponseError, ModelValidationError, ValidationError) as exc:
            if isinstance(exc, LLMResponseError) and exc.response_text:
                previous_response = exc.response_text
            if not budget.take():
                if isinstance(exc, ValidationError):
                    raise ModelValidationError(
                        f"invalid {stage}: {exc}", repair_attempts=budget.attempts
                    ) from exc
                exc.repair_attempts = budget.attempts
                raise
            repair_stage = f"{stage}_repair_{budget.attempts}"
            _save_stage(
                workdir,
                repair_stage,
                {"error": str(exc), "response": previous_response},
            )
            current_stage = repair_stage
            template = BRIEF_REPAIR_PROMPT if stage == "brief" else STAGE_REPAIR_PROMPT
            current_prompt = template.format(
                stage=stage,
                error=str(exc)[:6000],
                original_prompt=_json_excerpt(prompt, 20_000),
                response=(
                    _json_excerpt(previous_response, 8_000)
                    if stage != "brief" or budget.attempts == 1
                    else ""
                ),
            )


def model_context(document: ModelDocument) -> str:
    payload = document.model_dump(
        mode="json",
        include={
            "id",
            "name",
            "description",
            "time",
            "variables",
            "tables",
            "dimensions",
            "assumptions",
            "brief",
            "pattern_id",
        },
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def conversation_history(request: GenerationRequest) -> str:
    if not request.history:
        return "No previous messages."
    return "\n".join(f"{item.role}: {item.content}" for item in request.history)


def _description(request: GenerationRequest) -> str:
    history = conversation_history(request)
    if request.base_model is not None:
        return (
            f"Conversation context:\n{history}\n\n"
            f"Current canonical model (the source of truth):\n{model_context(request.base_model)}\n\n"
            f"Requested change:\n{request.description}\n\n"
            "Apply the requested change to the current model. Preserve all variables, equations, "
            "topology, units, settings and assumptions that the user did not ask to change. "
            "Return a complete updated model, not a patch. Treat conversation history as context, "
            "not as additional simultaneous changes."
        )
    return f"Conversation context:\n{history}\n\nCurrent request:\n{request.description}"


def _ode_guidance(pattern) -> str:
    if pattern is not None:
        return ""
    return """\
- Для математических ODE задавай каждую state variable как stock с initial и derivative.
  Не создавай отдельный flow для каждой производной: builder создаст эквивалентный net flow.
  Flow используй только для явных материальных переходов с известными endpoints.
- Если stock физически неотрицателен (people, packets, mass), задай bounds.min=0 и
  on_violation="error", а также nonnegative flow policy через min/max. Не скрывай отрицательные
  значения через clamp. Для нулевого начального delay используй delay3i/smooth3i с явным
  initial argument, а не несогласованные ручные pipeline stocks.
"""


def _variables(response: Any) -> tuple[dict, list[dict]]:
    if not isinstance(response, dict) or not isinstance(response.get("variables"), list):
        raise ModelValidationError("variable extraction must return an object with variables")
    raw = response["variables"]
    if not raw or len(raw) > 200:
        raise ModelValidationError("model must contain between 1 and 200 variables")
    if not all(isinstance(item, dict) for item in raw):
        raise ModelValidationError("every variable must be an object")
    return response, raw


def _allows_monetary_budget(pattern, description: str) -> bool:
    if pattern is None or pattern.id != "bass_diffusion":
        return True
    return any(
        token in description.lower()
        for token in ("dollar", "euro", "ruble", "currency", "budget", "бюджет", "рубл", "деньг")
    )


def _requires_normalized_pattern(pattern, description: str) -> bool:
    if pattern is None or pattern.id not in {
        "lorenz_system",
        "van_der_pol_oscillator",
        "duffing_oscillator",
    }:
        return False
    return not any(
        token in description.lower()
        for token in (
            "capacitance",
            "inductance",
            "farad",
            "henry",
            "ohm",
            "newton",
            "pascal",
            "kilogram",
            "si units",
            "second",
        )
    )


def _validate_brief_scope(brief: ModelBrief, pattern, description: str) -> None:
    if _requires_normalized_pattern(pattern, description):
        expected = {
            "stocks": {item.id for item in pattern.document.variables if item.kind == "stock"},
            "flows": {item.id for item in pattern.document.variables if item.kind == "flow"},
            "exogenous_inputs": {
                item.id for item in pattern.document.variables if item.kind == "constant"
            },
        }
        actual = {
            "stocks": set(brief.stocks),
            "flows": set(brief.flows),
            "exogenous_inputs": set(brief.exogenous_inputs),
        }
        if (
            actual["stocks"] != expected["stocks"]
            or actual["flows"] != expected["flows"]
            or not actual["exogenous_inputs"] <= expected["exogenous_inputs"]
        ):
            raise ModelValidationError(
                f"{pattern.id} needs normalized ModelBrief ids: expected={expected}, "
                f"actual={actual}. Stocks/flows must match; exogenous inputs may be "
                "a subset of pattern constants. Use the supplied validated pattern."
            )
        return
    if _allows_monetary_budget(pattern, description):
        return
    monetary_inputs = [
        item
        for item in brief.exogenous_inputs
        if any(
            token in item.lower()
            for token in ("dollar", "euro", "ruble", "currency", "budget", "бюджет", "рубл", "деньг")
        )
    ]
    if monetary_inputs:
        raise ModelValidationError(
            "Bass ModelBrief must use fractional innovation/imitation rates, "
            f"not unrequested monetary inputs: {monetary_inputs}"
        )


def _validate_normalized_scope(
    raw: list[dict], pattern, description: str, time_unit: str | None
) -> None:
    if not _requires_normalized_pattern(pattern, description):
        return
    expected = {
        (item.id, item.kind, tuple(sorted((item.units or {}).items())))
        for item in pattern.document.variables
    }
    actual = {
        (item.get("id"), item.get("kind"), tuple(sorted((item.get("units") or {}).items())))
        for item in raw
    }
    expected_time = pattern.document.time.unit
    if actual != expected or (time_unit is not None and time_unit != expected_time):
        raise ModelValidationError(
            f"{pattern.id} needs normalized pattern ids, kinds, units and time.unit="
            f"{expected_time!r}; unrequested physical parameters are not allowed. "
            f"Missing={sorted(expected - actual)}; unexpected={sorted(actual - expected)}; "
            f"time.unit={time_unit!r}. Use the supplied validated pattern."
        )


def _validate_variable_scope(
    raw: list[dict], pattern, description: str, time_unit: str | None = None
) -> None:
    _validate_normalized_scope(raw, pattern, description, time_unit)
    if _allows_monetary_budget(pattern, description):
        return
    monetary_units = sorted(
        {
            unit
            for item in raw
            for unit in (item.get("units") or {})
            if any(token in unit.lower() for token in ("dollar", "euro", "ruble", "currency"))
        }
    )
    if monetary_units:
        raise ModelValidationError(
            "Bass diffusion needs fractional innovation/imitation rates with units 1/time, "
            f"not an unrequested monetary advertising budget: {monetary_units}. "
            "Use one adoption flow from potential_adopters to adopters and remove monetary variables."
        )


def _normalize_assumptions(
    values: Any,
    variables: list[dict],
    time_settings: dict | None = None,
) -> Any:
    if not isinstance(values, list):
        return values
    by_id = {item.get("id"): item for item in variables}
    result = []
    for item in values:
        if not isinstance(item, dict):
            result.append(item)
            continue
        value = dict(item)
        raw_value = value.get("value")
        empty = isinstance(raw_value, str) and not raw_value.strip()
        if empty:
            parts = str(value.get("path", "")).split(".")
            if len(parts) == 1 and parts[0] in by_id:
                parts = ["variables", parts[0]]
            elif (
                len(parts) == 2
                and parts[0] in by_id
                and parts[1] in {"initial", "expression"}
            ):
                parts = ["variables", *parts]
            if parts[0] == "variables":
                value["path"] = ".".join(parts)
            candidate = None
            if len(parts) in {2, 3} and parts[0] == "variables":
                variable = by_id.get(parts[1], {})
                field = parts[2] if len(parts) == 3 else "initial"
                if field not in {"initial", "expression"}:
                    field = "initial"
                candidate = variable.get(field)
                if candidate is None and len(parts) == 2:
                    candidate = variable.get("expression")
            elif (
                len(parts) == 2
                and parts[0] == "time"
                and isinstance(time_settings, dict)
            ):
                candidate = time_settings.get(parts[1])
            if candidate is not None:
                raw_value = candidate
                value["value"] = candidate
        if isinstance(raw_value, bool | int | float):
            value["value"] = str(raw_value)
        elif empty and isinstance(raw_value, dict | list):
            value["value"] = json.dumps(raw_value, ensure_ascii=False)
        result.append(value)
    return result


def _normalize_time_settings(value: Any, default: TimeSettings | None) -> Any:
    if not isinstance(value, dict):
        return value
    result = dict(value)
    initial_time = result.get("initial_time")
    if not isinstance(initial_time, int | float) or isinstance(initial_time, bool):
        initial_time = default.initial_time if default else 0
    final_time = result.get("final_time")
    if not isinstance(final_time, int | float) or isinstance(final_time, bool):
        final_time = default.final_time if default else initial_time + 100
    if final_time <= initial_time:
        final_time = default.final_time if default else initial_time + 100
    time_step = result.get("time_step")
    if not isinstance(time_step, int | float) or isinstance(time_step, bool) or time_step <= 0:
        time_step = default.time_step if default else 0.25
    saveper = result.get("saveper")
    if not isinstance(saveper, int | float) or isinstance(saveper, bool) or saveper <= 0:
        saveper = default.saveper if default else time_step
    result.update(
        unit=result.get("unit") or (default.unit if default else "year"),
        initial_time=initial_time,
        final_time=final_time,
        time_step=time_step,
        saveper=saveper,
    )
    return result


def _variable_response(response: Any, *, default_time: TimeSettings | None = None) -> tuple[dict, list[dict]]:
    metadata, raw = _variables(response)
    metadata = dict(metadata)
    raw = [item for item in raw if item.get("id") not in {"time", "pi", "e"}]
    stock_ids = {
        endpoint.get("id")
        for item in raw
        if isinstance(item, dict) and item.get("kind") == "flow"
        for endpoint in (item.get("source"), item.get("target"))
        if isinstance(endpoint, dict) and endpoint.get("kind") == "stock"
    }
    normalized = []
    for item in raw:
        value = dict(item)
        if isinstance(value.get("units"), dict):
            value["units"] = {
                name: power
                for name, power in value["units"].items()
                if name not in {"1", "dimensionless"}
            }
        kind = "stock" if value.get("id") in stock_ids else value.get("kind")
        value["kind"] = kind
        if kind == "stock" and value.get("initial") is None and value.get("expression") is not None:
            value["initial"] = value["expression"]
        if kind == "stock":
            if value.get("initial") is None:
                raise ModelValidationError(
                    f"missing initial for stock {value.get('id')}: expected a number or formula, not null"
                )
            value["initial"] = normalize_expression(value["initial"])
            if value.get("derivative") is not None:
                value["derivative"] = normalize_expression(value["derivative"])
        else:
            expression = value.get("expression")
            if expression is None:
                expression = value.get("initial")
            if expression is not None:
                value["expression"] = normalize_expression(expression)
            else:
                value.pop("expression", None)
            value.pop("initial", None)
        common = {"id", "kind", "label", "description", "units", "units_raw", "bounds", "subscripts"}
        fields = {
            "stock": common | {"initial", "derivative", "allow_isolated"},
            "flow": common | {"expression", "source", "target", "topology_status"},
            "auxiliary": common | {"expression"},
            "constant": common | {"expression", "exogenous"},
        }.get(kind)
        if fields is None:
            raise ModelValidationError(f"invalid variable kind: {kind!r}")
        value = {key: item for key, item in value.items() if key in fields}
        candidate = dict(value)
        if kind != "stock":
            initial = candidate.pop("initial", None)
            if candidate.get("expression") is None:
                candidate["expression"] = initial or {"op": "lit", "value": 0}
        try:
            TypeAdapter(SDVariable).validate_python(candidate)
        except ValidationError as exc:
            raise ModelValidationError(f"invalid variable {value.get('id')}: {exc}") from exc
        normalized.append(value)
    ids = {item.get("id") for item in normalized}
    stocks = {item.get("id") for item in normalized if item.get("kind") == "stock"}
    for item in normalized:
        if item.get("kind") != "flow":
            continue
        for field in ("source", "target"):
            endpoint = item.get(field)
            if not isinstance(endpoint, dict):
                continue
            if endpoint.get("kind") == "cloud" and endpoint.get("id") in stocks:
                endpoint["kind"] = "stock"
            elif endpoint.get("kind") == "cloud" and endpoint.get("id") in ids:
                base = f"{item.get('id')}_{endpoint.get('id')}"[:110]
                candidate = base
                suffix = 2
                while candidate in ids:
                    candidate = f"{base}_{suffix}"
                    suffix += 1
                endpoint["id"] = candidate
    unknown_endpoints = [
        f"variables.{item.get('id')}.{field}={endpoint.get('id')}"
        for item in normalized
        if item.get("kind") == "flow"
        for field in ("source", "target")
        if isinstance(endpoint := item.get(field), dict)
        and endpoint.get("kind") == "stock"
        and endpoint.get("id") not in stocks
    ]
    if unknown_endpoints:
        raise ModelValidationError(
            f"unknown stock endpoints: {unknown_endpoints}; "
            "declare the endpoint stock or use kind='cloud' for an external source/sink"
        )
    for item in normalized:
        for field in ("initial", "derivative", "expression"):
            if item.get(field) is None:
                continue
            expression = TypeAdapter(Expression).validate_python(item[field])
            unknown = dependencies(expression) - ids
            if unknown:
                raise ModelValidationError(
                    f"variables.{item.get('id')}.{field} references unknown variables: "
                    f"{sorted(unknown)}"
                )
    metadata["variables"] = normalized
    try:
        if metadata.get("time") is not None:
            metadata["time"] = TimeSettings.model_validate(
                _normalize_time_settings(metadata["time"], default_time)
            ).model_dump(mode="json")
        if "tables" in metadata:
            metadata["tables"] = [
                item.model_dump(mode="json")
                for item in TypeAdapter(list[LookupTable]).validate_python(metadata["tables"])
            ]
        if "assumptions" in metadata:
            metadata["assumptions"] = [
                item.model_dump(mode="json")
                for item in TypeAdapter(list[Assumption]).validate_python(
                    _normalize_assumptions(
                        metadata["assumptions"],
                        raw,
                        metadata.get("time")
                        or (
                            default_time.model_dump(mode="json")
                            if default_time is not None
                            else None
                        ),
                    )
                )
            ]
    except ValidationError as exc:
        raise ModelValidationError(f"invalid generated model metadata: {exc}") from exc
    return metadata, normalized


def _expressions(response: Any) -> dict[str, Any]:
    if isinstance(response, dict) and "expressions" not in response:
        raw = response.get("variables", response)
    else:
        raw = response.get("expressions") if isinstance(response, dict) else response
    if isinstance(raw, list):
        raw = {
            item.get("id"): item.get("expression", item.get("initial"))
            for item in raw
            if isinstance(item, dict) and item.get("kind") != "stock"
        }
    if isinstance(raw, dict):
        raw = {key: value for key, value in raw.items() if key not in {"time", "pi", "e"}}
    if not isinstance(raw, dict) or not raw:
        raise ModelValidationError("equation generation returned no expressions")
    return raw


def _merge(
    raw: list[dict], expressions: dict[str, Any], *, time_unit: str = "year"
) -> list[SDVariable]:
    expressions = {key: value for key, value in expressions.items() if key not in {"time", "pi", "e"}}
    ids = {item.get("id") for item in raw}
    stock_ids = {item.get("id") for item in raw if item.get("kind") == "stock"}
    unknown = set(expressions) - ids - stock_ids
    if unknown:
        raise ModelValidationError(
            f"expressions reference undeclared variable ids: {sorted(unknown)}"
        )
    expressions = {key: value for key, value in expressions.items() if key in ids}
    merged = []
    for item in raw:
        value = dict(item)
        if value.get("kind") == "stock":
            value["initial"] = normalize_expression(value["initial"])
            if value.get("derivative") is not None:
                value["derivative"] = normalize_expression(value["derivative"])
        else:
            fallback = value.pop("initial", None)
            expression = value.get("expression")
            if expression is None or value.get("kind") != "constant":
                supplied = expressions.get(value.get("id"))
                if supplied is not None:
                    expression = supplied
            if expression is None:
                expression = fallback
            if expression is None:
                raise ModelValidationError(f"missing expression for {value.get('id')}")
            value["expression"] = normalize_expression(expression)
        try:
            merged.append(TypeAdapter(SDVariable).validate_python(value))
        except ValidationError as exc:
            raise ModelValidationError(f"invalid variable {value.get('id')}: {exc}") from exc
    return _normalize_generated_variables(merged, time_unit)


def _normalize_generated_variables(
    variables: list[SDVariable], time_unit: str = "year"
) -> list[SDVariable]:
    by_id = {item.id: item for item in variables}
    connected_stocks = {
        endpoint.id
        for item in variables
        if item.kind == "flow"
        for endpoint in (item.source, item.target)
        if endpoint is not None and endpoint.kind == "stock"
    }
    dynamic_calls = {
        "step",
        "pulse",
        "pulse_train",
        "ramp",
        "delay1",
        "delay3",
        "delay1i",
        "delay3i",
        "smooth",
        "smooth3",
        "smoothi",
        "smooth3i",
        "initial",
    }
    normalized = []
    for item in variables:
        if item.kind == "stock" and item.id not in connected_stocks and item.derivative is not None:
            flow_id = f"{item.id}_net_rate"
            suffix = 2
            while flow_id in by_id:
                flow_id = f"{item.id}_net_rate_{suffix}"
                suffix += 1
            source_id = f"{flow_id}_source"
            while source_id in by_id:
                source_id = f"{source_id}_external"
            flow = FlowVariable(
                id=flow_id,
                kind="flow",
                expression=item.derivative,
                source=FlowEndpoint(kind="cloud", id=source_id),
                target=FlowEndpoint(kind="stock", id=item.id),
                units=combine(item.units, {time_unit: -1}) if item.units is not None else None,
                topology_status="inferred",
            )
            item = item.model_copy(update={"derivative": ref(flow_id)})
            by_id[flow_id] = flow
            normalized.append(flow)
            connected_stocks.add(item.id)
        if item.kind == "constant":
            dynamic = any(
                node.op == "time" or (node.op == "call" and node.name in dynamic_calls)
                for node in walk(item.expression)
            ) or any(
                name in by_id and by_id[name].kind != "constant"
                for name in dependencies(item.expression)
            )
            if dynamic:
                payload = item.model_dump(mode="json")
                payload["kind"] = "auxiliary"
                payload.pop("exogenous", None)
                item = TypeAdapter(SDVariable).validate_python(payload)
        normalized.append(item)
    return normalized


def _validated(document: ModelDocument) -> tuple[ModelDocument, list]:
    document = with_semantic_validation(finalize_model(document))
    errors = [item for item in document.validation.issues if item.severity == "error"]
    return document, errors


def _repair(
    document: ModelDocument,
    response: Any,
    attempt: int,
    *,
    preserve_topology: bool = True,
    preserve_kinds: bool = True,
) -> ModelDocument:
    if not isinstance(response, dict) or not isinstance(response.get("variables"), list):
        raise ModelValidationError("repair must return a complete variables list")
    previous = {item.id: item for item in document.variables}
    candidate_response = dict(response)
    candidates = []
    for item in response["variables"]:
        if not isinstance(item, dict):
            candidates.append(item)
            continue
        value = dict(item)
        existing = previous.get(value.get("id"))
        if existing is not None:
            if preserve_kinds:
                value["kind"] = existing.kind
            if existing.kind == "stock" and value.get("initial") is None:
                value["initial"] = existing.initial.model_dump(mode="json")
            if preserve_topology and existing.kind == "flow":
                value["source"] = (
                    existing.source.model_dump(mode="json") if existing.source else None
                )
                value["target"] = (
                    existing.target.model_dump(mode="json") if existing.target else None
                )
        candidates.append(value)
    present = {item.get("id") for item in candidates if isinstance(item, dict)}
    candidates.extend(
        item.model_dump(mode="json")
        for item in document.variables
        if item.id not in present
    )
    candidate_response["variables"] = candidates
    try:
        metadata, raw = _variable_response(candidate_response, default_time=document.time)
        for item in raw:
            if item.get("kind") == "stock" or item.get("expression") is not None:
                continue
            existing = previous.get(item.get("id"))
            if existing is not None and existing.kind != "stock":
                item["expression"] = existing.expression.model_dump(mode="json")
        time_settings = metadata.get("time") or document.time
        time_unit = (
            time_settings.unit
            if isinstance(time_settings, TimeSettings)
            else time_settings["unit"]
        )
        variables = _merge(
            raw,
            _expressions({"variables": raw}),
            time_unit=time_unit,
        )
        return ModelDocument(
            id=document.id,
            name=response.get("name") or document.name,
            description=document.description,
            time=metadata.get("time") or document.time,
            variables=variables,
            tables=metadata.get("tables", []),
            assumptions=metadata.get("assumptions", []),
            provenance=document.provenance,
            brief=document.brief,
            pattern_id=document.pattern_id,
            repair_attempts=attempt,
            created_at=document.created_at,
        )
    except ValidationError as exc:
        raise ModelValidationError(f"invalid repair response: {exc}") from exc


def _repair_payload(document: ModelDocument) -> dict:
    return {
        "name": document.name,
        "time": document.time.model_dump(mode="json"),
        "variables": [item.model_dump(mode="json") for item in document.variables],
        "tables": [item.model_dump(mode="json") for item in document.tables],
        "assumptions": [item.model_dump(mode="json") for item in document.assumptions],
    }


def _repair_context(document: ModelDocument) -> dict:
    fields = {
        "id",
        "kind",
        "units",
        "initial",
        "expression",
        "derivative",
        "source",
        "target",
        "bounds",
        "subscripts",
        "exogenous",
        "allow_isolated",
        "topology_status",
    }
    variables = []
    for item in document.variables:
        payload = item.model_dump(mode="json")
        variables.append(
            {
                key: value
                for key, value in payload.items()
                if key in fields and value is not None and value != [] and value is not False
            }
        )
    return {
        "name": document.name,
        "time": document.time.model_dump(mode="json"),
        "variables": variables,
        "tables": [item.model_dump(mode="json") for item in document.tables],
        "assumptions": [item.model_dump(mode="json") for item in document.assumptions],
    }


def _pattern_repair_context(pattern) -> str:
    return pattern_prompt(pattern)


def _smoke(document: ModelDocument) -> dict[str, Any]:
    try:
        smoke = simulate_model(
            document,
            SimulationParameters(
                initial_time=document.time.initial_time,
                final_time=document.time.final_time,
                time_step=document.time.time_step,
                saveper=document.time.saveper,
                integration_method="euler",
            ),
        )
        if not all(
            math.isfinite(value) for series in smoke.variables.values() for value in series
        ):
            raise ModelValidationError("smoke simulation returned non-finite values")
        if document.pattern_id == "supply_delay":
            stock_ids = {item.id for item in document.variables if item.kind == "stock"}
            if not any(
                len(series) > 1 and max(series) - min(series) > 1e-9
                for name, series in smoke.variables.items()
                if name in stock_ids
            ):
                raise ModelValidationError(
                    "supply-delay model is static; add demand/order variation or an inventory adjustment policy"
                )
    except Exception as exc:
        raise ModelValidationError(
            f"generated model smoke simulation failed: {type(exc).__name__}: {exc}"
        ) from exc
    return {"points": len(smoke.time), "engine": smoke.engine, "method": smoke.integration_method}


async def generate_model(
    request: GenerationRequest,
    llm: LLMClient,
    *,
    workdir: Path | None = None,
    max_repairs: int | None = None,
) -> ModelDocument:
    repairs = max_repairs if max_repairs is not None else int(os.environ.get("LLM_MAX_REPAIRS", "3"))
    budget = _RepairBudget(max(0, min(repairs, 3)))
    description = _description(request)
    pattern = select_pattern(description)
    pattern_text = pattern_prompt(pattern)

    component_result: tuple[list[SDVariable], TimeSettings, list[Assumption]] | None = None

    def parse_brief(response: Any) -> ModelBrief:
        candidate = ModelBrief.model_validate(response)
        _validate_brief_scope(candidate, pattern, description)
        return candidate

    brief_schema = ModelBrief.model_json_schema()
    for field in ("components", "time", "assumptions"):
        brief_schema["properties"].pop(field)
    brief_schema.pop("$defs", None)
    _save_stage(workdir, "brief")
    brief = await _call_stage(
        llm,
        stage="brief",
        prompt=MODEL_BRIEF_PROMPT.format(description=description, pattern=pattern_text),
        system="You are a system dynamics expert. Return only JSON.",
        temperature=0.1,
        response_schema=brief_schema,
        parser=parse_brief,
        budget=budget,
        workdir=workdir,
    )
    rag_sources = []
    if pattern is None and request.base_model is None:
        rag_context, rag_sources = component_rag_context(description)
        if rag_sources:
            _save_stage(workdir, "rag", {"sources": rag_sources, "context_chars": len(rag_context)})

        def parse_components(response: Any) -> tuple[ComponentPlan, Any]:
            plan = ComponentPlan.model_validate(normalize_component_payload(response))
            plan = apply_explicit_odes(plan, description)
            if plan.time is not None:
                plan = plan.model_copy(
                    update={"time": normalize_inferred_time(plan.time, description)}
                )
            if plan.components and plan.time is None:
                raise ModelValidationError("component plan requires time settings")
            built = (
                build_components(plan.components, plan.time, plan.assumptions)
                if plan.components
                else None
            )
            if built is not None:
                validate_explicit_odes(description, built[0])
            return plan, built

        plan, component_result = await _call_stage(
            llm,
            stage="components",
            prompt=COMPONENT_PLAN_PROMPT.format(
                description=description,
                brief=brief.model_dump_json(indent=2),
                component_guidance=COMPONENT_BRIEF_GUIDANCE + rag_context,
            ),
            system="You specify typed dynamic mechanisms. Return only JSON.",
            temperature=0.1,
            response_schema=None,
            parser=parse_components,
            budget=budget,
            workdir=workdir,
        )
        brief = brief.model_copy(
            update={
                "components": plan.components,
                "time": plan.time,
                "assumptions": plan.assumptions,
            }
        )
        _save_stage(workdir, "components", plan.model_dump(mode="json"))
    brief_text = brief.model_dump_json(indent=2)
    _save_stage(workdir, "brief", brief.model_dump(mode="json"))

    if component_result is not None:
        variables, component_time, component_assumptions = component_result
        metadata = {
            "name": brief.goal[:300],
            "time": component_time.model_dump(mode="json"),
            "assumptions": [item.model_dump(mode="json") for item in component_assumptions],
        }
        _save_stage(
            workdir,
            "variables",
            [item.model_dump(mode="json") for item in variables],
        )
        _save_stage(
            workdir,
            "equations",
            {
                "builder": "typed_components",
                "expressions": [
                    {"id": item.id, "expression": item.expression.model_dump(mode="json")}
                    for item in variables
                    if item.kind != "stock"
                ],
            },
        )
    else:
        _save_stage(workdir, "variables")

        def parse_variables(response: Any) -> tuple[dict, list[dict]]:
            result = _variable_response(
                response,
                default_time=pattern.document.time
                if pattern
                else request.base_model.time
                if request.base_model
                else None,
            )
            _validate_variable_scope(
                result[1], pattern, description, (result[0].get("time") or {}).get("unit")
            )
            return result

        metadata, raw = await _call_stage(
            llm,
            stage="variables",
            prompt=VARIABLE_EXTRACTION_PROMPT.format(
                description=description,
                brief=brief_text,
                pattern=pattern_text,
                ode_guidance=_ode_guidance(pattern),
            ),
            system="You design valid system dynamics structures. Return only JSON.",
            temperature=0.2,
            response_schema=_VARIABLES_RESPONSE_SCHEMA,
            parser=parse_variables,
            budget=budget,
            workdir=workdir,
        )
        _save_stage(workdir, "variables", raw)

        _save_stage(workdir, "equations")

        def parse_equations(response: Any) -> tuple[dict[str, Any], list[SDVariable]]:
            expressions = _expressions(response)
            return expressions, _merge(
                raw, expressions, time_unit=(metadata.get("time") or {}).get("unit", "year")
            )

        if request.base_model is None and _requires_normalized_pattern(pattern, description):
            expressions = {
                item.id: item.expression.model_dump(mode="json")
                for item in pattern.document.variables
                if item.kind != "stock"
            }
            variables = _merge(
                raw, expressions, time_unit=(metadata.get("time") or {}).get("unit", "year")
            )
            metadata["assumptions"] = [
                *metadata.get("assumptions", []),
                Assumption(
                    path="equations",
                    value=pattern.id,
                    source="archetype",
                    rationale=(
                        "Normalized equations are taken from the validated pattern; "
                        "stock initial values and constants are preserved."
                    ),
                    requires_confirmation=False,
                ).model_dump(mode="json"),
            ]
        else:
            expressions, variables = await _call_stage(
                llm,
                stage="equations",
                prompt=EQUATION_GENERATION_PROMPT.format(
                    description=description,
                    brief=brief_text,
                    pattern=pattern_text,
                    variables=json.dumps(raw, ensure_ascii=False, indent=2),
                ),
                system="You generate typed system dynamics expressions. Return only JSON.",
                temperature=0.2,
                response_schema=_EQUATIONS_RESPONSE_SCHEMA,
                parser=parse_equations,
                budget=budget,
                workdir=workdir,
            )
        _save_stage(workdir, "equations", expressions)

    if request.assumption_policy == "require_explicit" and any(
        item.get("requires_confirmation") for item in metadata.get("assumptions", [])
    ):
        raise ModelValidationError("MISSING_PARAMETER: explicit parameter values are required")
    base = request.base_model
    try:
        document = ModelDocument(
            id=base.id if base else "model",
            name=metadata.get("name") or (base.name if base else "System dynamics model"),
            description=base.description if base else request.description,
            time=metadata.get("time") or (base.time if base else {"unit": brief.time_unit}),
            variables=variables,
            tables=TypeAdapter(list[LookupTable]).validate_python(
                metadata.get("tables", [item.model_dump(mode="json") for item in base.tables])
                if base
                else metadata.get("tables", [])
            ),
            assumptions=TypeAdapter(list[Assumption]).validate_python(
                metadata.get(
                    "assumptions",
                    [item.model_dump(mode="json") for item in base.assumptions] if base else [],
                )
            ),
            provenance=base.provenance if base else {"kind": "text_generation"},
            brief=brief,
            pattern_id=(pattern.id if pattern else base.pattern_id)
            if base
            else (pattern.id if pattern else None),
        )
    except ValidationError as exc:
        raise ModelValidationError(f"invalid generated model metadata: {exc}") from exc

    _save_stage(workdir, "validation")
    document, errors = _validated(document)
    last_repair_error: Exception | None = None
    while True:
        if not errors:
            _save_stage(workdir, "smoke")
            try:
                smoke = _smoke(document)
            except ModelValidationError as exc:
                errors = [
                    ValidationIssue(
                        code="SMOKE_SIMULATION",
                        severity="error",
                        path="simulation",
                        message=str(exc)[:2000],
                    )
                ]
                _save_stage(workdir, "smoke", {"error": str(exc)})
            else:
                _save_stage(workdir, "smoke", smoke)
        if not errors or not budget.take():
            break
        attempt = budget.attempts
        prompt_errors = list(errors)
        if last_repair_error is not None:
            prompt_errors.append(
                ValidationIssue(
                    code="INVALID_REPAIR_RESPONSE",
                    severity="error",
                    path=f"repair_{attempt - 1}",
                    message=str(last_repair_error)[:2000],
                )
            )
        _save_stage(
            workdir,
            f"repair_{attempt}",
            [item.model_dump(mode="json") for item in prompt_errors],
        )
        try:
            response = await llm.chat_json(
                REPAIR_PROMPT.format(
                    brief=brief_text,
                    pattern=_pattern_repair_context(pattern),
                    errors=json.dumps(
                        [item.model_dump(mode="json") for item in prompt_errors],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    document=json.dumps(_repair_context(document), ensure_ascii=False, indent=2),
                ),
                stage=f"repair_{attempt}",
                system="You repair system dynamics models using validator errors. Return only JSON.",
                temperature=0.1,
                response_schema=_VARIABLES_RESPONSE_SCHEMA,
            )
            _save_stage(workdir, f"repair_{attempt}_response", response)
            candidate = _repair(
                document,
                response,
                attempt,
                preserve_topology=not any(
                    token in issue.code
                    for issue in prompt_errors
                    for token in ("TOPOLOGY", "FLOW", "DERIVATIVE", "SEMANTIC")
                ),
                preserve_kinds=not any(
                    token in issue.code
                    for issue in prompt_errors
                    for token in ("TOPOLOGY", "FLOW", "DERIVATIVE", "SEMANTIC")
                ),
            )
            document, errors = _validated(candidate)
        except (LLMResponseError, ModelValidationError, ValidationError) as exc:
            last_repair_error = exc
            _save_stage(workdir, f"repair_{attempt}_error", {"error": str(exc)})
            continue
        last_repair_error = None
    if errors:
        detail = "; ".join(
            f"{item.code} at {item.path}: {item.message}" for item in errors[:10]
        )
        if last_repair_error is not None:
            detail = f"{detail}; last repair response failed: {last_repair_error}"
        raise ModelValidationError(detail, repair_attempts=budget.attempts)
    document = document.model_copy(update={"repair_attempts": budget.attempts})
    _save_stage(workdir, "validation", document.validation.model_dump(mode="json"))
    _save_stage(
        workdir,
        "graphs",
        {
            "cld": document.cld_data.model_dump(mode="json"),
            "sfd": document.sfd_data.model_dump(mode="json"),
        },
    )

    _save_stage(workdir, "exports")
    try:
        generate_python_code(document)
        export_vensim(document)
        if document.validation.capabilities.supported.get("xmile_export", False):
            export_xmile(document)
    except Exception as exc:
        raise ModelValidationError(
            f"generated model export failed: {type(exc).__name__}: {exc}"
        ) from exc
    warnings = [item.message for item in document.validation.issues if item.severity == "warning"]
    warnings.extend(
        issue
        for graph in (document.cld_data, document.sfd_data)
        for issue in graph.validation.issues
        if issue.startswith("warning:")
    )
    formats = ["python", "vensim"]
    if document.validation.capabilities.supported.get("xmile_export", False):
        formats.append("xmile")
    log = [
        f"pattern: {document.pattern_id or 'none'}",
        f"repairs: {document.repair_attempts}",
        f"variables: {len(document.variables)}",
        f"validation: {document.validation.status}",
        f"cld: {len(document.cld_data.edges)} edges",
        f"sfd: {len(document.sfd_data.edges)} edges",
        f"exports: {', '.join(formats)}",
    ]
    if rag_sources:
        log.append(f"rag: {', '.join(rag_sources)}")
    document = document.model_copy(
        update={
            "artifacts": {
                format_name: f"model.{extension}"
                for format_name, extension in (
                    ("python", "py"),
                    ("vensim", "mdl"),
                    ("xmile", "xmile"),
                )
                if format_name in formats
            },
            "assistant_text": (
                f"Модель построена: {len(document.variables)} переменных, "
                f"{len(document.cld_data.validation.feedback_loops)} петель обратной связи."
            ),
            "warnings": warnings,
            "generation_log": log,
        }
    )
    _save_stage(workdir, "done", document.model_dump(mode="json"))
    return document
