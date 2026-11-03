import logging
import uuid
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..broker import broker
from ..clients.generator import CoreJobInfo, GeneratorClient
from ..config import get_settings
from ..conversations.models import Conversation, Message
from ..core_runner import submit_with_retry, wait_for_core
from ..database import SessionFactory, utc_now
from ..models.models import Model, ModelVersion
from ..models.service import document_hash, next_version_number
from ..runs import ACTIVE_STATUSES, RunStatus
from .models import Generation
from .schemas import ConversationResultSnapshot

logger = logging.getLogger(__name__)
_EXPORT_FILES = {"python": "model.py", "vensim": "model.mdl", "xmile": "model.xmile"}


@broker.task
async def run_generation(generation_id: str) -> None:
    await execute_generation(uuid.UUID(generation_id))


async def kick_generation(generation_id: uuid.UUID) -> None:
    try:
        await run_generation.kiq(str(generation_id))
    except Exception:
        logger.warning("generation %s could not be enqueued; watchdog will retry", generation_id)


async def _claim(db: AsyncSession, generation_id: uuid.UUID, lease_owner: str) -> Generation | None:
    now = utc_now()
    settings = get_settings()
    result = await db.execute(
        update(Generation)
        .where(Generation.id == generation_id)
        .where(
            or_(
                Generation.status == RunStatus.QUEUED.value,
                (
                    Generation.status.in_([RunStatus.SUBMITTED.value, RunStatus.RUNNING.value])
                    & (Generation.lease_expires_at < now)
                ),
            )
        )
        .values(
            status=RunStatus.SUBMITTED.value,
            stage="submitting",
            started_at=now,
            lease_owner=lease_owner,
            lease_expires_at=now + timedelta(seconds=settings.worker_lease_seconds),
            updated_at=now,
            error=None,
        )
        .returning(Generation.id)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        return None
    await db.commit()
    return await db.get(Generation, generation_id)


async def execute_generation(
    generation_id: uuid.UUID,
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
        generation = await _claim(db, generation_id, lease_owner)
        if generation is None:
            return
        settings = get_settings()
        if generation.generator_job_id is None:
            generation.generator_job_id = await submit_with_retry(
                lambda: client.create_chat(generation.request, str(generation.id)),
                settings.core_submit_timeout_seconds,
            )
            generation.status = RunStatus.RUNNING.value
            generation.stage = "pending"
            generation.updated_at = utc_now()
            await db.commit()

        async def heartbeat(job: CoreJobInfo) -> None:
            now = utc_now()
            result = await db.execute(
                update(Generation)
                .where(Generation.id == generation_id, Generation.lease_owner == lease_owner)
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
            generation.generator_job_id,
            timeout_seconds=settings.generation_timeout_seconds,
            poll_interval=settings.poll_interval_seconds,
            heartbeat=heartbeat,
            failure_message="generation core could not produce a valid model",
        )
        raw_response = await client.get_result(job.job_id)
        response = ConversationResultSnapshot.model_validate(raw_response)
        exports = {}
        if response.model is not None:
            for export_format, filename in _EXPORT_FILES.items():
                if filename in job.files:
                    exports[export_format] = await client.download_text(job.job_id, filename)
        await heartbeat(job)
        await _save_result(db, generation, response, exports, job)
    except Exception as exc:
        logger.exception("generation %s failed", generation_id)
        await db.rollback()
        generation = await db.get(Generation, generation_id)
        if (
            generation is not None
            and generation.status in ACTIVE_STATUSES
            and generation.lease_owner == lease_owner
        ):
            generation.status = RunStatus.ERROR.value
            generation.stage = "error"
            generation.error = _public_error(exc)
            generation.finished_at = utc_now()
            generation.lease_owner = None
            generation.lease_expires_at = None
            message = await db.get(Message, generation.assistant_message_id)
            if message is not None:
                message.status = RunStatus.ERROR.value
                message.content = "Generation failed. You can retry it."
            await db.commit()
    finally:
        if own_client:
            await client.close()
        if own_db:
            await db.close()


def _public_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "generation timed out"
    if isinstance(exc, ValidationError):
        return "generator returned an invalid model document"
    text = str(exc)
    if text.startswith(("INVALID_", "UNSUPPORTED_", "MISSING_")):
        return text[:500]
    return "generation failed; please retry"


async def _save_result(
    db: AsyncSession,
    generation: Generation,
    response: ConversationResultSnapshot,
    exports: dict,
    job: CoreJobInfo,
) -> None:
    conversation = await db.scalar(
        select(Conversation).where(Conversation.id == generation.conversation_id).with_for_update()
    )
    if conversation is None:
        raise RuntimeError("generation conversation was deleted")
    message = await db.get(Message, generation.assistant_message_id)
    if message is None:
        raise RuntimeError("assistant message was deleted")
    now = utc_now()
    generation.status = RunStatus.DONE.value
    generation.stage = "done"
    generation.error = None
    generation.finished_at = now
    generation.updated_at = now
    generation.lease_owner = None
    generation.lease_expires_at = None
    generation.usage = job.manifest.get("usage") if isinstance(job.manifest, dict) else None
    message.content = response.assistant_text
    message.status = RunStatus.DONE.value
    conversation.last_message_at = now
    conversation.updated_at = now

    if response.model is not None:
        document = response.model.model_dump(mode="json")
        model = await db.scalar(
            select(Model)
            .where(Model.conversation_id == conversation.id)
            .order_by(Model.created_at.desc())
            .limit(1)
        )
        if model is None:
            model = Model(
                owner_id=generation.owner_id,
                conversation_id=conversation.id,
                name=document["name"],
            )
            db.add(model)
            await db.flush()
        else:
            model.name = document["name"]
            model.updated_at = now
        version = ModelVersion(
            model_id=model.id,
            generation_id=generation.id,
            version=await next_version_number(db, model.id),
            name=document["name"],
            document=document,
            model_hash=document_hash(document),
            exports=exports,
        )
        db.add(version)
    await db.commit()
