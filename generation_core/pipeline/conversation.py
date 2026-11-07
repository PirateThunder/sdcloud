import os
from pathlib import Path

from .generation import (
    _call_stage,
    _RepairBudget,
    _save_stage,
    conversation_history,
    generate_model,
    model_context,
)
from .llm import LLMClient
from .prompts import CONVERSATION_PROMPT
from .schemas import (
    ConversationRequest,
    ConversationResponse,
    GenerationRequest,
    MessageDecision,
)


async def respond_to_message(
    request: ConversationRequest,
    llm: LLMClient,
    *,
    workdir: Path | None = None,
    max_repairs: int | None = None,
) -> ConversationResponse:
    from .routing import generate_with_routing

    return await generate_with_routing(
        llm, _respond_to_message_once, request, workdir=workdir, max_repairs=max_repairs
    )


async def _respond_to_message_once(
    request: ConversationRequest,
    llm: LLMClient,
    *,
    workdir: Path | None = None,
    max_repairs: int | None = None,
) -> ConversationResponse:
    repairs = max_repairs if max_repairs is not None else int(os.environ.get("LLM_MAX_REPAIRS", "3"))
    budget = _RepairBudget(max(0, min(repairs, 3)))
    _save_stage(workdir, "message")
    base_model = model_context(request.base_model) if request.base_model else "null"
    decision = await _call_stage(
        llm,
        stage="message",
        prompt=CONVERSATION_PROMPT.format(
            history=conversation_history(request),
            base_model=base_model,
            description=request.description,
        ),
        system="You are a helpful system dynamics assistant. Return only JSON.",
        temperature=0.2,
        response_schema=MessageDecision.model_json_schema(),
        parser=MessageDecision.model_validate,
        budget=budget,
        workdir=workdir,
    )
    _save_stage(workdir, "message", decision.model_dump(mode="json"))

    if decision.action in {"answer", "clarify"}:
        return ConversationResponse(
            kind="clarification" if decision.action == "clarify" else "answer",
            assistant_text=decision.assistant_text,
        )

    action = "generate" if request.base_model is None else decision.action
    document = await generate_model(
        GenerationRequest(
            description=request.description,
            history=request.history,
            base_model=request.base_model if action == "update" else None,
            assumption_policy=request.assumption_policy,
        ),
        llm,
        workdir=workdir,
        max_repairs=max_repairs,
    )
    document = document.model_copy(update={"assistant_text": decision.assistant_text})
    return ConversationResponse(
        kind="model",
        assistant_text=decision.assistant_text,
        model=document,
    )
