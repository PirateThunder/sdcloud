"""Schemas for anonymous/guest endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GuestMessage(BaseModel):
    """A single message in a guest conversation."""

    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1)


class GuestChatRequest(BaseModel):
    """Request schema for guest chat."""

    messages: list[GuestMessage] = Field(default_factory=list)
    content: str = Field(..., min_length=1)


class GuestAssistantMessage(BaseModel):
    """Assistant message returned to a guest."""

    id: uuid.UUID
    role: str
    content: str
    model_metadata: dict | None = None
    tokens_used: int | None = None
    created_at: datetime


class GuestModelData(BaseModel):
    """Generated model data returned to a guest."""

    id: uuid.UUID
    name: str
    variables: list[dict] = []
    equations: list[dict] = []
    cld_data: dict = {}
    sfd_data: dict = {}
    python_code: str | None = None
    vensim_code: str | None = None
    status: str
    generation_log: list[str] = []
    created_at: datetime
    updated_at: datetime


class GuestChatResponse(BaseModel):
    """Response schema for guest chat."""

    message: GuestAssistantMessage
    model: GuestModelData | None = None


class GuestSimulationParameters(BaseModel):
    """Parameters for a guest simulation run."""

    time_start: float = Field(default=0.0)
    time_end: float = Field(default=100.0)
    time_step: float = Field(default=0.25)
    custom_params: dict = Field(default_factory=dict)


class GuestSimulationRequest(BaseModel):
    """Request schema for guest simulation."""

    python_code: str | None = None
    vensim_code: str | None = None
    parameters: GuestSimulationParameters


class GuestSimulationResult(BaseModel):
    """Result data for a guest simulation."""

    time: list[float]
    variables: dict[str, list[float]]


class GuestSimulationResponse(BaseModel):
    """Response schema for guest simulation."""

    status: str
    results: GuestSimulationResult | None = None
    error: str | None = None
