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
from .exceptions import LLMResponseError, ModelValidationError
from .expression_parser import normalize_expression
from .formats import export_xmile
from .io import write_json_atomic, write_stage
from .ir import dependencies, walk
from .llm import LLMClient
from .pattern_library import pattern_prompt, select_pattern
from .prompts import (
    EQUATION_GENERATION_PROMPT,
    MODEL_BRIEF_PROMPT,
    REPAIR_PROMPT,
    STAGE_REPAIR_PROMPT,
    VARIABLE_EXTRACTION_PROMPT,
)
from .schemas import (
    Assumption,
    Expression,
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
    if kind == "stock":
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
    response_schema: dict,
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
            current_prompt = STAGE_REPAIR_PROMPT.format(
                stage=stage,
                error=str(exc)[:6000],
                original_prompt=_json_excerpt(prompt, 30_000),
                response=_json_excerpt(previous_response),
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


def _variables(response: Any) -> tuple[dict, list[dict]]:
    if not isinstance(response, dict) or not isinstance(response.get("variables"), list):
        raise ModelValidationError("variable extraction must return an object with variables")
    raw = response["variables"]
    if not raw or len(raw) > 200:
        raise ModelValidationError("model must contain between 1 and 200 variables")
    if not all(isinstance(item, dict) for item in raw):
        raise ModelValidationError("every variable must be an object")
    return response, raw


def _normalize_assumptions(values: Any) -> Any:
    if not isinstance(values, list):
        return values
    result = []
    for item in values:
        if not isinstance(item, dict):
            result.append(item)
            continue
        value = dict(item)
        if isinstance(value.get("value"), bool | int | float):
            value["value"] = str(value["value"])
        result.append(value)
    return result


def _variable_response(response: Any) -> tuple[dict, list[dict]]:
    metadata, raw = _variables(response)
    metadata = dict(metadata)
    normalized = []
    for item in raw:
        value = dict(item)
        if isinstance(value.get("units"), dict):
            value["units"] = {
                name: power
                for name, power in value["units"].items()
                if name not in {"1", "dimensionless"}
            }
        kind = value.get("kind")
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
            metadata["time"] = TimeSettings.model_validate(metadata["time"]).model_dump(mode="json")
        if "tables" in metadata:
            metadata["tables"] = [
                item.model_dump(mode="json")
                for item in TypeAdapter(list[LookupTable]).validate_python(metadata["tables"])
            ]
        if "assumptions" in metadata:
            metadata["assumptions"] = [
                item.model_dump(mode="json")
                for item in TypeAdapter(list[Assumption]).validate_python(
                    _normalize_assumptions(metadata["assumptions"])
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
    if not isinstance(raw, dict) or not raw:
        raise ModelValidationError("equation generation returned no expressions")
    return raw


def _merge(raw: list[dict], expressions: dict[str, Any]) -> list[SDVariable]:
    ids = {item.get("id") for item in raw}
    unknown = set(expressions) - ids
    if unknown:
        raise ModelValidationError(f"expressions reference unknown variables: {sorted(unknown)}")
    merged = []
    for item in raw:
        value = dict(item)
        if value.get("kind") == "stock":
            value["initial"] = normalize_expression(value["initial"])
            if value.get("derivative") is not None:
                value["derivative"] = normalize_expression(value["derivative"])
        else:
            expression = expressions.get(value.get("id"), value.pop("initial", None))
            if expression is None:
                raise ModelValidationError(f"missing expression for {value.get('id')}")
            value["expression"] = normalize_expression(expression)
        try:
            merged.append(TypeAdapter(SDVariable).validate_python(value))
        except ValidationError as exc:
            raise ModelValidationError(f"invalid variable {value.get('id')}: {exc}") from exc
    return _normalize_generated_variables(merged)


def _normalize_generated_variables(variables: list[SDVariable]) -> list[SDVariable]:
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
        "smooth",
        "smooth3",
        "initial",
    }
    normalized = []
    for item in variables:
        if item.kind == "stock" and item.id in connected_stocks and item.derivative is not None:
            item = item.model_copy(update={"derivative": None})
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


def _repair(document: ModelDocument, response: Any, attempt: int) -> ModelDocument:
    if not isinstance(response, dict) or not isinstance(response.get("variables"), list):
        raise ModelValidationError("repair must return a complete variables list")
    try:
        metadata, raw = _variable_response(response)
        previous = {item.id: item for item in document.variables}
        for item in raw:
            if item.get("kind") == "stock" or item.get("expression") is not None:
                continue
            existing = previous.get(item.get("id"))
            if existing is not None and existing.kind != "stock":
                item["expression"] = existing.expression.model_dump(mode="json")
        variables = _merge(raw, _expressions({"variables": raw}))
        return ModelDocument(
            id=document.id,
            name=response.get("name") or document.name,
            description=document.description,
            time=response.get("time") or document.time,
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
    _save_stage(workdir, "brief")
    brief = await _call_stage(
        llm,
        stage="brief",
        prompt=MODEL_BRIEF_PROMPT.format(description=description, pattern=pattern_text),
        system="You are a system dynamics expert. Return only JSON.",
        temperature=0.1,
        response_schema=ModelBrief.model_json_schema(),
        parser=ModelBrief.model_validate,
        budget=budget,
        workdir=workdir,
    )
    brief_text = brief.model_dump_json(indent=2)
    _save_stage(workdir, "brief", brief.model_dump(mode="json"))

    _save_stage(workdir, "variables")
    metadata, raw = await _call_stage(
        llm,
        stage="variables",
        prompt=VARIABLE_EXTRACTION_PROMPT.format(
            description=description,
            brief=brief_text,
            pattern=pattern_text,
        ),
        system="You design valid system dynamics structures. Return only JSON.",
        temperature=0.2,
        response_schema=_VARIABLES_RESPONSE_SCHEMA,
        parser=_variable_response,
        budget=budget,
        workdir=workdir,
    )
    _save_stage(workdir, "variables", raw)

    _save_stage(workdir, "equations")

    def parse_equations(response: Any) -> tuple[dict[str, Any], list[SDVariable]]:
        expressions = _expressions(response)
        return expressions, _merge(raw, expressions)

    expressions, variables = await _call_stage(
        llm,
        stage="equations",
        prompt=EQUATION_GENERATION_PROMPT.format(
            description=description,
            brief=brief_text,
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
                    pattern=pattern_text,
                    errors=json.dumps(
                        [item.model_dump(mode="json") for item in prompt_errors],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    document=json.dumps(_repair_payload(document), ensure_ascii=False, indent=2),
                ),
                stage=f"repair_{attempt}",
                system="You repair system dynamics models using validator errors. Return only JSON.",
                temperature=0.1,
                response_schema=_VARIABLES_RESPONSE_SCHEMA,
            )
            _save_stage(workdir, f"repair_{attempt}_response", response)
            candidate = _repair(document, response, attempt)
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
