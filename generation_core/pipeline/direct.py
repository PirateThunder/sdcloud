from __future__ import annotations

from pathlib import Path
from typing import Any

from .description_scope import validate_description_scope
from .exceptions import ModelValidationError
from .generation import (
    _VARIABLES_RESPONSE_SCHEMA,
    _call_stage,
    _complete_document,
    _description,
    _merge,
    _RepairBudget,
    _save_stage,
    _smoke,
    _validated,
    _variable_response,
)
from .llm import LLMClient
from .prompts import DIRECT_GENERATION_PROMPT
from .schemas import GenerationRequest, ModelDocument


async def generate_direct_model(
    request: GenerationRequest,
    llm: LLMClient,
    *,
    workdir: Path | None = None,
) -> ModelDocument:
    validate_description_scope(request.description)
    description = _description(request)

    def parse_response(response: Any) -> tuple[dict, list]:
        metadata, raw = _variable_response(
            response,
            default_time=request.base_model.time if request.base_model else None,
        )
        expressions = {
            item["id"]: item["expression"]
            for item in raw
            if item.get("kind") != "stock" and item.get("expression") is not None
        }
        variables = _merge(
            raw,
            expressions,
            time_unit=(metadata.get("time") or {}).get("unit", "year"),
        )
        return metadata, variables

    metadata, variables = await _call_stage(
        llm,
        stage="direct",
        prompt=DIRECT_GENERATION_PROMPT.format(description=description),
        system="You create complete system dynamics models in one response. Return only JSON.",
        temperature=0.2,
        response_schema=_VARIABLES_RESPONSE_SCHEMA,
        parser=parse_response,
        budget=_RepairBudget(0),
        workdir=workdir,
    )
    if request.assumption_policy == "require_explicit" and any(
        item.get("requires_confirmation") for item in metadata.get("assumptions", [])
    ):
        raise ModelValidationError("MISSING_PARAMETER: explicit parameter values are required")
    base = request.base_model
    document = ModelDocument(
        id=base.id if base else "model",
        name=metadata.get("name") or (base.name if base else "System dynamics model"),
        description=base.description if base else request.description,
        time=metadata["time"],
        variables=variables,
        tables=metadata.get("tables", []),
        assumptions=metadata.get("assumptions", []),
        provenance=base.provenance if base else {"kind": "text_generation"},
    )
    _save_stage(workdir, "validation")
    document, errors = _validated(document)
    if errors:
        detail = "; ".join(
            f"{item.code} at {item.path}: {item.message}" for item in errors[:10]
        )
        raise ModelValidationError(detail, repair_attempts=0)
    _smoke(document)
    _save_stage(workdir, "validation", document.validation.model_dump(mode="json"))
    return _complete_document(document, workdir=workdir)
