import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ModelListItem(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    name: str
    kind: str
    latest_version: int
    latest_version_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ModelVersionListItem(BaseModel):
    id: uuid.UUID
    model_id: uuid.UUID
    generation_id: uuid.UUID | None
    version: int
    name: str
    model_hash: str
    created_at: datetime


class ModelVersionDetail(ModelVersionListItem):
    document: dict
    available_exports: list[str]


class ModelListResponse(BaseModel):
    items: list[ModelListItem]
    total: int


class ModelVersionListResponse(BaseModel):
    items: list[ModelVersionListItem]
    total: int


ExportFormat = Literal["python", "vensim", "xmile"]
