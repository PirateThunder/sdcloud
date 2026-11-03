import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    retry_of_id: uuid.UUID | None
    status: str
    stage: str | None
    error: str | None
    attempt: int
    model_version_id: uuid.UUID | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ModelTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str
    initial_time: float = 0
    final_time: float
    time_step: float = Field(gt=0)
    saveper: float = Field(gt=0)


class VariableSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    kind: Literal["stock", "flow", "auxiliary", "constant"]
    units: dict[str, int] | None = None


class ValidationSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["passed", "passed_with_warnings", "failed"]


class ModelDocumentSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["2.0"]
    id: str
    name: str
    description: str
    time: ModelTime
    variables: list[VariableSnapshot] = Field(min_length=1, max_length=200)
    tables: list[dict] = Field(default_factory=list, max_length=100)
    dimensions: list[dict] = Field(default_factory=list, max_length=20)
    artifacts: dict[str, str] = Field(default_factory=dict)
    validation: ValidationSnapshot

    @model_validator(mode="after")
    def check_valid(self):
        if self.validation.status == "failed":
            raise ValueError("failed model validation cannot be saved as a result")
        if self.time.final_time <= self.time.initial_time:
            raise ValueError("invalid model time horizon")
        return self


class ConversationResultSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["answer", "clarification", "model"]
    assistant_text: str = Field(min_length=1, max_length=20000)
    model: ModelDocumentSnapshot | None = None

    @model_validator(mode="after")
    def check_model(self):
        if (self.kind == "model") != (self.model is not None):
            raise ValueError("model response must contain exactly one model")
        return self


class TimeSeriesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[tuple[float, float]] = Field(min_length=2, max_length=10000)
    interpolation: Literal["linear"] = "linear"
    extrapolation: Literal["clamp", "error"] = "error"

    @model_validator(mode="after")
    def check_points(self):
        times = [point[0] for point in self.points]
        if any(right <= left for left, right in zip(times, times[1:], strict=False)):
            raise ValueError("time series timestamps must be strictly increasing")
        return self


class SimulationParametersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["auto", "pysd", "scipy"] = "auto"
    integration_method: Literal["euler", "rk4", "rk45", "dop853", "lsoda", "bdf"] = "euler"
    initial_time: float | None = None
    final_time: float | None = None
    time_step: float | None = Field(default=None, gt=0)
    saveper: float | None = Field(default=None, gt=0)
    parameters: dict[str, float] = Field(default_factory=dict, max_length=100)
    stock_initial: dict[str, float] = Field(default_factory=dict, max_length=100)
    input_series: dict[str, TimeSeriesInput] = Field(default_factory=dict, max_length=20)
    rtol: float = Field(default=1e-6, gt=0)
    atol: float = Field(default=1e-9, gt=0)

    @model_validator(mode="after")
    def check_parameters(self):
        for name in (*self.parameters, *self.stock_initial):
            if not name.isascii() or not name.isidentifier():
                raise ValueError("invalid parameter name")
        if (
            self.initial_time is not None
            and self.final_time is not None
            and self.final_time <= self.initial_time
        ):
            raise ValueError("final_time must be greater than initial_time")
        return self
