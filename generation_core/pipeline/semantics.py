from __future__ import annotations

from .ir import constant_number, dependencies, walk
from .schemas import CallExpression, ModelDocument, TimeExpression, ValidationIssue


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, severity="error", path=path, message=message)


def _sirs_issues(document: ModelDocument) -> list[ValidationIssue]:
    issues = []
    flows = [item for item in document.variables if item.kind == "flow"]
    infection = next(
        (
            flow
            for flow in flows
            if flow.source
            and flow.source.id == "susceptible"
            and flow.target
            and flow.target.id == "infectious"
            and {"susceptible", "infectious"} <= dependencies(flow.expression)
        ),
        None,
    )
    if infection is None:
        issues.append(
            _issue(
                "SEMANTIC_INFECTION_MISSING",
                "variables",
                "SIRS needs infection from susceptible to infectious controlled by both stocks",
            )
        )
    immunity_loss = next(
        (
            flow
            for flow in flows
            if flow.source
            and flow.source.id == "recovered"
            and flow.target
            and flow.target.id == "susceptible"
        ),
        None,
    )
    if immunity_loss is None:
        issues.append(
            _issue(
                "SEMANTIC_IMMUNITY_LOSS_MISSING",
                "variables",
                "SIRS needs an immunity-loss flow from recovered to susceptible",
            )
        )
    seasonal = [
        item
        for item in document.variables
        if item.kind == "auxiliary"
        and any(isinstance(node, TimeExpression) for node in walk(item.expression))
        and any(
            isinstance(node, CallExpression) and node.name in {"sin", "cos"}
            for node in walk(item.expression)
        )
    ]
    if not seasonal or (
        infection is not None
        and not any(item.id in dependencies(infection.expression) for item in seasonal)
    ):
        issues.append(
            _issue(
                "SEMANTIC_SEASONALITY_MISSING",
                "variables",
                "SIRS infection needs a seasonal sin/cos contact-rate auxiliary driven by time",
            )
        )
    variables = {item.id: item for item in document.variables}
    base = variables.get("base_contact_rate")
    duration = variables.get("infectious_duration")
    if base is not None and duration is not None:
        base_value = constant_number(base.expression)
        duration_value = constant_number(duration.expression)
        if (
            base_value is not None
            and duration_value is not None
            and base_value * duration_value < 1
        ):
            issues.append(
                _issue(
                    "SEMANTIC_NO_EPIDEMIC_GROWTH",
                    "variables.base_contact_rate",
                    "base_contact_rate * infectious_duration must be at least 1 for epidemic waves",
                )
            )
    return issues


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
    if document.pattern_id == "sirs_epidemic":
        issues.extend(_sirs_issues(document))
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
