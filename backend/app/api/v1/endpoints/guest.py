"""Anonymous/guest endpoints for chat and model generation."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, status

from app.core.exceptions import LLMError, SimulationError, ValidationError
from app.schemas.guest import (
    GuestChatRequest,
    GuestChatResponse,
    GuestSimulationRequest,
    GuestSimulationResponse,
)
from app.services.generation import generate_model_from_description
from app.services.llm.openrouter import OpenRouterLLM
from app.services.simulation.pysd_runner import PySDRunner
from app.utils.sd_prompts import MODEL_CONTEXT_PROMPT

router = APIRouter(prefix="/guest", tags=["Guest"])


@router.post(
    "/chat",
    response_model=GuestChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Anonymous chat with synchronous model generation",
)
async def guest_chat(data: GuestChatRequest) -> GuestChatResponse:
    """
    Process a chat message from an unauthenticated user.

    Does NOT persist anything to the database. The full conversation history
    must be provided by the caller on every request.
    """
    content = data.content.strip()
    if not content:
        raise ValidationError(detail="Message content cannot be empty")

    # Build conversation context from provided history + new message
    context_parts = []
    for msg in data.messages[-6:]:
        if msg.role == "user":
            context_parts.append(f"User: {msg.content}")
        elif msg.role == "assistant":
            preview = msg.content[:200] if msg.content else "..."
            context_parts.append(f"Assistant: {preview}")
    context_parts.append(f"User: {content}")
    context_text = "\n".join(context_parts)

    system_prompt = (
        "You are sdCloud, an AI assistant specialized in system dynamics modeling. "
        "You help users create, analyze, and simulate system dynamics models. "
        "Respond in a helpful, professional manner. Acknowledge the user's request "
        "and explain what model components will be generated."
    )

    user_prompt = (
        f"The user wants to build a system dynamics model. "
        f"Recent conversation context:\n{context_text}\n\n"
        f"Provide a brief, helpful response acknowledging their request and "
        f"describing what aspects of the system will be modeled. "
        f"Keep it concise (2-4 sentences)."
    )

    assistant_content = (
        "I'm analyzing your system description and generating a model. "
        "The components (variables, causal loop diagram, equations, and stock-flow diagram) "
        "will be ready shortly."
    )
    tokens_used = None

    try:
        llm = OpenRouterLLM()
        ai_response = await llm.chat(
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.7,
        )
        assistant_content = ai_response.text or assistant_content
        tokens_used = ai_response.cost
        await llm.close()
    except LLMError:
        # Keep fallback content
        pass

    # Generate model synchronously
    generation_result = await generate_model_from_description(content)

    message_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    model_data = None
    if generation_result["status"] == "completed":
        model_id = uuid.uuid4()
        model_data = {
            "id": model_id,
            "name": f"Model for {content[:50]}",
            "variables": generation_result["variables"],
            "equations": generation_result["equations"],
            "cld_data": generation_result["cld_data"],
            "sfd_data": generation_result["sfd_data"],
            "python_code": generation_result["python_code"],
            "vensim_code": generation_result["vensim_code"],
            "status": "completed",
            "generation_log": generation_result["log"],
            "created_at": now,
            "updated_at": now,
        }
        model_metadata = {
            "generation_log": generation_result["log"],
            "model_id": str(model_id),
            "variables_count": len(generation_result["variables"]),
            "equations_count": len(generation_result["equations"]),
            "cld_valid": generation_result["cld_data"]["validation"]["valid"],
            "sfd_valid": generation_result["sfd_data"]["validation"]["valid"],
            "feedback_loops": generation_result["cld_data"]["validation"].get("feedback_loops", []),
        }
    else:
        model_metadata = {
            "status": "error",
            "error": generation_result.get("error", "Model generation failed"),
        }

    assistant_message = {
        "id": message_id,
        "role": "assistant",
        "content": assistant_content,
        "model_metadata": model_metadata,
        "tokens_used": tokens_used,
        "created_at": now,
    }

    return GuestChatResponse(message=assistant_message, model=model_data)


@router.post(
    "/simulate",
    response_model=GuestSimulationResponse,
    status_code=status.HTTP_200_OK,
    summary="Run simulation on a guest-provided model",
)
async def guest_simulate(data: GuestSimulationRequest) -> GuestSimulationResponse:
    """
    Run a PySD simulation on model code provided by an unauthenticated user.

    Does NOT persist anything to the database.
    """
    if not data.python_code and not data.vensim_code:
        raise ValidationError(detail="Either python_code or vensim_code must be provided")

    runner = PySDRunner()

    try:
        if data.python_code:
            results = await runner.simulate_from_python(
                python_code=data.python_code,
                params=data.parameters.custom_params,
                time_start=data.parameters.time_start,
                time_end=data.parameters.time_end,
                time_step=data.parameters.time_step,
            )
        else:
            results = await runner.simulate_from_vensim(
                vensim_code=data.vensim_code,
                params=data.parameters.custom_params,
                time_start=data.parameters.time_start,
                time_end=data.parameters.time_end,
                time_step=data.parameters.time_step,
            )

        runner.cleanup()

        # Ensure 'time' key is present
        time_series = results.get("time", [])
        variables = {k: v for k, v in results.items() if k != "time"}

        return GuestSimulationResponse(
            status="completed",
            results={"time": time_series, "variables": variables},
        )

    except SimulationError as exc:
        runner.cleanup()
        return GuestSimulationResponse(status="error", error=str(exc.detail))
    except Exception as exc:
        runner.cleanup()
        return GuestSimulationResponse(status="error", error=str(exc))
