import pytest

from pipeline.components import build_components
from pipeline.exceptions import ModelValidationError
from pipeline.generation import generate_model
from pipeline.ode_equivalence import (
    apply_explicit_odes,
    explicit_ode_expressions,
    validate_explicit_odes,
)
from pipeline.schemas import ComponentPlan, GenerationRequest, TimeSettings

DESCRIPTION = (
    "A nonlinear controller starts with a=1 and b=0. Use da/dt = a - a^3/3 - b + 0.4 "
    "and db/dt = 0.12*(a + 0.5 - 0.6*b). Both states have units `state`, "
    "model time has unit `time`, and the horizon is 100 time units."
)


def recovery_components(*, factored=False, wrong_damping=False, wrong_cubic=False):
    return [
        {
            "kind": "polynomial_ode",
            "stock": "a",
            "initial": 1,
            "units": {"state": 1},
            "time_unit": "time",
            "terms": [
                {"coefficient": 1, "expression": "a", "sign": 1},
                {"coefficient": 3 if wrong_cubic else 1 / 3, "expression": "a^3", "sign": -1},
                {"coefficient": 1, "expression": "b", "sign": -1},
                {"coefficient": 0.4, "expression": "1", "sign": 1},
            ],
            "parameters": [],
        },
        {
            "kind": "polynomial_ode",
            "stock": "b",
            "initial": 0,
            "units": {"state": 1},
            "time_unit": "time",
            "terms": [
                {
                    "coefficient": "recovery_rate",
                    "expression": "a + offset - damping * b",
                    "sign": 1,
                }
            ]
            if factored
            else [
                {"coefficient": 0.12, "expression": "a", "sign": 1},
                {"coefficient": 0.06, "expression": "1", "sign": 1},
                {"coefficient": 0.6 if wrong_damping else 0.072, "expression": "b", "sign": -1},
            ],
            "parameters": [
                {"id": "recovery_rate", "value": 0.12, "role": "rate", "units": None},
                {"id": "offset", "value": 0.5, "role": "threshold", "units": None},
                {"id": "damping", "value": 0.6, "role": "scale", "units": None},
            ]
            if factored
            else [],
        },
    ]


def variables(components):
    result, _, _ = build_components(
        components,
        TimeSettings(unit="time", final_time=100, time_step=0.05, saveper=0.05),
    )
    return result


def test_extracts_explicit_equations_without_trailing_prose():
    sources = explicit_ode_expressions(DESCRIPTION)
    assert set(sources) == {"a", "b"}
    assert sources["a"][0] == "a - a^3/3 - b + 0.4"
    assert sources["b"][0] == "0.12*(a + 0.5 - 0.6*b)"


def test_extracts_all_equations_when_last_one_ends_with_a_period():
    sources = explicit_ode_expressions(
        "Use d(alpha)/dt = alpha-beta and d(beta)/dt = 0.5*alpha-beta."
    )
    assert set(sources) == {"alpha", "beta"}
    assert sources["beta"][0] == "0.5*alpha-beta"


def test_factored_and_correctly_expanded_equations_are_equivalent():
    validate_explicit_odes(DESCRIPTION, variables(recovery_components(factored=True)))
    validate_explicit_odes(DESCRIPTION, variables(recovery_components()))


def test_explicit_rhs_preserves_used_named_parameters_and_removes_decorative_ones():
    plan = ComponentPlan.model_validate(
        {
            "components": [
                {
                    "kind": "polynomial_ode",
                    "stock": "biomass",
                    "initial": 30,
                    "units": {"tonne": 1},
                    "time_unit": "time",
                    "terms": [{"coefficient": 999, "expression": "biomass", "sign": 1}],
                    "parameters": [
                        {"id": "growth", "value": 0.25, "role": "rate", "units": None},
                        {"id": "capacity", "value": 300, "role": "threshold", "units": None},
                        {"id": "loss", "value": 0.05, "role": "rate", "units": None},
                        {"id": "decorative", "value": 999, "role": "rate", "units": None},
                    ],
                }
            ],
            "assumptions": [],
        }
    )
    description = (
        "Use d(biomass)/dt = growth * biomass * (1 - biomass / capacity) - loss * biomass. "
        "Start with biomass=30 tonne."
    )
    transformed = apply_explicit_odes(plan, description)
    component = transformed.components[0]
    assert [term.coefficient for term in component.terms] == ["growth", "loss"]
    assert {parameter.id for parameter in component.parameters} == {"growth", "capacity", "loss"}
    validate_explicit_odes(description, variables([component]))


def test_explicit_rhs_restores_missing_stock_and_prevents_parameter_shadowing():
    description = "h=2 and k=0. Use dh/dt = k and dk/dt = 0.5*(-4*h - 0.2*k + 0.6). Use state units."
    h = {
        "kind": "polynomial_ode",
        "stock": "h",
        "initial": 2,
        "units": {"state": 1},
        "time_unit": "time",
        "terms": [{"coefficient": "k", "expression": "1", "sign": 1}],
        "parameters": [{"id": "k", "value": 0, "role": "rate", "units": None}],
    }
    k = {
        "kind": "polynomial_ode",
        "stock": "k",
        "initial": 0,
        "units": {"state": 1},
        "time_unit": "time",
        "terms": [{"coefficient": 0.5, "expression": "-4*h - 0.2*k + 0.6", "sign": 1}],
        "parameters": [],
    }
    transformed = apply_explicit_odes(ComponentPlan.model_validate({"components": [h]}), description)
    assert len(transformed.components) == 2
    assert transformed.components[1].stock == "k"
    assert transformed.components[1].initial == 0
    assert transformed.components[0].terms[0].coefficient == 1
    assert transformed.components[0].parameters == []
    validate_explicit_odes(description, variables(transformed.components))
    complete = apply_explicit_odes(
        ComponentPlan.model_validate({"components": [h, k]}), description
    )
    assert complete.components[0].parameters == []
    with pytest.raises(ModelValidationError, match=r"missing explicit ODE stocks.*'k'"):
        apply_explicit_odes(
            ComponentPlan.model_validate({"components": [h]}),
            description.replace("k=0. ", ""),
        )


def test_dropped_outer_multiplier_is_rejected():
    with pytest.raises(ModelValidationError, match=r"components\.b.*outer multipliers"):
        validate_explicit_odes(DESCRIPTION, variables(recovery_components(wrong_damping=True)))


def test_incorrect_cubic_coefficient_is_rejected():
    with pytest.raises(ModelValidationError, match=r"components\.a.*divisions"):
        validate_explicit_odes(DESCRIPTION, variables(recovery_components(wrong_cubic=True)))


def test_unknown_or_unsupported_equations_are_not_rejected():
    variables_ = variables(recovery_components(factored=True))
    validate_explicit_odes("Use dx/dt = unknown_function(x). Use a 10 second horizon.", variables_)
    validate_explicit_odes("Use da/dt = a + external_input.", variables_)


class ExplicitEquationLLM:
    def __init__(self):
        self.calls = []
        self.response = {
            "components": recovery_components(wrong_damping=True, wrong_cubic=True),
            "time": {
                "unit": "time",
                "initial_time": 0,
                "final_time": 100,
                "time_step": 0.05,
                "saveper": 0.05,
            },
            "assumptions": [],
        }

    async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
        self.calls.append(stage)
        if stage == "brief":
            return {
                "goal": "Preserve the explicit two-state controller equations",
                "time_horizon": "100 time units",
                "time_unit": "time",
                "stocks": ["a", "b"],
            }
        if stage == "components":
            return self.response
        raise AssertionError(stage)


async def test_explicit_rhs_overrides_llm_term_decomposition_without_repair():
    llm = ExplicitEquationLLM()
    document = await generate_model(
        GenerationRequest(description=DESCRIPTION),
        llm,
        max_repairs=0,
    )
    assert llm.calls == ["brief", "components"]
    assert document.repair_attempts == 0
    assert document.validation.status == "passed"
    components = {item.stock: item for item in document.brief.components}
    assert components["a"].terms[1].coefficient == pytest.approx(1 / 3)
    assert len(components["b"].terms) == 1
    assert components["b"].terms[0].coefficient == pytest.approx(0.12)
    assert "0.6" in components["b"].terms[0].expression


async def test_stock_shadowing_is_removed_before_component_schema_validation():
    llm = ExplicitEquationLLM()
    llm.response = {
        "components": [
            {
                "kind": "polynomial_ode",
                "stock": "h",
                "initial": 2,
                "units": {"state": 1},
                "time_unit": "time",
                "terms": [{"coefficient": "k", "expression": "k", "sign": 1}],
                "parameters": [{"id": "k", "value": 0, "role": "state", "units": None}],
            },
            {
                "kind": "polynomial_ode",
                "stock": "k",
                "initial": 0,
                "units": {"state": 1},
                "time_unit": "time",
                "terms": [{"coefficient": 0.5, "expression": "-4*h - 0.2*k + 0.6", "sign": 1}],
                "parameters": [],
            },
        ],
        "time": {"unit": "time", "initial_time": 0, "final_time": 80, "time_step": 0.05, "saveper": 0.05},
        "assumptions": [],
    }
    document = await generate_model(
        GenerationRequest(
            description=(
                "h=2 and k=0. Use dh/dt = k and dk/dt = 0.5*(-4*h - 0.2*k + 0.6). "
                "Both states have units state, model time has unit time, and the horizon is 80."
            )
        ),
        llm,
        max_repairs=0,
    )
    assert llm.calls == ["brief", "components"]
    assert document.validation.status == "passed"
    assert document.repair_attempts == 0
    h = next(component for component in document.brief.components if component.stock == "h")
    assert h.terms[0].coefficient == 1
    assert h.parameters == []


def test_explicit_shared_state_units_override_llm_physical_guesses():
    description = (
        "displacement=1.5 and velocity=0. Use d(displacement)/dt = velocity and "
        "d(velocity)/dt = 0.4*(-9*displacement - 0.3*velocity). "
        "Both states use unit state and time has unit time."
    )
    components = [
        {
            "kind": "polynomial_ode",
            "stock": "displacement",
            "initial": 1.5,
            "units": {"length": 1},
            "time_unit": "time",
            "terms": [{"coefficient": "velocity", "expression": "velocity", "sign": 1}],
            "parameters": [{"id": "velocity", "value": 0, "role": "rate", "units": None}],
        },
        {
            "kind": "polynomial_ode",
            "stock": "velocity",
            "initial": 0,
            "units": {"length/time": 1},
            "time_unit": "time",
            "terms": [{"coefficient": 0.4, "expression": "-9*displacement - 0.3*velocity"}],
            "parameters": [],
        },
    ]
    transformed = apply_explicit_odes(
        ComponentPlan.model_validate({"components": components}), description
    )
    assert all(component.units == {"state": 1} for component in transformed.components)
    validate_explicit_odes(description, variables(transformed.components))
