from __future__ import annotations

import json
import math
import re
from collections import Counter

from pydantic import TypeAdapter, ValidationError

from .exceptions import ModelValidationError
from .expression_parser import normalize_expression
from .ir import binary, call, dependencies, lit, ref, time, unary
from .schemas import (
    Assumption,
    AuxiliaryVariable,
    BooleanExpression,
    Bounds,
    CompareExpression,
    ComponentParameter,
    ComponentSpec,
    ConstantVariable,
    DelaySpec,
    Expression,
    FirstOrderSpec,
    FlowEndpoint,
    FlowVariable,
    ModelDocument,
    OdeStockSpec,
    QueueSpec,
    ScheduledFlowSpec,
    SDVariable,
    StockVariable,
    TimeSettings,
)
from .units import canonical_units, combine
from .validation import ModelValidator, validate_model


def _rate_units(units: dict[str, int], time_unit: str) -> dict[str, int]:
    return combine(canonical_units(units), {time_unit: -1})


def _coefficient_units(
    source_units: dict[str, int], target_units: dict[str, int], time_unit: str
) -> dict[str, int]:
    return combine(combine(canonical_units(target_units), canonical_units(source_units), -1), {time_unit: -1})


def _endpoint(value: str) -> FlowEndpoint:
    if value.startswith("cloud:"):
        return FlowEndpoint(kind="cloud", id=value.removeprefix("cloud:"))
    return FlowEndpoint(kind="stock", id=value)


def _stock(name: str, initial: float, units: dict[str, int], *, nonnegative: bool = False) -> StockVariable:
    return StockVariable(
        id=name,
        kind="stock",
        initial=lit(initial),
        units=canonical_units(units),
        bounds=Bounds(min=0) if nonnegative else None,
    )


def _constant(name: str, value: float, units: dict[str, int] | None) -> ConstantVariable:
    return ConstantVariable(id=name, kind="constant", expression=lit(value), units=units)


def _flow(
    name: str,
    expression: Expression,
    source: FlowEndpoint,
    target: FlowEndpoint,
    units: dict[str, int],
    time_unit: str,
) -> FlowVariable:
    return FlowVariable(
        id=name,
        kind="flow",
        expression=expression,
        source=source,
        target=target,
        units=_rate_units(units, time_unit),
    )


def _sum(expressions: list[Expression]) -> Expression:
    result = expressions[0]
    for expression in expressions[1:]:
        result = binary("add", result, expression)
    return result


class _ComponentBuilder:
    def __init__(self, settings: TimeSettings) -> None:
        self.settings = settings
        self.variables: list[SDVariable] = []

    def scheduled_rate(
        self,
        name: str,
        rate: float,
        units: dict[str, int],
        *,
        start: float = 0,
        end: float | None = None,
    ) -> Expression:
        rate_id = f"{name}_rate"
        self.variables.append(_constant(rate_id, rate, _rate_units(units, self.settings.unit)))
        if end is None and start == 0:
            return ref(rate_id)
        start_id = f"{name}_start_time"
        self.variables.append(_constant(start_id, start, {self.settings.unit: 1}))
        condition: Expression = CompareExpression(op="ge", args=(time(), ref(start_id)))
        if end is not None:
            end_id = f"{name}_end_time"
            self.variables.append(_constant(end_id, end, {self.settings.unit: 1}))
            condition = BooleanExpression(
                op="and",
                args=[condition, CompareExpression(op="lt", args=(time(), ref(end_id)))],
            )
        return call(
            "if_then_else",
            condition,
            ref(rate_id),
            binary("mul", lit(0), ref(rate_id)),
        )

    def first_order(self, spec: FirstOrderSpec) -> None:
        target_units = spec.target_units or spec.source_units
        self.variables.append(_stock(spec.source, spec.initial_source, spec.source_units))
        target = _endpoint(spec.target)
        if target.kind == "stock":
            self.variables.append(_stock(target.id, spec.initial_target, target_units))
        if spec.time_constant is not None:
            constant_id = f"{spec.flow}_time_constant"
            self.variables.append(
                _constant(constant_id, spec.time_constant, {self.settings.unit: 1})
            )
            expression = binary("div", ref(spec.source), ref(constant_id))
        else:
            constant_id = f"{spec.flow}_coefficient"
            self.variables.append(
                _constant(
                    constant_id,
                    spec.coefficient,
                    _coefficient_units(spec.source_units, target_units, self.settings.unit),
                )
            )
            expression = binary("mul", ref(spec.source), ref(constant_id))
        self.variables.append(
            _flow(
                spec.flow,
                expression,
                FlowEndpoint(kind="stock", id=spec.source),
                target,
                spec.source_units,
                self.settings.unit,
            )
        )

    def conditional_inflow(self, spec) -> None:
        self.variables.append(_stock(spec.stock, spec.initial, spec.units))
        self.variables.append(
            _flow(
                spec.inflow,
                self.scheduled_rate(
                    spec.inflow,
                    spec.rate,
                    spec.units,
                    start=spec.start_time,
                    end=spec.end_time,
                ),
                FlowEndpoint(kind="cloud", id=f"{spec.inflow}_source"),
                FlowEndpoint(kind="stock", id=spec.stock),
                spec.units,
                self.settings.unit,
            )
        )
        coefficient_id = f"{spec.outflow}_coefficient"
        self.variables.append(
            _constant(coefficient_id, spec.elimination_rate, {self.settings.unit: -1})
        )
        self.variables.append(
            _flow(
                spec.outflow,
                binary("mul", ref(spec.stock), ref(coefficient_id)),
                FlowEndpoint(kind="stock", id=spec.stock),
                FlowEndpoint(kind="cloud", id=f"{spec.outflow}_sink"),
                spec.units,
                self.settings.unit,
            )
        )

    def queue(self, spec: QueueSpec) -> None:
        self.variables.append(_stock(spec.stock, spec.initial, spec.units, nonnegative=True))
        self.variables.append(
            _flow(
                spec.arrivals,
                self.scheduled_rate(
                    spec.arrivals,
                    spec.arrival_rate,
                    spec.units,
                    start=spec.arrival_start_time,
                    end=spec.arrival_end_time,
                ),
                FlowEndpoint(kind="cloud", id=f"{spec.arrivals}_source"),
                FlowEndpoint(kind="stock", id=spec.stock),
                spec.units,
                self.settings.unit,
            )
        )
        service_time_id = f"{spec.service}_time"
        capacity_id = f"{spec.service}_capacity"
        self.variables.extend(
            [
                _constant(service_time_id, spec.service_time, {self.settings.unit: 1}),
                _constant(capacity_id, spec.max_service, _rate_units(spec.units, self.settings.unit)),
            ]
        )
        available = call("max", ref(spec.stock), binary("mul", lit(0), ref(spec.stock)))
        expression = call(
            "min",
            binary("div", available, ref(service_time_id)),
            ref(capacity_id),
        )
        self.variables.append(
            _flow(
                spec.service,
                expression,
                FlowEndpoint(kind="stock", id=spec.stock),
                FlowEndpoint(kind="cloud", id=f"{spec.service}_sink"),
                spec.units,
                self.settings.unit,
            )
        )

    def scheduled_flow(self, spec: ScheduledFlowSpec) -> None:
        source = _endpoint(spec.source)
        target = _endpoint(spec.target)
        units = spec.source_units if source.kind == "stock" else spec.target_units
        if units is None:
            raise ModelValidationError("scheduled_flow requires units for its stock")
        if source.kind == "stock":
            self.variables.append(_stock(source.id, spec.initial_source, units))
        if target.kind == "stock":
            self.variables.append(_stock(target.id, spec.initial_target, units))
        before_id = f"{spec.flow}_rate_before"
        after_id = f"{spec.flow}_rate_after"
        change_id = f"{spec.flow}_change_time"
        flow_units = _rate_units(units, self.settings.unit)
        self.variables.extend(
            [
                _constant(before_id, spec.rate, flow_units),
                _constant(after_id, spec.rate_after, flow_units),
                _constant(change_id, spec.change_time, {self.settings.unit: 1}),
            ]
        )
        expression = call(
            "if_then_else",
            CompareExpression(op="ge", args=(time(), ref(change_id))),
            ref(after_id),
            ref(before_id),
        )
        self.variables.append(
            _flow(spec.flow, expression, source, target, units, self.settings.unit)
        )

    def delay(self, spec: DelaySpec) -> None:
        self.variables.append(_stock(spec.stock, spec.initial_stock, spec.stock_units))
        flow_units = _rate_units(spec.stock_units, self.settings.unit)
        input_id = f"{spec.inflow}_input"
        base_id = f"{input_id}_base"
        self.variables.append(_constant(base_id, spec.input_rate, flow_units))
        requested: Expression = ref(base_id)
        if spec.input_rate_after is not None:
            change_id = f"{input_id}_change"
            change_time_id = f"{input_id}_change_time"
            self.variables.extend(
                [
                    _constant(change_id, spec.input_rate_after - spec.input_rate, flow_units),
                    _constant(change_time_id, spec.rate_change_time, {self.settings.unit: 1}),
                ]
            )
            requested = binary(
                "add", ref(base_id), call("step", ref(change_id), ref(change_time_id))
            )
        self.variables.append(
            AuxiliaryVariable(id=input_id, kind="auxiliary", expression=requested, units=flow_units)
        )
        delay_id = f"{spec.inflow}_delay_time"
        initial_rate_id = f"{spec.inflow}_initial_rate"
        self.variables.extend(
            [
                _constant(delay_id, spec.delay_time, {self.settings.unit: 1}),
                _constant(initial_rate_id, spec.initial_delayed_rate, flow_units),
            ]
        )
        delayed = call("delay3i", ref(input_id), ref(delay_id), ref(initial_rate_id))
        self.variables.append(
            _flow(
                spec.inflow,
                delayed,
                FlowEndpoint(kind="cloud", id=f"{spec.inflow}_source"),
                FlowEndpoint(kind="stock", id=spec.stock),
                spec.stock_units,
                self.settings.unit,
            )
        )
        if spec.consumption_time is None:
            consumption = binary("mul", lit(0), ref(spec.inflow))
        else:
            consumption_id = f"{spec.outflow}_time_constant"
            self.variables.append(
                _constant(consumption_id, spec.consumption_time, {self.settings.unit: 1})
            )
            consumption = binary("div", ref(spec.stock), ref(consumption_id))
        self.variables.append(
            _flow(
                spec.outflow,
                consumption,
                FlowEndpoint(kind="stock", id=spec.stock),
                FlowEndpoint(kind="cloud", id=f"{spec.outflow}_sink"),
                spec.stock_units,
                self.settings.unit,
            )
        )

    def _dimensioned_literals(
        self, expression: Expression, stock: str, term_index: int
    ) -> Expression:
        probe = ModelDocument(
            name="Component literal units",
            description="Dimensional literal inference",
            time=self.settings,
            variables=self.variables,
        )
        validator = ModelValidator(probe)
        path = f"components.{stock}.terms[{term_index}]"
        literal_index = 0

        def visit(node: Expression) -> Expression:
            nonlocal literal_index
            if node.op in {"add", "sub", "mul", "div", "pow", "mod", "lt", "le", "gt", "ge", "eq", "ne"}:
                left = visit(node.args[0])
                right = visit(node.args[1])
                if node.op in {"add", "sub"}:
                    operands = [left, right]
                    for index, other in ((0, right), (1, left)):
                        candidate = operands[index]
                        if candidate.op != "lit" or isinstance(candidate.value, bool):
                            continue
                        units = validator._units(other, path)
                        if not isinstance(units, dict):
                            continue
                        literal_index += 1
                        constant_id = f"{stock}_term_{term_index}_literal_{literal_index}"
                        constant = _constant(constant_id, candidate.value, units)
                        self.variables.append(constant)
                        validator.variables[constant_id] = constant
                        operands[index] = ref(constant_id)
                    left, right = operands
                return node.model_copy(update={"args": (left, right)})
            if node.op in {"neg", "pos", "not"}:
                return node.model_copy(update={"arg": visit(node.arg)})
            if node.op == "call":
                return node.model_copy(
                    update={"args": [visit(argument) for argument in node.args]}
                )
            if node.op == "if":
                return node.model_copy(
                    update={
                        "condition": visit(node.condition),
                        "then": visit(node.then),
                        "otherwise": visit(node.otherwise),
                    }
                )
            return node

        return visit(expression)

    def polynomial_odes(self, specs: list[OdeStockSpec]) -> None:
        coefficient_names = {
            term.coefficient
            for spec in specs
            for term in spec.terms
            if isinstance(term.coefficient, str)
        }
        parameter_roles: dict[str, ComponentParameter] = {}
        for spec in specs:
            self.variables.append(_stock(spec.stock, spec.initial, spec.units))
            for parameter in spec.parameters:
                if parameter.id in parameter_roles:
                    raise ModelValidationError(
                        f"component parameter {parameter.id} is declared more than once"
                    )
                parameter_roles[parameter.id] = parameter
                units = parameter.units
                if parameter.id in coefficient_names and units == {}:
                    units = None
                if units is None:
                    if parameter.role == "threshold":
                        units = canonical_units(spec.units)
                    elif parameter.id not in coefficient_names:
                        units = {} if parameter.role == "scale" else {self.settings.unit: -1}
                self.variables.append(_constant(parameter.id, parameter.value, units))
        for spec in specs:
            terms = []
            derivative_units = _rate_units(spec.units, self.settings.unit)
            for index, term in enumerate(spec.terms, start=1):
                expression = TypeAdapter(Expression).validate_python(
                    normalize_expression(term.expression)
                )
                expression = self._dimensioned_literals(expression, spec.stock, index)
                if isinstance(term.coefficient, str) and term.coefficient in dependencies(expression):
                    raise ModelValidationError(
                        f"components.{spec.stock}.terms[{index}]: coefficient "
                        f"{term.coefficient} cannot occur inside its own expression"
                    )
                probe = ModelDocument(
                    name="Component units",
                    description="Typed component unit inference",
                    time=self.settings,
                    variables=self.variables,
                )
                validator = ModelValidator(probe)
                expression_units = validator._units(expression, f"components.{spec.stock}")
                if expression_units is None or not isinstance(expression_units, dict) or validator.issues:
                    details = "; ".join(issue.message for issue in validator.issues)
                    raise ModelValidationError(
                        f"components.{spec.stock}.terms[{index}] has unknown or incompatible "
                        f"expression units: {details or term.expression}"
                    )
                units = combine(derivative_units, expression_units, -1)
                if isinstance(term.coefficient, str):
                    coefficient_id = term.coefficient
                    parameter = next(
                        (item for item in self.variables if item.id == coefficient_id), None
                    )
                    if parameter is None or parameter.kind != "constant":
                        raise ModelValidationError(
                            f"components.{spec.stock} references undeclared coefficient {coefficient_id}"
                        )
                    if parameter.units not in (None, {}) and parameter.units != units:
                        role = getattr(parameter_roles.get(coefficient_id), "role", None)
                        hint = (
                            "A threshold cannot be reused as a rate coefficient with these units. "
                            "Use a numeric coefficient preserving the product from the description, "
                            "or role='scale' with units=null."
                            if role == "threshold"
                            else "Do not reuse a rate for additive terms with different units. "
                            "Use a numeric coefficient preserving the product from the description, "
                            "or a separate coefficient with units=null."
                        )
                        hint += (
                            " If an outer coefficient multiplies a sum, keep that sum in one "
                            "expression with named threshold/scale references instead of "
                            "splitting it into incompatible terms."
                        )
                        raise ModelValidationError(
                            f"coefficient {coefficient_id} has units {parameter.units}; "
                            f"equation requires {units}. {hint}"
                        )
                    if parameter.units in (None, {}):
                        self.variables = [
                            item.model_copy(update={"units": units})
                            if item.id == coefficient_id
                            else item
                            for item in self.variables
                        ]
                else:
                    coefficient_id = f"{spec.stock}_term_{index}_coefficient"
                    self.variables.append(_constant(coefficient_id, term.coefficient, units))
                if term.coefficient == 1 and expression_units == derivative_units:
                    value = expression
                else:
                    value = binary("mul", ref(coefficient_id), expression)
                terms.append(unary("neg", value) if term.sign == -1 else value)
            self.variables = [
                item.model_copy(update={"derivative": _sum(terms)})
                if item.id == spec.stock and item.kind == "stock"
                else item
                for item in self.variables
            ]
        used_parameters = {
            name
            for variable in self.variables
            for field in ("expression", "derivative")
            if (expression := getattr(variable, field, None)) is not None
            for name in dependencies(expression)
        }
        unused = set(parameter_roles) - used_parameters
        if unused:
            raise ModelValidationError(
                f"unused ODE parameters must be removed or used in terms: {sorted(unused)}"
            )


def normalize_component_payload(response: dict) -> dict:
    if not isinstance(response, dict) or not isinstance(response.get("components"), list):
        raise ModelValidationError("component plan must contain a components list")
    assumptions = response.get("assumptions", [])
    if not isinstance(assumptions, list):
        raise ModelValidationError("component plan assumptions must be a list")
    components = []
    for raw in response["components"]:
        if not isinstance(raw, dict):
            components.append(raw)
            continue
        item = dict(raw)
        annotation_id = item.pop("id", None)
        kind = item.get("kind")
        if kind in {"first_order", "scheduled_flow"} and not item.get("flow"):
            item["flow"] = annotation_id
        if (
            kind == "delay"
            and item.get("input_rate") is None
            and isinstance(item.get("rate"), int | float)
            and not isinstance(item.get("rate"), bool)
        ):
            item["input_rate"] = item.pop("rate")
        if kind == "first_order":
            parameters = item.get("parameters")
            if isinstance(parameters, list) and item.get("coefficient") is None:
                coefficients = []
                time_constants = []
                for parameter in parameters:
                    if not isinstance(parameter, dict) or not isinstance(
                        parameter.get("value"), int | float
                    ):
                        continue
                    units = parameter.get("units") or {}
                    if set(units) <= {item.get("time_unit")} and units.get(
                        item.get("time_unit"), 0
                    ) > 0:
                        time_constants.append(parameter["value"])
                    else:
                        coefficients.append(parameter["value"])
                if len(coefficients) == 1:
                    item["coefficient"] = coefficients[0]
                    item.pop("parameters", None)
                elif len(time_constants) == 1 and item.get("time_constant") is None:
                    item["time_constant"] = time_constants[0]
                    item.pop("parameters", None)
            if item.get("coefficient") is None and item.get("time_constant") is None:
                matching = [
                    assumption.get("value")
                    for assumption in assumptions
                    if isinstance(assumption, dict)
                    and assumption.get("variable") == item.get("flow")
                    and isinstance(assumption.get("value"), int | float)
                    and not isinstance(assumption.get("value"), bool)
                ]
                if len(matching) == 1:
                    item["coefficient"] = matching[0]
        if kind == "polynomial_ode":
            parameters = item.get("parameters", [])
            for term in item.get("terms", []):
                if not isinstance(term, dict) or not isinstance(term.get("coefficient"), str):
                    continue
                match = re.fullmatch(
                    r"(?:rate|coefficient)_([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
                    term["coefficient"],
                )
                if match is None:
                    continue
                coefficient_id = term["coefficient"]
                value = float(match.group(1))
                term["coefficient"] = value
                if isinstance(parameters, list):
                    item["parameters"] = [
                        parameter
                        for parameter in parameters
                        if not isinstance(parameter, dict)
                        or parameter.get("id") != coefficient_id
                        or parameter.get("value") != value
                    ]
        components.append(item)
    unique_components = []
    seen = set()
    for item in components:
        signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        unique_components.append(item)
    components = unique_components
    if len(components) == 2:
        delay = next((item for item in components if item.get("kind") == "delay"), None)
        transfer = next((item for item in components if item.get("kind") == "first_order"), None)
        if (
            delay is not None
            and transfer is not None
            and transfer.get("source") == delay.get("stock")
            and transfer.get("flow") == delay.get("outflow")
            and isinstance(transfer.get("target"), str)
            and transfer["target"].startswith("cloud:")
            and transfer.get("coefficient") is None
            and transfer.get("time_constant") == delay.get("consumption_time")
            and transfer.get("source_units") == delay.get("stock_units")
        ):
            components = [delay]
    if len(components) == 2:
        delay = next((item for item in components if item.get("kind") == "delay"), None)
        transfer = next((item for item in components if item.get("kind") == "first_order"), None)
        if (
            delay is not None
            and transfer is not None
            and transfer.get("source") == delay.get("outflow")
            and isinstance(transfer.get("target"), str)
            and not transfer["target"].startswith("cloud:")
            and transfer.get("coefficient") is None
            and delay.get("consumption_time") is not None
            and transfer.get("time_constant") == delay["consumption_time"]
            and transfer.get("target_units") is not None
            and transfer["target_units"] == delay["stock_units"]
        ):
            components = [
                {
                    **delay,
                    "stock": transfer["target"],
                    "initial_stock": transfer["initial_target"],
                    "outflow": transfer["flow"],
                }
            ]
    return {
        **response,
        "components": components,
        "assumptions": [
            item
            for item in assumptions
            if isinstance(item, dict) and item.get("path") and item.get("rationale")
        ],
    }


def _merge_stocks(variables: list[SDVariable]) -> list[SDVariable]:
    result: list[SDVariable] = []
    stocks: dict[str, StockVariable] = {}
    for variable in variables:
        if variable.kind != "stock" or variable.id not in stocks:
            result.append(variable)
            if variable.kind == "stock":
                stocks[variable.id] = variable
            continue
        previous = stocks[variable.id]
        if (
            previous.initial != variable.initial
            or previous.units != variable.units
            or previous.derivative != variable.derivative
            or (
                previous.bounds is not None
                and variable.bounds is not None
                and previous.bounds != variable.bounds
            )
        ):
            raise ModelValidationError(
                f"component stock {variable.id} has conflicting initial, units, derivative or bounds"
            )
        if previous.bounds is None and variable.bounds is not None:
            replacement = previous.model_copy(update={"bounds": variable.bounds})
            result[result.index(previous)] = replacement
            stocks[variable.id] = replacement
    return result


def _duplicate_delay_consumption(delay: DelaySpec, transfer: FirstOrderSpec) -> bool:
    if transfer.source != delay.stock:
        return False
    if transfer.flow == delay.outflow:
        return True
    if delay.consumption_time is None:
        return False
    if transfer.time_constant is not None:
        return math.isclose(
            transfer.time_constant, delay.consumption_time, rel_tol=1e-9, abs_tol=1e-12
        )
    return transfer.coefficient is not None and math.isclose(
        transfer.coefficient,
        1 / delay.consumption_time,
        rel_tol=1e-9,
        abs_tol=1e-12,
    )


def _validate_component_composition(components: list[ComponentSpec]) -> None:
    delays = [item for item in components if isinstance(item, DelaySpec)]
    transfers = [item for item in components if isinstance(item, FirstOrderSpec)]
    for delay in delays:
        for transfer in transfers:
            if transfer.source == delay.outflow:
                raise ModelValidationError(
                    f"delay outflow {delay.outflow!r} cannot be reused as stock source "
                    f"in first_order {transfer.flow!r}; keep one delay and its terminal stock"
                )
            if _duplicate_delay_consumption(delay, transfer):
                raise ModelValidationError(
                    f"duplicate delay consumption: first_order {transfer.flow!r} drains "
                    f"{delay.stock!r} with the same flow or time constant; delay already "
                    "includes third-order transport and consumption. Remove the duplicate "
                    "first_order stage instead of adding another transport cascade."
                )


def normalize_inferred_time(settings: TimeSettings, description: str) -> TimeSettings:
    duration = settings.final_time - settings.initial_time
    step_is_explicit = re.search(
        r"time[\s_-]*step|шаг\s+(?:интегрирования|времени|модели)", description, re.IGNORECASE
    )
    saveper_is_explicit = re.search(r"saveper", description, re.IGNORECASE)
    steps = duration / settings.time_step
    if step_is_explicit is None and not math.isclose(
        steps, round(steps), rel_tol=1e-9, abs_tol=1e-9
    ):
        settings = settings.model_copy(update={"time_step": duration / math.ceil(steps)})
    ratio = settings.saveper / settings.time_step
    if saveper_is_explicit is None and not math.isclose(
        ratio, round(ratio), rel_tol=1e-9, abs_tol=1e-9
    ):
        settings = settings.model_copy(
            update={"saveper": settings.time_step * max(1, math.floor(ratio + 0.5))}
        )
    return settings


def build_components(
    components: list[ComponentSpec],
    settings: TimeSettings | None = None,
    assumptions: list[Assumption] | None = None,
) -> tuple[list[SDVariable], TimeSettings, list[Assumption]]:
    if not components:
        raise ModelValidationError("at least one typed component is required")
    try:
        components = TypeAdapter(list[ComponentSpec]).validate_python(components)
        _validate_component_composition(components)
        settings = settings or TimeSettings(unit=components[0].time_unit)
        mismatched = [item.kind for item in components if item.time_unit != settings.unit]
        if mismatched:
            raise ModelValidationError(
                f"component time_unit must match time.unit={settings.unit!r}: {mismatched}"
            )
        ratio = settings.saveper / settings.time_step
        if not math.isclose(ratio, round(ratio), rel_tol=1e-9, abs_tol=1e-9):
            raise ModelValidationError("time.saveper must be an integer multiple of time.time_step")
        steps = (settings.final_time - settings.initial_time) / settings.time_step
        if not math.isclose(steps, round(steps), rel_tol=1e-9, abs_tol=1e-9):
            raise ModelValidationError("time horizon must be an integer multiple of time.time_step")
        output_interval = max(1, math.ceil(steps / 9999))
        if output_interval > round(ratio):
            settings = settings.model_copy(
                update={"saveper": settings.time_step * output_interval}
            )
        ode_stocks = [item.stock for item in components if item.kind == "polynomial_ode"]
        if len(ode_stocks) != len(set(ode_stocks)):
            raise ModelValidationError("polynomial ODE stocks must be declared only once")
        builder = _ComponentBuilder(settings)
        for component in components:
            if component.kind == "first_order":
                builder.first_order(component)
            elif component.kind == "conditional_inflow":
                builder.conditional_inflow(component)
            elif component.kind == "queue":
                builder.queue(component)
            elif component.kind == "scheduled_flow":
                builder.scheduled_flow(component)
            elif component.kind == "delay":
                builder.delay(component)
        builder.polynomial_odes([item for item in components if item.kind == "polynomial_ode"])
        builder.variables = _merge_stocks(builder.variables)
        duplicates = [
            name for name, count in Counter(item.id for item in builder.variables).items() if count > 1
        ]
        if duplicates:
            raise ModelValidationError(f"component variable ids must be unique: {duplicates}")
        from .generation import _normalize_generated_variables

        variables = _normalize_generated_variables(builder.variables, settings.unit)
        document = ModelDocument(
            name="Typed component model",
            description="Model constructed from typed dynamic mechanisms",
            time=settings,
            variables=variables,
            assumptions=assumptions or [],
        )
        report = validate_model(document)
        errors = [item for item in report.issues if item.severity == "error"]
        if errors:
            raise ModelValidationError(
                "; ".join(
                    f"{item.code} at {item.path}: {item.message}" for item in errors[:10]
                )
            )
        return variables, settings, assumptions or []
    except ValidationError as exc:
        raise ModelValidationError(f"invalid typed components: {exc}") from exc
