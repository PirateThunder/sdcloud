import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, or_, update

from .auth.models import AuthSession
from .broker import broker
from .config import get_settings
from .database import SessionFactory, utc_now
from .generations.models import Generation
from .generations.tasks import kick_generation
from .runs import RunStatus
from .simulations.models import Simulation
from .simulations.tasks import kick_simulation

logger = logging.getLogger(__name__)


async def recover_jobs() -> tuple[int, int]:
    now = utc_now()
    settings = get_settings()
    queued_before = now - timedelta(seconds=settings.queued_retry_after_seconds)
    generation_ids = []
    simulation_ids = []
    async with SessionFactory() as db:
        for model, destination in ((Generation, generation_ids), (Simulation, simulation_ids)):
            result = await db.execute(
                update(model)
                .where(model.status == RunStatus.QUEUED.value, model.updated_at < queued_before)
                .values(updated_at=now)
                .returning(model.id)
            )
            destination.extend(result.scalars().all())
            result = await db.execute(
                update(model)
                .where(
                    model.status.in_([RunStatus.SUBMITTED.value, RunStatus.RUNNING.value]),
                    or_(model.lease_expires_at.is_(None), model.lease_expires_at < now),
                )
                .values(
                    status=RunStatus.QUEUED.value,
                    stage="recovering",
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
                .returning(model.id)
            )
            destination.extend(result.scalars().all())
        await db.commit()
    for generation_id in generation_ids:
        await kick_generation(generation_id)
    for simulation_id in simulation_ids:
        await kick_simulation(simulation_id)
    return len(generation_ids), len(simulation_ids)


@broker.task(schedule=[{"cron": "0 4 * * *"}])
async def purge_expired_sessions() -> None:
    async with SessionFactory() as db:
        await db.execute(delete(AuthSession).where(AuthSession.expires_at < utc_now()))
        await db.commit()


async def run_forever() -> None:
    while True:
        try:
            generations, simulations = await recover_jobs()
            if generations or simulations:
                logger.info("recovered %s generations and %s simulations", generations, simulations)
        except Exception:
            logger.exception("watchdog iteration failed")
        await asyncio.sleep(get_settings().watchdog_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_forever())
