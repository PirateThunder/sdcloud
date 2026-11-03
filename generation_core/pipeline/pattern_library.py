from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .ir import binary, call, lit, ref
from .schemas import (
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


def _model(name: str, variables: list, *, unit: str = "year") -> ModelDocument:
    return finalize_model(
        ModelDocument(
            name=name,
            description=f"Validated pattern: {name}",
            time=TimeSettings(unit=unit, final_time=100, time_step=0.25, saveper=0.25),
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
            _stock("inventory", {"item": 1}, 100),
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
            _constant("order_rate", {"item": 1, "week": -1}, 100),
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
}

_METADATA = {
    "exponential_growth": (
        "Exponential growth and decline",
        ("growth", "population", "decay", "рост", "экспонент"),
    ),
    "logistic_growth": (
        "Growth limited by carrying capacity",
        ("logistic", "capacity", "limit", "ёмкость", "логист"),
    ),
    "teacup_cooling": (
        "Cooling and first-order equilibration",
        ("teacup", "cooling", "temperature", "чай", "остыв", "температур"),
    ),
    "sir_epidemic": (
        "Susceptible infectious recovered epidemic",
        ("sir", "epidemic", "infection", "disease", "эпидем", "зараж", "болезн"),
    ),
    "predator_prey": (
        "Predator prey population dynamics",
        ("predator", "prey", "fox", "rabbit", "хищник", "жертва", "лис", "кролик", "лотка"),
    ),
    "bass_diffusion": (
        "Product adoption and diffusion",
        ("bass", "adoption", "diffusion", "product", "продукт", "внедрен", "диффуз"),
    ),
    "inventory": (
        "Inventory and backlog management",
        ("inventory", "stock", "warehouse", "backlog", "запас", "склад", "заказ"),
    ),
    "workforce": (
        "Hiring and workforce maturation",
        ("workforce", "employee", "hiring", "rookie", "expert", "персонал", "сотрудник", "найм"),
    ),
    "supply_delay": (
        "Supply chains and material delays",
        ("supply", "delivery", "delay", "shipment", "постав", "задерж", "достав"),
    ),
    "renewable_resource": (
        "Renewable resources and harvesting",
        ("resource", "fish", "forest", "harvest", "renewable", "рыб", "лес", "ресурс"),
    ),
}


@lru_cache(maxsize=len(_BUILDERS))
def get_pattern(pattern_id: str) -> Pattern:
    description, tags = _METADATA[pattern_id]
    return Pattern(pattern_id, description, tags, _BUILDERS[pattern_id]())


def select_pattern(description: str) -> Pattern | None:
    text = description.lower()
    candidates = []
    for pattern_id, (_, tags) in _METADATA.items():
        score = sum(tag in text for tag in tags)
        if score:
            candidates.append((score, pattern_id))
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
        "tables": [item.model_dump(mode="json") for item in pattern.document.tables],
    }
    for variable in pattern.document.variables:
        item = variable.model_dump(mode="json")
        item.pop("derivative", None)
        payload["variables"].append(item)
    return json.dumps(payload, ensure_ascii=False, indent=2)
