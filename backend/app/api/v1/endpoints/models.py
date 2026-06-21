"""Generated model endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import NotFoundError
from app.models.conversation import Conversation
from app.models.generated_model import GeneratedModel
from app.models.user import User
from app.schemas.generated_model import (
    GeneratedModelDetail,
    GeneratedModelListItem,
    GeneratedModelListResponse,
)

router = APIRouter(prefix="/models", tags=["Models"])


@router.get(
    "",
    response_model=GeneratedModelListResponse,
    summary="List generated models for current user",
)
async def list_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all generated models belonging to the current user's conversations."""
    # Get user's conversation IDs
    conv_result = await db.execute(
        select(Conversation.id).where(Conversation.user_id == current_user.id)
    )
    conv_ids = [row[0] for row in conv_result.all()]

    if not conv_ids:
        return {"items": [], "total": 0}

    # Get models for those conversations
    model_result = await db.execute(
        select(GeneratedModel)
        .where(GeneratedModel.conversation_id.in_(conv_ids))
        .order_by(GeneratedModel.created_at.desc())
    )
    models = model_result.scalars().all()

    items = []
    for model in models:
        items.append({
            "id": model.id,
            "message_id": model.message_id,
            "conversation_id": model.conversation_id,
            "name": model.name,
            "status": model.status,
            "created_at": model.created_at,
        })

    return {"items": items, "total": len(items)}


@router.get(
    "/{model_id}",
    response_model=GeneratedModelDetail,
    summary="Get generated model details",
)
async def get_model(
    model_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneratedModel:
    """Return detailed information about a generated model."""
    # Get model with ownership check through conversation
    result = await db.execute(
        select(GeneratedModel).where(GeneratedModel.id == model_id)
    )
    model = result.scalar_one_or_none()

    if model is None:
        raise NotFoundError(detail="Model not found")

    # Verify ownership
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == model.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Model not found")

    return model


@router.get(
    "/{model_id}/code",
    summary="Get model code (Python or Vensim)",
)
async def get_model_code(
    model_id: UUID,
    format: str = "python",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return the generated code for a model.

    Args:
        model_id: UUID of the generated model.
        format: "python" or "vensim".
    """
    result = await db.execute(
        select(GeneratedModel).where(GeneratedModel.id == model_id)
    )
    model = result.scalar_one_or_none()

    if model is None:
        raise NotFoundError(detail="Model not found")

    # Verify ownership
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == model.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Model not found")

    if format == "vensim":
        code = model.vensim_code or ""
        language = "vensim"
    else:
        code = model.python_code or ""
        language = "python"

    return {
        "model_id": str(model.id),
        "name": model.name,
        "format": format,
        "language": language,
        "code": code,
        "status": model.status,
    }


@router.get(
    "/{model_id}/variables",
    summary="Get model variables",
)
async def get_model_variables(
    model_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the variables of a generated model."""
    result = await db.execute(
        select(GeneratedModel).where(GeneratedModel.id == model_id)
    )
    model = result.scalar_one_or_none()

    if model is None:
        raise NotFoundError(detail="Model not found")

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == model.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Model not found")

    return {
        "model_id": str(model.id),
        "variables": model.variables,
        "count": len(model.variables),
    }


@router.get(
    "/{model_id}/equations",
    summary="Get model equations",
)
async def get_model_equations(
    model_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the equations of a generated model."""
    result = await db.execute(
        select(GeneratedModel).where(GeneratedModel.id == model_id)
    )
    model = result.scalar_one_or_none()

    if model is None:
        raise NotFoundError(detail="Model not found")

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == model.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Model not found")

    return {
        "model_id": str(model.id),
        "equations": model.equations,
        "count": len(model.equations),
    }


@router.get(
    "/{model_id}/cld",
    summary="Get model CLD data",
)
async def get_model_cld(
    model_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the Causal Loop Diagram data for a model."""
    result = await db.execute(
        select(GeneratedModel).where(GeneratedModel.id == model_id)
    )
    model = result.scalar_one_or_none()

    if model is None:
        raise NotFoundError(detail="Model not found")

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == model.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Model not found")

    return {
        "model_id": str(model.id),
        "cld_data": model.cld_data,
    }


@router.get(
    "/{model_id}/sfd",
    summary="Get model SFD data",
)
async def get_model_sfd(
    model_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the Stock-Flow Diagram data for a model."""
    result = await db.execute(
        select(GeneratedModel).where(GeneratedModel.id == model_id)
    )
    model = result.scalar_one_or_none()

    if model is None:
        raise NotFoundError(detail="Model not found")

    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == model.conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    if conv_result.scalar_one_or_none() is None:
        raise NotFoundError(detail="Model not found")

    return {
        "model_id": str(model.id),
        "sfd_data": model.sfd_data,
    }
