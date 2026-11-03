import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy import select

from ..auth.dependencies import CurrentUser
from ..database import DbDep
from ..models.service import owned_version
from ..redis import RedisDep
from . import service
from .models import Simulation
from .schemas import SimulationCreate, SimulationOut
from .tasks import kick_simulation

router = APIRouter(tags=["simulations"])


@router.post(
    "/model-versions/{version_id}/simulations", status_code=202, response_model=SimulationOut
)
async def create_simulation(
    version_id: uuid.UUID,
    body: SimulationCreate,
    db: DbDep,
    user: CurrentUser,
    redis: RedisDep,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> SimulationOut:
    version = await owned_version(db, version_id, user)
    simulation, created = await service.create_simulation(
        db,
        redis,
        user,
        version,
        body.parameters.model_dump(mode="json"),
        idempotency_key,
    )
    if not created:
        response.status_code = 200
    await kick_simulation(simulation.id)
    return service.simulation_out(simulation)


@router.get("/model-versions/{version_id}/simulations", response_model=list[SimulationOut])
async def list_simulations(
    version_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SimulationOut]:
    version = await owned_version(db, version_id, user)
    simulations = list(
        (
            await db.scalars(
                select(Simulation)
                .where(Simulation.model_version_id == version.id, Simulation.owner_id == user.id)
                .order_by(Simulation.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return [service.simulation_out(simulation) for simulation in simulations]


@router.get("/simulations/{simulation_id}", response_model=SimulationOut)
async def get_simulation(simulation_id: uuid.UUID, db: DbDep, user: CurrentUser) -> SimulationOut:
    simulation = await service.owned_simulation(db, simulation_id, user)
    return service.simulation_out(simulation)


@router.post("/simulations/{simulation_id}/retry", status_code=202, response_model=SimulationOut)
async def retry_simulation(
    simulation_id: uuid.UUID, db: DbDep, user: CurrentUser, redis: RedisDep
) -> SimulationOut:
    previous = await service.owned_simulation(db, simulation_id, user)
    simulation = await service.retry_simulation(db, redis, user, previous)
    await kick_simulation(simulation.id)
    return service.simulation_out(simulation)
