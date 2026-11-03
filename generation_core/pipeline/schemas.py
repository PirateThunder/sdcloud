from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
        validate_default=True,
    )


class VariableType(StrEnum):
    STOCK = "stock"
    FLOW = "flow"
    AUXILIARY = "auxiliary"
    CONSTANT = "constant"


NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class LiteralExpression(ContractModel):
    op: Literal["lit"]
    value: float | bool


class ReferenceExpression(ContractModel):
    op: Literal["ref"]
    name: str = Field(pattern=NAME_PATTERN, max_length=100)


class TimeExpression(ContractModel):
    op: Literal["time"]


class UnaryExpression(ContractModel):
    op: Literal["neg", "pos", "not"]
    arg: Expression


class BinaryExpression(ContractModel):
    op: Literal["add", "sub", "mul", "div", "pow", "mod"]
    args: tuple[Expression, Expression]

    @model_validator(mode="before")
    @classmethod
    def fold_nary_operations(cls, value):
        if not isinstance(value, dict):
            return value
        args = value.get("args")
        if value.get("op") not in {"add", "mul"} or not isinstance(args, list) or len(args) <= 2:
            return value
        folded = args[0]
        for arg in args[1:-1]:
            folded = {"op": value["op"], "args": [folded, arg]}
        return {"op": value["op"], "args": [folded, args[-1]]}


class CompareExpression(ContractModel):
    op: Literal["lt", "le", "gt", "ge", "eq", "ne"]
    args: tuple[Expression, Expression]


class BooleanExpression(ContractModel):
    op: Literal["and", "or"]
    args: list[Expression] = Field(min_length=2, max_length=100)


class CallExpression(ContractModel):
    op: Literal["call"]
    name: str = Field(pattern=NAME_PATTERN, max_length=50)
    args: list[Expression] = Field(default_factory=list, max_length=20)


class LookupExpression(ContractModel):
    op: Literal["lookup"]
    table: str = Field(pattern=NAME_PATTERN, max_length=100)
    arg: Expression


class IfExpression(ContractModel):
    op: Literal["if"]
    condition: Expression
    then: Expression
    otherwise: Expression


class IndexedExpression(ContractModel):
    op: Literal["index"]
    name: str = Field(pattern=NAME_PATTERN, max_length=100)
    indices: dict[str, str] = Field(min_length=1, max_length=8)


class ArrayExpression(ContractModel):
    op: Literal["array"]
    values: list[Expression] = Field(min_length=1, max_length=10000)
    shape: list[int] | None = Field(default=None, max_length=8)


Expression = Annotated[
    LiteralExpression
    | ReferenceExpression
    | TimeExpression
    | UnaryExpression
    | BinaryExpression
    | CompareExpression
    | BooleanExpression
    | CallExpression
    | LookupExpression
    | IfExpression
    | IndexedExpression
    | ArrayExpression,
    Field(discriminator="op"),
]


for _expression_type in (
    UnaryExpression,
    BinaryExpression,
    CompareExpression,
    BooleanExpression,
    CallExpression,
    LookupExpression,
    IfExpression,
    ArrayExpression,
):
    _expression_type.model_rebuild()


class Bounds(ContractModel):
    min: float | None = None
    max: float | None = None
    on_violation: Literal["error", "warn"] = "error"

    @model_validator(mode="after")
    def check_bounds(self) -> Bounds:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("bounds min must not exceed max")
        return self


class FlowEndpoint(ContractModel):
    kind: Literal["stock", "cloud"]
    id: str = Field(pattern=NAME_PATTERN, max_length=120)


class VariableBase(ContractModel):
    id: str = Field(pattern=NAME_PATTERN, max_length=100)
    label: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    units: dict[str, int] | None = None
    units_raw: str | None = Field(default=None, max_length=200)
    bounds: Bounds | None = None
    subscripts: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def normalize_units(self) -> VariableBase:
        if self.label is None:
            self.label = self.id
        if self.units is not None:
            self.units = {name: power for name, power in self.units.items() if power}
        return self

    @property
    def name(self) -> str:
        return self.id

    @property
    def type(self) -> VariableType:
        return VariableType(self.kind)


class StockVariable(VariableBase):
    kind: Literal["stock"]
    initial: Expression
    derivative: Expression | None = None
    allow_isolated: bool = False


class FlowVariable(VariableBase):
    kind: Literal["flow"]
    expression: Expression
    source: FlowEndpoint | None = None
    target: FlowEndpoint | None = None
    topology_status: Literal["declared", "inferred", "missing"] = "declared"


class AuxiliaryVariable(VariableBase):
    kind: Literal["auxiliary"]
    expression: Expression


class ConstantVariable(VariableBase):
    kind: Literal["constant"]
    expression: Expression
    exogenous: bool = False


SDVariable = Annotated[
    StockVariable | FlowVariable | AuxiliaryVariable | ConstantVariable,
    Field(discriminator="kind"),
]


class LookupTable(ContractModel):
    id: str = Field(pattern=NAME_PATTERN, max_length=100)
    label: str | None = Field(default=None, max_length=200)
    points: list[tuple[float, float]] = Field(min_length=2, max_length=1000)
    x_units: dict[str, int] | None = None
    y_units: dict[str, int] | None = None
    interpolation: Literal["linear"] = "linear"
    extrapolation: Literal["clamp", "linear", "error"] = "clamp"

    @model_validator(mode="after")
    def check_points(self) -> LookupTable:
        xs = [point[0] for point in self.points]
        if any(right <= left for left, right in zip(xs, xs[1:], strict=False)):
            raise ValueError("lookup x values must be strictly increasing")
        return self


class Dimension(ContractModel):
    id: str = Field(pattern=NAME_PATTERN, max_length=100)
    elements: list[str] = Field(min_length=1, max_length=100)


class Assumption(ContractModel):
    path: str = Field(min_length=1, max_length=300)
    value: str = Field(min_length=1, max_length=2000)
    source: Literal["user", "archetype", "llm_inferred", "imported", "migration"]
    rationale: str = Field(min_length=1, max_length=2000)
    requires_confirmation: bool = False


class Provenance(ContractModel):
    kind: Literal[
        "text_generation", "vensim_import", "xmile_import", "migration", "calibration"
    ] = "text_generation"
    source_name: str | None = Field(default=None, max_length=300)
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    parser_version: str | None = Field(default=None, max_length=100)


class ValidationIssue(ContractModel):
    code: str = Field(min_length=1, max_length=100)
    severity: Literal["error", "warning"]
    path: str = Field(min_length=1, max_length=300)
    message: str = Field(min_length=1, max_length=2000)
    hint: str | None = Field(default=None, max_length=1000)


class CapabilityReport(ContractModel):
    supported: dict[str, bool] = Field(default_factory=dict)
    reasons: dict[str, list[str]] = Field(default_factory=dict)


class ValidationReport(ContractModel):
    status: Literal["passed", "passed_with_warnings", "failed"]
    issues: list[ValidationIssue] = Field(default_factory=list)
    capabilities: CapabilityReport = Field(default_factory=CapabilityReport)

    @property
    def valid(self) -> bool:
        return self.status != "failed"


class CLDNode(ContractModel):
    id: str = Field(pattern=NAME_PATTERN, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    type: VariableType | Literal["variable"] = "variable"


class CLDEdge(ContractModel):
    source: str = Field(pattern=NAME_PATTERN)
    target: str = Field(pattern=NAME_PATTERN)
    polarity: Literal["+", "-", "unknown"]
    label: str | None = Field(default=None, max_length=200)


class FeedbackLoop(ContractModel):
    nodes: list[str]
    length: int = Field(ge=1)
    polarity: Literal["+", "-"]
    type: Literal["reinforcing", "balancing"]


class GraphValidation(ContractModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)
    feedback_loops: list[FeedbackLoop] = Field(default_factory=list)
    metrics: dict[str, int | float | str | bool] = Field(default_factory=dict)


class CLDData(ContractModel):
    nodes: list[CLDNode]
    edges: list[CLDEdge]
    validation: GraphValidation


class SFDNode(ContractModel):
    id: str = Field(pattern=NAME_PATTERN, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    type: VariableType | Literal["cloud"]


class SFDEdge(ContractModel):
    source: str = Field(pattern=NAME_PATTERN, max_length=120)
    target: str = Field(pattern=NAME_PATTERN, max_length=120)
    type: Literal["flow", "link"] = "link"
    label: str | None = Field(default=None, max_length=200)


class SFDData(ContractModel):
    nodes: list[SFDNode]
    edges: list[SFDEdge]
    validation: GraphValidation


class ModelBrief(ContractModel):
    goal: str = Field(min_length=1, max_length=2000)
    boundaries: list[str] = Field(default_factory=list, max_length=30)
    time_horizon: str = Field(min_length=1, max_length=200)
    time_unit: str = Field(min_length=1, max_length=100)
    aggregation: Literal["high", "medium", "low"] = "medium"
    stocks: list[str] = Field(min_length=1, max_length=50)
    flows: list[str] = Field(default_factory=list, max_length=100)
    exogenous_inputs: list[str] = Field(default_factory=list, max_length=50)
    expected_feedback_loops: list[str] = Field(default_factory=list, max_length=30)


class TimeSettings(ContractModel):
    unit: str = Field(min_length=1, max_length=100)
    initial_time: float = 0.0
    final_time: float = 100.0
    time_step: float = Field(default=0.25, gt=0.0)
    saveper: float = Field(default=0.25, gt=0.0)

    @model_validator(mode="after")
    def check_horizon(self) -> TimeSettings:
        if self.final_time <= self.initial_time:
            raise ValueError("final_time must be greater than initial_time")
        return self


def _empty_cld() -> CLDData:
    return CLDData(nodes=[], edges=[], validation=GraphValidation(valid=False))


def _empty_sfd() -> SFDData:
    return SFDData(nodes=[], edges=[], validation=GraphValidation(valid=False))


class ModelDocument(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    id: str = Field(default="model", pattern=NAME_PATTERN, max_length=100)
    name: str = Field(default="System dynamics model", min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=20000)
    time: TimeSettings
    variables: list[SDVariable] = Field(min_length=1, max_length=200)
    tables: list[LookupTable] = Field(default_factory=list, max_length=100)
    dimensions: list[Dimension] = Field(default_factory=list, max_length=20)
    assumptions: list[Assumption] = Field(default_factory=list, max_length=500)
    provenance: Provenance = Field(default_factory=Provenance)
    brief: ModelBrief | None = None
    pattern_id: str | None = Field(default=None, max_length=100)
    repair_attempts: int = Field(default=0, ge=0, le=10)
    capabilities: list[str] = Field(default_factory=list)
    validation: ValidationReport = Field(default_factory=lambda: ValidationReport(status="failed"))
    cld_data: CLDData = Field(default_factory=_empty_cld)
    sfd_data: SFDData = Field(default_factory=_empty_sfd)
    artifacts: dict[str, str] = Field(default_factory=dict)
    assistant_text: str | None = None
    warnings: list[str] = Field(default_factory=list)
    generation_log: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy(cls, value):
        if isinstance(value, dict) and value.get("schema_version") == "1.0":
            from .migration import migrate_v1

            return migrate_v1(value)
        return value

    def model_hash(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "time": self.time.model_dump(mode="json"),
            "variables": [item.model_dump(mode="json") for item in self.variables],
            "tables": [item.model_dump(mode="json") for item in self.tables],
            "dimensions": [item.model_dump(mode="json") for item in self.dimensions],
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()


class ChatMessage(ContractModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10000)


class GenerationRequest(ContractModel):
    description: str = Field(min_length=1, max_length=20000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)
    base_model: ModelDocument | None = None
    assumption_policy: Literal["allow_inferred", "require_explicit"] = "allow_inferred"


class ConversationRequest(GenerationRequest):
    pass


class MessageDecision(ContractModel):
    action: Literal["answer", "clarify", "generate", "update"]
    assistant_text: str = Field(min_length=1, max_length=20000)


class ConversationResponse(ContractModel):
    kind: Literal["answer", "clarification", "model"]
    assistant_text: str = Field(min_length=1, max_length=20000)
    model: ModelDocument | None = None

    @model_validator(mode="after")
    def check_model(self) -> ConversationResponse:
        if (self.kind == "model") != (self.model is not None):
            raise ValueError("model response must contain exactly one model")
        return self


class TimeSeries(ContractModel):
    points: list[tuple[float, float]] = Field(min_length=2, max_length=10000)
    interpolation: Literal["linear"] = "linear"
    extrapolation: Literal["clamp", "error"] = "error"

    @model_validator(mode="after")
    def check_points(self) -> TimeSeries:
        times = [point[0] for point in self.points]
        if any(right <= left for left, right in zip(times, times[1:], strict=False)):
            raise ValueError("time series timestamps must be strictly increasing")
        return self


class SimulationParameters(ContractModel):
    engine: Literal["auto", "pysd", "scipy"] = "auto"
    integration_method: Literal["euler", "rk4", "rk45", "dop853", "lsoda", "bdf"] = "euler"
    initial_time: float | None = None
    final_time: float | None = None
    time_step: float | None = Field(default=None, gt=0.0)
    saveper: float | None = Field(default=None, gt=0.0)
    parameters: dict[str, float] = Field(default_factory=dict, max_length=100)
    stock_initial: dict[str, float] = Field(default_factory=dict, max_length=100)
    input_series: dict[str, TimeSeries] = Field(default_factory=dict, max_length=20)
    rtol: float = Field(default=1e-6, gt=0.0)
    atol: float = Field(default=1e-9, gt=0.0)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_parameters(cls, value):
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        for old, new in (("time_start", "initial_time"), ("time_end", "final_time")):
            if old in migrated and new not in migrated:
                migrated[new] = migrated[old]
            migrated.pop(old, None)
        if "custom_params" in migrated and "parameters" not in migrated:
            migrated["parameters"] = migrated["custom_params"]
        migrated.pop("custom_params", None)
        if migrated.get("integration_method") == "rkf45":
            migrated["integration_method"] = "rk45"
        return migrated

    @model_validator(mode="after")
    def check_parameter_names(self) -> SimulationParameters:
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


class SimulationResult(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    model_id: str
    model_hash: str
    time: list[float]
    variables: dict[str, list[float]]
    requested_engine: Literal["auto", "pysd", "scipy"]
    engine: Literal["pysd", "scipy"]
    requested_method: str
    integration_method: str
    time_step: float
    saveper: float
    rtol: float | None = None
    atol: float | None = None
    fallback_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, int | float | str | bool] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
