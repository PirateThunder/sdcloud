import hashlib
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..exceptions import NotFoundError
from ..users.models import User
from .models import Model, ModelVersion
from .schemas import ModelListItem, ModelVersionDetail, ModelVersionListItem


def document_hash(document: dict) -> str:
    payload = {
        "schema_version": document["schema_version"],
        "time": document["time"],
        "variables": document["variables"],
        "tables": document.get("tables", []),
        "dimensions": document.get("dimensions", []),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


async def owned_model(db: AsyncSession, model_id: uuid.UUID, user: User) -> Model:
    model = await db.scalar(select(Model).where(Model.id == model_id, Model.owner_id == user.id))
    if model is None:
        raise NotFoundError("model not found")
    return model


async def owned_version(db: AsyncSession, version_id: uuid.UUID, user: User) -> ModelVersion:
    version = await db.scalar(
        select(ModelVersion)
        .join(Model, Model.id == ModelVersion.model_id)
        .where(ModelVersion.id == version_id, Model.owner_id == user.id)
    )
    if version is None:
        raise NotFoundError("model version not found")
    return version


async def latest_version(db: AsyncSession, model_id: uuid.UUID) -> ModelVersion | None:
    return await db.scalar(
        select(ModelVersion)
        .where(ModelVersion.model_id == model_id)
        .order_by(ModelVersion.version.desc())
        .limit(1)
    )


def model_list_item(model: Model, version: ModelVersion) -> ModelListItem:
    return ModelListItem(
        id=model.id,
        conversation_id=model.conversation_id,
        name=model.name,
        kind=model.kind,
        latest_version=version.version,
        latest_version_id=version.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def version_list_item(version: ModelVersion) -> ModelVersionListItem:
    return ModelVersionListItem(
        id=version.id,
        model_id=version.model_id,
        generation_id=version.generation_id,
        version=version.version,
        name=version.name,
        model_hash=version.model_hash,
        created_at=version.created_at,
    )


def version_detail(version: ModelVersion) -> ModelVersionDetail:
    return ModelVersionDetail(
        **version_list_item(version).model_dump(),
        document=version.document,
        available_exports=sorted(version.exports),
    )


async def next_version_number(db: AsyncSession, model_id: uuid.UUID) -> int:
    current = await db.scalar(
        select(func.max(ModelVersion.version)).where(ModelVersion.model_id == model_id)
    )
    return int(current or 0) + 1
