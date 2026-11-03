from pathlib import Path

from pydantic import ValidationError

from .exceptions import ModelValidationError
from .generation import _save_stage, conversation_history, generate_model, model_context
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
    _save_stage(workdir, "message")
    base_model = model_context(request.base_model) if request.base_model else "null"
    response = await llm.chat_json(
        CONVERSATION_PROMPT.format(
            history=conversation_history(request),
            base_model=base_model,
            description=request.description,
        ),
        stage="message",
        system="You are a helpful system dynamics assistant. Return only JSON.",
        temperature=0.2,
        response_schema=MessageDecision.model_json_schema(),
    )
    try:
        decision = MessageDecision.model_validate(response)
    except ValidationError as exc:
        raise ModelValidationError(f"invalid conversation decision: {exc}") from exc
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
