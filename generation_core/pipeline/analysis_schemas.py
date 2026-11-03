from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .schemas import (
    ContractModel,
    ModelDocument,
    SimulationParameters,
    SimulationResult,
    TimeSeries,
)


class Scenario(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    parameters: dict[str, float] = Field(default_factory=dict, max_length=100)
    stock_initial: dict[str, float] = Field(default_factory=dict, max_length=100)
    input_series: dict[str, TimeSeries] = Field(default_factory=dict, max_length=20)


class ScenarioRunRequest(ContractModel):
    model: ModelDocument
    parameters: SimulationParameters = Field(default_factory=SimulationParameters)
    scenarios: list[Scenario] = Field(min_length=1, max_length=50)
    failure_policy: Literal["fail_fast", "keep_partial"] = "fail_fast"


class ScenarioRun(ContractModel):
    name: str
    status: Literal["done", "error"]
    result: SimulationResult | None = None
    error: str | None = None


class ScenarioRunResult(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    model_hash: str
    status: Literal["done", "partial", "error"]
    runs: list[ScenarioRun]


class SamplingTarget(ContractModel):
    name: str
    distribution: Literal["uniform", "normal", "lognormal", "discrete"]
    low: float | None = None
    high: float | None = None
    mean: float | None = None
    std: float | None = Field(default=None, gt=0)
    values: list[float] | None = None
    probabilities: list[float] | None = None

    @model_validator(mode="after")
    def check_distribution(self) -> SamplingTarget:
        if self.distribution in {"uniform", "lognormal"} and (
            self.low is None or self.high is None or self.low >= self.high
        ):
            raise ValueError("uniform/lognormal require low < high")
        if self.distribution == "normal" and (self.mean is None or self.std is None):
            raise ValueError("normal requires mean and std")
        if self.distribution == "lognormal" and self.low is not None and self.low <= 0:
            raise ValueError("lognormal requires low > 0")
        if self.distribution == "discrete":
            if not self.values:
                raise ValueError("discrete requires values")
            if self.probabilities is not None and (
                len(self.probabilities) != len(self.values)
                or any(value < 0 for value in self.probabilities)
                or sum(self.probabilities) <= 0
            ):
                raise ValueError("invalid discrete probabilities")
        return self


class SensitivityRequest(ContractModel):
    model: ModelDocument
    parameters: SimulationParameters = Field(default_factory=SimulationParameters)
    runs: int = Field(default=100, ge=1, le=1000)
    seed: int = 42
    targets: list[SamplingTarget] = Field(min_length=1, max_length=20)
    quantiles: list[float] = Field(default=[0.05, 0.5, 0.95], min_length=1, max_length=10)
    failure_policy: Literal["fail_fast", "keep_partial"] = "keep_partial"

    @model_validator(mode="after")
    def check_quantiles(self) -> SensitivityRequest:
        if any(value < 0 or value > 1 for value in self.quantiles):
            raise ValueError("quantiles must be between 0 and 1")
        return self


class SensitivityResult(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    model_hash: str
    config_hash: str
    seed: int
    status: Literal["done", "partial", "error"]
    successful_runs: int
    failed_runs: int
    summary: dict[str, Any]
    failures: list[ScenarioRun]


class CalibrationTarget(ContractModel):
    name: str
    initial: float
    low: float
    high: float

    @model_validator(mode="after")
    def check_bounds(self) -> CalibrationTarget:
        if self.low >= self.high or not self.low <= self.initial <= self.high:
            raise ValueError("calibration requires low <= initial <= high and low < high")
        return self


class CalibrationRequest(ContractModel):
    model: ModelDocument
    parameters: SimulationParameters = Field(default_factory=SimulationParameters)
    targets: list[CalibrationTarget] = Field(min_length=1, max_length=20)
    time: list[float] = Field(min_length=2, max_length=10000)
    observations: dict[str, list[float]] = Field(min_length=1, max_length=100)
    weights: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_observations(self) -> CalibrationRequest:
        if any(right <= left for left, right in zip(self.time, self.time[1:], strict=False)):
            raise ValueError("observation timestamps must be strictly increasing")
        for name, values in self.observations.items():
            if len(values) != len(self.time):
                raise ValueError(f"observations {name} must match time length")
        return self


class CalibrationResult(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    status: Literal["done", "error"]
    fitted_parameters: dict[str, float]
    time: list[float]
    observations: dict[str, list[float]]
    predictions: dict[str, list[float]]
    residuals: dict[str, list[float]]
    metrics: dict[str, Any]
    success: bool
    message: str
    evaluations: int
    fitted_model: ModelDocument
