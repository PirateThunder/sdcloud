"""Pydantic schemas for Simulation."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SimulationParameters(BaseModel):
    """Schema for simulation parameters."""

    time_start: float = Field(default=0.0, ge=0.0)
    time_end: float = Field(default=100.0, gt=0.0)
    time_step: float = Field(default=0.25, gt=0.0)
    custom_params: dict = Field(default_factory=dict)


class SimulationCreate(BaseModel):
    """Schema for creating a simulation."""

    model_id: uuid.UUID
    parameters: SimulationParameters = Field(default_factory=SimulationParameters)


class SimulationResponse(BaseModel):
    """Schema for simulation response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    model_id: uuid.UUID
    parameters: dict | None = None
    time_start: float
    time_end: float
    time_step: float
    results: dict | None = None
    status: str
    created_at: datetime
    completed_at: datetime | None = None


class SimulationRunRequest(BaseModel):
    """Schema for requesting a simulation run."""

    parameters: SimulationParameters = Field(default_factory=SimulationParameters)


class SimulationResults(BaseModel):
    """Schema for simulation results."""

    variables: list[str]
    time: list[float]
    data: dict[str, list[float]]
    metadata: dict = Field(default_factory=dict)


class SimulationListResponse(BaseModel):
    """Schema for paginated simulation list."""

    items: list[SimulationResponse]
    total: int
