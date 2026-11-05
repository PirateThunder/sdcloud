import pytest

from pipeline.components import build_components, normalize_component_payload
from pipeline.exceptions import ModelValidationError
from pipeline.schemas import ComponentPlan, TimeSettings
from pipeline.simulation import simulate_model
from tests.test_components import adaptive, document, spring_components


def first_order(source="upper", target="lower", initial_source=100, initial_target=0):
    return {
        "kind": "first_order",
        "source": source,
        "target": target,
        "flow": "transfer" if target == "lower" else "drain",
        "time_constant": 2 if target == "lower" else 5,
        "initial_source": initial_source,
        "initial_target": initial_target,
        "source_units": {"litre": 1},
        "target_units": {"litre": 1} if target == "lower" else None,
        "time_unit": "second",
    }


def test_first_order_cascade_merges_identical_intermediate_stock():
    model = document(
        [
            first_order(),
            first_order(source="lower", target="cloud:sink", initial_source=0),
        ],
        final_time=40,
    )
    assert [item.id for item in model.variables if item.kind == "stock"] == ["upper", "lower"]
    result = simulate_model(model, adaptive())
    assert max(result.variables["lower"]) > 1
    totals = [
        upper + lower
        for upper, lower in zip(result.variables["upper"], result.variables["lower"], strict=True)
    ]
    assert all(0 <= total <= 100 + 1e-9 for total in totals)
    assert all(left >= right for left, right in zip(totals, totals[1:], strict=False))


def test_cascade_rejects_conflicting_stock_initial_values():
    with pytest.raises(ModelValidationError, match="conflicting initial"):
        build_components(
            [
                first_order(),
                first_order(source="lower", target="cloud:sink", initial_source=1),
            ],
            TimeSettings(unit="second"),
        )


def test_reciprocal_coefficient_and_time_constant_are_not_a_conflict():
    variables, _, _ = build_components(
        [
            {
                "kind": "first_order",
                "source": "level",
                "target": "cloud:sink",
                "flow": "clearance",
                "coefficient": 0.15,
                "time_constant": 20 / 3,
                "initial_source": 8,
                "initial_target": 0,
                "source_units": {"mmol_per_litre": 1},
                "target_units": None,
                "time_unit": "second",
            }
        ],
        TimeSettings(unit="second"),
    )
    coefficient = next(item for item in variables if item.id == "clearance_coefficient")
    assert coefficient.expression.value == pytest.approx(0.15)
    assert not any(item.id == "clearance_time_constant" for item in variables)


def test_descriptive_id_and_first_order_parameter_are_normalized():
    response = {
        "components": [
            {
                "kind": "first_order",
                "id": "clearance",
                "source": "level",
                "target": "cloud:sink",
                "parameters": [
                    {"id": "rate", "value": 0.15, "role": "rate", "units": {"second": -1}}
                ],
                "initial_source": 8,
                "initial_target": 0,
                "source_units": {"mmol": 1},
                "target_units": None,
                "time_unit": "second",
            }
        ],
        "time": None,
        "assumptions": [],
    }
    normalized = normalize_component_payload(response)
    component = normalized["components"][0]
    assert component["flow"] == "clearance"
    assert component["coefficient"] == 0.15
    assert "parameters" not in component
    assert ComponentPlan.model_validate(normalized).components[0].flow == "clearance"


def test_matching_assumption_can_supply_missing_first_order_coefficient():
    response = {
        "components": [
            {
                "kind": "first_order",
                "id": "decay",
                "source": "parent",
                "target": "cloud:sink",
                "flow": "decay",
                "initial_source": 100,
                "initial_target": 0,
                "source_units": {"atom": 1},
                "target_units": None,
                "time_unit": "second",
            }
        ],
        "time": None,
        "assumptions": [{"variable": "decay", "value": 0.2, "source": "llm_inferred"}],
    }
    normalized = normalize_component_payload(response)
    assert normalized["components"][0]["coefficient"] == 0.2
    assert normalized["assumptions"] == []


def test_numeric_coefficient_annotation_becomes_a_number():
    response = {
        "components": [
            {
                "kind": "polynomial_ode",
                "stock": "state",
                "initial": 1,
                "units": {"state": 1},
                "time_unit": "second",
                "terms": [{"coefficient": "rate_0.2", "expression": "state", "sign": 1}],
                "parameters": [
                    {"id": "rate_0.2", "value": 0.2, "role": "rate", "units": None}
                ],
            }
        ],
        "time": None,
        "assumptions": [],
    }
    normalized = normalize_component_payload(response)
    component = normalized["components"][0]
    assert component["terms"][0]["coefficient"] == 0.2
    assert component["parameters"] == []
    assert ComponentPlan.model_validate(normalized).components[0].terms[0].coefficient == 0.2


def test_empty_coefficient_units_placeholder_is_inferred():
    components = spring_components()
    components[1]["terms"][0]["coefficient"] = "stiffness"
    components[1]["parameters"] = [
        {"id": "stiffness", "value": 4, "role": "rate", "units": {}}
    ]
    model = document(components)
    stiffness = next(item for item in model.variables if item.id == "stiffness")
    assert stiffness.units == {"second": -2}


def test_output_sampling_respects_limit_without_changing_time_step():
    _, settings, _ = build_components(
        [
            {
                "kind": "first_order",
                "source": "level",
                "target": "cloud:sink",
                "flow": "drain",
                "coefficient": 0.1,
                "initial_source": 1,
                "initial_target": 0,
                "source_units": {"item": 1},
                "target_units": None,
                "time_unit": "second",
            }
        ],
        TimeSettings(
            unit="second",
            final_time=100,
            time_step=0.0005,
            saveper=0.0005,
        ),
    )
    assert settings.time_step == 0.0005
    assert settings.saveper == pytest.approx(0.0105)
    assert settings.final_time / settings.saveper < 10000


def test_unused_ode_parameter_is_rejected_instead_of_being_ignored():
    components = spring_components()
    components[1]["parameters"] = [
        {"id": "decorative_rate", "value": 0.2, "role": "rate", "units": None}
    ]
    with pytest.raises(ModelValidationError, match="unused ODE parameters.*decorative_rate"):
        build_components(components, TimeSettings(unit="second"))


def test_ode_additive_literal_gets_sibling_units_and_fitz_hugh_oscillates():
    model = document(
        [
            {
                "kind": "polynomial_ode",
                "stock": "v",
                "initial": 1,
                "units": {"state": 1},
                "time_unit": "second",
                "terms": [
                    {"coefficient": 1, "expression": "v", "sign": 1},
                    {"coefficient": 1 / 3, "expression": "v^3", "sign": -1},
                    {"coefficient": 1, "expression": "w", "sign": -1},
                    {"coefficient": 0.5, "expression": "1", "sign": 1},
                ],
                "parameters": [],
            },
            {
                "kind": "polynomial_ode",
                "stock": "w",
                "initial": 0,
                "units": {"state": 1},
                "time_unit": "second",
                "terms": [
                    {"coefficient": 0.08, "expression": "v + 0.7", "sign": 1},
                    {"coefficient": 0.08, "expression": "0.8 * w", "sign": -1},
                ],
                "parameters": [],
            },
        ],
        final_time=100,
        time_step=0.05,
    )
    literal = next(item for item in model.variables if item.id == "w_term_1_literal_1")
    assert literal.expression.value == 0.7
    assert literal.units == {"state": 1}
    result = simulate_model(model, adaptive())
    series = result.variables["v"]
    changes = sum(left * right < 0 for left, right in zip(series, series[1:], strict=False))
    assert changes >= 2


def test_delay_first_order_adapter_preserves_consumption_topology():
    response = {
        "components": [
            {
                "kind": "delay",
                "stock": "internal_stage",
                "inflow": "transport",
                "outflow": "delayed_items",
                "input_rate": 10,
                "delay_time": 4,
                "initial_stock": 0,
                "initial_delayed_rate": 0,
                "stock_units": {"item": 1},
                "time_unit": "second",
                "consumption_time": 2,
                "input_rate_after": 20,
                "rate_change_time": 5,
            },
            {
                "kind": "first_order",
                "source": "delayed_items",
                "target": "workshop",
                "flow": "consumption",
                "time_constant": 2,
                "initial_source": 0,
                "initial_target": 0,
                "source_units": {"item": 1},
                "target_units": {"item": 1},
                "time_unit": "second",
            },
        ],
        "time": None,
        "assumptions": [],
    }
    components = normalize_component_payload(response)["components"]
    assert len(components) == 1
    assert components[0]["stock"] == "workshop"
    assert components[0]["outflow"] == "consumption"
    model = document(components, final_time=30)
    from pipeline.schemas import SimulationParameters

    result = simulate_model(model, SimulationParameters(integration_method="euler"))
    assert result.variables["transport"][0] == 0
    assert result.variables["workshop"][-1] > 10


def test_duplicate_delay_consumption_is_idempotent():
    response = {
        "components": [
            {
                "kind": "delay",
                "stock": "parts",
                "inflow": "transport",
                "outflow": "consumption",
                "input_rate": 0,
                "delay_time": 2,
                "initial_stock": 0,
                "initial_delayed_rate": 0,
                "stock_units": {"item": 1},
                "time_unit": "second",
                "consumption_time": 3,
                "input_rate_after": 12,
                "rate_change_time": 3,
            },
            {
                "kind": "first_order",
                "source": "parts",
                "target": "cloud:sink",
                "flow": "consumption",
                "time_constant": 3,
                "initial_source": 0,
                "initial_target": 0,
                "source_units": {"item": 1},
                "target_units": None,
                "time_unit": "second",
            },
        ],
        "time": None,
        "assumptions": [],
    }
    components = normalize_component_payload(response)["components"]
    assert len(components) == 1
    assert components[0]["kind"] == "delay"
    model = document(components, final_time=20)
    from pipeline.schemas import SimulationParameters

    result = simulate_model(model, SimulationParameters(integration_method="euler"))
    assert result.variables["parts"][-1] > 10
