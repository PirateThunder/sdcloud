from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from pipeline.schemas import ModelDocument, SimulationParameters


class JobKind(StrEnum):
    GENERATE = "generate"
    CHAT = "chat"
    SIMULATE = "simulate"
    IMPORT = "import"
    SCENARIO = "scenario"
    SENSITIVITY = "sensitivity"
    CALIBRATION = "calibration"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: ModelDocument
    parameters: SimulationParameters = Field(default_factory=SimulationParameters)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=300)
    file_format: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class JobCreated(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str


class JobInfo(BaseModel):
    job_id: str
    kind: JobKind
    status: JobStatus
    stage: str | None = None
    attempt: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    files: list[str] = Field(default_factory=list)
    file_urls: list[str] = Field(default_factory=list)
    manifest: dict | None = None
    error: str | None = None
