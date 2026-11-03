import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from ..auth.dependencies import CurrentUser
from ..database import DbDep
from ..exceptions import ConflictError, NotFoundError
from . import service
from .models import Model, ModelVersion
from .schemas import (
    ExportFormat,
    ModelListItem,
    ModelListResponse,
    ModelVersionDetail,
    ModelVersionListResponse,
)

router = APIRouter(tags=["models"])
_EXPORTS = {
    "python": ("model.py", "text/x-python"),
    "vensim": ("model.mdl", "text/plain"),
    "xmile": ("model.xmile", "application/xml"),
}


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    db: DbDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ModelListResponse:
    models = list(
        (
            await db.scalars(
                select(Model)
                .where(Model.owner_id == user.id)
                .order_by(Model.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    items = []
    for model in models:
        version = await service.latest_version(db, model.id)
        if version is not None:
            items.append(service.model_list_item(model, version))
    total = await db.scalar(select(func.count(Model.id)).where(Model.owner_id == user.id))
    return ModelListResponse(items=items, total=int(total or 0))


@router.get("/models/{model_id}", response_model=ModelListItem)
async def get_model(model_id: uuid.UUID, db: DbDep, user: CurrentUser) -> ModelListItem:
    model = await service.owned_model(db, model_id, user)
    version = await service.latest_version(db, model.id)
    if version is None:
        raise ConflictError("model has no versions")
    return service.model_list_item(model, version)


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(model_id: uuid.UUID, db: DbDep, user: CurrentUser) -> None:
    model = await service.owned_model(db, model_id, user)
    await db.delete(model)
    await db.commit()


@router.get("/models/{model_id}/versions", response_model=ModelVersionListResponse)
async def list_versions(
    model_id: uuid.UUID, db: DbDep, user: CurrentUser
) -> ModelVersionListResponse:
    model = await service.owned_model(db, model_id, user)
    versions = list(
        (
            await db.scalars(
                select(ModelVersion)
                .where(ModelVersion.model_id == model.id)
                .order_by(ModelVersion.version.desc())
            )
        ).all()
    )
    return ModelVersionListResponse(
        items=[service.version_list_item(version) for version in versions], total=len(versions)
    )


@router.get("/model-versions/{version_id}", response_model=ModelVersionDetail)
async def get_version(version_id: uuid.UUID, db: DbDep, user: CurrentUser) -> ModelVersionDetail:
    version = await service.owned_version(db, version_id, user)
    return service.version_detail(version)


@router.get("/models/{model_id}/versions/{version_number}/export")
async def export_version(
    model_id: uuid.UUID,
    version_number: int,
    db: DbDep,
    user: CurrentUser,
    format: ExportFormat = "python",
) -> Response:
    model = await service.owned_model(db, model_id, user)
    version = await db.scalar(
        select(ModelVersion).where(
            ModelVersion.model_id == model.id, ModelVersion.version == version_number
        )
    )
    if version is None:
        raise NotFoundError("model version not found")
    content = version.exports.get(format)
    if content is None:
        raise ConflictError(f"{format} export is not available for this model version")
    filename, media_type = _EXPORTS[format]
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
