import uuid

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..exceptions import NotFoundError
from ..generations.models import Generation
from ..models.models import ModelVersion
from ..users.models import User
from .models import Conversation, Message
from .schemas import MessageOut


async def owned_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, user: User
) -> Conversation:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.owner_id == user.id
        )
    )
    if conversation is None:
        raise NotFoundError("conversation not found")
    return conversation


async def list_conversations(db: AsyncSession, user: User) -> list[Conversation]:
    statement = (
        select(Conversation)
        .where(Conversation.owner_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    return list((await db.scalars(statement)).all())


async def conversation_messages(
    db: AsyncSession, conversation: Conversation, limit: int, offset: int
) -> list[MessageOut]:
    messages = list(
        (
            await db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(
                    Message.created_at.asc(),
                    case((Message.role == "user", 0), else_=1),
                    Message.id.asc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    if not messages:
        return []
    generations = list(
        (
            await db.scalars(
                select(Generation).where(
                    Generation.assistant_message_id.in_([message.id for message in messages])
                )
            )
        ).all()
    )
    generation_by_message = {
        generation.assistant_message_id: generation for generation in generations
    }
    versions = []
    if generations:
        versions = list(
            (
                await db.scalars(
                    select(ModelVersion).where(
                        ModelVersion.generation_id.in_(
                            [generation.id for generation in generations]
                        )
                    )
                )
            ).all()
        )
    version_by_generation = {version.generation_id: version for version in versions}
    result = []
    for message in messages:
        generation = generation_by_message.get(message.id)
        version = version_by_generation.get(generation.id) if generation else None
        result.append(
            MessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                status=message.status,
                generation_id=generation.id if generation else None,
                model_version_id=version.id if version else None,
                created_at=message.created_at,
            )
        )
    return result
