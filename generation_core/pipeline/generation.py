from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .codegen import export_vensim, generate_python_code
from .exceptions import ModelValidationError
from .formats import export_xmile
from .io import write_json_atomic, write_stage
from .llm import LLMClient
from .pattern_library import pattern_prompt, select_pattern
from .prompts import (
    EQUATION_GENERATION_PROMPT,
    MODEL_BRIEF_PROMPT,
    REPAIR_PROMPT,
    VARIABLE_EXTRACTION_PROMPT,
)
from .schemas import (
    Assumption,
    GenerationRequest,
    LookupTable,
    ModelBrief,
    ModelDocument,
    SDVariable,
)
from .semantics import with_semantic_validation
from .validation import finalize_model


def _save_stage(workdir: Path | None, stage: str, value: Any = None) -> None:
    if workdir is None:
        return
    write_stage(workdir, stage)
    if value is not None:
        write_json_atomic(workdir / f"{stage}.json", value)


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
        if value.get("kind") != "stock":
            expression = expressions.get(value.get("id"), value.pop("initial", None))
            if expression is None:
                raise ModelValidationError(f"missing expression for {value.get('id')}")
            value["expression"] = expression
        try:
            merged.append(TypeAdapter(SDVariable).validate_python(value))
        except ValidationError as exc:
            raise ModelValidationError(f"invalid variable {value.get('id')}: {exc}") from exc
    return merged


def _validated(document: ModelDocument) -> tuple[ModelDocument, list]:
    document = with_semantic_validation(finalize_model(document))
    errors = [item for item in document.validation.issues if item.severity == "error"]
    return document, errors


def _repair(document: ModelDocument, response: Any, attempt: int) -> ModelDocument:
    if not isinstance(response, dict) or not isinstance(response.get("variables"), list):
        raise ModelValidationError("repair must return a complete variables list")
    try:
        raw_variables = []
        for item in response["variables"]:
            value = dict(item)
            if value.get("kind") != "stock":
                initial = value.pop("initial", None)
                if "expression" not in value and initial is not None:
                    value["expression"] = initial
            raw_variables.append(value)
        variables = TypeAdapter(list[SDVariable]).validate_python(raw_variables)
        tables = TypeAdapter(list[LookupTable]).validate_python(response.get("tables", []))
        assumptions = TypeAdapter(list[Assumption]).validate_python(response.get("assumptions", []))
        return ModelDocument(
            id=document.id,
            name=response.get("name") or document.name,
            description=document.description,
            time=response.get("time") or document.time,
            variables=variables,
            tables=tables,
            assumptions=assumptions,
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


async def generate_model(
    request: GenerationRequest,
    llm: LLMClient,
    *,
    workdir: Path | None = None,
    max_repairs: int | None = None,
) -> ModelDocument:
    description = _description(request)
    pattern = select_pattern(description)
    pattern_text = pattern_prompt(pattern)
    _save_stage(workdir, "brief")
    response = await llm.chat_json(
        MODEL_BRIEF_PROMPT.format(description=description, pattern=pattern_text),
        stage="brief",
        system="You are a system dynamics expert. Return only JSON.",
        temperature=0.1,
        response_schema=ModelBrief.model_json_schema(),
    )
    try:
        brief = ModelBrief.model_validate(response)
    except ValidationError as exc:
        raise ModelValidationError(f"invalid ModelBrief: {exc}") from exc
    brief_text = brief.model_dump_json(indent=2)
    _save_stage(workdir, "brief", brief.model_dump(mode="json"))

    _save_stage(workdir, "variables")
    response = await llm.chat_json(
        VARIABLE_EXTRACTION_PROMPT.format(
            description=description,
            brief=brief_text,
            pattern=pattern_text,
        ),
        stage="variables",
        system="You design valid system dynamics structures. Return only JSON.",
        temperature=0.2,
    )
    metadata, raw = _variables(response)
    _save_stage(workdir, "variables", raw)

    _save_stage(workdir, "equations")
    response = await llm.chat_json(
        EQUATION_GENERATION_PROMPT.format(
            description=description,
            brief=brief_text,
            variables=json.dumps(raw, ensure_ascii=False, indent=2),
        ),
        stage="equations",
        system="You generate typed system dynamics expressions. Return only JSON.",
        temperature=0.2,
    )
    expressions = _expressions(response)
    variables = _merge(raw, expressions)
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
    repairs = (
        max_repairs if max_repairs is not None else int(os.environ.get("LLM_MAX_REPAIRS", "3"))
    )
    repairs = max(0, min(repairs, 3))
    attempt = 0
    while errors and attempt < repairs:
        attempt += 1
        _save_stage(workdir, f"repair_{attempt}", [item.model_dump(mode="json") for item in errors])
        response = await llm.chat_json(
            REPAIR_PROMPT.format(
                brief=brief_text,
                pattern=pattern_text,
                errors=json.dumps(
                    [item.model_dump(mode="json") for item in errors], ensure_ascii=False, indent=2
                ),
                document=json.dumps(_repair_payload(document), ensure_ascii=False, indent=2),
            ),
            stage=f"repair_{attempt}",
            system="You repair system dynamics models using validator errors. Return only JSON.",
            temperature=0.1,
        )
        document = _repair(document, response, attempt)
        document, errors = _validated(document)
    if errors:
        raise ModelValidationError(
            "; ".join(f"{item.code} at {item.path}: {item.message}" for item in errors[:10])
        )
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
