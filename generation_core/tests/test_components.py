import math

import pytest

from pipeline.components import build_components
from pipeline.exceptions import ModelValidationError
from pipeline.generation import generate_model
from pipeline.schemas import (
    GenerationRequest,
    ModelBrief,
    ModelDocument,
    SimulationParameters,
    TimeSettings,
)
from pipeline.simulation import simulate_model


def document(components, *, final_time=20, time_step=0.025, unit="second"):
    variables, settings, assumptions = build_components(
        components,
        TimeSettings(
            unit=unit,
            final_time=final_time,
            time_step=time_step,
            saveper=time_step,
        ),
    )
    assert assumptions == []
    return ModelDocument(
        name="Component test",
        description="Deterministic typed component test",
        time=settings,
        variables=variables,
    )


def adaptive():
    return SimulationParameters(
        engine="scipy", integration_method="dop853", rtol=1e-9, atol=1e-12
    )


def test_first_order_time_constant_has_analytic_discharge():
    result = simulate_model(
        document(
            [
                {
                    "kind": "first_order",
                    "source": "charge",
                    "target": "cloud:ground",
                    "flow": "discharge",
                    "time_constant": 5,
                    "initial_source": 5,
                    "initial_target": 0,
                    "source_units": {"coulomb": 1},
                    "target_units": {"coulomb": 1},
                    "time_unit": "second",
                }
            ],
            final_time=50,
        ),
        adaptive(),
    )
    assert result.variables["charge"][0] == 5
    assert result.variables["charge"][-1] == pytest.approx(5 * math.exp(-10), rel=1e-7)
    current = next(item for item in result.variables if item == "discharge")
    assert result.variables[current][0] == 1


def test_first_order_chain_conserves_material():
    result = simulate_model(
        document(
            [
                {
                    "kind": "first_order",
                    "source": "parent",
                    "target": "daughter",
                    "flow": "transformation",
                    "coefficient": 0.2,
                    "initial_source": 100,
                    "initial_target": 0,
                    "source_units": {"atom": 1},
                    "target_units": {"atom": 1},
                    "time_unit": "second",
                }
            ]
        ),
        adaptive(),
    )
    assert result.variables["daughter"][-1] > 1
    for parent, daughter in zip(result.variables["parent"], result.variables["daughter"], strict=True):
        assert parent + daughter == pytest.approx(100, abs=1e-8)


def test_conditional_inflow_stops_then_eliminates():
    result = simulate_model(
        document(
            [
                {
                    "kind": "conditional_inflow",
                    "stock": "drug_mass",
                    "inflow": "infusion",
                    "outflow": "elimination",
                    "rate": 10,
                    "start_time": 0,
                    "end_time": 2,
                    "elimination_rate": 0.1,
                    "initial": 0,
                    "units": {"mg": 1},
                    "time_unit": "second",
                }
            ],
            unit="second",
        ),
        adaptive(),
    )
    series = result.variables["drug_mass"]
    assert series[result.time.index(2)] == pytest.approx(100 * (1 - math.exp(-0.2)), rel=1e-7)
    assert series[-1] < series[result.time.index(2)]
    assert all(value >= 0 for value in series)


def test_queue_converges_without_negative_stock():
    result = simulate_model(
        document(
            [
                {
                    "kind": "queue",
                    "stock": "waiting_people",
                    "arrivals": "arrivals",
                    "service": "service_flow",
                    "service_time": 0.125,
                    "max_service": 8,
                    "arrival_rate": 2,
                    "initial": 40,
                    "units": {"person": 1},
                    "time_unit": "second",
                }
            ],
            final_time=30,
            time_step=0.01,
        ),
        SimulationParameters(integration_method="euler"),
    )
    assert result.variables["waiting_people"][-1] == pytest.approx(0.25, abs=0.005)
    assert min(result.variables["waiting_people"]) >= 0
    assert min(result.variables["service_flow"]) >= 0


def test_queue_supports_finite_arrival_burst():
    result = simulate_model(
        document(
            [
                {
                    "kind": "queue",
                    "stock": "packets",
                    "arrivals": "incoming_traffic",
                    "service": "processing",
                    "service_time": 0.5,
                    "max_service": 40,
                    "arrival_rate": 100,
                    "initial": 0,
                    "units": {"packet": 1},
                    "time_unit": "second",
                    "arrival_end_time": 5,
                }
            ],
            time_step=0.025,
        ),
        SimulationParameters(integration_method="euler"),
    )
    series = result.variables["packets"]
    assert series[result.time.index(5)] > 1
    assert series[-1] == pytest.approx(0, abs=1e-4)


def test_delay_has_gradual_transport_response_and_later_consumption():
    result = simulate_model(
        document(
            [
                {
                    "kind": "delay",
                    "stock": "blanks",
                    "inflow": "transport",
                    "outflow": "consumption",
                    "input_rate": 10,
                    "delay_time": 4,
                    "initial_stock": 0,
                    "initial_delayed_rate": 0,
                    "stock_units": {"item": 1},
                    "time_unit": "second",
                    "consumption_time": 2,
                    "input_rate_after": 20,
                    "rate_change_time": 5,
                }
            ],
            final_time=30,
            time_step=0.025,
        ),
        SimulationParameters(integration_method="euler"),
    )
    series = result.variables["blanks"]
    before = series[: result.time.index(1) + 1]
    assert max(before) < 0.1
    assert series[-1] > 10
    assert result.variables["transport"][0] == 0


def spring_components():
    return [
        {
            "kind": "polynomial_ode",
            "stock": "position",
            "initial": 1,
            "units": {"meter": 1},
            "time_unit": "second",
            "terms": [{"coefficient": 1, "expression": "velocity", "sign": 1}],
            "parameters": [],
        },
        {
            "kind": "polynomial_ode",
            "stock": "velocity",
            "initial": 0,
            "units": {"meter": 1, "second": -1},
            "time_unit": "second",
            "terms": [
                {"coefficient": 4, "expression": "position", "sign": -1},
                {"coefficient": 0.4, "expression": "velocity", "sign": -1},
            ],
            "parameters": [],
        },
    ]


def test_polynomial_ode_builds_second_order_spring():
    result = simulate_model(document(spring_components()), adaptive())
    series = result.variables["position"]
    sign_changes = sum(
        left * right < 0 for left, right in zip(series, series[1:], strict=False)
    )
    assert sign_changes >= 2
    assert max(abs(value) for value in series) <= 1.001
    model = document(spring_components())
    velocity = next(item for item in model.variables if item.id == "velocity_net_rate")
    assert velocity.source.kind == "cloud"
    assert velocity.target.id == "velocity"
    assert velocity.topology_status == "inferred"


def test_rossler_coefficient_units_are_inferred_from_polynomial_terms():
    components = [
        {
            "kind": "polynomial_ode",
            "stock": stock,
            "initial": initial,
            "units": {"state": 1},
            "time_unit": "second",
            "terms": terms,
            "parameters": parameters,
        }
        for stock, initial, terms, parameters in [
            ("x", 1, [
                {"coefficient": 1, "expression": "y", "sign": -1},
                {"coefficient": 1, "expression": "z", "sign": -1},
            ], []),
            ("y", 1, [
                {"coefficient": 1, "expression": "x", "sign": 1},
                {"coefficient": 0.2, "expression": "y", "sign": 1},
            ], []),
            ("z", 0, [
                {"coefficient": 0.2, "expression": "one", "sign": 1},
                {"coefficient": "nonlinear_coupling", "expression": "z * (x - critical_x)", "sign": 1},
            ], [
                {"id": "one", "value": 1, "role": "scale"},
                {"id": "critical_x", "value": 5.7, "role": "threshold"},
                {"id": "nonlinear_coupling", "value": 1, "role": "rate"},
            ]),
        ]
    ]
    model = document(components, final_time=100, time_step=0.05, unit="second")
    coupling = next(item for item in model.variables if item.id == "nonlinear_coupling")
    assert coupling.units == {"state": -1, "second": -1}
    threshold = next(item for item in model.variables if item.id == "critical_x")
    assert threshold.units == {"state": 1}
    result = simulate_model(model, adaptive())
    series = result.variables["x"]
    assert sum(left * right < 0 for left, right in zip(series, series[1:], strict=False)) >= 2


def test_allee_thresholds_keep_their_stock_units():
    model = document(
        [
            {
                "kind": "polynomial_ode",
                "stock": "animals",
                "initial": 5,
                "units": {"animal": 1},
                "time_unit": "second",
                "terms": [
                    {
                        "coefficient": "growth_rate",
                        "expression": "animals * (animals / lower_threshold - 1) * (1 - animals / upper_threshold)",
                        "sign": 1,
                    },
                    {"coefficient": 0.05, "expression": "animals", "sign": -1},
                ],
                "parameters": [
                    {"id": "growth_rate", "value": 0.2, "role": "rate"},
                    {"id": "lower_threshold", "value": 10, "role": "threshold"},
                    {"id": "upper_threshold", "value": 100, "role": "threshold"},
                ],
            }
        ],
        final_time=100,
        time_step=0.1,
    )
    result = simulate_model(model, adaptive())
    series = result.variables["animals"]
    assert series[-1] < series[0]
    assert all(left >= right - 1e-9 for left, right in zip(series, series[1:], strict=False))


def self_decay_component():
    return {
        "kind": "polynomial_ode",
        "stock": "terminal",
        "initial": 0,
        "units": {"item": 1},
        "time_unit": "second",
        "terms": [{"coefficient": 0.4, "expression": "terminal", "sign": -1}],
        "parameters": [],
    }


def test_zero_stock_with_only_self_decay_is_rejected():
    with pytest.raises(ModelValidationError, match="vacuous stock.*no inflow"):
        build_components([self_decay_component()], TimeSettings(unit="second"))


def test_zero_stock_with_zero_derivative_is_a_valid_equilibrium():
    component = self_decay_component()
    component["terms"] = [{"coefficient": 0, "expression": "terminal", "sign": 1}]
    model = document([component], final_time=2)
    result = simulate_model(model, adaptive())
    assert set(result.variables["terminal"]) == {0}
    assert result.time[-1] == 2


def test_zero_stock_with_a_positive_term_is_allowed():
    component = self_decay_component()
    component["terms"].append({"coefficient": 0.4, "expression": "1", "sign": 1})
    model = document([component], final_time=2)
    result = simulate_model(model, adaptive())
    assert result.variables["terminal"][-1] > 0


def test_invalid_polynomial_coefficient_units_are_rejected():
    with pytest.raises(ModelValidationError, match="coefficient stiffness.*equation requires"):
        build_components(
            [
                {
                    "kind": "polynomial_ode",
                    "stock": "position",
                    "initial": 1,
                    "units": {"meter": 1},
                    "time_unit": "second",
                    "terms": [{"coefficient": 1, "expression": "velocity", "sign": 1}],
                    "parameters": [],
                },
                {
                    "kind": "polynomial_ode",
                    "stock": "velocity",
                    "initial": 0,
                    "units": {"meter": 1, "second": -1},
                    "time_unit": "second",
                    "terms": [{"coefficient": "stiffness", "expression": "position", "sign": -1}],
                    "parameters": [
                        {"id": "stiffness", "value": 4, "role": "rate", "units": {"second": -1}}
                    ],
                }
            ],
            TimeSettings(unit="second"),
        )


def test_duplicate_component_stock_is_rejected():
    component = {
        "kind": "polynomial_ode",
        "stock": "value",
        "initial": 0,
        "units": {"state": 1},
        "time_unit": "second",
        "terms": [{"coefficient": 1, "expression": "value", "sign": 1}],
        "parameters": [],
    }
    with pytest.raises(ModelValidationError, match="polynomial ODE stocks.*only once"):
        build_components([component, component], TimeSettings(unit="second"))


def component_brief():
    return ModelBrief(
        goal="First-order discharge",
        boundaries=["Capacitor and environment"],
        time_horizon="20 seconds",
        time_unit="second",
        stocks=["charge"],
        flows=["discharge"],
        components=[
            {
                "kind": "first_order",
                "source": "charge",
                "target": "cloud:ground",
                "flow": "discharge",
                "time_constant": 5,
                "initial_source": 5,
                "initial_target": 0,
                "source_units": {"coulomb": 1},
                "target_units": {"coulomb": 1},
                "time_unit": "second",
            }
        ],
        time=TimeSettings(unit="second", final_time=20, time_step=0.05, saveper=0.05),
    )


def component_plan():
    brief = component_brief().model_dump(mode="json")
    return {field: brief[field] for field in ("components", "time", "assumptions")}


class ComponentLLM:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
        self.calls.append(stage)
        if self.responses and stage.startswith("components"):
            return self.responses.pop(0)
        if stage == "brief":
            brief = component_brief().model_dump(mode="json")
            brief.update(components=[], time=None, assumptions=[])
            return brief
        return component_plan()


async def test_typed_components_skip_free_form_variable_and_equation_stages(tmp_path):
    llm = ComponentLLM()
    result = await generate_model(
        GenerationRequest(description="A custom first-order dynamic mechanism"),
        llm,
        workdir=tmp_path,
        max_repairs=0,
    )
    assert llm.calls == ["brief", "components"]
    assert result.repair_attempts == 0
    assert result.time.final_time == 20
    assert result.brief.components[0].kind == "first_order"
    assert (tmp_path / "components.json").exists()
    assert (tmp_path / "variables.json").exists()
    assert (tmp_path / "equations.json").exists()
    assert not (tmp_path / "variables_response.json").exists()


async def test_invalid_typed_brief_uses_bounded_stage_repair():
    invalid = component_plan()
    invalid["components"][0]["coefficient"] = 0.1
    llm = ComponentLLM([invalid, component_plan()])
    result = await generate_model(
        GenerationRequest(description="A custom first-order dynamic mechanism"),
        llm,
        max_repairs=1,
    )
    assert llm.calls == ["brief", "components", "components_repair_1"]
    assert result.repair_attempts == 1


async def test_duplicate_delay_consumption_uses_bounded_stage_repair():
    delay = {
        "kind": "delay",
        "stock": "blanks",
        "inflow": "transport",
        "outflow": "consumption",
        "input_rate": 10,
        "delay_time": 4,
        "initial_stock": 0,
        "initial_delayed_rate": 0,
        "stock_units": {"item": 1},
        "time_unit": "second",
        "consumption_time": 2,
        "input_rate_after": 20,
        "rate_change_time": 5,
    }
    duplicate = {
        "kind": "first_order",
        "source": "blanks",
        "target": "cloud:extra",
        "flow": "extra_transport",
        "time_constant": 2,
        "initial_source": 0,
        "initial_target": 0,
        "source_units": {"item": 1},
        "target_units": None,
        "time_unit": "second",
    }
    valid = {**component_plan(), "components": [delay]}
    invalid = {**component_plan(), "components": [delay, duplicate]}
    llm = ComponentLLM([invalid, valid])
    result = await generate_model(
        GenerationRequest(description="A custom first-order dynamic mechanism"),
        llm,
        max_repairs=1,
    )
    assert llm.calls == ["brief", "components", "components_repair_1"]
    assert result.repair_attempts == 1
    assert result.brief.components[0].kind == "delay"


async def test_no_components_preserves_legacy_pipeline():
    class LegacyLLM(ComponentLLM):
        async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
            self.calls.append(stage)
            if stage == "brief":
                brief = component_brief().model_dump(mode="json")
                brief.update(components=[], time=None, assumptions=[])
                return brief
            if stage == "components":
                return {"components": [], "time": None, "assumptions": []}
            if stage == "variables":
                return {
                    "name": "Legacy discharge",
                    "time": {"unit": "second", "initial_time": 0, "final_time": 20, "time_step": 0.05, "saveper": 0.05},
                    "variables": [
                        {"id": "charge", "kind": "stock", "units": {"coulomb": 1}, "initial": 5},
                        {"id": "discharge", "kind": "flow", "units": {"coulomb": 1, "second": -1}, "source": {"kind": "stock", "id": "charge"}, "target": {"kind": "cloud", "id": "ground"}},
                        {"id": "decay_rate", "kind": "constant", "units": {"second": -1}, "initial": 0.2},
                    ],
                    "tables": [],
                    "assumptions": [],
                }
            if stage == "equations":
                return {"expressions": {"discharge": "charge * decay_rate", "decay_rate": 0.2}}
            raise AssertionError(stage)

    llm = LegacyLLM()
    result = await generate_model(
        GenerationRequest(description="A custom first-order dynamic mechanism"),
        llm,
        max_repairs=0,
    )
    assert llm.calls == ["brief", "components", "variables", "equations"]
    assert result.validation.status == "passed"


async def test_component_annotations_are_normalized_without_changing_mechanism():
    plan = component_plan()
    plan["components"][0]["id"] = "descriptive_component_name"
    plan["assumptions"] = [
        {"source": "llm_inferred", "value": "Explanatory annotation, not a parameter assumption"}
    ]
    llm = ComponentLLM([plan])
    result = await generate_model(
        GenerationRequest(description="A custom first-order dynamic mechanism"),
        llm,
        max_repairs=0,
    )
    assert llm.calls == ["brief", "components"]
    assert result.assumptions == []
    assert result.brief.components[0].source == "charge"


def test_scheduled_flow_changes_rate_without_duplicate_stocks():
    result = simulate_model(
        document(
            [
                {
                    "kind": "scheduled_flow",
                    "source": "charge_fraction",
                    "target": "cloud:load",
                    "flow": "discharge",
                    "rate": 0.01,
                    "rate_after": 0.02,
                    "change_time": 10,
                    "initial_source": 0.9,
                    "initial_target": 0,
                    "source_units": {},
                    "target_units": {},
                    "time_unit": "second",
                }
            ],
            final_time=30,
        ),
        adaptive(),
    )
    series = result.variables["charge_fraction"]
    assert series[result.time.index(10)] == pytest.approx(0.8, rel=1e-8)
    assert series[-1] == pytest.approx(0.4, abs=1e-6)


def test_simulation_rejects_stock_bound_violation_instead_of_returning_it():
    from pipeline.exceptions import SimulationError

    model = document(
        [
            {
                "kind": "queue",
                "stock": "work_items",
                "arrivals": "incoming",
                "service": "completed",
                "service_time": 0.25,
                "max_service": 8,
                "arrival_rate": 0,
                "initial": 6,
                "units": {"item": 1},
                "time_unit": "hour",
            }
        ],
        final_time=15,
        time_step=0.25,
        unit="hour",
    )
    with pytest.raises(SimulationError, match="STOCK_BOUNDS_VIOLATION"):
        simulate_model(
            model,
            SimulationParameters(time_step=0.5, saveper=0.5, integration_method="euler"),
        )
