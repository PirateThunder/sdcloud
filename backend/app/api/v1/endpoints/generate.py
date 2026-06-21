"""Message generation endpoint — triggers AI model generation."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import LLMError, NotFoundError, ValidationError
from app.models.conversation import Conversation
from app.models.generated_model import GeneratedModel
from app.models.message import Message
from app.models.user import User
from app.schemas.message import MessageCreate, MessageResponse
from app.services.llm.openrouter import OpenRouterLLM
from app.utils.sd_prompts import MODEL_CONTEXT_PROMPT
from app.workers.tasks import generate_model_task

router = APIRouter(prefix="/conversations", tags=["Generation"])


@router.post(
    "/{conversation_id}/messages",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a message and trigger AI model generation",
)
async def send_message(
    conversation_id: UUID,
    data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Send a user message and initiate the AI model generation pipeline.

    The pipeline:
    1. Saves the user message
    2. Creates an assistant message placeholder
    3. Generates initial LLM response
    4. Triggers background model generation
    5. Returns the assistant response immediately
    """
    # Verify conversation ownership
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise NotFoundError(detail="Conversation not found")

    if not data.content or not data.content.strip():
        raise ValidationError(detail="Message content cannot be empty")

    # Save user message
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=data.content.strip(),
    )
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)

    # Create assistant message placeholder
    assistant_message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content="Generating model... This may take a few moments.",
        model_metadata={"status": "generating"},
    )
    db.add(assistant_message)
    await db.commit()
    await db.refresh(assistant_message)

    # Generate initial response via LLM
    try:
        llm = OpenRouterLLM()

        # Get conversation history for context
        history_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .where(Message.role.in_(["user", "assistant"]))
            .order_by(Message.created_at.asc())
        )
        history = history_result.scalars().all()

        # Build context prompt
        context_parts = []
        for msg in history[-6:]:  # Last 6 messages for context
            if msg.role == "user":
                context_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                content_preview = msg.content[:200] if msg.content else "..."
                context_parts.append(f"Assistant: {content_preview}")

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

        ai_response = await llm.chat(
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.7,
        )

        # Update assistant message with the response
        assistant_message.content = (
            ai_response.text
            or "I'm analyzing your system description and generating a model. "
               "The components (variables, causal loop diagram, equations, and stock-flow diagram) "
               "will be ready shortly. You can view the generated model in the Models section."
        )
        assistant_message.tokens_used = ai_response.cost

        await db.commit()
        await llm.close()

    except LLMError as exc:
        assistant_message.content = (
            f"I'm working on generating your model based on: '{data.content[:100]}...'. "
            f"The model components will be generated and you'll be able to view and simulate them."
        )
        await db.commit()

    # Trigger background model generation
    try:
        # Fire and forget the background task
        asyncio.create_task(
            generate_model_task(
                conversation_id=str(conversation_id),
                message_id=str(assistant_message.id),
                user_description=data.content.strip(),
            )
        )
    except Exception as exc:
        assistant_message.model_metadata = {
            "status": "error",
            "error": f"Failed to start generation: {str(exc)}",
        }
        await db.commit()

    return {
        "user_message": {
            "id": str(user_message.id),
            "role": user_message.role,
            "content": user_message.content,
            "created_at": user_message.created_at.isoformat(),
        },
        "assistant_message": {
            "id": str(assistant_message.id),
            "role": assistant_message.role,
            "content": assistant_message.content,
            "model_metadata": assistant_message.model_metadata,
            "tokens_used": assistant_message.tokens_used,
            "created_at": assistant_message.created_at.isoformat(),
        },
        "generation_status": "started",
    }
