"""Conversation endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationListItem,
    ConversationUpdate,
)

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get(
    "",
    response_model=list[ConversationListItem],
    summary="List user's conversations",
)
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Conversation]:
    """Return all conversations for the current user."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    conversations = result.scalars().all()

    # Attach message counts
    for conv in conversations:
        count_result = await db.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conv.id)
        )
        conv.message_count = count_result.scalar() or 0

    return list(conversations)


@router.post(
    "",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation",
)
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    """Create a new conversation for the current user."""
    conversation = Conversation(
        user_id=current_user.id,
        title=data.title or "New Conversation",
        model_type=data.model_type,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    # Ensure messages is loaded
    conversation.messages = []
    return conversation


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="Get conversation with messages",
)
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    """Return a conversation including all its messages."""
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
        .options(selectinload(Conversation.messages))
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise NotFoundError(detail="Conversation not found")

    return conversation


@router.patch(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="Update conversation",
)
async def update_conversation(
    conversation_id: UUID,
    data: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    """Update conversation title."""
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
        .options(selectinload(Conversation.messages))
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise NotFoundError(detail="Conversation not found")

    if data.title is not None:
        conversation.title = data.title

    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete conversation",
)
async def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a conversation and all its messages."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise NotFoundError(detail="Conversation not found")

    await db.delete(conversation)
    await db.commit()


# ─── Messages ─────────────────────────────────────────────────

@router.get(
    "/{conversation_id}/messages",
    summary="Get conversation message history",
)
async def get_messages(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all messages in a conversation."""
    # Verify conversation ownership
    conv_result = await db.execute(
        select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Conversation not found")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()

    return {
        "messages": [
            {
                "id": str(msg.id),
                "conversation_id": str(msg.conversation_id),
                "role": msg.role,
                "content": msg.content,
                "model_metadata": msg.model_metadata,
                "tokens_used": msg.tokens_used,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ],
        "total": len(messages),
    }
