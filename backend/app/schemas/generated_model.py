"""Pydantic schemas for GeneratedModel."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SDVariable(BaseModel):
    """Schema for a system dynamics variable."""

    name: str
    type: str = Field(..., pattern="^(stock|flow|auxiliary|constant)$")
    description: str | None = None
    initial_value: float | None = None
    units: str | None = None


class SDEquation(BaseModel):
    """Schema for a system dynamics equation."""

    lhs: str
    rhs: str
    variable_type: str = Field(..., pattern="^(stock|flow|auxiliary|constant)$")


class CLDNode(BaseModel):
    """Schema for a CLD node."""

    id: str
    label: str
    type: str = Field(default="variable", pattern="^(stock|flow|auxiliary|constant|variable)$")


class CLDEdge(BaseModel):
    """Schema for a CLD edge."""

    source: str
    target: str
    polarity: str = Field(..., pattern="^[+\-]$")
    label: str | None = None


class CLDData(BaseModel):
    """Schema for CLD diagram data."""

    nodes: list[CLDNode]
    edges: list[CLDEdge]


class SFDNode(BaseModel):
    """Schema for a SFD node."""

    id: str
    label: str
    type: str = Field(..., pattern="^(stock|flow|auxiliary|cloud|constant)$")


class SFDEdge(BaseModel):
    """Schema for a SFD edge."""

    source: str
    target: str
    type: str = Field(default="link", pattern="^(flow|link)$")
    label: str | None = None


class SFDData(BaseModel):
    """Schema for SFD diagram data."""

    nodes: list[SFDNode]
    edges: list[SFDEdge]


class GeneratedModelBase(BaseModel):
    """Base schema for generated model."""

    name: str


class GeneratedModelCreate(GeneratedModelBase):
    """Schema for creating a generated model record."""

    message_id: uuid.UUID
    conversation_id: uuid.UUID


class GeneratedModelDetail(GeneratedModelBase):
    """Schema for generated model detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    variables: list[SDVariable] = []
    equations: list[SDEquation] = []
    cld_data: CLDData | None = None
    sfd_data: SFDData | None = None
    vensim_code: str | None = None
    python_code: str | None = None
    status: str
    created_at: datetime


class GeneratedModelListItem(GeneratedModelBase):
    """Schema for listing generated models."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    status: str
    created_at: datetime


class GeneratedModelListResponse(BaseModel):
    """Schema for paginated model list."""

    items: list[GeneratedModelListItem]
    total: int
