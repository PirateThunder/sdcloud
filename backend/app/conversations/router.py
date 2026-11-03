import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response

from ..auth.dependencies import CurrentUser
from ..database import DbDep
from ..generations import service as generation_service
from ..generations.tasks import kick_generation
from ..redis import RedisDep
from . import service
from .models import Conversation, Message
from .schemas import (
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageAccepted,
    MessageCreate,
    MessageOut,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(db: DbDep, user: CurrentUser) -> list[Conversation]:
    return await service.list_conversations(db, user)


@router.post("", status_code=201, response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate, db: DbDep, user: CurrentUser
) -> Conversation:
    title = body.title.strip() if body.title and body.title.strip() else "New conversation"
    conversation = Conversation(owner_id=user.id, title=title)
    db.add(conversation)
    await db.commit()
    return conversation


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: uuid.UUID, db: DbDep, user: CurrentUser
) -> Conversation:
    return await service.owned_conversation(db, conversation_id, user)


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, db: DbDep, user: CurrentUser
) -> Conversation:
    conversation = await service.owned_conversation(db, conversation_id, user)
    conversation.title = body.title.strip()
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, db: DbDep, user: CurrentUser) -> None:
    conversation = await service.owned_conversation(db, conversation_id, user)
    await db.delete(conversation)
    await db.commit()


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageOut]:
    conversation = await service.owned_conversation(db, conversation_id, user)
    return await service.conversation_messages(db, conversation, limit, offset)


@router.post("/{conversation_id}/messages", status_code=202, response_model=MessageAccepted)
async def send_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    db: DbDep,
    user: CurrentUser,
    redis: RedisDep,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> MessageAccepted:
    conversation = await service.owned_conversation(db, conversation_id, user)
    generation, created = await generation_service.create_generation(
        db, redis, user, conversation, body.content, idempotency_key
    )
    if not created:
        response.status_code = 200
    await kick_generation(generation.id)
    user_message = await db.get(Message, generation.user_message_id)
    assistant_message = await db.get(Message, generation.assistant_message_id)
    return MessageAccepted(
        user_message=MessageOut(
            id=user_message.id,
            role=user_message.role,
            content=user_message.content,
            status=user_message.status,
            created_at=user_message.created_at,
        ),
        assistant_message=MessageOut(
            id=assistant_message.id,
            role=assistant_message.role,
            content=assistant_message.content,
            status=assistant_message.status,
            generation_id=generation.id,
            created_at=assistant_message.created_at,
        ),
        generation_id=generation.id,
        status=generation.status,
    )
