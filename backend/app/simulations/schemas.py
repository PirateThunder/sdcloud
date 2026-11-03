import math
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..generations.schemas import SimulationParametersInput


class SimulationCreate(BaseModel):
    parameters: SimulationParametersInput = Field(default_factory=SimulationParametersInput)


class SimulationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    model_version_id: uuid.UUID
    retry_of_id: uuid.UUID | None
    status: str
    stage: str | None
    parameters: dict
    result: dict | None
    requested_engine: str | None
    engine: str | None
    requested_method: str | None
    integration_method: str | None
    fallback_reason: str | None
    error: str | None
    attempt: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SimulationResultSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["2.0"]
    model_id: str
    model_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    time: list[float] = Field(min_length=1, max_length=10000)
    variables: dict[str, list[float]] = Field(min_length=1)
    requested_engine: Literal["auto", "pysd", "scipy"]
    engine: Literal["pysd", "scipy"]
    requested_method: str
    integration_method: str
    time_step: float = Field(gt=0)
    saveper: float = Field(gt=0)
    rtol: float | None = None
    atol: float | None = None
    fallback_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, int | float | str | bool] = Field(default_factory=dict)
    created_at: datetime

    @model_validator(mode="after")
    def check_series(self):
        if any(not math.isfinite(value) for value in self.time):
            raise ValueError("non-finite time value")
        if any(right <= left for left, right in zip(self.time, self.time[1:], strict=False)):
            raise ValueError("simulation time must be strictly increasing")
        for name, values in self.variables.items():
            if len(values) != len(self.time):
                raise ValueError(f"series {name} has a different length")
            if any(not math.isfinite(value) for value in values):
                raise ValueError(f"series {name} contains non-finite values")
        return self
