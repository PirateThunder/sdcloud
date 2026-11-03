from __future__ import annotations

from .ir import dependencies
from .schemas import ModelDocument, ValidationIssue


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, severity="error", path=path, message=message)


def semantic_issues(document: ModelDocument) -> list[ValidationIssue]:
    document = ModelDocument.model_validate(document.model_dump())
    issues = []
    flows = [item for item in document.variables if item.kind == "flow"]
    stocks = [item for item in document.variables if item.kind == "stock"]
    for flow in flows:
        name = flow.id.lower()
        if any(token in name for token in ("death", "mortality", "смерт")) and (
            flow.source is None or flow.source.kind != "stock"
        ):
            issues.append(
                _issue(
                    "INVALID_DEATH_FLOW",
                    f"variables.{flow.id}.source",
                    "death/mortality flow must remove entities from a stock, not create them from a cloud",
                )
            )
        if any(token in name for token in ("birth", "natality", "рожд")) and (
            flow.target is None or flow.target.kind != "stock"
        ):
            issues.append(
                _issue(
                    "INVALID_BIRTH_FLOW",
                    f"variables.{flow.id}.target",
                    "birth flow must add entities to a stock",
                )
            )
    if document.pattern_id == "predator_prey" and len(stocks) >= 2:
        stock_ids = {item.id for item in stocks}
        candidates = [flow for flow in flows if len(dependencies(flow.expression) & stock_ids) >= 2]
        predation = next(
            (flow for flow in candidates if flow.source and flow.source.kind == "stock"),
            None,
        )
        if predation is None:
            issues.append(
                _issue(
                    "SEMANTIC_PREDATION_MISSING",
                    "variables",
                    "predator-prey model needs an outflow from prey controlled by both populations",
                )
            )
        else:
            prey_id = predation.source.id
            reproduction = next(
                (
                    flow
                    for flow in flows
                    if flow.target
                    and flow.target.kind == "stock"
                    and flow.target.id != prey_id
                    and (
                        len(dependencies(flow.expression) & stock_ids) >= 2
                        or predation.id in dependencies(flow.expression)
                    )
                ),
                None,
            )
            if reproduction is None:
                issues.append(
                    _issue(
                        "SEMANTIC_PREDATOR_GROWTH_MISSING",
                        "variables",
                        "predator-prey model needs predator growth driven by prey or predation",
                    )
                )
    return issues


def with_semantic_validation(document: ModelDocument) -> ModelDocument:
    semantic = semantic_issues(document)
    if not semantic:
        return document
    issues = [*document.validation.issues, *semantic]
    return document.model_copy(
        update={
            "validation": document.validation.model_copy(
                update={"status": "failed", "issues": issues}
            )
        }
    )
