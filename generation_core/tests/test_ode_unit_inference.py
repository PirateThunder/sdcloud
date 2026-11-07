import pytest

from pipeline.components import build_components
from pipeline.exceptions import ModelValidationError
from pipeline.ode_equivalence import (
    apply_explicit_odes,
    explicit_ode_expressions,
    validate_explicit_odes,
)
from pipeline.schemas import ComponentPlan, TimeSettings
from pipeline.simulation import simulate_model
from tests.test_components import adaptive, document


def test_explicit_odes_stop_at_top_level_punctuation_but_not_function_commas():
    description = (
        "Используй d(difference)/dt=-0.15*difference, единицу времени minute, "
        "и d(other)/dt=min(difference, 4), затем остановись."
    )
    sources = explicit_ode_expressions(description)
    assert set(sources) == {"difference", "other"}
    assert sources["difference"][0] == "-0.15*difference"
    assert sources["other"][0] == "min(difference, 4)"


def test_explicit_decay_does_not_leave_a_decorative_parameter():
    description = "Используй d(difference)/dt=-0.15*difference, единицу времени minute."
    raw = {
        "components": [
            {
                "kind": "polynomial_ode",
                "stock": "difference",
                "initial": 50,
                "units": {"heat_unit": 1},
                "time_unit": "minute",
                "terms": [{"coefficient": 0.15, "expression": "difference", "sign": -1}],
                "parameters": [
                    {"id": "decay_coefficient", "value": 0.15, "role": "rate", "units": None}
                ],
            }
        ]
    }
    plan = apply_explicit_odes(ComponentPlan.model_validate(raw), description)
    assert plan.components[0].parameters == []
    build_components(plan.components, TimeSettings(unit="minute"))


def test_explicit_logistic_threshold_receives_stock_units_and_correct_behavior():
    model = document(
        [
            {
                "kind": "polynomial_ode",
                "stock": "algae",
                "initial": 50,
                "units": {"tonne": 1},
                "time_unit": "year",
                "terms": [
                    {
                        "coefficient": 0.4,
                        "expression": "algae*(1-algae/500)",
                        "sign": 1,
                    },
                    {"coefficient": 10, "expression": "1", "sign": -1},
                ],
                "parameters": [],
            }
        ],
        final_time=200,
        unit="year",
    )
    assert any(
        variable.kind == "constant"
        and variable.expression.value == 500
        and variable.units == {"tonne": 1}
        for variable in model.variables
    )
    result = simulate_model(model, adaptive())
    assert result.variables["algae"][-1] == pytest.approx(473.60679775, abs=1e-5)


def test_coupled_ode_literals_inherit_units_from_equation_constraints():
    components = [
        {
            "kind": "polynomial_ode",
            "stock": "alpha",
            "initial": 30,
            "units": {"entity": 1},
            "time_unit": "year",
            "terms": [{"coefficient": 1, "expression": "alpha*(0.4-0.005*alpha-0.002*beta)"}],
            "parameters": [],
        },
        {
            "kind": "polynomial_ode",
            "stock": "beta",
            "initial": 20,
            "units": {"entity": 1},
            "time_unit": "year",
            "terms": [{"coefficient": 1, "expression": "beta*(0.3-0.001*alpha-0.003*beta)"}],
            "parameters": [],
        },
    ]
    variables, _, _ = build_components(components, TimeSettings(unit="year"))
    constants = {
        variable.expression.value: variable.units
        for variable in variables
        if variable.kind == "constant"
    }
    assert constants[0.4] == {"year": -1}
    assert constants[0.005] == {"year": -1, "entity": -1}
    assert constants[0.002] == {"year": -1, "entity": -1}
    assert constants[0.001] == {"year": -1, "entity": -1}
    assert constants[0.003] == {"year": -1, "entity": -1}
    validate_explicit_odes(
        "Use d(alpha)/dt=alpha*(0.4-0.005*alpha-0.002*beta) and "
        "d(beta)/dt=beta*(0.3-0.001*alpha-0.003*beta).",
        variables,
    )


def test_signed_scheduled_net_inflow_is_not_clamped():
    model = document(
        [
            {
                "kind": "scheduled_flow",
                "source": "cloud:net_power",
                "target": "charge",
                "flow": "net_power",
                "rate": -2,
                "rate_after": 2,
                "change_time": 4,
                "initial_source": 0,
                "initial_target": 100,
                "source_units": None,
                "target_units": {"wh": 1},
                "time_unit": "hour",
            }
        ],
        final_time=10,
        unit="hour",
    )
    result = simulate_model(model, adaptive())
    assert result.variables["charge"][-1] == pytest.approx(104, abs=1e-5)


def test_negative_scheduled_outflow_is_rejected_instead_of_reversing_topology():
    with pytest.raises(ModelValidationError, match="negative scheduled rate"):
        document(
            [
                {
                    "kind": "scheduled_flow",
                    "source": "charge",
                    "target": "cloud:sink",
                    "flow": "net_power",
                    "rate": -2,
                    "rate_after": 2,
                    "change_time": 4,
                    "initial_source": 100,
                    "source_units": {"wh": 1},
                    "time_unit": "hour",
                }
            ],
            unit="hour",
        )


def test_nonlinear_state_power_falls_back_to_consistent_literal_units():
    components = [
        {
            "kind": "polynomial_ode",
            "stock": "u",
            "initial": 2,
            "units": {"state": 1},
            "time_unit": "time",
            "terms": [{"coefficient": 1, "expression": "v"}],
            "parameters": [],
        },
        {
            "kind": "polynomial_ode",
            "stock": "v",
            "initial": 0,
            "units": {"state": 1},
            "time_unit": "time",
            "terms": [
                {"coefficient": 0.3, "expression": "(1-u^2)*v", "sign": 1},
                {"coefficient": 1, "expression": "u", "sign": -1},
            ],
            "parameters": [],
        },
    ]
    variables, _, _ = build_components(components, TimeSettings(unit="time"))
    assert any(
        variable.kind == "constant"
        and variable.expression.value == 1
        and variable.units == {"state": 2}
        for variable in variables
    )
    description = "u=2 and v=0. Use du/dt=v and dv/dt=0.3*(1-u^2)*v-u."
    validate_explicit_odes(description, variables)
    result = simulate_model(document(components, final_time=100, unit="time"), adaptive())
    series = result.variables["u"]
    assert all(abs(value) < 100 for value in series)
    assert sum(left * right < 0 for left, right in zip(series, series[1:], strict=False)) >= 2


def test_identical_shared_ode_parameters_are_merged_but_conflicts_are_rejected():
    def cascade():
        return [
            {
                "kind": "polynomial_ode",
                "stock": "reagent_a",
                "initial": 90,
                "units": {"mole": 1},
                "time_unit": "hour",
                "terms": [{"coefficient": "transfer", "expression": "reagent_a", "sign": -1}],
                "parameters": [
                    {"id": "transfer", "value": 0.2, "role": "rate", "units": {"hour": -1}}
                ],
            },
            {
                "kind": "polynomial_ode",
                "stock": "reagent_b",
                "initial": 0,
                "units": {"mole": 1},
                "time_unit": "hour",
                "terms": [
                    {"coefficient": "transfer", "expression": "reagent_a", "sign": 1},
                    {"coefficient": "loss", "expression": "reagent_b", "sign": -1},
                ],
                "parameters": [
                    {"id": "transfer", "value": 0.2, "role": "rate", "units": {"hour": -1}},
                    {"id": "loss", "value": 0.05, "role": "rate", "units": {"hour": -1}},
                ],
            },
        ]

    variables, _, _ = build_components(cascade(), TimeSettings(unit="hour"))
    assert sum(variable.id == "transfer" for variable in variables) == 1
    result = simulate_model(document(cascade(), final_time=50, unit="hour"), adaptive())
    assert max(result.variables["reagent_b"]) > 1
    conflicting = cascade()
    conflicting[1]["parameters"][0]["value"] = 0.3
    with pytest.raises(ModelValidationError, match="declared more than once"):
        build_components(conflicting, TimeSettings(unit="hour"))


def test_only_literal_redundant_ode_parameters_are_removed():
    def ode(*, include_missing=False):
        parameters = [
            {"id": "growth_rate_a", "value": 0.7, "role": "rate", "units": None},
            {"id": "competition_coeff_a", "value": 0.05, "role": "scale", "units": None},
        ]
        if include_missing:
            parameters.append({"id": "missing_rate", "value": 0.123, "role": "rate", "units": None})
        return [
            {
                "kind": "polynomial_ode",
                "stock": "population_a",
                "initial": 50,
                "units": {"person": 1},
                "time_unit": "year",
                "terms": [
                    {"coefficient": 0.7, "expression": "population_a", "sign": 1},
                    {"coefficient": 0.05, "expression": "population_a^2", "sign": -1},
                ],
                "parameters": parameters,
            }
        ]

    variables, _, _ = build_components(ode(), TimeSettings(unit="year"))
    ids = {item.id for item in variables}
    assert "growth_rate_a" not in ids
    assert "competition_coeff_a" not in ids
    assert any(item.expression.value == 0.7 for item in variables if item.kind == "constant")
    assert any(item.expression.value == 0.05 for item in variables if item.kind == "constant")
    with pytest.raises(ModelValidationError, match="unused ODE parameters.*missing_rate"):
        build_components(ode(include_missing=True), TimeSettings(unit="year"))
