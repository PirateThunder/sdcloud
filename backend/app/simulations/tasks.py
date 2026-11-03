import logging
import uuid
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..broker import broker
from ..clients.generator import CoreJobInfo, GeneratorClient
from ..config import get_settings
from ..core_runner import submit_with_retry, wait_for_core
from ..database import SessionFactory, utc_now
from ..models.models import ModelVersion
from ..runs import ACTIVE_STATUSES, RunStatus
from .models import Simulation
from .schemas import SimulationResultSnapshot

logger = logging.getLogger(__name__)


@broker.task
async def run_simulation(simulation_id: str) -> None:
    await execute_simulation(uuid.UUID(simulation_id))


async def kick_simulation(simulation_id: uuid.UUID) -> None:
    try:
        await run_simulation.kiq(str(simulation_id))
    except Exception:
        logger.warning("simulation %s could not be enqueued; watchdog will retry", simulation_id)


async def _claim(db: AsyncSession, simulation_id: uuid.UUID, lease_owner: str) -> Simulation | None:
    now = utc_now()
    result = await db.execute(
        update(Simulation)
        .where(Simulation.id == simulation_id)
        .where(
            or_(
                Simulation.status == RunStatus.QUEUED.value,
                (
                    Simulation.status.in_([RunStatus.SUBMITTED.value, RunStatus.RUNNING.value])
                    & (Simulation.lease_expires_at < now)
                ),
            )
        )
        .values(
            status=RunStatus.SUBMITTED.value,
            stage="submitting",
            started_at=now,
            lease_owner=lease_owner,
            lease_expires_at=now + timedelta(seconds=get_settings().worker_lease_seconds),
            updated_at=now,
            error=None,
        )
        .returning(Simulation.id)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        return None
    await db.commit()
    return await db.get(Simulation, simulation_id)


async def execute_simulation(
    simulation_id: uuid.UUID,
    *,
    db: AsyncSession | None = None,
    client: GeneratorClient | None = None,
) -> None:
    own_db = db is None
    own_client = client is None
    db = db or SessionFactory()
    client = client or GeneratorClient()
    lease_owner = uuid.uuid4().hex
    try:
        simulation = await _claim(db, simulation_id, lease_owner)
        if simulation is None:
            return
        settings = get_settings()
        version = await db.get(ModelVersion, simulation.model_version_id)
        if version is None:
            raise RuntimeError("model version was deleted")
        if simulation.generator_job_id is None:
            simulation.generator_job_id = await submit_with_retry(
                lambda: client.create_simulation(
                    {"model": version.document, "parameters": simulation.request},
                    str(simulation.id),
                ),
                settings.core_submit_timeout_seconds,
            )
            simulation.status = RunStatus.RUNNING.value
            simulation.stage = "pending"
            simulation.updated_at = utc_now()
            await db.commit()

        async def heartbeat(job: CoreJobInfo) -> None:
            now = utc_now()
            result = await db.execute(
                update(Simulation)
                .where(Simulation.id == simulation_id, Simulation.lease_owner == lease_owner)
                .values(
                    status=RunStatus.RUNNING.value,
                    stage=job.stage or job.status,
                    lease_expires_at=now + timedelta(seconds=settings.worker_lease_seconds),
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                await db.rollback()
                raise RuntimeError("worker lease lost")
            await db.commit()

        job = await wait_for_core(
            client,
            simulation.generator_job_id,
            timeout_seconds=settings.simulation_timeout_seconds,
            poll_interval=settings.poll_interval_seconds,
            heartbeat=heartbeat,
            failure_message="simulation failed in generation core",
        )
        raw_result = await client.get_result(job.job_id)
        result = SimulationResultSnapshot.model_validate(raw_result)
        if result.model_hash != version.model_hash:
            raise ValueError("model hash mismatch")
        await heartbeat(job)
        simulation.result = result.model_dump(mode="json")
        simulation.requested_engine = result.requested_engine
        simulation.engine = result.engine
        simulation.requested_method = result.requested_method
        simulation.integration_method = result.integration_method
        simulation.fallback_reason = result.fallback_reason
        simulation.status = RunStatus.DONE.value
        simulation.stage = "done"
        simulation.error = None
        simulation.finished_at = utc_now()
        simulation.updated_at = utc_now()
        simulation.lease_owner = None
        simulation.lease_expires_at = None
        await db.commit()
    except Exception as exc:
        logger.exception("simulation %s failed", simulation_id)
        await db.rollback()
        simulation = await db.get(Simulation, simulation_id)
        if (
            simulation is not None
            and simulation.status in ACTIVE_STATUSES
            and simulation.lease_owner == lease_owner
        ):
            simulation.status = RunStatus.ERROR.value
            simulation.stage = "error"
            simulation.error = _public_error(exc)
            simulation.finished_at = utc_now()
            simulation.lease_owner = None
            simulation.lease_expires_at = None
            await db.commit()
    finally:
        if own_client:
            await client.close()
        if own_db:
            await db.close()


def _public_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "simulation timed out"
    if isinstance(exc, ValidationError | ValueError):
        return "generator returned an invalid simulation result"
    text = str(exc)
    if text.startswith(("INVALID_", "UNSUPPORTED_", "MISSING_")):
        return text[:500]
    return "simulation failed; please retry"
