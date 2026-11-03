import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from ..auth.dependencies import CurrentUser
from ..database import DbDep
from ..redis import RedisDep
from . import service
from .models import Generation
from .schemas import GenerationOut
from .tasks import kick_generation

router = APIRouter(prefix="/generations", tags=["generations"])


@router.get("", response_model=list[GenerationOut])
async def list_generations(
    db: DbDep,
    user: CurrentUser,
    conversation_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GenerationOut]:
    statement = select(Generation).where(Generation.owner_id == user.id)
    if conversation_id is not None:
        statement = statement.where(Generation.conversation_id == conversation_id)
    generations = list(
        (
            await db.scalars(
                statement.order_by(Generation.created_at.desc()).limit(limit).offset(offset)
            )
        ).all()
    )
    return [await service.generation_out(db, generation) for generation in generations]


@router.get("/{generation_id}", response_model=GenerationOut)
async def get_generation(generation_id: uuid.UUID, db: DbDep, user: CurrentUser) -> GenerationOut:
    generation = await service.owned_generation(db, generation_id, user)
    return await service.generation_out(db, generation)


@router.post("/{generation_id}/retry", status_code=202, response_model=GenerationOut)
async def retry_generation(
    generation_id: uuid.UUID, db: DbDep, user: CurrentUser, redis: RedisDep
) -> GenerationOut:
    previous = await service.owned_generation(db, generation_id, user)
    generation = await service.retry_generation(db, redis, user, previous)
    await kick_generation(generation.id)
    return await service.generation_out(db, generation)
