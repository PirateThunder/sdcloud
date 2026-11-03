import uuid

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..exceptions import ConflictError, NotFoundError
from ..generations.service import request_hash
from ..models.models import ModelVersion
from ..models.service import owned_version
from ..redis import fixed_window_limit
from ..runs import RunStatus
from ..users.models import User
from .models import Simulation
from .schemas import SimulationOut


async def owned_simulation(db: AsyncSession, simulation_id: uuid.UUID, user: User) -> Simulation:
    simulation = await db.scalar(
        select(Simulation).where(Simulation.id == simulation_id, Simulation.owner_id == user.id)
    )
    if simulation is None:
        raise NotFoundError("simulation not found")
    return simulation


def simulation_out(simulation: Simulation) -> SimulationOut:
    return SimulationOut(
        id=simulation.id,
        model_version_id=simulation.model_version_id,
        retry_of_id=simulation.retry_of_id,
        status=simulation.status,
        stage=simulation.stage,
        parameters=simulation.request,
        result=simulation.result,
        requested_engine=simulation.requested_engine,
        engine=simulation.engine,
        requested_method=simulation.requested_method,
        integration_method=simulation.integration_method,
        fallback_reason=simulation.fallback_reason,
        error=simulation.error,
        attempt=simulation.attempt,
        created_at=simulation.created_at,
        started_at=simulation.started_at,
        finished_at=simulation.finished_at,
    )


async def check_simulation_rate(redis: Redis, user: User) -> None:
    allowed = await fixed_window_limit(
        redis, f"rate:simulation:{user.id}", get_settings().simulation_per_hour, 3600
    )
    if not allowed:
        raise HTTPException(429, "simulation rate limit exceeded", headers={"Retry-After": "3600"})


async def create_simulation(
    db: AsyncSession,
    redis: Redis,
    user: User,
    version: ModelVersion,
    parameters: dict,
    idempotency_key: str,
) -> tuple[Simulation, bool]:
    payload_hash = request_hash({"model_hash": version.model_hash, "parameters": parameters})
    existing = await db.scalar(
        select(Simulation).where(
            Simulation.owner_id == user.id, Simulation.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if existing.request_hash != payload_hash:
            raise ConflictError("Idempotency-Key was already used with different parameters")
        return existing, False
    await check_simulation_rate(redis, user)
    simulation = Simulation(
        owner_id=user.id,
        model_version_id=version.id,
        idempotency_key=idempotency_key,
        request_hash=payload_hash,
        request=parameters,
    )
    db.add(simulation)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(Simulation).where(
                Simulation.owner_id == user.id, Simulation.idempotency_key == idempotency_key
            )
        )
        if existing is None or existing.request_hash != payload_hash:
            raise ConflictError("Idempotency-Key conflict") from None
        return existing, False
    return simulation, True


async def retry_simulation(
    db: AsyncSession, redis: Redis, user: User, previous: Simulation
) -> Simulation:
    if previous.status != RunStatus.ERROR.value:
        raise ConflictError("only failed simulations can be retried")
    await check_simulation_rate(redis, user)
    simulation = Simulation(
        owner_id=user.id,
        model_version_id=previous.model_version_id,
        retry_of_id=previous.id,
        idempotency_key=f"retry:{previous.id}:{uuid.uuid4().hex}",
        request_hash=previous.request_hash,
        request=previous.request,
        attempt=previous.attempt + 1,
    )
    db.add(simulation)
    await db.commit()
    return simulation


__all__ = [
    "create_simulation",
    "owned_simulation",
    "owned_version",
    "retry_simulation",
    "simulation_out",
]
