import hashlib
import json
import uuid

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..conversations.models import Conversation, Message
from ..database import utc_now
from ..exceptions import ConflictError, NotFoundError
from ..models.models import Model, ModelVersion
from ..redis import fixed_window_limit
from ..runs import RunStatus
from ..users.models import User
from .models import Generation
from .schemas import GenerationOut


def request_hash(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


async def owned_generation(db: AsyncSession, generation_id: uuid.UUID, user: User) -> Generation:
    generation = await db.scalar(
        select(Generation).where(Generation.id == generation_id, Generation.owner_id == user.id)
    )
    if generation is None:
        raise NotFoundError("generation not found")
    return generation


async def check_generation_rate(redis: Redis, user: User) -> None:
    allowed = await fixed_window_limit(
        redis,
        f"rate:generation:{user.id}",
        get_settings().generation_per_hour,
        3600,
    )
    if not allowed:
        raise HTTPException(429, "generation rate limit exceeded", headers={"Retry-After": "3600"})


async def create_generation(
    db: AsyncSession,
    redis: Redis,
    user: User,
    conversation: Conversation,
    content: str,
    idempotency_key: str,
) -> tuple[Generation, bool]:
    description = content.strip()
    history_rows = list(
        (
            await db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(24)
            )
        ).all()
    )
    history = [
        {"role": message.role, "content": message.content[:6000]}
        for message in reversed(history_rows)
        if message.content and (message.role == "user" or message.status == RunStatus.DONE.value)
    ][-12:]
    base_version = await db.scalar(
        select(ModelVersion)
        .join(Model, ModelVersion.model_id == Model.id)
        .where(Model.conversation_id == conversation.id)
        .order_by(ModelVersion.version.desc())
        .limit(1)
    )
    payload = {
        "description": description,
        "history": history,
        "base_model": base_version.document if base_version else None,
        "assumption_policy": "allow_inferred",
    }
    payload_hash = request_hash(payload)
    existing = await db.scalar(
        select(Generation).where(
            Generation.owner_id == user.id, Generation.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.conversation_id != conversation.id
            or existing.request.get("description") != description
        ):
            raise ConflictError("Idempotency-Key was already used with a different request")
        return existing, False
    await check_generation_rate(redis, user)

    user_message = Message(conversation_id=conversation.id, role="user", content=description)
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="",
        status=RunStatus.QUEUED.value,
    )
    db.add_all([user_message, assistant_message])
    await db.flush()
    generation = Generation(
        owner_id=user.id,
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        idempotency_key=idempotency_key,
        request_hash=payload_hash,
        request=payload,
    )
    db.add(generation)
    now = utc_now()
    conversation.last_message_at = now
    conversation.updated_at = now
    if conversation.title == "New conversation":
        conversation.title = description[:80]
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(Generation).where(
                Generation.owner_id == user.id, Generation.idempotency_key == idempotency_key
            )
        )
        if (
            existing is None
            or existing.conversation_id != conversation.id
            or existing.request.get("description") != description
        ):
            raise ConflictError("Idempotency-Key conflict") from None
        return existing, False
    return generation, True


async def generation_out(db: AsyncSession, generation: Generation) -> GenerationOut:
    version = await db.scalar(
        select(ModelVersion).where(ModelVersion.generation_id == generation.id)
    )
    return GenerationOut(
        id=generation.id,
        conversation_id=generation.conversation_id,
        user_message_id=generation.user_message_id,
        assistant_message_id=generation.assistant_message_id,
        retry_of_id=generation.retry_of_id,
        status=generation.status,
        stage=generation.stage,
        error=generation.error,
        attempt=generation.attempt,
        model_version_id=version.id if version else None,
        created_at=generation.created_at,
        started_at=generation.started_at,
        finished_at=generation.finished_at,
    )


async def retry_generation(
    db: AsyncSession, redis: Redis, user: User, previous: Generation
) -> Generation:
    if previous.status != RunStatus.ERROR.value:
        raise ConflictError("only failed generations can be retried")
    await check_generation_rate(redis, user)
    assistant = Message(
        conversation_id=previous.conversation_id,
        role="assistant",
        content="",
        status=RunStatus.QUEUED.value,
    )
    db.add(assistant)
    await db.flush()
    generation = Generation(
        owner_id=user.id,
        conversation_id=previous.conversation_id,
        user_message_id=previous.user_message_id,
        assistant_message_id=assistant.id,
        retry_of_id=previous.id,
        idempotency_key=f"retry:{previous.id}:{uuid.uuid4().hex}",
        request_hash=previous.request_hash,
        request=previous.request,
        attempt=previous.attempt + 1,
    )
    db.add(generation)
    await db.commit()
    return generation
