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
    from pipeline.benchmark import load_prompts

    mismatches = []
    for prompt in load_prompts():
        selected = select_pattern(prompt["description"])
        actual = selected.id if selected else None
        if actual != prompt["expected_pattern"]:
            mismatches.append((prompt["id"], prompt["expected_pattern"], actual))
    assert not mismatches
