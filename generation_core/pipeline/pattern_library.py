from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .codegen import expression_to_vensim
from .expression_parser import parse_expression
from .ir import binary, call, constant_number, lit, ref
from .schemas import (
    AuxiliaryVariable,
    ConstantVariable,
    FlowEndpoint,
    FlowVariable,
    ModelDocument,
    StockVariable,
    TimeSettings,
)
from .validation import finalize_model


@dataclass(frozen=True)
class Pattern:
    id: str
    description: str
    tags: tuple[str, ...]
    document: ModelDocument


def _expression(value):
    return lit(value) if isinstance(value, int | float) else value


def _stock(name: str, units: dict[str, int], initial):
    return StockVariable(id=name, kind="stock", initial=_expression(initial), units=units)


def _constant(name: str, units: dict[str, int], value):
    return ConstantVariable(id=name, kind="constant", expression=_expression(value), units=units)


def _endpoint(value: str) -> FlowEndpoint:
    if value.startswith("cloud:"):
        return FlowEndpoint(kind="cloud", id=value.split(":", 1)[1])
    return FlowEndpoint(kind="stock", id=value)


def _flow(name: str, units: dict[str, int], expression, source: str, target: str):
    return FlowVariable(
        id=name,
        kind="flow",
        expression=_expression(expression),
        source=_endpoint(source),
        target=_endpoint(target),
        units=units,
    )


def _auxiliary(name: str, units: dict[str, int], expression):
    return AuxiliaryVariable(id=name, kind="auxiliary", expression=expression, units=units)


def _model(
    name: str,
    variables: list,
    *,
    unit: str = "year",
    final_time: float = 100,
    time_step: float = 0.25,
    saveper: float | None = None,
) -> ModelDocument:
    return finalize_model(
        ModelDocument(
            name=name,
            description=f"Validated pattern: {name}",
            time=TimeSettings(
                unit=unit,
                final_time=final_time,
                time_step=time_step,
                saveper=saveper if saveper is not None else time_step,
            ),
            variables=variables,
        )
    )


def exponential() -> ModelDocument:
    return _model(
        "Exponential growth",
        [
            _stock("population", {"person": 1}, 1000),
            _flow(
                "births",
                {"person": 1, "year": -1},
                binary("mul", ref("population"), ref("birth_rate")),
                "cloud:births_source",
                "population",
            ),
            _constant("birth_rate", {"year": -1}, 0.02),
        ],
    )


def logistic() -> ModelDocument:
    return _model(
        "Logistic growth",
        [
            _stock("population", {"person": 1}, 100),
            _flow(
                "net_growth",
                {"person": 1, "year": -1},
                binary(
                    "mul",
                    binary("mul", ref("population"), ref("growth_rate")),
                    binary("sub", lit(1), binary("div", ref("population"), ref("capacity"))),
                ),
                "cloud:growth_source",
                "population",
            ),
            _constant("growth_rate", {"year": -1}, 0.1),
            _constant("capacity", {"person": 1}, 1000),
        ],
    )


def teacup() -> ModelDocument:
    return _model(
        "Teacup cooling",
        [
            _stock("teacup_temperature", {"degree_fahrenheit": 1}, 180),
            _flow(
                "heat_loss",
                {"degree_fahrenheit": 1, "minute": -1},
                binary(
                    "div",
                    binary("sub", ref("teacup_temperature"), ref("room_temperature")),
                    ref("characteristic_time"),
                ),
                "teacup_temperature",
                "cloud:room_sink",
            ),
            _constant("room_temperature", {"degree_fahrenheit": 1}, 70),
            _constant("characteristic_time", {"minute": 1}, 10),
        ],
        unit="minute",
    )


def sir() -> ModelDocument:
    return _model(
        "SIR epidemic",
        [
            _stock(
                "susceptible",
                {"person": 1},
                binary("sub", ref("total_population"), ref("initial_infectious")),
            ),
            _stock("infectious", {"person": 1}, ref("initial_infectious")),
            _stock("recovered", {"person": 1}, 0),
            _flow(
                "infection",
                {"person": 1, "day": -1},
                binary(
                    "mul",
                    binary(
                        "div",
                        binary("mul", ref("susceptible"), ref("infectious")),
                        ref("total_population"),
                    ),
                    ref("contact_infectivity"),
                ),
                "susceptible",
                "infectious",
            ),
            _flow(
                "recovering",
                {"person": 1, "day": -1},
                binary("div", ref("infectious"), ref("duration")),
                "infectious",
                "recovered",
            ),
            _constant("total_population", {"person": 1}, 1000),
            _constant("initial_infectious", {"person": 1}, 5),
            _constant("contact_infectivity", {"day": -1}, 0.3),
            _constant("duration", {"day": 1}, 5),
        ],
        unit="day",
    )


def predator_prey() -> ModelDocument:
    return _model(
        "Predator prey",
        [
            _stock("prey", {"rabbit": 1}, 100),
            _stock("predators", {"fox": 1}, 20),
            _flow(
                "prey_births",
                {"rabbit": 1, "year": -1},
                binary("mul", ref("prey"), ref("prey_growth")),
                "cloud:prey_births_source",
                "prey",
            ),
            _flow(
                "predation",
                {"rabbit": 1, "year": -1},
                binary("mul", binary("mul", ref("prey"), ref("predators")), ref("predation_rate")),
                "prey",
                "cloud:predation_sink",
            ),
            _flow(
                "predator_births",
                {"fox": 1, "year": -1},
                binary("mul", ref("predation"), ref("conversion_efficiency")),
                "cloud:predator_births_source",
                "predators",
            ),
            _flow(
                "predator_deaths",
                {"fox": 1, "year": -1},
                binary("mul", ref("predators"), ref("predator_mortality")),
                "predators",
                "cloud:predator_deaths_sink",
            ),
            _constant("prey_growth", {"year": -1}, 0.1),
            _constant("predation_rate", {"fox": -1, "year": -1}, 0.02),
            _constant("conversion_efficiency", {"fox": 1, "rabbit": -1}, 0.1),
            _constant("predator_mortality", {"year": -1}, 0.1),
        ],
    )


def bass_diffusion() -> ModelDocument:
    return _model(
        "Bass diffusion",
        [
            _stock("potential_adopters", {"person": 1}, ref("total_market")),
            _stock("adopters", {"person": 1}, 0),
            _flow(
                "adoption",
                {"person": 1, "year": -1},
                binary(
                    "mul",
                    ref("potential_adopters"),
                    binary(
                        "add",
                        ref("innovation"),
                        binary(
                            "div",
                            binary("mul", ref("imitation"), ref("adopters")),
                            ref("total_market"),
                        ),
                    ),
                ),
                "potential_adopters",
                "adopters",
            ),
            _constant("total_market", {"person": 1}, 10000),
            _constant("innovation", {"year": -1}, 0.03),
            _constant("imitation", {"year": -1}, 0.38),
        ],
    )


def inventory() -> ModelDocument:
    return _model(
        "Inventory",
        [
            _stock("inventory", {"item": 1}, ref("target_inventory")),
            _flow(
                "sales",
                {"item": 1, "week": -1},
                ref("demand_rate"),
                "inventory",
                "cloud:sales_sink",
            ),
            _flow(
                "replenishment",
                {"item": 1, "week": -1},
                binary(
                    "div",
                    binary("sub", ref("target_inventory"), ref("inventory")),
                    ref("lead_time"),
                ),
                "cloud:supply_source",
                "inventory",
            ),
            _constant("target_inventory", {"item": 1}, 1000),
            _constant("demand_rate", {"item": 1, "week": -1}, 100),
            _constant("lead_time", {"week": 1}, 4),
        ],
        unit="week",
    )


def workforce() -> ModelDocument:
    return _model(
        "Workforce",
        [
            _stock("rookies", {"person": 1}, 5),
            _stock("experts", {"person": 1}, 50),
            _flow(
                "hiring",
                {"person": 1, "year": -1},
                ref("hiring_rate"),
                "cloud:hiring_source",
                "rookies",
            ),
            _flow(
                "maturation",
                {"person": 1, "year": -1},
                binary("div", ref("rookies"), ref("maturation_time")),
                "rookies",
                "experts",
            ),
            _flow(
                "departures",
                {"person": 1, "year": -1},
                binary("div", ref("experts"), ref("average_tenure")),
                "experts",
                "cloud:departures_sink",
            ),
            _constant("hiring_rate", {"person": 1, "year": -1}, 20),
            _constant("maturation_time", {"year": 1}, 3),
            _constant("average_tenure", {"year": 1}, 10),
        ],
    )


def supply_delay() -> ModelDocument:
    return _model(
        "Supply chain delay",
        [
            _stock("inventory", {"item": 1}, 50),
            _flow(
                "shipments",
                {"item": 1, "week": -1},
                call("delay3", ref("order_rate"), ref("delay_time")),
                "cloud:supplier_source",
                "inventory",
            ),
            _flow(
                "sales",
                {"item": 1, "week": -1},
                ref("demand_rate"),
                "inventory",
                "cloud:sales_sink",
            ),
            _auxiliary(
                "order_rate",
                {"item": 1, "week": -1},
                binary("add", lit(100), call("step", lit(50), lit(5))),
            ),
            _constant("demand_rate", {"item": 1, "week": -1}, 100),
            _constant("delay_time", {"week": 1}, 4),
        ],
        unit="week",
    )


def renewable_resource() -> ModelDocument:
    return _model(
        "Renewable resource",
        [
            _stock("resource", {"tonne": 1}, 500),
            _flow(
                "natural_growth",
                {"tonne": 1, "year": -1},
                binary(
                    "mul",
                    binary("mul", ref("growth_rate"), ref("resource")),
                    binary("sub", lit(1), binary("div", ref("resource"), ref("capacity"))),
                ),
                "cloud:growth_source",
                "resource",
            ),
            _flow(
                "harvest",
                {"tonne": 1, "year": -1},
                binary("mul", ref("harvest_rate"), ref("resource")),
                "resource",
                "cloud:harvest_sink",
            ),
            _constant("growth_rate", {"year": -1}, 0.2),
            _constant("capacity", {"tonne": 1}, 1000),
            _constant("harvest_rate", {"year": -1}, 0.05),
        ],
    )


def sirs_epidemic() -> ModelDocument:
    return _model(
        "Seasonal SIRS epidemic",
        [
            _stock(
                "susceptible",
                {"person": 1},
                binary("sub", ref("total_population"), ref("initial_infectious")),
            ),
            _stock("infectious", {"person": 1}, ref("initial_infectious")),
            _stock("recovered", {"person": 1}, 0),
            _auxiliary(
                "contact_rate",
                {"day": -1},
                parse_expression(
                    "base_contact_rate * (1 + seasonal_amplitude * sin(2 * pi * time / seasonal_period))"
                ),
            ),
            _flow(
                "infection",
                {"person": 1, "day": -1},
                parse_expression(
                    "susceptible * infectious / total_population * contact_rate"
                ),
                "susceptible",
                "infectious",
            ),
            _flow(
                "recovery",
                {"person": 1, "day": -1},
                parse_expression("infectious / infectious_duration"),
                "infectious",
                "recovered",
            ),
            _flow(
                "immunity_loss",
                {"person": 1, "day": -1},
                parse_expression("recovered / immunity_duration"),
                "recovered",
                "susceptible",
            ),
            _constant("total_population", {"person": 1}, 1000),
            _constant("initial_infectious", {"person": 1}, 5),
            _constant("base_contact_rate", {"day": -1}, 0.35),
            _constant("infectious_duration", {"day": 1}, 5),
            _constant("immunity_duration", {"day": 1}, 90),
            _constant("seasonal_amplitude", {}, 0.6),
            _constant("seasonal_period", {"day": 1}, 365),
        ],
        unit="day",
        final_time=730,
        time_step=0.5,
        saveper=1,
    )


def supply_chain_bullwhip() -> ModelDocument:
    return _model(
        "Supply chain bullwhip",
        [
            _stock("inventory", {"item": 1}, ref("initial_inventory")),
            _stock("supply_line", {"item": 1}, ref("initial_supply_line")),
            _auxiliary(
                "demand",
                {"item": 1, "week": -1},
                parse_expression("if_then_else(time >= 10, high_demand, base_demand)"),
            ),
            _auxiliary(
                "expected_demand",
                {"item": 1, "week": -1},
                parse_expression("smooth(demand, forecast_time)"),
            ),
            _auxiliary(
                "target_inventory",
                {"item": 1},
                parse_expression("expected_demand * coverage_time"),
            ),
            _auxiliary(
                "target_supply_line",
                {"item": 1},
                parse_expression("expected_demand * lead_time"),
            ),
            _flow(
                "order_rate",
                {"item": 1, "week": -1},
                parse_expression(
                    "max(expected_demand + (target_inventory - inventory) / adjustment_time + "
                    "(target_supply_line - supply_line) / adjustment_time, zero_rate)"
                ),
                "cloud:supplier_orders",
                "supply_line",
            ),
            _flow(
                "shipments",
                {"item": 1, "week": -1},
                parse_expression("delay3(order_rate, lead_time)"),
                "supply_line",
                "inventory",
            ),
            _flow(
                "sales",
                {"item": 1, "week": -1},
                parse_expression("demand"),
                "inventory",
                "cloud:customer_sink",
            ),
            _constant("initial_inventory", {"item": 1}, 400),
            _constant("initial_supply_line", {"item": 1}, 400),
            _constant("base_demand", {"item": 1, "week": -1}, 100),
            _constant("high_demand", {"item": 1, "week": -1}, 160),
            _constant("coverage_time", {"week": 1}, 4),
            _constant("lead_time", {"week": 1}, 4),
            _constant("forecast_time", {"week": 1}, 2),
            _constant("adjustment_time", {"week": 1}, 2),
            _constant("zero_rate", {"item": 1, "week": -1}, 0),
        ],
        unit="week",
    )


def student_club() -> ModelDocument:
    return _model(
        "Student speaking club",
        [
            _stock("interested_students", {"person": 1}, 500),
            _stock("active_members", {"person": 1}, 20),
            _stock("tired_members", {"person": 1}, 0),
            _auxiliary(
                "capacity_factor",
                {},
                parse_expression("max(1 - active_members / club_capacity, zero_dimensionless)"),
            ),
            _auxiliary(
                "campaign_factor",
                {},
                parse_expression(
                    "if_then_else(time >= 60, campaign_boost, baseline_campaign)"
                ),
            ),
            _flow(
                "joining",
                {"person": 1, "week": -1},
                parse_expression(
                    "interested_students * joining_rate * "
                    "(1 + word_of_mouth * active_members / club_capacity) * "
                    "capacity_factor * campaign_factor"
                ),
                "interested_students",
                "active_members",
            ),
            _flow(
                "leaving",
                {"person": 1, "week": -1},
                parse_expression(
                    "active_members * leaving_rate + active_members * overcrowding_rate * "
                    "max(active_members / club_capacity - 1, zero_dimensionless)"
                ),
                "active_members",
                "tired_members",
            ),
            _flow(
                "returning",
                {"person": 1, "week": -1},
                parse_expression("tired_members / recovery_time"),
                "tired_members",
                "interested_students",
            ),
            _constant("club_capacity", {"person": 1}, 80),
            _constant("joining_rate", {"week": -1}, 0.15),
            _constant("leaving_rate", {"week": -1}, 0.08),
            _constant("overcrowding_rate", {"week": -1}, 0.3),
            _constant("word_of_mouth", {}, 1.5),
            _constant("recovery_time", {"week": 1}, 20),
            _constant("baseline_campaign", {}, 1),
            _constant("campaign_boost", {}, 3),
            _constant("zero_dimensionless", {}, 0),
        ],
        unit="week",
        final_time=104,
    )


def lorenz_system() -> ModelDocument:
    state_rate = {"state": 1, "time": -1}
    return _model(
        "Lorenz system",
        [
            _stock("x", {"state": 1}, 1),
            _stock("y", {"state": 1}, 1),
            _stock("z", {"state": 1}, 1),
            _flow("dx", state_rate, parse_expression("sigma * (y - x)"), "cloud:x_source", "x"),
            _flow(
                "dy",
                state_rate,
                parse_expression("rho * x - decay_y * y - coupling_rate * x * z"),
                "cloud:y_source",
                "y",
            ),
            _flow(
                "dz",
                state_rate,
                parse_expression("xy_rate * x * y - beta * z"),
                "cloud:z_source",
                "z",
            ),
            _constant("sigma", {"time": -1}, 10),
            _constant("rho", {"time": -1}, 28),
            _constant("beta", {"time": -1}, 8 / 3),
            _constant("coupling_rate", {"state": -1, "time": -1}, 1),
            _constant("decay_y", {"time": -1}, 1),
            _constant("xy_rate", {"state": -1, "time": -1}, 1),
        ],
        unit="time",
        time_step=0.01,
        saveper=0.05,
    )


def van_der_pol_oscillator() -> ModelDocument:
    return _model(
        "Van der Pol oscillator",
        [
            _stock("position", {}, 2),
            _stock("velocity", {"time": -1}, 0),
            _flow(
                "d_position",
                {"time": -1},
                parse_expression("velocity"),
                "cloud:position_source",
                "position",
            ),
            _flow(
                "d_velocity",
                {"time": -2},
                parse_expression(
                    "mu * (1 - position^2) * velocity - acceleration_scale * position"
                ),
                "cloud:velocity_source",
                "velocity",
            ),
            _constant("mu", {"time": -1}, 3),
            _constant("acceleration_scale", {"time": -2}, 1),
        ],
        unit="time",
        final_time=60,
        time_step=0.01,
        saveper=0.05,
    )


def duffing_oscillator() -> ModelDocument:
    return _model(
        "Duffing oscillator",
        [
            _stock("position", {"length": 1}, 1),
            _stock("velocity", {"length": 1, "time": -1}, 0),
            _flow(
                "d_position",
                {"length": 1, "time": -1},
                parse_expression("velocity"),
                "cloud:position_source",
                "position",
            ),
            _flow(
                "d_velocity",
                {"length": 1, "time": -2},
                parse_expression(
                    "-delta * velocity - alpha * position - beta * position^3 + "
                    "gamma * cos(omega * time)"
                ),
                "cloud:velocity_source",
                "velocity",
            ),
            _constant("delta", {"time": -1}, 0.3),
            _constant("alpha", {"time": -2}, -1),
            _constant("beta", {"length": -2, "time": -2}, 1),
            _constant("gamma", {"length": 1, "time": -2}, 0.37),
            _constant("omega", {"time": -1}, 1.2),
        ],
        unit="time",
        final_time=200,
        time_step=0.01,
        saveper=0.05,
    )


_BUILDERS = {
    "exponential_growth": exponential,
    "logistic_growth": logistic,
    "teacup_cooling": teacup,
    "sir_epidemic": sir,
    "predator_prey": predator_prey,
    "bass_diffusion": bass_diffusion,
    "inventory": inventory,
    "workforce": workforce,
    "supply_delay": supply_delay,
    "renewable_resource": renewable_resource,
    "sirs_epidemic": sirs_epidemic,
    "supply_chain_bullwhip": supply_chain_bullwhip,
    "student_club": student_club,
    "lorenz_system": lorenz_system,
    "van_der_pol_oscillator": van_der_pol_oscillator,
    "duffing_oscillator": duffing_oscillator,
}

_METADATA = {
    "exponential_growth": (
        "Exponential growth and decline",
        (
            "growth",
            "grows",
            "bacteria",
            "bacterial",
            "colony",
            "population",
            "decay",
            "interest",
            "deposit",
            "рост",
            "экспонент",
        ),
    ),
    "logistic_growth": (
        "Growth limited by carrying capacity",
        ("logistic", "carrying capacity", "capacity", "limit", "ёмкост", "вместим", "логист"),
    ),
    "teacup_cooling": (
        "Cooling and first-order equilibration",
        ("teacup", "cooling", "temperature", "чай", "остыв", "температур"),
    ),
    "sir_epidemic": (
        "Susceptible infectious recovered epidemic",
        (
            "sir",
            "susceptible",
            "infectious",
            "recovered",
            "norovirus",
            "epidemic",
            "infection",
            "disease",
            "эпидем",
            "зараж",
            "болезн",
        ),
    ),
    "predator_prey": (
        "Predator prey population dynamics",
        (
            "predator",
            "prey",
            "fox",
            "rabbit",
            "wolf",
            "wolves",
            "deer",
            "owl",
            "owls",
            "mice",
            "хищник",
            "жертва",
            "лис",
            "кролик",
            "лотка",
        ),
    ),
    "bass_diffusion": (
        "Product adoption and diffusion",
        (
            "bass",
            "adoption",
            "diffusion",
            "product",
            "advertising",
            "recommendations",
            "word of mouth",
            "adopters",
            "продукт",
            "внедрен",
            "диффуз",
            "инновац",
            "подражан",
        ),
    ),
    "inventory": (
        "Inventory and backlog management",
        ("inventory", "warehouse", "backlog", "запас", "склад", "заказ"),
    ),
    "workforce": (
        "Hiring and workforce maturation",
        (
            "workforce",
            "employee",
            "hiring",
            "hires",
            "trainee",
            "trainees",
            "consultant",
            "consultants",
            "junior",
            "senior",
            "nurse",
            "nurses",
            "rookie",
            "expert",
            "персонал",
            "сотрудник",
            "найм",
            "новичк",
            "эксперт",
            "наним",
            "увольн",
        ),
    ),
    "supply_delay": (
        "Supply chains and material delays",
        (
            "supply",
            "delivery",
            "delay",
            "shipment",
            "shipping",
            "replenishment",
            "постав",
            "задерж",
            "задержка поставки",
            "задержкой поставки",
            "достав",
        ),
    ),
    "renewable_resource": (
        "Renewable resources and harvesting",
        (
            "resource",
            "fish",
            "fish stock",
            "fishing",
            "forest",
            "harvest",
            "hunting",
            "hunting quota",
            "regenerates",
            "regeneration",
            "renewable",
            "рыб",
            "лес",
            "ресурс",
            "промысел",
            "восстанавли",
        ),
    ),
    "sirs_epidemic": (
        "Seasonal SIRS epidemic with waning immunity",
        (
            "sirs",
            "seasonal",
            "seasonal epidemic",
            "recurring epidemic",
            "repeated waves",
            "temporary immunity",
            "lose immunity",
            "loss of immunity",
            "immunity loss",
            "waning immunity",
            "seasonal waves",
            "повторные волны",
        ),
    ),
    "supply_chain_bullwhip": (
        "Supply chain oscillations and bullwhip effect",
        (
            "bullwhip",
            "supply chain",
            "customer demand",
            "order amplification",
            "supplier",
            "retailer",
            "demand increase",
            "holiday demand",
            "purchasing orders",
            "цепочка поставок",
        ),
    ),
    "student_club": (
        "Student club growth, capacity, burnout and campaigns",
        (
            "speaking club",
            "english speaking club",
            "student club",
            "student community",
            "клуб",
            "студен",
        ),
    ),
    "lorenz_system": (
        "Lorenz chaotic three-variable attractor",
        ("lorenz", "лоренц", "chaotic attractor", "butterfly attractor"),
    ),
    "van_der_pol_oscillator": (
        "Van der Pol nonlinear relaxation oscillator",
        ("van der pol", "ван дер пол", "relaxation oscillator", "предельный цикл"),
    ),
    "duffing_oscillator": (
        "Duffing driven nonlinear oscillator",
        ("duffing", "даффинг", "two-well oscillator", "двухъямный"),
    ),
}


@lru_cache(maxsize=len(_BUILDERS))
def get_pattern(pattern_id: str) -> Pattern:
    description, tags = _METADATA[pattern_id]
    return Pattern(pattern_id, description, tags, _BUILDERS[pattern_id]())


def select_pattern(description: str) -> Pattern | None:
    import re

    from .ode_equivalence import explicit_ode_expressions

    text = description.casefold()
    candidates = []
    for pattern_id, (_, tags) in _METADATA.items():
        matched = []
        for tag in sorted(tags, key=len, reverse=True):
            if not re.search(rf"(?<![\w]){re.escape(tag)}", text):
                continue
            if any(tag in longer for longer in matched):
                continue
            matched.append(tag)
        score = sum(len(tag) for tag in matched)
        if score:
            candidates.append((score, pattern_id))
    explicit_stocks = set(explicit_ode_expressions(description))
    if len(explicit_stocks) > 1:
        candidates = [
            candidate
            for candidate in candidates
            if sum(item.kind == "stock" for item in get_pattern(candidate[1]).document.variables)
            == len(explicit_stocks)
        ]
    if not candidates:
        return None
    return get_pattern(max(candidates)[1])


def pattern_prompt(pattern: Pattern | None) -> str:
    if pattern is None:
        return "No domain pattern selected."
    payload = {
        "pattern_id": pattern.id,
        "purpose": pattern.description,
        "time": pattern.document.time.model_dump(mode="json"),
        "variables": [],
        "equations": [],
        "tables": [item.model_dump(mode="json") for item in pattern.document.tables],
    }
    names = {item.id: item.id for item in pattern.document.variables}
    table_names = {item.id: item.id for item in pattern.document.tables}

    def prompt_value(expression):
        if (number := constant_number(expression)) is not None:
            return number
        return expression_to_vensim(expression, names, table_names)

    for variable in pattern.document.variables:
        item = variable.model_dump(mode="json")
        item.pop("derivative", None)
        item.pop("expression", None)
        if variable.kind == "stock":
            item["initial"] = prompt_value(variable.initial)
        elif variable.kind == "constant":
            item["initial"] = prompt_value(variable.expression)
        else:
            item["initial"] = None
            payload["equations"].append(
                {"id": variable.id, "expression": prompt_value(variable.expression)}
            )
        payload["variables"].append(item)
    return json.dumps(payload, ensure_ascii=False, indent=2)
