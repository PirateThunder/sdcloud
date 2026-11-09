import math

import pytest

from pipeline.pattern_library import get_pattern, select_pattern
from pipeline.schemas import SimulationParameters
from pipeline.simulation import simulate_model

PROMPTS = {
    "sirs_epidemic": "SIRS epidemic with seasonal waves and waning immunity",
    "supply_chain_bullwhip": "Supply chain with bullwhip effect after a customer demand step",
    "student_club": "Создай систему студентов МСГ, которые создают English speaking club",
    "lorenz_system": "Lorenz chaotic attractor",
    "van_der_pol_oscillator": "Van der Pol relaxation oscillator",
    "duffing_oscillator": "Duffing two-well oscillator",
}


@pytest.mark.parametrize(("expected", "prompt"), PROMPTS.items())
def test_archetype_selection_and_validation(expected, prompt):
    pattern = select_pattern(prompt)
    assert pattern is not None and pattern.id == expected
    assert not [issue for issue in pattern.document.validation.issues if issue.severity == "error"]


def test_selector_does_not_match_substrings_or_replace_explicit_topology():
    assert select_pattern("Скорость движения задана явно, без дополнительных процессов.") is None
    assert select_pattern("Model one stock with a prescribed outflow.") is None
    description = (
        "Two colonies begin with alpha=30 population and beta=20 population. "
        "Use d(alpha)/dt = alpha*(0.4-0.005*alpha-0.002*beta) and "
        "d(beta)/dt = beta*(0.3-0.001*alpha-0.003*beta)."
    )
    assert select_pattern(description) is None
    predator = (
        "Predator and prey populations start at x=10 and y=2. "
        "Use dx/dt = x-0.1*x*y and dy/dt = 0.01*x*y-0.2*y."
    )
    assert select_pattern(predator).id == "predator_prey"


def test_selector_avoids_nested_tag_double_count_and_handles_russian_inflection():
    renewable = select_pattern(
        "A renewable forest regenerates toward carrying capacity with a fractional harvest"
    )
    assert renewable is not None and renewable.id == "renewable_resource"
    oscillator = select_pattern("Построй осциллятор Ван дер Поля с устойчивым предельным циклом")
    assert oscillator is not None and oscillator.id == "van_der_pol_oscillator"


def test_predator_equilibrium_is_valid_but_does_not_satisfy_dynamic_behavior():
    from pipeline.ir import lit
    from pipeline.semantics import semantic_issues

    document = get_pattern("predator_prey").document.model_copy(
        update={"pattern_id": "predator_prey"}
    )
    variables = []
    for variable in document.variables:
        if variable.id == "prey":
            variable = variable.model_copy(update={"initial": lit(50)})
        elif variable.id == "predators":
            variable = variable.model_copy(update={"initial": lit(5)})
        variables.append(variable)
    document = document.model_copy(update={"variables": variables})
    assert not semantic_issues(document)
    result = simulate_model(document, SimulationParameters())
    assert_finite(result)
    for stock_id in ("prey", "predators"):
        series = result.variables[stock_id]
        assert max(series) - min(series) < 1e-9


def adaptive_parameters() -> SimulationParameters:
    return SimulationParameters(
        engine="scipy", integration_method="dop853", rtol=1e-9, atol=1e-12
    )


def assert_finite(result):
    assert all(math.isfinite(value) for series in result.variables.values() for value in series)


def test_sirs_produces_repeated_epidemic_waves():
    result = simulate_model(get_pattern("sirs_epidemic").document, adaptive_parameters())
    assert_finite(result)
    series = result.variables["infectious"]
    peaks = [
        value
        for index in range(1, len(series) - 1)
        if (value := series[index]) > series[index - 1]
        and value >= series[index + 1]
        and value > 1
    ]
    assert len(peaks) >= 3


def test_supply_chain_amplifies_demand_step():
    result = simulate_model(get_pattern("supply_chain_bullwhip").document, SimulationParameters())
    assert_finite(result)
    assert max(result.variables["order_rate"]) > 160
    assert result.variables["order_rate"][-1] == pytest.approx(160)


def test_supply_delay_is_stateful_and_dynamic():
    document = get_pattern("supply_delay").document
    assert "delay" in document.capabilities
    result = simulate_model(document, SimulationParameters())
    assert_finite(result)
    assert max(result.variables["inventory"]) > min(result.variables["inventory"])


def test_club_campaign_produces_a_second_growth_wave():
    result = simulate_model(get_pattern("student_club").document, adaptive_parameters())
    assert_finite(result)
    index = result.time.index(60.0)
    assert max(result.variables["active_members"][index:]) > result.variables["active_members"][index]


@pytest.mark.parametrize(
    ("pattern_id", "variable", "minimum", "maximum"),
    [
        ("lorenz_system", "x", -10, 10),
        ("van_der_pol_oscillator", "position", -1.8, 1.8),
        ("duffing_oscillator", "position", -1, 1),
    ],
)
def test_nonlinear_oscillators_have_expected_ranges(pattern_id, variable, minimum, maximum):
    result = simulate_model(get_pattern(pattern_id).document, adaptive_parameters())
    assert_finite(result)
    series = result.variables[variable]
    assert min(series) < minimum
    assert max(series) > maximum


def test_all_benchmark_descriptions_select_expected_archetype():
    from pathlib import Path

    from pipeline.benchmark import load_prompts

    mismatches = []
    root = Path(__file__).parents[1] / "pipeline"
    for filename in (
        "benchmark_prompts.json",
        "benchmark_holdout_prompts.json",
        "benchmark_confirmation_prompts.json",
    ):
        for prompt in load_prompts(root / filename):
            selected = select_pattern(prompt["description"])
            actual = selected.id if selected else None
            if actual != prompt["expected_pattern"]:
                mismatches.append((filename, prompt["id"], prompt["expected_pattern"], actual))
    assert not mismatches


def test_pattern_prompt_matches_structure_input_contract():
    import json

    from pipeline.pattern_library import pattern_prompt

    payload = json.loads(pattern_prompt(get_pattern("bass_diffusion")))
    variables = {item["id"]: item for item in payload["variables"]}
    assert variables["potential_adopters"]["initial"] == "total_market"
    assert variables["adoption"]["source"]["id"] == "potential_adopters"
    assert variables["adoption"]["target"]["id"] == "adopters"
    assert variables["total_market"]["initial"] == 10000
    assert variables["imitation"]["units"] == {"year": -1}
    for item in variables.values():
        assert "expression" not in item
        if item["kind"] in {"stock", "constant"}:
            assert not isinstance(item["initial"], dict)
    equations = {item["id"]: item["expression"] for item in payload["equations"]}
    assert "adoption" in equations
    assert isinstance(equations["adoption"], str)
    assert "potential_adopters" in equations["adoption"]
    assert '"op"' not in equations["adoption"]


def test_independent_corpus_is_outside_pattern_library_and_has_oracles():
    from pathlib import Path

    from pipeline.benchmark import load_prompts

    path = Path(__file__).parents[1] / "pipeline" / "benchmark_independent_prompts.json"
    prompts = load_prompts(path)
    assert len(prompts) >= 12
    supported = {
        "analytic_exponential",
        "cascade",
        "conservation",
        "delayed_response",
        "event_change",
        "monotonic",
        "range",
        "sign_changes",
        "steady_state",
    }
    for prompt in prompts:
        assert prompt["expected_pattern"] is None
        assert select_pattern(prompt["description"]) is None, prompt["id"]
        assert prompt["expected_behavior"]["kind"] in supported


def test_independent_confirmation_corpus_stays_outside_pattern_library():
    from pathlib import Path

    from pipeline.benchmark import load_prompts

    path = Path(__file__).parents[1] / "pipeline" / "benchmark_independent_confirmation_prompts.json"
    prompts = load_prompts(path)
    assert len(prompts) == 10
    for prompt in prompts:
        assert prompt["expected_pattern"] is None
        assert select_pattern(prompt["description"]) is None, prompt["id"]
        assert prompt["expected_behavior"]["kind"]
